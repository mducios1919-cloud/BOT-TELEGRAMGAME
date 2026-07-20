# main.py - Ứng dụng chính với API và giao diện admin
import os
import sys
import json
import time
import base64
import threading
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from flask import Flask, request, jsonify, render_template, send_file, session, redirect, url_for
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import requests

# Thiết lập đường dẫn
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Import các module zefoy
try:
    from zefoy import ZefoyClient, ZefoyCaptcha, SubmitResult, CaptchaResult
    from zefoy.services import ServiceInfo, parse_services, print_services_table
    from zefoy.ocr import solve_image
    from zefoy.newocr import NewOcrWeb
    from zefoy.fingerprint import apply_session_guard_cookies, build_captcha_encoded
    from zefoy.submit import is_captcha_page
    ZEFOY_AVAILABLE = True
except ImportError as e:
    print(f"Lỗi import zefoy: {e}")
    ZEFOY_AVAILABLE = False

# Tạo Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'zefoy-secret-key-change-this')
CORS(app)

# Cấu hình
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'zefoy2026')
ADMIN_PASSWORD_HASH = generate_password_hash(ADMIN_PASSWORD)

# Lưu trữ dữ liệu (trong production nên dùng database)
SESSIONS = {}
CAPTCHA_CACHE = {}
SERVICE_CACHE = {}
CACHE_TIME = 300  # 5 phút

# ==================== UTILITY FUNCTIONS ====================

def require_admin(f):
    """Decorator yêu cầu đăng nhập admin"""
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated

def get_zefoy_client():
    """Tạo client zefoy mới"""
    if not ZEFOY_AVAILABLE:
        raise Exception("Zefoy module không khả dụng")
    return ZefoyClient(timeout=45)

def solve_captcha_auto(image_bytes: bytes) -> str:
    """Giải captcha tự động"""
    try:
        # Thử NewOCR web
        result = NewOcrWeb().ocr(image_bytes, lang="eng", psm="6")
        text = re.sub(r'[^a-zA-Z]', '', result.text or '').lower()
        if text:
            return text
    except Exception as e:
        print(f"NewOCR error: {e}")
    
    # Fallback dùng solve_image
    try:
        return solve_image(image_bytes)
    except Exception as e:
        print(f"Fallback OCR error: {e}")
        return ""

# ==================== API ENDPOINTS ====================

@app.route('/api/captcha', methods=['GET'])
def api_get_captcha():
    """Lấy captcha mới"""
    try:
        client = get_zefoy_client()
        captcha = client.get_captcha()
        
        # Lưu vào cache
        session_id = captcha.session_id or str(int(time.time()))
        CAPTCHA_CACHE[session_id] = {
            'captcha': captcha,
            'client': client,
            'created': time.time()
        }
        
        # Trả về dữ liệu
        return jsonify({
            'success': True,
            'session_id': session_id,
            'image': base64.b64encode(captcha.image_bytes).decode('ascii'),
            'image_url': captcha.image_url,
            'captcha_token': captcha.captcha_token,
            'message': 'Captcha đã được tạo'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/solve', methods=['POST'])
def api_solve_captcha():
    """Giải captcha và submit"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Missing JSON data'}), 400
        
        link = data.get('link', '').strip()
        service = data.get('service', 'Comments Hearts')
        captcha_answer = data.get('captcha_answer', '').strip()
        session_id = data.get('session_id', '')
        
        if not link:
            return jsonify({'success': False, 'error': 'Vui lòng nhập link video'}), 400
        
        # Nếu có captcha_answer thì dùng, không thì auto solve
        if captcha_answer:
            # Dùng captcha có sẵn
            client = get_zefoy_client()
            if session_id and session_id in CAPTCHA_CACHE:
                cache = CAPTCHA_CACHE[session_id]
                captcha = cache['captcha']
                client = cache['client']
            else:
                captcha = client.get_captcha()
            
            result = client.submit_answer(captcha_answer, captcha=captcha)
        else:
            # Auto solve
            result = client.solve_and_submit(max_attempts=3)
        
        if result.success:
            # Lấy danh sách services
            services = [s.title for s in result.services]
            
            return jsonify({
                'success': True,
                'message': 'Đã đăng nhập thành công',
                'session_id': result.session_id,
                'services': services,
                'answer': result.answer
            })
        else:
            return jsonify({
                'success': False,
                'error': result.message or 'Không thể giải captcha',
                'attempts': result.attempts
            }), 400
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/services', methods=['GET'])
def api_get_services():
    """Lấy danh sách services"""
    try:
        # Kiểm tra cache
        if SERVICE_CACHE and time.time() - SERVICE_CACHE.get('time', 0) < CACHE_TIME:
            return jsonify({
                'success': True,
                'services': SERVICE_CACHE.get('services', []),
                'cached': True
            })
        
        client = get_zefoy_client()
        # Đảm bảo có session
        client.get_captcha()
        
        # Lấy services
        html = client.session.get(client.base_url, timeout=30).text
        services = parse_services(html)
        
        # Cache
        SERVICE_CACHE['services'] = [s.to_dict() for s in services]
        SERVICE_CACHE['time'] = time.time()
        
        return jsonify({
            'success': True,
            'services': SERVICE_CACHE['services']
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/submit', methods=['POST'])
def api_submit_service():
    """Submit service (hearts, views, etc.)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Missing JSON data'}), 400
        
        link = data.get('link', '').strip()
        service = data.get('service', 'Comments Hearts')
        session_id = data.get('session_id', '')
        
        if not link:
            return jsonify({'success': False, 'error': 'Vui lòng nhập link video'}), 400
        
        # Lấy client từ session hoặc tạo mới
        if session_id and session_id in SESSIONS:
            client = SESSIONS[session_id]
        else:
            client = get_zefoy_client()
            SESSIONS[session_id] = client
        
        # Kiểm tra session
        client.session.get(client.base_url, timeout=30)
        
        # Tìm service action
        html = client.session.get(client.base_url, timeout=30).text
        services = parse_services(html)
        
        service_action = None
        service_input = None
        for s in services:
            if s.title.lower() == service.lower():
                service_action = s.action
                service_input = s.input_name
                break
        
        if not service_action:
            # Thử tìm bằng regex
            for m in re.finditer(
                r'<form action="([^"]+)"[^>]*>[\s\S]*?name="([^"]+)"[^>]*placeholder="Enter Video',
                html,
                re.I
            ):
                prev = html[max(0, m.start() - 400):m.start()]
                titles = re.findall(r'<h5[^>]*>([^<]+)</h5>', prev)
                title = titles[-1].strip() if titles else service
                if title.lower() == service.lower():
                    service_action = m.group(1)
                    service_input = m.group(2)
                    break
        
        if not service_action:
            return jsonify({'success': False, 'error': f'Không tìm thấy service: {service}'}), 400
        
        # Submit video
        url = service_action if service_action.startswith('http') else f'{client.base_url}{service_action}'
        token = "".join(random.choices(ascii_letters + digits, k=16))
        boundary = f'----WebKitFormBoundary{token}'
        
        parts = [
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="{service_input or "video_url"}"\r\n\r\n'
            f'{link}\r\n'
        ]
        parts.append(f'--{boundary}--\r\n')
        body = ''.join(parts)
        
        resp = client.session.post(
            url,
            headers={
                'content-type': f'multipart/form-data; boundary={boundary}',
                'user-agent': client.user_agent,
                'origin': client.base_url,
                'referer': client.base_url,
                'accept': '*/*'
            },
            data=body.encode('utf-8'),
            timeout=45
        )
        
        # Parse response
        text = resp.text.strip()
        if text.lower() == 'success':
            return jsonify({'success': True, 'message': 'Đã gửi thành công'})
        
        # Giải mã base64 nếu có
        try:
            decoded = base64.b64decode(text).decode('utf-8', errors='replace')
            if 'success' in decoded.lower():
                return jsonify({'success': True, 'message': decoded})
        except:
            pass
        
        return jsonify({'success': False, 'message': text or 'Không có phản hồi'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/status', methods=['GET'])
def api_status():
    """Kiểm tra trạng thái API"""
    return jsonify({
        'status': 'running',
        'zefoy_available': ZEFOY_AVAILABLE,
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0'
    })

# ==================== ADMIN ROUTES ====================

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Đăng nhập admin"""
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        
        return render_template('admin_login.html', error='Sai tên đăng nhập hoặc mật khẩu')
    
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    """Đăng xuất admin"""
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin')
@require_admin
def admin_dashboard():
    """Dashboard admin"""
    return render_template('admin_dashboard.html')

@app.route('/admin/services')
@require_admin
def admin_services():
    """Quản lý services"""
    return render_template('admin_services.html')

@app.route('/admin/api-keys')
@require_admin
def admin_api_keys():
    """Quản lý API keys"""
    # TODO: Implement API key management
    return render_template('admin_api_keys.html')

@app.route('/admin/settings')
@require_admin
def admin_settings():
    """Cài đặt"""
    return render_template('admin_settings.html')

# ==================== MAIN APP ROUTES ====================

@app.route('/')
def index():
    """Trang chủ"""
    return render_template('index.html')

@app.route('/captcha')
def captcha_page():
    """Trang captcha"""
    return render_template('index.html')

# ==================== STARTUP ====================

def create_requirements():
    """Tạo file requirements.txt"""
    req_path = ROOT / 'requirements.txt'
    requirements = [
        'flask>=2.3.0',
        'flask-cors>=4.0.0',
        'requests>=2.31.0',
        'beautifulsoup4>=4.12.0',
        'pycryptodome>=3.20.0',
        'python-dotenv>=1.0.0',
        'werkzeug>=2.3.0'
    ]
    
    if not req_path.exists():
        with open(req_path, 'w') as f:
            f.write('\n'.join(requirements))
    
    # Cũng tạo requirements cho zefoy nếu chưa có
    zefoy_req = ROOT / 'zefoy' / 'requirements.txt'
    if not zefoy_req.exists():
        zefoy_req.parent.mkdir(exist_ok=True)
        with open(zefoy_req, 'w') as f:
            f.write('\n'.join(requirements))

def create_templates():
    """Tạo các file template"""
    templates_dir = ROOT / 'templates'
    templates_dir.mkdir(exist_ok=True)
    
    # index.html
    with open(templates_dir / 'index.html', 'w', encoding='utf-8') as f:
        f.write('''<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zefoy API - Tool Tăng Tương Tác TikTok</title>
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
        .text-muted { color: #8b949e !important; }
        .bg-dark-card { background: #0d1117; }
        .service-badge { background: #21262d; padding: 4px 12px; border-radius: 20px; font-size: 12px; cursor: pointer; border: 1px solid #30363d; }
        .service-badge:hover { border-color: #58a6ff; }
        .service-badge.active { background: #238636; border-color: #238636; color: #fff; }
        .captcha-img { border-radius: 8px; border: 1px solid #30363d; max-width: 100%; }
        .log-area { background: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 12px; max-height: 200px; overflow-y: auto; font-family: monospace; font-size: 13px; color: #8b949e; }
        .log-area .log-success { color: #3fb950; }
        .log-area .log-error { color: #f85149; }
        .log-area .log-info { color: #58a6ff; }
        .preloader { display: none; }
        .spinner-border-sm { width: 1rem; height: 1rem; border-width: 0.15em; }
        .status-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }
        .status-online { background: #3fb950; }
        .status-offline { background: #f85149; }
        .status-wait { background: #d29922; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg sticky-top">
        <div class="container">
            <a class="navbar-brand text-white fw-bold" href="/">
                <i class="bi bi-rocket-takeoff"></i> Zefoy API
            </a>
            <div class="ms-auto">
                <span class="text-muted small">v1.0</span>
                <a href="/admin" class="btn btn-secondary btn-sm ms-2">
                    <i class="bi bi-shield-lock"></i> Admin
                </a>
            </div>
        </div>
    </nav>

    <div class="container py-4">
        <div class="row">
            <div class="col-lg-8 mx-auto">
                <div class="text-center mb-4">
                    <h1 class="display-5 fw-bold">🚀 Tool Tăng Tương Tác TikTok</h1>
                    <p class="text-muted">Hỗ trợ: Comments Hearts, Views, Followers, Shares và nhiều hơn</p>
                </div>

                <div class="card mb-3">
                    <div class="card-body">
                        <div class="row g-3">
                            <div class="col-md-8">
                                <label class="form-label small text-muted">Link video TikTok</label>
                                <div class="input-group">
                                    <span class="input-group-text bg-dark-card border-secondary"><i class="bi bi-link-45deg"></i></span>
                                    <input type="text" class="form-control" id="videoLink" placeholder="https://www.tiktok.com/@user/video/123456789">
                                </div>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label small text-muted">Chọn dịch vụ</label>
                                <select class="form-select" id="serviceSelect">
                                    <option value="Comments Hearts">💬 Comments Hearts</option>
                                    <option value="Views">👁️ Views</option>
                                    <option value="Hearts">❤️ Hearts</option>
                                    <option value="Followers">👥 Followers</option>
                                    <option value="Shares">🔄 Shares</option>
                                    <option value="Favorites">⭐ Favorites</option>
                                    <option value="Live Stream">🔴 Live Stream</option>
                                    <option value="Repost">🔄 Repost</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card mb-3">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <span><i class="bi bi-shield-check"></i> Xác thực Captcha</span>
                        <button class="btn btn-secondary btn-sm" id="refreshCaptcha">
                            <i class="bi bi-arrow-clockwise"></i> Làm mới
                        </button>
                    </div>
                    <div class="card-body">
                        <div class="row align-items-center">
                            <div class="col-md-4 text-center">
                                <img id="captchaImg" class="captcha-img" src="" alt="Captcha" style="max-height: 120px;">
                                <div id="captchaStatus" class="mt-2 small text-muted">Chưa tải captcha</div>
                            </div>
                            <div class="col-md-8">
                                <div class="input-group">
                                    <input type="text" class="form-control" id="captchaAnswer" placeholder="Nhập captcha">
                                    <button class="btn btn-primary" id="solveCaptcha">
                                        <i class="bi bi-check2-circle"></i> Giải
                                    </button>
                                </div>
                                <div class="mt-2">
                                    <button class="btn btn-secondary btn-sm" id="autoSolve">
                                        <i class="bi bi-magic"></i> Auto Solve
                                    </button>
                                    <span class="text-muted ms-2 small">(sử dụng OCR)</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card mb-3">
                    <div class="card-header">
                        <i class="bi bi-terminal"></i> Log
                    </div>
                    <div class="card-body">
                        <div id="logArea" class="log-area">
                            <div class="log-info">🔹 Chờ thực hiện...</div>
                        </div>
                    </div>
                </div>

                <div class="card mb-3">
                    <div class="card-header">
                        <i class="bi bi-list-ul"></i> Dịch vụ khả dụng
                    </div>
                    <div class="card-body" id="servicesList">
                        <div class="text-muted">Đang tải dịch vụ...</div>
                    </div>
                </div>

                <button class="btn btn-primary w-100 btn-lg" id="submitBtn">
                    <i class="bi bi-play-circle"></i> Bắt đầu
                </button>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        let currentSessionId = null;
        let isProcessing = false;

        function log(message, type = 'info') {
            const area = document.getElementById('logArea');
            const div = document.createElement('div');
            div.className = `log-${type}`;
            const time = new Date().toLocaleTimeString();
            div.textContent = `[${time}] ${message}`;
            area.appendChild(div);
            area.scrollTop = area.scrollHeight;
        }

        async function loadServices() {
            try {
                const resp = await fetch('/api/services');
                const data = await resp.json();
                if (data.success) {
                    const container = document.getElementById('servicesList');
                    container.innerHTML = data.services.map(s => 
                        `<span class="service-badge ${s.available ? 'active' : ''}" 
                             onclick="selectService('${s.title}')">
                            ${s.available ? '🟢' : '🔴'} ${s.title}
                        </span>`
                    ).join(' ');
                    log('Đã tải danh sách dịch vụ', 'success');
                }
            } catch(e) {
                log('Lỗi tải dịch vụ: ' + e.message, 'error');
            }
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
                    document.getElementById('captchaImg').src = `data:image/png;base64,${data.image}`;
                    document.getElementById('captchaStatus').textContent = '✅ Captcha đã tải';
                    document.getElementById('captchaAnswer').value = '';
                    log('Captcha đã tải thành công', 'success');
                } else {
                    log('Lỗi tải captcha: ' + data.error, 'error');
                }
            } catch(e) {
                log('Lỗi tải captcha: ' + e.message, 'error');
            }
        }

        async function autoSolve() {
            if (!currentSessionId) {
                await refreshCaptcha();
            }
            try {
                log('Đang auto solve captcha...', 'info');
                const resp = await fetch('/api/solve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        link: document.getElementById('videoLink').value || 'https://www.tiktok.com/@test/video/123456789',
                        service: document.getElementById('serviceSelect').value,
                        session_id: currentSessionId
                    })
                });
                const data = await resp.json();
                if (data.success) {
                    document.getElementById('captchaAnswer').value = data.answer || '';
                    log(`✅ Auto solve thành công: ${data.answer}`, 'success');
                    if (data.services) {
                        log(`Dịch vụ khả dụng: ${data.services.join(', ')}`, 'info');
                    }
                } else {
                    log('❌ Auto solve thất bại: ' + data.error, 'error');
                }
            } catch(e) {
                log('Lỗi auto solve: ' + e.message, 'error');
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
                    log('⚠️ Vui lòng nhập link video', 'error');
                    return;
                }

                if (!currentSessionId) {
                    await refreshCaptcha();
                }

                // Giải captcha nếu chưa có
                if (!answer) {
                    log('Đang giải captcha tự động...', 'info');
                    const solveResp = await fetch('/api/solve', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            link: link,
                            service: service,
                            session_id: currentSessionId
                        })
                    });
                    const solveData = await solveResp.json();
                    if (!solveData.success) {
                        log('❌ Giải captcha thất bại: ' + solveData.error, 'error');
                        return;
                    }
                    document.getElementById('captchaAnswer').value = solveData.answer || '';
                    log(`✅ Captcha: ${solveData.answer}`, 'success');
                }

                // Submit service
                log(`🚀 Đang gửi ${service} cho video...`, 'info');
                const resp = await fetch('/api/submit', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        link: link,
                        service: service,
                        session_id: currentSessionId
                    })
                });
                const data = await resp.json();
                if (data.success) {
                    log(`✅ ${data.message || 'Đã gửi thành công!'}`, 'success');
                } else {
                    log('❌ Lỗi: ' + (data.message || data.error || 'Không xác định'), 'error');
                }

            } catch(e) {
                log('❌ Lỗi: ' + e.message, 'error');
            } finally {
                isProcessing = false;
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-play-circle"></i> Bắt đầu';
            }
        }

        // Event listeners
        document.getElementById('refreshCaptcha').addEventListener('click', refreshCaptcha);
        document.getElementById('solveCaptcha').addEventListener('click', () => {
            // Giải thủ công - đã có captcha, chỉ cần nhập
            log('Nhập captcha thủ công và nhấn Bắt đầu', 'info');
        });
        document.getElementById('autoSolve').addEventListener('click', autoSolve);
        document.getElementById('submitBtn').addEventListener('click', submit);

        // Enter key support
        document.getElementById('captchaAnswer').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') submit();
        });
        document.getElementById('videoLink').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') submit();
        });

        // Khởi tạo
        window.onload = function() {
            refreshCaptcha();
            loadServices();
            log('🚀 Zefoy API đã sẵn sàng', 'success');
        };
    </script>
</body>
</html>''')

    # admin_login.html
    with open(templates_dir / 'admin_login.html', 'w', encoding='utf-8') as f:
        f.write('''<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Đăng nhập Admin - Zefoy API</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0d1117; color: #c9d1d9; min-height: 100vh; display: flex; align-items: center; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; }
        .card-header { background: transparent; border-bottom: 1px solid #30363d; }
        .form-control { background: #0d1117; border: 1px solid #30363d; color: #c9d1d9; }
        .form-control:focus { background: #0d1117; border-color: #58a6ff; color: #c9d1d9; box-shadow: 0 0 0 3px rgba(88,166,255,0.2); }
        .btn-primary { background: #238636; border: none; }
        .btn-primary:hover { background: #2ea043; }
        .alert-danger { background: #0d1117; border-color: #f85149; color: #f85149; }
    </style>
</head>
<body>
    <div class="container">
        <div class="row justify-content-center">
            <div class="col-md-4">
                <div class="card">
                    <div class="card-header text-center">
                        <h4><i class="bi bi-shield-lock"></i> Admin Login</h4>
                    </div>
                    <div class="card-body">
                        {% if error %}
                        <div class="alert alert-danger">{{ error }}</div>
                        {% endif %}
                        <form method="POST">
                            <div class="mb-3">
                                <label class="form-label small text-muted">Username</label>
                                <input type="text" name="username" class="form-control" required>
                            </div>
                            <div class="mb-3">
                                <label class="form-label small text-muted">Password</label>
                                <input type="password" name="password" class="form-control" required>
                            </div>
                            <button type="submit" class="btn btn-primary w-100">Đăng nhập</button>
                        </form>
                        <div class="text-center mt-3">
                            <a href="/" class="text-muted small">← Quay lại</a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
</body>
</html>''')

    # admin_dashboard.html
    with open(templates_dir / 'admin_dashboard.html', 'w', encoding='utf-8') as f:
        f.write('''<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard - Zefoy API</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        body { background: #0d1117; color: #c9d1d9; }
        .navbar { background: #161b22 !important; border-bottom: 1px solid #30363d; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; }
        .card-header { background: transparent; border-bottom: 1px solid #30363d; }
        .stat-card { text-align: center; padding: 20px; }
        .stat-card .number { font-size: 2rem; font-weight: bold; color: #58a6ff; }
        .stat-card .label { color: #8b949e; font-size: 0.9rem; }
        .sidebar { min-height: 100vh; border-right: 1px solid #30363d; }
        .nav-link { color: #8b949e; padding: 12px 20px; border-radius: 8px; }
        .nav-link:hover, .nav-link.active { color: #c9d1d9; background: #21262d; }
        .nav-link i { margin-right: 10px; width: 20px; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg sticky-top">
        <div class="container-fluid">
            <a class="navbar-brand text-white fw-bold" href="/admin">
                <i class="bi bi-shield-lock"></i> Zefoy Admin
            </a>
            <div class="ms-auto">
                <span class="text-muted small me-3">{{ now.strftime('%Y-%m-%d %H:%M') }}</span>
                <a href="/admin/logout" class="btn btn-secondary btn-sm">
                    <i class="bi bi-box-arrow-right"></i> Đăng xuất
                </a>
            </div>
        </div>
    </nav>

    <div class="container-fluid">
        <div class="row">
            <div class="col-md-2 sidebar pt-3">
                <nav class="nav flex-column">
                    <a class="nav-link active" href="/admin">
                        <i class="bi bi-speedometer2"></i> Dashboard
                    </a>
                    <a class="nav-link" href="/admin/services">
                        <i class="bi bi-list-ul"></i> Dịch vụ
                    </a>
                    <a class="nav-link" href="/admin/api-keys">
                        <i class="bi bi-key"></i> API Keys
                    </a>
                    <a class="nav-link" href="/admin/settings">
                        <i class="bi bi-gear"></i> Cài đặt
                    </a>
                    <hr class="border-secondary">
                    <a class="nav-link" href="/">
                        <i class="bi bi-house"></i> Trang chủ
                    </a>
                </nav>
            </div>
            <div class="col-md-10 pt-4">
                <h4><i class="bi bi-speedometer2"></i> Tổng quan</h4>
                <p class="text-muted">Quản lý API Zefoy và các dịch vụ</p>

                <div class="row g-3 mb-4">
                    <div class="col-md-3">
                        <div class="card stat-card">
                            <div class="number">1</div>
                            <div class="label">API Version</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card stat-card">
                            <div class="number" style="color: #3fb950;">{{ services_online }}</div>
                            <div class="label">Dịch vụ Online</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card stat-card">
                            <div class="number" style="color: #d29922;">{{ services_total }}</div>
                            <div class="label">Tổng dịch vụ</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card stat-card">
                            <div class="number" style="color: #f85149;">{{ 'OK' if zefoy_available else 'ERROR' }}</div>
                            <div class="label">Zefoy Status</div>
                        </div>
                    </div>
                </div>

                <div class="row">
                    <div class="col-md-6">
                        <div class="card">
                            <div class="card-header">📋 Dịch vụ khả dụng</div>
                            <div class="card-body" id="servicesList">
                                <div class="text-muted">Đang tải...</div>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="card">
                            <div class="card-header">🔑 API Endpoints</div>
                            <div class="card-body">
                                <div class="mb-2">
                                    <code class="text-info">GET /api/captcha</code>
                                    <span class="text-muted small d-block">Lấy captcha mới</span>
                                </div>
                                <div class="mb-2">
                                    <code class="text-info">POST /api/solve</code>
                                    <span class="text-muted small d-block">Giải captcha + đăng nhập</span>
                                </div>
                                <div class="mb-2">
                                    <code class="text-info">POST /api/submit</code>
                                    <span class="text-muted small d-block">Gửi service (hearts, views...)</span>
                                </div>
                                <div class="mb-2">
                                    <code class="text-info">GET /api/services</code>
                                    <span class="text-muted small d-block">Lấy danh sách dịch vụ</span>
                                </div>
                                <div class="mb-2">
                                    <code class="text-info">GET /api/status</code>
                                    <span class="text-muted small d-block">Kiểm tra trạng thái API</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        async function loadServices() {
            try {
                const resp = await fetch('/api/services');
                const data = await resp.json();
                if (data.success) {
                    const container = document.getElementById('servicesList');
                    container.innerHTML = data.services.map(s => 
                        `<div class="d-flex justify-content-between py-1 border-bottom border-secondary">
                            <span>${s.title}</span>
                            <span class="${s.available ? 'text-success' : 'text-danger'}">
                                ${s.available ? '🟢 Online' : '🔴 Offline'}
                            </span>
                        </div>`
                    ).join('');
                }
            } catch(e) {
                document.getElementById('servicesList').innerHTML = '<div class="text-danger">Lỗi tải dịch vụ</div>';
            }
        }
        loadServices();
        setInterval(loadServices, 30000);
    </script>
</body>
</html>''')

    # admin_services.html
    with open(templates_dir / 'admin_services.html', 'w', encoding='utf-8') as f:
        f.write('''<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dịch vụ - Zefoy API</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        body { background: #0d1117; color: #c9d1d9; }
        .navbar { background: #161b22 !important; border-bottom: 1px solid #30363d; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; }
        .card-header { background: transparent; border-bottom: 1px solid #30363d; }
        .sidebar { min-height: 100vh; border-right: 1px solid #30363d; }
        .nav-link { color: #8b949e; padding: 12px 20px; border-radius: 8px; }
        .nav-link:hover, .nav-link.active { color: #c9d1d9; background: #21262d; }
        .nav-link i { margin-right: 10px; width: 20px; }
        .table { color: #c9d1d9; }
        .table thead th { border-bottom: 1px solid #30363d; color: #8b949e; }
        .table td { border-bottom: 1px solid #21262d; }
        .status-online { color: #3fb950; }
        .status-offline { color: #f85149; }
        .status-wait { color: #d29922; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg sticky-top">
        <div class="container-fluid">
            <a class="navbar-brand text-white fw-bold" href="/admin">
                <i class="bi bi-shield-lock"></i> Zefoy Admin
            </a>
            <div class="ms-auto">
                <a href="/admin/logout" class="btn btn-secondary btn-sm">
                    <i class="bi bi-box-arrow-right"></i> Đăng xuất
                </a>
            </div>
        </div>
    </nav>

    <div class="container-fluid">
        <div class="row">
            <div class="col-md-2 sidebar pt-3">
                <nav class="nav flex-column">
                    <a class="nav-link" href="/admin">
                        <i class="bi bi-speedometer2"></i> Dashboard
                    </a>
                    <a class="nav-link active" href="/admin/services">
                        <i class="bi bi-list-ul"></i> Dịch vụ
                    </a>
                    <a class="nav-link" href="/admin/api-keys">
                        <i class="bi bi-key"></i> API Keys
                    </a>
                    <a class="nav-link" href="/admin/settings">
                        <i class="bi bi-gear"></i> Cài đặt
                    </a>
                    <hr class="border-secondary">
                    <a class="nav-link" href="/">
                        <i class="bi bi-house"></i> Trang chủ
                    </a>
                </nav>
            </div>
            <div class="col-md-10 pt-4">
                <div class="d-flex justify-content-between align-items-center mb-3">
                    <h4><i class="bi bi-list-ul"></i> Danh sách dịch vụ</h4>
                    <button class="btn btn-secondary btn-sm" onclick="loadServices()">
                        <i class="bi bi-arrow-clockwise"></i> Làm mới
                    </button>
                </div>
                <div class="card">
                    <div class="card-body">
                        <div class="table-responsive">
                            <table class="table" id="servicesTable">
                                <thead>
                                    <tr>
                                        <th>#</th>
                                        <th>Tên dịch vụ</th>
                                        <th>Trạng thái</th>
                                        <th>Action</th>
                                    </tr>
                                </thead>
                                <tbody id="servicesBody">
                                    <tr><td colspan="4" class="text-muted">Đang tải...</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        async function loadServices() {
            const tbody = document.getElementById('servicesBody');
            tbody.innerHTML = '<tr><td colspan="4" class="text-muted">Đang tải...</td></tr>';
            try {
                const resp = await fetch('/api/services');
                const data = await resp.json();
                if (data.success) {
                    tbody.innerHTML = data.services.map((s, i) => `
                        <tr>
                            <td>${i + 1}</td>
                            <td>${s.title}</td>
                            <td class="${s.available ? 'status-online' : 'status-offline'}">
                                ${s.available ? '🟢 Online' : '🔴 Offline'}
                                <span class="text-muted small">${s.status}</span>
                            </td>
                            <td>
                                <span class="text-muted small">${s.action || 'N/A'}</span>
                            </td>
                        </tr>
                    `).join('');
                }
            } catch(e) {
                tbody.innerHTML = `<tr><td colspan="4" class="text-danger">Lỗi: ${e.message}</td></tr>`;
            }
        }
        loadServices();
        setInterval(loadServices, 30000);
    </script>
</body>
</html>''')

    # admin_api_keys.html
    with open(templates_dir / 'admin_api_keys.html', 'w', encoding='utf-8') as f:
        f.write('''<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>API Keys - Zefoy API</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        body { background: #0d1117; color: #c9d1d9; }
        .navbar { background: #161b22 !important; border-bottom: 1px solid #30363d; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; }
        .card-header { background: transparent; border-bottom: 1px solid #30363d; }
        .sidebar { min-height: 100vh; border-right: 1px solid #30363d; }
        .nav-link { color: #8b949e; padding: 12px 20px; border-radius: 8px; }
        .nav-link:hover, .nav-link.active { color: #c9d1d9; background: #21262d; }
        .nav-link i { margin-right: 10px; width: 20px; }
        .form-control { background: #0d1117; border: 1px solid #30363d; color: #c9d1d9; }
        .form-control:focus { background: #0d1117; border-color: #58a6ff; color: #c9d1d9; }
        .btn-primary { background: #238636; border: none; }
        .btn-primary:hover { background: #2ea043; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg sticky-top">
        <div class="container-fluid">
            <a class="navbar-brand text-white fw-bold" href="/admin">
                <i class="bi bi-shield-lock"></i> Zefoy Admin
            </a>
            <div class="ms-auto">
                <a href="/admin/logout" class="btn btn-secondary btn-sm">
                    <i class="bi bi-box-arrow-right"></i> Đăng xuất
                </a>
            </div>
        </div>
    </nav>

    <div class="container-fluid">
        <div class="row">
            <div class="col-md-2 sidebar pt-3">
                <nav class="nav flex-column">
                    <a class="nav-link" href="/admin">
                        <i class="bi bi-speedometer2"></i> Dashboard
                    </a>
                    <a class="nav-link" href="/admin/services">
                        <i class="bi bi-list-ul"></i> Dịch vụ
                    </a>
                    <a class="nav-link active" href="/admin/api-keys">
                        <i class="bi bi-key"></i> API Keys
                    </a>
                    <a class="nav-link" href="/admin/settings">
                        <i class="bi bi-gear"></i> Cài đặt
                    </a>
                    <hr class="border-secondary">
                    <a class="nav-link" href="/">
                        <i class="bi bi-house"></i> Trang chủ
                    </a>
                </nav>
            </div>
            <div class="col-md-10 pt-4">
                <h4><i class="bi bi-key"></i> Quản lý API Keys</h4>
                <p class="text-muted">Tạo và quản lý API keys cho phép truy cập</p>

                <div class="card mb-3">
                    <div class="card-header">
                        <i class="bi bi-plus-circle"></i> Tạo API Key mới
                    </div>
                    <div class="card-body">
                        <div class="row g-3">
                            <div class="col-md-6">
                                <input type="text" class="form-control" placeholder="Tên API Key" id="apiKeyName">
                            </div>
                            <div class="col-md-4">
                                <select class="form-select" id="apiKeyRole">
                                    <option value="user">User</option>
                                    <option value="admin">Admin</option>
                                </select>
                            </div>
                            <div class="col-md-2">
                                <button class="btn btn-primary w-100" onclick="createApiKey()">
                                    <i class="bi bi-plus"></i> Tạo
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header">
                        <i class="bi bi-list"></i> Danh sách API Keys
                    </div>
                    <div class="card-body">
                        <div class="text-muted" id="apiKeyList">
                            <div class="alert alert-info bg-dark-card border-secondary text-muted">
                                <i class="bi bi-info-circle"></i> Chức năng đang phát triển. 
                                Sử dụng username/password admin để xác thực.
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        function createApiKey() {
            alert('Tính năng đang phát triển. Vui lòng sử dụng đăng nhập admin.');
        }
    </script>
</body>
</html>''')

    # admin_settings.html
    with open(templates_dir / 'admin_settings.html', 'w', encoding='utf-8') as f:
        f.write('''<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cài đặt - Zefoy API</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        body { background: #0d1117; color: #c9d1d9; }
        .navbar { background: #161b22 !important; border-bottom: 1px solid #30363d; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; }
        .card-header { background: transparent; border-bottom: 1px solid #30363d; }
        .sidebar { min-height: 100vh; border-right: 1px solid #30363d; }
        .nav-link { color: #8b949e; padding: 12px 20px; border-radius: 8px; }
        .nav-link:hover, .nav-link.active { color: #c9d1d9; background: #21262d; }
        .nav-link i { margin-right: 10px; width: 20px; }
        .form-control { background: #0d1117; border: 1px solid #30363d; color: #c9d1d9; }
        .form-control:focus { background: #0d1117; border-color: #58a6ff; color: #c9d1d9; }
        .btn-primary { background: #238636; border: none; }
        .btn-primary:hover { background: #2ea043; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg sticky-top">
        <div class="container-fluid">
            <a class="navbar-brand text-white fw-bold" href="/admin">
                <i class="bi bi-shield-lock"></i> Zefoy Admin
            </a>
            <div class="ms-auto">
                <a href="/admin/logout" class="btn btn-secondary btn-sm">
                    <i class="bi bi-box-arrow-right"></i> Đăng xuất
                </a>
            </div>
        </div>
    </nav>

    <div class="container-fluid">
        <div class="row">
            <div class="col-md-2 sidebar pt-3">
                <nav class="nav flex-column">
                    <a class="nav-link" href="/admin">
                        <i class="bi bi-speedometer2"></i> Dashboard
                    </a>
                    <a class="nav-link" href="/admin/services">
                        <i class="bi bi-list-ul"></i> Dịch vụ
                    </a>
                    <a class="nav-link" href="/admin/api-keys">
                        <i class="bi bi-key"></i> API Keys
                    </a>
                    <a class="nav-link active" href="/admin/settings">
                        <i class="bi bi-gear"></i> Cài đặt
                    </a>
                    <hr class="border-secondary">
                    <a class="nav-link" href="/">
                        <i class="bi bi-house"></i> Trang chủ
                    </a>
                </nav>
            </div>
            <div class="col-md-10 pt-4">
                <h4><i class="bi bi-gear"></i> Cài đặt</h4>
                <p class="text-muted">Cấu hình hệ thống</p>

                <div class="card mb-3">
                    <div class="card-header">🔐 Bảo mật</div>
                    <div class="card-body">
                        <div class="row g-3">
                            <div class="col-md-6">
                                <label class="form-label small text-muted">Admin Username</label>
                                <input type="text" class="form-control" value="admin" readonly>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label small text-muted">Thay đổi mật khẩu</label>
                                <div class="input-group">
                                    <input type="password" class="form-control" placeholder="Mật khẩu mới" id="newPassword">
                                    <button class="btn btn-secondary" onclick="changePassword()">Cập nhật</button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header">⚙️ Cấu hình hệ thống</div>
                    <div class="card-body">
                        <div class="row g-3">
                            <div class="col-md-6">
                                <label class="form-label small text-muted">Session Timeout (giây)</label>
                                <input type="number" class="form-control" value="3600" readonly>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label small text-muted">Max Attempts</label>
                                <input type="number" class="form-control" value="3" readonly>
                            </div>
                            <div class="col-12">
                                <div class="alert alert-info bg-dark-card border-secondary text-muted">
                                    <i class="bi bi-info-circle"></i> Các thay đổi sẽ áp dụng sau khi restart
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        function changePassword() {
            alert('Tính năng đang phát triển. Vui lòng set biến môi trường ADMIN_PASSWORD');
        }
    </script>
</body>
</html>''')

def create_render_yaml():
    """Tạo file render.yaml cho deploy"""
    render_yaml = ROOT / 'render.yaml'
    content = '''services:
  - type: web
    name: zefoy-api
    runtime: python
    plan: starter
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn main:app --timeout 120 --workers 2
    envVars:
      - key: ADMIN_USERNAME
        value: admin
      - key: ADMIN_PASSWORD
        value: zefoy2026
      - key: SECRET_KEY
        generateValue: true
      - key: PYTHON_VERSION
        value: 3.10.0
    healthCheckPath: /api/status
'''
    with open(render_yaml, 'w', encoding='utf-8') as f:
        f.write(content)

# ==================== MAIN ====================

if __name__ == '__main__':
    # Tạo các file cần thiết
    create_requirements()
    create_templates()
    create_render_yaml()
    
    # Các biến môi trường
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    print("=" * 50)
    print("🚀 ZEFOY API SERVER")
    print("=" * 50)
    print(f"📍 Port: {port}")
    print(f"🔧 Debug: {debug}")
    print(f"👤 Admin: {ADMIN_USERNAME}")
    print(f"🔑 Admin Password: {ADMIN_PASSWORD}")
    print("=" * 50)
    print("📂 API Endpoints:")
    print("  GET  /api/captcha   - Lấy captcha")
    print("  POST /api/solve     - Giải captcha + đăng nhập")
    print("  POST /api/submit    - Gửi service")
    print("  GET  /api/services  - Danh sách dịch vụ")
    print("  GET  /api/status    - Trạng thái")
    print("  GET  /admin         - Admin dashboard")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=port, debug=debug, threaded=True)
