/* 监控（monitor）：关注的博主、共享采集的作品动态，以及今日 AI 选题建议。
   Visibility is owned by workspace-navigation.js; this file owns data, rendering and edits.
   共享采集是服务端行为：同一博主只采集一份，这里只按当前账号展示关注范围。 */
(() => {
  const root = document.getElementById("monitorContent");
  if (!root) return;

  const INTERVAL_LABELS = { 60: "每小时", 120: "每 2 小时", 360: "每 6 小时", 1440: "每天一次" };
  const DATE_OPTIONS = [
    ["today", "今天"],
    ["yesterday", "昨天"],
    ["7d", "最近 7 天"],
    ["15d", "最近 15 天"],
    ["30d", "最近 30 天"],
    ["all", "全部日期"],
  ];
  // 空列表文案跟着筛选条件走，否则会让人以为采集失败了。
  const DATE_EMPTY_HINTS = {
    today: "今天还没有新作品。",
    yesterday: "昨天没有采集到作品。",
    "7d": "最近 7 天没有作品。",
    "15d": "最近 15 天没有作品。",
    "30d": "最近 30 天没有作品。",
  };
  // 博主行里的条数跟着作品动态的日期筛选走，这里给出对应的短标签。
  const DATE_COUNT_LABELS = {
    today: "今日",
    yesterday: "昨日",
    "7d": "近 7 天",
    "15d": "近 15 天",
    "30d": "近 30 天",
    all: "全部",
  };
  const WEEK_OPTIONS = [["current", "本周选题"], ["next", "下周选题"]];
  const CATEGORY_OPTIONS = [["highlight", "重点"], ["daily", "日常"], ["series", "系列"], ["test", "测试"]];
  const FORMAT_OPTIONS = [["video", "视频"], ["article", "图文"]];
  const WORK_FILTERS = [
    { key: "all", label: "全部" },
    { key: "new", label: "新发现" },
    { key: "saved", label: "已收藏" },
  ];
  const WORK_PAGE_SIZE = 20;
  const BLOGGER_PAGE_SIZE = 20;
  const BLOGGER_SCROLL_THRESHOLD = 100;
  const POLL_INTERVAL_MS = 5000;
  const pendingBloggerRetries = new Set();
  const BLOCKING_COLLECTION_CODES = new Set([
    "unauthorized", "session_revoked", "account_disabled", "permission_denied", "needs_relogin",
    "insufficient_points", "insufficient_balance", "subscription_required", "subscription_expired", "platform_mode_required",
  ]);
  const CATEGORY_LABELS = { highlight: "重点", daily: "日常", series: "系列", test: "测试" };

  const dom = {
    stats: document.getElementById("monitorStats"),
    addBlogger: document.getElementById("monitorAddBloggerButton"),
    settings: document.getElementById("monitorSettingsButton"),
    aiAutoTag: document.getElementById("monitorAiAutoTag"),
    aiPendingTag: document.getElementById("monitorAiPendingTag"),
    aiMeta: document.getElementById("monitorAiMeta"),
    aiContext: document.getElementById("monitorAiContext"),
    analysisModal: document.getElementById("monitorAnalysisModal"),
    recommendations: document.getElementById("monitorRecommendations"),
    aiMessage: document.getElementById("monitorAiMessage"),
    updateButton: document.getElementById("monitorUpdateButton"),
    updateLabel: document.getElementById("monitorUpdateLabel"),
    bloggerSearch: document.getElementById("monitorBloggerSearch"),
    bloggerTabs: document.getElementById("monitorBloggerTabs"),
    bloggerList: document.getElementById("monitorBloggerList"),
    bloggerMessage: document.getElementById("monitorBloggerMessage"),
    feedTabs: document.getElementById("monitorFeedTabs"),
    dateSelect: document.getElementById("monitorDateSelect"),
    syncButton: document.getElementById("monitorSyncButton"),
    syncLabel: document.getElementById("monitorSyncLabel"),
    workList: document.getElementById("monitorWorkList"),
    workMessage: document.getElementById("monitorWorkMessage"),
    workSummary: document.getElementById("monitorWorkSummary"),
    workPager: document.getElementById("monitorWorkPager"),
    addModal: document.getElementById("monitorAddBloggerModal"),
    addShare: document.getElementById("monitorAddShareInput"),
    addNote: document.getElementById("monitorAddNoteInput"),
    addInterval: document.getElementById("monitorAddIntervalSelect"),
    addPriority: document.getElementById("monitorAddPriorityInput"),
    addError: document.getElementById("monitorAddError"),
    addCancel: document.getElementById("monitorAddCancelButton"),
    addConfirm: document.getElementById("monitorAddConfirmButton"),
    settingsModal: document.getElementById("monitorSettingsModal"),
    settingsCollect: document.getElementById("monitorSettingsCollectInput"),
    settingsInterval: document.getElementById("monitorSettingsIntervalSelect"),
    settingsAi: document.getElementById("monitorSettingsAiInput"),
    settingsAiTime: document.getElementById("monitorSettingsAiTimeInput"),
    usageLine: document.getElementById("monitorUsageLine"),
    usageNote: document.getElementById("monitorUsageNote"),
    usageBilling: document.getElementById("monitorUsageBilling"),
    keyState: document.getElementById("monitorKeyState"),
    settingsError: document.getElementById("monitorSettingsError"),
    settingsCancel: document.getElementById("monitorSettingsCancelButton"),
    settingsSave: document.getElementById("monitorSettingsSaveButton"),
    bloggerModal: document.getElementById("monitorBloggerModal"),
    bloggerSummary: document.getElementById("monitorBloggerSummary"),
    bloggerNote: document.getElementById("monitorBloggerNoteInput"),
    bloggerInterval: document.getElementById("monitorBloggerIntervalSelect"),
    bloggerPriority: document.getElementById("monitorBloggerPriorityInput"),
    bloggerEnabled: document.getElementById("monitorBloggerEnabledInput"),
    bloggerError: document.getElementById("monitorBloggerError"),
    bloggerUnfollow: document.getElementById("monitorBloggerUnfollowButton"),
    bloggerCancel: document.getElementById("monitorBloggerCancelButton"),
    bloggerSave: document.getElementById("monitorBloggerSaveButton"),
    workModal: document.getElementById("monitorWorkModal"),
    workTitle: document.getElementById("monitorWorkTitle"),
    workBody: document.getElementById("monitorWorkBody"),
    workClose: document.getElementById("monitorWorkCloseButton"),
    workTopic: document.getElementById("monitorWorkTopicButton"),
    workBreakdown: document.getElementById("monitorWorkBreakdownButton"),
    topicModal: document.getElementById("monitorTopicModal"),
    topicTitle: document.getElementById("monitorTopicTitleInput"),
    topicWeek: document.getElementById("monitorTopicWeekSelect"),
    topicCategory: document.getElementById("monitorTopicCategorySelect"),
    topicFormat: document.getElementById("monitorTopicFormatSelect"),
    topicOutline: document.getElementById("monitorTopicOutlineInput"),
    topicError: document.getElementById("monitorTopicError"),
    topicCancel: document.getElementById("monitorTopicCancelButton"),
    topicConfirm: document.getElementById("monitorTopicConfirmButton"),
  };

  const state = {
    accountId: "",
    loaded: false,
    busy: false,
    requestVersion: 0,
    accountRevision: 0,
    overview: null,
    follows: null,
    works: null,
    bloggerFilter: "all",
    bloggerKeyword: "",
    bloggerPage: 1,
    bloggerKey: "",
    bloggerVersion: 0,
    bloggerLoading: false,
    bloggerError: "",
    bloggerRetryAppend: false,
    bloggerHasMore: false,
    workFilter: "all",
    workDate: "all",
    workPage: 1,
    activeBloggerId: "",
    intervalOptions: [60, 120, 360, 1440],
    editingBloggerId: "",
    activeWork: null,
    pendingTopic: null,
    pollTimer: 0,
    recommendationToastMessage: "",
    recommendationToastStartedAt: "",
    recommendationToastGeneratedAt: "",
  };

  // ------------------------------------------------------------ helpers

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function svgNode(tag, attributes) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attributes || {}).forEach((key) => {
      // SVG 元素的 className 是只读对象，样式类要通过 classList 加。
      if (key === "class") node.classList.add(String(attributes[key]));
      else node.setAttribute(key, String(attributes[key]));
    });
    return node;
  }

  // 快照节点在 viewBox 里的坐标；没有变化时贴着中线，避免一条平线看起来像出错。
  function trendNodes(values, width, height, pad) {
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min;
    const stepX = (width - pad * 2) / (values.length - 1);
    return values.map((value, index) => ({
      value,
      index,
      // 相对上一个采集点的增长量；第一个点没有上一个，记成 null。
      delta: index > 0 ? value - values[index - 1] : null,
      x: pad + index * stepX,
      y: pad + (span > 0 ? 1 - (value - min) / span : 0.5) * (height - pad * 2),
    }));
  }

  // 悬停气泡里的增长量：第一个点说「起点」，其余标出相对上一个采集点的增减。
  function trendDeltaText(node) {
    if (node.delta === null) return "起点";
    return `较上次 ${node.delta >= 0 ? "+" : ""}${formatCount(node.delta)}`;
  }

  // 点太密时圆点会连成一条粗线，这种情况只画折线，悬停仍然按节点给出数值。
  const TREND_DOT_MIN_GAP = 8;

  function likeTrendPoints(trend) {
    if (!Array.isArray(trend)) return [];
    return trend.filter((value) => typeof value === "number" && Number.isFinite(value));
  }

  // 点赞曲线：折线 + 可悬停的快照节点。悬停到某个节点时在它旁边弹出该点的点赞数，移开即消失。
  // 命中区是按节点横向切片的整列透明矩形，鼠标在曲线上任意横向位置都能取到最近的节点。
  function buildTrendChart({
    values,
    width,
    height,
    pad,
    className,
    shellTag,
    shellClass,
    strokeWidth,
    stretch,
    ariaLabel,
    tipLabel,
  }) {
    const nodes = trendNodes(values, width, height, pad);
    const svg = svgNode("svg", {
      viewBox: `0 0 ${width} ${height}`,
      class: className,
      role: "img",
      "aria-label": ariaLabel,
    });
    // 弹窗里的曲线要横向铺满卡片，等比缩放会把折线压扁。
    if (stretch) svg.setAttribute("preserveAspectRatio", "none");
    svg.append(svgNode("polyline", {
      points: nodes.map((node) => `${node.x.toFixed(2)},${node.y.toFixed(2)}`).join(" "),
      fill: "none",
      "stroke-width": String(strokeWidth),
      "vector-effect": "non-scaling-stroke",
    }));

    const gap = nodes.length > 1 ? (width - pad * 2) / (nodes.length - 1) : width;
    const showDots = gap >= TREND_DOT_MIN_GAP;
    const dots = showDots
      ? nodes.map((node) => {
          // 零长度的圆头线段画出来就是圆点，且跟着 non-scaling-stroke 保持固定像素直径。
          const dot = svgNode("path", {
            d: `M ${node.x.toFixed(2)},${node.y.toFixed(2)} l 0.01 0`,
            class: "monitor-trend-dot",
            "vector-effect": "non-scaling-stroke",
          });
          svg.append(dot);
          return dot;
        })
      : [];

    const shell = el(shellTag || "div", shellClass || "monitor-trend-shell");
    // 统一的悬停类：鼠标移到曲线上时整条线加深，两种曲线共用一套样式。
    shell.classList.add("monitor-trend-shell");
    // 用 span 而不是 div：行内曲线外面套的是 span，div 嵌在里面不是合法结构。
    // position: absolute 会让它按块级盒子参与定位，不影响气泡外观。
    const tip = el("span", "monitor-trend-tip");
    tip.hidden = true;
    let active = -1;

    const hide = () => {
      if (active >= 0 && dots[active]) dots[active].classList.remove("is-active");
      active = -1;
      tip.hidden = true;
    };
    const show = (node) => {
      if (active >= 0 && dots[active]) dots[active].classList.remove("is-active");
      active = node.index;
      if (dots[active]) dots[active].classList.add("is-active");
      tip.textContent = tipLabel(node);
      const ratioX = node.x / width;
      const ratioY = node.y / height;
      // 靠边时把一个边贴住节点，靠上时改到节点下方，避免气泡被卡片裁掉。
      tip.className = "monitor-trend-tip"
        + (ratioY < 0.35 ? " is-below" : "")
        + (ratioX < 0.12 ? " is-edge-left" : "")
        + (ratioX > 0.88 ? " is-edge-right" : "");
      tip.style.left = `${(ratioX * 100).toFixed(2)}%`;
      tip.style.top = `${(ratioY * 100).toFixed(2)}%`;
      tip.hidden = false;
    };

    nodes.forEach((node) => {
      const half = gap / 2;
      const left = Math.max(0, node.x - half);
      const right = Math.min(width, node.x + half);
      const hit = svgNode("rect", {
        x: left.toFixed(2),
        y: 0,
        width: Math.max(1, right - left).toFixed(2),
        height,
        class: "monitor-trend-hit",
      });
      hit.addEventListener("pointerenter", () => show(node));
      svg.append(hit);
    });
    svg.addEventListener("pointerleave", hide);

    shell.append(svg);
    shell.append(tip);
    return shell;
  }

  // 作品动态行里的点赞迷你曲线：至少两个采集点才画，行内不带坐标轴和时间。
  function renderLikeSpark(trend) {
    const points = likeTrendPoints(trend);
    if (points.length < 2) return null;
    return buildTrendChart({
      values: points,
      width: 132,
      height: 40,
      pad: 3,
      className: "monitor-work-spark",
      shellTag: "span",
      shellClass: "monitor-work-spark-shell",
      strokeWidth: 1.6,
      stretch: false,
      ariaLabel: `点赞增长曲线：${formatCount(points[0])} 到 ${formatCount(points[points.length - 1])}`,
      tipLabel: (node) => `点赞 ${formatCount(node.value)} · ${trendDeltaText(node)}`,
    });
  }

  function setMessage(node, message, isError = false) {
    if (!node) return;
    node.hidden = !message;
    node.textContent = message || "";
    node.classList.toggle("is-error", Boolean(message) && isError);
  }

  /* 凭证被平台拒绝（errorCode=needs_relogin）时的统一出口：给一个能直接点开的
     「登录已失效，请重新登录」，其余错误照旧显示后台文案。 */
  const RELOGIN_TEXT = "登录已失效，请重新登录";

  function isRelogin(code) {
    return String(code || "") === "needs_relogin";
  }

  function reloginNode(className) {
    // 出现这个提示说明平台已拒绝本地凭证，后台也清掉了会话：把身份区同步成未登录。
    if (window.accountModule && typeof window.accountModule.sessionInvalid === "function") {
      window.accountModule.sessionInvalid();
    }
    const node = el("button", className, RELOGIN_TEXT);
    node.type = "button";
    node.classList.add("monitor-relogin");
    node.addEventListener("click", (event) => {
      if (event && typeof event.stopPropagation === "function") event.stopPropagation();
      if (window.accountModule && typeof window.accountModule.openLogin === "function") window.accountModule.openLogin();
    });
    return node;
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

  function accountQuery(extra) {
    const params = new URLSearchParams({ accountId: state.accountId });
    Object.entries(extra || {}).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
    });
    return params.toString();
  }

  function isSameAccount(accountId) {
    return state.accountId === accountId;
  }

  function intervalLabel(minutes) {
    return INTERVAL_LABELS[Number(minutes)] || `每 ${minutes} 分钟`;
  }

  function formatCount(value) {
    if (value === null || value === undefined || value === "") return "—";
    const number = Number(value);
    if (!Number.isFinite(number)) return "—";
    return number.toLocaleString("zh-CN");
  }

  // ------------------------------------------------------------ pickers
  // 项目约定：页面不使用原生 select。这里复用选题模块的浮层样式，
  // 值仍放在隐藏 input 里，读写方式和其他模块一致。

  const pickers = {};
  const pickerOrder = [];
  let openPicker = "";

  function intervalOptions() {
    const source = Array.isArray(state.intervalOptions) && state.intervalOptions.length ? state.intervalOptions : [60, 120, 360, 1440];
    return source.map((minutes) => [String(minutes), intervalLabel(minutes)]);
  }

  function createPicker(key, config) {
    const input = document.getElementById(config.input);
    const host = document.querySelector(`[data-monitor-picker="${key}"] .topics-select-control`);
    if (!input || !host) return null;
    const control = el("button", "am-input topics-select-button");
    control.type = "button";
    control.id = `${config.input}Button`;
    control.setAttribute("aria-haspopup", "menu");
    control.setAttribute("aria-expanded", "false");
    control.setAttribute("aria-label", config.label);
    const value = el("span", "topics-select-value");
    value.id = `${config.input}Value`;
    const menu = el("div", "topics-select-menu");
    menu.id = `${config.input}Menu`;
    menu.setAttribute("role", "menu");
    menu.setAttribute("aria-label", config.label);
    menu.hidden = true;
    control.append(value);
    host.append(control, menu);

    const picker = {
      key,
      input,
      control,
      menu,
      options: () => config.options(),
      labelFor: (option) => (config.options().find(([candidate]) => candidate === option) || [])[1] || option,
      set(next, options) {
        const allowed = config.options().map(([candidate]) => candidate);
        const resolved = allowed.includes(String(next)) ? String(next) : allowed[0];
        input.value = resolved;
        value.textContent = picker.labelFor(resolved);
        if (!options || !options.silent) {
          picker.close();
          if (config.onChange) config.onChange(resolved);
        }
        return resolved;
      },
      render() {
        menu.replaceChildren(...config.options().map(([option, label]) => {
          const selected = input.value === option;
          const button = el("button", selected ? "is-current" : "", (selected && key !== "workDate" ? "✓ " : "") + label);
          button.type = "button";
          button.setAttribute("role", "menuitemradio");
          button.setAttribute("aria-checked", String(selected));
          button.addEventListener("click", () => {
            picker.set(option);
            control.focus?.({ preventScroll: true });
          });
          return button;
        }));
      },
      open() {
        closePickers(key);
        openPicker = key;
        picker.render();
        menu.hidden = false;
        control.setAttribute("aria-expanded", "true");
      },
      close() {
        menu.hidden = true;
        control.setAttribute("aria-expanded", "false");
        if (openPicker === key) openPicker = "";
      },
    };
    control.addEventListener("click", () => {
      if (menu.hidden) picker.open();
      else picker.close();
    });
    menu.addEventListener("keydown", (event) => {
      if (event.key === "Escape") picker.close();
    });
    pickers[key] = picker;
    pickerOrder.push(key);
    picker.set(input.value, { silent: true });
    return picker;
  }

  function closePickers(except) {
    pickerOrder.forEach((key) => {
      if (key !== except) pickers[key]?.close();
    });
  }

  function setPickerValue(key, value) {
    pickers[key]?.set(value, { silent: true });
  }

  function pickerValue(key) {
    return pickers[key]?.input.value || "";
  }

  let detailRequest = 0;
  let analysisReturnFocus = null;
  document.getElementById("monitorAnalysisModal")?.addEventListener("keydown", event => {
    if (event.key !== "Tab") return;
    const modal = document.getElementById("monitorAnalysisModal");
    const nodes = [...(modal.querySelectorAll?.('button:not([disabled]), a[href], input:not([disabled]), [tabindex="0"]') || [])].filter(node => !node.hidden);
    if (!nodes.length) return;
    const first = nodes[0], last = nodes[nodes.length - 1];
    if (event.shiftKey && (document.activeElement === first || !modal.contains?.(document.activeElement))) { event.preventDefault(); last.focus?.(); }
    else if (!event.shiftKey && (document.activeElement === last || !modal.contains?.(document.activeElement))) { event.preventDefault(); first.focus?.(); }
  });

  function closeModals() {
    detailRequest += 1;
    const returnFocus = analysisReturnFocus;
    analysisReturnFocus = null;
    returnFocus?.focus?.();
    [dom.addModal, dom.settingsModal, dom.bloggerModal, dom.workModal, dom.topicModal, dom.analysisModal].forEach((modal) => {
      if (modal) modal.hidden = true;
    });
    closePickers();
  }

  function setBusy(button, label, busy, busyText) {
    if (!button) return;
    button.disabled = Boolean(busy);
    if (label) label.textContent = busy ? busyText : label.dataset.idleLabel || label.textContent;
  }

  // ------------------------------------------------------------ loading

  async function loadAll({ silent = false } = {}) {
    if (!state.accountId) return;
    const accountId = state.accountId;
    const version = ++state.requestVersion;
    try {
      const [overview, , works] = await Promise.all([
        api(`/api/monitor/overview?${accountQuery()}`),
        loadBloggers(),
        api(`/api/monitor/works?${accountQuery({ bloggerId: state.activeBloggerId, filter: state.workFilter, date: state.workDate, page: state.workPage })}`),
      ]);
      if (version !== state.requestVersion || !isSameAccount(accountId)) return;
      state.overview = overview;
      settleRecommendationToast();
      state.works = works;
      state.intervalOptions = Array.isArray(overview?.settings?.intervalMinutesOptions) ? overview.settings.intervalMinutesOptions : state.intervalOptions;
      state.loaded = true;
      state.busy = false;
      render();
    } catch (error) {
      if (version !== state.requestVersion || !isSameAccount(accountId)) return;
      state.busy = false;
      setMessage(dom.workMessage, responseMessage(error, "监控数据读取失败。"), true);
      schedulePoll();
    }
    schedulePoll();
  }

  async function refreshOverview() {
    if (!state.accountId) return;
    const accountId = state.accountId;
    const version = state.requestVersion;
    try {
      const overview = await api(`/api/monitor/overview?${accountQuery()}`);
      if (version !== state.requestVersion || !isSameAccount(accountId)) return;
      state.overview = overview;
      settleRecommendationToast();
      renderStats();
      renderRecommendations();
    } catch (_error) {
      /* 轮询失败不打断页面，下一轮再试 */
    }
  }

  // ------------------------------------------------------------ render

  function render() {
    renderStats();
    renderRecommendations();
    renderBloggers();
    renderWorks();
  }

  function renderStats() {
    const overview = state.overview;
    if (!dom.stats) return;
    dom.stats.replaceChildren();
    const entries = [
      { label: "监控博主", value: overview ? String(overview.bloggerCount) : "—" },
      { label: "今日采集", value: overview ? String(overview.todayCollected) : "—" },
      { label: "新发现作品", value: overview ? String(overview.newToday) : "—" },
    ];
    entries.forEach((entry) => {
      const cell = el("div", "monitor-stat");
      cell.append(el("span", "monitor-stat-label", entry.label));
      cell.append(el("strong", "monitor-stat-value", entry.value));
      dom.stats.append(cell);
    });
    const health = overview?.health || { key: "empty", label: "读取中…", tone: "muted" };
    const cell = el("div", "monitor-stat monitor-stat-health");
    const pill = el("span", `monitor-health is-${health.tone || "muted"}`);
    pill.append(el("i", "monitor-health-dot"));
    pill.append(document.createTextNode(health.label || ""));
    cell.append(pill);
    const usage = overview?.usage;
    if (usage) {
      cell.append(el("span", "monitor-stat-note", `今日调用 ${usage.todayRequests} 次`));
    }
    dom.stats.append(cell);
  }

  function recommendationInputs() {
    return state.overview?.recommendation || null;
  }

  function renderRecommendations() {
    const recommendation = recommendationInputs();
    const settings = state.overview?.settings || {};
    const running = recommendation?.status === "running";
    if (dom.updateButton) dom.updateButton.disabled = running;
    if (dom.updateLabel) dom.updateLabel.textContent = running ? "生成中…" : "更新建议";
    dom.updateButton?.classList.toggle("is-busy", Boolean(running));
    if (dom.aiAutoTag) {
      dom.aiAutoTag.textContent = settings.aiEnabled === false
        ? "自动生成已关闭"
        : `每天 ${settings.aiDailyTime || "10:30"} 自动生成`;
    }
    const meta = recommendation?.generatedText
      ? `${recommendation.generatedText} 更新 · 参考最近 30 天复盘`
      : "还没有生成建议";
    if (dom.aiMeta) dom.aiMeta.textContent = meta;
    const evidenceButton = document.getElementById("monitorAiEvidenceButton");
    if (evidenceButton) evidenceButton.disabled = !recommendation?.generatedAt;
    if (dom.aiContext) {
      const inputs = recommendation?.inputs || {};
      const parts = [];
      if (inputs.monitorWorkCount !== undefined) parts.push(`已分析 ${inputs.monitorWorkCount} 条监控作品`);
      if (inputs.reviewWorkCount !== undefined) parts.push(`近 30 天复盘 ${inputs.reviewWorkCount} 条`);
      if (inputs.hasPositioning === false) parts.push("商业定位待完善");
      if (inputs.hasAudience === false) parts.push("目标人群待完善");
      dom.aiContext.textContent = parts.join(" · ");
    }
    const candidates = Number(state.overview?.newToday || 0);
    if (dom.aiPendingTag) {
      const pendingAfter = recommendation?.generatedAt ? candidates : 0;
      dom.aiPendingTag.hidden = pendingAfter <= 0;
      dom.aiPendingTag.textContent = pendingAfter > 0 ? `新增 ${pendingAfter} 条待分析` : "";
    }

    if (!dom.recommendations) return;
    dom.recommendations.replaceChildren();
    const items = Array.isArray(recommendation?.items) ? recommendation.items : [];
    const dismissedButton = document.getElementById("monitorDismissedRecommendationsButton");
    if (dismissedButton) dismissedButton.hidden = !(recommendation?.dismissedItems || []).length;
    if (recommendation?.status === "running") {
      setMessage(dom.aiMessage, "正在结合监控作品和账号数据生成建议…");
    } else if (["pending", "unconfirmed"].includes(recommendation?.status)) {
      setMessage(dom.aiMessage, recommendation.error || "上次生成结果未确认，旧建议已保留。");
    } else if (recommendation?.status === "failed" && isRelogin(recommendation.errorCode)) {
      // 平台拒绝凭证：给一个可直接点开的重新登录入口，不显示后台错误原文。
      if (dom.aiMessage) {
        dom.aiMessage.replaceChildren(reloginNode("monitor-relogin-line"));
        dom.aiMessage.hidden = false;
        dom.aiMessage.classList.add("is-error");
      }
    } else if (recommendation?.status === "failed") {
      setMessage(dom.aiMessage, recommendation.error || "生成失败，已有建议保留。", true);
    } else if (recommendation?.status === "skipped") {
      setMessage(dom.aiMessage, recommendation.error || "这次没有需要分析的新内容。");
    } else {
      setMessage(dom.aiMessage, "");
    }
    if (!items.length) {
      const empty = el("p", "monitor-empty", recommendation?.status === "running" ? "" : recommendation?.message || (recommendation?.generatedAt ? "本次没有筛选到适合推荐的作品。" : "还没有建议。等新作品进来，或点「更新建议」立即生成一次。"));
      if (empty.textContent) dom.recommendations.append(empty);
      return;
    }
    items.slice(0, 3).forEach((item, index) => dom.recommendations.append(renderRecommendation(item, index)));
  }

  function renderRecommendation(item, index) {
    const work = item.sourceWork || {};
    const card = el("article", "monitor-recommendation");
    const head = el("div", "monitor-recommendation-head");
    head.append(el("span", `monitor-tag is-${item.priority || "worth"}`, ({ primary: "优先推荐", worth: "值得尝试", backup: "备选方向" }[item.priority] || "值得尝试")));
    head.append(el("span", "monitor-tag", "原标题"));
    head.append(el("span", "monitor-rank", String(index + 1).padStart(2, "0")));
    card.append(head, el("h4", "monitor-recommendation-title", work.title || item.title || ""));
    const metadata = el("div", "recommendation-source-metadata");
    const source = el("p", "recommendation-source-line");
    source.append(el("span", "", work.authorName || work.bloggerName || "作者未知"), el("span", "", "·"), el("time", "", work.publishedText || (work.publishedAt ? analysisDate(work.publishedAt) : "发布时间未知")));
    const metrics = el("p", "recommendation-metrics-line");
    [["点赞", "likes"], ["评论", "comments"]].forEach(([label, key]) => {
      const metric = el("span", "", `${label} `);
      metric.append(el("b", "", work.metrics?.[key] == null ? "暂无数据" : formatCount(work.metrics[key])));
      metrics.append(metric);
    });
    metadata.append(source, metrics);
    card.append(metadata);
    const info = el("dl", "monitor-recommendation-info");
    [["推荐理由", item.reason], ["我的切入角度", item.angle]].forEach(([label, value]) => {
      const row = el("div", "monitor-recommendation-info-row");
      row.append(el("dt", "monitor-recommendation-info-label", label), el("dd", "monitor-recommendation-info-text", value || "暂未提供"));
      info.append(row);
    });
    card.append(info);
    const foot = el("footer", "monitor-recommendation-foot");
    const adopt = el("button", "am-primary-action monitor-compact-action", item.topicId ? "已加入选题" : "加入选题");
    adopt.type = "button";
    adopt.disabled = Boolean(item.topicId || item.dismissed);
    adopt.addEventListener("click", () => openTopicModalFromRecommendation(item));
    const breakdown = el("button", "am-secondary-action monitor-compact-action", "拆解视频");
    breakdown.type = "button";
    breakdown.disabled = work.kind === "image" || !safeWorkUrl(work.shareUrl) || !item.sourceWorkId;
    breakdown.title = work.kind === "image" ? "图文作品暂不支持视频拆解" : !safeWorkUrl(work.shareUrl) ? "暂无可用的视频链接" : "拆解原作品";
    breakdown.addEventListener("click", () => breakdownRecommendation(item));
    const detail = el("button", "monitor-text-button", "作品详情");
    detail.type = "button";
    detail.disabled = !item.sourceWorkId;
    detail.addEventListener("click", () => { analysisReturnFocus = detail; openWorkModal(item.sourceWorkId); });
    const evidence = el("button", "monitor-text-button", "推荐依据");
    evidence.type = "button";
    evidence.addEventListener("click", () => showRecommendationEvidence(item, evidence));
    foot.append(adopt, breakdown, detail, evidence);
    card.append(foot);
    return card;
  }

  document.getElementById("monitorDismissedRecommendationsButton")?.addEventListener("click", event => {
    analysisReturnFocus = event.currentTarget || event.target;
    const target = document.getElementById("monitorAnalysisBody");
    if (!target) return;
    target.replaceChildren();
    (state.overview?.recommendation?.dismissedItems || []).forEach(item => {
      const row = el("div", "recommendation-dismissed-row");
      row.append(el("p", "", item.sourceWork?.title || item.title || "原作品"));
      const restore = el("button", "monitor-text-button", "撤销暂不考虑");
      restore.type = "button";
      restore.addEventListener("click", async () => {
        const revision = state.accountRevision;
        restore.disabled = true;
        await restoreRecommendation(item.key);
        if (revision === state.accountRevision) closeModals();
      });
      row.append(restore);
      target.append(row);
    });
    document.getElementById("monitorAnalysisTitle").textContent = "历史暂不考虑";
    document.getElementById("monitorAnalysisModal").hidden = false;
    document.getElementById("monitorAnalysisCloseButton")?.focus?.();
  });

  function safeWorkUrl(value) {
    return /^https?:\/\/[^\s]+$/i.test(String(value || "")) ? String(value) : "";
  }

  async function breakdownRecommendation(item) {
    const revision = state.accountRevision;
    try {
      const work = await api(`/api/monitor/works/${encodeURIComponent(item.sourceWorkId)}?${accountQuery()}`);
      if (revision !== state.accountRevision) return;
      if (!safeWorkUrl(work.shareUrl)) { showToast("暂无可用的视频链接", "info"); return; }
      await startBreakdown(work);
    } catch (error) { if (revision === state.accountRevision) showToast(error.message, "error"); }
  }

  function showRecommendationEvidence(item, trigger) {
    analysisReturnFocus = trigger || document.activeElement;
    const references = item.references || [];
    const body = el("div", "monitor-evidence-body");
    if (item.evidence) {
      body.append(el("p", "monitor-evidence-label", "外部作品依据"));
      body.append(el("p", "", item.evidence));
    }
    if (references.length) {
      body.append(el("p", "monitor-evidence-label", "参考作品"));
      references.forEach((reference) => {
        const full = String(reference.title || reference.id || "");
        const node = el("a", "monitor-evidence-link", full.length > 44 ? `${full.slice(0, 44)}…` : full);
        node.href = safeWorkUrl(reference.shareUrl);
        node.target = "_blank";
        node.rel = "noreferrer noopener";
        node.title = full;
        body.append(node);
      });
    } else {
      body.append(el("p", "monitor-hint", "这次没有引用到具体作品。"));
    }
    if (!item.reviewEvidence && !(item.reviewReferences || []).length) body.append(el("p", "monitor-hint", "本账号复盘依据：暂无可用记录，不据此判断历史效果。"));
    if (item.reviewEvidence) {
      body.append(el("p", "monitor-evidence-label", "本账号复盘依据"));
      body.append(el("p", "", item.reviewEvidence));
    }
    (item.reviewReferences || []).forEach((ref) => {
      const entry = el("details", "radar-review-reference");
      const title = String(ref.title || ref.id || "");
      const summary = el("summary", "radar-evidence-link", title.length > 44 ? `${title.slice(0, 44)}…` : title);
      summary.title = title;
      entry.append(summary);
      entry.append(el("p", "", title));
      entry.append(el("p", "monitor-hint", `作品 ID：${ref.id} · 发布于 ${analysisDate(ref.publishedAt)}`));
      entry.append(el("p", "", reviewMetrics(ref.metrics)));
      if (ref.scriptOpening) entry.append(el("p", "", `关联脚本开头：${ref.scriptOpening}${ref.scriptOpeningTruncated ? "（仅前400字）" : ""}`));
      if (ref.note) entry.append(el("p", "", `复盘备注：${ref.note}`));
      entry.append(el("p", "monitor-hint", `生成时指标快照 · 采集于 ${analysisDate(ref.collectedAt)}`));
      body.append(entry);
    });

    const work = item.sourceWork || {};
    body.append(el("p", "monitor-evidence-label", "生成时原作品快照"));
    body.append(el("p", "", `${work.title || item.title} · ${work.authorName || work.bloggerName || "作者未知"} · ${work.publishedText || analysisDate(work.publishedAt)}`));
    body.append(el("p", "", reviewMetrics(work.metrics)));
    body.append(el("p", "", `指标采集于 ${analysisDate(work.statsUpdatedAt)}`));
    body.append(el("p", "monitor-evidence-label", "账号匹配与切入角度"));
    body.append(el("p", "", `${item.reason || "暂无数据"}\n${item.angle || "暂无数据"}`));
    const analysis = state.overview?.recommendation?.analysis || {};
    body.append(el("p", "monitor-evidence-label", "判断边界与数据缺口"));
    body.append(el("p", "", "仅根据标题与可用数据判断主题，未分析视频正文；互动数据不证明标题本身的效果。"));
    body.append(el("p", "", (analysis.gaps || []).join("；") || "未记录额外数据缺口"));
    const action = el("button", "monitor-text-button", item.dismissed ? "撤销暂不考虑" : "暂不考虑");
    action.type = "button";
    action.addEventListener("click", async () => {
      const revision = state.accountRevision;
      action.disabled = true;
      await (item.dismissed ? restoreRecommendation(item.key) : dismissRecommendation(item.key));
      if (revision === state.accountRevision) closeModals();
    });
    body.append(action);
    const target = document.getElementById("monitorAnalysisBody");
    if (!target) return;
    target.replaceChildren(body);
    const title = document.getElementById("monitorAnalysisTitle");
    if (title) title.textContent = "推荐依据";
    document.getElementById("monitorAnalysisModal").hidden = false;
    document.getElementById("monitorAnalysisCloseButton")?.focus?.();
  }

  function analysisDate(value) {
    if (!value) return "未知";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
  }

  function reviewMetrics(metrics = {}) {
    const fields = { views: "播放", likes: "点赞", comments: "评论", shares: "分享", saves: "收藏", completionRate: "完播率", bounceRate2s: "2秒跳出率", fansGained: "吸粉量", skipRate: "划走率", captionExpandRate: "文案展开率" };
    const rates = new Set(["completionRate", "bounceRate2s", "skipRate", "captionExpandRate"]);
    return Object.entries(fields).map(([key, label]) => `${label} ${metrics?.[key] == null ? "缺失" : `${metrics[key]}${rates.has(key) ? "%" : ""}`}`).join(" · ");
  }

  function showEvidence(event) {
    analysisReturnFocus = event?.currentTarget || event?.target || document.activeElement;
    const title = document.getElementById("monitorAnalysisTitle");
    if (title) title.textContent = "分析依据";
    const recommendation = recommendationInputs() || {};
    const items = recommendation.items || [];
    if (!recommendation.generatedAt) {
      showToast("还没有生成建议", "info");
      return;
    }
    const lines = [];
    lines.push(`生成时间：${recommendation.generatedText || recommendation.generatedAt}`);
    if (recommendation.window?.note) lines.push(`分析范围：${recommendation.window.note}`);
    const analysis = recommendation.analysis;
    if (analysis) {
      const review = analysis.review || {};
      lines.push(`账号复盘：${analysisDate(review.from)} 至 ${analysisDate(review.to)}（北京时间）\n共 ${review.total || 0} 条，实际提交 ${review.submitted || 0} 条`);
      if (review.selectionRule) lines.push(review.selectionRule);
      if (analysis.gaps?.length) lines.push(`数据缺口：\n${analysis.gaps.join("\n")}`);
    } else {
      lines.push("历史建议未记录分析快照，更新建议后可查看。");
    }
    items.forEach((item, index) => {
      const refs = (item.references || []).map((ref) => ref.title || ref.id).filter(Boolean);
      lines.push(`${index + 1}. ${item.title}${refs.length ? `\n   参考：${refs.join("；")}` : ""}`);
      if (item.reviewEvidence) lines.push(`   本账号复盘：${item.reviewEvidence}`);
      (item.reviewReferences || []).forEach(ref => lines.push(`   复盘作品：${ref.title || ref.id}（${ref.id}）\n   ${reviewMetrics(ref.metrics)}`));
    });
    const body = document.getElementById("monitorAnalysisBody");
    if (!body) return;
    body.replaceChildren();
    lines.forEach(line => body.append(el("p", "radar-analysis-paragraph", line)));
    if (dom.analysisModal) dom.analysisModal.hidden = false;
    document.getElementById("monitorAnalysisCloseButton")?.focus?.();
  }

  // 列表拥有独立请求版本，刷新与追加不会互相覆盖或混入其他筛选的数据。
  async function loadBloggers({ append = false } = {}) {
    if (!state.accountId) return;
    const key = JSON.stringify([state.accountId, state.bloggerKeyword, state.bloggerFilter, state.workDate]);
    const reset = key !== state.bloggerKey;
    if (append && (reset || state.bloggerLoading || !state.bloggerHasMore)) return;
    if (reset) {
      state.bloggerKey = key;
      state.bloggerPage = 1;
      state.follows = null;
      state.bloggerHasMore = false;
      if (dom.bloggerList) dom.bloggerList.scrollTop = 0;
    }
    const version = ++state.bloggerVersion;
    const accountId = state.accountId;
    const params = { keyword: state.bloggerKeyword, priority: state.bloggerFilter === "priority", date: state.workDate };
    const lastPage = append ? state.bloggerPage + 1 : state.bloggerPage;
    state.bloggerLoading = true;
    state.bloggerError = "";
    renderBloggerLoadStatus();
    if (reset) renderBloggers();
    try {
      let items = append ? [...(state.follows?.items || [])] : [];
      let data;
      for (let page = append ? lastPage : 1; page <= lastPage; page += 1) {
        data = await api(`/api/monitor/bloggers?${new URLSearchParams({ accountId, ...params, page, pageSize: BLOGGER_PAGE_SIZE })}`);
        if (version !== state.bloggerVersion || !isSameAccount(accountId)) return;
        items.push(...(data.items || []));
        if (page >= data.pageCount) break;
      }
      state.follows = { ...data, items: [...new Map(items.map(item => [item.id, item])).values()] };
      state.bloggerPage = data.page || 1;
      state.bloggerHasMore = state.bloggerPage < data.pageCount;
    } catch (error) {
      if (version !== state.bloggerVersion || !isSameAccount(accountId)) return;
      state.bloggerError = responseMessage(error, "博主列表加载失败，请重试。");
      state.bloggerRetryAppend = append;
    } finally {
      if (version === state.bloggerVersion && isSameAccount(accountId)) {
        state.bloggerLoading = false;
        renderBloggers();
      }
    }
  }

  function renderBloggerLoadStatus() {
    const status = document.getElementById("monitorBloggerLoadStatus");
    if (!status) return;
    status.replaceChildren();
    status.hidden = !state.bloggerLoading && !state.bloggerError;
    if (state.bloggerLoading) status.append(el("span", "", "正在加载…"));
    else if (state.bloggerError) {
      status.append(el("span", "", state.bloggerError));
      const retry = el("button", "monitor-text-button", "重试");
      retry.type = "button";
      retry.addEventListener("click", () => loadBloggers({ append: state.bloggerRetryAppend }));
      status.append(retry);
    }
  }

  function loadMoreBloggersOnScroll() {
    const list = dom.bloggerList;
    if (!list || root.hidden || !list.clientHeight || state.bloggerError) return;
    if (list.scrollHeight - list.clientHeight - list.scrollTop <= BLOGGER_SCROLL_THRESHOLD) {
      loadBloggers({ append: true });
    }
  }

  function renderBloggers() {
    const data = state.follows;
    if (dom.bloggerTabs) {
      dom.bloggerTabs.replaceChildren();
      [
        { key: "all", label: `全部 ${data ? data.total : "—"}` },
        { key: "priority", label: `重点关注 ${data ? data.priorityCount : "—"}` },
      ].forEach((tab) => {
        const button = el("button", `monitor-tab${state.bloggerFilter === tab.key ? " is-active" : ""}`, tab.label);
        button.type = "button";
        button.setAttribute("role", "tab");
        button.setAttribute("aria-selected", String(state.bloggerFilter === tab.key));
        button.addEventListener("click", () => {
          state.bloggerFilter = tab.key;
          state.bloggerPage = 1;
          loadAll({ silent: true });
        });
        dom.bloggerTabs.append(button);
      });
    }

    if (!dom.bloggerList) return;
    const scrollTop = dom.bloggerList.scrollTop || 0;
    dom.bloggerList.replaceChildren();
    const items = Array.isArray(data?.items) ? data.items : [];
    if (!items.length && !state.bloggerLoading && !state.bloggerError) {
      setMessage(dom.bloggerMessage, state.bloggerKeyword || state.bloggerFilter !== "all" ? "没有匹配的博主。" : "还没有关注博主，先添加一个。");
    } else {
      setMessage(dom.bloggerMessage, "");
    }
    items.forEach((blogger) => {
      const row = el("div", `monitor-blogger${state.activeBloggerId === blogger.id ? " is-active" : ""}`);
      const select = el("button", "monitor-blogger-main");
      select.type = "button";
      select.setAttribute("aria-pressed", String(state.activeBloggerId === blogger.id));
      select.addEventListener("click", () => selectBlogger(blogger.id));
      const avatar = el("span", "monitor-avatar", (blogger.name || "博").trim().slice(0, 1));
      // 走服务端缓存：抖音头像是 HEIC 加签临时链，直链在浏览器里显示不出来。
      const avatarSource = blogger.avatarSrc || blogger.avatarUrl || "";
      if (avatarSource) {
        const image = el("img", "monitor-avatar-image");
        image.src = avatarSource;
        image.alt = "";
        image.loading = "lazy";
        image.addEventListener("error", () => image.remove());
        avatar.append(image);
      }
      select.append(avatar);
      const copy = el("span", "monitor-blogger-copy");
      copy.append(el("strong", "monitor-blogger-name", blogger.name || blogger.nickname || "未命名博主"));
      // 条数按作品动态当前选的日期范围统计：切到「最近 7 天」，这里就是近 7 天的发布条数。
      const rangeCount = blogger.rangeWorkCount === undefined || blogger.rangeWorkCount === null
        ? blogger.todayWorkCount
        : blogger.rangeWorkCount;
      const rangeLabel = DATE_COUNT_LABELS[state.workDate] || DATE_COUNT_LABELS.today;
      const metaParts = [`${rangeLabel} ${rangeCount} 条`, intervalLabel(blogger.intervalMinutes)];
      if (blogger.priority) metaParts.push("重点关注");
      if (!blogger.enabled) metaParts.push("已暂停");
      copy.append(el("small", "monitor-blogger-meta", metaParts.join(" · ")));
      select.append(copy);
      row.append(select);
      const edit = el("button", "monitor-text-button monitor-blogger-settings", "设置");
      edit.type = "button";
      edit.addEventListener("click", () => openBloggerModal(blogger));
      row.append(edit);
      const collectionNotice = bloggerCollectionNotice(blogger);
      if (collectionNotice) row.append(collectionNotice);
      dom.bloggerList.append(row);
    });
    if (dom.bloggerModal && !dom.bloggerModal.hidden && state.editingBloggerId) {
      const current = items.find(item => item.id === state.editingBloggerId);
      if (current && dom.bloggerSummary) {
        dom.bloggerSummary.querySelectorAll(".monitor-blogger-error").forEach(node => node.remove());
        const notice = bloggerCollectionNotice(current);
        if (notice) dom.bloggerSummary.append(notice);
      }
    }
    dom.bloggerList.scrollTop = scrollTop;
    renderBloggerLoadStatus();
  }

  function bloggerCollectionNotice(blogger) {
    const key = `${state.accountId}:${blogger.id}`;
    if (pendingBloggerRetries.has(key) || ["running", "queued"].includes(blogger.status)) {
      const notice = el("small", "monitor-blogger-error", "正在采集…");
      notice.setAttribute("role", "status");
      return notice;
    }
    if (isRelogin(blogger.lastErrorCode)) return reloginNode("monitor-blogger-error");
    if (["auth_required", "insufficient_balance"].includes(blogger.status) || BLOCKING_COLLECTION_CODES.has(blogger.lastErrorCode)) {
      return el("small", "monitor-blogger-error", blogger.lastError || "采集暂不可用");
    }
    if (!["failed", "partial"].includes(blogger.status)) return null;
    const notice = el("small", "monitor-blogger-error");
    notice.append(el("span", "", blogger.status === "partial" ? "本次采集未完成，" : "本次采集失败，"));
    const retry = el("button", "monitor-blogger-retry", "立即重试");
    retry.type = "button";
    retry.setAttribute("aria-label", `立即重试采集${blogger.name || blogger.nickname || "这位博主"}`);
    retry.addEventListener("click", (event) => {
      event.stopPropagation();
      retryBlogger(blogger.id);
    });
    notice.append(retry);
    return notice;
  }

  async function retryBlogger(bloggerId) {
    const accountId = state.accountId;
    if (!accountId || !bloggerId) return;
    const key = `${accountId}:${bloggerId}`;
    if (pendingBloggerRetries.has(key)) return;
    pendingBloggerRetries.add(key);
    state.requestVersion += 1; // 使点击前尚未返回的旧快照失效。
    renderBloggers();
    try {
      if (window.accountModule?.requireLogin && !(await window.accountModule.requireLogin())) return;
      if (!isSameAccount(accountId)) return;
      await api(`/api/monitor/collect?${new URLSearchParams({ accountId, bloggerId })}`, { method: "POST" });
      if (!isSameAccount(accountId)) return;
      state.busy = true;
      await loadAll({ silent: true });
      if (!isSameAccount(accountId)) return;
      // 即使首次读取尚未出现 running，也继续查询本次提交的结果。
      state.busy = true;
      schedulePoll();
    } catch (error) {
      if (isSameAccount(accountId)) showToast(responseMessage(error, "采集提交失败，请重试"), "error");
    } finally {
      pendingBloggerRetries.delete(key);
      if (isSameAccount(accountId)) renderBloggers();
    }
  }

  function selectBlogger(bloggerId) {
    state.activeBloggerId = state.activeBloggerId === bloggerId ? "" : bloggerId;
    state.workPage = 1;
    loadAll({ silent: true });
  }

  function renderWorks() {
    if (dom.feedTabs) {
      dom.feedTabs.replaceChildren();
      WORK_FILTERS.forEach((tab) => {
        const button = el("button", `monitor-tab${state.workFilter === tab.key ? " is-active" : ""}`, tab.label);
        button.type = "button";
        button.setAttribute("role", "tab");
        button.setAttribute("aria-selected", String(state.workFilter === tab.key));
        button.addEventListener("click", () => {
          state.workFilter = tab.key;
          state.workPage = 1;
          loadAll({ silent: true });
        });
        dom.feedTabs.append(button);
      });
    }
    setPickerValue("workDate", state.workDate);

    if (!dom.workList) return;
    dom.workList.replaceChildren();
    const data = state.works;
    const items = Array.isArray(data?.items) ? data.items : [];
    if (!items.length) {
      let hint = "这个范围内还没有采集到作品。";
      if (state.activeBloggerId) hint = "这位博主在这个范围内没有作品。";
      else if (state.workFilter === "saved") hint = "还没有收藏作品。";
      else if (state.workFilter === "new") hint = "今天还没有新发现的作品。";
      else if (DATE_EMPTY_HINTS[state.workDate]) hint = DATE_EMPTY_HINTS[state.workDate] + "把日期切到「全部日期」可以看已采集的历史作品。";
      setMessage(dom.workMessage, hint);
    } else {
      setMessage(dom.workMessage, "");
    }
    items.forEach((work) => dom.workList.append(renderWork(work)));
    if (dom.workSummary) {
      const lastSync = state.overview?.lastSuccessText;
      dom.workSummary.textContent = data
        ? `共 ${data.total} 条 · 每页 ${data.pageSize} 条${lastSync ? ` · 最近成功同步 ${lastSync}` : ""}`
        : "";
    }
    renderPager(dom.workPager, data, (page) => {
      state.workPage = page;
      loadAll({ silent: true });
    });
  }

  // 按北京时间的发布日期判断，采集刷新不改变标签。
  function isPublishedToday(publishedAt) {
    if (!publishedAt) return false;
    const published = new Date(publishedAt);
    if (Number.isNaN(published.getTime())) return false;
    const formatter = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai" });
    return formatter.format(published) === formatter.format(new Date());
  }

  function renderWork(work) {
    const row = el("article", "monitor-work");
    const thumb = el("button", "monitor-thumb");
    thumb.type = "button";
    thumb.setAttribute("aria-label", `查看作品详情：${work.title || work.id}`);
    thumb.addEventListener("click", () => openWorkModal(work.id));
    if (work.coverUrl || work.coverSrc) {
      const image = el("img", "monitor-thumb-image");
      // 走服务端缓存：抖音封面是 HEIC 且链接会过期，直链在浏览器里显示不出来。
      image.src = work.coverSrc || work.coverUrl;
      image.alt = "";
      image.loading = "lazy";
      image.addEventListener("error", () => {
        image.remove();
        thumb.classList.add("is-placeholder");
      });
      thumb.append(image);
    } else {
      thumb.classList.add("is-placeholder");
    }
    if (work.kind === "image") thumb.append(el("span", "monitor-thumb-tag", `图文 ${work.imageCount || ""}`.trim()));
    else if (work.durationSeconds) thumb.append(el("span", "monitor-thumb-duration", formatDuration(work.durationSeconds)));
    row.append(thumb);

    const copy = el("div", "monitor-work-copy");
    const titleRow = el("div", "monitor-work-title-row");
    const fullTitle = work.title || "（无标题）";
    const titleChars = Array.from(fullTitle);
    const title = el("button", "monitor-work-title", titleChars.length > 130 ? `${titleChars.slice(0, 130).join("")}……` : fullTitle);
    title.title = fullTitle;
    title.type = "button";
    title.addEventListener("click", () => openWorkModal(work.id));
    titleRow.append(title);
    if (work.pinned) titleRow.append(el("span", "monitor-tag", "置顶"));
    copy.append(titleRow);
    // 标题下面的空白处：左边还是博主/时间与指标两行，右边放第一页采集到的点赞曲线。
    const body = el("div", "monitor-work-body");
    const summary = el("div", "monitor-work-summary");
    const meta = el("p", "monitor-work-meta", `${work.bloggerName || "未知博主"} · ${work.publishedText || "发布时间未知"}`);
    // 「数据监控」= 这条作品还在该博主最新一轮的第一页里，跟雷达一样贴在时间右侧；落出第一页自动消失。
    if (work.monitored) meta.append(el("span", "monitor-tag is-monitored", "数据监控"));
    if (isPublishedToday(work.publishedAt)) meta.append(el("span", "monitor-tag is-today", "今天"));
    if (work.isNew) meta.append(el("span", "monitor-tag is-new", "新发现"));
    summary.append(meta);
    const metrics = el("div", "monitor-work-metrics");
    [
      ["点赞", work.metrics?.likes],
      ["评论", work.metrics?.comments],
      ["分享", work.metrics?.shares],
      ["收藏", work.metrics?.collects],
    ].forEach(([label, value]) => {
      metrics.append(el("span", "", `${label} ${formatCount(value)}`));
    });
    summary.append(metrics);
    body.append(summary);
    const spark = renderLikeSpark(work.likeTrend);
    if (spark) body.append(spark);
    copy.append(body);
    row.append(copy);

    const actions = el("div", "monitor-work-actions");
    const topic = el("button", "am-secondary-action monitor-compact-action", "加入选题");
    topic.type = "button";
    topic.addEventListener("click", () => openTopicModalFromWork(work));
    actions.append(topic);
    const breakdown = el("button", "am-secondary-action monitor-compact-action", "拆解视频");
    breakdown.type = "button";
    breakdown.addEventListener("click", () => startBreakdown(work));
    actions.append(breakdown);
    const save = el("button", `monitor-icon-button${work.saved ? " is-saved" : ""}`, work.saved ? "已收藏" : "收藏");
    save.type = "button";
    save.setAttribute("aria-pressed", String(Boolean(work.saved)));
    save.addEventListener("click", () => toggleSaved(work));
    actions.append(save);
    row.append(actions);
    return row;
  }

  function formatDuration(seconds) {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    const minutes = Math.floor(total / 60);
    const rest = total % 60;
    return `${minutes}:${String(rest).padStart(2, "0")}`;
  }

  // 接口返回的是 UTC ISO 字符串；页面统一按北京时间显示，避免和列表时间对不上。
  function formatMoment(value) {
    const text = String(value || "");
    if (!text) return "暂无";
    const moment = new Date(text);
    if (Number.isNaN(moment.getTime())) return "暂无";
    return moment.toLocaleString("zh-CN", {
      timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false,
    });
  }

  function renderPager(host, data, onSelect) {
    if (!host) return;
    host.replaceChildren();
    if (!data || !data.pageCount || data.pageCount <= 1) return;
    const previous = el("button", "monitor-page-button");
    previous.innerHTML = '<svg class="wb-nav-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m14 6-6 6 6 6"/></svg>';
    previous.type = "button";
    previous.setAttribute("aria-label", "上一页");
    previous.disabled = data.page <= 1;
    previous.addEventListener("click", () => onSelect(data.page - 1));
    host.append(previous);
    const start = Math.max(1, Math.min(data.page - 2, data.pageCount - 4));
    for (let page = start; page < start + Math.min(5, data.pageCount); page += 1) {
      const button = el("button", `monitor-page-button${page === data.page ? " is-active" : ""}`, String(page));
      button.type = "button";
      if (page === data.page) button.setAttribute("aria-current", "page");
      button.addEventListener("click", () => onSelect(page));
      host.append(button);
    }
    const next = el("button", "monitor-page-button");
    next.innerHTML = '<svg class="wb-nav-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m10 6 6 6-6 6"/></svg>';
    next.type = "button";
    next.setAttribute("aria-label", "下一页");
    next.disabled = data.page >= data.pageCount;
    next.addEventListener("click", () => onSelect(data.page + 1));
    host.append(next);
  }

  // ------------------------------------------------------------ actions

  function clearRecommendationToast() {
    const toast = document.getElementById("toast");
    if (state.recommendationToastMessage && toast?.textContent === state.recommendationToastMessage && toast.classList.contains("is-loading")) {
      toast.className = "am-toast";
      toast.textContent = "";
    }
    state.recommendationToastMessage = "";
    state.recommendationToastStartedAt = "";
    state.recommendationToastGeneratedAt = "";
  }

  // 点「更新建议」后的加载提示：等到这一轮真的跑完（状态离开 running，且是新一轮或已产出新建议）再收起，
  // 否则 POST 刚返回时概览里还是上一轮的旧状态，提示会被立刻清掉。
  function settleRecommendationToast() {
    if (!state.recommendationToastMessage) return;
    const recommendation = recommendationInputs() || {};
    if (String(recommendation.status || "") === "running") return;
    const startedAt = String(recommendation.startedAt || "");
    const generatedAt = String(recommendation.generatedAt || "");
    const newRun = Boolean(startedAt) && startedAt !== state.recommendationToastStartedAt;
    const produced = Boolean(generatedAt) && generatedAt !== state.recommendationToastGeneratedAt;
    if (newRun || produced) clearRecommendationToast();
  }

  function schedulePoll() {
    window.clearTimeout(state.pollTimer);
    if (!state.accountId || root.hidden) return;
    const recommendation = recommendationInputs();
    const collecting = Number(state.overview?.health?.key === "syncing");
    const bloggerRunning = (state.follows?.items || []).some(item => ["running", "queued"].includes(item.status));
    const busy = ["running", "pending"].includes(recommendation?.status) || collecting === 1 || bloggerRunning || state.busy || Boolean(state.recommendationToastMessage);
    const subscriptionBlocked = state.overview?.health?.key === "insufficient_balance" || (state.follows?.items || []).some(item =>
      item.status === "insufficient_balance" || ["insufficient_points", "insufficient_balance", "subscription_required", "subscription_expired"].includes(item.lastErrorCode));
    if (!busy && !subscriptionBlocked) return;
    state.pollTimer = window.setTimeout(async () => {
      await refreshOverview();
      await loadAll({ silent: true });
    }, busy ? POLL_INTERVAL_MS : 60000);
  }

  async function toggleSaved(work) {
    try {
      const payload = await api(`/api/monitor/works/${encodeURIComponent(work.id)}/saved`, {
        method: "POST",
        body: { accountId: state.accountId, saved: !work.saved },
      });
      showToast(payload?.saved ? "已收藏到当前账号" : "已取消收藏", "success");
      await loadAll({ silent: true });
    } catch (error) {
      showToast(responseMessage(error, "收藏失败"), "error");
    }
  }

  async function dismissRecommendation(key) {
    const revision = state.accountRevision;
    try {
      await api(`/api/monitor/recommendations/${encodeURIComponent(key)}/dismiss?${accountQuery()}`, { method: "POST" });
      if (revision !== state.accountRevision) return;
      showToast("已暂不考虑，可随时撤销", "success");
      await refreshOverview();
    } catch (error) {
      if (revision !== state.accountRevision) return;
      showToast(responseMessage(error, "操作失败"), "error");
    }
  }

  async function restoreRecommendation(key) {
    const revision = state.accountRevision;
    try {
      await api(`/api/monitor/recommendations/${encodeURIComponent(key)}/restore?${accountQuery()}`, { method: "POST" });
      if (revision !== state.accountRevision) return;
      await refreshOverview();
      if (revision === state.accountRevision) showToast("已撤销暂不考虑，可参与下次推荐", "success");
    } catch (error) {
      if (revision !== state.accountRevision) return;
      showToast(responseMessage(error, "撤销失败"), "error");
    }
  }

  async function updateRecommendations() {
    if (!state.accountId || dom.updateButton?.disabled) return;
    // 未登录时不启动平台任务：先弹登录框，避免「已开始生成选题建议」之后在后台静默失败。
    if (window.accountModule && !(await window.accountModule.requireLogin())) return;
    dom.updateButton.disabled = true;
    if (dom.updateLabel) dom.updateLabel.textContent = "生成中…";
    try {
      const current = recommendationInputs() || {};
      state.recommendationToastStartedAt = String(current.startedAt || "");
      state.recommendationToastGeneratedAt = String(current.generatedAt || "");
      state.recommendationToastMessage = "已开始生成选题建议";
      await api(`/api/monitor/recommendations/generate?${accountQuery()}`, { method: "POST" });
      showToast(state.recommendationToastMessage, "loading");
      await refreshOverview();
      schedulePoll();
    } catch (error) {
      clearRecommendationToast();
      showToast(responseMessage(error, "生成失败"), "error");
      dom.updateButton.disabled = false;
      if (dom.updateLabel) dom.updateLabel.textContent = "更新建议";
    }
  }

  async function syncNow() {
    if (!state.accountId) return;
    // 未登录时不启动平台任务：先弹登录框，避免「已开始同步」之后在后台静默失败。
    if (window.accountModule && !(await window.accountModule.requireLogin())) return;
    dom.syncButton.disabled = true;
    if (dom.syncLabel) dom.syncLabel.textContent = "同步中…";
    try {
      const payload = await api(`/api/monitor/collect?${accountQuery({ bloggerId: state.activeBloggerId })}`, { method: "POST" });
      const started = Number(payload?.started || 0);
      const running = Number(payload?.running || 0);
      if (!started && !running) showToast("当前账号还没有可采集的博主", "info");
      else {
        // 这里只通知任务已受理；切页会停止轮询，不能依赖轮询收起全局提示。
        showToast(started ? `已开始同步 ${started} 位博主` : "已有同步任务在进行", "info");
      }
      state.busy = true;
      schedulePoll();
    } catch (error) {
      showToast(responseMessage(error, "同步失败"), "error");
    } finally {
      dom.syncButton.disabled = false;
      if (dom.syncLabel) dom.syncLabel.textContent = "立即同步";
    }
  }

  async function startBreakdown(work) {
    if (work.kind === "image") {
      showToast("这是图文作品，现有拆解只支持视频；可以先加入选题。", "info");
      return;
    }
    if (!work.shareUrl) {
      showToast("这条作品没有可用的原始链接", "error");
      return;
    }
    closeModals();
    window.selectWorkspaceModule?.("split");
    try {
      await window.breakdownModule?.start?.(work.shareUrl, work.title);
    } catch (error) {
      showToast(responseMessage(error, "拆解失败，请稍后重试"), "error");
    }
  }

  // ------------------------------------------------------------ work detail

  // 作品详情里的点赞增长曲线：用完整快照画，点比行内多，下面标首末采集时间与增长量。
  function renderWorkTrend(snapshots) {
    const block = el("div", "monitor-work-detail-trend");
    const points = (Array.isArray(snapshots) ? snapshots : [])
      .map((item) => ({
        at: String(item?.at || ""),
        likes: item?.metrics?.likes,
      }))
      .filter((item) => typeof item.likes === "number" && Number.isFinite(item.likes));
    if (points.length < 2) {
      block.append(el("p", "monitor-hint", "第一页监控至少两轮采集后才能生成增长曲线。"));
      return block;
    }
    const values = points.map((item) => item.likes);
    const first = values[0];
    const last = values[values.length - 1];
    block.append(el("p", "monitor-work-detail-trend-title", "点赞增长曲线"));
    block.append(buildTrendChart({
      values,
      width: 640,
      height: 160,
      pad: 8,
      className: "monitor-trend-chart",
      shellClass: "monitor-trend-chart-shell",
      strokeWidth: 2,
      stretch: true,
      ariaLabel: `点赞增长曲线：${formatCount(first)} 到 ${formatCount(last)}`,
      tipLabel: (node) => `点赞 ${formatCount(node.value)} · ${trendDeltaText(node)} · ${formatMoment(points[node.index].at)}`,
    }));
    const axis = el("div", "monitor-work-detail-trend-axis");
    axis.append(el("span", "", `${formatCount(first)} · ${formatMoment(points[0].at)}`));
    axis.append(el("span", "", `${formatCount(last)} · ${formatMoment(points[points.length - 1].at)}`));
    block.append(axis);
    const growth = last - first;
    block.append(el("p", "monitor-hint", `区间增长 ${growth >= 0 ? "+" : ""}${formatCount(growth)} · 共 ${points.length} 个采集点`));
    return block;
  }

  async function openWorkModal(workId) {
    if (!state.accountId) return;
    const revision = state.accountRevision;
    const request = ++detailRequest;
    try {
      const detail = await api(`/api/monitor/works/${encodeURIComponent(workId)}?${accountQuery()}`);
      if (revision !== state.accountRevision || request !== detailRequest) return;
      state.activeWork = detail;
      renderWorkDetail(detail);
      if (dom.analysisModal) dom.analysisModal.hidden = true;
      if (dom.workModal) dom.workModal.hidden = false;
      document.getElementById("monitorWorkCloseButton")?.focus?.();
    } catch (error) {
      if (revision !== state.accountRevision || request !== detailRequest) return;
      showToast(responseMessage(error, "作品详情读取失败"), "error");
    }
  }

  function renderWorkDetail(work) {
    if (dom.workTitle) dom.workTitle.textContent = work.title || "作品详情";
    if (!dom.workBody) return;
    dom.workBody.replaceChildren();
    const meta = el("p", "monitor-work-detail-meta");
    meta.textContent = [
      work.bloggerName || "未知博主",
      work.publishedText || "发布时间未知",
      work.kind === "image" ? "图文" : "视频",
      work.pinned ? "置顶" : "",
    ].filter(Boolean).join(" · ");
    dom.workBody.append(meta);
    const metrics = el("div", "monitor-work-detail-metrics");
    [
      ["点赞", work.metrics?.likes],
      ["评论", work.metrics?.comments],
      ["分享", work.metrics?.shares],
      ["收藏", work.metrics?.collects],
    ].forEach(([label, value]) => {
      const cell = el("div", "monitor-work-detail-metric");
      cell.append(el("span", "monitor-stat-label", label));
      cell.append(el("strong", "monitor-work-detail-value", formatCount(value)));
      metrics.append(cell);
    });
    dom.workBody.append(metrics);
    dom.workBody.append(renderWorkTrend(work.snapshots));
    dom.workBody.append(el("p", "monitor-hint", `数据采集时间：${formatMoment(work.statsUpdatedAt)} · 已保存 ${work.snapshotCount} 次快照`));
    const links = document.getElementById("monitorDetailVideoLinks");
    if (links) {
      links.replaceChildren();
      const url = safeWorkUrl(work.shareUrl);
      const id = String(url).match(/^https?:\/\/(?:www\.)?(?:douyin\.com\/(?:video|note)|iesdouyin\.com\/share\/(?:video|slides))\/(\d+)(?:\/?(?:[?#].*)?)$/i)?.[1] || String(work.id || "");
      const backup = /^\d+$/.test(id) ? `https://www.douyin.com/jingxuan?modal_id=${id}` : "";
      [["查看视频", url], ["备用链接", backup]].forEach(([label, href]) => {
        const node = el(href ? "a" : "span", "monitor-text-button", href ? label : `${label}不可用`);
        if (href) { node.href = href; node.target = "_blank"; node.rel = "noopener noreferrer"; }
        links.append(node);
      });
    }
    if (work.kind === "image") {
      dom.workBody.append(el("p", "monitor-hint", "图文作品暂时不能拆解，可以先加入选题。"));
    }
    if (dom.workBreakdown) dom.workBreakdown.disabled = work.kind === "image";
  }

  // ------------------------------------------------------------ topic modal

  function openTopicModalFromWork(work) {
    state.pendingTopic = { kind: "work", work, suggestion: {
      title: (work.title || "").replace(/[#＃][^\s#＃]+/gu, "").replace(/\s+/g, " ").trim().slice(0, 60),
      outline: "",
    } };
    openTopicModal();
  }

  function openTopicModalFromRecommendation(item) {
    state.pendingTopic = { kind: "recommendation", key: item.key, suggestion: {
      title: item.title || "",
      outline: "",
    } };
    openTopicModal();
  }

  function openTopicModal() {
    const suggestion = state.pendingTopic?.suggestion || {};
    if (!state.pendingTopic) return;
    if (dom.topicTitle) {
      if (state.pendingTopic.kind === "recommendation") dom.topicTitle.removeAttribute("maxlength");
      else dom.topicTitle.setAttribute("maxlength", "160");
      dom.topicTitle.value = suggestion.title || "";
    }
    if (dom.topicOutline) dom.topicOutline.value = suggestion.outline || "";
    setPickerValue("topicWeek", "current");
    setPickerValue("topicCategory", "highlight");
    setPickerValue("topicFormat", "video");
    setMessage(dom.topicError, "");
    if (dom.topicModal) dom.topicModal.hidden = false;
    window.topicEntryModal?.resize(dom.topicModal);
    dom.topicTitle?.focus();
  }

  async function submitTopic() {
    const pending = state.pendingTopic;
    if (!pending) return;
    const title = (dom.topicTitle?.value || "").trim();
    if (!title) {
      setMessage(dom.topicError, "选题标题不能为空。", true);
      return;
    }
    dom.topicConfirm.disabled = true;
    const revision = state.accountRevision;
    try {
      if (pending.kind === "recommendation") {
        await api(`/api/monitor/recommendations/${encodeURIComponent(pending.key)}/topic`, {
          method: "POST",
          body: {
            accountId: state.accountId,
            title,
            outline: (dom.topicOutline?.value || "").trim(),
            category: pickerValue("topicCategory") || "highlight",
            format: pickerValue("topicFormat") || "video",
            weekPlan: pickerValue("topicWeek") || "current",
          },
        });
      } else {
        await api(`/api/accounts/${encodeURIComponent(state.accountId)}/topics`, {
          method: "POST",
          body: {
            title,
            outline: (dom.topicOutline?.value || "").trim(),
            category: pickerValue("topicCategory") || "highlight",
            format: pickerValue("topicFormat") || "video",
            weekStart: weekStartFor(pickerValue("topicWeek") || "current"),
          },
        });
      }
      if (revision !== state.accountRevision) return;
      closeModals();
      state.pendingTopic = null;
      /* 选题页保留着已读的周，这里写入的是另一页的数据，交给它下次进入时补读。 */
      window.topicsModule?.invalidate?.();
      showToast("已加入选题，可在「本周选题」里继续编辑", "success");
      await loadAll({ silent: true });
      await refreshOverview();
    } catch (error) {
      if (revision !== state.accountRevision) return;
      setMessage(dom.topicError, responseMessage(error, "加入选题失败"), true);
    } finally {
      dom.topicConfirm.disabled = false;
    }
  }

  function weekStartFor(plan) {
    const today = new Date();
    const day = (today.getDay() + 6) % 7;
    const monday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - day);
    if (plan === "next") monday.setDate(monday.getDate() + 7);
    const month = String(monday.getMonth() + 1).padStart(2, "0");
    const date = String(monday.getDate()).padStart(2, "0");
    return `${monday.getFullYear()}-${month}-${date}`;
  }

  // ------------------------------------------------------------ blogger modal

  function openBloggerModal(blogger) {
    state.editingBloggerId = blogger.id;
    if (dom.bloggerSummary) {
      dom.bloggerSummary.replaceChildren();
      dom.bloggerSummary.append(el("strong", "monitor-blogger-summary-name", blogger.name || blogger.nickname || "未命名博主"));
      const parts = [];
      if (blogger.uniqueId) parts.push(`抖音号 ${blogger.uniqueId}`);
      if (blogger.followerCount !== null && blogger.followerCount !== undefined) parts.push(`粉丝 ${formatCount(blogger.followerCount)}`);
      parts.push(`已保存作品 ${blogger.workCount} 条`);
      dom.bloggerSummary.append(el("p", "monitor-hint", parts.join(" · ")));
      const notice = bloggerCollectionNotice(blogger);
      if (notice) dom.bloggerSummary.append(notice);
    }
    if (dom.bloggerNote) dom.bloggerNote.value = blogger.note || "";
    setPickerValue("bloggerInterval", String(blogger.intervalMinutes || 360));
    if (dom.bloggerPriority) dom.bloggerPriority.checked = Boolean(blogger.priority);
    if (dom.bloggerEnabled) dom.bloggerEnabled.checked = blogger.enabled !== false;
    setMessage(dom.bloggerError, "");
    if (dom.bloggerModal) dom.bloggerModal.hidden = false;
  }

  async function saveBlogger() {
    const bloggerId = state.editingBloggerId;
    if (!bloggerId) return;
    dom.bloggerSave.disabled = true;
    try {
      await api(`/api/monitor/bloggers/${encodeURIComponent(bloggerId)}?${accountQuery()}`, {
        method: "PATCH",
        body: {
          note: dom.bloggerNote?.value.trim() || "",
          priority: Boolean(dom.bloggerPriority?.checked),
          intervalMinutes: Number(pickerValue("bloggerInterval") || 360),
          enabled: Boolean(dom.bloggerEnabled?.checked),
        },
      });
      closeModals();
      showToast("博主设置已保存", "success");
      await loadAll({ silent: true });
    } catch (error) {
      setMessage(dom.bloggerError, responseMessage(error, "保存失败"), true);
    } finally {
      dom.bloggerSave.disabled = false;
    }
  }

  async function unfollowBlogger() {
    const bloggerId = state.editingBloggerId;
    if (!bloggerId) return;
    if (!window.confirm("取消关注后不再自动采集这位博主；已保存的作品和选题会保留。确定取消吗？")) return;
    try {
      await api(`/api/monitor/bloggers/${encodeURIComponent(bloggerId)}?${accountQuery()}`, { method: "DELETE" });
      if (state.activeBloggerId === bloggerId) state.activeBloggerId = "";
      closeModals();
      showToast("已取消关注", "success");
      await loadAll({ silent: true });
    } catch (error) {
      setMessage(dom.bloggerError, responseMessage(error, "取消关注失败"), true);
    }
  }

  // ------------------------------------------------------------ add modal

  function openAddModal() {
    if (dom.addShare) dom.addShare.value = "";
    if (dom.addNote) dom.addNote.value = "";
    if (dom.addPriority) dom.addPriority.checked = false;
    setPickerValue("addInterval", String(state.overview?.settings?.intervalMinutes || 360));
    setMessage(dom.addError, "");
    if (dom.addModal) dom.addModal.hidden = false;
    dom.addShare?.focus();
  }

  async function submitAddBlogger() {
    const shareText = (dom.addShare?.value || "").trim();
    if (!shareText) {
      setMessage(dom.addError, "请先粘贴博主主页链接。", true);
      return;
    }
    dom.addConfirm.disabled = true;
    const originalLabel = dom.addConfirm.textContent;
    dom.addConfirm.textContent = "正在解析…";
    try {
      const payload = await api(`/api/monitor/bloggers?${accountQuery()}`, {
        method: "POST",
        body: {
          shareText,
          note: dom.addNote?.value.trim() || "",
          priority: Boolean(dom.addPriority?.checked),
          intervalMinutes: Number(pickerValue("addInterval") || 360),
        },
      });
      closeModals();
      const name = payload?.blogger?.name || "博主";
      showToast(payload?.alreadyFollowing ? `${name} 已经在关注列表里，已重新开始采集` : `已添加 ${name}，正在采集作品`, "success");
      state.busy = true;
      await loadAll({ silent: true });
    } catch (error) {
      setMessage(dom.addError, responseMessage(error, "添加失败，请检查链接"), true);
    } finally {
      dom.addConfirm.disabled = false;
      dom.addConfirm.textContent = originalLabel;
    }
  }

  // ------------------------------------------------------------ settings modal

  // 关闭开关后，它控制的设置行灰态且不可操作；值仍随表单一起保存。
  // 「每天自动生成选题建议」是独立开关，服务端按自身时刻照常调度，不随采集一起禁用。
  function syncSettingsControls() {
    const collectOn = Boolean(dom.settingsCollect?.checked);
    const aiOn = Boolean(dom.settingsAi?.checked);
    if (pickers.settingsInterval) pickers.settingsInterval.control.disabled = !collectOn;
    if (!collectOn) {
      pickers.settingsInterval?.close();
    }
    if (dom.settingsAiTime) dom.settingsAiTime.disabled = !aiOn;
    setSettingsRowOff(dom.settingsInterval, !collectOn);
    setSettingsRowOff(dom.settingsAiTime, !aiOn);
  }

  function setSettingsRowOff(input, off) {
    if (!input || typeof input.closest !== "function") return;
    const row = input.closest(".home-field, .settings-switch-row");
    row?.classList?.toggle?.("is-off", off);
  }


  /* 682.500 -> 682.5：界面只保留有效小数位。 */
  function trimPoints(value) {
    let text = String(value === null || value === undefined ? "0" : value).trim();
    if (text.indexOf(".") < 0) return text || "0";
    while (text.endsWith("0")) text = text.slice(0, -1);
    if (text.endsWith(".")) text = text.slice(0, -1);
    return text || "0";
  }

  async function openSettingsModal() {
    try {
      const payload = await api("/api/monitor/settings");
      const settings = payload?.settings || {};
      state.intervalOptions = Array.isArray(payload?.intervalOptions) && payload.intervalOptions.length ? payload.intervalOptions : state.intervalOptions;
      if (dom.settingsCollect) dom.settingsCollect.checked = settings.collectEnabled !== false;
      setPickerValue("settingsInterval", String(settings.intervalMinutes || 360));
      if (dom.settingsAi) dom.settingsAi.checked = settings.aiEnabled !== false;
      if (dom.settingsAiTime) dom.settingsAiTime.value = settings.aiDailyTime || "10:30";
      syncSettingsControls();
      const usage = payload?.usage || {};
      /* 一轮监控可能包含多次调用：按「总请求数 + 累计消耗积分」汇总，不写成一个固定价格。 */
      const charged = Number(usage.chargedTotalPoints || 0);
      if (dom.usageLine) {
        dom.usageLine.textContent = charged
          ? `全部工作台账号：今日调用 ${usage.todayRequests || 0} 次 · 累计 ${usage.requests || 0} 次 · 累计消耗 ${trimPoints(charged)} 积分`
          : `全部工作台账号：今日调用 ${usage.todayRequests || 0} 次 · 累计 ${usage.requests || 0} 次`;
      }
      if (dom.usageNote) {
        const breakdown = usage.todayBreakdown || {};
        dom.usageNote.textContent = "每次查询都由创作服务按有效查询计费：资料与作品列表合计记在同一天；频繁手动同步会消耗更多积分。";
        if (breakdown.posts) dom.usageNote.textContent = `今日作品/资料请求 ${breakdown.posts} 次。${dom.usageNote.textContent}`;
      }
      if (dom.usageBilling) {
        dom.usageBilling.textContent = charged
          ? `全部工作台账号：创作服务已扣积分合计 ${trimPoints(charged)}（今日 ${trimPoints(Number(usage.chargedTodayPoints || 0))}）。`
          : "全部工作台账号尚未产生创作服务扣点。";
      }
      if (dom.keyState) {
        dom.keyState.textContent = payload?.creationConfigured
          ? "数据采集走创作服务平台；接口与密钥由平台统一维护，工作台不再持有。"
          : "尚未登录或未切换到真实通路，请先在账号与订阅里登录后再采集。";
      }
      setMessage(dom.settingsError, "");
      if (dom.settingsModal) dom.settingsModal.hidden = false;
    } catch (error) {
      showToast(responseMessage(error, "设置读取失败"), "error");
    }
  }

  async function saveSettings() {
    dom.settingsSave.disabled = true;
    try {
      const payload = await api("/api/monitor/settings", {
        method: "PUT",
        body: {
          collectEnabled: Boolean(dom.settingsCollect?.checked),
          intervalMinutes: Number(pickerValue("settingsInterval") || 360),
        },
      });
      closeModals();
      showToast("监控设置已保存", "success");
      if (payload?.settings) state.overview = { ...(state.overview || {}), settings: payload.settings };
      await loadAll({ silent: true });
    } catch (error) {
      setMessage(dom.settingsError, responseMessage(error, "保存失败"), true);
    } finally {
      dom.settingsSave.disabled = false;
    }
  }

  // ------------------------------------------------------------ wiring

  const pickerConfigs = [
    { key: "workDate", input: "monitorDateSelect", label: "作品日期", options: () => DATE_OPTIONS, onChange: (next) => {
      state.workDate = next;
      state.workPage = 1;
      loadAll({ silent: true });
    } },
    { key: "addInterval", input: "monitorAddIntervalSelect", label: "检查频率", options: intervalOptions },
    { key: "settingsInterval", input: "monitorSettingsIntervalSelect", label: "默认检查频率", options: intervalOptions },
    { key: "bloggerInterval", input: "monitorBloggerIntervalSelect", label: "检查频率", options: intervalOptions },
    { key: "topicWeek", input: "monitorTopicWeekSelect", label: "计划安排", options: () => WEEK_OPTIONS },
    { key: "topicCategory", input: "monitorTopicCategorySelect", label: "选题分类", options: () => CATEGORY_OPTIONS },
    { key: "topicFormat", input: "monitorTopicFormatSelect", label: "内容形式", options: () => FORMAT_OPTIONS },
  ];
  pickerConfigs.forEach((config) => createPicker(config.key, config));

  document.getElementById("monitorAiEvidenceButton")?.addEventListener("click", showEvidence);
  document.getElementById("monitorAnalysisCloseButton")?.addEventListener("click", closeModals);
  dom.analysisModal?.addEventListener("click", event => { if (event.target === dom.analysisModal) closeModals(); });
  dom.addBlogger?.addEventListener("click", openAddModal);
  dom.settings?.addEventListener("click", openSettingsModal);
  dom.settingsCollect?.addEventListener("change", syncSettingsControls);
  dom.settingsAi?.addEventListener("change", syncSettingsControls);
  dom.updateButton?.addEventListener("click", updateRecommendations);
  dom.syncButton?.addEventListener("click", syncNow);
  let searchTimer = 0;
  dom.bloggerSearch?.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => {
      state.bloggerKeyword = (dom.bloggerSearch.value || "").trim();
      state.bloggerPage = 1;
      loadAll({ silent: true });
    }, 250);
  });
  dom.addCancel?.addEventListener("click", () => { dom.addModal.hidden = true; });
  dom.addConfirm?.addEventListener("click", submitAddBlogger);
  dom.settingsCancel?.addEventListener("click", () => { dom.settingsModal.hidden = true; });
  dom.settingsSave?.addEventListener("click", saveSettings);
  dom.bloggerCancel?.addEventListener("click", () => { dom.bloggerModal.hidden = true; });
  dom.bloggerSave?.addEventListener("click", saveBlogger);
  dom.bloggerUnfollow?.addEventListener("click", unfollowBlogger);
  dom.workClose?.addEventListener("click", () => { dom.workModal.hidden = true; });
  dom.workTopic?.addEventListener("click", () => {
    if (!state.activeWork) return;
    openTopicModalFromWork(state.activeWork);
  });
  dom.workBreakdown?.addEventListener("click", () => {
    if (!state.activeWork) return;
    startBreakdown(state.activeWork);
  });
  dom.topicCancel?.addEventListener("click", () => { dom.topicModal.hidden = true; state.pendingTopic = null; });
  dom.topicConfirm?.addEventListener("click", submitTopic);

  // 鼠标点到浮层外面就算失焦，直接把选择器收起来（和其他模块的浮层同一套交互）。
  document.addEventListener("pointerdown", (event) => {
    if (!openPicker) return;
    if (event.target.closest?.(".topics-select-control")) return;
    closePickers();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (openPicker) {
      event.preventDefault();
      closePickers();
      return;
    }
    const open = [dom.addModal, dom.settingsModal, dom.bloggerModal, dom.workModal, dom.topicModal, dom.analysisModal].some((modal) => modal && !modal.hidden);
    if (open) {
      event.preventDefault();
      closeModals();
      state.pendingTopic = null;
    }
  });

  window.addEventListener("workspace-module-change", (event) => {
    if (event?.detail?.module !== "monitor") {
      window.clearTimeout(state.pollTimer);
      return;
    }
    if (state.accountId) loadAll({ silent: state.loaded });
  });

  window.addEventListener("subscription-refreshed", () => {
    if (state.accountId && !root.hidden) loadAll({ silent: true });
  });

  window.addEventListener("focus", () => {
    if (state.accountId && !root.hidden && state.loaded) refreshOverview();
  });

  dom.bloggerList?.addEventListener("scroll", loadMoreBloggersOnScroll, { passive: true });

  function onAccountChange(accountId) {
    const next = String(accountId || "");
    if (next === state.accountId) return;
    window.clearTimeout(state.pollTimer);
    clearRecommendationToast();
    state.bloggerVersion += 1;
    state.bloggerKey = "";
    state.bloggerLoading = false;
    state.bloggerError = "";
    state.bloggerHasMore = false;
    state.accountRevision += 1;
    state.requestVersion += 1;
    closeModals();
    state.activeWork = null;
    state.pendingTopic = null;
    state.accountId = next;
    state.loaded = false;
    state.overview = null;
    state.follows = null;
    state.works = null;
    state.activeBloggerId = "";
    state.workFilter = "all";
    state.workDate = "all";
    state.workPage = 1;
    state.bloggerFilter = "all";
    state.bloggerKeyword = "";
    state.bloggerPage = 1;
    state.busy = false;
    if (dom.bloggerSearch) dom.bloggerSearch.value = "";
    render();
    if (next && !root.hidden) loadAll();
  }

  window.monitorModule = { onAccountChange, openWork(accountId, workId) {
    if (!accountId || !workId) return;
    onAccountChange(accountId);
    return openWorkModal(workId);
  }, openBlogger(accountId, bloggerId, nickname) {
    if (!accountId || accountId !== state.accountId || !bloggerId) return;
    state.activeBloggerId = bloggerId;
    state.workPage = 1;
    state.workFilter = "all";
    state.workDate = "all";
    state.bloggerFilter = "all";
    state.bloggerPage = 1;
    state.bloggerKeyword = String(nickname || "");
    if (dom.bloggerSearch) dom.bloggerSearch.value = state.bloggerKeyword;
    window.selectWorkspaceModule?.("monitor");
  } };
})();
