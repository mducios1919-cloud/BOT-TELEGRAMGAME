<?php
require __DIR__.'/config.php';
if (empty($_SESSION['token']) || ($_SESSION['role']??'')!=='admin') { header('Location: index.php'); exit; }
?>
<!DOCTYPE html><html lang="vi"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TienBuff — Admin</title>
<link rel="stylesheet" href="style.css">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=JetBrains+Mono&display=swap" rel="stylesheet">
</head><body>
<div class="app">
  <header class="topbar">
    <div class="logo"><span class="dot"></span>TIENBUFF</div>
    <div class="nav">
      <a href="dashboard.php">🎯 Buff</a>
      <a href="admin.php" class="active">⚙ Admin</a>
      <span class="badge admin"><?= htmlspecialchars($_SESSION['username']) ?> • ADMIN</span>
      <a href="logout.php" class="btn ghost" style="padding:6px 12px">Đăng xuất</a>
    </div>
  </header>

  <section class="card">
    <h2>🍪 Thêm Cookie + User-Agent</h2>
    <p class="subtitle">Dán Cookie từ trình duyệt (đã đăng nhập/qua captcha zefoy.com) và User-Agent tương ứng.</p>
    <div class="field"><label>Nhãn (tuỳ chọn)</label>
      <input id="ckLabel" placeholder="VD: acc-01"></div>
    <div class="field"><label>Cookie string</label>
      <textarea id="ckStr" placeholder="PHPSESSID=…; zf=…; cf_clearance=…"></textarea></div>
    <div class="field"><label>User-Agent</label>
      <input id="ckUa" placeholder="Mozilla/5.0 (Windows NT 10.0; Win64; x64) …"></div>
    <button class="btn primary" onclick="addCookie()">➕ Thêm cookie</button>
    <div id="addMsg" class="form-msg hidden"></div>
  </section>

  <section class="card">
    <h2>📋 Danh sách Cookie <span class="badge on" id="ckCount">0</span></h2>
    <p class="subtitle">Hệ thống tự động luân phiên các cookie đang bật.</p>
    <div style="overflow-x:auto"><table id="ckTable"><thead>
      <tr><th>Nhãn</th><th>Cookie (preview)</th><th>User-Agent</th><th>Trạng thái</th><th></th></tr>
    </thead><tbody></tbody></table></div>
  </section>

  <section class="card">
    <h2>📈 Nhật ký chạy gần đây</h2>
    <div class="stats" id="statsBox"></div>
    <div style="overflow-x:auto;max-height:400px;overflow-y:auto"><table id="hisTable"><thead>
      <tr><th>Thời gian</th><th>Dịch vụ</th><th>URL</th><th>Cookie</th><th>Kết quả</th></tr>
    </thead><tbody></tbody></table></div>
  </section>

  <section class="card">
    <h2>👤 Quản lý user</h2>
    <p class="subtitle">Xoá user hiện tại để mở đăng ký cho người mới.</p>
    <button class="btn danger" onclick="if(confirm('Xoá user duy nhất và mở đăng ký lại?'))resetUser()">🗑 Xoá user & mở đăng ký</button>
  </section>
</div>
<script>
async function api(action,body={},method='POST',id){
  const q=id?('&id='+encodeURIComponent(id)):'';
  const opts={method,headers:{'Content-Type':'application/json'}};
  if(method!=='GET'&&method!=='DELETE') opts.body=JSON.stringify(body);
  const r=await fetch('api.php?action='+action+q,opts);
  const j=await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(j.detail||j.message||j.error||('HTTP '+r.status));
  return j;
}
function msg(t,cls){const e=document.getElementById('addMsg');e.textContent=t;e.className='form-msg '+cls;}
async function addCookie(){
  const label=document.getElementById('ckLabel').value.trim();
  const cookie_string=document.getElementById('ckStr').value.trim();
  const user_agent=document.getElementById('ckUa').value.trim();
  if(!cookie_string||!user_agent){msg('Cần cookie_string và user_agent','err');return;}
  try{
    await api('admin_add',{label,cookie_string,user_agent});
    msg('✓ Đã thêm cookie','ok');
    document.getElementById('ckStr').value=''; document.getElementById('ckLabel').value='';
    loadCookies();
  }catch(e){msg(e.message,'err');}
}
async function loadCookies(){
  try{
    const r=await api('admin_cookies',{},'GET');
    const tb=document.querySelector('#ckTable tbody'); tb.innerHTML='';
    (r.cookies||[]).forEach(c=>{
      const tr=document.createElement('tr');
      tr.innerHTML=`<td><b>${c.label}</b></td>
        <td><span class="mono">${c.cookie_preview}</span></td>
        <td><span class="mono">${c.user_agent.slice(0,60)}…</span></td>
        <td><span class="badge ${c.active?'on':'off'}">${c.active?'ACTIVE':'OFF'}</span></td>
        <td style="text-align:right">
          <button class="btn ghost" style="padding:6px 10px" onclick="toggleCk('${c.id}')">${c.active?'⏸':'▶'}</button>
          <button class="btn danger" style="padding:6px 10px" onclick="delCk('${c.id}')">🗑</button>
        </td>`;
      tb.appendChild(tr);
    });
    document.getElementById('ckCount').textContent=(r.cookies||[]).length;
  }catch(e){console.error(e);}
}
async function delCk(id){ if(!confirm('Xoá cookie này?'))return; try{await api('admin_del',{},'DELETE',id); loadCookies();}catch(e){alert(e.message);} }
async function toggleCk(id){ try{await api('admin_toggle',{},'POST',id); loadCookies();}catch(e){alert(e.message);} }
async function loadHistory(){
  try{
    const r=await api('admin_history',{},'GET');
    const s=r.stats||{}; const sb=document.getElementById('statsBox');
    sb.innerHTML=`<div class="stat"><div class="k">Total runs</div><div class="v">${s.total_runs||0}</div></div>
                  <div class="stat"><div class="k">Success</div><div class="v">${s.total_success||0}</div></div>`;
    const tb=document.querySelector('#hisTable tbody'); tb.innerHTML='';
    (r.history||[]).forEach(h=>{
      const tr=document.createElement('tr');
      const t=new Date(h.at*1000).toLocaleString('vi-VN');
      tr.innerHTML=`<td>${t}</td><td>${h.service}</td><td><span class="mono">${h.url}</span></td>
        <td>${h.cookie_label||''}</td>
        <td><span class="badge ${h.ok?'on':'off'}">${h.ok?'OK':'FAIL'}</span> <span class="mono">${(h.message||'').slice(0,80)}</span></td>`;
      tb.appendChild(tr);
    });
  }catch(e){console.error(e);}
}
async function resetUser(){ try{await api('admin_reset_user',{},'DELETE'); alert('Đã xoá user.');}catch(e){alert(e.message);} }
loadCookies(); loadHistory(); setInterval(loadHistory, 15000);
</script></body></html>
