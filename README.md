# TienBuff — TikTok Buff API + PHP Panel

Source mới thay cho `zefoy.zip`, port từ `buff.py` v3.0.3 (TIENDEV).
Không còn cần user tự giải captcha: **admin dán Cookie + User-Agent** đã đăng nhập
sẵn từ browser vào panel, hệ thống sẽ tự động luân phiên dùng.

## 🎯 Tính năng
- **1 user duy nhất được đăng ký** (first-come-first-serve).
- **Admin panel**: thêm / bật-tắt / xoá cookie + user-agent, xem lịch sử, reset user.
- **Dashboard user**: chọn dịch vụ, dán link TikTok, chạy 1 lần hoặc lặp vô hạn.
- API JSON sạch, PHP frontend chỉ là proxy — dễ đưa lên shared hosting.
- Deploy 1 click lên Render.

## 🚀 Deploy Render (API Python)
1. Push thư mục này lên GitHub (hoặc dùng "Deploy from local").
2. Trên Render → **New Web Service** → chọn repo → chọn Python → dùng `render.yaml`.
3. Set env vars trong Render:
   - `ADMIN_USER` (mặc định `admin`)
   - `ADMIN_PASS` (đổi ngay!)
   - `JWT_SECRET` — sinh tự động bằng render.yaml.
4. Sau khi deploy, ghi lại URL kiểu `https://tienbuff-api.onrender.com`.

## 🌐 Chạy PHP panel (bất kỳ shared hosting nào có PHP ≥ 7.4 + cURL)
1. Upload thư mục `php_web/` lên hosting.
2. Sửa `php_web/config.php` → đổi `$API_BASE` thành URL Render của bạn.
   Hoặc set env `TIENBUFF_API_BASE`.
3. Truy cập `index.php`, đăng nhập admin → thêm cookie → đăng ký user → dùng.

## 📡 API dùng trực tiếp (không qua PHP)

Tất cả endpoint trả JSON. Auth bằng `Authorization: Bearer <token>`.

| Method | Path | Body | Ai |
|---|---|---|---|
| GET  | `/api/status`             | — | công khai |
| POST | `/api/register`           | `{username,password}` | công khai (chỉ 1 lần) |
| POST | `/api/login`              | `{username,password}` | user/admin |
| GET  | `/api/me`                 | — | authenticated |
| GET  | `/api/services`           | — | user |
| POST | `/api/run`                | `{service,video_url}` | user |
| GET  | `/api/admin/cookies`      | — | admin |
| POST | `/api/admin/cookies`      | `{label,cookie_string,user_agent}` | admin |
| DELETE | `/api/admin/cookies/{id}` | — | admin |
| POST | `/api/admin/cookies/{id}/toggle` | — | admin |
| GET  | `/api/admin/history`      | — | admin |
| DELETE | `/api/admin/user`         | — | admin |

## 🍪 Lấy Cookie từ đâu?
1. Vào https://zefoy.com/, giải captcha đăng nhập thành công.
2. Mở DevTools → Application → Cookies → copy toàn bộ cookie thành chuỗi
   dạng `PHPSESSID=…; zf=…; cf_clearance=…`.
3. Copy `User-Agent` từ Network tab (bất kỳ request nào).
4. Dán vào form Admin. Xong.

## 🔒 Lưu ý bảo mật
- Đổi `ADMIN_PASS` ngay sau khi deploy.
- Trên free tier Render, data lưu ở `/tmp` → mất khi service ngủ. Muốn giữ,
  gắn Render **Disk** rồi set `DATA_DIR` sang mount point (ví dụ `/var/data`).
- Cookie chứa session nhạy cảm — không share URL admin ra ngoài.

Bản quyền logic Zefoy: **TIENDEV** (từ `buff.py` v3.0.3 Premium).
