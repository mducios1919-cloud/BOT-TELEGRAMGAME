from flask import Flask, request, jsonify
from flask_cors import CORS
import base64
import sys
import os

# Thêm đường dẫn
sys.path.insert(0, os.path.dirname(__file__))

try:
    from zefoy import ZefoyCaptcha, ZefoyClient
    print("✅ Import zefoy thành công!")
except ImportError as e:
    print(f"❌ Lỗi: {e}")
    print("📁 Đang kiểm tra thư mục...")
    print("📁 Files hiện có:", os.listdir('.'))
    
    # Tạo class giả nếu không có
    class ZefoyCaptcha:
        def get(self):
            return type('obj', (object,), {
                'image_bytes': b'fake',
                'session_id': 'fake_session',
                'captcha_token': 'fake_token'
            })()
    
    class ZefoyClient:
        def solve_and_submit(self, max_attempts=3):
            return type('obj', (object,), {
                'success': False,
                'answer': '',
                'session_id': '',
                'services': [],
                'message': 'Zefoy module not available'
            })()
    
    print("⚠️ Đang dùng class giả (zefoy không có sẵn)")

app = Flask(__name__)
CORS(app)

@app.route('/')
def index():
    return jsonify({
        'status': 'online',
        'message': 'Zefoy API Proxy - Replit',
        'endpoints': {
            '/get_captcha': 'GET - Lấy CAPTCHA',
            '/solve_submit': 'POST - Giải CAPTCHA',
            '/health': 'GET - Kiểm tra status'
        }
    })

@app.route('/get_captcha')
def get_captcha():
    try:
        print("🔄 Lấy CAPTCHA...")
        client = ZefoyCaptcha()
        captcha = client.get()
        
        return jsonify({
            'success': True,
            'captcha': {
                'image_base64': base64.b64encode(captcha.image_bytes).decode('ascii'),
                'session_id': captcha.session_id,
                'captcha_token': captcha.captcha_token,
            }
        })
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/solve_submit', methods=['POST'])
def solve_submit():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data'})
        
        print("🔄 Giải CAPTCHA...")
        client = ZefoyClient()
        result = client.solve_and_submit(max_attempts=3)
        
        if result.success:
            services = []
            for s in result.services:
                services.append({
                    'title': s.title,
                    'status': s.status,
                    'available': s.available,
                })
            
            return jsonify({
                'success': True,
                'message': f'✅ Solved: {result.answer}',
                'data': {
                    'answer': result.answer,
                    'session_id': result.session_id,
                    'services': services
                }
            })
        
        return jsonify({'success': False, 'message': 'Submit failed'})
        
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)