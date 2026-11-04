/* Creator home（首页）：today's actions, saved ideas, and the week at a glance.
   Visibility is owned by workspace-navigation.js; this file owns data, rendering, and edits. */
(() => {
  const root = document.getElementById("homeContent");
  if (!root) return;

  const CATEGORY_LABELS = { highlight: "重点", daily: "日常", series: "系列", test: "测试" };
  const FORMAT_LABELS = { video: "视频", article: "图文" };
  const STATUS_LABELS = { pending: "待处理", editing: "待拍摄", ready_to_publish: "待发布", published: "已发布", pending_creation: "待创作" };
  const STATUS_ORDER = ["pending", "editing", "ready_to_publish", "published"];
  const TASK_PAGE_SIZE = 6;
  const INSPIRATION_PAGE_SIZE = 5;
  const NEWLINE = String.fromCharCode(10);

  const dom = {
    taskPanel: document.getElementById("homeTaskPanel"),
    dueAll: document.getElementById("homeDueAll"),
    dueOverdue: document.getElementById("homeDueOverdue"),
    duePrev: document.getElementById("homeDuePrev"),
    dueNext: document.getElementById("homeDueNext"),
    duePage: document.getElementById("homeDuePage"),
    focusTitle: document.getElementById("homeFocusTitle"),
    focusDescription: document.getElementById("homeFocusDescription"),
    focusAction: document.getElementById("homeFocusAction"),
    focusOverdue: document.getElementById("homeFocusOverdue"),
    weekRing: document.getElementById("homeWeekRing"),
    weekHeadline: document.getElementById("homeWeekHeadline"),
    weekRange: document.getElementById("homeWeekRange"),
    weekDays: document.getElementById("homeWeekDays"),
    ideaPending: document.getElementById("homeIdeaPending"),
    inspirationRecentLabel: document.getElementById("homeInspirationRecentLabel"),
    breakdown: document.getElementById("homeBreakdownButton"),
    inspirationPanel: document.getElementById("homeInspirationPanel"),
    title: document.getElementById("homeTitle"),
    date: document.getElementById("homeDate"),
    statsList: document.getElementById("homeStatsList"),
    statsMessage: document.getElementById("homeStatsMessage"),
    newScript: document.getElementById("homeNewScriptButton"),
    taskCount: document.getElementById("homeTaskCount"),
    taskList: document.getElementById("homeTaskList"),
    taskEmpty: document.getElementById("homeTaskEmpty"),
    taskMessage: document.getElementById("homeTaskMessage"),
    addTask: document.getElementById("homeAddTaskButton"),
    taskMore: document.getElementById("homeTaskMoreButton"),
    weekPlan: document.getElementById("homeWeekPlanButton"),
    weekProgress: document.getElementById("homeWeekProgress"),
    weekPercent: document.getElementById("homeWeekPercent"),
    weekBar: document.getElementById("homeWeekBar"),
    weekMeta: document.getElementById("homeWeekMeta"),
    weekMessage: document.getElementById("homeWeekMessage"),
    inspirationInput: document.getElementById("homeInspirationInput"),
    inspirationSourceInput: document.getElementById("homeInspirationSourceInput"),
    inspirationSave: document.getElementById("homeInspirationSaveButton"),
    inspirationMessage: document.getElementById("homeInspirationMessage"),
    inspirationList: document.getElementById("homeInspirationList"),
    inspirationEmpty: document.getElementById("homeInspirationEmpty"),
    inspirationMore: document.getElementById("homeInspirationMoreButton"),
    taskModal: document.getElementById("homeTaskModal"),
    taskModalTitle: document.getElementById("homeTaskModalTitle"),
    taskTitle: document.getElementById("homeTaskTitleInput"),
    taskDate: document.getElementById("homeTaskDateInput"),
    taskLink: document.getElementById("homeTaskLinkSelect"),
    taskNote: document.getElementById("homeTaskNoteInput"),
    taskError: document.getElementById("homeTaskModalError"),
    taskSave: document.getElementById("homeTaskSaveButton"),
    taskCancel: document.getElementById("homeTaskCancelButton"),
    taskDelete: document.getElementById("homeTaskDeleteButton"),
    taskListModal: document.getElementById("homeTaskListModal"),
    taskScopeTabs: document.getElementById("homeTaskScopeTabs"),
    taskModalList: document.getElementById("homeTaskModalList"),
    taskModalEmpty: document.getElementById("homeTaskModalEmpty"),
    taskPageLabel: document.getElementById("homeTaskPageLabel"),
    taskPrev: document.getElementById("homeTaskPrevButton"),
    taskNext: document.getElementById("homeTaskNextButton"),
    taskListClose: document.getElementById("homeTaskListCloseButton"),
    inspirationModal: document.getElementById("homeInspirationModal"),
    inspirationModalList: document.getElementById("homeInspirationModalList"),
    inspirationModalEmpty: document.getElementById("homeInspirationModalEmpty"),
    inspirationPageLabel: document.getElementById("homeInspirationPageLabel"),
    inspirationPrev: document.getElementById("homeInspirationPrevButton"),
    inspirationNext: document.getElementById("homeInspirationNextButton"),
    inspirationClose: document.getElementById("homeInspirationCloseButton"),
    convertModal: document.getElementById("homeConvertModal"),
    convertHint: document.getElementById("homeConvertHint"),
    convertTitle: document.getElementById("homeConvertTitleInput"),
    convertOutline: document.getElementById("homeConvertOutlineInput"),
    convertCategory: document.getElementById("homeConvertCategorySelect"),
    convertFormat: document.getElementById("homeConvertFormatSelect"),
    convertWeek: document.getElementById("homeConvertWeekInput"),
    convertPublishDate: document.getElementById("homeConvertPublishDateInput"),
    convertError: document.getElementById("homeConvertError"),
    convertConfirm: document.getElementById("homeConvertConfirmButton"),
    convertCancel: document.getElementById("homeConvertCancelButton"),
    rescheduleModal: document.getElementById("homeRescheduleModal"),
    rescheduleHint: document.getElementById("homeRescheduleHint"),
    rescheduleDate: document.getElementById("homeRescheduleDateInput"),
    rescheduleError: document.getElementById("homeRescheduleError"),
    rescheduleSave: document.getElementById("homeRescheduleSaveButton"),
    rescheduleCancel: document.getElementById("homeRescheduleCancelButton"),
    taskRowMenu: document.getElementById("homeTaskRowMenu"),
  };

  const state = {
    accountId: "",
    loaded: false,
    loading: false,
    requestVersion: 0,
    date: todayIso(),
    weekStart: weekStartOf(new Date()),
    stats: null,
    tasks: [],
    taskCount: 0,
    dueFilter: "all",
    duePage: 1,
    inspirations: [],
    inspirationTotal: 0,
    week: null,
    linkOptions: { topics: [], scripts: [] },
    message: "",
    actionMessage: "",
    editingTaskId: "",
    taskScope: "pending",
    taskPage: 1,
    taskPageCount: 1,
    taskModalItems: [],
    taskModalMessage: "",
    inspirationPage: 1,
    editingInspirationId: "",
    convertingInspirationId: "",
    rescheduling: null,
    menuTaskKey: "",
    menuAnchor: null,
  };

  // ---------------------------------------------------------------- helpers

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function isoOf(day) {
    return [day.getFullYear(), pad(day.getMonth() + 1), pad(day.getDate())].join("-");
  }

  function todayIso() {
    return isoOf(new Date());
  }

  function parseIso(iso) {
    const parts = String(iso || "").split("-").map(Number);
    if (parts.length !== 3 || parts.some((value) => !Number.isFinite(value))) return null;
    return new Date(parts[0], parts[1] - 1, parts[2]);
  }

  function weekStartOf(day) {
    const base = new Date(day.getFullYear(), day.getMonth(), day.getDate());
    base.setDate(base.getDate() - ((base.getDay() + 6) % 7));
    return isoOf(base);
  }

  function shiftIso(iso, days) {
    const day = parseIso(iso);
    if (!day) return iso;
    day.setDate(day.getDate() + days);
    return isoOf(day);
  }

  function formatDateLine(iso) {
    const day = parseIso(iso);
    if (!day) return "";
    return (day.getMonth() + 1) + "月" + day.getDate() + "日 · 星期" + "日一二三四五六"[day.getDay()];
  }

  function relativeDayLabel(iso) {
    const today = todayIso();
    if (iso === today) return "今天";
    if (iso === shiftIso(today, -1)) return "昨天";
    if (iso === shiftIso(today, 1)) return "明天";
    const day = parseIso(iso);
    return day ? (day.getMonth() + 1) + "月" + day.getDate() + "日" : "";
  }

  function formatStamp(value) {
    const parsed = new Date(String(value || ""));
    if (Number.isNaN(parsed.getTime())) return "";
    return relativeDayLabel(isoOf(parsed)) + " " + pad(parsed.getHours()) + ":" + pad(parsed.getMinutes());
  }

  function el(tag, className = "", text = "") {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function isSameAccount(accountId) {
    return state.accountId === accountId;
  }

  async function api(url, options) {
    const settings = options || {};
    const request = { method: settings.method || "GET" };
    if (settings.body !== undefined && settings.body !== null) {
      request.headers = { "Content-Type": "application/json" };
      request.body = JSON.stringify(settings.body);
    }
    const response = await fetch(url, request);
    if (response.status === 204) return null;
    return readJson(response);
  }

  function setModalOpen(modal, open) {
    if (!modal) return;
    modal.hidden = !open;
  }

  function setMessage(node, message) {
    if (!node) return;
    node.hidden = !message;
    node.textContent = message || "";
  }

  function paginate(items, page, size) {
    const total = items.length;
    const pageCount = Math.max(1, Math.ceil(total / size));
    const current = Math.max(1, Math.min(page, pageCount));
    const start = (current - 1) * size;
    return { items: items.slice(start, start + size), total, pageCount, page: current };
  }

  // ---------------------------------------------------------------- pickers

  const pickers = {};
  const pickerKeys = ["link", "category", "format"];
  let openPickerKey = "";

  function createPicker(key, config) {
    const input = document.getElementById(config.input);
    const host = document.querySelector("[data-home-picker=" + JSON.stringify(key) + "] .topics-select-control");
    if (!input || !host) return null;

    const control = document.createElement("button");
    control.type = "button";
    control.className = "am-input topics-select-button";
    control.id = config.input + "Button";
    control.setAttribute("aria-haspopup", "menu");
    control.setAttribute("aria-expanded", "false");
    control.setAttribute("aria-label", config.label);

    const value = el("span", "topics-select-value");
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

    const menu = el("div", "topics-select-menu");
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
      select: (option, options) => {
        const silent = Boolean(options && options.silent);
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
          button.classList.toggle("is-current", selected);
          button.textContent = (selected ? "✓ " : "") + label;
          button.addEventListener("click", () => {
            picker.select(option);
            picker.control.focus?.({ preventScroll: true });
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
        const current = menu.querySelector("[aria-checked=true]") || menu.querySelector("button");
        current?.focus?.({ preventScroll: true });
      },
      close: (options) => {
        const restoreFocus = Boolean(options && options.restoreFocus);
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
      if (["ArrowDown", "ArrowUp"].indexOf(event.key) < 0) return;
      event.preventDefault();
      picker.open();
    });
    menu.addEventListener("keydown", (event) => {
      const buttons = Array.from(menu.querySelectorAll("button"));
      const index = buttons.indexOf(document.activeElement);
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        picker.close({ restoreFocus: true });
        return;
      }
      if (["ArrowDown", "ArrowUp", "Home", "End"].indexOf(event.key) < 0) return;
      event.preventDefault();
      const next = event.key === "Home" ? 0
        : event.key === "End" ? buttons.length - 1
        : (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next]?.focus?.({ preventScroll: true });
    });

    return picker;
  }

  function closeAllPickers(exceptKey = "", options) {
    const restoreFocus = Boolean(options && options.restoreFocus);
    for (const key of pickerKeys) {
      const picker = pickers[key];
      if (!picker || key === exceptKey) continue;
      picker.close({ restoreFocus });
    }
  }

  function linkOptions() {
    const options = [["", "不关联"]];
    for (const topic of state.linkOptions.topics) options.push(["topic:" + topic.id, "选题 · " + topic.title]);
    for (const script of state.linkOptions.scripts) options.push(["script:" + script.id, "脚本 · " + script.title]);
    return options;
  }

  pickers.link = createPicker("link", { input: "homeTaskLinkSelect", label: "关联内容", options: linkOptions });
  pickers.category = createPicker("category", {
    input: "homeConvertCategorySelect",
    label: "选题分类",
    options: () => Object.keys(CATEGORY_LABELS).map((key) => [key, CATEGORY_LABELS[key]]),
  });
  pickers.format = createPicker("format", {
    input: "homeConvertFormatSelect",
    label: "内容形式",
    options: () => Object.keys(FORMAT_LABELS).map((key) => [key, FORMAT_LABELS[key]]),
  });

  // ------------------------------------------------------------------ data

  function applyOverview(payload) {
    const today = payload.todayTasks || {};
    const ideas = payload.inspirations || {};
    const links = payload.linkOptions || {};
    state.date = payload.date || state.date;
    state.weekStart = payload.weekStart || state.weekStart;
    state.stats = payload.stats || null;
    state.tasks = Array.isArray(today.allItems) ? today.allItems : (Array.isArray(today.items) ? today.items : []);
    state.taskCount = Number.isFinite(today.count) ? today.count : state.tasks.length;
    state.inspirations = Array.isArray(ideas.items) ? ideas.items : [];
    state.inspirationTotal = Number.isFinite(ideas.total) ? ideas.total : state.inspirations.length;
    state.week = payload.week || null;
    state.linkOptions = {
      topics: Array.isArray(links.topics) ? links.topics : [],
      scripts: Array.isArray(links.scripts) ? links.scripts : [],
    };
  }

  async function loadHome(options) {
    const silent = Boolean(options && options.silent);
    const accountId = state.accountId;
    if (!accountId) {
      state.loaded = false;
      state.stats = null;
      render();
      return;
    }
    const version = ++state.requestVersion;
    state.loading = true;
    if (!silent) {
      state.message = "";
      state.actionMessage = "";
    }
    try {
      const url = "/api/accounts/" + encodeURIComponent(accountId) + "/home?today=" + state.date + "&weekStart=" + state.weekStart;
      const payload = await api(url);
      if (version !== state.requestVersion || !isSameAccount(accountId)) return;
      applyOverview(payload);
      state.loaded = true;
      state.message = "";
    } catch (error) {
      if (version !== state.requestVersion || !isSameAccount(accountId)) return;
      state.message = responseMessage(error, "首页读取失败，可稍后重试。");
      state.loaded = false;
      state.taskCount = 0;
      state.inspirationTotal = 0;
      state.stats = null;
      state.tasks = [];
      state.taskCount = 0;
      state.inspirations = [];
      state.inspirationTotal = 0;
      state.week = null;
      showToast(responseMessage(error, "首页读取失败"), "error");
    } finally {
      if (version === state.requestVersion) state.loading = false;
      if (isSameAccount(accountId)) render();
    }
  }

  function onAccountChange(accountId) {
    window.homeAdviceModule?.onAccountChange?.(accountId);
    const next = String(accountId || "");
    if (next === state.accountId) return;
    state.accountId = next;
    state.loaded = false;
    state.stats = null;
    state.tasks = [];
    state.taskCount = 0;
    state.inspirations = [];
    state.inspirationTotal = 0;
    state.week = null;
    state.linkOptions = { topics: [], scripts: [] };
    state.requestVersion += 1;
    state.message = "";
    state.actionMessage = "";
    state.editingTaskId = "";
    state.editingInspirationId = "";
    state.dueFilter = "all";
    state.duePage = 1;
    state.taskScope = "pending";
    state.taskPage = 1;
    state.inspirationPage = 1;
    state.date = todayIso();
    state.weekStart = weekStartOf(new Date());
    closeTaskMenu();
    // Paint the cleared state first so the previous account's numbers never linger.
    render();
    if (next) loadHome();
  }

  // -------------------------------------------------------------- rendering

  function render() {
    renderHeader();
    renderStats();
    renderTasks();
    renderWeek();
    renderInspirations();
    renderTaskModalList();
    renderInspirationModalList();
  }

  function renderHeader() {
    if (!dom.title) return;
    dom.title.textContent = "工作概况";
    if (!dom.date) return;
    if (!state.accountId) dom.date.textContent = "先选择账号";
    else if (state.loaded) dom.date.textContent = formatDateLine(state.date);
    else dom.date.textContent = state.message || "读取中…";
  }

  function renderStats() {
    if (!dom.statsList) return;
    const stats = state.stats;
    const counts = (stats && stats.statusCounts) || {};
    const hints = { pending: "推进脚本", editing: "准备出镜", ready_to_publish: "完成发布准备", published: "回看内容表现" };
    const definitions = [
      { key: "topicCount", label: "选题", hint: "寻找下一个方向", value: stats ? stats.topicCount : null },
    ].concat(STATUS_ORDER.map((status) => ({
      key: "status:" + status, label: STATUS_LABELS[status], hint: hints[status],
      value: stats ? counts[status] || 0 : null,
    })));
    dom.statsList.replaceChildren(...definitions.map((definition) => {
      const button = el("button", "home-stat");
      button.type = "button";
      button.dataset.homeStat = definition.key;
      button.append(
        el("span", "home-stat-label", definition.label),
        el("strong", "home-stat-value", definition.value === null ? "—" : String(definition.value)),
        el("small", "home-stat-hint", definition.hint),
      );
      button.addEventListener("click", () => handleStatClick(definition.key));
      return button;
    }));
    setMessage(dom.statsMessage, state.message);
  }

  function taskActionLabel(item) {
    if (item.kind === "manual") return item.done ? "重新打开" : "标记完成";
    if (!item.scriptId) return "去创作";
    if (item.status === "pending") return "继续编写";
    if (item.status === "editing") return "查看拍摄稿";
    if (item.status === "ready_to_publish") return "发布准备";
    return "查看脚本";
  }

  function taskMetaText(item) {
    if (item.kind === "manual") {
      const parts = ["手动任务", relativeDayLabel(item.date) + "完成"];
      if (item.linkType) parts.push(item.linkMissing ? "关联内容已删除" : "关联：" + item.linkTitle);
      return parts.join(" · ");
    }
    return (STATUS_LABELS[item.status] || "待处理") + " · 计划" + relativeDayLabel(item.date) + "发布";
  }

  function taskIcon(item) {
    const paths = item.kind === "manual"
      ? ["M9 4H6a1 1 0 0 0-1 1v15a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V5a1 1 0 0 0-1-1h-3M9 2h6v4H9Z", "m8 11 1.5 1.5L12 10m2 2h2m-8 5h8"]
      : !item.scriptId
        ? ["m4 20 3-11 8-5 5 5-5 8-11 3Zm0 0 7-7m3-10 7 7", "M13.5 12a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0"]
        : item.status === "editing"
          ? ["M4 6h12v14H4Zm12 5 5-3v10l-5-3M7 3h6"]
          : item.status === "ready_to_publish"
            ? ["M12 16V3m-4 4 4-4 4 4M5 13v7h14v-7"]
            : ["M13 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5M8 8h4M8 12h2M8 16h2", "m13 13 1-4 5.5-5.5a1.4 1.4 0 0 1 2 2L16 11l-3 2Zm4.5-7.5 2 2"];
    const icon = el("span", "home-task-icon");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    for (const [key, value] of Object.entries({ viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "1.6", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" })) svg.setAttribute(key, value);
    paths.forEach((d) => { const path = document.createElementNS("http://www.w3.org/2000/svg", "path"); path.setAttribute("d", d); svg.append(path); });
    icon.append(svg);
    return icon;
  }

  function buildTaskRow(item, options) {
    const inModal = Boolean(options && options.inModal);
    const row = el("li", "home-task-row");
    row.dataset.homeTask = item.id;
    const copy = el("div", "home-task-copy");
    const title = el("p", "home-task-title", item.title || "未命名任务");
    title.setAttribute("title", item.title || "未命名任务");
    copy.append(title);
    const meta = el("p", "home-task-meta", taskMetaText(item));
    if (item.overdueDays > 0) meta.append(el("span", "home-task-overdue", "逾期 " + item.overdueDays + " 天"));
    copy.append(meta);

    const actions = el("div", "home-task-actions");
    const action = el("button", "am-secondary-action home-task-action", taskActionLabel(item) + " →");
    action.type = "button";
    action.addEventListener("click", () => runTaskAction(item));
    actions.append(action);
    if (!inModal) {
      const more = el("button", "home-task-more");
      const dots = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      dots.setAttribute("viewBox", "0 0 24 24");
      dots.setAttribute("width", "18"); dots.setAttribute("height", "18");
      dots.setAttribute("fill", "currentColor"); dots.setAttribute("aria-hidden", "true");
      [5, 12, 19].forEach((cy) => { const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle"); circle.setAttribute("cx", "12"); circle.setAttribute("cy", cy); circle.setAttribute("r", "1.5"); dots.append(circle); });
      more.append(dots);
      more.type = "button";
      more.setAttribute("aria-haspopup", "menu");
      more.setAttribute("aria-expanded", "false");
      more.setAttribute("aria-label", "更多操作");
      more.addEventListener("click", (event) => {
        event.stopPropagation?.();
        if (state.menuTaskKey === item.id) closeTaskMenu();
        else openTaskMenu(item, more);
      });
      actions.append(more);
    }
    row.append(copy, actions);
    if (!inModal) row.append(taskIcon(item));
    return row;
  }

  function renderTasks() {
    if (!dom.taskList) return;
    const overdue = state.tasks.filter((item) => item.overdueDays > 0);
    const items = state.dueFilter === "overdue" ? overdue : state.tasks;
    const pages = Math.max(1, Math.ceil(items.length / 4));
    state.duePage = Math.min(state.duePage, pages);
    dom.taskList.replaceChildren(...items.slice((state.duePage - 1) * 4, state.duePage * 4).map((item) => buildTaskRow(item)));
    if (dom.taskCount) dom.taskCount.textContent = state.loaded ? state.taskCount + " 项待办" : "";
    if (dom.dueAll) { dom.dueAll.textContent = "全部待办" + (state.loaded ? " " + state.taskCount : ""); dom.dueAll.setAttribute("aria-pressed", String(state.dueFilter === "all")); }
    if (dom.dueOverdue) { dom.dueOverdue.textContent = "逾期事项" + (state.loaded ? " " + overdue.length : ""); dom.dueOverdue.setAttribute("aria-pressed", String(state.dueFilter === "overdue")); }
    if (dom.duePage) dom.duePage.textContent = state.loaded ? "共 " + items.length + " 项 · " + state.duePage + " / " + pages : "";
    if (dom.duePrev) dom.duePrev.disabled = !state.loaded || state.duePage <= 1;
    if (dom.dueNext) dom.dueNext.disabled = !state.loaded || state.duePage >= pages;
    if (dom.taskEmpty) {
      dom.taskEmpty.hidden = !(state.loaded && items.length === 0) || Boolean(state.message);
      dom.taskEmpty.textContent = state.dueFilter === "overdue" ? "暂无逾期事项。" : "今天没有待办，安排一个新任务吧。";
    }
    setMessage(dom.taskMessage, state.message || state.actionMessage);
    if (dom.focusTitle) dom.focusTitle.textContent = !state.accountId ? "选择工作台，开始今天的创作。" : state.message ? "暂时无法读取今日工作" : !state.loaded ? "正在整理今日工作…" : state.taskCount ? "先推进手里的内容，再开始新创作。" : "今天的待办已清，开始下一条创作。";
    if (dom.focusDescription) dom.focusDescription.textContent = state.loaded && !state.message ? (state.taskCount ? "当前有 " + state.taskCount + " 项待办需要处理，其中 " + overdue.length + " 项已逾期。\n先确认发布安排，让积累的想法变成真正发布的作品。" : "记下一个灵感，或从本周选题中开始新的创作。") : (state.message || "选题、脚本和发布安排都将汇总在这里。");
    if (dom.focusAction) { dom.focusAction.disabled = !state.accountId || (!state.loaded && !state.message); dom.focusAction.textContent = state.message ? "重新加载 ↗" : state.taskCount ? "处理今日待办 ↗" : "新建脚本 ↗"; }
    if (dom.focusOverdue) dom.focusOverdue.hidden = !state.loaded || Boolean(state.message) || !overdue.length;
    scheduleInspirationLayout();
  }

  function renderWeek() {
    const week = state.week;
    const target = week ? week.target : 0;
    const published = week ? week.published : 0;
    if (dom.weekProgress) dom.weekProgress.textContent = week ? published + " / " + target : "—";
    if (dom.weekPercent) {
      if (!week) dom.weekPercent.textContent = "";
      else if (week.percent === null || week.percent === undefined) dom.weekPercent.textContent = "未设目标";
      else dom.weekPercent.textContent = week.percent + "%";
    }
    if (dom.weekBar) dom.weekBar.style.width = week && week.percent ? week.percent + "%" : "0%";
    if (dom.weekMeta) {
      const meta = week ? [["待拍摄", week.editing], ["待发布", week.readyToPublish]] : [];
      dom.weekMeta.replaceChildren(...meta.map(([label, value]) => {
        const item = el("li", "home-week-meta-item");
        item.append(el("span", "", label), el("strong", "", String(value)));
        return item;
      }));
    }
    if (dom.weekRing) dom.weekRing.style.background = "conic-gradient(#292929 " + (week?.percent || 0) + "%, #ededed 0)";
    if (dom.weekHeadline) dom.weekHeadline.textContent = !week ? "本周计划尚未加载" : !target ? "先设定本周发布目标" : published >= target ? "本周目标已完成" : published ? "继续推进本周的内容" : "新的一周，从第一条开始";
    if (dom.weekRange) dom.weekRange.textContent = week ? state.weekStart.slice(5).replace("-", ".") + " — " + shiftIso(state.weekStart, 6).slice(5).replace("-", ".") + " · 按选题计划统计" : "";
    if (dom.weekDays) dom.weekDays.replaceChildren(...(week ? Array.from({ length: 7 }, (_, i) => {
      const date = shiftIso(state.weekStart, i);
      const day = el("div", "home-week-day" + (date === state.date ? " is-today" : ""));
      day.append(el("span", "", "一二三四五六日"[i]), el("span", "home-week-date", String(Number(date.slice(-2)))));
      if (date === state.date) day.setAttribute("aria-current", "date");
      return day;
    }) : []));
    setMessage(dom.weekMessage, state.message);
  }

  function buildInspirationItem(item, options) {
    const full = Boolean(options && options.full);
    const row = el("li", "home-inspiration-item");
    row.dataset.homeInspiration = item.id;
    const copy = el("div", "home-inspiration-copy");

    if (full && state.editingInspirationId === item.id) {
      row.classList.add("is-editing");
      const editor = el("textarea", "am-textarea home-inspiration-editor");
      editor.value = item.text;
      editor.maxLength = 2000;
      const sourceInput = el("input", "am-input home-inspiration-editor-source");
      sourceInput.type = "text";
      sourceInput.maxLength = 500;
      sourceInput.value = item.source || "";
      sourceInput.placeholder = "来源或参考链接（选填）";
      copy.append(editor, sourceInput);
      const actions = el("div", "home-inspiration-actions");
      const save = el("button", "am-primary-action home-compact-action", "保存");
      save.type = "button";
      save.addEventListener("click", () => saveInspirationEdit(item, editor, sourceInput));
      const cancel = el("button", "am-secondary-action home-compact-action", "取消");
      cancel.type = "button";
      cancel.addEventListener("click", () => {
        state.editingInspirationId = "";
        renderInspirationModalList();
      });
      actions.append(save, cancel);
      row.append(copy, actions);
      return row;
    }

    copy.append(el("p", "home-inspiration-text", item.text));
    const meta = item.source
      ? "来源：" + item.source + " · " + formatStamp(item.createdAt)
      : formatStamp(item.createdAt);
    const details = full ? el("div", "home-inspiration-details") : copy;
    details.append(el("p", "home-inspiration-meta", meta));
    if (full) copy.append(details);

    const actions = el("div", "home-inspiration-actions");
    if (item.topicId) {
      (full ? details : actions).append(el("span", "home-inspiration-badge", item.topicMissing ? "关联选题已删除" : "已转入选题"));
      if (!item.topicMissing) {
        const view = el("button", full ? "am-secondary-action home-compact-action" : "home-link-button", "查看选题 →");
        view.type = "button";
        view.addEventListener("click", () => openTopics());
        actions.append(view);
      }
    } else {
      const convert = el("button", "am-secondary-action home-compact-action", "转为选题");
      convert.type = "button";
      convert.addEventListener("click", () => openConvertModal(item));
      actions.append(convert);
    }
    if (full) {
      const edit = el("button", "am-secondary-action home-compact-action", "编辑");
      edit.type = "button";
      edit.addEventListener("click", () => {
        state.editingInspirationId = item.id;
        renderInspirationModalList();
      });
      const remove = el("button", "am-secondary-action home-compact-action home-inspiration-delete", "删除");
      remove.type = "button";
      remove.addEventListener("click", () => deleteInspiration(item));
      actions.append(edit, remove);
    }
    row.append(copy, actions);
    return row;
  }

  let inspirationLayoutFrame = 0;

  function scheduleInspirationLayout() {
    if (!window.requestAnimationFrame || inspirationLayoutFrame) return;
    inspirationLayoutFrame = window.requestAnimationFrame(() => {
      inspirationLayoutFrame = 0;
      fitInspirationPreview();
    });
  }

  function fitInspirationPreview() {
    if (root.classList.contains("home-redesign")) return;
    const panel = dom.inspirationPanel;
    if (!panel || !dom.taskPanel || !panel.getClientRects().length) return;
    const list = dom.inspirationList;
    const block = list.closest(".home-list-block");
    const rows = Array.from(list.children);
    block.hidden = false;
    panel.style.height = "";
    rows.forEach((row, index) => { row.hidden = window.innerWidth <= 1240 && index >= 3; });
    if (window.innerWidth <= 1240) return;

    // Measure the task card independently: the preview must never stretch it.
    const taskHeight = dom.taskPanel.getBoundingClientRect().height;
    const panelTop = panel.getBoundingClientRect().top;
    const style = window.getComputedStyle(panel);
    const padding = parseFloat(style.paddingBottom) || 0;
    const gap = parseFloat(style.rowGap) || 0;
    const formHeight = block.getBoundingClientRect().top - panelTop - gap + padding;
    const height = Math.max(taskHeight, formHeight);
    const bottom = panelTop + height - padding;
    let visibleCount = 0;
    let full = false;
    rows.forEach((row) => {
      full = full || row.getBoundingClientRect().bottom > bottom + 0.5;
      row.hidden = full;
      if (!full) visibleCount += 1;
    });
    // When tasks are few, keep the form usable and access records via View all.
    block.hidden = rows.length > 0
      ? visibleCount === 0
      : block.getBoundingClientRect().bottom > bottom + 0.5;
    panel.style.height = height + "px";
  }

  function renderInspirations() {
    const hasRecords = state.loaded && !state.message && state.inspirations.length > 0;
    if (dom.ideaPending) dom.ideaPending.hidden = !hasRecords;
    if (dom.inspirationRecentLabel) dom.inspirationRecentLabel.hidden = !hasRecords;
    if (dom.ideaPending) dom.ideaPending.textContent = state.loaded && state.stats ? state.stats.pendingInspirationCount + " 条待整理灵感" : "";
    if (!dom.inspirationList) return;
    dom.inspirationList.replaceChildren(...state.inspirations.slice(0, 2).map((item) => buildInspirationItem(item)));
    if (dom.inspirationEmpty) {
      dom.inspirationEmpty.hidden = !(state.loaded && state.inspirations.length === 0) || Boolean(state.message);
    }
    scheduleInspirationLayout();
  }

  function renderTaskModalList() {
    if (!dom.taskModalList) return;
    dom.taskModalList.replaceChildren(...state.taskModalItems.map((item) => buildTaskRow(item, { inModal: true })));
    if (dom.taskModalEmpty) {
      dom.taskModalEmpty.hidden = state.taskModalItems.length > 0 || Boolean(state.taskModalMessage);
      dom.taskModalEmpty.textContent = state.taskModalMessage
        || (state.taskScope === "done" ? "还没有已完成的任务。" : "没有待办任务。");
    }
    if (dom.taskPageLabel) dom.taskPageLabel.textContent = "第 " + state.taskPage + " / " + state.taskPageCount + " 页";
    if (dom.taskPrev) dom.taskPrev.disabled = state.taskPage <= 1;
    if (dom.taskNext) dom.taskNext.disabled = state.taskPage >= state.taskPageCount;
    if (dom.taskScopeTabs) {
      dom.taskScopeTabs.querySelectorAll("[data-home-task-scope]").forEach((button) => {
        const selected = button.dataset.homeTaskScope === state.taskScope;
        button.setAttribute("aria-selected", String(selected));
        button.classList.toggle("is-active", selected);
      });
    }
  }

  function renderInspirationModalList() {
    if (!dom.inspirationModalList) return;
    const page = paginate(state.inspirations, state.inspirationPage, INSPIRATION_PAGE_SIZE);
    state.inspirationPage = page.page;
    dom.inspirationModalList.replaceChildren(...page.items.map((item) => buildInspirationItem(item, { full: true })));
    if (dom.inspirationModalEmpty) dom.inspirationModalEmpty.hidden = state.inspirations.length > 0;
    if (dom.inspirationPageLabel) dom.inspirationPageLabel.textContent = "第 " + page.page + " / " + page.pageCount + " 页";
    if (dom.inspirationPrev) dom.inspirationPrev.disabled = page.page <= 1;
    if (dom.inspirationNext) dom.inspirationNext.disabled = page.page >= page.pageCount;
  }

  // --------------------------------------------------------------- task menu

  function closeTaskMenu() {
    state.menuTaskKey = "";
    state.menuAnchor = null;
    if (!dom.taskRowMenu) return;
    dom.taskRowMenu.hidden = true;
    dom.taskRowMenu.replaceChildren();
  }

  function menuActionsFor(item) {
    if (item.kind === "manual") {
      return [
        { label: item.done ? "重新打开" : "标记完成", run: () => toggleTask(item) },
        { label: "编辑", run: () => openTaskEditor(item) },
        { label: "修改日期", run: () => openReschedule(item) },
        { label: "删除", tone: "danger", run: () => deleteTask(item) },
      ];
    }
    return [
      { label: taskActionLabel(item), run: () => runTaskAction(item) },
      { label: "修改日期", run: () => openReschedule(item) },
      { label: "查看选题", run: () => openTopics() },
    ];
  }

  function openTaskMenu(item, anchor) {
    if (!dom.taskRowMenu) return;
    state.menuTaskKey = item.id;
    state.menuAnchor = anchor;
    dom.taskRowMenu.replaceChildren(...menuActionsFor(item).map((action) => {
      const button = el("button", action.tone === "danger" ? "is-danger" : "", action.label);
      button.type = "button";
      button.setAttribute("role", "menuitem");
      button.addEventListener("click", () => {
        closeTaskMenu();
        action.run();
      });
      return button;
    }));
    dom.taskRowMenu.hidden = false;
    anchor.setAttribute("aria-expanded", "true");
    positionTaskMenu();
  }

  function positionTaskMenu() {
    if (!dom.taskRowMenu || dom.taskRowMenu.hidden || !state.menuAnchor) return;
    const rect = state.menuAnchor.getBoundingClientRect();
    const width = dom.taskRowMenu.offsetWidth || 148;
    const viewport = window.innerWidth || 1440;
    const left = Math.max(8, Math.min(rect.right - width, viewport - width - 8));
    dom.taskRowMenu.style.left = left + "px";
    dom.taskRowMenu.style.top = rect.bottom + 6 + "px";
  }

  // -------------------------------------------------------------- task edits

  async function runTaskAction(item) {
    if (item.kind === "manual") {
      await toggleTask(item);
      return;
    }
    await openTopicScript(item.topicId, { create: !item.scriptId });
  }

  async function toggleTask(item) {
    try {
      await api("/api/manual-tasks/" + encodeURIComponent(item.id), { method: "PATCH", body: { done: !item.done } });
      await refreshAfterChange();
      showToast(item.done ? "任务已重新打开" : "任务已完成", "success");
    } catch (error) {
      state.actionMessage = responseMessage(error, "任务更新失败");
      render();
      showToast(responseMessage(error, "任务更新失败"), "error");
    }
  }

  async function deleteTask(item) {
    try {
      await api("/api/manual-tasks/" + encodeURIComponent(item.id), { method: "DELETE" });
      await refreshAfterChange();
      showToast("任务已删除", "success");
    } catch (error) {
      state.actionMessage = responseMessage(error, "任务删除失败");
      render();
      showToast(responseMessage(error, "任务删除失败"), "error");
    }
  }

  function resizeTaskNote() {
    if (!dom.taskNote || !dom.taskModal || dom.taskModal.hidden) return;
    const field = dom.taskNote;
    if (window.CSS?.supports?.("field-sizing", "content")) {
      field.style.height = "auto";
      return;
    }
    field.style.height = "90px";
    const borderHeight = field.offsetHeight - field.clientHeight;
    field.style.height = `${Math.max(90, field.scrollHeight + borderHeight)}px`;
  }

  function openTaskEditor(item) {
    closeTaskMenu();
    state.editingTaskId = item ? item.id : "";
    dom.taskModalTitle.textContent = item ? "编辑任务" : "添加任务";
    dom.taskTitle.value = item ? item.title : "";
    dom.taskDate.value = item ? item.date : todayIso();
    dom.taskNote.value = item && item.note ? item.note : "";
    const linkValue = item && item.linkType && item.linkId ? item.linkType + ":" + item.linkId : "";
    if (pickers.link) pickers.link.select(linkValue, { silent: true });
    else if (dom.taskLink) dom.taskLink.value = linkValue;
    dom.taskDelete.hidden = !item;
    setMessage(dom.taskError, "");
    setModalOpen(dom.taskModal, true);
    resizeTaskNote();
    dom.taskTitle.focus?.({ preventScroll: true });
  }

  async function saveTask() {
    if (window.WorkbenchDateTimePicker?.validateInputs(dom.taskDate) === false) return;
    closeAllPickers();
    const title = dom.taskTitle.value.trim();
    if (!title) {
      setMessage(dom.taskError, "任务内容不能为空。");
      return;
    }
    const rawLink = dom.taskLink ? dom.taskLink.value : "";
    const parts = rawLink ? rawLink.split(":") : ["", ""];
    const body = {
      title,
      date: dom.taskDate.value || todayIso(),
      note: dom.taskNote.value.trim(),
      linkType: parts[0] || "",
      linkId: parts.slice(1).join(":") || "",
    };
    const editingId = state.editingTaskId;
    try {
      if (editingId) {
        await api("/api/manual-tasks/" + encodeURIComponent(editingId), { method: "PATCH", body });
      } else if (state.accountId) {
        await api("/api/accounts/" + encodeURIComponent(state.accountId) + "/manual-tasks", { method: "POST", body });
      }
      setModalOpen(dom.taskModal, false);
      state.editingTaskId = "";
      await refreshAfterChange();
      showToast(editingId ? "任务已更新" : "任务已添加", "success");
    } catch (error) {
      setMessage(dom.taskError, responseMessage(error, "任务保存失败"));
    }
  }

  async function deleteTaskFromEditor() {
    const editingId = state.editingTaskId;
    if (!editingId) return;
    try {
      await api("/api/manual-tasks/" + encodeURIComponent(editingId), { method: "DELETE" });
      setModalOpen(dom.taskModal, false);
      state.editingTaskId = "";
      await refreshAfterChange();
      showToast("任务已删除", "success");
    } catch (error) {
      setMessage(dom.taskError, responseMessage(error, "任务删除失败"));
    }
  }

  function openReschedule(item) {
    closeTaskMenu();
    state.rescheduling = item;
    dom.rescheduleHint.textContent = item.kind === "manual"
      ? "这条手动任务的执行日期。"
      : "这条选题的计划发布日期会一起更新。";
    dom.rescheduleDate.value = item.date || todayIso();
    setMessage(dom.rescheduleError, "");
    setModalOpen(dom.rescheduleModal, true);
    dom.rescheduleDate.focus?.({ preventScroll: true });
  }

  async function saveReschedule() {
    if (window.WorkbenchDateTimePicker?.validateInputs(dom.rescheduleDate) === false) return;
    const item = state.rescheduling;
    if (!item) return;
    const value = dom.rescheduleDate.value;
    if (!value) {
      setMessage(dom.rescheduleError, "请选择日期。");
      return;
    }
    try {
      if (item.kind === "manual") {
        await api("/api/manual-tasks/" + encodeURIComponent(item.id), { method: "PATCH", body: { date: value } });
      } else {
        await api("/api/topics/" + encodeURIComponent(item.topicId), { method: "PATCH", body: { publishDate: value } });
      }
      setModalOpen(dom.rescheduleModal, false);
      state.rescheduling = null;
      await refreshAfterChange();
      showToast("日期已更新", "success");
    } catch (error) {
      setMessage(dom.rescheduleError, responseMessage(error, "日期保存失败"));
    }
  }

  // ------------------------------------------------------------ task dialog

  async function loadTaskList() {
    if (!state.accountId) return;
    try {
      const url = "/api/accounts/" + encodeURIComponent(state.accountId) + "/home/tasks?scope=" + state.taskScope
        + "&page=" + state.taskPage + "&pageSize=" + TASK_PAGE_SIZE + "&today=" + state.date;
      const payload = await api(url);
      state.taskModalItems = Array.isArray(payload.items) ? payload.items : [];
      state.taskPage = payload.page || 1;
      state.taskPageCount = payload.pageCount || 1;
      state.taskModalMessage = "";
    } catch (error) {
      state.taskModalItems = [];
      state.taskPageCount = 1;
      state.taskModalMessage = responseMessage(error, "任务读取失败");
    }
    renderTaskModalList();
  }

  function openTaskListModal() {
    closeTaskMenu();
    state.taskScope = "pending";
    state.taskPage = 1;
    setModalOpen(dom.taskListModal, true);
    loadTaskList();
  }

  // ----------------------------------------------------------- inspirations

  async function saveInspiration() {
    const text = dom.inspirationInput.value.trim();
    if (!text) {
      setMessage(dom.inspirationMessage, "先写下一条灵感。");
      return;
    }
    if (!state.accountId) return;
    try {
      await api("/api/accounts/" + encodeURIComponent(state.accountId) + "/inspirations", {
        method: "POST",
        body: { text, source: dom.inspirationSourceInput.value.trim() },
      });
      dom.inspirationInput.value = "";
      dom.inspirationSourceInput.value = "";
      setMessage(dom.inspirationMessage, "");
      await refreshAfterChange();
      showToast("已保存灵感", "success");
    } catch (error) {
      setMessage(dom.inspirationMessage, responseMessage(error, "灵感保存失败"));
    }
  }

  async function saveInspirationEdit(item, editor, sourceInput) {
    const text = editor.value.trim();
    if (!text) {
      showToast("灵感内容不能为空", "error");
      return;
    }
    try {
      await api("/api/inspirations/" + encodeURIComponent(item.id), {
        method: "PATCH",
        body: { text, source: sourceInput.value.trim() },
      });
      state.editingInspirationId = "";
      await refreshAfterChange();
      showToast("灵感已更新", "success");
    } catch (error) {
      showToast(responseMessage(error, "灵感保存失败"), "error");
    }
  }

  async function deleteInspiration(item) {
    try {
      await api("/api/inspirations/" + encodeURIComponent(item.id), { method: "DELETE" });
      state.editingInspirationId = "";
      await refreshAfterChange();
      showToast("灵感已删除", "success");
    } catch (error) {
      showToast(responseMessage(error, "灵感删除失败"), "error");
    }
  }

  function openInspirationModal() {
    state.inspirationPage = 1;
    state.editingInspirationId = "";
    setModalOpen(dom.inspirationModal, true);
    renderInspirationModalList();
  }

  function openConvertModal(item) {
    state.convertingInspirationId = item.id;
    state.editingInspirationId = "";
    setModalOpen(dom.inspirationModal, false);
    dom.convertHint.textContent = "灵感内容会带入选题大纲，可以先调整再确认。";
    const firstLine = item.text.split(NEWLINE).find((line) => line.trim()) || item.text;
    dom.convertTitle.value = firstLine.trim().slice(0, 160);
    dom.convertOutline.value = item.text;
    if (pickers.category) pickers.category.select("daily", { silent: true });
    if (pickers.format) pickers.format.select("video", { silent: true });
    dom.convertWeek.value = weekStartOf(new Date());
    dom.convertPublishDate.value = "";
    setMessage(dom.convertError, "");
    setModalOpen(dom.convertModal, true);
    dom.convertTitle.focus?.({ preventScroll: true });
  }

  async function confirmConvert() {
    if (window.WorkbenchDateTimePicker?.validateInputs(dom.convertWeek, dom.convertPublishDate) === false) return;
    const inspirationId = state.convertingInspirationId;
    if (!inspirationId) return;
    closeAllPickers();
    const title = dom.convertTitle.value.trim();
    if (!title) {
      setMessage(dom.convertError, "选题标题不能为空。");
      return;
    }
    const weekValue = dom.convertWeek.value;
    const weekStart = weekValue ? weekStartOf(parseIso(weekValue) || new Date()) : state.weekStart;
    try {
      await api("/api/inspirations/" + encodeURIComponent(inspirationId) + "/topic", {
        method: "POST",
        body: {
          title,
          outline: dom.convertOutline.value.trim(),
          category: dom.convertCategory.value || "daily",
          format: dom.convertFormat.value || "video",
          weekStart,
          publishDate: dom.convertPublishDate.value || "",
        },
      });
      setModalOpen(dom.convertModal, false);
      state.convertingInspirationId = "";
      /* 选题页保留着已读的周，这里写入的是另一页的数据，交给它下次进入时补读。 */
      window.topicsModule?.invalidate?.();
      await refreshAfterChange();
      showToast("已加入选题库", "success");
    } catch (error) {
      setMessage(dom.convertError, responseMessage(error, "转为选题失败"));
    }
  }

  // -------------------------------------------------------------- handoffs

  function openTopics() {
    window.selectWorkspaceModule?.("topics");
  }

  function openTopicsWeek() {
    const week = state.weekStart || weekStartOf(new Date());
    window.selectWorkspaceModule?.("topics");
    window.topicsModule?.actions?.selectWeek?.(week);
  }

  function openScripts(status) {
    window.selectWorkspaceModule?.("scripts");
    window.selectScriptStatusFilter?.(status || "all");
  }

  function startNewScript() {
    window.selectWorkspaceModule?.("create");
    window.openNewScriptPanel?.();
  }

  /* A topic without a script opens 去创作; a linked one opens that script. */
  async function openTopicScript(topicId, { create = false } = {}) {
    const topics = window.topicsModule;
    if (!topicId || !topics) {
      openTopics();
      return;
    }
    if (!topics.state?.loaded) {
      try {
        await topics.refresh?.();
      } catch (_error) {
        // The topics module renders its own failure message.
      }
    }
    if (create) await topics.actions?.openTopicCreation?.(topicId);
    else await topics.actions?.openTopicScript?.(topicId);
  }

  function handleStatClick(key) {
    if (key === "topicCount") {
      openTopics();
      return;
    }
    if (key === "pendingInspirationCount") {
      openInspirationModal();
      return;
    }
    if (key === "scriptCount") {
      openScripts("all");
      return;
    }
    if (key.indexOf("status:") === 0) openScripts(key.slice("status:".length));
  }

  async function refreshAfterChange() {
    await loadHome({ silent: true });
    if (dom.taskListModal && !dom.taskListModal.hidden) await loadTaskList();
  }

  // ---------------------------------------------------------------- wiring

  const filterDue = (filter) => { closeTaskMenu(); state.dueFilter = filter; state.duePage = 1; renderTasks(); };
  dom.dueAll?.addEventListener("click", () => filterDue("all"));
  dom.dueOverdue?.addEventListener("click", () => filterDue("overdue"));
  dom.duePrev?.addEventListener("click", () => { if (state.duePage > 1) { closeTaskMenu(); state.duePage--; renderTasks(); } });
  dom.dueNext?.addEventListener("click", () => { if (!dom.dueNext.disabled) { closeTaskMenu(); state.duePage++; renderTasks(); } });
  dom.focusAction?.addEventListener("click", () => { if (state.message) loadHome(); else if (state.taskCount) { filterDue("all"); dom.taskPanel?.scrollIntoView({ behavior: "smooth", block: "center" }); } else startNewScript(); });
  dom.focusOverdue?.addEventListener("click", () => { filterDue("overdue"); dom.taskPanel?.scrollIntoView({ behavior: "smooth", block: "center" }); });
  dom.breakdown?.addEventListener("click", () => window.selectWorkspaceModule?.("split"));
  root.querySelectorAll("[data-home-navigation]").forEach((button) => button.addEventListener("click", () => button.dataset.homeNavigation === "topics" ? openTopicsWeek() : window.selectWorkspaceModule?.(button.dataset.homeNavigation)));

  dom.addTask?.addEventListener("click", () => openTaskEditor(null));
  dom.newScript?.addEventListener("click", startNewScript);
  dom.taskMore?.addEventListener("click", openTaskListModal);
  dom.weekPlan?.addEventListener("click", openTopicsWeek);
  dom.inspirationMore?.addEventListener("click", openInspirationModal);
  dom.inspirationSave?.addEventListener("click", saveInspiration);
  dom.taskSave?.addEventListener("click", saveTask);
  dom.taskNote?.addEventListener("input", resizeTaskNote);
  dom.taskCancel?.addEventListener("click", () => {
    state.editingTaskId = "";
    setModalOpen(dom.taskModal, false);
  });
  dom.taskDelete?.addEventListener("click", deleteTaskFromEditor);
  dom.taskListClose?.addEventListener("click", () => setModalOpen(dom.taskListModal, false));
  dom.taskPrev?.addEventListener("click", () => {
    if (state.taskPage <= 1) return;
    state.taskPage -= 1;
    loadTaskList();
  });
  dom.taskNext?.addEventListener("click", () => {
    if (state.taskPage >= state.taskPageCount) return;
    state.taskPage += 1;
    loadTaskList();
  });
  dom.taskScopeTabs?.addEventListener("click", (event) => {
    const button = event.target.closest?.("[data-home-task-scope]");
    if (!button) return;
    state.taskScope = button.dataset.homeTaskScope === "done" ? "done" : "pending";
    state.taskPage = 1;
    renderTaskModalList();
    loadTaskList();
  });
  dom.inspirationClose?.addEventListener("click", () => setModalOpen(dom.inspirationModal, false));
  dom.inspirationPrev?.addEventListener("click", () => {
    state.inspirationPage = Math.max(1, state.inspirationPage - 1);
    state.editingInspirationId = "";
    renderInspirationModalList();
  });
  dom.inspirationNext?.addEventListener("click", () => {
    state.inspirationPage += 1;
    state.editingInspirationId = "";
    renderInspirationModalList();
  });
  dom.convertConfirm?.addEventListener("click", confirmConvert);
  dom.convertCancel?.addEventListener("click", () => {
    state.convertingInspirationId = "";
    setModalOpen(dom.convertModal, false);
  });
  dom.rescheduleSave?.addEventListener("click", saveReschedule);
  dom.rescheduleCancel?.addEventListener("click", () => {
    state.rescheduling = null;
    setModalOpen(dom.rescheduleModal, false);
  });

  document.addEventListener("pointerdown", (event) => {
    if (dom.taskRowMenu && !dom.taskRowMenu.hidden && !dom.taskRowMenu.contains(event.target)
      && !event.target.closest?.(".home-task-more")) {
      closeTaskMenu();
    }
    if (openPickerKey && !event.target.closest?.(".topics-select-control")) closeAllPickers();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (openPickerKey) {
      closeAllPickers("", { restoreFocus: true });
      return;
    }
    if (dom.taskRowMenu && !dom.taskRowMenu.hidden) {
      closeTaskMenu();
      return;
    }
    if (dom.taskModal && !dom.taskModal.hidden) setModalOpen(dom.taskModal, false);
    else if (dom.taskListModal && !dom.taskListModal.hidden) setModalOpen(dom.taskListModal, false);
    else if (dom.inspirationModal && !dom.inspirationModal.hidden) setModalOpen(dom.inspirationModal, false);
    else if (dom.convertModal && !dom.convertModal.hidden) setModalOpen(dom.convertModal, false);
    else if (dom.rescheduleModal && !dom.rescheduleModal.hidden) setModalOpen(dom.rescheduleModal, false);
  });
  window.addEventListener("resize", positionTaskMenu);
  window.addEventListener("resize", resizeTaskNote);
  window.addEventListener("resize", scheduleInspirationLayout);
  if (window.ResizeObserver) {
    const inspirationLayoutObserver = new window.ResizeObserver(scheduleInspirationLayout);
    [dom.taskPanel, dom.inspirationPanel, dom.inspirationInput, dom.inspirationMessage].forEach((element) => {
      if (element) inspirationLayoutObserver.observe(element);
    });
  }
  window.addEventListener("scroll", positionTaskMenu, true);
  window.addEventListener("focus", () => {
    const next = todayIso();
    if (next !== state.date) {
      state.date = next;
      state.weekStart = weekStartOf(new Date());
    }
    if (state.accountId && !root.hidden) loadHome({ silent: true });
  });
  window.addEventListener("workspace-module-change", (event) => {
    if (event?.detail?.module !== "today") {
      closeTaskMenu();
      closeAllPickers();
      return;
    }
    if (state.accountId) loadHome({ silent: state.loaded });
  });

  // app.js reports every account switch so the home page always follows the active account.
  window.homeModule = {
    onAccountChange,
    refresh: () => loadHome({ silent: true }),
    state,
    render,
    helpers: { todayIso, weekStartOf, relativeDayLabel, taskActionLabel, taskMetaText, paginate, formatStamp },
    actions: {
      loadHome,
      openTaskEditor,
      saveTask,
      toggleTask,
      deleteTask,
      openTaskListModal,
      loadTaskList,
      openReschedule,
      saveReschedule,
      saveInspiration,
      openInspirationModal,
      openConvertModal,
      confirmConvert,
      openTopics,
      openTopicsWeek,
      openScripts,
      startNewScript,
      handleStatClick,
    },
    pickers,
    dom,
  };

  render();
})();
