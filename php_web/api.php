<?php
require __DIR__ . '/config.php';
header('Content-Type: application/json; charset=utf-8');

$action = $_GET['action'] ?? '';
$method_get = ['status','me','services','admin_cookies','admin_history'];

$map = [
  'status'         => ['GET',  '/api/status', false],
  'register'       => ['POST', '/api/register', false],
  'login'          => ['POST', '/api/login', false],
  'me'             => ['GET',  '/api/me', true],
  'services'       => ['GET',  '/api/services', true],
  'run'            => ['POST', '/api/run', true],
  'admin_cookies'  => ['GET',  '/api/admin/cookies', true],
  'admin_add'      => ['POST', '/api/admin/cookies', true],
  'admin_del'      => ['DELETE','/api/admin/cookies/{id}', true],
  'admin_toggle'   => ['POST', '/api/admin/cookies/{id}/toggle', true],
  'admin_history'  => ['GET',  '/api/admin/history', true],
  'admin_reset_user'=> ['DELETE','/api/admin/user', true],
];

if (!isset($map[$action])) { http_response_code(400); echo json_encode(['error'=>'unknown action']); exit; }
[$method, $path, $need_auth] = $map[$action];

$body_raw = file_get_contents('php://input');
$body = $body_raw ? json_decode($body_raw, true) : [];

if (strpos($path, '{id}') !== false) {
  $id = $_GET['id'] ?? '';
  if (!$id) { http_response_code(400); echo json_encode(['error'=>'missing id']); exit; }
  $path = str_replace('{id}', urlencode($id), $path);
}

$url = rtrim($API_BASE, '/') . $path;
$headers = ['Content-Type: application/json', 'Accept: application/json'];
if ($need_auth) {
  if (empty($_SESSION['token'])) { http_response_code(401); echo json_encode(['error'=>'chưa đăng nhập']); exit; }
  $headers[] = 'Authorization: Bearer ' . $_SESSION['token'];
}

$ch = curl_init($url);
$opts = [
  CURLOPT_CUSTOMREQUEST => $method,
  CURLOPT_HTTPHEADER => $headers,
  CURLOPT_RETURNTRANSFER => true,
  CURLOPT_TIMEOUT => 90,
  CURLOPT_SSL_VERIFYPEER => false,
];
if ($method !== 'GET') $opts[CURLOPT_POSTFIELDS] = json_encode($body ?: (object)[]);
curl_setopt_array($ch, $opts);
$resp = curl_exec($ch);
$code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$err = curl_error($ch);
curl_close($ch);

if ($resp === false) { http_response_code(502); echo json_encode(['error'=>'proxy failed: '.$err]); exit; }

// side-effects: login/register store token; admin actions require role check
$json = json_decode($resp, true);
if (in_array($action, ['login','register']) && $code === 200 && isset($json['token'])) {
  $_SESSION['token'] = $json['token'];
  $_SESSION['role']  = $json['role'] ?? 'user';
  $_SESSION['username'] = $json['username'] ?? '';
}
if ($action === 'logout') { session_destroy(); echo json_encode(['ok'=>true]); exit; }

http_response_code($code ?: 200);
echo $resp;
