/* 记忆管理（settings）：直接展示记忆，账号定位由独立弹窗编辑。
   可见性由 workspace-navigation.js 管理；本文件负责数据、渲染与操作。

   约定：
   * 密钥与接口配置已随订阅积分体系移除，页面不再读写任何供应商凭据。
   * 定位草稿留在内存里；离开设置或切换账号前如有未保存修改会先询问。 */
(() => {
  const root = document.getElementById("settingsContent");
  if (!root) return;

  const dom = {
    positioningModal: document.getElementById("positioningModal"),
    openPositioning: document.getElementById("projectSettingsOpenPositioning"),
    closePositioning: document.getElementById("positioningModalClose"),
    scope: document.getElementById("positioningModalScope"),
    panelPositioning: document.getElementById("projectSettingsPanelPositioning"),
    positioningEmpty: document.getElementById("projectSettingsPositioningEmpty"),
    business: document.getElementById("projectSettingsBusinessPositioning"),
    audience: document.getElementById("projectSettingsAudience"),
    positioningMessage: document.getElementById("projectSettingsPositioningMessage"),
    savePositioning: document.getElementById("projectSettingsSavePositioning"),
    enhancePositioning: document.getElementById("projectSettingsEnhancePositioning"),
    panelMemory: document.getElementById("projectSettingsPanelMemory"),
    memoryWarnings: document.getElementById("projectSettingsMemoryWarnings"),
    memoryWorkspace: document.getElementById("projectSettingsMemoryWorkspace"),
    memoryPath: document.getElementById("projectSettingsMemoryPath"),
    memoryChoose: document.getElementById("projectSettingsMemoryChoose"),
    memoryStatus: document.getElementById("projectSettingsMemoryStatus"),
    memoryOpenFolder: document.getElementById("projectSettingsMemoryOpenFolder"),
    memorySave: document.getElementById("projectSettingsMemorySave"),
    memoryCounts: document.getElementById("projectSettingsMemoryCounts"),
    memoryFilters: document.getElementById("projectSettingsMemoryFilters"),
    memoryRefresh: document.getElementById("projectSettingsMemoryRefresh"),
    memoryEmpty: document.getElementById("projectSettingsMemoryEmpty"),
    memoryList: document.getElementById("projectSettingsMemoryList"),
    memoryPager: document.getElementById("projectSettingsMemoryPager"),
    memoryMessage: document.getElementById("projectSettingsMemoryMessage"),
    memoryModal: document.getElementById("memoryModal"),
    memoryModalTitle: document.getElementById("memoryModalTitle"),
    memoryModalNameField: document.getElementById("memoryModalNameField"),
    memoryModalName: document.getElementById("memoryModalName"),
    memoryModalSource: document.getElementById("memoryModalSource"),
    memoryModalBody: document.getElementById("memoryModalBody"),
    memoryModalEnabled: document.getElementById("memoryModalEnabled"),
    memoryModalError: document.getElementById("memoryModalError"),
    memoryModalSave: document.getElementById("memoryModalSave"),
    memoryModalCancel: document.getElementById("memoryModalCancel"),
  };

  const state = {
    positioningOpener: null,
    moduleActive: false,
    accountId: "",
    // 定位：记忆已保存的值，用来判断草稿是否有未保存修改。
    positioning: { accountId: "", loaded: false, business: "", audience: "", maxLength: 0, token: 0 },
    positioningBusy: false,
    positioningEnhancing: false,
    enhancementToken: 0,
    /* 记忆：展示和保存当前工作台的实际目录。 */
    memory: {
      loaded: false,
      directory: "",
      savedDirectory: "",
      accountDirectory: "",
      accountExists: false,
      accountError: "",
      migrationWarnings: [],
      exists: false,
      writable: false,
      isObsidian: false,
      error: "",
      items: [],
      errors: [],
      counts: { total: 0, enabled: 0 },
      filter: "all",
      page: 1,
      accountId: "",
      token: 0,
      editingId: "",
    },
    memoryBusy: false,
  };

  function responseMessage(error, fallback) {
    return error?.detail?.message || error?.message || fallback;
  }

  async function readJson(response) {
    const payload = await response.json();
    if (!response.ok) throw payload;
    return payload;
  }

  async function api(path, options = {}) {
    const request = { method: options.method || "GET" };
    if (options.body !== undefined && options.body !== null) {
      request.headers = { "Content-Type": "application/json" };
      request.body = JSON.stringify(options.body);
    }
    return readJson(await fetch(path, request));
  }

  /* tone: "success" 通过 / "warning" 连接受阻 / "error" 其他失败 / "" 中性。 */
  function setMessage(element, text, tone = "") {
    if (!element) return;
    element.textContent = text || "";
    const active = Boolean(text) ? tone : "";
    element.classList.toggle("is-success", active === "success");
    element.classList.toggle("is-warning", active === "warning");
    element.classList.toggle("is-error", active === "error");
    element.hidden = !text;
  }

  function currentAccount() {
    /* activeAccountId / accounts 由 app.js 维护；设置页只读它们来显示账号名。 */
    try {
      const id = activeAccountId;
      return accounts.find((item) => item.id === id) || null;
    } catch (_error) {
      return null;
    }
  }

  function accountId() {
    try {
      return String(activeAccountId || "");
    } catch (_error) {
      return "";
    }
  }

  function resizePositioning() {
    if (!dom.positioningModal?.open) return;
    for (const field of [dom.business, dom.audience]) {
      if (!field) continue;
      field.style.height = "0px";
      field.style.height = Math.max(76, field.scrollHeight || 76) + "px";
    }
  }

  function openPositioning() {
    if (dom.positioningModal.open) return;
    state.positioningOpener = document.activeElement;
    // Every opening reads the latest saved profile (including onboarding edits).
    resetPositioning();
    dom.positioningModal.showModal();
    resizePositioning();
    loadPositioning();
  }

  function closePositioning(force = false) {
    if (!dom.positioningModal.open) return true;
    if (!force && (positioningDirty() || state.positioningEnhancing || state.positioningBusy) &&
        !confirmDiscard("账号定位还有未保存的修改或正在处理的请求，关闭后将丢失未保存内容。是否继续？")) return false;
    invalidateEnhancement();
    state.positioning.token += 1;
    state.positioningBusy = false;
    discardPositioningDraft();
    dom.positioningModal.close();
    state.positioningOpener?.focus();
    return true;
  }

  // ------------------------------------------------------------------ 账号定位

  function positioningDirty() {
    const saved = state.positioning;
    if (!saved.loaded) return false;
    return (dom.business?.value || "") !== saved.business || (dom.audience?.value || "") !== saved.audience;
  }

  function renderPositioning() {
    const saved = state.positioning;
    const id = accountId();
    const hasAccount = Boolean(id);
    if (dom.positioningEmpty) dom.positioningEmpty.hidden = hasAccount;
    for (const field of [dom.business, dom.audience]) {
      if (!field) continue;
      field.disabled = !hasAccount || !saved.loaded || state.positioningBusy || state.positioningEnhancing;
      if (saved.maxLength > 0) field.maxLength = saved.maxLength;
    }
    if (dom.savePositioning) dom.savePositioning.disabled = !hasAccount || !saved.loaded || state.positioningBusy || state.positioningEnhancing;
    if (dom.enhancePositioning) {
      dom.enhancePositioning.disabled = !hasAccount || !saved.loaded || saved.accountId !== id || state.positioningBusy || state.positioningEnhancing;
      dom.enhancePositioning.textContent = state.positioningEnhancing ? "完善中…" : "Agent完善";
    }
    if (dom.scope) {
      const account = currentAccount();
      dom.scope.textContent = account ? `当前账号：${account.name}` : "当前账号：未选择";
    }
    resizePositioning();
  }

  function applyPositioningView(payload, requestedAccountId) {
    if (!payload) return;
    const saved = state.positioning;
    saved.accountId = requestedAccountId;
    saved.loaded = true;
    /* 占位文案（历史「待完善」）按未填写展示，避免把占位当成真实定位。 */
    saved.business = payload.hasPositioning ? String(payload.profile?.businessPositioning || "") : "";
    saved.audience = payload.hasAudience ? String(payload.profile?.targetAudience || "") : "";
    saved.maxLength = Number(payload.maxLength) > 0 ? Number(payload.maxLength) : 0;
    if (dom.business) dom.business.value = saved.business;
    if (dom.audience) dom.audience.value = saved.audience;
    renderPositioning();
  }

  function resetPositioning() {
    state.positioning = { accountId: "", loaded: false, business: "", audience: "", maxLength: 0, token: state.positioning.token + 1 };
    if (dom.business) dom.business.value = "";
    if (dom.audience) dom.audience.value = "";
    setMessage(dom.positioningMessage, "");
    renderPositioning();
  }

  async function loadPositioning() {
    const id = accountId();
    if (!id) {
      resetPositioning();
      return;
    }
    if (state.positioning.loaded && state.positioning.accountId === id) return;
    const token = state.positioning.token + 1;
    state.positioning.token = token;
    try {
      const payload = await api(`/api/accounts/${encodeURIComponent(id)}/positioning`);
      /* 迟到的响应不能写进另一个账号的页面。 */
      if (state.positioning.token !== token || accountId() !== id) return;
      applyPositioningView(payload, id);
    } catch (error) {
      if (state.positioning.token !== token || accountId() !== id) return;
      setMessage(dom.positioningMessage, responseMessage(error, "定位读取失败"), "error");
    }
  }

  async function savePositioning() {
    if (state.positioningBusy || state.positioningEnhancing || !state.positioning.loaded) return;
    const id = accountId();
    if (!id) {
      setMessage(dom.positioningMessage, "请先选择一个账号。", "warning");
      return;
    }
    const token = ++state.positioning.token;
    state.positioningBusy = true;
    renderPositioning();
    setMessage(dom.positioningMessage, "");
    try {
      const payload = await api(`/api/accounts/${encodeURIComponent(id)}/positioning`, {
        method: "PUT",
        body: {
          businessPositioning: dom.business?.value || "",
          targetAudience: dom.audience?.value || "",
        },
      });
      if (accountId() !== id || state.positioning.token !== token) return;
      applyPositioningView(payload, id);
      setMessage(dom.positioningMessage, "定位已保存，后续 AI 生成会使用这次的内容。", "success");
    } catch (error) {
      if (accountId() !== id || state.positioning.token !== token) return;
      setMessage(dom.positioningMessage, responseMessage(error, "定位保存失败"), "error");
    } finally {
      if (state.positioning.token === token) {
        state.positioningBusy = false;
        renderPositioning();
      }
    }
  }

  function invalidateEnhancement() {
    state.enhancementToken += 1;
    state.positioningEnhancing = false;
    renderPositioning();
  }

  async function enhancePositioning() {
    const id = accountId();
    if (!id || !state.positioning.loaded || state.positioning.accountId !== id ||
        state.positioningBusy || state.positioningEnhancing) return;
    const body = {
      businessPositioning: dom.business?.value || "",
      targetAudience: dom.audience?.value || "",
    };
    if (!body.businessPositioning.trim() && !body.targetAudience.trim()) {
      setMessage(dom.positioningMessage, "请先填写商业定位或面向人群的简要内容。", "warning");
      return;
    }
    const token = ++state.enhancementToken;
    const isCurrent = () => token === state.enhancementToken && accountId() === id && dom.positioningModal.open;
    state.positioningEnhancing = true;
    renderPositioning();
    setMessage(dom.positioningMessage, "正在完善定位…");
    try {
      const result = await api(`/api/accounts/${encodeURIComponent(id)}/positioning/enhance`, { method: "POST", body });
      if (!isCurrent()) return;
      const limit = state.positioning.maxLength || 2000;
      if ([result?.businessPositioning, result?.targetAudience].some((value) =>
        typeof value !== "string" || !value.trim() || [...value].length > limit)) {
        throw new Error("AI 返回的定位内容无效，已保留原文。");
      }
      // 只更新输入框，保留已保存快照，使生成结果继续受未保存守卫保护。
      dom.business.value = result.businessPositioning;
      dom.audience.value = result.targetAudience;
      setMessage(dom.positioningMessage, "已完善，请检查后保存。", "success");
    } catch (error) {
      if (isCurrent()) setMessage(dom.positioningMessage, responseMessage(error, "定位完善失败，已保留原文。"), "error");
    } finally {
      if (token === state.enhancementToken) {
        state.positioningEnhancing = false;
        renderPositioning();
      }
    }
  }

  // -------------------------------------------------------------------- 记忆管理

  const MEMORY_CATEGORY_LABELS = { preference: "写作偏好", experience: "个人经历", reference_copy: "爆款文案" };
  const memoryFilterButtons = dom.memoryFilters
    ? [...dom.memoryFilters.querySelectorAll("[data-memory-filter]")]
    : [];
  function memoryDirectoryDirty() {
    /* 首次读取还没回来时，输入框里已经有内容就当作草稿，不能覆盖用户输入。 */
    if (!state.memory.loaded) return Boolean((dom.memoryPath?.value || "").trim());
    return (dom.memoryPath?.value || "").trim() !== state.memory.savedDirectory;
  }

  function renderMemoryDirectory() {
    const memory = state.memory;
    /* 用户改了路径但还没保存时不要覆盖他的输入。 */
    if (dom.memoryPath && !memoryDirectoryDirty()) dom.memoryPath.value = memory.directory;
    if (dom.memoryStatus) {
      let text = "正在读取目录…";
      let tone = "";
      if (memory.loaded) {
        if (memory.error) {
          text = memory.error;
          tone = "is-error";
        } else if (memoryDirectoryDirty()) {
          text = "目录已更改，待保存";
          tone = "is-pending";
        } else if (memory.exists && memory.writable) {
          text = "目录可用";
          tone = "is-ok";
        } else if (memory.exists) {
          text = "目录不可写，请检查系统权限。";
          tone = "is-error";
        }
      }
      if (!accountId()) text = "请先选择工作台";
      dom.memoryStatus.classList.toggle("is-pending", tone === "is-pending");
      dom.memoryStatus.textContent = text;
      dom.memoryStatus.classList.toggle("is-ok", tone === "is-ok");
      dom.memoryStatus.classList.toggle("is-error", tone === "is-error");
    }
    if (dom.memoryWorkspace) dom.memoryWorkspace.textContent = accountId()
      ? `当前工作台：${currentAccount()?.name || "未命名工作台"}` : "请先选择工作台";
    if (dom.memoryPath) {
      dom.memoryPath.disabled = state.memoryBusy || !accountId();
      dom.memoryPath.style.height = "0px";
      dom.memoryPath.style.height = Math.max(44, dom.memoryPath.scrollHeight || 44) + "px";
    }
    setMessage(dom.memoryWarnings, memory.migrationWarnings.map(item => `${item.file}: ${item.reason}`).join("；"), "warning");
    const usable = memory.loaded && memory.accountExists && !memory.error && memory.accountId === accountId();
    if (dom.memoryOpenFolder) dom.memoryOpenFolder.disabled = !usable;
    if (dom.memorySave) dom.memorySave.disabled = state.memoryBusy || !accountId() || !memory.loaded || !memoryDirectoryDirty() || !(dom.memoryPath?.value || "").trim();
    if (dom.memoryChoose) dom.memoryChoose.disabled = state.memoryBusy || !accountId();
    if (dom.memoryRefresh) dom.memoryRefresh.disabled = state.memoryBusy || !accountId();
  }

  function applyMemoryView(payload) {
    if (!payload) return;
    const memory = state.memory;
    const dirty = memoryDirectoryDirty();
    memory.loaded = true;
    memory.directory = typeof payload.accountDirectory === "string" ? payload.accountDirectory : "";
    memory.savedDirectory = memory.directory;
    memory.exists = Boolean(payload.accountExists);
    memory.writable = Boolean(payload.accountExists) && !payload.accountError;
    memory.isObsidian = Boolean(payload.isObsidian);
    memory.accountId = payload.accountId || "";
    memory.accountDirectory = payload.accountDirectory || "";
    memory.accountExists = Boolean(payload.accountExists);
    memory.accountError = payload.accountError || "";
    memory.migrationWarnings = Array.isArray(payload.migrationWarnings) ? payload.migrationWarnings : [];
    memory.error = payload.accountId ? memory.accountError : (typeof payload.error === "string" ? payload.error : "");
    if (!dirty && dom.memoryPath) dom.memoryPath.value = memory.directory;
    renderMemoryDirectory();
  }

  async function loadMemoryDirectory(id, token) {
    try {
      const payload = await api("/api/memory-settings" + (id ? "?accountId=" + encodeURIComponent(id) : ""));
      if (state.memory.token !== token || accountId() !== id) return;
      applyMemoryView(payload);
    } catch (error) {
      if (state.memory.token !== token || accountId() !== id) return;
      state.memory.loaded = true;
      state.memory.accountExists = false;
      state.memory.error = responseMessage(error, "记忆目录读取失败");
      renderMemoryDirectory();
      setMessage(dom.memoryMessage, state.memory.error, "error");
    }
  }

  async function saveMemoryDirectory() {
    if (state.memoryBusy || !accountId()) return;
    const id = accountId();
    const token = state.memory.token;
    const directory = (dom.memoryPath?.value || "").trim();
    if (!directory) {
      setMessage(dom.memoryMessage, "请先填写记忆文件夹路径。", "warning");
      return;
    }
    if (directory === state.memory.savedDirectory) {
      setMessage(dom.memoryMessage, "目录没有变化，无需保存。");
      return;
    }
    state.memoryBusy = true;
    renderMemoryDirectory();
    setMessage(dom.memoryMessage, "");
    try {
      const payload = await api("/api/memory-settings", { method: "PUT", body: { directory, accountId: id } });
      if (accountId() !== id || state.memory.token !== token) return;
      state.memory.savedDirectory = payload.accountDirectory;
      if (dom.memoryPath) dom.memoryPath.value = payload.accountDirectory;
      const migrated = Number(payload?.migrated) > 0 ? "，已复制 " + payload.migrated + " 条记忆" : "";
      setMessage(dom.memoryMessage, "目录已保存" + migrated + "，后续生成会读取这里的内容。", "success");
      await loadMemories();
    } catch (error) {
      if (accountId() === id && state.memory.token === token) setMessage(dom.memoryMessage, responseMessage(error, "目录保存失败"), "error");
    } finally {
      state.memoryBusy = false;
      renderMemoryDirectory();
    }
  }

  async function chooseMemoryDirectory() {
    if (state.memoryBusy || !accountId()) return;
    const id = accountId();
    const token = state.memory.token;
    state.memoryBusy = true;
    renderMemoryDirectory();
    setMessage(dom.memoryMessage, "");
    try {
      const payload = await api("/api/memory-settings/choose", { method: "POST", body: {} });
      if (accountId() !== id || state.memory.token !== token) return;
      const directory = typeof payload?.directory === "string" ? payload.directory : "";
      if (directory && dom.memoryPath) dom.memoryPath.value = directory;
      setMessage(dom.memoryMessage, "已选择文件夹，确认后点「保存目录」。");
    } catch (error) {
      if (accountId() === id && state.memory.token === token) setMessage(dom.memoryMessage, responseMessage(error, "未选择文件夹"), "warning");
    } finally {
      state.memoryBusy = false;
      renderMemoryDirectory();
    }
  }

  async function openMemoryDirectory(target) {
    const id = accountId();
    if (!id) return;
    try {
      await api("/api/memory-settings/open", { method: "POST", body: { target, accountId: id } });
    } catch (error) {
      if (accountId() === id) setMessage(dom.memoryMessage, responseMessage(error, "打开失败"), "error");
    }
  }

  function visibleMemories() {
    const filter = state.memory.filter;
    if (filter === "all") return state.memory.items;
    return state.memory.items.filter((item) => item.category === filter);
  }

  function memoryNodeLabel(item) {
    if (item.category === "experience") return "个人经历";
    if (item.category === "reference_copy") return "爆款文案";
    return "写作偏好";
  }

  function memorySourceLabel(item) {
    if (item.source === "pending-experience") return "已采纳经验";
    if (item.source === "breakdown") return "拆解收藏";
    if (item.source === "migrated") return "历史迁移";
    return "手动创建";
  }

  function memoryRow(item) {
    const row = document.createElement("li");
    row.className = "project-settings-memory-item" + (item.enabled ? "" : " is-disabled");
    row.dataset.memoryId = item.id;

    const copy = document.createElement("div");
    copy.className = "project-settings-memory-copy";
    const title = document.createElement("p");
    title.className = "project-settings-memory-title";
    const isPreference = item.category === "preference";
    const isReference = item.category === "reference_copy";
    title.textContent = isPreference ? item.content : item.title;
    if (isReference) title.title = item.title || "";
    if (isReference) title.classList.add("is-reference-body");
    if (isPreference) title.classList.add("is-preference-body");
    const text = document.createElement("p");
    text.className = "project-settings-memory-text";
    text.textContent = item.summary || "";
    const meta = document.createElement("p");
    meta.className = "project-settings-memory-meta";
    const metaText = document.createElement("span");
    metaText.textContent = item.category !== "preference"
      ? memoryNodeLabel(item) + " · " + memorySourceLabel(item)
      : memorySourceLabel(item);
    if (isReference) {
      const body = document.createElement("p");
      body.id = "memory-copy-" + item.id;
      body.className = "project-settings-memory-reference-content";
      body.textContent = item.content || "";
      body.hidden = true;
      const expand = document.createElement("button");
      expand.type = "button";
      expand.className = "project-settings-link project-settings-memory-expand";
      expand.textContent = "展开查看全文";
      expand.setAttribute("aria-expanded", "false");
      expand.setAttribute("aria-controls", body.id);
      expand.addEventListener("click", () => {
        const expanded = expand.getAttribute("aria-expanded") !== "true";
        body.hidden = !expanded;
        expand.setAttribute("aria-expanded", String(expanded));
        expand.textContent = expanded ? "收起" : "展开查看全文";
      });
      copy.append(title, expand, body, meta);
    } else if (isPreference) copy.append(title, meta);
    else copy.append(title, text, meta);

    const category = document.createElement("span");
    category.className = "project-settings-memory-node";
    category.textContent = MEMORY_CATEGORY_LABELS[item.category] || "写作偏好";

    meta.append(category, metaText);

    const actions = document.createElement("div");
    actions.className = "project-settings-memory-actions";
    const toggleLabel = document.createElement("label");
    toggleLabel.className = "project-settings-memory-toggle";
    const toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.checked = Boolean(item.enabled);
    toggle.dataset.memoryToggle = item.id;
    toggle.setAttribute("aria-label", (item.enabled ? "暂停" : "启用") + "「" + item.title + "」");
    toggle.addEventListener("change", () => toggleMemory(item.id, toggle.checked));
    /* 用滑动开关表达启停，和原生勾选框区分开；轨道是装饰，状态由 input 承载。 */
    const toggleTrack = document.createElement("span");
    toggleTrack.className = "project-settings-memory-switch";
    toggleTrack.setAttribute("aria-hidden", "true");
    const toggleText = document.createElement("span");
    toggleText.textContent = item.enabled ? "启用" : "已暂停";
    toggleLabel.append(toggle, toggleTrack, toggleText);
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "project-settings-link project-settings-memory-edit";
    edit.textContent = "编辑";
    edit.addEventListener("click", () => openMemoryModal(item));
    actions.append(toggleLabel, edit);
    if (["preference", "reference_copy"].includes(item.category)) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "project-settings-link project-settings-memory-delete";
      remove.textContent = "删除";
      let confirming = false;
      remove.addEventListener("click", async () => {
        if (!confirming) {
          confirming = true;
          remove.textContent = "确认删除";
          remove.title = item.category === "reference_copy" ? "删除收藏，不影响原拆解记录" : "删除此条写作偏好，文件移入本地回收目录";
          return;
        }
        const owner = accountId();
        remove.disabled = true;
        try {
          await api("/api/accounts/" + encodeURIComponent(owner) + "/memories/" + encodeURIComponent(item.id), { method: "DELETE" });
          if (accountId() === owner) await loadMemories();
        } catch (error) {
          if (accountId() === owner) setMessage(dom.memoryMessage, responseMessage(error, "删除失败"), "error");
          remove.disabled = false;
        }
      });
      actions.append(remove);
    }
    row.append(copy, actions);
    return row;
  }

  const MEMORY_PAGE_SIZE = 10;

  function renderMemoryPager(total) {
    const pager = dom.memoryPager;
    if (!pager) return;
    pager.replaceChildren();
    pager.hidden = total <= MEMORY_PAGE_SIZE;
    if (pager.hidden) return;
    const pages = Math.ceil(total / MEMORY_PAGE_SIZE);
    const info = document.createElement("span");
    info.textContent = `第 ${state.memory.page} / ${pages} 页 · 共 ${total} 条`;
    info.setAttribute("role", "status");
    const makeButton = (label, delta, disabled) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "am-secondary-action";
      button.textContent = label;
      button.disabled = disabled;
      button.addEventListener("click", () => {
        state.memory.page += delta;
        renderMemories();
        dom.memoryList?.scrollIntoView?.({ block: "start", behavior: "auto" });
        // Restore keyboard focus after rebuilding the pagination controls.
        const buttons = [...pager.querySelectorAll("button")];
        (buttons[delta < 0 ? 0 : 1]?.disabled
          ? buttons.find(item => !item.disabled) : buttons[delta < 0 ? 0 : 1])?.focus();
      });
      return button;
    };
    pager.append(makeButton("上一页", -1, state.memory.page === 1), info,
      makeButton("下一页", 1, state.memory.page === pages));
  }

  function renderMemories() {
    const memory = state.memory;
    const hasAccount = Boolean(accountId());
    if (dom.memoryCounts) {
      dom.memoryCounts.textContent = hasAccount
        ? "共 " + memory.counts.total + " 条 · 已启用 " + memory.counts.enabled + " 条 · 当前账号"
        : "请先在左侧选择一个账号，再管理它的记忆。";
    }
    for (const button of memoryFilterButtons) {
      const active = button.dataset.memoryFilter === memory.filter;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    }
    const rows = hasAccount ? visibleMemories() : [];
    memory.page = Math.min(Math.max(1, memory.page), Math.max(1, Math.ceil(rows.length / MEMORY_PAGE_SIZE)));
    renderMemoryPager(rows.length);
    if (dom.memoryEmpty) {
      dom.memoryEmpty.hidden = !hasAccount || rows.length > 0;
      dom.memoryEmpty.textContent = memory.items.length > 0
        ? "这个分类下还没有记忆。"
        : "当前账号还没有记忆。采纳 Agent 回传的待确认经验后，会自动出现在这里。";
    }
    const list = dom.memoryList;
    if (!list) return;
    list.replaceChildren(...(hasAccount ? rows.slice((memory.page - 1) * MEMORY_PAGE_SIZE, memory.page * MEMORY_PAGE_SIZE).map(memoryRow) : []));
    /* 文件问题只来自当前工作台；根目录迁移警告在存储区单独展示。 */
    const directoryProblems = memory.errors.map((item) => item.file ? `${item.file}: ${item.reason}` : item.reason);
    if (directoryProblems.length) setMessage(dom.memoryMessage, directoryProblems.join("；"), "error");
  }

  async function loadMemories() {
    const id = accountId();
    const token = ++state.memory.token;
    await loadMemoryDirectory(id, token);
    if (state.memory.token !== token || accountId() !== id) return;
    if (!id) {
      state.memory.items = [];
      state.memory.errors = [];
      state.memory.counts = { total: 0, enabled: 0 };
      state.memory.accountId = "";
      renderMemories();
      return;
    }
    try {
      const payload = await api("/api/accounts/" + encodeURIComponent(id) + "/memories");
      /* 迟到的列表响应不能写进另一个账号的页面。 */
      if (state.memory.token !== token || accountId() !== id) return;
      state.memory.accountId = id;
      state.memory.items = Array.isArray(payload?.items) ? payload.items : [];
      state.memory.errors = Array.isArray(payload?.errors) ? payload.errors : [];
      state.memory.counts = {
        total: Number(payload?.counts?.total) || 0,
        enabled: Number(payload?.counts?.enabled) || 0,
      };
      setMessage(dom.memoryMessage, "");
      renderMemories();
    } catch (error) {
      if (state.memory.token !== token || accountId() !== id) return;
      setMessage(dom.memoryMessage, responseMessage(error, "记忆读取失败"), "error");
    }
  }

  async function toggleMemory(memoryId, enabled) {
    const id = accountId();
    if (!id || !memoryId) return;
    setMessage(dom.memoryMessage, "");
    try {
      await api("/api/accounts/" + encodeURIComponent(id) + "/memories/" + encodeURIComponent(memoryId), {
        method: "PATCH",
        body: { enabled },
      });
      if (accountId() !== id) return;
      setMessage(dom.memoryMessage, enabled ? "已启用这条记忆。" : "已暂停这条记忆。", "success");
    } catch (error) {
      if (accountId() !== id) return;
      setMessage(dom.memoryMessage, responseMessage(error, "记忆状态更新失败"), "error");
    }
    await loadMemories();
  }

  function openMemoryModal(item) {
    /* 记忆来自采纳待确认经验，页面只提供编辑已有条目。 */
    if (!accountId()) {
      setMessage(dom.memoryMessage, "请先选择一个账号。", "warning");
      return;
    }
    if (!item?.id) return;
    clearTimeout(memoryBodyScrollbarHideTimer);
    dom.memoryModalBody?.classList.remove("is-scrolling");
    state.memory.editingId = item.id;
    state.memory.editingCategory = item.category;
    if (dom.memoryModalNameField) dom.memoryModalNameField.hidden = item.category === "preference";
    if (dom.memoryModalTitle) dom.memoryModalTitle.textContent = "编辑记忆";
    if (dom.memoryModalName) dom.memoryModalName.value = item?.title || "";
    if (dom.memoryModalSource) {
      dom.memoryModalSource.hidden = item.category !== "reference_copy";
      dom.memoryModalSource.textContent = "来源：" + (item.sourceUrl || item.evidence || "本地视频拆解") + " · 收藏副本，可独立编辑";
    }
    if (dom.memoryModalBody) dom.memoryModalBody.value = item?.content || "";
    if (dom.memoryModalEnabled) dom.memoryModalEnabled.checked = item ? item.enabled !== false : true;
    setMessage(dom.memoryModalError, "");
    if (dom.memoryModal) dom.memoryModal.hidden = false;
    if (item.category !== "experience") dom.memoryModalBody?.focus();
    else dom.memoryModalName?.focus();
  }

  function closeMemoryModal() {
    clearTimeout(memoryBodyScrollbarHideTimer);
    dom.memoryModalBody?.classList.remove("is-scrolling");
    state.memory.editingId = "";
    if (dom.memoryModal) dom.memoryModal.hidden = true;
    setMessage(dom.memoryModalError, "");
  }

  async function saveMemory() {
    const id = accountId();
    const editingId = state.memory.editingId;
    if (!id || !editingId || state.memoryBusy) return;
    const body = {
      ...(state.memory.editingCategory === "preference" ? {} : { title: (dom.memoryModalName?.value || "").trim() }),
      content: (dom.memoryModalBody?.value || "").trim(),
      enabled: dom.memoryModalEnabled ? Boolean(dom.memoryModalEnabled.checked) : true,
    };
    if (Array.from(body.content).length > 4000) {
      setMessage(dom.memoryModalError, "记忆内容最多 4000 个字，内容未截断，请精简后保存。", "error");
      return;
    }
    if (!body.content || (state.memory.editingCategory !== "preference" && !body.title)) {
      setMessage(dom.memoryModalError, state.memory.editingCategory === "preference" ? "请填写记忆内容。" : "请填写标题和记忆内容。", "error");
      return;
    }
    state.memoryBusy = true;
    if (dom.memoryModalSave) dom.memoryModalSave.disabled = true;
    setMessage(dom.memoryModalError, "");
    try {
      await api("/api/accounts/" + encodeURIComponent(id) + "/memories/" + encodeURIComponent(editingId), {
        method: "PUT",
        body,
      });
      if (accountId() !== id) return;
      closeMemoryModal();
      setMessage(dom.memoryMessage, "记忆已更新。", "success");
    } catch (error) {
      if (accountId() !== id) return;
      setMessage(dom.memoryModalError, responseMessage(error, "记忆保存失败"), "error");
      return;
    } finally {
      state.memoryBusy = false;
      if (dom.memoryModalSave) dom.memoryModalSave.disabled = false;
    }
    await loadMemories();
  }

  // ------------------------------------------------------------ 未保存修改的处理

  function discardPositioningDraft() {
    if (dom.business) dom.business.value = state.positioning.loaded ? state.positioning.business : "";
    if (dom.audience) dom.audience.value = state.positioning.loaded ? state.positioning.audience : "";
  }

  function confirmDiscard(message) {
    return window.confirm(message);
  }

  function guardAccountChange() {
    /* app.js 在切换前调用；返回 false 表示用户选择继续编辑，切换取消。 */
    if (memoryDirectoryDirty()) {
      if (!confirmDiscard("记忆文件夹路径还有未保存的修改，切换账号后将丢失。是否继续？")) {
        window.selectWorkspaceModule?.("settings");
        dom.memoryPath?.focus();
        return false;
      }
      dom.memoryPath.value = state.memory.savedDirectory;
    }
    if (!positioningDirty() && !state.positioningEnhancing && !state.positioningBusy) return true;
    if (confirmDiscard("账号定位还有未保存的修改，切换账号后将丢失。是否继续？")) return true;
    dom.business?.focus();
    return false;
  }

  function onAccountChange(nextAccountId) {
    const id = String(nextAccountId || "");
    invalidateEnhancement();
    state.positioning.token += 1;
    setMessage(dom.positioningMessage, "");
    state.positioningBusy = false;
    resetPositioning();
    state.memory.token += 1;
    state.memory.loaded = false;
    state.memory.directory = "";
    state.memory.savedDirectory = "";
    if (dom.memoryPath) dom.memoryPath.value = "";
    state.memory.accountDirectory = "";
    state.memory.accountExists = false;
    state.memory.accountError = "";
    state.memory.migrationWarnings = [];
    closeMemoryModal();
    setMessage(dom.memoryMessage, "");
    renderMemoryDirectory();
    /* 上一个账号的记忆先清空，避免新账号页面短暂显示别人的记忆。 */
    state.memory.accountId = "";
    state.memory.items = [];
    state.memory.page = 1;
    state.memory.errors = [];
    state.memory.counts = { total: 0, enabled: 0 };
    renderPositioning();
    if (dom.positioningModal.open && id) loadPositioning();
    else renderPositioning();
    renderMemories();
    if (state.moduleActive) loadMemories();
  }

  function onModuleChange(module) {
    state.moduleActive = module === "settings";
    if (!state.moduleActive) {
      if ((positioningDirty() || state.positioningEnhancing || state.positioningBusy) && !confirmDiscard("账号定位还有未保存的修改，离开后将丢失。是否继续？")) {
        window.selectWorkspaceModule?.("settings");
        return;
      }
      if (memoryDirectoryDirty() && !confirmDiscard("记忆文件夹路径还有未保存的修改，离开后将丢失。是否继续？")) {
        window.selectWorkspaceModule?.("settings");
        return;
      }
      closePositioning(true);
      invalidateEnhancement();
      discardPositioningDraft();
      if (dom.memoryPath && state.memory.loaded) dom.memoryPath.value = state.memory.savedDirectory;
      closeMemoryModal();
      setMessage(dom.positioningMessage, "");
      setMessage(dom.memoryMessage, "");
      return;
    }
    loadMemories();
  }

  // -------------------------------------------------------------------- 绑定

  dom.openPositioning?.addEventListener("click", openPositioning);
  dom.closePositioning?.addEventListener("click", () => closePositioning());
  dom.positioningModal?.addEventListener("cancel", event => { event.preventDefault(); closePositioning(); });
  for (const field of [dom.business, dom.audience]) field?.addEventListener("input", resizePositioning);
  window.addEventListener("resize", resizePositioning);
  if (typeof ResizeObserver !== "undefined" && dom.positioningModal) {
    let width = -1;
    new ResizeObserver(entries => {
      const next = entries[0].contentRect.width;
      if (next !== width) { width = next; resizePositioning(); }
    }).observe(dom.positioningModal);
  }
  dom.savePositioning?.addEventListener("click", savePositioning);
  dom.enhancePositioning?.addEventListener("click", enhancePositioning);
  window.addEventListener("resize", renderMemoryDirectory);
  if (typeof ResizeObserver !== "undefined" && dom.memoryPath?.parentElement) {
    let memoryPathWidth = -1;
    const memoryPathObserver = new ResizeObserver(entries => {
      const width = entries[0].contentRect.width;
      if (width !== memoryPathWidth) {
        memoryPathWidth = width;
        renderMemoryDirectory();
      }
    });
    memoryPathObserver.observe(dom.memoryPath.parentElement);
  }
  dom.memoryChoose?.addEventListener("click", chooseMemoryDirectory);
  dom.memorySave?.addEventListener("click", saveMemoryDirectory);
  dom.memoryOpenFolder?.addEventListener("click", () => openMemoryDirectory("folder"));
  dom.memoryRefresh?.addEventListener("click", () => loadMemories());
  let memoryBodyScrollbarHideTimer;
  dom.memoryModalBody?.addEventListener("scroll", () => {
    dom.memoryModalBody.classList.add("is-scrolling");
    clearTimeout(memoryBodyScrollbarHideTimer);
    memoryBodyScrollbarHideTimer = setTimeout(() => {
      dom.memoryModalBody.classList.remove("is-scrolling");
    }, 500);
  }, { passive: true });
  dom.memoryModalCancel?.addEventListener("click", closeMemoryModal);
  dom.memoryModalSave?.addEventListener("click", saveMemory);
  /* 改动路径即视为新的候选值：清掉上一次的提示，让用户知道还没保存。 */
  dom.memoryPath?.addEventListener("input", () => {
    setMessage(dom.memoryMessage, "");
    renderMemoryDirectory();
  });
  for (const button of memoryFilterButtons) {
    button.addEventListener("click", () => {
      state.memory.filter = button.dataset.memoryFilter;
      state.memory.page = 1;
      renderMemories();
    });
  }

  window.addEventListener("workspace-module-change", (event) => onModuleChange(event?.detail?.module));

  /* app.js 依赖这组钩子：可取消的账号切换 + 切换后的跟随。 */
  window.settingsModule = {
    openPositioning,
    confirmAccountChange: guardAccountChange,
    hasUnsavedChanges: () => positioningDirty() || memoryDirectoryDirty() || state.positioningBusy || state.positioningEnhancing || state.memoryBusy,
    onAccountChange,
    openReferenceCopies() {
      window.selectWorkspaceModule?.("settings");
      state.memory.filter = "reference_copy";
      state.memory.page = 1;
      loadMemories();
    },
    openWritingPreferences() {
      window.selectWorkspaceModule?.("settings");
      state.memory.filter = "preference";
      state.memory.page = 1;
      loadMemories();
    },
  };

  renderPositioning();
})();
