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

  grid.innerHTML = `
    ${donutHtml(sys.cpu_percent, `${sys.cpu_percent}%`, 'CPU', '处理器负载', 'var(--primary)')}
    ${donutHtml(sys.memory_percent, `${sys.memory_percent}%`, '内存', `${sys.memory_used_gb} / ${sys.memory_total_gb} GB`, 'var(--warning)')}
    ${donutHtml(sys.disk_percent, `${sys.disk_percent}%`, '磁盘', `剩余 ${sys.disk_free_gb} GB`, 'var(--purple)')}
    ${donutHtml(
      stats.total_users ? (stats.active_users / stats.total_users * 100) : 0,
      `${stats.active_users}/${stats.total_users}`,
      '活跃用户', stats.total_traffic_human, 'var(--success)'
    )}
    <div class="metric-card metric-wide">
      <div class="donut" style="--pct:${proxy.connections > 0 ? Math.min(proxy.connections * 10, 100) : 0};--donut-color:var(--cyan)">
        <span class="donut-value">${proxy.connections}</span>
      </div>
      <div class="metric-body">
        <div class="donut-label">在线连接</div>
        <div style="font-size:1.1rem;font-weight:600;margin:4px 0">
          ${proxy.running ? '<span class="badge on">代理运行中</span>' : '<span class="badge danger">代理已停止</span>'}
        </div>
        <div class="donut-sub">端口 ${proxy.port} · ${tlsLabel(proxy.fake_tls_mode)}</div>
      </div>
    </div>
  `;

  document.getElementById('proxy-status-badge').innerHTML =
    proxy.running ? '<span class="badge on">运行中</span>' : '<span class="badge danger">已停止</span>';

  document.getElementById('proxy-info').innerHTML = `
    <div class="proxy-info-item"><div class="label">公网 IP</div><div class="value">${esc(proxy.public_ip)}</div></div>
    <div class="proxy-info-item"><div class="label">代理端口</div><div class="value">${proxy.port}</div></div>
    <div class="proxy-info-item"><div class="label">伪装域名</div><div class="value">${esc(proxy.domain || '-')}</div></div>
    <div class="proxy-info-item"><div class="label">混淆模式</div><div class="value">${tlsLabel(proxy.fake_tls_mode)}</div></div>
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

function renderUsers(users) {
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

function copyLink(link) {
  navigator.clipboard.writeText(link).then(() => toast('链接已复制到剪贴板', 'success')).catch(() => {
    const ta = document.createElement('textarea');
    ta.value = link;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
    toast('链接已复制', 'success');
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
  const cur = document.documentElement.getAttribute('data-theme') || 'dark';
  applyTheme(cur === 'dark' ? 'light' : 'dark');
  toast('已切换主题', 'info');
}

const savedTheme = localStorage.getItem('mtp_theme') || 'dark';
document.documentElement.setAttribute('data-theme', savedTheme);
if (document.getElementById('icon-moon')) {
  document.getElementById('icon-moon').classList.toggle('hidden', savedTheme === 'light');
  document.getElementById('icon-sun').classList.toggle('hidden', savedTheme !== 'light');
}

// ===== 初始化 =====
document.getElementById('login-pass').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
if (token) showApp();