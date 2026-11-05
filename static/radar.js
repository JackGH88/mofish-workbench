/* 雷达（radar）：按行业关键词持续发现近期视频、低粉爆款与趋势，并生成 AI 选题建议。
   Visibility is owned by workspace-navigation.js; this file owns data, rendering and edits.
   采集是服务端行为：定时任务按关键词在后台跑，这里只展示状态并触发手动更新。 */
(() => {
  const root = document.getElementById("radarContent");
  if (!root) return;

  const TABS = [
    { key: "all", label: "全部" },
    { key: "latest", label: "最新视频" },
    { key: "lowfans", label: "低粉爆款" },
  ];
  const FILTERS = [
    { key: "all", label: "全部状态" },
    { key: "unread", label: "未读" },
    { key: "saved", label: "已收藏" },
  ];
  const LIKE_RANGES = [
    { key: "all", label: "不限", min: 0, max: null },
    { key: "0-49", label: "0–49", min: 0, max: 49 },
    { key: "50-99", label: "50–99", min: 50, max: 99 },
    { key: "100-299", label: "100–299", min: 100, max: 299 },
    { key: "300-499", label: "300–499", min: 300, max: 499 },
    { key: "500-999", label: "500–999", min: 500, max: 999 },
    { key: "1000-plus", label: "1千及以上", min: 1000, max: null },
  ];
  const DAYS = [
    { key: "today", label: "今天" },
    { key: "yesterday", label: "昨天" },
    { key: "7d", label: "近 7 天" },
    { key: "30d", label: "近 30 天" },
    { key: "all", label: "全部日期" },
  ];
  const TOPIC_WEEKS = [
    { key: "current", label: "本周选题" },
    { key: "next", label: "下周选题" },
  ];
  const TOPIC_CATEGORIES = [
    { key: "highlight", label: "重点" },
    { key: "daily", label: "日常" },
    { key: "series", label: "系列" },
    { key: "test", label: "测试" },
  ];
  const TOPIC_FORMATS = [
    { key: "video", label: "视频" },
    { key: "article", label: "图文" },
  ];
  const TAB_HINTS = {
    all: "全部来源的采集作品，按发布时间排序并去重展示。",
    latest: "按关键词收集的视频，按所选发布时间范围展示。",
    lowfans: "近 7 天平台标记的低粉高互动作品。",
  };
  const EMPTY_HINTS = {
    today: "今天还没有新的发现。",
    yesterday: "昨天没有采集到作品。",
    "7d": "最近 7 天没有发现作品。",
    "30d": "最近 30 天没有发现作品。",
    all: "还没有采集到作品。",
  };
  // 只有「最新视频」支持按发布时间继续翻页；低粉爆款接口不支持翻页。
  const POLL_INTERVAL_MS = 5000;
  // 顶部「已开始更新…」是一次性加载提示，必须能被可靠地收掉，否则会一直悬停。
  // 完成判定不能只看轮询里是否观察到「进行中」：采集可能在第一次轮询前就结束，
  // 那样永远等不到状态翻转。所以同时看目标是否真的推进过，并留一个兜底超时。
  const UPDATE_TIMEOUT_MS = 180000;
  const WORK_BATCH_ROWS = 4;
  const WORK_MAX_BATCH = 50;

  const state = {
    accountId: "",
    overview: null,
    settings: { collectEnabled: true, aiEnabled: true, aiDailyTime: "10:30" },
    group: "all",
    tab: "all",
    day: "all",
    likesRange: "all",
    keywordIds: [],
    view: "cover",
    filter: "all",
    page: 1,
    works: null,
    worksKey: "",
    worksLoading: false,
    worksError: "",
    worksRetryAppend: false,
    trendRows: [],
    suggestionKeywordId: "",
    detailWorkId: "",
    topicTarget: null,
    aiExpanded: false,
    keywordsExpanded: false,
    loaded: false,
    pollTimer: 0,
    updateWatch: null,
  };

  const dom = {
    statusText: document.getElementById("radarStatusText"),
    syncButton: document.getElementById("radarSyncButton"),
    syncLabel: document.getElementById("radarSyncLabel"),
    notice: document.getElementById("radarNotice"),
    settingsButton: document.getElementById("radarSettingsButton"),
    addKeywordButton: document.getElementById("radarAddKeywordButton"),
    keywordFilters: document.getElementById("radarKeywordFilters"),
    dayTabs: document.getElementById("radarDayTabs"),
    likesTabs: document.getElementById("radarLikesTabs"),
    filterTabs: document.getElementById("radarFilterTabs"),
    viewTabs: document.getElementById("radarViewTabs"),
    workCount: document.getElementById("radarWorkCount"),
    keywordList: document.getElementById("radarKeywordList"),
    keywordMore: document.getElementById("radarKeywordMoreButton"),
    keywordMoreFooter: document.getElementById("radarKeywordMoreFooter"),
    keywordMeta: document.getElementById("radarKeywordMeta"),
    keywordMessage: document.getElementById("radarKeywordMessage"),
    suggestionRow: document.getElementById("radarSuggestionRow"),
    suggestionList: document.getElementById("radarSuggestionList"),
    aiAutoTag: document.getElementById("radarAiAutoTag"),
    aiMeta: document.getElementById("radarAiMeta"),
    aiEvidence: document.getElementById("radarAiEvidenceButton"),
    aiUpdate: document.getElementById("radarAiUpdateButton"),
    aiUpdateLabel: document.getElementById("radarAiUpdateLabel"),
    aiList: document.getElementById("radarRecommendations"),
    aiMessage: document.getElementById("radarAiMessage"),
    aiMore: document.getElementById("radarAiMoreButton"),
    tabs: document.getElementById("radarTabs"),
    feedHint: document.getElementById("radarFeedHint"),
    workList: document.getElementById("radarWorkList"),
    feedMessage: document.getElementById("radarFeedMessage"),
    feedTotal: document.getElementById("radarFeedTotal"),
    moreFooter: document.getElementById("radarLoadMoreFooter"),
    moreButton: document.getElementById("radarLoadMoreButton"),
    trendList: document.getElementById("radarTrendList"),
    trendMeta: document.getElementById("radarTrendMeta"),
    trendMessage: document.getElementById("radarTrendMessage"),
  };

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
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
    node.classList.add("radar-relogin");
    node.addEventListener("click", (event) => {
      if (event && typeof event.stopPropagation === "function") event.stopPropagation();
      if (window.accountModule && typeof window.accountModule.openLogin === "function") window.accountModule.openLogin();
    });
    return node;
  }

  async function readJson(response) {
    let payload = null;
    try {
      payload = await response.json();
    } catch (_error) {
      payload = null;
    }
    if (!response.ok) {
      const detail = payload && payload.detail ? payload.detail : payload;
      // 只展示后端给的中性文案，不回落到可能带上游名字的错误码。
      const message = (detail && detail.message) || "请求失败";
      const error = new Error(String(message));
      error.code = detail && detail.code ? String(detail.code) : "";
      throw error;
    }
    return payload;
  }

  async function api(url, options) {
    const settings = options || {};
    const request = { method: settings.method || "GET" };
    if (settings.body !== undefined && settings.body !== null) {
      request.headers = { "Content-Type": "application/json" };
      request.body = JSON.stringify(settings.body);
    }
    return readJson(await fetch(url, request));
  }

  function accountQuery(extra) {
    const params = new URLSearchParams({ accountId: state.accountId });
    Object.entries(extra || {}).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
    });
    return params.toString();
  }

  function formatCount(value) {
    if (value === null || value === undefined || value === "") return "—";
    const number = Number(value);
    if (!Number.isFinite(number)) return "—";
    if (number >= 10000) {
      const wan = number / 10000;
      return `${wan >= 100 ? Math.round(wan) : wan.toFixed(1)} 万`;
    }
    return number.toLocaleString("zh-CN");
  }

  function formatTrendScore(value) {
    const number = Number(value);
    if (value === "" || !Number.isFinite(number)) return "—";
    if (number >= 100000000) return `${Number((number / 100000000).toFixed(1))}亿`;
    if (number >= 10000) return `${Number((number / 10000).toFixed(1))}万`;
    return number.toLocaleString("zh-CN");
  }

  function showToast(message, type) {
    if (typeof window.showToast === "function" && window.showToast !== showToast) {
      window.showToast(message, type || "info");
      return;
    }
    setMessage(dom.notice, message, type === "error");
  }

  // ------------------------------------------------------------ pickers
  // 项目约定：页面不使用原生 select；值放在隐藏 input 里，样式复用选题模块的浮层。

  const pickers = {};
  const pickerOrder = [];
  let openPicker = "";

  function createPicker(key, config) {
    const input = document.getElementById(config.input);
    const host = document.querySelector(`[data-radar-picker="${key}"] .topics-select-control`);
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

    const options = () => (typeof config.options === "function" ? config.options() : config.options || []);
    const labelFor = (raw) => {
      const match = options().find((entry) => String(entry[0]) === String(raw));
      return match ? String(match[1]) : String(raw || "");
    };

    const picker = {
      input,
      labelFor,
      render() {
        menu.replaceChildren();
        options().forEach(([optionValue, optionLabel]) => {
          const item = el("button", "topics-select-option", optionLabel);
          item.type = "button";
          item.dataset.value = String(optionValue);
          item.setAttribute("role", "menuitemradio");
          item.setAttribute("aria-checked", String(String(optionValue) === String(input.value)));
          item.classList.toggle("is-active", String(optionValue) === String(input.value));
          item.addEventListener("click", () => {
            picker.set(optionValue);
            picker.close();
            control.focus();
          });
          menu.append(item);
        });
      },
      set(next, options2) {
        input.value = String(next);
        value.textContent = labelFor(next);
        if (!(options2 && options2.silent)) {
          config.onChange?.(String(next));
        }
        picker.render();
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
    control.addEventListener("click", (event) => {
      event.stopPropagation();
      if (menu.hidden) picker.open();
      else picker.close();
    });
    control.addEventListener("keydown", (event) => {
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

  document.addEventListener("click", () => closePickers());
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closePickers();
      closeModals();
    }
  });

  // ------------------------------------------------------------ modals

  let pendingTrendSubscription = null;
  let trendSubscriptionSubmitting = false;
  const modals = {
    manageKeywords: document.getElementById("radarManageKeywordsModal"),
    trends: document.getElementById("radarTrendsModal"),
    trendSubscribe: document.getElementById("radarTrendSubscribeModal"),
    keyword: document.getElementById("radarKeywordModal"),
    settings: document.getElementById("radarSettingsModal"),
    detail: document.getElementById("radarDetailModal"),
    topic: document.getElementById("radarTopicModal"),
    analysis: document.getElementById("radarAnalysisModal"),
  };

  function openModal(modal) {
    if (modal) modal.hidden = false;
  }

  let detailRequest = 0;
  let analysisReturnFocus = null;
  document.getElementById("radarAnalysisModal")?.addEventListener("keydown", event => {
    if (event.key !== "Tab") return;
    const modal = document.getElementById("radarAnalysisModal");
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
    pendingTrendSubscription = null;
    Object.values(modals).forEach((modal) => {
      if (modal) modal.hidden = true;
    });
  }

  Object.values(modals).forEach((modal) => {
    if (!modal) return;
    modal.addEventListener("click", (event) => {
      if (event.target === modal) closeModals();
    });
  });

  // ------------------------------------------------------------ data

  function keywordsById() {
    const map = new Map();
    (state.overview?.keywords || []).forEach((keyword) => map.set(keyword.id, keyword));
    return map;
  }

  function isRunning() {
    const keywords = state.overview?.keywords || [];
    const collecting = keywords.some((keyword) => ["queued", "running"].includes(keyword.collection?.status));
    const aiRunning = state.overview?.recommendation?.job?.status === "running";
    return { collecting, aiRunning, busy: collecting || aiRunning };
  }

  let viewRevision = 0;
  let overviewRequest = 0;
  let worksRequest = 0;
  let billingTimer = 0;
  let initialLoad = null;
  const COVER_DIMENSIONS_KEY = "radar.coverDimensions.v1";
  const coverDimensions = readCoverDimensions();
  let coverCacheTimer = 0;

  function readCoverDimensions() {
    const cache = new Map();
    try {
      const entries = JSON.parse(window.sessionStorage?.getItem(COVER_DIMENSIONS_KEY) || "[]");
      if (Array.isArray(entries)) entries.slice(-128).forEach(entry => {
        if (!Array.isArray(entry)) return;
        const [src, size] = entry;
        if (typeof src === "string" && /^\/api\/radar\/covers\/\d+$/.test(src)
            && size && Number.isFinite(size.width) && Number.isFinite(size.height)
            && size.width > 0 && size.height > 0 && size.width <= 32768 && size.height <= 32768) cache.set(src, size);
      });
    } catch (_) { /* Cover sizing is optional when browser storage is unavailable. */ }
    return cache;
  }

  function rememberCoverDimensions(src, width, height) {
    const previous = coverDimensions.get(src);
    if (previous?.width === width && previous?.height === height) return;
    coverDimensions.delete(src);
    coverDimensions.set(src, { width, height });
    while (coverDimensions.size > 128) coverDimensions.delete(coverDimensions.keys().next().value);
    if (!/^\/api\/radar\/covers\/\d+$/.test(src)) return;
    window.clearTimeout(coverCacheTimer);
    coverCacheTimer = window.setTimeout(() => {
      try {
        const entries = Array.from(coverDimensions).filter(([key]) => /^\/api\/radar\/covers\/\d+$/.test(key));
        window.sessionStorage?.setItem(COVER_DIMENSIONS_KEY, JSON.stringify(entries));
      } catch (_) { /* Keep the in-memory cache even if storage is disabled/full. */ }
    }, 0);
  }

  function setInitialLoading(loading) {
    root.classList.toggle("is-initial-loading", loading);
    root.setAttribute("aria-busy", String(loading));
    [".radar-directions", ".radar-feed-actions"].forEach(selector => {
      const controls = root.querySelector(selector);
      if (controls) controls.inert = loading;
    });
    const indicator = document.getElementById("radarLoadingState");
    if (indicator) indicator.hidden = !loading;
  }

  async function prepareInitialCovers() {
    const images = Array.from(dom.workList?.querySelectorAll("img") || []).slice(0, 8);
    if (!images.length) return;
    let timer;
    const decoded = Promise.all(images.map(image => {
      image.loading = "eager";
      return typeof image.decode === "function" ? image.decode().catch(() => {}) : Promise.resolve();
    }));
    try {
      await Promise.race([decoded, new Promise(resolve => { timer = window.setTimeout(resolve, 600); })]);
    } finally { window.clearTimeout(timer); }
  }

  function scheduleBillingRefresh(revision, delay) {
    window.clearTimeout(billingTimer);
    billingTimer = window.setTimeout(() => {
      if (revision !== viewRevision || root.hidden || document.hidden) return;
      loadOverview({ silent: true }).catch(() => {});
    }, delay);
  }

  async function loadOverview(options) {
    const settings = options || {};
    const revision = viewRevision;
    const request = ++overviewRequest;
    const accountId = state.accountId;
    const previous = state.overview;
    let overview;
    try {
      overview = await api(`/api/radar/overview?${accountQuery()}`);
    } catch (error) {
      if (revision !== viewRevision || request !== overviewRequest) return null;
      state.overview = { ...(state.overview || {}), usage: { ...(state.overview?.usage || {}), syncStatus: "error" } };
      renderStatus();
      scheduleBillingRefresh(revision, 15000);
      throw error;
    }
    if (revision !== viewRevision || request !== overviewRequest || accountId !== state.accountId) return null;
    if (overview.accountId && overview.accountId !== accountId) return null;
    state.overview = overview;
    if (settings.silent !== true) render();
    else renderStatusOnly(previous);
    scheduleBillingRefresh(revision, overview.usage?.syncStatus === "syncing" ? 1500 : 15000);
    return state.overview;
  }

  function renderStatusOnly() {
    renderStatus();
    renderKeywords();
  }

  function workBatchSize() {
    if (state.view === "list") return WORK_BATCH_ROWS;
    const available = dom.workList?.clientWidth;
    const columns = available ? Math.max(1, Math.floor((available + 18) / 218)) : 4;
    return Math.min(WORK_MAX_BATCH, columns * WORK_BATCH_ROWS);
  }

  async function loadWorks(options = {}) {
    const key = JSON.stringify([state.accountId, state.tab, state.day, state.likesRange, state.filter, [...state.keywordIds].sort()]);
    const same = state.worksKey === key && state.works;
    const append = options.append === true;
    if (append && (state.worksLoading || !same || !state.works.hasMore)) return;
    const revision = viewRevision;
    const request = ++worksRequest;
    const likesRange = LIKE_RANGES.find(option => option.key === state.likesRange);
    const original = same ? state.works : null;
    const refreshPrefix = Boolean(same && !options.reset && !append);
    const batch = workBatchSize();
    let offset = append ? original.nextOffset : 0;
    // Refresh the loaded prefix in place; polling and business actions must not collapse it.
    const target = append ? offset + batch : same && !options.reset ? (original.nextOffset || batch) : batch;
    const received = [];
    let data, hasMore = false;
    state.worksLoading = true;
    state.worksError = "";
    renderLoadMore();
    try {
      do {
        const size = Math.min(WORK_MAX_BATCH, Math.max(1, target - offset));
        data = await api(`/api/radar/works?${accountQuery({
          tab: state.tab, day: state.day, minLikes: likesRange.min, maxLikes: likesRange.max,
          filter: state.filter, keywordIds: state.keywordIds.join(","), page: 1,
          offset, pageSize: size,
        })}`);
        if (revision !== viewRevision || request !== worksRequest) return;
        const rows = data.items || [];
        received.push(...rows);
        const next = Number.isFinite(data.nextOffset) ? data.nextOffset : offset + rows.length;
        hasMore = rows.length > 0 && next > offset && (data.hasMore ?? next < Number(data.total || 0));
        offset = next;
      } while (refreshPrefix && offset < target && hasMore);
      const unique = new Map((append ? original.items : []).map(work => [work.id, work]));
      received.forEach(work => unique.set(work.id, work));
      state.works = { ...data, items: [...unique.values()], nextOffset: offset, hasMore };
      state.worksKey = key;
      renderWorks();
    } catch (error) {
      if (revision !== viewRevision || request !== worksRequest) return;
      state.worksError = error.message;
      state.worksRetryAppend = append;
      throw error;
    } finally {
      if (revision === viewRevision && request === worksRequest) {
        state.worksLoading = false;
        renderLoadMore();
        scheduleWorkLayout();
      }
    }
  }

  async function loadMoreWorks(manual = false) {
    if (state.worksLoading || root.hidden || !state.accountId) return;
    if (manual && !state.loaded) { await loadAll(); return; }
    if (!state.loaded || (!manual && state.worksError)) return;
    const retry = Boolean(state.worksError);
    if (!retry && !state.works?.hasMore) return;
    try { await loadWorks({ append: retry ? state.worksRetryAppend : true }); }
    catch (_) { /* Keep existing cards; the footer offers an explicit retry. */ }
  }

  // ------------------------------------------------------------ render

  function render() {
    renderStatus();
    renderKeywords();
    renderRecommendations();
    renderTrains();
  }


  /* 682.500 -> 682.5：界面只保留有效小数位。 */
  function trimPoints(value) {
    let text = String(value === null || value === undefined ? "0" : value).trim();
    if (text.indexOf(".") < 0) return text || "0";
    while (text.endsWith("0")) text = text.slice(0, -1);
    if (text.endsWith(".")) text = text.slice(0, -1);
    return text || "0";
  }

  function renderStatus() {
    const overview = state.overview || {};
    const usage = overview.usage || {};
    const syncText = String(overview.lastSuccessText || "").trim();
    const syncParts = syncText.match(/^(.*?)\s+(\d{2}:\d{2})$/);
    const cost = usage.chargedTotalPoints;
    const checking = !state.overview || usage.syncStatus === "syncing";
    const costText = cost == null ? (checking && state.accountId ? "核对中" : "—") : trimPoints(cost);
    const costNote = usage.syncStatus === "error" ? (cost == null ? "积分暂时无法核对" : "更新失败，显示已核实积分") : "";
    const stats = [
      { label: "订阅数", value: String(overview.enabledKeywordCount || 0) },
      { label: "今日新发现条数", value: String(overview.todayNewCount || 0), note: overview.todayNewBySource ? `搜索 ${overview.todayNewBySource.search || 0} · 低粉 ${overview.todayNewBySource.lowfans || 0}（合计去重）` : "" },
      { label: "最近同步时间", value: syncParts ? syncParts[2] : (syncText || "—"), note: syncParts ? syncParts[1] : (!syncText ? "暂无同步" : "") },
      // 暂时隐藏积分概览，保留统计和展示逻辑，恢复时移除 hidden 即可。
      { label: "累计消耗积分", value: costText, note: costNote, hidden: true },
    ];
    if (dom.statusText) {
      dom.statusText.replaceChildren(...stats.map((stat) => {
        const cell = el("div", "radar-stat");
        if (stat.hidden) {
          cell.hidden = true;
          cell.style.display = "none";
        }
        const valueRow = el("div", "radar-stat-value-row");
        valueRow.append(el("strong", "radar-stat-value", stat.value));
        if (stat.note) valueRow.append(el("span", "radar-stat-note", stat.note));
        cell.append(el("span", "radar-stat-label", stat.label), valueRow);
        return cell;
      }));
    }
    const health = overview.health || {};
    if (dom.notice && health.key && !["ok", "empty"].includes(health.key)) {
      setMessage(dom.notice, health.label || "", health.tone === "warning");
    } else {
      setMessage(dom.notice, "");
    }
    const running = isRunning();
    if (dom.syncLabel) dom.syncLabel.textContent = running.collecting ? "同步中…" : "立即更新";
    if (dom.syncButton) dom.syncButton.disabled = running.collecting;
    if (dom.syncButton) dom.syncButton.classList.toggle("is-busy", running.collecting);
    if (dom.keywordMeta) {
      const keywords = overview.keywords || [];
      dom.keywordMeta.textContent = keywords.length
        ? `共 ${keywords.length} 个 · 已启用 ${overview.enabledKeywordCount || 0} 个`
        : "";
    }
    if (dom.trendMeta) dom.trendMeta.textContent = "近 24 小时";
    const settings = overview.settings || {};
    state.settings = settings;
    if (dom.aiAutoTag) {
      dom.aiAutoTag.textContent = settings.aiEnabled === false ? "已关闭自动生成" : `每天 ${settings.aiDailyTime || "10:30"} 自动生成`;
    }
  }

  function renderKeywords() {
    if (!dom.keywordList) return;
    dom.keywordList.replaceChildren();
    const overview = state.overview;
    const keywords = overview?.keywords || [];
    const retainedIds = state.keywordIds.filter(id => keywords.some(keyword => keyword.id === id));
    if (retainedIds.length !== state.keywordIds.length) {
      state.keywordIds = retainedIds;
      state.page = 1;
      worksRequest += 1;
      state.works = null;
      renderWorks();
      loadWorks().catch(error => setMessage(dom.feedMessage, error.message, true));
    }
    renderKeywordFilters(keywords);
    const visible = keywords;
    if (visible.length <= 5) state.keywordsExpanded = false;
    if (dom.keywordMore) {
      dom.keywordMore.hidden = visible.length <= 5;
      dom.keywordMore.textContent = state.keywordsExpanded ? "收起 ↑" : `展开更多（${visible.length - 5}）↓`;
      dom.keywordMore.setAttribute("aria-expanded", String(state.keywordsExpanded));
    }
    if (dom.keywordMoreFooter) dom.keywordMoreFooter.hidden = visible.length <= 5;
    if (!keywords.length) {
      setMessage(dom.keywordMessage, "还没有订阅关键词。点关键词一栏的「添加关键词」开始收集行业动态。");
      renderSuggestions();
      return;
    }
    if (!visible.length) {
      setMessage(dom.keywordMessage, "这个方向下还没有关键词。");
      renderSuggestions();
      return;
    }
    setMessage(dom.keywordMessage, "");
    (state.keywordsExpanded ? visible : visible.slice(0, 5)).forEach((keyword) => dom.keywordList.append(keywordCard(keyword)));
    renderSuggestions();
  }

  function renderKeywordFilters(keywords = state.overview?.keywords || []) {
    if (!dom.keywordFilters) return;
    const signature = JSON.stringify([state.accountId, state.keywordIds, keywords.map(keyword => [keyword.id, keyword.text, keyword.enabled])]);
    if (dom.keywordFilters.dataset.renderKey === signature) return;
    dom.keywordFilters.dataset.renderKey = signature;
    const focusedId = document.activeElement?.parentElement === dom.keywordFilters ? document.activeElement.dataset.keywordId : null;
    dom.keywordFilters.replaceChildren();
    [{ id: "", text: "全部" }, ...keywords].forEach(keyword => {
      const button = el("button", "radar-keyword-filter", keyword.text);
      button.type = "button";
      button.dataset.keywordId = keyword.id;
      const selected = keyword.id ? state.keywordIds.includes(keyword.id) : state.keywordIds.length === 0;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", String(selected));
      if (keyword.enabled === false) button.title = "已暂停订阅，仍可查看已采集作品";
      button.addEventListener("click", () => {
        state.keywordIds = !keyword.id ? [] : state.keywordIds.includes(keyword.id)
          ? state.keywordIds.filter(id => id !== keyword.id)
          : [...state.keywordIds, keyword.id];
        state.page = 1;
        renderKeywordFilters();
        loadWorks({ reset: true }).catch(error => setMessage(dom.feedMessage, error.message, true));
      });
      dom.keywordFilters.append(button);
      if (focusedId === keyword.id) button.focus({ preventScroll: true });
    });
  }

  function renderFilterSegments() {
    [[dom.dayTabs, DAYS, "day"], [dom.likesTabs, LIKE_RANGES, "likesRange"], [dom.filterTabs, FILTERS, "filter"]].forEach(([host, options, key]) => {
      if (!host) return;
      host.replaceChildren();
      const ordered = key === "day" ? [options.find(item => item.key === "all"), ...options.filter(item => item.key !== "all")] : options;
      ordered.forEach(option => {
        const button = el("button", "radar-seg-item", option.label);
        button.type = "button";
        button.dataset.value = option.key;
        button.classList.toggle("is-active", state[key] === option.key);
        button.setAttribute("aria-pressed", String(state[key] === option.key));
        button.addEventListener("click", () => {
          state[key] = option.key;
          state.page = 1;
          renderFilterSegments();
          loadWorks({ reset: true }).catch(error => setMessage(dom.feedMessage, error.message, true));
        });
        host.append(button);
      });
    });
  }

  function renderViewTabs() {
    if (!dom.viewTabs) return;
    dom.viewTabs.replaceChildren();
    [{ key: "cover", label: "封面" }, { key: "list", label: "列表" }].forEach(option => {
      const button = el("button", "radar-seg-item", option.label);
      button.type = "button";
      button.dataset.view = option.key;
      button.setAttribute("aria-pressed", String(state.view === option.key));
      button.classList.toggle("is-active", state.view === option.key);
      button.addEventListener("click", () => {
        state.view = option.key;
        renderViewTabs();
        renderWorks();
      });
      dom.viewTabs.append(button);
    });
  }

  let layoutFrame = 0;
  function layoutWorks() {
    const host = dom.workList;
    if (!host || typeof host.getBoundingClientRect !== "function") return;
    const cards = Array.from(host.children);
    if (state.view !== "cover") {
      host.style.height = "";
      cards.forEach(card => { card.style.width = ""; card.style.left = ""; card.style.top = ""; });
      observeLoadMore();
      return;
    }
    const available = host.clientWidth;
    if (!available) return; // Navigation/ResizeObserver will arrange the visible module.
    const gap = 18, verticalGap = 24;
    // Sparse results retain the same size as a four-card row instead of filling the screen.
    const capacity = Math.max(1, Math.floor((available + gap) / 218));
    const desiredColumns = cards.length > 0 && cards.length < 4 ? 4 : cards.length;
    const columns = Math.max(1, Math.min(desiredColumns, capacity));
    const width = (available - gap * (columns - 1)) / columns;
    const heights = Array(columns).fill(0);
    cards.forEach(card => { card.style.width = `${width}px`; });
    cards.forEach((card, index) => {
      // Preserve feed order across columns, including an incomplete final row.
      const column = index % columns;
      card.style.left = `${column * (width + gap)}px`;
      card.style.top = `${heights[column]}px`;
      heights[column] += card.getBoundingClientRect().height + verticalGap;
    });
    host.style.height = `${cards.length ? Math.max(...heights) - verticalGap : 0}px`;
    observeLoadMore();
  }

  function scheduleWorkLayout() {
    if (!window.requestAnimationFrame) { layoutWorks(); return; }
    window.cancelAnimationFrame(layoutFrame);
    layoutFrame = window.requestAnimationFrame(layoutWorks);
  }
  if (typeof ResizeObserver !== "undefined" && dom.workList) {
    let lastWidth = -1;
    new ResizeObserver(entries => {
      const width = entries[0].contentRect.width;
      if (width !== lastWidth) { lastWidth = width; scheduleWorkLayout(); }
    }).observe(dom.workList);
  }
  window.addEventListener("resize", scheduleWorkLayout);
  document.fonts?.ready.then(scheduleWorkLayout);

  function collectionSummary(collection) {
    const sources = collection?.sources || {};
    return [["search", "搜索"], ["lowfans", "低粉"]].flatMap(([key, label]) => {
      const row = sources[key];
      if (!row) return [];
      const filtered = Number(row.skipped || 0) + Number(row.invalidTag || 0);
      let text = `${label}：返回 ${row.received || 0}，新增 ${row.added || 0}，已有 ${row.updated || 0}`;
      if (filtered) text += `，过滤 ${filtered}`;
      if (row.linked) text += `，新关联 ${row.linked}`;
      if (row.stopReason === "page_limit") text += "；达到采集上限";
      else if (row.stopReason === "filtered_invalid_results") text += "；部分结果未通过校验";
      else if (["request_failed", "repeated_page", "repeated_cursor", "invalid_cursor"].includes(row.stopReason)) text += "；部分完成";
      else if (key === "search" && !row.added && !row.updated) text += "；本轮未采集到符合时间范围的视频";
      return [text];
    }).join(" / ");
  }

  function keywordCard(keyword) {
    const card = el("div", "radar-keyword");
    card.dataset.keywordId = keyword.id;
    card.setAttribute("role", "listitem");
    const head = el("div", "radar-keyword-head");
    const name = el("button", "radar-keyword-name", keyword.text);
    name.type = "button";
    name.addEventListener("click", () => { closeModals(); showSuggestions(keyword.id); });
    head.append(name);
    if (keyword.kind === "key") head.append(el("span", "radar-tag radar-tag-strong", "重点"));
    head.append(el("span", "radar-chip", keyword.group || "未分组"));
    card.append(head);

    const meta = el("p", "radar-keyword-meta");
    const collection = keyword.collection || {};
    const statusLabel = {
      idle: "等待采集",
      queued: "排队中",
      running: "采集中",
      success: "已同步",
      partial: "部分成功",
      failed: "采集失败",
      auth_required: "登录已失效",
      insufficient_balance: "额度不足，已暂停",
    }[collection.status] || "等待采集";
    const bits = [`每天 ${keyword.dailyTime}`, statusLabel];
    if (collection.windowLabel) bits.push(`上轮范围：${collection.windowLabel}`);
    bits.push(`作品 ${keyword.workCount}`);
    meta.textContent = bits.join(" · ");
    card.append(meta);
    const summary = collectionSummary(collection);
    if (summary) card.append(el("p", "radar-keyword-note", summary));

    // 卡片只保留中性状态（meta 里的「部分成功 / 采集失败」）。次要数据源失败、上一轮
    // 失败的原文都不再常驻，避免每张卡片挂一行红字；细节在本轮跑完时提示一次，
    // 只有需要用户动手的凭证失效才继续在卡片上给出入口。
    if (isRelogin(collection.lastErrorCode)) {
      card.append(reloginNode("radar-keyword-error"));
    } else if (collection.gapNote) {
      card.append(el("p", "radar-keyword-note", collection.gapNote));
    }
    const foot = el("div", "radar-keyword-foot");
    const trendCount = (keyword.trend?.items || []).length;
    foot.append(el("span", "radar-hint", trendCount ? `相关飙升话题 ${trendCount} 个` : "暂无相关飙升话题"));
    const actions = el("div", "radar-keyword-actions");
    const update = el("button", "radar-text-button", collection.status === "running" ? "采集中…" : "立即更新");
    update.type = "button";
    update.disabled = collection.status === "running";
    update.addEventListener("click", () => collectKeyword(keyword.id));
    actions.append(update);
    const suggest = el("button", "radar-text-button", "联想");
    suggest.type = "button";
    suggest.addEventListener("click", () => { closeModals(); showSuggestions(keyword.id); });
    actions.append(suggest);
    const pause = el("button", "radar-text-button", keyword.enabled ? "暂停" : "恢复");
    pause.type = "button";
    pause.addEventListener("click", () => updateKeyword(keyword.id, { enabled: !keyword.enabled }));
    actions.append(pause);
    const remove = el("button", "radar-text-button", "取消订阅");
    remove.type = "button";
    remove.addEventListener("click", () => removeKeyword(keyword));
    actions.append(remove);
    foot.append(actions);
    card.append(foot);
    return card;
  }

  function renderSuggestions() {
    if (!dom.suggestionRow) return;
    const keyword = keywordsById().get(state.suggestionKeywordId);
    const words = (keyword?.suggestions || []).filter((word) => word !== keyword?.text);
    if (!keyword || !words.length) {
      dom.suggestionRow.hidden = true;
      dom.suggestionList?.replaceChildren();
      return;
    }
    dom.suggestionRow.hidden = false;
    if (dom.suggestionList) {
      dom.suggestionList.replaceChildren();
      words.forEach((word) => {
        const exists = [...keywordsById().values()].some((item) => item.text === word);
        const button = el("button", "radar-suggest-item", exists ? `${word}（已订阅）` : `＋ ${word}`);
        button.type = "button";
        button.disabled = exists;
        button.addEventListener("click", () => addKeyword(word, keyword.group, keyword.kind));
        dom.suggestionList.append(button);
      });
    }
  }

  function priorityLabel(priority) {
    return { primary: "优先", worth: "可做", backup: "备选" }[priority] || "可做";
  }

  function renderRecommendations() {
    if (!dom.aiList) return;
    const recommendation = state.overview?.recommendation || {};
    const items = (recommendation.items || []).slice(0, 6);
    const dismissedButton = document.getElementById("radarDismissedRecommendationsButton");
    if (dismissedButton) dismissedButton.hidden = !(recommendation?.dismissedItems || []).length;
    const job = recommendation.job || {};
    const metaBits = [];
    if (recommendation.generatedText) metaBits.push(`生成于 ${recommendation.generatedText}`);
    if (recommendation.scope) metaBits.push(String(recommendation.scope).replace(/行业雷达|雷达/g, "内容采集"));
    if (items.some(item => (item.references || []).some(ref => ref.evidenceInvalid))) metaBits.push("部分历史依据已隔离，建议需重新核实");
    if (job.status === "running") metaBits.push("正在生成…");
    if (job.status === "failed" && job.error && !isRelogin(job.errorCode)) metaBits.push(job.error);
    const showRelogin = job.status === "failed" && isRelogin(job.errorCode);
    if (dom.aiMeta) {
      if (showRelogin) {
        // 重新登录入口是一个可点击元素：清空后再拼“文案 · 按钮”。
        dom.aiMeta.replaceChildren();
        dom.aiMeta.textContent = metaBits.length ? `${metaBits.join(" · ")} · ` : "";
        dom.aiMeta.append(reloginNode("radar-relogin-inline"));
      } else {
        dom.aiMeta.textContent = metaBits.join(" · ");
      }
    }
    if (dom.aiUpdateLabel) dom.aiUpdateLabel.textContent = job.status === "running" ? "生成中…" : "更新建议";
    if (dom.aiUpdate) dom.aiUpdate.disabled = job.status === "running";
    if (dom.aiEvidence) dom.aiEvidence.disabled = !recommendation.generatedAt;

    dom.aiList.replaceChildren();
    if (!items.length) {
      setMessage(
        dom.aiMessage,
        job.status === "running"
          ? "正在结合账号定位和最近七天的发现生成建议…"
          : recommendation.message || (recommendation.generatedAt ? "本次没有筛选到适合推荐的作品。" : "还没有建议，点「更新建议」生成一次。")
      );
    } else {
      setMessage(dom.aiMessage, "");
      const limit = state.aiExpanded ? items.length : 3;
      items.slice(0, limit).forEach((item, index) => dom.aiList.append(recommendationCard(item, index)));
    }
    if (dom.aiMore) {
      const hasMore = items.length > 3;
      dom.aiMore.hidden = !hasMore;
      dom.aiMore.textContent = state.aiExpanded ? "收起建议 ↑" : `更多建议（${items.length - 3}）→`;
    }
  }

  // 核心建议始终展示，参考作品与补充依据保留折叠。
  function recommendationCard(item, index) {
    const work = item.sourceWork || {};
    const card = el("article", "radar-recommendation");
    const head = el("div", "radar-recommendation-head");
    head.append(el("span", `monitor-tag is-${item.priority || "worth"}`, ({ primary: "优先推荐", worth: "值得尝试", backup: "备选方向" }[item.priority] || "值得尝试")));
    head.append(el("span", "monitor-tag", "原标题"));
    head.append(el("span", "radar-rank", String(index + 1).padStart(2, "0")));
    card.append(head, el("h4", "radar-recommendation-title", work.title || item.title || ""));
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
    const info = el("dl", "radar-recommendation-info");
    [["推荐理由", item.reason], ["我的切入角度", item.angle]].forEach(([label, value]) => {
      const row = el("div", "radar-recommendation-info-row");
      row.append(el("dt", "radar-recommendation-info-label", label), el("dd", "radar-recommendation-info-text", value || "暂未提供"));
      info.append(row);
    });
    card.append(info);
    const foot = el("footer", "radar-recommendation-foot");
    const adopt = el("button", "am-primary-action monitor-compact-action", item.topicId ? "已加入选题" : "加入选题");
    adopt.type = "button";
    adopt.disabled = Boolean(item.topicId || item.dismissed);
    adopt.addEventListener("click", () => openTopicModal({ kind: "recommendation", key: item.key, title: item.sourceWork?.title || item.title, outline: item.angle || item.reason || "" }));
    const breakdown = el("button", "am-secondary-action monitor-compact-action", "拆解视频");
    breakdown.type = "button";
    breakdown.disabled = work.kind === "image" || !safeWorkUrl(work.shareUrl) || !item.sourceWorkId;
    breakdown.title = work.kind === "image" ? "图文作品暂不支持视频拆解" : !safeWorkUrl(work.shareUrl) ? "暂无可用的视频链接" : "拆解原作品";
    breakdown.addEventListener("click", () => breakdownRecommendation(item));
    const detail = el("button", "radar-text-button", "作品详情");
    detail.type = "button";
    detail.disabled = !item.sourceWorkId;
    detail.addEventListener("click", () => { analysisReturnFocus = detail; openDetail(item.sourceWorkId); });
    const evidence = el("button", "radar-text-button", "推荐依据");
    evidence.type = "button";
    evidence.addEventListener("click", () => showRecommendationEvidence(item, evidence));
    foot.append(adopt, breakdown, detail, evidence);
    card.append(foot);
    return card;
  }

  document.getElementById("radarDismissedRecommendationsButton")?.addEventListener("click", event => {
    analysisReturnFocus = event.currentTarget || event.target;
    const target = document.getElementById("radarAnalysisBody");
    if (!target) return;
    target.replaceChildren();
    (state.overview?.recommendation?.dismissedItems || []).forEach(item => {
      const row = el("div", "recommendation-dismissed-row");
      row.append(el("p", "", item.sourceWork?.title || item.title || "原作品"));
      const restore = el("button", "radar-text-button", "撤销暂不考虑");
      restore.type = "button";
      restore.addEventListener("click", async () => {
        const revision = viewRevision;
        restore.disabled = true;
        await restoreRecommendation(item.key);
        if (revision === viewRevision) closeModals();
      });
      row.append(restore);
      target.append(row);
    });
    document.getElementById("radarAnalysisTitle").textContent = "历史暂不考虑";
    document.getElementById("radarAnalysisModal").hidden = false;
    document.getElementById("radarAnalysisCloseButton")?.focus?.();
  });

  function safeWorkUrl(value) {
    return /^https?:\/\/[^\s]+$/i.test(String(value || "")) ? String(value) : "";
  }

  async function breakdownRecommendation(item) {
    const revision = viewRevision;
    try {
      const work = await api(`/api/radar/works/${encodeURIComponent(item.sourceWorkId)}?${accountQuery()}`);
      if (revision !== viewRevision) return;
      if (!safeWorkUrl(work.shareUrl)) { showToast("暂无可用的视频链接", "info"); return; }
      await startBreakdown(work);
    } catch (error) { if (revision === viewRevision) showToast(error.message, "error"); }
  }

  function showRecommendationEvidence(item, trigger) {
    analysisReturnFocus = trigger || document.activeElement;
    const refs = item.references || [];
    const body = el("div", "radar-evidence-body");
    if (item.topicId) {
      body.append(el("p", "radar-evidence-label", "选题状态"));
      body.append(el("p", "", "已加入选题"));
    }
    if (item.evidence) {
      body.append(el("p", "radar-evidence-label", "外部作品依据"));
      body.append(el("p", "", item.evidence));
    }
    if (refs.length) {
      body.append(el("p", "radar-evidence-label", "参考作品"));
      refs.forEach((ref) => {
        const full = String(ref.title || ref.id || "");
        const link = el("button", "radar-evidence-link", full.length > 44 ? `${full.slice(0, 44)}…` : full);
        link.type = "button";
        link.title = [ref.authorName, ref.publishedText].filter(Boolean).join(" · ") || full;
        link.addEventListener("click", () => openDetail(ref.id));
        body.append(link);
      });
    } else {
      body.append(el("p", "radar-hint", "这次没有引用到具体作品。"));
    }
    if (!item.reviewEvidence && !(item.reviewReferences || []).length) body.append(el("p", "radar-hint", "本账号复盘依据：暂无可用记录，不据此判断历史效果。"));
    if (item.reviewEvidence) {
      body.append(el("p", "radar-evidence-label", "本账号复盘依据"));
      body.append(el("p", "", item.reviewEvidence));
    }
    (item.reviewReferences || []).forEach((ref) => {
      const entry = el("details", "radar-review-reference");
      const title = String(ref.title || ref.id || "");
      const summary = el("summary", "radar-evidence-link", title.length > 44 ? `${title.slice(0, 44)}…` : title);
      summary.title = title;
      entry.append(summary);
      entry.append(el("p", "", title));
      entry.append(el("p", "radar-hint", `作品 ID：${ref.id} · 发布于 ${analysisDate(ref.publishedAt)}`));
      entry.append(el("p", "", reviewMetrics(ref.metrics)));
      if (ref.scriptOpening) entry.append(el("p", "", `关联脚本开头：${ref.scriptOpening}${ref.scriptOpeningTruncated ? "（仅前400字）" : ""}`));
      if (ref.note) entry.append(el("p", "", `复盘备注：${ref.note}`));
      entry.append(el("p", "radar-hint", `生成时指标快照 · 采集于 ${analysisDate(ref.collectedAt)}`));
      body.append(entry);
    });

    const work = item.sourceWork || {};
    body.append(el("p", "radar-evidence-label", "生成时原作品快照"));
    body.append(el("p", "", `${work.title || item.title} · ${work.authorName || work.bloggerName || "作者未知"} · ${work.publishedText || analysisDate(work.publishedAt)}`));
    body.append(el("p", "", reviewMetrics(work.metrics)));
    body.append(el("p", "", `指标采集于 ${analysisDate(work.statsUpdatedAt)}`));
    body.append(el("p", "radar-evidence-label", "账号匹配与切入角度"));
    body.append(el("p", "", `${item.reason || "暂无数据"}\n${item.angle || "暂无数据"}`));
    const analysis = state.overview?.recommendation?.analysis || {};
    body.append(el("p", "radar-evidence-label", "判断边界与数据缺口"));
    body.append(el("p", "", "仅根据标题与可用数据判断主题，未分析视频正文；互动数据不证明标题本身的效果。"));
    body.append(el("p", "", (analysis.gaps || []).join("；") || "未记录额外数据缺口"));
    const action = el("button", "radar-text-button", item.dismissed ? "撤销暂不考虑" : "暂不考虑");
    action.type = "button";
    action.addEventListener("click", async () => {
      const revision = viewRevision;
      action.disabled = true;
      await (item.dismissed ? restoreRecommendation(item.key) : dismissRecommendation(item.key));
      if (revision === viewRevision) closeModals();
    });
    body.append(action);
    const target = document.getElementById("radarAnalysisBody");
    if (!target) return;
    target.replaceChildren(body);
    const title = document.getElementById("radarAnalysisTitle");
    if (title) title.textContent = "推荐依据";
    document.getElementById("radarAnalysisModal").hidden = false;
    document.getElementById("radarAnalysisCloseButton")?.focus?.();
  }

  function renderTrains() {
    if (!dom.trendList) return;
    dom.trendList.replaceChildren();
    const rows = state.overview?.trends || [];
    const items = [];
    rows.forEach((row) => {
      (row.items || []).forEach((item) => items.push({ ...item, from: row.keyword, updatedText: row.updatedText }));
    });
    if (!items.length) {
      setMessage(dom.trendMessage, "还没有热度数据，采集后会在这里显示飙升话题。");
      return;
    }
    setMessage(dom.trendMessage, "");
    items.slice(0, 10).forEach((item, index) => {
      const row = el("div", "radar-trend");
      row.setAttribute("role", "listitem");
      // 标题与热度同排，来源和操作各占一行。
      const head = el("div", "radar-trend-head");
      head.append(el("span", "radar-trend-rank", String(index + 1).padStart(2, "0")));
      head.append(el("strong", "radar-trend-keyword", item.keyword || ""));
      if (item.score !== null && item.score !== undefined) {
        const score = el("span", "radar-trend-score", formatTrendScore(item.score));
        score.title = String(item.score);
        head.append(score);
      }
      row.append(head);
      const foot = el("div", "radar-trend-foot");
      const meta = [item.from ? `来自 ${item.from}` : "", item.updatedText ? `更新 ${item.updatedText}` : ""].filter(Boolean);
      if (meta.length) foot.append(el("span", "radar-trend-meta", meta.join(" · ")));
      const subscribed = [...keywordsById().values()].some((keyword) => keyword.text === item.keyword);
      const button = el("button", "radar-text-button", subscribed ? "已订阅" : "订阅话题");
      button.disabled = subscribed;
      button.type = "button";
      button.setAttribute("aria-label", `${subscribed ? "已订阅话题" : "订阅话题"}：${item.keyword || ""}`);
      button.addEventListener("click", () => searchTrend(item.keyword || ""));
      foot.append(button);
      row.append(foot);
      dom.trendList.append(row);
    });
  }

  function renderTabs() {
    if (!dom.tabs) return;
    dom.tabs.replaceChildren();
    TABS.forEach((tab) => {
      const button = el("button", "radar-seg-item", tab.label);
      button.type = "button";
      button.setAttribute("role", "tab");
      button.dataset.tab = tab.key;
      const active = tab.key === state.tab;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", String(active));
      button.addEventListener("click", () => {
        if (state.tab === tab.key) return;
        state.tab = tab.key;
        state.page = 1;
        renderTabs();
        renderFeedHint();
        loadWorks({ reset: true }).catch((error) => setMessage(dom.feedMessage, error.message, true));
      });
      dom.tabs.append(button);
    });
  }

  function renderFeedHint() {
    if (dom.feedHint) dom.feedHint.textContent = TAB_HINTS[state.tab] || "";
  }

  function renderWorks() {
    if (!dom.workList) return;
    const data = state.works || { items: [], total: 0, page: 1, pageCount: 1 };
    const existing = new Map(Array.from(dom.workList.children).map(row => [row.dataset.workId, row]));
    const rows = data.items.map(work => {
      const key = JSON.stringify(work);
      const previous = existing.get(work.id);
      if (previous?.dataset.renderKey === key) return previous;
      const row = workRow(work);
      row.dataset.renderKey = key;
      return row;
    });
    const current = Array.from(dom.workList.children);
    if (rows.length !== current.length || rows.some((row, index) => row !== current[index])) dom.workList.replaceChildren(...rows);
    dom.workList.classList.toggle("is-cover-view", state.view === "cover");
    dom.workList.classList.toggle("is-list-view", state.view === "list");
    if (dom.workCount) dom.workCount.textContent = `共 ${data.total || 0} 条`;
    renderFeedHint();
    if (!data.items.length) {
      setMessage(dom.feedMessage, EMPTY_HINTS[state.day] || "还没有发现作品。");
    } else {
      setMessage(dom.feedMessage, "");
    }
    layoutWorks();
    renderLoadMore();
  }

  function renderLoadMore() {
    const data = state.works;
    const count = data?.items.length || 0;
    if (dom.feedTotal) dom.feedTotal.textContent = `已加载 ${count} 条 · 共 ${data?.total || 0} 条`;
    if (dom.moreButton) {
      dom.moreButton.textContent = state.worksLoading ? "加载中…" : state.worksError ? "加载失败，点击重试" : data?.hasMore ? "加载更多" : "已全部加载";
      dom.moreButton.disabled = state.worksLoading || (!state.worksError && !data?.hasMore);
      dom.moreButton.setAttribute("aria-busy", String(state.worksLoading));
      dom.moreButton.title = state.worksError || "";
    }
  }

  let moreObserver = null;
  function observeLoadMore() {
    if (!moreObserver || !dom.moreFooter) return;
    moreObserver.unobserve(dom.moreFooter);
    if (state.loaded && !root.hidden && !state.worksLoading && !state.worksError && state.works?.hasMore) moreObserver.observe(dom.moreFooter);
  }
  if (typeof IntersectionObserver !== "undefined" && dom.moreFooter) {
    moreObserver = new IntersectionObserver(entries => {
      if (!document.hidden && entries.some(entry => entry.isIntersecting)) loadMoreWorks();
    }, { root: null, rootMargin: "0px", threshold: 0 });
  }
  dom.moreButton?.addEventListener("click", () => loadMoreWorks(true));

  // 封面尺寸与监控作品动态一致，右侧标题与封面顶部对齐。
  function workRow(work) {
    const row = el("article", "radar-work");
    row.setAttribute("role", "listitem");
    row.dataset.workId = work.id;

    const thumb = el("button", "radar-thumb");
    thumb.type = "button";
    thumb.setAttribute("aria-label", `查看作品：${work.title || "未命名作品"}`);
    if (work.coverSrc) {
      const image = el("img", "radar-thumb-image");
      image.src = work.coverSrc;
      image.alt = "";
      image.loading = "lazy";
      const dimensions = coverDimensions.get(work.coverSrc);
      if (dimensions) {
        image.width = dimensions.width;
        image.height = dimensions.height;
        thumb.style.setProperty("--radar-cover-ratio", `${dimensions.width} / ${dimensions.height}`);
      }
      thumb.classList.add("is-loading");
      image.addEventListener("load", () => {
        if (image.naturalWidth && image.naturalHeight) rememberCoverDimensions(work.coverSrc, image.naturalWidth, image.naturalHeight);
        thumb.classList.remove("is-loading");
        scheduleWorkLayout();
      });
      image.addEventListener("error", () => { image.hidden = true; thumb.classList.remove("is-loading"); thumb.classList.add("is-placeholder"); scheduleWorkLayout(); });
      thumb.append(image);
    }
    thumb.classList.toggle("is-placeholder", !work.coverSrc);
    if (work.kind === "image") thumb.append(el("span", "radar-thumb-tag", `图文 ${work.imageCount || ""}`.trim()));
    else if (work.durationSeconds) thumb.append(el("span", "radar-thumb-duration", formatDuration(work.durationSeconds)));
    thumb.addEventListener("click", () => openDetail(work.id));
    row.append(thumb);

    const copy = el("div", "radar-work-copy");
    const fullTitle = work.title || "（无标题）";
    const title = el("button", "radar-work-title", fullTitle);
    title.title = fullTitle;
    title.type = "button";
    title.addEventListener("click", () => openDetail(work.id));
    copy.append(title);

    // 第二行：作者 · 发布时间，后面并排低粉爆款与关键词标签。
    const meta = el("div", "radar-work-meta");
    meta.append(el("span", "radar-work-author", work.authorName || "未知作者"));
    meta.append(el("span", "radar-work-dot", "·"));
    meta.append(el("span", "radar-work-time", work.publishedText || "发布时间未知"));
    if ((work.sources || []).includes("search")) meta.append(el("span", "radar-tag radar-tag-latest", "最新视频"));
    if (work.lowFans) meta.append(el("span", "radar-tag radar-tag-lowfans", "低粉爆款"));
    (work.keywords || []).slice(0, 2).forEach((keyword) => meta.append(el("span", "radar-chip", keyword)));
    if (work.publishedAt && new Date(work.publishedAt).toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" }) === new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" })) meta.append(el("span", "radar-tag radar-tag-today", "今天"));
    if (work.isNew) meta.append(el("span", "radar-chip radar-chip-new", "新发现"));
    if (work.imported && !work.isNew) meta.append(el("span", "radar-chip radar-chip-muted", "历史导入"));
    copy.append(meta);

    const metrics = el("div", "radar-work-metrics");
    const entries = [];
    if (work.authorFollowers !== null && work.authorFollowers !== undefined) entries.push(["粉丝", work.authorFollowers]);
    if (work.metrics?.likes !== null && work.metrics?.likes !== undefined) entries.push(["点赞", work.metrics.likes]);
    if (work.metrics?.comments !== null && work.metrics?.comments !== undefined) entries.push(["评论", work.metrics.comments]);
    if (work.metrics?.shares !== null && work.metrics?.shares !== undefined) entries.push(["分享", work.metrics.shares]);
    if (!entries.length) {
      metrics.append(el("span", "radar-work-metric", "指标暂缺"));
    } else {
      entries.forEach(([label, value]) => metrics.append(el("span", "radar-work-metric", `${label} ${formatCount(value)}`)));
    }
    copy.append(metrics);
    row.append(copy);

    const actions = el("div", "radar-work-actions");
    const adopt = el("button", "am-secondary-action radar-compact-action", work.topicId ? "已加入选题" : "加入选题");
    adopt.type = "button";
    adopt.disabled = Boolean(work.topicId);
    adopt.addEventListener("click", () => openTopicModal({ kind: "work", workId: work.id, title: work.title || "", outline: "" }));
    actions.append(adopt);
    const breakdown = el("button", "am-secondary-action radar-compact-action", "拆解视频");
    breakdown.type = "button";
    breakdown.addEventListener("click", () => startBreakdown(work));
    actions.append(breakdown);
    const save = el("button", `am-secondary-action radar-compact-action${work.saved ? " is-saved" : ""}`, work.saved ? "已收藏" : "收藏");
    save.type = "button";
    save.setAttribute("aria-pressed", String(Boolean(work.saved)));
    save.addEventListener("click", () => toggleSaved(work));
    actions.append(save);
    actions.setAttribute("role", "group");
    actions.setAttribute("aria-label", "视频操作");
    row.append(actions);
    return row;
  }

  function formatDuration(seconds) {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    const minutes = Math.floor(total / 60);
    const rest = total % 60;
    return `${minutes}:${String(rest).padStart(2, "0")}`;
  }

  // ------------------------------------------------------------ actions

  async function refresh(options) {
    if (!await loadOverview(options)) return;
    await loadWorks();
    renderRecommendations();
  }

  async function collectKeyword(keywordId) {
    try {
      await api(`/api/radar/keywords/${keywordId}/collect`, { method: "POST" });
      beginUpdate("已开始更新这个关键词", { kind: "keywords", ids: [keywordId], baseline: attemptBaseline([keywordId]) });
      startPolling();
      await refresh({ silent: true });
      renderStatus();
      renderKeywords();
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function collectAccount() {
    // 未登录时不启动平台任务：先弹登录框，避免「已开始更新」之后在后台静默失败。
    if (window.accountModule && !(await window.accountModule.requireLogin())) return;
    try {
      const result = await api("/api/radar/collect", { method: "POST", body: { accountId: state.accountId } });
      if (!result.started && !result.running) {
        showToast("没有可更新的关键词，先添加关键词。", "error");
        return;
      }
      const ids = (state.overview?.keywords || []).filter((keyword) => keyword.enabled).map((keyword) => keyword.id);
      beginUpdate("已开始更新全部关键词", { kind: "keywords", ids, baseline: attemptBaseline(ids) });
      startPolling();
      await refresh({ silent: true });
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function updateKeyword(keywordId, fields) {
    const revision = viewRevision;
    try {
      const result = await api(`/api/radar/keywords/${keywordId}`, { method: "PATCH", body: fields });
      if (revision !== viewRevision) return;
      overviewRequest += 1;
      state.overview = result.overview;
      render();
      showToast(fields.enabled === false ? "已暂停订阅" : "已更新关键词", "success");
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function removeKeyword(keyword) {
    if (!window.confirm(`取消订阅「${keyword.text}」？已收集的作品和已经加入的选题会保留。`)) return;
    const revision = viewRevision;
    try {
      const result = await api(`/api/radar/keywords/${keyword.id}`, { method: "DELETE" });
      if (revision !== viewRevision) return;
      overviewRequest += 1;
      state.overview = result.overview;
      if (state.suggestionKeywordId === keyword.id) state.suggestionKeywordId = "";
      if (state.keywordIds.includes(keyword.id)) { state.keywordIds = state.keywordIds.filter(id => id !== keyword.id); state.page = 1; worksRequest += 1; }
      render();
      await loadWorks();
      showToast("已取消订阅", "success");
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function addKeyword(text, group, kind, errorId = "radarKeywordModalError") {
    const revision = viewRevision;
    const value = String(text || "").trim();
    if (!value) {
      setMessage(document.getElementById(errorId), "请填写关键词", true);
      return;
    }
    const fields = {
      accountId: state.accountId,
      text: value,
      kind: kind || "normal",
      group: group !== undefined ? group : "",
    };
    try {
      const result = await api("/api/radar/keywords", { method: "POST", body: fields });
      if (revision !== viewRevision) return;
      overviewRequest += 1;
      state.overview = result.overview;
      closeModals();
      showToast("已添加关键词，正在导入最近七天的内容", "success");
      startPolling();
      await refresh();
    } catch (error) {
      setMessage(document.getElementById(errorId), error.message, true);
    }
  }

  async function toggleSaved(work) {
    const revision = viewRevision;
    const accountId = state.accountId;
    const saved = !work.saved;
    try {
      await api(`/api/radar/works/${work.id}/saved`, {
        method: "POST",
        body: { accountId, saved },
      });
      if (revision !== viewRevision) return;
      work.saved = saved;
      if (state.activeWork?.id === work.id) state.activeWork.saved = saved;
      updateDetailActions();
      await loadOverview({ silent: true });
      if (revision !== viewRevision) return;
      renderStatus();
      await loadWorks();
      if (revision === viewRevision) showToast(saved ? "已收藏" : "已取消收藏", "success");
    } catch (error) {
      if (revision === viewRevision) showToast(error.message, "error");
    }
  }

  async function markRead(workId) {
    try {
      await api(`/api/radar/works/${workId}/read`, { method: "POST", body: { accountId: state.accountId } });
    } catch (_error) {
      /* 已读只是辅助状态，失败不打断浏览 */
    }
  }

  async function showSuggestions(keywordId) {
    state.suggestionKeywordId = keywordId;
    const keyword = keywordsById().get(keywordId);
    if (!keyword) return;
    if ((keyword.suggestions || []).length) {
      renderSuggestions();
      return;
    }
    try {
      const result = await api(`/api/radar/keywords/${keywordId}/suggest`, { method: "POST" });
      await loadOverview({ silent: true });
      renderKeywords();
      if (!result.words?.length) showToast("没有找到联想词", "info");
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function searchTrend(keyword) {
    if (!keyword) return;
    const exists = [...keywordsById().values()].some((item) => item.text === keyword);
    if (exists) {
      state.group = "all";
      renderKeywords();
      showToast("这个关键词已经在订阅里", "info");
      return;
    }
    if (modals.trends) modals.trends.hidden = true;
    pendingTrendSubscription = { keyword, accountId: state.accountId };
    document.getElementById("radarTrendSubscribeDescription").textContent = `将话题「${keyword}」添加到当前账号的订阅？`;
    setMessage(document.getElementById("radarTrendSubscribeError"), "");
    openModal(modals.trendSubscribe);
    document.getElementById("radarTrendSubscribeCancel")?.focus?.();
  }

  async function confirmTrendSubscription() {
    const pending = pendingTrendSubscription;
    if (!pending || trendSubscriptionSubmitting || pending.accountId !== state.accountId) return;
    trendSubscriptionSubmitting = true;
    const button = document.getElementById("radarTrendSubscribeConfirm");
    button.disabled = true;
    button.textContent = "正在订阅…";
    try {
      await addKeyword(pending.keyword, "", "normal", "radarTrendSubscribeError");
    } finally {
      trendSubscriptionSubmitting = false;
      button.disabled = false;
      button.textContent = "确认订阅并采集";
    }
  }

  async function updateRecommendation() {
    // 未登录时不启动平台任务：先弹登录框，避免「已开始生成」之后在后台静默失败。
    if (window.accountModule && !(await window.accountModule.requireLogin())) return;
    try {
      await api("/api/radar/recommendation", { method: "POST", body: { accountId: state.accountId } });
      beginUpdate("已开始生成选题建议", { kind: "ai", baseline: aiRunMarker() });
      startPolling();
      renderRecommendations();
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function dismissRecommendation(key) {
    const revision = viewRevision;
    try {
      const view = await api(`/api/radar/recommendation/${key}/dismiss`, {
        method: "POST",
        body: { accountId: state.accountId },
      });
      if (revision !== viewRevision) return;
      if (state.overview) state.overview.recommendation = view;
      renderRecommendations();
      showToast("已标记暂不考虑", "success");
    } catch (error) {
      if (revision !== viewRevision) return;
      showToast(error.message, "error");
    }
  }

  async function restoreRecommendation(key) {
    const revision = viewRevision;
    try {
      const view = await api(`/api/radar/recommendation/${encodeURIComponent(key)}/restore`, { method: "POST", body: { accountId: state.accountId } });
      if (revision !== viewRevision) return;
      if (state.overview) state.overview.recommendation = view;
      renderRecommendations();
      showToast("已撤销暂不考虑", "success");
    } catch (error) { if (revision === viewRevision) showToast(error.message, "error"); }
  }

  async function openDetail(workId) {
    const revision = viewRevision;
    const request = ++detailRequest;
    try {
      const work = await api(`/api/radar/works/${workId}?${accountQuery()}`);
      if (revision !== viewRevision || request !== detailRequest) return;
      state.detailWorkId = workId;
      state.activeWork = work;
      renderDetail(work);
      if (modals.analysis) modals.analysis.hidden = true;
      openModal(modals.detail);
      document.getElementById("radarDetailCloseButton")?.focus?.();
      markRead(workId);
      if (state.workIdIsUnread) loadWorks().catch(() => {});
    } catch (error) {
      if (revision !== viewRevision || request !== detailRequest) return;
      showToast(error.message, "error");
    }
  }

  const pendingAuthorMonitors = new Set();

  function authorMonitorKey(accountId, workId) {
    return JSON.stringify([accountId, workId]);
  }

  async function monitorDetailAuthor() {
    const work = state.activeWork;
    if (!work || work.authorFollowing || modals.detail?.hidden) return;
    const accountId = state.accountId;
    const workId = state.detailWorkId;
    const key = authorMonitorKey(accountId, workId);
    if (pendingAuthorMonitors.has(key)) return;
    const revision = viewRevision;
    const request = detailRequest;
    const isCurrent = () => revision === viewRevision && request === detailRequest &&
      accountId === state.accountId && workId === state.detailWorkId && !modals.detail?.hidden;
    pendingAuthorMonitors.add(key);
    updateDetailActions();
    try {
      if (window.accountModule && !(await window.accountModule.requireLogin())) return;
      if (!isCurrent()) return;
      const result = await api(`/api/radar/works/${encodeURIComponent(workId)}/monitor?${new URLSearchParams({ accountId })}`, { method: "POST" });
      if (!isCurrent()) return;
      Object.assign(work, { authorId: result.authorId, authorProfileUrl: result.authorProfileUrl, authorFollowing: result.authorFollowing });
      showToast(result.alreadyFollowing ? "该博主已监控" : "已添加监控，正在采集作品", "success");
    } catch (error) {
      if (isCurrent()) showToast(error.message, "error");
    } finally {
      pendingAuthorMonitors.delete(key);
      if (isCurrent()) updateDetailActions();
      // A reopened modal may have read the old state while this request was in flight.
      else if (accountId === state.accountId && workId === state.detailWorkId && !modals.detail?.hidden) {
        openDetail(workId);
      }
    }
  }

  function updateDetailActions() {
    if (!state.detailWorkId) return;
    const work = state.activeWork;
    const saved = document.getElementById("radarDetailSaveButton");
    if (saved && work) saved.textContent = work.saved ? "已收藏" : "收藏";
    const monitor = document.getElementById("radarDetailMonitorButton");
    const hint = document.getElementById("radarDetailMonitorHint");
    const pending = pendingAuthorMonitors.has(authorMonitorKey(state.accountId, state.detailWorkId));
    if (monitor) {
      monitor.textContent = work?.authorFollowing ? "已监控" : pending ? "添加中…" : "监控博主";
      monitor.disabled = !work || Boolean(work.authorFollowing) || pending;
    }
    if (hint) hint.hidden = !work || Boolean(work.authorProfileUrl) || Boolean(work.authorFollowing);
  }

  function renderDetail(work) {
    const title = document.getElementById("radarDetailTitle");
    const body = document.getElementById("radarDetailBody");
    if (title) title.textContent = work.kind === "image" ? "图文详情" : "视频详情";
    if (!body) return;
    body.replaceChildren();
    const layout = el("div", "radar-detail-layout");
    const cover = el("div", "radar-detail-cover");
    const placeholder = el("span", "radar-detail-cover-placeholder", "暂无封面");
    cover.append(placeholder);
    if (work.coverSrc) {
      placeholder.textContent = "封面加载中";
      const image = el("img", "radar-detail-cover-image");
      image.alt = `${work.title || "当前作品"}的封面`;
      image.addEventListener("load", () => { placeholder.hidden = true; cover.classList.add("is-loaded"); });
      image.addEventListener("error", () => { image.hidden = true; cover.classList.remove("is-loaded"); placeholder.hidden = false; placeholder.textContent = "封面暂不可用"; });
      image.src = work.coverSrc;
      cover.append(image);
    }
    if (work.kind !== "image" && Number(work.durationSeconds) > 0) {
      cover.append(el("span", "radar-thumb-duration", formatDuration(work.durationSeconds)));
    }
    const content = el("div", "radar-detail-info");
    content.append(el("h3", "radar-detail-work-title", work.title || "未命名作品"));
    layout.append(cover, content);
    body.append(layout);
    const meta = el("p", "radar-detail-meta");
    const bits = [work.authorName || "未知作者", work.publishedText || "发布时间未知"];
    if (work.authorFollowers !== null && work.authorFollowers !== undefined) {
      bits.push(`粉丝 ${formatCount(work.authorFollowers)}`);
    }
    meta.textContent = bits.join(" · ");
    content.append(meta);
    const metrics = el("dl", "radar-detail-metrics");
    [["likes", "点赞"], ["comments", "评论"], ["shares", "分享"]].forEach(([field, label]) => {
      const item = el("div", "radar-detail-metric");
      item.append(el("dt", "", label), el("dd", "", work.metrics?.[field] == null ? "—" : formatCount(work.metrics[field])));
      metrics.append(item);
    });

    const tags = el("div", "radar-detail-tags");
    if (work.lowFans) tags.append(el("span", "radar-tag radar-tag-lowfans", "低粉爆款"));
    (work.keywords || []).forEach((keyword) => tags.append(el("span", "radar-chip", keyword)));
    if (work.baseline) tags.append(el("span", "radar-chip radar-chip-muted", "历史导入"));
    if (tags.childElementCount) content.append(tags);
    content.append(metrics);

    if (work.snapshots?.length) {
      content.append(el("p", "radar-detail-section", "指标快照"));
      const list = el("div", "radar-detail-snapshots");
      work.snapshots.slice(-6).reverse().forEach((snapshot) => {
        const row = el("div", "radar-detail-snapshot");
        row.append(el("span", "radar-detail-snapshot-time", snapshot.at ? snapshot.at.slice(0, 16).replace("T", " ") : ""));
        const metrics = snapshot.metrics || {};
        const values = ["likes", "comments", "shares"]
          .filter((field) => metrics[field] !== null && metrics[field] !== undefined)
          .map((field) => `${({ likes: "点赞", comments: "评论", shares: "分享" })[field]} ${formatCount(metrics[field])}`);
        row.append(el("span", "radar-detail-snapshot-value", values.join(" · ") || "指标暂缺"));
        list.append(row);
      });
      content.append(list);
    }
    const links = document.getElementById("radarDetailVideoLinks");
    if (links) {
      links.replaceChildren();
      const url = safeWorkUrl(work.shareUrl);
      const id = String(url).match(/^https?:\/\/(?:www\.)?(?:douyin\.com\/(?:video|note)|iesdouyin\.com\/share\/(?:video|slides))\/(\d+)(?:\/?(?:[?#].*)?)$/i)?.[1] || String(work.id || "");
      const backup = /^\d+$/.test(id) ? `https://www.douyin.com/jingxuan?modal_id=${id}` : "";
      [["查看视频", url], ["备用链接", backup]].forEach(([label, href]) => {
        const node = el(href ? "a" : "span", "am-secondary-action", href ? label : `${label}不可用`);
        if (href) { node.href = href; node.target = "_blank"; node.rel = "noopener noreferrer"; }
        links.append(node);
      });
    }
    const stats = el("p", "radar-hint");
    stats.textContent = work.statsUpdatedAt ? `指标更新于 ${work.statsUpdatedAt.slice(0, 16).replace("T", " ")}` : "";
    if (stats.textContent) content.append(stats);
    updateDetailActions();
  }

  function openTopicModal(target) {
    state.topicTarget = target;
    const titleInput = document.getElementById("radarTopicTitleInput");
    const outlineInput = document.getElementById("radarTopicOutlineInput");
    if (titleInput) {
      if (target.kind === "recommendation") titleInput.removeAttribute("maxlength");
      else titleInput.setAttribute("maxlength", "160");
      const title = target.title || "";
      titleInput.value = target.kind === "work"
        ? title.replace(/[#＃][^\s#＃]+/gu, "").replace(/\s+/gu, " ").trim()
        : title;
    }
    if (outlineInput) outlineInput.value = target.outline || "";
    setPickerValue("topicWeek", "current");
    setPickerValue("topicCategory", "daily");
    setPickerValue("topicFormat", "video");
    setMessage(document.getElementById("radarTopicError"), "");
    const hint = document.getElementById("radarTopicHint");
    if (hint) {
      hint.textContent =
        target.kind === "recommendation"
          ? "保存到当前账号的选题库，切入角度和推荐理由会一起写进大纲。"
          : "保存到当前账号的选题库，之后可在「本周选题」里继续编辑。";
    }
    openModal(modals.topic);
    window.topicEntryModal?.resize(modals.topic);
  }

  async function confirmTopic() {
    const target = state.topicTarget;
    if (!target) return;
    const title = document.getElementById("radarTopicTitleInput")?.value?.trim() || "";
    if (!title) {
      setMessage(document.getElementById("radarTopicError"), "请填写选题标题", true);
      return;
    }
    const body = {
      accountId: state.accountId,
      title,
      outline: document.getElementById("radarTopicOutlineInput")?.value || "",
      category: pickerValue("topicCategory") || "daily",
      format: pickerValue("topicFormat") || "video",
      weekPlan: pickerValue("topicWeek") || "current",
    };
    const revision = viewRevision;
    try {
      if (target.kind === "recommendation") {
        const result = await api(`/api/radar/recommendation/${target.key}/topic`, { method: "POST", body });
        if (revision !== viewRevision) return;
        if (state.overview) state.overview.recommendation = result.recommendation;
      } else {
        await api(`/api/radar/works/${target.workId}/topic`, { method: "POST", body });
      }
      window.topicsModule?.invalidate?.();
      if (revision !== viewRevision) return;
      closeModals();
      showToast("已加入选题，可在「本周选题」里继续编辑", "success");
      await loadOverview({ silent: true });
      render();
      await loadWorks();
    } catch (error) {
      if (revision !== viewRevision) return;
      setMessage(document.getElementById("radarTopicError"), error.message, true);
    }
  }

  async function startBreakdown(work) {
    if (work.kind === "image") {
      showToast("这是图文作品，现有拆解只支持视频；可以先加入选题。", "info");
      return;
    }
    if (!work.shareUrl) {
      showToast("这条作品没有可用的分享链接，暂时不能拆解。", "error");
      return;
    }
    // 与监控页一致：切到拆解模块，由它自己创建任务并展示进度。
    closeModals();
    window.selectWorkspaceModule?.("split");
    try {
      await window.breakdownModule?.start?.(work.shareUrl, work.title);
    } catch (error) {
      showToast(error?.message || "拆解失败，请稍后重试", "error");
    }
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
    const title = document.getElementById("radarAnalysisTitle");
    if (title) title.textContent = "分析依据";
    const recommendation = state.overview?.recommendation || {};
    const items = (recommendation.items || []).slice(0, 6);
    if (!recommendation.generatedAt) {
      showToast("还没有生成建议", "info");
      return;
    }
    const lines = [];
    lines.push(`生成时间：${recommendation.generatedText || recommendation.generatedAt}`);
    if (recommendation.scope) lines.push(`分析范围：${recommendation.scope}`);
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
    const body = document.getElementById("radarAnalysisBody");
    if (!body) return;
    body.replaceChildren();
    lines.forEach(line => body.append(el("p", "radar-analysis-paragraph", line)));
    openModal(modals.analysis);
    document.getElementById("radarAnalysisCloseButton")?.focus?.();
  }

  // ------------------------------------------------------------ polling

  /* 本轮跑完时的一句话结论。卡片不再常驻失败原文，所以这里把「有几个关键词没拿到、
     缺的是哪个数据源」说明一次，不指向尚未提供的详情入口。 */
  function roundResultToast(ids) {
    const keywords = (state.overview?.keywords || []).filter(k => !ids || ids.includes(k.id));
    const issues = keywords.filter((keyword) => ["partial", "failed"].includes(keyword.collection?.status));
    if (!issues.length) {
      const details = keywords.map(k => collectionSummary(k.collection)).filter(Boolean);
      return { message: details.length ? "本轮更新完成，" + details.join("；") : "内容采集已完成本轮更新", type: "success" };
    }
    const failed = issues.filter((keyword) => keyword.collection?.status === "failed").length;
    const partial = issues.length - failed;
    const reasons = [];
    issues.forEach((keyword) => {
      const raw = String(keyword.collection?.lastError || "");
      // 后台新写的失败原因是「低粉爆款未获取、热度飙升榜未获取」这种短片段（不含句号）；
      // 旧版长句和整段报错原文一律不回放，避免把已经下架的文案又弹一次。
      if (raw.includes("。")) return;
      raw.split(/[、，,]/).forEach((part) => {
        const text = part.trim();
        if (text && !reasons.includes(text)) reasons.push(text);
      });
    });
    const detail = reasons.length ? "（" + reasons.join("、") + "）" : "";
    return {
      message: "本轮采集结束，" + [failed ? `${failed} 个关键词采集失败` : "", partial ? `${partial} 个关键词未完全获取` : ""].filter(Boolean).join("，") + detail,
      type: failed ? "error" : "info",
    };
  }

  /* 「已开始更新…」是一次性加载提示，必须能被可靠地收掉。判定完成同时看三件事，
     避免采集在第一次轮询前就结束、状态翻转永远观察不到、提示一直悬停：
       * 观察到过「进行中」（sawBusy）；
       * 目标真的推进过（lastAttemptAt / lastRunAt 变化）；
       * 兜底超时（无论观察到什么都收掉提示，绝不永久悬停）。 */
  function keywordAttemptAt(keywordId) {
    const keyword = (state.overview?.keywords || []).find((item) => item.id === keywordId);
    return String(keyword?.collection?.lastAttemptAt || "");
  }

  function attemptBaseline(keywordIds) {
    const baseline = {};
    keywordIds.forEach((keywordId) => { baseline[keywordId] = keywordAttemptAt(keywordId); });
    return baseline;
  }

  function aiRunMarker() {
    return String(state.overview?.recommendation?.job?.lastRunAt || "");
  }

  function beginUpdate(message, watch) {
    state.updateWatch = { ...watch, at: Date.now(), sawBusy: false };
    showToast(message, "loading");
  }

  function updateSettled() {
    const watch = state.updateWatch;
    if (!watch) return true;
    if (Date.now() - watch.at > UPDATE_TIMEOUT_MS) return true;
    if (watch.kind === "ai") {
      if (state.overview?.recommendation?.job?.status === "running") { watch.sawBusy = true; return false; }
      return watch.sawBusy || aiRunMarker() !== watch.baseline;
    }
    const watched = (state.overview?.keywords || []).filter((keyword) => watch.ids.includes(keyword.id));
    if (watched.some((keyword) => ["queued", "running"].includes(keyword.collection?.status))) {
      watch.sawBusy = true;
      return false;
    }
    const advanced = watch.ids.some((keywordId) => keywordAttemptAt(keywordId) !== watch.baseline[keywordId]);
    return watch.sawBusy || advanced;
  }

  function recommendationResultToast() {
    const job = state.overview?.recommendation?.job || {};
    if (job.status === "success") return { message: "选题建议已更新", type: "success" };
    if (job.status === "failed") return { message: "选题建议更新失败" + (job.error ? `：${job.error}` : "，请稍后重试"), type: "error" };
    if (job.status === "skipped") return { message: "本次未生成选题建议" + (job.error ? `：${job.error}` : "，已有建议保留"), type: "info" };
    return { message: "选题建议更新状态暂时无法确认，请稍后刷新查看", type: "info" };
  }

  function settleUpdate() {
    const watch = state.updateWatch;
    const timedOut = Date.now() - watch.at > UPDATE_TIMEOUT_MS;
    const result = timedOut
      ? { message: "更新状态暂时无法确认，请稍后刷新查看", type: "info" }
      : watch.kind === "ai" ? recommendationResultToast() : roundResultToast(watch.ids);
    state.updateWatch = null;
    stopPolling();
    render();
    showToast(result.message, result.type);
  }

  function startPolling() {
    if (state.pollTimer) return;
    state.pollTimer = window.setInterval(async () => {
      if (document.hidden) return;
      try {
        const previous = state.overview;
        await loadOverview({ silent: true });
        await loadWorks();
        renderRecommendations();
        if (state.updateWatch) {
          if (updateSettled()) settleUpdate();
          return;
        }
        // 定时采集没有点击动作，退回「本轮从进行中变为空闲」的判定。
        const before = isRunningSnapshot(previous);
        const after = isRunning();
        if (before.busy && !after.busy) {
          stopPolling();
          render();
          if (before.collecting) {
            const ids = (previous?.keywords || []).filter(k => ["queued", "running"].includes(k.collection?.status)).map(k => k.id);
            const result = roundResultToast(ids);
            showToast(result.message, result.type);
          }
          if (before.aiRunning) {
            const result = recommendationResultToast();
            showToast(result.message, result.type);
          }
        }
      } catch (_error) {
        stopPolling();
        // 网络异常也不能把加载提示永久挂住。
        if (state.updateWatch) {
          state.updateWatch = null;
          showToast("更新状态暂时无法确认，请稍后刷新查看", "info");
        }
      }
    }, POLL_INTERVAL_MS);
  }

  function isRunningSnapshot(overview) {
    const keywords = overview?.keywords || [];
    const collecting = keywords.some((keyword) => ["queued", "running"].includes(keyword.collection?.status));
    const aiRunning = overview?.recommendation?.job?.status === "running";
    return { busy: collecting || aiRunning, collecting, aiRunning };
  }

  function stopPolling() {
    if (!state.pollTimer) return;
    window.clearInterval(state.pollTimer);
    state.pollTimer = 0;
  }

  // ------------------------------------------------------------ wiring

  function openKeywordModal() {
    const input = document.getElementById("radarKeywordInput");
    if (input) input.value = "";

    setMessage(document.getElementById("radarKeywordModalError"), "");
    openModal(modals.keyword);
    input?.focus();
  }

  // 关闭开关后，它控制的设置行灰态且不可操作；值仍随表单一起保存。
  function syncSettingsControls() {
    const collect = document.getElementById("radarCollectEnabled");
    const collectTime = document.getElementById("radarCollectTimeInput");
    if (collectTime) collectTime.disabled = !collect?.checked;
    setSettingsRowOff(collectTime, !collect?.checked);
    const ai = document.getElementById("radarAiEnabled");
    const time = document.getElementById("radarAiTimeInput");
    const aiOn = Boolean(ai?.checked);
    if (time) time.disabled = !aiOn;
    setSettingsRowOff(time, !aiOn);
  }

  function setSettingsRowOff(input, off) {
    if (!input || typeof input.closest !== "function") return;
    const row = input.closest(".settings-switch-row, .home-field");
    row?.classList?.toggle?.("is-off", off);
  }

  function openSettingsModal() {
    const settings = state.overview?.settings || state.settings || {};
    const collect = document.getElementById("radarCollectEnabled");
    const ai = document.getElementById("radarAiEnabled");
    const time = document.getElementById("radarAiTimeInput");
    if (collect) collect.checked = settings.collectEnabled !== false;
    const collectTime = document.getElementById("radarCollectTimeInput");
    if (collectTime) collectTime.value = settings.collectDailyTime || "";
    if (ai) ai.checked = settings.aiEnabled !== false;
    if (time) time.value = settings.aiDailyTime || "10:30";
    syncSettingsControls();
    const usage = document.getElementById("radarSettingsUsage");
    const data = state.overview?.usage || {};
    if (usage) {
      const breakdown = data.todayBreakdown || {};
      const labels = { search: "关键词搜索", lowfans: "低粉爆款", trend: "热度飙升", suggest: "关键词联想" };
      const bits = Object.entries(breakdown).map(([key, value]) => `${labels[key] || "其他查询"} ${value} 次`);
      usage.textContent = [
        `今日请求 ${data.todayRequests || 0} 次`,
        bits.length ? `今日请求明细：${bits.join("、")}` : "",
        `历史累计消耗：${trimPoints(Number(data.chargedTotalPoints || 0))} 积分（含今日）`,
        "积分由创作服务平台按有效查询结算，以平台账单为准。",
      ]
        .filter(Boolean)
        .join("\n");
    }
    setMessage(document.getElementById("radarSettingsError"), "");
    openModal(modals.settings);
  }

  async function saveSettings() {
    const fields = {
      collectEnabled: Boolean(document.getElementById("radarCollectEnabled")?.checked),
      collectDailyTime: document.getElementById("radarCollectTimeInput")?.value || "",
    };
    if (!/^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/.test(fields.collectDailyTime)) {
      setMessage(document.getElementById("radarSettingsError"), "每天采集时间请使用 HH:mm 格式（00:00–23:59）", true);
      return;
    }
    try {
      await api("/api/radar/settings", { method: "PUT", body: fields });
      closeModals();
      showToast("采集设置已保存", "success");
      await refresh();
    } catch (error) {
      setMessage(document.getElementById("radarSettingsError"), error.message, true);
    }
  }

  document.getElementById("radarTrendSubscribeCancel")?.addEventListener("click", closeModals);
  document.getElementById("radarTrendSubscribeConfirm")?.addEventListener("click", confirmTrendSubscription);

  document.getElementById("radarManageKeywordsButton")?.addEventListener("click", () => {
    closeModals(); renderKeywords(); openModal(modals.manageKeywords);
    modals.manageKeywords?.querySelector("[data-radar-panel-close]")?.focus();
  });
  document.getElementById("radarTrendsButton")?.addEventListener("click", () => {
    closeModals(); renderTrains(); openModal(modals.trends);
    modals.trends?.querySelector("[data-radar-panel-close]")?.focus();
  });
  document.querySelectorAll("[data-radar-panel-close]").forEach(button => button.addEventListener("click", closeModals));
  document.getElementById("radarResetFiltersButton")?.addEventListener("click", () => {
    state.tab = "all"; state.day = "all"; state.likesRange = "all"; state.filter = "all"; state.keywordIds = []; state.page = 1;
    renderTabs(); renderFilterSegments(); renderKeywordFilters();
    loadWorks({ reset: true }).catch(error => setMessage(dom.feedMessage, error.message, true));
  });

  dom.syncButton?.addEventListener("click", collectAccount);
  dom.settingsButton?.addEventListener("click", openSettingsModal);
  document.getElementById("radarCollectEnabled")?.addEventListener("change", syncSettingsControls);
  document.getElementById("radarAiEnabled")?.addEventListener("change", syncSettingsControls);
  dom.addKeywordButton?.addEventListener("click", openKeywordModal);
  dom.aiUpdate?.addEventListener("click", updateRecommendation);
  dom.aiEvidence?.addEventListener("click", showEvidence);
  dom.keywordMore?.addEventListener("click", () => {
    state.keywordsExpanded = !state.keywordsExpanded;
    renderKeywords();
  });
  dom.aiMore?.addEventListener("click", () => {
    state.aiExpanded = !state.aiExpanded;
    renderRecommendations();
  });
  document.getElementById("radarKeywordCancelButton")?.addEventListener("click", closeModals);
  document.getElementById("radarKeywordConfirmButton")?.addEventListener("click", () => addKeyword(document.getElementById("radarKeywordInput")?.value, undefined, undefined));
  document.getElementById("radarKeywordInput")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") addKeyword(document.getElementById("radarKeywordInput")?.value, undefined, undefined);
  });
  document.getElementById("radarSettingsCancelButton")?.addEventListener("click", closeModals);
  document.getElementById("radarSettingsConfirmButton")?.addEventListener("click", saveSettings);
  document.getElementById("radarDetailMonitorButton")?.addEventListener("click", monitorDetailAuthor);
  document.getElementById("radarDetailCloseButton")?.addEventListener("click", closeModals);
  document.getElementById("radarAnalysisCloseButton")?.addEventListener("click", closeModals);
  document.getElementById("radarDetailSaveButton")?.addEventListener("click", async () => {
    const work = state.activeWork;
    if (work) await toggleSaved(work);
  });
  document.getElementById("radarDetailTopicButton")?.addEventListener("click", () => {
    const work = state.activeWork;
    if (!work) return;
    openTopicModal({ kind: "work", workId: work.id, title: work.title || "", outline: "" });
  });
  document.getElementById("radarDetailBreakdownButton")?.addEventListener("click", () => {
    const work = state.activeWork;
    if (work) startBreakdown(work);
  });
  document.getElementById("radarTopicCancelButton")?.addEventListener("click", closeModals);
  document.getElementById("radarTopicConfirmButton")?.addEventListener("click", confirmTopic);

  createPicker("topicWeek", { input: "radarTopicWeekSelect", label: "计划安排", options: () => TOPIC_WEEKS.map((entry) => [entry.key, entry.label]) });
  createPicker("topicCategory", { input: "radarTopicCategorySelect", label: "选题分类", options: () => TOPIC_CATEGORIES.map((entry) => [entry.key, entry.label]) });
  createPicker("topicFormat", { input: "radarTopicFormatSelect", label: "内容形式", options: () => TOPIC_FORMATS.map((entry) => [entry.key, entry.label]) });

  renderTabs();
  renderFilterSegments();
  renderViewTabs();

  window.addEventListener("workspace-module-change", (event) => {
    if (event.detail?.module !== "radar") {
      stopPolling();
      return;
    }
    scheduleWorkLayout();
    if (!state.accountId) return;
    // 进入雷达时才拉数据：模块在后台时不占用数据请求，也不影响其他页面。
    if (state.loaded) {
      refresh()
        .then(() => {
          if (isRunning().busy) startPolling();
        })
        .catch((error) => setMessage(dom.feedMessage, error.message, true));
    } else {
      loadAll();
    }
  });

  function onAccountChange(accountId, force = false) {
    const next = String(accountId || "");
    if (!force && next === state.accountId && (state.loaded || initialLoad?.revision === viewRevision)) {
      if (state.loaded && !root.hidden) loadOverview({ silent: true }).catch(() => {});
      return;
    }
    viewRevision += 1;
    window.clearTimeout(billingTimer);
    stopPolling();
    state.updateWatch = null;
    closeModals();
    state.activeWork = null;
    state.pendingTopic = null;
    state.accountId = next;
    setInitialLoading(Boolean(next));
    state.loaded = false;
    state.overview = null;
    state.works = null;
    state.worksKey = ""; state.worksLoading = false; state.worksError = "";
    state.group = "all";
    state.tab = "all";
    state.day = "all";
    state.likesRange = "all";
    state.keywordIds = [];
    state.filter = "all";
    state.page = 1;
    state.suggestionKeywordId = "";
    state.detailWorkId = "";
    state.topicTarget = null;
    state.aiExpanded = false;
    state.keywordsExpanded = false;
    setPickerValue("day", "all");
    setPickerValue("filter", "all");
    renderTabs();
    renderFilterSegments();
    renderViewTabs();
    render();
    renderWorks();
    if (next && !root.hidden) loadAll();
  }

  function loadAll() {
    if (!state.accountId) return;
    if (initialLoad?.revision === viewRevision) return initialLoad.promise;
    const revision = viewRevision;
    setInitialLoading(true);
    const promise = (async () => {
      try {
        // Overview and works are independent for the initial, unfiltered account view.
        await Promise.all([loadOverview(), loadWorks()]);
        if (revision !== viewRevision) return;
        await prepareInitialCovers();
        if (revision !== viewRevision) return;
        layoutWorks();
        state.loaded = true;
        if (isRunning().busy) startPolling();
      } catch (error) {
        if (revision !== viewRevision) return;
        setMessage(dom.feedMessage, error.message, true);
      } finally {
        if (revision === viewRevision) {
          setInitialLoading(false);
          initialLoad = null;
          scheduleWorkLayout();
        }
      }
    })();
    initialLoad = { revision, promise };
    return promise;
  }

  window.addEventListener("focus", () => {
    if (state.accountId && state.loaded && !root.hidden) {
      refresh({ silent: true })
        .then(() => renderRecommendations())
        .catch(() => {});
    }
  });

  function clearSession() {
    closeModals();
    setInitialLoading(false);
    state.activeWork = null;
    viewRevision += 1;
    window.clearTimeout(billingTimer);
    stopPolling();
    state.overview = null;
    state.loaded = false;
    state.works = null;
    state.worksKey = ""; state.worksLoading = false; state.worksError = "";
    state.keywordIds = [];
    render();
    renderWorks();
  }

  let queuedSessionRefresh = null;
  function onSessionChange() {
    if (!state.accountId) return;
    if (!state.loaded) {
      const pending = initialLoad?.promise;
      if (pending) {
        // Subscription identity is often discovered just after the account on startup.
        // Finish the coherent initial load first, then revalidate without clearing it.
        if (queuedSessionRefresh === pending) return;
        queuedSessionRefresh = pending;
        const revision = viewRevision;
        pending.then(() => {
          if (queuedSessionRefresh === pending) queuedSessionRefresh = null;
          if (revision === viewRevision) onSessionChange();
        });
      } else { onAccountChange(state.accountId, true); }
      return;
    }
    viewRevision += 1;
    window.clearTimeout(billingTimer);
    stopPolling();
    state.updateWatch = null;
    // Credit ownership may change; recheck it while retaining this workspace's local content.
    // The old generation cannot release its append lock after this revision changes.
    state.worksLoading = false;
    state.worksError = "";
    renderLoadMore();
    state.overview = { ...state.overview, usage: { syncStatus: "syncing" } };
    renderStatus();
    const revision = viewRevision;
    refresh({ silent: true }).then(() => {
      if (revision !== viewRevision) return;
      if (isRunning().busy) startPolling();
    }).catch(error => {
      if (revision === viewRevision) setMessage(dom.feedMessage, error.message, true);
    });
  }

  window.radarModule = {
    onAccountChange, clearSession,
    openWork(accountId, workId) {
      if (!accountId || !workId) return;
      onAccountChange(accountId);
      return openDetail(workId);
    },
    onSessionChange,
  };
})();
