/* Identity is supplied by the overview's local cache. Only bootstrap/manual actions POST. */
(() => {
  const root = document.getElementById('reviewAccount');
  if (!root) return;
  const el = suffix => document.getElementById('reviewAccount' + suffix);
  const name = el('Name'), platform = el('Platform');
  const toggle = el('Toggle'), details = el('Details'), refreshButton = el('Refresh');
  const loginButton = el('Login'), loginStatus = el('LoginStatus');
  const loginPending = new Set(), loginMessages = new Map();
  let closeTimer;
  const cache = new Map(), pending = new Set(), attempted = new Set();
  let accountId = '';
  function cancelClose() { clearTimeout(closeTimer); }
  function openDetails() {
    cancelClose();
    details.hidden = false;
    toggle.setAttribute('aria-expanded', 'true');
  }
  function closeDetails() {
    cancelClose();
    details.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
  }
  function render(identity = {}) {
    const nickname = String(identity.nickname || '').trim();
    const handle = String(identity.uniqueId || '').trim();
    const identified = Boolean(nickname || handle);
    const busy = pending.has(accountId);
    const labels = {unbound:'未绑定抖音账号', login_required:'抖音待登录', logged_in:'昵称暂不可用', unread:'账号信息未读取', empty:'未选择账号'};
    name.textContent = identified ? nickname || handle : busy ? '正在读取账号…' : labels[identity.status] || '账号信息暂不可用';
    platform.hidden = !identified;
    el('Tip').textContent = identified ? [nickname, handle ? '抖音号：' + handle : '抖音号暂不可用'].filter(Boolean).join(' · ') : name.textContent;
    const date = identity.updatedAt ? new Date(identity.updatedAt) : null;
    const updated = date && !Number.isNaN(date.getTime()) ? '最近更新：' + date.toLocaleString('zh-CN', {timeZone:'Asia/Shanghai',hour12:false}) : '尚无成功读取记录';
    el('Updated').textContent = busy ? '正在更新账号信息…' : identity.status === 'login_required' ? '请重新登录 · ' + updated : identity.status === 'unknown' ? '更新未成功 · ' + updated : updated;
    refreshButton.disabled = !accountId || busy;
    refreshButton.textContent = '刷新账号信息';
    loginButton.hidden = !accountId || !['unbound', 'login_required'].includes(identity.status);
    loginButton.disabled = !accountId || loginPending.has(accountId);
    loginButton.textContent = loginPending.has(accountId) ? '正在打开…' : '授权帐号';
    loginStatus.textContent = loginMessages.get(accountId) || '';
    loginStatus.hidden = !loginStatus.textContent;
    toggle.setAttribute('aria-label', '查看抖音账号信息：' + name.textContent);
    root.setAttribute('aria-busy', String(busy));
  }
  function remember(id, data) {
    if (!data || data.accountId !== id) return;
    const previous = cache.get(id);
    // An overview started before a refresh must not restore an older snapshot.
    if (previous?.checkedAt && (!data.checkedAt || data.checkedAt < previous.checkedAt)) return;
    cache.set(id, data);
  }
  async function refresh(reason = 'manual') {
    if (!accountId || pending.has(accountId)) return;
    const current = accountId;
    if (reason === 'initial' && attempted.has(current)) return;
    attempted.add(current);
    pending.add(current);
    render(cache.get(current));
    try {
      const response = await fetch('/api/accounts/' + encodeURIComponent(current) + '/publish-identity', {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({reason})
      });
      if (!response.ok) throw new Error('identity unavailable');
      const data = await response.json();
      if (data.accountId !== current) throw new Error('identity account mismatch');
      remember(current, data);
    } catch (_) {
      cache.set(current, {...cache.get(current), accountId:current, status:'unknown', needsInitialRead:false});
    } finally {
      pending.delete(current);
      if (accountId === current) render(cache.get(current));
    }
  }
  async function authorize() {
    const current = accountId;
    if (!current || loginPending.has(current) || loginButton.hidden) return;
    loginPending.add(current);
    loginMessages.delete(current);
    render(cache.get(current));
    try {
      const response = await fetch('/api/accounts/' + encodeURIComponent(current) + '/publish-login', {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({platform:'douyin'})
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail?.message || data.message || '无法打开登录页，请重试。');
      loginMessages.set(current, '已打开登录页，请完成登录后点击“刷新账号信息”。');
    } catch (error) {
      loginMessages.set(current, error.message || '无法打开登录页，请重试。');
    } finally {
      loginPending.delete(current);
      if (accountId === current) render(cache.get(current));
    }
  }
  function updateFromOverview(id, data) {
    if (!data || data.accountId !== id || pending.has(id)) return;
    remember(id, data);
    if (accountId !== id) return;
    render(cache.get(id));
    if (cache.get(id)?.needsInitialRead && !attempted.has(id)) refresh('initial');
  }
  function onAccountChange(next) {
    accountId = String(next || '');
    closeDetails();
    render(cache.get(accountId) || {status:accountId ? 'unread' : 'empty'});
  }
  toggle.addEventListener('click', () => {
    details.hidden = !details.hidden;
    toggle.setAttribute('aria-expanded', String(!details.hidden));
  });
  root.addEventListener('pointerenter', event => { if (event.pointerType !== 'touch') openDetails(); });
  root.addEventListener('pointerleave', () => {
    cancelClose();
    closeTimer = setTimeout(() => { if (!root.contains(document.activeElement)) closeDetails(); }, 180);
  });
  root.addEventListener('focusin', cancelClose);
  root.addEventListener('focusout', event => { if (!root.contains(event.relatedTarget)) closeDetails(); });
  loginButton.addEventListener('click', authorize);
  refreshButton.addEventListener('click', () => refresh('manual'));
  document.addEventListener('click', event => { if (!root.contains(event.target)) closeDetails(); });
  root.addEventListener('keydown', event => { if (event.key === 'Escape') { closeDetails(); toggle.focus(); } });
  window.reviewAccountModule = {onAccountChange, updateFromOverview, refresh};
  closeDetails();
  render({status:'empty'});
})();
