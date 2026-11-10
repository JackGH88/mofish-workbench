/* All-account sound delivery; the server owns deduplication, not page visibility. */
(() => {
  if (window.WorkbenchNativeReturnNotifications) return;
  const clientId = crypto.randomUUID();
  let busy = false, timer = null, receipt = null, nextPlayAt = 0;

  async function post(action, body) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch('/api/return-notifications/' + action, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body), cache: 'no-store', signal: controller.signal,
      });
      if (response.status === 409) return {expired: true};
      if (!response.ok) throw new Error('Sound delivery unavailable');
      return await response.json();
    } finally { clearTimeout(timeout); }
  }

  async function sync() {
    if (busy) return;
    busy = true;
    clearTimeout(timer);
    try {
      if (receipt) {
        // A lost acknowledgement must not replay an already emitted sound.
        await post('ack', receipt);
        receipt = null;
        return;
      }
      const feedback = window.WorkbenchReturnFeedback;
      if (Date.now() < nextPlayAt || !feedback?.canPlay()) return;
      const {item} = await post('claim', {clientId});
      if (!item) return;
      const identity = {id: item.id, token: item.token};
      if (await feedback.play()) {
        receipt = identity;
        nextPlayAt = Date.now() + 1000;
        await post('ack', receipt);
        receipt = null;
      } else {
        await post('release', identity);
      }
    } catch (_) {
      // Network failure leaves the durable record pending; retry on timer/unlock.
    } finally {
      busy = false;
      timer = setTimeout(sync, 1200);
    }
  }
  window.WorkbenchReturnSounds = {sync};
  window.addEventListener('focus', sync);
  window.addEventListener('pageshow', sync);
  window.addEventListener('workbench-scripts-changed', sync);
  window.addEventListener('pagehide', () => clearTimeout(timer));
  sync();
})();
