<?php
/**
 * PHP client mẫu — gọi Zefoy API deploy trên Render.
 *
 * Cách dùng:
 *   php php_client.php <video_url> [service_name]
 * hoặc mở trên hosting (InfinityFree...): ?url=...&service=...
 *
 * Cấu hình:
 */
$API_BASE  = getenv('ZEFOY_API')  ?: 'https://YOUR-APP.onrender.com';
$API_KEY   = getenv('ZEFOY_KEY')  ?: 'YOUR_ADMIN_TOKEN';
$DEFAULT_SERVICE = 'Views';   // "Followers", "Views", "Hearts", "Comments Hearts", "Favorites", "Shares"...

// ---------- HTTP helper ----------
function api($method, $path, $body = null) {
    global $API_BASE, $API_KEY;
    $ch = curl_init($API_BASE . $path);
    $headers = ['X-API-Key: ' . $API_KEY, 'Accept: application/json'];
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CUSTOMREQUEST  => $method,
        CURLOPT_TIMEOUT        => 60,
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

// ---------- flow: new session -> solve captcha -> send ----------
function run_tick($video_url, $service) {
    // 1) tạo session
    [$c, $r] = api('POST', '/api/session/new');
    if ($c !== 200 || !isset($r['session_id'])) return ['step'=>'new','resp'=>$r];
    $sid = $r['session_id'];

    // 2) nếu chưa login -> giải captcha auto
    if (empty($r['logged_in'])) {
        [$c2, $r2] = api('POST', "/api/session/$sid/solve");
        if (empty($r2['success'])) return ['step'=>'solve','sid'=>$sid,'resp'=>$r2];
    }

    // 3) gửi tick
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
    print_r(run_tick($url, $svc));
} else {
    header('Content-Type: application/json; charset=utf-8');
    $url = $_GET['url'] ?? $_POST['url'] ?? null;
    $svc = $_GET['service'] ?? $_POST['service'] ?? $DEFAULT_SERVICE;
    if (!$url) { echo json_encode(['error'=>'missing url']); exit; }
    echo json_encode(run_tick($url, $svc), JSON_UNESCAPED_UNICODE|JSON_PRETTY_PRINT);
}
