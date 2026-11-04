/* Weekly topic planning（选题）：plan one week of topics and hand them to the script page.
   Visibility is owned by workspace-navigation.js; this file owns data, rendering, and edits.
   Other pages (首页灵感、拆解视频、监控) can write a topic too: they call invalidate() so the
   loaded week is reloaded on the next visit instead of on every module switch. */
(() => {
  const root = document.getElementById("topicsContent");
  if (!root) return;

  const CATEGORY_ORDER = ["highlight", "daily", "series", "test"];
  const CATEGORY_LABELS = { highlight: "重点", daily: "日常", series: "系列", test: "测试" };
  const FORMAT_LABELS = { video: "视频", article: "图文" };
  /* 待创作 is topic-only: it marks a topic that has not produced a script yet, so it
     never collides with the script page's default 待处理 backlog. */
  const PENDING_CREATION = "pending_creation";
  const TOPIC_STATUS_LABELS = { [PENDING_CREATION]: "待创作" };
  const DEFAULT_TARGETS = { highlight: 2, daily: 2, series: 0, test: 1 };

  const dom = {
    previousWeek: document.getElementById("topicsPreviousWeekButton"),
    nextWeek: document.getElementById("topicsNextWeekButton"),
    currentWeek: document.getElementById("topicsCurrentWeekButton"),
    weekRange: document.getElementById("topicsWeekRange"),
    form: document.getElementById("topicForm"),
    title: document.getElementById("topicTitleInput"),
    outline: document.getElementById("topicOutlineInput"),
    category: document.getElementById("topicCategorySelect"),
    format: document.getElementById("topicFormatSelect"),
    publishDate: document.getElementById("topicPublishDateInput"),
    materials: document.getElementById("topicMaterialsInput"),
    submit: document.getElementById("topicSubmitButton"),
    reset: document.getElementById("topicResetButton"),
    summaryCount: document.getElementById("topicsSummaryCount"),
    summaryHint: document.getElementById("topicsSummaryHint"),
    progressList: document.getElementById("topicProgressList"),
    targetsButton: document.getElementById("topicTargetsButton"),
    confirmButton: document.getElementById("topicConfirmButton"),
    confirmState: document.getElementById("topicConfirmState"),
    listCount: document.getElementById("topicsListCount"),
    tabs: document.getElementById("topicCategoryTabs"),
    tableWrap: document.getElementById("topicsTableWrap"),
    tableBody: document.getElementById("topicsTableBody"),
    emptyState: document.getElementById("topicsEmptyState"),
    rowMenu: document.getElementById("topicRowMenu"),
    editModal: document.getElementById("topicEditModal"),
    editTitle: document.getElementById("topicEditTitleInput"),
    editOutline: document.getElementById("topicEditOutlineInput"),
    editCategory: document.getElementById("topicEditCategorySelect"),
    editFormat: document.getElementById("topicEditFormatSelect"),
    editWeek: document.getElementById("topicEditWeekInput"),
    editPublishDate: document.getElementById("topicEditPublishDateInput"),
    editMaterials: document.getElementById("topicEditMaterialsInput"),
    editWeekHint: document.getElementById("topicEditWeekHint"),
    cancelEdit: document.getElementById("cancelTopicEditButton"),
    saveEdit: document.getElementById("saveTopicEditButton"),
    targetsModal: document.getElementById("topicTargetsModal"),
    targetInputs: {
      highlight: document.getElementById("topicTargetHighlightInput"),
      daily: document.getElementById("topicTargetDailyInput"),
      series: document.getElementById("topicTargetSeriesInput"),
      test: document.getElementById("topicTargetTestInput"),
    },
    targetsTotal: document.getElementById("topicTargetsTotal"),
    cancelTargets: document.getElementById("cancelTopicTargetsButton"),
    saveTargets: document.getElementById("saveTopicTargetsButton"),
    deleteModal: document.getElementById("topicDeleteModal"),
    deleteDescription: document.getElementById("topicDeleteModalDescription"),
    cancelDelete: document.getElementById("cancelTopicDeleteButton"),
    confirmDelete: document.getElementById("confirmTopicDeleteButton"),
  };

  // ------------------------------------------------------------------
  // Picker fields（选题分类 / 内容形式）
  // ------------------------------------------------------------------
  // These used to be native <select> elements, whose popup cannot be styled.
  // Each field is now a button plus a menu that reuses the row menu's surface.
  // The hidden input keeps owning the value, so form reads and drafts are unchanged.

  const PICKER_CONFIGS = {
    category: { input: "topicCategorySelect", label: "选题分类", options: () => CATEGORY_ORDER.map((value) => [value, CATEGORY_LABELS[value]]) },
    format: { input: "topicFormatSelect", label: "内容形式", options: () => ["video", "article"].map((value) => [value, FORMAT_LABELS[value]]) },
    editCategory: { input: "topicEditCategorySelect", label: "选题分类", options: () => CATEGORY_ORDER.map((value) => [value, CATEGORY_LABELS[value]]) },
    editFormat: { input: "topicEditFormatSelect", label: "内容形式", options: () => ["video", "article"].map((value) => [value, FORMAT_LABELS[value]]) },
  };

  const pickers = {};
  const pickerKeys = Object.keys(PICKER_CONFIGS);
  let openPickerKey = "";

  /** Build one picker and return the handle its field uses to read and write it. */
  function createPicker(key) {
    const config = PICKER_CONFIGS[key];
    const input = document.getElementById(config.input);
    const host = document.querySelector('[data-topic-picker="' + key + '"] .topics-select-control');
    if (!input || !host) return null;

    const control = document.createElement("button");
    control.type = "button";
    control.className = "am-input topics-select-button";
    control.id = config.input + "Button";
    control.setAttribute("aria-haspopup", "menu");
    control.setAttribute("aria-expanded", "false");
    control.setAttribute("aria-label", config.label);

    const value = document.createElement("span");
    value.className = "topics-select-value";
    value.id = config.input + "Value";

    const chevron = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    chevron.setAttribute("class", "topics-select-chevron");
    chevron.setAttribute("width", "12");
    chevron.setAttribute("height", "12");
    chevron.setAttribute("viewBox", "0 0 12 12");
    chevron.setAttribute("fill", "none");
    chevron.setAttribute("aria-hidden", "true");
    chevron.setAttribute("focusable", "false");
    const chevronPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    chevronPath.setAttribute("d", "M3 4.5L6 7.5L9 4.5");
    chevronPath.setAttribute("stroke", "currentColor");
    chevronPath.setAttribute("stroke-width", "1.5");
    chevronPath.setAttribute("stroke-linecap", "round");
    chevronPath.setAttribute("stroke-linejoin", "round");
    chevron.append(chevronPath);

    const menu = document.createElement("div");
    menu.className = "topics-select-menu";
    menu.id = config.input + "Menu";
    menu.setAttribute("role", "menu");
    menu.setAttribute("aria-label", config.label);
    menu.hidden = true;

    control.append(value, chevron);
    host.append(control, menu);

    const picker = {
      key,
      input,
      control,
      value,
      menu,
      options: () => config.options(),
      labelFor: (option) => (config.options().find(([candidate]) => candidate === option) || [])[1] || option,
      select: (option, { silent = false } = {}) => {
        const allowed = config.options().map(([candidate]) => candidate);
        const next = allowed.includes(option) ? option : allowed[0];
        input.value = next;
        value.textContent = picker.labelFor(next);
        if (silent) return next;
        picker.close();
        return next;
      },
      render: () => {
        menu.replaceChildren(...config.options().map(([option, label]) => {
          const selected = input.value === option;
          const button = document.createElement("button");
          button.type = "button";
          button.setAttribute("role", "menuitemradio");
          button.setAttribute("aria-checked", String(selected));
          button.dataset.topicOption = option;
          button.classList.toggle("is-current", selected);
          // The leading check keeps the same read as the 制作状态 menu.
          button.textContent = (selected ? "✓ " : "") + label;
          button.addEventListener("click", () => {
            picker.select(option);
            picker.control.focus?.({ preventScroll: true });
            captureDraft();
          });
          return button;
        }));
      },
      open: () => {
        closeAllPickers(key);
        openPickerKey = key;
        picker.render();
        menu.hidden = false;
        control.setAttribute("aria-expanded", "true");
        const current = menu.querySelector('[aria-checked="true"]') || menu.querySelector("button");
        current?.focus?.({ preventScroll: true });
      },
      close: ({ restoreFocus = false } = {}) => {
        const wasOpen = !menu.hidden;
        menu.hidden = true;
        control.setAttribute("aria-expanded", "false");
        if (openPickerKey === key) openPickerKey = "";
        if (restoreFocus && wasOpen) control.focus?.({ preventScroll: true });
      },
    };

    control.addEventListener("click", () => {
      if (menu.hidden) picker.open();
      else picker.close();
    });
    control.addEventListener("keydown", (event) => {
      if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
      event.preventDefault();
      picker.open();
    });
    menu.addEventListener("keydown", (event) => {
      const buttons = [...menu.querySelectorAll("button")];
      const index = buttons.indexOf(document.activeElement);
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        picker.close({ restoreFocus: true });
        return;
      }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "Home" ? 0
        : event.key === "End" ? buttons.length - 1
        : (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next]?.focus?.({ preventScroll: true });
    });

    return picker;
  }

  function closeAllPickers(exceptKey = "", { restoreFocus = false } = {}) {
    for (const key of pickerKeys) {
      const picker = pickers[key];
      if (!picker || key === exceptKey) continue;
      picker.close({ restoreFocus });
    }
  }

  function setPickerValue(key, option) {
    return pickers[key]?.select(option, { silent: true }) || "";
  }

  const state = {
    accountId: "",
    weekStart: weekStartOf(new Date()),
    topics: [],
    plans: {},
    defaultTargets: { ...DEFAULT_TARGETS },
    category: "all",
    loaded: false,
    stale: false,
    loading: false,
    requestVersion: 0,
    listMessage: "",
    drafts: new Map(),
    adviceDraft: null,
    editingTopicId: "",
    deletingTopicId: "",
    menuTopicId: "",
  };

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function isoDate(date) {
    return (date.getFullYear()) + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate());
  }

  function parseIsoDate(text) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(text || "").trim());
    if (!match) return null;
    const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    return Number.isNaN(date.getTime()) ? null : date;
  }

  /** Week boundaries are Monday-based and computed in local time. */
  function weekStartOf(date) {
    const copy = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    copy.setDate(copy.getDate() - ((copy.getDay() + 6) % 7));
    return isoDate(copy);
  }

  function shiftWeek(weekStart, weeks) {
    const date = parseIsoDate(weekStart) || new Date();
    date.setDate(date.getDate() + weeks * 7);
    return isoDate(date);
  }

  function formatWeekRange(weekStart) {
    const start = parseIsoDate(weekStart);
    if (!start) return "";
    const end = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 6);
    return pad(start.getMonth() + 1) + "." + pad(start.getDate()) + " — " + pad(end.getMonth() + 1) + "." + pad(end.getDate());
  }

  function formatDayLabel(value) {
    const date = parseIsoDate(value);
    return date ? pad(date.getMonth() + 1) + "月" + pad(date.getDate()) + "日" : "";
  }

  function formatTimestamp(value) {
    const date = new Date(String(value || ""));
    if (Number.isNaN(date.getTime())) return "";
    return (date.getMonth() + 1) + "月" + date.getDate() + "日 " + pad(date.getHours()) + ":" + pad(date.getMinutes());
  }

  function overdueDays(topic) {
    if (!topic.publishDate || topic.status === "published") return 0;
    const publish = parseIsoDate(topic.publishDate);
    if (!publish) return 0;
    const today = new Date();
    const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    const difference = Math.round((todayStart.getTime() - publish.getTime()) / 86400000);
    return difference > 0 ? difference : 0;
  }

  function statusLabel(status) {
    return TOPIC_STATUS_LABELS[status] || workflowStatusLabel(status);
  }

  function statusClass(status) {
    return "is-" + String(status || PENDING_CREATION).replaceAll("_", "-");
  }

  function primaryActionFor(topic) {
    // 去创作 opens the 新建脚本 creation view; the script is only created once the
    // operator presses 生成 or 直接手写 there.
    if (!topic.scriptId) return { label: "去创作", kind: "create" };
    return topic.status === "pending" || topic.status === "editing"
      ? { label: "继续写", kind: "open" }
      : { label: "查看脚本", kind: "open" };
  }

  function findTopic(topicId) {
    return state.topics.find((topic) => topic.id === topicId) || null;
  }

  function weekTopics(weekStart = state.weekStart) {
    return state.topics
      .filter((topic) => topic.weekStart === weekStart)
      .sort((left, right) => String(right.createdAt || "").localeCompare(String(left.createdAt || "")));
  }

  function targetsForWeek(weekStart = state.weekStart) {
    const plan = state.plans[weekStart];
    return { ...state.defaultTargets, ...(plan && plan.targets ? plan.targets : {}) };
  }

  function markWeekStale(weekStart) {
    const plan = state.plans[weekStart];
    if (plan && plan.confirmedAt) state.plans[weekStart] = { ...plan, confirmedAt: "" };
  }

  function isSameAccount(accountId) {
    return state.accountId === accountId;
  }

  function emptyForm() {
    return { title: "", outline: "", category: "highlight", format: "video", publishDate: "", materials: "" };
  }

  function draftKey() {
    return state.accountId + "|" + state.weekStart;
  }

  function readForm() {
    return {
      title: dom.title.value,
      outline: dom.outline.value,
      category: dom.category.value,
      format: dom.format.value,
      publishDate: dom.publishDate.value,
      materials: dom.materials.value,
    };
  }

  function resizeOutline(field) {
    if (!field.clientWidth) return;
    const borderHeight = field.offsetHeight - field.clientHeight;
    field.style.height = "0px";
    field.style.height = Math.max(76, field.scrollHeight + borderHeight) + "px";
  }

  function applyForm(values) {
    const draft = { ...emptyForm(), ...(values || {}) };
    dom.title.value = draft.title;
    dom.outline.value = draft.outline;
    resizeOutline(dom.outline);
    setPickerValue("category", CATEGORY_LABELS[draft.category] ? draft.category : "highlight");
    setPickerValue("format", FORMAT_LABELS[draft.format] ? draft.format : "video");
    dom.publishDate.value = parseIsoDate(draft.publishDate) ? draft.publishDate : "";
    dom.materials.value = draft.materials;
  }

  function captureDraft() {
    state.drafts.set(draftKey(), readForm());
  }

  function restoreDraft() {
    applyForm(state.drafts.get(draftKey()) || emptyForm());
  }

  function setFormBusy(busy) {
    dom.submit.disabled = busy;
    dom.submit.textContent = busy ? "保存中…" : "加入本周计划";
  }

  function setTopicModalOpen(modal, open) {
    modal.hidden = !open;
    const anyOpen = [...document.querySelectorAll(".prompt-modal")].some((item) => !item.hidden);
    document.body.classList.toggle("is-modal-open", anyOpen);
  }

  function closeRowMenu() {
    if (state.menuTopicId) {
      const anchor = dom.tableBody.querySelector('[data-topic-menu="' + state.menuTopicId + '"]');
      anchor?.setAttribute("aria-expanded", "false");
    }
    state.menuTopicId = "";
    dom.rowMenu.hidden = true;
    dom.rowMenu.replaceChildren();
  }

  function renderWeek() {
    dom.weekRange.textContent = formatWeekRange(state.weekStart);
    const isCurrent = state.weekStart === weekStartOf(new Date());
    dom.currentWeek.disabled = isCurrent;
    dom.currentWeek.setAttribute("aria-label", isCurrent ? "当前已是本周" : "回到本周");
  }

  function buildProgressRow(category, count, target) {
    const row = document.createElement("li");
    row.className = "topics-progress-row";
    const label = document.createElement("span");
    label.className = "topics-progress-label";
    label.textContent = CATEGORY_LABELS[category];
    const track = document.createElement("span");
    track.className = "topics-progress-track";
    const fill = document.createElement("i");
    fill.className = "topics-progress-fill";
    const value = document.createElement("span");
    value.className = "topics-progress-value";
    if (!target) {
      row.classList.add("is-untargeted");
      value.textContent = count > 0 ? count + " 条" : "未设目标";
      fill.style.width = "0%";
    } else {
      fill.style.width = Math.min(100, Math.round((count / target) * 100)) + "%";
      if (count >= target) {
        fill.classList.add("is-complete");
        value.textContent = count + " / " + target + " ✓";
      } else {
        value.textContent = count + " / " + target;
      }
    }
    track.append(fill);
    row.append(label, track, value);
    return row;
  }

  function renderSummary() {
    const topics = weekTopics();
    const targets = targetsForWeek();
    const total = CATEGORY_ORDER.reduce((sum, category) => sum + (targets[category] || 0), 0);
    dom.summaryCount.textContent = topics.length + " / " + total;
    if (!total) {
      dom.summaryHint.textContent = "还没有设置本周目标，点击「设置目标」填写计划数量。";
    } else {
      const remaining = total - topics.length;
      dom.summaryHint.textContent = remaining > 0
        ? "再补 " + remaining + " 条，完成本周选题目标。"
        : "本周已安排 " + topics.length + " 条，达到计划目标。";
    }
    dom.progressList.replaceChildren(...CATEGORY_ORDER.map((category) => buildProgressRow(
      category,
      topics.filter((topic) => topic.category === category).length,
      targets[category] || 0,
    )));

    const confirmedAt = state.plans[state.weekStart]?.confirmedAt || "";
    if (!topics.length) {
      dom.confirmState.textContent = "先添加选题，再确认本周计划。";
    } else if (confirmedAt) {
      dom.confirmState.textContent = "已于 " + formatTimestamp(confirmedAt) + " 确认，之后仍可继续修改。";
    } else {
      dom.confirmState.textContent = "本周计划有更新，确认后表示这一周的安排已经看完。";
    }
    dom.confirmState.classList.toggle("is-stale", Boolean(topics.length) && !confirmedAt);
    dom.confirmButton.disabled = !topics.length || Boolean(confirmedAt);
  }

  function renderTabs() {
    const topics = weekTopics();
    const options = [["all", "全部", topics.length]].concat(CATEGORY_ORDER.map((category) => [
      category,
      CATEGORY_LABELS[category],
      topics.filter((topic) => topic.category === category).length,
    ]));
    dom.tabs.replaceChildren(...options.map((option) => {
      const value = option[0];
      const button = document.createElement("button");
      button.type = "button";
      button.className = "topics-tab" + (state.category === value ? " is-active" : "");
      button.dataset.topicCategory = value;
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", String(state.category === value));
      button.textContent = option[1] + " " + option[2];
      button.addEventListener("click", () => selectCategory(value));
      return button;
    }));
  }

  function buildStatusCell(topic) {
    const cell = document.createElement("td");
    const wrapper = document.createElement("span");
    wrapper.className = "topics-status";
    const dot = document.createElement("i");
    dot.className = "topics-status-dot " + statusClass(topic.status);
    dot.setAttribute("aria-hidden", "true");
    const label = document.createElement("span");
    label.textContent = statusLabel(topic.status);
    wrapper.append(dot, label);
    cell.append(wrapper);
    return cell;
  }

  function buildDateCell(topic) {
    const cell = document.createElement("td");
    const wrapper = document.createElement("span");
    wrapper.className = "topics-date";
    const label = document.createElement("span");
    label.textContent = topic.publishDate ? formatDayLabel(topic.publishDate) : "未排期";
    wrapper.append(label);
    const overdue = overdueDays(topic);
    if (overdue) {
      const pill = document.createElement("span");
      pill.className = "topics-overdue";
      pill.textContent = "逾期 " + overdue + " 天";
      wrapper.append(pill);
    }
    cell.append(wrapper);
    return cell;
  }

  function buildChipCell(text) {
    const cell = document.createElement("td");
    const chip = document.createElement("span");
    chip.className = "topics-chip";
    chip.textContent = text;
    cell.append(chip);
    return cell;
  }

  function buildTitleCell(topic) {
    const cell = document.createElement("td");
    const wrapper = document.createElement("div");
    wrapper.className = "topics-cell-title";
    const title = document.createElement("button");
    title.type = "button";
    title.className = "topics-title-button";
    title.dataset.topicEdit = topic.id;
    title.textContent = topic.title || "未命名选题";
    title.addEventListener("click", () => openTopicEditor(topic.id));
    wrapper.append(title);
    if (topic.outline) {
      const outline = document.createElement("span");
      outline.className = "topics-row-note";
      outline.textContent = "大纲：" + topic.outline;
      wrapper.append(outline);
    }
    if (topic.materials) {
      const materials = document.createElement("span");
      materials.className = "topics-row-note";
      materials.textContent = "素材：" + topic.materials;
      wrapper.append(materials);
    }
    cell.append(wrapper);
    return cell;
  }

  function buildActionCell(topic) {
    const cell = document.createElement("td");
    const actions = document.createElement("div");
    actions.className = "topics-row-actions";

    const primary = document.createElement("button");
    primary.type = "button";
    const action = primaryActionFor(topic);
    primary.className = action.kind === "open"
      ? "am-secondary-action topics-row-button"
      : "am-primary-action topics-row-button";
    if (action.kind === "create") {
      primary.dataset.topicCreate = topic.id;
      primary.addEventListener("click", () => openTopicCreation(topic.id));
    } else {
      primary.dataset.topicScript = topic.id;
      primary.addEventListener("click", () => openTopicScript(topic.id));
    }
    primary.textContent = action.label;
    actions.append(primary);

    if (topic.status === "ready_to_publish") {
      const publish = document.createElement("button");
      publish.type = "button";
      publish.className = "am-secondary-action topics-row-button";
      publish.dataset.topicPublish = topic.id;
      publish.textContent = "标记已发布";
      publish.addEventListener("click", () => updateTopicStatus(topic.id, "published"));
      actions.append(publish);
    }

    const more = document.createElement("button");
    more.type = "button";
    more.className = "topics-row-more";
    more.dataset.topicMenu = topic.id;
    more.setAttribute("aria-haspopup", "menu");
    more.setAttribute("aria-expanded", "false");
    more.setAttribute("aria-label", "更多操作：" + (topic.title || "未命名选题"));
    more.textContent = "⋯";
    more.addEventListener("click", (event) => {
      event.stopPropagation();
      if (state.menuTopicId === topic.id) closeRowMenu();
      else openRowMenu(topic.id, more);
    });
    actions.append(more);

    cell.append(actions);
    return cell;
  }

  function renderList() {
    let topics = weekTopics();
    if (state.category !== "all") topics = topics.filter((topic) => topic.category === state.category);

    dom.listCount.textContent = topics.length + " 条";
    if (!topics.length) {
      dom.tableBody.replaceChildren();
      dom.tableWrap.hidden = true;
      dom.emptyState.hidden = false;
      const hasAny = weekTopics().length > 0;
      dom.emptyState.textContent = state.listMessage
        || (hasAny ? "这个分类下本周还没有选题。" : "本周还没有选题，先在上方添加第一条选题。");
      return;
    }
    dom.tableWrap.hidden = false;
    dom.emptyState.hidden = true;
    dom.tableBody.replaceChildren(...topics.map((topic) => {
      const row = document.createElement("tr");
      row.dataset.topicRow = topic.id;
      row.append(
        buildTitleCell(topic),
        buildChipCell(CATEGORY_LABELS[topic.category] || CATEGORY_LABELS.highlight),
        buildChipCell(FORMAT_LABELS[topic.format] || FORMAT_LABELS.video),
        buildDateCell(topic),
        buildStatusCell(topic),
        buildActionCell(topic),
      );
      return row;
    }));
  }

  function render() {
    renderWeek();
    renderSummary();
    renderTabs();
    renderList();
  }

  async function loadTopics() {
    const accountId = state.accountId;
    const version = ++state.requestVersion;
    if (!accountId) {
      state.topics = [];
      state.plans = {};
      render();
      return;
    }
    state.loading = true;
    state.listMessage = "正在读取选题…";
    try {
      const response = await fetch("/api/accounts/" + encodeURIComponent(accountId) + "/topics");
      const payload = await readJson(response);
      if (version !== state.requestVersion || !isSameAccount(accountId)) return;
      state.topics = Array.isArray(payload.items) ? payload.items : [];
      state.plans = payload.plans && typeof payload.plans === "object" ? payload.plans : {};
      if (payload.defaultTargets) state.defaultTargets = { ...state.defaultTargets, ...payload.defaultTargets };
      state.loaded = true;
      state.stale = false;
      state.listMessage = "";
    } catch (error) {
      if (version !== state.requestVersion || !isSameAccount(accountId)) return;
      state.topics = [];
      state.plans = {};
      state.listMessage = "选题读取失败，可稍后重试。";
      showToast(responseMessage(error, "选题读取失败"), "error");
    } finally {
      if (version === state.requestVersion) state.loading = false;
      if (isSameAccount(accountId)) render();
    }
  }

  function onAccountChange(accountId) {
    const next = String(accountId || "");
    if (next === state.accountId) return;
    cancelAdviceDraft();
    captureDraft();
    state.accountId = next;
    state.topics = [];
    state.plans = {};
    state.loaded = false;
    state.stale = false;
    state.listMessage = "";
    state.requestVersion += 1;
    state.category = "all";
    closeRowMenu();
    restoreDraft();
    if (next) loadTopics();
    else render();
  }

  /* 首页灵感、拆解视频和监控都能直接写入选题库，但都不在本模块里。它们只登记「过期」，
     由下一次进入选题时补一次读取，切页本身不多花一次请求；如果选题页此时正开着，
     才立即刷新，让用户当场看到新选题。 */
  function invalidate() {
    state.stale = true;
    if (state.accountId && !root.hidden) loadTopics();
  }

  function selectWeek(weekStart) {
    if (!weekStart || weekStart === state.weekStart) return;
    cancelAdviceDraft();
    captureDraft();
    state.weekStart = weekStart;
    state.category = "all";
    closeRowMenu();
    restoreDraft();
    render();
  }

  function selectCategory(category) {
    state.category = category;
    renderTabs();
    renderList();
  }

  function cancelAdviceDraft() {
    if (!state.adviceDraft) return;
    applyForm(state.adviceDraft.previous);
    state.adviceDraft = null;
    const notice = document.getElementById("topicAdviceDraftNotice");
    if (notice) notice.hidden = true;
  }

  function beginAdviceDraft(advice, accountId) {
    if (state.accountId !== accountId) return;
    cancelAdviceDraft();
    selectWeek(weekStartOf(new Date()));
    state.adviceDraft = { id: advice.id, accountId, previous: readForm() };
    applyForm({title: advice.topicTitle, outline: advice.angle, category: "test", format: "video", publishDate: "",
      materials: "来源：账号下一步建议 / " + advice.title + "\n参考作品：" + (advice.references || []).map(r => r.title).join("、")});
    const notice = document.getElementById("topicAdviceDraftNotice");
    if (notice) notice.hidden = false;
  }
  document.getElementById("topicAdviceDraftCancel")?.addEventListener("click", cancelAdviceDraft);

  async function submitTopic(event) {
    if (window.WorkbenchDateTimePicker?.validateInputs(dom.publishDate) === false) { event?.preventDefault?.(); return; }
    event?.preventDefault?.();
    if (!state.accountId) {
      showToast("请先选择账号", "error");
      return;
    }
    const form = readForm();
    const title = form.title.trim();
    if (!title) {
      showToast("请填写选题标题", "error");
      dom.title.focus?.();
      return;
    }
    const accountId = state.accountId;
    if (dom.submit.disabled) return;
    const adviceDraft = state.adviceDraft;
    setFormBusy(true);
    try {
      const endpoint = adviceDraft ? "/home/advice/" + encodeURIComponent(adviceDraft.id) + "/topic" : "/topics";
      const response = await fetch("/api/accounts/" + encodeURIComponent(accountId) + endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          outline: form.outline,
          category: form.category,
          format: form.format,
          publishDate: form.publishDate,
          materials: form.materials,
          weekStart: state.weekStart,
        }),
      });
      const topic = await readJson(response);
      if (!isSameAccount(accountId)) return;
      if (!state.topics.some(item => item.id === topic.id)) state.topics.push(topic);
      if (adviceDraft && state.adviceDraft === adviceDraft) {
        cancelAdviceDraft();
        window.homeAdviceModule?.refresh?.();
      }
      if (!adviceDraft) state.drafts.delete(draftKey());
      markWeekStale(topic.weekStart);
      render();
      if (!adviceDraft) applyForm({ ...emptyForm(), category: form.category, format: form.format });
      showToast("已加入本周计划", "success");
    } catch (error) {
      showToast(responseMessage(error, "选题保存失败"), "error");
    } finally {
      setFormBusy(false);
    }
  }

  async function patchTopic(topicId, fields, fallbackMessage) {
    const accountId = state.accountId;
    try {
      const response = await fetch("/api/topics/" + encodeURIComponent(topicId), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      });
      const updated = await readJson(response);
      if (!isSameAccount(accountId)) return null;
      const topic = findTopic(topicId);
      if (topic) {
        const previousWeek = topic.weekStart;
        Object.assign(topic, updated);
        if (Object.hasOwn(fields, "weekStart") && fields.weekStart !== previousWeek) state.category = "all";
        if (Object.keys(fields).some((key) => key !== "status")) {
          markWeekStale(previousWeek);
          markWeekStale(topic.weekStart);
        }
      }
      render();
      return updated;
    } catch (error) {
      showToast(responseMessage(error, fallbackMessage), "error");
      return null;
    }
  }

  async function updateTopicStatus(topicId, status) {
    const updated = await patchTopic(topicId, { status }, "选题状态更新失败");
    if (updated) showToast("已改为" + statusLabel(status), "success");
  }

  function openTopicEditor(topicId) {
    const topic = findTopic(topicId);
    if (!topic) return;
    state.editingTopicId = topicId;
    dom.editTitle.value = topic.title;
    dom.editOutline.value = topic.outline;
    setPickerValue("editCategory", topic.category);
    setPickerValue("editFormat", topic.format);
    dom.editWeek.value = topic.weekStart;
    dom.editPublishDate.value = topic.publishDate;
    dom.editMaterials.value = topic.materials;
    renderEditWeekHint();
    setTopicModalOpen(dom.editModal, true);
    resizeOutline(dom.editOutline);
    dom.editTitle.focus?.();
  }

  function renderEditWeekHint() {
    const week = weekStartOf(parseIsoDate(dom.editWeek.value) || new Date());
    dom.editWeekHint.textContent = "所属周按所选日期所在周一计算：" + formatWeekRange(week) + "。";
  }

  function closeTopicEditor() {
    state.editingTopicId = "";
    setTopicModalOpen(dom.editModal, false);
  }

  async function saveTopicEditor() {
    if (window.WorkbenchDateTimePicker?.validateInputs(dom.editWeek, dom.editPublishDate) === false) return;
    const topic = findTopic(state.editingTopicId);
    if (!topic) {
      closeTopicEditor();
      return;
    }
    const title = dom.editTitle.value.trim();
    if (!title) {
      showToast("请填写选题标题", "error");
      dom.editTitle.focus?.();
      return;
    }
    const updated = await patchTopic(topic.id, {
      title,
      outline: dom.editOutline.value,
      category: dom.editCategory.value,
      format: dom.editFormat.value,
      weekStart: weekStartOf(parseIsoDate(dom.editWeek.value) || parseIsoDate(topic.weekStart) || new Date()),
      publishDate: dom.editPublishDate.value,
      materials: dom.editMaterials.value,
    }, "选题保存失败");
    if (!updated) return;
    closeTopicEditor();
    showToast(updated.weekStart === state.weekStart ? "选题已更新" : "选题已移动到其他周", "success");
  }

  function openTargetsEditor() {
    const targets = targetsForWeek();
    CATEGORY_ORDER.forEach((category) => {
      dom.targetInputs[category].value = String(targets[category] || 0);
    });
    renderTargetsTotal();
    setTopicModalOpen(dom.targetsModal, true);
    dom.targetInputs.highlight.focus?.();
  }

  function renderTargetsTotal() {
    const total = CATEGORY_ORDER.reduce((sum, category) => {
      const value = Number(dom.targetInputs[category].value);
      return sum + (Number.isFinite(value) && value > 0 ? value : 0);
    }, 0);
    dom.targetsTotal.textContent = "本周共计划 " + total + " 条选题。";
  }

  function closeTargetsEditor() {
    setTopicModalOpen(dom.targetsModal, false);
  }

  async function saveTargets() {
    const targets = {};
    for (const category of CATEGORY_ORDER) {
      const raw = String(dom.targetInputs[category].value).trim();
      const value = raw === "" ? 0 : Number(raw);
      if (!Number.isInteger(value) || value < 0 || value > 50) {
        showToast("每个分类的目标请填写 0—50 的整数", "error");
        dom.targetInputs[category].focus?.();
        return;
      }
      targets[category] = value;
    }
    const accountId = state.accountId;
    try {
      const response = await fetch(
        "/api/accounts/" + encodeURIComponent(accountId) + "/topic-plans/" + encodeURIComponent(state.weekStart),
        { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ targets }) },
      );
      const plan = await readJson(response);
      if (!isSameAccount(accountId)) return;
      state.plans[plan.weekStart] = plan;
      render();
      closeTargetsEditor();
      showToast("本周目标已保存，需要重新确认计划", "success");
    } catch (error) {
      showToast(responseMessage(error, "本周目标保存失败"), "error");
    }
  }

  async function confirmWeekPlan() {
    const accountId = state.accountId;
    try {
      const response = await fetch(
        "/api/accounts/" + encodeURIComponent(accountId) + "/topic-plans/" + encodeURIComponent(state.weekStart) + "/confirm",
        { method: "POST" },
      );
      const plan = await readJson(response);
      if (!isSameAccount(accountId)) return;
      state.plans[plan.weekStart] = plan;
      render();
      showToast("本周计划已确认", "success");
    } catch (error) {
      showToast(responseMessage(error, "本周计划确认失败"), "error");
    }
  }

  function openTopicDeleteModal(topicId) {
    const topic = findTopic(topicId);
    if (!topic) return;
    state.deletingTopicId = topicId;
    dom.deleteDescription.textContent = topic.scriptId
      ? "将删除「" + topic.title + "」这个选题，本周计划会重新变成待确认；已经创建的脚本会保留在脚本页。"
      : "将删除「" + topic.title + "」这个选题，本周计划会重新变成待确认。";
    setTopicModalOpen(dom.deleteModal, true);
    dom.cancelDelete.focus?.();
  }

  function closeTopicDeleteModal() {
    state.deletingTopicId = "";
    setTopicModalOpen(dom.deleteModal, false);
  }

  async function confirmTopicDelete() {
    const topic = findTopic(state.deletingTopicId);
    if (!topic) {
      closeTopicDeleteModal();
      return;
    }
    const accountId = state.accountId;
    try {
      const response = await fetch("/api/topics/" + encodeURIComponent(topic.id), { method: "DELETE" });
      if (!response.ok) await readJson(response);
      if (!isSameAccount(accountId)) return;
      state.topics = state.topics.filter((item) => item.id !== topic.id);
      markWeekStale(topic.weekStart);
      render();
      closeTopicDeleteModal();
      showToast("选题已删除", "success");
    } catch (error) {
      showToast(responseMessage(error, "选题删除失败"), "error");
    }
  }

  function buildRowMenu() {
    const topic = findTopic(state.menuTopicId);
    if (!topic) return;
    const nodes = [];
    const nextWeek = document.createElement("button");
    nextWeek.type = "button";
    nextWeek.setAttribute("role", "menuitem");
    nextWeek.dataset.topicMove = "next";
    nextWeek.textContent = "移到下一周";
    nextWeek.addEventListener("click", () => {
      closeRowMenu();
      patchTopic(topic.id, { weekStart: shiftWeek(topic.weekStart, 1) }, "选题移动失败")
        .then((updated) => { if (updated) showToast("已移到 " + formatWeekRange(updated.weekStart), "success"); });
    });
    nodes.push(nextWeek);

    nodes.push(document.createElement("hr"));

    const remove = document.createElement("button");
    remove.type = "button";
    remove.setAttribute("role", "menuitem");
    remove.className = "is-danger";
    remove.dataset.topicDelete = topic.id;
    remove.textContent = "删除选题";
    remove.addEventListener("click", () => {
      closeRowMenu();
      openTopicDeleteModal(topic.id);
    });
    nodes.push(remove);

    dom.rowMenu.replaceChildren(...nodes);
  }

  function placeRowMenu(anchor) {
    const bounds = anchor.getBoundingClientRect();
    const width = dom.rowMenu.offsetWidth || 190;
    const height = dom.rowMenu.offsetHeight || 240;
    const left = Math.max(8, Math.min(bounds.right - width, window.innerWidth - width - 8));
    const top = bounds.bottom + 6 + height > window.innerHeight - 8
      ? Math.max(8, bounds.top - height - 6)
      : bounds.bottom + 6;
    dom.rowMenu.style.left = left + "px";
    dom.rowMenu.style.top = top + "px";
  }

  /** Scrolling keeps the menu glued to its row instead of dismissing it. */
  function repositionRowMenu() {
    if (dom.rowMenu.hidden || !state.menuTopicId) return;
    const anchor = dom.tableBody.querySelector('[data-topic-menu="' + state.menuTopicId + '"]');
    if (!anchor) {
      closeRowMenu();
      return;
    }
    placeRowMenu(anchor);
  }

  function openRowMenu(topicId, anchor) {
    closeRowMenu();
    state.menuTopicId = topicId;
    buildRowMenu();
    dom.rowMenu.hidden = false;
    placeRowMenu(anchor);
    anchor.setAttribute("aria-expanded", "true");
    dom.rowMenu.querySelector("button")?.focus?.({ preventScroll: true });
  }

  /** The script page hides rows that do not match its filter, so clear it before opening. */
  async function showScriptForTopic(scriptId, accountId) {
    window.selectWorkspaceModule?.("scripts");
    selectScriptStatusFilter("all");
    await selectAccount(accountId, scriptId);
  }

  async function openTopicScript(topicId) {
    const topic = findTopic(topicId);
    if (!topic) return;
    const accountId = state.accountId;
    try {
      const response = await fetch("/api/topics/" + encodeURIComponent(topicId) + "/script", { method: "POST" });
      const payload = await readJson(response);
      if (!isSameAccount(accountId)) return;
      const stored = findTopic(topicId);
      if (stored) Object.assign(stored, payload.topic);
      render();
      if (payload.created) showToast("已创建关联脚本", "success");
      await showScriptForTopic(payload.script.id, payload.topic.accountId);
    } catch (error) {
      showToast(responseMessage(error, "无法打开脚本"), "error");
    }
  }

  /** 去创作: open the 新建脚本 creation view with this topic already filled in. */
  function openTopicCreation(topicId) {
    const topic = findTopic(topicId);
    if (!topic) return;
    window.selectWorkspaceModule?.("create");
    window.openNewScriptPanel?.();
    window.prefillDraftTopic?.(topicId);
  }

  dom.previousWeek.addEventListener("click", () => selectWeek(shiftWeek(state.weekStart, -1)));
  dom.nextWeek.addEventListener("click", () => selectWeek(shiftWeek(state.weekStart, 1)));
  dom.currentWeek.addEventListener("click", () => selectWeek(weekStartOf(new Date())));
  dom.form.addEventListener("submit", submitTopic);
  dom.reset.addEventListener("click", () => {
    state.drafts.delete(draftKey());
    applyForm(emptyForm());
  });
  dom.form.addEventListener("input", () => captureDraft());
  dom.targetsButton.addEventListener("click", openTargetsEditor);
  dom.confirmButton.addEventListener("click", confirmWeekPlan);
  dom.cancelEdit.addEventListener("click", closeTopicEditor);
  dom.saveEdit.addEventListener("click", saveTopicEditor);
  dom.editWeek.addEventListener("change", renderEditWeekHint);
  dom.cancelTargets.addEventListener("click", closeTargetsEditor);
  dom.saveTargets.addEventListener("click", saveTargets);
  CATEGORY_ORDER.forEach((category) => dom.targetInputs[category].addEventListener("input", renderTargetsTotal));
  dom.cancelDelete.addEventListener("click", closeTopicDeleteModal);
  dom.confirmDelete.addEventListener("click", confirmTopicDelete);

  // Build the picker controls; each one mirrors its hidden input's current value.
  for (const key of pickerKeys) {
    const picker = createPicker(key);
    if (!picker) continue;
    pickers[key] = picker;
    picker.select(picker.input.value, { silent: true });
  }

  document.addEventListener("pointerdown", (event) => {
    if (!dom.rowMenu.hidden && !dom.rowMenu.contains(event.target)) closeRowMenu();
    if (openPickerKey && !event.target.closest?.(".topics-select-control")) closeAllPickers();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (openPickerKey) {
      closeAllPickers("", { restoreFocus: true });
      return;
    }
    if (!dom.rowMenu.hidden) {
      closeRowMenu();
      return;
    }
    if (!dom.editModal.hidden) closeTopicEditor();
    else if (!dom.targetsModal.hidden) closeTargetsEditor();
    else if (!dom.deleteModal.hidden) closeTopicDeleteModal();
  });
  for (const field of [dom.outline, dom.editOutline]) {
    field.addEventListener("input", () => resizeOutline(field));
    // Width changes include revealing a hidden form and layout changes.
    if (typeof ResizeObserver !== "undefined") {
      let width = -1;
      new ResizeObserver((entries) => {
        const nextWidth = entries[0].contentRect.width;
        if (nextWidth === width) return;
        width = nextWidth;
        resizeOutline(field);
      }).observe(field);
    }
  }
  window.addEventListener("resize", () => {
    repositionRowMenu();
    resizeOutline(dom.outline);
    resizeOutline(dom.editOutline);
  });
  window.addEventListener("scroll", repositionRowMenu, true);
  window.addEventListener("workspace-module-change", (event) => {
    if (event?.detail?.module !== "topics") {
      closeRowMenu();
      closeAllPickers();
      return;
    }
    if (state.accountId && (!state.loaded || state.stale)) loadTopics();
    resizeOutline(dom.outline);
  });

  // app.js reports every account switch so the planner always follows the active account.
  window.topicsModule = {
    onAccountChange,
    refresh: loadTopics,
    invalidate,
    state,
    helpers: {
      weekStartOf,
      shiftWeek,
      formatWeekRange,
      overdueDays,
      primaryActionFor,
      statusLabel,
      targetsForWeek,
    },
    actions: {
      submitTopic,
      beginAdviceDraft,
      cancelAdviceDraft,
      selectCategory,
      selectWeek,
      openTopicScript,
      openTopicCreation,
      updateTopicStatus,
      confirmWeekPlan,
      openTopicEditor,
      saveTopicEditor,
      openTargetsEditor,
      saveTargets,
      openTopicDeleteModal,
      confirmTopicDelete,
      setPickerValue,
    },
    pickers,
    dom,
  };

  restoreDraft();
  render();
})();
