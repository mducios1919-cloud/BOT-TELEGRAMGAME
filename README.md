# Zefoy Web API (Render-ready)

## Cấu trúc
```
zefoy_render/
├── app.py              ← FastAPI app (entry point)
├── zefoy/              ← package gốc (captcha, submit, fingerprint...)
├── requirements.txt
├── Procfile
├── render.yaml
└── runtime.txt
```

## Deploy lên Render
1. Đẩy folder này lên GitHub repo.
2. Vào https://render.com → **New +** → **Web Service** → chọn repo.
3. Render tự đọc `render.yaml`. Bấm **Create**.
4. Sau khi deploy xong, URL sẽ có dạng `https://<tên-app>.onrender.com`.
5. Test: mở `https://<tên-app>.onrender.com/health` phải trả `{"ok":true}`.

## Endpoints (không cần token)
| Method | Path | Body | Trả về |
|---|---|---|---|
| POST | `/api/start` | `{}` | `{session_id, captcha_b64}` |
| POST | `/api/solve` | `{session_id, answer}` | `{ok, services[]}` |
| POST | `/api/services` | `{session_id}` | `{services[], total_sent}` |
| POST | `/api/run` | `{session_id, service, url}` | `{ok, amount, kind, message, total_sent}` |
| POST | `/api/refresh_captcha` | `{session_id}` | `{captcha_b64}` |

## Test nhanh bằng curl
```bash
curl -X POST https://<app>.onrender.com/api/start
```
