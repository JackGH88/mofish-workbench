/* 拆解视频：粘贴分享链接 → 下载与转写 → 在独立结果页看视频文案、分析并加入选题。
   工作台导航只负责显隐；本文件负责数据、渲染与编辑。
   结果页沿用旧版「拆片」的面板、时间轴与字幕高亮视觉。 */
(() => {
  const root = document.getElementById("breakdownContent");
  if (!root) return;

  /* 拆解要调用创作服务平台转写，未登录时先弹登录框。
     登录态由账户模块统一判断（它会向本地会话确认，避免把已登录错判成未登录）；
     账户模块缺失时放行，交给后面的 401 兜底。 */
  async function requireWorkbenchLogin() {
    if (!window.accountModule || typeof window.accountModule.requireLogin !== "function") return true;
    return window.accountModule.requireLogin();
  }

  const CATEGORY_LABELS = { highlight: "重点", daily: "日常", series: "系列", test: "测试" };
  /* 作品标题常常是一整段发布文案。结果页标题栏只显示前 50 个字，
     多出来的部分用省略号收尾；侧栏记录与删除弹窗仍然用完整标题。 */
  const RESULT_TITLE_LIMIT = 40;
  const PHASE_PRESENTATIONS = {
    queued: { title: "排队中", hint: "正在等待开始。" },
    parsing: { title: "正在解析分享链接", hint: "平台正在解析链接并返回可下载的视频地址。" },
    downloading: { title: "正在下载视频", hint: "视频下载完成后，将自动提取音频并转写文案。" },
    extracting: { title: "正在提取音频", hint: "正在提取视频中的声音，为文案转写做准备。" },
    uploading: { title: "正在上传音频", hint: "正在上传音频，完成后将自动转写文案。" },
    transcribing: { title: "正在转写视频文案", hint: "创作服务正在把口播内容转成文字。" },
    fetching: { title: "正在获取转写结果", hint: "正在取回文案与时间码。" },
    rewriting: { title: "正在整理文案", hint: "正在整理转写结果。" },
    complete: { title: "转写完成", hint: "视频与文案已就绪，可以开始拆解。" },
    failed: { title: "拆解失败", hint: "请检查链接与本地配置后重新拆解。" },
  };
  /* 旧记录可能残留的过渡阶段名，渲染前统一归一化到上面的新阶段。 */
  const LEGACY_PHASE_ALIASES = { submitting: "parsing", preparing_audio: "extracting", uploading_audio: "uploading" };
  /* 拆分后的处理步骤：解析链接（按次计费）→ 本地下载与提取 → 直传核验与转写 → 内容分析。 */
  const PROGRESS_STEPS = ["解析链接", "下载视频", "提取音频", "上传与转写", "内容分析"];
  const PHASE_STEP = { queued: -1, parsing: 0, downloading: 1, extracting: 2, uploading: 3, transcribing: 3, fetching: 3, rewriting: 3, complete: 4, failed: -1 };
  const STAGE_STEP = { resolve: 0, parse: 0, download: 1, probe: 2, extract: 2, store: 3, transcribe: 3 };
  const STATUS_LABELS = { queued: "排队中", running: "进行中", reconciling: "待确认", succeeded: "成功", failed: "失败", cancelled: "已取消" };

  const dom = {
    newButton: document.getElementById("breakdownNewButton"),
    rewriteButton: document.getElementById("breakdownRewriteButton"),
    taskNewButton: document.getElementById("breakdownTaskNewButton"),
    list: document.getElementById("breakdownList"),
    listCount: document.getElementById("breakdownCount"),
    listEmpty: document.getElementById("breakdownEmpty"),
    form: document.getElementById("breakdownForm"),
    intro: document.getElementById("breakdownIntro"),
    progress: document.getElementById("breakdownProgress"),
    shareInput: document.getElementById("breakdownShareInput"),
    pasteButton: document.getElementById("breakdownPasteButton"),
    chooseMediaButton: document.getElementById("breakdownChooseMediaButton"),
    mediaInput: document.getElementById("breakdownMediaInput"),
    mediaState: document.getElementById("breakdownMediaState"),
    feeCap: document.getElementById("breakdownFeeCap"),
    clearButton: document.getElementById("breakdownClearButton"),
    submitButton: document.getElementById("breakdownSubmitButton"),
    formMessage: document.getElementById("breakdownFormMessage"),
    recordLoading: document.getElementById("breakdownRecordLoading"),
    taskState: document.getElementById("breakdownTaskState"),
    taskIndicator: document.getElementById("breakdownTaskIndicator"),
    taskCopy: document.getElementById("breakdownTaskCopy"),
    taskActions: document.getElementById("breakdownTaskActions"),
    taskTitle: document.getElementById("breakdownTaskTitle"),
    taskMessage: document.getElementById("breakdownTaskMessage"),
    stageSummary: document.getElementById("breakdownStageSummary"),
    retryButton: document.getElementById("breakdownRetryButton"),
    failedDelete: document.getElementById("breakdownFailedDelete"),
    taskDiagnostic: document.getElementById("breakdownTaskDiagnostic"),
    result: document.getElementById("breakdownResult"),
    resultTitle: document.getElementById("breakdownResultTitle"),
    resultMeta: document.getElementById("breakdownResultMeta"),
    resultFees: document.getElementById("breakdownResultFees"),
    workbench: document.getElementById("breakdownWorkbench"),
    timeline: document.getElementById("breakdownTimeline"),
    hint: document.getElementById("breakdownHint"),
    videoPanel: document.getElementById("breakdownVideoPanel"),
    contentPanel: document.getElementById("breakdownContentPanel"),
    panelTabsList: document.getElementById("breakdownPanelTabs"),
    panelTabs: [
      { id: "transcript", tab: document.getElementById("breakdownTranscriptTab") },
      { id: "analysis", tab: document.getElementById("breakdownAnalysisTab") },
    ],
    video: document.getElementById("breakdownVideo"),
    playbackToggle: document.getElementById("breakdownPlaybackToggle"),
    transcript: document.getElementById("breakdownTranscript"),
    transcriptEmpty: document.getElementById("breakdownTranscriptEmpty"),
    analysisBody: document.getElementById("breakdownAnalysisBody"),
    analysisState: document.getElementById("breakdownAnalysisState"),
    analysisEmpty: document.getElementById("breakdownAnalysisEmpty"),
    analyzeButton: document.getElementById("breakdownAnalyzeButton"),
    collectCopyButton: document.getElementById("breakdownCollectCopyButton"),
    addTopicButton: document.getElementById("breakdownAddTopicButton"),
    deleteButton: document.getElementById("breakdownDeleteButton"),
    actionsControl: document.getElementById("breakdownActionsControl"),
    actionsButton: document.getElementById("breakdownActionsButton"),
    actionsPanel: document.getElementById("breakdownActionsPanel"),
    track: document.getElementById("breakdownTrack"),
    trackClock: null,
    ticks: null,
    waveform: document.getElementById("breakdownWaveform"),
    playhead: document.getElementById("breakdownPlayhead"),
    playheadLabel: null,
    duration: null,
    topicModal: document.getElementById("breakdownTopicModal"),
    topicTitle: document.getElementById("breakdownTopicTitleInput"),
    topicWeek: document.getElementById("breakdownTopicWeekSelect"),
    topicCategory: document.getElementById("breakdownTopicCategorySelect"),
    topicFormat: document.getElementById("breakdownTopicFormatSelect"),
    topicOutline: document.getElementById("breakdownTopicOutlineInput"),
    topicDate: document.getElementById("breakdownTopicDateInput"),
    topicMessage: document.getElementById("breakdownTopicModalMessage"),
    topicCancel: document.getElementById("cancelBreakdownTopicButton"),
    topicConfirm: document.getElementById("confirmBreakdownTopicButton"),
    deleteModal: document.getElementById("breakdownDeleteModal"),
    deleteCopy: document.getElementById("breakdownDeleteModalDescription"),
    deleteCancel: document.getElementById("cancelBreakdownDeleteButton"),
    deleteConfirm: document.getElementById("confirmBreakdownDeleteButton"),
  };
  if (dom.track) {
    dom.trackClock = dom.track.querySelector(".clock");
    dom.ticks = dom.track.querySelector(".ticks");
    dom.playheadLabel = dom.playhead?.querySelector("span") || null;
  }
  if (dom.video?.parentElement) dom.duration = dom.video.parentElement.querySelector(".duration");

  const state = {
    accountId: "",
    items: [],
    activeId: "",
    record: null,
    task: null,
    segments: [],
    duration: 0,
    busy: false,
    analyzingId: "",
    pollTimer: null,
    pollFailures: 0,
    requestVersion: 0,
    recordRequestVersion: 0,
    pendingRecordId: "",
    feeRequestVersion: 0,
    pendingDeleteId: "",
    deleteArmedFor: "",
    deletingId: "",
    tab: "transcript",
    /* 本次转写的来源与费用上限：本地素材选中后覆盖链接，两者二选一。 */
    media: { id: "", name: "", durationSeconds: 0, uploading: false },
    feeCap: null,
    collectingCopyId: "",
  };

  /* Timeline/playback state kept outside `state` so the render helpers can read it
     without threading it through every call. The video column also caches the width
     it last wrote, so the resize observer cannot ping-pong on its own output. */
  let trackDragging = false;
  let trackSeekPending = false;
  let trackSeekTarget = null;
  let playbackFrame = null;
  let videoColumnWidth = 0;

  /* ------------------------------------------------------------ 工具 */

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function formatTime(seconds) {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const minutes = Math.floor(total / 60);
    return `${String(minutes).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
  }

  function isoDate(date) {
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${date.getFullYear()}-${month}-${day}`;
  }

  function weekStartOf(date) {
    const copy = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    copy.setDate(copy.getDate() - ((copy.getDay() + 6) % 7));
    return copy;
  }

  function shiftIsoWeek(weekStartIso, weeks) {
    const [year, month, day] = String(weekStartIso).split("-").map(Number);
    const date = new Date(year, (month || 1) - 1, day || 1);
    date.setDate(date.getDate() + weeks * 7);
    return isoDate(date);
  }

  function formatDate(iso) {
    const text = String(iso || "");
    return text ? text.slice(0, 10).replace(/-/g, "/") : "";
  }

  function responseMessage(error, fallback) {
    const detail = error?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (detail && typeof detail === "object" && typeof detail.message === "string") return detail.message;
    if (typeof error?.message === "string" && error.message.trim()) return error.message;
    return fallback;
  }

  function showToast(message, kind) {
    window.showToast?.(message, kind);
  }

  async function readJson(response) {
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw payload || { message: "请求失败" };
    return payload;
  }

  function isSameAccount(accountId) {
    return state.accountId === String(accountId || "");
  }

  /* ------------------------------------------------------------ 列表 */

  function recordStatusLabel(record) {
    const phase = String(record?.task?.phase || "");
    if (phase === "failed") return { label: "拆解失败", kind: "is-failed" };
    if (phase && phase !== "complete") return { label: "转写中", kind: "is-running" };
    if (record?.analysisStatus === "running" || record?.analysisStatus === "pending") return { label: "分析中", kind: "is-running" };
    if (record?.analysisStatus === "failed") return { label: "分析失败", kind: "is-failed" };
    if (record?.topicId) return { label: "已加入选题", kind: "is-topic" };
    if (record?.analysisStatus === "complete") return { label: "已分析", kind: "is-analysed" };
    return { label: "可拆解", kind: "is-ready" };
  }

  function buildRow(record) {
    const item = el("li", "breakdown-item");
    item.dataset.breakdownId = record.id;
    if (record.id === (state.pendingRecordId || state.activeId)) item.classList.add("is-active");

    const open = el("button", "breakdown-item-open");
    open.type = "button";
    open.addEventListener("click", () => openRecord(record.id));
    // Same shape as a 脚本 list row: status dot, title, then one meta line that
    // carries the date and the state instead of a separate pill.
    const status = recordStatusLabel(record);
    const indicator = el("i", "breakdown-item-dot");
    indicator.setAttribute("role", "img");
    indicator.setAttribute("aria-label", `拆解状态：${status.label}`);
    indicator.title = `拆解状态：${status.label}`;
    open.append(indicator);
    open.append(el("strong", "breakdown-item-title", String(record.title || "视频标题待获取")));
    open.append(el("span", "breakdown-item-meta", [formatDate(record.createdAt) || "刚刚", status.label].join(" · ")));

    // 删除从记录卡片迁到结果卡片右上角，整张卡片只剩「打开这条记录」一个动作。
    item.append(open);
    return item;
  }

  function renderList() {
    dom.list.replaceChildren(...state.items.map(buildRow));
    dom.listEmpty.hidden = state.items.length > 0;
    dom.listCount.textContent = `共 ${state.items.length} 条拆解记录`;
  }

  function upsertItem(record) {
    const index = state.items.findIndex((item) => item.id === record.id);
    if (index >= 0) state.items[index] = { ...state.items[index], ...record };
    else state.items = [record, ...state.items];
    renderList();
  }

  async function loadList() {
    if (!state.accountId) {
      state.items = [];
      renderList();
      return;
    }
    const accountId = state.accountId;
    const version = ++state.requestVersion;
    try {
      const payload = await readJson(await fetch(`/api/accounts/${encodeURIComponent(accountId)}/breakdowns`));
      if (!isSameAccount(accountId) || version !== state.requestVersion) return;
      state.items = Array.isArray(payload?.items) ? payload.items : [];
      renderList();
    } catch (error) {
      if (!isSameAccount(accountId) || version !== state.requestVersion) return;
      showToast(responseMessage(error, "读取拆解记录失败"), "error");
    }
  }

  /* -------------------------------------------------------- 结果渲染 */

  function renderVideo() {
    const videoFile = String(state.task?.videoFile || "").trim();
    dom.video.src = videoFile ? `/api/files/${videoFile.split("/").map(encodeURIComponent).join("/")}` : "";
    dom.video.hidden = !videoFile;
    dom.playbackToggle.hidden = true;
    const mediaEmpty = document.getElementById("breakdownMediaEmpty");
    if (mediaEmpty) mediaEmpty.hidden = Boolean(videoFile);
    dom.video.poster = String(state.task?.posterFile || "").trim()
      ? `/api/files/${String(state.task.posterFile).split("/").map(encodeURIComponent).join("/")}`
      : "";
    renderPlaybackControl();
  }

  function renderPlaybackControl() {
    const playing = !dom.video.paused && !dom.video.hidden;
    dom.playbackToggle.hidden = true;
    dom.playbackToggle.classList.toggle("is-playing", playing);
    dom.playbackToggle.setAttribute("aria-pressed", String(playing));
    dom.playbackToggle.setAttribute("aria-label", playing ? "暂停视频" : "播放视频");
  }

  function renderTranscript() {
    dom.transcript.replaceChildren();
    // 文案与分析共用一个内容区，显隐交给 renderTabs() 统一决定。
    for (const segment of state.segments) {
      const item = el("article", "caption");
      const time = el("time", null, `${formatTime(segment.start)} — ${formatTime(segment.end)}`);
      const caption = el("button", "split-caption", segment.text);
      caption.type = "button";
      caption.addEventListener("click", () => setActiveTime(segment.start, { seekVideo: true, scrollSegment: true }));
      item.append(time, caption);
      dom.transcript.append(item);
    }
  }

  function effectiveDuration() {
    const segmentEnd = state.segments.reduce((latest, segment) => Math.max(latest, Number(segment.end) || 0), 0);
    return Math.max(Number(state.duration) || 0, segmentEnd, Number(dom.video.duration) || 0);
  }

  function renderWaveform(peaks) {
    const amplitudes = Array.isArray(peaks)
      ? peaks.map((peak) => Math.max(8, Math.min(100, 8 + (Number(peak) || 0) * 92)))
      : [];
    dom.waveform.replaceChildren(...amplitudes.map((amplitude) => {
      const bar = el("span", "split-waveform-bar");
      bar.style.height = `${amplitude}%`;
      return bar;
    }));
  }

  function renderTicks(duration) {
    const tickCount = 7;
    dom.ticks.replaceChildren(...Array.from({ length: tickCount }, (_, index) => (
      el("span", null, formatTime(duration > 0 ? (duration * index) / (tickCount - 1) : 0))
    )));
  }

  function laneGeometry() {
    const trackRect = dom.track.getBoundingClientRect();
    const waveformRect = dom.waveform.getBoundingClientRect();
    const measured = Number(waveformRect.width);
    if (Number(trackRect.width) > 0 && Number.isFinite(measured) && measured > 0) {
      return { viewportStart: waveformRect.left, trackOffset: waveformRect.left - trackRect.left, width: measured };
    }
    const trackWidth = Math.max(0, Number(trackRect.width) || 0);
    return { viewportStart: (Number(trackRect.left) || 0) + 76, trackOffset: 76, width: Math.max(0, trackWidth - 81) };
  }

  function renderPlayhead(seconds, duration) {
    const ratio = duration > 0 ? Math.max(0, Math.min(1, seconds / duration)) : 0;
    const lane = laneGeometry();
    dom.playhead.style.left = `${Math.round((lane.trackOffset + lane.width * ratio) * 1000) / 1000}px`;
    const currentTime = formatTime(seconds);
    if (dom.trackClock) dom.trackClock.textContent = currentTime;
    if (dom.playheadLabel) dom.playheadLabel.textContent = currentTime;
    if (dom.duration) dom.duration.textContent = `${currentTime} / ${formatTime(duration)}`;
  }

  function renderActiveSegment(seconds, scrollSegment = false) {
    let activeIndex = state.segments.findIndex((segment) => seconds >= segment.start && seconds < segment.end);
    if (activeIndex < 0) {
      for (let index = state.segments.length - 1; index >= 0; index -= 1) {
        if (seconds >= state.segments[index].start) { activeIndex = index; break; }
      }
    }
    dom.transcript.querySelectorAll(".split-caption").forEach((caption, index) => {
      const isActive = index === activeIndex;
      caption.parentElement?.classList.toggle("is-active", isActive);
      caption.setAttribute("aria-current", isActive ? "true" : "false");
      if (isActive && scrollSegment && document.getElementById("breakdownFollowPlayback")?.checked) {
        const item = caption.parentElement;
        const top = item.getBoundingClientRect().top - dom.transcript.getBoundingClientRect().top + dom.transcript.scrollTop;
        if (top < dom.transcript.scrollTop || top + item.offsetHeight > dom.transcript.scrollTop + dom.transcript.clientHeight) {
          dom.transcript.scrollTop = Math.max(0, top - 8);
        }
      }
    });
  }

  function setActiveTime(seconds, { seekVideo = false, scrollSegment = false } = {}) {
    const duration = effectiveDuration();
    const clamped = Math.max(0, Math.min(Number(seconds) || 0, duration || 0));
    if (seekVideo && !dom.video.hidden) dom.video.currentTime = clamped;
    renderPlayhead(clamped, duration);
    renderActiveSegment(clamped, scrollSegment);
    return clamped;
  }

  /* ------------------------------------------------- 视频列、播放与音轨 */

  /* The reference video is a 9:16 frame sharing the row with the 视频文案 and
     拆解分析 columns, so its width has to follow the row height instead of a fixed
     180px. Measuring the workbench (whose height is a definite clamp()) keeps the
     three columns the same height, exactly like the old 拆片 workbench. */
  function syncVideoColumnSize() {
    // The approved result layout has a fixed-ratio player beside the analysis.
  }

  function cancelPlaybackSync() {
    if (playbackFrame !== null) window.cancelAnimationFrame(playbackFrame);
    playbackFrame = null;
  }

  /* timeupdate only fires a few times a second, which leaves the playhead lagging
     behind the 口播. Drive the timeline from the animation clock instead, and stand
     back while the operator drags so the drag is not fought frame by frame. */
  function startPlaybackSync() {
    cancelPlaybackSync();
    const step = () => {
      if (dom.video.paused || dom.result.hidden) { cancelPlaybackSync(); return; }
      if (!trackDragging && !trackSeekPending) setActiveTime(dom.video.currentTime, { scrollSegment: true });
      playbackFrame = window.requestAnimationFrame(step);
    };
    playbackFrame = window.requestAnimationFrame(step);
  }

  function isTextEditingTarget(target) {
    return Boolean(target?.matches?.("input, textarea, select, [contenteditable='true']"));
  }

  async function togglePlayback() {
    if (!dom.video.src || dom.video.hidden) return;
    if (!dom.video.paused) { dom.video.pause(); return; }
    try {
      await dom.video.play();
    } catch (_error) {
      showToast("视频无法播放，请检查媒体文件。", "error");
      renderPlaybackControl();
    }
  }

  function updateTimeFromPointer(event, { seekVideo = true } = {}) {
    const lane = laneGeometry();
    const ratio = Math.max(0, Math.min(1, (event.clientX - lane.viewportStart) / Math.max(lane.width, 1)));
    return setActiveTime(ratio * effectiveDuration(), { seekVideo, scrollSegment: true });
  }

  function renderAnalysis() {
    const analysis = state.record?.analysis || null;
    const status = String(state.record?.analysisStatus || "idle");
    const running = ["pending", "running"].includes(status) || state.analyzingId === state.activeId && Boolean(state.activeId);
    const shown = analysisShown();
    dom.analysisBody.replaceChildren();
    if (shown) {
      const cta = analysis.cta;
      const modules = [
        { label: "视频选题", kind: "topic", core: analysis.topic, note: analysis.audience },
        { label: "开头留人钩子", kind: "hook", core: analysis.hookQuote ? `“${analysis.hookQuote}”` : analysis.hook, note: analysis.hookQuote ? analysis.hook : "历史分析未保留开头原句，可补充分析。" },
        { label: "完整视频结构", kind: "structure", core: "", note: analysis.structureSummary || `共 ${(analysis.sections || []).length} 个环节，按原视频顺序排列，可保存为结构模板。` },
        { label: "结尾 CTA", kind: "ending", core: cta ? (cta.present ? `“${cta.quote}”` : "未发现明确的行动引导") : "尚未分析结尾引导", note: cta ? [cta.type, cta.explanation].filter(Boolean).join("：") : "这是一条历史拆解记录，补充分析后可保存结尾引导。" },
      ];
      for (const item of modules) {
        const block = el("section", "breakdown-material");
        const head = el("div", "breakdown-material-head");
        const draft = analysis.templates?.[item.kind];
        const category = { hook: "开头钩子", structure: "视频结构", ending: "结尾 CTA" }[item.kind];
        head.append(el("h2", null, draft ? `${category}：${draft.name}` : item.label));
        const button = el("button", "breakdown-material-save am-secondary-action");
        button.type = "button";
        button.dataset.kind = item.kind;
        const saved = item.kind === "topic" ? state.record.topicId : state.record.writingAssetIds?.[item.kind];
        const unavailable = item.kind === "ending" && !cta?.present;
        button.textContent = saved ? "已添加" : item.kind === "topic" ? "加入选题" : `＋ 添加到${{hook:"开头模板",structure:"结构模板",ending:"结尾引导"}[item.kind]}`;
        button.disabled = Boolean(saved) || unavailable || running || (item.kind !== "topic" && !draft);
        if (item.kind !== "topic" && !draft && !saved) button.title = "请先补充分析，生成模板草稿";
        button.hidden = unavailable;
        button.addEventListener("click", () => item.kind === "topic" ? openTopicModal() : collectWritingAsset(item.kind, button));
        head.append(button);
        block.append(head);
        if (item.kind === "structure") {
          const flow = el("ol", "breakdown-material-flow");
          const steps = draft ? draft.content.split("→").map(text => text.trim()).filter(Boolean) : (analysis.sections || []).map(section => section.name);
          for (const name of steps) flow.append(el("li", null, name));
          block.append(flow);
        } else block.append(el("p", "breakdown-material-core", item.core));
        block.append(el("p", "breakdown-material-note", item.note));
        dom.analysisBody.append(block);
      }
    }
    dom.analysisEmpty.textContent = running
      ? (shown ? "正在补充分析，完成后会自动更新，请稍候…" : "正在分析内容结构，完成后会自动显示，请稍候…")
      : shown ? (!analysis.templates ? "历史记录需补充分析，生成模板名称和通用结构后再添加。" : "") : analysisStateMessage(status, running);
    dom.analysisState.setAttribute("aria-busy", String(running));
    if (running) dom.analysisState.hidden = false;
    /* 拆解分析默认在链接拆解阶段就跑完了，所以这里只在真的没有结果时给出入口：
       服务重启或模型报错留下的 failed，以及老记录里从未分析过的 idle。 */
    const canAnalyze = (!shown || !analysis?.templates) && !running && state.segments.length > 0;
    dom.analyzeButton.hidden = !canAnalyze && !running;
    dom.analyzeButton.disabled = !canAnalyze;
    dom.analyzeButton.textContent = running ? (shown ? "正在补充分析…" : "正在分析…") : shown ? "补充分析" : status === "failed" ? "重试分析" : "开始分析";
  }

  /* 分析结果有效时才顶掉状态位：failed 的旧结果不再冒充可用分析。 */
  function analysisShown() {
    const status = String(state.record?.analysisStatus || "idle");
    return Boolean(state.record?.analysis) && status !== "failed";
  }

  function analysisStateMessage(status, running) {
    if (status === "failed") return state.record?.analysisError || "分析失败，请重试分析。";
    if (running) return "正在分析内容结构，完成后会显示在这里。";
    if (!state.segments.length) return "视频文案转写完成后才能分析。";
    return "这条记录还没有拆解分析结果。";
  }

  function renderPanels() {
    dom.videoPanel.hidden = false;
    dom.contentPanel.hidden = false;
    dom.workbench.dataset.visiblePanels = "video content";
    syncVideoColumnSize();
  }

  /* 文案与分析保留 Tab 选中态、aria-selected 与 roving tabindex。 */
  function renderTabs() {
    const shown = analysisShown();
    dom.transcript.hidden = !state.segments.length;
    dom.transcriptEmpty.hidden = Boolean(state.segments.length);
    dom.analysisState.hidden = shown && Boolean(state.record?.analysis?.templates) && state.analyzingId !== state.activeId;
    dom.analysisBody.hidden = !shown;
  }

  function collectWritingAsset(kind, button) {
    const id = state.activeId;
    const accountId = state.accountId;
    const draft = state.record?.analysis?.templates?.[kind];
    if (!id || !accountId || button.disabled || !draft) return;
    const isCurrent = () => state.activeId === id && state.accountId === accountId && !state.pendingRecordId;
    const opened = window.openWritingAssetDraft?.({
      accountId, kind, draft, isCurrent,
      save: async body => readJson(await fetch(`/api/accounts/${encodeURIComponent(accountId)}/breakdowns/${encodeURIComponent(id)}/writing-assets/${kind}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      })),
      onSaved: asset => {
        if (!isCurrent()) return;
        state.record.writingAssetIds = { ...state.record.writingAssetIds, [kind]: asset.id };
        renderAnalysis();
      },
    });
    if (!opened) showToast("素材编辑器暂不可用，请稍后重试", "error");
  }

  /* 右上角三个动作按需启用：删除针对当前选中的记录，加入选题只在拿到分析结果、
     且这条记录还没写过选题时可用。 */
  function setActionsOpen(open, restoreFocus = false) {
    if (!open) {
      state.deleteArmedFor = "";
      renderDeleteControl();
    }
    dom.actionsPanel.hidden = !open;
    dom.actionsButton.setAttribute("aria-expanded", String(open));
    if (restoreFocus && !dom.actionsButton.disabled) dom.actionsButton.focus();
  }

  function renderDeleteControl() {
    const armed = Boolean(state.activeId) && state.deleteArmedFor === state.activeId;
    dom.deleteButton.textContent = armed ? "确认删除" : "删除";
    dom.deleteButton.classList.toggle("is-armed", armed);
    dom.deleteButton.setAttribute("aria-label", armed ? "再次点击确认删除当前拆解记录" : "删除当前拆解记录");
    dom.deleteButton.disabled = !state.activeId || Boolean(state.pendingRecordId) || Boolean(state.deletingId);
  }

  function renderHeaderActions() {
    if (state.pendingRecordId || state.deleteArmedFor !== state.activeId) state.deleteArmedFor = "";
    dom.actionsButton.disabled = !state.activeId || Boolean(state.pendingRecordId);
    if (dom.actionsButton.disabled) setActionsOpen(false);
    const record = state.pendingRecordId ? null : state.record;
    if (dom.rewriteButton) {
      dom.rewriteButton.disabled = !record || record.analysisStatus !== "complete" || !record.analysis?.sections?.length || state.task?.phase !== "complete" || !String(state.task?.transcript || "").trim();
      dom.rewriteButton.title = dom.rewriteButton.disabled ? "拆解结构和原文准备好后可仿写" : "使用拆解结构与原文仿写新脚本";
    }
    const topicLinked = Boolean(record?.topicId);
    dom.addTopicButton.disabled = !record || !record.analysis || topicLinked;
    dom.addTopicButton.textContent = topicLinked ? "已加入选题" : "加入选题";
    renderDeleteControl();
    if (dom.collectCopyButton) {
      const collected = Boolean(record?.referenceCopyId);
      const collecting = state.collectingCopyId === state.activeId && Boolean(state.activeId);
      const ready = state.task?.phase === "complete" && Boolean(String(state.task?.transcript || "").trim());
      dom.collectCopyButton.disabled = !record || !ready || collecting || collected;
      dom.collectCopyButton.textContent = collecting ? "正在加入…" : collected ? "已加入爆款文案" : "加入爆款文案";
      dom.collectCopyButton.title = ready ? "收藏当前视频文案，创作时按篇选择参考" : "视频文案转写完成后可收藏";
    }
  }

  async function collectReferenceCopy() {
    setActionsOpen(false, true);
    const id = state.activeId;
    const accountId = state.accountId;
    if (!id || !accountId || state.collectingCopyId === id) return;
    state.collectingCopyId = id;
    renderHeaderActions();
    try {
      const result = await readJson(await fetch(`/api/accounts/${encodeURIComponent(accountId)}/breakdowns/${encodeURIComponent(id)}/reference-copy`, { method: "POST" }));
      if (state.activeId !== id || state.accountId !== accountId) return;
      state.record.referenceCopyId = result.id;
      showToast("已加入爆款文案，可在创作时按篇勾选参考", "success");
    } catch (error) {
      if (state.activeId === id && state.accountId === accountId) showToast(responseMessage(error, "收藏失败"), "error");
    } finally {
      if (state.collectingCopyId === id) state.collectingCopyId = "";
      renderHeaderActions();
    }
  }

  function analysisPending() {
    return ["pending", "running"].includes(state.record?.analysisStatus);
  }

  function normalizedPhase(task) {
    const raw = String(task?.phase || "");
    return LEGACY_PHASE_ALIASES[raw] || raw;
  }

  /* 失败阶段：优先用平台回报的 failedStage，其次按解析 / 转写各自的错误码判断。 */
  function failedStageOf(service) {
    const explicit = String(service?.failedStage || "");
    if (explicit) return explicit;
    if (service?.parse?.errorCode) return "parse";
    if (service?.transcription?.errorCode) return "transcribe";
    return "";
  }

  function renderTaskState() {
    const phase = normalizedPhase(state.task);
    const hasRecord = Boolean(state.activeId || state.pendingRecordId);
    const ready = Boolean(state.record) && phase === "complete" && !analysisPending();
    dom.form.hidden = hasRecord;
    dom.intro.hidden = hasRecord;
    const loading = hasRecord && !state.record;
    dom.recordLoading.hidden = !loading;
    dom.taskState.hidden = !hasRecord || loading || ready;
    const locked = hasRecord || state.busy;
    dom.shareInput.readOnly = locked;
    dom.submitButton.disabled = locked;
    dom.pasteButton.disabled = locked;
    dom.clearButton.disabled = locked;
    dom.submitButton.textContent = hasRecord ? (phase === "failed" ? "拆解失败" : "正在拆解…") : state.busy ? "正在提交…" : "开始拆解";
    if (state.record) dom.shareInput.value = state.record.shareText || "";
    if (!hasRecord || loading) return;
    const failed = phase === "failed";
    const analysing = phase === "complete" && analysisPending();
    const service = state.task?.creationService || {};
    const stage = failed ? failedStageOf(service) : String(service.currentStage || "");
    let step;
    if (analysing || phase === "complete") step = 4;
    else if (failed) step = PHASE_STEP[normalizedPhase({ phase: state.task?.failedPhase })] ?? STAGE_STEP[stage] ?? -1;
    else step = PHASE_STEP[phase] ?? -1;
    dom.failedDelete.hidden = !failed;

    const diagnostic = [];
    if (service.parse?.taskId) diagnostic.push(`解析任务号 ${service.parse.taskId}`);
    if (service.transcription?.taskId) diagnostic.push(`转写任务号 ${service.transcription.taskId}`);
    if (state.task?.errorCode) diagnostic.push(`错误码 ${state.task.errorCode}`);
    if (failed && step < 0) diagnostic.push("阶段未知");
    dom.taskDiagnostic.textContent = diagnostic.join(" · ");
    dom.taskDiagnostic.hidden = !diagnostic.length;
    // Keep markers mounted across polling, including phase changes within one step.
    // Replacing them restarts the CSS spinner every 1.5 seconds.
    if (!dom.progress.children.length) {
      PROGRESS_STEPS.forEach((label) => {
        const item = el("li");
        const copy = el("div", "breakdown-progress-copy");
        copy.append(el("strong", "breakdown-progress-label", label), el("p", "breakdown-progress-subtitle"));
        item.append(el("span"), copy);
        dom.progress.append(item);
      });
    }
    PROGRESS_STEPS.forEach((label, index) => {
      const kind = index < step ? "is-complete" : index === step ? (failed ? "is-failed" : "is-current") : "is-pending";
      const item = dom.progress.children[index];
      if (item.className !== kind) item.className = kind;
      const marker = item.children[0];
      const markerText = index < step ? "✓" : index === step && failed ? "!" : String(index + 1);
      if (marker.textContent !== markerText) marker.textContent = markerText;
      let subtitle = ["等待解析链接", "等待下载视频", "等待提取音频", "等待上传与转写", "等待内容分析"][index];
      if (index < step) subtitle = ["已获取视频地址", "视频已下载完成", "音频已提取完成", "上传与文案转写已完成", "内容分析已完成"][index];
      if (state.task?.source === "upload" && index < 2) subtitle = "本地素材，无需此步骤";
      if (index === step) {
        subtitle = failed ? state.task?.message || "处理失败，请重试" : ({
          parsing: "正在解析视频地址…", downloading: "正在下载视频…", extracting: "正在提取音频…",
          uploading: "正在上传音频…", transcribing: "正在转写视频文案…", fetching: "正在获取转写结果…",
          rewriting: "正在整理转写文案…", complete: state.record?.analysisStatus === "pending" ? "等待开始内容分析…" : "正在分析内容结构…",
        }[phase] || "正在处理…");
        if (!failed && index === 3 && service.transcription?.status === "reconciling") subtitle = "转写结果待确认，正在查询…";
      }
      const subtitleNode = item.children[1].children[1];
      if (subtitleNode.textContent !== subtitle) subtitleNode.textContent = subtitle;
      if (index === step) item.setAttribute("aria-current", "step");
      else item.removeAttribute("aria-current");
      item.setAttribute("aria-label", `${label}：${index < step ? "已完成" : index === step ? (failed ? "失败" : "进行中") : "待处理"}`);
    });
    const presentation = analysing ? { title: "正在分析内容结构", hint: "视频与文案已就绪，正在生成拆解分析。" }
      : PHASE_PRESENTATIONS[phase] || PHASE_PRESENTATIONS.queued;
    dom.taskState.dataset.phase = failed ? "failed" : analysing ? "analysing" : phase;
    // 当前状态与辅助说明为主信息，步骤条呈现整体进度。
    dom.taskCopy.hidden = false;
    dom.taskActions.hidden = !failed;
    dom.taskMessage.hidden = false;
    dom.taskTitle.textContent = presentation.title;
    dom.taskMessage.textContent = failed ? state.task?.message || presentation.hint : presentation.hint;
    renderStageSummary(service);
    dom.retryButton.hidden = !failed;
  }

  function resultTitleText(title) {
    const text = String(title || "").trim() || "脚本文案";
    const characters = Array.from(text);
    return characters.length > RESULT_TITLE_LIMIT ? `${characters.slice(0, RESULT_TITLE_LIMIT).join("")}...` : text;
  }

  function renderResult() {
    const record = state.record;
    const phase = String(state.task?.phase || "");
    const ready = Boolean(record) && phase === "complete" && !analysisPending();
    // 未就绪时由独立状态卡承载操作，结果工具栏仅在结果可用时显示。
    dom.result.hidden = !ready;
    dom.result.classList.toggle("is-pending", !ready);
    dom.workbench.hidden = !ready;
    dom.timeline.hidden = true;
    dom.hint.hidden = true;
    if (!record) return;
    dom.resultTitle.textContent = resultTitleText(record.title);
    dom.resultTitle.title = String(record.title || "").trim() || "脚本文案";
    const author = String(state.task?.author || "").trim();
    const meta = [];
    if (author && !["未知作者", "作者未提供", "—", "-"].includes(author)) meta.push(author);
    if (Number.isFinite(state.duration) && state.duration > 0) meta.push(formatTime(state.duration));
    const sourceMeta = el("span", "breakdown-result-source");
    if (meta.length) sourceMeta.append(el("span", "breakdown-result-author", meta.join(" · ")));
    authorActionsNode = el("span", "breakdown-author-actions");
    sourceMeta.append(authorActionsNode);
    renderAuthorActions();
    const copyTitle = el("button", "breakdown-copy-title", "复制标题");
    copyTitle.type = "button";
    copyTitle.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(String(record.title || "").trim());
        showToast("标题已复制", "success");
      } catch (_) { showToast("复制失败，请选择标题手动复制", "error"); }
    });
    sourceMeta.append(copyTitle);
    const source = String(record.shareText || "").match(/https?:\/\/[^\s<>"']+/)?.[0];
    if (source) {
      const link = el("a", null, "查看原视频 ↗");
      link.href = source;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      sourceMeta.append(link);
    }
    const metrics = state.task?.metrics || {};
    const counts = [["点赞", "likes"], ["评论", "comments"], ["收藏", "collects"], ["分享", "shares"]].flatMap(([label, key]) => {
      const value = metrics[key];
      return typeof value === "number" && Number.isFinite(value) && value >= 0 ? [`${label} ${value.toLocaleString("zh-CN")}`] : [];
    });
    dom.resultMeta.replaceChildren(...(counts.length ? [el("span", "breakdown-result-metrics", counts.join("　"))] : []), sourceMeta);
    dom.resultMeta.hidden = false;
    if (dom.resultFees) dom.resultFees.hidden = true;
    if (!ready) return;
    renderVideo();
    renderTranscript();
    renderWaveform(state.task?.waveformPeaks);
    const duration = effectiveDuration();
    dom.track.hidden = duration <= 0;
    renderTicks(duration);
    trackDragging = false;
    trackSeekPending = false;
    trackSeekTarget = null;
    setActiveTime(0);
    renderAnalysis();
    renderPanels();
    // The workbench height is a definite clamp(), so the video column can be
    // measured as soon as the content lands instead of waiting for a resize.
    window.requestAnimationFrame(syncVideoColumnSize);
  }

  function render() {
    renderList();
    renderTaskState();
    renderResult();
    renderHeaderActions();
    renderTabs();
    renderMediaState();
    renderFeeCap();
  }

  /* ------------------------------------------------------------ 数据 */

  let authorActionsNode = null;
  let authorRequestVersion = 0;
  let authorStatus = null;

  function renderAuthorActions() {
    if (!authorActionsNode) return;
    authorActionsNode.replaceChildren();
    const status = authorStatus;
    if (!status) return;
    const accountId = state.accountId;
    const recordId = state.activeId;
    const current = () => state.accountId === accountId && state.activeId === recordId && !state.pendingRecordId;
    if (status.profileUrl) {
      const link = el("a", null, "查看主页");
      link.href = status.profileUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      authorActionsNode.append(link);
      const button = el("button", null, status.following ? "查看监控" : "添加监控");
      button.type = "button";
      button.addEventListener("click", async () => {
        if (!current() || button.disabled) return;
        if (status.following) {
          window.monitorModule?.openBlogger?.(accountId, status.bloggerId, status.nickname);
          return;
        }
        button.disabled = true;
        try {
          const result = await readJson(await fetch(`/api/accounts/${encodeURIComponent(accountId)}/breakdowns/${encodeURIComponent(recordId)}/author/monitor`, { method: "POST" }));
          if (!current()) return;
          authorRequestVersion += 1;
          authorStatus = result;
          renderAuthorActions();
          showToast("已添加监控，后续采集按现有规则计费", "success");
        } catch (error) {
          if (current()) showToast(responseMessage(error, "添加监控失败"), "error");
        } finally { button.disabled = false; }
      });
      authorActionsNode.append(button);
    } else if (status.uniqueId) {
      const button = el("button", null, "复制抖音号");
      button.type = "button";
      button.addEventListener("click", async () => {
        if (!current()) return;
        try { await navigator.clipboard.writeText(status.uniqueId); if (current()) showToast("抖音号已复制", "success"); }
        catch (_) { if (current()) showToast("复制失败，请重试", "error"); }
      });
      authorActionsNode.append(button);
    }
  }

  async function loadAuthorStatus() {
    const version = ++authorRequestVersion;
    const accountId = state.accountId;
    const recordId = state.activeId;
    authorStatus = null;
    renderAuthorActions();
    if (!accountId || !recordId) return;
    try {
      const result = await readJson(await fetch(`/api/accounts/${encodeURIComponent(accountId)}/breakdowns/${encodeURIComponent(recordId)}/author`));
      if (version !== authorRequestVersion || state.accountId !== accountId || state.activeId !== recordId) return;
      authorStatus = result;
      renderAuthorActions();
    } catch (_) { /* Optional local author actions must not block the video. */ }
  }

  function applyRecord(payload) {
    state.record = payload;
    loadAuthorStatus();
    state.task = payload?.task || null;
    state.duration = Number(payload?.task?.duration) || 0;
    state.segments = Array.isArray(payload?.task?.transcriptSegments)
      ? payload.task.transcriptSegments.map((segment) => ({
        start: Math.max(0, Number(segment.start) || 0),
        end: Math.max(0, Number(segment.end) || 0),
        text: String(segment.text || "").trim(),
      })).filter((segment) => segment.end >= segment.start && segment.text)
      : [];
    upsertItem({
      id: payload.id,
      title: payload.title,
      accountId: payload.accountId,
      taskId: payload.taskId,
      shareText: payload.shareText,
      analysisStatus: payload.analysisStatus,
      topicId: payload.topicId,
      createdAt: payload.createdAt,
      updatedAt: payload.updatedAt,
      task: { phase: payload?.task?.phase || "", message: payload?.task?.message || "" },
    });
  }

  function stopPolling() {
    if (state.pollTimer !== null) window.clearTimeout(state.pollTimer);
    state.pollTimer = null;
    state.pollFailures = 0;
  }

  function schedulePoll(delay) {
    stopPolling();
    const id = state.activeId;
    state.pollTimer = window.setTimeout(() => {
      state.pollTimer = null;
      if (state.activeId === id) refreshRecord().catch(() => {});
    }, delay);
  }

  async function refreshRecord() {
    const id = state.activeId;
    if (!id || state.pendingRecordId) return;
    const version = ++state.recordRequestVersion;
    try {
      const payload = await readJson(await fetch(`/api/breakdowns/${encodeURIComponent(id)}`));
      if (state.activeId !== id || state.recordRequestVersion !== version) return;
      applyRecord(payload);
      state.pollFailures = 0;
      render();
      const phase = String(payload?.task?.phase || "");
      if ((phase && phase !== "complete" && phase !== "failed") || (phase === "complete" && analysisPending())) schedulePoll(1500);
    } catch (error) {
      if (state.activeId !== id || state.recordRequestVersion !== version) return;
      state.pollFailures += 1;
      schedulePoll(Math.min(1500 * 2 ** Math.min(state.pollFailures, 4), 15000));
    }
  }

  // 参考脚本面板的 pending selection：保留已显示内容，详情到齐后再一次提交。
  function renderRecordSelection() {
    const pending = Boolean(state.pendingRecordId);
    dom.result.inert = pending;
    dom.taskState.inert = pending;
    dom.result.setAttribute("aria-busy", String(pending));
    renderList();
    renderHeaderActions();
    if (!state.record) renderTaskState();
  }

  function resumeRecordPolling() {
    const phase = String(state.task?.phase || "");
    if (state.activeId && ((phase && phase !== "complete" && phase !== "failed") || analysisPending())) schedulePoll(1500);
  }

  async function openRecord(id) {
    window.closeWritingAssetDraft?.();
    window.BreakdownRewrite?.close();
    if (!id || state.pendingRecordId === id || (!state.pendingRecordId && state.activeId === id)) return;
    stopPolling();
    const version = ++state.recordRequestVersion;
    const accountId = state.accountId;
    // 等待 B 时点回已展示的 A：取消 B，保留 A 的播放器、Tab 与滚动位置。
    if (state.activeId === id && state.record) {
      state.pendingRecordId = "";
      renderRecordSelection();
      resumeRecordPolling();
      return;
    }
    state.pendingRecordId = id;
    dom.video.pause();
    cancelPlaybackSync();
    renderRecordSelection();
    try {
      const payload = await readJson(await fetch(`/api/breakdowns/${encodeURIComponent(id)}`));
      if (state.accountId !== accountId || state.pendingRecordId !== id || state.recordRequestVersion !== version) return;
      state.pendingRecordId = "";
      state.activeId = id;
      state.inFlight = false;
      state.tab = "transcript";
      applyRecord(payload);
      renderRecordSelection();
      render();
      resumeRecordPolling();
    } catch (error) {
      if (state.accountId !== accountId || state.pendingRecordId !== id || state.recordRequestVersion !== version) return;
      state.pendingRecordId = "";
      renderRecordSelection();
      showToast(responseMessage(error, "读取拆解记录失败，请重试"), "error");
      resumeRecordPolling();
    }
  }

  /* 新建拆解从空白输入开始：列表里刚看过的记录会把分享文案留在输入框里，
     新建时必须清掉。重新拆解（retryButton）不传 resetLink，保留原链接方便同一条重试。 */
  function showNewForm(options) {
    window.BreakdownRewrite?.close();
    setActionsOpen(false);
    state.pendingRecordId = "";
    state.recordRequestVersion += 1;
    dom.result.inert = false;
    dom.taskState.inert = false;
    dom.result.setAttribute("aria-busy", "false");
    const retryMedia = !options?.resetLink ? state.task?.retryMedia : null;
    const needsMedia = !options?.resetLink && state.task?.source === "upload";
    stopPolling();
    state.activeId = "";
    state.record = null;
    state.task = null;
    state.segments = [];
    state.duration = 0;
    state.inFlight = false;
    state.tab = "transcript";
    dom.form.hidden = false;
    dom.taskState.hidden = true;
    state.feeCap = null;
    if (needsMedia) {
      dom.shareInput.value = "";
      clearMedia();
      if (retryMedia) state.media = { id: retryMedia.mediaId, name: retryMedia.name, durationSeconds: retryMedia.durationSeconds, uploading: false };
    }
    if (options?.resetLink) {
      dom.shareInput.value = "";
      clearMedia();
      state.feeCap = null;
    }
    setFormMessage(needsMedia && !retryMedia ? "本地素材已不可用，请重新选择文件。" : "");
    render();
    loadFeeCap();
    window.requestAnimationFrame(() => dom.shareInput.focus());
  }

  function setFormMessage(message, kind = "") {
    dom.formMessage.hidden = !message;
    dom.formMessage.textContent = message;
    dom.formMessage.dataset.kind = kind;
  }

  /* ------------------------------------------------------ 本地素材与费用上限 */

  function formatDuration(seconds) {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    if (!total) return "";
    const minutes = Math.floor(total / 60);
    const rest = total % 60;
    return minutes ? `${minutes} 分 ${String(rest).padStart(2, "0")} 秒` : `${rest} 秒`;
  }

  function renderMediaState() {
    const chosen = Boolean(state.media.id);
    dom.mediaState.hidden = !chosen && !state.media.uploading;
    if (state.media.uploading) {
      dom.mediaState.textContent = "正在读取本地音视频…";
      dom.mediaState.dataset.kind = "";
    } else if (chosen) {
      const duration = formatDuration(state.media.durationSeconds);
      dom.mediaState.textContent = `本地音视频：${state.media.name}${duration ? `（约 ${duration}）` : ""}`;
      dom.mediaState.dataset.kind = "";
    } else {
      dom.mediaState.textContent = "";
    }
    if (dom.shareInput) dom.shareInput.readOnly = chosen || state.busy || Boolean(state.activeId);
    dom.chooseMediaButton.textContent = chosen ? "更换本地音视频" : "选择本地音视频";
  }

  /* 分享链接在输入后提示转写时长上限，本地素材按真实时长估算。
     任务提交后以平台落定的授权额度为准，界面不再出现人民币金额。 */
  function renderFeeCap() {
    // 没有记录或待拆解素材时保持空白，异步报价返回也不显示消耗提示。
    if (!state.activeId && !state.media.id && !dom.shareInput.value.trim()) {
      dom.feeCap.hidden = true;
      dom.feeCap.textContent = "";
      return;
    }
    if (!state.activeId && !state.media.id && dom.shareInput.value.trim()) {
      dom.feeCap.textContent = "最长支持转写 10 分钟以内视频，超出上限会中止！";
      dom.feeCap.hidden = false;
      return;
    }
    const service = state.task?.creationService || {};
    const settledTranscription = String(service.transcription?.maxChargePoints || service.maxChargePoints || "").trim();
    const settledParse = String(service.parse?.maxChargePoints || "").trim();
    const cap = state.feeCap;
    if (settledTranscription || settledParse) {
      const parts = [];
      if (settledParse) parts.push(`视频解析上限 ${trimPoints(settledParse)} 积分`);
      if (settledTranscription) parts.push(`音频转写上限 ${trimPoints(settledTranscription)} 积分`);
      dom.feeCap.textContent = `本次${parts.join("、")}`;
      dom.feeCap.hidden = false;
      return;
    }
    const parseEstimate = String(cap?.parseEstimatedPoints || "").trim();
    const transcriptionEstimate = String(cap?.estimatedPoints || "").trim();
    if (!transcriptionEstimate && !parseEstimate) {
      dom.feeCap.hidden = true;
      dom.feeCap.textContent = "";
      return;
    }
    const scope = cap.source === "upload" ? "本地素材时长" : `最长 ${Math.round((cap.durationSeconds || 0) / 60)} 分钟`;
    const parts = [];
    if (parseEstimate) parts.push(`视频解析 ${trimPoints(parseEstimate)} 积分`);
    if (transcriptionEstimate) parts.push(`音频转写 ${trimPoints(transcriptionEstimate)} 积分`);
    dom.feeCap.textContent = `本次预计消耗 ${parts.join(" + ")}（${scope}估算，超出授权上限会中止结算）`;
    dom.feeCap.hidden = false;
  }

  /* 682.500 → 682.5：界面只保留有效小数位。 */
  function trimPoints(value) {
    let text = String(value === null || value === undefined ? "0" : value).trim();
    if (text.indexOf(".") < 0) return text || "0";
    while (text.endsWith("0")) text = text.slice(0, -1);
    if (text.endsWith(".")) text = text.slice(0, -1);
    return text || "0";
  }

  async function loadFeeCap() {
    const version = state.feeRequestVersion + 1;
    state.feeRequestVersion = version;
    try {
      const query = state.media.id ? `?mediaId=${encodeURIComponent(state.media.id)}` : "";
      const payload = await readJson(await fetch(`/api/creation/transcription-quote${query}`));
      if (state.feeRequestVersion !== version) return;
      state.feeCap = payload;
    } catch (_error) {
      /* 取不到上限不阻塞提交：真正的上限仍由服务端在提交时决定。 */
      if (state.feeRequestVersion !== version) return;
      state.feeCap = null;
    }
    renderFeeCap();
  }

  async function chooseMedia() {
    if (state.busy || state.activeId) return;
    dom.mediaInput.value = "";
    dom.mediaInput.click();
  }

  async function uploadMedia(file) {
    if (!file) return;
    state.media.uploading = true;
    renderMediaState();
    setFormMessage("");
    const body = new FormData();
    body.append("file", file, file.name);
    try {
      const payload = await readJson(await fetch("/api/creation/media", { method: "POST", body }));
      state.media = {
        id: String(payload.mediaId || ""),
        name: String(payload.name || file.name),
        durationSeconds: Number(payload.durationSeconds) || 0,
        uploading: false,
      };
      // 选了本地素材就不再需要链接：清掉输入框，避免提交两份来源。
      dom.shareInput.value = "";
      state.feeCap = {
        source: "upload",
        durationSeconds: state.media.durationSeconds,
        estimatedPoints: String(payload.estimatedPoints || ""),
        estimateMinutes: String(payload.estimateMinutes || ""),
      };
    } catch (error) {
      state.media = { id: "", name: "", durationSeconds: 0, uploading: false };
      setFormMessage(responseMessage(error, "本地素材读取失败，请重新选择。"), "error");
    } finally {
      state.media.uploading = false;
      renderMediaState();
      renderFeeCap();
    }
  }

  function clearMedia() {
    state.media = { id: "", name: "", durationSeconds: 0, uploading: false };
    if (dom.mediaInput) dom.mediaInput.value = "";
    renderMediaState();
  }

  /* 两笔独立结算：视频解析按次、音频转写按平台核验分钟，分别展示状态与积分。 */
  function stageStatusText(view) {
    const status = String(view?.status || "");
    return view?.statusLabel || STATUS_LABELS[status] || "";
  }

  function chargedText(view) {
    const charged = String(view?.chargedPoints || "");
    if (charged && Number(charged) > 0) return `已扣 ${trimPoints(charged)} 积分`;
    const frozen = String(view?.frozenPoints || "");
    if (frozen && Number(frozen) > 0) return `已冻结 ${trimPoints(frozen)} 积分`;
    return "尚未扣点";
  }

  function minutesText(view) {
    const quantity = String(view?.quantity || "").trim();
    if (!quantity || !(Number(quantity) > 0)) return "";
    // 计费分钟是平台核验时长折算的精确小数，展示收敛到两位，便于阅读。
    return `${trimPoints(Number(quantity).toFixed(2))} 分钟`;
  }

  function billingLines(service) {
    if (!service) return [];
    const lines = [];
    const parse = service.parse || {};
    if (parse.taskId || parse.status) {
      const count = String(parse.quantity || "").trim() || "1";
      lines.push(["视频解析", stageStatusText(parse), `${count} 次`, chargedText(parse)].filter(Boolean).join(" · "));
    }
    const transcription = service.transcription || {};
    if (transcription.taskId || transcription.status) {
      lines.push(["音频转写", stageStatusText(transcription), minutesText(transcription), chargedText(transcription)].filter(Boolean).join(" · "));
    }
    return lines;
  }

  function billingText(service) {
    return billingLines(service).join("\n");
  }

  /* 两段状态分别展示：解析成功/失败、转写成功/失败，各带次数或分钟与积分。 */
  function renderStageSummary(service) {
    const container = dom.stageSummary;
    if (!container) return;
    const stages = [
      { name: "视频解析", view: service?.parse || {}, unit: (view) => `${String(view.quantity || "").trim() || "1"} 次` },
      { name: "音频转写", view: service?.transcription || {}, unit: minutesText },
    ];
    container.replaceChildren();
    let shown = 0;
    for (const stage of stages) {
      if (!stage.view.taskId && !stage.view.status) continue;
      const status = String(stage.view.status || "");
      const row = el("div", "breakdown-stage-row");
      row.dataset.status = status === "succeeded" ? "succeeded" : status === "failed" ? "failed" : "running";
      row.append(el("span", "breakdown-stage-name", stage.name));
      row.append(el("span", "breakdown-stage-status", stageStatusText(stage.view) || "处理中"));
      row.append(el("span", "breakdown-stage-detail", [stage.unit(stage.view), chargedText(stage.view)].filter(Boolean).join(" · ")));
      container.append(row);
      shown += 1;
    }
    // 解析已计费、后续阶段失败时不退费：明确告知，避免用户以为重新拆解能拿回这笔。
    const parseCharged = Number(service?.parse?.chargedPoints || 0);
    const parseFailed = String(service?.parse?.status || "") === "failed";
    const laterFailed = [String(service?.transcription?.status || ""), String(state.task?.phase || "")].some(
      (value) => value === "failed",
    );
    if (shown && !parseFailed && laterFailed && parseCharged > 0) {
      const note = el("p", "breakdown-stage-note");
      note.textContent = "视频解析已计费，后续阶段失败时不退回解析费。";
      container.append(note);
    }
    container.hidden = shown === 0;
  }

  function setBusy(disabled) {
    state.busy = disabled;
    dom.submitButton.disabled = disabled;
    dom.pasteButton.disabled = disabled;
    dom.clearButton.disabled = disabled;
    dom.submitButton.textContent = disabled ? "正在提交…" : "开始拆解";
    renderTaskState();
    renderAnalysis();
  }

  async function submitBreakdown(event, sourceTitle = "") {
    event?.preventDefault();
    // 拆解要走创作服务平台转写，未登录时先弹登录框：
    // 否则会先建一条记录，再把「请先登录」写成这条记录的失败原因。
    if (!(await requireWorkbenchLogin())) return;
    if (state.busy || state.activeId) return;
    const shareText = dom.shareInput.value.trim();
    const mediaId = state.media.id;
    if (!shareText && !mediaId) {
      setFormMessage("请先粘贴视频分享链接，或选择本地音视频文件", "error");
      dom.shareInput.focus();
      return;
    }
    if (!state.accountId) {
      setFormMessage("请先创建或选择账号", "error");
      return;
    }
    const accountId = state.accountId;
    setBusy(true);
    setFormMessage("");
    try {
      const payload = await readJson(await fetch(`/api/accounts/${encodeURIComponent(accountId)}/breakdowns`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(mediaId ? { mediaId } : { shareText, ...(sourceTitle ? { title: sourceTitle } : {}) }),
      }));
      if (!isSameAccount(accountId)) return;
      dom.shareInput.value = "";
      clearMedia();
      state.items = [{ ...payload, task: { phase: "queued", message: "正在排队…" } }, ...state.items.filter((item) => item.id !== payload.id)];
      await openRecord(payload.id);
      showToast("已提交拆解任务", "success");
    } catch (error) {
      if (isSameAccount(accountId)) setFormMessage(responseMessage(error, "拆解失败，请检查链接后重试。"), "error");
    } finally {
      if (isSameAccount(accountId)) setBusy(false);
    }
  }

  /* 就地重试失败任务：服务端复用解析结果与本地 MP3，重启/重试都不重复解析或重复上传。 */
  async function retryBreakdown(id) {
    if (!id || state.busy) return;
    if (!(await requireWorkbenchLogin())) return;
    state.busy = true;
    renderTaskState();
    try {
      const payload = await readJson(await fetch(`/api/breakdowns/${encodeURIComponent(id)}/retry`, { method: "POST" }));
      if (state.activeId !== id) return;
      applyRecord(payload);
      state.recordRequestVersion += 1;
      render();
      resumeRecordPolling();
      showToast("已重新开始拆解", "success");
    } catch (error) {
      if (state.activeId === id) showToast(responseMessage(error, "重新拆解失败，请稍后重试"), "error");
    } finally {
      state.busy = false;
      renderTaskState();
    }
  }

  async function analyze() {
    if (!state.activeId || state.busy || analysisPending()) return;
    const id = state.activeId;
    state.busy = true;
    state.analyzingId = id;
    renderAnalysis();
    try {
      const payload = await readJson(await fetch(`/api/breakdowns/${encodeURIComponent(id)}/analyze`, { method: "POST" }));
      if (state.activeId !== id) return;
      applyRecord(payload);
      render();
      showToast("拆解分析完成", "success");
    } catch (error) {
      if (state.activeId === id) {
        showToast(responseMessage(error, "拆解分析失败"), "error");
        await refreshRecord();
      }
    } finally {
      state.busy = false;
      if (state.analyzingId === id) state.analyzingId = "";
      renderAnalysis();
      renderTabs();
    }
  }

  /* -------------------------------------------------------- 选题弹窗 */

  /* The week and category fields reuse the 选题 module's picker surface so the two
     places cannot drift, and so no native select ever appears in this page. */
  function createPicker(key, inputId, label, readOptions) {
    const input = document.getElementById(inputId);
    const host = document.querySelector(`[data-breakdown-picker="${key}"] .topics-select-control`);
    const control = el("button", "am-input topics-select-button");
    control.type = "button";
    control.id = inputId + "Button";
    control.setAttribute("aria-haspopup", "menu");
    control.setAttribute("aria-expanded", "false");
    control.setAttribute("aria-label", label);
    const valueNode = el("span", "topics-select-value");
    valueNode.id = inputId + "Value";
    const chevron = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    chevron.setAttribute("class", "topics-select-chevron");
    chevron.setAttribute("width", "12");
    chevron.setAttribute("height", "12");
    chevron.setAttribute("viewBox", "0 0 12 12");
    chevron.setAttribute("fill", "none");
    chevron.setAttribute("aria-hidden", "true");
    const chevronPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    chevronPath.setAttribute("d", "M3 4.5L6 7.5L9 4.5");
    chevronPath.setAttribute("stroke", "currentColor");
    chevronPath.setAttribute("stroke-width", "1.5");
    chevronPath.setAttribute("stroke-linecap", "round");
    chevronPath.setAttribute("stroke-linejoin", "round");
    chevron.append(chevronPath);
    const menu = el("div", "topics-select-menu");
    menu.id = inputId + "Menu";
    menu.setAttribute("role", "menu");
    menu.setAttribute("aria-label", label);
    menu.hidden = true;
    control.append(valueNode, chevron);
    host.append(control, menu);

    const optionsOf = () => readOptions();
    const labelFor = (option) => (optionsOf().find(([candidate]) => candidate === option) || [])[1] || option;
    const picker = {
      control,
      input,
      close() {
        menu.hidden = true;
        control.setAttribute("aria-expanded", "false");
      },
      setOptions() {
        menu.replaceChildren(...optionsOf().map(([option, optionLabel]) => {
          const selected = input.value === option;
          const button = el("button", selected ? "is-current" : null, (selected ? "✓ " : "") + optionLabel);
          button.type = "button";
          button.setAttribute("role", "menuitemradio");
          button.setAttribute("aria-checked", String(selected));
          button.dataset.breakdownOption = option;
          button.addEventListener("click", () => {
            picker.select(option);
            control.focus({ preventScroll: true });
          });
          return button;
        }));
      },
      select(option, { silent = false } = {}) {
        const allowed = optionsOf().map(([candidate]) => candidate);
        const next = allowed.includes(option) ? option : allowed[0];
        input.value = next;
        valueNode.textContent = labelFor(next);
        if (!silent) {
          picker.setOptions();
          picker.close();
        }
        return next;
      },
    };
    control.addEventListener("click", () => {
      const open = menu.hidden;
      picker.setOptions();
      menu.hidden = !open;
      control.setAttribute("aria-expanded", String(open));
      if (open) menu.querySelector("button")?.focus({ preventScroll: true });
    });
    document.addEventListener("pointerdown", (event) => {
      if (!menu.hidden && !control.contains(event.target) && !menu.contains(event.target)) picker.close();
    });
    return picker;
  }

  function weekOptions() {
    const currentWeekStart = isoDate(weekStartOf(new Date()));
    const options = [];
    for (let offset = -2; offset <= 5; offset += 1) {
      const start = shiftIsoWeek(currentWeekStart, offset);
      const endDate = new Date(start);
      endDate.setDate(endDate.getDate() + 6);
      const suffix = offset === 0 ? "（本周）" : offset === 1 ? "（下周）" : "";
      options.push([start, `${start} ~ ${isoDate(endDate)}${suffix}`]);
    }
    return options;
  }

  const weekPicker = createPicker("week", "breakdownTopicWeekSelect", "计划周", weekOptions);
  const categoryPicker = createPicker("category", "breakdownTopicCategorySelect", "选题分类", () => [
    ["highlight", CATEGORY_LABELS.highlight],
    ["daily", CATEGORY_LABELS.daily],
    ["series", CATEGORY_LABELS.series],
    ["test", CATEGORY_LABELS.test],
  ]);
  const formatPicker = createPicker("format", "breakdownTopicFormatSelect", "内容形式", () => [
    ["video", "视频"],
    ["article", "图文"],
  ]);

  function openTopicModal() {
    setActionsOpen(false);
    if (!state.record?.analysis) return;
    /* 标题与大纲先放拆解分析给出的初稿（后端存的就是这一份），改过就以改过的为准。 */
    const draft = state.record.topicDraft || {};
    weekPicker.setOptions();
    weekPicker.select(isoDate(weekStartOf(new Date())), { silent: true });
    categoryPicker.select("highlight", { silent: true });
    formatPicker.select("video", { silent: true });
    dom.topicTitle.value = draft.title || state.record.title || "";
    dom.topicOutline.value = draft.outline || "";
    dom.topicDate.value = "";
    dom.topicMessage.hidden = true;
    dom.topicModal.hidden = false;
    dom.topicConfirm.disabled = false;
    window.topicEntryModal?.resize(dom.topicModal);
    window.requestAnimationFrame(() => dom.topicTitle.focus());
  }

  function closeTopicModal(restoreFocus = false) {
    dom.topicModal.hidden = true;
    weekPicker.close();
    categoryPicker.close();
    formatPicker.close();
    if (restoreFocus) dom.actionsButton.focus();
  }

  async function confirmTopic() {
    if (window.WorkbenchDateTimePicker?.validateInputs(dom.topicDate) === false) return;
    if (!state.activeId) return;
    const title = (dom.topicTitle.value || "").trim();
    if (!title) {
      dom.topicMessage.hidden = false;
      dom.topicMessage.textContent = "选题标题不能为空。";
      dom.topicTitle.focus();
      return;
    }
    const id = state.activeId;
    dom.topicConfirm.disabled = true;
    try {
      const payload = await readJson(await fetch(`/api/breakdowns/${encodeURIComponent(id)}/topic`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          outline: (dom.topicOutline.value || "").trim(),
          category: dom.topicCategory.value,
          format: dom.topicFormat.value,
          weekStart: dom.topicWeek.value,
          publishDate: dom.topicDate.value,
        }),
      }));
      if (state.activeId !== id) return;
      closeTopicModal(true);
      /* 选题页保留着已读的周，这里写入的是另一页的数据，交给它下次进入时补读。 */
      window.topicsModule?.invalidate?.();
      await refreshRecord();
      showToast("已加入选题，可在「本周选题」里继续编辑", "success");
    } catch (error) {
      dom.topicMessage.hidden = false;
      dom.topicMessage.textContent = responseMessage(error, "加入选题失败");
    } finally {
      dom.topicConfirm.disabled = false;
    }
  }

  /* -------------------------------------------------------- 删除弹窗 */

  function askDelete(record) {
    setActionsOpen(false);
    state.pendingDeleteId = record.id;
    dom.deleteCopy.textContent = `「${record.title || "视频标题待获取"}」会被移除，已加入的选题和已创建的脚本都会保留。`;
    dom.deleteModal.hidden = false;
    window.requestAnimationFrame(() => dom.deleteConfirm.focus());
  }

  function closeDeleteModal(restoreFocus = false) {
    state.pendingDeleteId = "";
    dom.deleteModal.hidden = true;
    if (restoreFocus) dom.actionsButton.focus();
  }

  async function confirmDelete(id = state.pendingDeleteId) {
    if (!id || state.deletingId) return;
    const accountId = state.accountId;
    state.deletingId = id;
    renderDeleteControl();
    dom.deleteConfirm.disabled = true;
    try {
      await readJson(await fetch(`/api/breakdowns/${encodeURIComponent(id)}`, { method: "DELETE" }));
      if (!isSameAccount(accountId)) return;
      closeDeleteModal();
      state.items = state.items.filter((item) => item.id !== id);
      if (state.activeId === id) showNewForm({ resetLink: true });
      renderList();
      showToast("拆解记录已删除", "success");
    } catch (error) {
      showToast(responseMessage(error, "删除拆解记录失败"), "error");
    } finally {
      state.deletingId = "";
      state.deleteArmedFor = "";
      renderDeleteControl();
      dom.deleteConfirm.disabled = false;
    }
  }

  /* ------------------------------------------------------------ 事件 */

  /* Tab 只切显示：不重新请求分析，也不打断正在播放的视频。 */
  function selectTab(tabId) {
    if (state.tab === tabId) return;
    state.tab = tabId;
    renderTabs();
  }

  /* Roving tabindex 必须配方向键，否则未选中的 Tab 键盘不可达。 */
  function moveTabSelection(event) {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const index = dom.panelTabs.findIndex(({ id }) => id === state.tab);
    const next = dom.panelTabs[(index + step + dom.panelTabs.length) % dom.panelTabs.length];
    if (!next) return;
    selectTab(next.id);
    next.tab?.focus();
  }

  dom.actionsButton.addEventListener("click", () => {
    if (dom.actionsButton.disabled) return;
    const open = dom.actionsPanel.hidden;
    setActionsOpen(open);
    if (open) [dom.collectCopyButton, dom.addTopicButton, dom.deleteButton].find((button) => button && !button.disabled)?.focus();
  });
  // WebKit does not focus buttons on pointer activation. Keep focus within
  // the menu until click dispatch, rather than closing it between down/up.
  dom.actionsControl.addEventListener("pointerdown", (event) => {
    const button = event.target.closest?.("button");
    if (event.button !== 0 || !button || button.disabled || !dom.actionsControl.contains(button)) return;
    event.preventDefault();
    button.focus({ preventScroll: true });
  });
  dom.actionsControl.addEventListener("focusout", () => {
    window.setTimeout(() => {
      if (!dom.actionsControl.contains(document.activeElement)) setActionsOpen(false);
    }, 0);
  });
  document.addEventListener("pointerdown", (event) => {
    if (!dom.actionsControl.contains(event.target)) setActionsOpen(false);
  });
  dom.form.addEventListener("submit", submitBreakdown);
  dom.newButton.addEventListener("click", () => showNewForm({ resetLink: true }));
  dom.taskNewButton.addEventListener("click", () => showNewForm({ resetLink: true }));
  dom.clearButton.addEventListener("click", () => {
    dom.shareInput.value = "";
    clearMedia();
    setFormMessage("");
    renderFeeCap();
    dom.shareInput.focus();
  });
  dom.chooseMediaButton.addEventListener("click", chooseMedia);
  dom.mediaInput.addEventListener("change", () => {
    const file = dom.mediaInput.files?.[0];
    if (file) uploadMedia(file);
  });
  /* 手输链接即视为改用链接来源：把本地素材让开，避免两种来源同时提交。 */
  dom.shareInput.addEventListener("input", () => {
    if (dom.shareInput.value.trim() && state.media.id) clearMedia();
    renderFeeCap();
  });
  dom.pasteButton.addEventListener("click", async () => {
    try {
      dom.shareInput.value = await navigator.clipboard.readText();
      setFormMessage("");
      renderFeeCap();
      showToast("已从剪贴板粘贴", "success");
    } catch (_error) {
      setFormMessage("浏览器未允许读取剪贴板，请手动粘贴", "error");
      dom.shareInput.focus();
    }
  });
  /* 重新拆解就地重跑同一条任务：复用已保存的解析结果与本地素材，不重复解析。
     没有可重试的记录（例如任务文件已丢失）时才退回新建表单。 */
  dom.retryButton.addEventListener("click", () => {
    if (state.activeId) retryBreakdown(state.activeId);
    else showNewForm();
  });
  document.getElementById("breakdownFailedDelete").addEventListener("click", () => {
    if (state.activeId) askDelete({ id: state.activeId, title: state.record?.title });
  });
  /* 删除针对当前打开的那条记录；列表还没读回来时用当前记录兜住，避免点了没反应。 */
  dom.deleteButton.addEventListener("click", () => {
    if (!state.activeId || state.pendingRecordId || state.deletingId) return;
    if (state.deleteArmedFor !== state.activeId) {
      state.deleteArmedFor = state.activeId;
      renderDeleteControl();
      return;
    }
    confirmDelete(state.activeId);
  });
  dom.analyzeButton.addEventListener("click", analyze);
  dom.collectCopyButton?.addEventListener("click", collectReferenceCopy);
  document.getElementById("breakdownCopyTranscript")?.addEventListener("click", async () => {
    const text = String(state.task?.transcript || state.segments.map(item => item.text).join("\n"));
    if (!text) return showToast("暂无可复制的文案", "info");
    try { await navigator.clipboard.writeText(text); showToast("全文已复制", "success"); }
    catch (_) { showToast("复制失败，请选择文案手动复制", "error"); }
  });
  document.getElementById("breakdownDownloadSrt")?.addEventListener("click", () => {
    if (!state.segments.length) return;
    const stamp = value => {
      const total = Math.round(Math.max(0, Number(value) || 0) * 1000);
      return `${String(Math.floor(total / 3600000)).padStart(2,"0")}:${String(Math.floor(total / 60000) % 60).padStart(2,"0")}:${String(Math.floor(total / 1000) % 60).padStart(2,"0")},${String(total % 1000).padStart(3,"0")}`;
    };
    const text = state.segments.map((item, index) => `${index + 1}\n${stamp(item.start)} --> ${stamp(item.end)}\n${item.text}`).join("\n\n");
    const url = URL.createObjectURL(new Blob([text], {type:"text/plain;charset=utf-8"}));
    const link = el("a"); link.href = url; link.download = "视频文案.srt"; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  dom.addTopicButton.addEventListener("click", openTopicModal);
  dom.panelTabs.forEach(({ id, tab }) => tab?.addEventListener("click", () => selectTab(id)));
  dom.panelTabsList?.addEventListener("keydown", moveTabSelection);
  dom.topicCancel.addEventListener("click", () => closeTopicModal(true));
  dom.topicConfirm.addEventListener("click", confirmTopic);
  dom.deleteCancel.addEventListener("click", () => closeDeleteModal(true));
  dom.deleteConfirm.addEventListener("click", () => confirmDelete());
  dom.playbackToggle.addEventListener("click", togglePlayback);
  // Native controls own pointer play/pause, seeking and volume.
  dom.video.addEventListener("play", () => { renderPlaybackControl(); startPlaybackSync(); });
  dom.video.addEventListener("pause", () => { renderPlaybackControl(); cancelPlaybackSync(); });
  dom.video.addEventListener("ended", () => { renderPlaybackControl(); cancelPlaybackSync(); });
  dom.video.addEventListener("loadedmetadata", () => { if (!dom.result.hidden) setActiveTime(dom.video.currentTime || 0); });
  // timeupdate still backs the animation clock up whenever the browser throttles
  // frames (background tab, a paused timeline that was just seeked).
  dom.video.addEventListener("timeupdate", () => {
    if (!trackDragging && !trackSeekPending) setActiveTime(dom.video.currentTime);
  });
  // Seeking is asynchronous: hold the playhead on the drag target until the video
  // actually reports that time, otherwise the playhead snaps back mid-drag.
  dom.video.addEventListener("seeked", () => {
    if (!trackSeekPending || trackSeekTarget === null) return;
    if (Math.abs(dom.video.currentTime - trackSeekTarget) > 0.1) return;
    trackSeekPending = false;
    trackSeekTarget = null;
  });
  dom.track.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    trackDragging = true;
    dom.track.setPointerCapture?.(event.pointerId);
    updateTimeFromPointer(event);
    const move = (moveEvent) => {
      if (moveEvent.pointerId === event.pointerId) updateTimeFromPointer(moveEvent);
    };
    const release = (releaseEvent) => {
      if (releaseEvent.pointerId !== event.pointerId) return;
      const targetTime = updateTimeFromPointer(releaseEvent, { seekVideo: false });
      trackDragging = false;
      trackSeekPending = true;
      trackSeekTarget = targetTime;
      setActiveTime(targetTime, { seekVideo: true, scrollSegment: true });
      dom.track.releasePointerCapture?.(event.pointerId);
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", release);
      document.removeEventListener("pointercancel", release);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", release);
    document.addEventListener("pointercancel", release);
  });
  document.addEventListener("keydown", (event) => {
    if (event.code === "Space") {
      if (dom.actionsControl.contains(event.target)) return;
      const isCaption = event.target?.classList?.contains("split-caption");
      if (event.target === dom.video || (!isCaption && event.target?.matches?.("button, a, input, select, textarea"))) return;
      // Space plays and pauses the reference video, the same shortcut the old 拆片
      // workbench offered. It stays out of dialogs and text fields so typing a
      // 选题 keeps its spaces.
      if (root.hidden || dom.result.hidden || dom.video.hidden || !dom.video.src) return;
      if (!dom.topicModal.hidden || !dom.deleteModal.hidden) return;
      if (isTextEditingTarget(event.target)) return;
      event.preventDefault();
      if (event.repeat) return;
      if (document.activeElement === dom.workbench) dom.workbench.blur();
      togglePlayback();
      return;
    }
    if (event.key !== "Escape") return;
    if (!dom.actionsPanel.hidden) { event.preventDefault(); setActionsOpen(false, true); return; }
    if (!dom.topicModal.hidden) { event.preventDefault(); closeTopicModal(true); return; }
    if (!dom.deleteModal.hidden) { event.preventDefault(); closeDeleteModal(true); }
  });
  document.addEventListener("pointerdown", (event) => {
    if (!dom.topicModal.hidden && event.target === dom.topicModal) closeTopicModal(true);
    if (!dom.deleteModal.hidden && event.target === dom.deleteModal) closeDeleteModal(true);
  });
  window.addEventListener("resize", () => {
    if (dom.result.hidden) return;
    syncVideoColumnSize();
    setActiveTime(dom.video.currentTime || 0);
  });
  if (typeof window.ResizeObserver === "function") {
    const observer = new window.ResizeObserver(() => {
      if (dom.result.hidden) return;
      syncVideoColumnSize();
      setActiveTime(dom.video.currentTime || 0);
    });
    observer.observe(dom.workbench);
    observer.observe(dom.track);
  }

  /* ------------------------------------------------------- 工作台联动 */

  function onAccountChange(accountId) {
    const next = String(accountId || "");
    if (next === state.accountId) return;
    window.BreakdownRewrite?.close();
    stopPolling();
    authorRequestVersion += 1;
    authorStatus = null;
    authorActionsNode = null;
    state.accountId = next;
    state.items = [];
    state.activeId = "";
    state.record = null;
    state.task = null;
    state.segments = [];
    state.duration = 0;
    state.requestVersion += 1;
    dom.shareInput.value = "";
    clearMedia();
    state.feeCap = null;
    setFormMessage("");
    showNewForm();
    if (next) loadList();
  }

  window.addEventListener("workspace-module-change", (event) => {
    const isBreakdown = event?.detail?.module === "split";
    if (!isBreakdown) {
      window.closeWritingAssetDraft?.();
      window.BreakdownRewrite?.close();
      setActionsOpen(false);
      dom.video.pause();
      cancelPlaybackSync();
      stopPolling();
      return;
    }
    // The 拆解视频 module was display:none, so its workbench could not be measured
    // until now; the video column is sized on the first visible frame.
    window.requestAnimationFrame(syncVideoColumnSize);
    if (state.accountId && !state.items.length) loadList();
    if (state.activeId) refreshRecord().catch(() => {});
    if (!state.activeId && !state.pendingRecordId) showNewForm();
  });

  dom.rewriteButton?.addEventListener("click", () => {
    if (dom.rewriteButton.disabled) return;
    const accountId = state.accountId, recordId = state.activeId;
    window.BreakdownRewrite?.open({ accountId, recordId,
      isCurrent: () => state.accountId === accountId && state.activeId === recordId && !state.pendingRecordId,
    });
  });

  window.breakdownModule = {
    onAccountChange,
    // 监控页的「拆解视频」把作品链接交给现有拆解流程，不另复制一套下载和转写。
    start: (shareText, title = "") => {
      const text = String(shareText || "").trim();
      if (!text) return Promise.resolve(null);
      if (state.busy) return Promise.resolve(null);
      showNewForm();
      dom.shareInput.value = text;
      return submitBreakdown(undefined, String(title || "").trim());
    },
  };
  state.accountId = "";
  render();
})();
