<?php
/**
 * PHP client mẫu — gọi Zefoy API deploy trên Render.
 *
 * Sau khi deploy, domain sẽ là: https://YOUR-APP.onrender.com
 * và API nằm ở: https://YOUR-APP.onrender.com/api/*
 *
 * Cách dùng (CLI):
 *   php php_client.php <video_url> [service_name]
 *
 * Hoặc mở qua HTTP (upload lên hosting PHP như InfinityFree):
 *   php_client.php?url=<video_url>&service=Views
 *
 * ĐỔI 2 hằng số dưới đây trước khi deploy.
 */
$API_BASE  = getenv('ZEFOY_API') ?: 'https://YOUR-APP.onrender.com';
$API_KEY   = getenv('ZEFOY_KEY') ?: 'YOUR_ADMIN_TOKEN';
$DEFAULT_SERVICE = 'Views'; // Views, Hearts, Followers, Comments Hearts, Favorites, Shares, ...

// ---------- HTTP helper ----------
function api($method, $path, $body = null) {
    global $API_BASE, $API_KEY;
    $ch = curl_init(rtrim($API_BASE, '/') . $path);
    $headers = ['X-API-Key: ' . $API_KEY, 'Accept: application/json'];
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CUSTOMREQUEST  => $method,
        CURLOPT_TIMEOUT        => 90,
        CURLOPT_SSL_VERIFYPEER => false,
    ]);
    if ($body !== null) {
        $headers[] = 'Content-Type: application/json';
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($body));
    }
    curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
    $out  = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    return [$code, json_decode($out, true), $out];
}

/**
 * Cách 1 (KHUYẾN NGHỊ) — gọi 1 phát endpoint mới /api/tick:
 * server tự tạo session, giải captcha, gửi tick.
 */
function tick_oneshot($video_url, $service) {
    [$c, $r] = api('POST', '/api/tick', ['service' => $service, 'url' => $video_url]);
    return ['http' => $c, 'resp' => $r];
}

/**
 * Cách 2 — chạy từng bước (nếu cần điều khiển captcha thủ công).
 */
function run_tick($video_url, $service) {
    [$c, $r] = api('POST', '/api/session/new');
    if ($c !== 200 || !isset($r['session_id'])) return ['step'=>'new','resp'=>$r];
    $sid = $r['session_id'];
    if (empty($r['logged_in'])) {
        [$c2, $r2] = api('POST', "/api/session/$sid/solve");
        if (empty($r2['success'])) return ['step'=>'solve','sid'=>$sid,'resp'=>$r2];
    }
    [$c3, $r3] = api('POST', "/api/session/$sid/send", [
        'service' => $service, 'url' => $video_url
    ]);
    return ['step'=>'send','sid'=>$sid,'resp'=>$r3];
}

// ---------- entry ----------
if (php_sapi_name() === 'cli') {
    $url = $argv[1] ?? null;
    $svc = $argv[2] ?? $DEFAULT_SERVICE;
    if (!$url) { fwrite(STDERR, "usage: php php_client.php <video_url> [service]\n"); exit(1); }
    print_r(tick_oneshot($url, $svc));
} else {
    header('Content-Type: application/json; charset=utf-8');
    $url = $_GET['url'] ?? $_POST['url'] ?? null;
    $svc = $_GET['service'] ?? $_POST['service'] ?? $DEFAULT_SERVICE;
    if (!$url) { echo json_encode(['error'=>'missing url']); exit; }
    echo json_encode(tick_oneshot($url, $svc), JSON_UNESCAPED_UNICODE|JSON_PRETTY_PRINT);
}
