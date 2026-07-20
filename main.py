from flask import Flask, request, jsonify
from flask_cors import CORS
import base64, hashlib, time, requests, re, os, json, urllib3
from bs4 import BeautifulSoup
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

app = Flask(__name__)
CORS(app)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
BASE_URL = "https://zefoy.com"
PASSPHRASE = "43fdda1192dde7f8ffff7161e13580d7"
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_session():
    """Tạo session với headers giống trình duyệt"""
    session = requests.Session()
    session.verify = False
    session.headers.update({
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
    })
    return session

class ZefoyCaptcha:
    def __init__(self):
        self.session = get_session()
        self.base_url = BASE_URL
    
    def get(self):
        # Lấy session cookie
        self.session.get(self.base_url, timeout=60)
        ts = int(time.time())
        resp = self.session.get(
            f"{self.base_url}/?getcapthca={ts}",
            headers={'Accept':'application/json','X-Requested-With':'XMLHttpRequest'},
            timeout=60
        )
        data = resp.json()
        md5 = hashlib.md5(USER_AGENT.encode()).hexdigest()
        encoded = data.get(md5) or list(data.values())[0]
        once = base64.b64decode(encoded)
        path = base64.b64decode(once).decode().strip()
        img_resp = self.session.get(
            f"{self.base_url}/{path.lstrip('/')}",
            timeout=60
        )
        class R: pass
        r = R()
        r.image_bytes = img_resp.content
        r.session_id = self.session.cookies.get('PHPSESSID')
        return r

class ZefoyClient:
    def __init__(self):
        self.session = get_session()
        self.base_url = BASE_URL
        self.total_sent = 0
        self.services_ids = {}
        self.services_input = {}
    
    def submit_captcha(self, answer):
        try:
            fingerprint = {'deviceInfo':{'cpuCores':8,'platform':'Win32'},'browserInfo':{'userAgent':USER_AGENT,'language':'en'},'screenInfo':{'width':1920,'height':1080}}
            salt = os.urandom(8)
            derived = b''; block = b''
            while len(derived) < 48:
                block = hashlib.md5(block + PASSPHRASE.encode() + salt).digest()
                derived += block
            key, iv = derived[:32], derived[32:48]
            cipher = AES.new(key, AES.MODE_CBC, iv)
            encrypted = cipher.encrypt(pad(json.dumps(fingerprint).encode(), AES.block_size))
            captcha_encoded = json.dumps({'ct':base64.b64encode(encrypted).decode(),'iv':iv.hex(),'s':salt.hex()})
            resp = self.session.post(
                self.base_url,
                data={'captchalogin':answer,'captcha_encoded':captcha_encoded},
                headers={
                    'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
                    'X-Requested-With':'XMLHttpRequest',
                    'Origin':self.base_url,
                    'Referer':f"{self.base_url}/"
                },
                timeout=60,
                allow_redirects=False
            )
            if resp.text.strip().lower() == 'success':
                return self.get_services()
            return None
        except Exception as e:
            print(f"Submit error: {e}")
            return None
    
    def get_services(self):
        try:
            resp = self.session.get(self.base_url, timeout=60)
            soup = BeautifulSoup(resp.text, 'html.parser')
            REAL = ['Followers','Hearts','Comments Hearts','Views','Shares','Favorites','Live Stream','Repost']
            services = []
            
            for card in soup.find_all('div', class_='card'):
                title_el = card.find(['h5','h6'], class_=['card-title','mb-3']) or card.find('h5')
                if not title_el: continue
                title = title_el.get_text(strip=True)
                if not title or len(title) < 3: continue
                
                is_real = False
                for r in REAL:
                    if r.lower() in title.lower() or title.lower() in r.lower():
                        is_real = True
                        break
                if not is_real: continue
                
                status_el = card.find('small') or card.find('p', class_='card-text')
                status = status_el.get_text(strip=True) if status_el else 'Online'
                
                form = card.find('form')
                action = None
                input_name = None
                if form:
                    action = form.get('action')
                    inp = form.find('input', {'type':'text'})
                    if inp:
                        input_name = inp.get('name')
                    if not input_name:
                        for inp in form.find_all('input'):
                            if inp.get('type') != 'hidden' and inp.get('name'):
                                input_name = inp.get('name')
                                break
                
                if action:
                    self.services_ids[title] = action
                if input_name:
                    self.services_input[title] = input_name
                
                online = True
                if 'soon' in status.lower() or 'update' in status.lower() or 'offline' in status.lower():
                    online = False
                if 'ago' in status.lower() and 'updated' in status.lower():
                    online = True
                
                services.append({
                    'title': title,
                    'status': status or 'Online',
                    'available': online,
                    'action': action,
                    'input_name': input_name
                })
            
            print(f"✅ Đã tìm thấy {len(services)} services")
            return services
            
        except Exception as e:
            print(f"Get services error: {e}")
            return []
    
    def _parse_timer(self, html):
        if not html: return None
        m = re.search(r'remainingTimelogin\s*=\s*(-?\d+)', html)
        if m: v = int(m.group(1)); return v if v > 0 else None
        m = re.search(r'Please wait\s+(\d+)\s+seconds', html, re.I)
        if m: v = int(m.group(1)); return v if v > 0 else None
        return None
    
    def _parse_sent_amount(self, html):
        if not html: return None,None,None
        m = re.search(r'Successfully\s+(\d+)\s*([a-zA-Z ]*?)\s*sent\.?', html, re.I)
        if m:
            amount = int(m.group(1)); kind = (m.group(2) or '').strip().lower() or 'items'
            msg = re.sub(r'\s+', ' ', m.group(0)).strip()
            return amount, kind, msg
        return None,None,None
    
    def run_service(self, service_title, video_url):
        try:
            action = self.services_ids.get(service_title)
            input_name = self.services_input.get(service_title)
            
            if not action:
                print(f"⚠️ Không tìm thấy action cho {service_title}")
                services = self.get_services()
                for s in services:
                    if s['title'] == service_title:
                        action = s.get('action')
                        input_name = s.get('input_name')
                        if action: self.services_ids[service_title] = action
                        if input_name: self.services_input[service_title] = input_name
                        break
            
            if not action:
                return {'success': False, 'message': f'❌ Không tìm thấy action cho {service_title}'}
            
            if action.startswith('/'):
                action_url = self.base_url.rstrip('/') + action
            elif action.startswith('http'):
                action_url = action
            else:
                action_url = self.base_url.rstrip('/') + '/' + action.lstrip('/')
            
            if not input_name:
                input_name = 'url'
            
            print(f"   Action URL: {action_url}")
            print(f"   Input name: {input_name}")
            
            data = {input_name: video_url}
            resp = self.session.post(
                action_url,
                data=data,
                headers={
                    'Origin': self.base_url,
                    'Referer': f"{self.base_url}/",
                    'Accept': '*/*',
                },
                timeout=60
            )
            
            text = resp.text
            
            if 'Session expired' in text:
                return {'success': False, 'message': '⚠️ Session expired'}
            
            wait = self._parse_timer(text)
            if wait and wait > 0:
                return {'success': False, 'message': f'⏳ Chờ {wait}s'}
            
            amount, kind, sent_msg = self._parse_sent_amount(text)
            if amount is not None:
                self.total_sent += amount
                return {'success': True, 'message': f'✅ {sent_msg}  |  Total: {self.total_sent}'}
            
            if 'success' in text.lower():
                return {'success': True, 'message': f'✅ Đã tăng {service_title} thành công!'}
            
            if 'Too many requests' in text:
                return {'success': False, 'message': '⚠️ Too many requests'}
            
            m = re.search(r"color:\s*green;?'?[^>]*>\s*([^<]+)", text, re.I)
            if m and 'Checking Timer' not in m.group(1):
                return {'success': True, 'message': f'✅ {m.group(1).strip()}'}
            
            return {'success': False, 'message': f'❌ Lỗi: {text[:100]}'}
            
        except Exception as e:
            return {'success': False, 'message': str(e)}

# ===== CACHE =====
cache = {
    'cookies': None,
    'services': None,
    'session_id': None,
    'services_ids': {},
    'services_input': {}
}

# ===== API =====
@app.route('/')
def index():
    return jsonify({'status':'ok','message':'Zefoy API v2.0'})

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
        
        answer = re.sub(r'[^a-zA-Z]', '', data.get('answer', '').strip()).lower()
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
            cache['services_ids'] = client.services_ids
            cache['services_input'] = client.services_input
            
            online = sum(1 for s in services if s['available'])
            print(f"✅ Lưu cache: {len(cache['services_ids'])} actions")
            
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
        
        client.services_ids = cache.get('services_ids', {})
        client.services_input = cache.get('services_input', {})
        
        print(f"📦 Cache actions: {list(client.services_ids.keys())}")
        
        result = client.run_service(service_title, video_url)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
