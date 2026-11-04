/* Record-scoped rewrite preparation, backed by the normal local writing handshake. */
(() => {
  const get = suffix => document.getElementById(`breakdownRewrite${suffix}`);
  const dialog = get('Dialog');
  if (!dialog) return;
  const requirements = get('Requirements'), toggle = get('PreviewToggle');
  const preview = get('Preview'), previewText = get('PreviewText');
  const openButton = get('Open'), switchButton = get('Switch');
  const assistantDialog = document.getElementById('writingAssistantDialog');
  const names = {codex: 'Codex', workbuddy: 'WorkBuddy'};
  let owner = null, generation = 0, previewVersion = 0, timer = null;
  let busy = false, choosing = false, attempt = null, loadingAssistant = false;
  const current = (id = generation) => id === generation && owner && owner.isCurrent();
  const notify = (message, type = 'error') => window.showToast?.(message, type);
  const selected = () => window.WritingAssistants?.selected?.() || '';
  function render() {
    const agent = selected();
    get('AgentName').textContent = names[agent] || '未配置';
    switchButton.textContent = agent ? '切换 Agent' : '配置助手';
    openButton.textContent = busy ? '正在打开…' : loadingAssistant ? '正在读取…' : agent ? `在 ${names[agent]} 中打开` : '配置助手';
    for (const button of dialog.querySelectorAll('button')) button.disabled = busy;
    openButton.disabled = busy || loadingAssistant;
    switchButton.disabled = busy || loadingAssistant;
    requirements.readOnly = busy;
    dialog.setAttribute('aria-busy', String(busy));
  }
  function fit() {
    if (!dialog.open) return;
    requirements.style.height = '136px';
    requirements.style.height = `${Math.max(136, requirements.scrollHeight + 2)}px`;
  }
  async function request(url, body, signal) {
    const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body), signal});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail?.message || '仿写任务处理失败，请重试。');
    return data;
  }
  const endpoint = () => `/api/accounts/${encodeURIComponent(owner.accountId)}/breakdowns/${encodeURIComponent(owner.recordId)}/rewrite`;
  async function loadPreview() {
    if (!current() || preview.hidden) return;
    const id = generation, sequence = ++previewVersion;
    previewText.textContent = '正在读取发送内容…';
    try {
      const result = await request(endpoint() + '/preview', {requirements: requirements.value.trim()});
      if (current(id) && sequence === previewVersion) previewText.textContent = result.prompt;
    } catch (error) {
      if (current(id) && sequence === previewVersion) previewText.textContent = error.message;
    }
  }
  function close() {
    generation++;
    previewVersion++;
    clearTimeout(timer);
    owner = null;
    busy = false;
    attempt = null;
    if (choosing) assistantDialog?.close();
    choosing = false;
    dialog.close();
  }
  async function open(options) {
    close();
    owner = options;
    requirements.value = '';
    preview.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
    toggle.querySelector('span').textContent = '查看将发送的内容';
    previewText.textContent = '';
    loadingAssistant = true;
    render();
    dialog.showModal();
    fit();
    const id = generation;
    try { await window.WritingAssistants.refresh(); }
    catch (error) { if (current(id)) notify(error.message || '无法读取助手配置，请重试。'); }
    finally { if (current(id)) { loadingAssistant = false; render(); } }
  }
  function choose(continueAfter = false) {
    if (!current() || busy || choosing) return;
    choosing = true;
    const id = generation;
    let configured = false;
    dialog.close();
    assistantDialog.addEventListener('close', () => {
      if (!current(id)) return;
      choosing = false;
      dialog.showModal();
      fit(); render();
      switchButton.focus();
      if (configured && continueAfter) launch();
    }, {once: true});
    window.WritingAssistants.open({onConfigured: () => { configured = true; }});
  }
  async function launch() {
    if (!current() || busy || loadingAssistant) return;
    if (!window.WritingAssistants.isConfigured()) { choose(true); return; }
    const id = generation, agentId = selected(), text = requirements.value.trim();
    const signature = JSON.stringify([agentId, text]);
    if (!attempt || attempt.signature !== signature) attempt = {signature, requestId: crypto.randomUUID()};
    const body = {requirements: text, agentId, requestId: attempt.requestId};
    busy = true; render();
    try {
      const result = await request(endpoint(), body);
      if (!current(id)) return;
      notify(result.message, result.opened ? 'info' : 'error');
      // Preserve the request ID on failure so a lost response/retry cannot duplicate drafts.
      if (result.opened) close();
    } catch (error) { if (current(id)) notify(error.message); }
    finally { if (current(id)) { busy = false; render(); } }
  }
  requirements.addEventListener('input', () => {
    fit(); clearTimeout(timer); previewVersion++;
    if (!preview.hidden) { previewText.textContent = '正在读取发送内容…'; timer = setTimeout(loadPreview, 250); }
  });
  toggle.addEventListener('click', () => {
    preview.hidden = !preview.hidden;
    toggle.setAttribute('aria-expanded', String(!preview.hidden));
    toggle.querySelector('span').textContent = preview.hidden ? '查看将发送的内容' : '收起发送内容';
    if (!preview.hidden) loadPreview();
  });
  switchButton.addEventListener('click', () => choose());
  openButton.addEventListener('click', launch);
  get('Close').addEventListener('click', () => { if (!busy) close(); });
  dialog.addEventListener('cancel', event => { event.preventDefault(); if (!busy) close(); });
  dialog.addEventListener('click', event => {
    if (event.target !== dialog || busy) return;
    const box = dialog.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) close();
  });
  window.addEventListener('resize', fit);
  window.addEventListener('writing-assistant-change', () => { if (current()) render(); });
  window.BreakdownRewrite = {open, close};
})();
