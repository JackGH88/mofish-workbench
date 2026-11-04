/* Durable import snapshot + immediate SSE invalidation; synchronizes clean current content without navigation. */
(() => {
  let workbench = null, initialized = false, busy = false, again = false;
  let timer = null, failures = 0, delivering = false;
  const seen = new Set(), dirtyAccounts = new Map(), queue = [];
  let source = null;

  async function refresh() {
    if (document.hidden || !window.refreshImportedScriptList) return;
    for (const [accountId, notices] of [...dirtyAccounts]) {
      try {
        if (await window.refreshImportedScriptList(accountId, notices)) dirtyAccounts.delete(accountId);
      } catch (_) { /* Keep the account dirty for the next snapshot/focus. */ }
    }
  }

  async function deliver() {
    if (delivering || document.hidden || !queue.length || !window.WorkbenchReturnFeedback) return;
    delivering = true;
    const item = queue.shift();
    const generation = workbench;
    try {
      const action = item.result === 'updated' ? '脚本已更新' : item.result === 'reused' ? '已有相同脚本，已复用' : '脚本已回传';
      await window.WorkbenchReturnFeedback.notify(
        'script-import:' + JSON.stringify([generation, item.id]),
        `✓ ${item.accountName || '目标账号'} ·《${item.title || '未命名脚本'}》${action}${item.editorDeferred ? '；当前页面保留了本地编辑内容，请核对' : ''}`,
        true, () => workbench === generation);
    } finally {
      setTimeout(() => { delivering = false; deliver(); }, 2300);
    }
  }

  async function sync() {
    if (busy) { again = true; return; }
    clearTimeout(timer);
    busy = true;
    try {
      const response = await fetch('/api/script-import/notifications', {cache:'no-store'});
      if (!response.ok) throw new Error('import snapshot unavailable');
      const payload = await response.json();
      if (!payload.workbenchId || !Array.isArray(payload.items)) throw new Error('invalid import snapshot');
      if (workbench !== payload.workbenchId) {
        workbench = payload.workbenchId;
        initialized = false; seen.clear(); queue.length = 0; dirtyAccounts.clear();
      }
      for (const item of payload.items) {
        if (seen.has(item.id)) continue;
        seen.add(item.id);
        if (!dirtyAccounts.has(item.accountId)) dirtyAccounts.set(item.accountId, []);
        if (initialized) dirtyAccounts.get(item.accountId).push(item);
        if (initialized) queue.push(item);
      }
      initialized = true;
      await refresh();
      deliver();
      failures = 0;
    } catch (_) {
      failures += 1;
    } finally {
      busy = false;
      const delay = again ? 0 : Math.min(3000 * 2 ** Math.min(failures, 4), 30000);
      again = false;
      timer = setTimeout(sync, delay);
    }
  }

  function connect() {
    if (source || typeof EventSource === 'undefined') return;
    source = new EventSource('/api/script-import/events');
    const invalidate = () => {
      sync();
      // One SSE connection carries invalidations for both import and bound writing returns.
      window.dispatchEvent(new CustomEvent('workbench-scripts-changed'));
    };
    source.addEventListener('ready', invalidate);
    source.addEventListener('change', invalidate);
    source.onerror = () => { /* Native reconnect plus snapshot polling repairs missed events. */ };
  }
  function resume() { deliver(); sync(); }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) resume(); });
  window.addEventListener('focus', resume);
  window.addEventListener('pageshow', () => { connect(); resume(); });
  window.addEventListener('pagehide', () => { source?.close(); source = null; clearTimeout(timer); });
  connect();
  sync();
})();
