/* 账户与订阅：登录、套餐、积分明细与订单记录。

   数据来自工作台后端的 /api/subscription/*，由后端转发创作服务 API 平台。
   积分是否足够、应该扣多少一律由平台判定；本模块只负责展示与发起请求。

   约定：
   * 正常业务操作不弹出扣费确认，只有平台返回积分或订阅不足时才引导订阅。
   * 登录凭证只存在服务端，浏览器不读取也不缓存。 */
(() => {
  "use strict";

  const root = document.getElementById("accountContent");
  if (!root) return;

  const identityHost = document.getElementById("accountIdentity");
  const popover = document.getElementById("accountPopover");
  const popoverHead = document.getElementById("accountPopoverHead");
  const popoverFooter = document.getElementById("accountPopoverFooter");
  const modal = document.getElementById("subscriptionModal");

  const TIER_TAGS = ["基础额度", "专业额度", "高级额度"];
  const POINTS_VALIDITY_NOTICE = "新套餐立即生效，未到期的剩余积分继续保留，并按原有效期到期。使用时优先扣除即将到期的积分。";
  const FALLBACK_ENTITLEMENTS = ["全部现有工作台功能", "不额外限制创作账号数量"];
  const FALLBACK_CAPABILITIES = [
    "内容采集", "行业关键词", "监控对标博主", "AI 选题推荐", "音视频转文案",
    "拆解视频", "脚本生成与仿写", "生成标题", "生成封面", "数据复盘分析",
  ];
  const LEDGER_STATUS = {
    grant: ["已发放", "is-success"],
    freeze: ["处理中", "is-info"],
    settle: ["已结算", "is-success"],
    release: ["已退还", "record-status-neutral"],
    expire: ["已失效", "record-status-neutral"],
    refund_revoke: ["已撤销", "record-status-neutral"],
    adjust: ["已调整", "record-status-neutral"],
  };
  const LEDGER_TYPES = [["all", "全部类型"], ["consumed", "消耗"], ["frozen", "冻结"], ["issued", "发放"], ["expired", "失效"]];
  const LEDGER_PERIODS = [["current", "本周期"], ["last", "上一周期"]];
  const ORDER_STATES = [["all", "全部状态"], ["created", "待支付 / 待确认"], ["paid", "正在开通"], ["granted", "购买完成"], ["closed", "已关闭"], ["failed", "失败"]];
  const ORDER_PERIODS = [["3m", "最近三个月"], ["1m", "本月"]];
  const ORDER_STATUS_TEXT = {
    created: "待支付 / 待确认", granted: "购买完成", failed: "失败", pending: "待支付", paying: "支付中", paid: "已付款，正在开通", closed: "已关闭",
    refunding: "退款中", refunded: "已退款", recovering: "恢复中",
  };
  const ORDER_STATUS_CLASS = {
    created: "is-warning", granted: "is-success", failed: "is-warning", pending: "is-warning", paying: "is-info", paid: "is-success", closed: "record-status-neutral",
    refunding: "is-info", refunded: "record-status-neutral", recovering: "is-warning",
  };
  // 接口用渠道标识，界面按标识渲染中文。
  const PAY_CHANNEL_TEXT = { wechat: "微信支付", alipay: "支付宝", redeem_code: "兑换码支付" };

  const state = {
    loggedIn: false,
    phone: "",
    paymentOwner: "",
    // 通路未知时留空，不能预设成 mock：真实环境下登录框会误报「当前为模拟环境」。
    // 只有服务端明确回了 mode 才据此渲染演示文案。
    mode: "",
    error: "",
    subscription: null,
    points: null,
    trialGift: null,
    plans: [],
    ordersLoading: false,
    ordersError: "",
    ledger: { items: [], page: 1, pageSize: 10, total: 0, pageCount: 1 },
    orders: { items: [], page: 1, pageSize: 10, total: 0, pageCount: 1 },
    ledgerFilter: { period: "current", type: "all" },
    orderFilter: { status: "all", period: "3m" },
    smsTimer: 0,
    ledgerLoading: false,
    ledgerError: "",
    loadedLedger: false,
    loadedOrders: false,
  };

  /* 进入工作台和恢复「账户与订阅」会几乎同时各要一次数据；同一秒内只打一次平台，
     否则每次刷新都会把平台接口打两遍，很容易撞上平台的 120 次/分钟限流。 */
  let refreshInFlight = null;
  let refreshSucceededAt = 0;
  // 本地会话只负责提前恢复身份，迟到时不能覆盖概览或退出登录后的状态。
  let identityRevision = 0;
  // Unlike identityRevision, this changes only at authentication boundaries.
  let authGeneration = 0;
  let authMutation = null;
  function getSession() {
    return { loggedIn: state.loggedIn, owner: state.paymentOwner, generation: authGeneration };
  }
  function emitSessionChange() {
    authGeneration += 1;
    window.dispatchEvent(new CustomEvent("creation-session-changed", { detail: getSession() }));
  }
  function beginAuthMutation(blockIdentityReads = false) {
    // Set before notifying consumers: event handlers may synchronously request an overview.
    authMutation = blockIdentityReads ? authGeneration + 1 : null;
    identityRevision += 1;
    refreshInFlight = null;
    refreshSucceededAt = 0;
    state.loggedIn = false;
    state.phone = "";
    state.paymentOwner = "";
    state.subscription = null;
    state.points = null;
    state.trialGift = null;
    emitSessionChange();
  }
  function updateTrialGift(result, owner) {
    if (!state.loggedIn || !owner || owner !== state.paymentOwner) return false;
    // Guide configuration describes the offer; only grant describes what was issued.
    state.trialGift = { grant: result?.grant || null };
    renderPage();
    return true;
  }
  async function refreshBalanceAfterGrant(owner) {
    const generation = authGeneration;
    const sameIdentity = () => state.loggedIn && owner && owner === state.paymentOwner && generation === authGeneration;
    if (!sameIdentity()) return false;
    // A pre-grant overview may already be in flight. Never reuse it as confirmation.
    while (refreshInFlight) {
      await refreshInFlight;
      if (!sameIdentity()) return false;
    }
    return refresh(true);
  }
  let ledgerRevision = 0;
  const ledgerViews = new Map();
  const ledgerRequests = new Map();

  function resetLedger() {
    ledgerRevision += 1;
    ledgerViews.clear();
    ledgerRequests.clear();
    state.ledger = { items: [], page: 1, pageSize: 10, total: 0, pageCount: 1 };
    state.loadedLedger = false;
    state.ledgerLoading = false;
    state.ledgerError = "";
  }

  function esc(value) {
    return String(value === null || value === undefined ? "" : value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[char]));
  }

  /* 682.500 → 682.5，99.00 → 99：界面只保留有效小数位。 */
  function trimZeros(value) {
    const text = String(value === null || value === undefined ? "0" : value).trim();
    if (text.indexOf(".") < 0) return text || "0";
    return text.replace(/\.?0+$/, "") || "0";
  }

  function numberText(value) {
    return trimZeros(value === null || value === undefined ? "0" : value);
  }

  function formatDateTime(value, withYear) {
    const text = String(value || "");
    const match = text.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    if (!match) return text || "—";
    const stamp = match[4] + ":" + match[5];
    // 与工作台既有日期口径一致：带年份用 年.月.日，不带宽度的列表用 月.日。
    return (withYear ? match[1] + "." + match[2] + "." + match[3] + " " : match[2] + "." + match[3] + " ") + stamp;
  }

  function balanceText() {
    if (!state.points) return state.error ? "暂不可用" : "加载中…";
    return numberText(state.points && state.points.available);
  }

  function frozenText() {
    return numberText(state.points && state.points.frozen);
  }

  function planNameText() {
    return (state.subscription && state.subscription.planName) || "未订阅";
  }

  function isSubscriptionActive() {
    const subscription = state.subscription;
    if (!subscription || subscription.status !== "active") return false;
    const now = Date.now();
    const start = Date.parse(subscription.periodStart);
    const end = Date.parse(subscription.currentPeriodEnd);
    return Number.isFinite(end) && now < end
      && (!Number.isFinite(start) || start <= now);
  }

  function toast(message, type) {
    if (typeof window.showToast === "function") window.showToast(message, type || "info");
  }

  async function api(path, options) {
    const config = Object.assign({ headers: { Accept: "application/json" } }, options || {});
    if (config.body !== undefined) {
      config.method = config.method || "POST";
      config.headers = Object.assign({}, config.headers, { "Content-Type": "application/json" });
      config.body = JSON.stringify(config.body);
    }
    let response;
    let payload = null;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      response = await fetch(path, {...config, signal: controller.signal});
      try { payload = await response.json(); } catch (_) { payload = null; }
    } catch (error) {
      throw { code: "unreachable", message: "无法连接本地服务，请确认服务已启动后重试。" };
    } finally { clearTimeout(timeout); }
    if (response.ok && payload) return payload;
    const detail = (payload && payload.detail) || {};
    throw {
      code: detail.code || "upstream_unavailable",
      message: detail.message || "请求失败，请稍后重试。",
      details: detail.details || null,
      needsSubscription: Boolean(detail.needsSubscription),
    };
  }

  // ------------------------------------------------------------------ 数据读取

  function refresh(force) {
    if (authMutation !== null) return Promise.resolve(false);
    if (refreshInFlight) return refreshInFlight;
    if (!force && refreshSucceededAt && Date.now() - refreshSucceededAt < 1000) return Promise.resolve();
    const request = performRefresh()
      .then((ok) => { if (ok && refreshInFlight === request) refreshSucceededAt = Date.now(); return ok; })
      .finally(() => { if (refreshInFlight === request) refreshInFlight = null; });
    refreshInFlight = request;
    return request;
  }

  async function performRefresh() {
    const revision = identityRevision;
    try {
      const overview = await api("/api/subscription/overview", { cache: "no-store" });
      if (revision !== identityRevision) return false;
      const identityChanged = state.loggedIn !== Boolean(overview.loggedIn) ||
        (overview.phone && overview.phone !== state.phone) ||
        ((overview.paymentOwner || "") !== state.paymentOwner);
      identityRevision += 1;
      state.loggedIn = Boolean(overview.loggedIn);
      state.error = "";
      state.mode = overview.mode || state.mode;
      state.phone = overview.phone || state.phone;
      if (identityChanged) {
        state.trialGift = null;
        stopPayment();
        paymentAttempt = null;
        if (modal.open) closeModal();
        redemption = null;
        window.radarModule?.onSessionChange?.();
      }
      state.paymentOwner = overview.paymentOwner || "";
      if (identityChanged) emitSessionChange();
      if (state.loggedIn && state.paymentOwner && restoredPaymentOwner !== state.paymentOwner) {
        restoredPaymentOwner = state.paymentOwner;
        const saved = readPayment();
        if (saved) resumePayment(saved);
      }
      state.plans = (overview.plans && overview.plans.items) || [];
      state.subscription = overview.subscription || null;
      state.points = overview.points || null;
      if (Object.prototype.hasOwnProperty.call(overview, "trialGift")) state.trialGift = overview.trialGift;
      window.dispatchEvent(new CustomEvent("subscription-refreshed"));
      if (identityChanged) { resetLedger(); resetOrders(); }
      state.loadedOrders = false;
      // 身份和余额已就绪，不再等待积分明细或订单列表。
      renderIdentity();
      renderPage();
      if (state.loggedIn) {
        // 只读当前可见的栏目，切到其它栏目时再按需加载：订单与积分明细不该在每次
        // 刷新页面时都打一遍平台（可直接吃掉一半的平台配额）。
        await loadLedger();
        if (listModal.open && listView === "orders") await loadOrders();
      } else {
        state.ledger = { items: [], page: 1, pageSize: 10, total: 0, pageCount: 1 };
        state.orders = { items: [], page: 1, pageSize: 10, total: 0, pageCount: 1 };
      }
      return true;
    } catch (error) {
      // 读取失败（例如平台限流）不等于登录失效：保留上一次状态并给重试，
      // 绝不把界面降级成「未登录」，否则左下角会冒出一个不该有的登录入口。
      if (revision !== identityRevision) return false;
      state.error = error.message || "账户信息读取失败。";
      toast(state.error, "error");
      return false;
    } finally {
      renderIdentity();
      renderPage();
    }
  }

  async function loadLedger(force = false) {
    if (!state.loggedIn) return;
    if (force) ledgerRequests.clear();
    const key = [state.ledger.page, state.ledgerFilter.period, state.ledgerFilter.type].join("|");
    const revision = ++ledgerRevision;
    const cached = ledgerViews.get(key);
    const page = state.ledger.page;
    state.ledger = cached || { items: [], page, pageSize: 10, total: 0, pageCount: 1 };
    state.loadedLedger = Boolean(cached);
    state.ledgerLoading = true;
    state.ledgerError = "";
    renderPage();
    const requestKey = key + (force ? "|refresh" : "");
    let request = ledgerRequests.get(requestKey);
    if (!request) {
      request = api("/api/subscription/ledger?page=" + page
        + "&pageSize=10&period=" + encodeURIComponent(state.ledgerFilter.period)
        + "&type=" + encodeURIComponent(state.ledgerFilter.type)
        + (force ? "&refresh=true" : ""));
      ledgerRequests.set(requestKey, request);
    }
    try {
      const result = await request;
      if (revision !== ledgerRevision) return;
      if (force) ledgerViews.clear();
      if (ledgerViews.size >= 20) ledgerViews.delete(ledgerViews.keys().next().value);
      ledgerViews.set(key, result);
      state.ledger = result;
      state.loadedLedger = true;
    } catch (error) {
      if (revision !== ledgerRevision) return;
      state.ledgerError = error.message || "积分明细读取失败，请重试。";
    } finally {
      if (ledgerRequests.get(requestKey) === request) ledgerRequests.delete(requestKey);
      if (revision === ledgerRevision) {
        state.ledgerLoading = false;
        renderPage();
      }
    }
  }

  async function loadOrders(renderLoading = true) {
    if (!state.loggedIn) return;
    const revision = ++ordersRevision;
    const owner = state.paymentOwner;
    state.ordersLoading = true;
    state.ordersError = "";
    if (renderLoading) renderList();
    try {
      const orders = await api("/api/subscription/orders?page=" + state.orders.page
        + "&pageSize=10&status=" + encodeURIComponent(state.orderFilter.status)
        + "&period=" + encodeURIComponent(state.orderFilter.period));
      if (revision !== ordersRevision || owner !== state.paymentOwner) return;
      state.orders = orders;
      state.loadedOrders = true;
    } catch (error) {
      if (revision !== ordersRevision || owner !== state.paymentOwner) return;
      state.ordersError = error.message || "订单读取失败，请重试。";
    } finally {
      if (revision === ordersRevision) {
        state.ordersLoading = false;
        renderList();
      }
    }
  }

  // ------------------------------------------------------------------ 侧栏入口

  function renderIdentity() {
    if (identityHost) {
      // 未登录也能用工作台，左下角就是登录入口（只写「登录」，与上方导航图标同轴居中）。
      const phone = state.loggedIn ? (state.phone || "已登录") : "登录";
      // 未登录时入口只剩一行文字，分隔线加上内边距会把它压得比右侧收起按钮低。
      identityHost.classList.toggle("is-logged-out", !state.loggedIn);
      identityHost.innerHTML =
        '<button class="identity-trigger" id="identityTrigger" type="button" popovertarget="accountPopover"'
        + ' aria-expanded="false" aria-controls="accountPopover" aria-label="打开账号菜单">'
        + '<span class="identity-copy account-switcher-copy"><strong>' + esc(phone) + "</strong>"
        + "</span></button>";
    }
    if (!popoverHead || !popoverFooter) return;
    if (state.loggedIn) {
      popoverHead.innerHTML =
        '<div class="popover-account-copy account-switcher-copy"><strong>' + esc(state.phone || "已登录")
        + "</strong><small>可用积分 " + esc(balanceText()) + "</small></div>"
        + '<span class="plan-badge' + (isSubscriptionActive() ? ' is-active' : '') + '">'
        + esc(planNameText()) + "</span>";
      popoverFooter.hidden = false;
      popoverFooter.innerHTML = '<span class="popover-session">已登录账号</span>'
        + '<button type="button" class="text-button" data-sub-action="logout">退出登录</button>';
    } else {
      popoverHead.innerHTML = '<strong>尚未登录</strong>'
        + '<button type="button" class="text-button" data-sub-action="login">登录 / 注册</button>';
      popoverFooter.hidden = true;
      popoverFooter.innerHTML = "";
    }
  }

  function closeAccountMenu() {
    if (popover && popover.matches(":popover-open")) popover.hidePopover();
  }

  if (popover) {
    popover.addEventListener("beforetoggle", (event) => {
      if (event.newState !== "open") return;
      const trigger = document.getElementById("identityTrigger");
      if (!trigger) return;
      const bounds = trigger.getBoundingClientRect();
      popover.style.left = Math.max(12, Math.min(bounds.left, window.innerWidth - 272)) + "px";
      popover.style.bottom = Math.max(12, window.innerHeight - bounds.top + 10) + "px";
    });
    popover.addEventListener("toggle", (event) => {
      document.getElementById("identityTrigger")?.setAttribute("aria-expanded", String(event.newState === "open"));
    });
    window.addEventListener("resize", closeAccountMenu);
  }

  // ------------------------------------------------------------------ 页面渲染

  function summaryHTML() {
    const cells = [["当前套餐", planNameText()], ["可用积分", balanceText()], ["冻结积分", frozenText()],
      ["本周期发放", numberText(state.subscription && state.subscription.periodPoints)],
      ["当前套餐到期时间", formatDateTime(state.subscription && state.subscription.currentPeriodEnd, true)]];
    if (state.points?.subscriptionAvailable != null) cells.push(["订阅可用积分", numberText(state.points.subscriptionAvailable)]);
    if (state.points?.trialAvailable != null) cells.push(["体验可用积分", numberText(state.points.trialAvailable)]);
    const trialCycles = (state.points?.cycles || []).filter(cycle => cycle.source === "trial_gift");
    const grant = state.trialGift?.grant || state.trialGift;
    if (grant?.amount != null) {
      cells.push(["体验已发放", numberText(grant.amount)]);
      cells.push(["体验到期时间", formatDateTime(grant.expiresAt || trialCycles[0]?.expiresAt, true)]);
    } else if (trialCycles.length) {
      // Show issued amounts, never the remaining balance or current offer configuration.
      for (const cycle of trialCycles) {
        if (cycle.granted != null) cells.push(["体验已发放", numberText(cycle.granted)]);
        cells.push(["体验到期时间", formatDateTime(cycle.expiresAt, true)]);
      }
    }
    return '<dl class="summary">' + cells.map((cell, index) => '<div><dt>' + cell[0]
      + '</dt><dd' + (cell[0].includes("到期时间") ? ' class="date"' : '') + '><span>' + esc(cell[1] || "—") + '</span>'
      + (index === 0 ? '<button class="am-primary-action account-subscribe" type="button" data-sub-action="open-plans">订阅</button>' : '')
      + '</dd></div>').join('') + '</dl>';
  }

  function pointsExpiryHTML() {
    const now = Date.now();
    const cycles = (state.points?.cycles || [])
      .filter(cycle => cycle.status === "active" && Number(cycle.available) > 0 && Date.parse(cycle.expiresAt) > now)
      .sort((a, b) => Date.parse(a.expiresAt) - Date.parse(b.expiresAt));
    if (!cycles.length) return "";
    return '<section class="points-expiry" aria-label="积分到期时间"><h2>积分到期时间</h2>'
      + '<p>各批积分按各自有效期使用，优先扣除即将到期的积分。</p><ul>'
      + cycles.map(cycle => '<li><span>' + esc(cycle.source === "trial_gift" ? "体验积分" : cycle.planName || "订阅积分")
        + '</span><strong>' + esc(numberText(cycle.available)) + ' 积分</strong><span>到期于 '
        + esc(formatDateTime(cycle.expiresAt, true)) + '</span></li>').join('') + '</ul></section>';
  }

  function planPriceHTML(plan) {
    const current = plan.priceCents;
    const original = plan.originalPriceCents;
    const discounted = Number.isSafeInteger(current) && Number.isSafeInteger(original)
      && current >= 0 && original > 0 && original > current;
    let prefix = "";
    if (discounted) {
      const rate = current / original * 10;
      const rounded = Number(rate.toFixed(2));
      const label = rounded + " 折";
      const originalText = (original / 100).toFixed(2).replace(/\.?0+$/, "");
      prefix = '<div class="original-price-row"><span class="original-price">原价 <del>¥'
        + esc(originalText) + ' / 月</del></span><span class="discount-badge">'
        + esc(label) + '</span></div>';
    }
    return '<div class="' + (discounted ? "discount-pricing" : "plan-pricing") + '">'
      + prefix + '<div class="price"><span class="currency">¥</span><b>'
      + esc(trimZeros(plan.priceText)) + '</b><span>/ 月</span>'
      + (discounted ? '<span class="sale-label">优惠价</span>' : "") + '</div></div>';
  }

  function planCardHTML(plan, index) {
    const current = Boolean(state.subscription && state.subscription.planId === plan.planId);
    const entitlements = (plan.entitlements && plan.entitlements.length ? plan.entitlements : FALLBACK_ENTITLEMENTS);
    const capabilities = (plan.capabilities && plan.capabilities.length ? plan.capabilities : FALLBACK_CAPABILITIES);
    return '<article class="plan-card' + (current ? " current" : "") + '">'
      + '<header class="plan-card-heading"><div class="plan-title-row"><h3>' + esc(plan.name) + "</h3>"
      + (current ? '<span class="current-tag">当前套餐</span>' : "") + "</div>"
      + '<span class="plan-tier-tag tier-' + (index % 3) + '">' + esc(TIER_TAGS[index] || "套餐") + "</span></header>"
      + planPriceHTML(plan)
      + '<p class="plan-points"><strong>' + esc(numberText(plan.points)) + "</strong><span>积分 / 周期</span></p>"
      + '<ul class="plan-features plan-entitlements">'
      + entitlements.map((item) => '<li><span class="tick">✓</span>' + esc(item) + "</li>").join("")
      + "</ul>"
      + '<p class="plan-capabilities-label">包含以下功能</p>'
      + '<ul class="plan-capabilities" aria-label="包含功能">'
      + capabilities.map((item) => '<li><span class="tick">✓</span>' + esc(collectionDisplayName(item)) + "</li>").join("")
      + "</ul>"
      + '<button class="am-secondary-action plan-buy-button" type="button" data-sub-buy="' + esc(plan.planId) + '">'
      + (current ? "再次购买" : "购买" + esc(plan.name)) + "</button></article>";
  }

  // The legacy custom-service plan is replaced only in the storefront.
  // Keep all backend subscription and historical order records unchanged.
  const LEGACY_CUSTOM_PLAN_ID = "abc";

  function customServiceCardHTML() {
    return "<article class=\"plan-card custom-service-card\"><header class=\"plan-card-heading\"><h3>定制服务</h3><span class=\"plan-tier-tag tier-0\">专属方案</span></header><div class=\"custom-title\">按需定制<span class=\"custom-mark\" aria-hidden=\"true\">↗</span></div><p class=\"custom-intro\">根据你的业务需求，沟通适合的功能与服务方案。</p><div class=\"custom-detail\"><p class=\"custom-lead\">从一个想法，到适合你的方案</p><ol class=\"steps\"><li><span class=\"step-number\">01</span><div><h3>需求沟通</h3><p>聊聊你的业务场景与目标</p></div></li><li><span class=\"step-number\">02</span><div><h3>范围确认</h3><p>一起梳理需要定制的内容</p></div></li><li><span class=\"step-number\">03</span><div><h3>方案商议</h3><p>结合实际需求，沟通实施方式</p></div></li></ol></div><button data-sub-action=\"contact-custom\" class=\"contact-button\" type=\"button\" aria-haspopup=\"dialog\">联系定制 <span aria-hidden=\"true\">↗</span></button></article>";
  }

  function customServiceModal() {
    openModal("聊聊你的定制需求", `<header class="dialog-heading"><span class="dialog-eyebrow"><i></i>专属定制咨询</span><button data-sub-action="close" class="close-button am-modal-dismiss" type="button" aria-label="关闭联系弹窗" autofocus><svg class="am-modal-close-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true" focusable="false"><path d="M6 6l12 12M18 6 6 18"/></svg></button></header>
      <h2 id="customDialogTitle">聊聊你的定制需求</h2>
      <p id="customDialogDescription">添加微信，沟通你的业务场景与想法。</p>
      <section class="contact-panel" aria-label="微信联系方式">
        <div class="contact-qr"><img src="/static/images/custom-service-wechat.png" width="844" height="860" alt="杰少Coding 的微信二维码，使用微信扫一扫添加" /></div>
        <p class="wechat-id">杰少Coding</p>
        <p class="scan-caption">打开微信扫一扫，添加好友咨询</p>
      </section>
      <p class="contact-tip">可以提前整理使用场景与期望功能，<br class="desktop-break">方便沟通更适合你的方案。</p>`, true);
  }

  function plansHTML() {
    const purchasablePlans = state.plans.filter((plan) => plan.planId !== LEGACY_CUSTOM_PLAN_ID);
    // 套餐各自独立成卡：容器保持透明，卡片自带白底，与确认版一致。
    return '<div class="plan-grid">'
      + purchasablePlans.map((plan, index) => planCardHTML(plan, index)).join("")
      + customServiceCardHTML()
      + '</div>' + (purchasablePlans.length ? '<section class="plan-rules" aria-label="购买与周期规则"><div class="section-head"><h2>购买与周期规则</h2></div>'
      + noticeHTML(POINTS_VALIDITY_NOTICE, "冻结积分仍用于原任务结算。", true)
      + '<p class="page-foot">各批积分按各自有效期使用 · 手动购买，无自动扣款。订阅到期不影响已保存的本地内容。</p></section>' : '<div class="empty">暂时没有可售套餐，可联系咨询定制服务。</div>');
  }

  function noticeHTML(text, small, info) {
    return '<div class="notice' + (info ? " info" : "") + '"><span class="notice-icon">' + (info ? "i" : "!") + "</span><div>"
      + "<strong>" + esc(text) + "</strong>" + (small ? "<small>" + esc(small) + "</small>" : "") + "</div></div>";
  }

  function selectHTML(id, options, selected) {
    return '<select class="am-select" id="' + id + '" aria-label="' + esc(options.label) + '">'
      + options.items.map((entry) => '<option value="' + esc(entry[0]) + '"'
        + (entry[0] === selected ? " selected" : "") + ">" + esc(entry[1]) + "</option>").join("")
      + "</select>";
  }

  function pagerHTML(page, pageCount, total) {
    const start = Math.max(1, Math.min(page - 2, pageCount - 4));
    const pages = [];
    for (let index = 0; index < Math.min(5, pageCount); index += 1) pages.push(start + index);
    return '<footer class="monitor-list-foot"><span class="monitor-hint">共 ' + total + " 条 · 每页 10 条</span>"
      + '<nav class="monitor-pager" aria-label="列表分页">'
      + '<button class="monitor-page-button" type="button" data-sub-page="' + (page - 1) + '"'
      + (page <= 1 ? " disabled" : "") + ' aria-label="上一页"><svg class="wb-nav-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m14 6-6 6 6 6"/></svg></button>'
      + pages.map((number) => '<button class="monitor-page-button' + (number === page ? " is-active" : "")
        + '" type="button" data-sub-page="' + number + '" aria-label="第 ' + number + ' 页"'
        + (number === page ? ' aria-current="page"' : "") + ">" + number + "</button>").join("")
      + '<button class="monitor-page-button" type="button" data-sub-page="' + (page + 1) + '"'
      + (page >= pageCount ? " disabled" : "") + ' aria-label="下一页"><svg class="wb-nav-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m10 6 6 6-6 6"/></svg></button></nav></footer>';
  }

  function collectionDisplayName(value) {
    return String(value || "").replace(/行业雷达|雷达监控|雷达/g, "内容采集");
  }

  function ledgerBusinessHTML(item) {
    if (item.refType !== "task") return esc(collectionDisplayName(item.business || "—"));
    const context = item.businessContext || {};
    const api = item.interface || {};
    const source = { topic_recommendations: "选题推荐", monitor: "监控", radar: "内容采集", script: "脚本", review: "复盘", breakdown: "拆解视频", settings: "项目设置" }[context.source];
    const capabilities = { profile: "博主资料", posts: "博主作品列表", video: "视频详情",
      search: "关键词视频搜索", low_fans: "低粉爆款", trends: "热度飙升榜", suggestions: "关键词联想" };
    const scriptAction = source === "脚本" && { generate_title: "生成标题", generate_cover_title: "生成封面标题", generate_cover: "生成封面" }[context.action];
    const reviewAction = source === "复盘" && { review_video: "AI 辅助复盘", suggest_factors: "AI 因子建议", home_advice: "账号下一步建议" }[context.action];
    // 拆解视频向平台提交解析与转写两个独立结算任务，操作备注要分开，不能都叫「视频文案转写」。
    const breakdownAction = source === "拆解视频"
      && { parse_video: "视频解析", transcribe_audio: "音频转写文字", transcribe_video: "视频转文案",
        analyze_structure: "结构及拆解分析" }[context.action];
    const breakdownNote = source === "拆解视频" && ({ transcribe_video: "视频文案转写" }[context.action] || breakdownAction);
    const positioningAction = source === "项目设置" && context.action === "enhance_positioning" ? "账号定位完善" : "";
    const radarAction = source === "内容采集" && context.action === "resolve_author" ? "识别视频博主" : "";
    const operation = radarAction || positioningAction || breakdownAction || reviewAction || scriptAction || capabilities[api.capability] || (api.scene === "radar_topics" ? "AI 选题" : "");
    const title = source && operation ? source + " · " + operation : (collectionDisplayName(item.business) || "任务消费");
    const labels = [];
    if (context.trigger === "schedule") labels.push(context.accountId ? "系统定时" : "系统定时 · 共享采集");
    if (context.accountId) labels.push("发起账号：" + (context.accountName || "未命名账号"));
    if (breakdownNote) labels.push("操作：" + breakdownNote);
    if (reviewAction) labels.push("操作：" + reviewAction);
    if (context.targetId || context.targetName || context.targetHandle) {
      const readable = (value) => {
        const text = String(value || "").trim();
        return /^MS4w[A-Za-z0-9_-]+$/.test(text) ? "" : text;
      };
      if (api.capability === "video" || context.action === "resolve_author") {
        const title = readable(context.targetName);
        labels.push("视频：" + (title ? (title.length > 60 ? title.slice(0, 60) + "…" : title) : "视频详情查询"));
      } else {
        const name = readable(context.targetName);
        const handle = readable(context.targetHandle);
        labels.push("博主：" + (name || (handle ? "抖音号 " + handle : "博主昵称暂缺"))
          + (name && handle ? "（抖音号：" + handle + "）" : ""));
      }
    }
    if (["3:4", "4:3"].includes(context.aspectRatio)) labels.push("生成 " + context.aspectRatio + " 封面");
    if (context.keyword) labels.push("关键词：" + context.keyword);
    if (!source || (!context.accountId && context.trigger !== "schedule")) labels.push("历史记录未记录来源或发起账号");
    return '<div class="record-business-title">' + esc(title) + '</div>'
      + '<div class="record-business-context">' + labels.map(esc).join(" ｜ ") + '</div>';
  }

  function ledgerHTML() {
    const rows = state.ledger.items || [];
    return '<div class="section-head"><h2>积分明细</h2><div class="filters">'
      + '<button class="am-secondary-action" type="button" data-sub-action="refresh-ledger"'
      + (state.ledgerLoading ? " disabled" : "") + '>刷新</button>'
      + selectHTML("pointPeriod", { label: "积分周期", items: LEDGER_PERIODS }, state.ledgerFilter.period)
      + selectHTML("pointType", { label: "积分类型", items: LEDGER_TYPES }, state.ledgerFilter.type)
      + "</div></div>"
      + (state.ledgerLoading ? '<p class="record-note" role="status">' + (state.loadedLedger ? '正在更新积分明细…' : '正在加载积分明细…') + '</p>' : "")
      + (state.ledgerError ? '<p class="record-note" role="alert">' + esc(state.ledgerError) + (state.loadedLedger ? ' 当前显示上次结果。' : '') + '</p>' : "")
      + '<div class="table-scroll"><table class="am-table records ledger-table"><thead><tr><th>业务</th><th>积分变化</th>'
      + '<th>状态</th><th>关联记录</th><th>时间</th></tr></thead><tbody>'
      + rows.map((item) => {
        const status = LEDGER_STATUS[item.type] || ["已完成", ""];
        return '<tr><td class="record-name">' + ledgerBusinessHTML(item) + "</td>"
          + '<td class="point-change ' + esc(item.type) + '">' + esc(numberText(item.pointsChange)) + "</td>"
          + '<td><span class="am-status ' + status[1] + '">' + esc(status[0]) + "</span></td>"
          + '<td><button class="record-link" type="button" data-sub-ref="' + esc(item.refId || "") + '">'
          + esc(item.refId || "—") + "</button></td>"
          + '<td class="record-meta">' + esc(formatDateTime(item.createdAt)) + "</td></tr>";
      }).join("") + "</tbody></table></div>"
      + (rows.length || state.ledgerLoading || state.ledgerError ? "" : '<div class="empty"><strong>暂无相关记录</strong>换个类型或周期查看。</div>')
      + (state.ledger.truncated ? '<p class="record-note">仅显示最近 2000 条流水。</p>' : "")
      + pagerHTML(state.ledger.page, state.ledger.pageCount, state.ledger.total)
      + '<p class="page-foot">冻结积分暂不可用，任务完成后按实际结果结算。各批未使用积分按各自有效期到期，续购不改变原有效期；历史创作内容继续保留。</p>';
  }

  function ordersHTML() {
    const rows = state.orders.items || [];
    return '<div class="section-head"><h2>订单记录</h2><div class="filters">'
      + selectHTML("orderStatus", { label: "订单状态", items: ORDER_STATES }, state.orderFilter.status)
      + selectHTML("orderPeriod", { label: "订单时间", items: ORDER_PERIODS }, state.orderFilter.period)
      + "</div></div>"
      + '<div class="table-scroll"><table class="am-table records"><thead><tr><th>套餐</th>'
      + '<th>实付金额</th><th>发放积分</th><th>状态</th><th>订单号</th><th>下单时间</th>'
      + '<th>支付时间</th><th>支付方式</th></tr></thead><tbody>'
      + rows.map((order) => {
        const pending = ["pending", "created"].includes(order.status);
        return '<tr><td class="record-name">' + esc(order.planName || "—") + "</td>"
          + '<td class="record-amount">' + (pending ? "—" : "¥ " + esc(order.priceText || "0.00")) + "</td>"
          + '<td class="record-amount">' + (pending || (state.mode === "live" && order.status === "paid") ? "—" : esc(numberText(order.points)) + " 积分") + "</td>"
          + '<td><span class="record-status-group"><span class="am-status '
          + esc(ORDER_STATUS_CLASS[order.status] || "record-status-neutral") + '">'
          + esc(ORDER_STATUS_TEXT[order.status] || order.status || "—") + "</span>"
          + '<button class="record-status-action" type="button" data-sub-order="' + esc(order.orderId) + '">'
          + (pending ? '查看待支付订单' : order.status === 'paid' ? '查看开通进度' : '查看订单') + '</button>'
          + "</span></td>"
          + '<td class="record-meta">' + esc(order.orderId) + "</td>"
          + '<td class="record-meta">' + esc(formatDateTime(order.createdAt, true)) + "</td>"
          + '<td class="record-meta">' + (order.paidAt ? esc(formatDateTime(order.paidAt, true)) : "—") + "</td>"
          + "<td>" + (order.payChannel ? esc(PAY_CHANNEL_TEXT[order.payChannel] || order.payChannel) : "—") + "</td></tr>";
      }).join("") + "</tbody></table></div>"
      + (rows.length || state.ordersLoading || state.ordersError ? "" : '<div class="empty"><strong>暂无相关订单</strong>尝试切换筛选条件。</div>')
      + '<p class="record-note">待支付订单不会变更当前套餐与积分。</p>'
      + (state.ordersLoading ? '<p role="status">正在加载订单记录…</p>' : "")
      + (state.ordersError ? '<p role="alert">' + esc(state.ordersError) + ' <button type="button" class="text-button" data-sub-action="retry-orders">重试</button></p>' : "")
      + pagerHTML(state.orders.page, state.orders.pageCount, state.orders.total);
  }

  function renderPage() {
    const split = state.loggedIn;
    root.classList.toggle("split-modules", split);
    const heading = '<header class="account-heading"><div><h1>账户与订阅</h1>'
      + '<p>管理套餐、积分与订单。</p></div>'
      + (state.loggedIn ? '<button class="text-button account-orders" type="button" data-sub-action="open-orders">订单记录</button>' : "") + "</header>";
    if (state.error) {
      // 读取失败（例如平台限流）时留在原地给重试，不切成「未登录」的样子。
      root.innerHTML = '<div class="account-overview">' + heading + "</div>"
        + '<section id="pageBody"><div class="empty"><strong>账户信息读取失败</strong>'
        + "<p>" + esc(state.error) + "</p>"
        + '<button class="am-primary-action" type="button" data-sub-action="retry">重试</button></div></section>';
      return;
    }
    if (!state.loggedIn) {
      root.innerHTML = '<div class="account-overview">' + heading + "</div>"
        + '<section id="pageBody"><div class="empty"><strong>登录后查看你的套餐与积分</strong>'
        + '<p>使用手机号验证码登录，首次登录自动注册。</p>'
        + '<button class="am-primary-action" type="button" data-sub-action="login">登录 / 注册</button></div></section>';
      return;
    }
    root.innerHTML = '<div class="account-overview">' + heading + summaryHTML() + pointsExpiryHTML() + '</div>'
      + '<section id="pageBody" aria-label="积分明细">' + ledgerHTML() + '</section>';
    if (listModal.open && listView === "plans") renderList();
    enhanceFilters();
  }

  /* 下拉菜单沿用选题模块的悬浮卡片样式，保证全站一致。 */
  function closeFilterMenus() {
    document.querySelectorAll("#accountContent .record-filter, #accountListModal .record-filter").forEach((host) => {
      const menu = host.querySelector("[role=menu]");
      const button = host.querySelector("[aria-haspopup]");
      if (menu) menu.hidden = true;
      if (button) button.setAttribute("aria-expanded", "false");
    });
  }

  function enhanceFilters(container = root) {
    container.querySelectorAll(".filters select").forEach((select) => {
      const host = document.createElement("div");
      host.className = "topics-select-control record-filter";
      select.before(host);
      host.append(select);
      select.hidden = true;
      const label = select.getAttribute("aria-label") || "筛选";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "am-input topics-select-button";
      button.setAttribute("aria-label", label);
      button.setAttribute("aria-haspopup", "menu");
      button.setAttribute("aria-expanded", "false");
      button.innerHTML = '<span class="topics-select-value">' + esc(select.options[select.selectedIndex].textContent)
        + '</span><svg class="topics-select-chevron" width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">'
        + '<path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
      const menu = document.createElement("div");
      menu.className = "topics-select-menu";
      menu.setAttribute("role", "menu");
      menu.setAttribute("aria-label", label);
      menu.hidden = true;
      Array.from(select.options).forEach((option) => {
        const item = document.createElement("button");
        item.type = "button";
        item.setAttribute("role", "menuitemradio");
        item.setAttribute("aria-checked", String(option.selected));
        item.classList.toggle("is-current", option.selected);
        item.textContent = (option.selected ? "✓ " : "") + option.textContent;
        item.addEventListener("click", () => {
          select.value = option.value;
          closeFilterMenus();
          select.dispatchEvent(new Event("change", { bubbles: true }));
          button.focus();
        });
        menu.append(item);
      });
      button.addEventListener("click", () => {
        const open = menu.hidden;
        closeFilterMenus();
        if (!open) return;
        menu.hidden = false;
        button.setAttribute("aria-expanded", "true");
      });
      button.addEventListener("keydown", (event) => {
        if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
        event.preventDefault();
        menu.hidden = false;
        button.setAttribute("aria-expanded", "true");
        (menu.querySelector(".is-current") || menu.firstElementChild)?.focus();
      });
      host.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          closeFilterMenus();
          button.focus();
        }
      });
      host.addEventListener("focusout", (event) => {
        if (!host.contains(event.relatedTarget)) closeFilterMenus();
      });
      host.append(button, menu);
    });
  }

  // 列表与支付分别使用原生 dialog，子弹窗关闭后保留列表上下文。
  const listModal = document.createElement("dialog");
  listModal.id = "accountListModal";
  document.body.append(listModal);
  let listView = "";
  let listTrigger = null;
  let ordersRevision = 0;
  function resetOrders() {
    closeList();
    state.orders = { items: [], page: 1, pageSize: 10, total: 0, pageCount: 1 };
    state.loadedOrders = false;
    state.ordersError = "";
    state.orderFilter = { status: "all", period: "3m" };
  }
  function closeList() {
    ordersRevision += 1;
    state.ordersLoading = false;
    if (!listModal.open) return;
    listModal.close();
    listModal.innerHTML = "";
    listView = "";
    const fallback = root.querySelector('[data-sub-action="' + (listTrigger?.dataset.subAction || "open-plans") + '"]');
    (listTrigger?.isConnected ? listTrigger : fallback)?.focus();
  }
  function renderList(prepare = false) {
    if (!listModal.open && !prepare) return;
    const plans = listView === "plans";
    const focused = listModal.contains(document.activeElement) ? document.activeElement : null;
    const focusLabel = focused?.getAttribute("aria-label");
    listModal.className = plans ? "account-list-modal account-plans-modal" : "account-list-modal account-orders-modal";
    listModal.setAttribute("aria-label", plans ? "订阅套餐" : "订单记录");
    if (!listModal.querySelector(".account-list-body")) {
      listModal.innerHTML = '<header class="modal-head"><h2></h2>'
        + '<button class="close-button am-modal-dismiss" type="button" data-sub-action="close-list" aria-label="关闭列表"><svg class="am-modal-close-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true" focusable="false"><path d="M6 6l12 12M18 6 6 18"/></svg></button></header><div class="account-list-body"></div>';
    }
    listModal.querySelector(".modal-head h2").textContent = plans ? "订阅套餐" : "订单记录";
    const body = listModal.querySelector(".account-list-body");
    body.className = 'account-list-body' + (plans ? ' plans-body' : '');
    body.innerHTML = plans ? plansHTML() : ordersHTML();
    enhanceFilters(listModal);
    if (focused && !modal.open) {
      const replacement = Array.from(listModal.querySelectorAll("button")).find(button =>
        focusLabel ? button.getAttribute("aria-label") === focusLabel : button.textContent === focused.textContent);
      (replacement || listModal.querySelector("button"))?.focus();
    }
  }
  function openList(view) {
    if (!state.loggedIn) { loginModal(); return; }
    listTrigger = document.activeElement;
    listView = view;
    if (view === "orders") { state.ordersLoading = true; state.ordersError = ""; }
    renderList(true);
    if (!listModal.open) listModal.showModal();
    listModal.querySelector('[data-sub-action="close-list"]')?.focus();
    if (view === "orders") loadOrders(false);
    else refresh(true);
  }
  listModal.addEventListener("cancel", event => {
    event.preventDefault();
    if (!modal.open) closeList();
  });

  // ------------------------------------------------------------------ 弹窗

  let childTrigger = null;
  function openModal(title, body, customContact = false) {
    if (!modal) return;
    stopPayment();
    modal.classList.toggle("custom-service-modal", customContact);
    modal.classList.toggle("redemption-modal", ["兑换码支付", "确认兑换"].includes(title));
    modal.setAttribute("aria-label", title);
    if (!modal.open) {
      childTrigger = document.activeElement;
      modal.showModal();
    }
    modal.innerHTML = customContact ? body : '<header class="modal-head"><h2>' + esc(title) + "</h2>"
      + '<button class="close-button am-modal-dismiss" type="button" data-sub-action="close" aria-label="关闭弹窗"><svg class="am-modal-close-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true" focusable="false"><path d="M6 6l12 12M18 6 6 18"/></svg></button></header>' + body;
    const focus = modal.querySelector("input:not([type=checkbox]),button");
    if (focus) focus.focus();
  }

  function closeModal() {
    if (!modal || !modal.open || redemptionBusy) return;
    if (redemption && !redemption.key) redemption = null;
    stopPayment();
    modal.close();
    modal.innerHTML = "";
    if (listModal.open) {
      const replacement = Array.from(listModal.querySelectorAll("button")).find(button =>
        ["subBuy", "subOrder", "subAction"].some(key => childTrigger?.dataset[key] && button.dataset[key] === childTrigger.dataset[key]));
      (replacement || listModal.querySelector("button"))?.focus();
    }
  }

  function loginModal() {
    if (redemptionBusy) return;
    redemption = null;
    const demo = state.mode === "mock";
    openModal("登录新媒体运营工作台",
      '<p class="modal-sub">使用手机号验证码登录，首次登录自动注册。</p>'
      + (demo ? '<p class="demo-label">当前为模拟环境：短信不真实发送，验证码固定 123456。</p>' : "")
      + '<label class="field"><span>手机号</span><input class="am-input" id="subPhone" inputmode="numeric" maxlength="11"'
      + ' autocomplete="tel" placeholder="请输入 11 位手机号" aria-label="手机号"></label>'
      + '<label class="field"><span>验证码</span><div class="code-field">'
      + '<input class="am-input" id="subCode" inputmode="numeric" maxlength="6" autocomplete="off" placeholder="6 位验证码" aria-label="验证码">'
      + '<button id="subSendCode" type="button" data-sub-action="send-code">获取验证码</button></div></label>'
      + '<label class="checkline"><input id="subAgree" type="checkbox">'
      + '<span>我已阅读并同意<button type="button" data-legal-document="terms" aria-haspopup="dialog">《用户协议》</button>与<button type="button" data-legal-document="privacy" aria-haspopup="dialog">《隐私政策》</button></span></label>'
      + '<button id="subLogin" class="am-primary-action full" type="button" data-sub-action="login-submit" disabled>登录 / 注册</button>');
  }

  // 支付方式图标：品牌色实心路径，便于一眼分辨渠道。
  const PAY_METHOD_ICON = {
    "兑换码支付": { color: "#1d1d1f", path: "M4 4a2 2 0 0 0-2 2v3a3 3 0 0 1 0 6v3a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-3a3 3 0 0 1 0-6V6a2 2 0 0 0-2-2H4zm10 3h2v2h-2V7zm0 4h2v2h-2v-2zm0 4h2v2h-2v-2z" },
    "微信支付": { color: "#07C160", path: "M8.691 2.188C3.891 2.188 0 5.476 0 9.53c0 2.212 1.17 4.203 3.002 5.55a.59.59 0 0 1 .213.665l-.39 1.48c-.019.07-.048.141-.048.213 0 .163.13.295.29.295a.326.326 0 0 0 .167-.054l1.903-1.114a.864.864 0 0 1 .717-.098 10.16 10.16 0 0 0 2.837.403c.276 0 .543-.027.811-.05-.857-2.578.157-4.972 1.932-6.446 1.703-1.415 3.882-1.98 5.853-1.838-.576-3.583-4.196-6.348-8.596-6.348zM5.785 5.991c.642 0 1.162.529 1.162 1.18a1.17 1.17 0 0 1-1.162 1.178A1.17 1.17 0 0 1 4.623 7.17c0-.651.52-1.18 1.162-1.18zm5.813 0c.642 0 1.162.529 1.162 1.18a1.17 1.17 0 0 1-1.162 1.178 1.17 1.17 0 0 1-1.162-1.178c0-.651.52-1.18 1.162-1.18zm5.34 2.867c-1.797-.052-3.746.512-5.28 1.786-1.72 1.428-2.687 3.72-1.78 6.22.942 2.453 3.666 4.229 6.884 4.229.826 0 1.622-.12 2.361-.336a.722.722 0 0 1 .598.082l1.584.926a.272.272 0 0 0 .14.047c.134 0 .24-.111.24-.247 0-.06-.023-.12-.038-.177l-.327-1.233a.582.582 0 0 1-.023-.156.49.49 0 0 1 .201-.398C23.024 18.48 24 16.82 24 14.98c0-3.21-2.931-5.837-6.656-6.088V8.89c-.135-.01-.27-.027-.407-.03zm-2.53 3.274c.535 0 .969.44.969.982a.976.976 0 0 1-.969.983.976.976 0 0 1-.969-.983c0-.542.434-.982.97-.982zm4.844 0c.535 0 .969.44.969.982a.976.976 0 0 1-.969.983.976.976 0 0 1-.969-.983c0-.542.434-.982.969-.982z" },
    "支付宝": { color: "#1677FF", path: "M19.695 15.07c3.426 1.158 4.203 1.22 4.203 1.22V3.846c0-2.124-1.705-3.845-3.81-3.845H3.914C1.808.001.102 1.722.102 3.846v16.31c0 2.123 1.706 3.845 3.813 3.845h16.173c2.105 0 3.81-1.722 3.81-3.845v-.157s-6.19-2.602-9.315-4.119c-2.096 2.602-4.8 4.181-7.607 4.181-4.75 0-6.361-4.19-4.112-6.949.49-.602 1.324-1.175 2.617-1.497 2.025-.502 5.247.313 8.266 1.317a16.796 16.796 0 0 0 1.341-3.302H5.781v-.952h4.799V6.975H4.77v-.953h5.81V3.591s0-.409.411-.409h2.347v2.84h5.744v.951h-5.744v1.704h4.69a19.453 19.453 0 0 1-1.986 5.06c1.424.52 2.702 1.011 3.654 1.333m-13.81-2.032c-.596.06-1.71.325-2.321.869-1.83 1.608-.735 4.55 2.968 4.55 2.151 0 4.301-1.388 5.99-3.61-2.403-1.182-4.438-2.028-6.637-1.809" },
  };

  function payMethodIcon(method) {
    const icon = PAY_METHOD_ICON[method];
    if (!icon) return "";
    return '<svg class="pay-method-icon" viewBox="0 0 24 24" width="18" height="18" fill="'
      + icon.color + '" aria-hidden="true" focusable="false"><path d="' + icon.path + '"/></svg>';
  }

  function purchaseModal(planId) {
    const pendingPayment = paymentAttempt || readPayment();
    if (pendingPayment) { resumePayment(pendingPayment); return; }
    if (redemption?.key) { redemptionConfirm(); return; }
    const plan = state.plans.find((item) => item.planId === planId);
    if (!plan) { toast("套餐信息已更新，请刷新后重试。", "error"); return; }
    const price = trimZeros(plan.priceText);
    // 套餐摘要卡 → 周期与积分有效期提示 → 勾选 → 支付方式 → 实付栏。
    openModal("确认购买",
      '<div class="buy-summary"><h3>' + esc(plan.name) + "</h3>"
      + '<div class="price"><span class="currency">¥</span><b>' + esc(price) + "</b><span>/ 月</span></div>"
      + "<p>本周期含 " + esc(numberText(plan.points)) + " 积分</p></div>"
      + '<p class="modal-sub" style="margin-bottom:0">支付成功后立即开启新周期。</p>'
      + noticeHTML(POINTS_VALIDITY_NOTICE, "冻结的 " + frozenText() + " 积分仍用于原任务结算。", true)
      + '<label class="checkline"><input id="subPayAgree" type="checkbox">'
      + "<span>我已确认套餐权益，并了解积分按各自有效期使用的规则。</span></label>"
      + '<div class="payment-methods">'
      + ["微信支付", "兑换码支付"].map((method, index) => "<label>" + payMethodIcon(method)
        + '<input name="subMethod" type="radio" value="' + method + '"' + (index === 0 ? " checked" : "") + ">"
        + method + "</label>").join("")
      + "</div>"
      + '<div class="pay-total"><span>实付 <b>¥' + esc(price) + "</b></span>"
      + '<button id="subPaySubmit" class="am-primary-action" type="button" data-sub-action="pay-submit"'
      + ' data-sub-plan="' + esc(plan.planId) + '" disabled>确认并支付</button></div>'
      + (state.mode === "mock" ? '<p class="demo-label">演示流程，不会发起真实付款</p>' : ""));
  }

  // Sensitive redemption data lives only in this page's memory; never storage/URL.
  let redemption = null;
  let redemptionBusy = false;
  let redemptionRetryAt = 0;
  window.addEventListener("beforeunload", (event) => {
    if (!redemption?.key) return;
    event.preventDefault();
    event.returnValue = "";
  });

  function redemptionInput(planId) {
    if (redemption && redemption.key) { redemptionConfirm(); return; }
    redemption = { planCode: planId, code: "" };
    openModal("兑换码支付",
      '<p class="modal-sub">固定套餐，一码一次；兑换失败不消耗兑换码。</p>'
      + '<label class="redeem-label" for="subRedeemCode">兑换码</label>'
      + '<input id="subRedeemCode" class="am-input redeem-input" type="password" autocomplete="off" spellcheck="false" maxlength="256" placeholder="请输入所选套餐的兑换码">'
      + '<p id="subRedeemError" class="modal-sub" role="status"></p>'
      + '<div class="modal-foot"><button type="button" class="am-secondary-action" data-sub-action="redeem-back">返回支付方式</button>'
      + '<button id="subRedeemPreview" type="button" class="am-primary-action" data-sub-action="redeem-preview">预览套餐权益</button></div>');
  }

  function redemptionMessage(message) {
    const host = modal.querySelector("#subRedeemError");
    if (host) host.textContent = message;
  }

  async function previewRedemption() {
    if (redemptionBusy || !redemption) return;
    if (Date.now() < redemptionRetryAt) {
      redemptionMessage('请等待 ' + Math.ceil((redemptionRetryAt - Date.now()) / 1000) + ' 秒后重试。'); return;
    }
    const input = modal.querySelector("#subRedeemCode");
    if (input) redemption.code = input.value;
    if (!redemption.code.trim()) { redemptionMessage("请输入兑换码。"); return; }
    redemptionBusy = true;
    const button = modal.querySelector("#subRedeemPreview");
    if (button) button.disabled = true;
    try {
      const preview = await api("/api/subscription/redemptions/preview", {
        body: { code: redemption.code, planCode: redemption.planCode }, cache: "no-store"
      });
      if (!preview.plan || !Number.isInteger(preview.plan.version)) throw {message: "套餐预览不完整，请稍后重试。"};
      redemption.preview = preview;
      redemption.key = null;
      redemptionRetryAt = 0;
      redemptionConfirm();
    } catch (error) {
      redemptionMessage(error.message);
      if (error.code === "rate_limited") redemptionRetryAt = Date.now() + Math.max(1, Number(error.details?.retryAfterSeconds || 60)) * 1000;
      if (["unauthorized", "session_revoked"].includes(error.code)) {
        modal.querySelector('#subRedeemError').insertAdjacentHTML('afterend', '<button type="button" class="am-secondary-action" data-sub-action="login">重新登录</button>');
      }
    } finally {
      redemptionBusy = false;
      if (button) button.disabled = false;
    }
  }

  function redemptionConfirm() {
    const plan = redemption.preview.plan;
    const retry = Boolean(redemption.key);
    openModal("确认兑换",
      '<div class="buy-summary"><h3>' + esc(plan.name) + '</h3><p>本周期含 '
      + esc(numberText(plan.points)) + ' 积分 · ' + esc(plan.periodLabel || '自然月') + '</p>'
      + '<p>套餐价值 ¥' + esc((Number(plan.amountFen || 0) / 100).toFixed(2)) + ' · 现金实付 ¥0.00</p></div>'
      + '<ul class="redeem-benefits">' + (plan.benefits || FALLBACK_ENTITLEMENTS).map(x => '<li>' + esc(x) + '</li>').join('') + '</ul>'
      + noticeHTML(redemption.preview.notice?.message || POINTS_VALIDITY_NOTICE,
        '兑换后立即开启新周期，原积分有效期不变；冻结积分继续结算原任务。', true)
      + '<label class="checkline"><input id="subRedeemAgree" type="checkbox"' + (retry ? ' checked' : '') + '><span>我已确认最新套餐权益，并了解积分按各自有效期使用的规则。</span></label>'
      + '<p id="subRedeemError" class="modal-sub" role="status">' + (retry ? '上次兑换结果尚待确认，请使用原请求重试。' : '') + '</p>'
      + '<div id="subRedeemConflict"></div><div class="modal-foot">'
      + (!retry ? '<button type="button" class="am-secondary-action" data-sub-action="redeem-edit">修改兑换码</button>' : '')
      + '<button id="subRedeemSubmit" type="button" class="am-primary-action" data-sub-action="redeem-submit"' + (retry ? '' : ' disabled') + '>' + (retry ? '使用原请求重试' : '确认兑换') + '</button></div>');
  }

  async function submitRedemption() {
    if (redemptionBusy || !redemption || !modal.querySelector("#subRedeemAgree")?.checked) return;
    if (Date.now() < redemptionRetryAt) {
      redemptionMessage('请等待 ' + Math.ceil((redemptionRetryAt - Date.now()) / 1000) + ' 秒后重试。'); return;
    }
    redemptionBusy = true;
    const button = modal.querySelector("#subRedeemSubmit");
    button.disabled = true;
    button.textContent = "正在确认兑换…";
    if (!redemption.key) {
      redemption.key = crypto.randomUUID();
      redemption.body = {code: redemption.code, planCode: redemption.planCode, planVersion: redemption.preview.plan.version};
    }
    const attempt = redemption;
    try {
      const result = await api("/api/subscription/redemptions", {
        body: redemption.body, headers: {"Idempotency-Key": redemption.key}, cache: "no-store"
      });
      if (redemption !== attempt) return;
      redemption = null;
      resetLedger();
      state.orders.page = 1;
      state.orderFilter = {status: "all", period: "3m"};
      if (refreshInFlight) await refreshInFlight;
      const refreshed = await refresh(true);
      await loadOrders();
      renderPage();
      paymentSuccessModal(result.order);
      if (!refreshed || !state.loadedOrders) toast("兑换已成功，账户数据暂未刷新，请稍后刷新查看。", "error");
    } catch (error) {
      if (redemption !== attempt) return;
      redemptionMessage(error.message);
      if (error.code === "plan_changed") {
        redemption.key = null;
        redemption.body = null;
        redemptionBusy = false;
        await previewRedemption(); // Always clears agreement and generates a new key only after confirmation.
        if (!redemption.key && modal.querySelector('#subRedeemSubmit') === button) {
          button.disabled = true;
          button.textContent = '请重新预览';
          button.dataset.subAction = 'redeem-preview';
          button.disabled = false;
        }
        return;
      }
      if (error.code === "unfinished_order" && error.details?.orderId) {
        modal.querySelector('#subRedeemConflict').innerHTML = '<button class="am-secondary-action" type="button" data-sub-order="'
          + esc(error.details.orderId) + '">查看并处理未完成订单</button><p class="modal-sub">处理后回到套餐购买，使用原请求重试。</p>';
      }
      if (error.code === "rate_limited") redemptionRetryAt = Date.now() + Math.max(1, Number(error.details?.retryAfterSeconds || 60)) * 1000;
      if (["unauthorized", "session_revoked"].includes(error.code)) {
        modal.querySelector('#subRedeemConflict').innerHTML = '<button type="button" class="am-secondary-action" data-sub-action="login">重新登录</button>';
      }
      const terminal = ["redemption_invalid", "redemption_used", "redemption_expired", "redemption_revoked", "redemption_plan_mismatch", "plan_unavailable", "redemption_unavailable", "idempotency_conflict", "validation_error", "idempotency_key_required"];
      if (terminal.includes(error.code)) {
        redemption.key = null;
        button.dataset.subAction = 'redeem-edit';
        button.textContent = '重新输入并预览';
      } else {
        button.textContent = "使用原请求重试";
      }
      button.disabled = false;
    } finally { redemptionBusy = false; }
  }

  function paymentSuccessModal(order) {
    const subscription = state.subscription || {};
    const period = subscription.periodStart && subscription.currentPeriodEnd
      ? formatDateTime(subscription.periodStart, true) + " — " + formatDateTime(subscription.currentPeriodEnd, true)
      : "";
    openModal(order.payChannel === "redeem_code" ? "兑换成功" : "支付成功",
      '<div class="center payment-success"><div class="success-icon">✓</div>'
      + '<p class="payment-success-amount"><span>实付</span> <strong>¥' + esc(order.priceText || "0.00") + '</strong></p>'
      + '<p class="payment-success-benefit">' + esc(order.planName || "套餐") + "已生效 · 已发放 " + esc(numberText(order.points)) + " 积分</p>"
      + (period ? '<p class="payment-success-period">新周期：' + esc(period) + "</p>" : "")
      + '<p class="payment-success-note">原任务冻结的 ' + esc(frozenText()) + " 积分仍保留结算。</p>"
      + '<button class="am-primary-action full" type="button" data-sub-action="close">返回工作台</button>'
      + (state.mode === "mock" ? '<span class="demo-label">以上为演示结果，未产生真实支付</span>' : "")
      + "</div>");
  }

  function orderModal(order) {
    if (state.mode === 'live' && ['created','paid'].includes(order.status)) {
      const attempt = paymentAttempt || readPayment() || {owner: state.paymentOwner,
        key: 'wb-order-' + crypto.randomUUID(), planId: order.planId || '', failures: 0};
      if (attempt.orderId && attempt.orderId !== order.orderId) stopPayment();
      attempt.orderId = order.orderId;
      attempt.order = order;
      paymentAttempt = attempt;
      savePayment();
      resumePayment(attempt);
      return;
    }
    const pending = ["pending", "created"].includes(order.status);
    const cells = [
      ["套餐", order.planName || "—"],
      [pending ? "应付金额" : "实付金额", "¥ " + (order.priceText || "0.00")],
      [pending ? "支付后发放" : "发放积分", numberText(order.points) + " 积分"],
      ["订单状态", ORDER_STATUS_TEXT[order.status] || order.status || "—"],
      ["下单时间", formatDateTime(order.createdAt, true)],
      ["支付时间", order.paidAt ? formatDateTime(order.paidAt, true) : "—"],
    ];
    if (!pending && order.payChannel) {
      cells.push(["支付方式", PAY_CHANNEL_TEXT[order.payChannel] || order.payChannel]);
    }
    openModal(pending ? "待支付订单" : "订单详情",
      '<section class="order-modal-detail"><p class="modal-sub">订单号 ' + esc(order.orderId) + "</p>"
      + '<div class="detail-grid">' + cells.map((cell) => "<div><span>" + esc(cell[0]) + "</span><b>"
        + esc(cell[1]) + "</b></div>").join("") + "</div></section>"
      + (pending ? '<p class="modal-sub">请按平台订单完成付款，或手动关闭未支付订单后再兑换。</p>' : "")
      + '<div class="modal-foot"><button class="am-secondary-action" type="button" data-sub-order="' + esc(order.orderId) + '">查询订单状态</button>'
      + (pending && state.mode === "live" ? '<button class="am-secondary-action" type="button" data-sub-action="order-close" data-order-id="' + esc(order.orderId) + '">关闭未支付订单</button>' : '')
      + (redemption?.key ? '<button class="am-primary-action" type="button" data-sub-action="redeem-resume">返回兑换</button>' : '') + '</div>');
  }

  function insufficientModal(error) {
    const details = error.details || {};
    const required = details.requiredPoints ? numberText(details.requiredPoints) : "";
    const available = details.availablePoints ? numberText(details.availablePoints) : balanceText();
    openModal("积分不足",
      '<p class="modal-sub">' + (required ? "本次需要 " + esc(required) + " 积分，" : "")
      + "当前可用 " + esc(available) + " 积分。</p>"
      + '<p class="modal-sub">可购买套餐开启新周期。</p>'
      + noticeHTML(POINTS_VALIDITY_NOTICE, "", true)
      + '<div class="modal-foot"><button class="am-secondary-action" type="button" data-sub-action="close">暂不购买</button>'
      + '<button class="am-primary-action" type="button" data-sub-action="goto-account">查看套餐</button></div>');
  }

  // ------------------------------------------------------------------ 交互

  async function sendCode() {
    const phoneInput = modal && modal.querySelector("#subPhone");
    const button = modal && modal.querySelector("#subSendCode");
    if (!phoneInput || !button) return;
    try {
      const result = await api("/api/subscription/sms-code", { body: { phone: phoneInput.value.trim() } });
      let seconds = Number(result.retryAfterSeconds || 60);
      button.disabled = true;
      button.textContent = seconds + " 秒后重试";
      window.clearInterval(state.smsTimer);
      state.smsTimer = window.setInterval(() => {
        seconds -= 1;
        if (!button.isConnected) { window.clearInterval(state.smsTimer); return; }
        button.textContent = seconds > 0 ? seconds + " 秒后重试" : "获取验证码";
        if (seconds <= 0) { window.clearInterval(state.smsTimer); button.disabled = false; }
      }, 1000);
      toast(result.demoCode ? "模拟短信已发送，验证码为 " + result.demoCode + "。" : "验证码已发送。", "success");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  /* 手机号、验证码与同意勾选共同决定提交按钮是否可用。 */
  function syncLoginSubmit() {
    if (!modal || !modal.open) return;
    const phone = modal.querySelector("#subPhone");
    const code = modal.querySelector("#subCode");
    const agree = modal.querySelector("#subAgree");
    const submit = modal.querySelector("#subLogin");
    if (!submit || !phone || !code || !agree) return;
    submit.disabled = !(/^1\d{10}$/.test(phone.value.trim()) && code.value.trim().length === 6 && agree.checked);
  }

  async function submitLogin() {
    const phoneInput = modal && modal.querySelector("#subPhone");
    const codeInput = modal && modal.querySelector("#subCode");
    if (!phoneInput || !codeInput) return;
    const button = modal.querySelector("#subLogin");
    if (button) button.disabled = true;
    beginAuthMutation(true);
    const generation = authGeneration;
    try {
      const result = await api("/api/subscription/login", { body: { phone: phoneInput.value.trim(), code: codeInput.value.trim() } });
      if (generation !== authGeneration) return;
      authMutation = null;
      window.radarModule?.onSessionChange?.();
      identityRevision += 1;
      refreshInFlight = null;
      refreshSucceededAt = 0;
      resetLedger();
      closeModal();
      await refresh(true);
      toast(result.registered ? "注册成功。" : "已登录。", "success");
    } catch (error) {
      if (generation !== authGeneration) return;
      if (button) button.disabled = false;
      toast(error.message, "error");
    } finally {
      if (authMutation === generation) authMutation = null;
    }
  }

  // Only non-secret recovery identifiers are persisted, partitioned by platform account.
  let paymentAttempt = null;
  let paymentTimer = 0;
  let paymentExpiryTimer = 0;
  let paymentVisible = false;
  let paymentView = 0;
  let restoredPaymentOwner = '';
  function stopPayment() {
    clearTimeout(paymentTimer);
    clearTimeout(paymentExpiryTimer);
    paymentVisible = false;
    paymentView += 1;
  }
  function paymentStorageKey() { return 'nativePurchase.v1.' + state.paymentOwner; }
  function savePayment(required = false) {
    if (!paymentAttempt || paymentAttempt.owner !== state.paymentOwner) return;
    const {key, planId, orderId, closing} = paymentAttempt;
    // If persistence is unavailable, never create an order that cannot be recovered.
    try { localStorage.setItem(paymentStorageKey(), JSON.stringify({key, planId, orderId, closing})); }
    catch (error) { if (required) throw error; }
  }
  function readPayment() {
    if (!state.paymentOwner) return null;
    try {
      const saved = JSON.parse(localStorage.getItem(paymentStorageKey()) || 'null');
      if (saved && typeof saved.key === 'string' && typeof saved.planId === 'string')
        return {...saved, owner: state.paymentOwner, failures: 0, busy: false};
    } catch (_) { /* No persisted attempt. */ }
    return null;
  }
  function paymentCurrent(attempt) {
    return paymentAttempt === attempt && attempt.owner === state.paymentOwner && state.loggedIn;
  }
  function paymentHeaders(attempt) {
    return {'X-Payment-Owner': attempt.owner, 'Idempotency-Key': attempt.key};
  }
  function schedulePayment(attempt, delay = 5000) {
    clearTimeout(paymentTimer);
    if (paymentCurrent(attempt) && paymentVisible)
      paymentTimer = setTimeout(() => runPayment(attempt), delay);
  }
  function renderPayment(message = '') {
    const attempt = paymentAttempt;
    if (!attempt) return;
    const order = attempt.order || {};
    const status = order.status || 'created';
    const expiry = Date.parse(order.payment?.expiresAt || order.expiresAt || '');
    const expired = Number.isFinite(expiry) && Date.now() >= expiry;
    const canScan = status === 'created' && !attempt.closing && Number.isFinite(expiry) && !expired &&
      order.payment?.status === 'ready' && !order.payment.mock && order.payment.codeUrl && order.qrImage;
    const title = status === 'paid' ? '已付款，正在开通' : status === 'closed' ? '订单已关闭'
      : status === 'failed' ? '支付失败' : '微信扫码支付';
    const description = status === 'paid' ? '收款已确认，正在发放套餐和积分，请勿重复付款。'
      : status === 'closed' ? '服务端已确认关闭，可重新选择套餐购买。'
      : status === 'failed' ? '服务端已确认失败，可重新选择套餐购买。'
      : attempt.closing ? '正在确认取消结果，请勿付款。将继续查询原订单。'
      : expired ? '二维码已过期，正在确认原订单最终状态，请勿重复购买。'
      : canScan ? '请使用微信扫一扫。付款后将自动确认开通结果。'
      : order.payment?.mock ? '支付服务尚处于模拟模式，无法进行真实扫码付款。'
      : '正在准备二维码或等待渠道确认，请稍候。';
    openModal(title, '<div class="center native-payment" role="status">'
      + '<p class="modal-sub">订单号 ' + esc(order.orderId || '正在获取') + '</p>'
      + (order.orderId ? '<p class="payment-success-amount"><strong>¥' + esc(order.priceText) + '</strong></p>' : '')
      + (canScan ? '<img class="native-payment-qr" alt="微信支付二维码" src="' + esc(order.qrImage) + '">'
        : '<div class="native-payment-placeholder">' + (['closed','failed'].includes(status) ? '—' : '等待确认…') + '</div>')
      + '<p>' + description + '</p>'
      + (canScan && Number.isFinite(expiry) ? '<p class="modal-sub">有效期至 ' + esc(formatDateTime(order.payment?.expiresAt || order.expiresAt, true)) + '</p>' : '')
      + '<p class="modal-sub native-payment-message">' + esc(message) + '</p></div>'
      + '<div class="modal-foot"><button type="button" class="am-secondary-action" data-sub-action="close">关闭弹窗</button>'
      + (!['closed','failed'].includes(status) ? '<button type="button" class="am-secondary-action" data-sub-action="payment-retry">查询 / 重试原订单</button>' : '')
      + (order.orderId && status === 'created' ? '<button type="button" class="am-secondary-action" data-sub-action="payment-cancel">取消订单</button>' : '') + '</div>');
    paymentVisible = true;
    const qr = modal.querySelector('.native-payment-qr');
    if (qr) qr.addEventListener('error', () => {
      if (paymentCurrent(attempt) && qr.isConnected)
        modal.querySelector('.native-payment-message').textContent = '二维码加载失败，请重试原订单。';
    });
    if (canScan && Number.isFinite(expiry)) paymentExpiryTimer = setTimeout(() => {
      if (paymentCurrent(attempt) && paymentVisible) { renderPayment(); schedulePayment(attempt); }
    }, Math.max(1, expiry - Date.now()));
  }
  async function acceptPayment(attempt, order, view) {
    if (!paymentCurrent(attempt)) return;
    attempt.order = order;
    attempt.orderId = order.orderId;
    attempt.failures = 0;
    savePayment();
    const visible = paymentVisible && view === paymentView;
    if (['granted', 'closed', 'failed'].includes(order.status)) {
      try { localStorage.removeItem(paymentStorageKey()); } catch (_) { /* Retry will recover the terminal server order. */ }
      if (visible) renderPayment();
      stopPayment();
      paymentAttempt = null;
      const completionView = paymentView;
      if (order.status === 'granted') {
        resetLedger();
        if (refreshInFlight) await refreshInFlight;
        if (attempt.owner !== state.paymentOwner) return;
        const refreshed = await refresh(true);
        if (attempt.owner !== state.paymentOwner) return;
        await loadOrders();
        if (attempt.owner !== state.paymentOwner) return;
        renderPage();
        if (visible && modal.open && paymentView === completionView) paymentSuccessModal(order);
        if (!refreshed) toast('购买已完成，账户数据暂未刷新，请稍后刷新查看。', 'error');
      }
      return;
    }
    if (visible) renderPayment();
  }
  async function runPayment(attempt, cancel = false) {
    if (!paymentCurrent(attempt) || !paymentVisible) return;
    if (attempt.busy) {
      if (cancel) { attempt.cancelQueued = true; attempt.closing = true; savePayment(); renderPayment('正在等待查询完成后取消…'); }
      schedulePayment(attempt); return;
    }
    clearTimeout(paymentTimer);
    attempt.busy = true;
    const view = paymentView;
    try {
      if (cancel) { attempt.closing = true; savePayment(); }
      const options = {body: {}, headers: paymentHeaders(attempt), cache: 'no-store'};
      const order = attempt.orderId
        ? await api('/api/subscription/orders/' + encodeURIComponent(attempt.orderId) + (cancel ? '/close' : '/query'), options)
        : await api('/api/subscription/purchase', {...options, body: {planId: attempt.planId, method: '微信支付'}});
      await acceptPayment(attempt, order, view);
    } catch (error) {
      if (!paymentCurrent(attempt)) return;
      if (error.code === 'unfinished_order' && error.details?.orderId) {
        attempt.orderId = error.details.orderId;
        savePayment();
      }
      attempt.failures = Math.min((attempt.failures || 0) + 1, 6);
      if (paymentVisible && view === paymentView)
        renderPayment('暂未确认结果：' + error.message + ' 将继续查询原订单，请勿重复付款。');
    } finally {
      attempt.busy = false;
      if (attempt.cancelQueued && paymentCurrent(attempt) && attempt.order?.status === 'created' && paymentVisible) {
        attempt.cancelQueued = false;
        runPayment(attempt, true);
        return;
      }
      schedulePayment(attempt, Math.min(60000, 5000 * 2 ** (attempt.failures || 0)));
    }
  }
  function resumePayment(attempt) {
    paymentAttempt = attempt;
    renderPayment();
    runPayment(attempt);
  }
  async function submitPayment(planId) {
    if (state.mode === 'mock') {
      const button = modal.querySelector('#subPaySubmit');
      if (!button || button.disabled) return;
      button.disabled = true;
      try {
        const order = await api('/api/subscription/purchase', {body: {planId, method: '微信支付'}});
        await refresh(true);
        paymentSuccessModal(order);
      } catch (error) { toast(error.message, 'error'); button.disabled = false; }
      return;
    }
    if (!state.paymentOwner) { toast('账户状态尚未就绪，请刷新后重试。', 'error'); return; }
    const prior = paymentAttempt || readPayment();
    if (prior) { resumePayment(prior); return; }
    paymentAttempt = {owner: state.paymentOwner, planId, key: 'wb-order-' + crypto.randomUUID(), failures: 0};
    try { savePayment(true); } catch (_) {
      paymentAttempt = null;
      toast('浏览器无法保存订单恢复信息，请允许本地存储后重试。', 'error'); return;
    }
    resumePayment(paymentAttempt);
  }

  async function logout() {
    if (redemptionBusy) return;
    beginAuthMutation(true);
    const generation = authGeneration;
    stopPayment();
    paymentAttempt = null;
    state.paymentOwner = "";
    restoredPaymentOwner = "";
    closeModal();
    redemption = null;
    identityRevision += 1;
    refreshInFlight = null;
    refreshSucceededAt = 0;
    resetLedger();
    resetOrders();
    window.radarModule?.clearSession?.();
    try {
      await api("/api/subscription/logout", { method: "POST", body: {} });
    } catch (error) {
      // 平台不可达也必须让用户退出去：本地会话已经清掉，界面照常回未登录状态。
      toast(error.message, "error");
    }
    if (generation !== authGeneration) return;
    authMutation = null;
    window.radarModule?.onSessionChange?.();
    closeAccountMenu();
    await refresh(true);
    toast("已退出登录，本地内容保留。", "info");
  }

  document.addEventListener("click", (event) => {

    const page = event.target.closest("[data-sub-page]");
    if (page && !page.disabled) {
      const target = Number(page.dataset.subPage);
      if (!page.closest("#accountListModal")) {
        if (target < 1 || target > state.ledger.pageCount) return;
        state.ledger.page = target;
        loadLedger().then(renderPage);
      } else {
        if (target < 1 || target > state.orders.pageCount) return;
        state.orders.page = target;
        loadOrders().then(renderPage);
      }
      return;
    }

    const buy = event.target.closest("[data-sub-buy]");
    if (buy) { purchaseModal(buy.dataset.subBuy); return; }

    const order = event.target.closest("[data-sub-order]");
    if (order) {
      const owner = state.paymentOwner;
      const revision = ordersRevision;
      api("/api/subscription/orders/" + encodeURIComponent(order.dataset.subOrder), {headers: {'X-Payment-Owner': owner}})
        .then(result => { if (owner === state.paymentOwner && revision === ordersRevision && listModal.open) orderModal(result); })
        .catch((error) => toast(error.message, "error"));
      return;
    }

    const ref = event.target.closest("[data-sub-ref]");
    if (ref && ref.dataset.subRef) {
      if (/^WB/.test(ref.dataset.subRef)) {
        api("/api/subscription/orders/" + encodeURIComponent(ref.dataset.subRef))
          .then(orderModal)
          .catch((error) => toast(error.message, "error"));
      } else {
        openModal("任务记录", '<p class="modal-sub">任务 ' + esc(ref.dataset.subRef)
          + '</p><p class="modal-sub">任务进度与结算由创作服务 API 平台维护，费用已记入积分明细。</p>');
      }
      return;
    }

    const action = event.target.closest("[data-sub-action]");
    if (!action) return;
    const name = action.dataset.subAction;
    if (name === "open-plans") { openList("plans"); return; }
    if (name === "open-orders") { openList("orders"); return; }
    if (name === "close-list") { closeList(); return; }
    if (name === "retry-orders") { loadOrders(); return; }
    if (name === "payment-retry") { if (paymentAttempt) runPayment(paymentAttempt); return; }
    if (name === "payment-cancel") {
      if (paymentAttempt) {
        paymentAttempt.closing = true;
        renderPayment('正在申请取消订单…');
        runPayment(paymentAttempt, true);
      }
      return;
    }
    if (name === "contact-custom") { customServiceModal(); return; }
    if (name === "refresh-ledger") { loadLedger(true); return; }
    if (name === "retry") { refresh(true); return; }
    if (name === "login") { closeAccountMenu(); loginModal(); return; }
    if (name === "logout") { logout(); return; }
    if (name === "close") { closeModal(); return; }
    if (name === "send-code") { sendCode(); return; }
    if (name === "login-submit") { submitLogin(); return; }
    if (name === "redeem-resume") { redemptionConfirm(); return; }
    if (name === "order-close") {
      action.disabled = true;
      api("/api/subscription/orders/" + encodeURIComponent(action.dataset.orderId) + "/close", {body: {}})
        .then(orderModal).catch(error => { toast(error.message, "error"); action.disabled = false; }); return;
    }
    if (name === "redeem-preview") { previewRedemption(); return; }
    if (name === "redeem-submit") { if (event.detail <= 1) submitRedemption(); return; }
    if (name === "redeem-edit") { const id = redemption.planCode; redemption = null; redemptionInput(id); return; }
    if (name === "redeem-back") { const id = redemption.planCode; redemption = null; purchaseModal(id); return; }
    if (name === "pay-submit") { submitPayment(action.dataset.subPlan); return; }
    if (name === "open-account") { closeModal(); closeList(); closeAccountMenu(); window.selectWorkspaceModule?.("account"); return; }
    if (name === "goto-account") { closeModal(); closeAccountMenu(); window.selectWorkspaceModule?.("account"); openList("plans"); return; }
  });

  document.addEventListener("input", (event) => {
    if (event.target.id === "subPhone" || event.target.id === "subCode") syncLoginSubmit();
  });

  document.addEventListener("change", (event) => {
    if (event.target.id === "subAgree") {
      syncLoginSubmit();
      return;
    }
    if (event.target.name === "subMethod" && event.target.value === "兑换码支付") {
      redemptionInput(modal.querySelector("#subPaySubmit").dataset.subPlan); return;
    }
    if (event.target.id === "subRedeemAgree") {
      const submit = modal.querySelector("#subRedeemSubmit");
      if (submit) submit.disabled = redemptionBusy || !event.target.checked;
      return;
    }
    if (event.target.id === "subPayAgree") {
      const submit = modal && modal.querySelector("#subPaySubmit");
      if (submit) submit.disabled = !event.target.checked;
      return;
    }
    if (event.target.id === "pointPeriod") { state.ledger.page = 1; state.ledgerFilter.period = event.target.value; loadLedger().then(renderPage); return; }
    if (event.target.id === "pointType") { state.ledger.page = 1; state.ledgerFilter.type = event.target.value; loadLedger().then(renderPage); return; }
    if (event.target.id === "orderStatus") { state.orders.page = 1; state.orderFilter.status = event.target.value; loadOrders().then(renderPage); return; }
    if (event.target.id === "orderPeriod") { state.orders.page = 1; state.orderFilter.period = event.target.value; loadOrders().then(renderPage); return; }
  });

  document.addEventListener("click", (event) => {
    if ((!root.contains(event.target) && !listModal.contains(event.target)) || event.target.closest(".record-filter")) return;
    closeFilterMenus();
  });

  document.addEventListener("keydown", event => {
    if (event.key !== "Tab") return;
    const activeDialog = modal?.open ? modal : listModal.open ? listModal : null;
    if (!activeDialog) return;
    const controls = Array.from(activeDialog.querySelectorAll('button, input, select, textarea, a[href], [tabindex]'))
      .filter(element => !element.disabled && element.tabIndex >= 0 && element.getClientRects().length);
    if (!controls.length) { event.preventDefault(); activeDialog.focus(); return; }
    const index = controls.indexOf(document.activeElement);
    if (index < 0 || (event.shiftKey ? index === 0 : index === controls.length - 1)) {
      event.preventDefault();
      controls[event.shiftKey ? controls.length - 1 : 0].focus();
    }
  });

  if (modal) modal.addEventListener("cancel", (event) => { event.preventDefault(); closeModal(); });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !modal || !modal.open) return;
    event.preventDefault();
    event.stopPropagation();
    closeModal();
  });

  root.addEventListener("workspace-module-change", () => closeFilterMenus());
  window.addEventListener("workspace-module-change", (event) => {
    if (event.detail && event.detail.module === "account") refresh(true);
  });

  /* 本地会话是否有效：只读本地存储，不占平台配额。 */
  async function hasLocalSession() {
    if (authMutation !== null) return false;
    const revision = identityRevision;
    try {
      const response = await fetch("/api/subscription/session",
        { headers: { Accept: "application/json" }, cache: "no-store" });
      // 状态都读不出来时不拦：这属于服务异常，交给后面的 401 兜底，
      // 不能因为一次读失败就把已登录的用户当成未登录。
      if (!response.ok) return true;
      const session = await response.json();
      if (revision !== identityRevision) return state.loggedIn;
      if (!session || !session.loggedIn) return false;
      const changed = !state.loggedIn || (session.phone && session.phone !== state.phone) ||
        (session.paymentOwner && session.paymentOwner !== state.paymentOwner);
      state.loggedIn = true;
      state.paymentOwner = session.paymentOwner || state.paymentOwner;
      state.phone = session.phone || state.phone;
      state.mode = session.mode || state.mode;
      if (changed) emitSessionChange();
      renderIdentity();
      return true;
    } catch (_) {
      return true;
    }
  }

  /* 触发平台能力前先问一句登录状态：未登录就直接弹出登录框，
     而不是先提示「已开始」再在后台静默失败。

     这里向本地会话确认一次，而不是只看 state.loggedIn——后者在页面刚打开、
     或上一次刷新失败时还是 false，会把已登录的用户错拦下来。 */
  async function requireLogin() {
    if (state.loggedIn || await hasLocalSession()) return true;
    closeAccountMenu();
    loginModal();
    return false;
  }

  /* 直接打开登录框：供「登录已失效，请重新登录」这类可点击提示调用，
     不先判断本地会话——本地会话还在、但平台已拒绝凭证时也要能重新登录。 */
  function openLogin() {
    closeAccountMenu();
    loginModal();
  }

  /* 平台已拒绝本地凭证、后台也清掉了会话：把身份区同步成未登录。
     否则左上角还挂着手机号，与「登录已失效，请重新登录」自相矛盾。 */
  function sessionInvalid() {
    beginAuthMutation();
    stopPayment();
    paymentAttempt = null;
    state.paymentOwner = "";
    restoredPaymentOwner = "";
    identityRevision += 1;
    refreshInFlight = null;
    refreshSucceededAt = 0;
    resetLedger();
    resetOrders();
    window.radarModule?.clearSession?.();
    state.loggedIn = false;
    state.phone = "";
    state.subscription = null;
    state.points = null;
    state.ledger = { items: [], page: 1, pageSize: 10, total: 0, pageCount: 1 };
    state.orders = { items: [], page: 1, pageSize: 10, total: 0, pageCount: 1 };
    renderIdentity();
    renderPage();
  }

  // 供雷达、监控等模块在启动平台任务前调用。
  async function openPlans() {
    if (!await requireLogin()) return;
    closeAccountMenu();
    openList("plans");
  }
  window.accountModule = { requireLogin, openLogin, sessionInvalid, openPlans, getSession, refreshBalanceAfterGrant, updateTrialGift };

  /* 工作台本身不需要登录；只有撞到要调用平台的付费能力时才提示登录。
     这里统一接住被拒的 401，直接弹出登录框，不必让每个模块各写一份。 */
  const nativeFetch = window.fetch.bind(window);
  let lastLoginPromptAt = 0;
  window.fetch = (input, init) => {
    const generation = authGeneration;
    const owner = state.paymentOwner;
    const requestOwner = new Headers(init?.headers || input?.headers || {}).get("X-Payment-Owner");
    return nativeFetch(input, init).then((response) => {
      const url = typeof input === "string" ? input : (input && input.url) || "";
      const isLoginCall = url.indexOf("/api/subscription/login") >= 0 || url.indexOf("/api/subscription/sms-code") >= 0;
      const stalePayment = generation !== authGeneration || owner !== state.paymentOwner ||
        (requestOwner && requestOwner !== state.paymentOwner);
      // 一串并发请求可能同时被拒，限个频，别弹出一叠登录框。
      if (response.status === 401 && !stalePayment && !isLoginCall && Date.now() - lastLoginPromptAt > 3000) {
        lastLoginPromptAt = Date.now();
        closeAccountMenu();
        loginModal();
      }
      return response;
    });
  };

  hasLocalSession();
  refresh();
})();
