from flask import Flask, request, jsonify
from flask_cors import CORS
import base64
import hashlib
import time
import requests
import re
import os
import json

app = Flask(__name__)
CORS(app)

# ==================== CLASS ZEFOY CAPTCHA ====================
class ZefoyCaptcha:
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.base_url = "https://zefoy.com"
    
    def get(self):
        # GET / để lấy session
        self.session.get(self.base_url, timeout=30)
        
        # GET CAPTCHA
        ts = int(time.time())
        url = f"{self.base_url}/?getcapthca={ts}"
        resp = self.session.get(url, headers={
            'Accept': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            'User-Agent': self.user_agent
        }, timeout=30)
        
        data = resp.json()
        md5 = hashlib.md5(self.user_agent.encode()).hexdigest()
        encoded = data.get(md5)
        if not encoded:
            encoded = list(data.values())[0]
        
        # Double base64 decode
        once = base64.b64decode(encoded)
        path = base64.b64decode(once).decode().strip()
        image_url = f"{self.base_url}/{path.lstrip('/')}"
        img_resp = self.session.get(image_url, headers={'User-Agent': self.user_agent}, timeout=30)
        
        class Result: pass
        r = Result()
        r.image_bytes = img_resp.content
        r.image_url = image_url
        r.session_id = self.session.cookies.get('PHPSESSID')
        return r

# ==================== CLASS ZEFOY CLIENT ====================
class ZefoyClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.base_url = "https://zefoy.com"
    
    def submit_and_get_services(self, answer):
        try:
            # Thử import Crypto, nếu ko có thì báo lỗi
            try:
                from Crypto.Cipher import AES
                from Crypto.Util.Padding import pad
            except ImportError:
                return None
            
            # Fingerprint
            fingerprint = {
                'deviceInfo': {'cpuCores': 8, 'platform': 'Win32'},
                'browserInfo': {'userAgent': self.user_agent, 'language': 'en'},
                'screenInfo': {'width': 1920, 'height': 1080}
            }
            
            # AES encrypt
            passphrase = "43fdda1192dde7f8ffff7161e13580d7"
            salt = os.urandom(8)
            
            derived = b''
            block = b''
            while len(derived) < 48:
                block = hashlib.md5(block + passphrase.encode() + salt).digest()
                derived += block
            
            key = derived[:32]
            iv = derived[32:48]
            
            cipher = AES.new(key, AES.MODE_CBC, iv)
            data_bytes = json.dumps(fingerprint).encode()
            encrypted = cipher.encrypt(pad(data_bytes, AES.block_size))
            
            captcha_encoded = json.dumps({
                'ct': base64.b64encode(encrypted).decode(),
                'iv': iv.hex(),
                's': salt.hex()
            })
            
            # Submit CAPTCHA
            data = {
                'captchalogin': answer,
                'captcha_encoded': captcha_encoded
            }
            
            resp = self.session.post(self.base_url, data=data, headers={
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest',
                'User-Agent': self.user_agent,
                'Origin': self.base_url,
                'Referer': f"{self.base_url}/",
            }, timeout=30, allow_redirects=False)
            
            body = resp.text.strip().lower()
            if body != 'success':
                return None
            
            # Lấy services
            return self.get_services()
            
        except Exception as e:
            print(f"Submit error: {e}")
            return None
    
    def get_services(self):
        try:
            resp = self.session.get(self.base_url, headers={
                'User-Agent': self.user_agent,
                'Referer': f"{self.base_url}/",
            }, timeout=30)
            
            html = resp.text
            services = []
            
            # Parse services
            titles = re.findall(r'<h5[^>]*>([^<]+)</h5>', html)
            statuses = re.findall(r'<small[^>]*>([^<]*)</small>', html)
            
            for i, title in enumerate(titles):
                title = title.strip()
                if not title or len(title) < 3:
                    continue
                status = statuses[i].strip() if i < len(statuses) else 'Online'
                available = not ('soon' in status.lower() or 'update' in status.lower() or 'offline' in status.lower())
                services.append({
                    'title': title,
                    'status': status or 'Online',
                    'available': available
                })
            
            # Loại trùng
            seen = set()
            unique = []
            for s in services:
                if s['title'] not in seen:
                    seen.add(s['title'])
                    unique.append(s)
            
            return unique
            
        except Exception as e:
            print(f"Get services error: {e}")
            return []

# ==================== CACHE ====================
captcha_cache = {}

# ==================== ROUTES ====================
@app.route('/')
def index():
    return jsonify({'status': 'ok', 'message': 'Zefoy API Running'})

@app.route('/get_captcha')
def get_captcha():
    try:
        client = ZefoyCaptcha()
        captcha = client.get()
        
        captcha_cache['image'] = captcha.image_bytes
        captcha_cache['cookies'] = client.session.cookies.get_dict()
        
        return jsonify({
            'success': True,
            'captcha': {
                'image_base64': base64.b64encode(captcha.image_bytes).decode('ascii'),
                'session_id': captcha.session_id,
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/submit_manual', methods=['POST'])
def submit_manual():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Không có dữ liệu'})
        
        answer = data.get('answer', '').strip()
        answer = re.sub(r'[^a-zA-Z]', '', answer).lower()
        
        if not answer:
            return jsonify({'success': False, 'message': 'Vui lòng nhập CAPTCHA'})
        
        print(f"🔄 Submit CAPTCHA: {answer}")
        
        client = ZefoyClient()
        if 'cookies' in captcha_cache:
            for name, value in captcha_cache['cookies'].items():
                client.session.cookies.set(name, value)
        
        services = client.submit_and_get_services(answer)
        
        if services is not None and len(services) > 0:
            online_count = sum(1 for s in services if s['available'])
            return jsonify({
                'success': True,
                'message': f'✅ CAPTCHA đúng! Tìm thấy {online_count} dịch vụ online.',
                'data': {
                    'answer': answer,
                    'session_id': client.session.cookies.get('PHPSESSID'),
                    'services': services
                }
            })
        else:
            return jsonify({
                'success': False,
                'message': '❌ CAPTCHA sai hoặc không lấy được services. Thử lại!'
            })
            
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

# ==================== MAIN ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
