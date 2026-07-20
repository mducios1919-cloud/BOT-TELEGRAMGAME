import os
import sys
import json
import time
import base64
import hashlib
import re
import random
from datetime import datetime
from string import ascii_letters, digits

try:
    import flask
except ImportError:
    os.system("pip install flask flask-cors requests beautifulsoup4 pycryptodome gunicorn")

from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

app = Flask(__name__)
CORS(app)

# ==================== CONSTANTS ====================
BASE_URL = "https://zefoy.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
AES_KEY = "43fdda1192dde7f8ffff7161e13580d7"

# ==================== CRYPTO ====================
def _evp_bytes_to_key(password, salt, key_len=32, iv_len=16):
    derived = b""
    block = b""
    while len(derived) < key_len + iv_len:
        block = hashlib.md5(block + password + salt).digest()
        derived += block
    return derived[:key_len], derived[key_len:key_len + iv_len]

def encrypt_aes(plaintext):
    salt = os.urandom(8)
    key, iv = _evp_bytes_to_key(AES_KEY.encode(), salt)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    ct = cipher.encrypt(pad(plaintext.encode(), AES.block_size))
    return json.dumps({
        "ct": base64.b64encode(ct).decode(),
        "iv": iv.hex(),
        "s": salt.hex()
    })

# ==================== FINGERPRINT ====================
def build_fingerprint():
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Saigon")
        now = datetime.now(tz)
        offset = -int(now.utcoffset().total_seconds() // 60)
        dt = now.strftime("%H:%M:%S %d/%m/%Y")
    except:
        offset = 420
        dt = datetime.now().strftime("%H:%M:%S %d/%m/%Y")
    
    return {
        "deviceInfo": {
            "cpuCores": 8,
            "deviceMemoryGB": 8,
            "platform": "Win32",
            "gpu": {"vendor": "Google Inc.", "renderer": "ANGLE"}
        },
        "browserInfo": {
            "userAgent": USER_AGENT,
            "timezone": "Asia/Saigon",
            "timezoneOffset": offset,
            "localeDateTime": dt,
            "language": "en",
            "webdriver": False
        },
        "screenInfo": {"width": 1920, "height": 1080, "colorDepth": 24},
        "storageInfo": {"localStorage": "Yes", "sessionStorage": "Yes"}
    }

# ==================== ZEFOY CLIENT ====================
class ZefoyClient:
    def __init__(self):
        self.s = requests.Session()
        self.s.verify = False
        self.s.headers.update({"User-Agent": USER_AGENT})
        self.is_logged_in = False
        self.services = []
    
    def _get_captcha(self):
        """Lấy captcha image và token"""
        self.s.get(BASE_URL, timeout=30)
        self.s.cookies.set("zf", hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest())
        self.s.cookies.set("za", "200")
        
        ts = int(time.time())
        resp = self.s.get(f"{BASE_URL}/?getcapthca={ts}", 
                          headers={"X-Requested-With": "XMLHttpRequest"}, timeout=30)
        data = resp.json()
        
        key = hashlib.md5(USER_AGENT.encode()).hexdigest()
        encoded = data.get(key) or list(data.values())[0]
        
        path = base64.b64decode(base64.b64decode(encoded)).decode().strip()
        if not path.startswith("/"):
            path = "/" + path
        
        img_resp = self.s.get(f"{BASE_URL}{path}", timeout=30)
        token = path.split("_CAPTCHA=")[1].split("&")[0] if "_CAPTCHA=" in path else None
        
        return {
            "image": img_resp.content,
            "token": token,
            "path": path,
            "session": self.s.cookies.get("PHPSESSID")
        }
    
    def _login(self, answer):
        """Submit captcha answer"""
        answer = re.sub(r'[^a-zA-Z]', '', answer or "").lower()
        if not answer:
            return False
        
        encoded = encrypt_aes(json.dumps(build_fingerprint()))
        
        resp = self.s.post(BASE_URL, data={
            "captchalogin": answer,
            "captcha_encoded": encoded
        }, headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": BASE_URL + "/"
        }, timeout=30, allow_redirects=False)
        
        if resp.text.strip().lower() == "success":
            self.is_logged_in = True
            self._load_services()
            return True
        return False
    
    def _load_services(self):
        """Lấy danh sách services sau khi login"""
        html = self.s.get(BASE_URL, timeout=30).text
        self.services = []
        soup = BeautifulSoup(html, "html.parser")
        
        for card in soup.select("div.card"):
            title = card.select_one("h5, h6, .card-title")
            if not title:
                continue
            name = title.get_text(strip=True)
            if not name:
                continue
            
            form = card.select_one("form")
            action = form.get("action") if form else None
            inp = form.select_one("input[type=text]") if form else None
            input_name = inp.get("name") if inp else None
            
            available = bool(form)
            self.services.append({
                "name": name,
                "action": action,
                "input_name": input_name,
                "available": available
            })
    
    def auto_login(self, max_attempts=5):
        """Tự động giải captcha và login"""
        for i in range(max_attempts):
            try:
                captcha = self._get_captcha()
                answer = self._ocr(captcha["image"])
                if answer and len(answer) >= 3:
                    if self._login(answer):
                        return {"success": True, "answer": answer, "attempt": i+1, "services": self.services}
            except Exception as e:
                print(f"Attempt {i+1}: {e}")
            time.sleep(2)
        return {"success": False, "error": "Max attempts"}
    
    def _ocr(self, img_bytes):
        """OCR bằng newocr.com"""
        try:
            session = requests.Session()
            session.verify = False
            session.headers.update({"User-Agent": USER_AGENT})
            
            session.get("https://www.newocr.com", timeout=30)
            resp = session.post("https://www.newocr.com", data={"preview": "1"},
                               files={"userfile": ("captcha.png", img_bytes)}, timeout=60)
            
            html = resp.text
            m = re.search(r'name\s*=\s*["\']?u["\']?\s+value\s*=\s*["\']([a-f0-9]{32})["\']', html, re.I)
            if not m:
                m = re.search(r'name\s*=\s*["\']u["\'][^>]*value\s*=\s*["\']([^"\']+)', html, re.I)
            file_id = m.group(1) if m else None
            if not file_id:
                return ""
            
            resp = session.post("https://www.newocr.com", data={
                "u": file_id, "ocr": "1", "l2[]": "eng", "psm": "6",
                "x1": "0", "y1": "0", "x2": "100", "y2": "100"
            }, timeout=60)
            
            m = re.search(r'<textarea[^>]*id=["\']ocr-result["\'][^>]*>([\s\S]*?)</textarea>', resp.text, re.I)
            text = m.group(1).strip() if m else ""
            return re.sub(r'[^a-zA-Z]', '', text).lower()
        except:
            return ""
    
    def submit_service(self, link, service_name):
        """Gửi service"""
        if not self.is_logged_in:
            return {"success": False, "error": "Chưa đăng nhập"}
        
        # Tìm service
        svc = None
        for s in self.services:
            if s["name"].lower() == service_name.lower():
                svc = s
                break
        
        if not svc or not svc["action"]:
            # Thử parse lại
            self._load_services()
            for s in self.services:
                if s["name"].lower() == service_name.lower():
                    svc = s
                    break
        
        if not svc or not svc["action"]:
            return {"success": False, "error": f"Không tìm thấy service: {service_name}"}
        
        # Submit
        url = svc["action"] if svc["action"].startswith("http") else f"{BASE_URL}{svc['action']}"
        boundary = f"----WebKitFormBoundary{''.join(random.choices(ascii_letters + digits, k=16))}"
        body = f'--{boundary}\r\nContent-Disposition: form-data; name="{svc["input_name"] or "video_url"}"\r\n\r\n{link}\r\n--{boundary}--\r\n'
        
        resp = self.s.post(url, data=body.encode(), headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Origin": BASE_URL,
            "Referer": BASE_URL + "/"
        }, timeout=45)
        
        text = resp.text.strip()
        if text.lower() == "success":
            return {"success": True, "message": "Đã gửi thành công!"}
        try:
            decoded = base64.b64decode(text).decode()
            if "success" in decoded.lower():
                return {"success": True, "message": decoded}
        except:
            pass
        return {"success": False, "message": text or "Không có phản hồi"}

# ==================== API ====================
client = ZefoyClient()

@app.route('/api/captcha')
def get_captcha():
    try:
        c = client._get_captcha()
        return jsonify({
            "success": True,
            "image": base64.b64encode(c["image"]).decode(),
            "token": c["token"],
            "session": c["session"]
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        answer = data.get("answer", "").strip()
        if not answer:
            return jsonify({"success": False, "error": "Nhập captcha"})
        
        if client._login(answer):
            return jsonify({"success": True, "services": client.services})
        return jsonify({"success": False, "error": "Sai captcha"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/solve', methods=['POST'])
def auto_solve():
    try:
        result = client.auto_login(max_attempts=5)
        if result["success"]:
            return jsonify({"success": True, "answer": result["answer"], "services": client.services})
        return jsonify({"success": False, "error": result.get("error", "Thất bại")})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/submit', methods=['POST'])
def submit():
    try:
        data = request.get_json()
        link = data.get("link", "").strip()
        service = data.get("service", "Comments Hearts")
        answer = data.get("answer", "").strip()
        
        if not link:
            return jsonify({"success": False, "error": "Nhập link video"})
        
        # Nếu có captcha thì login trước
        if answer:
            if not client._login(answer):
                return jsonify({"success": False, "error": "Sai captcha"})
        elif not client.is_logged_in:
            # Auto login
            result = client.auto_login(max_attempts=3)
            if not result["success"]:
                return jsonify({"success": False, "error": "Không thể đăng nhập"})
        
        return jsonify(client.submit_service(link, service))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/services')
def services():
    try:
        if not client.is_logged_in:
            client.auto_login(max_attempts=2)
        return jsonify({"success": True, "services": client.services})
    except:
        return jsonify({"success": False, "services": []})

@app.route('/api/status')
def status():
    return jsonify({
        "status": "running",
        "version": "3.0",
        "timestamp": datetime.now().isoformat()
    })

# ==================== HTML ====================
HTML = '''
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zefoy API v3</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        body { background: #0d1117; color: #c9d1d9; }
        .card { background: #161b22; border: 1px solid #30363d; }
        .card-header { background: transparent; border-bottom: 1px solid #30363d; }
        .form-control, .form-select { background: #0d1117; border: 1px solid #30363d; color: #c9d1d9; }
        .form-control:focus, .form-select:focus { background: #0d1117; border-color: #58a6ff; color: #c9d1d9; }
        .btn-primary { background: #238636; border: none; }
        .btn-primary:hover { background: #2ea043; }
        .btn-success { background: #1a7f37; border: none; }
        .btn-success:hover { background: #2ea043; }
        .btn-secondary { background: #21262d; border: 1px solid #30363d; }
        .captcha-img { max-height: 120px; border-radius: 8px; border: 1px solid #30363d; }
        .log-area { background: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 12px; max-height: 150px; overflow-y: auto; font-family: monospace; font-size: 13px; }
        .log-area .log-success { color: #3fb950; }
        .log-area .log-error { color: #f85149; }
        .log-area .log-info { color: #58a6ff; }
        .login-status { padding: 8px 16px; border-radius: 20px; font-size: 13px; }
        .login-status.on { background: #1a7f37; color: #fff; }
        .login-status.off { background: #21262d; color: #8b949e; }
        .service-badge { background: #21262d; padding: 4px 12px; border-radius: 20px; font-size: 12px; cursor: pointer; border: 1px solid #30363d; display: inline-block; margin: 2px; }
        .service-badge:hover { border-color: #58a6ff; }
        .service-badge.active { background: #238636; border-color: #238636; color: #fff; }
        .service-badge.off { opacity: 0.4; }
    </style>
</head>
<body>
    <nav class="navbar navbar-dark bg-dark border-bottom border-secondary">
        <div class="container">
            <span class="navbar-brand"><i class="bi bi-rocket-takeoff"></i> Zefoy API v3</span>
            <span id="loginStatus" class="login-status off"><i class="bi bi-circle-fill" style="font-size:8px;"></i> Chưa login</span>
        </div>
    </nav>
    <div class="container py-4">
        <div class="row">
            <div class="col-lg-8 mx-auto">
                <div class="card mb-3">
                    <div class="card-header">
                        <i class="bi bi-shield-check"></i> Captcha
                        <button class="btn btn-secondary btn-sm float-end" id="refreshBtn"><i class="bi bi-arrow-clockwise"></i> Làm mới</button>
                    </div>
                    <div class="card-body">
                        <div class="row align-items-center">
                            <div class="col-md-4 text-center">
                                <img id="captchaImg" class="captcha-img" src="">
                                <div id="captchaStatus" class="mt-2 small text-muted">Chưa tải</div>
                            </div>
                            <div class="col-md-8">
                                <div class="input-group">
                                    <input type="text" class="form-control" id="captchaInput" placeholder="Nhập captcha">
                                    <button class="btn btn-primary" id="loginBtn"><i class="bi bi-box-arrow-in-right"></i> Login</button>
                                </div>
                                <div class="mt-2">
                                    <button class="btn btn-success btn-sm" id="autoBtn"><i class="bi bi-magic"></i> Auto Login</button>
                                    <button class="btn btn-secondary btn-sm" id="servicesBtn"><i class="bi bi-list-ul"></i> Lấy Services</button>
                                    <span class="text-muted small">(Auto Login = giải captcha tự động)</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="card mb-3">
                    <div class="card-body">
                        <div class="row g-2">
                            <div class="col-md-7">
                                <input type="text" class="form-control" id="videoLink" placeholder="Link TikTok">
                            </div>
                            <div class="col-md-5">
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
                    <div class="card-body"><div id="logArea" class="log-area"><div class="log-info">🔹 Đã sẵn sàng</div></div></div>
                </div>
                <div class="card mb-3">
                    <div class="card-header"><i class="bi bi-list-ul"></i> Dịch vụ</div>
                    <div class="card-body" id="servicesContainer"><span class="text-muted">🔹 Login để xem</span></div>
                </div>
                <button class="btn btn-primary w-100 btn-lg" id="submitBtn"><i class="bi bi-play-circle"></i> Bắt đầu</button>
            </div>
        </div>
    </div>
    <script>
        let loggedIn = false;
        let processing = false;

        function log(msg, type='info') {
            const el = document.getElementById('logArea');
            const d = document.createElement('div');
            d.className = 'log-' + type;
            d.textContent = '[' + new Date().toLocaleTimeString() + '] ' + msg;
            el.appendChild(d);
            el.scrollTop = el.scrollHeight;
        }

        function updateStatus(on) {
            const el = document.getElementById('loginStatus');
            loggedIn = on;
            if (on) {
                el.className = 'login-status on';
                el.innerHTML = '<i class="bi bi-circle-fill" style="font-size:8px;"></i> Đã login';
            } else {
                el.className = 'login-status off';
                el.innerHTML = '<i class="bi bi-circle-fill" style="font-size:8px;"></i> Chưa login';
            }
        }

        function renderServices(services) {
            const el = document.getElementById('servicesContainer');
            if (!services || services.length === 0) {
                el.innerHTML = '<span class="text-muted">🔹 Không có dịch vụ</span>';
                return;
            }
            el.innerHTML = services.map(s => 
                `<span class="service-badge ${s.available ? 'active' : 'off'}" onclick="selectService('${s.name}')">
                    ${s.available ? '🟢' : '🔴'} ${s.name}
                </span>`
            ).join(' ');
        }

        function selectService(name) {
            document.getElementById('serviceSelect').value = name;
            document.querySelectorAll('.service-badge').forEach(el => {
                el.classList.toggle('active', el.textContent.includes(name));
            });
        }

        async function refreshCaptcha() {
            try {
                log('Đang tải captcha...', 'info');
                const resp = await fetch('/api/captcha');
                const data = await resp.json();
                if (data.success) {
                    document.getElementById('captchaImg').src = 'data:image/png;base64,' + data.image;
                    document.getElementById('captchaStatus').textContent = '✅ Đã tải';
                    document.getElementById('captchaInput').value = '';
                    log('Captcha đã tải', 'success');
                    updateStatus(false);
                } else {
                    log('Lỗi: ' + data.error, 'error');
                }
            } catch(e) { log('Lỗi: ' + e.message, 'error'); }
        }

        async function login(answer) {
            if (!answer) {
                log('⚠️ Nhập captcha', 'error');
                return false;
            }
            try {
                log('Đang login...', 'info');
                const resp = await fetch('/api/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({answer: answer})
                });
                const data = await resp.json();
                if (data.success) {
                    log('✅ Login thành công!', 'success');
                    updateStatus(true);
                    if (data.services) {
                        renderServices(data.services);
                        log('📋 Đã tải ' + data.services.length + ' dịch vụ', 'success');
                    }
                    return true;
                } else {
                    log('❌ Login thất bại: ' + (data.error || 'Sai captcha'), 'error');
                    return false;
                }
            } catch(e) { log('❌ Lỗi: ' + e.message, 'error'); return false; }
        }

        async function autoLogin() {
            try {
                log('🔓 Đang auto login...', 'info');
                const resp = await fetch('/api/solve', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({})
                });
                const data = await resp.json();
                if (data.success) {
                    document.getElementById('captchaInput').value = data.answer || '';
                    log('✅ Auto login thành công! Captcha: ' + data.answer, 'success');
                    updateStatus(true);
                    if (data.services) {
                        renderServices(data.services);
                        log('📋 Đã tải ' + data.services.length + ' dịch vụ', 'success');
                    }
                    return true;
                } else {
                    log('❌ Auto login thất bại: ' + (data.error || 'Unknown'), 'error');
                    return false;
                }
            } catch(e) { log('❌ Lỗi: ' + e.message, 'error'); return false; }
        }

        async function getServices() {
            if (!loggedIn) {
                log('⚠️ Login trước', 'error');
                return;
            }
            try {
                log('📋 Đang lấy services...', 'info');
                const resp = await fetch('/api/services');
                const data = await resp.json();
                if (data.success) {
                    renderServices(data.services);
                    log('📋 Đã tải ' + data.services.length + ' dịch vụ', 'success');
                } else {
                    log('❌ Lỗi: ' + data.error, 'error');
                }
            } catch(e) { log('❌ Lỗi: ' + e.message, 'error'); }
        }

        async function submit() {
            if (processing) return;
            processing = true;
            const btn = document.getElementById('submitBtn');
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Đang xử lý...';

            try {
                const link = document.getElementById('videoLink').value.trim();
                const service = document.getElementById('serviceSelect').value;
                const answer = document.getElementById('captchaInput').value.trim();

                if (!link) {
                    log('⚠️ Nhập link video', 'error');
                    return;
                }

                log('🚀 Đang gửi ' + service + '...', 'info');
                const resp = await fetch('/api/submit', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({link, service, answer: answer || undefined})
                });
                const data = await resp.json();
                if (data.success) {
                    log('✅ ' + (data.message || 'Thành công!'), 'success');
                } else {
                    log('❌ ' + (data.error || data.message || 'Thất bại'), 'error');
                }
            } catch(e) { log('❌ ' + e.message, 'error'); }
            finally {
                processing = false;
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-play-circle"></i> Bắt đầu';
            }
        }

        // Events
        document.getElementById('refreshBtn').onclick = refreshCaptcha;
        document.getElementById('loginBtn').onclick = () => login(document.getElementById('captchaInput').value.trim());
        document.getElementById('autoBtn').onclick = autoLogin;
        document.getElementById('servicesBtn').onclick = getServices;
        document.getElementById('submitBtn').onclick = submit;
        document.getElementById('captchaInput').onkeypress = e => { if(e.key==='Enter') login(e.target.value.trim()); };
        document.getElementById('videoLink').onkeypress = e => { if(e.key==='Enter') submit(); };

        // Init
        refreshCaptcha();
        log('🚀 Zefoy API v3 đã sẵn sàng', 'success');
        log('💡 Login → Chọn service → Gửi', 'info');
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 50)
    print("🚀 ZEFOY API v3")
    print("=" * 50)
    print(f"📍 Port: {port}")
    print("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
