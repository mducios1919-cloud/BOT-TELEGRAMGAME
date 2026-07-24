<?php
require __DIR__ . '/config.php';
// nếu đã đăng nhập → chuyển vào dashboard hoặc admin
if (!empty($_SESSION['token'])) {
  header('Location: ' . ($_SESSION['role'] === 'admin' ? 'admin.php' : 'dashboard.php'));
  exit;
}
?>
<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TienBuff — Đăng nhập</title>
<link rel="stylesheet" href="style.css">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
</head>
<body>
<div class="app auth-shell">
  <div class="auth-card">
    <div style="text-align:center;margin-bottom:26px">
      <div class="logo" style="font-size:34px"><span class="dot"></span>TIENBUFF</div>
      <p style="color:var(--muted);margin-top:8px;font-size:14px">TikTok Buff Panel • Premium Edition</p>
    </div>
    <div class="card">
      <div class="tabs">
        <button id="tabLogin" class="active" onclick="showTab('login')">Đăng nhập</button>
        <button id="tabReg" onclick="showTab('reg')">Đăng ký</button>
      </div>

      <form id="formLogin" onsubmit="return doLogin(event)">
        <div class="field"><label>Tài khoản</label><input name="username" required autocomplete="username"></div>
        <div class="field"><label>Mật khẩu</label><input name="password" type="password" required autocomplete="current-password"></div>
        <button class="btn primary" style="width:100%">🚀 Đăng nhập</button>
        <div id="msgLogin" class="form-msg hidden"></div>
        <p class="mono" style="margin-top:12px;text-align:center">Admin: dùng tài khoản trong biến môi trường ADMIN_USER/ADMIN_PASS</p>
      </form>

      <form id="formReg" class="hidden" onsubmit="return doReg(event)">
        <div id="regStatus" class="form-msg" style="background:rgba(34,211,238,.1);color:var(--neon-3)">Đang kiểm tra khả dụng…</div>
        <div class="field"><label>Tài khoản (3-32 ký tự)</label><input name="username" required minlength="3" maxlength="32"></div>
        <div class="field"><label>Mật khẩu (≥ 6 ký tự)</label><input name="password" type="password" required minlength="6"></div>
        <button class="btn success" style="width:100%" id="btnReg">✨ Tạo tài khoản</button>
        <div id="msgReg" class="form-msg hidden"></div>
        <p class="mono" style="margin-top:12px;text-align:center">⚠ Chỉ 1 người được đăng ký. Ai đăng ký trước, người đó dùng.</p>
      </form>
    </div>
  </div>
</div>
<script>
function showTab(t){
  const L=t==='login';
  document.getElementById('tabLogin').classList.toggle('active',L);
  document.getElementById('tabReg').classList.toggle('active',!L);
  document.getElementById('formLogin').classList.toggle('hidden',!L);
  document.getElementById('formReg').classList.toggle('hidden',L);
  if(!L) checkReg();
}
async function api(action,body={}){
  const r=await fetch('api.php?action='+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const j=await r.json().catch(()=>({}));
  return {ok:r.ok,status:r.status,data:j};
}
function msg(id,txt,cls){const e=document.getElementById(id);e.textContent=txt;e.className='form-msg '+cls;}
async function doLogin(ev){
  ev.preventDefault();
  const f=ev.target, u=f.username.value.trim(), p=f.password.value;
  const r=await api('login',{username:u,password:p});
  if(r.ok){location.href=r.data.role==='admin'?'admin.php':'dashboard.php';return false;}
  msg('msgLogin', r.data.detail||r.data.message||r.data.error||'Đăng nhập thất bại','err');
  return false;
}
async function doReg(ev){
  ev.preventDefault();
  const f=ev.target, u=f.username.value.trim(), p=f.password.value;
  const r=await api('register',{username:u,password:p});
  if(r.ok){location.href='dashboard.php';return false;}
  msg('msgReg', r.data.detail||r.data.message||r.data.error||'Đăng ký thất bại','err');
  return false;
}
async function checkReg(){
  const r=await api('status'); const st=document.getElementById('regStatus'); const btn=document.getElementById('btnReg');
  if(r.ok && r.data.registration_open){st.textContent='✓ Đăng ký đang mở — hãy nhanh tay!';st.className='form-msg ok';btn.disabled=false;}
  else{st.textContent='✗ Đã có người đăng ký. Chỉ 1 user duy nhất.';st.className='form-msg err';btn.disabled=true;}
}
</script>
</body></html>
