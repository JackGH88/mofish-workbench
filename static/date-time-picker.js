/* Shared local-date controls. No network, storage or scheduling side effects. */
(function () {
  'use strict';
  const pad = n => String(n).padStart(2, '0');
  function localDate(y, m, d) { const x = new Date(0); x.setHours(12, 0, 0, 0); x.setFullYear(y, m, d); return x; }
  function formatDate(d) { return String(d.getFullYear()).padStart(4, '0') + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function parseDate(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || ''); if (!m || +m[1] < 1) return null;
    const d = localDate(+m[1], +m[2] - 1, +m[3]); return formatDate(d) === s ? d : null;
  }
  function parseTime(s) { const m = /^(\d{2}):(\d{2})$/.exec(s || ''); return m && +m[1] < 24 && +m[2] < 60 ? [+m[1], +m[2]] : null; }
  function parseValue(s, mode) {
    const date = mode === 'time' ? null : parseDate(mode === 'datetime' ? s.slice(0, 10) : s);
    const time = mode === 'date' ? null : parseTime(mode === 'datetime' ? s.slice(11) : s);
    if (mode === 'datetime' && (s.length !== 16 || s[10] !== ' ')) return null;
    return (mode === 'time' || date) && (mode === 'date' || time) ? { date, time } : null;
  }
  function monthDays(y, m) { const offset = (localDate(y, m, 1).getDay() + 6) % 7; return Array.from({ length: 42 }, (_, i) => localDate(y, m, 1 - offset + i)); }
  function shiftMonth(date, delta) { const first = localDate(date.getFullYear(), date.getMonth() + delta, 1); return localDate(first.getFullYear(), first.getMonth(), Math.min(date.getDate(), localDate(first.getFullYear(), first.getMonth() + 1, 0).getDate())); }
  const core = { parseDate, parseTime, parseValue, formatDate, monthDays, shiftMonth };
  if (typeof module !== 'undefined' && module.exports) module.exports = core;
  if (typeof document === 'undefined') return;
  const cssURL = new URL('date-time-picker.css?v=20261031-1', document.currentScript.src).href;
  const svg = path => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
  const arrow = direction => svg(`<path d="${direction === 'left' ? 'm14 6-6 6 6 6' : 'm10 6 6 6-6 6'}"/>`);
  const calendar = svg('<rect x="4" y="5" width="16" height="16" rx="3"/><path d="M8 3v4m8-4v4M4 11h16"/>');
  const clock = svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>');
  const mounted = new WeakMap(), roots = new WeakSet(); let active = null;
  function styles(root) {
    if (roots.has(root)) return; roots.add(root);
    const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = cssURL;
    (root === document ? document.head : root).append(link);
  }
  function ancestors(node) { const result = []; while (node) { if (node.nodeType === 1) result.push(node); node = node.parentNode || node.host; } return result; }
  function validTarget(a) {
    return a.input.isConnected && !a.input.disabled && !a.input.readOnly && a.input.value === a.initial && a.input.getClientRects().length > 0 &&
      !ancestors(a.input).some(n => n.hidden || (n.tagName === 'DIALOG' && !n.open));
  }
  function close(restore = true) {
    if (!active) return;
    const a = active; active = null; a.observer.disconnect(); cancelAnimationFrame(a.frame);
    clearTimeTimers(a); a.pop.close(); a.pop.remove(); a.button.setAttribute('aria-expanded', 'false');
    if (restore && a.button.isConnected && a.input.getClientRects().length) a.button.focus({ preventScroll: true });
  }
  function closeScope(root) { if (active && (root === document || root === active.input || root.contains(active.input))) close(false); }
  function position(a) {
    if (active !== a) return;
    if (!validTarget(a)) { close(false); return; }
    const r = a.wrap.getBoundingClientRect(), p = a.pop;
    const top = r.bottom + 8 + p.offsetHeight <= innerHeight - 12 ? r.bottom + 8 : r.top - p.offsetHeight - 8;
    p.style.left = Math.max(12, Math.min(r.left, innerWidth - p.offsetWidth - 12)) + 'px';
    p.style.top = Math.max(12, Math.min(top, innerHeight - p.offsetHeight - 12)) + 'px';
  }
  function commit(a, value) {
    if (active !== a || !validTarget(a)) { close(false); return; }
    close(); a.input.value = value; a.input.setCustomValidity('');
    a.input.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
    a.input.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
  }
  function readTime(a) {
    if (a.mode === 'date') return true;
    const h = a.pop.querySelector('[data-hour]'), m = a.pop.querySelector('[data-minute]');
    if (!/^\d{1,2}$/.test(h.value) || +h.value > 23) { h.setCustomValidity('请输入 0–23 的小时'); h.reportValidity(); return false; }
    if (!/^\d{1,2}$/.test(m.value) || +m.value > 59) { m.setCustomValidity('请输入 0–59 的分钟'); m.reportValidity(); return false; }
    a.hour = +h.value; a.minute = +m.value; return true;
  }
  function clearTimeTimers(a) {
    a.pop.querySelectorAll('.dt-time-list').forEach(list => clearTimeout(list.snapTimer));
  }
  function setTime(a, list, value, center = false) {
    const part = list.dataset.part, buttons = list.querySelectorAll('button');
    value = Math.max(0, Math.min(buttons.length - 1, value));
    a[part] = value;
    const input = a.pop.querySelector(`[data-${part}]`);
    input.value = pad(value); input.setCustomValidity('');
    buttons.forEach((b, i) => { b.classList.toggle('is-selected', i === value); b.setAttribute('aria-pressed', String(i === value)); b.tabIndex = i === value ? 0 : -1; });
    if (center) { clearTimeout(list.snapTimer); list.scrollTop = value * 30; }
    list.lastTop = list.scrollTop;
  }
  function readWheel(a, list) {
    if (Math.abs(list.scrollTop - (list.lastTop ?? list.scrollTop)) < .1) return;
    setTime(a, list, Math.round(list.scrollTop / 30));
  }
  function centerTimes(a) {
    a.pop.querySelectorAll('.dt-time-list').forEach(list => setTime(a, list, a[list.dataset.part], true));
  }
  function bindTimes(a) {
    a.pop.querySelectorAll('.dt-time-list').forEach(list => {
      list.addEventListener('scroll', () => {
        if (active !== a || !list.isConnected || Math.abs(list.scrollTop - list.lastTop) < .1) return;
        readWheel(a, list);
        clearTimeout(list.snapTimer);
        list.snapTimer = setTimeout(() => { if (active === a && list.isConnected) setTime(a, list, a[list.dataset.part], true); }, 120);
      });
    });
  }
  function render(a, focusSelector) {
    clearTimeTimers(a);
    let html = '<div class="dt-body">';
    if (a.mode !== 'time') {
      html += `<section class="dt-date-panel"><div class="dt-head"><button type="button" data-action="months" class="dt-month">${a.year}年 ${a.month + 1}月</button><button type="button" class="dt-icon" data-action="prev" aria-label="上个月">${arrow('left')}</button><button type="button" class="dt-icon" data-action="next" aria-label="下个月">${arrow('right')}</button></div>`;
      if (a.monthView) {
        html += `<label class="dt-year">年份<input data-year type="number" min="1" max="9999" value="${a.year}" aria-label="年份"></label><div class="dt-months">${Array.from({ length: 12 }, (_, i) => `<button type="button" data-month="${i}" class="${i === a.month ? 'is-selected' : ''}">${i + 1}月</button>`).join('')}</div>`;
      } else {
        html += '<div class="dt-week">' + ['一', '二', '三', '四', '五', '六', '日'].map(d => `<span>${d}</span>`).join('') + '</div><div class="dt-days">';
        html += monthDays(a.year, a.month).map(d => {
          const value = formatDate(d), selected = value === a.date;
          return `<button type="button" data-date="${value}" aria-label="${value}" aria-pressed="${selected}" ${d.getFullYear() < 1 || d.getFullYear() > 9999 ? 'disabled' : ''} class="${d.getMonth() !== a.month ? 'is-other ' : ''}${value === formatDate(new Date()) ? 'is-today ' : ''}${selected ? 'is-selected' : ''}">${d.getDate()}</button>`;
        }).join('') + '</div>';
      }
    }
    if (a.mode !== 'time') html += '</section>';
    if (a.mode !== 'date') html += `<section class="dt-time-panel"><p class="dt-time-title">时间 · 24 小时制</p><div class="dt-time-inputs"><input data-hour aria-label="小时" inputmode="numeric" maxlength="2" value="${pad(a.hour)}"><span>:</span><input data-minute aria-label="分钟" inputmode="numeric" maxlength="2" value="${pad(a.minute)}"></div><div class="dt-time-lists">${[['hour', 24, a.hour], ['minute', 60, a.minute]].map(([part, count, val]) => `<div class="dt-time-wheel"><div class="dt-time-highlight" aria-hidden="true"></div><div class="dt-time-list" data-part="${part}" tabindex="0" aria-label="${part === 'hour' ? '小时' : '分钟'}列表">${Array.from({ length: count }, (_, i) => `<button type="button" data-part="${part}" data-value="${i}" aria-pressed="${i === val}" class="${i === val ? 'is-selected' : ''}">${pad(i)}</button>`).join('')}</div></div>`).join('')}</div></section>`;
    html += '</div>';
    html += `<div class="dt-footer">${a.mode !== 'time' ? '<button type="button" data-action="today">今天</button>' : ''}${a.clearable ? '<button type="button" data-action="clear">清空</button>' : ''}<button type="button" class="dt-cancel" data-action="cancel">取消</button>${a.mode !== 'date' ? '<button type="button" class="dt-primary" data-action="confirm">确定</button>' : ''}</div>`;
    a.pop.innerHTML = html;
    centerTimes(a); bindTimes(a);
    position(a);
    if (focusSelector) a.pop.querySelector(focusSelector)?.focus({ preventScroll: true });
  }
  function open(input) {
    const config = mounted.get(input); if (!config || input.disabled || input.readOnly) return;
    close(false); const parsed = parseValue(input.value, config.mode), date = parsed?.date || new Date();
    const pop = document.createElement('dialog'); pop.className = 'wb-datetime-popup'; pop.dataset.mode = config.mode; pop.setAttribute('aria-label', '日期时间选择');
    const a = { ...config, input, pop, initial: input.value, year: date.getFullYear(), month: date.getMonth(), date: formatDate(date), hour: parsed?.time?.[0] ?? 10, minute: parsed?.time?.[1] ?? 30, monthView: false };
    a.observer = new MutationObserver(() => { if (!validTarget(a)) close(false); });
    active = a; document.body.append(pop); render(a); pop.showModal(); position(a); centerTimes(a); a.button.setAttribute('aria-expanded', 'true');
    (pop.querySelector('.dt-days .is-selected') || pop.querySelector('input,button'))?.focus({ preventScroll: true });
    for (const node of ancestors(input)) a.observer.observe(node, { attributes: true, attributeFilter: ['open', 'hidden', 'class', 'style', 'disabled', 'readonly'], childList: true });
    // Detect programmatic value refills and detached/hidden forms without wrapping .value setters.
    const check = () => { if (active !== a) return; if (!validTarget(a)) { close(false); return; } a.frame = requestAnimationFrame(check); }; a.frame = requestAnimationFrame(check);
    pop.addEventListener('cancel', e => { e.preventDefault(); e.stopPropagation(); close(); });
    pop.addEventListener('click', e => {
      e.stopPropagation(); const b = e.target.closest('button'); if (!b || b.disabled) return;
      const action = b.dataset.action;
      if (action === 'cancel') return close();
      if (action === 'clear') return commit(a, '');
      a.pop.querySelectorAll('.dt-time-list').forEach(list => readWheel(a, list));
      if (!readTime(a)) return;
      if (b.dataset.date) { a.date = b.dataset.date; if (a.mode === 'date') return commit(a, a.date); }
      if (b.dataset.month !== undefined) { a.month = +b.dataset.month; a.monthView = false; }
      if (b.dataset.part) { setTime(a, b.closest('.dt-time-list'), +b.dataset.value, true); b.focus({ preventScroll: true }); return; }
      if (action === 'months') a.monthView = !a.monthView;
      if (action === 'prev' || action === 'next') { const d = localDate(a.year, a.month + (action === 'prev' ? -1 : 1), 1); if (d.getFullYear() >= 1 && d.getFullYear() <= 9999) { a.year = d.getFullYear(); a.month = d.getMonth(); } }
      if (action === 'today') { const now = new Date(); a.date = formatDate(now); a.year = now.getFullYear(); a.month = now.getMonth(); a.monthView = false; if (a.mode === 'date') return commit(a, a.date); }
      if (action === 'confirm') return commit(a, (a.mode === 'datetime' ? a.date + ' ' : '') + pad(a.hour) + ':' + pad(a.minute));
      render(a, b.dataset.date ? `[data-date="${a.date}"]` : b.dataset.part ? `[data-part="${b.dataset.part}"][data-value="${b.dataset.value}"]` : action ? `[data-action="${action}"]` : '[data-action="months"]');
    });
    pop.addEventListener('input', e => {
      if (e.target.matches('input')) e.target.setCustomValidity('');
      const part = e.target.hasAttribute('data-hour') ? 'hour' : e.target.hasAttribute('data-minute') ? 'minute' : null;
      if (part && /^\d{1,2}$/.test(e.target.value) && +e.target.value < (part === 'hour' ? 24 : 60)) {
        const raw = e.target.value;
        setTime(a, pop.querySelector(`.dt-time-list[data-part="${part}"]`), +raw, true);
        e.target.value = raw;
      }
    });
    pop.addEventListener('change', e => { if (e.target.hasAttribute('data-year')) { const n = +e.target.value; if (Number.isInteger(n) && n >= 1 && n <= 9999) { a.year = n; a.pop.querySelector('[data-action="months"]').textContent = a.year + '年 ' + (a.month + 1) + '月'; } else { e.target.setCustomValidity('请输入 1–9999 的年份'); e.target.reportValidity(); } } });
    pop.addEventListener('keydown', e => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); return; }
      const list = e.target.closest('.dt-time-list');
      if (list && ['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) {
        e.preventDefault(); readWheel(a, list);
        const value = e.key === 'Home' ? 0 : e.key === 'End' ? list.children.length - 1 : a[list.dataset.part] + (e.key === 'ArrowUp' ? -1 : 1);
        setTime(a, list, value, true);
        list.querySelector('.is-selected').focus({ preventScroll: true }); return;
      }
      const day = e.target.dataset.date;
      if (day && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown'].includes(e.key)) {
        e.preventDefault(); if (!readTime(a)) return; let d = parseDate(day); const offset = (d.getDay() + 6) % 7;
        if (e.key.startsWith('Page')) d = shiftMonth(d, e.key === 'PageUp' ? -1 : 1);
        else d.setDate(d.getDate() + ({ ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7, Home: -offset, End: 6 - offset })[e.key]);
        if (d.getFullYear() < 1 || d.getFullYear() > 9999) return;
        a.year = d.getFullYear(); a.month = d.getMonth(); render(a, `[data-date="${formatDate(d)}"]`);
      }
      if (e.key === 'Enter' && e.target.matches('[data-hour],[data-minute]')) { e.preventDefault(); pop.querySelector('[data-action="confirm"]').click(); }
    });
  }
  function attach(input, options = {}) {
    if (mounted.has(input)) return mounted.get(input);
    const mode = options.mode || input.dataset.dateTime || input.type;
    if (!['date', 'time', 'datetime'].includes(mode)) return null;
    styles(input.getRootNode()); styles(document);
    const native = input.type, value = input.value; input.type = 'text'; input.value = value;
    input.dataset.dateTime = mode; input.autocomplete = 'off'; input.placeholder ||= mode === 'date' ? 'YYYY-MM-DD' : mode === 'time' ? 'HH:mm' : 'YYYY-MM-DD HH:mm';
    const wrap = document.createElement('span'); wrap.className = 'wb-datetime-control'; input.before(wrap); wrap.append(input);
    const button = document.createElement('button'); button.type = 'button'; button.className = 'wb-datetime-trigger'; button.setAttribute('aria-label', mode === 'date' ? '选择日期' : mode === 'time' ? '选择时间' : '选择日期和时间'); button.setAttribute('aria-haspopup', 'dialog'); button.setAttribute('aria-expanded', 'false'); button.innerHTML = mode === 'time' ? clock : calendar; wrap.append(button);
    const config = { mode, wrap, button, clearable: options.clearable ?? (input.dataset.dateTimeClearable !== 'false' && mode === 'date' && !input.required) }; mounted.set(input, config);
    button.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); open(input); });
    input.addEventListener('keydown', e => { if (e.key === 'ArrowDown' && e.altKey) { e.preventDefault(); open(input); } });
    if (native === 'date' || native === 'time') {
      const validate = () => {
        let message = input.value && !parseValue(input.value, mode) ? (mode === 'date' ? '请输入有效日期，格式 YYYY-MM-DD' : '请输入有效时间，格式 HH:mm') : '';
        if (!message && input.value && ((input.min && input.value < input.min) || (input.max && input.value > input.max))) message = '请选择允许范围内的日期或时间';
        input.setCustomValidity(message);
      };
      config.validate = validate;

      input.addEventListener('input', validate); input.addEventListener('change', validate);
    }
    const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    Object.defineProperty(input, 'value', { configurable: true, get() { return descriptor.get.call(this); }, set(value) { descriptor.set.call(this, value); config.validate?.(); if (active?.input === this && this.value !== active.initial) close(false); } });
    const sync = () => { button.disabled = input.disabled || input.readOnly; if (!input.value) input.setCustomValidity(''); };
    new MutationObserver(sync).observe(input, { attributes: true, attributeFilter: ['disabled', 'readonly', 'value'] }); sync();
    return config;
  }
  function validateInputs(...inputs) { for (const input of inputs) { if (!input || input.disabled) continue; mounted.get(input)?.validate?.(); if (!input.reportValidity()) return false; } return true; }
  function enhance(root = document) { styles(root === document ? document : root.getRootNode()); root.querySelectorAll('input[type="date"],input[type="time"],input[data-date-time]').forEach(input => attach(input)); }
  document.addEventListener('pointerdown', e => { if (!active) return; const r = active.pop.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) close(); }, true);
  window.addEventListener('resize', () => { if (active) position(active); });
  document.addEventListener('scroll', () => { if (active) position(active); }, true);
  window.WorkbenchDateTimePicker = { ...core, attach, enhance, open, close, closeScope, arrow, validateInputs };
  enhance();
  new MutationObserver(records => { for (const r of records) for (const n of r.addedNodes) if (n.nodeType === 1 && !n.closest('.wb-datetime-popup,.wb-datetime-control')) { if (n.matches('input[type="date"],input[type="time"]')) attach(n); enhance(n); } }).observe(document.body, { childList: true, subtree: true });
})();
