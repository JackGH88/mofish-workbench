/* Trial gift is a read-only, creation-service identity scoped guide. */
(() => {
  const byId = (id) => document.getElementById(id);
  const root = byId('homeContent');
  const today = byId('homeTodayFocus');
  const panel = byId('trialGiftPanel');
  const dialog = byId('trialGiftModal');
  if (!root || !today || !panel || !dialog) return;
  const card = panel.closest('.home-focus');
  const tabs = byId('trialGiftTabs');
  const rotationControl = byId('trialGiftRotationControl');
  const giftTab = byId('trialGiftOfferTab');
  const todayTab = byId('trialGiftTodayTab');
  let session = {loggedIn: false, owner: '', generation: -1};
  let data = null, eligible = false, selected = 'today', failed = false;
  let pending = null, timer = null, controller = null, disposed = false;
  let returnFocus = null, imageKey = '', balanceSynced = false;
  const amountText = (value) => String(value).replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '');
  const current = (snapshot) => !disposed && snapshot.owner === session.owner && snapshot.generation === session.generation;
  // Fixed guest advertising is intentional; authenticated entitlement always comes from the API.
  const isGuest = () => session.generation >= 0 && !session.loggedIn;
  const hasOfferPage = () => isGuest() || (eligible && !failed);
  const stopPolling = () => { clearTimeout(timer); timer = null; };
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let rotationTimer = null, userPaused = false;
  let homeActive = !root.hidden, windowFocused = document.hasFocus();
  let hovered = card.matches(':hover'), keyboardFocus = false;
  const stopRotation = () => { clearTimeout(rotationTimer); rotationTimer = null; };
  function hasOpenModal() {
    return [...document.querySelectorAll('dialog[open], [role="dialog"], [aria-modal="true"]')]
      .some(el => !el.hidden && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
  }
  function canRotate() {
    return hasOfferPage() && !disposed && homeActive && !root.hidden && !document.hidden
      && windowFocused && !hovered && !keyboardFocus && !dialog.open && !hasOpenModal() && !userPaused && !reducedMotion.matches;
  }
  function syncRotation() {
    if (!canRotate()) { stopRotation(); return; }
    // Ordinary renders and API refreshes must not postpone the next switch.
    if (rotationTimer !== null) return;
    rotationTimer = setTimeout(() => {
      rotationTimer = null;
      if (!canRotate()) return;
      selected = selected === 'gift' ? 'today' : 'gift';
      render();
    }, 8000);
  }
  function selectPage(page) {
    selected = page; stopRotation(); render();
  }
  function syncKeyboardFocus() {
    keyboardFocus = card.contains(document.activeElement) && document.activeElement.matches(':focus-visible');
    syncRotation();
  }

  function render() {
    const guest = isGuest();
    const show = hasOfferPage();
    panel.hidden = !show || selected !== 'gift';
    today.hidden = show && selected === 'gift';
    tabs.hidden = !show;
    rotationControl.hidden = !show;
    rotationControl.textContent = userPaused ? '恢复自动切换' : '暂停自动切换';
    rotationControl.setAttribute('aria-pressed', String(userPaused));
    card.classList.toggle('has-trial-gift', show);
    card.classList.toggle('is-trial-gift', !panel.hidden);
    panel.inert = panel.hidden;
    today.inert = today.hidden;
    giftTab.setAttribute('aria-pressed', String(!panel.hidden));
    todayTab.setAttribute('aria-pressed', String(!today.hidden));
    byId('trialGiftTitle').textContent = guest ? '新用户注册赠送100积分'
      : data && eligible ? `新用户注册赠送${amountText(data.amount)}积分` : '';
    byId('trialGiftOpen').textContent = guest ? '立即领取 100 积分' : '立即领取积分';
    byId('trialGiftDescription').textContent = guest
      ? '注册登录后，添加微信联系管理员领取体验积分；具体活动与领取资格以登录后页面为准。'
      : '添加微信联系管理员，领取一次创作体验积分。\n新老注册账号均可参与。';
    syncRotation();
  }

  function restoreFocus() {
    const target = returnFocus?.isConnected && returnFocus.getClientRects().length ? returnFocus :
      (!today.hidden && !byId('homeFocusAction')?.disabled ? byId('homeFocusAction') : today);
    target?.focus({preventScroll: true});
    returnFocus = null;
  }

  function close({refresh = true} = {}) {
    stopPolling();
    if (!dialog.open) return;
    dialog.close();
    restoreFocus();
    syncRotation();
    if (refresh && !disposed) void refreshGuide();
  }

  function syncSession(next = window.accountModule?.getSession?.()) {
    if (!next) return;
    const changed = next.owner !== session.owner || next.generation !== session.generation || next.loggedIn !== session.loggedIn;
    if (!changed) return;
    session = {...next};
    userPaused = false;
    stopRotation();
    controller?.abort(); controller = null; pending = null;
    data = null; eligible = false; selected = isGuest() ? 'gift' : 'today'; failed = false; balanceSynced = false; imageKey = '';
    render(); close({refresh: false}); stopPolling();
    byId('trialGiftQr').removeAttribute('src');
    byId('trialGiftUserId').value = '';
    byId('trialGiftGuide').textContent = '';
    if (session.loggedIn && session.owner) void refreshGuide();
  }

  function schedule() {
    stopPolling();
    if (dialog.open && !disposed) timer = setTimeout(() => { timer = null; void refreshGuide(); }, 30000);
  }

  function updateDialog() {
    if (!data || !eligible) return;
    byId('trialGiftModalTitle').textContent = `领取${amountText(data.amount)}体验积分`;
    byId('trialGiftGuide').textContent = data.guideText || '';
    byId('trialGiftUserId').value = data.userId;
    const key = `${session.owner}|${session.generation}|${data.qrCodeUrl}`;
    if (key !== imageKey) {
      imageKey = key;
      loadImage();
    }
  }

  function loadImage() {
    if (!data || !eligible) return;
    const image = byId('trialGiftQr');
    image.hidden = false;
    byId('trialGiftImageStatus').textContent = '正在加载微信二维码…';
    byId('trialGiftImageRetry').hidden = true;
    image.src = '/api/subscription/trial-gift/qrcode?owner=' + encodeURIComponent(session.owner)
      + '&version=' + encodeURIComponent(data.qrCodeUrl) + '&t=' + Date.now();
  }

  async function fetchGuide(snapshot, signal) {
    const response = await fetch('/api/subscription/trial-gift', {
      cache: 'no-store', signal, headers: {'Accept': 'application/json', 'X-Payment-Owner': snapshot.owner},
    });
    if (!current(snapshot)) return;
    if (response.status === 401) {
      window.accountModule?.sessionInvalid?.();
      return;
    }
    if (!response.ok) throw new Error('领取状态刷新失败，请稍后重试。');
    const result = await response.json();
    if (!current(snapshot)) return;
    if (typeof result.visible !== 'boolean' || typeof result.claimed !== 'boolean' ||
        (result.visible && !result.claimed && (!/^\d+(\.\d{1,3})?$/.test(result.amount) ||
          !result.qrCodeUrl || !result.userId))) throw new Error('领取信息暂不可用，请稍后重试。');
    const nextEligible = result.visible && !result.claimed;
    if (nextEligible && !eligible) selected = 'gift';
    eligible = nextEligible;
    data = result; failed = false;
    window.accountModule?.updateTrialGift?.(result, snapshot.owner);
    byId('trialGiftStatus').textContent = '';
    render();
    if (!eligible) close({refresh: false});
    else if (dialog.open) updateDialog();
    if (result.claimed && !balanceSynced) {
      const refreshed = await window.accountModule?.refreshBalanceAfterGrant?.(snapshot.owner);
      if (current(snapshot)) balanceSynced = refreshed !== false;
    }
  }

  function refreshGuide() {
    if (disposed || !session.loggedIn || !session.owner) return Promise.resolve();
    if (pending) return pending;
    const snapshot = {...session};
    const abort = new AbortController(); controller = abort;
    const timeout = setTimeout(() => abort.abort(), 15000);
    const request = fetchGuide(snapshot, abort.signal).catch((error) => {
      if (!current(snapshot)) return;
      failed = true; render();
      byId('trialGiftStatus').textContent = error.name === 'AbortError' ? '领取状态请求超时，请稍后重试。' : (error instanceof TypeError ? '无法连接服务，领取状态刷新失败，请稍后重试。' : error.message || '领取状态刷新失败，请稍后重试。');
    }).finally(() => {
      clearTimeout(timeout);
      if (pending === request) {
        pending = null; controller = null; schedule();
      }
    });
    pending = request;
    return request;
  }

  function open() {
    if (isGuest()) { window.accountModule?.openLogin?.(); syncRotation(); return; }
    if (!eligible || failed || dialog.open) return;
    // Safari does not focus buttons on pointer click; retain the actual opener.
    returnFocus = byId('trialGiftOpen');
    byId('trialGiftCopyStatus').textContent = '';
    updateDialog(); dialog.showModal();
    syncRotation();
    byId('trialGiftClose').focus();
    void refreshGuide();
  }
  rotationControl.addEventListener('click', () => { userPaused = !userPaused; stopRotation(); render(); });
  giftTab.addEventListener('click', () => selectPage('gift'));
  todayTab.addEventListener('click', () => selectPage('today'));
  tabs.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const target = event.key === 'Home' ? giftTab : event.key === 'End' ? todayTab : document.activeElement === giftTab ? todayTab : giftTab;
    target.click(); target.focus();
  });
  byId('trialGiftOpen').addEventListener('click', open);
  byId('trialGiftClose').addEventListener('click', () => close());
  byId('trialGiftRefresh').addEventListener('click', () => void refreshGuide());
  byId('trialGiftImageRetry').addEventListener('click', loadImage);
  byId('trialGiftQr').addEventListener('load', () => { byId('trialGiftImageStatus').textContent = ''; });
  byId('trialGiftQr').addEventListener('error', () => {
    byId('trialGiftQr').hidden = true;
    byId('trialGiftImageStatus').textContent = '二维码加载失败，请重试。';
    byId('trialGiftImageRetry').hidden = false;
  });
  byId('trialGiftCopy').addEventListener('click', async () => {
    const snapshot = {...session};
    try {
      await navigator.clipboard.writeText(byId('trialGiftUserId').value);
      if (current(snapshot)) byId('trialGiftCopyStatus').textContent = '用户 ID 已复制';
    } catch (_) {
      if (!current(snapshot)) return;
      byId('trialGiftUserId').focus(); byId('trialGiftUserId').select();
      byId('trialGiftCopyStatus').textContent = '自动复制失败，请复制已选中的用户 ID。';
    }
  });
  dialog.addEventListener('cancel', (event) => { event.preventDefault(); close(); });
  dialog.addEventListener('click', (event) => {
    const r = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom)) close();
  });
  dialog.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); return; }
    if (event.key !== 'Tab') return;
    const controls = [...dialog.querySelectorAll('button, input, [tabindex]')].filter(el => !el.disabled && el.tabIndex >= 0 && el.getClientRects().length);
    const index = controls.indexOf(document.activeElement);
    if (index < 0 || (event.shiftKey ? index === 0 : index === controls.length - 1)) {
      event.preventDefault(); controls[event.shiftKey ? controls.length - 1 : 0]?.focus();
    }
  });
  // Native dialogs and the workbench's hidden/ARIA dialogs share the same pause rule.
  const modalObserver = new MutationObserver(syncRotation);
  const observeModals = () => modalObserver.observe(document.body, {
    subtree: true, childList: true, attributes: true, attributeFilter: ['open', 'hidden', 'aria-hidden', 'class', 'style'],
  });
  observeModals();
  card.addEventListener('mouseenter', () => { hovered = true; syncRotation(); });
  card.addEventListener('mouseleave', () => { hovered = false; syncRotation(); });
  card.addEventListener('focusin', syncKeyboardFocus);
  card.addEventListener('focusout', () => queueMicrotask(syncKeyboardFocus));
  card.addEventListener('keydown', () => { keyboardFocus = true; syncRotation(); });
  card.addEventListener('pointerdown', () => { keyboardFocus = false; syncRotation(); });
  reducedMotion.addEventListener('change', syncRotation);
  document.addEventListener('visibilitychange', syncRotation);
  window.addEventListener('blur', () => { windowFocused = false; syncRotation(); });
  window.addEventListener('creation-session-changed', (event) => syncSession(event.detail));
  window.addEventListener('focus', () => { windowFocused = true; syncRotation(); syncSession(); void refreshGuide(); });
  window.addEventListener('workspace-module-change', (event) => {
    homeActive = event.detail?.module === 'today';
    if (homeActive) { syncSession(); void refreshGuide(); }
    else close();
    syncRotation();
  });
  window.addEventListener('pagehide', () => {
    disposed = true; modalObserver.disconnect(); stopRotation(); stopPolling(); controller?.abort(); close({refresh: false});
  });
  window.addEventListener('pageshow', () => {
    if (disposed) { disposed = false; pending = null; observeModals(); syncRotation(); void refreshGuide(); }
  });
  syncSession(); render();
})();
