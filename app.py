"""
Zefoy Web API — Render-ready FastAPI wrapper.

Không cần admin token. Client (PHP) chỉ cần:
  POST /api/start                → { session_id, captcha_b64 }
  POST /api/solve                → { session_id, answer } → { ok, services }
  POST /api/services             → { session_id } → { services }
  POST /api/run                  → { session_id, service, url } → { ok, amount, kind, message, timer, total }
  POST /api/refresh_captcha      → { session_id } → { captcha_b64 }  (khi user muốn ảnh mới)

Session state được giữ trong RAM theo session_id (UUID). Đủ dùng cho 1 instance Render free.
"""
from __future__ import annotations

import base64
import io
import os
import re
import random
import time
import uuid
from string import ascii_letters, digits
from typing import Any, Optional
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from zefoy.captcha import DEFAULT_USER_AGENT, ZefoyCaptcha
from zefoy.fingerprint import apply_session_guard_cookies, build_captcha_encoded
from zefoy.submit import ZefoyClient, is_captcha_page
from zefoy.services import parse_services

app = FastAPI(title="Zefoy Web API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

import traceback
from fastapi.responses import JSONResponse
from fastapi.requests import Request as _Req

@app.exception_handler(Exception)
async def _all_ex(request: _Req, exc: Exception):
    tb = traceback.format_exc()
    print("[UNHANDLED]", tb, flush=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": type(exc).__name__,
            "message": str(exc) or "unknown error",
            "hint": "Zefoy có thể chặn IP Render (Cloudflare). Xem log Render để chi tiết.",
        },
    )


# ─────────── session store (in-memory) ────────────
SESSIONS: dict[str, dict[str, Any]] = {}
SESSION_TTL = 60 * 30  # 30 phút


def _new_session_state() -> dict[str, Any]:
    client = ZefoyClient()
    return {
        "client": client,
        "created": time.time(),
        "last_used": time.time(),
        "services": {},        # title -> raw status
        "services_ids": {},    # title -> action path
        "services_status": {}, # title -> bool available
        "video_key": None,
        "total_sent": 0,
        "captcha_b64": None,
    }


def _get(session_id: str) -> dict[str, Any]:
    _gc()
    st = SESSIONS.get(session_id)
    if not st:
        raise HTTPException(404, "session not found — bấm 'Bắt đầu' để tạo session mới")
    st["last_used"] = time.time()
    return st


def _gc():
    now = time.time()
    dead = [k for k, v in SESSIONS.items() if now - v["last_used"] > SESSION_TTL]
    for k in dead:
        SESSIONS.pop(k, None)


# ─────────── Zefoy helpers (chuyển từ run.py) ────────────
def _decode_response(body: str) -> str:
    """Zefoy trả về base64-reversed. Giải mã ra text sạch."""
    if not body:
        return ""
    text = body.strip()
    if text.lower() == "success":
        return "success"
    rev = text[::-1]
    for candidate in (unquote(rev), rev, unquote(text), text):
        try:
            decoded = base64.b64decode(candidate + "=" * (-len(candidate) % 4)).decode("utf-8", errors="replace")
            if decoded and any(c.isprintable() for c in decoded):
                return decoded
        except Exception:
            continue
    return text


def _parse_sent_amount(html: str) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """Trích số lượng đã gửi từ HTML phản hồi."""
    if not html:
        return None, None, None
    patterns = [
        (r"Sent\s+(\d+)\s+([A-Za-z]+)", 1, 2),
        (r"(\d+)\s+(views?|hearts?|followers?|shares?|comments?|favorites?)\s+(?:sent|added)", 1, 2),
        (r"Successfully\s+sent\s+(\d+)\s+([A-Za-z]+)", 1, 2),
        (r"\+\s*(\d+)\s+([A-Za-z]+)", 1, 2),
    ]
    for pat, ai, ki in patterns:
        m = re.search(pat, html, re.I)
        if m:
            try:
                return int(m.group(ai)), m.group(ki).lower(), m.group(0).strip()
            except Exception:
                pass
    # message xanh
    m = re.search(r"color:\s*green;?'?[^>]*>\s*([^<]+)", html, re.I)
    if m and "Checking Timer" not in m.group(1):
        msg = m.group(1).strip()
        m2 = re.search(r"(\d+)", msg)
        if m2:
            return int(m2.group(1)), "unit", msg
        return None, None, msg
    return None, None, None


def _parse_timer(html: str) -> Optional[int]:
    if not html:
        return None
    for pat in [
        r"remainingTimelogin\s*=\s*(-?\d+)",
        r"var\s+ltm\s*=\s*(-?\d+)",
        r"ltm\s*=\s*(-?\d+)",
        r"Please wait\s+(\d+)\s+seconds",
    ]:
        m = re.search(pat, html, re.I)
        if m:
            v = int(m.group(1))
            if v > 0:
                return v
    m = re.search(r"(\d+)\s*minute\(s\)\s*(\d+)\s*second", html, re.I)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None


def _refresh_services(st: dict[str, Any]) -> None:
    client: ZefoyClient = st["client"]
    resp = client.session.get(client.base_url + "/", headers={"user-agent": client.user_agent}, timeout=30)
    html = resp.text or ""
    st["services"], st["services_ids"], st["services_status"] = {}, {}, {}
    try:
        for svc in parse_services(html):
            st["services"][svc.title] = svc.raw_status or svc.status
            st["services_status"][svc.title] = bool(svc.available)
            if svc.action:
                st["services_ids"][svc.title] = svc.action
            if svc.input_name:
                st["video_key"] = svc.input_name
    except Exception:
        pass
    # fallback regex
    if len(st["services_ids"]) == 0:
        for m in re.finditer(
            r'<form action="([^"]+)">[\s\S]*?name="([^"]+)"[^>]*placeholder="Enter Video',
            html, re.I,
        ):
            prev = html[max(0, m.start() - 400): m.start()]
            tm = re.findall(r"<h5[^>]*>([^<]+)</h5>", prev)
            title = tm[-1].strip() if tm else m.group(1)[:12]
            st["services_ids"][title] = m.group(1)
            st["video_key"] = m.group(2)
            st["services"].setdefault(title, "unknown")
            st["services_status"].setdefault(title, True)


def _post_service(st: dict[str, Any], service: str, url: str) -> str:
    client: ZefoyClient = st["client"]
    action = st["services_ids"].get(service)
    if not action:
        _refresh_services(st)
        action = st["services_ids"].get(service)
    if not action:
        raise HTTPException(400, f"Service không tìm thấy: {service}")
    video_key = st.get("video_key")
    if not video_key:
        raise HTTPException(400, "video_key chưa có, thử refresh services")

    token = "".join(random.choices(ascii_letters + digits, k=16))
    boundary = f"----WebKitFormBoundary{token}"
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{video_key}"\r\n\r\n{url}\r\n',
        f"--{boundary}--\r\n",
    ]
    body = "".join(parts)
    target = action if str(action).startswith("http") else f"{client.base_url}/{action.lstrip('/')}"
    resp = client.session.post(
        target,
        headers={
            "content-type": f"multipart/form-data; boundary={boundary}",
            "user-agent": client.user_agent,
            "origin": "https://zefoy.com",
            "referer": "https://zefoy.com/",
            "accept": "*/*",
        },
        data=body.encode("utf-8"),
        timeout=45,
    )
    return _decode_response(resp.text or "")


# ─────────── Pydantic models ────────────
class StartReq(BaseModel):
    pass


class SolveReq(BaseModel):
    session_id: str
    answer: str


class SidReq(BaseModel):
    session_id: str


class RunReq(BaseModel):
    session_id: str
    service: str
    url: str


# ─────────── Routes ────────────
from fastapi.responses import FileResponse
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

@app.get("/")
def root():
    idx = os.path.join(_STATIC_DIR, "index.html")
    if os.path.exists(idx):
        return FileResponse(idx)
    return {"name": "Zefoy Web API", "version": "1.0.0"}

@app.get("/api")
def api_info():
    return {"endpoints": ["/api/start","/api/solve","/api/services","/api/run","/api/refresh_captcha"], "sessions_active": len(SESSIONS)}


@app.get("/health")
def health():
    return {"ok": True, "sessions": len(SESSIONS)}


@app.post("/api/start")
def start(_: StartReq = StartReq()):
    """Tạo session mới + lấy captcha."""
    sid = uuid.uuid4().hex
    st = _new_session_state()
    client: ZefoyClient = st["client"]
    captcha = client.get_captcha(refresh_session=True)
    st["captcha_b64"] = base64.b64encode(captcha.image_bytes).decode("ascii")
    SESSIONS[sid] = st
    return {
        "session_id": sid,
        "captcha_b64": st["captcha_b64"],
        "captcha_mime": "image/png",
    }


@app.post("/api/refresh_captcha")
def refresh_captcha(req: SidReq):
    st = _get(req.session_id)
    client: ZefoyClient = st["client"]
    captcha = client.get_captcha(refresh_session=False)
    st["captcha_b64"] = base64.b64encode(captcha.image_bytes).decode("ascii")
    return {"captcha_b64": st["captcha_b64"], "captcha_mime": "image/png"}


@app.post("/api/solve")
def solve(req: SolveReq):
    st = _get(req.session_id)
    client: ZefoyClient = st["client"]
    ans = re.sub(r"[^a-zA-Z]", "", req.answer or "").lower()
    if not ans:
        raise HTTPException(400, "Captcha answer rỗng")
    result = client.submit_answer(ans)
    if not result.success:
        # captcha sai → cấp captcha mới
        try:
            captcha = client.get_captcha(refresh_session=False)
            st["captcha_b64"] = base64.b64encode(captcha.image_bytes).decode("ascii")
        except Exception:
            pass
        return {
            "ok": False,
            "message": result.message or "Captcha sai, thử lại",
            "captcha_b64": st.get("captcha_b64"),
        }
    _refresh_services(st)
    return {
        "ok": True,
        "answer": ans,
        "services": [
            {
                "name": name,
                "status": st["services"].get(name, ""),
                "available": bool(st["services_status"].get(name, False)),
                "has_action": name in st["services_ids"],
            }
            for name in st["services"]
        ],
    }


@app.post("/api/services")
def services(req: SidReq):
    st = _get(req.session_id)
    _refresh_services(st)
    return {
        "services": [
            {
                "name": name,
                "status": st["services"].get(name, ""),
                "available": bool(st["services_status"].get(name, False)),
                "has_action": name in st["services_ids"],
            }
            for name in st["services"]
        ],
        "total_sent": st.get("total_sent", 0),
    }


@app.post("/api/run")
def run(req: RunReq):
    st = _get(req.session_id)
    # Step 1: gửi link để get confirm token
    html1 = _post_service(st, req.service, req.url)
    if "Session expired" in html1 or is_captcha_page(html1):
        raise HTTPException(401, "Session hết hạn, tạo session mới")
    if "service is currently not working" in html1.lower():
        return {"ok": False, "message": "Service tạm không hoạt động", "html": html1[:500]}
    timer = _parse_timer(html1)
    if timer and timer > 0:
        return {"ok": False, "cooldown": timer, "message": f"Đang cooldown {timer}s"}

    # extract hidden field (confirm token)
    m = re.search(
        r'<input[^>]+type=["\']hidden["\'][^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']+)["\']',
        html1, re.I,
    )
    if not m:
        m = re.search(
            r'<input[^>]+name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']+)["\']',
            html1, re.I,
        )
    if not m:
        return {"ok": False, "message": "Không tìm thấy confirm token", "html": html1[:500]}
    confirm_name, confirm_value = m.group(1), m.group(2)

    # Step 2: gửi confirm để tick thật
    html2 = _post_service(st, req.service, req.url)  # fallback, some services need same POST
    # Actually the confirm step reuses the action with the token field:
    client: ZefoyClient = st["client"]
    action = st["services_ids"].get(req.service)
    token = "".join(random.choices(ascii_letters + digits, k=16))
    boundary = f"----WebKitFormBoundary{token}"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="{confirm_name}"\r\n\r\n{confirm_value}\r\n'
        f"--{boundary}--\r\n"
    )
    target = action if str(action).startswith("http") else f"{client.base_url}/{action.lstrip('/')}"
    resp = client.session.post(
        target,
        headers={
            "content-type": f"multipart/form-data; boundary={boundary}",
            "user-agent": client.user_agent,
            "origin": "https://zefoy.com",
            "referer": "https://zefoy.com/",
            "accept": "*/*",
        },
        data=body.encode("utf-8"),
        timeout=45,
    )
    html3 = _decode_response(resp.text or "")

    amount, kind, msg = _parse_sent_amount(html3)
    timer2 = _parse_timer(html3)
    if amount:
        st["total_sent"] = st.get("total_sent", 0) + amount

    return {
        "ok": bool(amount or msg),
        "amount": amount,
        "kind": kind,
        "message": msg or "Đã gửi (không parse được số lượng)",
        "cooldown": timer2,
        "total_sent": st.get("total_sent", 0),
        "service": req.service,
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
