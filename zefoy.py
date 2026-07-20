# zefoy.py - Đặt TÊN FILE LÀ zefoy.py (KHÔNG phải thư mục)
import base64
import hashlib
import time
import requests
import json
import re
import os

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

class ZefoyCaptcha:
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.user_agent = DEFAULT_USER_AGENT
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
        
        token = None
        if '_CAPTCHA=' in path:
            token = path.split('_CAPTCHA=')[1].split('&')[0]
        
        class Result:
            pass
        result = Result()
        result.image_bytes = img_resp.content
        result.image_url = image_url
        result.captcha_token = token
        result.session_id = self.session.cookies.get('PHPSESSID')
        return result

class ZefoyClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.user_agent = DEFAULT_USER_AGENT
        self.base_url = "https://zefoy.com"
    
    def solve_and_submit(self, max_attempts=3):
        class Result:
            pass
        result = Result()
        
        try:
            # Lấy CAPTCHA
            captcha_client = ZefoyCaptcha()
            captcha = captcha_client.get()
            
            # OCR bằng NewOCR
            answer = self._ocr_captcha(captcha.image_bytes)
            
            if not answer:
                result.success = False
                result.message = "OCR failed"
                result.answer = ""
                result.session_id = ""
                result.services = []
                return result
            
            # Submit
            submit_result = self._submit_captcha(answer)
            
            if submit_result:
                result.success = True
                result.answer = answer
                result.session_id = self.session.cookies.get('PHPSESSID')
                result.services = self._get_services()
                result.message = "Success"
            else:
                result.success = False
                result.message = "Submit failed"
                result.answer = answer
                result.session_id = ""
                result.services = []
                
        except Exception as e:
            result.success = False
            result.message = str(e)
            result.answer = ""
            result.session_id = ""
            result.services = []
        
        return result
    
    def _ocr_captcha(self, image_bytes):
        try:
            boundary = '----WebKitFormBoundary' + ''.join([chr(97 + (i % 26)) for i in range(16)])
            
            body = f"--{boundary}\r\n"
            body += 'Content-Disposition: form-data; name="preview"\r\n\r\n'
            body += "1\r\n"
            body += f"--{boundary}\r\n"
            body += 'Content-Disposition: form-data; name="userfile"; filename="captcha.png"\r\n'
            body += 'Content-Type: application/octet-stream\r\n\r\n'
            body += image_bytes.decode('latin-1')
            body += f"\r\n--{boundary}--\r\n"
            
            headers = {
                'Content-Type': f'multipart/form-data; boundary={boundary}',
                'User-Agent': self.user_agent
            }
            
            resp = self.session.post('https://www.newocr.com/', data=body.encode('latin-1'), headers=headers, timeout=60)
            
            match = re.search(r'name="u"\s+value="([a-f0-9]{32})"', resp.text)
            if not match:
                return ''
            file_id = match.group(1)
            
            ocr_data = {
                'u': file_id,
                'ocr': '1',
                'l2[]': 'eng',
                'psm': '6',
                'x1': '0', 'y1': '0', 'x2': '100', 'y2': '100'
            }
            
            resp = self.session.post('https://www.newocr.com/', data=ocr_data, headers={'User-Agent': self.user_agent}, timeout=60)
            
            match = re.search(r'<textarea[^>]*id="ocr-result"[^>]*>([\s\S]*?)</textarea>', resp.text)
            if match:
                text = match.group(1).strip()
                text = re.sub(r'[^a-zA-Z]', '', text)
                return text.lower()
            
            return ''
        except Exception as e:
            print(f"OCR error: {e}")
            return ''
    
    def _submit_captcha(self, answer):
        try:
            import json
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
                'User-Agent': self.user_agent
            }, timeout=30)
            
            return resp.text.strip().lower() == 'success'
            
        except Exception as e:
            print(f"Submit error: {e}")
            return False
    
    def _get_services(self):
        try:
            resp = self.session.get(self.base_url, headers={'User-Agent': self.user_agent}, timeout=30)
            
            services = []
            pattern = r'<h5[^>]*>([^<]+)</h5>\s*<small[^>]*>([^<]*)</small>'
            matches = re.findall(pattern, resp.text)
            
            for title, status in matches:
                title = title.strip()
                status = status.strip()
                if not title:
                    continue
                
                available = not ('soon' in status.lower() or 'update' in status.lower())
                services.append({
                    'title': title,
                    'status': status or 'Online',
                    'available': available
                })
            
            return services
        except Exception as e:
            print(f"Get services error: {e}")
            return []
