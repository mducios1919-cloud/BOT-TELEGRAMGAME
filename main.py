from flask import Flask, request, jsonify
from flask_cors import CORS
import base64
import hashlib
import time
import requests
import re
import os
import json
from bs4 import BeautifulSoup

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
        self.total_sent = 0
    
    def submit_and_get_services(self, answer):
        try:
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import pad
            
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
            if body != 'success':
                return None
            
            return self.get_services()
            
        except Exception as e:
            print(f"Submit error: {e}")
            return None
    
    def get_services(self):
        """Lấy danh sách services - DÙNG BEAUTIFULSOUP GIỐNG PYTHON GỐC"""
        try:
            resp = self.session.get(self.base_url, headers={
                'User-Agent': self.user_agent,
                'Referer': f"{self.base_url}/",
            }, timeout=30)
            
            html = resp.text
            soup = BeautifulSoup(html, 'html.parser')
            
            services = []
            service_titles = []
            
            # Tìm các card service
            for card in soup.find_all('div', class_='card'):
                title_el = card.find(['h5', 'h6', 'div'], class_=['card-title', 'mb-3'])
                if not title_el:
                    continue
                
                title = title_el.get_text(strip=True)
                if not title or len(title) < 3:
                    continue
                
                # Lấy status
                status_el = card.find('small')
                if not status_el:
                    status_el = card.find('p', class_='card-text')
                status = status_el.get_text(strip=True) if status_el else 'Online'
                
                # Lấy action URL và input name từ form
                form = card.find('form')
                action = form.get('action') if form else None
                input_name = None
                if form:
                    inp = form.find('input', {'type': 'text'})
                    if inp:
                        input_name = inp.get('name')
                
                # Xác định online
                status_lower = status.lower()
                online = True
                if 'soon' in status_lower or 'update' in status_lower or 'offline' in status_lower:
                    online = False
                if 'ago' in status_lower and 'updated' in status_lower:
                    online = True
                
                # Lưu vào service_titles để tránh trùng
                if title not in service_titles:
                    service_titles.append(title)
                    services.append({
                        'title': title,
                        'status': status or 'Online',
                        'available': online,
                        'action': action,
                        'input_name': input_name
                    })
            
            # Lọc bỏ fake services
            fake_keywords = ['terms', 'privacy', 'contact', 'policy', 'cookie', 'about']
            real_services = []
            for s in services:
                title_lower = s['title'].lower()
                is_fake = any(kw in title_lower for kw in fake_keywords)
                if not is_fake:
                    real_services.append(s)
            
            print(f"✅ Đã tìm thấy {len(real_services)} services")
            for s in real_services:
                print(f"   - {s['title']}: {'Online' if s['available'] else 'Offline'}")
            
            return real_services
            
        except Exception as e:
            print(f"Get services error: {e}")
            return []
    
    def _parse_timer(self, html):
        """Lấy timer từ response"""
        if not html:
            return None
        m = re.search(r'remainingTimelogin\s*=\s*(-?\d+)', html)
        if m:
            v = int(m.group(1))
            return v if v > 0 else None
        m = re.search(r'Please wait\s+(\d+)\s+seconds', html, re.I)
        if m:
            v = int(m.group(1))
            return v if v > 0 else None
        return None
    
    def _parse_sent_amount(self, html):
        """Lấy số lượng đã gửi"""
        if not html:
            return None, None, None
        m = re.search(r'Successfully\s+(\d+)\s*([a-zA-Z ]*?)\s*sent\.?', html, re.I)
        if m:
            amount = int(m.group(1))
            kind = (m.group(2) or '').strip().lower() or 'items'
            msg = re.sub(r'\s+', ' ', m.group(0)).strip()
            return amount, kind, msg
        m = re.search(r'(\d+)\s*(views?|hearts?|likes?|shares?|followers?|favorites?)\s*sent', html, re.I)
        if m:
            return int(m.group(1)), m.group(2).lower(), m.group(0).strip()
        return None, None, None
    
    def run_service(self, service_title, video_url):
        """Chạy dịch vụ tăng tương tác"""
        try:
            # Lấy danh sách services với action
            services = self.get_services()
            
            # Tìm service cần chạy
            target = None
            for s in services:
                if s['title'].lower() == service_title.lower():
                    target = s
                    break
            
            if not target:
                return {'success': False, 'message': f'Không tìm thấy service: {service_title}'}
            
            if not target['available']:
                return {'success': False, 'message': f'Service {service_title} đang offline'}
            
            if not target['action'] or not target['input_name']:
                return {'success': False, 'message': f'Không tìm thấy action cho service {service_title}'}
            
            # Gửi request
            action_url = target['action']
            if not action_url.startswith('http'):
                action_url = f"{self.base_url}{action_url.lstrip('/')}"
            
            data = {target['input_name']: video_url}
            
            resp = self.session.post(action_url, data=data, headers={
                'User-Agent': self.user_agent,
                'Origin': self.base_url,
                'Referer': f"{self.base_url}/",
                'Accept': '*/*',
            }, timeout=30)
            
            response_text = resp.text
            
            # Kiểm tra kết quả
            if 'Session expired' in response_text:
                return {'success': False, 'message': '⚠️ Session expired, cần lấy CAPTCHA lại'}
            
            # Kiểm tra timer
            wait = self._parse_timer(response_text)
            if wait and wait > 0:
                return {'success': False, 'message': f'⏳ Vui lòng chờ {wait} giây...'}
            
            # Kiểm tra số lượng đã gửi
            amount, kind, sent_msg = self._parse_sent_amount(response_text)
            if amount is not None:
                self.total_sent += amount
                return {
                    'success': True, 
                    'message': f'✅ {sent_msg}  |  Total: {self.total_sent}'
                }
            
            # Kiểm tra các thông báo khác
            if 'success' in response_text.lower():
                return {'success': True, 'message': f'✅ Đã tăng {service_title} thành công!'}
            
            if 'Too many requests' in response_text:
                return {'success': False, 'message': '⚠️ Too many requests, vui lòng chờ...'}
            
            if 'service is currently not working' in response_text.lower():
                return {'success': False, 'message': f'❌ Service {service_title} đang bảo trì'}
            
            # Thử parse message từ HTML
            m = re.search(r"color:\s*green;?'?[^>]*>\s*([^<]+)", response_text, re.I)
            if m and 'Checking Timer' not in m.group(1):
                return {'success': True, 'message': f'✅ {m.group(1).strip()}'}
            
            return {'success': False, 'message': f'❌ Lỗi không xác định: {response_text[:100]}'}
            
        except Exception as e:
            return {'success': False, 'message': str(e)}

# ==================== CACHE ====================
captcha_cache = {}

# ==================== ROUTES ====================
@app.route('/')
def index():
    return jsonify({'status': 'ok', 'message': 'Zefoy API Running - Full Version'})

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
        print(f"❌ Lỗi submit: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/run_service', methods=['POST'])
def run_service():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Không có dữ liệu'})
        
        service_title = data.get('service', '')
        video_url = data.get('video_url', '')
        
        if not service_title:
            return jsonify({'success': False, 'message': 'Vui lòng chọn dịch vụ'})
        if not video_url:
            return jsonify({'success': False, 'message': 'Vui lòng nhập link video'})
        
        print(f"🔄 Chạy service: {service_title} - Video: {video_url}")
        
        # Tạo client với session đã có
        client = ZefoyClient()
        if 'cookies' in captcha_cache:
            for name, value in captcha_cache['cookies'].items():
                client.session.cookies.set(name, value)
        
        result = client.run_service(service_title, video_url)
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ Lỗi run_service: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

# ==================== MAIN ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
