/* Local workbench restart: durable job polling and workspace-bound verification. */
(() => {
  'use strict';
  const key = 'workbenchRestart.v1';
  const active = new Set(['waiting', 'starting', 'restarting', 'verifying']);
  let record = null, dialog = null, heading, introduction, message, progress, spinner, cancel, force, retry, discard, close, timer, clockTimer, polling = false, starting = false, forcing = false;
  const account = () => window.WorkbenchScriptContext?.()?.accountId || null;
  function save() { try { if (record) localStorage.setItem(key, JSON.stringify(record)); else localStorage.removeItem(key); } catch (_) {} }
  async function request(path, body, token) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(path, {method: body ? 'POST' : 'GET', cache:'no-store', signal:controller.signal,
        headers:body ? {'Content-Type':'application/json', 'X-Workbench-Update-Token':token} : {},
        body:body ? JSON.stringify(body) : undefined});
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.message || '操作失败，请稍后重试。');
      return data;
    } finally { clearTimeout(timeout); }
  }
  function element(tag, text, className) {
    const node = document.createElement(tag); node.textContent = text || ''; if (className) node.className = className; return node;
  }
  function show() {
    if (dialog) { if (!dialog.open) dialog.showModal(); return; }
    dialog = element('dialog', '', 'pm-dialog pm-import-dialog');
    dialog.setAttribute('aria-label', '重启工作台');
    heading = element('h2', '强制重启', 'modal-title');
    introduction = element('p', '将中断本机工作台正在执行的任务，并重新打开工作台，使插件生效。', 'pm-save-note');
    dialog.append(heading, introduction);
    const statusRow = element('div', '', 'pm-message pm-restart-status');
    spinner = element('span', '', 'pm-spinner pm-restart-spinner');
    spinner.hidden = true; spinner.setAttribute('aria-hidden', 'true');
    message = element('span'); message.setAttribute('role', 'status');
    statusRow.append(spinner, message); dialog.appendChild(statusRow);
    progress = element('p', '', 'pm-save-note pm-restart-progress');
    progress.hidden = true; dialog.appendChild(progress);
    const actions = element('div', '', 'pm-dialog-actions');
    cancel = element('button', '取消重启', 'pm-btn'); cancel.hidden = true;
    force = element('button', '强制重启', 'pm-btn'); force.hidden = true;
    force.onclick = forceRestart;
    retry = element('button', '重新检查连接', 'pm-btn is-primary'); retry.hidden = true;
    discard = element('button', '仍然强制重启', 'pm-btn'); discard.hidden = true;
    discard.onclick = () => start({discardUnsaved:true});
    close = element('button', '关闭', 'pm-btn'); close.hidden = true;
    cancel.onclick = async () => {
      cancel.disabled = true;
      try { const status = await request('/api/system/restart/status'); await request('/api/system/restart/cancel', {}, status.operationToken); record = null; save(); clearTimeout(timer); setBusy(false); message.textContent = '已取消重启，可以继续使用工作台。'; cancel.hidden = true; force.hidden = true; close.hidden = false; }
      catch (error) { message.textContent = error.message; }
      finally { cancel.disabled = false; }
    };
    retry.onclick = () => { retry.hidden = true; if (record) { record.deadline = Date.now() + 180000; save(); poll(); } else start(); };
    close.onclick = () => dialog.close();
    dialog.addEventListener('cancel', event => { if (!close.hidden) return; event.preventDefault(); });
    actions.append(cancel, force, retry, discard, close); dialog.appendChild(actions); document.body.appendChild(dialog); dialog.showModal();
  }
  const stageLabels = {stopping:'正在停止服务', starting:'正在启动服务', verifying_plugins:'正在确认插件'};
  function inferredStage(phase) {
    return {restarting:'stopping', starting:'starting', verifying:'verifying_plugins', complete:'verifying_plugins'}[phase];
  }
  function updateProgress(current, job) {
    const previous = current.progress || {};
    const phase = job.phase || previous.phase || 'starting';
    const stage = phase === 'complete' ? 'verifying_plugins'
      : Object.hasOwn(stageLabels, job.stage) ? job.stage
      : inferredStage(phase) || (phase === 'waiting' ? undefined : previous.stage);
    const seconds = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
    const now = Date.now() / 1000;
    const startedAt = seconds(job.startedAt) ? job.startedAt : previous.startedAt ?? now;
    const stageStartedAt = seconds(job.stageStartedAt) ? job.stageStartedAt
      : seconds(job.stageTimes?.[stage]) ? job.stageTimes[stage]
      : previous.stage === stage ? previous.stageStartedAt ?? startedAt : now;
    current.progress = {phase, stage, startedAt, stageStartedAt,
      message:typeof job.message === 'string' ? job.message : previous.message || ''};
    save(); renderProgress();
  }
  function renderProgress() {
    if (!progress || !record) return;
    const state = record.progress;
    if (!state) return;
    const elapsed = since => Math.max(0, Math.floor(Date.now() / 1000 - since));
    const label = stageLabels[state.stage] || (state.phase === 'waiting' ? '等待任务结束' : '正在重启工作台');
    progress.hidden = false;
    progress.textContent = label + ' · 已用时 ' + elapsed(state.startedAt) + ' 秒 · 当前阶段 ' + elapsed(state.stageStartedAt) + ' 秒';
  }
  function setBusy(busy) {
    spinner.hidden = !busy;
    if (!busy) { clearTimeout(clockTimer); clockTimer = null; return; }
    renderProgress();
    if (!clockTimer) {
      const tick = () => { renderProgress(); clockTimer = setTimeout(tick, 1000); };
      tick();
    }
  }
  function failed(text) { setBusy(false); retry.textContent = record ? '重新检查连接' : '重试重启'; message.textContent = text; force.hidden = true; discard.hidden = true; cancel.hidden = true; retry.hidden = false; close.hidden = false; }
  async function forceRestart() {
    if (forcing || !record || force.hidden) return;
    if (!window.confirm('强制重启会中断正在执行的任务，并断开所有工作台连接。确定继续吗？')) return;
    const current = record;
    forcing = true; force.disabled = true; cancel.disabled = true;
    try {
      const status = await request('/api/system/restart/status');
      if (record !== current) return;
      if (status.job?.id !== current.id || status.job?.phase !== 'waiting') {
        throw new Error('重启状态已变化，请重新检查。');
      }
      await request('/api/system/restart/force', {jobId:current.id, confirmed:true}, status.operationToken);
      force.hidden = true; cancel.hidden = true;
      current.deadline = Date.now() + 180000; save();
      message.textContent = '正在强制重启工作台，恢复后将自动刷新…';
    } catch (error) {
      // Reconcile status after a lost response; never resend force automatically.
      message.textContent = error.message;
    } finally {
      forcing = false; force.disabled = false; cancel.disabled = false;
      clearTimeout(timer); poll();
    }
  }
  async function poll() {
    if (!record || polling) return;
    clearTimeout(timer);
    polling = true;
    setBusy(true);
    const current = record;
    try {
      const status = await request('/api/system/restart/status');
      if (record !== current) return;
      const job = status.job || {};
      // A lost start response is reconciled by status; never blindly POST again.
      if (!current.id && active.has(job.phase)) { current.id = job.id; save(); }
      if (job.id !== current.id) { record = null; save(); failed('未找到本次重启记录，请检查当前服务状态后重试。'); return; }
      if (job.phase === 'waiting') current.deadline = Date.now() + 180000;
      force.hidden = job.phase !== 'waiting'; cancel.hidden = job.phase !== 'waiting'; close.hidden = active.has(job.phase); retry.hidden = true;
      updateProgress(current, job);
      message.textContent = job.message || '恢复后将自动确认插件版本。';
      if (job.phase === 'failed' || job.phase === 'cancelled') {
        record = null; save(); failed(job.phase === 'cancelled'
          ? job.message || '重启已取消，可以关闭此窗口或重试重启。'
          : (job.error || job.message || '重启失败。') + ' 请重试重启；若服务无法连接，请手动重新打开工作台后检查插件版本。'); return;
      }
      if (job.phase === 'complete' && status.instanceId !== current.instanceId) {
        if (account() && account() !== current.accountId) {
          message.textContent = '工作台已重启；已切换工作台，请在当前插件列表查看生效版本。'; record = null; save(); setBusy(false); close.hidden = false; return;
        }
        const result = await request('/api/plugins?accountId=' + encodeURIComponent(current.accountId));
        if (record !== current) return;
        if (account() && account() !== current.accountId) {
          message.textContent = '工作台已重启；请在当前工作台查看插件版本。';
          record = null; save(); setBusy(false); close.hidden = false; return;
        }
        const views = result.plugins || [];
        const problems = current.targets.filter(target => {
          const view = views.find(item => item.id === target.id);
          return !view || view.activeVersion !== target.version || view.pendingVersion || view.loadError || view.installError;
        });
        if (problems.length) {
          const reasons = problems.map(target => {
            const view = views.find(item => item.id === target.id);
            return target.id + '：' + (view?.installError || view?.loadError || '目标版本尚未生效，请查看插件详情');
          });
          message.textContent = '工作台已重启，但插件未全部生效。' + reasons.join('；');
          record = null; save(); setBusy(false); close.hidden = false; window.WorkbenchPlugins?.refreshAll(); return;
        }
        if (!current.reloaded) {
          current.reloaded = true; save();
          try { localStorage.setItem('workspaceModule.v1', 'plugins'); } catch (_) {}
          window.location.reload(); return;
        }
        heading.textContent = '重启成功'; introduction.hidden = true;
        message.textContent = '工作台已重新启动，插件已生效，可以继续使用。'; close.hidden = false; record = null; save(); setBusy(false); return;
      }
      if (Date.now() > current.deadline && job.phase !== 'waiting') { failed('暂未恢复连接，请重新检查连接。'); return; }
      timer = setTimeout(poll, 1000);
    } catch (error) {
      if (record !== current) return;
      if (Date.now() > current.deadline) failed('暂未恢复连接。' + error.message);
      else { message.textContent = (current.progress?.message ? current.progress.message + ' · ' : '') + '连接暂时断开，正在等待服务恢复…'; timer = setTimeout(poll, 1000); }
    } finally { polling = false; }
  }
  async function start({discardUnsaved = false} = {}) {
    if (starting) return;
    show();
    if (record) { poll(); return; }
    heading.textContent = '强制重启'; introduction.hidden = false; progress.hidden = true;
    starting = true;
    const confirmation = discardUnsaved
      ? '仍然强制重启将丢弃未保存的设置、复盘笔记和创作草稿，并中断正在执行的任务。确定丢弃这些未保存内容并重启吗？'
      : '将中断本机工作台正在执行的任务，并重新打开工作台，使插件生效。是否继续？';
    if (!window.confirm(confirmation)) { starting = false; if (!discardUnsaved) dialog.close(); return; }
    setBusy(true);
    close.hidden = true; retry.hidden = true; discard.hidden = true; message.textContent = '正在检查重启条件…';
    const owner = account();
    try {
      if (!owner) throw new Error('请先选择工作台。');
      if (window.prepareWorkbenchUpdate) {
        try {
          let saveTimeout;
          try {
            await Promise.race([window.prepareWorkbenchUpdate({discardUnsaved}), new Promise((_, reject) => {
              saveTimeout = setTimeout(() => reject(new Error('内容保存超时，请检查保存状态后重试。')), 15000);
            })]);
          } finally { clearTimeout(saveTimeout); }
        }
        catch (error) { throw Object.assign(new Error(error.message.replace(/更新/g, '重启')), {code:error.code}); }
      }
      const status = await request('/api/system/restart/status');
      if (status.transport === 'desktop' && !window.webkit?.messageHandlers?.workbenchRestart) {
        throw new Error('请在新版墨鱼工作台应用内强制重启；浏览器无法重新打开桌面应用。');
      }
      const result = await request('/api/plugins?accountId=' + encodeURIComponent(owner));
      if (account() !== owner) throw new Error('工作台已切换，请重新操作。');
      record = {accountId:owner, instanceId:status.instanceId, deadline:Date.now() + 180000,
        targets:(result.plugins || []).filter(view => view.pendingVersion).map(view => ({id:view.id, version:view.pendingVersion}))};
      updateProgress(record, {phase:'starting'});
      try {
        const job = await request('/api/system/restart/start', {force:true, confirmed:true}, status.operationToken);
        record.id = job.id; updateProgress(record, job);
      } catch (error) {
        const latest = await request('/api/system/restart/status');
        if (!active.has(latest.job?.phase)) { record = null; save(); throw error; }
        record.id = latest.job.id; updateProgress(record, latest.job);
      }
      if (status.transport === 'desktop') {
        try {
          await window.webkit.messageHandlers.workbenchRestart.postMessage({
            jobId:record.id, instanceId:status.instanceId,
            desktopInstance:status.desktopInstance, token:status.operationToken
          });
        } catch (error) {
          await request('/api/system/restart/native-failed', {jobId:record.id}, status.operationToken);
          record = null; save(); throw error;
        }
      }
      poll();
    } catch (error) {
      failed(error.message);
      if (!record && error.code === 'UNSAVED_WORKBENCH_FORMS') {
        message.textContent += ' 如需丢弃未保存内容，可选择“仍然强制重启”。';
        discard.hidden = false;
      }
    }
    finally { starting = false; }
  }
  window.WorkbenchRestart = {start};
  function resume() {
    try { record = JSON.parse(localStorage.getItem(key) || 'null'); } catch (_) {}
    if (record) { record.deadline = Date.now() + 180000; show(); if (!record.progress) updateProgress(record, {phase:'starting'}); poll(); }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', resume); else resume();
})();
