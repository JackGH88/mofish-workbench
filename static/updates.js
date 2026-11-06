/* Public release notifications never install code or restart the workbench. */
(() => {
  const entry = document.getElementById('workbenchUpdateButton');
  if (!entry) return;
  const dialog = document.createElement('dialog');
  dialog.className = 'workbench-update-dialog';
  dialog.id = 'workbenchUpdateDialog';
  dialog.setAttribute('aria-labelledby', 'workbenchUpdateTitle');
  dialog.innerHTML = `<header><h2 id="workbenchUpdateTitle">版本与更新</h2><button class="update-close am-modal-dismiss" aria-label="关闭" type="button"><svg class="am-modal-close-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button></header>
    <section class="workbench-update-status"><span class="update-status-icon" data-update="icon" aria-hidden="true">↻</span><div><div class="update-status-heading"><h3 data-update="title">正在检查版本</h3><span class="update-distribution" data-update="distribution"></span></div><p data-update="subtitle">正在获取版本信息</p></div></section>
    <dl><dt>当前版本</dt><dd data-update="current">读取中…</dd><dt>最新版本</dt><dd data-update="latest">尚未检查</dd><dt>上次检查</dt><dd data-update="checked">—</dd></dl>
    <h3 data-update="notesTitle">更新说明</h3><div class="workbench-update-notes" data-update="notes">检查后显示版本说明。</div>
    <p class="workbench-update-message" data-update="message" role="status" aria-live="polite"></p>
    <section class="workbench-update-action" data-update="action" hidden><h3 data-update="actionTitle"></h3><p data-update="actionHint"></p></section>
    <div data-update="fallback" hidden><label for="workbenchUpgradePrompt">请手动复制升级提示词</label><textarea id="workbenchUpgradePrompt" data-update="prompt" readonly></textarea></div>
    <footer><button type="button" class="am-secondary-action" data-update="check">检查更新</button><a class="am-primary-action" data-update="download" target="_blank" rel="noopener noreferrer" hidden>下载新版安装包</a><button type="button" class="am-primary-action" data-update="copy" hidden>复制升级提示词</button></footer>`;
  document.body.append(dialog);
  const elements = Object.fromEntries([...dialog.querySelectorAll('[data-update]')].map(node => [node.dataset.update, node]));
  let state = null, busy = false, polling = false, localError = '', timer;
  function resizePrompt() {
    const field = elements.prompt;
    if (!dialog.open || elements.fallback.hidden || !field.clientWidth) return;
    // Reset first so shorter text and wider windows also shrink the field.
    field.style.height = '0px';
    field.style.height = field.scrollHeight + 'px';
  }
  if (typeof ResizeObserver !== 'undefined') {
    let previousWidth;
    new ResizeObserver(entries => {
      const width = entries[0].contentRect.width;
      if (width === previousWidth) return;
      previousWidth = width;
      resizePrompt();
    }).observe(dialog);
  } else {
    window.addEventListener?.('resize', resizePrompt);
  }
  document.fonts?.ready.then(resizePrompt);
  const formatTime = value => value ? new Date(value * 1000).toLocaleString('zh-CN') : '—';
  function message(text, error = false) {
    elements.message.textContent = text;
    elements.message.classList.toggle('is-error', error);
  }
  function render(data) {
    const targetChanged = state?.latest?.tag !== data.latest?.tag || state?.distribution !== data.distribution;
    state = data;
    const label = data.current.version ? 'v' + data.current.version : '未发布';
    const desktop = data.distribution === 'desktop';
    document.getElementById('workbenchVersionLabel').textContent = data.available ? '有新版本' : label + (data.current.development ? ' · 开发版' : '');
    entry.classList.toggle('has-update', data.available);
    // On the root so the indicator survives account/login UI re-renders.
    document.documentElement.classList.toggle('workbench-has-update', data.available);
    elements.current.textContent = label + (data.current.development ? ' · 开发版' : '');
    elements.latest.textContent = data.latest?.tag || (data.checkedAt && !data.checkError ? '暂无正式版本' : '尚未检查');
    elements.latest.classList.toggle('workbench-version-badge', Boolean(data.latest));
    elements.latest.classList.toggle('is-new', Boolean(data.available));
    elements.checked.textContent = formatTime(data.checkedAt);
    elements.notes.textContent = (data.latest?.notes || '暂无版本说明。')
      .replace(/^(发布[ \t]+v[^\s]+)[ \t]*\r?\n(?:[ \t]*\r?\n)+/, '$1\n');
    elements.check.disabled = busy;
    elements.copy.hidden = desktop || !data.available;
    elements.copy.disabled = busy;
    const ready = !busy && !localError && !data.checkError && Boolean(data.checkedAt);
    const known = Boolean(data.current.version && data.latest);
    const current = ready && known && !data.available;
    elements.distribution.textContent = desktop ? '应用版' : '部署版';
    elements.title.textContent = busy || !data.checkedAt ? '正在检查版本' : localError || data.checkError ? '暂时无法检查更新' : !data.current.version ? '无法识别当前版本' : data.available ? '发现新版本' : current ? '已是最新版本' : '暂无正式版本';
    elements.icon.textContent = busy || !data.checkedAt ? '↻' : localError || data.checkError || !data.current.version ? '!' : data.available ? '↑' : current ? '✓' : '—';
    elements.icon.classList.toggle('is-neutral', !ready || !known);
    elements.subtitle.textContent = !ready ? '请稍候或重新检查' : !known ? '可稍后重新检查版本信息' : data.available ? (desktop ? '新版本已就绪，下载后安装即可' : '新版本已就绪，可交给 Agent 升级') : '当前无需升级，继续安心创作';
    elements.notesTitle.textContent = current ? '本版更新说明' : '更新说明';
    elements.action.hidden = !data.available;
    elements.actionTitle.textContent = desktop ? '下载并安装新版本' : '让 Agent 帮你升级';
    elements.actionHint.textContent = desktop ? (data.latest?.downloadUrl ? '下载新版安装包，退出应用后完成安装。' : '安装包暂不可用，请稍后重新检查。') : '复制升级提示词，粘贴给部署工作台的 Agent 即可。';
    elements.download.hidden = !desktop || !data.available || !data.latest?.downloadUrl;
    if (!elements.download.hidden) elements.download.href = data.latest.downloadUrl;
    else elements.download.removeAttribute('href');
    if (targetChanged || desktop || !data.available) elements.fallback.hidden = true;
    if (busy) message('正在检查最新版本，请稍候…');
    else if (localError) message(localError, true);
    else if (data.checkError) message('暂时无法检查，请稍后重试。' + (data.lastSuccessfulCheckAt ? '当前显示上次获取的版本信息（' + formatTime(data.lastSuccessfulCheckAt) + '）。' : ''));
    else if (!data.checkedAt) message('正在检查正式版本…');
    else if (!data.current.version) message('无法识别当前版本，请核对当前安装信息后重试。');
    else message('');
  }
  async function request(action = 'status') {
    const response = await fetch('/api/system/update/' + action, {
      method: action === 'status' ? 'GET' : 'POST', cache: 'no-store', signal: AbortSignal.timeout(25000),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '暂时无法检查，请稍后重试。');
    return data;
  }
  async function poll() {
    if (polling) return;
    polling = true;
    clearTimeout(timer);
    try { const data = await request(); if (!busy) render(data); }
    catch (error) { if (dialog.open) message(error.message, true); }
    finally { polling = false; timer = setTimeout(poll, 30000); }
  }
  entry.addEventListener('click', () => {
    document.getElementById('accountPopover')?.hidePopover?.();
    localError = '';
    if (state) render(state);
    dialog.showModal();
    resizePrompt();
    poll();
  });
  dialog.querySelector('.update-close').addEventListener('click', () => dialog.close());
  elements.check.addEventListener('click', async () => {
    if (busy) return;
    busy = true; localError = '';
    if (state) render(state);
    try {
      const result = await request('check');
      busy = false;
      localError = result.checkError ? '检查失败：' + result.checkError + (result.lastSuccessfulCheckAt ? '上次成功获取：' + formatTime(result.lastSuccessfulCheckAt) + '。' : '') : '';
      render(result);
    } catch (error) {
      busy = false; localError = error.message;
      if (state) render(state); else { elements.check.disabled = false; message(localError, true); }
    }
  });
  elements.copy.addEventListener('click', async () => {
    const prompt = state?.upgradePrompt;
    if (!prompt || !state.available) return;
    try {
      await navigator.clipboard.writeText(prompt);
      elements.fallback.hidden = true;
      message('已复制，粘贴给 Agent 即可。');
    } catch {
      elements.fallback.hidden = false;
      elements.prompt.value = prompt;
      resizePrompt();
      elements.prompt.focus(); elements.prompt.select();
      message('无法自动复制，请手动复制下方升级提示词。');
    }
  });
  [dialog, elements.notes].forEach(container => {
    let hideTimer;
    container.addEventListener('scroll', () => {
      if (!dialog.open) return;
      clearTimeout(hideTimer); container.classList.add('is-scrolling');
      hideTimer = setTimeout(() => container.classList.remove('is-scrolling'), 500);
    }, {passive: true});
    dialog.addEventListener('close', () => { clearTimeout(hideTimer); container.classList.remove('is-scrolling'); });
  });
  poll();
})();
