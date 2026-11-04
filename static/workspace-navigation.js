/* Navigation owns visibility only: the editor DOM and pending saves remain intact. */
(() => {
  const layout = document.querySelector('.tool-layout');
  const trigger = document.getElementById('accountSwitcherButton');
  const popover = document.getElementById('accountSwitcherPopover');
  const placeholder = document.getElementById('modulePlaceholder');
  const topicsContent = document.getElementById('topicsContent');
  const homeContent = document.getElementById('homeContent');
  const reviewContent = document.getElementById('reviewContent');
  const monitorContent = document.getElementById('monitorContent');
  const radarContent = document.getElementById('radarContent');
  const breakdownContent = document.getElementById('breakdownContent');
  const settingsContent = document.getElementById('settingsContent');
  const accountContent = document.getElementById('accountContent');
  const pluginsContent = document.getElementById('pluginsContent');
  // 创作 is its own entry: it owns the creation panel, so 脚本 keeps only list + editor.
  const labels = { today: '工作概况', radar: '内容采集', monitor: '对标监控', topics: '本周选题', create: '创作助手', scripts: '内容发布', review: '数据复盘', settings: '记忆管理', plugins: '插件管理', account: '账户与订阅', split: '拆解视频' };
  const navigation = [...document.querySelectorAll('[data-workspace-module]')];
  const storageKey = 'workspaceModule.v1';

  // Keep the selected first-level entry visible inside the compact rail without
  // scrolling the page. The navigation is not a scroll container on mobile.
  function revealNavigationItem(button) {
    const scroller = button?.closest?.('.workspace-navigation');
    if (!scroller || typeof scroller.clientHeight !== 'number') return;
    const scrollerRect = scroller.getBoundingClientRect();
    const buttonRect = button.getBoundingClientRect();
    if (buttonRect.top < scrollerRect.top) {
      scroller.scrollTop -= scrollerRect.top - buttonRect.top;
    } else if (buttonRect.bottom > scrollerRect.bottom) {
      scroller.scrollTop += buttonRect.bottom - scrollerRect.bottom;
    }
  }

  window.revealActiveWorkspaceNavigation = () => {
    revealNavigationItem(navigation.find(button => button.classList.contains('is-active')));
  };

  function selectModule(module, { source } = {}) {
    if (window.workspaceAccountState && window.workspaceAccountState !== 'ready') return;
    if (module === 'topicRecommendations') module = 'today';
    if (!Object.hasOwn(labels, module)) module = 'scripts';
    if (pluginsContent) {
      if (module === 'plugins' && source === 'workspacePluginManagementButton') {
        pluginsContent.dataset.returnModule = 'scripts';
      } else {
        delete pluginsContent.dataset.returnModule;
      }
    }
    layout.dataset.workspaceModule = module;
    const isCreate = module === 'create';
    const isScripts = module === 'scripts';
    const isTopics = module === 'topics';
    const isHome = module === 'today';
    const isReview = module === 'review';
    const isMonitor = module === 'monitor';
    const isRadar = module === 'radar';
    const isBreakdown = module === 'split';
    const isSettings = module === 'settings';
    const isAccount = module === 'account';
    const isPlugins = module === 'plugins';
    document.getElementById('scriptSidebar').hidden = !isScripts;
    document.getElementById('workspaceContent').hidden = !(isScripts || isCreate);
    if (topicsContent) topicsContent.hidden = !isTopics;
    if (homeContent) homeContent.hidden = !isHome;
    if (reviewContent) reviewContent.hidden = !isReview;
    if (monitorContent) monitorContent.hidden = !isMonitor;
    if (radarContent) radarContent.hidden = !isRadar;
    if (breakdownContent) breakdownContent.hidden = !isBreakdown;
    if (settingsContent) settingsContent.hidden = !isSettings;
    if (pluginsContent) pluginsContent.hidden = !isPlugins;
    if (accountContent) accountContent.hidden = !isAccount;
    placeholder.hidden = isScripts || isCreate || isTopics || isHome || isReview || isBreakdown || isMonitor || isRadar || isSettings || isPlugins || isAccount;
    document.getElementById('modulePlaceholderTitle').textContent = labels[module];
    navigation.forEach(button => {
      const selected = button.dataset.workspaceModule === module;
      button.classList.toggle('is-active', selected);
      if (selected) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
    window.revealActiveWorkspaceNavigation();
    if (!isScripts) document.querySelectorAll('#workspaceContent video, #workspaceContent audio').forEach(media => media.pause());
    if (!isBreakdown) document.querySelectorAll('#breakdownContent video, #breakdownContent audio').forEach(media => media.pause());
    try { localStorage.setItem(storageKey, module); } catch (_) { /* storage is optional */ }
    window.dispatchEvent(new CustomEvent('workspace-module-change', { detail: { module } }));
  }
  function positionPopover() {
    const bounds = trigger.getBoundingClientRect();
    popover.style.left = `${Math.max(8, Math.min(bounds.left, innerWidth - popover.offsetWidth - 8))}px`;
    popover.style.top = `${bounds.bottom + 8}px`;
    popover.style.maxHeight = `${Math.max(120, innerHeight - bounds.bottom - 24)}px`;
  }
  function closePopover(restoreFocus = false) {
    window.resetAccountSwitcherInteraction?.();
    popover.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
    if (restoreFocus) trigger.focus();
  }
  function openPopover() {
    popover.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    positionPopover();
    (popover.querySelector('.account-record.is-active') || popover.querySelector('button'))?.focus();
  }
  window.refreshAccountSwitcher = () => {
    const account = accounts.find(item => item.id === activeAccountId);
    const name = account?.name || '选择账号';
    document.getElementById('currentAccountName').textContent = name;
    document.getElementById('currentAccountPlatform').textContent = account ? '工作台' : '';
    trigger.title = `切换工作台：${name}`;
    trigger.setAttribute('aria-label', `切换工作台：${name}`);
  };
  trigger.addEventListener('click', () => popover.hidden ? openPopover() : closePopover());
  trigger.addEventListener('keydown', event => {
    if (event.key === 'ArrowDown') { event.preventDefault(); openPopover(); }
  });
  popover.addEventListener('click', event => {
    if (event.target.closest('button')) closePopover(event.target.closest('.account-record') !== null);
  });
  // Existing account rows implement Enter/Space on keyup for their hold gesture.
  popover.addEventListener('keyup', event => {
    if (['Enter', ' '].includes(event.key) && event.target.matches('.account-record') && !event.target.closest('.is-delete-revealed')) closePopover(true);
  });
  popover.addEventListener('keydown', event => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    const buttons = [...popover.querySelectorAll('button')].filter(button => button.getBoundingClientRect().width > 0 && getComputedStyle(button).visibility !== 'hidden' && !button.disabled);
    const index = buttons.indexOf(document.activeElement);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
    event.preventDefault(); buttons[next]?.focus();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !popover.hidden) { event.preventDefault(); closePopover(true); }
  });
  document.addEventListener('pointerdown', event => {
    if (!popover.hidden && !popover.contains(event.target) && !trigger.contains(event.target)) closePopover();
  });
  document.addEventListener('focusin', event => {
    if (!popover.hidden && !popover.contains(event.target) && event.target !== trigger) closePopover();
  });
  window.addEventListener('resize', () => { if (!popover.hidden) positionPopover(); });
  window.addEventListener('scroll', () => { if (!popover.hidden) positionPopover(); }, true);
  navigation.forEach(button => button.addEventListener('click', () => selectModule(button.dataset.workspaceModule, { source: button.id })));
  // Other modules (for example the weekly topic planner) switch views through this hook.
  window.selectWorkspaceModule = selectModule;
  let saved = 'today';
  try { saved = localStorage.getItem(storageKey) || saved; } catch (_) { /* storage is optional */ }
  window.restoreWorkspaceNavigation = () => selectModule(saved);
  selectModule(saved);
  window.refreshAccountSwitcher();
})();
