<?php
// ========== CONFIG ==========
// Đổi thành URL Render của bạn sau khi deploy, ví dụ:
// $API_BASE = 'https://zefoy-api.onrender.com';
$API_BASE = getenv('ZEFOY_API_BASE') ?: 'https://YOUR-APP.onrender.com';
