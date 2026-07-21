# Zefoy API + Admin (deploy Render.com)

Toàn bộ project Zefoy đóng gói lại thành **1 file `main.py`** (không mã hoá, chỉ base64 encode để giữ nguyên cấu trúc `zefoy.captcha`, `zefoy.submit`, `zefoy.newocr`,...), kèm một Flask app (`app.py`) cung cấp:

- **REST API** để giải captcha, chọn service, gửi tick.
- **Admin UI** (mở `/` trên trình duyệt) — nhập link video, giải captcha, chọn dịch vụ, gửi/loop tự động.
- **PHP client mẫu** (`php_client.php`) để gọi từ website / InfinityFree.

## Cấu trúc

```
zefoy_render/
├── main.py            # bundle full package zefoy (import hook, không mã hoá)
├── app.py             # Flask API + Admin UI
├── requirements.txt
├── render.yaml        # blueprint deploy Render
├── Procfile           # dự phòng
├── runtime.txt        # Python 3.11
├── php_client.php     # gọi API từ PHP
└── README.md
```

## Deploy Render.com (Free tier — không sập)

1. Đẩy folder này lên GitHub (public hoặc private).
2. Render → New → **Blueprint** → chọn repo. Render đọc `render.yaml` tự động tạo service `zefoy-api`.
   - Nếu tạo thủ công (New → Web Service), điền:
     - **Build Command:** `pip install -r requirements.txt`
     - **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 60`
     - **Environment:** `Python 3`
3. Ở tab **Environment**, thêm biến `ADMIN_TOKEN` (Render tự sinh nếu dùng blueprint). Ghi lại token này.
4. Deploy. URL sẽ dạng `https://zefoy-api-xxxx.onrender.com`.

### Vì sao không sập free tier

- 1 worker, 4 threads → RAM giữ ~120–180 MB (limit 512 MB).
- `MAX_SESSIONS=15`, TTL 30 phút, LRU tự evict.
- Không dùng Playwright/Selenium/Chromium → không nổ RAM.
- Không có background loop server-side; client (Admin UI hoặc PHP) tự đẩy tick định kỳ. Render free sleep sau 15' idle không ảnh hưởng vì mỗi tick tự đánh thức.

## Dùng Admin UI

Mở `https://<render-url>/` → dán `ADMIN_TOKEN` → **Tạo Session** → captcha hiện ra → **Giải tự động** (NewOCR) hoặc gõ tay → chọn service, dán link video → **Gửi 1 tick** hoặc **Loop**.

## Dùng API trực tiếp

Tất cả endpoint yêu cầu header `X-API-Key: <ADMIN_TOKEN>`.

| Method | Path | Body | Kết quả |
|---|---|---|---|
| POST | `/api/session/new` | – | tạo session, trả `session_id` + captcha (base64 PNG) hoặc `logged_in:true` + danh sách service |
| GET  | `/api/session/{sid}/captcha` | – | tải lại captcha mới |
| POST | `/api/session/{sid}/solve` | – | tự OCR (NewOCR + ddddocr) rồi submit |
| POST | `/api/session/{sid}/submit` | `{answer}` | submit tay |
| GET  | `/api/session/{sid}/services` | – | refresh trạng thái service |
| POST | `/api/session/{sid}/send` | `{service, url}` | gửi 1 tick |
| DELETE | `/api/session/{sid}` | – | xoá session |
| GET  | `/api/health` | – | check sống |

## Chạy `main.py` như code gốc (CLI, offline)

```bash
pip install requests beautifulsoup4 pycryptodome colorama prettytable
python main.py
```

Nó chạy đúng như `run.py` gốc (hỏi link video, tương tác terminal). Import từ mã khác vẫn OK:

```python
import main            # đăng ký hook
from zefoy.submit import ZefoyClient
```

## PHP client

Sửa `$API_BASE` và `$API_KEY` trong `php_client.php` rồi upload lên hosting.

```bash
php php_client.php "https://www.tiktok.com/@x/video/1234" "Views"
```

Hoặc gọi qua HTTP: `https://your-site.free.nf/php_client.php?url=...&service=Views`.

## Lưu ý thực tế

- IP hosting free (InfinityFree, một số vùng Render) hay bị Cloudflare của Zefoy chặn → nếu captcha luôn fail hoặc login mãi không được, đổi region hoặc dùng proxy.
- Không đẩy tick nhanh hơn `wait_seconds` server trả về — sẽ bị Zefoy khoá tạm.
