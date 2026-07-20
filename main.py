from flask import Flask, request, jsonify
from flask_cors import CORS
import base64
import sys
import os

# Thêm đường dẫn
sys.path.insert(0, os.path.dirname(__file__))

# Import zefoy - CÓ TRY/EXCEPT ĐÚNG
try:
    from zefoy import ZefoyCaptcha, ZefoyClient
    print("✅ Import zefoy thành công!")
except ImportError as e:
    print(f"❌ Lỗi import: {e}")
    print("📁 Files hiện có:", os.listdir('.'))
    
    # Tạo class giả nếu không có
    class ZefoyCaptcha:
        def get(self):
            class Result:
                pass
            r = Result()
            r.image_bytes = b'fake'
            r.session_id = 'fake_session'
            r.captcha_token = 'fake_token'
            return r
    
    class ZefoyClient:
        def solve_and_submit(self, max_attempts=3):
            class Result:
                pass
            r = Result()
            r.success = False
            r.answer = ''
            r.session_id = ''
            r.services = []
            r.message = 'Zefoy module not available'
            return r
    
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
        
        # Kiểm tra nếu là fake data
        if captcha.image_bytes == b'fake':
            return jsonify({
                'success': False,
                'error': 'Zefoy module not available - đang dùng class giả'
            })
        
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
        
        return jsonify({
            'success': False, 
            'message': result.message if hasattr(result, 'message') else 'Submit failed'
        })
        
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
