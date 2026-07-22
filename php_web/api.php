<?php
require __DIR__ . '/config.php';
header('Content-Type: application/json; charset=utf-8');

$action = $_GET['action'] ?? '';
$body = file_get_contents('php://input');
$data = $body ? json_decode($body, true) : [];

$map = [
    'start'   => '/api/start',
    'solve'   => '/api/solve',
    'services'=> '/api/services',
    'run'     => '/api/run',
    'refresh' => '/api/refresh_captcha',
];
if (!isset($map[$action])) {
    http_response_code(400);
    echo json_encode(['error' => 'unknown action']);
    exit;
}

$url = rtrim($API_BASE, '/') . $map[$action];
$ch = curl_init($url);
curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_POSTFIELDS => json_encode($data ?: (object)[]),
    CURLOPT_HTTPHEADER => ['Content-Type: application/json'],
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT => 60,
    CURLOPT_SSL_VERIFYPEER => false,
]);
$resp = curl_exec($ch);
$code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$err = curl_error($ch);
curl_close($ch);

if ($resp === false) {
    http_response_code(502);
    echo json_encode(['error' => 'proxy failed: ' . $err]);
    exit;
}
http_response_code($code ?: 200);
echo $resp;
