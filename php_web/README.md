# Zefoy PHP Web (giao diện buff)

## Cấu trúc
```
php_web/
├── index.php    ← trang chính (UI)
├── api.php      ← proxy gọi FastAPI backend
├── config.php   ← sửa URL Render ở đây
├── app.js
└── style.css
```

## Cài
1. Sửa `config.php`, đặt `$API_BASE = 'https://<tên-app>.onrender.com';` (URL Render sau khi deploy `zefoy_render`).
2. Upload cả folder `php_web/` lên hosting PHP (InfinityFree, 000webhost, hoặc VPS Apache/Nginx + PHP 7.4+).
3. Truy cập `https://your-site.com/index.php`.

## Cách dùng
1. Bấm **▶ Bắt đầu / Lấy captcha** → server tạo session, hiện ảnh captcha.
2. Nhìn ảnh, gõ chữ vào ô → **✔ Gửi captcha** (giải tay, không auto).
3. Chọn service (🟢 = online) + dán link TikTok → **🚀 Bắt đầu buff**.
4. Kết quả hiện số lượng đã gửi (view/heart/…) trong ô "Tổng đã gửi" và "Lượt gần nhất".
5. Tick **Chạy lặp lại** để tự động lặp sau mỗi cooldown.

## Yêu cầu PHP
- PHP 7.4+ có extension `curl`.
- Không cần MySQL, không cần token/admin.
