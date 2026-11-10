/* 通用插件宿主：多插件列表、详情弹窗外壳、阶段页签扩展槽与通用接口客户端。
   载入宿主不出现任何供应商细节；插件通过 window.WorkbenchPlugins 接入自己的界面。 */
(() => {
  "use strict";

  const HOST_API_VERSION = "1";
  const API_BASE = "/api/plugins";

  const plugins = new Map(); // id -> 插件定义
  const stages = new Map(); // stageId -> { pluginId, button, panel, show, hide }
  let views = [];
  let detailPluginId = null;
  let detailReturnFocus = null;
  let accountEpoch = 0;
  let loadSequence = 0;
  let detailSequence = 0;
  let loading = false;
  let loadError = "";
  const currentAccountId = () => window.WorkbenchScriptContext?.()?.accountId || null;

  // One account-scoped stream shared by all mounted plugin subscribers.
  let changeStream = null, changeAccount = null, changeConnected = false;
  const changeListeners = new Set();
  function stopChanges() {
    if (changeStream) changeStream.close();
    changeStream = null; changeAccount = null; changeConnected = false;
  }
  function watchChanges(pluginId, callback) {
    const accountId = currentAccountId();
    if (!accountId || typeof EventSource === "undefined") return () => {};
    if (changeAccount && changeAccount !== accountId) { stopChanges(); changeListeners.clear(); }
    const listener = { pluginId, callback, accountId };
    changeListeners.add(listener);
    if (!changeStream) {
      changeAccount = accountId;
      const source = new EventSource("/api/plugin-events?accountId=" + encodeURIComponent(accountId));
      changeStream = source;
      const dispatch = event => {
        if (changeStream !== source || currentAccountId() !== accountId) return;
        for (const item of [...changeListeners]) {
          if (item.accountId !== accountId || (event.pluginId && event.pluginId !== item.pluginId)) continue;
          try { item.callback(event); } catch (error) { console.error(error); }
        }
      };
      source.addEventListener("ready", () => {
        if (changeStream !== source) return;
        changeConnected = true; dispatch({ type: "connected" });
      });
      source.addEventListener("change", event => {
        try { dispatch({ ...JSON.parse(event.data), type: "change" }); } catch (_) {}
      });
      source.onerror = () => {
        if (changeStream !== source) return;
        changeConnected = false; dispatch({ type: "disconnected" });
      };
    } else if (changeConnected) callback({ type: "connected" });
    return () => { changeListeners.delete(listener); if (!changeListeners.size) stopChanges(); };
  }

  const returnListeners = new Map();
  function syncReturnListeners() {
    for(const [id,stop] of returnListeners){if(!isAvailable(id)){stop();returnListeners.delete(id);}}
    for(const view of views){
      if(!isAvailable(view.id)||returnListeners.has(view.id))continue;
      const account=currentAccountId(),epoch=accountEpoch,id=view.id;
      returnListeners.set(id,watchChanges(id,event=>{
        const notice=event.notice;
        if(!notice||typeof notice.id!=='string'||typeof notice.message!=='string')return;
        const current=()=>accountEpoch===epoch&&currentAccountId()===account&&isAvailable(id);
        if(!current())return;
        const key='workbench-return:'+JSON.stringify([account,id,notice.id]);
        window.WorkbenchReturnFeedback?.notify(key,notice.message,notice.success===true,current).catch(()=>{});
      }));
    }
  }

  const pendingRequests = new Set();
  async function workspaceFetch(url, options) {
    const controller = new AbortController();
    pendingRequests.add(controller);
    try { return await fetch(url, { ...options, signal: controller.signal }); }
    finally { pendingRequests.delete(controller); }
  }

  // ------------------------------------------------------------- 通用接口
  async function rawRequest(method, url, body, accountId = currentAccountId()) {
    if (!accountId) throw new Error("请先选择工作台。");
    const epoch = accountEpoch;
    url += (url.includes("?") ? "&" : "?") + "accountId=" + encodeURIComponent(accountId);
    const multipart = typeof FormData !== "undefined" && body instanceof FormData;
    let response;
    try {
      response = await workspaceFetch(url, {
        method,
        headers: body && !multipart ? { "Content-Type": "application/json" } : undefined,
        body: multipart ? body : body ? JSON.stringify(body) : undefined,
      });
    } catch (error) {
      if (epoch !== accountEpoch || accountId !== currentAccountId()) {
        const stale = new Error(""); stale.code = "stale_workspace"; throw stale;
      }
      const err = new Error("无法连接本地服务，请确认工作台正在运行。");
      err.code = "network";
      throw err;
    }
    let data = {};
    try { data = await response.json(); } catch (_) { data = {}; }
    if (epoch !== accountEpoch || accountId !== currentAccountId()) {
      const error = new Error("");
      error.code = "stale_workspace";
      throw error;
    }
    if (!response.ok) {
      const detail = (data && data.detail) || {};
      const err = new Error(detail.message || data.message || "操作失败，请稍后重试。");
      err.code = detail.code || data.code || "error";
      err.status = response.status;
      throw err;
    }
    return data;
  }

  function createApi(boundAccountId) {
    const boundEpoch = accountEpoch;
    const account = () => boundAccountId === undefined ? currentAccountId() : boundAccountId;
    const request = (method, path, body, accountId = account()) => rawRequest(method, API_BASE + path, body, accountId);
    const mutatePackage = async (method, path, body) => {
      const epoch = accountEpoch, accountId = account();
      if (accountId !== currentAccountId() || (boundAccountId !== undefined && boundEpoch !== accountEpoch)) {
        const error = new Error(""); error.code = "stale_workspace"; throw error;
      }
      const result = await request(method, path, body, accountId);
      signalPackageChange();
      if (epoch === accountEpoch && accountId === currentAccountId()) await refreshAll();
      return result;
    };
    return {
      hostApiVersion: HOST_API_VERSION,
      listPlugins: () => request("GET", ""),
      confirmPackage: (token) => mutatePackage("POST", "/packages/confirm", {token, trusted: true}),
      getPlugin: (id) => request("GET", "/" + encodeURIComponent(id)),
      install: (id) => mutatePackage("POST", "/" + encodeURIComponent(id) + "/install"),
      enable: (id) => request("POST", "/" + encodeURIComponent(id) + "/enable"),
      disable: (id) => request("POST", "/" + encodeURIComponent(id) + "/disable"),
      uninstall: async (id) => {
        const epoch = accountEpoch, accountId = account();
        if (!accountId || accountId !== currentAccountId() || (boundAccountId !== undefined && boundEpoch !== accountEpoch)) {
          const error = new Error(""); error.code = "stale_workspace"; throw error;
        }
        const name = viewFor(id)?.name || id;
        if (!window.confirm("全局卸载“" + name + "”？此操作影响所有工作台，所有工作台将无法使用该插件。各工作台的凭据、平台配置、任务数据和媒体文件均保留；重新安装后默认停用，需在各工作台分别启用。")) {
          // Reject so older detail callers cannot run their success/close path.
          const error = new Error(""); error.code = "cancelled"; throw error;
        }
        if (epoch !== accountEpoch || accountId !== currentAccountId()) {
          const error = new Error(""); error.code = "stale_workspace"; throw error;
        }
        return mutatePackage("POST", "/packages/" + encodeURIComponent(id) + "/uninstall", {confirmed: true});
      },
      credentialStatus: (id) => request("GET", "/" + encodeURIComponent(id) + "/credentials"),
      setCredential: (id, value) => request("PUT", "/" + encodeURIComponent(id) + "/credentials", { value }),
      deleteCredential: (id) => request("DELETE", "/" + encodeURIComponent(id) + "/credentials"),
      verifyCredential: (id) => request("POST", "/" + encodeURIComponent(id) + "/credentials/verify"),
      pluginFetch: (id, method, path, body, accountId = account()) => request(method, "/" + encodeURIComponent(id) + (path || ""), body, accountId),
      adoptPublishMedia: (scriptId, media, replace, accountId = account()) =>
        rawRequest("POST", "/api/scripts/" + encodeURIComponent(scriptId) + "/publish-assets/adopt", {
          media, replace: Boolean(replace),
        }, accountId),
    };
  }
  const api = createApi();

  // ------------------------------------------------------------- 轻提示
  let toastEl = null;
  let toastTimer = null;
  function toast(message, type) {
    if (!message) return;
    // Share the host's top-layer notification so native plugin dialogs cannot cover it.
    if (typeof showToast === "function") return showToast(message, type || "info", 3600);
    if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.setAttribute("role", "status");
      toastEl.setAttribute("aria-live", "polite");
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = message;
    toastEl.className = "pm-toast" + (type === "success" ? " is-success" : type === "error" ? " is-error" : "");
    toastEl.hidden = false;
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => { toastEl.hidden = true; }, 3600);
  }

  function viewFor(id) {
    return views.find((item) => item.id === id) || null;
  }

  function isAvailable(id) {
    const view = viewFor(id);
    return !!(view && view.installed && view.enabled && !view.loadError);
  }

  // ------------------------------------------------------------- 注册与扩展槽
  function contextFor(id) {
    return {
      api,
      pluginId: id,
      watchChanges: callback => watchChanges(id, callback),
      toast,
      refresh: refreshAll,
      openDetail: (pluginId) => openDetail(pluginId || id),
      registerStageTab: (config) => registerStageTab(id, config),
    };
  }

  function registerPlugin(definition) {
    const id = definition && definition.id;
    if (!id) throw new Error("插件缺少 id");
    if (String(definition.hostApiVersion || "").split(".")[0] !== HOST_API_VERSION) {
      window.console && console.warn("插件 " + id + " 与宿主接口版本不兼容，已跳过加载。");
      return;
    }
    plugins.set(id, definition);
    if (typeof definition.mount === "function") {
      try { definition.mount(contextFor(id)); }
      catch (error) { window.console && console.error("插件 " + id + " 挂载失败", error); }
    }
    if (views.length) { renderManagement(); syncStages(); }
  }

  function registerStageTab(pluginId, config) {
    const nav = document.getElementById("stageNavigator");
    // 与宿主阶段同一容器，插件视图才能占据阶段区域而不是堆在编辑区下方。
    const host = document.getElementById("taskWorkspace") || document.getElementById("workspaceContent");
    if (!nav || !host) return;
    const anchor = config.afterStage
      ? nav.querySelector('button[data-stage="' + config.afterStage + '"]')
      : null;
    const separator = anchor ? anchor.nextElementSibling : null;
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.pluginStage = config.id;
    button.textContent = config.label;
    button.hidden = true;
    const stageSeparator = document.createElement("span");
    stageSeparator.setAttribute("aria-hidden", "true");
    stageSeparator.hidden = true;
    const insertAfter = separator && separator.tagName === "SPAN" ? separator : anchor;
    if (insertAfter && insertAfter.parentElement === nav) insertAfter.after(button);
    else nav.appendChild(button);
    button.after(stageSeparator);

    const panel = document.createElement("section");
    panel.className = "pm-stage-host";
    panel.dataset.pluginStage = config.id;
    if (typeof config.previewContext === "function") panel.dataset.scriptPreview = "true";
    panel.hidden = true;
    host.appendChild(panel);
    if (typeof config.mount === "function") config.mount(panel);
    button.addEventListener("click", () => showStage(config.id));
    stages.set(config.id, {
      pluginId,
      button,
      separator: stageSeparator,
      panel,
      show: config.show,
      hide: config.hide,
      prepareContext: config.prepareContext,
      previewContext: config.previewContext,
      afterStage: config.afterStage,
      order: Number(config.order) || 0,
    });
    // Stable sibling order when several independently loaded plugins share a slot.
    if (insertAfter) {
      let previous = insertAfter;
      [...stages.values()].filter(item => item.afterStage === config.afterStage)
        .sort((a,b) => a.order - b.order || a.pluginId.localeCompare(b.pluginId))
        .forEach(item => {
          previous.after(item.button, item.separator);
          previous = item.separator;
        });
    }
  }

  const HOST_STAGE_IDS = ["rewriteStage", "splitStage", "writeStage", "titleStage", "coverStage", "publishStage"];

  function hostStageSections() {
    return HOST_STAGE_IDS.map((id) => document.getElementById(id)).filter(Boolean);
  }

  const stageSelections = new Map();

  function stageSelectionKey(context = window.WorkbenchScriptContext?.()) {
    if (!context?.scriptId) return null;
    return "workbench.pluginStage.v1." + JSON.stringify([context.accountId || null, context.scriptId]);
  }

  function rememberStage(stageId) {
    const key = stageSelectionKey();
    if (!key) return;
    stageSelections.set(key, stageId || null);
    try {
      if (stageId) localStorage.setItem(key, stageId);
      else localStorage.removeItem(key);
    } catch (_) { /* Storage is optional; retain the selection for this page. */ }
  }

  function restoreStage() {
    const key = stageSelectionKey();
    if (!key) return;
    let stageId = stageSelections.get(key);
    if (!stageSelections.has(key)) {
      try { stageId = localStorage.getItem(key); } catch (_) { /* storage is optional */ }
    }
    const entry = stages.get(stageId);
    if (entry && !entry.button.hidden && entry.panel.hidden) showStage(stageId);
  }

  // Prepare only the visible plugin or the target's remembered plugin stage.
  // Older plugins without this optional hook retain their existing behavior.
  async function prepareScriptContext(context) {
    const key = stageSelectionKey(context);
    let remembered = stageSelections.get(key);
    if (!stageSelections.has(key)) {
      try { remembered = localStorage.getItem(key); } catch (_) {}
    }
    const target = stages.get(remembered);
    // Present the destination without calling show() or changing committed context.
    // show() remains behind the host's ownership/save checks.
    for (const entry of stages.values()) {
      if (entry !== target && !entry.panel.hidden) {
        entry.hide?.({cancelPreview: true});
        entry.panel.hidden = true;
        entry.button?.classList.remove("is-active");
      }
    }
    if (target && isAvailable(target.pluginId) && typeof target.previewContext === 'function') {
      try {
        // Remove the host placeholder before the plugin measures its viewport.
        window.WorkbenchScriptNavigation?.previewPlugin?.();
        target.panel.hidden = false;
        target.previewContext(context);
        document.querySelectorAll('#stageNavigator button').forEach(button => button.classList.remove('is-active'));
        target.button.classList.add('is-active');
      } catch (_) { target.panel.hidden = true; /* Optional preview cannot block navigation. */ }
    }
    await Promise.allSettled([...stages.entries()]
      .filter(([id, entry]) => isAvailable(entry.pluginId) && id === remembered && typeof entry.prepareContext === 'function')
      .map(([, entry]) => Promise.resolve().then(() => entry.prepareContext(context))));
  }

  function showStage(stageId) {
    const entry = stages.get(stageId);
    if (!entry || entry.button.hidden) return;
    hostStageSections().forEach((section) => { section.hidden = true; });
    document.querySelectorAll('#stageNavigator button[data-stage]').forEach((button) => {
      button.classList.remove("is-active");
    });
    stages.forEach((item) => {
      if (item !== entry && !item.panel.hidden && typeof item.hide === "function") item.hide();
      if (item === entry) return;
      item.panel.hidden = true;
      item.button.classList.remove("is-active");
    });
    rememberStage(stageId);
    entry.panel.hidden = false;
    entry.button.classList.add("is-active");
    if (typeof entry.show === "function") entry.show();
  }

  function syncStages() {
    stages.forEach((entry) => {
      const available = isAvailable(entry.pluginId);
      entry.button.hidden = !available;
      entry.separator.hidden = !available;
      if (available) return;
      const wasShown = !entry.panel.hidden;
      if (typeof entry.hide === "function") entry.hide({invalidate: true});
      entry.panel.hidden = true;
      entry.button.classList.remove("is-active");
      // 插件不可用时回到编辑阶段，但不触发阶段保存或生成。
      if (wasShown) {
        const edit = document.getElementById("rewriteStage");
        const editButton = document.getElementById("editStageButton");
        if (edit) edit.hidden = false;
        if (editButton) editButton.classList.add("is-active");
      }
    });
    restoreStage();
  }

  // 宿主渲染任何原生阶段时，收起插件的阶段视图。
  function onHostStageRender() {
    stages.forEach((entry) => {
      if (typeof entry.hide === "function") entry.hide();
      entry.panel.hidden = true;
      entry.button.classList.remove("is-active");
    });
    restoreStage();
  }

  // ------------------------------------------------------------- 插件管理页面
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function stateTag(view) {
    if (!view.installed) return { text: "未安装", className: "pm-tag" };
    if (view.enabled) return { text: "已启用", className: "pm-tag is-success" };
    return { text: "已停用", className: "pm-tag" };
  }

  function configTag(view) {
    if (view.configStatus === "not_required") return null;
    if (view.configStatus === "configured") return { text: "已配置", className: "pm-tag is-success" };
    if (view.configStatus === "invalid") return { text: "凭据失效", className: "pm-tag is-danger" };
    return { text: "未配置", className: "pm-tag is-warn" };
  }

  function pluginDescription(view) {
    if (view.id === "ai-edit" && view.description === "通过 Codex / WorkBuddy 剪辑口播视频，成片自动回传。") {
      return "适用于已录制的口播原视频，通过 Codex / WorkBuddy 进行 AI 自动剪辑，成片自动回传工作台。";
    }
    return view.description || "";
  }

  function buildCard(view) {
    const cardApi = createApi(currentAccountId());
    const epoch = accountEpoch;
    const definition = plugins.get(view.id);
    const card = el("article", "pm-card");
    card.dataset.pluginId = view.id;
    const open = el("button", "pm-card-open");
    open.type = "button";
    open.setAttribute("aria-label", "查看 " + view.name + " 详情");
    const symbol = el("span", "pm-symbol");
    const iconUrl = view.resources?.icon || definition?.icon || (view.id === "ai-edit" ? "/static/images/ai-edit.svg" : "");
    if (iconUrl) {
      const icon = el("img", "pm-symbol-image");
      icon.src = iconUrl;
      icon.alt = "";
      symbol.appendChild(icon);
    } else {
      symbol.textContent = (definition && definition.symbol) || (view.name || "?").slice(0, 1);
    }
    open.appendChild(symbol);
    const copy = el("span", "pm-card-copy");
    copy.appendChild(el("h3", null, view.name));
    const tags = el("span", "pm-card-tags");
    tags.appendChild(el("span", view.installed ? "pm-tag is-success" : "pm-tag", view.installed ? "已安装" : "未安装"));
    const state = stateTag(view);
    if (view.installed) tags.appendChild(el("span", state.className, state.text));
    const config = configTag(view);
    if (config) tags.appendChild(el("span", config.className, config.text));
    copy.appendChild(tags);
    open.appendChild(copy);
    card.appendChild(open);
    const description = el("p");
    description.appendChild(document.createTextNode(pluginDescription(view)));
    if (view.version) {
      description.appendChild(document.createElement("br"));
      description.appendChild(el("span", "pm-save-note", "当前生效版本 " + (view.activeVersion || (view.restartRequired || view.loadError ? "未生效" : view.version))));
    }
    card.appendChild(description);
    appendRestartNotice(card, view);
    if (view.installError) card.appendChild(el("p", "pm-callout", view.installError));
    const details = el("button", "pm-card-details", "查看详情 →");
    details.type = "button";
    const footer = el("div", "pm-card-footer");
    footer.appendChild(details);
    const toggle = el("button", "pm-switch");
    toggle.type = "button";
    toggle.setAttribute("role", "switch");
    toggle.setAttribute("aria-label", "启用 " + view.name);
    toggle.setAttribute("aria-checked", String(Boolean(view.installed && view.enabled)));
    toggle.disabled = !view.installed || !!view.loadError;
    toggle.title = view.installed ? "仅在当前工作台启用 / 停用插件" : "全局安装后可在当前工作台启用";
    toggle.appendChild(el("span"));
    toggle.addEventListener("click", async () => {
      if (toggle.disabled) return;
      toggle.disabled = true;
      toggle.setAttribute("aria-busy", "true");
      try {
        await (view.enabled ? cardApi.disable(view.id) : cardApi.enable(view.id));
        if (epoch !== accountEpoch) return;
        await refreshAll();
        if (epoch !== accountEpoch) return;
        toast(view.enabled ? "插件已停用。" : "插件已启用。", "success");
        const replacement = document.querySelector(
          '#pluginsContent .pm-card[data-plugin-id="' + view.id + '"] .pm-switch'
        );
        if (replacement) replacement.focus();
      } catch (error) {
        if (epoch === accountEpoch) toast(error.message, "error");
      } finally {
        toggle.disabled = !view.installed || !!view.loadError;
        toggle.removeAttribute("aria-busy");
      }
    });
    footer.appendChild(toggle);
    card.appendChild(footer);
    open.addEventListener("click", () => openDetail(view.id, details));
    details.addEventListener("click", () => openDetail(view.id, details));
    return card;
  }

  function appendRestartNotice(container, view) {
    if (!view.pendingVersion && !view.migrationPending) return;
    const message = view.migrationPending
      ? "插件正在等待旧版任务结束；请等待所有工作台的任务结束后再重启，完成全局插件迁移。"
      : "请等待所有工作台的任务结束后再重启生效。";
    container.appendChild(el("p", "pm-callout", (view.pendingVersion ? "待生效版本 " + view.pendingVersion + " · " : "") + message));
    container.appendChild(restartButton());
  }

  function restartButton() {
    const button = el("button", "pm-btn is-primary pm-restart-button", "强制重启");
    button.type = "button";
    button.addEventListener("click", () => window.WorkbenchRestart?.start());
    return button;
  }

  function renderManagement() {
    const root = document.getElementById("pluginsContent");
    if (!root) return;
    const header = el("header", "pm-header");
    const copy = el("div");
    copy.appendChild(el("h1", "pm-title", "插件管理"));
    copy.appendChild(el("p", "pm-subtitle", "插件统一安装和升级；启用状态、平台配置和任务数据按工作台独立保存。"));
    header.appendChild(copy);
    const actions = el("div", "pm-header-actions");
    if (root.dataset.returnModule === "scripts") {
      const backButton = el("button", "pm-btn", "返回内容工作台");
      backButton.type = "button";
      backButton.addEventListener("click", () => {
        window.selectWorkspaceModule?.("scripts");
        document.getElementById("workspacePluginManagementButton")?.focus();
      });
      actions.appendChild(backButton);
    }
    const addButton = el("button", "pm-btn", "导入插件");
    addButton.type = "button";
    addButton.addEventListener("click", openPackageImport);
    actions.appendChild(addButton);
    header.appendChild(actions);

    const fragment = document.createDocumentFragment();
    fragment.appendChild(header);
    if (loadError && views.length) fragment.appendChild(el("p", "pm-callout", loadError));
    if (!views.length) {
      fragment.appendChild(el("div", "pm-empty", (!currentAccountId() ? "请先选择工作台。" : loading ? "正在读取插件…" : loadError || "尚未安装插件；安装后所有工作台均可使用。")));
    } else {
      const grid = el("section", "pm-grid");
      grid.setAttribute("aria-label", "插件卡片列表");
      views.forEach((view) => grid.appendChild(buildCard(view)));
      fragment.appendChild(grid);
      fragment.appendChild(el("p", "pm-note", "安装、升级和卸载影响所有工作台；卡片开关和平台凭据仅作用于当前工作台。"));
    }
    root.replaceChildren(fragment);
  }

  // ------------------------------------------------------------- 详情弹窗
  let dialog = null;
  let dialogBody = null;
  let dialogTitle = null;
  let dialogSubtitle = null;

  function ensureDialog() {
    if (dialog) return;
    dialog = document.createElement("dialog");
    dialog.className = "pm-dialog";
    dialog.id = "pluginDetailDialog";
    const head = el("header", "pm-dialog-head");
    dialogTitle = el("h2", "modal-title");
    dialogTitle.id = "pluginDetailTitle";
    const dismiss = el("button", "pm-dismiss am-modal-dismiss");
    dismiss.type = "button";
    dismiss.setAttribute("aria-label", "关闭插件详情");
    dismiss.innerHTML = '<svg class="am-modal-close-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="m6 6 12 12M18 6 6 18"/></svg>';
    dismiss.addEventListener("click", closeDetail);
    head.appendChild(dialogTitle);
    head.appendChild(dismiss);
    dialog.appendChild(head);
    dialogSubtitle = el("p", "pm-dialog-subtitle");
    dialog.appendChild(dialogSubtitle);
    dialogBody = el("div", "pm-dialog-body");
    dialog.appendChild(dialogBody);
    dialog.addEventListener("close", () => {
      const pluginId = detailPluginId;
      let target = detailReturnFocus && detailReturnFocus.isConnected ? detailReturnFocus : null;
      // 卡片可能已重建，回退到同一插件的“查看详情”入口，保证焦点回到触发点。
      if (!target && pluginId) {
        target = document.querySelector(
          '#pluginsContent .pm-card[data-plugin-id="' + pluginId + '"] .pm-card-details'
        );
      }
      detailPluginId = null;
      if (target && typeof target.focus === "function") target.focus();
    });
    document.body.appendChild(dialog);
  }

  function openDetail(pluginId, trigger) {
    const view = viewFor(pluginId);
    if (!view) { toast("插件不存在或未加载。", "error"); return; }
    ensureDialog();
    detailPluginId = pluginId;
    detailReturnFocus = trigger || document.activeElement;
    renderDetail();
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "open");
    const dismiss = dialog.querySelector(".pm-dismiss");
    if (dismiss) dismiss.focus();
  }

  function closeDetail() {
    detailSequence++;
    if (!dialog) return;
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  }

  function renderDetail() {
    if (!dialog || !detailPluginId) return;
    const view = viewFor(detailPluginId);
    const definition = plugins.get(detailPluginId);
    if (!view) { closeDetail(); return; }
    dialogTitle.textContent = view.name;
    dialogSubtitle.textContent = pluginDescription(view);
    dialogBody.replaceChildren();
    dialogBody.appendChild(el("p", "pm-save-note", "安装、升级和卸载影响所有工作台；启用状态和平台凭据按工作台独立保存。卸载保留凭据、配置、任务和媒体，重新安装后默认停用。"));
    appendRestartNotice(dialogBody, view);
    if (view.installError) dialogBody.appendChild(el("p", "pm-callout", view.installError));

    const epoch = accountEpoch, sequence = ++detailSequence;
    const isCurrent = () => epoch === accountEpoch && sequence === detailSequence && !!detailPluginId;
    const host = {
      api: createApi(currentAccountId()),
      isCurrent,
      toast,
      view,
      pluginId: detailPluginId,
      refresh: refreshAll,
      reloadViews: () => isCurrent() ? reloadViews() : Promise.resolve(null),
      close: () => { if (isCurrent()) closeDetail(); },
      openDetail,
    };
    if (definition && typeof definition.renderDetail === "function") {
      const content = el("div"); dialogBody.appendChild(content);
      definition.renderDetail(content, host);
    } else {
      dialogBody.appendChild(el("p", "pm-save-note", view.loadError ? "插件尚未成功加载；请按提示重启或重新导入插件包。" : "该插件暂无配置项。"));
      const remove = el("button", "pm-btn", "卸载插件");
      remove.type = "button";
      remove.addEventListener("click", async () => {
        remove.disabled = true;
        try { await host.api.uninstall(host.pluginId); if (isCurrent()) { closeDetail(); await refreshAll(); } }
        catch (error) { if (isCurrent()) { toast(error.message, "error"); remove.disabled = false; } }
      });
      dialogBody.appendChild(remove);
    }
  }

  // One shared loader per immutable resource URL. Failed loads can be retried.
  const resourceLoads = new Map();
  const loadedVersions = new Map();
  const completedResources = new Set();
  const styleNodes = new Map();
  function loadResource(url, style) {
    if (resourceLoads.has(url)) return resourceLoads.get(url);
    const promise = new Promise((resolve, reject) => {
      const node = document.createElement(style ? "link" : "script");
      if (style) { node.rel = "stylesheet"; node.href = url; styleNodes.set(url, node); }
      else { node.src = url; node.async = false; }
      node.onload = resolve;
      node.onerror = () => { node.remove(); resourceLoads.delete(url); reject(new Error("插件资源加载失败，请刷新重试。")); };
      document.head.appendChild(node);
    });
    resourceLoads.set(url, promise);
    return promise;
  }
  async function loadPluginResources(items, isCurrent) {
    for (const view of items) {
      if (!view.resources || view.loadError) continue;
      if (!isCurrent()) return;
      const revision = view.activeVersion + ":" + (view.resourceRevision || "");
      if (loadedVersions.has(view.id) && loadedVersions.get(view.id) !== revision) {
        // The host persists the selected workspace before notifying plugins.
        window.location.reload();
        return;
      }
      const alreadyLoaded = completedResources.has(view.id);
      loadedVersions.set(view.id, revision);
      try {
        for (const url of view.resources.styles || []) await loadResource(url, true);
        if (!alreadyLoaded) {
          for (const url of view.resources.scripts || []) {
            if (!isCurrent()) return;
            await loadResource(url, false);
          }
        }
        completedResources.add(view.id);
      } catch (error) { view.loadError = "resources_failed"; if (isCurrent()) toast(error.message, "error"); }
    }
  }

  let importDialog = null;
  function openPackageImport() {
    const account = currentAccountId(), epoch = accountEpoch;
    if (!account) { toast("请先选择工作台。", "error"); return; }
    if (importDialog) importDialog.remove();
    const modal = el("dialog", "pm-dialog pm-import-dialog");
    importDialog = modal;
    modal.setAttribute("aria-labelledby", "packageImportTitle");
    const title = el("h2", "modal-title", "导入插件包"); title.id = "packageImportTitle";
    modal.appendChild(title);
    const introduction = el("p", "pm-save-note", "选择插件 ZIP 文件，为所有工作台统一安装或升级；启用状态和平台凭据仍按工作台独立保存。");
    modal.appendChild(introduction);
    const file = el("input", "pm-package-file"); file.type = "file"; file.accept = ".zip,application/zip";
    file.setAttribute("aria-label", "选择插件 ZIP 文件"); file.hidden = true;
    const fileRow = el("div", "pm-package-picker");
    const chooseFile = el("button", "pm-package-choose", "选择文件"); chooseFile.type = "button";
    const fileName = el("span", "pm-package-filename", "未选择文件");
    fileName.setAttribute("role", "status");
    chooseFile.addEventListener("click", () => { if (!file.disabled) file.click(); });
    fileRow.append(file, chooseFile, fileName); modal.appendChild(fileRow);
    const preview = el("div", "pm-package-preview"); modal.appendChild(preview);
    const trustLabel = el("label", "pm-package-trust");
    const trust = el("input"); trust.type = "checkbox";
    trustLabel.appendChild(trust);
    trustLabel.appendChild(document.createTextNode("我确认此插件包来自可信来源，允许其中的代码在本机运行。"));
    trustLabel.hidden = true; modal.appendChild(trustLabel);
    const status = el("p", "pm-message"); status.setAttribute("role", "status"); modal.appendChild(status);
    const actions = el("div", "pm-dialog-actions");
    const close = el("button", "pm-btn", "关闭"); close.type = "button";
    const confirm = el("button", "pm-btn is-primary", "确认导入"); confirm.type = "button"; confirm.disabled = true;
    actions.append(close, confirm); modal.appendChild(actions);
    let checked = null, busy = false, sequence = 0;
    const current = () => epoch === accountEpoch && account === currentAccountId() && importDialog === modal && modal.open;
    function refreshButton() { confirm.disabled = busy || !checked || !trust.checked; }
    function setBusy(value) { busy = value; file.disabled = value; chooseFile.disabled = value; close.disabled = value; refreshButton(); }
    close.addEventListener("click", () => modal.close());
    modal.addEventListener("cancel", (event) => { if (busy) event.preventDefault(); });
    modal.addEventListener("close", () => { sequence++; modal.remove(); if (importDialog === modal) importDialog = null; });
    trust.addEventListener("change", refreshButton);
    file.addEventListener("change", async () => {
      const selected = file.files[0];
      fileName.textContent = selected ? selected.name : "未选择文件";
      fileName.title = selected ? selected.name : "";
      if (!selected) {
        sequence++; checked = null; trust.checked = false; trustLabel.hidden = true;
        preview.replaceChildren(); status.textContent = ""; refreshButton(); return;
      }
      const request = ++sequence; checked = null; trust.checked = false; trustLabel.hidden = true;
      preview.replaceChildren(); status.textContent = "正在检查插件包…"; setBusy(true);
      try {
        if (selected.size > 32 * 1024 * 1024) throw new Error("插件包超过 32 MB 限制。");
        const body = new FormData(); body.append("file", selected);
        const response = await workspaceFetch(API_BASE + "/packages/check?accountId=" + encodeURIComponent(account), {method: "POST", body});
        const result = await response.json();
        if (!current() || request !== sequence) return;
        if (!response.ok) throw new Error(result.detail?.message || "插件包检查失败。");
        checked = result;
        preview.appendChild(el("h3", null, result.manifest.name));
        preview.appendChild(el("p", "pm-save-note", "当前生效：" + (result.activeVersion || "未安装") + " → 导入版本：" + result.manifest.version));
        if (result.pendingVersion) preview.appendChild(el("p", "pm-save-note", "已有待生效版本：" + result.pendingVersion));
        preview.appendChild(el("p", "pm-tag is-success", "兼容检查通过"));
        const installNote = result.action === "unchanged" ? "此版本已导入，确认后为所有工作台安装并保留各工作台已有配置。" : "为所有工作台安装或升级；请等待所有工作台的任务结束后再重启服务生效。";
        const releaseNotes = (result.manifest.releaseNotes || "").trim();
        const notesSeparator = releaseNotes && !/[。！？.!?]$/.test(releaseNotes) ? "。" : "";
        preview.appendChild(el("p", "pm-package-notes", releaseNotes + notesSeparator + (releaseNotes ? " " : "") + installNote));
        status.textContent = "";
        confirm.textContent = result.action === "upgrade" ? "确认升级" : "确认安装";
        trustLabel.hidden = false;
      } catch (error) { if (current()) status.textContent = error.message || "无法检查插件包。"; }
      finally { if (current()) setBusy(false); }
    });
    confirm.addEventListener("click", async () => {
      if (!checked || !trust.checked || busy) return;
      setBusy(true); status.textContent = "正在保存插件包…";
      try {
        const result = await createApi(account).confirmPackage(checked.token);
        if (!current()) return;
        checked = null;
        introduction.remove(); fileRow.remove(); preview.remove(); trustLabel.remove(); confirm.remove();
        title.textContent = result.restartRequired ? "请重启工作台" : "插件已安装";
        status.textContent = result.restartRequired
          ? "插件已为所有工作台导入；请等待所有工作台的任务结束后再重启生效。重启会让所有工作台短暂断开连接。"
          : "当前版本已为所有工作台安装；请在需要使用的工作台配置并启用。";
        close.textContent = result.restartRequired ? "稍后重启" : "知道了";
        if (result.restartRequired) actions.appendChild(restartButton());
        else close.classList.add("is-primary");
        setBusy(false);
        close.focus();
      } catch (error) { if (current()) status.textContent = error.message; }
      finally { if (current()) setBusy(false); }
    });
    document.body.appendChild(modal); modal.showModal();
  }

  // ------------------------------------------------------------- 刷新与启动

  // 重新拉取插件视图并刷新卡片与页签；返回指定插件视图，供详情自我重绘。
  async function reloadViews({ background = false } = {}) {
    const accountId = currentAccountId(), epoch = accountEpoch, sequence = ++loadSequence;
    const isCurrent = () => epoch === accountEpoch && sequence === loadSequence && accountId === currentAccountId();
    const previousViews = JSON.stringify(views), previousError = loadError;
    if (!background) {
      loading = !!accountId;
      loadError = "";
      if (!accountId) views = [];
      renderManagement();
    }
    try {
      const payload = accountId ? await createApi(accountId).listPlugins() : {plugins: []};
      if (!isCurrent()) return null;
      loadError = (payload.failures || []).map(item => item.message).join("；");
      const incoming = (payload && payload.plugins) || [];
      await loadPluginResources(incoming, isCurrent);
      if (!isCurrent()) return null;
      views = incoming;
    } catch (error) {
      if (!isCurrent()) return null;
      if (background) return null;
      views = [];
      loadError = error.message || "插件读取失败，请稍后重试。";
      toast(loadError, "error");
    }
    loading = false;
    if (background && previousViews === JSON.stringify(views) && previousError === loadError) return null;
    syncReturnListeners();
    renderManagement();
    window.dispatchEvent(new CustomEvent("workbench:plugins-changed"));
    syncStages();
    return detailPluginId ? viewFor(detailPluginId) : null;
  }

  async function refreshAll(options) {
    const epoch = accountEpoch, previousDetail = JSON.stringify(viewFor(detailPluginId));
    await reloadViews(options);
    if (epoch === accountEpoch && detailPluginId &&
        (!options?.background || previousDetail !== JSON.stringify(viewFor(detailPluginId)))) renderDetail();
  }

  const PACKAGE_REVISION_KEY = "workbench.plugins.global-revision";
  let packageRevision = 0;
  function signalPackageChange() {
    try {
      // A fresh value emits a storage event in other tabs, including other workspaces.
      window.localStorage.setItem(PACKAGE_REVISION_KEY, Date.now() + ":" + (++packageRevision) + ":" + Math.random());
    } catch (_) { /* Focus/visibility refresh remains available when storage is blocked. */ }
  }

  let foregroundRefresh = null, packageRefreshQueued = false;
  function onPackageRevision(event) {
    if (event.key !== PACKAGE_REVISION_KEY || !event.newValue) return;
    // A mutation arriving during a fetch requires another read after that fetch.
    if (foregroundRefresh) { packageRefreshQueued = true; return foregroundRefresh; }
    return refreshOnForeground();
  }
  function refreshOnForeground() {
    if (document.visibilityState === "hidden" || !currentAccountId() || foregroundRefresh) return;
    foregroundRefresh = refreshAll({background: true}).finally(() => {
      foregroundRefresh = null;
      if (packageRefreshQueued) {
        packageRefreshQueued = false;
        return refreshOnForeground();
      }
    });
    return foregroundRefresh;
  }

  function onAccountChange() {
    accountEpoch++;
    stopChanges(); changeListeners.clear(); returnListeners.clear();
    pendingRequests.forEach((controller) => controller.abort());
    pendingRequests.clear();
    if ([...loadedVersions.keys()].some((id) => !completedResources.has(id))) {
      window.location.reload();
      return Promise.resolve();
    }
    styleNodes.forEach((node, url) => { node.remove(); resourceLoads.delete(url); });
    styleNodes.clear();
    if (importDialog) importDialog.close();
    loadSequence++;
    views = [];
    closeDetail();
    detailPluginId = null;
    syncStages();
    window.dispatchEvent(new CustomEvent("workbench:plugins-account-changed"));
    return refreshAll();
  }

  window.WorkbenchPlugins = {
    hostApiVersion: HOST_API_VERSION,
    api,
    registerPlugin,
    registerStageTab,
    refreshAll,
    onAccountChange,
    onHostStageRender,
    prepareScriptContext,
    clearStageSelection: () => rememberStage(null),
    showStage,
    toast,
    isAvailable,
    getViews: () => views.slice(),
    watchChanges,
  };

  function start() {
    window.addEventListener("workspace-module-change", (event) => {
      if (event.detail?.module === "plugins") renderManagement();
    });
    window.addEventListener("storage", onPackageRevision);
    window.addEventListener("focus", refreshOnForeground);
    document.addEventListener("visibilitychange", refreshOnForeground);
    refreshAll();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
