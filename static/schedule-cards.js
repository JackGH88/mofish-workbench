/* Account-scoped schedule indicators; the editor panel need not be mounted. */
(() => {
  'use strict';
  let items = {}, account = null, generation = 0, stop = null;
  let connected = false, timer = null, pending = false, again = false;
  const host = () => window.WorkbenchPlugins;
  const currentAccount = () => window.WorkbenchScriptContext?.()?.accountId || null;
  const available = () => host()?.isAvailable('heygen');
  const shapes = {clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',check:'<circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/>',loader:'<path d="M21 12a9 9 0 1 1-6.2-8.55"/><path d="M16 3h5v5"/>',send:'<path d="m21 3-6 18-4-8-8-4 18-6Z"/><path d="m11 13 10-10"/>',scissors:'<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="m8.2 8.2 12.8 12.8M8.2 15.8 20 4"/>',question:'<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 5 .4c0 1.8-2.5 1.9-2.5 3.6M12 17h.01"/>',link:'<path d="m10 13 4-4M8 15l-1 1a3.5 3.5 0 0 1-5-5l4-4a3.5 3.5 0 0 1 5 0M16 9l1-1a3.5 3.5 0 0 1 5 5l-4 4a3.5 3.5 0 0 1-5 0" transform="translate(0 -1)"/>',error:'<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6m0-6-6 6"/>',missed:'<path d="M21 11a9 9 0 1 0-9 10M12 7v5l3 2M20 15v3M20 21h.01"/>'};
  const icons = {
    scheduled: ['clock', '已安排定时剪辑'],
    running: ['loader', '正在准备定时剪辑'],
    sending: ['send', '正在启动剪辑助手'],
    editing: ['scissors', '助手正在剪辑，等待成片回传'],
    send_uncertain: ['question', '发送结果待确认，请检查剪辑助手'],
    linking: ['link', '成片等待确认回传关联'],
    failed: ['error', '定时剪辑失败'],
    missed: ['missed', '已错过计划时间'],
    completed: ['check', '成片已回传并关联脚本'],
  };
  // Reuse existing visual styles, but keep publishing progress distinct from video linking.
  const postStates = {
    waiting_video: ['editing', '等待视频回传后生成发布素材'],
    waiting_host: ['send_uncertain', '成片已回传 · 等待工作台升级以生成发布素材'],
    title: ['running', '成片已回传 · 正在生成标题'],
    prompt: ['running', '成片已回传 · 正在生成封面提示词'],
    covers: ['running', '成片已回传 · 正在生成两种比例封面'],
    failed: ['failed', '成片已回传 · 发布素材生成失败'],
    paused: ['send_uncertain', '成片已回传 · 发布素材生成已暂停'],
    completed: ['completed', '标题及两种比例封面已完成 · 待确认'],
  };
  function postState(item) {
    const stage = item.postProcessing?.stage;
    // While waiting for video, retain scheduling / assistant / failure status.
    if (stage === 'waiting_video' && item.status !== 'completed') return null;
    return Object.hasOwn(postStates, stage) ? postStates[stage] : null;
  }
  function visualState(item) {
    const post = postState(item);
    if (post) return post[0];
    if (item.display === 'completed') return 'completed';
    if (item.status === 'completed' || (item.display === 'waiting' && item.publishStatus)) return 'linking';
    if (['failed', 'missed', 'send_uncertain'].includes(item.status)) return item.status;
    if (item.display === 'editing') return 'editing';
    if (item.status === 'sent') return item.display === 'waiting' ? 'linking' : 'editing';
    return ['scheduled', 'running', 'sending'].includes(item.status) ? item.status : 'scheduled';
  }
  let menu = null, anchor = null, closeTimer = null, restoringFocus = false;
  function closeMenu(restoreFocus = false) {
    clearTimeout(closeTimer);
    const previous = anchor;
    menu?.remove(); menu = null; anchor = null;
    previous?.setAttribute('aria-expanded', 'false');
    if (restoreFocus && previous?.isConnected) { restoringFocus = true; previous.focus(); restoringFocus = false; }
  }
  function deferClose() { clearTimeout(closeTimer); closeTimer = setTimeout(closeMenu, 180); }
  function positionMenu() {
    if (!menu || !anchor) return;
    const box = anchor.getBoundingClientRect(), bounds = menu.getBoundingClientRect();
    const below = box.bottom + 6;
    const preferredTop = below + bounds.height <= window.innerHeight - 8
      ? below : box.top - bounds.height - 6;
    menu.style.left = Math.max(8, Math.min(box.right - bounds.width, window.innerWidth - bounds.width - 8)) + 'px';
    menu.style.top = Math.max(8, Math.min(preferredTop, window.innerHeight - bounds.height - 8)) + 'px';
  }
  function openMenu(icon, focusAction = false) {
    clearTimeout(closeTimer);
    if (anchor === icon && menu) {
      if (focusAction) menu.querySelector('button').focus();
      return;
    }
    closeMenu();
    const item = icon.cardItem, sid = item.scriptId || icon.cardScriptId;
    const owner = account, epoch = generation;
    anchor = icon;
    menu = document.createElement('div');
    menu.className = 'script-card-status-menu';
    menu.setAttribute('role', 'dialog');
    menu.setAttribute('aria-label', '剪辑状态');
    const caption = document.createElement('div');
    caption.className = 'script-card-status-caption'; caption.textContent = icon.title;
    const hide = document.createElement('button'); hide.type = 'button';
    hide.textContent = '隐藏本次状态';
    menu.append(caption, hide); document.body.append(menu);
    icon.setAttribute('aria-expanded', 'true');
    menu.onmouseenter = () => clearTimeout(closeTimer);
    menu.onmouseleave = deferClose;
    menu.onfocusin = () => clearTimeout(closeTimer);
    menu.onfocusout = event => { if (!menu?.contains(event.relatedTarget) && event.relatedTarget !== anchor) deferClose(); };
    menu.onclick = event => event.stopPropagation();
    menu.onkeydown = event => { if (event.key === 'Escape') { event.preventDefault(); closeMenu(true); } };
    positionMenu();
    hide.onclick = async event => {
      event.stopPropagation(); hide.disabled = true;
      try {
        await host().api.pluginFetch('heygen', 'POST', '/studio/scripts/' + encodeURIComponent(sid)
          + '/card-status/' + item.source + '/' + encodeURIComponent(item.id) + '/hide', {}, owner);
        if (epoch !== generation || owner !== currentAccount()) return;
        // Do not hide a newer task which arrived while this request was in flight.
        if (items[sid]?.id === item.id && items[sid]?.source === item.source) items[sid].display = 'hidden';
        closeMenu(); render(); refresh();
      } catch (error) {
        if (epoch !== generation || owner !== currentAccount()) return;
        hide.disabled = false;
        caption.textContent = error.message || '隐藏失败，请重试。';
        caption.setAttribute('role', 'alert');
        positionMenu();
      }
    };
    if (focusAction) hide.focus();
  }
  function bindIcon(icon) {
    icon.tabIndex = 0;
    icon.setAttribute('aria-haspopup', 'dialog');
    icon.setAttribute('aria-expanded', 'false');
    icon.onmouseenter = () => openMenu(icon);
    icon.onmouseleave = deferClose;
    icon.onfocus = () => { if (!restoringFocus) openMenu(icon); };
    icon.onblur = event => { if (!menu?.contains(event.relatedTarget)) deferClose(); };
    icon.onclick = event => { event.preventDefault(); event.stopPropagation(); openMenu(icon, true); };
    icon.onkeydown = event => {
      if (['Enter', ' ', 'ArrowDown'].includes(event.key)) {
        event.preventDefault(); event.stopPropagation(); openMenu(icon, true);
      } else if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeMenu(); }
    };
    icon.onkeyup = event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); event.stopPropagation(); } };
  }
  function render() {
    if (anchor?.isConnected === false) closeMenu();
    for (const card of document.querySelectorAll('#historyList .history-record')) {
      const item = account === currentAccount() ? items[card.dataset.scriptId] : null;
      let icon = card.querySelector('.script-schedule-status');
      const visible = item && !['cancelled', 'stopped'].includes(item.status) && item.display !== 'hidden';
      card.classList.toggle('has-schedule-status', !!visible);
      if (!visible) { if (anchor === icon) closeMenu(); icon?.remove(); continue; }
      if (!icon) { icon = document.createElement('i'); bindIcon(icon); card.append(icon); }
      if (anchor === icon && (icon.cardItem?.id !== item.id || icon.cardItem?.source !== item.source)) closeMenu();
      icon.cardItem = item; icon.cardScriptId = card.dataset.scriptId;
      const state = visualState(item);
      const [shape, label] = icons[state];
      const post = postState(item);
      const text = post ? post[1] : item.executionMode === 'immediate' ? ({scheduled: '立即剪辑待启动', running: '正在准备立即剪辑', failed: '立即剪辑失败'}[state] || label) : item.source === 'manual' ? ({running: '正在准备剪辑', editing: '已提交剪辑，等待成片回传', failed: '剪辑启动失败'}[state] || label) : label;
      if (icon.dataset.visualState !== state) {
        icon.className = 'script-schedule-status is-' + state;
        const drawing = ['loader', 'send', 'scissors', 'link'].includes(shape)
          ? '<g transform="translate(12 12) scale(0.84) translate(-12 -12)">' + shapes[shape] + '</g>'
          : shapes[shape];
        icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + drawing + '</svg>';
        icon.dataset.visualState = state;
      }
      icon.dataset.state = item.display;
      const date = new Date(item.scheduledAt);
      const when = item.executionMode === 'immediate' || Number.isNaN(date.getTime()) ? '' : date.toLocaleString('zh-CN', { hour12: false });
      icon.title = [text, when, post && item.postProcessing.message, post && item.postProcessing.error, item.error].filter(Boolean).join(' · ');
      icon.setAttribute('role', 'button'); icon.setAttribute('aria-label', icon.title + '，隐藏本次状态');
      if (anchor === icon && menu && !menu.querySelector('button').disabled) {
        menu.querySelector('.script-card-status-caption').textContent = icon.title;
        positionMenu();
      }
    }
  }
  function schedulePoll() {
    clearTimeout(timer); timer = null;
    if (account && available() && !connected && !document.hidden)
      timer = setTimeout(refresh, 10000);
  }
  async function refresh() {
    if (!account || !available() || document.hidden) return;
    if (pending) { again = true; return; }
    const epoch = generation, owner = account;
    pending = true;
    try {
      const result = await host().api.pluginFetch('heygen', 'GET', '/studio/schedules/cards', undefined, owner);
      if (epoch !== generation || owner !== currentAccount()) return;
      items = result.items || {}; render();
    } catch (_) { /* Preserve the last known state on transient failures. */ }
    finally {
      if (epoch === generation) {
        pending = false;
        if (again) { again = false; refresh(); } else schedulePoll();
      }
    }
  }
  function reset() {
    closeMenu();
    generation++; stop?.(); stop = null; clearTimeout(timer); timer = null;
    items = {}; account = currentAccount(); connected = false; pending = false; again = false;
    render();
  }
  function connect() {
    if (account !== currentAccount()) reset();
    if (!available()) { reset(); return; }
    if (!account) return;
    if (!stop) stop = host().watchChanges('heygen', event => {
      if (event.type === 'disconnected') { connected = false; schedulePoll(); return; }
      if (event.type === 'connected') { connected = true; clearTimeout(timer); }
      refresh();
    });
    refresh();
  }
  document.addEventListener('pointerdown', event => { if (menu && !menu.contains(event.target) && !anchor?.contains(event.target)) closeMenu(); });
  document.addEventListener('scroll', () => closeMenu(), true);
  window.addEventListener('resize', () => closeMenu());
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { clearTimeout(timer); timer = null; }
    else connect();
  });
  window.addEventListener('workbench:plugins-account-changed', reset);
  window.addEventListener('workbench:plugins-changed', connect);
  window.WorkbenchScheduleCards = { render, refresh };
  connect();
})();
