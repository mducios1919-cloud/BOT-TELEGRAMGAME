<?php require __DIR__ . '/config.php'; ?>
<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Zefoy Buff Panel</title>
<link rel="stylesheet" href="style.css" />
</head>
<body>
<div class="app">
  <header class="topbar">
    <div class="logo">⚡ <b>ZEFOY</b> Buff Panel</div>
    <div class="api-info">API: <code id="apiBase"><?= htmlspecialchars($API_BASE) ?></code></div>
  </header>

  <section class="card">
    <h2>1. Bắt đầu phiên</h2>
    <p class="muted">Nhấn nút để lấy session + ảnh captcha từ server.</p>
    <button id="btnStart" class="btn primary">▶ Bắt đầu / Lấy captcha</button>
    <div id="sessionBox" class="hidden">
      <div class="captcha-wrap">
        <img id="captchaImg" alt="captcha" />
        <button id="btnRefresh" class="btn ghost">🔄 Ảnh khác</button>
      </div>
      <div class="row">
        <input id="captchaAnswer" placeholder="Nhập chữ trong ảnh (chỉ chữ cái)" autocomplete="off" />
        <button id="btnSolve" class="btn primary">✔ Gửi captcha</button>
      </div>
      <div class="sid">session: <code id="sidView"></code></div>
    </div>
  </section>

  <section class="card hidden" id="panelServices">
    <h2>2. Chọn dịch vụ & link video</h2>
    <div class="row">
      <select id="serviceSel"></select>
      <button id="btnReloadSvc" class="btn ghost">↻ Reload</button>
    </div>
    <input id="videoUrl" placeholder="https://www.tiktok.com/@user/video/..." />
    <button id="btnRun" class="btn success">🚀 Bắt đầu buff</button>
    <label class="loop"><input type="checkbox" id="loopChk" /> Chạy lặp lại (auto sau mỗi lượt)</label>
  </section>

  <section class="card hidden" id="panelStats">
    <h2>3. Kết quả</h2>
    <div class="stats">
      <div class="stat"><div class="k">Tổng đã gửi</div><div class="v" id="statTotal">0</div></div>
      <div class="stat"><div class="k">Lượt gần nhất</div><div class="v" id="statLast">–</div></div>
      <div class="stat"><div class="k">Dịch vụ</div><div class="v" id="statSvc">–</div></div>
      <div class="stat"><div class="k">Cooldown</div><div class="v" id="statCd">–</div></div>
    </div>
    <div class="events" id="events"></div>
  </section>
</div>
<script src="app.js"></script>
</body>
</html>
