/* Presentation only: never changes the selected script or bypasses save guards. */
(() => {
  let reset = null, preview = null, destination = null, awaitingPublish = false;
  const snapshots = new Map();
  const key = context => JSON.stringify([context?.accountId, context?.scriptId, window.WorkbenchPlugins?.getViews?.().map(v => [v.id, v.enabled, v.resourceRevision])]);
  function capture() {
    const context = window.WorkbenchScriptContext?.();
    const panel = document.querySelector('#rewriteStage:not([hidden]), #coverStage:not([hidden]), #titleStage:not([hidden]), #publishStage:not([hidden])');
    if (!context?.scriptId) return;
    if (!panel || document.querySelector('.pm-stage-host:not([hidden])')) { snapshots.delete(key(context)); return; }
    const clone = panel.cloneNode(true);
    const fields = panel.querySelectorAll('input, textarea, select');
    clone.querySelectorAll('input, textarea, select').forEach((field, i) => {
      if (field.type !== 'file') field.value = fields[i].value;
      if ('checked' in field) field.checked = fields[i].checked;
    });
    const stage = ({rewriteStage:'edit', coverStage:'cover', titleStage:'title', publishStage:'publish'})[panel.id];
    clone.removeAttribute('id');clone.dataset.nativePreview = stage;
    clone.querySelectorAll('[id]').forEach(node => {
      node.dataset.previewId = node.id;
      node.removeAttribute('id');
    });
    clone.inert = true;
    const id = key(context);snapshots.delete(id);
    snapshots.set(id, {node: clone, stage, time: Date.now()});
    while (snapshots.size > 8) snapshots.delete(snapshots.keys().next().value);
  }
  function previewPlugin() {
    preview?.remove(); preview = null;
    // A remembered plugin stage overrides the script's native stage. Release
    // the retained live cover too, before the plugin measures its viewport.
    document.getElementById('workspaceContent')?.classList.remove('is-cover-switching');
  }
  const clear = () => { reset?.(); reset = null; awaitingPublish = false; destination = null; };
  function finish() {
    if (reset && document.getElementById('publishStage')?.hidden === false && document.getElementById('publishAssetsStatus')?.dataset.state === 'loading') {
      awaitingPublish = true;
      return;
    }
    clear();
  }
  function publishReady(context) {
    if (!awaitingPublish || context.accountId !== destination?.accountId || context.scriptId !== destination?.scriptId) return;
    if (preview?.dataset.nativePreview === 'publish') window.WorkbenchPublishPreviews?.seedFromSnapshot?.(preview);
    clear();
  }
  function begin(context, message, { failed = false } = {}) {
    const switching = !message && !failed;
    if (!reset) capture();
    clear();
    destination = context;
    if (switching) document.querySelectorAll('.history-record[data-script-id]').forEach(card => {
      const selected = card.dataset.scriptId === context.scriptId;
      card.classList.toggle('is-active', selected); card.setAttribute('aria-pressed', String(selected));
    });
    const content = document.getElementById('workspaceContent');
    if (!content) return;
    // Cover-to-cover navigation commits the new data in one synchronous render.
    // Keep the current panel visible and inert until then, rather than swapping
    // it for a clone (or an empty placeholder) and back again.
    const retainCover = switching && context.stage === 'cover'
      && document.getElementById('coverStage')?.hidden === false
      && !document.querySelector('.pm-stage-host:not([hidden])');
    const status = message ? document.createElement('div') : null;
    if (status) {
      status.className = 'script-navigation-status'; status.setAttribute('role', 'status');
      status.textContent = message;
    }
    const panels = [...content.querySelectorAll('.workflow-stage, .pm-stage-host, .workspace-script-actions, #stageNavigator')];
    const previous = panels.map(node => [node, node.inert]);
    panels.forEach(node => { node.inert = true; });
    content.classList.add('is-script-switching');
    content.classList.toggle('is-cover-switching', retainCover);
    if (switching && !retainCover) {
      const cached = snapshots.get(key(context));
      const hit = cached && Date.now() - cached.time < 300000;
      preview = hit ? cached.node.cloneNode(true) : document.createElement('div');
      preview.classList.add('script-stage-preview');preview.inert = true;
      for (const type of ['click', 'input', 'change', 'keydown', 'submit']) preview.addEventListener(type, event => { event.preventDefault(); event.stopImmediatePropagation(); }, true);
      content.querySelectorAll('#stageNavigator button').forEach(button => button.classList.toggle('is-active', button.dataset.stage === (hit ? cached.stage : context.stage || 'edit')));
      (document.getElementById('taskWorkspace') || content).append(preview);
    }
    if (status) {
      content.querySelector('#stageNavigator')?.after(status);
      if (!status.isConnected) content.prepend(status);
    }
    reset = () => {
      previous.forEach(([node, inert]) => { node.inert = inert; });
      content.classList.remove('is-script-switching'); status?.remove(); previewPlugin();
      content.classList.remove('is-cover-switching');
      // Snapshots begin at the top. Every native panel must match when revealed,
      // including the outer scrollers used by long editors and cover results.
      if (switching) content.querySelectorAll('#rewriteStage, #titleStage, #titleStage .title-platform-groups, #coverStage, #publishStage').forEach(node => { node.scrollTop = 0; });
    };
  }
  function fail(context) {
    // Keep stale panels locked; the caller reports the error through the toast.
    begin(context, undefined, { failed: true });
  }
  function invalidate() { snapshots.clear(); window.dispatchEvent(new CustomEvent('workbench:script-snapshots-invalidated')); }
  window.WorkbenchScriptNavigation = { begin, finish, fail, invalidate, previewPlugin, publishReady };
  window.addEventListener('workbench:plugins-changed', () => snapshots.clear());
  window.addEventListener('workbench:script-snapshots-invalidated', () => snapshots.clear());
  window.addEventListener('workbench:plugins-account-changed', () => { clear(); invalidate(); });
})();
