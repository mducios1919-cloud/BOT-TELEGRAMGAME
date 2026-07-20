from flask import Flask, request, jsonify
from flask_cors import CORS
import base64
import sys
import os

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

@app.route('/')
def index():
    return jsonify({'status': 'ok', 'message': 'Zefoy API on Render'})

@app.route('/get_captcha')
def get_captcha():
    try:
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
        return jsonify({'success': False, 'error': str(e)})

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

# Render dùng gunicorn, không cần if __name__ == '__main__'
