from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import base64
import sys
import os
import io
import requests
import re
import hashlib
import time
import json

sys.path.insert(0, os.path.dirname(__file__))

# Import zefoy - nếu có thì dùng, không thì tự viết
try:
    from zefoy import ZefoyCaptcha, ZefoyClient
    print("✅ Import zefoy thành công!")
except Exception as e:
    print(f"❌ Lỗi import: {e}")
    # Tự viết class zefoy
    class ZefoyCaptcha:
        def __init__(self):
            self.session = requests.Session()
            self.session.verify = False
            self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            self.base_url = "https://zefoy.com"
        
        def get(self):
            self.session.get(self.base_url, timeout=30)
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
            
            once = base64.b64decode(encoded)
            path = base64.b64decode(once).decode().strip()
            image_url = f"{self.base_url}/{path.lstrip('/')}"
            img_resp = self.session.get(image_url, headers={'User-Agent': self.user_agent}, timeout=30)
            
            token = None
            if '_CAPTCHA=' in path:
                token = path.split('_CAPTCHA=')[1].split('&')[0]
            
            class Result: pass
            r = Result()
            r.image_bytes = img_resp.content
            r.image_url = image_url
            r.captcha_token = token
            r.session_id = self.session.cookies.get('PHPSESSID')
            return r
    
    class ZefoyClient:
        def __init__(self):
            self.session = requests.Session()
            self.session.verify = False
            self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            self.base_url = "https://zefoy.com"
        
        def submit_captcha(self, answer):
            """Submit CAPTCHA và lấy services"""
            try:
                from Crypto.Cipher import AES
                from Crypto.Util.Padding import pad
                
                # Tạo fingerprint
                fingerprint = {
                    'deviceInfo': {'cpuCores': 8, 'platform': 'Win32'},
                    'browserInfo': {'userAgent': self.user_agent, 'language': 'en'},
                    'screenInfo': {'width': 1920, 'height': 1080}
                }
                
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
                if body == 'success':
                    # Lấy services sau khi submit thành công
                    return self.get_services()
                return None
                
            except Exception as e:
                print(f"Submit error: {e}")
                return None
        
        def get_services(self):
            """Lấy danh sách services từ panel"""
            try:
                # GET / để lấy panel HTML
                resp = self.session.get(self.base_url, headers={
                    'User-Agent': self.user_agent,
                    'Referer': f"{self.base_url}/",
                }, timeout=30)
                
                html = resp.text
                services = []
                
                # Parse services từ HTML
                pattern = r'<h5[^>]*>([^<]+)</h5>\s*<small[^>]*>([^<]*)</small>'
                matches = re.findall(pattern, html)
                
                if not matches:
                    # Thử pattern khác
                    pattern = r'<h5[^>]*class="[^"]*card-title[^"]*"[^>]*>([^<]+)</h5>[\s\S]*?<p[^>]*class="[^"]*card-text[^"]*"[^>]*>([^<]*)</p>'
                    matches = re.findall(pattern, html)
                
                # Nếu vẫn không có, thử parse trực tiếp
                if not matches:
                    # Tìm tất cả các service title
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
                else:
                    for title, status in matches:
                        title = title.strip()
                        status = status.strip()
                        if not title or len(title) < 3:
                            continue
                        available = not ('soon' in status.lower() or 'update' in status.lower() or 'offline' in status.lower())
                        services.append({
                            'title': title,
                            'status': status or 'Online',
                            'available': available
                        })
                
                # Loại bỏ trùng lặp
                seen = set()
                unique_services = []
                for s in services:
                    if s['title'] not in seen:
                        seen.add(s['title'])
                        unique_services.append(s)
                
                print(f"✅ Đã tìm thấy {len(unique_services)} services")
                for s in unique_services:
                    print(f"   - {s['title']}: {'Online' if s['available'] else 'Offline'}")
                
                return unique_services
                
            except Exception as e:
                print(f"Get services error: {e}")
                return []

app = Flask(__name__)
CORS(app)

captcha_cache = {}

@app.route('/')
def index():
    return jsonify({'status': 'ok', 'message': 'Zefoy API'})

@app.route('/get_captcha')
def get_captcha():
    try:
        client = ZefoyCaptcha()
        captcha = client.get()
        
        captcha_cache['image'] = captcha.image_bytes
        captcha_cache['session_id'] = captcha.session_id
        captcha_cache['cookies'] = client.session.cookies.get_dict()
        
        return jsonify({
            'success': True,
            'captcha': {
                'image_base64': base64.b64encode(captcha.image_bytes).decode('ascii'),
                'session_id': captcha.session_id,
                'captcha_token': captcha.captcha_token,
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/submit_manual', methods=['POST'])
def submit_manual():
    try:
        data = request.get_json()
        answer = data.get('answer', '').strip()
        answer = re.sub(r'[^a-zA-Z]', '', answer).lower()
        
        if not answer:
            return jsonify({'success': False, 'message': 'Vui lòng nhập CAPTCHA'})
        
        print(f"🔄 Submit CAPTCHA: {answer}")
        
        # Tạo client với session đã có
        client = ZefoyClient()
        if 'cookies' in captcha_cache:
            for name, value in captcha_cache['cookies'].items():
                client.session.cookies.set(name, value)
        
        # Submit và lấy services
        services = client.submit_captcha(answer)
        
        if services is not None:
            # Lấy session ID mới
            session_id = client.session.cookies.get('PHPSESSID')
            
            # Đếm số services online
            online_count = sum(1 for s in services if s['available'])
            
            return jsonify({
                'success': True,
                'message': f'✅ CAPTCHA đúng! Tìm thấy {online_count} dịch vụ online.',
                'data': {
                    'answer': answer,
                    'session_id': session_id,
                    'services': services
                }
            })
        else:
            return jsonify({
                'success': False,
                'message': '❌ CAPTCHA sai hoặc hết hạn. Thử lại!'
            })
            
    except Exception as e:
        print(f"❌ Lỗi submit: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
