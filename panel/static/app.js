const API = location.pathname.startsWith('/mtproxy') ? '/mtproxy' : '';
let token = localStorage.getItem('mtp_token') || '';
let dashboardData = null;
let modalLink = '';
let refreshTimer = null;
let confirmCallback = null;

const PAGE_TITLES = {
  dashboard: '系统看板',
  users: '用户管理',
  settings: '代理设置',
  security: '安全设置',
  nodes: '服务器',
  forward: '端口转发',
};

const ICONS = {
  share: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.59 13.51l6.83 3.98M15.41 6.51l-6.82 3.98"/></svg>',
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>',
  edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>',
  toggle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="1" y="5" width="22" height="14" rx="7"/><circle cx="8" cy="12" r="3"/></svg>',
  delete: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>',
};

// ===== 工具函数 =====
function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function show(el) { el.classList.remove('hidden'); }
function hide(el) { el.classList.add('hidden'); }

function setLoading(on) {
  const el = document.getElementById('global-loading');
  on ? show(el) : hide(el);
}

function toast(msg, type = 'info') {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const icons = {
    success: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>',
    error: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>',
    info: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>',
  };
  el.innerHTML = `${icons[type] || icons.info}<span>${esc(msg)}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.style.animation = 'toastOut 0.3s ease forwards';
    setTimeout(() => el.remove(), 300);
  }, 3200);
}

function confirmDialog(title, msg, onOk) {
  document.getElementById('confirm-title').textContent = title;
  document.getElementById('confirm-msg').textContent = msg;
  confirmCallback = onOk;
  document.getElementById('confirm-ok').onclick = () => {
    closeModal('modal-confirm');
    if (confirmCallback) confirmCallback();
    confirmCallback = null;
  };
  show(document.getElementById('modal-confirm'));
}

function donutHtml(pct, value, label, sub, color) {
  const p = Math.min(Math.max(pct, 0), 100);
  return `
    <div class="metric-card">
      <div class="donut-label">${label}</div>
      <div class="donut" style="--pct:${p};--donut-color:${color}">
        <span class="donut-value">${value}</span>
      </div>
      ${sub ? `<div class="donut-sub">${sub}</div>` : ''}
    </div>`;
}

async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const url = path.startsWith('http') ? path : `${API}${path}`;
  const res = await fetch(url, { ...opts, headers });
  if (res.status === 401) { logout(); throw new Error('登录已过期'); }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(typeof err.detail === 'string' ? err.detail : `请求失败 ${res.status}`);
  }
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return res.json();
  return res;
}

// ===== 侧边栏 =====
function toggleSidebar(open) {
  const sb = document.getElementById('sidebar');
  const ov = document.getElementById('sidebar-overlay');
  if (open === undefined) open = !sb.classList.contains('open');
  sb.classList.toggle('open', open);
  ov.classList.toggle('show', open);
}

// ===== 登录 =====
async function doLogin() {
  const username = document.getElementById('login-user').value.trim();
  const password = document.getElementById('login-pass').value;
  const errEl = document.getElementById('login-error');
  const btn = document.getElementById('btn-login');
  btn.disabled = true;
  setLoading(true);
  try {
    const data = await api('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) });
    token = data.token;
    localStorage.setItem('mtp_token', token);
    hide(errEl);
    showApp();
    toast('登录成功', 'success');
  } catch (e) {
    errEl.textContent = e.message;
    show(errEl);
    toast(e.message, 'error');
  } finally {
    btn.disabled = false;
    setLoading(false);
  }
}

function logout() {
  token = '';
  localStorage.removeItem('mtp_token');
  if (refreshTimer) clearInterval(refreshTimer);
  toggleSidebar(false);
  hide(document.getElementById('app-view'));
  show(document.getElementById('login-view'));
}

function showApp() {
  hide(document.getElementById('login-view'));
  show(document.getElementById('app-view'));
  refreshDashboard();
  loadSettings();
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(refreshDashboard, 15000);
}

function switchTab(name) {
  document.querySelectorAll('.nav-item[data-tab]').forEach(n => {
    n.classList.toggle('active', n.dataset.tab === name);
  });
  document.querySelectorAll('.panel-section').forEach(s => {
    s.classList.toggle('active', s.id === `tab-${name}`);
  });
  document.getElementById('page-title').textContent = PAGE_TITLES[name] || name;
  toggleSidebar(false);
  document.getElementById('content-area').classList.remove('fade-in');
  void document.getElementById('content-area').offsetWidth;
  document.getElementById('content-area').classList.add('fade-in');
}

// ===== 看板渲染 =====
function tlsLabel(mode) {
  return { ee: 'ee 开启', dd: 'dd 开启', off: '已关闭' }[mode] || mode;
}

function statusBadge(u) {
  if (!u.raw_enabled) return '<span class="badge off">已禁用</span>';
  if (u.expired) return '<span class="badge danger">已到期</span>';
  if (u.over_quota) return '<span class="badge warn">超流量</span>';
  if (u.is_online) return '<span class="badge online">在线</span>';
  if (u.enabled) return '<span class="badge on">正常</span>';
  return '<span class="badge off">离线</span>';
}

function renderStats(data) {
  const { system: sys, proxy, stats } = data;
  const grid = document.getElementById('stats-grid');

  const barHtml = (pct, color) => `
    <div class="dense-bar"><div class="dense-bar-fill" style="width:${Math.min(pct,100)}%;background:${color}"></div></div>`;

  grid.innerHTML = `
    <div class="dense-card">
      <div class="dense-card-head"><span class="dense-icon" style="background:rgba(42,171,238,.12);color:#1d9ad8">⚙</span><span>CPU</span><b>${sys.cpu_percent}%</b></div>
      ${barHtml(sys.cpu_percent, 'linear-gradient(90deg,#2aabee,#1d7fe0)')}
      <div class="dense-card-sub">处理器负载 · ${sys.cpu_count || ''}核</div>
    </div>
    <div class="dense-card">
      <div class="dense-card-head"><span class="dense-icon" style="background:rgba(245,158,11,.12);color:#d97706">▤</span><span>内存</span><b>${sys.memory_percent}%</b></div>
      ${barHtml(sys.memory_percent, 'linear-gradient(90deg,#f59e0b,#d97706)')}
      <div class="dense-card-sub">${sys.memory_used_gb} / ${sys.memory_total_gb} GB</div>
    </div>
    <div class="dense-card">
      <div class="dense-card-head"><span class="dense-icon" style="background:rgba(168,85,247,.12);color:#7c3aed">◉</span><span>磁盘</span><b>${sys.disk_percent}%</b></div>
      ${barHtml(sys.disk_percent, 'linear-gradient(90deg,#a855f7,#7c3aed)')}
      <div class="dense-card-sub">剩余 ${sys.disk_free_gb} GB</div>
    </div>
    <div class="dense-card">
      <div class="dense-card-head"><span class="dense-icon" style="background:rgba(34,197,94,.12);color:#16a34a">◈</span><span>用户</span><b>${stats.active_users}/${stats.total_users}</b></div>
      ${barHtml(stats.total_users ? stats.active_users/stats.total_users*100 : 0, 'linear-gradient(90deg,#22c55e,#16a34a)')}
      <div class="dense-card-sub">总流量 ${stats.total_traffic_human}</div>
    </div>
    <div class="dense-card dense-wide">
      <div class="dense-card-head">
        <span class="dense-icon" style="background:rgba(42,171,238,.12);color:#1d9ad8">⇄</span>
        <span>代理状态</span>
        ${proxy.running ? '<span class="badge on">运行中</span>' : '<span class="badge danger">已停止</span>'}
        <span style="flex:1"></span>
        <button class="btn btn-sm" onclick="showPage('proxy')">去设置</button>
      </div>
      <div class="dense-proxy-grid">
        <div><span>在线连接</span><b>${proxy.connections}</b></div>
        <div><span>端口</span><b>${proxy.port}</b></div>
        <div><span>伪装域名</span><b style="font-size:.8rem">${esc(proxy.domain || '-')}</b></div>
        <div><span>混淆</span><b>${tlsLabel(proxy.fake_tls_mode)}</b></div>
        <div><span>公网IP</span><b style="font-size:.8rem">${esc(proxy.public_ip)}</b></div>
        <div><span>SOCKS5</span><b>${proxy.socks5_running ? '运行中' : '未启用'}</b></div>
      </div>
    </div>
  `;

  const uc = document.getElementById('user-count');
  if (uc) uc.textContent = `${stats.total_users} 个密钥`;
}

function trafficHtml(u) {
  const limit = u.traffic_limit_gb > 0 ? `${u.traffic_limit_gb} GB` : '不限';
  let bar = '';
  if (u.traffic_limit_gb > 0) {
    const pct = Math.min(u.traffic_percent, 100);
    const color = pct >= 90 ? 'var(--danger)' : pct >= 70 ? 'var(--warning)' : 'var(--success)';
    bar = `<div class="traffic-bar"><div class="traffic-bar-fill" style="width:${pct}%;background:${color}"></div></div>
           <span style="font-size:0.72rem;color:var(--text-muted)">${pct}% 已用</span>`;
  }
  return `<div class="traffic-cell"><strong>${u.total_human}</strong> <span style="color:var(--text-muted)">/ ${limit}</span>${bar}</div>`;
}

function actionButtons(u) {
  return `
    <div class="action-group">
      <button class="action-btn" onclick="showShare(${u.id})" title="分享/二维码">${ICONS.share}</button>
      <button class="action-btn" onclick="copyLink(${JSON.stringify(u.tg_link)})" title="复制链接">${ICONS.copy}</button>
      <button class="action-btn" onclick="openEditUser(${u.id})" title="编辑">${ICONS.edit}</button>
      <button class="action-btn" onclick="toggleUser(${u.id}, ${!u.raw_enabled})" title="${u.raw_enabled ? '禁用' : '启用'}">${ICONS.toggle}</button>
      <button class="action-btn danger" onclick="deleteUser(${u.id})" title="删除">${ICONS.delete}</button>
    </div>`;
}

function formatExpiry(exp) {
  if (!exp) return '<span style="color:var(--text-muted)">永久</span>';
  return new Date(exp).toLocaleDateString('zh-CN');
}

function formatLastSeen(ts) {
  if (!ts) return '<span style="color:var(--text-muted)">从未</span>';
  const diff = Date.now() - new Date(ts).getTime();
  if (diff < 0) return '刚刚';
  const m = Math.floor(diff / 60000);
  if (m < 1) return '刚刚';
  if (m < 60) return m + ' 分钟前';
  const h = Math.floor(m / 60);
  if (h < 24) return h + ' 小时前';
  const d = Math.floor(h / 24);
  if (d < 30) return d + ' 天前';
  return new Date(ts).toLocaleDateString('zh-CN');
}

let _allUsers = [];

function filterUsers() {
  const q = document.getElementById('user-search').value.trim().toLowerCase();
  const filtered = q ? _allUsers.filter(u => (u.remark || '').toLowerCase().includes(q)) : _allUsers;
  renderUsers(filtered, false);
}

function exportUsers() {
  if (!_allUsers.length) { toast('没有用户可导出', 'info'); return; }
  const lines = _allUsers.map(u => (u.remark || '未命名') + '\n' + u.tg_link + '\n');
  const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'mtproxy-users.txt';
  a.click();
  URL.revokeObjectURL(a.href);
  toast('已导出 ' + _allUsers.length + ' 个用户链接', 'success');
}

function renderUsers(users, save = true) {
  if (save) _allUsers = users;
  const tbody = document.getElementById('users-tbody');
  const cards = document.getElementById('users-cards');
  if (!users.length) {
    const empty = '<div class="empty-state">暂无用户，点击上方生成新密钥</div>';
    tbody.innerHTML = `<tr><td colspan="5">${empty}</td></tr>`;
    cards.innerHTML = empty;
    return;
  }

  tbody.innerHTML = users.map(u => `
    <tr>
      <td><div class="user-name">${esc(u.remark || '未命名')}</div><div class="user-secret">${u.secret.slice(0, 12)}…</div></td>
      <td>${statusBadge(u)}</td>
      <td>${trafficHtml(u)}<div style="font-size:0.72rem;color:var(--text-muted);margin-top:4px">↑${u.upload_human} ↓${u.download_human}</div></td>
      <td>${formatExpiry(u.expires_at)}</td>
      <td>${formatLastSeen(u.last_seen)}</td>
      <td>${actionButtons(u)}</td>
    </tr>
  `).join('');

  cards.innerHTML = users.map(u => `
    <div class="user-card">
      <div class="user-card-header">
        <div>
          <div class="user-name">${esc(u.remark || '未命名')}</div>
          <div class="user-secret">${u.secret.slice(0, 12)}…</div>
        </div>
        ${statusBadge(u)}
      </div>
      <div class="user-card-stats">
        <div><div class="stat-label">总流量</div>${u.total_human}</div>
        <div><div class="stat-label">配额</div>${u.traffic_limit_gb > 0 ? u.traffic_limit_gb + ' GB' : '不限'}</div>
        <div><div class="stat-label">上行</div>${u.upload_human}</div>
        <div><div class="stat-label">到期</div>${u.expires_at ? new Date(u.expires_at).toLocaleDateString('zh-CN') : '永久'}</div>
        <div><div class="stat-label">最后在线</div>${formatLastSeen(u.last_seen)}</div>
      </div>
      ${u.traffic_limit_gb > 0 ? trafficHtml(u) : ''}
      <div class="user-card-actions">
        <button class="btn btn-primary btn-sm" onclick="showShare(${u.id})">分享</button>
        <button class="btn btn-ghost btn-sm" onclick="copyLink(${JSON.stringify(u.tg_link)})">复制</button>
        <button class="btn btn-ghost btn-sm" onclick="openEditUser(${u.id})">编辑</button>
        <button class="btn btn-ghost btn-sm" onclick="toggleUser(${u.id}, ${!u.raw_enabled})">${u.raw_enabled ? '禁用' : '启用'}</button>
        <button class="btn btn-danger btn-sm" onclick="deleteUser(${u.id})">删除</button>
      </div>
    </div>
  `).join('');
}

async function refreshDashboard() {
  try {
    dashboardData = await api('/api/dashboard');
    renderStats(dashboardData);
    renderUsers(dashboardData.users);
  } catch (_) {}
}

// ===== 用户操作 =====
async function withLoading(fn) {
  setLoading(true);
  try { await fn(); } finally { setLoading(false); }
}

async function addUser() {
  const remark = document.getElementById('new-remark').value.trim();
  const limit = parseFloat(document.getElementById('new-limit').value) || 0;
  const expiresVal = document.getElementById('new-expires').value;
  const body = { remark, traffic_limit_gb: limit };
  if (expiresVal) body.expires_days = parseInt(expiresVal);
  await withLoading(async () => {
    try {
      await api('/api/users', { method: 'POST', body: JSON.stringify(body) });
      document.getElementById('new-remark').value = '';
      document.getElementById('new-expires').value = '';
      toast('密钥已生成，代理已重启', 'success');
      refreshDashboard();
    } catch (e) { toast(e.message, 'error'); }
  });
}

function openEditUser(id) {
  const u = dashboardData.users.find(x => x.id === id);
  if (!u) return;
  document.getElementById('edit-id').value = id;
  document.getElementById('edit-title').textContent = `编辑 — ${u.remark || '未命名'}`;
  document.getElementById('edit-remark').value = u.remark;
  document.getElementById('edit-limit').value = u.traffic_limit_gb;
  document.getElementById('edit-expires').value = '';
  show(document.getElementById('modal-edit'));
}

async function saveEditUser() {
  const id = parseInt(document.getElementById('edit-id').value);
  const body = {
    remark: document.getElementById('edit-remark').value.trim(),
    traffic_limit_gb: parseFloat(document.getElementById('edit-limit').value) || 0,
  };
  const days = document.getElementById('edit-expires').value;
  if (days !== '') body.expires_days = parseInt(days);
  await withLoading(async () => {
    try {
      await api(`/api/users/${id}`, { method: 'PUT', body: JSON.stringify(body) });
      toast('保存成功', 'success');
      closeModal('modal-edit');
      refreshDashboard();
    } catch (e) { toast(e.message, 'error'); }
  });
}

function resetUserTraffic() {
  const id = parseInt(document.getElementById('edit-id').value);
  confirmDialog('重置流量', '确认重置该用户的流量统计？此操作不可撤销。', async () => {
    await withLoading(async () => {
      try {
        await api(`/api/users/${id}`, { method: 'PUT', body: JSON.stringify({ reset_traffic: true }) });
        toast('流量已重置', 'success');
        refreshDashboard();
      } catch (e) { toast(e.message, 'error'); }
    });
  });
}

async function toggleUser(id, enabled) {
  await withLoading(async () => {
    try {
      await api(`/api/users/${id}`, { method: 'PUT', body: JSON.stringify({ enabled }) });
      toast(enabled ? '已启用' : '已禁用', 'success');
      refreshDashboard();
    } catch (e) { toast(e.message, 'error'); }
  });
}

function deleteUser(id) {
  confirmDialog('删除用户', '确认删除该用户？此操作不可恢复。', async () => {
    await withLoading(async () => {
      try {
        await api(`/api/users/${id}`, { method: 'DELETE' });
        toast('已删除', 'success');
        refreshDashboard();
      } catch (e) { toast(e.message, 'error'); }
    });
  });
}

async function showShare(id) {
  const user = dashboardData.users.find(u => u.id === id);
  if (!user) return;
  modalLink = user.tg_link;
  document.getElementById('modal-title').textContent = `分享 — ${user.remark || '未命名'}`;
  document.getElementById('modal-link').textContent = user.tg_link;
  // SOCKS5 信息
  try {
    const s = await api('/api/socks5/status');
    const server = dashboardData.proxy.public_ip || '';
    document.getElementById('modal-socks').innerHTML = `
      <div class="socks-row"><span>SOCKS5 服务器</span><code>${server}:${s.port}</code></div>
      <div class="socks-row"><span>用户名</span><code>${user.socks_user || ''}</code></div>
      <div class="socks-row"><span>密码</span><code>${user.socks_pass || ''}</code></div>`;
  } catch (e) { /* 忽略 */ }
  setLoading(true);
  try {
    const res = await fetch(`${API}/api/users/${id}/qrcode`, { headers: { Authorization: `Bearer ${token}` } });
    document.getElementById('modal-qr').src = URL.createObjectURL(await res.blob());
    show(document.getElementById('modal-share'));
  } catch (_) { toast('二维码加载失败', 'error'); }
  finally { setLoading(false); }
}

function closeModal(id, e) {
  if (e && e.target !== e.currentTarget) return;
  hide(document.getElementById(id));
}

function copyModalLink() { copyLink(modalLink); }

// 通用复制：优先 Clipboard API，HTTP 等非安全上下文降级到 execCommand
function copyText(text) {
  return new Promise((resolve, reject) => {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(resolve).catch(() => fallbackCopy(text) ? resolve() : reject());
    } else {
      fallbackCopy(text) ? resolve() : reject();
    }
  });
}

function fallbackCopy(text) {
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    return ok;
  } catch (e) { return false; }
}

function copyLink(link) {
  copyText(link).then(() => toast('链接已复制到剪贴板', 'success')).catch(() => {
    toast('复制失败，请手动复制', 'error');
  });
}

// ===== 设置 =====
async function loadSettings() {
  try {
    const s = await api('/api/settings');
    document.getElementById('set-proxy-port').value = s.proxy_port;
    document.getElementById('set-panel-port').value = s.panel_port;
    document.getElementById('set-domain').value = s.domain;
    document.getElementById('set-tls-mode').value = s.fake_tls_mode;
    document.getElementById('set-public-ip').value = s.public_ip;
    document.getElementById('set-adtag').value = s.adtag;
    document.getElementById('sec-username').value = s.admin_user;
  } catch (_) {}
}

async function saveSettings() {
  const body = {
    proxy_port: parseInt(document.getElementById('set-proxy-port').value),
    panel_port: parseInt(document.getElementById('set-panel-port').value),
    domain: document.getElementById('set-domain').value.trim(),
    fake_tls_mode: document.getElementById('set-tls-mode').value,
    public_ip: document.getElementById('set-public-ip').value.trim(),
    adtag: document.getElementById('set-adtag').value.trim(),
    skip_domain_check: document.getElementById('set-skip-domain').checked,
  };
  await withLoading(async () => {
    try {
      const res = await api('/api/settings', { method: 'PUT', body: JSON.stringify(body) });
      toast(res.message || '保存成功', 'success');
      refreshDashboard();
      loadSettings();
    } catch (e) { toast(e.message, 'error'); }
  });
}

async function saveAdmin() {
  const username = document.getElementById('sec-username').value.trim();
  const password = document.getElementById('sec-password').value;
  if (!username || password.length < 6) { toast('用户名和密码（至少6位）不能为空', 'error'); return; }
  await withLoading(async () => {
    try {
      await api('/api/settings/admin', { method: 'PUT', body: JSON.stringify({ username, password }) });
      toast('管理员已更新，请重新登录', 'success');
      setTimeout(logout, 1500);
    } catch (e) { toast(e.message, 'error'); }
  });
}

async function proxyAction(action) {
  await withLoading(async () => {
    try {
      const res = await api(`/api/proxy/${action}`, { method: 'POST' });
      toast(action === 'stop' ? '代理已停止' : (res.running ? '代理运行中' : '操作完成'), 'success');
      refreshDashboard();
    } catch (e) { toast(e.message, 'error'); }
  });
}

// ===== 主题切换 =====
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('mtp_theme', theme);
  document.getElementById('icon-moon').classList.toggle('hidden', theme === 'light');
  document.getElementById('icon-sun').classList.toggle('hidden', theme !== 'light');
}

function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme') || 'light';
  applyTheme(cur === 'dark' ? 'light' : 'dark');
  toast('已切换主题', 'info');
}

const savedTheme = localStorage.getItem('mtp_theme') || 'light';
document.documentElement.setAttribute('data-theme', savedTheme);
if (document.getElementById('icon-moon')) {
  document.getElementById('icon-moon').classList.toggle('hidden', savedTheme === 'light');
  document.getElementById('icon-sun').classList.toggle('hidden', savedTheme !== 'light');
}

// ===== 初始化 =====
document.getElementById('login-pass').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
if (token) showApp();
// ===== 服务器节点管理 =====
let _allNodes = [];

async function loadNodes() {
  try {
    _allNodes = await api('/api/nodes');
    renderNodes();
  } catch (e) { console.error('加载节点失败', e); }
}

function renderNodes() {
  const grid = document.getElementById('nodes-grid');
  const countEl = document.getElementById('node-count');
  // 本地节点 + 远程节点
  const total = _allNodes.length + 1;
  countEl.textContent = total + ' 台服务器';

  let html = `
    <div class="node-card node-local">
      <div class="node-card-header">
        <div>
          <div class="node-name">本机 <span class="badge success">本地</span></div>
          <div class="node-ip">${dashboardData.proxy.public_ip || '-'} : ${dashboardData.proxy.port || 443}</div>
        </div>
        <span class="badge ${dashboardData.proxy.running ? 'success' : 'danger'}">${dashboardData.proxy.running ? '运行中' : '已停止'}</span>
      </div>
      <div class="node-stats">
        <div><div class="stat-label">CPU</div>${Math.round(dashboardData.system.cpu_percent || 0)}%</div>
        <div><div class="stat-label">内存</div>${Math.round(dashboardData.system.mem_percent || 0)}%</div>
        <div><div class="stat-label">用户</div>${dashboardData.users ? dashboardData.users.length : 0}</div>
        <div><div class="stat-label">连接</div>${dashboardData.proxy.connections || 0}</div>
      </div>
    </div>`;

  for (const n of _allNodes) {
    const online = n.status === 'online';
    const lastSeen = n.last_seen ? formatLastSeen(n.last_seen) : '从未连接';
    html += `
    <div class="node-card ${online ? '' : 'node-offline'}">
      <div class="node-card-header">
        <div>
          <div class="node-name">${escapeHtml(n.name)}</div>
          <div class="node-ip">${escapeHtml(n.public_ip || n.host)} : ${n.proxy_port}</div>
        </div>
        <span class="badge ${online ? 'success' : 'danger'}">${online ? '在线' : '离线'}</span>
      </div>
      <div class="node-stats">
        <div><div class="stat-label">CPU</div>${online ? Math.round(n.cpu_percent || 0) + '%' : '-'}</div>
        <div><div class="stat-label">内存</div>${online ? Math.round(n.mem_percent || 0) + '%' : '-'}</div>
        <div><div class="stat-label">代理</div>${online ? (n.proxy_running ? '运行中' : '已停止') : '-'}</div>
        <div><div class="stat-label">最后在线</div>${lastSeen}</div>
      </div>
      <div class="node-card-actions">
        <button class="btn btn-ghost btn-sm" onclick="syncNode(${n.id})" ${online ? '' : 'disabled'}>同步用户</button>
        <button class="btn btn-ghost btn-sm" onclick="copyNodeLinks(${n.id})" ${online ? '' : 'disabled'}>复制链接</button>
        <button class="btn btn-ghost btn-sm" onclick="showEditNodeModal(${n.id})">编辑</button>
        <button class="btn btn-danger btn-sm" onclick="deleteNode(${n.id}, '${escapeHtml(n.name)}')">删除</button>
      </div>
    </div>`;
  }

  if (!_allNodes.length) {
    html += '<div class="empty-state">暂无远程服务器，点右上角添加</div>';
  }
  grid.innerHTML = html;
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function showAddNodeModal() {
  try {
    const data = await api('/api/nodes/install-command');
    document.getElementById('install-cmd-text').textContent = data.command;
    show(document.getElementById('modal-add-node'));
  } catch (e) { toast('获取安装命令失败', 'error'); }
}

function copyInstallCmd() {
  const txt = document.getElementById('install-cmd-text').textContent;
  copyText(txt).then(() => toast('安装命令已复制', 'success')).catch(() => toast('复制失败，请手动复制', 'error'));
}

async function syncNode(id) {
  try {
    const data = await api(`/api/nodes/${id}/sync`, { method: 'POST' });
    toast(data.status === 'ok' ? '用户已同步到节点' : '同步失败', data.status === 'ok' ? 'success' : 'error');
  } catch (e) { toast('同步失败', 'error'); }
}

async function copyNodeLinks(id) {
  // 复制该节点上所有用户的 tg 链接
  try {
    const links = [];
    for (const u of _allUsers) {
      try {
        const data = await api(`/api/nodes/${id}/link/${u.id}`);
        links.push(`${u.remark || '未命名'}\n${data.tg_link}\n`);
      } catch (e) { /* 跳过失败的 */ }
    }
    if (!links.length) { toast('没有可复制的链接', 'info'); return; }
    await copyText(links.join('\n'));
    toast(`已复制 ${links.length} 个链接`, 'success');
  } catch (e) { toast('复制失败', 'error'); }
}

async function deleteNode(id, name) {
  if (!confirm(`确定删除服务器「${name}」吗？该服务器上的代理不会自动卸载。`)) return;
  try {
    await api(`/api/nodes/${id}`, { method: 'DELETE' });
    toast('已删除', 'success'); loadNodes();
  } catch (e) { toast('删除失败', 'error'); }
}

// 切换到服务器 tab 时加载
const _origSwitchTab = switchTab;
switchTab = function(tab) {
  _origSwitchTab(tab);
  if (tab === 'nodes') loadNodes();
  if (tab === 'settings') loadSocks5Status();
  if (tab === 'forward') loadForward();
};

// ===== 编辑节点 =====
function showEditNodeModal(id) {
  const n = _allNodes.find(x => x.id === id);
  if (!n) return;
  document.getElementById('edit-node-id').value = id;
  document.getElementById('edit-node-name').value = n.name || '';
  document.getElementById('edit-node-port').value = n.proxy_port || 443;
  document.getElementById('edit-node-domain').value = n.domain || '';
  show(document.getElementById('modal-edit-node'));
}

async function saveNodeEdit() {
  const id = document.getElementById('edit-node-id').value;
  const body = {
    name: document.getElementById('edit-node-name').value.trim(),
    proxy_port: parseInt(document.getElementById('edit-node-port').value) || 443,
    domain: document.getElementById('edit-node-domain').value.trim(),
  };
  if (!body.name) { toast('名称不能为空', 'error'); return; }
  try {
    await api(`/api/nodes/${id}`, { method: 'PUT', body: JSON.stringify(body) });
    toast('已更新，节点代理正在重启', 'success');
    closeModal('modal-edit-node');
    loadNodes();
  } catch (e) { toast('更新失败', 'error'); }
}

// ===== SOCKS5 =====
async function loadSocks5Status() {
  try {
    const s = await api('/api/socks5/status');
    document.getElementById('set-socks5-port').value = s.port;
    document.getElementById('socks5-badge').innerHTML =
      `<span class="badge ${s.running ? 'success' : 'danger'}">${s.running ? '运行中' : '已停止'}</span>`;
  } catch (e) { /* 忽略 */ }
}

async function socks5Action(action) {
  try {
    const s = await api(`/api/socks5/${action}`, { method: 'POST' });
    toast(s.running ? 'SOCKS5 已启动' : 'SOCKS5 已停止', 'success');
    loadSocks5Status();
  } catch (e) { toast('操作失败', 'error'); }
}

async function socks5SavePort() {
  const port = parseInt(document.getElementById('set-socks5-port').value) || 1080;
  try {
    await api('/api/socks5/port', { method: 'PUT', body: JSON.stringify({ port }) });
    toast('端口已保存', 'success');
    loadSocks5Status();
  } catch (e) { toast('保存失败', 'error'); }
}

// ===== 端口转发 =====
let _forwardRules = [];
let _forwardChains = [];

async function loadForward() {
  try {
    const [rules, chains] = await Promise.all([
      api('/api/forward/rules'),
      api('/api/forward/chains'),
    ]);
    _forwardRules = rules;
    _forwardChains = chains;
    renderForwardRules();
    renderForwardChains();
  } catch (e) {
    toast('转发数据加载失败', 'error');
  }
}

function renderForwardChains() {
  const el = document.getElementById('chains-list');
  if (!_forwardChains.length) {
    el.innerHTML = '<p class="hint-text">暂无链路，点右上角"新建链路"创建。</p>';
    return;
  }
  el.innerHTML = _forwardChains.map(c => {
    const hops = c.rules.map((r, i) =>
      `<span class="chain-hop">${esc(r.listen_node_name)}:${r.listen_port}</span>` +
      (i < c.rules.length - 1 ? '<span class="chain-arrow">→</span>' : '')
    ).join('');
    const last = c.rules[c.rules.length - 1];
    const tail = last ? `<span class="chain-arrow">→</span><span class="chain-hop chain-target">${esc(last.target_host)}:${last.target_port}</span>` : '';
    const allRunning = c.rules.length > 0 && c.rules.every(r => r.running);
    return `
      <div class="chain-card">
        <div class="chain-card-head">
          <b>${esc(c.name)}</b>
          ${allRunning ? '<span class="badge on">畅通</span>' : '<span class="badge danger">有中断</span>'}
          <span style="flex:1"></span>
          <button class="btn btn-ghost btn-sm" onclick="deleteChain(${c.id})">删除</button>
        </div>
        <div class="chain-path">${hops}${tail}</div>
      </div>`;
  }).join('');
}

function renderForwardRules() {
  const el = document.getElementById('forward-rules-list');
  const single = _forwardRules.filter(r => !r.chain_id);
  if (!single.length) {
    el.innerHTML = '<p class="hint-text">暂无独立隧道，点右上角"添加隧道"创建。</p>';
    return;
  }
  el.innerHTML = '<div class="tunnel-grid">' + single.map(r => {
    const proto = (r.protocol || 'tcp').toUpperCase();
    const protoColor = r.protocol === 'udp' ? '#7c3aed' : r.protocol === 'both' ? '#0d9488' : '#1d9ad8';
    return `
    <div class="tunnel-card">
      <div class="tunnel-card-head">
        <b>${esc(r.name)}</b>
        ${r.running ? '<span class="badge on">运行中</span>' : '<span class="badge off">已停止</span>'}
      </div>
      <div class="tunnel-path">
        <span class="tunnel-node">${esc(r.listen_node_name)}<b>:${r.listen_port}</b></span>
        <span class="chain-arrow">→</span>
        <span class="tunnel-node tunnel-target">${esc(r.target_host)}<b>:${r.target_port}</b></span>
      </div>
      <div class="tunnel-meta">
        <span class="tunnel-tag" style="background:rgba(29,154,216,.1);color:${protoColor}">${proto}</span>
        ${r.user_name ? `<span class="tunnel-tag">👤 ${esc(r.user_name)}</span>` : ''}
        ${r.speed_limit_mbps > 0 ? `<span class="tunnel-tag">⚡ ${r.speed_limit_mbps}M</span>` : '<span class="tunnel-tag tunnel-tag-dim">⚡ 不限速</span>'}
        ${r.traffic_limit_gb > 0 ? `<span class="tunnel-tag">📦 ${r.traffic_limit_gb}G</span>` : ''}
      </div>
      <div class="tunnel-actions">
        ${r.running
          ? `<button class="btn btn-ghost btn-sm" onclick="toggleForward(${r.id}, false)">停止</button>`
          : `<button class="btn btn-primary btn-sm" onclick="toggleForward(${r.id}, true)">启动</button>`}
        <button class="btn btn-ghost btn-sm" onclick="deleteForwardRule(${r.id})">删除</button>
      </div>
    </div>`;
  }).join('') + '</div>';
}

let _fwNodesCache = [];
async function showAddForwardModal() {
  const [nodes, users] = await Promise.all([
    api('/api/nodes').catch(() => []),
    api('/api/users').catch(() => []),
  ]);
  _fwNodesCache = nodes;
  const sel = document.getElementById('fw-node');
  sel.innerHTML = '<option value="0">本机</option>' +
    nodes.map(n => `<option value="${n.id}">${esc(n.name)} (${esc(n.host)})</option>`).join('');
  const tsel = document.getElementById('fw-target-node');
  tsel.innerHTML = '<option value="">手动填 IP / 域名</option>' +
    nodes.map(n => `<option value="${n.id}">${esc(n.name)} (${esc(n.host)})</option>`).join('');
  tsel.onchange = () => {
    const nid = parseInt(tsel.value);
    const n = _fwNodesCache.find(x => x.id === nid);
    document.getElementById('fw-target-host').value = n ? (n.public_ip || n.host) : '';
    updateFwPreview();
  };
  const usel = document.getElementById('fw-user');
  usel.innerHTML = '<option value="0">不指定</option>' +
    users.map(u => `<option value="${u.id}">${esc(u.remark || '用户'+u.id)}</option>`).join('');
  const csel = document.getElementById('fw-chain');
  csel.innerHTML = '<option value="0">单条隧道</option>' +
    _forwardChains.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('');
  ['fw-name','fw-listen-port','fw-target-port','fw-target-host','fw-speed','fw-quota'].forEach(id => document.getElementById(id).value = '');
  document.getElementById('fw-protocol').value = 'tcp';
  // 实时预览
  ['fw-node','fw-listen-port','fw-target-host','fw-target-port'].forEach(id => {
    document.getElementById(id).oninput = updateFwPreview;
    document.getElementById(id).onchange = updateFwPreview;
  });
  updateFwPreview();
  show(document.getElementById('modal-add-forward'));
}

function updateFwPreview() {
  const nodeSel = document.getElementById('fw-node');
  const nodeName = nodeSel.options[nodeSel.selectedIndex]?.text?.split(' (')[0] || '本机';
  const lp = document.getElementById('fw-listen-port').value || '?';
  const th = document.getElementById('fw-target-host').value || '?';
  const tp = document.getElementById('fw-target-port').value || '?';
  document.getElementById('fw-preview-text').textContent =
    `${nodeName}:${lp}  →  ${th}:${tp}`;
}

async function saveForwardRule() {
  const body = {
    name: document.getElementById('fw-name').value.trim(),
    listen_node_id: parseInt(document.getElementById('fw-node').value),
    listen_port: parseInt(document.getElementById('fw-listen-port').value),
    target_host: document.getElementById('fw-target-host').value.trim(),
    target_port: parseInt(document.getElementById('fw-target-port').value),
    chain_id: parseInt(document.getElementById('fw-chain').value),
    protocol: document.getElementById('fw-protocol').value,
    user_id: parseInt(document.getElementById('fw-user').value) || 0,
    speed_limit_mbps: parseInt(document.getElementById('fw-speed').value) || 0,
    traffic_limit_gb: parseFloat(document.getElementById('fw-quota').value) || 0,
  };
  if (!body.listen_port || !body.target_host || !body.target_port) {
    toast('监听端口、目标地址、目标端口必填', 'error');
    return;
  }
  try {
    await api('/api/forward/rules', {method: 'POST', body: JSON.stringify(body)});
    closeModal('modal-add-forward');
    toast('转发规则已创建并启动', 'success');
    loadForward();
  } catch (e) {
    toast('创建失败: ' + e.message, 'error');
  }
}

async function toggleForward(id, start) {
  try {
    await api(`/api/forward/rules/${id}/${start ? 'start' : 'stop'}`, {method: 'POST'});
    toast(start ? '转发已启动' : '转发已停止', 'success');
    loadForward();
  } catch (e) {
    toast('操作失败: ' + e.message, 'error');
  }
}

async function deleteForwardRule(id) {
  if (!confirm('删除这条转发规则？')) return;
  try {
    await api(`/api/forward/rules/${id}`, {method: 'DELETE'});
    toast('已删除', 'success');
    loadForward();
  } catch (e) {
    toast('删除失败: ' + e.message, 'error');
  }
}

function showAddChainModal() {
  document.getElementById('chain-name').value = '';
  show(document.getElementById('modal-add-chain'));
}

async function saveForwardChain() {
  const name = document.getElementById('chain-name').value.trim();
  if (!name) { toast('链路名称必填', 'error'); return; }
  try {
    await api('/api/forward/chains', {method: 'POST', body: JSON.stringify({name})});
    closeModal('modal-add-chain');
    toast('链路已创建', 'success');
    loadForward();
  } catch (e) {
    toast('创建失败: ' + e.message, 'error');
  }
}

async function deleteChain(id) {
  if (!confirm('删除整条链路（含其中所有转发规则）？')) return;
  try {
    await api(`/api/forward/chains/${id}`, {method: 'DELETE'});
    toast('链路已删除', 'success');
    loadForward();
  } catch (e) {
    toast('删除失败: ' + e.message, 'error');
  }
}
