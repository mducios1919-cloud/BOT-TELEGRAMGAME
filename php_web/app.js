const $ = (id) => document.getElementById(id);
let SID = null;
let LOOP = false;

async function api(action, body = {}) {
  const r = await fetch(`api.php?action=${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || j.detail || `HTTP ${r.status}`);
  return j;
}

function log(msg, cls = 'info') {
  const t = new Date().toTimeString().slice(0, 8);
  const el = document.createElement('div');
  el.className = 'evt ' + cls;
  el.innerHTML = `<span class="t">${t}</span>${msg}`;
  const box = $('events');
  box.prepend(el);
  while (box.children.length > 60) box.removeChild(box.lastChild);
}

$('btnStart').onclick = async () => {
  $('btnStart').disabled = true;
  $('btnStart').textContent = '⏳ Đang lấy session...';
  try {
    const r = await api('start');
    SID = r.session_id;
    $('sidView').textContent = SID.slice(0, 12) + '…';
    $('captchaImg').src = 'data:image/png;base64,' + r.captcha_b64;
    $('sessionBox').classList.remove('hidden');
    $('captchaAnswer').focus();
    log('Đã tạo session, mời giải captcha', 'info');
  } catch (e) { log('Lỗi start: ' + e.message, 'err'); }
  $('btnStart').disabled = false;
  $('btnStart').textContent = '▶ Bắt đầu / Lấy captcha';
};

$('btnRefresh').onclick = async () => {
  if (!SID) return;
  try {
    const r = await api('refresh', { session_id: SID });
    $('captchaImg').src = 'data:image/png;base64,' + r.captcha_b64;
    $('captchaAnswer').value = '';
    $('captchaAnswer').focus();
  } catch (e) { log('Lỗi refresh: ' + e.message, 'err'); }
};

$('btnSolve').onclick = async () => {
  const ans = $('captchaAnswer').value.trim();
  if (!ans) { $('captchaAnswer').focus(); return; }
  $('btnSolve').disabled = true;
  try {
    const r = await api('solve', { session_id: SID, answer: ans });
    if (!r.ok) {
      log('Captcha sai: ' + (r.message || ''), 'err');
      if (r.captcha_b64) $('captchaImg').src = 'data:image/png;base64,' + r.captcha_b64;
      $('captchaAnswer').value = '';
      $('captchaAnswer').focus();
    } else {
      log('✔ Captcha đúng! Load danh sách service...', 'ok');
      renderServices(r.services);
      $('panelServices').classList.remove('hidden');
      $('panelStats').classList.remove('hidden');
    }
  } catch (e) { log('Lỗi solve: ' + e.message, 'err'); }
  $('btnSolve').disabled = false;
};

$('captchaAnswer').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') $('btnSolve').click();
});

function renderServices(list) {
  const sel = $('serviceSel');
  sel.innerHTML = '';
  (list || []).forEach((s) => {
    const opt = document.createElement('option');
    opt.value = s.name;
    opt.textContent = `${s.available ? '🟢' : '🔴'} ${s.name} — ${s.status}`;
    if (!s.has_action || !s.available) opt.disabled = true;
    sel.appendChild(opt);
  });
}

$('btnReloadSvc').onclick = async () => {
  try {
    const r = await api('services', { session_id: SID });
    renderServices(r.services);
    log('Đã reload dịch vụ', 'info');
  } catch (e) { log('Lỗi reload: ' + e.message, 'err'); }
};

async function runOnce() {
  const svc = $('serviceSel').value;
  const url = $('videoUrl').value.trim();
  if (!svc || !url) { log('Chọn dịch vụ và nhập link video', 'err'); return; }
  $('statSvc').textContent = svc;
  try {
    const r = await api('run', { session_id: SID, service: svc, url });
    if (r.amount) {
      $('statLast').textContent = `+${r.amount} ${r.kind || ''}`;
      $('statTotal').textContent = r.total_sent ?? '0';
      log(`✔ ${svc}: +${r.amount} ${r.kind || ''}`, 'ok');
    } else if (r.cooldown) {
      $('statCd').textContent = r.cooldown + 's';
      log(`⏱ Cooldown ${r.cooldown}s — ${r.message || ''}`, 'info');
    } else {
      log((r.ok ? '✔ ' : '✗ ') + (r.message || 'không rõ'), r.ok ? 'ok' : 'err');
    }
    return r;
  } catch (e) { log('Lỗi run: ' + e.message, 'err'); return null; }
}

$('btnRun').onclick = async () => {
  LOOP = $('loopChk').checked;
  $('btnRun').disabled = true;
  do {
    const r = await runOnce();
    if (LOOP) {
      const wait = (r && r.cooldown) ? Math.max(r.cooldown, 5) : 8;
      $('btnRun').textContent = `⏳ Chờ ${wait}s...`;
      let left = wait;
      await new Promise((res) => {
        const iv = setInterval(() => {
          left--;
          $('statCd').textContent = left + 's';
          $('btnRun').textContent = `⏳ Chờ ${left}s...`;
          if (left <= 0) { clearInterval(iv); res(); }
        }, 1000);
      });
      LOOP = $('loopChk').checked;
    }
  } while (LOOP);
  $('btnRun').disabled = false;
  $('btnRun').textContent = '🚀 Bắt đầu buff';
};
