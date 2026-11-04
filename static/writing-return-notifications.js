/* Global writing returns are independent of navigation and editor selection. */
(() => {
  let previous = null;
  let timer = null;
  let busy = false;
  let again = false;
  const dirtyAccounts = new Map();
  let failures = 0;
  const queue = [];
  let delivering = false;
  const identity = item => JSON.stringify([item.accountId, item.scriptId]);
  const revision = item => JSON.stringify([item.taskId, item.appliedAt, item.submissionIds || []]);

  async function refresh() {
    if (document.hidden || !window.refreshImportedScriptList) return;
    for (const [accountId, notices] of [...dirtyAccounts]) {
      try {
        if (await window.refreshImportedScriptList(accountId, notices)) dirtyAccounts.delete(accountId);
      } catch (_) { /* Retry list/editor refresh even after the snapshot has advanced. */ }
    }
  }

  async function deliver() {
    if (delivering || document.hidden || !queue.length) return;
    delivering = true;
    const item = queue.shift();
    try {
      await window.WorkbenchReturnFeedback?.notify(
        'writing-return:' + identity(item) + ':' + revision(item),
        `✓《${item.title || '未命名脚本'}》脚本已回传${item.editorDeferred ? '；当前页面保留了本地编辑内容，请核对' : ''}`, true);
    } finally {
      // Give each script its own readable toast when several finish together.
      setTimeout(() => { delivering = false; deliver(); }, 2300);
    }
  }

  async function sync() {
    if (busy) { again = true; return; }
    clearTimeout(timer);
    busy = true;
    try {
      const response = await fetch('/api/writing-return-notifications', {cache: 'no-store'});
      if (!response.ok) throw new Error('return snapshot unavailable');
      const payload = await response.json();
      if (!Array.isArray(payload.items)) throw new Error('invalid return snapshot');
      const next = new Map(payload.items.map(item => [identity(item), item]));
      for (const [key, item] of next) {
        const old = previous?.get(key);
        if (old && old.status === item.status && revision(old) === revision(item)) continue;
        // This also discovers scripts created by another window or the breakdown page.
        const notice = {...item, result: 'updated'};
        if (!dirtyAccounts.has(item.accountId)) dirtyAccounts.set(item.accountId, []);
        const notices = dirtyAccounts.get(item.accountId);
        const index = notices.findIndex(value => value.scriptId === item.scriptId);
        if (index >= 0) notices[index] = notice;
        else notices.push(notice);
        if (previous && item.status === 'applied' && item.appliedAt && (!old || revision(old) !== revision(item))) {
          queue.push(notice);
        }
      }
      // Initial load establishes a baseline: opening historical scripts never replays returns.
      previous = next;
      failures = 0;
      await refresh();
      deliver();
    } catch (_) {
      failures += 1;
    } finally {
      busy = false;
      const delay = again ? 0 : Math.min(3000 * 2 ** Math.min(failures, 4), 30000);
      again = false;
      timer = setTimeout(sync, delay);
    }
  }

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) sync();
  });
  window.addEventListener('focus', sync);
  window.addEventListener('workbench-scripts-changed', sync);
  window.addEventListener('workspace-module-change', sync);
  window.addEventListener('pageshow', sync);
  window.addEventListener('pagehide', () => clearTimeout(timer));
  sync();
})();
