<?php
/**
 * php_web.php — Mẫu website PHP full (upload lên InfinityFree / bất kỳ hosting PHP nào)
 * kết nối tới Zefoy API đã deploy trên Render.
 *
 * ĐỔI 2 dòng dưới trước khi upload.
 */
$API_BASE = 'https://YOUR-APP.onrender.com';   // domain Render của bạn — API tự nằm ở $API_BASE/api/*
$API_KEY  = 'YOUR_ADMIN_TOKEN';                // trùng ADMIN_TOKEN đặt trên Render

$SERVICES = ['Views','Hearts','Followers','Comments Hearts','Favorites','Shares','Live Stream','Repost'];

function zefoy_call($API_BASE, $API_KEY, $path, $body = null) {
    $ch = curl_init(rtrim($API_BASE,'/') . $path);
    $headers = ['X-API-Key: '.$API_KEY, 'Accept: application/json'];
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CUSTOMREQUEST  => 'POST',
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
    return [$code, json_decode($out, true)];
}

$result = null;
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $url = trim($_POST['url'] ?? '');
    $svc = $_POST['service'] ?? 'Views';
    if ($url) {
        [$code, $resp] = zefoy_call($API_BASE, $API_KEY, '/api/tick', ['service'=>$svc,'url'=>$url]);
        $result = ['http'=>$code, 'resp'=>$resp];
    }
}
?>
<!doctype html>
<html lang="vi"><head>
<meta charset="utf-8">
<title>TikTok Booster</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0f172a;--fg:#e2e8f0;--card:#1e293b;--accent:#38bdf8;--ok:#22c55e;--err:#ef4444}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,Segoe UI;background:var(--bg);color:var(--fg)}
header{padding:16px 20px;background:#0b1220;border-bottom:1px solid #1e293b}
h1{margin:0;font-size:18px;color:var(--accent)}
main{max-width:720px;margin:0 auto;padding:20px;display:grid;gap:16px}
.card{background:var(--card);padding:18px;border-radius:12px;border:1px solid #334155}
label{display:block;font-size:12px;color:#94a3b8;margin:0 0 6px}
input,select,button{font:inherit;color:var(--fg);background:#0b1220;border:1px solid #334155;border-radius:8px;padding:10px 12px;width:100%}
button{background:var(--accent);color:#0b1220;font-weight:600;border:0;cursor:pointer}
.row{display:flex;gap:10px;flex-wrap:wrap}.row>*{flex:1;min-width:140px}
pre{background:#0b1220;padding:12px;border-radius:8px;overflow:auto;font-size:12px;max-height:280px}
.tag{display:inline-block;padding:3px 10px;border-radius:99px;font-size:12px}
.tag.ok{background:var(--ok);color:#00220a}.tag.err{background:var(--err);color:#3a0000}
.small{color:#94a3b8;font-size:12px}
</style></head><body>
<header><h1>🚀 TikTok Booster (Zefoy)</h1></header>
<main>
  <form class="card" method="POST">
    <label>Link video TikTok</label>
    <input name="url" required placeholder="https://www.tiktok.com/@user/video/123..." value="<?=htmlspecialchars($_POST['url'] ?? '')?>">
    <div class="row" style="margin-top:12px">
      <div>
        <label>Dịch vụ</label>
        <select name="service">
          <?php foreach ($SERVICES as $s): $sel=($s===($_POST['service']??'Views'))?'selected':''; ?>
            <option <?=$sel?>><?=$s?></option>
          <?php endforeach; ?>
        </select>
      </div>
      <div style="display:flex;align-items:flex-end"><button type="submit">Gửi 1 tick</button></div>
    </div>
    <p class="small" style="margin-top:12px">API: <code><?=htmlspecialchars($API_BASE)?>/api/tick</code></p>
  </form>

  <?php if ($result): $r=$result['resp']??[]; $ok=!empty($r['ok']); ?>
  <div class="card">
    <p>Kết quả:
      <span class="tag <?=$ok?'ok':'err'?>"><?=$ok?'OK':'FAIL'?></span>
      <?php if(!empty($r['wait_seconds'])): ?>
        <span class="small">chờ <?=$r['wait_seconds']?>s trước tick sau</span>
      <?php endif; ?>
    </p>
    <pre><?=htmlspecialchars(json_encode($result, JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE))?></pre>
  </div>
  <?php endif; ?>

  <div class="card small">
    <p><b>Hướng dẫn:</b></p>
    <ol>
      <li>Deploy folder <code>zefoy_render</code> lên Render (Blueprint từ <code>render.yaml</code>).</li>
      <li>Ghi lại URL Render (dạng <code>https://xxx.onrender.com</code>) và <code>ADMIN_TOKEN</code>.</li>
      <li>Sửa <code>$API_BASE</code> và <code>$API_KEY</code> ở đầu file này.</li>
      <li>Upload <code>php_web.php</code> lên hosting PHP (VD InfinityFree) → mở trong trình duyệt.</li>
    </ol>
  </div>
</main>
</body></html>
