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

# ==================== CONFIG ====================
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
BASE_URL = "https://zefoy.com"
PASSPHRASE = "43fdda1192dde7f8ffff7161e13580d7"

# ==================== CLASS ZEFOY CAPTCHA ====================
class ZefoyCaptcha:
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.user_agent = USER_AGENT
        self.base_url = BASE_URL
    
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
        self.user_agent = USER_AGENT
        self.base_url = BASE_URL
        self.total_sent = 0
    
    def submit_captcha(self, answer):
        try:
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import pad
            
            fingerprint = {
                'deviceInfo': {'cpuCores': 8, 'platform': 'Win32'},
                'browserInfo': {'userAgent': self.user_agent, 'language': 'en'},
                'screenInfo': {'width': 1920, 'height': 1080}
            }
            
            salt = os.urandom(8)
            derived = b''
            block = b''
            while len(derived) < 48:
                block = hashlib.md5(block + PASSPHRASE.encode() + salt).digest()
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
            
            if resp.text.strip().lower() == 'success':
                return self.get_services()
            return None
            
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
            soup = BeautifulSoup(html, 'html.parser')
            
            REAL_SERVICES = [
                'Followers', 'Hearts', 'Comments Hearts', 'Views',
                'Shares', 'Favorites', 'Live Stream', 'Repost'
            ]
            
            services = []
            service_titles = []
            
            for card in soup.find_all('div', class_='card'):
                title_el = card.find(['h5', 'h6'], class_=['card-title', 'mb-3'])
                if not title_el:
                    title_el = card.find('h5')
                if not title_el:
                    continue
                
                title = title_el.get_text(strip=True)
                if not title or len(title) < 3:
                    continue
                
                is_real = False
                for real in REAL_SERVICES:
                    if real.lower() in title.lower() or title.lower() in real.lower():
                        is_real = True
                        break
                
                if not is_real:
                    continue
                
                status_el = card.find('small')
                if not status_el:
                    status_el = card.find('p', class_='card-text')
                status = status_el.get_text(strip=True) if status_el else 'Online'
                
                form = card.find('form')
                action = None
                input_name = None
                
                if form:
                    action = form.get('action')
                    inp = form.find('input', {'type': 'text'})
                    if inp:
                        input_name = inp.get('name')
                
                status_lower = status.lower()
                online = True
                if 'soon' in status_lower or 'update' in status_lower or 'offline' in status_lower:
                    online = False
                if 'ago' in status_lower and 'updated' in status_lower:
                    online = True
                
                if title not in service_titles:
                    service_titles.append(title)
                    services.append({
                        'title': title,
                        'status': status or 'Online',
                        'available': online,
                        'action': action,
                        'input_name': input_name
                    })
            
            print(f"✅ Tìm thấy {len(services)} services")
            for s in services:
                print(f"   - {s['title']}: online={s['available']}, action={s['action']}")
            
            return services
            
        except Exception as e:
            print(f"Get services error: {e}")
            return []
    
    def _parse_timer(self, html):
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
        if not html:
            return None, None, None
        m = re.search(r'Successfully\s+(\d+)\s*([a-zA-Z ]*?)\s*sent\.?', html, re.I)
        if m:
            amount = int(m.group(1))
            kind = (m.group(2) or '').strip().lower() or 'items'
            msg = re.sub(r'\s+', ' ', m.group(0)).strip()
            return amount, kind, msg
        return None, None, None
    
    def run_service(self, service_title, video_url):
        try:
            services = self.get_services()
            
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
            
            action = target['action']
            if action.startswith('/'):
                action_url = self.base_url.rstrip('/') + action
            elif action.startswith('http'):
                action_url = action
            else:
                action_url = self.base_url.rstrip('/') + '/' + action.lstrip('/')
            
            data = {target['input_name']: video_url}
            
            resp = self.session.post(action_url, data=data, headers={
                'User-Agent': self.user_agent,
                'Origin': self.base_url,
                'Referer': f"{self.base_url}/",
                'Accept': '*/*',
            }, timeout=30)
            
            response_text = resp.text
            
            if 'Session expired' in response_text:
                return {'success': False, 'message': '⚠️ Session expired, cần lấy CAPTCHA lại'}
            
            wait = self._parse_timer(response_text)
            if wait and wait > 0:
                return {'success': False, 'message': f'⏳ Vui lòng chờ {wait} giây...'}
            
            amount, kind, sent_msg = self._parse_sent_amount(response_text)
            if amount is not None:
                self.total_sent += amount
                return {
                    'success': True,
                    'message': f'✅ {sent_msg}  |  Total: {self.total_sent}'
                }
            
            if 'success' in response_text.lower():
                return {'success': True, 'message': f'✅ Đã tăng {service_title} thành công!'}
            
            if 'Too many requests' in response_text:
                return {'success': False, 'message': '⚠️ Too many requests, vui lòng chờ...'}
            
            if 'service is currently not working' in response_text.lower():
                return {'success': False, 'message': f'❌ Service {service_title} đang bảo trì'}
            
            m = re.search(r"color:\s*green;?'?[^>]*>\s*([^<]+)", response_text, re.I)
            if m and 'Checking Timer' not in m.group(1):
                return {'success': True, 'message': f'✅ {m.group(1).strip()}'}
            
            return {'success': False, 'message': f'❌ Lỗi: {response_text[:100]}'}
            
        except Exception as e:
            return {'success': False, 'message': str(e)}

# ==================== CACHE ====================
cache = {
    'cookies': None,
    'services': None,
    'session_id': None
}

# ==================== API ROUTES ====================
@app.route('/')
def index():
    return jsonify({
        'status': 'ok',
        'message': 'Zefoy API v2.0',
        'endpoints': {
            '/get_captcha': 'GET - Lấy CAPTCHA',
            '/submit': 'POST - Submit CAPTCHA (body: {"answer":"..."})',
            '/services': 'GET - Lấy danh sách services',
            '/run': 'POST - Chạy service (body: {"service":"Views","video_url":"..."})',
            '/health': 'GET - Kiểm tra status'
        }
    })

@app.route('/get_captcha')
def get_captcha():
    try:
        client = ZefoyCaptcha()
        captcha = client.get()
        
        cache['cookies'] = client.session.cookies.get_dict()
        
        return jsonify({
            'success': True,
            'data': {
                'image_base64': base64.b64encode(captcha.image_bytes).decode('ascii'),
                'session_id': captcha.session_id
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/submit', methods=['POST'])
def submit():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Missing data'})
        
        answer = data.get('answer', '').strip()
        answer = re.sub(r'[^a-zA-Z]', '', answer).lower()
        
        if not answer:
            return jsonify({'success': False, 'message': 'Vui lòng nhập CAPTCHA'})
        
        print(f"🔄 Submit CAPTCHA: {answer}")
        
        client = ZefoyClient()
        if cache.get('cookies'):
            for name, value in cache['cookies'].items():
                client.session.cookies.set(name, value)
        
        services = client.submit_captcha(answer)
        
        if services:
            cache['services'] = services
            cache['session_id'] = client.session.cookies.get('PHPSESSID')
            
            online = sum(1 for s in services if s['available'])
            return jsonify({
                'success': True,
                'message': f'✅ CAPTCHA đúng! {online} services online',
                'data': {
                    'session_id': cache['session_id'],
                    'services': services
                }
            })
        
        return jsonify({'success': False, 'message': '❌ CAPTCHA sai!'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/services')
def get_services():
    try:
        if not cache.get('services'):
            client = ZefoyClient()
            if cache.get('cookies'):
                for name, value in cache['cookies'].items():
                    client.session.cookies.set(name, value)
            services = client.get_services()
            cache['services'] = services
        else:
            services = cache['services']
        
        return jsonify({
            'success': True,
            'data': {
                'services': services,
                'session_id': cache.get('session_id')
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/run', methods=['POST'])
def run():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Missing data'})
        
        service_title = data.get('service', '')
        video_url = data.get('video_url', '')
        
        if not service_title:
            return jsonify({'success': False, 'message': 'Vui lòng chọn dịch vụ'})
        if not video_url:
            return jsonify({'success': False, 'message': 'Vui lòng nhập link video'})
        
        print(f"🔄 Chạy service: {service_title} - Video: {video_url}")
        
        client = ZefoyClient()
        if cache.get('cookies'):
            for name, value in cache['cookies'].items():
                client.session.cookies.set(name, value)
        
        result = client.run_service(service_title, video_url)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

# ==================== MAIN ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
