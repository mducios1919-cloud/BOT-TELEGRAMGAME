"""TienBuff API — FastAPI backend for TikTok Zefoy buffing.

Auth model:
  - Admin: credentials from env ADMIN_USER/ADMIN_PASS (default admin/admin123)
  - User: ONE user only, registered via /api/register (first-come-first-serve)
Admin manages cookie/user-agent pool. User calls /api/services and /api/run.
"""
from __future__ import annotations
import time
import traceback
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import storage
from .auth import (
    ADMIN_PASS, ADMIN_USER, hash_password, make_token, require_admin,
    require_user, verify_password,
)
from .zefoy_core import build_session, get_services, run_boost

app = FastAPI(title="TienBuff API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.exception_handler(Exception)
async def _err(request, exc):
    if isinstance(exc, HTTPException):
        raise exc
    tb = traceback.format_exc()
    print("[UNHANDLED]", tb, flush=True)
    return JSONResponse(500, {"error": type(exc).__name__, "message": str(exc)})


# ─────────── models ────────────
class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)


class LoginIn(BaseModel):
    username: str
    password: str


class CookieIn(BaseModel):
    label: str = ""
    cookie_string: str = Field(min_length=10)
    user_agent: str = Field(min_length=10)


class RunIn(BaseModel):
    service: str
    video_url: str = Field(min_length=8)


# ─────────── public ────────────
@app.get("/")
def root():
    return {"name": "TienBuff API", "status": "ok", "version": "1.0.0"}


@app.get("/api/status")
def status():
    d = storage.read()
    return {
        "has_user": d.get("user") is not None,
        "registration_open": d.get("user") is None,
        "cookie_count": len(d.get("cookies", [])),
        "active_cookie_count": sum(1 for c in d.get("cookies", []) if c.get("active", True)),
        "stats": d.get("stats", {}),
    }


# ─────────── auth ────────────
@app.post("/api/register")
def register(inp: RegisterIn):
    d = storage.read()
    if d.get("user") is not None:
        raise HTTPException(403, "Đã có người đăng ký. Chỉ 1 user duy nhất được phép.")
    def _m(dd):
        dd["user"] = {
            "username": inp.username,
            "password_hash": hash_password(inp.password),
            "created_at": time.time(),
        }
    storage.write(_m)
    return {"ok": True, "token": make_token(inp.username, "user"), "role": "user", "username": inp.username}


@app.post("/api/login")
def login(inp: LoginIn):
    # admin?
    if inp.username == ADMIN_USER and inp.password == ADMIN_PASS:
        return {"ok": True, "token": make_token(inp.username, "admin"), "role": "admin", "username": inp.username}
    d = storage.read()
    u = d.get("user")
    if not u or u["username"] != inp.username or not verify_password(inp.password, u["password_hash"]):
        raise HTTPException(401, "Sai tài khoản hoặc mật khẩu")
    return {"ok": True, "token": make_token(inp.username, "user"), "role": "user", "username": inp.username}


@app.get("/api/me")
def me(claims: dict = Depends(require_user)):
    return {"username": claims["sub"], "role": claims.get("role", "user")}


# ─────────── admin ────────────
@app.get("/api/admin/cookies")
def list_cookies(_: dict = Depends(require_admin)):
    d = storage.read()
    # mask cookie for safety in list view
    out = []
    for c in d["cookies"]:
        cs = c["cookie_string"]
        out.append({
            "id": c["id"], "label": c["label"], "active": c.get("active", True),
            "created_at": c.get("created_at"), "last_used": c.get("last_used", 0),
            "user_agent": c["user_agent"],
            "cookie_preview": (cs[:40] + "…" + cs[-20:]) if len(cs) > 65 else cs,
        })
    return {"cookies": out}


@app.post("/api/admin/cookies")
def add_cookie(inp: CookieIn, _: dict = Depends(require_admin)):
    entry = storage.add_cookie(inp.label, inp.cookie_string, inp.user_agent)
    return {"ok": True, "id": entry["id"]}


@app.delete("/api/admin/cookies/{cid}")
def del_cookie(cid: str, _: dict = Depends(require_admin)):
    ok = storage.delete_cookie(cid)
    if not ok:
        raise HTTPException(404, "Không tìm thấy cookie")
    return {"ok": True}


@app.post("/api/admin/cookies/{cid}/toggle")
def toggle_cookie(cid: str, _: dict = Depends(require_admin)):
    ok = storage.toggle_cookie(cid)
    if not ok:
        raise HTTPException(404, "Không tìm thấy cookie")
    return {"ok": True}


@app.get("/api/admin/history")
def history(_: dict = Depends(require_admin)):
    d = storage.read()
    return {"history": d.get("history", [])[:100], "stats": d.get("stats", {})}


@app.delete("/api/admin/user")
def reset_user(_: dict = Depends(require_admin)):
    def _m(d):
        d["user"] = None
    storage.write(_m)
    return {"ok": True, "message": "Đã xoá user. Có thể đăng ký lại."}


# ─────────── buff endpoints (user) ────────────
def _pick_session():
    c = storage.pick_active_cookie()
    if not c:
        raise HTTPException(400, "Admin chưa thêm cookie nào. Vào trang admin để thêm cookie + user-agent.")
    return c, build_session(c["cookie_string"], c["user_agent"])


@app.get("/api/services")
def api_services(claims: dict = Depends(require_user)):
    c, s = _pick_session()
    services, home_html = get_services(s)
    if not services:
        raise HTTPException(502, "Không lấy được danh sách dịch vụ. Cookie có thể đã hết hạn.")
    return {
        "cookie_id": c["id"], "cookie_label": c["label"],
        "services": [{
            "name": x["name"], "active": x["active"], "status": x["status"],
        } for x in services],
    }


@app.post("/api/run")
def api_run(inp: RunIn, claims: dict = Depends(require_user)):
    c, s = _pick_session()
    services, home_html = get_services(s)
    target = next((x for x in services if x["name"] == inp.service), None)
    if not target:
        raise HTTPException(400, f"Không tìm thấy dịch vụ '{inp.service}'")
    if not target["active"]:
        raise HTTPException(400, f"Dịch vụ '{inp.service}' đang bảo trì")

    result = run_boost(s, target, home_html, inp.video_url)
    entry = {
        "at": time.time(), "by": claims["sub"], "service": inp.service,
        "url": inp.video_url[:120], "ok": result["ok"],
        "message": result["message"], "cooldown": result.get("cooldown", 0),
        "amount": result.get("amount"), "cookie_label": c["label"],
    }
    storage.push_history(entry)
    return {
        "ok": result["ok"], "message": result["message"],
        "cooldown": result.get("cooldown", 0), "amount": result.get("amount"),
        "service": inp.service, "cookie": c["label"],
    }
