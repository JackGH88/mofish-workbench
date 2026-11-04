/* Shared local assistant configuration for both writing entry points. */
(() => {
  const dialog = document.getElementById('writingAssistantDialog');
  if (!dialog) return;
  const rows = dialog.querySelector('[data-assistant-rows]');
  const save = dialog.querySelector('[data-assistant-save]');
  const scopeNote = dialog.querySelector('[data-assistant-scope]');
  const path = dialog.querySelector('[data-assistant-path]');
  const chooseButton = dialog.querySelector('[data-assistant-choose]');
  let choosing = false;
  const testButton = dialog.querySelector('[data-assistant-test]');
  const pathArea = dialog.querySelector('[data-assistant-path-area]');
  let current = { selected: null, items: [] }, selected = '', busy = false;
  let scope=null, session=0, refreshSequence=0, onConfigured=null;
  const active = id => id===session && (!scope || scope.isCurrent());
  const names = { codex: 'Codex', workbuddy: 'WorkBuddy' };
  const downloadUrls = { codex: 'https://chatgpt.com/zh-Hans-CN/codex/', workbuddy: 'https://www.workbuddy.cn/' };
  const skillLabels = { missing: '回传技能未配置', installed: '回传技能已安装', outdated: '回传技能待更新', conflict: '回传技能冲突，请先备份并移开同名目录' };
  const notify = (message, type = 'error') => window.showToast?.(message, type);
  async function request(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail?.message || '助手配置读取失败，请重试。');
    return data;
  }
  function changed() { window.dispatchEvent(new CustomEvent('writing-assistant-change')); }
  function render() {
    const selectedItem = current.items.find(item => item.id === selected);
    const needsManualPath = selectedItem?.installed === false;
    dialog.querySelector('[data-assistant-manual]').hidden = !needsManualPath;
    if (!needsManualPath) {
      pathArea.hidden = true;
      path.value = '';
    }
    dialog.querySelector('.assistant-tools').hidden = !needsManualPath;
    testButton.remove();
    rows.replaceChildren();
    for (const item of current.items) {
      const row = document.createElement('div');
      const selection = document.createElement('label');
      selection.className = 'assistant-option-selection';
      row.className = 'assistant-option' + (selected === item.id ? ' is-selected' : '');
      const radio = document.createElement('input');
      radio.type = 'radio'; radio.name = 'writing-assistant'; radio.value = item.id;
      radio.checked = selected === item.id; radio.disabled = busy;
      radio.addEventListener('change', () => { selected = item.id; path.value = ''; render(); rows.querySelector('input:checked')?.focus(); });
      const body = document.createElement('span'); body.className = 'assistant-option-body';
      const heading = document.createElement('span'); heading.className = 'assistant-option-heading';
      const name = document.createElement('strong'); name.textContent = item.name;
      const badge = document.createElement('span'); badge.className = 'assistant-badge' + (item.installed ? ' installed' : '');
      badge.textContent = item.installed ? '本机已安装' : '未检测到';
      heading.append(name, badge);
      const description = document.createElement('small');
      description.textContent = item.installed ? skillLabels[item.skillStatus] + (item.verification?.returnedAt ? ' · 回传已验证' : ' · 回传未验证') : '安装后重新检测，或手动选择、填写应用路径';
      body.append(heading, description); selection.append(radio, body); row.append(selection);
      if (item.installed && selected === item.id) {
        row.classList.add('has-action');
        row.append(testButton);
      } else if (!item.installed && downloadUrls[item.id]) {
        const download = document.createElement('a');
        download.className = 'assistant-link assistant-download';
        download.href = downloadUrls[item.id];
        download.target = '_blank';
        download.rel = 'noopener noreferrer';
        download.textContent = '去官方下载';
        download.setAttribute('aria-label', `去 ${item.name} 官网下载（新窗口打开）`);
        const arrow = document.createElement('span');
        arrow.textContent = ' ↗';
        arrow.setAttribute('aria-hidden', 'true');
        download.append(arrow);
        row.classList.add('has-action');
        row.append(download);
      }
      rows.append(row);
    }
    if (!current.items.length) rows.textContent = '暂时无法读取本机助手，请重新检测。';
    save.disabled = busy || !selected;
    chooseButton.hidden = current.platform !== 'darwin';
    chooseButton.textContent = choosing ? '正在选择…' : '选择应用';
    save.textContent = busy && !choosing ? '正在配置…' : '使用并配置';
    for (const button of dialog.querySelectorAll('button')) button.disabled = busy || (button === save && !selected);
    path.disabled = busy;
  }
  async function refresh() {
    const id=session,sequence=++refreshSequence;
    const fresh=await request('/api/writing-assistants');
    if(!active(id)||sequence!==refreshSequence)return current;
    current=fresh;
    if(!scope)selected = current.selected || current.items.find(item => item.installed)?.id || 'codex';
    changed(); render(); return current;
  }
  async function open(options) {
    ++session;scope=typeof options?.onSave==='function'?options:null;onConfigured=typeof options?.onConfigured==='function'?options.onConfigured:null;
    busy=false;choosing=false;
    selected=scope?.agentId||current.selected||'codex';
    if (scopeNote) { scopeNote.textContent = scope?.contextNote || ''; scopeNote.hidden = !scopeNote.textContent; }
    if (!dialog.open) dialog.showModal();
    path.value = ''; pathArea.hidden = true;
    render();
    const id=session;
    try { await refresh(); } catch (error) { if(active(id))notify(error.message); }
  }
  dialog.addEventListener('close',()=>{if(dialog.open)return;++session;scope=null;onConfigured=null;busy=false;choosing=false;if(scopeNote){scopeNote.textContent='';scopeNote.hidden=true;}});
  function closeScope(value){if(value&&scope===value)dialog.close();}
  dialog.querySelectorAll('[data-assistant-close]').forEach(button => button.addEventListener('click', () => dialog.close()));
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  dialog.addEventListener('click', event => { if (event.target === dialog && !busy) { const box = dialog.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close(); } });
  dialog.querySelector('[data-assistant-refresh]').addEventListener('click', async () => {
    try { await refresh(); notify('已重新检测本机助手', 'success'); } catch (error) { notify(error.message); }
  });
  dialog.querySelector('[data-assistant-manual]').addEventListener('click', () => { pathArea.hidden = !pathArea.hidden; if (!pathArea.hidden) path.focus(); });
  chooseButton.addEventListener('click', async () => {
    if (busy || !selected) return;
    const id=session;
    choosing = true; busy = true; render();
    try {
      const result = await request('/api/writing-assistants/choose', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent: selected }),
      });
      if (active(id)&&!result.cancelled) path.value = result.path;
    } catch (error) { if(active(id))notify(error.message); }
    finally { if(active(id)){choosing = false; busy = false; render(); path.focus();} }
  });
  testButton.addEventListener('click', async () => {
    if(busy||!active(session))return;
    const item=current.items.find(item=>item.id===selected);
    if(scope ? !item?.installed||item?.skillStatus!=='installed' : !current.selected||selected!==current.selected){notify('请先使用并配置所选助手，再进行回传测试。');return;}
    const id=session;busy = true; render();
    try { const result = await request('/api/writing-assistants/test'+(scope?'?agent='+encodeURIComponent(selected):''), {method: 'POST'}); if(active(id))notify(result.message, 'info'); }
    catch (error) { if(active(id))notify(error.message); }
    finally { if(active(id)){busy = false; render();} }
  });
  save.addEventListener('click', async () => {
    if (busy || !selected || !active(session)) return;
    const id=session,target=scope,agent=selected,configured=onConfigured;
    busy = true; render();
    try {
      const fresh = await request('/api/writing-assistants/configure', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ agent, path: path.value.trim(), selectDefault:!target }) });
      if(!active(id))return;
      current=fresh;
      if(target)await target.onSave(agent);
      if(!active(id))return;
      changed(); dialog.close(); configured?.(agent); notify(`${names[agent]} 已配置，回传技能已安装`, 'success');
    } catch (error) { if(active(id))notify(error.message); }
    finally { if(active(id)){busy = false; render();} }
  });
  document.querySelectorAll('[data-configure-assistant]').forEach(button => button.addEventListener('click', open));
  window.WritingAssistants = { open, closeScope, refresh, selected: () => current.selected, isConfigured: agent => agent ? current.items.some(item=>item.id===agent&&item.installed&&item.skillStatus==='installed') : Boolean(current.selected), label: () => current.selected ? `${names[current.selected]} 生成` : '待配置Agent' };
  refresh().catch(() => {});
})();
