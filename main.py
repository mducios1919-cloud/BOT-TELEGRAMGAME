from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import base64
import sys
import os
import io

sys.path.insert(0, os.path.dirname(__file__))

try:
    from zefoy import ZefoyCaptcha, ZefoyClient
    print("✅ Import zefoy thành công!")
except Exception as e:
    print(f"❌ Lỗi: {e}")
    class ZefoyCaptcha:
        def get(self):
            class R: pass
            r = R()
            r.image_bytes = b'fake'
            r.session_id = 'fake'
            r.captcha_token = 'fake'
            return r
    class ZefoyClient:
        def solve_and_submit(self, max_attempts=3):
            class R: pass
            r = R()
            r.success = False
            r.answer = ''
            r.session_id = ''
            r.services = []
            r.message = 'Zefoy not available'
            return r
    print("⚠️ Dùng class giả")

app = Flask(__name__)
CORS(app)

# Lưu captcha tạm
captcha_cache = {}

@app.route('/')
def index():
    return jsonify({'status': 'ok', 'message': 'Zefoy API'})

@app.route('/get_captcha')
def get_captcha():
    try:
        client = ZefoyCaptcha()
        captcha = client.get()
        
        # Lưu vào cache
        captcha_cache['image'] = captcha.image_bytes
        captcha_cache['session_id'] = captcha.session_id
        captcha_cache['captcha_token'] = captcha.captcha_token
        
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

@app.route('/captcha_image')
def captcha_image():
    """Hiển thị ảnh CAPTCHA trực tiếp"""
    if 'image' not in captcha_cache:
        return jsonify({'error': 'Chưa có CAPTCHA'}), 404
    return send_file(
        io.BytesIO(captcha_cache['image']),
        mimetype='image/png'
    )

@app.route('/submit_manual', methods=['POST'])
def submit_manual():
    """Submit CAPTCHA bằng tay"""
    try:
        data = request.get_json()
        answer = data.get('answer', '').strip()
        
        if not answer:
            return jsonify({'success': False, 'message': 'Vui lòng nhập CAPTCHA'})
        
        print(f"🔄 Submit CAPTCHA thủ công: {answer}")
        
        # Tạo client mới và submit
        client = ZefoyClient()
        
        # Dùng session đã có
        if 'session_id' in captcha_cache:
            client.session.cookies.set('PHPSESSID', captcha_cache['session_id'])
        
        # Submit
        from zefoy import ZefoyCaptcha
        captcha_client = ZefoyCaptcha()
        captcha_client.session.cookies.set('PHPSESSID', captcha_cache['session_id'])
        
        # Gọi submit
        submit_ok = client._submit_captcha(answer)
        
        if submit_ok:
            services = client._get_services()
            return jsonify({
                'success': True,
                'message': f'✅ CAPTCHA đúng! Session đã được tạo.',
                'data': {
                    'answer': answer,
                    'session_id': client.session.cookies.get('PHPSESSID'),
                    'services': services
                }
            })
        else:
            return jsonify({
                'success': False,
                'message': '❌ CAPTCHA sai hoặc hết hạn. Thử lại!'
            })
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/solve_submit', methods=['POST'])
def solve_submit():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data'})
        
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
                'message': f'Solved: {result.answer}',
                'data': {
                    'answer': result.answer,
                    'session_id': result.session_id,
                    'services': services
                }
            })
        return jsonify({'success': False, 'message': 'Submit failed'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
