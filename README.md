# Zefoy Render (FastAPI + built-in Web UI)

## Deploy Render
1. Push toàn bộ folder này lên GitHub repo (hoặc upload zip).
2. Trên Render → New → Web Service → chọn repo.
3. Render tự đọc `render.yaml`. Nếu tạo tay:
   - Environment: **Python 3.11**
   - Build: `pip install -r requirements.txt`
   - Start: `gunicorn -k uvicorn.workers.UvicornWorker app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 60`
4. Sau khi deploy: vào `https://<tên-app>.onrender.com/` — đã có **UI sẵn**, không cần PHP.

## Nếu vẫn Internal Server Error
- Mở tab **Logs** trên Render, xem dòng `[UNHANDLED]` → sẽ in traceback thật.
- Nguyên nhân phổ biến: **Cloudflare của zefoy.com chặn IP Render free** (trả 403/challenge). Khi đó bấm "Bắt đầu" sẽ báo lỗi cụ thể, không còn 500 trắng bóc.
- Cách xử lý: đổi sang Render plan có IP tĩnh, hoặc thêm proxy trung gian.

## PHP web (tuỳ chọn)
Trong `php_web/` — chỉ dùng nếu muốn host UI ở PHP hosting riêng. Sửa `config.php`:
```php
$API_BASE = 'https://<tên-app>.onrender.com';
```
Nhưng khuyến nghị: dùng thẳng UI có sẵn tại root Render URL.

## API endpoints
- `POST /api/start` → tạo session + captcha (base64 PNG)
- `POST /api/refresh_captcha` `{session_id}` → ảnh mới
- `POST /api/solve` `{session_id, answer}` → xác thực captcha
- `POST /api/services` `{session_id}` → list service
- `POST /api/run` `{session_id, service, url}` → buff
