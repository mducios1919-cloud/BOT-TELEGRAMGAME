#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zefoy HTTP API + Admin UI — Flask app for Render.com free tier.

- Loads bundled zefoy modules from main.py (in-memory import hook).
- Exposes a small REST API protected by ADMIN_TOKEN (or open if none set).
- Serves a single-page admin UI at "/" to: create session, view captcha,
  auto-solve (NewOCR + fallbacks), pick service, submit link, send ticks.
- Sessions kept in an in-memory dict with a hard cap + LRU eviction so the
  Render free instance (512MB) never blows up.

Env:
  ADMIN_TOKEN     — required header X-API-Key for /api/* (optional, recommended)
  MAX_SESSIONS    — default 20
  PORT            — provided by Render
"""
from __future__ import annotations

# Register bundled zefoy package first
import main  # noqa: F401

import base64
import os
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request, Response

from zefoy.submit import ZefoyClient, is_captcha_page
from zefoy.fingerprint import apply_session_guard_cookies, build_captcha_encoded
from zefoy.captcha import ZefoyCaptcha, DEFAULT_USER_AGENT
from zefoy.newocr import NewOcrWeb
from zefoy.services import parse_services
import re
import random
from string import ascii_letters, digits

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "").strip()
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", "20"))
SESSION_TTL = int(os.environ.get("SESSION_TTL", "1800"))  # 30 min

app = Flask(__name__)
_lock = threading.Lock()
_sessions: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()


# ---------- session store ----------

def _new_session_obj() -> Dict[str, Any]:
    client = ZefoyClient()
    return {
        "client": client,
        "created": time.time(),
        "last": time.time(),
        "captcha_bytes": None,
        "captcha_encoded": None,
        "services": {},           # title -> raw status
        "services_ids": {},       # title -> action url
        "services_status": {},    # title -> bool available
        "video_key": None,
        "logged_in": False,
    }


def _evict_if_needed():
    now = time.time()
    dead = [k for k, v in _sessions.items() if now - v["last"] > SESSION_TTL]
    for k in dead:
        _sessions.pop(k, None)
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)


def _get(sid: str) -> Optional[Dict[str, Any]]:
    with _lock:
        s = _sessions.get(sid)
        if s:
            s["last"] = time.time()
            _sessions.move_to_end(sid)
        return s


# ---------- auth ----------

def _auth_ok() -> bool:
    if not ADMIN_TOKEN:
        return True
    tok = request.headers.get("X-API-Key") or request.args.get("api_key") or ""
    return tok == ADMIN_TOKEN


@app.before_request
def _guard():
    if request.path.startswith("/api/") and not _auth_ok():
        return jsonify({"error": "unauthorized"}), 401


# ---------- helpers ----------

def _refresh_services(s: Dict[str, Any]) -> None:
    client: ZefoyClient = s["client"]
    r = client.session.get(client.base_url, timeout=30)
    html = r.text
    s["services"], s["services_ids"], s["services_status"] = {}, {}, {}
    try:
        for svc in parse_services(html):
            s["services"][svc.title] = svc.raw_status or svc.status
            s["services_status"][svc.title] = bool(svc.available)
            if svc.action:
                s["services_ids"][svc.title] = svc.action
            if svc.input_name:
                s["video_key"] = svc.input_name
    except Exception:
        pass
    # fallback
    for m in re.finditer(
        r'<form action="([^"]+)">[\s\S]*?name="([^"]+)"[^>]*placeholder="Enter Video',
        html, re.I):
        prev = html[max(0, m.start()-400):m.start()]
        tm = re.findall(r'<h5[^>]*>([^<]+)</h5>', prev)
        title = tm[-1].strip() if tm else m.group(1)[:12]
        s["services_ids"].setdefault(title, m.group(1))
        s["video_key"] = m.group(2)
        s["services"].setdefault(title, "unknown")
        s["services_status"].setdefault(title, True)


def _post_service(s: Dict[str, Any], service: str, url: str) -> str:
    client: ZefoyClient = s["client"]
    action = s["services_ids"].get(service)
    if not action:
        _refresh_services(s)
        action = s["services_ids"].get(service)
    if not action:
        raise RuntimeError("service action not found")
    vkey = s.get("video_key")
    if not vkey:
        raise RuntimeError("video_key not found")
    token = "".join(random.choices(ascii_letters + digits, k=16))
    boundary = f"----WebKitFormBoundary{token}"
    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="{vkey}"\r\n\r\n{url}\r\n'
        f'--{boundary}--\r\n'
    )
    full = action if str(action).startswith("http") else f'{client.base_url}{action.lstrip("/")}'
    r = client.session.post(
        full,
        headers={
            "content-type": f"multipart/form-data; boundary={boundary}",
            "user-agent": client.user_agent,
            "origin": "https://zefoy.com",
            "referer": "https://zefoy.com/",
            "accept": "*/*",
            "x-requested-with": "XMLHttpRequest",
        },
        data=body.encode("utf-8"),
        timeout=45,
    )
    return r.text or ""


# ---------- API ----------

@app.post("/api/session/new")
def api_new():
    with _lock:
        _evict_if_needed()
        sid = uuid.uuid4().hex
        _sessions[sid] = _new_session_obj()
    s = _get(sid)
    client: ZefoyClient = s["client"]
    # first hit to establish PHPSESSID
    r = client.session.get(client.base_url, timeout=30)
    if not is_captcha_page(r.text):
        s["logged_in"] = True
        _refresh_services(s)
        return jsonify({"session_id": sid, "logged_in": True,
                        "services": s["services"], "video_key": s["video_key"]})
    # need captcha
    try:
        apply_session_guard_cookies(client.session)
        cap = client.get_captcha(refresh_session=False)
        s["captcha_bytes"] = cap.image_bytes
        s["captcha_encoded"] = build_captcha_encoded(client.user_agent)
        return jsonify({
            "session_id": sid,
            "logged_in": False,
            "captcha_png_b64": base64.b64encode(cap.image_bytes).decode(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/session/<sid>/captcha")
def api_captcha(sid):
    s = _get(sid)
    if not s: return jsonify({"error": "no session"}), 404
    client: ZefoyClient = s["client"]
    apply_session_guard_cookies(client.session)
    cap = client.get_captcha(refresh_session=False)
    s["captcha_bytes"] = cap.image_bytes
    s["captcha_encoded"] = build_captcha_encoded(client.user_agent)
    return jsonify({"captcha_png_b64": base64.b64encode(cap.image_bytes).decode()})


@app.post("/api/session/<sid>/solve")
def api_solve(sid):
    """Auto solve via NewOCR + fallbacks."""
    s = _get(sid)
    if not s: return jsonify({"error": "no session"}), 404
    img = s.get("captcha_bytes")
    if not img: return jsonify({"error": "no captcha loaded"}), 400
    text = ""
    try:
        text = (NewOcrWeb().ocr(img).text or "")
    except Exception as e:
        text = ""
    if not re.sub(r'[^a-zA-Z]', '', text):
        try:
            from zefoy.ocr import solve_ddddocr
            text = solve_ddddocr(img) or ""
        except Exception:
            pass
    text = re.sub(r'[^a-zA-Z]', '', text or '').lower()
    if not text:
        return jsonify({"error": "ocr empty", "answer": ""}), 200
    # submit
    return _do_submit(s, text)


@app.post("/api/session/<sid>/submit")
def api_submit(sid):
    """Manual answer submit."""
    s = _get(sid)
    if not s: return jsonify({"error": "no session"}), 404
    answer = (request.json or {}).get("answer", "") if request.is_json else request.form.get("answer", "")
    answer = re.sub(r'[^a-zA-Z]', '', answer or '').lower()
    if not answer: return jsonify({"error": "empty answer"}), 400
    return _do_submit(s, answer)


def _do_submit(s, answer):
    client: ZefoyClient = s["client"]
    encoded = s.get("captcha_encoded") or build_captcha_encoded(client.user_agent)
    apply_session_guard_cookies(client.session)
    r = client.session.post(
        client.base_url,
        headers={
            "user-agent": client.user_agent,
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "x-requested-with": "XMLHttpRequest",
            "origin": "https://zefoy.com",
            "referer": "https://zefoy.com/",
            "accept": "*/*",
        },
        data={"captchalogin": answer, "captcha_encoded": encoded},
        timeout=30, allow_redirects=False,
    )
    body = (r.text or "").strip()
    ok = r.status_code == 200 and body.lower() == "success"
    if not ok and not is_captcha_page(body) and len(body) > 1000:
        ok = True
    if ok:
        s["logged_in"] = True
        _refresh_services(s)
        return jsonify({"success": True, "answer": answer,
                        "services": s["services"],
                        "services_status": s["services_status"],
                        "video_key": s["video_key"]})
    return jsonify({"success": False, "answer": answer, "raw": body[:400]}), 200


@app.get("/api/session/<sid>/services")
def api_services(sid):
    s = _get(sid)
    if not s: return jsonify({"error": "no session"}), 404
    _refresh_services(s)
    return jsonify({"services": s["services"],
                    "services_status": s["services_status"],
                    "video_key": s["video_key"]})


@app.post("/api/session/<sid>/send")
def api_send(sid):
    """Body: {service, url}"""
    s = _get(sid)
    if not s: return jsonify({"error": "no session"}), 404
    data = request.json or {}
    service = data.get("service")
    url = data.get("url")
    if not service or not url:
        return jsonify({"error": "service & url required"}), 400
    try:
        body = _post_service(s, service, url)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    low = body.lower()
    if "session expired" in low or is_captcha_page(body):
        s["logged_in"] = False
        return jsonify({"status": "session_expired"}), 200
    m = re.search(r'(\d+)\s*seconds?\s*(?:for your next|before trying)', body, re.I)
    wait = int(m.group(1)) if m else None
    return jsonify({"status": "ok", "wait_seconds": wait, "raw_head": body[:300]})


@app.delete("/api/session/<sid>")
def api_close(sid):
    with _lock:
        _sessions.pop(sid, None)
    return jsonify({"ok": True})


@app.get("/api/health")
def api_health():
    return jsonify({"ok": True, "sessions": len(_sessions), "ts": int(time.time())})


# ---------- Admin UI ----------

INDEX_HTML = r"""<!doctype html>
<html lang="vi"><head>
<meta charset="utf-8"><title>Zefoy Admin</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0f172a;--fg:#e2e8f0;--card:#1e293b;--accent:#38bdf8;--ok:#22c55e;--err:#ef4444}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 system-ui,Segoe UI,Roboto;background:var(--bg);color:var(--fg)}
header{padding:14px 20px;background:#0b1220;border-bottom:1px solid #1e293b;display:flex;gap:12px;align-items:center}
h1{font-size:16px;margin:0;color:var(--accent)}
main{max-width:960px;margin:0 auto;padding:16px;display:grid;gap:14px}
.card{background:var(--card);padding:14px 16px;border-radius:10px;border:1px solid #334155}
label{display:block;font-size:12px;color:#94a3b8;margin-bottom:4px}
input,select,button,textarea{font:inherit;color:var(--fg);background:#0b1220;border:1px solid #334155;border-radius:6px;padding:8px 10px;width:100%}
button{background:var(--accent);color:#0b1220;border:0;font-weight:600;cursor:pointer;width:auto;padding:8px 14px}
button.secondary{background:#334155;color:var(--fg)}
button:disabled{opacity:.5;cursor:not-allowed}
.row{display:flex;gap:10px;flex-wrap:wrap}.row>*{flex:1;min-width:120px}
img.captcha{background:#fff;padding:6px;border-radius:6px;max-width:260px;display:block}
pre{background:#0b1220;padding:10px;border-radius:6px;overflow:auto;max-height:200px;font-size:12px}
.tag{display:inline-block;padding:2px 8px;border-radius:99px;font-size:11px;background:#334155}
.tag.ok{background:var(--ok);color:#00220a}.tag.err{background:var(--err);color:#3a0000}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:6px 8px;border-bottom:1px solid #334155;text-align:left}
tr:hover{background:#0b1220}
.small{font-size:12px;color:#94a3b8}
</style></head><body>
<header><h1>ZEFOY · Admin Panel</h1>
<span class="small">API endpoint tại <code>/api/*</code></span></header>
<main>
  <div class="card">
    <label>API Key (X-API-Key) — trống nếu server không đặt ADMIN_TOKEN</label>
    <div class="row">
      <input id="apikey" placeholder="ADMIN_TOKEN"/>
      <button onclick="saveKey()">Lưu</button>
      <button class="secondary" onclick="newSession()">Tạo Session</button>
    </div>
    <p class="small">Session ID: <code id="sid">-</code> · <span id="loginState" class="tag">chưa login</span></p>
  </div>

  <div class="card" id="capCard" style="display:none">
    <label>Captcha</label>
    <img id="capImg" class="captcha"/>
    <div class="row" style="margin-top:8px">
      <button onclick="reloadCap()" class="secondary">Đổi captcha</button>
      <button onclick="autoSolve()">Giải tự động (NewOCR)</button>
    </div>
    <div class="row" style="margin-top:8px">
      <input id="manual" placeholder="Hoặc nhập tay rồi Submit"/>
      <button onclick="manualSubmit()" class="secondary">Submit</button>
    </div>
  </div>

  <div class="card" id="sendCard" style="display:none">
    <label>Video URL (TikTok)</label>
    <input id="vurl" placeholder="https://www.tiktok.com/@user/video/123..."/>
    <div class="row" style="margin-top:8px">
      <select id="svc"></select>
      <button onclick="sendTick()">Gửi 1 tick</button>
      <button onclick="loopStart()" class="secondary">Loop</button>
      <button onclick="loopStop()" class="secondary">Dừng</button>
    </div>
    <p class="small" id="loopState">Loop: OFF</p>
    <pre id="log"></pre>
  </div>

  <div class="card" id="svcCard" style="display:none">
    <label>Trạng thái dịch vụ</label>
    <table><thead><tr><th>Service</th><th>Status</th><th>Online</th></tr></thead>
      <tbody id="svcTable"></tbody></table>
  </div>
</main>
<script>
let SID=null, LOOP=null;
function key(){return document.getElementById('apikey').value.trim()}
function saveKey(){localStorage.setItem('zk',key());toast('saved')}
function toast(m){console.log(m)}
function log(m){const el=document.getElementById('log');el.textContent=(new Date().toLocaleTimeString()+' '+m+'\n'+el.textContent).slice(0,4000)}
async function api(path,opt={}){opt.headers=Object.assign({'X-API-Key':key(),'Content-Type':'application/json'},opt.headers||{});const r=await fetch(path,opt);return r.json()}
async function newSession(){
  const r=await api('/api/session/new',{method:'POST'});
  if(r.error){alert(r.error);return}
  SID=r.session_id;document.getElementById('sid').textContent=SID;
  if(r.logged_in){onLogin(r)}else{showCap(r.captcha_png_b64)}
}
function showCap(b64){document.getElementById('capCard').style.display='';
  document.getElementById('capImg').src='data:image/png;base64,'+b64}
async function reloadCap(){const r=await api(`/api/session/${SID}/captcha`);if(r.captcha_png_b64)showCap(r.captcha_png_b64)}
async function autoSolve(){log('solving...');const r=await api(`/api/session/${SID}/solve`,{method:'POST'});
  log('solve -> '+JSON.stringify(r).slice(0,200));if(r.success)onLogin(r);else reloadCap()}
async function manualSubmit(){const a=document.getElementById('manual').value;
  const r=await api(`/api/session/${SID}/submit`,{method:'POST',body:JSON.stringify({answer:a})});
  log('submit -> '+JSON.stringify(r).slice(0,200));if(r.success)onLogin(r);else reloadCap()}
function onLogin(r){
  document.getElementById('loginState').textContent='logged in';
  document.getElementById('loginState').className='tag ok';
  document.getElementById('capCard').style.display='none';
  document.getElementById('sendCard').style.display='';
  renderServices(r.services||{}, r.services_status||{});
}
function renderServices(svc,st){
  const sel=document.getElementById('svc');sel.innerHTML='';
  const tb=document.getElementById('svcTable');tb.innerHTML='';
  document.getElementById('svcCard').style.display='';
  Object.keys(svc).forEach(k=>{
    const o=document.createElement('option');o.value=k;o.textContent=k;sel.appendChild(o);
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${k}</td><td>${svc[k]||''}</td><td><span class="tag ${st[k]?'ok':'err'}">${st[k]?'ON':'OFF'}</span></td>`;
    tb.appendChild(tr);
  });
}
async function sendTick(){
  const service=document.getElementById('svc').value;
  const url=document.getElementById('vurl').value.trim();
  if(!url){alert('nhập link');return}
  const r=await api(`/api/session/${SID}/send`,{method:'POST',body:JSON.stringify({service,url})});
  log('send -> '+JSON.stringify(r).slice(0,300));
  if(r.status==='session_expired'){document.getElementById('loginState').textContent='expired';document.getElementById('loginState').className='tag err';reloadCap();document.getElementById('capCard').style.display=''}
  return r;
}
function loopStart(){
  if(LOOP)return;
  document.getElementById('loopState').textContent='Loop: ON';
  const tick=async()=>{const r=await sendTick();let w=(r&&r.wait_seconds)||18;LOOP=setTimeout(tick,w*1000)};
  tick();
}
function loopStop(){if(LOOP){clearTimeout(LOOP);LOOP=null}document.getElementById('loopState').textContent='Loop: OFF'}
(function(){const k=localStorage.getItem('zk');if(k)document.getElementById('apikey').value=k})();
</script></body></html>
"""


@app.get("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html; charset=utf-8")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
