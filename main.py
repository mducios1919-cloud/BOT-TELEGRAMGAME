import os
import sys
import json
import time
import base64
import hashlib
import re
import random
from datetime import datetime
from typing import Optional
from string import ascii_letters, digits
from urllib.parse import urlparse

# ==================== CÀI ĐẶT DEPENDENCIES ====================
try:
    import flask
except ImportError:
    os.system("pip install flask flask-cors requests beautifulsoup4 pycryptodome gunicorn")

# ==================== FLASK APP ====================
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

app = Flask(__name__)
CORS(app)

# ==================== CONSTANTS ====================
DEFAULT_BASE_URL = "https://zefoy.com"
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
AES_PASSPHRASE = "43fdda1192dde7f8ffff7161e13580d7"

# ==================== CRYPTO UTIL ====================
def evp_bytes_to_key(password: bytes, salt: bytes, key_len: int = 32, iv_len: int = 16):
    derived = b""
    block = b""
    while len(derived) < key_len + iv_len:
        block = hashlib.md5(block + password + salt).digest()
        derived += block
    return derived[:key_len], derived[key_len:key_len + iv_len]

def encrypt_cryptojs_json(plaintext, passphrase=AES_PASSPHRASE):
    if not isinstance(plaintext, str):
        plaintext = json.dumps(plaintext, separators=(",", ":"), ensure_ascii=False)
    salt = os.urandom(8)
    key, iv = evp_bytes_to_key(passphrase.encode("utf-8"), salt)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    ciphertext = cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
    payload = {
        "ct": base64.b64encode(ciphertext).decode("ascii"),
        "iv": iv.hex(),
        "s": salt.hex(),
    }
    return json.dumps(payload, separators=(",", ":"))

# ==================== FINGERPRINT ====================
def browser_guard_cookies():
    zf = hashlib.md5(str(int(time.time() * 1000)).encode("utf-8")).hexdigest()
    return {"zf": zf, "za": "200"}

def build_device_fingerprint(user_agent):
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Saigon")
        now = datetime.now(tz)
        offset_min = -int(now.utcoffset().total_seconds() // 60)
        locale_dt = now.strftime("%H:%M:%S %d/%m/%Y")
    except:
        now = datetime.utcnow()
        offset_min = 0
        locale_dt = now.strftime("%H:%M:%S %d/%m/%Y")
    
    return {
        "deviceInfo": {
            "cpuCores": 8,
            "deviceMemoryGB": 8,
            "platform": "Win32",
            "gpu": {"vendor": "Google Inc.", "renderer": "ANGLE"},
        },
        "browserInfo": {
            "userAgent": user_agent,
            "timezone": "Asia/Saigon",
            "timezoneOffset": offset_min,
            "localeDateTime": locale_dt,
            "language": "en",
            "languages": ["en"],
            "webdriver": False,
        },
        "screenInfo": {
            "width": 1920,
            "height": 1080,
            "colorDepth": 24,
        },
        "storageInfo": {
            "localStorage": "Yes",
            "sessionStorage": "Yes",
        }
    }

def build_captcha_encoded(user_agent):
    fp = build_device_fingerprint(user_agent)
    return encrypt_cryptojs_json(fp)

# ==================== ZEFOY CAPTCHA ====================
class ZefoyCaptchaError(Exception):
    pass

class CaptchaResult:
    def __init__(self, image_bytes, image_url, image_path, captcha_token, session_id, cookies):
        self.image_bytes = image_bytes
        self.image_url = image_url
        self.image_path = image_path
        self.captcha_token = captcha_token
        self.session_id = session_id
        self.cookies = cookies

class ZefoyCaptcha:
    def __init__(self, session=None, timeout=30):
        self.base_url = DEFAULT_BASE_URL
        self.user_agent = DEFAULT_USER_AGENT
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.verify = False
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
    
    @property
    def session_id(self):
        return self.session.cookies.get("PHPSESSID")
    
    def ensure_session(self):
        self.session.get(f"{self.base_url}/", timeout=self.timeout)
        cookies = browser_guard_cookies()
        for name, value in cookies.items():
            self.session.cookies.set(name, value, path="/")
        if not self.session_id:
            raise ZefoyCaptchaError("No session cookie")
        return self.session_id
    
    def get(self):
        self.ensure_session()
        ts = int(time.time())
        url = f"{self.base_url}/?getcapthca={ts}"
        resp = self.session.get(url, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=self.timeout)
        data = resp.json()
        
        user_agent_md5 = hashlib.md5(self.user_agent.encode()).hexdigest()
        encoded = data.get(user_agent_md5) or list(data.values())[0]
        
        once = base64.b64decode(encoded)
        twice = base64.b64decode(once)
        image_path = twice.decode("utf-8").strip()
        if not image_path.startswith("/"):
            image_path = "/" + image_path
        
        image_url = f"{self.base_url}{image_path}"
        resp = self.session.get(image_url, timeout=self.timeout)
        image_bytes = resp.content
        
        token = None
        if "_CAPTCHA=" in image_path:
            token = image_path.split("_CAPTCHA=")[1].split("&")[0]
        
        return CaptchaResult(
            image_bytes=image_bytes,
            image_url=image_url,
            image_path=image_path,
            captcha_token=token,
            session_id=self.session_id,
            cookies=self.session.cookies.get_dict()
        )

# ==================== OCR ====================
class NewOcrWeb:
    def __init__(self, timeout=60):
        self.base_url = "https://www.newocr.com"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update({
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": self.base_url + "/",
        })
    
    def ocr(self, image_bytes):
        self.session.get(self.base_url, timeout=self.timeout)
        resp = self.session.post(
            self.base_url,
            data={"preview": "1"},
            files={"userfile": ("captcha.png", image_bytes, "application/octet-stream")},
            timeout=self.timeout
        )
        html = resp.text
        m = re.search(r'name\s*=\s*["\']?u["\']?\s+value\s*=\s*["\']([a-f0-9]{32})["\']', html, re.I)
        if m:
            file_id = m.group(1)
        else:
            m = re.search(r'name\s*=\s*["\']u["\'][^>]*value\s*=\s*["\']([^"\']+)', html, re.I)
            file_id = m.group(1) if m else None
        if not file_id:
            raise Exception("File id not found")
        
        data = {
            "l3": "", "l2[]": "eng", "r": "0", "psm": "6",
            "u": file_id, "x1": "0", "y1": "0", "x2": "100", "y2": "100", "ocr": "1"
        }
        resp = self.session.post(self.base_url, data=data, timeout=self.timeout)
        m = re.search(r'<textarea[^>]*id=["\']ocr-result["\'][^>]*>([\s\S]*?)</textarea>', resp.text, re.I)
        text = m.group(1).strip() if m else ""
        return re.sub(r'[^a-zA-Z]', '', text or "").lower()

def solve_captcha(image_bytes):
    try:
        return NewOcrWeb().ocr(image_bytes)
    except Exception as e:
        print(f"OCR error: {e}")
        return ""

# ==================== ZEFOY CLIENT ====================
class ZefoyClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.captcha_client = ZefoyCaptcha(self.session)
        self.base_url = DEFAULT_BASE_URL
        self.user_agent = DEFAULT_USER_AGENT
        self.is_logged_in = False
        self.services_cache = []
    
    def get_captcha(self):
        return self.captcha_client.get()
    
    def login(self, answer):
        """Đăng nhập bằng captcha"""
        answer = re.sub(r'[^a-z]', '', answer.lower())
        if not answer:
            return {"success": False, "error": "Empty answer"}
        
        self.captcha_client.ensure_session()
        encoded = build_captcha_encoded(self.user_agent)
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": self.base_url,
            "Referer": self.base_url + "/",
        }
        data = {"captchalogin": answer, "captcha_encoded": encoded}
        resp = self.session.post(self.base_url, data=data, headers=headers, timeout=30, allow_redirects=False)
        xhr_body = resp.text.strip()
        xhr_ok = resp.status_code == 200 and xhr_body.lower() == "success"
        
        if xhr_ok:
            follow = self.session.get(self.base_url, timeout=30)
            html = follow.text
            self.is_logged_in = True
            self.services_cache = self._parse_services(html)
            return {"success": True, "html": html, "services": self.services_cache}
        
        return {"success": False, "error": f"Login failed: {xhr_body[:100]}"}
    
    def _parse_services(self, html):
        """Parse danh sách services từ HTML"""
        services = []
        soup = BeautifulSoup(html, "html.parser")
        
        for card in soup.select("div.card"):
            title_el = card.select_one("h5, h6, .card-title, .toptitle")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not title:
                continue
            
            status_el = card.select_one("p.card-text, .card-text, p")
            raw_status = status_el.get_text(" ", strip=True) if status_el else ""
            if raw_status.lower() in ("search", "search."):
                raw_status = ""
            
            form = card.select_one("form")
            action = form.get("action") if form else None
            inp = None
            if form:
                inp = form.select_one("input[type=text], input.form-control, input:not([type=hidden])")
            input_name = inp.get("name") if inp else None
            
            available = False
            if raw_status:
                if "online" in raw_status.lower() or "update" in raw_status.lower() or "days ago" in raw_status.lower():
                    available = True
            elif action:
                available = True
            
            services.append({
                "title": title,
                "status": raw_status or "Online",
                "available": available,
                "action": action,
                "input_name": input_name
            })
        
        return services
    
    def get_services(self):
        """Lấy danh sách services (phải login trước)"""
        if not self.is_logged_in:
            return []
        if self.services_cache:
            return self.services_cache
        
        html = self.session.get(self.base_url, timeout=30).text
        self.services_cache = self._parse_services(html)
        return self.services_cache
    
    def submit_service(self, link, service_name):
        """Gửi service (phải login trước)"""
        if not self.is_logged_in:
            return {"success": False, "error": "Chưa đăng nhập. Vui lòng giải captcha trước"}
        
        services = self.get_services()
        
        service_action = None
        service_input = None
        
        for svc in services:
            if svc["title"].lower() == service_name.lower():
                service_action = svc.get("action")
                service_input = svc.get("input_name")
                break
        
        if not service_action:
            html = self.session.get(self.base_url, timeout=30).text
            for m in re.finditer(r'<form action="([^"]+)"[^>]*>[\s\S]*?name="([^"]+)"[^>]*placeholder="Enter Video', html, re.I):
                prev = html[max(0, m.start() - 400):m.start()]
                titles = re.findall(r'<h5[^>]*>([^<]+)</h5>', prev)
                title = titles[-1].strip() if titles else service_name
                if title.lower() == service_name.lower():
                    service_action = m.group(1)
                    service_input = m.group(2)
                    break
        
        if not service_action:
            return {"success": False, "error": f"Service '{service_name}' not found"}
        
        url = service_action if service_action.startswith("http") else f"{self.base_url}{service_action}"
        token = "".join(random.choices(ascii_letters + digits, k=16))
        boundary = f'----WebKitFormBoundary{token}'
        
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{service_input or "video_url"}"\r\n\r\n{link}\r\n']
        parts.append(f'--{boundary}--\r\n')
        body = ''.join(parts)
        
        resp = self.session.post(
            url,
            headers={
                'content-type': f'multipart/form-data; boundary={boundary}',
                'user-agent': self.user_agent,
                'origin': self.base_url,
                'referer': self.base_url,
                'accept': '*/*'
            },
            data=body.encode('utf-8'),
            timeout=45
        )
        
        text = resp.text.strip()
        if text.lower() == 'success':
            return {"success": True, "message": "Đã gửi thành công"}
        
        try:
            decoded = base64.b64decode(text).decode('utf-8', errors='replace')
            if 'success' in decoded.lower():
                return {"success": True, "message": decoded}
        except:
            pass
        
        return {"success": False, "message": text or "Không có phản hồi"}
    
    def solve_and_login(self, max_attempts=3):
        """Tự động giải captcha và đăng nhập"""
        for attempt in range(max_attempts):
            try:
                captcha = self.get_captcha()
                answer = solve_captcha(captcha.image_bytes)
                if not answer:
                    continue
                result = self.login(answer)
                if result["success"]:
                    return {
                        "success": True,
                        "answer": answer,
                        "attempts": attempt + 1,
                        "services": result.get("services", [])
                    }
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                time.sleep(2)
        return {"success": False, "error": "Max attempts reached"}

# ==================== API ENDPOINTS ====================

@app.route('/api/captcha', methods=['GET'])
def api_get_captcha():
    """Lấy captcha mới"""
    try:
        client = ZefoyClient()
        captcha = client.get_captcha()
        return jsonify({
            'success': True,
            'session_id': captcha.session_id,
            'image': base64.b64encode(captcha.image_bytes).decode('ascii'),
            'image_url': captcha.image_url,
            'captcha_token': captcha.captcha_token
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/login', methods=['POST'])
def api_login():
    """Đăng nhập bằng captcha"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Missing data'}), 400
        
        answer = data.get('answer', '').strip()
        if not answer:
            return jsonify({'success': False, 'error': 'Vui lòng nhập captcha'}), 400
        
        client = ZefoyClient()
        result = client.login(answer)
        
        if result["success"]:
            return jsonify({
                'success': True,
                'message': 'Đăng nhập thành công',
                'services': result.get("services", [])
            })
        else:
            return jsonify({'success': False, 'error': result.get('error', 'Đăng nhập thất bại')}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/solve', methods=['POST'])
def api_solve():
    """Tự động giải captcha và đăng nhập"""
    try:
        client = ZefoyClient()
        result = client.solve_and_login(max_attempts=3)
        
        if result.get('success'):
            return jsonify({
                'success': True,
                'message': 'Đăng nhập thành công',
                'answer': result.get('answer'),
                'attempts': result.get('attempts'),
                'services': result.get('services', [])
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Không thể giải captcha')
            }), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/submit', methods=['POST'])
def api_submit():
    """Gửi service (phải login trước)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Missing data'}), 400
        
        link = data.get('link', '').strip()
        service = data.get('service', 'Comments Hearts')
        answer = data.get('answer', '').strip()
        
        if not link:
            return jsonify({'success': False, 'error': 'Vui lòng nhập link video'}), 400
        
        client = ZefoyClient()
        
        if answer:
            login_result = client.login(answer)
            if not login_result["success"]:
                return jsonify({'success': False, 'error': login_result.get('error', 'Đăng nhập thất bại')}), 400
        else:
            login_result = client.solve_and_login(max_attempts=3)
            if not login_result.get("success"):
                return jsonify({'success': False, 'error': login_result.get('error', 'Không thể đăng nhập')}), 400
        
        result = client.submit_service(link, service)
        
        if result.get('success'):
            return jsonify({'success': True, 'message': result.get('message', 'Thành công')})
        else:
            return jsonify({'success': False, 'error': result.get('error', result.get('message', 'Thất bại'))}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/services', methods=['GET'])
def api_services():
    """Lấy danh sách services (phải login trước)"""
    try:
        client = ZefoyClient()
        if not client.is_logged_in:
            login_result = client.solve_and_login(max_attempts=2)
            if not login_result.get("success"):
                return jsonify({'success': False, 'error': 'Không thể đăng nhập'}), 400
        
        services = client.get_services()
        return jsonify({'success': True, 'services': services})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/status', methods=['GET'])
def api_status():
    """Kiểm tra trạng thái API"""
    return jsonify({
        'status': 'running',
        'version': '2.1',
        'timestamp': datetime.now().isoformat(),
        'endpoints': [
            'GET  /api/captcha  - Lấy captcha',
            'POST /api/login    - Login bằng captcha',
            'POST /api/solve    - Auto login (OCR)',
            'POST /api/submit   - Gửi service',
            'GET  /api/services - Danh sách service',
            'GET  /api/status   - Trạng thái'
        ]
    })

# ==================== HTML TEMPLATE ====================
HTML_INDEX = '''
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zefoy API - Tool TikTok</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        body { background: #0d1117; color: #c9d1d9; min-height: 100vh; }
        .navbar { background: #161b22 !important; border-bottom: 1px solid #30363d; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; }
        .card-header { background: transparent; border-bottom: 1px solid #30363d; }
        .form-control, .form-select { background: #0d1117; border: 1px solid #30363d; color: #c9d1d9; }
        .form-control:focus, .form-select:focus { background: #0d1117; border-color: #58a6ff; color: #c9d1d9; box-shadow: 0 0 0 3px rgba(88,166,255,0.2); }
        .btn-primary { background: #238636; border: none; }
        .btn-primary:hover { background: #2ea043; }
        .btn-secondary { background: #21262d; border: 1px solid #30363d; }
        .btn-secondary:hover { background: #30363d; }
        .btn-success { background: #1a7f37; border: none; }
        .btn-success:hover { background: #2ea043; }
        .captcha-img { border-radius: 8px; border: 1px solid #30363d; max-width: 100%; max-height: 120px; }
        .log-area { background: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 12px; max-height: 200px; overflow-y: auto; font-family: monospace; font-size: 13px; color: #8b949e; }
        .log-area .log-success { color: #3fb950; }
        .log-area .log-error { color: #f85149; }
        .log-area .log-info { color: #58a6ff; }
        .service-badge { background: #21262d; padding: 4px 12px; border-radius: 20px; font-size: 12px; cursor: pointer; border: 1px solid #30363d; display: inline-block; margin: 2px; }
        .service-badge:hover { border-color: #58a6ff; }
        .service-badge.active { background: #238636; border-color: #238636; color: #fff; }
        .service-badge.offline { opacity: 0.5; }
        .login-status { padding: 8px 16px; border-radius: 20px; font-size: 13px; }
        .login-status.logged-in { background: #1a7f37; color: #fff; }
        .login-status.logged-out { background: #21262d; color: #8b949e; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg sticky-top">
        <div class="container">
            <a class="navbar-brand text-white fw-bold" href="/"><i class="bi bi-rocket-takeoff"></i> Zefoy API</a>
            <div class="ms-auto d-flex align-items-center gap-2">
                <span id="loginStatus" class="login-status logged-out"><i class="bi bi-circle-fill" style="font-size:8px;"></i> Chưa login</span>
                <a href="/api/status" target="_blank" class="btn btn-secondary btn-sm"><i class="bi bi-info-circle"></i> API</a>
            </div>
        </div>
    </nav>
    <div class="container py-4">
        <div class="row">
            <div class="col-lg-8 mx-auto">
                <div class="text-center mb-4">
                    <h1 class="display-5 fw-bold">🚀 Tool Tăng Tương Tác TikTok</h1>
                    <p class="text-muted">Comments Hearts, Views, Followers, Shares và nhiều hơn</p>
                </div>
                
                <div class="card mb-3">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <span><i class="bi bi-shield-check"></i> Xác thực Captcha</span>
                        <button class="btn btn-secondary btn-sm" id="refreshCaptcha"><i class="bi bi-arrow-clockwise"></i> Làm mới</button>
                    </div>
                    <div class="card-body">
                        <div class="row align-items-center">
                            <div class="col-md-4 text-center">
                                <img id="captchaImg" class="captcha-img" src="" alt="Captcha">
                                <div id="captchaStatus" class="mt-2 small text-muted">Chưa tải captcha</div>
                            </div>
                            <div class="col-md-8">
                                <div class="input-group">
                                    <input type="text" class="form-control" id="captchaAnswer" placeholder="Nhập captcha">
                                    <button class="btn btn-primary" id="loginBtn"><i class="bi bi-box-arrow-in-right"></i> Login</button>
                                </div>
                                <div class="mt-2 d-flex gap-2 flex-wrap">
                                    <button class="btn btn-success btn-sm" id="autoSolve"><i class="bi bi-magic"></i> Auto Login</button>
                                    <button class="btn btn-secondary btn-sm" id="getServicesBtn"><i class="bi bi-list-ul"></i> Lấy Services</button>
                                    <span class="text-muted small align-self-center">(Cần login trước)</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card mb-3">
                    <div class="card-body">
                        <div class="row g-3">
                            <div class="col-md-7">
                                <label class="form-label small text-muted">Link video TikTok</label>
                                <input type="text" class="form-control" id="videoLink" placeholder="https://www.tiktok.com/@user/video/123456789">
                            </div>
                            <div class="col-md-5">
                                <label class="form-label small text-muted">Chọn dịch vụ</label>
                                <select class="form-select" id="serviceSelect">
                                    <option value="Comments Hearts">💬 Comments Hearts</option>
                                    <option value="Views">👁️ Views</option>
                                    <option value="Hearts">❤️ Hearts</option>
                                    <option value="Followers">👥 Followers</option>
                                    <option value="Shares">🔄 Shares</option>
                                    <option value="Favorites">⭐ Favorites</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card mb-3">
                    <div class="card-header"><i class="bi bi-terminal"></i> Log</div>
                    <div class="card-body"><div id="logArea" class="log-area"><div class="log-info">🔹 Chờ thực hiện...</div></div></div>
                </div>

                <div class="card mb-3">
                    <div class="card-header"><i class="bi bi-list-ul"></i> Dịch vụ khả dụng</div>
                    <div class="card-body" id="servicesContainer">
                        <span class="text-muted">🔹 Đăng nhập để xem dịch vụ</span>
                    </div>
                </div>

                <button class="btn btn-primary w-100 btn-lg" id="submitBtn"><i class="bi bi-play-circle"></i> Bắt đầu</button>
            </div>
        </div>
    </div>

    <script>
        let currentSessionId = null;
        let isProcessing = false;
        let isLoggedIn = false;

        function log(msg, type='info') {
            const area = document.getElementById('logArea');
            const d = document.createElement('div');
            d.className = 'log-' + type;
            d.textContent = '[' + new Date().toLocaleTimeString() + '] ' + msg;
            area.appendChild(d);
            area.scrollTop = area.scrollHeight;
        }

        function updateLoginStatus(status) {
            const el = document.getElementById('loginStatus');
            if (status) {
                el.className = 'login-status logged-in';
                el.innerHTML = '<i class="bi bi-circle-fill" style="font-size:8px;"></i> Đã login';
                isLoggedIn = true;
            } else {
                el.className = 'login-status logged-out';
                el.innerHTML = '<i class="bi bi-circle-fill" style="font-size:8px;"></i> Chưa login';
                isLoggedIn = false;
            }
        }

        function renderServices(services) {
            const container = document.getElementById('servicesContainer');
            if (!services || services.length === 0) {
                container.innerHTML = '<span class="text-muted">🔹 Không có dịch vụ nào</span>';
                return;
            }
            container.innerHTML = services.map(s => 
                `<span class="service-badge ${s.available ? 'active' : 'offline'}" 
                     onclick="selectService('${s.title}')">
                    ${s.available ? '🟢' : '🔴'} ${s.title}
                </span>`
            ).join(' ');
        }

        function selectService(title) {
            document.getElementById('serviceSelect').value = title;
            document.querySelectorAll('.service-badge').forEach(el => {
                el.classList.toggle('active', el.textContent.includes(title));
            });
        }

        async function refreshCaptcha() {
            try {
                log('Đang tải captcha...', 'info');
                const resp = await fetch('/api/captcha');
                const data = await resp.json();
                if (data.success) {
                    currentSessionId = data.session_id;
                    document.getElementById('captchaImg').src = 'data:image/png;base64,' + data.image;
                    document.getElementById('captchaStatus').textContent = '✅ Captcha đã tải';
                    document.getElementById('captchaAnswer').value = '';
                    log('Captcha đã tải', 'success');
                    updateLoginStatus(false);
                } else {
                    log('Lỗi: ' + data.error, 'error');
                }
            } catch(e) { log('Lỗi: ' + e.message, 'error'); }
        }

        async function login(answer) {
            if (!answer) {
                log('⚠️ Vui lòng nhập captcha', 'error');
                return false;
            }
            try {
                log('Đang đăng nhập...', 'info');
                const resp = await fetch('/api/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({answer: answer})
                });
                const data = await resp.json();
                if (data.success) {
                    log('✅ Đăng nhập thành công!', 'success');
                    updateLoginStatus(true);
                    if (data.services) {
                        renderServices(data.services);
                        log('📋 Đã tải ' + data.services.length + ' dịch vụ', 'success');
                    }
                    return true;
                } else {
                    log('❌ Đăng nhập thất bại: ' + (data.error || 'Unknown error'), 'error');
                    return false;
                }
            } catch(e) {
                log('❌ Lỗi: ' + e.message, 'error');
                return false;
            }
        }

        async function autoSolve() {
            try {
                log('🔓 Đang auto login...', 'info');
                const resp = await fetch('/api/solve', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({})
                });
                const data = await resp.json();
                if (data.success) {
                    document.getElementById('captchaAnswer').value = data.answer || '';
                    log('✅ Auto login thành công! Captcha: ' + data.answer, 'success');
                    updateLoginStatus(true);
                    if (data.services) {
                        renderServices(data.services);
                        log('📋 Đã tải ' + data.services.length + ' dịch vụ', 'success');
                    }
                    return true;
                } else {
                    log('❌ Auto login thất bại: ' + (data.error || 'Unknown'), 'error');
                    return false;
                }
            } catch(e) {
                log('❌ Lỗi: ' + e.message, 'error');
                return false;
            }
        }

        async function getServices() {
            if (!isLoggedIn) {
                log('⚠️ Vui lòng đăng nhập trước', 'error');
                return;
            }
            try {
                log('📋 Đang lấy danh sách dịch vụ...', 'info');
                const resp = await fetch('/api/services');
                const data = await resp.json();
                if (data.success) {
                    renderServices(data.services);
                    log('📋 Đã tải ' + data.services.length + ' dịch vụ', 'success');
                } else {
                    log('❌ Lỗi: ' + data.error, 'error');
                }
            } catch(e) {
                log('❌ Lỗi: ' + e.message, 'error');
            }
        }

        async function submit() {
            if (isProcessing) return;
            isProcessing = true;
            const btn = document.getElementById('submitBtn');
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Đang xử lý...';

            try {
                const link = document.getElementById('videoLink').value.trim();
                const service = document.getElementById('serviceSelect').value;
                const answer = document.getElementById('captchaAnswer').value.trim();

                if (!link) {
                    log('⚠️ Nhập link video', 'error');
                    return;
                }

                log('🚀 Đang gửi ' + service + '...', 'info');
                
                const resp = await fetch('/api/submit', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        link: link,
                        service: service,
                        answer: answer || undefined
                    })
                });
                const data = await resp.json();
                if (data.success) {
                    log('✅ ' + (data.message || 'Thành công!'), 'success');
                } else {
                    log('❌ ' + (data.error || data.message || 'Thất bại'), 'error');
                    if (data.error && data.error.includes('login')) {
                        updateLoginStatus(false);
                    }
                }
            } catch(e) {
                log('❌ ' + e.message, 'error');
            }
            finally {
                isProcessing = false;
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-play-circle"></i> Bắt đầu';
            }
        }

        // Event listeners
        document.getElementById('refreshCaptcha').addEventListener('click', refreshCaptcha);
        document.getElementById('loginBtn').addEventListener('click', () => {
            login(document.getElementById('captchaAnswer').value.trim());
        });
        document.getElementById('autoSolve').addEventListener('click', autoSolve);
        document.getElementById('getServicesBtn').addEventListener('click', getServices);
        document.getElementById('submitBtn').addEventListener('click', submit);

        document.getElementById('captchaAnswer').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') login(document.getElementById('captchaAnswer').value.trim());
        });
        document.getElementById('videoLink').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') submit();
        });

        window.onload = function() {
            refreshCaptcha();
            log('🚀 Zefoy API đã sẵn sàng', 'success');
            log('💡 Hướng dẫn: Login → Chọn service → Gửi', 'info');
        };
    </script>
</body>
</html>
'''

# ==================== MAIN ROUTE ====================
@app.route('/')
def index():
    return render_template_string(HTML_INDEX)

# ==================== MAIN ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    print("=" * 50)
    print("🚀 ZEFOY API SERVER v2.1")
    print("=" * 50)
    print(f"📍 Port: {port}")
    print("📌 Endpoints:")
    print("  GET  /api/captcha  - Lấy captcha")
    print("  POST /api/login    - Login bằng captcha")
    print("  POST /api/solve    - Auto login")
    print("  POST /api/submit   - Gửi service")
    print("  GET  /api/services - Danh sách service")
    print("  GET  /api/status   - Trạng thái")
    print("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=debug, threaded=True)
