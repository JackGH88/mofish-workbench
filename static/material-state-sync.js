/* One read-only poller for the visible title/cover panel, including idle jobs. */
(() => {
  'use strict';
  window.createMaterialStateSync = ({ context, read, apply, status, delay = 1500,
    setTimer = setTimeout, clearTimer = clearTimeout }) => {
    let current = null, timer = null, abort = null, epoch = 0, failures = 0, fresh = null;
    const key = value => value ? JSON.stringify([value.accountId, value.scriptId, value.stage]) : '';
    const valid = (version, owner) => version === epoch && key(owner) === key(context());
    async function poll(initial = false) {
      const owner = current, version = epoch;
      if (!owner || !valid(version, owner)) return;
      abort = new AbortController();
      status(owner, { loading: initial, error: '' });
      try {
        const payload = await read(owner, abort.signal);
        if (!valid(version, owner)) return;
        apply(owner, payload);
        failures = 0;
        status(owner, { loading: false, error: '' });
      } catch (error) {
        if (!valid(version, owner)) return;
        failures += 1;
        status(owner, { loading: false, error: '状态同步失败，正在重试；已保留当前内容。' });
      } finally {
        if (valid(version, owner)) {
          abort = null;
          timer = setTimer(() => { timer = null; void poll(); }, Math.min(30000, delay * 2 ** Math.min(failures, 4)));
        }
      }
    }
    function sync(force = false) {
      const next = context();
      if (!force && key(next) === key(current)) return;
      epoch += 1;
      if (timer !== null) clearTimer(timer);
      timer = null;
      abort?.abort(); abort = null;
      if (current) status(current, { loading: false, error: '' });
      current = next; failures = 0;
      if (current) {
        // A freshly applied panel-state response is already authoritative. Start
        // normal background polling without flashing a second loading state.
        if (!force && fresh?.key === key(current) && Date.now() < fresh.until) {
          timer = setTimer(() => { timer = null; void poll(); }, delay);
        } else void poll(true);
      }
      fresh = null;
    }
    function seed(owner) { fresh = { key: key(owner), until: Date.now() + delay }; }
    return { sync, seed };
  };
})();
