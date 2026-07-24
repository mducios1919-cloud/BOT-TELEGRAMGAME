<?php
require __DIR__.'/config.php';
if (empty($_SESSION['token'])) { header('Location: index.php'); exit; }
$isAdmin = ($_SESSION['role'] ?? '') === 'admin';
?>
<!DOCTYPE html><html lang="vi"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TienBuff — Dashboard</title>
<link rel="stylesheet" href="style.css">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=JetBrains+Mono&display=swap" rel="stylesheet">
</head><body>
<div class="app">
  <header class="topbar">
    <div class="logo"><span class="dot"></span>TIENBUFF</div>
    <div class="nav">
      <a href="dashboard.php" class="active">🎯 Buff</a>
      <?php if($isAdmin):?><a href="admin.php">⚙ Admin</a><?php endif;?>
      <span class="badge <?= $isAdmin?'admin':'on' ?>"><?= htmlspecialchars($_SESSION['username']) ?><?= $isAdmin?' • ADMIN':'' ?></span>
      <a href="logout.php" class="btn ghost" style="padding:6px 12px">Đăng xuất</a>
    </div>
  </header>

  <section class="card">
    <h2>🚀 Chọn dịch vụ & bật buff</h2>
    <p class="subtitle">Cookie do admin cấu hình. Bạn chỉ cần dán link video TikTok và chọn dịch vụ.</p>
    <div class="row">
      <div><label>Dịch vụ</label><select id="serviceSel"><option>Đang tải…</option></select></div>
      <div style="flex:0 0 auto;min-width:auto"><label>&nbsp;</label><button class="btn ghost" onclick="loadServices()">↻ Reload</button></div>
    </div>
    <div class="field"><label>Link TikTok</label>
      <input id="videoUrl" placeholder="https://www.tiktok.com/@user/video/…"></div>
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
      <button class="btn success" id="btnRun" onclick="run()">▶ Bắt đầu buff</button>
      <label class="loop"><input type="checkbox" id="loopChk"> Chạy lặp lại tự động</label>
    </div>
  </section>

  <section class="card">
    <h2>📊 Thống kê</h2>
    <div class="stats">
      <div class="stat"><div class="k">Tổng đã gửi</div><div class="v" id="statTotal">0</div></div>
      <div class="stat"><div class="k">Lượt gần nhất</div><div class="v" id="statLast">—</div></div>
      <div class="stat"><div class="k">Dịch vụ</div><div class="v" id="statSvc">—</div></div>
      <div class="stat"><div class="k">Cooldown</div><div class="v" id="statCd">—</div></div>
    </div>
    <h2 style="margin-top:20px">📝 Nhật ký</h2>
    <div class="events" id="events"></div>
  </section>
</div>
<script>
const $=id=>document.getElementById(id); let LOOP=false, TOTAL=0;
async function api(action,body={},method='POST'){
  const opts={method,headers:{'Content-Type':'application/json'}};
  if(method!=='GET') opts.body=JSON.stringify(body);
  const r=await fetch('api.php?action='+action,opts);
  const j=await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(j.detail||j.message||j.error||('HTTP '+r.status));
  return j;
}
function log(msg,cls='info'){
  const t=new Date().toTimeString().slice(0,8);
  const el=document.createElement('div'); el.className='evt '+cls;
  el.innerHTML=`<span class="t">${t}</span><span>${msg}</span>`;
  const box=$('events'); box.prepend(el); while(box.children.length>80) box.removeChild(box.lastChild);
}
async function loadServices(){
  try{
    const r=await api('services',{},'GET');
    const sel=$('serviceSel'); sel.innerHTML='';
    (r.services||[]).forEach(s=>{
      const o=document.createElement('option'); o.value=s.name;
      o.textContent=(s.active?'🟢 ':'🔴 ')+s.name+' — '+s.status;
      if(!s.active) o.disabled=true; sel.appendChild(o);
    });
    log('Đã tải danh sách dịch vụ (cookie: '+r.cookie_label+')','info');
  }catch(e){ log('Lỗi services: '+e.message,'err'); }
}
async function runOnce(){
  const svc=$('serviceSel').value; const url=$('videoUrl').value.trim();
  if(!svc||!url){ log('Chọn dịch vụ và nhập link','err'); return null; }
  $('statSvc').textContent=svc;
  try{
    const r=await api('run',{service:svc,video_url:url});
    if(r.amount){ TOTAL+=r.amount; $('statTotal').textContent=TOTAL; $('statLast').textContent='+'+r.amount; }
    else $('statLast').textContent=r.ok?'✓':'✗';
    if(r.cooldown){ $('statCd').textContent=r.cooldown+'s'; log('⏱ Cooldown '+r.cooldown+'s — '+r.message,'info'); }
    else log((r.ok?'✔ ':'✘ ')+r.message, r.ok?'ok':'err');
    return r;
  }catch(e){ log('Lỗi run: '+e.message,'err'); return null; }
}
async function run(){
  LOOP=$('loopChk').checked; $('btnRun').disabled=true;
  do{
    const r=await runOnce();
    if(LOOP){
      const wait=Math.max((r&&r.cooldown)||10, 5);
      for(let s=wait;s>0;s--){ $('statCd').textContent=s+'s'; $('btnRun').textContent='⏳ Chờ '+s+'s'; await new Promise(r=>setTimeout(r,1000));}
      LOOP=$('loopChk').checked;
    }
  }while(LOOP);
  $('btnRun').disabled=false; $('btnRun').textContent='▶ Bắt đầu buff';
}
loadServices();
</script></body></html>
