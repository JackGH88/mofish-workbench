/* 复盘（review）：按账号查看抖音已发布作品的表现，记录复盘并转成下一步动作。
   可见性由 workspace-navigation.js 管理；本文件负责数据、渲染与操作。 */
(() => {
  const root = document.getElementById("reviewContent");
  if (!root) return;

  const METRIC_LABELS = {
    views: "播放量",
    likes: "点赞",
    comments: "评论",
    shares: "分享",
    saves: "收藏",
    completionRate: "完播率",
    bounceRate2s: "2 秒跳出率",
    fansGained: "吸粉量",
    skipRate: "划走率",
    captionExpandRate: "文案展开率",
    avgImagesViewed: "平均浏览图片数",
  };
  const COUNT_FIELDS = ["views", "likes", "comments", "shares", "saves", "fansGained"];
  const PERCENT_FIELDS = ["completionRate", "bounceRate2s", "skipRate", "captionExpandRate"];
  const SUMMARY_FIELDS = [
    { key: "workCount", label: "所选作品", metric: "" },
    { key: "views", label: "累计播放量", metric: "views" },
    { key: "saves", label: "累计收藏量", metric: "saves" },
    { key: "fansGained", label: "累计吸粉量", metric: "fansGained" },
  ];
  const FILTERS = [
    { key: "all", label: "全部作品" },
    { key: "pending", label: "待复盘" },
    { key: "done", label: "已复盘" },
  ];
  // 内容因子的三个可选维度，顺序与弹窗里的下拉一致。
  const FACTOR_FIELDS = ["topic", "hook", "structure"];
  const TABS = [
    { key: "data", label: "数据表现" },
    { key: "note", label: "内容复盘" },
  ];
  const STATUS_TEXT = {
    idle: "未开启自动采集",
    queued: "等待采集",
    running: "采集中…",
    success: "上次采集成功",
    partial: "上次采集未跑完",
    failed: "上次采集失败",
    login_required: "需要重新登录",
  };
  const SCOPE_LABELS = { recent30: "近 30 天发布的作品", recent90: "近 90 天发布的作品", all: "全部作品" };
  const SUGGESTION_GROUPS = [
    { key: "observations", label: "数据事实" },
    { key: "hypotheses", label: "待验证的假设" },
    { key: "nextSteps", label: "下一步动作" },
  ];
  const POLL_INTERVAL_MS = 5000;
  /* 列表行只展示标题的前 40 个字，超出用省略号；完整标题仍在右侧详情里。 */
  const WORK_TITLE_MAX_CHARS = 40;

  const dom = {
    subtitle: document.getElementById("reviewSubtitle"),
    syncState: document.getElementById("reviewSyncState"),
    syncButton: document.getElementById("reviewSyncButton"),
    configButton: document.getElementById("reviewConfigButton"),
    notice: document.getElementById("reviewNotice"),
    summaryList: document.getElementById("reviewSummaryList"),
    summaryHint: document.getElementById("reviewSummaryHint"),
    filters: document.getElementById("reviewFilters"),
    search: document.getElementById("reviewSearchInput"),
    workList: document.getElementById("reviewWorkList"),
    emptyState: document.getElementById("reviewEmptyState"),
    listMessage: document.getElementById("reviewListMessage"),
    detail: document.getElementById("reviewDetail"),
    configModal: document.getElementById("reviewConfigModal"),
    configEnabled: document.getElementById("reviewEnabledInput"),
    configMode: document.getElementById("reviewModeInput"),
    configInterval: document.getElementById("reviewIntervalInput"),
    configDailyTime: document.getElementById("reviewDailyTimeInput"),
    configScope: document.getElementById("reviewScopeInput"),
    configHint: document.getElementById("reviewConfigHint"),
    configMessage: document.getElementById("reviewConfigMessage"),
    configCancel: document.getElementById("reviewConfigCancelButton"),
    configSave: document.getElementById("reviewConfigSaveButton"),
    trendPanel: document.getElementById("reviewTrendPanel"),
    trendSubtitle: document.getElementById("reviewTrendSubtitle"),
    trendScope: document.getElementById("reviewTrendScope"),
    trendRange: document.getElementById("reviewTrendRange"),
    trendSummary: document.getElementById("reviewTrendSummary"),
    trendChart: document.getElementById("reviewTrendChart"),
    trendFootNote: document.getElementById("reviewTrendFootNote"),
    trendHint: document.getElementById("reviewTrendHint"),
    trendDetail: document.getElementById("reviewTrendDetail"),
    trendMessage: document.getElementById("reviewTrendMessage"),
    factorPanel: document.getElementById("reviewFactorPanel"),
    factorSubtitle: document.getElementById("reviewFactorSubtitle"),
    factorPending: document.getElementById("reviewFactorPendingButton"),
    factorMetric: document.getElementById("reviewFactorMetricInput"),
    factorTabs: document.getElementById("reviewFactorTabs"),
    factorRange: document.getElementById("reviewFactorRange"),
    factorMetricCaption: document.getElementById("reviewFactorMetricCaption"),
    factorBars: document.getElementById("reviewFactorBars"),
    factorCoverage: document.getElementById("reviewFactorCoverage"),
    factorInsightTitle: document.getElementById("reviewFactorInsightTitle"),
    factorInsightText: document.getElementById("reviewFactorInsightText"),
    factorInsightNote: document.getElementById("reviewFactorInsightNote"),
    factorWorks: document.getElementById("reviewFactorWorks"),
    factorMessage: document.getElementById("reviewFactorMessage"),
    factorModal: document.getElementById("reviewFactorModal"),
    factorWorkSelect: document.getElementById("reviewFactorWorkInput"),
    factorSource: document.getElementById("reviewFactorSource"),
    factorTopicSelect: document.getElementById("reviewFactorTopicInput"),
    factorHookSelect: document.getElementById("reviewFactorHookInput"),
    factorStructureSelect: document.getElementById("reviewFactorStructureInput"),
    factorAttributes: document.getElementById("reviewFactorAttributes"),
    factorModalHint: document.getElementById("reviewFactorModalHint"),
    factorModalMessage: document.getElementById("reviewFactorModalMessage"),
    factorAi: document.getElementById("reviewFactorAiButton"),
    factorCancel: document.getElementById("reviewFactorCancelButton"),
    factorSave: document.getElementById("reviewFactorSaveButton"),

  };

  // 采集设置里的三个下拉复用选题的自定义菜单：原生 select 的弹层无法跟这里的
  // 圆角/留白语言统一，值仍由隐藏 input 持有，读取方式不变。
  const PICKER_CONFIGS = {
    mode: {
      input: "reviewModeInput",
      label: "采集方式",
      options: () => [
        { value: "interval", label: "按间隔采集" },
        { value: "daily", label: "每天定时采集" },
      ],
      // 切换采集方式后立刻刷新从属行的灰态，不用关掉弹窗再打开。
      onSelect: () => syncConfigControls(),
    },
    interval: {
      input: "reviewIntervalInput",
      label: "采集间隔",
      options: () =>
        (state.options && state.options.intervalMinutes ? state.options.intervalMinutes : [30, 60, 120, 360, 720]).map((minutes) => ({
          value: String(minutes),
          label: minutes >= 60 ? "每 " + minutes / 60 + " 小时" : "每 " + minutes + " 分钟",
        })),
    },
    scope: {
      input: "reviewScopeInput",
      label: "日常更新范围",
      options: () =>
        (state.options && state.options.scopes ? state.options.scopes : [{ key: "recent30" }, { key: "recent90" }, { key: "all" }]).map((scope) => ({
          value: scope.key,
          label: SCOPE_LABELS[scope.key] || scope.key,
        })),
    },
    factorMetric: {
      input: "reviewFactorMetricInput",
      label: "因子对比指标",
      options: () =>
        ((state.factors && state.factors.metricOptions) || [
          { key: "median", label: "播放量中位数" },
          { key: "mean", label: "平均播放量" },
          { key: "fans", label: "平均吸粉量" },
          { key: "conversion", label: "每千次播放吸粉数" },
        ]).map((item) => ({ value: String(item.key), label: String(item.label) })),
      onSelect: (option) => {
        state.factorMetric = option || "median";
        state.factorGroup = "";
        state.factors = null;
        renderFactorPanel();
        loadFactors({ silent: true });
      },
    },
    factorWork: {
      input: "reviewFactorWorkInput",
      label: "选择作品",
      options: () =>
        (Array.isArray(state.pendingFactorWorks) ? state.pendingFactorWorks : []).map((item) => ({
          value: String(item.workId || ""),
          label: String(item.title || "未命名作品"),
        })),
      onSelect: (option) => loadFactorWork(option),
    },
    factorTopic: { input: "reviewFactorTopicInput", label: "选题分类", options: () => factorPickerOptions("topic") },
    factorHook: { input: "reviewFactorHookInput", label: "钩子", options: () => factorPickerOptions("hook") },
    factorStructure: { input: "reviewFactorStructureInput", label: "结构", options: () => factorPickerOptions("structure") },
  };

  const pickers = {};
  let openPickerKey = "";

  function createPicker(key) {
    const config = PICKER_CONFIGS[key];
    const input = document.getElementById(config.input);
    const host = document.querySelector('[data-review-picker="' + key + '"] .topics-select-control');
    if (!input || !host) return null;

    const control = button("am-input topics-select-button", "");
    control.id = config.input + "Button";
    control.setAttribute("aria-haspopup", "menu");
    control.setAttribute("aria-expanded", "false");
    control.setAttribute("aria-label", config.label);
    const value = el("span", "topics-select-value");
    value.id = config.input + "Value";
    const chevron = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    chevron.setAttribute("class", "topics-select-chevron");
    chevron.setAttribute("viewBox", "0 0 12 12");
    chevron.setAttribute("aria-hidden", "true");
    const chevronPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    chevronPath.setAttribute("d", "M3 4.5L6 7.5L9 4.5");
    chevronPath.setAttribute("stroke", "currentColor");
    chevronPath.setAttribute("stroke-width", "1.5");
    chevronPath.setAttribute("stroke-linecap", "round");
    chevronPath.setAttribute("stroke-linejoin", "round");
    chevron.append(chevronPath);
    control.append(value, chevron);

    const menu = el("div", "topics-select-menu");
    menu.id = config.input + "Menu";
    menu.setAttribute("role", "menu");
    menu.setAttribute("aria-label", config.label);
    menu.hidden = true;
    control.setAttribute("aria-controls", menu.id);

    host.append(control, menu);

    const picker = {
      key,
      input,
      control,
      menu,
      labelFor: (option) => {
        const found = config.options().find((item) => item.value === option);
        return found ? found.label : option;
      },
      value: () => input.value,
      setValue: (option, { silent = false } = {}) => {
        const allowed = config.options().map((item) => item.value);
        const next = allowed.indexOf(option) >= 0 ? option : allowed[0];
        input.value = next;
        value.textContent = picker.labelFor(next);
        picker.renderOptions();
        if (!silent) picker.close();
        if (!silent && config.onSelect) config.onSelect(next);
        return next;
      },
      renderOptions: () => {
        menu.replaceChildren(
          ...config.options().map((option) => {
            const node = button("topics-select-option" + (input.value === option.value ? " is-current" : ""), option.label);
            node.setAttribute("role", "menuitemradio");
            node.setAttribute("aria-checked", input.value === option.value ? "true" : "false");
            node.addEventListener("click", (event) => {
              event.preventDefault();
              picker.setValue(option.value);
              control.focus();
            });
            return node;
          })
        );
      },
      open: () => {
        closePickers(key);
        menu.hidden = false;
        control.setAttribute("aria-expanded", "true");
        openPickerKey = key;
      },
      close: () => {
        menu.hidden = true;
        control.setAttribute("aria-expanded", "false");
        if (openPickerKey === key) openPickerKey = "";
      },
    };
    control.addEventListener("click", () => {
      if (menu.hidden) picker.open();
      else picker.close();
    });
    picker.renderOptions();
    return picker;
  }

  function closePickers(except) {
    Object.values(pickers).forEach((picker) => {
      if (picker && picker.key !== except) picker.close();
    });
  }

  const state = {
    accountId: "",
    loaded: false,
    loading: false,
    requestVersion: 0,
    config: null,
    options: null,
    works: [],
    summary: null,
    scripts: [],
    filter: "all",
    search: "",
    selectedId: "",
    detail: null,
    detailRequestVersion: 0,
    tab: "data",
    noteDraft: "",
    noteDirty: false,
    busy: false,
    syncPhase: "",
    syncFeedback: null,
    loginOpening: false,
    suggestion: null,
    suggestionError: "",
    message: "",
    pollTimer: 0,
    trend: null,
    trendDays: 30,
    trendScope: "account",
    trendDetail: null,
    trendMessage: "",
    trendMessageError: false,
    trendRequestVersion: 0,
    factors: null,
    factorDimension: "hook",
    factorMetric: "median",
    factorRangeDays: 30,
    factorGroup: "",
    factorCatalog: null,
    pendingFactorWorks: [],
    factorWork: null,
    factorSelection: null,
    factorSaving: false,
    factorMessage: "",
    factorMessageError: false,
    factorRequestVersion: 0,

  };

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function button(className, text) {
    const node = el("button", className, text);
    node.type = "button";
    return node;
  }

  /* 按字符（而不是 UTF-16 码元）计数，标题里的 emoji 或补充平面字符不会被截成半个。 */
  function truncateTitle(value, max = WORK_TITLE_MAX_CHARS) {
    const chars = Array.from(String(value == null ? "" : value));
    if (chars.length <= max) return chars.join("");
    return chars.slice(0, max).join("") + "…";
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

  function setMessage(node, message, { error = false } = {}) {
    if (!node) return;
    node.hidden = !message;
    node.textContent = message || "";
    node.classList.toggle("is-error", Boolean(error) && Boolean(message));
  }

  function isSameAccount(accountId) {
    return state.accountId === accountId;
  }

  function formatStamp(iso) {
    const text = String(iso || "").trim();
    if (!text) return "";
    const moment = new Date(text);
    if (Number.isNaN(moment.getTime())) return "";
    const pad = (value) => String(value).padStart(2, "0");
    return (
      moment.getFullYear() +
      "-" + pad(moment.getMonth() + 1) +
      "-" + pad(moment.getDate()) +
      " " + pad(moment.getHours()) +
      ":" + pad(moment.getMinutes())
    );
  }

  function formatMetric(field, value) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value !== "number") return String(value);
    if (PERCENT_FIELDS.indexOf(field) >= 0) return value + "%";
    return value.toLocaleString("zh-CN");
  }

  function metricFieldsFor(work) {
    const fields = ["views", "likes", "comments", "shares", "saves", "completionRate", "bounceRate2s", "fansGained"];
    if (work && work.kind === "image") {
      return ["views", "likes", "comments", "shares", "saves", "skipRate", "captionExpandRate", "avgImagesViewed", "fansGained"];
    }
    return fields;
  }

  function hasData(work) {
    return Boolean(work && work.hasData);
  }

  function workCounts() {
    const pending = state.works.filter((work) => !work.reviewedAt).length;
    return { all: state.works.length, pending, done: state.works.length - pending };
  }

  function selectedWork() {
    return state.works.find((work) => work.id === state.selectedId) || null;
  }

  function scriptTitle(scriptId) {
    const found = state.scripts.find((item) => item.id === scriptId);
    return found ? found.title || "未命名脚本" : "";
  }

  // ------------------------------------------------------------------
  // 顶部状态与概览
  // ------------------------------------------------------------------

  function syncSummaryText() {
    const config = state.config;
    if (!config) return "正在读取采集状态…";
    const parts = [STATUS_TEXT[config.status] || "采集状态未知"];
    if (config.running) parts.push("正在采集");
    else if (config.enabled && config.nextRunAt) parts.push("下次 " + formatStamp(config.nextRunAt));
    else if (!config.enabled) parts.push("自动采集关闭");
    if (config.lastSuccessAt) parts.push("上次成功 " + formatStamp(config.lastSuccessAt));
    return parts.join(" · ");
  }

  function renderSyncState() {
    const running = Boolean(state.config && state.config.running);
    const checking = state.syncPhase === "checking";
    dom.syncButton.disabled = running || Boolean(state.syncPhase) || !state.accountId;
    dom.syncButton.textContent = checking ? "检查登录中…" : running || state.syncPhase === "starting" ? "采集中…" : "立即同步";
  }

  function renderNotice() {
    // Collection feedback belongs beside the settings button, never in a banner.
    dom.notice.replaceChildren();
    dom.notice.hidden = true;
    const node = dom.syncState;
    node.replaceChildren();
    const config = state.config || {};
    const active = config.running || state.syncPhase;
    const feedback = state.syncFeedback;
    const loginRequired = feedback ? feedback.loginRequired : config.status === "login_required";
    const text = active ? "" : feedback?.text || state.message ||
      (["login_required", "failed", "partial"].includes(config.status) && config.message) || syncSummaryText();
    node.hidden = !text;
    node.textContent = text;
    if (text && loginRequired) {
      const action = button("review-link-button", state.loginOpening ? "正在打开…" : "授权抖音账号");
      action.disabled = state.loginOpening;
      action.dataset.reviewNoticeAction = "login";
      node.append(" ", action);
    }
  }

  function renderSummary() {
    const summary = state.summary || {};
    const totals = summary.metricTotals || {};
    dom.summaryList.replaceChildren(
      ...SUMMARY_FIELDS.map((field) => {
        const card = el("div", "review-summary-card");
        card.setAttribute("role", "listitem");
        card.append(el("span", "review-summary-label", field.label));
        const value = field.metric ? formatMetric(field.metric, totals[field.metric] ?? 0) : String(summary.workCount ?? 0);
        card.append(el("strong", "review-summary-value", value));
        return card;
      })
    );
    const withData = summary.worksWithData ?? 0;
    const hint = [];
    hint.push("数字是所选作品最近一次采集快照的累计值，不是这段时间的新增量。");
    if (withData < (summary.workCount ?? 0)) {
      hint.push("其中 " + withData + " 条有平台数值，其余显示「—」的作品不计入合计。");
    }
    hint.push("作品吸粉量不等于账号粉丝净增。");
    dom.summaryHint.textContent = hint.join("");
  }

  // ------------------------------------------------------------------
  // 每日播放与吸粉趋势、内容因子
  // ------------------------------------------------------------------
  const FACTOR_DIMENSION_LABELS = {
    topic: "选题分类",
    hook: "钩子",
    structure: "结构",
    time: "时段",
    format: "形态",
    platform: "平台",
    origin: "创作来源",
  };
  const FACTOR_INSIGHT = {
    topic: {
      title: "先看差异，再设计下一次验证",
      text: "这里按选题分类分组。发布时间、内容长度和钩子也可能同时影响结果，排名不代表单一因素的效果。",
    },
    hook: {
      title: "先看差异，再设计下一次验证",
      text: "这里按开头钩子分组。同一批作品的选题和发布时间并不相同，建议挑一个差别最大的分类，用它写一条新内容再比较。",
    },
    structure: {
      title: "先看差异，再设计下一次验证",
      text: "这里按内容结构分组。结构常常和选题绑定，结论只描述这组作品，不写成通用规律。",
    },
    time: {
      title: "发布时间是可验证的变量",
      text: "时段按实际发布时间的北京时间划分。观众活跃时段会被选题和内容质量影响，样本少时先当线索。",
    },
    format: {
      title: "形态对比需要两类样本",
      text: "形态取实际发布的视频或图文。只有一类样本时，这里只说明当前构成，不比较优劣。",
    },
    platform: {
      title: "当前只有抖音数据",
      text: "本期只采集抖音，没有其他平台样本，因此不生成跨平台结论。",
    },
    origin: {
      title: "创作方式和内容分类分开看",
      text: "创作来源记录这条作品是直接创建还是参考链接仿写；内容因子仍按最终作品确认，两者互不替代。",
    },
  };

  function formatCount(value) {
    if (typeof value !== "number" || Number.isNaN(value)) return "—";
    return Math.round(value).toLocaleString("zh-CN");
  }

  function formatFactorValue(metric, value) {
    if (typeof value !== "number" || Number.isNaN(value)) return "—";
    if (metric === "conversion") return value.toFixed(1);
    return formatCount(value);
  }

  function shortDate(iso) {
    const text = String(iso || "");
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
    return match ? match[2] + "." + match[3] : text;
  }

  function renderSeg(host, options, activeKey, dataName) {
    if (!host) return;
    host.replaceChildren(
      ...options.map((option) => {
        const node = button("review-seg-button" + (option.key === activeKey ? " is-active" : ""), option.label);
        node.setAttribute("role", "tab");
        node.setAttribute("aria-selected", option.key === activeKey ? "true" : "false");
        node.dataset[dataName] = option.key;
        return node;
      })
    );
  }

  function trendScopeOptions() {
    const options = (state.trend && state.trend.scopeOptions) || [];
    return options.length
      ? options.map((item) => ({ key: String(item.key), label: String(item.label) }))
      : [{ key: "account", label: "账号整体" }, { key: "tracked", label: "已跟踪作品" }];
  }

  function trendRangeOptions() {
    const ranges = (state.trend && state.trend.rangeOptions) || [7, 30, 90];
    return ranges.map((days) => ({ key: String(days), label: "近 " + days + " 天" }));
  }

  function renderTrendSummary() {
    if (!dom.trendSummary) return;
    const trend = state.trend;
    const summary = (trend && trend.summary) || {};
    const covered = summary.coveredDays || 0;
    const windowDays = summary.windowDays || state.trendDays || 0;
    const cards = [
      { label: "期间播放量", value: covered ? formatCount(summary.views) : "—" },
      { label: "期间吸粉量", value: covered ? formatCount(summary.fans) : "—", unit: "人" },
      { label: "日均吸粉速度", value: typeof summary.avgFansPerDay === "number" ? summary.avgFansPerDay.toFixed(1) : "—", unit: "人 / 天" },
      { label: "有效数据覆盖", value: covered + " / " + windowDays, unit: "天" },
    ];
    dom.trendSummary.replaceChildren(
      ...cards.map((card) => {
        const cell = el("div");
        cell.append(el("span", "", card.label));
        const strong = el("strong", "", card.value);
        if (card.unit) strong.append(el("em", "", card.unit));
        cell.append(strong);
        return cell;
      })
    );
  }

  function niceCeil(value) {
    if (!(value > 0)) return 0;
    const magnitude = Math.pow(10, Math.floor(Math.log10(value)));
    const steps = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
    for (const step of steps) {
      const candidate = step * magnitude;
      if (candidate >= value) return candidate;
    }
    return 10 * magnitude;
  }

  function svgNode(tag, attributes, textValue) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attributes || {}).forEach((key) => node.setAttribute(key, String(attributes[key])));
    if (textValue !== undefined) node.textContent = textValue;
    return node;
  }

  function drawTrendChart() {
    const host = dom.trendChart;
    if (!host) return;
    host.replaceChildren();
    const trend = state.trend;
    const points = trend && Array.isArray(trend.points) ? trend.points : [];
    const measured = typeof host.clientWidth === "number" && host.clientWidth > 0 ? host.clientWidth : 0;
    const width = Math.max(300, Math.round(measured || 720));
    const compact = width < 560;
    const hasValue = points.some((point) => typeof point.views === "number" || typeof point.fans === "number");
    if (!points.length || !hasValue) {
      host.append(el("p", "review-chart-empty", points.length
        ? "这段时间还没有官方日数据：后台通常第二天更新，采集一次后这里会补上。"
        : "还没有采集到官方日数据，先点「立即同步」。"));
      return;
    }
    const height = 220;
    const pad = { top: 18, right: compact ? 46 : 64, bottom: 32, left: compact ? 46 : 64 };
    const plotWidth = Math.max(60, width - pad.left - pad.right);
    const plotHeight = height - pad.top - pad.bottom;
    const viewValues = points.map((point) => point.views).filter((value) => typeof value === "number");
    const fanValues = points.map((point) => point.fans).filter((value) => typeof value === "number");
    const viewMax = niceCeil(Math.max(0, ...viewValues));
    const fanMax = niceCeil(Math.max(0, ...fanValues));
    const stepX = points.length > 1 ? plotWidth / (points.length - 1) : 0;
    const xAt = (index) => Math.round((pad.left + (points.length > 1 ? index * stepX : plotWidth / 2)) * 100) / 100;
    const yAt = (value, max) => {
      if (!(max > 0) || typeof value !== "number") return null;
      return Math.round((pad.top + plotHeight - (value / max) * plotHeight) * 100) / 100;
    };
    const svg = svgNode("svg", {
      viewBox: "0 0 " + width + " " + height,
      role: "group",
      "aria-label": "每日播放量与吸粉量双轴折线图",
    });

    for (let index = 0; index <= 3; index += 1) {
      const y = Math.round((pad.top + (plotHeight / 3) * index) * 100) / 100;
      svg.append(svgNode("line", { x1: pad.left, x2: pad.left + plotWidth, y1: y, y2: y, stroke: "#ededee" }));
      const leftValue = Math.round((viewMax / 3) * (3 - index));
      const rightValue = Math.round((fanMax / 3) * (3 - index));
      svg.append(svgNode("text", { x: pad.left - 10, y: y + 4, "text-anchor": "end" }, formatCount(leftValue)));
      svg.append(svgNode("text", { x: pad.left + plotWidth + 10, y: y + 4, fill: "#447a60" }, formatCount(rightValue)));
    }

    const segment = (field) => {
      const runs = [];
      let current = [];
      points.forEach((point, index) => {
        const y = yAt(point[field], field === "views" ? viewMax : fanMax);
        if (y === null) {
          if (current.length > 1) runs.push(current);
          current = [];
          return;
        }
        current.push(xAt(index) + "," + y);
      });
      if (current.length > 1) runs.push(current);
      return runs;
    };
    const viewRuns = segment("views");
    const fanRuns = segment("fans");
    fanRuns.forEach((run) => {
      svg.append(svgNode("polyline", {
        points: run.join(" "),
        fill: "none",
        stroke: "#447a60",
        "stroke-width": 2,
        "stroke-dasharray": "6 4",
        "stroke-linejoin": "round",
      }));
    });
    viewRuns.forEach((run) => {
      svg.append(svgNode("polyline", {
        points: run.join(" "),
        fill: "none",
        stroke: "#d8809a",
        "stroke-width": 2.4,
        "stroke-linejoin": "round",
      }));
    });

    // 日期刻度：按可用宽度决定间隔，宁可少画几个也不让文字叠在一起。
    const labelSpacing = compact ? 46 : 62;
    const labelStep = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor(plotWidth / labelSpacing))));
    points.forEach((point, index) => {
      const isEdge = index === 0 || index === points.length - 1;
      if (!isEdge && index % labelStep !== 0) return;
      svg.append(svgNode("text", { x: xAt(index), y: height - 10, "text-anchor": "middle" }, shortDate(point.date)));
    });

    const hitWidth = Math.max(14, Math.min(48, plotWidth / Math.max(1, points.length)));
    points.forEach((point, index) => {
      const group = svgNode("g", { class: "review-chart-day", tabindex: "0", role: "button" });
      const dayLabel = shortDate(point.date);
      const viewsLabel = typeof point.views === "number" ? "播放 " + formatCount(point.views) : "播放暂无数据";
      const fansLabel = typeof point.fans === "number" ? "吸粉 " + formatCount(point.fans) : "吸粉暂无数据";
      const statusLabel = point.status === "pending" ? "，今天还没结束" : point.status === "missing" ? "，后台还没给出这一天的数据" : "";
      group.setAttribute("aria-label", dayLabel + "：" + viewsLabel + "，" + fansLabel + statusLabel);
      group.dataset.reviewTrendDay = point.date;
      group.append(svgNode("rect", {
        class: "review-chart-hit",
        x: xAt(index) - hitWidth / 2,
        y: pad.top - 6,
        width: hitWidth,
        height: plotHeight + 12,
      }));
      group.append(svgNode("line", {
        class: "review-chart-marker",
        x1: xAt(index),
        x2: xAt(index),
        y1: pad.top - 4,
        y2: pad.top + plotHeight,
      }));
      const viewY = yAt(point.views, viewMax);
      if (viewY !== null) {
        group.append(svgNode("circle", {
          cx: xAt(index),
          cy: viewY,
          r: points.length > 20 ? 2.6 : 3.6,
          fill: "#fff",
          stroke: "#d8809a",
          "stroke-width": 2,
        }));
      }
      const fanY = yAt(point.fans, fanMax);
      if (fanY !== null) {
        group.append(svgNode("circle", {
          cx: xAt(index),
          cy: fanY,
          r: points.length > 20 ? 2.2 : 3,
          fill: "#447a60",
        }));
      }
      svg.append(group);
    });

    host.append(svg);
  }

  function renderTrendPanel() {
    if (!dom.trendChart) return;
    const trend = state.trend;
    renderSeg(dom.trendRange, trendRangeOptions(), String(state.trendDays), "reviewTrendDays");
    renderSeg(dom.trendScope, trendScopeOptions(), state.trendScope, "reviewTrendScope");
    if (dom.trendSubtitle) {
      const scopeLabel = state.trendScope === "tracked" ? "已跟踪作品" : "账号整体";
      const note = state.options && state.options.trendScopeNote ? state.options.trendScopeNote : "";
      dom.trendSubtitle.textContent = scopeLabel + " · 抖音后台逐日报表 · 独立于上方发布日期筛选" + (note ? "。" + note : "");
    }
    renderTrendSummary();
    drawTrendChart();
    if (dom.trendFootNote) {
      const coverage = (trend && trend.coverage) || {};
      const parts = ["数据来源：抖音后台导出报表 · 时区：北京时间"];
      if (coverage.accountFirstDay && coverage.accountLastDay) {
        parts.push("后台可用日期 " + shortDate(coverage.accountFirstDay) + "–" + shortDate(coverage.accountLastDay));
      }
      if (state.trendScope === "tracked" && coverage.trackedWorks) {
        parts.push("已跟踪 " + coverage.trackedWorks + " 条作品");
      }
      dom.trendFootNote.textContent = parts.join(" · ");
    }
    if (dom.trendHint) {
      dom.trendHint.textContent = state.trendScope === "tracked"
        ? "悬停查看某一天，点击查看这天的作品贡献"
        : "悬停查看某一天；账号口径不拆到单条作品";
    }
    renderTrendDetail();
    setMessage(dom.trendMessage, state.trendMessage, { error: state.trendMessageError });
  }

  function renderTrendDetail() {
    const host = dom.trendDetail;
    if (!host) return;
    const detail = state.trendDetail;
    if (!detail) {
      host.hidden = true;
      host.replaceChildren();
      return;
    }
    host.hidden = false;
    const head = el("div", "review-day-detail-head");
    head.append(el("h4", "", shortDate(detail.date) + " · 播放与吸粉贡献"));
    const totals = [];
    if (typeof detail.account.views === "number") totals.push("账号播放 " + formatCount(detail.account.views));
    if (typeof detail.account.fans === "number") totals.push("账号吸粉 " + formatCount(detail.account.fans));
    head.append(el("small", "review-panel-hint", totals.join(" · ") || "后台没有这一天的汇总数据"));
    const close = button("home-link-button", "收起");
    close.dataset.reviewTrendClose = "1";
    head.append(close);
    host.replaceChildren(head);
    const works = detail.works.filter((item) =>
      (Number.isFinite(item.views) && item.views > 0) ||
      (Number.isFinite(item.fans) && item.fans !== 0)
    );
    if (!works.length) {
      host.append(el("p", "review-panel-hint", detail.works.length
        ? "这一天暂无有播放或吸粉变化的作品。"
        : "这一天还没有采集到作品逐日明细。"));
    } else {
      works.forEach((item) => {
        const row = el("div", "review-day-contribution");
        row.append(el("span", "", item.title || "未命名作品"));
        row.append(el("small", "", "播放 " + formatCount(item.views) + " · 吸粉 " + formatCount(item.fans)));
        host.append(row);
      });
    }
    host.append(el("p", "review-panel-hint", detail.note || ""));
  }

  async function loadTrend({ silent = false } = {}) {
    if (!state.accountId || !dom.trendChart) return;
    const version = ++state.trendRequestVersion;
    const accountId = state.accountId;
    if (!silent) setMessage(dom.trendMessage, "正在读取每日趋势…");
    try {
      const payload = await api(
        "/api/accounts/" + encodeURIComponent(accountId) + "/review/trend?days=" + state.trendDays + "&scope=" + state.trendScope
      );
      if (version !== state.trendRequestVersion || !isSameAccount(accountId)) return;
      state.trend = payload;
      state.trendMessage = "";
      state.trendMessageError = false;
      state.trendDetail = null;
    } catch (error) {
      if (version !== state.trendRequestVersion || !isSameAccount(accountId)) return;
      state.trendMessage = responseMessage(error, "每日趋势读取失败");
      state.trendMessageError = true;
    }
    renderTrendPanel();
  }

  async function loadTrendDay(day) {
    if (!state.accountId || !day) return;
    try {
      const detail = await api(
        "/api/accounts/" + encodeURIComponent(state.accountId) + "/review/trend/day?date=" + encodeURIComponent(day)
      );
      state.trendDetail = detail;
    } catch (error) {
      state.trendDetail = null;
      state.trendMessage = responseMessage(error, "这一天的作品明细读取失败");
      state.trendMessageError = true;
    }
    renderTrendPanel();
  }

  // ------------------------------------------------------------------
  // 内容因子分析
  // ------------------------------------------------------------------

  function pendingFactorCount() {
    if (typeof state.factorPendingCount === "number") return state.factorPendingCount;
    return Array.isArray(state.pendingFactorWorks) ? state.pendingFactorWorks.length : 0;
  }

  function renderFactorPanel() {
    if (!dom.factorBars) return;
    const factors = state.factors;
    if (dom.factorSubtitle) {
      const windowDays = (factors && factors.windowDays) || 7;
      dom.factorSubtitle.textContent =
        "统一比较发布日起 " + windowDays + " 个自然日 · 各因子独立分组，不代表因果关系";
    }
    const dimensions = (factors && factors.dimensions) || Object.keys(FACTOR_DIMENSION_LABELS).map((key) => ({ key, label: FACTOR_DIMENSION_LABELS[key] }));
    renderSeg(
      dom.factorTabs,
      dimensions
        .filter((item) => item.key !== "platform")
        .map((item) => ({ key: String(item.key), label: String(item.label) })),
      state.factorDimension,
      "reviewFactorDimension"
    );
    const ranges = (factors && factors.rangeOptions) || [30, 90];
    renderSeg(
      dom.factorRange,
      ranges.map((days) => ({ key: String(days), label: "发布 " + days + " 天内" })),
      String(state.factorRangeDays),
      "reviewFactorRange"
    );
    pickers.factorMetric?.renderOptions();
    // 指标下拉要显示当前选中的指标，否则按钮上是空白。
    pickers.factorMetric?.setValue(state.factorMetric, { silent: true });
    if (dom.factorPending) {
      dom.factorPending.textContent = "补全作品因子";
      if (pendingFactorCount() > 0) {
        dom.factorPending.append(el("span", "review-factor-count", String(pendingFactorCount())));
      }
      dom.factorPending.disabled = pendingFactorCount() === 0;
    }
    const metricLabel = (factors && factors.metricLabel) || "";
    if (dom.factorMetricCaption) {
      dom.factorMetricCaption.textContent = "发布后 " + ((factors && factors.windowDays) || 7) + " 天 · " + metricLabel;
    }
    const groups = (factors && factors.groups) || [];
    if (!groups.length) {
      dom.factorBars.replaceChildren(el("p", "review-factor-empty", factorEmptyMessage()));
    } else {
      const max = Math.max(...groups.map((group) => (typeof group.value === "number" ? group.value : 0)), 1);
      dom.factorBars.replaceChildren(
        ...groups.map((group) => {
          const node = button("review-factor-bar" + (state.factorGroup === group.name ? " is-selected" : ""));
          node.dataset.reviewFactorGroup = String(group.name);
          node.setAttribute("aria-pressed", state.factorGroup === group.name ? "true" : "false");
          const name = el("span", "review-factor-bar-name");
          name.append(el("strong", "", String(group.name)));
          name.append(el("small", "", group.sampleCount + " 条" + (group.smallSample ? " · 样本较少" : "")));
          const track = el("span", "review-factor-bar-track");
          const fill = el("span", "review-factor-bar-fill");
          const ratio = typeof group.value === "number" ? Math.max(0, Math.min(100, (group.value / max) * 100)) : 0;
          fill.style.width = ratio.toFixed(1) + "%";
          track.append(fill);
          node.append(name, track, el("span", "review-factor-bar-value", formatFactorValue(state.factorMetric, group.value)));
          return node;
        })
      );
    }
    if (dom.factorCoverage) dom.factorCoverage.textContent = factorCoverageText(factors);
    const insight = FACTOR_INSIGHT[state.factorDimension] || FACTOR_INSIGHT.hook;
    if (dom.factorInsightTitle) dom.factorInsightTitle.textContent = insight.title;
    if (dom.factorInsightText) dom.factorInsightText.textContent = insightText(factors, insight);
    if (dom.factorInsightNote) {
      dom.factorInsightNote.textContent =
        "样本少于 " + ((factors && factors.coverage && factors.coverage.smallSampleLimit) || 5) +
        " 条时标记「样本较少」，只作为观察线索；侧栏提示不能当成因果结论。";
    }
    renderFactorWorks();
    setMessage(dom.factorMessage, state.factorMessage, { error: state.factorMessageError });
  }

  function factorEmptyMessage() {
    const factors = state.factors;
    if (!factors) return "还没有因子数据。";
    if (factors.automatic) {
      return factors.coverage && factors.coverage.eligible
        ? "这一维度暂时没有可比较的分组。"
        : "还没有作品具备完整的 7 天窗口数据，先同步一次该账号的作品逐日明细。";
    }
    return "还没有作品确认过这个维度的分类：点右上角「补全作品因子」逐条确认后，这里会出现分组。";
  }

  function factorCoverageText(factors) {
    if (!factors) return "";
    const coverage = factors.coverage || {};
    const parts = [];
    if (factors.automatic) {
      parts.push("发布属性与创作来源直接取采集结果，共 " + (coverage.eligible || 0) + " 条参与比较。");
    } else {
      parts.push(
        (coverage.eligible || 0) + " / " + (coverage.total || 0) + " 条已确认分类，" +
        (coverage.pendingFactors || 0) + " 条待确认（不参与本维度）。"
      );
    }
    if (coverage.outOfRange) parts.push(coverage.outOfRange + " 条作品不在所选发布日期范围内。");
    const excluded = coverage.excluded || [];
    if (excluded.length) {
      parts.push("未纳入：" + excluded.map((item) => item.reason + " " + item.count + " 条").join("、") + "。");
    }
    return parts.join("");
  }

  function insightText(factors, insight) {
    if (!factors) return insight.text;
    const groups = factors.groups || [];
    if (state.factorDimension === "format" && groups.length <= 1) {
      return "当前只有「" + (groups[0] ? groups[0].name : "一种形态") + "」样本，沿用现有视频 / 图文分类，本期不做优劣对比。";
    }
    if (state.factorDimension === "platform") {
      return "本期没有其他平台样本，不生成跨平台优劣结论。";
    }
    return insight.text;
  }

  function renderFactorWorks() {
    const host = dom.factorWorks;
    if (!host) return;
    const groups = (state.factors && state.factors.groups) || [];
    const group = groups.find((item) => item.name === state.factorGroup);
    if (!group) {
      host.hidden = true;
      host.replaceChildren();
      return;
    }
    host.hidden = false;
    const head = el("div", "review-day-detail-head");
    head.append(el("h4", "", group.name + " · " + group.sampleCount + " 条作品"));
    head.append(el("small", "review-panel-hint", "发布后 " + ((state.factors && state.factors.windowDays) || 7) + " 天表现"));
    const close = button("review-link-button", "收起");
    close.dataset.reviewFactorGroupClose = "1";
    head.append(close);
    host.replaceChildren(head);
    (group.works || []).forEach((item) => {
      const row = el("div", "review-factor-sample");
      const copy = el("div");
      copy.append(el("strong", "", item.title || "未命名作品"));
      const meta = [item.publishedText || "", item.confirmed ? "内容因子已确认" : "内容因子待确认"].filter(Boolean).join(" · ");
      copy.append(el("small", "", meta));
      row.append(copy);
      row.append(el("span", "", "播放 " + formatCount(item.views)));
      row.append(el("span", "", "吸粉 " + formatCount(item.fans)));
      host.append(row);
    });
  }

  async function loadFactors({ silent = false } = {}) {
    if (!state.accountId || !dom.factorBars) return;
    const version = ++state.factorRequestVersion;
    const accountId = state.accountId;
    if (!silent) setMessage(dom.factorMessage, "正在读取因子分析…");
    try {
      const payload = await api(
        "/api/accounts/" + encodeURIComponent(accountId) + "/review/factors?dimension=" + state.factorDimension +
        "&metric=" + state.factorMetric + "&days=" + state.factorRangeDays
      );
      if (version !== state.factorRequestVersion || !isSameAccount(accountId)) return;
      state.factors = payload;
      state.factorMessage = "";
      state.factorMessageError = false;
    } catch (error) {
      if (version !== state.factorRequestVersion || !isSameAccount(accountId)) return;
      state.factorMessage = responseMessage(error, "因子分析读取失败");
      state.factorMessageError = true;
    }
    renderFactorPanel();
  }

  function factorCatalogEntries(kind) {
    const catalog = (state.factorCatalog && state.factorCatalog[kind]) || [];
    return catalog.map((item) => ({ id: String(item.id || ""), name: String(item.name || "") }));
  }

  function factorPickerOptions(kind) {
    const entries = factorCatalogEntries(kind);
    const options = [{ value: "", label: "未分类" }, ...entries.map((item) => ({ value: item.name, label: item.name }))];
    const selectedName = factorSelectedName(kind);
    if (selectedName && !entries.some((item) => item.name === selectedName)) {
      // 历史分类被改名或删除时仍然显示原值，不让用户的选择悄悄变成「未分类」。
      options.push({ value: selectedName, label: selectedName + "（历史分类）" });
    }
    return options;
  }

  // 弹窗里下拉当前应该显示的分类：优先用正在编辑的选择（含 AI 建议），再退回已保存的因子。
  function factorSelectionOf(detail) {
    const factors = (detail || {}).factors || {};
    const selection = {};
    FACTOR_FIELDS.forEach((key) => {
      const record = factors[key];
      selection[key] = record && record.name ? String(record.name) : "";
    });
    return selection;
  }

  function factorSelectedName(kind) {
    const selection = state.factorSelection;
    if (selection && typeof selection[kind] === "string") return selection[kind];
    return factorSelectionOf(state.factorWork)[kind] || "";
  }

  function setFactorModalOpen(open) {
    if (!dom.factorModal) return;
    dom.factorModal.hidden = !open;
    document.body.classList.toggle("is-modal-open", !dom.factorModal.hidden);
    if (!open) closePickers();
    if (!open) {
      state.factorWork = null;
      state.factorSelection = null;
      setMessage(dom.factorModalMessage, "");
    }
  }

  // applySelection 只在刚拉完某条作品时用：平时重渲染是为了刷新提示和按钮态，
  // 不能把用户刚手选或 AI 刚建议的分类冲回已保存的值。
  function renderFactorModal({ applySelection = false } = {}) {
    const detail = state.factorWork;
    if (!dom.factorWorkSelect || !detail) return;
    const work = detail.work || {};
    const factors = detail.factors || {};
    pickers.factorWork?.setValue(work.id || "", { silent: true });
    if (applySelection) {
      const selection = state.factorSelection || factorSelectionOf(detail);
      pickers.factorTopic?.setValue(selection.topic, { silent: true });
      pickers.factorHook?.setValue(selection.hook, { silent: true });
      pickers.factorStructure?.setValue(selection.structure, { silent: true });
    }
    if (dom.factorSource) {
      const candidates = detail.candidates || {};
      const pieces = [];
      if (candidates.source === "reference") {
        pieces.push("创作来源：参考链接（独立记录，不替代内容因子）");
        pieces.push(
          detail.hasScriptContent
            ? "参考视频的分类不会带过来，需要按自己的最终稿确认，或点下方 AI 建议。"
            : "这条作品还没有最终稿，先人工补标分类。"
        );
      } else if (candidates.source === "script") {
        pieces.push("创作来源：直接创建");
        pieces.push("下面是从新建脚本时带入的候选，请对照最终发布内容确认。");
      } else {
        pieces.push("还没有关联脚本，可以直接按最终内容人工补标。");
      }
      if (detail.confirmed) pieces.push("这条作品已经确认过，可以人工修正。");
      dom.factorSource.textContent = pieces.join(" ");
    }
    if (dom.factorAttributes) {
      const attributes = [];
      if (work.publishedText) attributes.push("实际发布：" + work.publishedText);
      attributes.push("形态：" + (work.kind === "image" ? "图文" : "视频"));
      attributes.push("平台：" + (work.platform === "channels" ? "视频号" : "抖音"));
      if (factors.updatedAt) attributes.push("上次确认：" + formatStamp(factors.updatedAt));
      dom.factorAttributes.textContent = attributes.join(" · ");
    }
    if (dom.factorModalHint) {
      dom.factorModalHint.textContent = [
        state.options && state.options.factorNote,
        state.options && state.options.factorCatalogNote,
      ].filter(Boolean).join("");
    }
    if (dom.factorAi) {
      dom.factorAi.disabled = state.factorSaving || !detail.hasScriptContent;
    }
    if (dom.factorSave) dom.factorSave.disabled = state.factorSaving;
  }

  async function openFactorModal(workId) {
    if (!state.accountId || !dom.factorModal) return;
    const list = Array.isArray(state.pendingFactorWorks) ? state.pendingFactorWorks : [];
    if (!list.length) {
      showToast("当前没有待确认因子的作品", "success");
      return;
    }
    pickers.factorWork?.renderOptions();
    pickers.factorWork?.setValue(String(workId || list[0].workId), { silent: true });
    setFactorModalOpen(true);
    setMessage(dom.factorModalMessage, "");
    await loadFactorWork(workId || list[0].workId);
  }

  async function loadFactorWork(workId) {
    if (!workId) return;
    try {
      const detail = await api("/api/review/works/" + encodeURIComponent(workId) + "/factors");
      state.factorWork = detail;
      state.factorSelection = factorSelectionOf(detail);
      renderFactorModal({ applySelection: true });
    } catch (error) {
      setMessage(dom.factorModalMessage, responseMessage(error, "作品因子读取失败"), { error: true });
    }
  }

  async function saveFactorWork() {
    const detail = state.factorWork;
    if (!detail || state.factorSaving) return;
    const workId = (detail.work || {}).id;
    if (!workId) return;
    // 先读下拉里的当前选择，再进入保存态：重新渲染会把还没保存的选择冲掉。
    const readName = (select) => (select && select.value ? { name: select.value } : { name: "" });
    const selection = {
      topic: readName(dom.factorTopicSelect),
      hook: readName(dom.factorHookSelect),
      structure: readName(dom.factorStructureSelect),
    };
    state.factorSaving = true;
    setMessage(dom.factorModalMessage, "正在保存…");
    renderFactorModal();
    try {
      await api("/api/review/works/" + encodeURIComponent(workId) + "/factors", {
        method: "PUT",
        body: {
          topic: selection.topic,
          hook: selection.hook,
          structure: selection.structure,
          origin: normalizeOrigin(detail.candidates ? detail.candidates.origin : "unknown"),
          confirmed: true,
        },
      });
      showToast("已确认作品因子，统计已更新", "success");
      state.factorWork = null;
      state.factorSelection = null;
      setFactorModalOpen(false);
      await refreshFactorData();
    } catch (error) {
      setMessage(dom.factorModalMessage, responseMessage(error, "作品因子保存失败"), { error: true });
    } finally {
      state.factorSaving = false;
      renderFactorModal();
    }
  }

  function normalizeOrigin(value) {
    return ["direct", "reference", "unknown"].indexOf(String(value)) >= 0 ? String(value) : "unknown";
  }

  async function suggestFactorWork() {
    const detail = state.factorWork;
    if (!detail || state.factorSaving) return;
    const workId = (detail.work || {}).id;
    if (!workId) return;
    state.factorSaving = true;
    setMessage(dom.factorModalMessage, "正在按最终稿匹配现有分类…");
    renderFactorModal();
    try {
      const payload = await api("/api/review/works/" + encodeURIComponent(workId) + "/factors/suggest", {
        method: "POST",
        body: { mode: "ai" },
      });
      const suggestions = payload.suggestions || {};
      // 按最终稿只覆盖模型给出建议的维度，没把握的维度保留当前选择，再整体刷一次下拉。
      const selection = {
        topic: pickers.factorTopic?.value() || "",
        hook: pickers.factorHook?.value() || "",
        structure: pickers.factorStructure?.value() || "",
      };
      FACTOR_FIELDS.forEach((key) => {
        const name = String(suggestions[key] || "");
        if (name) selection[key] = name;
      });
      state.factorSelection = selection;
      renderFactorModal({ applySelection: true });
      setMessage(dom.factorModalMessage, "已按最终稿给出建议，请核对后确认。");
    } catch (error) {
      setMessage(dom.factorModalMessage, responseMessage(error, "AI 因子建议失败"), { error: true });
    } finally {
      state.factorSaving = false;
      renderFactorModal();
    }
  }

  async function refreshFactorData() {
    await loadFactors({ silent: true });
    await loadReview({ silent: true });
  }


  // ------------------------------------------------------------------

  // ------------------------------------------------------------------
  // 作品列表
  // ------------------------------------------------------------------

  function renderFilters() {
    const counts = workCounts();
    dom.filters.replaceChildren(
      ...FILTERS.map((filter) => {
        const node = button("review-filter", filter.label + " " + counts[filter.key]);
        node.setAttribute("role", "tab");
        const active = state.filter === filter.key;
        node.classList.toggle("is-active", active);
        node.setAttribute("aria-selected", active ? "true" : "false");
        node.dataset.reviewFilter = filter.key;
        return node;
      })
    );
  }

  function visibleWorks() {
    const keyword = state.search.trim().toLowerCase();
    return state.works.filter((work) => {
      if (state.filter === "pending" && work.reviewedAt) return false;
      if (state.filter === "done" && !work.reviewedAt) return false;
      if (keyword && !String(work.title || "").toLowerCase().includes(keyword)) return false;
      return true;
    });
  }

  function coverNode(work) {
    const cover = el("span", "review-cover");
    cover.setAttribute("aria-hidden", "true");
    cover.append(el("span", "review-cover-fallback", work.kind === "image" ? "图文" : "视频"));
    const source = work.coverSrc || work.coverUrl;
    if (source) {
      const image = document.createElement("img");
      image.alt = "";
      image.loading = "lazy";
      image.src = source;
      image.addEventListener("error", () => image.remove());
      cover.append(image);
    }
    return cover;
  }

  function renderWorkList() {
    const items = visibleWorks();
    if (!state.works.length) {
      dom.workList.replaceChildren();
      dom.emptyState.hidden = false;
      dom.emptyState.textContent = state.config && state.config.enabled
        ? "还没有采集到作品，点「立即同步」用该账号的专用浏览器采集一次。"
        : "还没有采集记录，点「立即同步」开始一次采集。";
      return;
    }
    dom.emptyState.hidden = items.length > 0;
    dom.emptyState.textContent = items.length ? "" : "没有符合当前筛选的作品。";

    dom.workList.replaceChildren(
      ...items.map((work) => {
        const row = button("review-work" + (work.id === state.selectedId ? " is-active" : ""));
        row.dataset.reviewWork = work.id;
        row.setAttribute("role", "listitem");
        const head = el("span", "review-work-main");
        head.append(coverNode(work));
        const copy = el("span", "review-work-copy");
        copy.append(el("strong", "review-work-title", truncateTitle(work.title || "未命名作品")));
        const meta = [work.publishedText || "发布时间未知", work.durationText || "", work.reviewedAt ? "已复盘" : "待复盘"]
          .filter(Boolean)
          .join(" · ");
        copy.append(el("small", "review-work-meta", meta));
        head.append(copy);
        row.append(head);
        ["views", "completionRate", "fansGained"].forEach((field) => {
          row.append(el("span", "review-work-metric" + (hasData(work) ? "" : " is-empty"), formatMetric(field, work.metrics?.[field])));
        });
        return row;
      })
    );
    setMessage(dom.listMessage, "");
  }

  // ------------------------------------------------------------------
  // 单条作品详情
  // ------------------------------------------------------------------

  function trendNode(work) {
    const points = (work.snapshots || [])
      .map((snapshot) => ({ at: snapshot.collectedAt, value: snapshot.metrics ? snapshot.metrics.views : null }))
      .filter((point) => typeof point.value === "number");
    const wrapper = el("div", "review-trend");
    const head = el("div", "review-trend-head");
    head.append(el("h4", "review-block-title", "播放量变化"));
    head.append(el("small", "", points.length >= 2 ? "按采集快照" : "快照不足"));
    wrapper.append(head);
    if (points.length < 2) {
      wrapper.append(el("p", "review-panel-hint", "至少要有两次不同的采集快照，才能看到变化趋势。"));
      return wrapper;
    }
    const values = points.map((point) => point.value);
    const max = Math.max(...values);
    const min = Math.min(...values);
    const span = max - min || 1;
    const width = 100;
    const height = 32;
    const step = points.length > 1 ? width / (points.length - 1) : width;
    const coordinates = points
      .map((point, index) => {
        const x = (index * step).toFixed(2);
        const y = (height - ((point.value - min) / span) * height).toFixed(2);
        return x + "," + y;
      })
      .join(" ");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("class", "review-trend-chart");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "播放量快照趋势");
    const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    polyline.setAttribute("points", coordinates);
    polyline.setAttribute("fill", "none");
    polyline.setAttribute("stroke", "currentColor");
    polyline.setAttribute("stroke-width", "1.6");
    polyline.setAttribute("vector-effect", "non-scaling-stroke");
    svg.append(polyline);
    wrapper.append(svg);
    const axis = el("div", "review-trend-axis");
    axis.append(el("span", "", formatStamp(points[0].at)));
    axis.append(el("span", "", formatStamp(points[points.length - 1].at)));
    wrapper.append(axis);
    return wrapper;
  }

  function renderDataTab(work) {
    const panel = document.createDocumentFragment();
    const grid = el("div", "review-metric-grid");
    metricFieldsFor(work).forEach((field) => {
      const cell = el("div", "review-metric-cell");
      cell.append(el("span", "review-metric-label", METRIC_LABELS[field] || field));
      cell.append(el("strong", "review-metric-value" + (hasData(work) ? "" : " is-empty"), formatMetric(field, work.metrics?.[field])));
      grid.append(cell);
    });
    panel.append(grid);

    if (!hasData(work)) {
      const hint = el("div", "review-callout");
      hint.append(el("h4", "review-block-title", "平台暂未提供作品指标"));
      hint.append(
        el(
          "p",
          "review-panel-hint",
          "后台对这些作品显示「—」，这里保留为空值，不写成 0，也不会据此给出表现结论。"
        )
      );
      panel.append(hint);
    }
    if (work.collectedAt) {
      panel.append(el("p", "review-panel-hint", "本次数据采集于 " + formatStamp(work.collectedAt) + "。"));
    }
    panel.append(trendNode(work));
    return panel;
  }

  function renderNoteTab(work) {
    const panel = document.createDocumentFragment();
    const scriptRow = el("label", "review-field");
    scriptRow.append(el("span", "review-field-label", "关联脚本"));
    const select = document.createElement("select");
    select.className = "am-input review-script-select";
    select.dataset.reviewField = "script";
    const none = document.createElement("option");
    none.value = "";
    none.textContent = "不关联";
    select.append(none);
    const linkedMissing = work.scriptId && !scriptTitle(work.scriptId);
    state.scripts.forEach((script) => {
      const option = document.createElement("option");
      option.value = script.id;
      option.textContent = script.title || "未命名脚本";
      select.append(option);
    });
    if (linkedMissing) {
      const option = document.createElement("option");
      option.value = work.scriptId;
      option.textContent = "已删除的脚本";
      select.append(option);
    }
    select.value = work.scriptId || "";
    scriptRow.append(select);
    panel.append(scriptRow);
    if (work.scriptId && linkedMissing) {
      panel.append(el("p", "review-panel-hint", "原来关联的脚本已被删除，可以重新选择一个。"));
    } else if (!work.scriptId) {
      panel.append(el("p", "review-panel-hint", "关联脚本后，AI 辅助复盘才能结合当时的选题和写法。"));
    }

    const noteHead = el("div", "review-block-head");
    noteHead.append(el("h4", "review-block-title", "我的复盘笔记"));
    const suggest = button("am-secondary-action review-inline-action", state.busy ? "生成中…" : "AI 辅助复盘");
    suggest.dataset.reviewAction = "suggest";
    suggest.disabled = state.busy;
    noteHead.append(suggest);
    panel.append(noteHead);

    const textarea = document.createElement("textarea");
    textarea.className = "am-textarea review-note";
    textarea.maxLength = (state.options && state.options.noteLimit) || 4000;
    textarea.placeholder = "哪些值得保留？哪里可能没留住人？下一条准备验证什么？";
    textarea.dataset.reviewField = "note";
    textarea.value = state.noteDirty ? state.noteDraft : work.note || "";
    panel.append(textarea);
    panel.append(el("p", "review-panel-hint", "AI 建议需要自己核对；确认之前不会变成长期写作经验。"));
    const actions = el("div", "review-action-row");
    const save = button("am-primary-action", "保存并标记已复盘");
    save.dataset.reviewAction = "save-note";
    save.disabled = state.busy;
    actions.append(save);
    panel.append(actions);

    const suggestion = suggestionNode();
    if (suggestion) panel.append(suggestion);
    return panel;
  }

  function suggestionNode() {
    if (!state.suggestion && !state.suggestionError) return null;
    const box = el("div", "review-callout review-suggestion");
    if (state.suggestionError) {
      box.append(el("h4", "review-block-title", "AI 辅助复盘不可用"));
      box.append(el("p", "review-panel-hint", state.suggestionError));
      return box;
    }
    box.append(el("h4", "review-block-title", "AI 辅助复盘建议"));
    SUGGESTION_GROUPS.forEach((group) => {
      const items = state.suggestion[group.key] || [];
      if (!items.length) return;
      box.append(el("p", "review-suggestion-label", group.label));
      const list = el("ul", "review-suggestion-list");
      items.forEach((item) => list.append(el("li", "", item)));
      box.append(list);
    });
    box.append(el("p", "review-panel-hint", "以上内容不会自动写入笔记，需要自己判断后再保存。"));
    return box;
  }

  function renderActionTab(work) {
    const panel = document.createDocumentFragment();
    panel.append(el("p", "review-panel-hint", "每次复盘留下一项明确的行动，方便回头验证。"));

    const topicBox = el("div", "review-callout");
    topicBox.append(el("h4", "review-block-title", "继续验证这个方向"));
    topicBox.append(el("p", "review-panel-hint", "带上这条作品和复盘笔记，打开预填好的选题表单，由你确认后再保存。"));
    const topicAction = button("am-secondary-action", "加入选题计划");
    topicAction.dataset.reviewAction = "topic";
    topicAction.disabled = state.busy;
    topicBox.append(topicAction);
    panel.append(topicBox);

    const experienceBox = el("div", "review-callout");
    experienceBox.append(el("h4", "review-block-title", "沉淀可复用的经验"));
    experienceBox.append(el("p", "review-panel-hint", "把复盘笔记存成待确认经验，确认后才会用于后续写作。"));
    const experienceAction = button("am-secondary-action", "保存候选经验");
    experienceAction.dataset.reviewAction = "experience";
    experienceAction.disabled = state.busy;
    if (!String(work.note || "").trim()) experienceAction.disabled = true;
    experienceBox.append(experienceAction);
    if (!String(work.note || "").trim()) {
      experienceBox.append(el("p", "review-panel-hint", "先在「内容复盘」里写下笔记。"));
    }
    panel.append(experienceBox);
    return panel;
  }

  function renderDetail() {
    if (!TABS.some((tab) => tab.key === state.tab)) state.tab = "data";
    const work = state.detail && state.detail.id === state.selectedId ? state.detail : selectedWork();
    dom.detail.replaceChildren();
    if (!work) {
      const empty = el("div", "review-detail-empty");
      empty.append(el("h3", "review-block-title", "选择一条作品开始复盘"));
      empty.append(el("p", "review-panel-hint", "左侧点开任意作品，可以看它的数据、写下复盘。"));
      dom.detail.append(empty);
      return;
    }

    const head = el("div", "review-detail-head");
    const badge = el("span", "review-detail-badge" + (work.reviewedAt ? " is-done" : ""), work.reviewedAt ? "已复盘" : "待复盘");
    head.append(badge);
    head.append(el("h3", "review-detail-title", work.title || "未命名作品"));
    const meta = [
      work.publishedText ? work.publishedText + " 发布" : "",
      work.kind === "image" ? "图文" : work.durationText || "",
      work.collectedAt ? "数据采集于 " + formatStamp(work.collectedAt) : "",
    ]
      .filter(Boolean)
      .join(" · ");
    head.append(el("small", "review-detail-meta", meta));
    if (work.scriptId) {
      head.append(el("small", "review-detail-meta", "已关联脚本：" + (scriptTitle(work.scriptId) || "已删除的脚本")));
    }
    dom.detail.append(head);

    const tabs = el("div", "review-tabs");
    tabs.setAttribute("role", "tablist");
    TABS.forEach((tab) => {
      const node = button("review-tab" + (state.tab === tab.key ? " is-active" : ""), tab.label);
      node.setAttribute("role", "tab");
      node.setAttribute("aria-selected", state.tab === tab.key ? "true" : "false");
      node.dataset.reviewTab = tab.key;
      tabs.append(node);
    });
    dom.detail.append(tabs);

    const body = el("div", "review-detail-body");
    if (state.tab === "data") body.append(renderDataTab(work));
    else if (state.tab === "note") body.append(renderNoteTab(work));
    dom.detail.append(body);
    const suggestionMessage = el("p", "review-message review-suggestion-message");
    setMessage(suggestionMessage, state.message && state.tab === "note" ? state.message : "");
    dom.detail.append(suggestionMessage);
  }

  function render() {
    renderSyncState();
    renderNotice();
    renderSummary();
    renderTrendPanel();
    renderFactorPanel();
    renderFilters();
    renderWorkList();
    renderDetail();
  }

  // ------------------------------------------------------------------
  // 数据加载
  // ------------------------------------------------------------------

  async function loadReview({ silent = false } = {}) {
    const accountId = state.accountId;
    if (!accountId) {
      state.works = [];
      state.summary = null;
      state.config = null;
      state.detail = null;
      render();
      dom.subtitle.textContent = "先选择账号，再查看这个账号的作品表现";
      return;
    }
    const version = ++state.requestVersion;
    state.loading = true;
    if (!silent) setMessage(dom.listMessage, "正在读取复盘数据…");
    try {
      const payload = await api("/api/accounts/" + encodeURIComponent(accountId) + "/review");
      if (version !== state.requestVersion || !isSameAccount(accountId)) return;
      const completed = state.loaded && !payload.config?.running && (
        state.config?.running || payload.config?.lastSuccessAt !== state.config?.lastSuccessAt
      );
      window.reviewAccountModule?.updateFromOverview(accountId, payload.identity);
      state.config = payload.config || null;
      state.options = payload.options || null;
      state.works = Array.isArray(payload.works) ? payload.works : [];
      state.summary = payload.summary || null;
      state.scripts = payload.linkOptions && Array.isArray(payload.linkOptions.scripts) ? payload.linkOptions.scripts : [];
      // 首屏的默认口径可以用于首绘；用户切换到别的范围后，不能被这次返回的默认值覆盖。
      const trend = payload.trend;
      if (trend && (!state.trend || (Number(trend.days) === Number(state.trendDays) && trend.scope === state.trendScope))) {
        state.trend = trend;
        state.trendDetail = null;
      }
      const factors = payload.factors;
      if (
        factors &&
        (!state.factors ||
          (factors.dimension === state.factorDimension &&
            factors.metric === state.factorMetric &&
            Number(factors.rangeDays) === Number(state.factorRangeDays)))
      ) {
        state.factors = factors;
      }
      state.factorCatalog = payload.factorCatalog || state.factorCatalog;
      state.pendingFactorWorks = Array.isArray(payload.pendingFactorWorks) ? payload.pendingFactorWorks : [];
      state.loaded = true;
      if (!state.selectedId || !state.works.some((work) => work.id === state.selectedId)) {
        state.selectedId = state.works.length ? state.works[0].id : "";
        state.detail = null;
        state.noteDirty = false;
        state.suggestion = null;
        state.suggestionError = "";
      } else if (state.detail) {
        const refreshed = state.works.find((work) => work.id === state.detail.id);
        if (refreshed) state.detail = { ...state.detail, ...refreshed };
      }
      dom.subtitle.textContent = "从作品表现，找到下一条内容的方向";
      state.message = "";
      setMessage(dom.listMessage, "");
      if (completed) {
        await Promise.all([loadTrend({ silent: true }), loadFactors({ silent: true })]);
        if (!isSameAccount(accountId) || version !== state.requestVersion) return;
        if (state.selectedId && !state.noteDirty) await loadDetail(state.selectedId);
      }
    } catch (error) {
      if (version !== state.requestVersion || !isSameAccount(accountId)) return;
      setMessage(dom.listMessage, responseMessage(error, "复盘数据读取失败"), { error: true });
    } finally {
      if (version === state.requestVersion) state.loading = false;
    }
    render();
    schedulePoll();
  }

  async function loadDetail(workId) {
    const version = ++state.detailRequestVersion;
    try {
      const detail = await api("/api/review/works/" + encodeURIComponent(workId));
      if (version !== state.detailRequestVersion || state.selectedId !== workId) return;
      state.detail = detail;
      state.noteDirty = false;
      state.suggestion = null;
      state.suggestionError = "";
      render();
    } catch (error) {
      setMessage(dom.listMessage, responseMessage(error, "作品详情读取失败"), { error: true });
    }
  }

  function schedulePoll() {
    window.clearTimeout(state.pollTimer);
    const running = Boolean(state.config && state.config.running);
    if (!running || !state.accountId) return;
    const accountId = state.accountId;
    state.pollTimer = window.setTimeout(() => {
      if (!isSameAccount(accountId)) return;
      loadReview({ silent: true });
    }, POLL_INTERVAL_MS);
  }

  // ------------------------------------------------------------------
  // 操作
  // ------------------------------------------------------------------

  function guardNoteChange(next) {
    if (!state.noteDirty) {
      next();
      return;
    }
    const proceed = window.confirm("当前作品的复盘笔记还没有保存，继续会丢失刚才的修改。");
    if (!proceed) return;
    state.noteDirty = false;
    state.noteDraft = "";
    next();
  }

  function selectWork(workId) {
    if (workId === state.selectedId) return;
    guardNoteChange(() => {
      state.selectedId = workId;
      state.detail = null;
      state.suggestion = null;
      state.suggestionError = "";
      state.tab = "data";
      render();
      loadDetail(workId);
    });
  }

  async function syncNow() {
    if (!state.accountId || state.busy || state.syncPhase || state.config?.running) return;
    const accountId = state.accountId;
    state.syncFeedback = null;
    state.syncPhase = "checking";
    render();
    try {
      const login = await api("/api/accounts/" + encodeURIComponent(accountId) + "/publish-status?platform=douyin");
      if (!isSameAccount(accountId)) return;
      if (login.status !== "logged_in") {
        const loginRequired = ["login_required", "unbound"].includes(login.status);
        state.syncFeedback = {
          text: loginRequired ? "尚未登录抖音，请先授权抖音账号后再同步。" : "暂时无法确认抖音登录状态，请稍后重试。",
          loginRequired,
        };
        return;
      }
      state.syncPhase = "starting";
      render();
      await api("/api/accounts/" + encodeURIComponent(accountId) + "/review/collect", { method: "POST" });
      if (!isSameAccount(accountId)) return;
      await loadReview({ silent: true });
    } catch (error) {
      if (isSameAccount(accountId)) state.syncFeedback = { text: responseMessage(error, "采集启动失败") };
    } finally {
      if (isSameAccount(accountId)) {
        state.syncPhase = "";
        render();
      }
    }
  }

  async function openLogin() {
    if (!state.accountId || state.loginOpening) return;
    const accountId = state.accountId;
    state.loginOpening = true;
    render();
    try {
      await api("/api/accounts/" + encodeURIComponent(accountId) + "/publish-login", {
        method: "POST",
        body: { platform: "douyin" },
      });
      if (isSameAccount(accountId)) state.syncFeedback = { text: "已打开授权页面，请登录抖音后重新同步。" };
    } catch (error) {
      if (isSameAccount(accountId)) state.syncFeedback = { text: responseMessage(error, "打开登录失败"), loginRequired: true };
    } finally {
      if (isSameAccount(accountId)) {
        state.loginOpening = false;
        render();
      }
    }
  }

  async function saveNote() {
    const work = state.detail || selectedWork();
    if (!work || state.busy) return;
    const textarea = dom.detail.querySelector('[data-review-field="note"]');
    const note = textarea ? textarea.value : "";
    state.busy = true;
    try {
      const saved = await api("/api/review/works/" + encodeURIComponent(work.id) + "/note", {
        method: "PUT",
        body: { note, reviewed: true },
      });
      state.detail = { ...saved, snapshots: saved.snapshots || [] };
      state.noteDirty = false;
      state.noteDraft = "";
      state.works = state.works.map((item) => (item.id === saved.id ? { ...item, ...saved } : item));
      showToast("复盘笔记已保存", "success");
      await loadReview({ silent: true });
    } catch (error) {
      showToast(responseMessage(error, "复盘笔记保存失败"), "error");
    } finally {
      state.busy = false;
      render();
    }
  }

  async function linkScript(scriptId) {
    const work = state.detail || selectedWork();
    if (!work || state.busy) return;
    state.busy = true;
    try {
      const saved = await api("/api/review/works/" + encodeURIComponent(work.id) + "/script", {
        method: "PUT",
        body: { scriptId },
      });
      state.detail = { ...saved, snapshots: saved.snapshots || [] };
      state.works = state.works.map((item) => (item.id === saved.id ? { ...item, ...saved } : item));
      showToast(scriptId ? "已关联脚本" : "已取消关联", "success");
    } catch (error) {
      showToast(responseMessage(error, "关联脚本失败"), "error");
    } finally {
      state.busy = false;
      render();
    }
  }

  async function suggest() {
    const work = state.detail || selectedWork();
    if (!work || state.busy) return;
    state.busy = true;
    state.suggestionError = "";
    render();
    try {
      const payload = await api("/api/review/works/" + encodeURIComponent(work.id) + "/suggest", { method: "POST" });
      state.suggestion = payload.suggestions || null;
    } catch (error) {
      state.suggestion = null;
      state.suggestionError = responseMessage(error, "AI 辅助复盘失败");
    } finally {
      state.busy = false;
      render();
    }
  }

  async function addToTopics() {
    const work = state.detail || selectedWork();
    if (!work || state.busy) return;
    state.busy = true;
    try {
      const payload = await api("/api/review/works/" + encodeURIComponent(work.id) + "/topic-draft", {
        method: "POST",
        body: {},
      });
      const fields = payload.fields || {};
      const topics = window.topicsModule;
      if (!topics || !topics.dom) {
        showToast("选题模块还没有加载，请先打开选题页", "error");
        return;
      }
      topics.dom.title.value = fields.title || "";
      topics.dom.outline.value = fields.outline || "";
      topics.dom.materials.value = fields.materials || "";
      topics.actions?.setPickerValue?.("category", fields.category || "test");
      topics.actions?.setPickerValue?.("format", fields.format || "video");
      window.selectWorkspaceModule?.("topics");
      showToast("已预填选题表单，确认后再保存", "success");
    } catch (error) {
      showToast(responseMessage(error, "生成选题草稿失败"), "error");
    } finally {
      state.busy = false;
      render();
    }
  }

  async function saveExperience() {
    const work = state.detail || selectedWork();
    if (!work || state.busy) return;
    state.busy = true;
    try {
      await api("/api/review/works/" + encodeURIComponent(work.id) + "/experience", { method: "POST" });
      showToast("已存为待确认经验，确认后才会用于写作", "success");
    } catch (error) {
      showToast(responseMessage(error, "保存候选经验失败"), "error");
    } finally {
      state.busy = false;
      render();
    }
  }

  // ------------------------------------------------------------------
  // 采集设置弹窗
  // ------------------------------------------------------------------

  function setModalOpen(open) {
    const modal = dom.configModal;
    modal.hidden = !open;
    document.body.classList.toggle("is-modal-open", !modal.hidden);
    if (!open) closePickers();
    if (open) {
      const config = state.config || {};
      const options = state.options || {};
      dom.configEnabled.checked = Boolean(config.enabled);
      pickers.mode?.setValue(config.mode || "interval", { silent: true });
      pickers.interval?.renderOptions();
      pickers.interval?.setValue(String(config.intervalMinutes || (options.defaultIntervalMinutes ?? 60)), { silent: true });
      dom.configDailyTime.value = config.dailyTime || (options.defaultDailyTime || "12:30");
      pickers.scope?.setValue(config.scope || (options.defaultScope || "recent30"), { silent: true });
      dom.configHint.textContent = [options.platformUpdateNote, options.collectionNote].filter(Boolean).join("");
      setMessage(dom.configMessage, "");
      syncConfigControls();
      dom.configSave.focus();
    }
  }

  function syncConfigControls() {
    const isDaily = (pickers.mode ? pickers.mode.value() : dom.configMode.value) === "daily";
    // 关闭「定时采集」后，下面的采集方式和范围都不再生效，整体灰态且不可操作。
    const collectOn = Boolean(dom.configEnabled.checked);
    const intervalOn = collectOn && !isDaily;
    const dailyOn = collectOn && isDaily;
    if (pickers.interval) {
      pickers.interval.control.disabled = !intervalOn;
      pickers.interval.menu.hidden = true;
    }
    if (pickers.mode) pickers.mode.control.disabled = !collectOn;
    if (pickers.scope) pickers.scope.control.disabled = !collectOn;
    if (!collectOn) {
      pickers.mode?.close();
      pickers.scope?.close();
    }
    dom.configInterval.disabled = !intervalOn;
    dom.configDailyTime.disabled = !dailyOn;
    dom.configScope.disabled = !collectOn;
    setConfigRowOff(dom.configMode, !collectOn);
    setConfigRowOff(dom.configInterval, !intervalOn);
    setConfigRowOff(dom.configDailyTime, !dailyOn);
    setConfigRowOff(dom.configScope, !collectOn);
  }

  function setConfigRowOff(input, off) {
    if (!input || typeof input.closest !== "function") return;
    input.closest(".review-config-row")?.classList?.toggle?.("is-off", off);
  }

  async function saveConfig() {
    if (window.WorkbenchDateTimePicker?.validateInputs(dom.configDailyTime) === false) return;
    if (state.busy) return;
    state.busy = true;
    try {
      const config = await api("/api/accounts/" + encodeURIComponent(state.accountId) + "/review/config", {
        method: "PUT",
        body: {
          enabled: dom.configEnabled.checked,
          mode: pickers.mode ? pickers.mode.value() : dom.configMode.value,
          intervalMinutes: Number(pickers.interval ? pickers.interval.value() : dom.configInterval.value),
          dailyTime: dom.configDailyTime.value,
          scope: pickers.scope ? pickers.scope.value() : dom.configScope.value,
        },
      });
      state.config = config;
      setModalOpen(false);
      showToast(config.enabled ? "已保存，自动采集按设置执行" : "已保存，自动采集关闭", "success");
      await loadReview({ silent: true });
    } catch (error) {
      setMessage(dom.configMessage, responseMessage(error, "采集设置保存失败"), { error: true });
    } finally {
      state.busy = false;
      render();
    }
  }

  // ------------------------------------------------------------------
  // 事件
  // ------------------------------------------------------------------

  root.addEventListener("click", (event) => {
    const filter = event.target.closest("[data-review-filter]");
    const trendDays = event.target.closest("[data-review-trend-days]");
    if (trendDays) {
      state.trendDays = Number(trendDays.dataset.reviewTrendDays) || 30;
      state.trendDetail = null;
      state.trend = null;
      renderTrendPanel();
      loadTrend({ silent: true });
      return;
    }
    const trendScope = event.target.closest("[data-review-trend-scope]");
    if (trendScope) {
      state.trendScope = trendScope.dataset.reviewTrendScope === "tracked" ? "tracked" : "account";
      state.trendDetail = null;
      state.trend = null;
      renderTrendPanel();
      loadTrend({ silent: true });
      return;
    }
    const trendDay = event.target.closest("[data-review-trend-day]");
    if (trendDay) {
      loadTrendDay(trendDay.dataset.reviewTrendDay);
      return;
    }
    if (event.target.closest("[data-review-trend-close]")) {
      state.trendDetail = null;
      renderTrendPanel();
      return;
    }
    const factorDimension = event.target.closest("[data-review-factor-dimension]");
    if (factorDimension) {
      state.factorDimension = factorDimension.dataset.reviewFactorDimension || "hook";
      state.factorGroup = "";
      state.factors = null;
      renderFactorPanel();
      loadFactors({ silent: true });
      return;
    }
    const factorRange = event.target.closest("[data-review-factor-range]");
    if (factorRange) {
      state.factorRangeDays = Number(factorRange.dataset.reviewFactorRange) || 30;
      state.factorGroup = "";
      state.factors = null;
      renderFactorPanel();
      loadFactors({ silent: true });
      return;
    }
    const factorGroup = event.target.closest("[data-review-factor-group]");
    if (factorGroup) {
      const name = factorGroup.dataset.reviewFactorGroup || "";
      state.factorGroup = state.factorGroup === name ? "" : name;
      renderFactorPanel();
      return;
    }
    if (event.target.closest("[data-review-factor-group-close]")) {
      state.factorGroup = "";
      renderFactorPanel();
      return;
    }

    if (filter) {
      state.filter = filter.dataset.reviewFilter;
      render();
      return;
    }
    const workNode = event.target.closest("[data-review-work]");
    if (workNode) {
      selectWork(workNode.dataset.reviewWork);
      return;
    }
    const tab = event.target.closest("[data-review-tab]");
    if (tab) {
      state.tab = tab.dataset.reviewTab;
      render();
      return;
    }
    const action = event.target.closest("[data-review-action]");
    if (action) {
      const kind = action.dataset.reviewAction;
      if (kind === "save-note") saveNote();
      else if (kind === "suggest") suggest();
      else if (kind === "topic") addToTopics();
      else if (kind === "experience") saveExperience();
      return;
    }
    const noticeAction = event.target.closest("[data-review-notice-action]");
    if (noticeAction) {
      if (noticeAction.dataset.reviewNoticeAction === "login") openLogin();
    }
  });

  dom.detail.addEventListener("input", (event) => {
    const field = event.target.closest('[data-review-field="note"]');
    if (!field) return;
    state.noteDirty = true;
    state.noteDraft = field.value;
  });

  dom.detail.addEventListener("change", (event) => {
    const field = event.target.closest('[data-review-field="script"]');
    if (field) linkScript(field.value);
  });

  dom.search.addEventListener("input", () => {
    state.search = dom.search.value;
    renderWorkList();
    renderFilters();
  });

  dom.syncButton.addEventListener("click", syncNow);
  // 趋势图按容器宽度重绘：宽度变化就重新计算坐标，不做整体缩放。
  function watchTrendChart() {
    if (!dom.trendChart || typeof ResizeObserver !== "function") return;
    let last = 0;
    const observer = new ResizeObserver((entries) => {
      const entry = entries && entries[0];
      const width = Math.round((entry && entry.contentRect ? entry.contentRect.width : 0) || 0);
      if (!width || Math.abs(width - last) < 2) return;
      last = width;
      drawTrendChart();
    });
    observer.observe(dom.trendChart);
  }

  if (dom.factorPending) {
    dom.factorPending.addEventListener("click", () => openFactorModal());
  }
  if (dom.factorCancel) dom.factorCancel.addEventListener("click", () => setFactorModalOpen(false));
  if (dom.factorSave) dom.factorSave.addEventListener("click", () => saveFactorWork());
  if (dom.factorAi) dom.factorAi.addEventListener("click", () => suggestFactorWork());
  if (dom.factorModal) {
    dom.factorModal.addEventListener("click", (event) => {
      if (event.target === dom.factorModal) setFactorModalOpen(false);
    });
  }
  watchTrendChart();


  dom.configButton.addEventListener("click", () => setModalOpen(true));
  dom.configCancel.addEventListener("click", () => setModalOpen(false));
  dom.configSave.addEventListener("click", saveConfig);
  dom.configMode.addEventListener("change", syncConfigControls);
  dom.configEnabled.addEventListener("change", syncConfigControls);
  dom.configModal.addEventListener("click", (event) => {
    if (event.target === dom.configModal) setModalOpen(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (dom.factorModal && !dom.factorModal.hidden) {
      event.preventDefault();
      setFactorModalOpen(false);
      return;
    }
    if (!dom.configModal.hidden) {
      event.preventDefault();
      if (openPickerKey) closePickers();
      else setModalOpen(false);
    }
  });
  document.addEventListener("click", (event) => {
    if (!openPickerKey) return;
    const target = event.target;
    const inside =
      target &&
      typeof target.closest === "function" &&
      (target.closest(".review-config-row") || target.closest("[data-review-picker]"));
    if (!inside) closePickers();
  });

  function onAccountChange(accountId) {
    const next = String(accountId || "");
    if (next === state.accountId) return;
    window.clearTimeout(state.pollTimer);
    state.accountId = next;
    state.syncPhase = "";
    state.syncFeedback = null;
    state.loginOpening = false;
    window.reviewAccountModule?.onAccountChange(next);
    state.loaded = false;
    state.works = [];
    state.summary = null;
    state.config = null;
    state.selectedId = "";
    state.detail = null;
    state.noteDirty = false;
    state.suggestion = null;
    state.suggestionError = "";
    state.message = "";
    state.trend = null;
    state.trendDetail = null;
    state.trendMessage = "";
    state.trendMessageError = false;
    state.trendDays = 30;
    state.trendScope = "account";
    state.factors = null;
    state.factorGroup = "";
    state.factorWork = null;
    state.factorSelection = null;
    state.pendingFactorWorks = [];
    state.factorMessage = "";
    state.factorMessageError = false;
    render();
    if (next && !root.hidden) loadReview();
  }

  window.addEventListener("workspace-module-change", (event) => {
    if (event?.detail?.module !== "review") {
      if (state.noteDirty) {
        const save = window.confirm("复盘笔记还没有保存，要现在保存吗？");
        if (save) saveNote();
        else {
          state.noteDirty = false;
          state.noteDraft = "";
        }
      }
      window.clearTimeout(state.pollTimer);
      return;
    }
    if (state.accountId) loadReview({ silent: state.loaded });
    schedulePoll();
  });

  window.addEventListener("focus", () => {
    if (state.accountId && !root.hidden && state.config && state.config.running) loadReview({ silent: true });
  });

  // app.js reports every account switch so the review page follows the active account.
  window.reviewModule = {
    onAccountChange,
    refresh: () => loadReview({ silent: true }),
    state,
    helpers: { formatMetric, formatStamp, metricFieldsFor, formatFactorValue, shortDate },
    actions: {
      async openAdviceWork(workId, accountId) {
        if (state.accountId !== accountId) return;
        await loadReview({ silent: true });
        if (state.accountId !== accountId) return;
        selectWork(workId);
      },
      loadReview,
      loadDetail,
      syncNow,
      saveNote,
      linkScript,
      suggest,
      addToTopics,
      saveExperience,
      setModalOpen,
      saveConfig,
      loadTrend,
      loadTrendDay,
      loadFactors,
      openFactorModal,
      loadFactorWork,
      saveFactorWork,
      suggestFactorWork,
    },
    dom,
  };

  Object.keys(PICKER_CONFIGS).forEach((key) => {
    const picker = createPicker(key);
    if (picker) pickers[key] = picker;
  });

  render();
})();
