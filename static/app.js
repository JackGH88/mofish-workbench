// Business navigation stays gated until the account list is known.
window.workspaceAccountState = "loading";
// 新建脚本 only hosts 直接创建 now; 链接仿写 moved to the standalone 拆解视频 module.
const form = document.querySelector("#downloadForm");
const toast = document.querySelector("#toast");
const newTaskButton = document.querySelector("#newTaskButton");
const accountList = document.querySelector("#accountList");
const scriptList = document.querySelector("#historyList");
const scriptListSubtitle = document.querySelector("#scriptListSubtitle");
const accountSidebar = document.querySelector("#accountSidebar");
const scriptSidebar = document.querySelector("#scriptSidebar");
const toggleAccountSidebarButton = document.querySelector("#toggleAccountSidebar");
const newAccountButton = document.querySelector("#newAccountButton");
const accountDeleteModal = document.querySelector("#accountDeleteModal");
const accountDeleteModalDescription = document.querySelector("#accountDeleteModalDescription");
const cancelAccountDeleteButton = document.querySelector("#cancelAccountDeleteButton");
const confirmAccountDeleteButton = document.querySelector("#confirmAccountDeleteButton");
const accountEditModal = document.querySelector("#accountEditModal");
const accountEditNameInput = document.querySelector("#accountEditNameInput");
const cancelAccountEditButton = document.querySelector("#cancelAccountEditButton");
const saveAccountEditButton = document.querySelector("#saveAccountEditButton");
const newScriptButton = document.querySelector("#newScriptButton");
const workspaceContent = document.querySelector("#workspaceContent");
const workspaceStageHeader = document.querySelector("#workspaceStageHeader");
const workspaceEmpty = document.querySelector("#workspaceEmpty");
const workspaceEmptyTitle = document.querySelector("#workspaceEmptyTitle");
const workspaceEmptyHint = document.querySelector("#workspaceEmptyHint");
const workspaceEmptyCreateButton = document.querySelector("#workspaceEmptyCreateButton");
const workspaceLoading = document.querySelector("#workspaceLoading");
const taskWorkspace = document.querySelector("#taskWorkspace");
const taskStatusBar = document.querySelector("#taskStatusBar");
const taskStatusTitle = document.querySelector("#taskStatusTitle");
const taskStatusDescription = document.querySelector("#taskStatusDescription");
const taskStatusText = document.querySelector("#taskStatusText");
const taskStatusActions = document.querySelector("#taskStatusActions");
const retryTaskButton = document.querySelector("#retryTaskButton");
const deleteTaskButton = document.querySelector("#deleteTaskButton");
const editStage = document.querySelector("#rewriteStage");
const rewriteStage = document.querySelector("#rewriteStage");
const splitStage = document.querySelector("#splitStage");
const editStageButton = document.querySelector("#editStageButton");
const editStageSeparator = document.querySelector("#editStageSeparator");
const splitStageButton = document.querySelector("#splitStageButton");
const splitStageSeparator = document.querySelector("#splitStageSeparator");
// 拆片 availability for the retired link-script flow; the tab itself is never shown.
let splitStageReady = false;
const titleStage = document.querySelector("#titleStage");
const titleStageButton = document.querySelector("#titleStageButton");
const coverStage = document.querySelector("#coverStage");
const publishStage = document.querySelector("#publishStage");
const stageNavigator = document.querySelector("#stageNavigator");
const deleteScriptButton = document.querySelector("#deleteScriptButton");
const scriptStatusFilterControl = document.querySelector("#scriptStatusFilterControl");
const scriptStatusFilterButton = document.querySelector("#scriptStatusFilterButton");
const scriptStatusFilterLabel = document.querySelector("#scriptStatusFilterLabel");
const scriptStatusFilterMenu = document.querySelector("#scriptStatusFilterMenu");
const scriptActionsControl = document.querySelector("#scriptActionsControl");
const scriptActionsButton = document.querySelector("#scriptActionsButton");
const scriptActionsPanel = document.querySelector("#scriptActionsPanel");
const scriptWorkflowStatusControl = document.querySelector("#scriptWorkflowStatusControl");
const scriptWorkflowStatusButton = document.querySelector("#scriptWorkflowStatusButton");
const scriptWorkflowStatusLabel = document.querySelector("#scriptWorkflowStatusLabel");
const scriptWorkflowStatusMenu = document.querySelector("#scriptWorkflowStatusMenu");
const scriptMoveControl = document.querySelector("#scriptMoveControl");
const scriptMoveButton = document.querySelector("#scriptMoveButton");
const scriptMoveAccountLabel = document.querySelector("#scriptMoveAccountLabel");
const scriptMoveMenu = document.querySelector("#scriptMoveMenu");
const workspaceTitle = document.querySelector("#workspaceTitle");
const workspaceTitleInput = document.querySelector("#workspaceTitleInput");
const workspaceMeta = document.querySelector("#workspaceMeta");
const rewriteWarning = document.querySelector("#rewriteWarning");
const scriptEditorGrid = document.querySelector(".script-editor-grid");
const sourcePanel = document.querySelector("#sourceTranscript").closest(".script-editor-panel");
const rewritePanelTitle = document.querySelector(".rewrite-editor-panel h4");
const promptModal = document.querySelector("#promptModal");
const promptModalInput = document.querySelector("#promptModalInput");
const rewritePromptTemplateTabs = ["general", "retention", "story"].map((templateId) => document.querySelector(`[data-rewrite-prompt-template="${templateId}"]`));
const cancelPromptButton = document.querySelector("#cancelPromptButton");
const savePromptButton = document.querySelector("#savePromptButton");
const titlePromptModal = document.querySelector("#titlePromptModal");
const titlePromptModalInput = document.querySelector("#titlePromptModalInput");
const cancelTitlePromptButton = document.querySelector("#cancelTitlePromptButton");
const saveTitlePromptButton = document.querySelector("#saveTitlePromptButton");
const generateRewritesButton = document.querySelector("#generateRewritesButton");
const sourceTranscript = document.querySelector("#sourceTranscript");
const rewriteDraft = document.querySelector("#rewriteDraft");
const scrollSyncButton = document.querySelector("#scrollSyncButton");
const saveRewriteDraftStatus = document.querySelector("#saveRewriteDraftStatus");
const splitWorkbench = document.querySelector("#splitWorkbench");
const splitVideoPanel = document.querySelector("#splitVideoPanel");
const splitTranscriptPanel = document.querySelector("#splitTranscriptPanel");
const splitVideo = document.querySelector("#splitVideo");
const splitPlaybackToggle = document.querySelector("#splitPlaybackToggle");
const splitFullscreenToggle = document.querySelector("#splitFullscreenToggle");
const splitVideoDuration = document.querySelector("#splitVideoPanel .duration");
const splitTranscript = document.querySelector("#splitTranscript");
const splitTrack = document.querySelector("#splitTrack");
const splitTrackClock = document.querySelector("#splitTrack .clock");
const splitTrackTicks = document.querySelector("#splitTrack .ticks");
const splitWaveform = document.querySelector("#splitWaveform");
const splitPlayhead = document.querySelector("#splitPlayhead");
const splitPlayheadLabel = document.querySelector("#splitPlayhead span");
const toggleSplitVideo = document.querySelector("#toggleSplitVideo");
const toggleSplitTranscript = document.querySelector("#toggleSplitTranscript");
const splitTranscriptMeta = document.querySelector("#splitTranscriptMeta");
const splitPanelTabs = [
  { id: "transcript", tab: document.querySelector("#splitTranscriptTab") },
  { id: "structure", tab: document.querySelector("#splitStructureTab") },
];
const splitStructureActions = document.querySelector("#splitStructureActions");
const splitStructureBody = document.querySelector("#splitStructureBody");
const splitStructureEmpty = document.querySelector("#splitStructureEmpty");
const splitStructurePromptButton = document.querySelector("#splitStructurePromptButton");
const splitStructureMemoryButton = document.querySelector("#splitStructureMemoryButton");
const splitStructureGenerateButton = document.querySelector("#splitStructureGenerateButton");
const writeStage = document.querySelector("#writeStage");
const writeStageButton = document.querySelector("#writeStageButton");
const writeStageSeparator = document.querySelector("#writeStageSeparator");
const writeWorkbench = document.querySelector("#writeWorkbench");
const writeWorkbenchControls = document.querySelector("#writeWorkbenchControls");
const toggleWriteStructure = document.querySelector("#toggleWriteStructure");
const toggleWriteContent = document.querySelector("#toggleWriteContent");
const writeStructurePanel = document.querySelector("#writeStructurePanel");
const writeStructure = document.querySelector("#writeStructure");
const writeStructureEmpty = document.querySelector("#writeStructureEmpty");
const writeStructureMemoryButton = document.querySelector("#writeStructureMemoryButton");
const writeStructureGenerateButton = document.querySelector("#writeStructureGenerateButton");
const writeContentPanel = document.querySelector("#writeContentPanel");
const writeContentDraft = document.querySelector("#writeContentDraft");
const writeContentGenerating = document.querySelector("#writeContentGenerating");
const writeContentSaveState = document.querySelector("#writeContentSaveState");
const writeContentMemoryButton = document.querySelector("#writeContentMemoryButton");
const writeContentGenerateButton = document.querySelector("#writeContentGenerateButton");
const writeContentAgentButton = document.querySelector("#writeContentAgentButton");
const writeReferenceCopiesButton = document.querySelector("#writeReferenceCopiesButton");
const writeReferenceCopiesModal = document.querySelector("#writeReferenceCopiesModal");
const writeReferenceCopiesList = document.querySelector("#writeReferenceCopiesList");
const writeReferenceCopiesEmpty = document.querySelector("#writeReferenceCopiesEmpty");
const writeReferenceCopiesError = document.querySelector("#writeReferenceCopiesError");
const writeReferenceCopiesCancel = document.querySelector("#writeReferenceCopiesCancel");
const writeReferenceCopiesSave = document.querySelector("#writeReferenceCopiesSave");
const writePromptModal = document.querySelector("#writePromptModal");
const writePromptModalTitle = document.querySelector("#writePromptModalTitle");
const writePromptModalFieldLabel = document.querySelector("#writePromptModalFieldLabel");
const writePromptModalInput = document.querySelector("#writePromptModalInput");
const writePromptContextList = document.querySelector("#writePromptContextList");
const writePromptAntiSimilarityRow = document.querySelector("#writePromptAntiSimilarityRow");
const writePromptAntiSimilarityInput = document.querySelector("#writePromptAntiSimilarityInput");
const writeStructurePromptButton = document.querySelector("#writeStructurePromptButton");
const writeContentPromptButton = document.querySelector("#writeContentPromptButton");
const cancelWritePromptButton = document.querySelector("#cancelWritePromptButton");
const saveWritePromptButton = document.querySelector("#saveWritePromptButton");
const accountCreateModal = document.querySelector("#accountCreateModal");
const accountNameInput = document.querySelector("#accountNameInput");
const cancelAccountCreateButton = document.querySelector("#cancelAccountCreateButton");
const saveAccountCreateButton = document.querySelector("#saveAccountCreateButton");
const titlePromptSettingsButton = document.querySelector("#titlePromptSettingsButton");
const titleGenerateButton = document.querySelector("#titleGenerateButton");
const titleGenerationHint = document.querySelector("#titleGenerationHint");
const titleSourceDetails = document.querySelector("#titleSourceDetails");
const titleSourceName = document.querySelector("#titleSourceName");
const titleSourceTopics = document.querySelector("#titleSourceTopics");
const titleCandidateLists = {
  douyin: document.querySelector("#douyinTitleCandidateList"),
  channels: document.querySelector("#channelsTitleCandidateList"),
};
const titlePlatformGroups = {
  douyin: document.querySelector("#douyinTitleGroup"),
  channels: document.querySelector("#channelsTitleGroup"),
};
const publishDraftEditors = {
  douyin: {
    main: document.querySelector("#publishDouyinTitleInput"),
    count: document.querySelector("#publishDouyinTitleCount"),
    description: document.querySelector("#publishDouyinDescriptionInput"),
    save: document.querySelector("#saveDouyinPublishDraftButton"),
    restore: document.querySelector("#restoreDouyinSelectedTitleButton"),
  },
  channels: {
    main: document.querySelector("#publishChannelsShortTitleInput"),
    count: document.querySelector("#publishChannelsShortTitleCount"),
    description: document.querySelector("#publishChannelsDescriptionInput"),
    save: document.querySelector("#saveChannelsPublishDraftButton"),
    restore: document.querySelector("#restoreChannelsSelectedTitleButton"),
  },
};
const publishAssetsStatus = document.querySelector("#publishAssetsStatus");
const publishDraftTabs = {
  douyin: document.querySelector("#publishDouyinDraftTab"),
  channels: document.querySelector("#publishChannelsDraftTab"),
};
const publishDraftPanels = {
  douyin: document.querySelector("#publishDouyinDraftPanel"),
  channels: document.querySelector("#publishChannelsDraftPanel"),
};
const PUBLISH_DROP_FILE_RULES = {
  video: {
    label: "视频",
    extensions: [".mp4", ".mov", ".m4v", ".webm"],
    mimeTypes: {
      ".mp4": ["video/mp4"],
      ".mov": ["video/quicktime"],
      ".m4v": ["video/x-m4v", "video/mp4"],
      ".webm": ["video/webm"],
    },
  },
  image: {
    label: "图片",
    extensions: [".png", ".jpg", ".jpeg", ".webp"],
    mimeTypes: {
      ".png": ["image/png"],
      ".jpg": ["image/jpeg", "image/jpg"],
      ".jpeg": ["image/jpeg", "image/jpg"],
      ".webp": ["image/webp"],
    },
  },
};
const publishVideoInput = document.querySelector("#publishVideoInput");
const publishVideoDropZone = document.querySelector("#publishVideoDropZone");
const publishVideoStatus = document.querySelector("#publishVideoStatus");
const publishPortraitCoverInput = document.querySelector("#publishPortraitCoverInput");
const publishPortraitCoverDropZone = document.querySelector("#publishPortraitCoverDropZone");
const publishPortraitCoverStatus = document.querySelector("#publishPortraitCoverStatus");
const publishLandscapeCoverInput = document.querySelector("#publishLandscapeCoverInput");
const publishLandscapeCoverDropZone = document.querySelector("#publishLandscapeCoverDropZone");
const publishLandscapeCoverStatus = document.querySelector("#publishLandscapeCoverStatus");
const publishPlatformControls = {
  douyin: {
    status: document.querySelector("#douyinPublishStatus"),
    fill: document.querySelector("#startDouyinPublishFillButton"),
    taskStatus: document.querySelector("#douyinPublishTaskStatus"),
  },
  channels: {
    status: document.querySelector("#channelsPublishStatus"),
    fill: document.querySelector("#startChannelsPublishFillButton"),
    taskStatus: document.querySelector("#channelsPublishTaskStatus"),
  },
};
const coverPromptInput = document.querySelector("#coverPromptInput");
const coverReferencePicker = document.querySelector("#coverReferencePicker");
const coverSaveTemplateButton = document.querySelector("#coverSaveTemplateButton");
const coverTitleGenerateButton = document.querySelector("#coverTitleGenerateButton");
const coverGenerateButton = document.querySelector("#coverGenerateButton");
const coverResultList = document.querySelector("#coverResultList");
const coverResultsRegion = document.querySelector("#coverResultsRegion");
const coverGenerationStatus = document.querySelector("#coverGenerationStatus");
const coverUploadArea = document.querySelector("#coverUploadArea");
const coverUploadPreview = document.querySelector("#coverUploadPreview");
const coverUploadPreviewImage = document.querySelector("#coverUploadPreviewImage");
const coverUploadLabel = document.querySelector("#coverUploadLabel");
const coverUploadRemove = document.querySelector("#coverUploadRemove");
const coverUploadThumbs = document.querySelector("#coverUploadThumbs");
const coverFileInput = document.querySelector("#coverFileInput");
const coverMentionPopup = document.querySelector("#coverMentionPopup");
const coverMentionList = document.querySelector("#coverMentionList");
const coverRatioControl = document.querySelector("#coverRatioControl");
const coverRatioButton = document.querySelector("#coverRatioButton");
const coverRatioLabel = document.querySelector("#coverRatioLabel");
const coverRatioMenu = document.querySelector("#coverRatioMenu");
const coverTemplateModal = document.querySelector("#coverTemplateModal");
const coverTemplateGrid = document.querySelector("#coverTemplateGrid");
const coverTemplateNameModal = document.querySelector("#coverTemplateNameModal");
const coverTemplateNameInput = document.querySelector("#coverTemplateNameInput");
const cancelCoverTemplateSaveButton = document.querySelector("#cancelCoverTemplateSaveButton");
const confirmCoverTemplateSaveButton = document.querySelector("#confirmCoverTemplateSaveButton");
const coverTemplateCloseButton = document.querySelector("#coverTemplateCloseButton");
const coverPromptUsesRichText = coverPromptInput.getAttribute?.("contenteditable") === "true";

const taskStatusPresentations = {
  submitting: { title: "正在创建任务", description: "正在提交分享链接，请稍候。", fallbackMessage: "正在创建任务…" },
  queued: { title: "任务已创建，等待处理", description: "任务已提交，正在等待处理资源。", fallbackMessage: "任务已创建，等待处理。" },
  downloading: { title: "正在下载视频与音频", description: "正在提取视频素材并保存到本地任务目录。", fallbackMessage: "正在下载视频与音频" },
  preparing_audio: { title: "正在准备转写音频", description: "正在确认可用音频，必要时将从视频中提取音轨。", fallbackMessage: "正在准备转写音频" },
  uploading_audio: { title: "正在上传临时音频", description: "正在上传音频文件，以便进行语音转写。", fallbackMessage: "正在上传临时音频" },
  transcribing: { title: "正在转写口播稿", description: "正在将音频内容转为可编辑的原始脚本文案。", fallbackMessage: "正在转写口播稿" },
  rewriting: { title: "正在生成仿写稿", description: "正在根据转写内容生成一份可编辑的仿写脚本。", fallbackMessage: "正在生成仿写稿" },
  complete: { title: "任务处理完成", description: "正在同步脚本工作区，完成后即可编辑。", fallbackMessage: "处理完成" },
  failed: { title: "脚本处理失败", description: "任务未能完成，请根据失败信息检查配置或链接。", fallbackMessage: "处理失败，请检查配置和链接后重试。" },
};

const defaultRewriteSystemPrompt = promptModalInput.value.trim();
const defaultRewritePromptTemplates = [
  { id: "general", name: "通用仿写", systemPrompt: defaultRewriteSystemPrompt },
  { id: "retention", name: "高留存口播", systemPrompt: defaultRewriteSystemPrompt },
  { id: "story", name: "故事化表达", systemPrompt: defaultRewriteSystemPrompt },
];
let activeSystemPrompt = defaultRewriteSystemPrompt;
let rewritePromptTemplates = defaultRewritePromptTemplates.map((template) => ({ ...template }));
let selectedRewritePromptTemplateId = "general";
let promptModalTemplateId = "general";
let rewritePromptRequestVersion = 0;
let accountListRequestVersion = 0;
let rewriteDraftState = "等待保存";
let activeTime = 0;
let splitAnimationFrame = null;
let splitTrackIsDragging = false;
let splitTrackSeekPending = false;
let splitTrackSeekTarget = null;
let splitPanelVisibility = { video: true, transcript: true };
let splitPanelTab = "transcript";
let writePanelVisibility = { structure: true, content: true };
let splitSegments = [];
let splitDuration = 0;
let splitMediaDuration = 0;
let rewriteDraftSaveTimer = null;
let rewriteDraftVersion = 0;
let rewriteDraftDirty = false;
let selectedRewriteModel = "text-default";
let activeRewriteModels = {};
let rewriteModelsPollTimer = null;
let rewriteModelsPollScriptId = "";
let linkRewriteDraftVersion = 0;
let linkRewriteSession = 0;
let splitPendingSourceRestore = null;
let splitCompatibilityPollTimer = null;
let splitCompatibilityPollScriptId = "";
let splitCompatibilityTask = null;
let linkRewriteSaveInFlight = null;
let linkRewriteQueuedSave = null;
let accounts = [];
let scripts = [];
let scriptStatusFilter = "all";
/* The workspace column shows one view at a time: 创作 owns the creation panel, so the
   script column is only ever 空态 / 任务处理 / 编辑 and module switches must keep it. */
let workspaceView = "empty";
let createViewActive = false;
let workspaceEmptyCopy = null;
let activeAccountId = null;
let activeScriptId = null;
let activeTaskId = null;
let activeScript = null;
let pendingScriptId = null;
let scriptSwitchSequence = 0;
let deleteScriptArmedFor = null;
let scriptMoveInFlight = false;
let accountDeleteSummary = null;
let accountDeleteHold = null;
let accountDeleteReveal = null;
let accountDeleteSuppressedClickId = "";
let accountEditId = "";
let workspaceTitleEdit = null;
let linkTaskSubmissionVersion = 0;
const stageRequestVersions = new Map();
let titleState = null;
let titleSource = null;
let titleSourceReady = false;
let titleStateRequestVersion = 0;
let titleGenerationInFlight = false;
let titleGeneration = null;
let titleGenerationPollTimer = null;
let titleMutationKind = "";
let titleMutationVersion = 0;
let titleStateLoading = false;
let titleStateLoadError = "";
let titleStateContext = { accountId: null, scriptId: null };
let writingState = null;
let writingPrompts = { structure: "", content: "" };
let writingAntiSimilarity = { structure: true, content: true };
let writingProfile = null;
let writingMemory = null;
let writingReferenceCopies = [];
let writingReferenceCopyIds = [];
let writingReferenceCopyDraft = [];
let writingSourceReady = false;
let writingStateRequestVersion = 0;
let writingStateLoading = false;
let writingStateLoadError = "";
let writingGeneration = null;
let writingGenerationInFlight = false;
let writingGenerationNode = "";
let writingGenerationPollTimer = null;
let writingPromptNode = "";
let writingPromptSaveMode = "generate";
let writingContext = { accountId: null, scriptId: null };
let writeContentSaveTimer = null;
let writeContentSaveSession = 0;
let writeContentSaveInFlight = false;
let writeContentSavePromise = null;
let writingAgentOpening = false;
let writeContentSaveQueued = false;
let writeContentDirty = false;
let writeContentSaveStatus = "已保存";
let structureDraft = null;
let structureSaveTimer = null;
let structureSaveSession = 0;
let structureSavePromise = null;
const titleCandidateFocusIds = new Map();
const publishDraftBuffers = new Map();
const publishSaveTimers = new Map();
const publishSaveJobs = new Map();
const publishSaveErrors = new Map();
const publishCheckJobs = new Map();
const publishLoginCache = new Map();
const publishLoginVersions = new Map();
const publishLoginReturnChecks = new Set();
const PUBLISH_LOGIN_FRESH_MS = 10 * 60 * 1000;
function publishLoginKey(platform, accountId = activeAccountId) { return `${accountId}:${platform}`; }
function cachedPublishLogin(platform, accountId = activeAccountId) {
  const cached = publishLoginCache.get(publishLoginKey(platform, accountId));
  if (!cached) return null;
  if (["logged_in", "login_required"].includes(cached.status) && Date.now() - cached.checkedAt >= PUBLISH_LOGIN_FRESH_MS) {
    return { ...cached, status: "stale", message: "登录状态待确认" };
  }
  return cached;
}
function rememberPublishLogin(platform, payload, accountId = activeAccountId) {
  const key = publishLoginKey(platform, accountId);
  publishLoginVersions.set(key, (publishLoginVersions.get(key) || 0) + 1);
  if (payload.status !== "login_opened") publishLoginReturnChecks.delete(key);
  const result = { ...payload, platform, checkedAt: Date.now() };
  publishLoginCache.set(publishLoginKey(platform, accountId), result);
  if (activeAccountId === accountId) {
    publishStatuses[platform] = result;
    renderPublishAutomation();
  }
  return result;
}
function ensurePublishLogin(platform) {
  const pending = publishCheckJobs.get(publishLoginKey(platform));
  if (pending) {
    publishStatuses[platform] = { platform, status: "checking" };
    renderPublishAutomation();
    return pending;
  }
  const cached = cachedPublishLogin(platform);
  if (cached) {
    publishStatuses[platform] = cached;
    renderPublishAutomation();
    return Promise.resolve(cached);
  }
  return checkPublishStatus(platform);
}
const publishPreparing = new Set();

function publishBusy(platform) {
  return publishPreparing.has(publishDraftBufferKey(platform)) || ["submitting", "queued", "running"].includes(publishTasks[platform]?.status);
}
function publishAssetsLocked() { return titlePlatforms.some(publishBusy); }
function publishDraftValidation(platform, buffer) {
  const limit = platform === "channels" ? 16 : 30;
  return {
    main: !(buffer?.main || "").trim() ? "请填写标题" : [...buffer.main.trim()].length > limit ? `标题不能超过 ${limit} 字` : "",
    description: platform === "channels" && !splitPublishDescription(buffer?.description || "").description.trim() ? "请填写视频描述" : [...(buffer?.description || "")].length > 2000 ? "描述不能超过 2000 字" : "",
  };
}
function schedulePublishSave(platform) {
  const key = publishDraftBufferKey(platform);
  clearTimeout(publishSaveTimers.get(key));
  publishSaveTimers.set(key, setTimeout(() => {
    publishSaveTimers.delete(key);
    if (key === publishDraftBufferKey(platform)) void savePublishDraft(platform);
  }, 800));
}
function hasPendingPublishDrafts() {
  return titlePlatforms.some(platform => { const key = publishDraftBufferKey(platform); return publishDraftBuffers.get(key)?.dirty || publishSaveJobs.has(key); });
}
async function flushPublishDrafts() {
  for (const platform of titlePlatforms) {
    const key = publishDraftBufferKey(platform);
    if ((publishDraftBuffers.get(key)?.dirty || publishSaveJobs.has(key)) && !await savePublishDraft(platform)) {
      showToast("文案尚未保存，请重试保存后再切换。", "error");
      return false;
    }
  }
  return true;
}
let publishAssets = null;
/* Which platform's 文案 is showing. Both panels stay rendered; only one is visible. */
let publishDraftPlatform = "douyin";
let publishNavigationSnapshot = null;
let publishContextVersion = 0;
let publishAssetMutationVersion = 0;
const publishStatuses = { douyin: null, channels: null };
const publishTasks = { douyin: null, channels: null };
const publishTaskVersions = { douyin: 0, channels: 0 };
let isScrollSyncLocked = true;
let scrollSyncTarget = null;
let accountSidebarContentRevealCleanup = null;
let workspaceSwitchVersion = 0;
const workspaceActiveSelectionStorageKey = "workspaceActiveSelection.v1";
const coverRatioLabels = { portrait: "生成3:4", landscape: "生成4:3", both: "同时生成" };
const coverAspectOrder = { "3:4": 0, "4:3": 1 };
const COVER_REFERENCE_MAX = 5;
const retiredCoverTemplateIds = new Set(["clean", "product", "story"]);
let coverTemplateSequence = 0;
let coverTemplateArmedDeleteId = "";
let coverTemplateDeleteArmTimer = null;
let coverStateSyncTimer = null;
let coverGeneration = null;
let coverGenerationPollTimer = null;
let coverGenerationRequestSequence = 0;
let coverTitleGenerationVersion = 0;
let coverTitleGenerationInFlight = false;
let coverTitleGenerationPhase = "title";
let coverGenerationPollFailures = 0;
let titleGenerationPollFailures = 0;
let writingGenerationPollFailures = 0;
let splitCompatibilityPollFailures = 0;
let rewriteModelsPollFailures = 0;

// Durable-state pollers share one policy so a running job cannot keep the tab
// busy: a per-poller base delay, exponential backoff when the API is failing,
// and a full pause while the tab sits in the background.
const POLL_BACKOFF_CAP_MS = 8000;

function pollDelayFor(baseDelay, failureCount = 0) {
  if (!failureCount) return baseDelay;
  return Math.min(baseDelay * (2 ** Math.min(failureCount, 4)), POLL_BACKOFF_CAP_MS);
}

function documentIsHidden() {
  if (typeof document === "undefined" || document === null) return false;
  if (typeof document.visibilityState === "string") return document.visibilityState === "hidden";
  return document.hidden === true;
}

// Pollers that are parked while the tab is hidden, keyed by a stable id so a
// repeated resume cannot stack duplicate background callbacks.
const parkedPolls = new Map();
let visibilityListenerAttached = false;

function ensureVisibilityListener() {
  if (visibilityListenerAttached) return;
  visibilityListenerAttached = true;
  document.addEventListener?.("visibilitychange", () => {
    if (documentIsHidden()) return;
    const callbacks = [...parkedPolls.values()];
    parkedPolls.clear();
    callbacks.forEach((callback) => callback());
  });
}

// Returns the timeout id, or null when the tab is hidden and the callback waits
// for the tab to come back instead of issuing a background request.
function schedulePoll(key, callback, delay) {
  parkedPolls.delete(key);
  if (!documentIsHidden()) return window.setTimeout(callback, delay);
  parkedPolls.set(key, callback);
  ensureVisibilityListener();
  return null;
}

function cancelPoll(key, timerId) {
  parkedPolls.delete(key);
  if (timerId !== null && timerId !== undefined) window.clearTimeout(timerId);
  return null;
}

// Promise-style pollers (a loop that awaits between attempts) pause the same
// way: hidden tabs wait for the next visibilitychange instead of polling.
async function waitForPollDelay(delay) {
  if (!documentIsHidden()) {
    await new Promise((resolve) => window.setTimeout(resolve, delay));
    return;
  }
  await new Promise((resolve) => {
    const resume = () => {
      document.removeEventListener?.("visibilitychange", resume);
      resolve();
    };
    document.addEventListener?.("visibilitychange", resume);
  });
}
const coverDemo = {
  prompt: "",
  reference: "",
  referenceLabel: "",
  uploadedImages: [],
  activeImageId: "",
  results: [],
  pendingJobs: [],
  ratio: "both",
  selectedResult: "",
  phase: "idle",
  generationVersion: 0,
  generatedReference: "",
  templates: [],
};
const coverMentionState = { atIndex: -1, caret: 0, matches: [], selectedIndex: 0, target: null };
const coverMentionTargets = {
  cover: {
    input: coverPromptInput,
    popup: coverMentionPopup,
    list: coverMentionList,
    images: () => coverDemo.uploadedImages,
    richText: true,
  },
};
const coverMentionTokenPattern = /@([^\n]+?)（第(\d+)张参考图）[^\S\n]*/g;
const coverPromptBlockTags = new Set(["div", "p", "li"]);

function coverPromptNodeContains(node, target) {
  return node === target || [...(node?.childNodes || [])].some((child) => coverPromptNodeContains(child, target));
}

function coverPromptNodeText(node, endContainer = null, endOffset = 0) {
  const children = [...(node?.childNodes || [])];
  if (!children.length) {
    const value = node?.textContent || "";
    return node === endContainer ? value.slice(0, endOffset) : value;
  }
  let value = "";
  const childLimit = node === endContainer ? Math.min(endOffset, children.length) : children.length;
  for (const child of children.slice(0, childLimit)) {
    const tag = String(child.tagName || "").toLowerCase();
    if (coverPromptBlockTags.has(tag) && value && !value.endsWith("\n")) value += "\n";
    if (child.nodeType === 3) value += coverPromptNodeText(child, endContainer, endOffset);
    else if (tag === "br") value += "\n";
    else value += coverPromptNodeText(child, endContainer, endOffset);
    if (coverPromptNodeContains(child, endContainer)) break;
  }
  return value;
}

function coverPromptText() {
  if (!coverPromptUsesRichText) return coverPromptInput.value;
  if (typeof window.getSelection !== "function" && typeof coverPromptInput.__coverPromptText === "string") {
    return coverPromptInput.__coverPromptText;
  }
  return coverPromptNodeText(coverPromptInput);
}

function createCoverPromptTextNode(value) {
  if (typeof document.createTextNode === "function") return document.createTextNode(value);
  const node = document.createElement("span");
  node.textContent = value;
  return node;
}

function setCoverPromptText(value, caret = null) {
  if (!coverPromptUsesRichText) {
    coverPromptInput.value = value;
    return;
  }
  const nodes = [];
  let cursor = 0;
  coverMentionTokenPattern.lastIndex = 0;
  for (let match = coverMentionTokenPattern.exec(value); match; match = coverMentionTokenPattern.exec(value)) {
    if (match.index > cursor) nodes.push(createCoverPromptTextNode(value.slice(cursor, match.index)));
    const token = document.createElement("span");
    token.className = "cover-mention-token";
    token.setAttribute("contenteditable", "false");
    token.dataset.coverMentionToken = "true";
    token.textContent = match[0];
    nodes.push(token);
    cursor = match.index + match[0].length;
  }
  if (cursor < value.length) nodes.push(createCoverPromptTextNode(value.slice(cursor)));
  coverPromptInput.replaceChildren(...nodes);
  coverPromptInput.__coverPromptText = value;
  coverPromptInput.value = value;
  if (caret !== null) setCoverPromptCaret(caret);
}

function coverPromptCaret() {
  if (!coverPromptUsesRichText || typeof window.getSelection !== "function") return coverPromptText().length;
  const selection = window.getSelection();
  if (!selection?.rangeCount) return coverPromptText().length;
  const range = selection.getRangeAt(0);
  if (!coverPromptInput.contains(range.startContainer)) return coverPromptText().length;
  return coverPromptNodeText(coverPromptInput, range.startContainer, range.startOffset).length;
}

function setCoverPromptCaret(offset) {
  if (!coverPromptUsesRichText || typeof window.getSelection !== "function" || typeof document.createRange !== "function") return;
  const range = document.createRange();
  const selection = window.getSelection();
  let remaining = offset;
  const nodes = [...coverPromptInput.childNodes];
  for (const node of nodes) {
    const length = node.textContent.length;
    if (remaining > length) {
      remaining -= length;
      continue;
    }
    if (node.classList?.contains("cover-mention-token")) {
      if (remaining === 0) range.setStartBefore(node);
      else range.setStartAfter(node);
    } else {
      range.setStart(node, Math.min(remaining, length));
    }
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
    return;
  }
  range.selectNodeContents(coverPromptInput);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
}

function mentionInputText(target) {
  return target.richText ? coverPromptText() : target.input.value;
}

function mentionInputCaret(target) {
  return target.richText ? coverPromptCaret() : target.input.selectionStart ?? target.input.value.length;
}

const coverTemplatesStorageKey = "coverTemplates.v1";

function legacyCoverTemplates() {
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(coverTemplatesStorageKey) || "null");
  } catch (_error) {
    return [];
  }
  return Array.isArray(saved?.customTemplates) ? saved.customTemplates : [];
}

function coverTemplateMigrationKey(accountId) {
  return `coverTemplatesMigrated.${accountId}.v1`;
}

function coverTemplatePayload(template, legacyId = null) {
  return {
    label: String(template.label || "未命名模板"),
    prompt: String(template.prompt || ""),
    accent: String(template.accent || "linear-gradient(140deg, #bcd3d9, #7d9aa4 58%, #44545c)"),
    images: Array.isArray(template.images)
      ? template.images.filter((image) => image && typeof image.url === "string").map(({ id, name, url }) => ({ id: String(id || ""), name: String(name || ""), url }))
      : [],
    ...(legacyId ? { legacyId } : {}),
  };
}

async function coverTemplateRequest(path, options = {}) {
  const response = await fetch(path, options);
  const payload = response.status === 204 ? null : await readJson(response);
  if (!response.ok) throw payload;
  return payload;
}

async function loadCoverTemplatesForAccount(accountId = activeAccountId) {
  if (!accountId) {
    coverDemo.templates = [];
    return [];
  }
  const basePath = `/api/accounts/${encodeURIComponent(accountId)}/cover-templates`;
  let payload = await coverTemplateRequest(basePath);
  let items = Array.isArray(payload?.items) ? payload.items : [];
  let alreadyMigrated = false;
  try {
    alreadyMigrated = localStorage.getItem(coverTemplateMigrationKey(accountId)) === "true";
  } catch (_error) {
    alreadyMigrated = true;
  }
  if (!alreadyMigrated) {
    for (const legacy of legacyCoverTemplates()) {
      if (!legacy || typeof legacy !== "object" || !String(legacy.prompt || "").trim()) continue;
      await coverTemplateRequest(basePath, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(coverTemplatePayload(legacy, String(legacy.id || ""))),
      });
    }
    try { localStorage.setItem(coverTemplateMigrationKey(accountId), "true"); } catch (_error) { /* optional migration marker */ }
    payload = await coverTemplateRequest(basePath);
    items = Array.isArray(payload?.items) ? payload.items : [];
  }
  if (activeAccountId === accountId) coverDemo.templates = items;
  return items;
}

function coverScriptStorageKey() {
  return `coverScriptState.${activeScriptId || "__global__"}.v1`;
}

function cacheCoverStateLocally() {
  try {
    localStorage.setItem(coverScriptStorageKey(), JSON.stringify(serializeCoverState()));
  } catch (_error) {
    // Storage is optional: the current session remains usable when it is unavailable.
  }
}

function saveCoverState() {
  cacheCoverStateLocally();
  scheduleCoverStateSync();
}

function serializeCoverState() {
  return {
    prompt: coverDemo.prompt,
    ratio: coverDemo.ratio,
    uploadedImages: coverDemo.uploadedImages.map(({ id, name, url, source, sourceVideoPath, timestamp }) => ({ id, name, url, source, sourceVideoPath, timestamp })),
    results: coverDemo.results,
    pendingJobs: coverDemo.pendingJobs,
    generatedReference: coverDemo.generatedReference,
    activeImageId: coverDemo.activeImageId,
  };
}

function scheduleCoverStateSync() {
  if (!activeScriptId) return;
  window.clearTimeout(coverStateSyncTimer);
  const scriptId = activeScriptId;
  coverStateSyncTimer = window.setTimeout(() => {
    syncCoverStateToServer(scriptId).catch(() => {
      // Server unavailable: the local cache keeps the current session usable.
    });
  }, 500);
}

async function syncCoverStateToServer(scriptId, state = serializeCoverState()) {
  const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/cover-state`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ state }),
  });
  if (!response.ok) throw await response.json();
}

function coverStateHasLocalContent() {
  return Boolean(
    String(coverDemo.prompt || "").trim()
    || coverDemo.ratio !== "both"
    || coverDemo.uploadedImages.length
    || coverDemo.results.length
    || coverDemo.pendingJobs.length
    || coverDemo.generatedReference
    || coverDemo.activeImageId
  );
}

function applyCoverStatePayload(payload, scriptId, generationVersion) {
  if (activeScriptId !== scriptId || generationVersion !== coverDemo.generationVersion) return;
  const wasRunning = coverGeneration?.status === "running";
  const serverState = payload?.state;
  const hasServerState = serverState && typeof serverState === "object" && Object.keys(serverState).length > 0;
  if (hasServerState) {
    applyCoverState(serverState, { renderResults: false });
  }
  applyCoverGeneration(payload?.generation || null);
  renderCoverGenerateControl();
  resumeCoverTitleGenerationPolling(payload?.titleGeneration, scriptId);
  renderCoverResults();
  if (wasRunning && coverGeneration?.status !== "running" && coverDemo.results.length) {
    const failed = coverDemo.results.find((result) => result?.status !== "success");
    if (failed) showToast(failed.message || "部分封面生成失败", "error");
    else showToast("封面生成完成", "success");
  }
  resumeCoverGenerationPolling(scriptId);
  coverGenerationPollFailures = 0;
  // Only seed a truly empty server from meaningful local state. Polling a
  // populated server must remain read-only so an older client snapshot
  // cannot race a just-completed generation result.
  cacheCoverStateLocally();
  if (!hasServerState && coverStateHasLocalContent()) scheduleCoverStateSync();
}

async function fetchCoverStateFromServer(scriptId, generationVersion = coverDemo.generationVersion) {
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/cover-state`);
    const payload = await response.json();
    if (!response.ok) throw payload;
    applyCoverStatePayload(payload, scriptId, generationVersion);
    return true;
  } catch (_error) {
    // Server unavailable: keep the local cache for the current session.
    return false;
  }
}

function resumeCoverTitleGenerationPolling(generation, scriptId = activeScriptId) {
  if (
    coverTitleGenerationInFlight
    || !generation
    || generation.status !== "running"
    || !generation.jobId
    || !scriptId
  ) return;
  const generationVersion = ++coverTitleGenerationVersion;
  coverTitleGenerationInFlight = true;
  renderCoverTitleGenerateControl();
  pollCoverTitleJob(generation.jobId, generationVersion, scriptId)
    .then(() => {
      if (generationVersion === coverTitleGenerationVersion && activeScriptId === scriptId) {
        return fetchCoverStateFromServer(scriptId);
      }
      return null;
    })
    .catch((error) => {
      if (generationVersion === coverTitleGenerationVersion && activeScriptId === scriptId) {
        showToast(responseMessage(error, "封面标题生成已中断，请重试。"), "error");
      }
    })
    .finally(() => {
      if (generationVersion === coverTitleGenerationVersion && activeScriptId === scriptId) {
        coverTitleGenerationInFlight = false;
        renderCoverTitleGenerateControl();
      }
    });
}

function applyCoverGeneration(nextGeneration) {
  coverGeneration = nextGeneration && typeof nextGeneration === "object" ? nextGeneration : null;
  syncCoverPendingJobs();
}

function coverGenerationItems(generation = coverGeneration) {
  return Array.isArray(generation?.aspects) ? generation.aspects.filter((item) => item && typeof item === "object") : [];
}

function coverGenerationItemJobId(item, generation = coverGeneration) {
  return String(item?.jobId || generation?.jobId || "");
}

function syncCoverPendingJobs() {
  coverDemo.pendingJobs = coverGenerationItems()
    .filter((item) => item.status === "pending" || item.status === "submitted")
    .map((item) => ({ aspect: item.aspect, jobId: coverGenerationItemJobId(item) }));
}

function mergeCoverGeneration(nextGeneration, { requestToken = null, optimistic = false } = {}) {
  if (!nextGeneration || typeof nextGeneration !== "object") return;
  const incoming = coverGenerationItems(nextGeneration);
  if (!incoming.length) return;
  const current = coverGenerationItems();
  const merged = [...current];
  for (const item of incoming) {
    const index = merged.findIndex((existing) => existing.aspect === item.aspect);
    const normalized = { ...item, jobId: coverGenerationItemJobId(item, nextGeneration) };
    if (optimistic && requestToken) normalized.requestToken = requestToken;
    if (index >= 0) {
      const existing = merged[index];
      const existingJobId = String(existing?.jobId || "");
      const responseMatchesPlaceholder = requestToken && existing.requestToken === requestToken;
      const responseMatchesJob = !optimistic && normalized.jobId && existingJobId === normalized.jobId;
      if (!optimistic && requestToken && !responseMatchesPlaceholder && !responseMatchesJob) continue;
      merged[index] = normalized;
    }
    else merged.push(normalized);
  }
  coverGeneration = {
    ...(coverGeneration || {}),
    ...nextGeneration,
    jobId: nextGeneration.jobId || coverGeneration?.jobId || "",
    status: merged.some((item) => item.status === "pending" || item.status === "submitted") ? "running" : nextGeneration.status,
    aspects: merged.sort((a, b) => (coverAspectOrder[a.aspect] ?? 9) - (coverAspectOrder[b.aspect] ?? 9)),
  };
  syncCoverPendingJobs();
}

function removeCoverGenerationAspects(aspects, requestToken = null) {
  const removed = new Set(aspects);
  const retained = coverGenerationItems().filter((item) => (
    !removed.has(item.aspect) || (requestToken && item.requestToken !== requestToken)
  ));
  if (!retained.length) {
    applyCoverGeneration(null);
    return;
  }
  coverGeneration = {
    ...coverGeneration,
    status: retained.some((item) => item.status === "pending" || item.status === "submitted") ? "running" : "completed",
    aspects: retained,
  };
  syncCoverPendingJobs();
}

function stopCoverGenerationPolling() {
  coverGenerationPollTimer = cancelPoll("cover-generation", coverGenerationPollTimer);
  coverGenerationPollFailures = 0;
}

function resumeCoverGenerationPolling(scriptId = activeScriptId) {
  if (coverGenerationPollTimer !== null || coverGeneration?.status !== "running" || !scriptId) return;
  const generationVersion = coverDemo.generationVersion;
  coverGenerationPollTimer = schedulePoll("cover-generation", async () => {
    coverGenerationPollTimer = null;
    if (generationVersion !== coverDemo.generationVersion || activeScriptId !== scriptId) return;
    const ok = await fetchCoverStateFromServer(scriptId, generationVersion);
    if (!ok && generationVersion === coverDemo.generationVersion && activeScriptId === scriptId) {
      coverGenerationPollFailures += 1;
      resumeCoverGenerationPolling(scriptId);
    }
  }, pollDelayFor(1500, coverGenerationPollFailures));
}

function applyCoverState(saved, { renderResults = true } = {}) {
  coverDemo.selectedResult = "";
  coverDemo.results = Array.isArray(saved?.results)
    ? saved.results.filter((result) => result && typeof result === "object" && typeof result.aspect === "string")
    : [];
  coverDemo.pendingJobs = Array.isArray(saved?.pendingJobs)
    ? saved.pendingJobs.filter((job) => job && typeof job === "object" && (job.aspect === "3:4" || job.aspect === "4:3"))
    : [];
  coverDemo.generatedReference = saved?.generatedReference === "upload" ? "upload" : "";
  coverDemo.prompt = typeof saved?.prompt === "string" ? saved.prompt : "";
  coverDemo.ratio = coverRatioLabels[saved?.ratio] ? saved.ratio : "both";
  coverDemo.uploadedImages = Array.isArray(saved?.uploadedImages)
    ? saved.uploadedImages.filter((image) => image && typeof image === "object" && typeof image.url === "string")
    : [];
  coverDemo.activeImageId = coverDemo.uploadedImages.some((image) => image.id === saved?.activeImageId)
    ? saved.activeImageId
    : coverDemo.uploadedImages[0]?.id || "";
  coverDemo.phase = coverDemo.results.length ? "complete" : "idle";
  setCoverPromptText(coverDemo.prompt);
  renderCoverRatioButton();
  renderCoverReferenceState();
  if (renderResults) renderCoverResults();
  renderPublishAssets();
}

function loadCoverStateForScript({ serverPayload = null } = {}) {
  coverDemo.generationVersion += 1;
  stopCoverGenerationPolling();
  applyCoverGeneration(null);
  coverTitleGenerationVersion += 1;
  coverTitleGenerationInFlight = false;
  window.clearTimeout(coverStateSyncTimer);
  let saved = null;
  let migrated = false;
  try {
    saved = JSON.parse(localStorage.getItem(coverScriptStorageKey()) || "null");
  } catch (_error) {
    saved = null;
  }
  if (!saved) {
    try {
      const legacy = JSON.parse(localStorage.getItem("coverGeneration.v1") || "null");
      if (legacy && typeof legacy === "object") {
        localStorage.removeItem("coverGeneration.v1");
        saved = {
          prompt: typeof legacy.prompt === "string" ? legacy.prompt : "",
          ratio: coverRatioLabels[legacy.ratio] ? legacy.ratio : "both",
          uploadedImages: [],
          activeImageId: "",
          results: Array.isArray(legacy.results) ? legacy.results : [],
          generatedReference: legacy.generatedReference === "upload" ? "upload" : "",
        };
        migrated = true;
      }
    } catch (_error) {
      saved = null;
    }
  }
  applyCoverState(saved);
  if (migrated) saveCoverState();
  renderCoverGenerateControl();
  renderCoverTitleGenerateControl();
  renderCoverResults();
  if (!activeScriptId) return;
  // A composite panel payload already carries the server state; only fall back
  // to a dedicated request when the caller has none.
  if (serverPayload) applyCoverStatePayload(serverPayload, activeScriptId, coverDemo.generationVersion);
  else fetchCoverStateFromServer(activeScriptId);
}

function loadWorkspaceActiveSelection() {
  try {
    const saved = JSON.parse(localStorage.getItem(workspaceActiveSelectionStorageKey) || "null");
    if (!saved || typeof saved !== "object") return { accountId: "", scriptId: "" };
    return {
      accountId: typeof saved.accountId === "string" ? saved.accountId : "",
      scriptId: typeof saved.scriptId === "string" ? saved.scriptId : "",
    };
  } catch (_error) {
    return { accountId: "", scriptId: "" };
  }
}

function saveWorkspaceActiveSelection(accountId = activeAccountId, scriptId = activeScriptId) {
  try {
    localStorage.setItem(workspaceActiveSelectionStorageKey, JSON.stringify({
      accountId: String(accountId || ""),
      scriptId: String(scriptId || ""),
    }));
  } catch (_error) {
    // Storage is optional: the current session remains usable when it is unavailable.
  }
}

function responseMessage(error, fallback) {
  return error?.detail?.message || error?.message || fallback;
}

async function readJson(response) {
  const payload = await response.json();
  if (!response.ok) throw payload;
  return payload;
}

function scriptProcessingLabel(status) {
  return ({ processing: "处理中", failed: "处理失败", ready: "已就绪" })[status] || "等待处理";
}

function scriptStageLabel(stage) {
  return ({ edit: "编辑", split: "拆片", title: "标题", cover: "封面", publish: "发布" })[stage] || "编辑";
}

const workflowStatusLabels = {
  pending: "待处理",
  editing: "待拍摄",
  ready_to_publish: "待发布",
  published: "已发布",
};

function workflowStatusForScript(script) {
  return workflowStatusLabels[script?.workflowStatus] ? script.workflowStatus : "pending";
}

function workflowStatusLabel(status) {
  return workflowStatusLabels[status] || workflowStatusLabels.pending;
}

function shouldApplyLinkTaskUpdate(activeAccount, activeScript, pendingScript, accountId, scriptId) {
  return activeAccount === accountId && activeScript === scriptId && !pendingScript;
}

function isCurrentLinkTaskContext(accountId, scriptId) {
  return shouldApplyLinkTaskUpdate(activeAccountId, activeScriptId, pendingScriptId, accountId, scriptId);
}

function shouldResetLinkTaskControls(submissionVersion, currentVersion) {
  return submissionVersion === currentVersion;
}

function setLinkTaskControlsDisabled(disabled) {
  // The retired 链接仿写 form owned these controls, so there is nothing to disable.
  void disabled;
}

function invalidateLinkTaskSubmission() {
  linkTaskSubmissionVersion += 1;
  setLinkTaskControlsDisabled(false);
}

function setModalOpen(modal, open) {
  modal.hidden = !open;
  if (modal === accountCreateModal && !open) document.querySelector(window.workspaceAccountState === "empty" ? "#workspaceGateCreate" : "#accountSwitcherButton")?.focus();
  document.body.classList.toggle("is-modal-open", [promptModal, titlePromptModal, writePromptModal, accountCreateModal, accountEditModal, coverTemplateModal, coverTemplateNameModal, accountDeleteModal].some((item) => !item.hidden));
}

/* 提示文案必须盖在登录、订阅等模态框之上。这些模态框由浏览器放进 top layer，
   普通层叠里的 z-index 再高都排在它们下面，会被 ::backdrop 的模糊压暗，
   所以提示文案自己也用 popover 进入 top layer。
   淡入要等浮层打开后的下一帧再加 is-visible：直接从 display:none 变成可见不会触发过渡。 */
function openToastLayer() {
  if (typeof toast.showPopover !== "function") return;
  if (typeof toast.matches === "function" && toast.matches(":popover-open")) return;
  try {
    toast.showPopover();
  } catch (error) {
    /* 浮层不可用时退回原来的层叠方式。 */
  }
}

function closeToastLayer() {
  if (typeof toast.hidePopover !== "function") return;
  if (typeof toast.matches === "function" && !toast.matches(":popover-open")) return;
  try {
    toast.hidePopover();
  } catch (error) {
    /* 已经收起或脱离文档时忽略。 */
  }
}

/* top layer 按加入顺序叠放：提示还在显示时又打开了订阅弹框，把它重新入栈即可回到最上面。 */
function raiseToastLayer() {
  if (typeof toast.matches === "function" && !toast.matches(":popover-open")) return;
  closeToastLayer();
  openToastLayer();
}

document.addEventListener("toggle", (event) => {
  const target = event.target;
  if (!target || target === toast) return;
  if (event.newState === "open") raiseToastLayer();
}, true);

function showToast(message, type = "info", duration = 2600) {
  if (type === "success") window.onboardingModule?.refresh?.();
  window.clearTimeout(showToast.timer);
  window.clearTimeout(showToast.exitTimer);
  toast.textContent = message;
  toast.className = "am-toast";
  openToastLayer();
  window.requestAnimationFrame(() => { toast.className = `am-toast is-visible is-${type}`; });
  if (type !== "loading") {
    showToast.timer = window.setTimeout(() => {
      toast.className = "am-toast";
      showToast.exitTimer = window.setTimeout(closeToastLayer, 240);
    }, duration);
  }
}

function renderCoverResults() {
  const entries = [];
  const pendingAspects = coverDemo.pendingJobs.map((job) => job.aspect);
  for (const aspect of ["3:4", "4:3"]) {
    if (pendingAspects.includes(aspect)) {
      entries.push({ aspect, status: "generating" });
    } else {
      const result = coverDemo.results.find((item) => item && item.aspect === aspect);
      if (result) entries.push(result);
    }
  }

  if (!entries.length) {
    coverResultsRegion.hidden = true;
    const empty = document.createElement("div");
    const symbol = document.createElement("span");
    const message = document.createElement("p");
    empty.className = "cover-empty-state";
    symbol.textContent = "✦";
    message.textContent = "填写提示词后生成封面；上传参考图可按参考图风格生成。";
    empty.append(symbol, message);
    coverResultList.replaceChildren(empty);
    return;
  }

  coverResultsRegion.hidden = false;
  const sourceLabel = coverDemo.generatedReference ? "基于参考图生成" : "仅基于提示词生成";
  const existingCards = Array.from(coverResultList.children);
  const cards = entries.map((result) => {
    // Preserve unchanged images and spinners: rebuilding them can flash a blank
    // image or restart the animation during selection and state refresh.
    const existing = existingCards.find((card) => card.dataset.coverAspect === result.aspect);
    const renderKey = JSON.stringify([result.aspect, result.status, result.imageUrl || "", result.message || "", coverDemo.generatedReference]);
    if (existing?.dataset.coverRenderKey === renderKey) {
      const selected = coverDemo.selectedResult === existing.dataset.coverResult;
      existing.classList.toggle("is-selected", selected);
      existing.setAttribute("aria-pressed", String(selected));
      return existing;
    }
    const card = document.createElement("button");
    const title = document.createElement("strong");
    const aspect = result.aspect === "3:4" ? "3:4" : "4:3";
    const id = aspect === "3:4" ? "portrait" : "landscape";
    const selected = coverDemo.selectedResult === id;
    const generating = result.status === "generating";
    const cancelled = !generating && result.status === "cancelled";
    const failed = !generating && !cancelled && (result.status !== "success" || !result.imageUrl);
    card.type = "button";
    card.className = `cover-result-card ${aspect === "3:4" ? "is-portrait" : "is-landscape"} `
      + `${generating ? "is-generating" : cancelled ? "is-cancelled" : failed ? "is-error" : ""}`;
    card.dataset.coverResult = id;
    card.dataset.coverRenderKey = renderKey;
    card.dataset.coverAspect = aspect;
    card.dataset.coverReference = coverDemo.generatedReference;
    card.classList.toggle("is-selected", selected);
    card.setAttribute("aria-pressed", String(selected));
    if (generating) {
      const spinner = document.createElement("span");
      spinner.className = "cover-result-spinner";
      spinner.setAttribute("aria-hidden", "true");
      card.append(spinner);
    } else if (!failed && !cancelled) {
      const image = document.createElement("img");
      image.className = "cover-result-image";
      image.src = result.imageUrl;
      image.alt = `生成的${aspect}封面`;
      card.append(image);
    }
    title.textContent = `${aspect === "3:4" ? "人物竖版" : "场景横版"} · ${aspect}`;
    card.append(title);
    if (!generating) {
      const source = document.createElement("span");
      source.className = "cover-result-source";
      source.textContent = cancelled ? (result.message || "已取消，可重新生成") : failed ? (result.message || "生成失败，可重新生成") : sourceLabel;
      card.append(source);
    }
    card.addEventListener("click", () => {
      if (generating || failed) return;
      coverDemo.selectedResult = id;
      renderCoverResults();
    });
    return card;
  });
  for (const child of existingCards) {
    if (!cards.includes(child)) coverResultList.removeChild(child);
  }
  cards.forEach((card, index) => {
    if (coverResultList.children[index] !== card) {
      coverResultList.insertBefore(card, coverResultList.children[index] || null);
    }
  });
}

function renderCoverTemplates() {
  if (!coverDemo.templates.length) {
    const empty = document.createElement("div");
    const title = document.createElement("strong");
    const message = document.createElement("span");
    empty.className = "cover-template-empty-state";
    title.textContent = "暂无保存模板";
    message.textContent = "在封面编辑器中保存首个模板";
    empty.append(title, message);
    coverTemplateGrid.replaceChildren(empty);
    return;
  }
  coverTemplateGrid.replaceChildren(...coverDemo.templates.map((template) => {
    const wrap = document.createElement("div");
    const card = document.createElement("button");
    const visual = document.createElement("span");
    const actions = document.createElement("div");
    const remove = document.createElement("button");
    wrap.className = "cover-template-card-wrap";
    card.type = "button";
    card.className = "cover-template-card";
    card.dataset.coverTemplate = template.id;
    card.setAttribute("aria-label", template.label);
    visual.className = "cover-template-card-visual";
    if (template.images && template.images.length) {
      const image = document.createElement("img");
      image.className = "cover-template-card-image";
      image.src = template.images[0].url;
      image.alt = "";
      visual.append(image);
    } else {
      const label = document.createElement("span");
      visual.classList.add("is-text-only");
      label.className = "cover-template-card-label";
      label.textContent = template.label;
      visual.append(label);
    }
    visual.setAttribute("aria-hidden", "true");
    card.append(visual);
    actions.className = "cover-template-card-actions";
    actions.setAttribute("aria-label", `模板「${template.label}」操作`);
    remove.type = "button";
    remove.className = "cover-template-card-action is-danger"
      + (coverTemplateArmedDeleteId === template.id ? " is-armed" : "");
    remove.dataset.coverTemplateDelete = template.id;
    remove.textContent = coverTemplateArmedDeleteId === template.id ? "确认删除" : "删除";
    actions.append(remove);
    wrap.append(card, actions);
    return wrap;
  }));
}

async function openCoverTemplateModal() {
  renderCoverTemplates();
  setModalOpen(coverTemplateModal, true);
  coverReferencePicker.setAttribute("aria-expanded", "true");
  if (!activeAccountId) return;
  try {
    await loadCoverTemplatesForAccount();
    renderCoverTemplates();
  } catch (error) {
    renderCoverTemplates();
    showToast(responseMessage(error, "模板库同步失败"), "error");
  }
}

function closeCoverTemplateModal() {
  coverTemplateArmedDeleteId = "";
  window.clearTimeout(coverTemplateDeleteArmTimer);
  setModalOpen(coverTemplateModal, false);
  coverReferencePicker.setAttribute("aria-expanded", "false");
}

function openCoverTemplateNameModal() {
  const prompt = coverPromptText().trim();
  if (!prompt) return showToast("请先填写封面提示词", "error");
  coverTemplateNameInput.value = "";
  setModalOpen(coverTemplateNameModal, true);
  coverSaveTemplateButton.setAttribute("aria-expanded", "true");
  coverTemplateNameInput.focus?.();
}

function closeCoverTemplateNameModal() {
  coverTemplateNameInput.value = "";
  setModalOpen(coverTemplateNameModal, false);
  coverSaveTemplateButton.setAttribute("aria-expanded", "false");
}

async function deleteCoverTemplate(templateId) {
  const index = coverDemo.templates.findIndex((item) => item.id === templateId);
  if (index < 0) return;
  const removed = coverDemo.templates[index];
  if (!activeAccountId) {
    coverDemo.templates.splice(index, 1);
    renderCoverTemplates();
    renderCoverReferenceState();
    return showToast(`模板「${removed.label}」已删除`, "success");
  }
  try {
    await coverTemplateRequest(`/api/accounts/${encodeURIComponent(activeAccountId)}/cover-templates/${encodeURIComponent(templateId)}`, { method: "DELETE" });
  } catch (error) {
    return showToast(responseMessage(error, "删除模板失败"), "error");
  }
  coverDemo.templates.splice(index, 1);
  if (coverDemo.reference === templateId) {
    coverDemo.reference = "";
    coverDemo.referenceLabel = "";
  }
  renderCoverTemplates();
  renderCoverReferenceState();
  showToast(`模板「${removed.label}」已删除`, "success");
}

function handleCoverTemplateDelete(templateId) {
  if (coverTemplateArmedDeleteId === templateId) {
    coverTemplateArmedDeleteId = "";
    window.clearTimeout(coverTemplateDeleteArmTimer);
    coverTemplateDeleteArmTimer = null;
    deleteCoverTemplate(templateId);
    return;
  }
  coverTemplateArmedDeleteId = templateId;
  window.clearTimeout(coverTemplateDeleteArmTimer);
  coverTemplateDeleteArmTimer = window.setTimeout(() => {
    if (coverTemplateArmedDeleteId === templateId) {
      coverTemplateArmedDeleteId = "";
      renderCoverTemplates();
    }
  }, 2500);
  renderCoverTemplates();
  showToast("再次点击「删除」确认删除该模板", "info");
}

function selectCoverTemplate(templateId) {
  const template = coverDemo.templates.find((item) => item.id === templateId);
  if (!template) return;
  coverDemo.reference = template.id;
  coverDemo.referenceLabel = template.label;
  if (template.images && template.images.length) {
    coverDemo.uploadedImages = template.images.map(({ id, name, url }) => ({ id, name, url }));
    coverDemo.activeImageId = coverDemo.uploadedImages[0]?.id || "";
  } else {
    coverDemo.uploadedImages = [];
    coverDemo.activeImageId = "";
  }
  coverFileInput.value = "";
  setCoverPromptText(template.prompt);
  coverDemo.prompt = template.prompt;
  renderCoverReferenceState();
  saveCoverState();
  closeCoverTemplateModal();
}

async function saveCurrentCoverTemplate() {
  const name = coverTemplateNameInput.value.trim();
  const prompt = coverPromptText().trim();
  if (!name || !prompt) return showToast("请填写模板名称和提示词", "error");
  if (!activeAccountId) {
    coverTemplateSequence += 1;
    coverDemo.templates.push({
      id: `custom-${coverTemplateSequence}`,
      label: name,
      prompt,
      accent: "linear-gradient(140deg, #bcd3d9, #7d9aa4 58%, #44545c)",
      images: coverDemo.uploadedImages.map(({ id, name: imageName, url }) => ({ id, name: imageName, url })),
    });
    closeCoverTemplateNameModal();
    renderCoverTemplates();
    return showToast("模板已保存", "success");
  }
  const payload = coverTemplatePayload({
    label: name,
    prompt,
    accent: "linear-gradient(140deg, #bcd3d9, #7d9aa4 58%, #44545c)",
    images: coverDemo.uploadedImages,
  });
  try {
    const created = await coverTemplateRequest(`/api/accounts/${encodeURIComponent(activeAccountId)}/cover-templates`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    coverDemo.templates.push(created);
  } catch (error) {
    return showToast(responseMessage(error, "保存模板失败"), "error");
  }
  closeCoverTemplateNameModal();
  renderCoverTemplates();
  showToast("模板已保存", "success");
}

function renderCoverReferenceState() {
  const hasReference = Boolean(coverDemo.reference) || coverDemo.uploadedImages.length > 0;
  coverUploadArea.classList.toggle("has-reference", hasReference);
  coverUploadPreview.hidden = !hasReference;
  const activeImage = coverDemo.uploadedImages.find((image) => image.id === coverDemo.activeImageId);
  if (activeImage?.url) {
    coverUploadPreviewImage.src = activeImage.url;
    coverUploadPreviewImage.alt = activeImage.name;
    coverUploadPreviewImage.hidden = false;
  } else {
    coverUploadPreviewImage.hidden = true;
  }
  if (coverDemo.reference) {
    const base = coverDemo.referenceLabel || "已上传参考图";
    coverUploadLabel.textContent = coverDemo.uploadedImages.length ? `${base} · 已上传 ${coverDemo.uploadedImages.length} 张参考图` : base;
  } else {
    coverUploadLabel.textContent = coverDemo.uploadedImages.length ? `已上传 ${coverDemo.uploadedImages.length} 张参考图` : "已上传参考图";
  }
  renderCoverUploadThumbs();
  coverUploadRemove.hidden = !hasReference;
  coverUploadArea.setAttribute("aria-label", hasReference ? "更换参考图片" : "上传参考图片");
}

function renderCoverUploadThumbs() {
  coverUploadThumbs.replaceChildren(...coverDemo.uploadedImages.map((image) => {
    const active = image.id === coverDemo.activeImageId;
    const thumb = document.createElement("span");
    thumb.className = `cover-upload-thumb-item${active ? " is-active" : ""}`;
    thumb.dataset.coverUploadThumb = image.id;
    thumb.setAttribute("role", "button");
    thumb.setAttribute("tabindex", "0");
    thumb.setAttribute("aria-label", `切换到${image.name}`);
    thumb.setAttribute("aria-pressed", String(active));
    thumb.title = image.name;
    if (image.url) {
      const preview = document.createElement("img");
      preview.src = image.url;
      preview.alt = "";
      thumb.append(preview);
    } else {
      thumb.style.background = image.color;
    }
    return thumb;
  }));
}

function hideCoverMention(popup = coverMentionPopup) {
  popup.hidden = true;
  if (coverMentionState.target?.popup === popup) {
    coverMentionState.matches = [];
    coverMentionState.selectedIndex = 0;
    coverMentionState.target = null;
  }
}

function renderCoverMention(popup, list, matches, selectedIndex = 0) {
  list.replaceChildren(...matches.map((image) => {
    const option = document.createElement("button");
    const thumb = document.createElement("span");
    const name = document.createElement("strong");
    option.type = "button";
    option.className = "cover-mention-option";
    option.dataset.coverMentionId = image.id;
    option.setAttribute("role", "option");
    const active = matches.indexOf(image) === selectedIndex;
    option.classList.toggle("is-active", active);
    option.setAttribute("aria-selected", String(active));
    thumb.className = "cover-mention-thumb";
    if (image.url) {
      const preview = document.createElement("img");
      preview.src = image.url;
      preview.alt = "";
      thumb.append(preview);
    } else {
      thumb.style.background = image.color;
    }
    name.textContent = image.name;
    option.append(thumb, name);
    return option;
  }));
  popup.hidden = false;
}

function positionCoverMention(target) {
  const { input, popup } = target;
  if (typeof window.getComputedStyle !== "function" || !input?.getBoundingClientRect || !popup?.parentElement) return;
  const inputRect = input.getBoundingClientRect();
  const shellRect = popup.parentElement.getBoundingClientRect();
  const styles = window.getComputedStyle(input);
  const mirror = document.createElement("div");
  const marker = document.createElement("span");
  Object.assign(mirror.style, {
    position: "fixed",
    top: `${inputRect.top}px`,
    left: `${inputRect.left}px`,
    width: `${input.clientWidth}px`,
    padding: styles.padding,
    border: styles.border,
    boxSizing: styles.boxSizing,
    font: styles.font,
    letterSpacing: styles.letterSpacing,
    lineHeight: styles.lineHeight,
    whiteSpace: "pre-wrap",
    overflowWrap: "break-word",
    visibility: "hidden",
    pointerEvents: "none",
  });
  mirror.textContent = input.value.slice(0, coverMentionState.caret);
  marker.textContent = input.value.slice(coverMentionState.caret, coverMentionState.caret + 1) || "\u200b";
  mirror.append(marker);
  document.body.append(mirror);
  const markerRect = marker.getBoundingClientRect();
  mirror.remove();
  const popupWidth = Math.min(320, Math.max(0, shellRect.width - 16));
  const left = Math.max(8, Math.min(markerRect.left - shellRect.left, shellRect.width - popupWidth - 8));
  popup.style.left = `${left}px`;
  popup.style.top = `${markerRect.bottom - shellRect.top - (input.scrollTop || 0) + 6}px`;
  popup.style.right = "auto";
  popup.style.bottom = "auto";
}

function updateCoverMention(target) {
  const { input, popup, list, images } = target;
  const value = mentionInputText(target);
  const caret = mentionInputCaret(target);
  const atIndex = value.lastIndexOf("@", caret - 1);
  const uploadedImages = images();
  if (atIndex < 0 || uploadedImages.length === 0) return hideCoverMention(popup);
  const query = value.slice(atIndex + 1, caret).toLowerCase();
  const matches = uploadedImages.filter((image) => image.name.toLowerCase().includes(query));
  if (!matches.length) return hideCoverMention(popup);
  coverMentionState.atIndex = atIndex;
  coverMentionState.caret = caret;
  coverMentionState.matches = matches;
  coverMentionState.selectedIndex = 0;
  coverMentionState.target = target;
  renderCoverMention(popup, list, matches, coverMentionState.selectedIndex);
  positionCoverMention(target);
}

function handleCoverMentionKeydown(target, event) {
  if (target.popup.hidden || coverMentionState.target !== target || !coverMentionState.matches.length) return false;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const direction = event.key === "ArrowDown" ? 1 : -1;
    coverMentionState.selectedIndex = (coverMentionState.selectedIndex + direction + coverMentionState.matches.length) % coverMentionState.matches.length;
    renderCoverMention(target.popup, target.list, coverMentionState.matches, coverMentionState.selectedIndex);
    positionCoverMention(target);
    return true;
  }
  if (event.key === "Enter") {
    event.preventDefault();
    insertCoverMention(target, coverMentionState.matches[coverMentionState.selectedIndex]);
    return true;
  }
  if (event.key === "Escape") {
    event.preventDefault();
    hideCoverMention(target.popup);
    return true;
  }
  return false;
}

function coverMentionTokenBesideCaret(direction) {
  if (!coverPromptUsesRichText || typeof window.getSelection !== "function") return null;
  const selection = window.getSelection();
  if (!selection?.rangeCount) return null;
  const range = selection.getRangeAt(0);
  if (!range.collapsed) return null;
  const { startContainer, startOffset } = range;
  let candidate = null;
  if (startContainer === coverPromptInput) {
    candidate = coverPromptInput.childNodes[startOffset + direction];
  } else if (startContainer.parentElement === coverPromptInput && startContainer.nodeType === 3) {
    if (direction < 0 && startOffset === 0) candidate = startContainer.previousSibling;
    if (direction > 0 && startOffset === startContainer.textContent.length) candidate = startContainer.nextSibling;
  }
  return candidate?.classList?.contains("cover-mention-token") ? candidate : null;
}

function deleteCoverMentionToken(event) {
  if (event.key !== "Backspace" && event.key !== "Delete") return false;
  const direction = event.key === "Backspace" ? -1 : 0;
  const token = coverMentionTokenBesideCaret(direction);
  if (!token || typeof document.createRange !== "function" || typeof window.getSelection !== "function") return false;
  event.preventDefault();
  const parent = token.parentNode;
  const index = [...parent.childNodes].indexOf(token);
  token.remove();
  const range = document.createRange();
  range.setStart(parent, index);
  range.collapse(true);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  coverDemo.prompt = coverPromptText();
  coverPromptInput.__coverPromptText = coverDemo.prompt;
  coverPromptInput.value = coverDemo.prompt;
  saveCoverState();
  return true;
}

function insertCoverMention(target, image) {
  const { input, popup, images } = target;
  const value = mentionInputText(target);
  const before = value.slice(0, coverMentionState.atIndex);
  const after = value.slice(coverMentionState.caret);
  const position = images().findIndex((item) => item.id === image.id) + 1;
  const inserted = `@${image.name}（第${position}张参考图） `;
  const nextValue = before + inserted + after;
  const caret = before.length + inserted.length;
  if (target.richText) setCoverPromptText(nextValue, caret);
  else {
    input.value = nextValue;
    input.selectionStart = caret;
    input.selectionEnd = caret;
  }
  hideCoverMention(popup);
  if (target === coverMentionTargets.cover) {
    coverDemo.prompt = nextValue;
    saveCoverState();
  }
  input.focus();
}

function renderCoverRatioButton() {
  coverRatioLabel.textContent = coverRatioLabels[coverDemo.ratio];
  coverGenerateButton.textContent = coverDemo.ratio === "both" ? "生成两张封面" : "生成封面";
  coverRatioMenu.querySelectorAll("[data-cover-ratio]").forEach((option) => {
    option.setAttribute("aria-checked", String(option.dataset.coverRatio === coverDemo.ratio));
  });
}

function toggleCoverRatioMenu() {
  const open = coverRatioMenu.hidden;
  coverRatioMenu.hidden = !open;
  coverRatioButton.setAttribute("aria-expanded", String(open));
}

function hideCoverRatioMenu() {
  coverRatioMenu.hidden = true;
  coverRatioButton.setAttribute("aria-expanded", "false");
}

function selectCoverRatio(ratio) {
  if (!coverRatioLabels[ratio]) return;
  coverDemo.ratio = ratio;
  renderCoverRatioButton();
  hideCoverRatioMenu();
  renderCoverGenerateControl();
  saveCoverState();
}

function clearCoverReference() {
  const activeIndex = coverDemo.uploadedImages.findIndex((image) => image.id === coverDemo.activeImageId);
  if (activeIndex >= 0) {
    coverDemo.uploadedImages.splice(activeIndex, 1);
    const next = coverDemo.uploadedImages[Math.min(activeIndex, coverDemo.uploadedImages.length - 1)];
    coverDemo.activeImageId = next ? next.id : "";
  } else {
    coverDemo.reference = "";
    coverDemo.referenceLabel = "";
  }
  if (!coverDemo.uploadedImages.length) {
    coverDemo.reference = "";
    coverDemo.referenceLabel = "";
    coverDemo.activeImageId = "";
  }
  coverFileInput.value = "";
  renderCoverReferenceState();
  saveCoverState();
}

/* 封面、标题这类能力要走创作服务平台，未登录时先弹登录框再动手，
   而不是让请求失败后在预览区留下一条「请先登录」的错误。

   登录态由账户模块统一判断（它会向本地会话确认，避免把已登录错判成未登录）；
   账户模块缺失时放行，交给后面的 401 兜底。 */
async function requireWorkbenchLogin() {
  if (!window.accountModule || typeof window.accountModule.requireLogin !== "function") return true;
  return window.accountModule.requireLogin();
}

async function generateCover() {
  if (!(await requireWorkbenchLogin())) return;
  if (!coverDemo.prompt.trim()) return showToast("请先填写封面提示词", "error");
  if (!activeScriptId || pendingScriptId) return showToast("请先选择脚本", "error");
  const generationVersion = coverDemo.generationVersion;
  const scriptId = activeScriptId;
  const requestToken = ++coverGenerationRequestSequence;
  const prompt = syncCoverMentionPositions(coverDemo.prompt.trim());
  if (prompt !== coverDemo.prompt.trim()) {
    coverDemo.prompt = prompt;
    setCoverPromptText(prompt);
    saveCoverState();
  }
  const submittedPrompt = stripMentionNamesForSubmission(prompt);
  const selectedAspects = coverDemo.ratio === "both" ? ["3:4", "4:3"] : coverDemo.ratio === "portrait" ? ["3:4"] : ["4:3"];
  const pendingAspects = new Set(coverDemo.pendingJobs.map((job) => job.aspect));
  const aspects = selectedAspects.filter((aspect) => !pendingAspects.has(aspect));
  if (!aspects.length) {
    return showToast("该尺寸正在生成中，请稍候。", "error");
  }
  const requestRatio = aspects.length === 2 ? "both" : aspects[0] === "3:4" ? "portrait" : "landscape";
  coverDemo.selectedResult = "";
  coverDemo.generatedReference = coverDemo.uploadedImages.length ? "upload" : "";
  mergeCoverGeneration({
    jobId: "",
    status: "running",
    aspects: aspects.map((aspect) => ({ aspect, status: "pending", imageTaskId: "", imageUrl: "", message: "" })),
  }, { requestToken, optimistic: true });
  renderCoverGenerateControl();
  renderCoverResults();
  let response;
  try {
    response = await fetch(`/api/scripts/${encodeURIComponent(activeScriptId)}/cover-generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: submittedPrompt,
        ratio: requestRatio,
        imageUrls: coverDemo.uploadedImages.map((image) => image.url),
      }),
    });
    const payload = await readJson(response);
    if (!response.ok) throw payload;
    if (generationVersion !== coverDemo.generationVersion || activeScriptId !== scriptId) return;
    if (!payload?.generation) throw { detail: { message: "封面生成任务启动失败。" } };
    mergeCoverGeneration(payload.generation, { requestToken });
    renderCoverGenerateControl();
    renderCoverResults();
    resumeCoverGenerationPolling(scriptId);
  } catch (error) {
    if (generationVersion !== coverDemo.generationVersion || activeScriptId !== scriptId) return;
    removeCoverGenerationAspects(aspects, requestToken);
    renderCoverGenerateControl();
    showToast(coverGenerationErrorMessage(error, response?.status), "error");
  } finally {
    if (generationVersion === coverDemo.generationVersion && activeScriptId === scriptId) {
      renderCoverGenerateControl();
      renderCoverResults();
    }
  }
}

function mergeCoverResults(incoming) {
  return [
    ...coverDemo.results.filter((existing) => (
      existing && typeof existing === "object" && typeof existing.aspect === "string"
      && !incoming.some((next) => next && next.aspect === existing.aspect)
    )),
    ...incoming,
  ].sort((a, b) => (coverAspectOrder[a.aspect] ?? 9) - (coverAspectOrder[b.aspect] ?? 9));
}

function renderCoverGenerateControl() {
  const selected = coverDemo.ratio === "both" ? ["3:4", "4:3"] : coverDemo.ratio === "portrait" ? ["3:4"] : ["4:3"];
  const pendingAspects = coverDemo.pendingJobs.map((job) => job.aspect);
  coverGenerateButton.disabled = selected.every((aspect) => pendingAspects.includes(aspect));
  renderCoverGenerationStatus();
}

function serverConfirmedCoverJobs() {
  return coverGenerationItems().filter((item) => (
    (item.status === "pending" || item.status === "submitted")
    && Boolean(coverGenerationItemJobId(item))
  ));
}

function renderCoverGenerationStatus() {
  const jobs = serverConfirmedCoverJobs();
  coverGenerationStatus.hidden = jobs.length === 0;
  coverGenerationStatus.textContent = jobs.length
    ? `正在生成 ${jobs.length} 张，可离开页面，稍后查看结果`
    : "";
}

function renderCoverTitleGenerateControl() {
  coverTitleGenerateButton.disabled = coverTitleGenerationInFlight;
  coverTitleGenerateButton.textContent = coverTitleGenerationInFlight
    ? (coverTitleGenerationPhase === "frame" ? "正在提取参考图…" : "正在生成提示词…")
    : "生成提示词";
}

async function pollCoverTitleJob(jobId, generationVersion, scriptId) {
  for (;;) {
    await waitForPollDelay(1500);
    if (generationVersion !== coverTitleGenerationVersion || activeScriptId !== scriptId) return null;
    const response = await fetch(`/api/cover-title-jobs/${encodeURIComponent(jobId)}`);
    const payload = await response.json();
    if (!response.ok) throw payload;
    if (payload.status === "success") return payload.result;
    if (payload.status === "failed") throw { detail: payload.error || { message: "封面标题生成失败，请稍后重试。" } };
  }
}

async function generateCoverTitle() {
  if (!(await requireWorkbenchLogin())) return;
  if (!activeScriptId || pendingScriptId) return showToast("请先选择脚本", "error");
  if (coverTitleGenerationInFlight) return;
  const scriptId = activeScriptId;
  const accountId = activeAccountId;
  const submittedPrompt = coverPromptText();
  const assetVersion = publishAssetMutationVersion;
  const generationVersion = ++coverTitleGenerationVersion;
  let expectedImages = JSON.stringify(coverDemo.uploadedImages);
  const contextCurrent = () => generationVersion === coverTitleGenerationVersion
    && activeScriptId === scriptId && activeAccountId === accountId && !pendingScriptId;
  const inputsCurrent = () => contextCurrent() && assetVersion === publishAssetMutationVersion
    && coverPromptText() === submittedPrompt && JSON.stringify(coverDemo.uploadedImages) === expectedImages;
  const explainConflict = () => {
    if (contextCurrent()) showToast(coverPromptText() !== submittedPrompt
      ? "提示词已修改，未覆盖当前内容，请重新生成。"
      : "参考图或关联视频已修改，未覆盖当前内容，请重新生成。", "error");
  };
  coverTitleGenerationInFlight = true;
  coverTitleGenerationPhase = "frame";
  renderCoverTitleGenerateControl();
  let selectedReference = null;
  let warning = "";
  try {
    const manualCount = coverDemo.uploadedImages.filter((image) => image.source !== "publish-video").length;
    try {
      const frameResponse = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/cover-reference-from-video`, { method: "POST" });
      const framePayload = await readJson(frameResponse);
      if (!inputsCurrent()) { explainConflict(); return; }
      if (!frameResponse.ok) {
        if (framePayload?.detail?.code === "cover_video_changed") {
          showToast(responseMessage(framePayload, "关联视频已变更，请重新生成提示词。"), "error");
          return;
        }
        throw framePayload;
      }
      if (framePayload.reference) {
        if (manualCount >= COVER_REFERENCE_MAX) {
          warning = `已有 ${COVER_REFERENCE_MAX} 张手动参考图，请先删除一张再提取视频画面。`;
        } else {
          selectedReference = framePayload.reference;
          // Avoid ambiguous name-based @ resolution when a manual image has the same name.
          const names = new Set(coverDemo.uploadedImages.filter((image) => image.source !== "publish-video").map((image) => image.name));
          let suffix = 2;
          while (names.has(selectedReference.name)) selectedReference.name = `视频封面参考图 ${suffix++}`;
          const oldIndex = coverDemo.uploadedImages.findIndex((image) => image.source === "publish-video");
          coverDemo.uploadedImages = coverDemo.uploadedImages.filter((image) => image.source !== "publish-video");
          coverDemo.uploadedImages.splice(oldIndex < 0 ? coverDemo.uploadedImages.length : oldIndex, 0, selectedReference);
          coverDemo.activeImageId = selectedReference.id;
          expectedImages = JSON.stringify(coverDemo.uploadedImages);
          renderCoverReferenceState();
          saveCoverState();
        }
      }
    } catch (error) {
      if (!inputsCurrent()) { explainConflict(); return; }
      warning = responseMessage(error, "视频抽帧失败。");
    }
    coverTitleGenerationPhase = "title";
    renderCoverTitleGenerateControl();
    if (warning) showToast(`${warning} 将继续生成主副标题。`, "error");
    // Persist the exact prompt and references before the backend snapshots the title job.
    await syncCoverStateToServer(scriptId);
    if (!inputsCurrent()) { explainConflict(); return; }
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/cover-title-generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ referenceId: selectedReference?.id || "" }),
    });
    const payload = await readJson(response);
    if (!response.ok) throw payload;
    if (!payload.jobId) throw { detail: { message: "封面标题生成任务启动失败。" } };
    const result = await pollCoverTitleJob(payload.jobId, generationVersion, scriptId);
    if (!result || !contextCurrent()) return;
    if (!inputsCurrent()) { explainConflict(); return; }
    const mainTitle = String(result.mainTitle || "").trim();
    const subtitle = String(result.subtitle || "").trim();
    if (!mainTitle || !subtitle) throw { detail: { message: "封面标题生成结果无效，请重试。" } };
    const position = selectedReference ? coverDemo.uploadedImages.findIndex((image) => image.id === selectedReference.id) + 1 : 0;
    const prefix = position ? `参考 @${selectedReference.name}（第${position}张参考图） 视频画面的色调风格生成用于发布抖音/视频号平台的视频封面：\n` : "";
    const prompt = `${prefix}主标题：“${mainTitle}”\n副标题：“${subtitle}”`;
    setCoverPromptText(prompt);
    coverDemo.prompt = prompt;
    saveCoverState();
    showToast(warning ? `主副标题已生成；${warning}` : "封面提示词已生成", warning ? "error" : "success");
  } catch (error) {
    if (contextCurrent()) showToast(responseMessage(error, "封面提示词生成失败，请稍后重试。"), "error");
  } finally {
    if (generationVersion === coverTitleGenerationVersion && activeScriptId === scriptId) {
      coverTitleGenerationInFlight = false;
      coverTitleGenerationPhase = "title";
      renderCoverTitleGenerateControl();
    }
  }
}

function syncCoverMentionPositions(prompt) {
  return prompt.replace(/@([^\n]*?)（第(\d+)张参考图）/g, (match, name, number) => {
    const index = coverDemo.uploadedImages.findIndex((image) => image.name === name.trim());
    if (index < 0) return match;
    const position = index + 1;
    return position === Number(number) ? match : `@${name}（第${position}张参考图）`;
  });
}

function stripMentionNamesForSubmission(prompt) {
  return prompt.replace(/@([^\n]*?)（第(\d+)张参考图）/g, (match, name) => {
    const index = coverDemo.uploadedImages.findIndex((image) => image.name === name.trim());
    if (index < 0) return match;
    return `第${index + 1}张参考图`;
  });
}

function coverGenerationErrorMessage(error, status) {
  const detail = error?.detail;
  if (detail && typeof detail === "object" && typeof detail.message === "string" && detail.message.trim()) {
    return detail.message.trim();
  }
  if (error && typeof error === "object" && typeof error.code === "string" && typeof error.message === "string" && error.message.trim()) {
    return error.message.trim();
  }
  if (status === 404) return "封面生成接口不可用，请重启服务后再试。";
  if (typeof status === "number" && status >= 500) return "封面生成服务异常，请稍后再试。";
  return "封面生成失败，请确认服务已启动后重试。";
}

function renderScrollSyncControl() {
  const isLocked = isScrollSyncLocked;
  const label = isLocked ? "已绑定双栏滚动，点击取消绑定" : "双栏滚动未绑定，点击绑定";
  scrollSyncButton.classList.toggle("is-locked", isLocked);
  scrollSyncButton.classList.toggle("is-unlocked", !isLocked);
  scrollSyncButton.setAttribute("aria-pressed", String(isLocked));
  scrollSyncButton.setAttribute("aria-label", label);
  scrollSyncButton.title = isLocked ? "已绑定双栏滚动" : "双栏滚动未绑定";
}

function syncEditorScroll(source, target) {
  if (!isScrollSyncLocked || scrollSyncTarget === source) return;
  scrollSyncTarget = target;
  target.scrollTop = source.scrollTop;
  window.requestAnimationFrame(() => { scrollSyncTarget = null; });
}

function resetEditorScrollPositions() {
  sourceTranscript.scrollTop = 0;
  rewriteDraft.scrollTop = 0;
}

function formatScriptCreatedAt(value) {
  if (!value) return "未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未知";
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "numeric", day: "numeric",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(date);
  const fields = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
  return `${fields.year}/${fields.month}/${fields.day}/ ${fields.hour}:${fields.minute}`;
}

function renderWorkspaceMetadata(workspace) {
  const title = String(workspace.title || "未命名视频").trim() || "未命名视频";
  const author = String(workspace.author || "").trim();
  const createdAt = formatScriptCreatedAt(activeScript?.createdAt || workspace.createdAt);
  const editable = Boolean(activeScriptId && activeScript?.source === "blank");
  workspaceTitle.textContent = title;
  workspaceTitle.hidden = false;
  workspaceTitle.classList.toggle("is-editable", editable);
  workspaceTitle.setAttribute("role", editable ? "button" : "heading");
  workspaceTitle.setAttribute("tabindex", editable ? "0" : "-1");
  workspaceTitleInput.hidden = true;
  workspaceTitleEdit = null;
  workspaceMeta.textContent = author ? `作者：${author} · 创建时间：${createdAt}` : `创建时间：${createdAt}`;
}

function canEditWorkspaceTitle() {
  return Boolean(activeScriptId && activeScript?.source === "blank");
}

function startWorkspaceTitleEdit() {
  if (workspaceTitleEdit?.saving || !canEditWorkspaceTitle()) return;
  const title = String(activeScript.title || workspaceTitle.textContent || "").trim();
  workspaceTitleEdit = { title, accountId: activeAccountId, scriptId: activeScriptId, saving: false };
  workspaceTitleInput.value = title;
  workspaceTitleInput.disabled = false;
  workspaceTitle.hidden = true;
  workspaceTitleInput.hidden = false;
  workspaceTitleInput.focus();
  workspaceTitleInput.select();
}

function cancelWorkspaceTitleEdit() {
  if (!workspaceTitleEdit || workspaceTitleEdit.saving) return;
  workspaceTitle.textContent = workspaceTitleEdit.title;
  workspaceTitleInput.value = workspaceTitleEdit.title;
  workspaceTitleInput.hidden = true;
  workspaceTitle.hidden = false;
  workspaceTitleEdit = null;
}

async function commitWorkspaceTitleEdit() {
  const edit = workspaceTitleEdit;
  if (!edit || edit.saving || !canEditWorkspaceTitle()) return;
  const title = workspaceTitleInput.value.trim();
  if (!title) {
    showToast("标题不能为空", "error");
    cancelWorkspaceTitleEdit();
    return;
  }
  if (title === edit.title) {
    cancelWorkspaceTitleEdit();
    return;
  }
  const scriptId = edit.scriptId;
  const accountId = edit.accountId;
  edit.saving = true;
  workspaceTitleInput.disabled = true;
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/title`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    const saved = await readJson(response);
    if (activeAccountId !== accountId || activeScriptId !== scriptId || pendingScriptId || workspaceTitleEdit !== edit) return;
    activeScript = saved;
    scripts = scripts.map((script) => script.id === saved.id ? saved : script);
    renderWorkspaceMetadata(saved);
    renderScriptList();
    showToast("标题已保存", "success");
  } catch (error) {
    if (workspaceTitleEdit === edit) {
      edit.saving = false;
      workspaceTitleInput.disabled = false;
      showToast(responseMessage(error, "保存标题失败"), "error");
    }
  }
}

function formatTranscriptForDisplay(transcript) {
  const normalized = String(transcript || "").replace(/\r\n?/g, "\n").trim();
  if (!normalized) return "";
  return normalized.split(/\n\s*\n+/).map((paragraph) => {
    const compactParagraph = paragraph.replace(/\s*\n\s*/g, " ").replace(/\s+/g, " ").trim();
    const sentences = compactParagraph.match(/[^。！？!?]+[。！？!?]?/g) || [compactParagraph];
    const groups = [];
    for (let index = 0; index < sentences.length; index += 2) groups.push(sentences.slice(index, index + 2).join("").trim());
    return groups.filter(Boolean).join("\n\n");
  }).filter(Boolean).join("\n\n");
}

function renderTaskStatusCard(task) {
  const presentation = taskStatusPresentations[task.phase] || taskStatusPresentations.submitting;
  const liveMessage = String(task.message || presentation.fallbackMessage).trim() || presentation.fallbackMessage;
  taskStatusBar.dataset.phase = task.phase;
  taskStatusTitle.textContent = presentation.title;
  taskStatusDescription.textContent = presentation.description;
  taskStatusText.textContent = liveMessage;
  taskStatusActions.hidden = task.phase !== "failed";
  renderDeleteScriptControl();
}

function renderRewriteWarning(task) {
  const warning = String(task?.warningMessage || "").trim();
  const hasRewriteWarning = task?.rewriteStatus === "failed" && Boolean(warning);
  rewriteWarning.hidden = !hasRewriteWarning;
  rewriteWarning.textContent = hasRewriteWarning
    ? `${warning} 视频和原稿已保留，可重试生成仿写稿。`
    : "";
  generateRewritesButton.textContent = hasRewriteWarning ? "重试生成仿写稿" : "生成仿写稿";
}

function getRewriteWordCount() {
  return rewriteDraft.value.replace(/\s/g, "").length;
}

function renderRewriteDraft() {
  saveRewriteDraftStatus.textContent = `${getRewriteWordCount()} 字 · ${rewriteDraftState}`;
}

function resetRewriteDraftSaveSession() {
  window.clearTimeout(rewriteDraftSaveTimer);
  rewriteDraftSaveTimer = null;
  rewriteDraftVersion += 1;
  rewriteDraftDirty = false;
}

function isCurrentBlankRewriteSave({ accountId, scriptId, version }) {
  return version === rewriteDraftVersion
    && activeAccountId === accountId
    && activeScriptId === scriptId
    && activeScript?.source === "blank"
    && !pendingScriptId;
}

function scheduleRewriteDraftSave() {
  window.clearTimeout(rewriteDraftSaveTimer);
  rewriteDraftSaveTimer = window.setTimeout(() => {
    rewriteDraftSaveTimer = null;
    flushRewriteDraftSave();
  }, 400);
}

async function flushRewriteDraftSave() {
  if (!rewriteDraftDirty || !activeScriptId || !activeScript) return;
  rewriteDraftDirty = false;
  const scriptId = activeScriptId;
  const accountId = activeAccountId;
  const source = activeScript.source;
  const content = rewriteDraft.value;
  const version = rewriteDraftVersion;
  if (source === "link") {
    const taskId = activeTaskId;
    const outcome = await queueLinkRewriteSave(content, { automatic: true });
    if (
      outcome.error && !outcome.superseded
      && version === rewriteDraftVersion
      && activeAccountId === accountId
      && activeScriptId === scriptId
      && activeTaskId === taskId
      && activeScript?.source === "link"
      && !pendingScriptId
    ) {
      rewriteDraftDirty = true;
    }
    return;
  }
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/content`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content }) });
    const saved = await readJson(response);
    if (!isCurrentBlankRewriteSave({ accountId, scriptId, version })) return;
    activeScript = saved;
    rewriteDraftState = "已保存";
    window.onboardingModule?.refresh?.();
    renderRewriteDraft();
    renderTitleState();
  } catch (error) {
    if (!isCurrentBlankRewriteSave({ accountId, scriptId, version })) return;
    rewriteDraftDirty = true;
    rewriteDraftState = "自动保存失败";
    renderRewriteDraft();
    showToast(responseMessage(error, "保存脚本失败"), "error");
  }
}

function splitDurationFallback() {
  const segmentDuration = splitSegments.reduce((latest, segment) => Math.max(latest, Number(segment.end) || 0), 0);
  const metadataDuration = Number(splitDuration);
  return Math.max(Number.isFinite(metadataDuration) && metadataDuration > 0 ? metadataDuration : 0, segmentDuration);
}

function splitEffectiveDuration() {
  return splitMediaDuration > 0 ? splitMediaDuration : splitDurationFallback();
}

function formatTime(seconds) {
  const totalSeconds = Math.max(0, Math.floor(Number(seconds) || 0));
  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
}

function cancelSplitAnimationFrame() {
  if (splitAnimationFrame !== null) window.cancelAnimationFrame(splitAnimationFrame);
  splitAnimationFrame = null;
}

function syncSplitVideoColumnSize() {
  const workbenchHeight = Number(splitWorkbench.getBoundingClientRect().height) || 0;
  if (workbenchHeight <= 0) return;
  const width = Math.max(1, Math.round(workbenchHeight * 9 / 16));
  splitWorkbench.style.setProperty("--split-video-width", `${width}px`);
  splitWorkbench.style.setProperty("--split-video-height", `${Math.round(workbenchHeight)}px`);
}

function splitTimelineLaneGeometry() {
  const trackRect = splitTrack.getBoundingClientRect();
  const waveformRect = splitWaveform.getBoundingClientRect();
  const measuredWidth = Number(waveformRect.width);
  if (Number(trackRect.width) > 0 && Number.isFinite(measuredWidth) && measuredWidth > 0) {
    return {
      viewportStart: waveformRect.left,
      trackOffset: waveformRect.left - trackRect.left,
      width: measuredWidth,
    };
  }
  const trackWidth = Math.max(0, Number(trackRect.width) || 0);
  return {
    viewportStart: (Number(trackRect.left) || 0) + 76,
    trackOffset: 76,
    width: Math.max(0, trackWidth - 81),
  };
}

function renderSplitPlayhead(seconds, duration) {
  const ratio = duration > 0 ? Math.max(0, Math.min(1, seconds / duration)) : 0;
  const lane = splitTimelineLaneGeometry();
  const playheadPosition = Math.round((lane.trackOffset + lane.width * ratio) * 1000) / 1000;
  splitPlayhead.style.left = `${playheadPosition}px`;
  const currentTime = formatTime(seconds);
  splitTrackClock.textContent = currentTime;
  splitPlayheadLabel.textContent = currentTime;
  splitVideoDuration.textContent = `${currentTime} / ${formatTime(duration)}`;
}

function renderSplitTimelineTicks(duration) {
  const tickCount = 7;
  splitTrackTicks.replaceChildren(...Array.from({ length: tickCount }, (_, index) => {
    const tick = document.createElement("span");
    tick.textContent = formatTime(duration > 0 ? (duration * index) / (tickCount - 1) : 0);
    return tick;
  }));
}

function renderActiveTranscriptSegment(seconds, scrollSegment = false) {
  let activeIndex = splitSegments.findIndex((segment) => seconds >= segment.start && seconds < segment.end);
  if (activeIndex < 0) {
    for (let index = splitSegments.length - 1; index >= 0; index -= 1) {
      if (seconds >= splitSegments[index].start) {
        activeIndex = index;
        break;
      }
    }
  }
  splitTranscript.querySelectorAll(".split-caption").forEach((caption, index) => {
    const isActive = index === activeIndex;
    caption.parentElement?.classList.toggle("is-active", isActive);
    caption.setAttribute("aria-current", isActive ? "true" : "false");
    if (isActive && scrollSegment) caption.scrollIntoView?.({ block: "nearest" });
  });
}

function setSplitActiveTime(seconds, { seekVideo = false, scrollSegment = false } = {}) {
  const duration = splitEffectiveDuration();
  activeTime = Math.max(0, Math.min(Number(seconds) || 0, duration));
  if (seekVideo) splitVideo.currentTime = activeTime;
  renderSplitPlayhead(activeTime, duration);
  renderActiveTranscriptSegment(activeTime, scrollSegment);
}

function setSplitPanelVisible(panelName, visible) {
  const panel = { video: splitVideoPanel, transcript: splitTranscriptPanel }[panelName];
  const toggle = { video: toggleSplitVideo, transcript: toggleSplitTranscript }[panelName];
  if (!panel || !toggle) return;
  splitPanelVisibility[panelName] = visible;
  panel.hidden = !visible;
  toggle.classList.toggle("is-off", !visible);
  toggle.setAttribute("aria-pressed", String(visible));
  toggle.setAttribute("aria-label", `${visible ? "隐藏" : "显示"}${({ video: "视频", transcript: "字幕" })[panelName]}面板`);
  toggle.title = toggle.getAttribute("aria-label");
  splitWorkbench.dataset.visiblePanels = Object.entries(splitPanelVisibility)
    .filter(([, isVisible]) => isVisible)
    .map(([name]) => name)
    .join(" ");
  scheduleStructureRegrow();
}

function setWritePanelVisible(panelName, visible) {
  const panel = { structure: writeStructurePanel, content: writeContentPanel }[panelName];
  const toggle = { structure: toggleWriteStructure, content: toggleWriteContent }[panelName];
  if (!panel || !toggle) return;
  writePanelVisibility[panelName] = visible;
  panel.hidden = !visible;
  toggle.classList.toggle("is-off", !visible);
  toggle.setAttribute("aria-pressed", String(visible));
  toggle.setAttribute("aria-label", `${visible ? "隐藏" : "显示"}${({ structure: "脚本结构", content: "脚本内容" })[panelName]}`);
  toggle.title = toggle.getAttribute("aria-label");
  writeWorkbench.dataset.visiblePanels = Object.entries(writePanelVisibility)
    .filter(([, isVisible]) => isVisible)
    .map(([name]) => name)
    .join(" ");
  scheduleStructureRegrow();
}

function renderSplitRightPanel() {
  for (const { id, tab } of splitPanelTabs) {
    const active = splitPanelTab === id;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  }
  const structureActive = splitPanelTab === "structure";
  splitTranscriptMeta.hidden = structureActive;
  splitStructureActions.hidden = !structureActive;
  splitTranscript.hidden = structureActive || splitSegments.length === 0;
}

function applySplitRightPanel() {
  renderSplitRightPanel();
  renderWritingState();
  if (splitPanelTab === "structure") loadWritingStateForScript();
}

function selectSplitPanelTab(tabId) {
  if (splitPanelTab === tabId) return;
  splitPanelTab = tabId;
  applySplitRightPanel();
}

function setSplitStageAvailable(available) {
  // 拆片 moved to the 拆解视频 module, so the script workspace never offers the tab.
  // Availability is kept in a flag instead of the button so the retired stage can
  // still be rendered by the tests that cover the shared editor internals.
  splitStageReady = Boolean(available);
  splitStageButton.hidden = true;
  splitStageSeparator.hidden = true;
}

function setWriteStageAvailable(available) {
  writeStageButton.hidden = !available;
  writeStageSeparator.hidden = !available;
}

function splitVideoSource(videoFile) {
  const normalizedFile = String(videoFile || "").trim();
  return normalizedFile
    ? `/api/files/${normalizedFile.split("/").map(encodeURIComponent).join("/")}`
    : "";
}

function splitPosterSource(posterFile) {
  return splitVideoSource(posterFile);
}

function stopSplitCompatibilityPolling() {
  splitCompatibilityPollTimer = cancelPoll("split-compatibility", splitCompatibilityPollTimer);
  splitCompatibilityPollScriptId = "";
  splitCompatibilityPollFailures = 0;
}

function splitMediaNeedsPolling(task) {
  return task?.safariCompatibility === "pending" || task?.posterStatus === "pending";
}

function applySplitCompatibilityUpdate(task) {
  const videoFile = String(task?.videoFile || "").trim();
  const posterFile = String(task?.posterFile || "").trim();
  const posterChanged = task?.posterStatus === "ready" && posterFile && splitVideo.dataset.poster !== posterFile;
  if (posterChanged) {
    splitVideo.poster = splitPosterSource(posterFile);
    splitVideo.dataset.poster = posterFile;
  }
  if (task?.safariCompatibility !== "ready" || !videoFile || splitVideo.dataset.file === videoFile) return posterChanged;
  const resumeTime = Number.isFinite(Number(splitVideo.currentTime)) ? Number(splitVideo.currentTime) : activeTime;
  splitPendingSourceRestore = { time: resumeTime, resumePlayback: !splitVideo.paused };
  if (!splitVideo.paused) splitVideo.pause();
  splitVideo.dataset.file = videoFile;
  splitVideo.src = splitVideoSource(videoFile);
  splitVideo.hidden = false;
  splitPlaybackToggle.hidden = false;
  splitVideo.load?.();
  renderSplitPlaybackControl();
  return true;
}

function startSplitCompatibilityPolling(task) {
  stopSplitCompatibilityPolling();
  if (!splitMediaNeedsPolling(task) || !activeScriptId) return;
  const scriptId = activeScriptId;
  splitCompatibilityPollScriptId = scriptId;
  const poll = async () => {
    try {
      const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/workspace`);
      const payload = await readJson(response);
      if (activeScriptId !== scriptId || splitCompatibilityPollScriptId !== scriptId) return;
      const nextTask = payload?.task;
      applySplitCompatibilityUpdate(nextTask);
      splitCompatibilityPollFailures = 0;
      if (splitMediaNeedsPolling(nextTask)) {
        splitCompatibilityPollTimer = schedulePoll("split-compatibility", poll, pollDelayFor(1500, splitCompatibilityPollFailures));
      } else {
        stopSplitCompatibilityPolling();
      }
    } catch (_error) {
      if (activeScriptId === scriptId && splitCompatibilityPollScriptId === scriptId) {
        splitCompatibilityPollFailures += 1;
        splitCompatibilityPollTimer = schedulePoll("split-compatibility", poll, pollDelayFor(1500, splitCompatibilityPollFailures));
      }
    }
  };
  splitCompatibilityPollFailures = 0;
  splitCompatibilityPollTimer = schedulePoll("split-compatibility", poll, pollDelayFor(1500, splitCompatibilityPollFailures));
}

function resetSplitWorkbench() {
  stopSplitCompatibilityPolling();
  splitCompatibilityTask = null;
  cancelSplitAnimationFrame();
  splitTrackIsDragging = false;
  splitTrackSeekPending = false;
  splitTrackSeekTarget = null;
  splitVideo.pause();
  splitVideo.src = "";
  splitVideo.removeAttribute("poster");
  splitVideo.dataset.file = "";
  splitVideo.dataset.poster = "";
  splitPendingSourceRestore = null;
  splitVideo.hidden = true;
  splitPlaybackToggle.hidden = true;
  splitFullscreenToggle.hidden = true;
  splitTranscript.replaceChildren();
  splitTranscript.hidden = true;
  splitTrack.hidden = true;
  activeTime = 0;
  splitDuration = 0;
  splitMediaDuration = 0;
  splitSegments = [];
  splitPanelVisibility = { video: true, transcript: true };
  ["video", "transcript"].forEach((panelName) => setSplitPanelVisible(panelName, true));
}

function renderSplitPlaybackControl() {
  const isPlaying = !splitVideo.paused;
  splitPlaybackToggle.hidden = !splitVideo.src;
  splitPlaybackToggle.classList.toggle("is-playing", isPlaying);
  splitPlaybackToggle.textContent = "";
  splitPlaybackToggle.setAttribute("aria-label", isPlaying ? "暂停视频" : "播放视频");
  splitPlaybackToggle.setAttribute("aria-pressed", String(isPlaying));
  renderSplitFullscreenControl();
}

function renderSplitFullscreenControl() {
  const isFullscreen = document.fullscreenElement === splitVideo.parentElement;
  const label = isFullscreen ? "退出全屏" : "全屏播放";
  splitFullscreenToggle.hidden = !splitVideo.src;
  splitFullscreenToggle.classList.toggle("is-fullscreen", isFullscreen);
  splitFullscreenToggle.setAttribute("aria-label", label);
  splitFullscreenToggle.setAttribute("title", label);
  splitFullscreenToggle.setAttribute("aria-pressed", String(isFullscreen));
}

async function toggleSplitFullscreen() {
  if (!splitVideo.src || splitVideo.hidden) return;
  const container = splitVideo.parentElement;
  try {
    if (document.fullscreenElement === container) {
      await document.exitFullscreen();
    } else {
      await container.requestFullscreen();
    }
  } catch (error) {
    showToast("无法切换全屏，请检查浏览器是否允许全屏播放。", "error");
  }
  renderSplitFullscreenControl();
}

function renderSplitWaveform(peaks = []) {
  const amplitudes = Array.isArray(peaks)
    ? peaks.map((peak) => Math.max(8, Math.min(100, 8 + (Number(peak) || 0) * 92)))
    : [];
  splitWaveform.replaceChildren(...amplitudes.map((amplitude) => {
    const bar = document.createElement("span");
    bar.className = "split-waveform-bar";
    bar.style.height = `${amplitude}%`;
    return bar;
  }));
}

function rewriteModelState(model = selectedRewriteModel) {
  return activeRewriteModels[model] || { content: "", available: false, status: "pending", errorMessage: "" };
}

function renderActiveRewriteModel() {
  const state = rewriteModelState();
  const generating = state.status === "running";
  const content = String(state.content || "");
  rewriteDraft.value = content;
  rewriteDraft.disabled = generating;
  rewriteDraft.hidden = generating;
  rewriteDraftState = generating ? "脚本生成中..." : state.available ? "已保存" : "等待生成";
  generateRewritesButton.disabled = generating;
  generateRewritesButton.textContent = generating ? "正在生成…" : "生成仿写稿";
  renderRewriteDraft();
}

function stopRewriteModelsPolling() {
  rewriteModelsPollTimer = cancelPoll("rewrite-models", rewriteModelsPollTimer);
  rewriteModelsPollScriptId = "";
  rewriteModelsPollFailures = 0;
}

function pollRewriteModels(task) {
  if (!activeTaskId || !activeScriptId || !Object.values(task?.rewrites || activeRewriteModels).some((state) => state?.status === "running")) {
    stopRewriteModelsPolling();
    return;
  }
  rewriteModelsPollScriptId = activeScriptId;
  rewriteModelsPollTimer = cancelPoll("rewrite-models", rewriteModelsPollTimer);
  rewriteModelsPollTimer = schedulePoll("rewrite-models", async () => {
    const scriptId = rewriteModelsPollScriptId;
    const accountId = activeAccountId;
    try {
      const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/workspace`);
      const payload = await readJson(response);
      if (activeAccountId !== accountId || activeScriptId !== scriptId || pendingScriptId) return;
      const latest = payload?.task;
      if (!latest) return;
      activeRewriteModels = latest.rewrites || activeRewriteModels;
      if (latest.taskId === activeTaskId) renderActiveRewriteModel();
      rewriteModelsPollFailures = 0;
      pollRewriteModels(latest);
    } catch (error) {
      if (activeAccountId === accountId && activeScriptId === scriptId) {
        rewriteModelsPollFailures += 1;
        rewriteModelsPollTimer = schedulePoll(
          "rewrite-models",
          () => pollRewriteModels(task),
          pollDelayFor(1500, rewriteModelsPollFailures),
        );
      }
    }
  }, pollDelayFor(1500, rewriteModelsPollFailures));
}

function resetLinkRewriteSaveSession() {
  linkRewriteSession += 1;
  linkRewriteDraftVersion += 1;
  if (linkRewriteQueuedSave) linkRewriteQueuedSave.resolve({ saved: false, superseded: true });
  linkRewriteQueuedSave = null;
}

function hasSplitEntryContent(task) {
  return [task?.transcript, task?.sourceText, task?.rewrite]
    .some((value) => String(value || "").trim())
    || (Array.isArray(task?.transcriptSegments) && task.transcriptSegments
      .some((segment) => String(segment?.text || "").trim()));
}

function renderSplitWorkbench(task) {
  resetSplitWorkbench();
  splitCompatibilityTask = task || null;
  const videoFile = String(task?.videoFile || "").trim();
  splitVideo.dataset.file = videoFile;
  splitVideo.dataset.poster = String(task?.posterFile || "").trim();
  if (splitVideo.dataset.poster) splitVideo.poster = splitPosterSource(task?.posterFile);
  splitVideo.src = splitVideoSource(videoFile);
  splitVideo.hidden = !videoFile;
  splitPlaybackToggle.hidden = !videoFile;
  renderSplitPlaybackControl();
  splitDuration = Number(task?.duration) || 0;
  splitSegments = Array.isArray(task?.transcriptSegments)
    ? task.transcriptSegments.map((segment) => ({
      start: Math.max(0, Number(segment.start) || 0),
      end: Math.max(0, Number(segment.end) || 0),
      text: String(segment.text || "").trim(),
    })).filter((segment) => segment.end >= segment.start && segment.text)
    : [];
  splitTranscript.replaceChildren();
  for (const segment of splitSegments) {
    const item = document.createElement("article");
    const time = document.createElement("time");
    const caption = document.createElement("button");
    item.className = "caption";
    time.textContent = `${formatTime(segment.start)} — ${formatTime(segment.end)}`;
    caption.className = "split-caption";
    caption.type = "button";
    caption.textContent = segment.text;
    caption.addEventListener("click", () => setSplitActiveTime(segment.start, { seekVideo: true, scrollSegment: true }));
    item.append(time, caption);
    splitTranscript.append(item);
  }
  renderSplitRightPanel();
  renderSplitWaveform(task?.waveformPeaks);
  const duration = splitEffectiveDuration();
  splitTrack.hidden = duration <= 0;
  renderSplitTimelineTicks(duration);
  activeRewriteModels = task?.rewrites || { "text-default": { content: task?.rewrite || "", available: Boolean(task?.rewrite), status: task?.rewriteStatus || "pending" } };
  renderActiveRewriteModel();
  setSplitActiveTime(0);
}

function updateSplitTimeFromPointer(event, { seekVideo = true } = {}) {
  const lane = splitTimelineLaneGeometry();
  const ratio = Math.max(0, Math.min(1, (event.clientX - lane.viewportStart) / Math.max(lane.width, 1)));
  setSplitActiveTime(ratio * splitEffectiveDuration(), { seekVideo, scrollSegment: true });
  return activeTime;
}

function isSplitTextEditingTarget(target) {
  return Boolean(target?.matches?.("input, textarea, select, [contenteditable='true']"));
}

async function toggleSplitPlayback() {
  if (!splitVideo.src) return;
  if (!splitVideo.paused) {
    splitVideo.pause();
    return;
  }
  try {
    await splitVideo.play();
  } catch (error) {
    showToast("视频无法播放，请检查媒体文件。", "error");
    renderSplitPlaybackControl();
  }
}

function startSplitPlaybackSync() {
  cancelSplitAnimationFrame();
  const sync = () => {
    if (splitVideo.paused || splitStage.hidden) return cancelSplitAnimationFrame();
    if (!splitTrackIsDragging && !splitTrackSeekPending) {
      setSplitActiveTime(splitVideo.currentTime, { scrollSegment: true });
    }
    splitAnimationFrame = window.requestAnimationFrame(sync);
  };
  splitAnimationFrame = window.requestAnimationFrame(sync);
}

function isCurrentLinkRewriteSave(job) {
  return job.session === linkRewriteSession
    && job.version === linkRewriteDraftVersion
    && activeAccountId === job.accountId
    && activeScriptId === job.scriptId
    && activeTaskId === job.taskId
    && activeScript?.source === "link"
    && !pendingScriptId;
}

function isActiveLinkRewriteContext(job) {
  return job.session === linkRewriteSession
    && activeAccountId === job.accountId
    && activeScriptId === job.scriptId
    && activeTaskId === job.taskId
    && activeScript?.source === "link";
}

async function runLinkRewriteSave(job) {
  linkRewriteSaveInFlight = job;
  let outcome = { saved: false };
  try {
    const response = await fetch(`/api/tasks/${encodeURIComponent(job.taskId)}/rewrite`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: job.content, model: job.model }) });
    await readJson(response);
    const current = isCurrentLinkRewriteSave(job);
    if (current) {
      activeRewriteModels[job.model] = { ...rewriteModelState(job.model), content: job.content, available: Boolean(job.content), status: "complete", errorMessage: "" };
      if (job.model === selectedRewriteModel) {
        rewriteDraft.value = job.content;
      }
      rewriteDraftState = "已保存";
      renderRewriteDraft();
      if (!job.automatic) showToast("仿写稿已保存", "success");
    }
    outcome = { saved: current, superseded: !current };
  } catch (error) {
    const current = isCurrentLinkRewriteSave(job);
    if (current) {
      rewriteDraftState = job.automatic ? "自动保存失败" : "保存失败";
      renderRewriteDraft();
      showToast(responseMessage(error, "保存仿写稿失败"), "error");
    }
    outcome = { saved: false, error, superseded: !current };
  } finally {
    job.resolve(outcome);
    if (linkRewriteSaveInFlight !== job) return;
    linkRewriteSaveInFlight = null;
    const next = linkRewriteQueuedSave;
    linkRewriteQueuedSave = null;
    if (!next) return;
    if (isActiveLinkRewriteContext(next)) runLinkRewriteSave(next);
    else next.resolve({ saved: false, superseded: true });
  }
}

function queueLinkRewriteSave(content, { automatic = true } = {}) {
  if (!activeTaskId || !activeScriptId || activeScript?.source !== "link") {
    return Promise.resolve({ saved: false, superseded: true });
  }
  return new Promise((resolve) => {
    const job = {
      accountId: activeAccountId,
      scriptId: activeScriptId,
      taskId: activeTaskId,
      session: linkRewriteSession,
      version: linkRewriteDraftVersion,
      content,
      model: selectedRewriteModel,
      automatic,
      resolve,
    };
    if (linkRewriteSaveInFlight) {
      if (linkRewriteQueuedSave) linkRewriteQueuedSave.resolve({ saved: false, superseded: true });
      linkRewriteQueuedSave = job;
      return;
    }
    runLinkRewriteSave(job);
  });
}

function renderAccountList(message = "") {
  window.refreshAccountSwitcher?.();
  cancelAccountDeleteHold();
  closeAccountDeleteReveal();
  accountList.replaceChildren();
  if (message || accounts.length === 0) {
    const emptyState = document.createElement("p");
    emptyState.className = "history-empty";
    emptyState.textContent = message || "暂无账号";
    accountList.append(emptyState);
    return;
  }
  for (const account of accounts) {
    const row = document.createElement("div");
    row.className = "account-record-row";
    const button = document.createElement("button");
    button.className = "account-record";
    button.type = "button";
    button.setAttribute("aria-pressed", String(account.id === activeAccountId));
    if (account.id === activeAccountId) button.classList.add("is-active");
    const avatar = document.createElement("span");
    avatar.className = "account-avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = String(account.name || "账").trim().slice(0, 1) || "账";
    const copy = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = account.name || "未命名账号";
    const platform = document.createElement("small");
    platform.textContent = "工作台";
    copy.append(name, platform);
    button.append(avatar, copy);
    button.addEventListener("click", (event) => {
      if (accountDeleteSuppressedClickId === account.id) {
        accountDeleteSuppressedClickId = "";
        event.preventDefault?.();
        event.stopPropagation?.();
        return;
      }
      closeAccountDeleteReveal();
      selectAccount(account.id).catch((error) => showToast(responseMessage(error, "账号读取失败"), "error"));
    });
    row.append(button);
    if (!account.isSystem) {
      const edit = document.createElement("button");
      const remove = document.createElement("button");
      edit.className = "account-record-edit";
      edit.type = "button";
      edit.textContent = "编辑";
      edit.setAttribute("aria-label", `编辑账号「${account.name || "未命名账号"}」`);
      edit.addEventListener("click", (event) => {
        event.preventDefault?.();
        event.stopPropagation?.();
        closeAccountDeleteReveal();
        openAccountEditModal(account.id);
      });
      remove.className = "account-record-delete";
      remove.type = "button";
      remove.textContent = "删除";
      remove.setAttribute("aria-label", `删除账号「${account.name || "未命名账号"}」`);
      remove.addEventListener("click", (event) => {
        event.preventDefault?.();
        event.stopPropagation?.();
        closeAccountDeleteReveal();
        return openAccountDeleteModal(account.id);
      });
      button.addEventListener("pointerdown", (event) => startAccountDeleteHold(account, row, button, event));
      button.addEventListener("pointerup", (event) => cancelAccountDeleteHold({ accountId: account.id, pointerId: event.pointerId }));
      button.addEventListener("pointerleave", (event) => cancelAccountDeleteHold({ accountId: account.id, pointerId: event.pointerId }));
      button.addEventListener("pointercancel", (event) => cancelAccountDeleteHold({ accountId: account.id, pointerId: event.pointerId }));
      button.addEventListener("contextmenu", (event) => {
        if (accountDeleteHold?.accountId !== account.id) return;
        event.preventDefault?.();
      });
      button.addEventListener("keydown", (event) => {
        if (event.repeat || ![" ", "Enter"].includes(event.key)) return;
        event.preventDefault?.();
        startAccountDeleteHold(account, row, button, { pointerId: "keyboard", pointerType: "keyboard" });
      });
      button.addEventListener("keyup", (event) => {
        if (![" ", "Enter"].includes(event.key)) return;
        event.preventDefault?.();
        const revealed = accountDeleteReveal?.accountId === account.id;
        cancelAccountDeleteHold({ accountId: account.id, pointerId: "keyboard" });
        if (!revealed) selectAccount(account.id).catch((error) => showToast(responseMessage(error, "账号读取失败"), "error"));
      });
      row.append(edit, remove);
    }
    accountList.append(row);
  }
}

function cancelAccountDeleteHold({ accountId = "", pointerId = null } = {}) {
  const hold = accountDeleteHold;
  if (!hold || (accountId && hold.accountId !== accountId) || (pointerId !== null && hold.pointerId !== pointerId)) return false;
  window.clearTimeout(hold.timer);
  hold.row.classList.remove("is-delete-holding");
  accountDeleteHold = null;
  return true;
}

function closeAccountDeleteReveal() {
  if (!accountDeleteReveal) return;
  accountDeleteReveal.row.classList.remove("is-delete-revealed");
  accountDeleteReveal = null;
}

// Navigation closes the popover through one cleanup path, including during a hold.
window.resetAccountSwitcherInteraction = () => {
  cancelAccountDeleteHold();
  closeAccountDeleteReveal();
  accountDeleteSuppressedClickId = "";
};

function revealAccountDeleteAction(account, row, record) {
  cancelAccountDeleteHold({ accountId: account.id });
  closeAccountDeleteReveal();
  row.classList.add("is-delete-revealed");
  accountDeleteSuppressedClickId = account.id;
  accountDeleteReveal = { accountId: account.id, row, record };
}

function isDesktopAccountSidebarCollapsed() {
  const layout = document.querySelector(".tool-layout");
  return Boolean(
    layout?.classList.contains("is-account-collapsed")
    && window.matchMedia?.("(min-width: 901px)")?.matches === true,
  );
}

function startAccountDeleteHold(account, row, record, event) {
  if (isDesktopAccountSidebarCollapsed() && !record.closest?.(".account-switcher-popover")) return;
  if (event.pointerType === "mouse" && event.button !== 0) return;
  event.preventDefault?.();
  accountDeleteSuppressedClickId = "";
  closeAccountDeleteReveal();
  cancelAccountDeleteHold();
  const hold = {
    accountId: account.id,
    pointerId: event.pointerId,
    row,
    record,
    timer: null,
  };
  row.classList.add("is-delete-holding");
  if (event.pointerType !== "keyboard") record.setPointerCapture?.(event.pointerId);
  hold.timer = window.setTimeout(() => {
    if (accountDeleteHold !== hold) return;
    revealAccountDeleteAction(account, row, record);
  }, 5000);
  accountDeleteHold = hold;
}

async function openAccountDeleteModal(accountId) {
  const account = accounts.find((item) => item.id === accountId);
  if (!accountId || !account || account.isSystem) return;
  try {
    const response = await fetch(`/api/accounts/${encodeURIComponent(accountId)}/deletion-summary`);
    const summary = await readJson(response);
    if (summary?.account?.id !== accountId) throw new Error("账号删除信息无效");
    accountDeleteSummary = summary;
    const templateText = summary.coverTemplateCount ? `及 ${summary.coverTemplateCount} 个封面模板` : "";
    const topicText = summary.topicCount ? `、${summary.topicCount} 条选题` : "";
    const taskText = summary.manualTaskCount ? `、${summary.manualTaskCount} 个手动任务` : "";
    const ideaText = summary.inspirationCount ? `、${summary.inspirationCount} 条灵感` : "";
    accountDeleteModalDescription.textContent = `将永久删除「${summary.account.name}」及其 ${summary.scriptCount} 个脚本${templateText}${topicText}${taskText}${ideaText}，相关下载素材也会一并删除。此操作不可撤销。${accounts.length === 1 ? " 删除后，需要创建新的工作台才能继续使用。" : ""}`;
    confirmAccountDeleteButton.disabled = false;
    confirmAccountDeleteButton.textContent = "删除工作台";
    setModalOpen(accountDeleteModal, true);
    cancelAccountDeleteButton.focus();
  } catch (error) {
    showToast(responseMessage(error, "无法读取账号删除信息"), "error");
  }
}

function closeAccountDeleteModal() {
  accountDeleteSummary = null;
  closeAccountDeleteReveal();
  setModalOpen(accountDeleteModal, false);
}

function openAccountEditModal(accountId) {
  const account = accounts.find((item) => item.id === accountId);
  if (!accountId || !account || account.isSystem) return;
  accountEditId = accountId;
  accountEditNameInput.value = account.name || "";
  saveAccountEditButton.disabled = false;
  setModalOpen(accountEditModal, true);
  accountEditNameInput.focus();
  accountEditNameInput.select?.();
}

function closeAccountEditModal() {
  accountEditId = "";
  accountEditNameInput.value = "";
  saveAccountEditButton.disabled = false;
  setModalOpen(accountEditModal, false);
}

async function saveAccountEdit() {
  const accountId = accountEditId;
  const name = accountEditNameInput.value.trim();
  if (!accountId || saveAccountEditButton.disabled) return;
  if (!name) return showToast("请填写工作台名称", "error");
  saveAccountEditButton.disabled = true;
  try {
    const response = await fetch(`/api/accounts/${encodeURIComponent(accountId)}/name`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const updated = await readJson(response);
    if (updated?.id !== accountId) throw new Error("账号更新信息无效");
    accounts = accounts.map((account) => account.id === accountId ? updated : account);
    renderAccountList();
    if (activeAccountId === accountId) renderScriptList();
    closeAccountEditModal();
    showToast("账号已更新", "success");
  } catch (error) {
    showToast(responseMessage(error, "更新账号失败"), "error");
  } finally {
    if (!accountEditModal.hidden) saveAccountEditButton.disabled = false;
  }
}

async function confirmAccountDeletion() {
  const summary = accountDeleteSummary;
  const accountId = String(summary?.account?.id || "");
  if (!accountId || confirmAccountDeleteButton.disabled) return;
  confirmAccountDeleteButton.disabled = true;
  confirmAccountDeleteButton.textContent = "正在删除…";
  try {
    const response = await fetch(`/api/accounts/${encodeURIComponent(accountId)}`, { method: "DELETE" });
    const deleted = await readJson(response);
    accountListRequestVersion += 1;
    const deletedScriptIds = Array.isArray(deleted?.deletedScriptIds) ? deleted.deletedScriptIds : [];
    deletedScriptIds.forEach((scriptId) => {
      localStorage.removeItem(`coverScriptState.${scriptId}.v1`);
    });
    localStorage.removeItem(coverTemplateMigrationKey(accountId));
    localStorage.removeItem(publishDraftPlatformStorageKey(accountId));
    accounts = accounts.filter((account) => account.id !== accountId);
    const deletedActiveAccount = activeAccountId === accountId;
    if (!deletedActiveAccount) {
      renderAccountList();
      closeAccountDeleteModal();
      showToast("账号已删除", "success");
      return;
    }
    const nextAccountId = accounts[0]?.id || null;
    activeAccountId = null;
    window.WorkbenchPlugins?.onAccountChange?.(null);
    activeScriptId = null;
    activeScript = null;
    activeTaskId = null;
    pendingScriptId = null;
    scripts = [];
    invalidateLinkTaskSubmission();
    closeAccountDeleteModal();
    if (nextAccountId) await selectAccount(nextAccountId);
    else enterEmptyWorkspace();
    showToast("账号已删除", "success");
  } catch (error) {
    showToast(responseMessage(error, "删除账号失败"), "error");
  } finally {
    if (!accountDeleteModal.hidden) {
      confirmAccountDeleteButton.disabled = false;
      confirmAccountDeleteButton.textContent = "删除工作台";
    }
  }
}

function scriptCreatedKey(script) {
  return String(script?.createdAt || script?.updatedAt || "");
}

// Keep the sidebar ordered by creation time (newest first). Editing a script
// must not reshuffle the list, so the sort key is the immutable createdAt.
function sortScriptsByCreated() {
  scripts.sort((left, right) => {
    const leftKey = scriptCreatedKey(left);
    const rightKey = scriptCreatedKey(right);
    return rightKey < leftKey ? -1 : rightKey > leftKey ? 1 : 0;
  });
}

function visibleScripts() {
  return scriptStatusFilter === "all"
    ? scripts
    : scripts.filter((script) => workflowStatusForScript(script) === scriptStatusFilter);
}

function setScriptStatusMenuOpen(control, button, menu, open) {
  menu.hidden = !open;
  button.setAttribute("aria-expanded", String(open));
  control.classList.toggle("is-open", open);
}

function setScriptActionsOpen(open, restoreFocus = false) {
  scriptActionsPanel.hidden = !open;
  scriptActionsButton.setAttribute("aria-expanded", String(open));
  if (!open) {
    setScriptStatusMenuOpen(scriptWorkflowStatusControl, scriptWorkflowStatusButton, scriptWorkflowStatusMenu, false);
    setScriptStatusMenuOpen(scriptMoveControl, scriptMoveButton, scriptMoveMenu, false);
    deleteScriptArmedFor = null;
    deleteScriptButton.textContent = "删除";
    deleteScriptButton.classList.remove("is-armed");
    deleteScriptButton.setAttribute("aria-label", "删除当前脚本");
    if (restoreFocus) scriptActionsButton.focus();
  }
}

function hideScriptStatusMenus() {
  setScriptActionsOpen(false);
  setScriptStatusMenuOpen(scriptStatusFilterControl, scriptStatusFilterButton, scriptStatusFilterMenu, false);
  setScriptStatusMenuOpen(scriptWorkflowStatusControl, scriptWorkflowStatusButton, scriptWorkflowStatusMenu, false);
  setScriptStatusMenuOpen(scriptMoveControl, scriptMoveButton, scriptMoveMenu, false);
}

function wireScriptStatusMenuDismissal(control, menu) {
  let pendingClose = null;
  const cancelPendingClose = () => {
    if (pendingClose === null) return;
    window.clearTimeout(pendingClose);
    pendingClose = null;
  };
  const schedulePendingClose = () => {
    cancelPendingClose();
    pendingClose = window.setTimeout(() => {
      pendingClose = null;
      if (!control.matches(":hover") && !menu.matches(":hover")) hideScriptStatusMenus();
    }, 0);
  };
  control.addEventListener("pointerenter", cancelPendingClose);
  control.addEventListener("pointerleave", schedulePendingClose);
  menu.addEventListener("pointerenter", cancelPendingClose);
  control.addEventListener("focusout", () => {
    window.setTimeout(() => {
      if (!control.contains(document.activeElement)) hideScriptStatusMenus();
    }, 0);
  });
}

function renderScriptStatusFilterControl() {
  scriptStatusFilterLabel.textContent = `脚本 · ${scriptStatusFilter === "all" ? "全部" : workflowStatusLabel(scriptStatusFilter)}`;
  scriptStatusFilterMenu.querySelectorAll("[data-script-status-filter]").forEach((option) => {
    option.classList.toggle("is-active", option.dataset.scriptStatusFilter === scriptStatusFilter);
    option.setAttribute("aria-checked", String(option.dataset.scriptStatusFilter === scriptStatusFilter));
  });
}

function renderScriptWorkflowStatusControl() {
  const canUpdate = hasWorkspaceScriptActions();
  const status = workflowStatusForScript(activeScript);
  scriptWorkflowStatusControl.hidden = !canUpdate;
  scriptWorkflowStatusButton.disabled = !canUpdate || Boolean(pendingScriptId);
  scriptWorkflowStatusLabel.textContent = workflowStatusLabel(status);
  scriptWorkflowStatusButton.setAttribute("aria-label", `当前运营状态：${workflowStatusLabel(status)}，点击修改`);
  scriptWorkflowStatusMenu.querySelectorAll("[data-workflow-status]").forEach((option) => {
    option.classList.toggle("is-active", option.dataset.workflowStatus === status);
    option.setAttribute("aria-checked", String(option.dataset.workflowStatus === status));
  });
  if (scriptWorkflowStatusButton.disabled) setScriptStatusMenuOpen(scriptWorkflowStatusControl, scriptWorkflowStatusButton, scriptWorkflowStatusMenu, false);
}

function renderMoveScriptControl() {
  const canMove = hasWorkspaceScriptActions();
  const currentAccountId = activeScript?.accountId || activeAccountId;
  const currentAccount = accounts.find((account) => account.id === currentAccountId);
  const currentAccountName = currentAccount ? currentAccount.name || "未命名账号" : "";
  scriptMoveAccountLabel.textContent = currentAccountName;
  scriptMoveAccountLabel.title = currentAccountName;
  scriptMoveControl.hidden = !canMove;
  scriptMoveButton.disabled = !canMove || Boolean(pendingScriptId) || scriptMoveInFlight;
  scriptMoveButton.setAttribute("aria-label", "将当前脚本移动到其他账号");
  scriptMoveMenu.replaceChildren();
  for (const account of accounts) {
    const isCurrent = account.id === currentAccountId;
    const option = document.createElement("button");
    option.className = "script-move-option cover-ratio-option";
    option.type = "button";
    option.role = "menuitemradio";
    option.dataset.moveAccountId = account.id;
    option.disabled = isCurrent || Boolean(pendingScriptId) || scriptMoveInFlight;
    option.classList.toggle("is-current", isCurrent);
    option.setAttribute("aria-checked", String(isCurrent));
    const name = document.createElement("span");
    name.className = "script-move-account-name";
    name.textContent = account.name || "未命名账号";
    option.append(name);
    scriptMoveMenu.append(option);
  }
  if (scriptMoveButton.disabled) setScriptStatusMenuOpen(scriptMoveControl, scriptMoveButton, scriptMoveMenu, false);
}

function selectScriptStatusFilter(status) {
  if (status !== "all" && !workflowStatusLabels[status]) return;
  scriptStatusFilter = status;
  setScriptStatusMenuOpen(scriptStatusFilterControl, scriptStatusFilterButton, scriptStatusFilterMenu, false);
  const visible = visibleScripts();
  renderScriptList();
  if (visible.some((script) => script.id === activeScriptId)) return;
  if (visible[0]) {
    selectScript(visible[0].id, activeAccountId).catch((error) => showToast(responseMessage(error, "脚本读取失败"), "error"));
    return;
  }
  // 筛选落空时列表里没有可打开的脚本，编辑区让位给空态卡片。
  resetActiveScriptSelection();
  setDemoTaskState("empty");
}

function renderScriptList(message = "") {
  sortScriptsByCreated();
  scriptList.replaceChildren();
  renderScriptStatusFilterControl();
  const visible = visibleScripts();
  if (scriptListSubtitle) {
    const label = scriptStatusFilter === "all" ? "全部" : workflowStatusLabel(scriptStatusFilter);
    scriptListSubtitle.textContent = `当前筛选“${label}”，共 ${visible.length} 条脚本`;
  }
  if (message || visible.length === 0) {
    const emptyState = document.createElement("p");
    emptyState.className = "history-empty";
    emptyState.textContent = message || (scriptStatusFilter === "all" ? "暂无脚本" : `暂无${workflowStatusLabel(scriptStatusFilter)}脚本`);
    scriptList.append(emptyState);
    return;
  }
  for (const script of visible) {
    const button = document.createElement("button");
    button.className = "history-record";
    button.dataset.scriptId = script.id;
    button.type = "button";
    button.setAttribute("aria-pressed", String(script.id === (pendingScriptId || activeScriptId)));
    if (script.id === (pendingScriptId || activeScriptId)) button.classList.add("is-active");
    const status = workflowStatusForScript(script);
    const indicator = document.createElement("i");
    indicator.className = `script-workflow-status-dot is-${status.replaceAll("_", "-")}`;
    indicator.setAttribute("role", "img");
    indicator.setAttribute("aria-label", `运营状态：${workflowStatusLabel(status)}`);
    indicator.title = `运营状态：${workflowStatusLabel(status)}`;
    const title = document.createElement("strong");
    title.className = "history-record-title";
    title.textContent = script.title || "未命名脚本";
    const metadata = document.createElement("span");
    const displayStage = script.source === "link" && script.stage === "edit" ? "split" : script.stage;
    metadata.textContent = script.source === "link"
      ? `链接脚本 · ${scriptProcessingLabel(script.processingStatus)} · 阶段：${scriptStageLabel(displayStage)}`
      : `空白脚本 · 阶段：${scriptStageLabel(script.stage)}`;
    button.append(title, metadata, indicator);
    const accountId = activeAccountId;
    button.addEventListener("click", () => {
      // Re-selecting a card should not reset the workspace or hide its actions.
      // Keep selectScript itself refreshable for saves, polling and external returns.
      if (accountId !== activeAccountId || script.id === (pendingScriptId || activeScriptId)) return;
      return selectScript(script.id, accountId).catch((error) => showToast(responseMessage(error, "脚本读取失败"), "error"));
    });
    scriptList.append(button);
  }
  window.WorkbenchScheduleCards?.render();
  window.resumeWritingReturnSync?.();
}

function publishPlatformAvailable(platform) {
  return accounts.some((item) => item.id === activeAccountId) && ["douyin", "channels"].includes(platform);
}

function generatedPublishCover(aspect) {
  return coverDemo.results.find((item) => item?.aspect === aspect && item?.status === "success") || null;
}

function publishContextIsCurrent(accountId, scriptId, version = publishContextVersion) {
  return activeAccountId === accountId && activeScriptId === scriptId && publishContextVersion === version;
}

function setPublishAssetsStatus(message = "", state = "") {
  publishAssetsStatus.textContent = message;
  publishAssetsStatus.hidden = !message;
  publishAssetsStatus.dataset.state = state;
}

// Only persisted assets belong to the upload contract; generated previews do not.
function publishReadiness(platform) {
  const valid = asset => typeof asset?.path === "string" && Boolean(asset.path.trim());
  const covers = publishAssets?.covers || {};
  const missing = [];
  if (!valid(publishAssets?.video)) missing.push("视频");
  const missingCovers = ["3:4", "4:3"].filter(aspect => !valid(covers[aspect]));
  if (missingCovers.length === 2) missing.push("两张封面");
  else if (missingCovers.length) missing.push(`${missingCovers[0]} 封面`);
  const buffer = publishDraftBuffers.get(publishDraftBufferKey(platform));
  const errors = publishDraftValidation(platform, buffer);
  if (!buffer?.main?.trim()) missing.push(platform === "channels" ? "短标题" : "标题");
  if (platform === "channels" && !splitPublishDescription(buffer?.description || "").description.trim()) missing.push("视频描述");
  const limits = Object.values(errors).filter(message => message.includes("不能超过"));
  const join = items => items.length === 2 ? items.join("和") : items.join("、");
  let hint = missing.length ? `${missing.some(item => /视频$|封面/.test(item) && item !== "视频描述") ? "请补充" : "请填写"}${join(missing)}` : "";
  if (missing.length === 1 && missing[0] === "两张封面") hint = "请补充 3:4 和 4:3 封面";
  hint = [hint, ...limits].filter(Boolean).join("；");
  const assetState = publishAssetsStatus.dataset.state;
  const assetBlocked = ["loading", "saving", "error"].includes(assetState);
  if (assetBlocked) hint = publishAssetsStatus.textContent || "正在同步素材…";
  return { ready: !missing.length && !limits.length && !assetBlocked, hint, errors };
}

function renderPublishAssets() {
  const video = publishAssets?.video;
  const covers = publishAssets?.covers && typeof publishAssets.covers === "object" ? publishAssets.covers : {};
  publishVideoStatus.textContent = video?.name ? `已选择 ${video.name}` : "请选择本地视频";
  for (const [aspect, statusElement] of [
    ["3:4", publishPortraitCoverStatus],
    ["4:3", publishLandscapeCoverStatus],
  ]) {
    const saved = covers[aspect];
    const generated = generatedPublishCover(aspect);
    statusElement.textContent = saved?.path && saved?.name
      ? `已选择 ${saved.name}`
      : generated ? "已生成，待关联" : "请选择封面图片";
    const actionText = document.querySelector(aspect === "3:4" ? "#publishPortraitCoverActionText" : "#publishLandscapeCoverActionText");
    actionText.textContent = saved?.path ? "替换" : "上传";
  }
  window.WorkbenchPublishPreviews?.render({
    accountId: activeAccountId, scriptId: pendingScriptId ? "" : activeScriptId,
    assets: publishAssets, generated: [generatedPublishCover("3:4"), generatedPublishCover("4:3")],
  });
  const busy = ["loading", "saving"].includes(publishAssetsStatus.dataset.state) || publishAssetsLocked();
  const contextUnavailable = !activeScriptId || Boolean(pendingScriptId);
  publishVideoInput.disabled = contextUnavailable || busy;
  publishPortraitCoverInput.disabled = contextUnavailable || busy;
  publishLandscapeCoverInput.disabled = contextUnavailable || busy;
  publishVideoDropZone.classList.toggle("is-drop-disabled", publishVideoInput.disabled);
  publishPortraitCoverDropZone.classList.toggle("is-drop-disabled", publishPortraitCoverInput.disabled);
  publishLandscapeCoverDropZone.classList.toggle("is-drop-disabled", publishLandscapeCoverInput.disabled);
  if (publishVideoInput.disabled) publishVideoDropZone.classList.toggle("is-drag-over", false);
  if (publishPortraitCoverInput.disabled) publishPortraitCoverDropZone.classList.toggle("is-drag-over", false);
  if (publishLandscapeCoverInput.disabled) publishLandscapeCoverDropZone.classList.toggle("is-drag-over", false);
  renderPublishAutomation();
}

function renderPublishAutomation() {
  for (const platform of titlePlatforms) {
    const controls = publishPlatformControls[platform];
    const editor = publishDraftEditors[platform];
    const key = publishDraftBufferKey(platform);
    const available = publishPlatformAvailable(platform) && Boolean(activeScriptId);
    const status = publishStatuses[platform]?.status === "checking" ? publishStatuses[platform] : cachedPublishLogin(platform) || publishStatuses[platform];
    const task = publishTasks[platform];
    const buffer = publishDraftBuffers.get(key);
    const readiness = publishReadiness(platform);
    const errors = readiness.errors;
    const saving = publishSaveJobs.has(key);
    const saveError = publishSaveErrors.get(key);
    const busy = publishBusy(platform);
    const loggedIn = status?.status === "logged_in";
    const name = platform === "douyin" ? "抖音" : "视频号";
    const stateText = !available ? "请先选择工作台和脚本" : loggedIn ? `${name}已登录`
      : status?.status === "checking" ? "正在检查登录…"
      : status?.status === "login_opened" ? "请在浏览器中完成登录"
      : status?.status === "login_required" ? `${name}未登录` : status?.message || "登录状态待检查";
    const saveText = saving ? "保存中…" : saveError ? saveError : buffer?.dirty ? "文案待保存" : platformTitleState(platform)?.publishDraft ? "文案已保存" : "待填写文案";
    controls.status.textContent = stateText;
    if (available) {
      const detail = document.createElement("span");
      detail.className = "publish-status-detail";
      detail.textContent = ` · ${saving || saveError ? saveText : readiness.hint || saveText}`;
      controls.status.append(detail);
    }
    controls.status.classList.toggle("is-logged-in", available && loggedIn);
    let label = "上传并填写发布信息";
    let disabled = !available || Boolean(pendingScriptId);
    if (busy) { label = publishPreparing.has(key) ? (status?.status === "checking" ? "正在检查登录…" : "正在保存文案…") : "正在上传并填写…"; disabled = true; }
    else if (status?.status === "checking") { label = "正在检查登录…"; disabled = true; }
    else if (status?.status === "login_opened") label = "我已完成登录";
    else if (status?.status === "login_required") label = `登录${name}`;
    else if (!loggedIn && status?.status !== "stale") label = "重新检查";
    else {
      if (task?.status === "failed") label = "重试上传并填写";
      disabled ||= !readiness.ready || titleStateLoading || Boolean(titleMutationKind && titleMutationKind !== "publish") || Boolean(errors.main || errors.description);
    }
    controls.fill.textContent = label;
    controls.fill.disabled = disabled;
    editor.save.hidden = !saveError;
    editor.save.disabled = saving || busy || !buffer?.dirty;
    for (const field of ["main", "description"]) {
      editor[field].setAttribute("aria-invalid", String(Boolean(errors[field])));
      editor[field].setAttribute("aria-describedby", `${platform}PublishStatus`);
    }
    controls.taskStatus.textContent = task?.message || "";
    controls.taskStatus.hidden = !task?.message;
  }
}

async function handlePublishAction(platform) {
  if (publishPlatformControls[platform].fill.disabled || publishBusy(platform)) return;
  const status = (cachedPublishLogin(platform) || publishStatuses[platform])?.status;
  if (status === "login_required") return openPublishLogin(platform);
  if (!["logged_in", "stale"].includes(status)) return checkPublishStatus(platform);
  return startPublishFill(platform);
}

function resetPublishContext() {
  window.WorkbenchPublishPreviews?.close();
  if (!pendingScriptId) publishNavigationSnapshot = null;
  publishContextVersion += 1;
  publishAssetMutationVersion += 1;
  publishAssets = null;
  /* Runs after activeAccountId changes, so the remembered tab always fits the account. */
  publishDraftPlatform = normalizePublishDraftPlatform(storedPublishDraftPlatform() || "douyin");
  renderPublishDraftTabs();
  for (const platform of titlePlatforms) {
    publishStatuses[platform] = cachedPublishLogin(platform);
    publishTasks[platform] = null;
    publishTaskVersions[platform] += 1;
  }
  setPublishAssetsStatus();
  publishVideoInput.value = "";
  publishPortraitCoverInput.value = "";
  publishLandscapeCoverInput.value = "";
  renderPublishAssets();
  renderPublishDraft();
}

function appendPublishAsset(form, field, asset) {
  if (!asset) return;
  if (asset.file) {
    form.append(field, asset.file, asset.name || asset.file.name);
    return;
  }
  if (asset.path) {
    form.append(`${field}Path`, asset.path);
    form.append(`${field}Name`, asset.name || "");
  }
}

const publishFetch = (...args) => fetch.apply(null, args);

async function loadPublishAssets() {
  const accountId = activeAccountId;
  const scriptId = activeScriptId;
  const contextVersion = publishContextVersion;
  const assetMutationVersion = publishAssetMutationVersion;
  if (!accountId || !scriptId) return null;
  setPublishAssetsStatus("正在同步素材…", "loading");
  renderPublishAssets();
  try {
    const response = await publishFetch(
      `/api/scripts/${encodeURIComponent(scriptId)}/publish-assets/reconcile-generated-covers`,
      { method: "POST" },
    );
    const payload = await readJson(response);
    if (!publishContextIsCurrent(accountId, scriptId, contextVersion) || assetMutationVersion !== publishAssetMutationVersion) return null;
    publishAssets = payload && typeof payload === "object" ? payload : { video: null, covers: {} };
    setPublishAssetsStatus();
    renderPublishAssets();
    window.WorkbenchScriptNavigation?.publishReady?.({accountId, scriptId});
    return publishAssets;
  } catch (error) {
    if (publishContextIsCurrent(accountId, scriptId, contextVersion) && assetMutationVersion === publishAssetMutationVersion) {
      setPublishAssetsStatus(responseMessage(error, "素材同步失败"), "error");
      renderPublishAssets();
      window.WorkbenchScriptNavigation?.publishReady?.({accountId, scriptId});
    }
    return null;
  }
}

async function savePublishAssets(
  {
    video = null,
    coverAspect = "",
    cover = null,
    successMessage = "发布素材已保存",
    failureMessage = "素材保存失败",
  } = {},
  expectedContext = null,
) {
  const accountId = expectedContext?.accountId ?? activeAccountId;
  const scriptId = expectedContext?.scriptId ?? activeScriptId;
  const contextVersion = expectedContext?.contextVersion ?? publishContextVersion;
  if (!accountId || !scriptId || pendingScriptId || publishAssetsLocked() || !publishContextIsCurrent(accountId, scriptId, contextVersion)) return null;
  const existingVideo = publishAssets?.video;
  const nextVideo = video || existingVideo;
  const covers = { ...(publishAssets?.covers || {}) };
  if (coverAspect && cover) covers[coverAspect] = cover;
  const form = new FormData();
  appendPublishAsset(form, "video", nextVideo);
  appendPublishAsset(form, "portrait", covers["3:4"]);
  appendPublishAsset(form, "landscape", covers["4:3"]);
  publishAssetMutationVersion += 1;
  const mutationVersion = publishAssetMutationVersion;
  setPublishAssetsStatus("正在保存素材…", "saving");
  renderPublishAssets();
  try {
    const response = await publishFetch(`/api/scripts/${encodeURIComponent(scriptId)}/publish-assets`, {
      method: "PUT",
      body: form,
    });
    const payload = await readJson(response);
    if (!publishContextIsCurrent(accountId, scriptId, contextVersion) || mutationVersion !== publishAssetMutationVersion) return null;
    publishAssets = payload;
    setPublishAssetsStatus(successMessage);
    showToast(successMessage, "success");
    return publishAssets;
  } catch (error) {
    if (publishContextIsCurrent(accountId, scriptId, contextVersion) && mutationVersion === publishAssetMutationVersion) {
      setPublishAssetsStatus(responseMessage(error, failureMessage), "error");
      showToast(publishAssetsStatus.textContent, "error");
    }
    return null;
  } finally {
    if (publishContextIsCurrent(accountId, scriptId, contextVersion) && mutationVersion === publishAssetMutationVersion) {
      renderPublishAssets();
    }
  }
}

function checkPublishStatus(platform, knownStatus = null) {
  const accountId = activeAccountId;
  const key = publishLoginKey(platform, accountId);
  if (!accountId || !activeScriptId || !publishPlatformAvailable(platform)) return Promise.resolve(null);
  if (publishAssetsLocked()) return Promise.resolve(publishStatuses[platform]);
  if (knownStatus) {
    publishLoginVersions.set(key, (publishLoginVersions.get(key) || 0) + 1);
    return Promise.resolve(rememberPublishLogin(platform, knownStatus, accountId));
  }
  if (publishCheckJobs.has(key)) return publishCheckJobs.get(key);
  publishLoginReturnChecks.delete(key);
  const version = (publishLoginVersions.get(key) || 0) + 1;
  publishLoginVersions.set(key, version);
  publishStatuses[platform] = { platform, status: "checking" };
  renderPublishAutomation();
  const job = (async () => {
    try {
      const response = await publishFetch(`/api/accounts/${encodeURIComponent(accountId)}/publish-status?platform=${encodeURIComponent(platform)}`);
      const payload = await readJson(response);
      if (publishLoginVersions.get(key) !== version) return null;
      return rememberPublishLogin(platform, payload, accountId);
    } catch (error) {
      if (publishLoginVersions.get(key) === version) rememberPublishLogin(platform, { status: "unknown", message: responseMessage(error, "无法检查登录状态，请手动重试") }, accountId);
      return null;
    }
  })().finally(() => publishCheckJobs.delete(key));
  publishCheckJobs.set(key, job);
  return job;
}

async function openPublishLogin(platform) {
  const accountId = activeAccountId;
  if (!accountId || !activeScriptId || !publishPlatformAvailable(platform) || publishAssetsLocked()) return null;
  const key = publishLoginKey(platform, accountId);
  const version = (publishLoginVersions.get(key) || 0) + 1;
  publishLoginVersions.set(key, version);
  publishStatuses[platform] = { platform, status: "checking" };
  renderPublishAutomation();
  try {
    const response = await publishFetch(`/api/accounts/${encodeURIComponent(accountId)}/publish-login`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ platform }),
    });
    const payload = await readJson(response);
    if (publishLoginVersions.get(key) !== version) return null;
    publishLoginReturnChecks.add(key);
    return rememberPublishLogin(platform, payload, accountId);
  } catch (error) {
    if (publishLoginVersions.get(key) === version) rememberPublishLogin(platform, { status: "unknown", message: responseMessage(error, "无法打开登录页") }, accountId);
    return null;
  }
}

function applyPublishTask(task) {
  if (!task || !titlePlatforms.includes(task.platform)) return;
  publishTasks[task.platform] = task;
  renderPublishDraft();
  renderPublishAssets();
}

async function startPublishFill(platform) {
  const accountId = activeAccountId;
  const scriptId = activeScriptId;
  const contextVersion = publishContextVersion;
  if (!accountId || !scriptId || publishPlatformControls[platform]?.fill.disabled) return null;
  const key = publishDraftBufferKey(platform);
  if (publishBusy(platform) || !publishReadiness(platform).ready) return null;
  publishPreparing.add(key);
  renderPublishDraft();
  renderPublishAssets();
  try {
    if (!await savePublishDraft(platform)) return null;
    if (!publishContextIsCurrent(accountId, scriptId, contextVersion)) return null;
    // The publish-fill endpoint performs the authoritative login check once.
    if (!publishReadiness(platform).ready) return null;
  } finally {
    publishPreparing.delete(key);
    if (publishContextIsCurrent(accountId, scriptId, contextVersion)) { renderPublishDraft(); renderPublishAssets(); }
  }
  publishTaskVersions[platform] += 1;
  const taskVersion = publishTaskVersions[platform];
  applyPublishTask({ taskId: "", platform, status: "submitting", message: "正在启动上传并填写…" });
  try {
    const response = await publishFetch(`/api/scripts/${encodeURIComponent(scriptId)}/publish-fill`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ platform }),
    });
    const task = await readJson(response);
    if (!publishContextIsCurrent(accountId, scriptId, contextVersion) || publishTaskVersions[platform] !== taskVersion) return null;
    rememberPublishLogin(platform, { status: "logged_in" }, accountId);
    applyPublishTask(task);
    if (["queued", "running"].includes(task.status)) {
      schedulePoll(
        `publish-task-${platform}`,
        () => pollPublishTask(task.taskId, platform, accountId, scriptId, taskVersion),
        1500,
      );
    }
    return task;
  } catch (error) {
    if (publishContextIsCurrent(accountId, scriptId, contextVersion) && publishTaskVersions[platform] === taskVersion) {
      if (error?.detail?.code === "publish_assets_required") setPublishAssetsStatus(responseMessage(error, "请重新关联发布素材"), "error");
      if (error?.detail?.code === "publish_login_required") rememberPublishLogin(platform, { status: "login_required" }, accountId);
      applyPublishTask({ platform, status: "failed", message: responseMessage(error, "上传并填写启动失败") });
    }
    return null;
  }
}

async function pollPublishTask(
  taskId,
  platform,
  accountId = activeAccountId,
  scriptId = activeScriptId,
  taskVersion = publishTaskVersions[platform],
  failureCount = 0,
) {
  const contextVersion = publishContextVersion;
  if (!taskId || !publishContextIsCurrent(accountId, scriptId, contextVersion) || publishTaskVersions[platform] !== taskVersion) return null;
  try {
    const response = await publishFetch(`/api/publish-tasks/${encodeURIComponent(taskId)}`);
    const task = await readJson(response);
    if (
      !publishContextIsCurrent(accountId, scriptId, contextVersion)
      || publishTaskVersions[platform] !== taskVersion
      || (publishTasks[platform]?.taskId && publishTasks[platform].taskId !== taskId)
      || task.accountId !== accountId || task.scriptId !== scriptId || task.platform !== platform
    ) return null;
    applyPublishTask(task);
    if (["queued", "running"].includes(task.status)) {
      schedulePoll(
        `publish-task-${platform}`,
        () => pollPublishTask(taskId, platform, accountId, scriptId, taskVersion, 0),
        1500,
      );
    }
    return task;
  } catch (error) {
    const currentTask = publishTasks[platform];
    if (
      publishContextIsCurrent(accountId, scriptId, contextVersion)
      && publishTaskVersions[platform] === taskVersion
      && currentTask?.taskId === taskId
      && ["queued", "running"].includes(currentTask.status)
    ) {
      const retryDelay = pollDelayFor(1500, failureCount);
      schedulePoll(
        `publish-task-${platform}`,
        () => pollPublishTask(taskId, platform, accountId, scriptId, taskVersion, failureCount + 1),
        retryDelay,
      );
    }
    return null;
  }
}

function loadPublishWorkspace() {
  loadPublishAssets();
  void ensurePublishLogin(publishDraftPlatform);
}

function titleGenerationBlockReason() {
  if (titleGenerationInFlight) return "正在生成标题，请稍候。";
  if (titleStateLoading) return "正在同步标题状态，请稍候。";
  if (!activeScript) return "请先选择脚本。";
  if (activeScript.source === "link" && !titleSourceReady) {
    return "标题和话题尚未准备好，请稍候。";
  }
  return "";
}

function applyTitleGeneration(nextGeneration) {
  const previousStatus = titleGeneration?.status || "";
  titleGeneration = nextGeneration && typeof nextGeneration === "object" ? nextGeneration : null;
  titleGenerationInFlight = titleGeneration?.status === "running";
  // 运行中→失败只提示一次；历史失败记录不再长期占用提示行。
  if (previousStatus === "running" && titleCandidateCount()) {
    const message = titleGenerationErrorMessage();
    if (message) showToast(message, "error");
  }
}

function titleGenerationErrorMessage() {
  if (!titleGeneration || !["failed", "interrupted"].includes(titleGeneration.status)) return "";
  return titleGeneration.error?.message || "标题生成失败，已保留现有结果。";
}

function clearTitleGenerationPoll() {
  titleGenerationPollTimer = cancelPoll("title-generation", titleGenerationPollTimer);
  titleGenerationPollFailures = 0;
}

function resumeTitleGenerationPolling() {
  if (!titleGenerationInFlight || titleGenerationPollTimer !== null || !activeAccountId || !activeScriptId) return;
  const accountId = activeAccountId;
  const scriptId = activeScriptId;
  const requestVersion = titleStateRequestVersion;
  titleGenerationPollTimer = schedulePoll("title-generation", () => {
    titleGenerationPollTimer = null;
    pollTitleGeneration(accountId, scriptId, requestVersion);
  }, pollDelayFor(1500, titleGenerationPollFailures));
}

async function pollTitleGeneration(accountId, scriptId, requestVersion) {
  if (activeAccountId !== accountId || activeScriptId !== scriptId || requestVersion !== titleStateRequestVersion) return;
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/title-state`);
    const payload = await readJson(response);
    if (activeAccountId !== accountId || activeScriptId !== scriptId || requestVersion !== titleStateRequestVersion) return;
    applyTitleState(payload?.state || null);
    applyTitleSource(payload?.source, payload?.sourceReady);
    applyTitleGeneration(payload?.generation || null);
    titleStateLoadError = "";
    titleGenerationPollFailures = 0;
    renderTitleState();
    resumeTitleGenerationPolling();
  } catch (error) {
    if (activeAccountId !== accountId || activeScriptId !== scriptId || requestVersion !== titleStateRequestVersion) return;
    titleStateLoadError = responseMessage(error, "标题状态读取失败，已保留当前结果。");
    titleGenerationPollFailures += 1;
    renderTitleState();
    resumeTitleGenerationPolling();
  }
}

// Transient loading states are shown on the generate button itself instead of
// the hint line, so switching scripts or refreshing never pushes the panels
// below down with a one-off status line.
function titleGenerationHintText() {
  if (titleStateLoadError) return titleStateLoadError;
  const generationError = titleGenerationErrorMessage();
  // 已有可用标题时标题区不回显历史失败，避免把旧记录误当成当前状态。
  if (generationError && !titleCandidateCount()) return generationError;
  if (titleGenerationInFlight || titleStateLoading) return "";
  return titleGenerationBlockReason();
}

function titleActionsDisabled(reason = titleGenerationBlockReason()) {
  return Boolean(reason || titleMutationKind);
}

function titleTopicsText(topics) {
  return publishInlineTopicsText(topics);
}

function publishHashtagText(topic) {
  const text = String(topic || "").trim();
  const name = text.replace(/^#+/, "").trim();
  return name ? `#${name}` : "";
}

function publishInlineTopicsText(topics) {
  return Array.isArray(topics) ? topics.map(publishHashtagText).filter(Boolean).join(" ") : "";
}

function publishDescriptionWithTopics(description, topics) {
  const text = String(description || "").trim();
  const inline = publishInlineTopicsText(topics);
  return inline ? (text ? `${text} ${inline}` : inline) : text;
}

function splitPublishDescription(text) {
  const value = String(text || "").trim();
  const tokens = value.split(/\s+/).filter(Boolean);
  const topicParts = [];
  let end = tokens.length;
  while (end > 0 && tokens[end - 1].startsWith("#")) {
    topicParts.unshift(tokens[end - 1]);
    end -= 1;
  }
  const topics = topicParts.flatMap((token) => token.split(/[，,]/)).map((topic) => topic.trim()).filter((topic) => topic.length > 1);
  return { description: tokens.slice(0, end).join(" "), topics };
}

const titlePlatforms = ["douyin", "channels"];

function platformTitleState(platform) {
  return titleState?.platforms?.[platform] || null;
}

function platformMainField(platform) {
  return platform === "channels" ? "shortTitle" : "title";
}

function titleCandidateCount() {
  return titlePlatforms.reduce((count, platform) => count + (platformTitleState(platform)?.candidates?.length || 0), 0);
}

function publishDraftBufferKey(platform, accountId = activeAccountId, scriptId = activeScriptId) {
  return accountId && scriptId ? `${accountId}:${scriptId}:${platform}` : "";
}

/* 文案平台的 Tab 选择按账号记忆。 */
function publishDraftPlatformStorageKey(accountId = activeAccountId) {
  return accountId ? `publishDraftPlatform.${accountId}.v1` : "";
}

function storedPublishDraftPlatform(accountId = activeAccountId) {
  const key = publishDraftPlatformStorageKey(accountId);
  if (!key) return "";
  try {
    const saved = localStorage.getItem(key);
    return titlePlatforms.includes(saved) ? saved : "";
  } catch (_error) {
    return "";
  }
}

function savePublishDraftPlatform(platform) {
  const key = publishDraftPlatformStorageKey();
  if (!key) return;
  try {
    localStorage.setItem(key, platform);
  } catch (_error) { /* optional preference */ }
}

/* 账号未配置的平台不能留在前台，否则打开就只剩一排禁用按钮。 */
function normalizePublishDraftPlatform(candidate = publishDraftPlatform) {
  if (titlePlatforms.includes(candidate) && publishPlatformAvailable(candidate)) return candidate;
  return titlePlatforms.find((platform) => publishPlatformAvailable(platform)) || "douyin";
}

function renderPublishDraftTabs() {
  for (const platform of titlePlatforms) {
    const tab = publishDraftTabs[platform];
    const panel = publishDraftPanels[platform];
    const active = platform === publishDraftPlatform;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    panel.hidden = !active;
  }
}

function selectPublishDraftPlatform(platform) {
  if (!titlePlatforms.includes(platform) || platform === publishDraftPlatform) return;
  void savePublishDraft(publishDraftPlatform);
  publishDraftPlatform = platform;
  void ensurePublishLogin(platform);
  savePublishDraftPlatform(platform);
  renderPublishDraftTabs();
}

function hydratePublishDraftBuffer(platform, draft, { force = false } = {}) {
  const key = publishDraftBufferKey(platform);
  if (!key) return null;
  draft = draft && typeof draft === "object" ? draft : {};
  const current = publishDraftBuffers.get(key);
  if (!current || force || !current.dirty) {
    const mainField = platformMainField(platform);
    const next = {
      main: String(draft[mainField] || ""),
      description: publishDescriptionWithTopics(draft.description, draft.topics),
      dirty: false,
    };
    publishDraftBuffers.set(key, next);
    return next;
  }
  return current;
}

function markPublishDraftDirty(platform) {
  const editor = publishDraftEditors[platform];
  const key = publishDraftBufferKey(platform);
  if (!editor || !key || pendingScriptId || titleStateLoading || (titleMutationKind && titleMutationKind !== "publish")) return;
  publishDraftBuffers.set(key, { main: editor.main.value, description: editor.description.value, dirty: true });
}

function handlePublishDraftInput(platform) {
  markPublishDraftDirty(platform);
  publishSaveErrors.delete(publishDraftBufferKey(platform));
  schedulePublishSave(platform);
  renderPublishDraft(platform);
}

function applyTitleState(nextState, { commitPublishDraftPlatform = "" } = {}) {
  titleState = nextState || null;
  titlePlatforms.forEach((platform) => {
    hydratePublishDraftBuffer(platform, platformTitleState(platform)?.publishDraft, { force: commitPublishDraftPlatform === platform });
  });
}

function applyTitleSource(nextSource, nextSourceReady) {
  titleSource = nextSource && typeof nextSource === "object" ? nextSource : null;
  titleSourceReady = typeof nextSourceReady === "boolean" ? nextSourceReady : activeScript?.source !== "link";
}

function titleMutationIsCurrent(accountId, scriptId, requestVersion, mutationVersion) {
  return activeAccountId === accountId
    && activeScriptId === scriptId
    && requestVersion === titleStateRequestVersion
    && mutationVersion === titleMutationVersion;
}

function beginTitleMutation(kind) {
  if (titleMutationKind || titleStateLoading) return null;
  titleMutationKind = kind;
  titleMutationVersion += 1;
  renderTitleMutationControls();
  return titleMutationVersion;
}

function syncTitleCandidateCards() {
  titlePlatforms.forEach((platform) => {
    const list = titleCandidateLists[platform];
    const platformState = platformTitleState(platform);
    const candidates = Array.isArray(platformState?.candidates) ? platformState.candidates : [];
    const cards = Array.from(list.children).filter((card) => card.dataset?.titleCandidate);
    if (!candidates.length) {
      if (cards.length) renderTitleCandidateGroup(platform);
      return;
    }
    if (cards.length !== candidates.length) {
      renderTitleCandidateGroup(platform);
      return;
    }
    const candidatesById = new Map(candidates.map((candidate) => [candidate.id, candidate]));
    if (cards.some((card) => !candidatesById.has(card.dataset.titleCandidate))) {
      renderTitleCandidateGroup(platform);
      return;
    }
    const disabled = Boolean(titleMutationKind || titleStateLoading);
    cards.forEach((card) => {
      const selected = card.dataset.titleCandidate === platformState.selectedId;
      card.classList.toggle("is-selected", selected);
      syncTitleCandidateSelectionBadge(card, selected);
      card.setAttribute("aria-checked", String(selected));
      card.setAttribute("aria-pressed", String(selected));
      card.setAttribute("tabindex", selected ? "0" : "-1");
      card.disabled = disabled;
      if (disabled) card.setAttribute("aria-disabled", "true");
      else card.removeAttribute("aria-disabled");
      if (titleCandidateFocusIds.get(platform) === card.dataset.titleCandidate && selected && !disabled) {
        card.focus();
        titleCandidateFocusIds.delete(platform);
      }
    });
  });
  return true;
}

function syncTitleCandidateSelectionBadge(card, selected) {
  const badge = Array.from(card.children).find((child) => child.dataset?.titleCandidateSelectionBadge === "true");
  if (selected && !badge) {
    const selectionBadge = document.createElement("em");
    selectionBadge.dataset.titleCandidateSelectionBadge = "true";
    selectionBadge.textContent = "✓ 已选中";
    card.append(selectionBadge);
  } else if (!selected && badge) {
    badge.remove();
  }
}

function renderTitleMutationControls() {
  const reason = titleGenerationBlockReason();
  titleGenerateButton.disabled = titleActionsDisabled(reason);
  titleGenerateButton.textContent = titleGenerationInFlight
    ? "正在生成标题…"
    : titleStateLoading
      ? "正在同步标题状态…"
      : titleCandidateCount() ? "重新生成标题" : "生成标题";
  const titleHint = titleGenerationHintText();
  titleGenerationHint.textContent = titleHint;
  titleGenerationHint.hidden = !titleHint;
  const candidatesSynced = syncTitleCandidateCards();
  renderPublishDraft();
  return candidatesSynced;
}

function finishTitleMutation(accountId, scriptId, requestVersion, mutationVersion) {
  if (!titleMutationIsCurrent(accountId, scriptId, requestVersion, mutationVersion)) return;
  const mutationKind = titleMutationKind;
  titleMutationKind = "";
  if (mutationKind !== "generate") titleGenerationInFlight = false;
  if (mutationKind === "selection" && renderTitleMutationControls()) return;
  renderTitleState();
}

function renderTitleCandidateGroup(platform) {
  const list = titleCandidateLists[platform];
  const group = titlePlatformGroups[platform];
  const platformState = platformTitleState(platform);
  const candidates = Array.isArray(platformState?.candidates) ? platformState.candidates : [];
  const count = document.querySelector(`#${platform}TitleCandidateCount`);
  if (count) count.textContent = `${String(candidates.length).padStart(2, "0")} 个备选`;
  const renderKey = JSON.stringify([activeAccountId, activeScriptId, candidates, titleStateLoadError]);
  group.hidden = !candidates.length;
  if (list.dataset.titleRenderKey === renderKey) {
    const cards = Array.from(list.children).filter(card => card.dataset.titleCandidate);
    cards.forEach(card => {
      const selected = card.dataset.titleCandidate === platformState.selectedId;
      card.classList.toggle("is-selected", selected);
      syncTitleCandidateSelectionBadge(card, selected);
      card.setAttribute("aria-checked", String(selected));
      card.setAttribute("aria-pressed", String(selected));
      card.setAttribute("tabindex", selected ? "0" : "-1");
      card.disabled = Boolean(titleMutationKind || titleStateLoading);
      if (card.disabled) card.setAttribute("aria-disabled", "true");
      else card.removeAttribute("aria-disabled");
      if (titleCandidateFocusIds.get(platform) === card.dataset.titleCandidate && selected && !card.disabled) {
        card.focus();titleCandidateFocusIds.delete(platform);
      }
    });
    return;
  }
  list.dataset.titleRenderKey = renderKey;
  list.replaceChildren();
  if (!candidates.length) {
    const empty = document.createElement("p");
    empty.className = "title-candidates-empty";
    empty.textContent = titleStateLoadError ? "无法同步标题状态，请重试。" : platform === "channels" ? "视频号标题待生成。" : "生成后将在这里展示三个可选标题。";
    list.append(empty);
    return;
  }
  candidates.forEach((candidate, index) => {
    const selected = candidate.id === platformState.selectedId;
    const card = document.createElement("button");
    card.type = "button";
    card.className = `title-candidate-card${selected ? " is-selected" : ""}`;
    card.dataset.titleCandidate = candidate.id;
    card.dataset.titlePlatform = platform;
    card.setAttribute("role", "radio");
    card.setAttribute("aria-checked", String(selected));
    card.setAttribute("aria-pressed", String(selected));
    card.setAttribute("tabindex", selected ? "0" : "-1");
    card.disabled = Boolean(titleMutationKind || titleStateLoading);
    const heading = document.createElement("strong");
    heading.textContent = candidate[platformMainField(platform)] || "未命名标题";
    card.append(heading);
    if (platform === "channels") {
      const description = document.createElement("span");
      description.className = "title-candidate-description";
      description.textContent = candidate.description || "未设置描述";
      card.append(description);
    }
    const topics = document.createElement("span");
    topics.textContent = titleTopicsText(candidate.topics) || "未设置话题";
    card.append(topics);
    syncTitleCandidateSelectionBadge(card, selected);
    card.addEventListener("click", () => {
      titleCandidateFocusIds.set(platform, candidate.id);
      selectTitleCandidate(platform, candidate.id);
    });
    card.addEventListener("keydown", (event) => {
      const direction = ({ ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 })[event.key];
      if (!direction || card.disabled) return;
      event.preventDefault?.();
      const next = candidates[(index + direction + candidates.length) % candidates.length];
      titleCandidateFocusIds.set(platform, next.id);
      selectTitleCandidate(platform, next.id);
    });
    list.append(card);
    if (titleCandidateFocusIds.get(platform) === candidate.id && selected && !titleMutationKind) {
      card.focus();
      titleCandidateFocusIds.delete(platform);
    }
  });
}

function renderTitleState() {
  const source = titleSource && typeof titleSource === "object" ? titleSource : null;
  const hasTitleSource = Boolean(source?.title || source?.topics?.length);
  titleSourceDetails.hidden = !hasTitleSource;
  titleSourceName.textContent = hasTitleSource ? source.title || "" : "";
  titleSourceTopics.textContent = hasTitleSource ? titleTopicsText(source.topics) : "";

  const reason = titleGenerationBlockReason();
  titleGenerateButton.disabled = titleActionsDisabled(reason);
  titleGenerateButton.textContent = titleGenerationInFlight
    ? "正在生成标题…"
    : titleStateLoading
      ? "正在同步标题状态…"
      : titleCandidateCount() ? "重新生成标题" : "生成标题";
  const titleHint = titleGenerationHintText();
  titleGenerationHint.textContent = titleHint;
  titleGenerationHint.hidden = !titleHint;

  titlePlatforms.forEach(renderTitleCandidateGroup);
  renderPublishDraft();
}

function renderPublishDraft(platform = null) {
  const platforms = platform ? [platform] : titlePlatforms;
  platforms.forEach((currentPlatform) => {
  const editor = publishDraftEditors[currentPlatform];
  const draft = platformTitleState(currentPlatform)?.publishDraft;
  const buffer = hydratePublishDraftBuffer(currentPlatform, draft);
  const disabled = !activeAccountId || !activeScriptId || Boolean(pendingScriptId || (titleMutationKind && titleMutationKind !== "publish") || titleStateLoading || publishBusy(currentPlatform));
  const draftDirty = Boolean(buffer?.dirty);
  editor.main.disabled = disabled;
  editor.description.disabled = disabled;
  editor.save.disabled = disabled || !draftDirty;
  editor.main.value = buffer?.main || "";
  editor.count.textContent = `${editor.main.value.length}/${currentPlatform === "channels" ? 16 : 30}`;
  editor.description.value = buffer?.description || "";
  const group = platformTitleState(currentPlatform);
  const hasSelectedTitle = Boolean(group?.selectedId && group?.candidates?.some((candidate) => candidate.id === group.selectedId));
  editor.restore.hidden = !hasSelectedTitle || !(draft?.isCustomized || buffer?.dirty);
  editor.restore.disabled = disabled || Boolean(titleMutationKind);
  });
  renderPublishAutomation();
}

function resetTitleStateForScript() {
  titleStateRequestVersion += 1;
  titleMutationVersion += 1;
  clearTitleGenerationPoll();
  applyTitleGeneration(null);
  titleMutationKind = "";
  titleStateLoading = false;
  titleStateLoadError = "";
  titleState = null;
  titleSource = null;
  titleSourceReady = false;
  titleCandidateFocusIds.clear();
  titleStateContext = { accountId: activeAccountId, scriptId: activeScriptId };
  renderTitleState();
}

async function loadTitleStateForScript({ serverPayload = null } = {}) {
  const scriptId = activeScriptId;
  const accountId = activeAccountId;
  if (!scriptId || !accountId) return;
  const sameContext = titleStateContext.accountId === accountId && titleStateContext.scriptId === scriptId;
  if (sameContext && (titleMutationKind && titleMutationKind !== "generate" || titleStateLoading)) return;
  clearTitleGenerationPoll();
  titleStateRequestVersion += 1;
  titleMutationVersion += 1;
  titleMutationKind = "";
  titleStateLoading = true;
  titleStateLoadError = "";
  if (!sameContext) {
    applyTitleGeneration(null);
    titleState = null;
    titleSource = null;
    titleSourceReady = false;
    titleCandidateFocusIds.clear();
  }
  titleStateContext = { accountId, scriptId };
  renderTitleState();
  const requestVersion = titleStateRequestVersion;
  try {
    const payload = serverPayload
      || await readJson(await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/title-state`));
    if (activeAccountId !== accountId || activeScriptId !== scriptId || requestVersion !== titleStateRequestVersion) return;
    applyTitleState(payload?.state || null);
    applyTitleSource(payload?.source, payload?.sourceReady);
    applyTitleGeneration(payload?.generation || null);
    titleStateLoading = false;
    titleStateLoadError = "";
    renderTitleState();
    resumeTitleGenerationPolling();
  } catch (error) {
    if (activeAccountId !== accountId || activeScriptId !== scriptId || requestVersion !== titleStateRequestVersion) return;
    titleStateLoading = false;
    titleStateLoadError = responseMessage(error, "标题状态读取失败，已保留当前结果。");
    renderTitleState();
    resumeTitleGenerationPolling();
    showToast(titleStateLoadError, "error");
  }
}

async function generateTitles() {
  // 标题生成走创作服务平台，未登录时先弹登录框，
  // 而不是让 401 变成标题区里那行「请先登录后再使用该功能。」。
  if (!(await requireWorkbenchLogin())) return;
  const reason = titleGenerationBlockReason();
  if (reason) return showToast(reason, "error");
  const scriptId = activeScriptId;
  const accountId = activeAccountId;
  const requestVersion = titleStateRequestVersion;
  const mutationVersion = beginTitleMutation("generate");
  if (mutationVersion === null) return;
  titleGenerationInFlight = true;
  renderTitleState();
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/title-generate`, { method: "POST" });
    const payload = await readJson(response);
    if (!titleMutationIsCurrent(accountId, scriptId, requestVersion, mutationVersion)) return;
    applyTitleGeneration(payload?.generation || null);
    titleStateLoadError = "";
    resumeTitleGenerationPolling();
  } catch (error) {
    if (titleMutationIsCurrent(accountId, scriptId, requestVersion, mutationVersion)) {
      applyTitleGeneration(null);
      showToast(responseMessage(error, "标题生成启动失败，已保留现有结果。"), "error");
    }
  } finally {
    finishTitleMutation(accountId, scriptId, requestVersion, mutationVersion);
  }
}

async function selectTitleCandidate(platform, candidateId) {
  if (!platformTitleState(platform) || !activeScriptId) return;
  const scriptId = activeScriptId;
  const accountId = activeAccountId;
  const requestVersion = titleStateRequestVersion;
  const mutationVersion = beginTitleMutation("selection");
  if (mutationVersion === null) return;
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/title-selection`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ platform, candidateId }),
    });
    const payload = await readJson(response);
    if (!titleMutationIsCurrent(accountId, scriptId, requestVersion, mutationVersion)) return;
    applyTitleState(payload.state || null);
  } catch (error) {
    if (titleMutationIsCurrent(accountId, scriptId, requestVersion, mutationVersion)) {
      titleCandidateFocusIds.set(platform, platformTitleState(platform)?.selectedId || "");
      showToast(responseMessage(error, "标题选择失败"), "error");
    }
  } finally {
    finishTitleMutation(accountId, scriptId, requestVersion, mutationVersion);
  }
}

async function savePublishDraft(platform) {
  const key = publishDraftBufferKey(platform);
  clearTimeout(publishSaveTimers.get(key));
  publishSaveTimers.delete(key);
  if (publishSaveJobs.has(key)) return publishSaveJobs.get(key);
  if (!titlePlatforms.includes(platform) || !activeAccountId || !activeScriptId || pendingScriptId || titleStateLoading) return false;
  const accountId = activeAccountId, scriptId = activeScriptId, requestVersion = titleStateRequestVersion;
  const current = () => activeAccountId === accountId && activeScriptId === scriptId && titleStateRequestVersion === requestVersion;
  const job = (async () => {
    // Yield so the job is registered before any rendering or synchronous completion.
    await Promise.resolve();
    while (current()) {
      if (titleMutationKind) { await new Promise(resolve => setTimeout(resolve, 50)); continue; }
      const buffer = publishDraftBuffers.get(key);
      if (!buffer?.dirty) return true;
      const errors = publishDraftValidation(platform, buffer);
      if (errors.main || errors.description) {
        publishSaveErrors.delete(key); return false;
      }
      const snapshot = { ...buffer };
      const split = splitPublishDescription(snapshot.description);
      const mutationVersion = beginTitleMutation("publish");
      try {
        const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/publish-draft`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ platform, [platformMainField(platform)]: snapshot.main.trim(), description: split.description, topics: split.topics }),
        });
        const payload = await readJson(response);
        if (!titleMutationIsCurrent(accountId, scriptId, requestVersion, mutationVersion)) return false;
        const latest = publishDraftBuffers.get(key);
        const unchanged = latest?.main === snapshot.main && latest?.description === snapshot.description;
        applyTitleState(payload.state || null, { commitPublishDraftPlatform: unchanged ? platform : "" });
        publishSaveErrors.delete(key);
      } catch (error) {
        publishSaveErrors.set(key, responseMessage(error, "文案保存失败"));
        return false;
      } finally {
        finishTitleMutation(accountId, scriptId, requestVersion, mutationVersion);
      }
    }
    return false;
  })();
  publishSaveJobs.set(key, job);
  renderPublishAutomation();
  try { return await job; }
  finally {
    publishSaveJobs.delete(key);
    if (current()) renderPublishDraft(platform);
  }
}

async function restoreSelectedTitle(platform) {
  const hasDirtyBuffer = publishDraftBuffers.get(publishDraftBufferKey(platform))?.dirty;
  if ((!platformTitleState(platform)?.publishDraft?.isCustomized && !hasDirtyBuffer) || !activeScriptId) return;
  const scriptId = activeScriptId;
  const accountId = activeAccountId;
  const requestVersion = titleStateRequestVersion;
  const mutationVersion = beginTitleMutation("restore");
  if (mutationVersion === null) return;
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/publish-draft/restore-selected-title`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ platform }),
    });
    const payload = await readJson(response);
    if (!titleMutationIsCurrent(accountId, scriptId, requestVersion, mutationVersion)) return;
    applyTitleState(payload.state || null, { commitPublishDraftPlatform: platform });
    renderTitleState();
    showToast("已恢复为已选标题", "success");
  } catch (error) {
    if (titleMutationIsCurrent(accountId, scriptId, requestVersion, mutationVersion)) showToast(responseMessage(error, "恢复标题失败"), "error");
  } finally {
    finishTitleMutation(accountId, scriptId, requestVersion, mutationVersion);
  }
}

async function openTitlePromptSettings() {
  try {
    const response = await fetch("/api/title-settings");
    const payload = await readJson(response);
    titlePromptModalInput.value = payload.systemPrompt || "";
    setModalOpen(titlePromptModal, true);
    titlePromptModalInput.focus();
  } catch (error) {
    showToast(responseMessage(error, "标题提示词读取失败"), "error");
  }
}

function closeTitlePromptSettings() {
  setModalOpen(titlePromptModal, false);
}

async function saveTitlePromptSettings() {
  try {
    const response = await fetch("/api/title-settings", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ systemPrompt: titlePromptModalInput.value.trim() }),
    });
    await readJson(response);
    closeTitlePromptSettings();
    showToast("标题提示词已保存", "success");
  } catch (error) {
    showToast(responseMessage(error, "标题提示词保存失败"), "error");
  }
}

function hasWritingStructure() {
  const structure = writingState?.structure;
  if (!structure || typeof structure !== "object") return false;
  const topic = String(structure.topic || "").trim();
  const sections = Array.isArray(structure.sections) ? structure.sections : [];
  return Boolean(topic || sections.length);
}

function hasWritingContent() {
  return Boolean(String(writingState?.content || "").trim());
}

// The 编写 stage needs a reference transcript: a legacy link task, or the
// 拆解记录 that the topic was created from.
function hasWritingSource() {
  return Boolean(activeScript && (activeScript.source === "link" || activeScript.breakdownId));
}

function currentWritingPrompt(node) {
  const stored = node === "structure" ? writingPrompts.structure : writingPrompts.content;
  return String(stored || "");
}

function currentWritingAntiSimilarity(node) {
  return writingAntiSimilarity[node] !== false;
}

function writingNodeLabel(node) {
  return node === "structure" ? "脚本结构" : "脚本内容";
}

function resetWriteContentSaveSession() {
  window.clearTimeout(writeContentSaveTimer);
  writeContentSaveTimer = null;
  writeContentSaveSession += 1;
  writeContentSavePromise = null;
  writeContentSaveInFlight = false;
  writeContentSaveQueued = false;
  writeContentDirty = false;
  writeContentSaveStatus = "已保存";
}

function scheduleWriteContentSave() {
  window.clearTimeout(writeContentSaveTimer);
  writeContentSaveTimer = window.setTimeout(() => {
    writeContentSaveTimer = null;
    saveWritingContent();
  }, 400);
}

async function saveWritingContent() {
  if (writeContentSavePromise) {
    if (writeContentDirty) writeContentSaveQueued = true;
    return writeContentSavePromise;
  }
  const pending = performWritingContentSave();
  writeContentSavePromise = pending;
  try {
    return await pending;
  } finally {
    if (writeContentSavePromise === pending) writeContentSavePromise = null;
  }
}

async function performWritingContentSave() {
  if (!activeScriptId || !hasWritingSource() || !writeContentDirty) return { saved: false };
  if (writeContentSaveInFlight) {
    writeContentSaveQueued = true;
    return { saved: false };
  }
  const scriptId = activeScriptId;
  const accountId = activeAccountId;
  const session = writeContentSaveSession;
  const content = writeContentDraft.value;
  writeContentSaveInFlight = true;
  writeContentDirty = false;
  writeContentSaveStatus = "自动保存中";
  renderWriteContentSaveState();
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/writing-content`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content }),
    });
    const payload = await readJson(response);
    if (session !== writeContentSaveSession || activeScriptId !== scriptId || activeAccountId !== accountId) {
      return { saved: false, superseded: true };
    }
    applyWritingState(payload?.state || writingState);
    writeContentSaveStatus = "已保存";
    window.onboardingModule?.refresh?.();
    renderWriteContentSaveState();
    return { saved: true };
  } catch (error) {
    if (session === writeContentSaveSession && activeScriptId === scriptId && activeAccountId === accountId) {
      writeContentDirty = true;
      writeContentSaveStatus = "保存失败";
      renderWriteContentSaveState();
      showToast(responseMessage(error, "脚本内容保存失败"), "error");
    }
    return { saved: false, error };
  } finally {
    if (session === writeContentSaveSession) writeContentSaveInFlight = false;
    if (writeContentSaveQueued && session === writeContentSaveSession) {
      writeContentSaveQueued = false;
      scheduleWriteContentSave();
    }
  }
}

function resetWritingStateForScript() {
  writingStateRequestVersion += 1;
  clearWritingGenerationPoll();
  applyWritingGeneration(null);
  writingStateLoading = false;
  writingStateLoadError = "";
  writingState = null;
  writingReferenceCopies = [];
  writingReferenceCopyIds = [];
  writingReferenceCopyDraft = [];
  closeWriteReferenceCopiesModal();
  writingPrompts = { structure: "", content: "" };
  writingAntiSimilarity = { structure: true, content: true };
  writingProfile = null;
  writingMemory = null;
  writingSourceReady = false;
  writingPromptNode = "";
  writingGenerationNode = "";
  closeWritePromptModal();
  resetWriteContentSaveSession();
  resetStructureSaveSession();
  writingContext = { accountId: activeAccountId, scriptId: activeScriptId };
  renderWritingState();
}

async function loadWritingStateForScript() {
  const scriptId = activeScriptId;
  const accountId = activeAccountId;
  if (!scriptId || !accountId) return;
  const sameContext = writingContext.accountId === accountId && writingContext.scriptId === scriptId;
  if (sameContext && (writingGenerationInFlight || writingStateLoading)) return;
  clearWritingGenerationPoll();
  writingStateRequestVersion += 1;
  writingStateLoading = true;
  writingStateLoadError = "";
  if (!sameContext) {
    applyWritingGeneration(null);
    writingState = null;
    writingPrompts = { structure: "", content: "" };
    writingAntiSimilarity = { structure: true, content: true };
    writingProfile = null;
    writingMemory = null;
    writingSourceReady = false;
    resetWriteContentSaveSession();
    resetStructureSaveSession();
    writePanelVisibility = { structure: true, content: true };
    ["structure", "content"].forEach((panelName) => setWritePanelVisible(panelName, true));
  }
  writingContext = { accountId, scriptId };
  renderWritingState();
  const requestVersion = writingStateRequestVersion;
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/writing-state`);
    const payload = await readJson(response);
    if (activeAccountId !== accountId || activeScriptId !== scriptId || requestVersion !== writingStateRequestVersion) return;
    applyWritingState(payload?.state || null);
    applyWritingPayload(payload);
    applyWritingGeneration(payload?.generation || null);
    writingStateLoading = false;
    writingStateLoadError = "";
    renderWritingState();
    resumeWritingGenerationPolling();
  } catch (error) {
    if (activeAccountId !== accountId || activeScriptId !== scriptId || requestVersion !== writingStateRequestVersion) return;
    writingStateLoading = false;
    writingStateLoadError = responseMessage(error, "编写状态读取失败，已保留当前结果。");
    renderWritingState();
    resumeWritingGenerationPolling();
    showToast(writingStateLoadError, "error");
  }
}

function applyWritingPayload(payload) {
  writingPrompts = {
    structure: payload?.prompts?.structure || "",
    content: payload?.prompts?.content || "",
  };
  writingProfile = payload?.profile && typeof payload.profile === "object" ? payload.profile : null;
  writingMemory = payload?.memory && typeof payload.memory === "object" ? payload.memory : null;
  writingAntiSimilarity = {
    structure: writingMemory?.structure?.antiSimilarity !== false,
    content: writingMemory?.content?.antiSimilarity !== false,
  };
  writingSourceReady = Boolean(payload?.source?.ready);
  writingReferenceCopies = Array.isArray(payload?.referenceCopies) ? payload.referenceCopies : [];
  const selections = payload?.selections && typeof payload.selections === "object" ? payload.selections : {};
  writingReferenceCopyIds = Array.isArray(selections.referenceCopyIds) ? selections.referenceCopyIds.map(String) : [];
  renderWriteReferenceCopies();
}

function renderWriteReferenceCopies() {
  if (!writeReferenceCopiesButton) return;
  const count = writingReferenceCopyIds.length;
  writeReferenceCopiesButton.textContent = count ? `参考爆款文案 ${count}` : "参考爆款文案";
  writeReferenceCopiesButton.disabled = !activeScriptId;
  writeReferenceCopiesButton.title = writingReferenceCopies.length
    ? "选择本篇要使用的爆款文案"
    : "还没有启用的爆款文案，可在拆解详情中收藏";
}

function renderWriteReferenceCopiesModal() {
  if (!writeReferenceCopiesList) return;
  const items = writingReferenceCopies.filter((item) => item.enabled !== false || writingReferenceCopyDraft.includes(item.id));
  for (const id of writingReferenceCopyDraft) {
    if (!items.some((item) => item.id === id)) items.push({ id, title: "已删除或无法读取，请取消选择", enabled: false });
  }
  writeReferenceCopiesList.replaceChildren(...items.map((item) => {
    const label = document.createElement("label");
    label.className = "draft-experience-option";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = item.id;
    input.checked = writingReferenceCopyDraft.includes(item.id);
    input.addEventListener("change", () => {
      if (input.checked) {
        if (!writingReferenceCopyDraft.includes(item.id)) writingReferenceCopyDraft.push(item.id);
      } else {
        writingReferenceCopyDraft = writingReferenceCopyDraft.filter((id) => id !== item.id);
      }
    });
    const text = document.createElement("span");
    text.textContent = item.title + (item.enabled === false ? "（不可用，请取消选择）" : "");
    label.append(input, text);
    return label;
  }));
  if (writeReferenceCopiesEmpty) writeReferenceCopiesEmpty.hidden = writingReferenceCopies.length > 0;
}

async function openWriteReferenceCopiesModal() {
  if (!activeScriptId) return;
  const scriptId = activeScriptId;
  const accountId = activeAccountId;
  try {
    const response = await fetch(`/api/accounts/${encodeURIComponent(accountId)}/memories`);
    const payload = await window.readJson(response);
    if (scriptId !== activeScriptId || accountId !== activeAccountId) return;
    if (payload.directoryError) throw new Error(payload.directoryError);
    writingReferenceCopies = (payload.items || []).filter((item) => item.category === "reference_copy");
  } catch (error) {
    showToast(responseMessage(error, "爆款文案读取失败"), "error");
    return;
  }
  writingReferenceCopyDraft = writingReferenceCopyIds.slice();
  renderWriteReferenceCopiesModal();
  if (writeReferenceCopiesError) writeReferenceCopiesError.hidden = true;
  if (writeReferenceCopiesModal) writeReferenceCopiesModal.hidden = false;
}

function closeWriteReferenceCopiesModal() {
  if (writeReferenceCopiesModal) writeReferenceCopiesModal.hidden = true;
}

async function saveWriteReferenceCopies() {
  const scriptId = activeScriptId;
  const accountId = activeAccountId;
  if (!scriptId || !accountId) return;
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/memory-selections`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ referenceCopyIds: writingReferenceCopyDraft.slice(0, 50) }),
    });
    const payload = await window.readJson(response);
    if (activeScriptId !== scriptId || activeAccountId !== accountId) return;
    writingReferenceCopyIds = Array.isArray(payload?.referenceCopyIds) ? payload.referenceCopyIds.map(String) : [];
    renderWriteReferenceCopies();
    closeWriteReferenceCopiesModal();
    showToast("已保存本篇使用的爆款文案", "success");
  } catch (error) {
    if (writeReferenceCopiesError) {
      writeReferenceCopiesError.textContent = responseMessage(error, "爆款文案保存失败");
      writeReferenceCopiesError.hidden = false;
    }
  }
}

function applyWritingState(nextState) {
  const previousStructure = writingState?.structure || null;
  writingState = nextState && typeof nextState === "object"
    ? {
      structure: nextState.structure && typeof nextState.structure === "object" ? nextState.structure : null,
      content: typeof nextState.content === "string" ? nextState.content : "",
    }
    : { structure: null, content: "" };
  // A buffer without unsaved edits follows the server (a finished generation,
  // another tab, a reload). Unsaved edits stay until they are written back.
  if (structureDraft && !structureDraftDirty(structureDraft) && !structureDraft.saving
    && JSON.stringify(previousStructure) !== JSON.stringify(writingState.structure)) {
    structureDraft = null;
  }
}

function applyWritingGeneration(nextGeneration) {
  writingGeneration = nextGeneration && typeof nextGeneration === "object" ? nextGeneration : null;
  writingGenerationInFlight = writingGeneration?.status === "running";
  if (writingGeneration?.node) writingGenerationNode = writingGeneration.node;
}

function writingGenerationErrorMessage() {
  if (!writingGeneration || !["failed", "interrupted"].includes(writingGeneration.status)) return "";
  return writingGeneration.error?.message || "脚本生成失败，已保留现有结果。";
}

function writingGenerationBlockReason() {
  if (writingGenerationInFlight) return "正在生成脚本，请稍候。";
  if (writingStateLoading) return "正在同步编写状态，请稍候。";
  if (!activeScript) return "请先选择脚本。";
  if (hasWritingSource() && !writingSourceReady) return "原视频文案尚未准备好，请稍候。";
  return "";
}

function clearWritingGenerationPoll() {
  writingGenerationPollTimer = cancelPoll("writing-generation", writingGenerationPollTimer);
  writingGenerationPollFailures = 0;
}

function resumeWritingGenerationPolling() {
  if (!writingGenerationInFlight || writingGenerationPollTimer !== null || !activeAccountId || !activeScriptId) return;
  const accountId = activeAccountId;
  const scriptId = activeScriptId;
  const requestVersion = writingStateRequestVersion;
  writingGenerationPollTimer = schedulePoll("writing-generation", () => {
    writingGenerationPollTimer = null;
    pollWritingGeneration(accountId, scriptId, requestVersion);
  }, pollDelayFor(1500, writingGenerationPollFailures));
}

async function pollWritingGeneration(accountId, scriptId, requestVersion) {
  if (activeAccountId !== accountId || activeScriptId !== scriptId || requestVersion !== writingStateRequestVersion) return;
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/writing-state`);
    const payload = await readJson(response);
    if (activeAccountId !== accountId || activeScriptId !== scriptId || requestVersion !== writingStateRequestVersion) return;
    const wasInFlight = writingGenerationInFlight;
    applyWritingState(payload?.state || null);
    applyWritingPayload(payload);
    applyWritingGeneration(payload?.generation || null);
    writingStateLoadError = "";
    writingGenerationPollFailures = 0;
    renderWritingState();
    notifyWritingGenerationOutcome(wasInFlight);
    resumeWritingGenerationPolling();
  } catch (error) {
    if (activeAccountId !== accountId || activeScriptId !== scriptId || requestVersion !== writingStateRequestVersion) return;
    writingStateLoadError = responseMessage(error, "编写状态读取失败，已保留当前结果。");
    writingGenerationPollFailures += 1;
    renderWritingState();
    resumeWritingGenerationPolling();
  }
}

function notifyWritingGenerationOutcome(wasInFlight) {
  if (!wasInFlight) return;
  // A finished job clears writingGeneration, so an absent record right after an
  // in-flight poll means the node finished successfully; failed/interrupted jobs
  // persist a record with an error message.
  if (!writingGeneration || writingGeneration.status === "running") {
    if (!writingGeneration) showToast(`${writingNodeLabel(writingGenerationNode)}已生成`, "success");
    return;
  }
  showToast(writingGenerationErrorMessage() || "脚本生成失败，已保留现有结果。", "error");
}

async function generateWritingNode(node, prompt) {
  if (!(await flushStructureDraft())) {
    showToast("脚本结构还有未填写或未保存的修改，请先补全。", "error");
    return false;
  }
  const reason = writingGenerationBlockReason();
  if (reason) {
    showToast(reason, "error");
    return false;
  }
  if (node === "content" && !hasWritingStructure()) {
    showToast("请先生成脚本结构，再编写脚本内容。", "error");
    return false;
  }
  const text = String(prompt ?? "").trim();
  if (!text) {
    showToast("请输入提示词后再生成。", "error");
    return false;
  }
  const antiSimilarity = currentWritingAntiSimilarity(node);
  const scriptId = activeScriptId;
  const accountId = activeAccountId;
  const requestVersion = writingStateRequestVersion;
  writingGenerationInFlight = true;
  renderWritingState();
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/writing-generate`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ node, prompt: text, antiSimilarity }),
    });
    const payload = await readJson(response);
    if (activeAccountId !== accountId || activeScriptId !== scriptId || requestVersion !== writingStateRequestVersion) return false;
    writingPrompts[node] = text;
    writingAntiSimilarity[node] = antiSimilarity;
    applyWritingGeneration(payload?.generation || null);
    writingStateLoadError = "";
    renderWritingState();
    resumeWritingGenerationPolling();
    showToast(`正在生成${writingNodeLabel(node)}…`, "info");
    return true;
  } catch (error) {
    if (activeAccountId === accountId && activeScriptId === scriptId && requestVersion === writingStateRequestVersion) {
      applyWritingGeneration(null);
      renderWritingState();
      showToast(responseMessage(error, "脚本生成启动失败，已保留现有结果。"), "error");
    }
    return false;
  }
}

const writingAssistantRetries = new Map();
window.addEventListener("writing-assistant-change", () => renderWriteGenerationControls());

async function openWritingAgent() {
  if (!window.WritingAssistants?.isConfigured()) { window.WritingAssistants?.open(); return; }
  if (writingAgentOpening) return;
  const reason = writingGenerationBlockReason() || writingStateLoadError;
  if (reason || !hasWritingStructure() || !hasWritingSource()) {
    showToast(reason || "请先生成并保存脚本结构。", "error");
    return;
  }
  const scriptId = activeScriptId;
  const accountId = activeAccountId;
  const version = writingStateRequestVersion;
  const isCurrent = () => activeScriptId === scriptId && activeAccountId === accountId && writingStateRequestVersion === version;
  // Take the re-entrancy guard before the first await so a double click cannot
  // queue two launches.
  writingAgentOpening = true;
  writeContentDraft.readOnly = true;
  renderWriteGenerationControls();
  window.clearTimeout(writeContentSaveTimer);
  writeContentSaveTimer = null;
  try {
    if (!(await flushStructureDraft())) {
      if (isCurrent()) showToast("脚本结构还有未填写或未保存的修改，请先补全。", "error");
      return;
    }
    // Wait for an existing autosave, then flush any edits queued behind it.
    while (writeContentDirty || writeContentSaveInFlight) {
      const result = await saveWritingContent();
      if (!isCurrent() || result.superseded) return;
      if (result.error || !result.saved) throw new Error("脚本内容未能保存，请保存成功后再打开助手。");
    }
    if (!isCurrent()) return;
    const retryTask = writingAssistantRetries.get(scriptId);
    const url = `/api/scripts/${encodeURIComponent(scriptId)}/writing-agent` + (retryTask ? `/${encodeURIComponent(retryTask)}/retry` : "");
    const response = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    });
    const payload = await readJson(response);
    if (payload.opened === false && payload.retryable !== false) writingAssistantRetries.set(scriptId, payload.taskId);
    else writingAssistantRetries.delete(scriptId);
    if (isCurrent()) showToast(payload.message || "请在助手中检查预填内容并手动发送。", payload.opened === false ? "error" : "info");
  } catch (error) {
    if (isCurrent()) showToast(responseMessage(error, "未能打开助手，请重试。"), "error");
  } finally {
    writingAgentOpening = false;
    writeContentDraft.readOnly = false;
    renderWriteGenerationControls();
  }
}

function renderWritePromptContext(node) {
  if (!writePromptContextList) return;
  const items = [];
  if (node === "structure") {
    items.push("原爆款脚本文案（来自拆片转写）");
  } else {
    items.push("左侧选题与脚本结构");
  }
  items.push("账号档案（商业定位 + 目标人群）");
  if (node === "content") {
    items.push(currentWritingAntiSimilarity("content")
      ? "去同质化改写约束：已开启（要求用自己的话重写，不照抄原句）"
      : "去同质化改写约束：已关闭（允许复用原视频金句，可能与原脚本雷同）");
  }
  const preferences = writingMemory?.[node]?.preferences;
  const preferenceCount = Array.isArray(preferences) ? preferences.length : 0;
  if (preferenceCount) items.push(`该环节已沉淀偏好 ${preferenceCount} 条`);
  items.push("当前提示词（下方可编辑）");
  writePromptContextList.replaceChildren(...items.map((text) => {
    const li = document.createElement("li");
    li.textContent = text;
    return li;
  }));
}

function openWritePromptModal(node) {
  if (node !== "structure" && node !== "content") return;
  const reason = writingGenerationBlockReason();
  if (reason) return showToast(reason, "error");
  if (node === "structure" && !writingSourceReady) return showToast("原视频文案尚未准备好，请稍候。", "error");
  if (node === "content" && !hasWritingStructure()) return showToast("请先生成脚本结构，再编写脚本内容。", "error");
  writingPromptNode = node;
  writingPromptSaveMode = "generate";
  const isStructure = node === "structure";
  const hasResult = isStructure ? hasWritingStructure() : hasWritingContent();
  writePromptModalTitle.textContent = `${hasResult ? "重新生成" : "生成"}${writingNodeLabel(node)}`;
  writePromptModalFieldLabel.textContent = `${writingNodeLabel(node)}提示词`;
  writePromptModalInput.value = currentWritingPrompt(node);
  saveWritePromptButton.textContent = "保存并生成";
  writePromptAntiSimilarityRow.hidden = isStructure;
  writePromptAntiSimilarityInput.checked = currentWritingAntiSimilarity(node);
  renderWritePromptContext(node);
  setModalOpen(writePromptModal, true);
  writePromptModalInput.focus();
}

function openWritePromptSettings(node) {
  if (node !== "structure" && node !== "content") return;
  writingPromptNode = node;
  writingPromptSaveMode = "save";
  writePromptModalTitle.textContent = `配置${writingNodeLabel(node)}提示词`;
  writePromptModalFieldLabel.textContent = `${writingNodeLabel(node)}提示词`;
  writePromptModalInput.value = currentWritingPrompt(node);
  saveWritePromptButton.textContent = "保存";
  writePromptAntiSimilarityRow.hidden = node === "structure";
  writePromptAntiSimilarityInput.checked = currentWritingAntiSimilarity(node);
  renderWritePromptContext(node);
  setModalOpen(writePromptModal, true);
  writePromptModalInput.focus();
}

function closeWritePromptModal() {
  writingPromptNode = "";
  writingPromptSaveMode = "generate";
  setModalOpen(writePromptModal, false);
}

async function saveWritePrompt() {
  const node = writingPromptNode;
  if (!node || !activeScriptId) return;
  const prompt = writePromptModalInput.value.trim();
  if (!prompt) return showToast("请输入提示词后再保存。", "error");
  const antiSimilarity = currentWritingAntiSimilarity(node);
  const scriptId = activeScriptId;
  const accountId = activeAccountId;
  const requestVersion = writingStateRequestVersion;
  saveWritePromptButton.disabled = true;
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/writing-prompt`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ node, prompt, antiSimilarity }),
    });
    const payload = await readJson(response);
    if (activeAccountId !== accountId || activeScriptId !== scriptId || requestVersion !== writingStateRequestVersion) return;
    writingPrompts[node] = payload?.prompt || prompt;
    writingAntiSimilarity[node] = typeof payload?.antiSimilarity === "boolean" ? payload.antiSimilarity : antiSimilarity;
    closeWritePromptModal();
    showToast(`已保存${writingNodeLabel(node)}提示词`, "success");
  } catch (error) {
    if (activeAccountId === accountId && activeScriptId === scriptId) {
      showToast(responseMessage(error, "提示词保存失败"), "error");
    }
  } finally {
    saveWritePromptButton.disabled = false;
  }
}

async function saveWritePromptAndGenerate() {
  const node = writingPromptNode;
  if (!node) return;
  const prompt = writePromptModalInput.value.trim();
  if (!prompt) return showToast("请输入提示词后再生成。", "error");
  const generated = await generateWritingNode(node, prompt);
  if (generated) closeWritePromptModal();
}

async function sinkWritingMemory(node) {
  if (!activeScriptId) return;
  const reason = writingGenerationBlockReason();
  if (reason) return showToast(reason, "error");
  if (!(await flushStructureDraft())) return showToast("脚本结构还有未填写或未保存的修改，请先补全。", "error");
  const blocked = node === "structure" ? !hasWritingStructure() : !hasWritingContent();
  if (blocked) return showToast(`当前环节还没有可沉淀的${writingNodeLabel(node)}。`, "error");
  const scriptId = activeScriptId;
  const accountId = activeAccountId;
  const requestVersion = writingStateRequestVersion;
  const input = window.prompt("请输入要保存的写作偏好，例如：开头先提问、每段只讲一个要点。请勿粘贴整篇文案。", "");
  const rule = input?.trim();
  if (!rule) return;
  if (rule.length > 4000) return showToast("写作偏好最多 4000 字。", "error");
  for (const view of structureViews) view.memoryButton.disabled = true;
  writeContentMemoryButton.disabled = true;
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/writing-memory`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ node, rule }),
    });
    const payload = await readJson(response);
    if (activeAccountId !== accountId || activeScriptId !== scriptId || requestVersion !== writingStateRequestVersion) return;
    if (!writingMemory) writingMemory = { structure: { preferences: [], promptHistory: [] }, content: { preferences: [], promptHistory: [] } };
    const target = writingMemory[node] || (writingMemory[node] = { preferences: [], promptHistory: [] });
    target.preferences = Array.isArray(payload?.preferences) ? payload.preferences : target.preferences;
    renderWritingState();
    showToast(`已沉淀${writingNodeLabel(node)}偏好`, "success");
  } catch (error) {
    if (activeAccountId === accountId && activeScriptId === scriptId) {
      showToast(responseMessage(error, "沉淀失败"), "error");
    }
  } finally {
    renderWriteGenerationControls();
  }
}

function renderWriteContentSaveState() {
  const count = writeContentDraft.value.replace(/\s/g, "").length;
  writeContentSaveState.textContent = count ? `${count} 字 · ${writeContentSaveStatus}` : "";
  writeContentSaveState.hidden = !count;
}

const structureViews = [
  {
    body: writeStructure,
    empty: writeStructureEmpty,
    promptButton: writeStructurePromptButton,
    memoryButton: writeStructureMemoryButton,
    generateButton: writeStructureGenerateButton,
    visible: () => !writeStage.hidden,
  },
  {
    body: splitStructureBody,
    empty: splitStructureEmpty,
    promptButton: splitStructurePromptButton,
    memoryButton: splitStructureMemoryButton,
    generateButton: splitStructureGenerateButton,
    visible: () => !splitStage.hidden && splitPanelTab === "structure",
  },
];

const STRUCTURE_FIELD_KEYS = ["name", "purpose", "keyPoint"];
const STRUCTURE_FIELD_CLASS = { name: "is-name", purpose: "is-purpose", keyPoint: "is-key" };
// The section number and the plain dash share one marker column, so the title,
// the purpose and the key point all start on the same left edge.
const STRUCTURE_BULLET = "–";

function structureMarkerNode(className, text) {
  const marker = document.createElement("span");
  marker.className = `write-structure-marker ${className}`;
  marker.textContent = text;
  marker.setAttribute("aria-hidden", "true");
  return marker;
}

function structureSections(source) {
  return (Array.isArray(source?.sections) ? source.sections : []).map((section) => ({
    name: String(section?.name || ""),
    purpose: String(section?.purpose || ""),
    keyPoint: String(section?.keyPoint || ""),
  }));
}

const STRUCTURE_LEADING_DASH = /^[\s\-\u2010-\u2015\uFF0D]+/;

// A dash is drawn by the panel itself, so a dash typed into the saved text
// would show up twice. Strip it once on load and let the autosave persist it.
function stripStructureDash(value) {
  const text = String(value || "");
  const stripped = text.replace(STRUCTURE_LEADING_DASH, "");
  // A dash and nothing else is the only content, so keep it as typed instead
  // of turning the line into an empty field the save would reject.
  return stripped.trim() ? stripped : text;
}

function normalizeStructureSections(sections) {
  let changed = false;
  const normalized = sections.map((section) => {
    const purpose = stripStructureDash(section.purpose);
    const keyPoint = stripStructureDash(section.keyPoint);
    if (purpose !== section.purpose || keyPoint !== section.keyPoint) changed = true;
    return { name: section.name, purpose, keyPoint };
  });
  return { sections: normalized, changed };
}

function ensureStructureDraft() {
  if (structureDraft) return structureDraft;
  const structure = writingState?.structure || null;
  const loaded = normalizeStructureSections(structureSections(structure));
  structureDraft = {
    topic: String(structure?.topic || ""),
    sections: loaded.sections,
    // A cleaned-up dash counts as an edit so the fix is written back once.
    version: loaded.changed ? 1 : 0,
    savedVersion: 0,
    saving: false,
    failed: false,
  };
  return structureDraft;
}

function structureDraftDirty(draft) {
  return Boolean(draft) && draft.version !== draft.savedVersion;
}

function structureDraftComplete(draft) {
  if (!draft) return false;
  if (!String(draft.topic || "").trim() || !draft.sections.length) return false;
  return draft.sections.every((section) =>
    STRUCTURE_FIELD_KEYS.every((key) => String(section[key] || "").trim()));
}

function structureStatusText(draft) {
  if (!draft) return "";
  if (draft.saving) return "自动保存中…";
  if (draft.failed) return "保存失败，修改已保留";
  if (!structureDraftComplete(draft)) return "填写完整后自动保存";
  if (structureDraftDirty(draft)) return "待保存…";
  return "已自动保存";
}

function renderStructureStatus() {
  for (const view of structureViews) {
    const status = view.body._statusNode;
    if (status) status.textContent = structureStatusText(view.body._inlineDraft);
  }
}

function resetStructureSaveSession() {
  window.clearTimeout(structureSaveTimer);
  structureSaveTimer = null;
  structureSaveSession += 1;
  structureSavePromise = null;
  structureDraft = null;
}

function markStructureEdit(draft) {
  draft.version += 1;
  draft.failed = false;
  renderStructureStatus();
  scheduleStructureSave();
}

function saveStructureDraftNow() {
  window.clearTimeout(structureSaveTimer);
  structureSaveTimer = null;
  saveStructureDraft();
}

function scheduleStructureSave() {
  window.clearTimeout(structureSaveTimer);
  structureSaveTimer = window.setTimeout(() => {
    structureSaveTimer = null;
    saveStructureDraft();
  }, 600);
}

function saveStructureDraft() {
  if (structureSavePromise) return structureSavePromise;
  const pending = performStructureSave();
  structureSavePromise = pending;
  const release = () => { if (structureSavePromise === pending) structureSavePromise = null; };
  pending.then(release, release);
  return pending;
}

async function performStructureSave() {
  const draft = structureDraft;
  if (!draft || !structureDraftDirty(draft) || !activeScriptId || !hasWritingSource()) {
    return { saved: false };
  }
  if (!structureDraftComplete(draft)) {
    draft.failed = false;
    renderStructureStatus();
    return { saved: false, incomplete: true };
  }
  const version = draft.version;
  const scriptId = activeScriptId;
  const accountId = activeAccountId;
  const session = structureSaveSession;
  draft.saving = true;
  renderStructureStatus();
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/writing-structure`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic: draft.topic, sections: draft.sections }),
    });
    const payload = await readJson(response);
    if (session !== structureSaveSession || activeScriptId !== scriptId || activeAccountId !== accountId) {
      return { saved: false, superseded: true };
    }
    if (structureDraft === draft) {
      draft.savedVersion = version;
      draft.failed = false;
    }
    const saved = payload?.state?.structure;
    if (saved) writingState = { ...(writingState || { content: "" }), structure: saved };
    return { saved: true };
  } catch (error) {
    if (session === structureSaveSession && activeScriptId === scriptId && activeAccountId === accountId) {
      if (structureDraft === draft) draft.failed = true;
      showToast(responseMessage(error, "脚本结构保存失败，修改已保留。"), "error");
    }
    return { saved: false, error };
  } finally {
    if (session === structureSaveSession) {
      if (structureDraft === draft) draft.saving = false;
    }
    renderStructureStatus();
    renderWriteGenerationControls();
    if (structureDraft === draft && structureDraftDirty(draft) && !draft.failed) scheduleStructureSave();
  }
}

async function flushStructureDraft() {
  window.clearTimeout(structureSaveTimer);
  structureSaveTimer = null;
  for (let attempt = 0; attempt < 5; attempt += 1) {
    if (!structureDraft || !structureDraftDirty(structureDraft)) return true;
    const result = await saveStructureDraft();
    if (result?.saved) continue;
    if (result?.superseded) return true;
    return false;
  }
  return !structureDraftDirty(structureDraft);
}

function autoGrowStructureField(field) {
  if (!field?.isConnected) return;
  field.style.height = "auto";
  field.style.height = `${field.scrollHeight}px`;
}

function regrowStructureFields() {
  for (const view of structureViews) {
    if (view.body.hidden) continue;
    for (const field of view.body.querySelectorAll(".write-structure-input")) autoGrowStructureField(field);
  }
}

let structureRegrowScheduled = false;

function scheduleStructureRegrow() {
  if (structureRegrowScheduled) return;
  structureRegrowScheduled = true;
  window.requestAnimationFrame(() => {
    structureRegrowScheduled = false;
    regrowStructureFields();
  });
}

function structureToolButton(label, ariaLabel, action) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = "write-structure-tool";
  node.textContent = label;
  node.setAttribute("aria-label", ariaLabel);
  node.addEventListener("click", action);
  return node;
}

function structureInputNode(draft, section, key, label, placeholder) {
  const input = document.createElement("textarea");
  input.className = `write-structure-input ${STRUCTURE_FIELD_CLASS[key]}`;
  input.rows = 1;
  input.spellcheck = false;
  input.value = String(section[key] || "");
  input.placeholder = placeholder;
  input.setAttribute("aria-label", label);
  input.addEventListener("input", () => {
    section[key] = input.value;
    markStructureEdit(draft);
    autoGrowStructureField(input);
  });
  input.addEventListener("blur", saveStructureDraftNow);
  return input;
}

function rebuildStructureSurface() {
  for (const view of structureViews) view.body._inlineDraft = null;
  renderWriteStructure();
}

function focusStructureSection(index) {
  const view = structureViews.find((item) => item.visible());
  view?.body._nameFields?.[index]?.focus();
}

function addStructureSection(draft, index) {
  if (draft.sections.length >= 100) return showToast("最多支持 100 段。", "error");
  draft.sections.splice(index, 0, { name: "", purpose: "", keyPoint: "" });
  markStructureEdit(draft);
  rebuildStructureSurface();
  focusStructureSection(index);
}

function removeStructureSection(draft, index) {
  if (draft.sections.length <= 1) return showToast("结构至少保留一段。", "error");
  draft.sections.splice(index, 1);
  markStructureEdit(draft);
  rebuildStructureSurface();
}

function buildStructureSection(draft, section, index, nameFields) {
  const item = document.createElement("li");
  item.className = "write-structure-item";
  const nameLine = document.createElement("div");
  nameLine.className = "write-structure-line";
  const tools = document.createElement("span");
  tools.className = "write-structure-inline-tools";
  tools.append(
    structureToolButton("＋", `在第 ${index + 1} 段后插入新段落`, () => addStructureSection(draft, index + 1)),
    structureToolButton("删除", `删除第 ${index + 1} 段`, () => removeStructureSection(draft, index)),
  );
  const nameInput = structureInputNode(draft, section, "name", `第 ${index + 1} 段标题`, "段落标题");
  nameFields.push(nameInput);
  nameLine.append(structureMarkerNode("is-index", `${index + 1}.`), nameInput, tools);
  const purposeLine = document.createElement("div");
  purposeLine.className = "write-structure-line";
  purposeLine.append(
    structureMarkerNode("is-bullet", STRUCTURE_BULLET),
    structureInputNode(draft, section, "purpose", `第 ${index + 1} 段作用说明`, "这一段的作用说明"),
  );
  const keyLine = document.createElement("div");
  keyLine.className = "write-structure-line";
  keyLine.append(
    structureMarkerNode("is-bullet", STRUCTURE_BULLET),
    structureInputNode(draft, section, "keyPoint", `第 ${index + 1} 段要点`, "这一段的要点"),
  );
  item.append(nameLine, purposeLine, keyLine);
  return item;
}

function buildStructureSurface(view, draft) {
  const nodes = [];
  const body = view.body;
  const topicRow = document.createElement("div");
  topicRow.className = "write-structure-topic";
  const topicLabel = document.createElement("span");
  topicLabel.className = "write-structure-label";
  topicLabel.textContent = "选题";
  const topicInput = document.createElement("textarea");
  topicInput.className = "write-structure-input is-topic";
  topicInput.rows = 1;
  topicInput.spellcheck = false;
  topicInput.value = String(draft.topic || "");
  topicInput.placeholder = "这条视频的选题";
  topicInput.setAttribute("aria-label", "选题");
  topicInput.addEventListener("input", () => {
    draft.topic = topicInput.value;
    markStructureEdit(draft);
    autoGrowStructureField(topicInput);
  });
  topicInput.addEventListener("blur", saveStructureDraftNow);
  topicRow.append(topicLabel, topicInput);
  nodes.push(topicRow);

  const list = document.createElement("ol");
  list.className = "write-structure-list";
  const nameFields = [];
  draft.sections.forEach((section, index) => list.append(buildStructureSection(draft, section, index, nameFields)));
  nodes.push(list);
  body._nameFields = nameFields;

  const tools = document.createElement("div");
  tools.className = "write-structure-tools";
  tools.append(structureToolButton("＋ 新增段落", "在最后新增一段", () => addStructureSection(draft, draft.sections.length)));
  nodes.push(tools);

  const status = document.createElement("p");
  status.className = "write-structure-status";
  status.textContent = structureStatusText(draft);
  body._statusNode = status;
  nodes.push(status);
  return nodes;
}

function renderWriteStructure() {
  for (const view of structureViews) {
    // Only the structure surface the user is looking at renders; the other one
    // drops its draft memo so it rebuilds from the buffer when it reappears.
    if (!view.visible()) {
      view.body.hidden = true;
      view.empty.hidden = true;
      view.body._inlineDraft = null;
      continue;
    }
    const available = Boolean(writingState?.structure) || Boolean(structureDraft);
    view.body.hidden = !available;
    view.empty.hidden = available;
    if (!available) {
      view.body._inlineDraft = null;
      continue;
    }
    const draft = ensureStructureDraft();
    if (view.body._inlineDraft !== draft) {
      view.body._inlineDraft = draft;
      view.body.replaceChildren(...buildStructureSurface(view, draft));
      for (const field of view.body.querySelectorAll(".write-structure-input")) autoGrowStructureField(field);
    }
    renderStructureStatus();
  }
}

function renderWriteContent() {
  const generating = writingGenerationInFlight && writingGeneration?.node === "content";
  if (!generating && !writeContentDirty && document.activeElement !== writeContentDraft) {
    const content = String(writingState?.content || "");
    if (writeContentDraft.value !== content) writeContentDraft.value = content;
  }
  writeContentDraft.disabled = generating;
  writeContentDraft.readOnly = writingAgentOpening;
  writeContentGenerating.hidden = !generating;
  renderWriteContentSaveState();
}

function renderWriteGenerationControls() {
  const busy = writingGenerationInFlight || writingStateLoading || writingAgentOpening;
  const structureRunning = writingGenerationInFlight && writingGeneration?.node === "structure";
  const contentRunning = writingGenerationInFlight && writingGeneration?.node === "content";
  const structureReady = writingSourceReady;
  const hasStructure = hasWritingStructure();
  const hasContent = hasWritingContent();

  for (const view of structureViews) {
    view.generateButton.disabled = busy || !structureReady;
    view.generateButton.textContent = structureRunning ? "正在生成…" : hasStructure ? "重新生成" : "生成";
    view.generateButton.title = structureReady ? "" : "原视频文案尚未准备好";
    view.memoryButton.disabled = busy || !hasStructure;
  }

  writeContentGenerateButton.disabled = busy || !hasStructure;
  writeContentGenerateButton.textContent = contentRunning ? "正在生成…" : hasContent ? "重新生成" : "生成";
  writeContentGenerateButton.title = hasStructure ? "" : "请先生成脚本结构";
  writeContentAgentButton.disabled = busy || (Boolean(window.WritingAssistants?.isConfigured()) && (!hasStructure || !writingSourceReady || Boolean(writingStateLoadError) || !hasWritingSource()));
  writeContentAgentButton.textContent = writingAgentOpening ? "正在打开…" : (window.WritingAssistants?.label() || "待配置Agent");
  renderWriteReferenceCopies();

  writeContentMemoryButton.disabled = busy || !hasContent;
}

function renderWritingState() {
  renderWriteStructure();
  renderWriteContent();
  renderWriteGenerationControls();
}

const STAGE_ORDER = ["edit", "split", "write", "title", "cover", "publish"];

function stageAvailableForScript(script, stage) {
  if (stage === "edit") return !script || script.source !== "link";
  if (stage === "split") return Boolean(script && script.source === "link" && splitStageReady);
  // The 编写 stage needs a reference transcript, which a 拆解视频 topic carries.
  if (stage === "write") return Boolean(script && (script.source === "link" || script.breakdownId) && !writeStageButton.hidden);
  return true;
}

function fallbackStageForScript(script) {
  return STAGE_ORDER.find((stage) => stageAvailableForScript(script, stage)) || "edit";
}

function effectiveStageForScript(script, stage) {
  if (stageAvailableForScript(script, stage)) return stage;
  return fallbackStageForScript(script);
}

function renderStage(stage) {
  if (!publishStage.hidden && stage !== "publish") void flushPublishDrafts();
  const editAvailable = stageAvailableForScript(activeScript, "edit");
  editStageButton.hidden = !editAvailable;
  editStageSeparator.hidden = !editAvailable;
  const activeStage = effectiveStageForScript(activeScript, stage || activeScript?.stage || "edit");
  editStage.hidden = activeStage !== "edit";
  splitStage.hidden = activeStage !== "split";
  writeStage.hidden = activeStage !== "write";
  titleStage.hidden = activeStage !== "title";
  coverStage.hidden = activeStage !== "cover";
  publishStage.hidden = activeStage !== "publish";
  if (publishStage.hidden) window.WorkbenchPublishPreviews?.close();
  if (activeStage !== "split") {
    if (!splitVideo.paused) splitVideo.pause();
    cancelSplitAnimationFrame();
    stopSplitCompatibilityPolling();
  } else {
    const videoTime = !splitVideo.hidden && Number.isFinite(Number(splitVideo.currentTime))
      ? Number(splitVideo.currentTime)
      : activeTime;
    setSplitActiveTime(videoTime);
    syncSplitVideoColumnSize();
    startSplitCompatibilityPolling(splitCompatibilityTask);
    applySplitRightPanel();
  }
  if (activeStage === "write") {
    loadWritingStateForScript();
    renderWritingState();
  }
  stageNavigator.querySelectorAll("button[data-stage]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.stage === activeStage);
  });
  renderPublishAutomation();
  if (activeStage === "publish") loadPublishWorkspace();
  // 通用扩展点：宿主渲染原生阶段时通知插件收紧自己的阶段视图（插件自身阶段不经过这里）。
  window.WorkbenchPlugins?.onHostStageRender?.(activeStage);
}

function beginWorkspaceSwitch() {
  const version = ++workspaceSwitchVersion;
  workspaceContent.classList.add("is-switching");
  workspaceContent.setAttribute("aria-busy", "true");
  workspaceLoading.hidden = false;
  return version;
}

function finishWorkspaceSwitch(version) {
  if (version !== workspaceSwitchVersion) return;
  workspaceContent.classList.remove("is-switching");
  workspaceContent.setAttribute("aria-busy", "false");
  workspaceLoading.hidden = true;
}

/* The 创作 entry owns the creation panel; the 脚本 entry owns the editor, the task card
   and the empty card. Only one of them is visible at a time. */
function renderWorkspaceView() {
  const showCreate = createViewActive;
  const isEmpty = !showCreate && workspaceView === "empty";
  const showScript = !showCreate && !isEmpty;
  form.hidden = !showCreate;
  workspaceEmpty.hidden = !isEmpty;
  taskWorkspace.hidden = !showScript;
  // An empty stage header would still consume a grid row and its gap.
  workspaceStageHeader.hidden = !showScript;
  taskStatusBar.hidden = !showScript || workspaceView === "complete";
  renderWorkspaceEmptyCopy();
}

function renderWorkspaceEmptyCopy() {
  if (workspaceEmpty.hidden) return;
  if (workspaceEmptyCopy) {
    workspaceEmptyTitle.textContent = workspaceEmptyCopy.title;
    workspaceEmptyHint.textContent = workspaceEmptyCopy.hint;
    return;
  }
  const filtered = scriptStatusFilter !== "all";
  workspaceEmptyTitle.textContent = filtered ? "当前筛选下没有脚本" : "还没有脚本";
  workspaceEmptyHint.textContent = filtered
    ? "切换到「全部」，或者去「创作」新建一条。"
    : "去「创作」写下主题和要点，生成这个账号的第一条脚本。";
}

function setDemoTaskState(state, emptyCopy = null) {
  renderDeleteScriptControl();
  if (state === "empty") {
    workspaceEmptyCopy = emptyCopy;
    workspaceView = "empty";
    renderWorkspaceView();
    return;
  }
  if (state === "processing" || state === "failed") {
    window.leaveDraftPanel?.();
    stageNavigator.hidden = true;
    stageNavigator.querySelectorAll("button[data-stage]").forEach((button) => {
      button.hidden = true;
    });
    rewriteStage.hidden = true;
    splitStage.hidden = true;
    writeStage.hidden = true;
    titleStage.hidden = true;
    coverStage.hidden = true;
    publishStage.hidden = true;
    cancelSplitAnimationFrame();
    taskStatusBar.hidden = false;
    renderTaskStatusCard(state === "failed"
      ? { phase: "failed", message: "" }
      : { phase: "submitting", message: "" });
    workspaceView = state;
    renderWorkspaceView();
    return;
  }
  if (state === "complete") {
    stageNavigator.hidden = false;
    stageNavigator.querySelectorAll("button[data-stage]").forEach((button) => {
      if (!["split", "write"].includes(button.dataset.stage)) button.hidden = false;
    });
    taskStatusBar.hidden = true;
    renderStage(activeScript?.stage || "edit");
    workspaceView = "complete";
    renderWorkspaceView();
    return;
  }
  throw new Error(`未知任务状态：${state}`);
}

function setWorkspaceAccountState(state) {
  window.workspaceAccountState = state;
  const ready = state === "ready";
  const layout = document.querySelector(".tool-layout");
  layout.hidden = !ready;
  layout.inert = !ready;
  const gate = document.querySelector("#workspaceGate");
  gate.hidden = ready;
  gate.setAttribute("aria-busy", String(state === "loading"));
  document.querySelector("#workspaceGateTitle").textContent = state === "empty" ? "创建你的工作台" : state === "error" ? "工作台读取失败" : "正在读取工作台…";
  document.querySelector("#workspaceGateDescription").textContent = state === "empty" ? "为你的创作建立一个工作台，开始管理选题、脚本和视频。" : state === "error" ? "暂时无法读取工作台，请重试。" : "请稍候，即将准备就绪。";
  document.querySelector("#workspaceGateCreate").hidden = state !== "empty";
  document.querySelector("#workspaceGateRetry").hidden = state !== "error";
  if (!ready) {
    window.resetAccountSwitcherInteraction?.();
    document.querySelector("#accountSwitcherPopover").hidden = true;
    document.querySelector("#accountSwitcherButton").setAttribute("aria-expanded", "false");
  }
}

function notifyWorkspaceAccountChange(accountId) {
  window.WorkbenchDateTimePicker?.close(false);
  for (const name of ["topicsModule", "homeModule", "onboardingModule", "reviewModule", "breakdownModule", "monitorModule", "radarModule", "settingsModule", "WorkbenchPlugins"]) {
    window[name]?.onAccountChange?.(accountId);
  }
}

function enterEmptyWorkspace() {
  accountListRequestVersion += 1;
  setWorkspaceAccountState("empty");
  activeAccountId = null;
  activeScriptId = null;
  activeScript = null;
  activeTaskId = null;
  pendingScriptId = null;
  scripts = [];
  finishWorkspaceSwitch(++workspaceSwitchVersion);
  rewritePromptRequestVersion += 1;
  invalidateLinkTaskSubmission();
  stopRewriteModelsPolling();
  resetRewriteDraftSaveSession();
  resetLinkRewriteSaveSession();
  resetSplitWorkbench();
  resetTitleStateForScript();
  resetWritingStateForScript();
  resetPublishContext();
  loadCoverStateForScript();
  window.leaveDraftPanel?.();
  window.loadDraftPanelData?.(null);
  notifyWorkspaceAccountChange(null);
  saveWorkspaceActiveSelection(null, null);
  for (const modal of [promptModal, titlePromptModal, writePromptModal, accountCreateModal, accountEditModal, coverTemplateModal, coverTemplateNameModal, accountDeleteModal]) setModalOpen(modal, false);
  document.querySelectorAll(".tool-layout video, .tool-layout audio").forEach(media => media.pause());
  createViewActive = false;
  renderAccountList();
  renderScriptList();
  setDemoTaskState("empty");
  document.querySelector("#workspaceGateCreate").focus();
}

async function loadAccounts({ awaitInitialTitleState = false } = {}) {
  const requestVersion = ++accountListRequestVersion;
  const response = await fetch("/api/accounts");
  const payload = await readJson(response);
  if (requestVersion !== accountListRequestVersion) return;
  if (!Array.isArray(payload.items)) throw new Error("工作台列表格式无效");
  accounts = payload.items;
  if (!accounts.length) {
    enterEmptyWorkspace();
    return;
  }
  const savedSelection = loadWorkspaceActiveSelection();
  const savedAccountExists = accounts.some((account) => account.id === savedSelection.accountId);
  if (!accounts.some((account) => account.id === activeAccountId)) {
    activeAccountId = (savedAccountExists ? savedSelection.accountId : accounts[0].id);
  }
  renderAccountList();
  await selectAccount(activeAccountId, savedAccountExists ? savedSelection.scriptId : "", { awaitInitialTitleState });
  if (requestVersion !== accountListRequestVersion) return;
  const wasGated = window.workspaceAccountState !== "ready";
  setWorkspaceAccountState("ready");
  if (wasGated) window.restoreWorkspaceNavigation?.();
}

async function loadAccountRewritePrompt(accountId) {
  const requestVersion = ++rewritePromptRequestVersion;
  applyRewritePromptConfig({ systemPrompt: defaultRewriteSystemPrompt });
  try {
    const response = await fetch(`/api/accounts/${encodeURIComponent(accountId)}/rewrite-prompt`);
    const payload = await readJson(response);
    if (activeAccountId !== accountId || requestVersion !== rewritePromptRequestVersion) return;
    applyRewritePromptConfig(payload);
  } catch (_error) {
    if (activeAccountId !== accountId || requestVersion !== rewritePromptRequestVersion) return;
    applyRewritePromptConfig({ systemPrompt: defaultRewriteSystemPrompt });
  }
}

async function selectAccount(accountId, preferredScriptId = "", { awaitInitialTitleState = false } = {}) {
  if (!accountId || !accounts.some(account => account.id === accountId)) return;
  if (hasPendingPublishDrafts() && !await flushPublishDrafts()) return;
  const requestedAccountId = accountId;
  /* 项目设置可能还有没保存的定位草稿：切换账号前先问过用户。 */
  if (requestedAccountId !== activeAccountId && window.settingsModule?.confirmAccountChange?.() === false) return;
  const switchVersion = beginWorkspaceSwitch();
  if (activeAccountId !== requestedAccountId) invalidateLinkTaskSubmission();
  activeAccountId = accountId;
  window.refreshAccountSwitcher?.();
  activeScriptId = null;
  activeScript = null;
  pendingScriptId = null;
  resetDeleteScriptControl();
  coverDemo.templates = [];
  resetTitleStateForScript();
  resetWritingStateForScript();
  resetPublishContext();
  saveWorkspaceActiveSelection(requestedAccountId, preferredScriptId);
  notifyWorkspaceAccountChange(requestedAccountId);
  renderPublishAutomation();
  try {
    const promptLoad = loadAccountRewritePrompt(requestedAccountId);
    await loadScripts(requestedAccountId, preferredScriptId, { awaitInitialTitleState });
    await promptLoad;
    if (activeAccountId !== requestedAccountId) return;
    renderAccountList();
  } catch (error) {
    if (activeAccountId === requestedAccountId) {
      scripts = [];
      renderScriptList("脚本读取失败");
      setDemoTaskState("empty", { title: "脚本读取失败", hint: "请稍后重试，或切换账号后再试。" });
    }
    throw error;
  } finally {
    finishWorkspaceSwitch(switchVersion);
  }
}

// External imports and bound writing returns refresh only clean owning content, never navigate.
function importedEditorSnapshot(notices) {
  if (!activeScript || !notices.some(item => item.result === 'updated' && item.scriptId === activeScriptId)) return null;
  const link = activeScript.source === 'link';
  const editor = link ? writeContentDraft : rewriteDraft;
  const baseline = link ? String(writingState?.content || '') : String(activeScript.content || '');
  return {scriptId: activeScriptId, accountId: activeAccountId, switchSequence: scriptSwitchSequence,
    source: activeScript.source, updatedAt: activeScript.updatedAt, editor, value: editor.value,
    baseline, rewriteVersion: rewriteDraftVersion, writeSession: writeContentSaveSession,
    stateVersion: writingStateRequestVersion, blocked: importedEditorBusy(link) || editor.value !== baseline};
}

function importedEditorBusy(link) {
  return link
    ? writeContentDirty || writeContentSaveInFlight || writeContentSaveQueued || writingStateLoading || writingGenerationInFlight
    : rewriteDraftDirty || rewriteDraftSaveTimer !== null || rewriteDraftState === '自动保存中';
}

function syncImportedEditor(snapshot, latest, notices) {
  if (!snapshot || !latest || pendingScriptId || activeScriptId !== snapshot.scriptId
      || activeAccountId !== snapshot.accountId || scriptSwitchSequence !== snapshot.switchSequence
      || latest.accountId !== snapshot.accountId || latest.source !== snapshot.source) return;
  const link = snapshot.source === 'link';
  const editor = snapshot.editor;
  const changed = snapshot.blocked || importedEditorBusy(link) || editor.value !== snapshot.value
    || activeScript.updatedAt !== snapshot.updatedAt || rewriteDraftVersion !== snapshot.rewriteVersion
    || writeContentSaveSession !== snapshot.writeSession || writingStateRequestVersion !== snapshot.stateVersion;
  if (changed) {
    for (const notice of notices) {
      if (notice.result === 'updated' && notice.scriptId === snapshot.scriptId) notice.editorDeferred = true;
    }
    return;
  }
  const content = String(link ? latest.writingState?.content || '' : latest.content || '');
  // Keep the per-script fallback poll in step with the global return snapshot.
  if (latest.writingAgentTask) activeScript = {...activeScript, writingAgentTask: latest.writingAgentTask};
  const selection = [editor.selectionStart, editor.selectionEnd, editor.selectionDirection];
  const scroll = [editor.scrollTop, editor.scrollLeft];
  if (link) {
    writingStateRequestVersion += 1; // Reject older writing-state reads still in flight.
    writingState = {...writingState, content};
    activeScript = {...activeScript, writingState: {...activeScript.writingState, content}, updatedAt: latest.updatedAt};
    writeContentSaveStatus = '已保存';
  } else {
    rewriteDraftVersion += 1;
    activeScript = {...activeScript, content, updatedAt: latest.updatedAt};
    rewriteDraftState = '已保存';
  }
  editor.value = content;
  editor.setSelectionRange(Math.min(selection[0], content.length), Math.min(selection[1], content.length), selection[2]);
  editor.scrollTop = scroll[0]; editor.scrollLeft = scroll[1];
  if (link) renderWriteContentSaveState();
  else renderRewriteDraft();
}

let scriptListReadSequence = 0;
let scriptListFullLoads = 0;
window.refreshImportedScriptList = async function(accountId, notices = []) {
  if (activeAccountId !== accountId) return true;
  if (scriptListFullLoads) return false;
  const editorSnapshot = notices.length ? importedEditorSnapshot(notices) : null;
  const epoch = workspaceSwitchVersion;
  const sequence = ++scriptListReadSequence;
  const response = await fetch(`/api/accounts/${encodeURIComponent(accountId)}/scripts`, {cache: 'no-store'});
  const payload = await readJson(response);
  if (activeAccountId !== accountId || workspaceSwitchVersion !== epoch) return false;
  if (sequence !== scriptListReadSequence || scriptListFullLoads) return false;
  if (!Array.isArray(payload.items)) throw new Error('invalid script list');
  const scroll = scriptList.scrollTop;
  const sidebarScroll = scriptSidebar.scrollTop;
  const focusedId = document.activeElement?.closest?.('[data-script-id]')?.dataset.scriptId;
  if (editorSnapshot) syncImportedEditor(editorSnapshot, payload.items.find(item => item.id === editorSnapshot.scriptId), notices);
  scripts = payload.items;
  renderScriptList();
  if (focusedId) {
    [...scriptList.querySelectorAll('[data-script-id]')].find(el => el.dataset.scriptId === focusedId)?.focus({preventScroll:true});
  }
  scriptList.scrollTop = scroll;
  scriptSidebar.scrollTop = sidebarScroll;
  return true;
};

async function loadScripts(accountId, preferredScriptId = null, { awaitInitialTitleState = false, isCurrent = null } = {}) {
  if (activeAccountId !== accountId) return;
  const sequence = ++scriptListReadSequence;
  scriptListFullLoads += 1;
  try {
    const requestedAccountId = accountId;
    const requestedScriptId = preferredScriptId;
    if (activeAccountId !== requestedAccountId) return;
    activeAccountId = accountId;
    window.loadDraftPanelData?.(accountId);
    renderScriptList("正在读取脚本…");
    window.WorkbenchScriptNavigation?.invalidate();
    const response = await fetch(`/api/accounts/${encodeURIComponent(activeAccountId)}/scripts`);
    const payload = await readJson(response);
    if (activeAccountId !== requestedAccountId || (pendingScriptId && pendingScriptId !== requestedScriptId)) return;
    if (sequence !== scriptListReadSequence || (isCurrent && !isCurrent())) return;
    scripts = Array.isArray(payload.items) ? payload.items : [];
    renderScriptList();
    const visible = visibleScripts();
    const preferredScriptExists = visible.some((script) => script.id === requestedScriptId);
    const activeScriptExists = visible.some((script) => script.id === activeScriptId);
    const selectedId = preferredScriptExists ? requestedScriptId : activeScriptExists ? activeScriptId : visible[0]?.id;
    if (selectedId) await selectScript(selectedId, requestedAccountId, { awaitInitialTitleState });
    else setDemoTaskState("empty");
  } finally { scriptListFullLoads -= 1; }
}

function configureBlankEditor(script) {
  activeTaskId = null;
  stopRewriteModelsPolling();
  resetRewriteDraftSaveSession();
  resetLinkRewriteSaveSession();
  resetSplitWorkbench();
  setSplitStageAvailable(false);
  setWriteStageAvailable(Boolean(script?.breakdownId));
  scriptEditorGrid.classList.add("is-blank-editor");
  sourcePanel.hidden = true;
  scrollSyncButton.hidden = true;
  generateRewritesButton.hidden = true;
  rewritePanelTitle.textContent = "";
  sourceTranscript.value = "";
  rewriteDraft.placeholder = "请输入脚本内容...";
  rewriteDraft.value = script.content || "";
  rewriteDraftState = "已保存";
  renderRewriteWarning(null);
  renderWorkspaceMetadata({ title: script.title, createdAt: script.createdAt });
}

function configureLinkEditor(task) {
  activeTaskId = task?.taskId || activeScript?.taskId || null;
  resetRewriteDraftSaveSession();
  resetLinkRewriteSaveSession();
  setSplitStageAvailable(task?.phase === "complete" && hasSplitEntryContent(task));
  setWriteStageAvailable(task?.phase === "complete" && hasSplitEntryContent(task));
  scriptEditorGrid.classList.remove("is-blank-editor");
  sourcePanel.hidden = false;
  scrollSyncButton.hidden = false;
  generateRewritesButton.hidden = false;
  rewritePanelTitle.textContent = "仿写脚本";
  rewriteDraft.placeholder = "";
  sourceTranscript.value = formatTranscriptForDisplay(task?.transcript || task?.sourceText);
  selectedRewriteModel = activeScript?.selectedRewriteModel || "text-default";
  activeRewriteModels = task?.rewrites || { "text-default": { content: task?.rewrite || "", available: Boolean(task?.rewrite), status: task?.rewriteStatus || "pending" } };
  rewriteDraft.value = rewriteModelState().content || "";
  rewriteDraftState = rewriteModelState().available ? "已保存" : "等待生成";
  renderRewriteWarning(task);
  renderWorkspaceMetadata(task || activeScript);
  renderSplitWorkbench(task);
  renderActiveRewriteModel();
  pollRewriteModels(task);
}

async function selectScript(scriptId, accountId = activeAccountId, { awaitInitialTitleState = false } = {}) {
  window.WorkbenchDateTimePicker?.close(false);
  const requestedAccountId = accountId;
  const requestedScriptId = scriptId;
  if (activeAccountId !== requestedAccountId) return;
  const switchSequence = ++scriptSwitchSequence;
  if (hasPendingPublishDrafts()) {
    window.WorkbenchScriptNavigation?.begin({accountId, scriptId}, '正在保存当前脚本…');
    if (!await flushPublishDrafts()) { if (switchSequence === scriptSwitchSequence) window.WorkbenchScriptNavigation?.finish(); return; }
  }
  if (switchSequence !== scriptSwitchSequence || activeAccountId !== requestedAccountId) return;
  publishNavigationSnapshot ||= {
    accountId: activeAccountId,
    scriptId: activeScriptId,
    assets: publishAssets,
  };
  pendingScriptId = requestedScriptId;
  const nextContext = {accountId: requestedAccountId, scriptId: requestedScriptId, stage: scripts.find(script => script.id === requestedScriptId)?.stage || "edit"};
  window.WorkbenchScriptNavigation?.begin(nextContext);
  // Preparation starts beside panel-state, never on the navigation critical path.
  try { Promise.resolve(window.WorkbenchPlugins?.prepareScriptContext?.(nextContext)).catch(() => {}); } catch (_) { /* Optional plugin hook. */ }
  resetDeleteScriptControl();
  resetWritingStateForScript();
  resetPublishContext();
  resetRewriteDraftSaveSession();
  let payload;
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/panel-state`);
    payload = await readJson(response);
    if (payload.script?.id !== requestedScriptId || payload.script?.accountId !== requestedAccountId) throw new Error("脚本归属已变化，请重新选择。");
  } catch (error) {
    if (switchSequence !== scriptSwitchSequence || activeAccountId !== requestedAccountId) return;
    window.WorkbenchScriptNavigation?.fail(nextContext, () => selectScript(scriptId, accountId).catch(() => {}));
    throw error;
  }
  if (
    switchSequence !== scriptSwitchSequence
    || activeAccountId !== requestedAccountId
    || pendingScriptId !== requestedScriptId
    || payload.script?.accountId !== requestedAccountId
  ) return;
  activeScriptId = scriptId;
  activeScript = payload.script;
  if (activeScript.source === "link" && payload.task?.phase === "failed") {
    activeScript = { ...activeScript, processingStatus: "failed" };
    scripts = scripts.map((script) => script.id === activeScript.id ? activeScript : script);
  }
  pendingScriptId = null;
  resetDeleteScriptControl();
  publishNavigationSnapshot = null;
  loadCoverStateForScript({ serverPayload: payload.coverState });
  const initialTitleStateLoad = loadTitleStateForScript({ serverPayload: payload.titleState });
  saveWorkspaceActiveSelection(requestedAccountId, requestedScriptId);
  renderPublishAutomation();
  if (activeScript.source === "link") {
    activeTaskId = activeScript.taskId;
    const task = payload.task || { taskId: activeTaskId, phase: "queued", message: "任务已创建，等待处理。" };
    const failed = activeScript.processingStatus === "failed" || task.phase === "failed";
    const ready = activeScript.processingStatus === "ready" && task.phase === "complete";
    if (failed) {
      setDemoTaskState("failed");
      renderTaskStatusCard({ ...task, phase: "failed" });
    } else if (!ready) {
      setDemoTaskState("processing");
      renderTaskStatusCard(task);
      pollTask(activeTaskId, requestedScriptId, requestedAccountId).catch((error) => {
        if (isCurrentLinkTaskContext(requestedAccountId, requestedScriptId)) finishTaskFailure(error);
      });
    } else {
      configureLinkEditor(task);
      resetEditorScrollPositions();
      renderRewriteDraft();
      setDemoTaskState("complete");
    }
  } else {
    configureBlankEditor(activeScript);
    resetEditorScrollPositions();
    renderRewriteDraft();
    setDemoTaskState("complete");
  }
  renderScriptList();
  window.WorkbenchScriptNavigation?.finish();
  if (awaitInitialTitleState) await initialTitleStateLoad;
}

async function pollTask(taskId, scriptId, accountId) {
  if (activeAccountId !== accountId || activeScriptId !== scriptId || pendingScriptId && pendingScriptId !== scriptId) return;
  const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}`);
  const task = await readJson(response);
  if (activeAccountId !== accountId || activeScriptId !== scriptId || pendingScriptId && pendingScriptId !== scriptId) return;
  renderTaskStatusCard(task);
  await loadTitleStateForScript();
  if (activeAccountId !== accountId || activeScriptId !== scriptId || pendingScriptId && pendingScriptId !== scriptId) return;
  if (["queued", "downloading", "preparing_audio", "uploading_audio", "transcribing", "rewriting"].includes(task.phase)) {
    schedulePoll("link-task", () => pollTask(taskId, scriptId, accountId).catch((error) => {
      if (activeAccountId === accountId && activeScriptId === scriptId) finishTaskFailure(error);
    }), 1500);
    return;
  }
  if (task.phase === "complete") {
    await loadScripts(accountId, scriptId);
    return;
  }
  if (activeAccountId === accountId && activeScriptId === scriptId) finishTaskFailure(task);
}

function finishTaskFailure(error) {
  const message = responseMessage(error, "处理失败，请检查配置和链接后重试。");
  if (activeScript?.source === "link") {
    activeScript = { ...activeScript, processingStatus: "failed" };
    scripts = scripts.map((item) => item.id === activeScript.id ? activeScript : item);
    renderScriptList();
  }
  setDemoTaskState("failed");
  renderTaskStatusCard({ ...error, phase: "failed", message });
  showToast(message, "error");
}

/* 创作 is a first-class sidebar entry, so this only navigates there and starts a fresh
   creation draft: the script that is open in 脚本 stays selected. */
function openNewTaskForm() {
  hideScriptStatusMenus();
  invalidateLinkTaskSubmission();
  // The sidebar hook re-enters the 创作 view through the module-change listener.
  if (window.selectWorkspaceModule) window.selectWorkspaceModule("create");
  else enterCreateView();
  const topicInput = document.querySelector("#draftTopicInput");
  window.requestAnimationFrame(() => topicInput?.focus());
}

function enterCreateView() {
  createViewActive = true;
  renderWorkspaceView();
  window.enterDraftPanel?.();
}

/* Clear everything that describes the script the editor had open. */
function resetActiveScriptSelection() {
  activeScriptId = null;
  activeScript = null;
  activeTaskId = null;
  pendingScriptId = null;
  resetDeleteScriptControl();
  renderScriptWorkflowStatusControl();
  resetTitleStateForScript();
  resetWritingStateForScript();
  resetPublishContext();
  saveWorkspaceActiveSelection(activeAccountId, null);
}

function renderDeleteScriptControl() {
  const canDelete = hasWorkspaceScriptActions();
  const armed = canDelete && deleteScriptArmedFor === activeScriptId;
  deleteScriptButton.hidden = !canDelete;
  deleteScriptButton.disabled = !canDelete || Boolean(pendingScriptId);
  deleteScriptButton.textContent = armed ? "确认删除" : "删除";
  deleteScriptButton.classList.toggle("is-armed", armed);
  deleteScriptButton.setAttribute("aria-label", armed ? "再次点击确认删除当前脚本" : "删除当前脚本");
  // 新建脚本 navigates to the 创作 entry; it is the only way back while a script is open.
  newScriptButton.hidden = false;
  scriptActionsButton.disabled = !canDelete || Boolean(pendingScriptId) || scriptMoveInFlight;
  if (scriptActionsButton.disabled) setScriptActionsOpen(false);
  renderScriptWorkflowStatusControl();
  renderMoveScriptControl();
}

function hasWorkspaceScriptActions() {
  // Keep the toolbar geometry stable while the replacement script loads.
  // Pending selections disable actions instead of removing them from the row.
  if (!activeScriptId || !activeScript) return false;
  return activeScript.source !== "link" || activeScript.processingStatus === "ready";
}

function resetDeleteScriptControl() {
  setScriptActionsOpen(false);
  deleteScriptArmedFor = null;
  renderDeleteScriptControl();
}

async function deleteCurrentScript() {
  if (!activeScriptId || !activeScript || pendingScriptId) return;
  const accountId = activeAccountId;
  const scriptId = activeScriptId;
  if (deleteScriptArmedFor !== scriptId) {
    deleteScriptArmedFor = scriptId;
    renderDeleteScriptControl();
    return;
  }
  deleteScriptButton.disabled = true;
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}`, { method: "DELETE" });
    await readJson(response);
    if (activeAccountId !== accountId || activeScriptId !== scriptId) return;
    localStorage.removeItem(`coverScriptState.${scriptId}.v1`);
    scripts = scripts.filter((script) => script.id !== scriptId);
    sortScriptsByCreated();
    const nextScriptId = scripts[0]?.id;
    resetActiveScriptSelection();
    if (nextScriptId) await selectScript(nextScriptId, accountId);
    else {
      renderScriptList();
      setDemoTaskState("empty");
    }
    showToast("脚本已删除", "success");
  } catch (error) {
    if (activeAccountId === accountId && activeScriptId === scriptId) {
      resetDeleteScriptControl();
      showToast(responseMessage(error, "删除脚本失败"), "error");
    }
  } finally {
    if (activeAccountId === accountId && activeScriptId === scriptId) renderDeleteScriptControl();
  }
}

async function moveCurrentScript(targetAccountId) {
  if (scriptMoveInFlight || !activeScriptId || !activeScript || pendingScriptId || !targetAccountId || targetAccountId === activeAccountId) return;
  const sourceAccountId = activeAccountId;
  const scriptId = activeScriptId;
  scriptMoveInFlight = true;
  renderDeleteScriptControl();
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/account`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ targetAccountId }),
    });
    const moved = await readJson(response);
    if (activeAccountId !== sourceAccountId || activeScriptId !== scriptId || pendingScriptId) return;
    hideScriptStatusMenus();
    await selectAccount(moved.accountId, scriptId);
    if (activeAccountId === moved.accountId && activeScriptId === scriptId) showToast("脚本已移动", "success");
  } catch (error) {
    if (activeAccountId === sourceAccountId && activeScriptId === scriptId) showToast(responseMessage(error, "移动脚本失败"), "error");
  } finally {
    scriptMoveInFlight = false;
    renderDeleteScriptControl();
  }
}

function normalizeRewritePromptConfig(payload = {}) {
  const selectedTemplateId = ["general", "retention", "story"].includes(payload.selectedTemplateId)
    ? payload.selectedTemplateId
    : "general";
  const sourceTemplates = Array.isArray(payload.templates) ? payload.templates : [];
  const templates = defaultRewritePromptTemplates.map((fallback) => {
    const saved = sourceTemplates.find((template) => template?.id === fallback.id);
    const content = String(
      saved?.systemPrompt || (fallback.id === selectedTemplateId ? payload.systemPrompt : fallback.systemPrompt) || "",
    ).trim();
    return { ...fallback, systemPrompt: content || fallback.systemPrompt };
  });
  const systemPrompt = templates.find((template) => template.id === selectedTemplateId)?.systemPrompt || defaultRewriteSystemPrompt;
  return { templates, selectedTemplateId, systemPrompt };
}

function applyRewritePromptConfig(payload) {
  const config = normalizeRewritePromptConfig(payload);
  rewritePromptTemplates = config.templates;
  selectedRewritePromptTemplateId = config.selectedTemplateId;
  promptModalTemplateId = config.selectedTemplateId;
  activeSystemPrompt = config.systemPrompt;
}

function rewritePromptTemplate(templateId = promptModalTemplateId) {
  return rewritePromptTemplates.find((template) => template.id === templateId) || rewritePromptTemplates[0];
}

function renderRewritePromptTemplateTabs() {
  for (const tab of rewritePromptTemplateTabs) {
    const active = tab.dataset.rewritePromptTemplate === promptModalTemplateId;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  }
}

function selectRewritePromptTemplate(templateId) {
  const nextTemplate = rewritePromptTemplate(templateId);
  if (!nextTemplate || nextTemplate.id === promptModalTemplateId) return;
  const currentTemplate = rewritePromptTemplate();
  if (
    currentTemplate
    && promptModalInput.value !== currentTemplate.systemPrompt
    && !window.confirm("当前模板有未保存修改，切换后将丢失。是否继续？")
  ) return;
  promptModalTemplateId = nextTemplate.id;
  promptModalInput.value = nextTemplate.systemPrompt;
  renderRewritePromptTemplateTabs();
  promptModalInput.focus();
}

function openPromptSettings() {
  promptModalTemplateId = selectedRewritePromptTemplateId;
  promptModalInput.value = rewritePromptTemplate()?.systemPrompt || activeSystemPrompt;
  renderRewritePromptTemplateTabs();
  setModalOpen(promptModal, true);
  promptModalInput.focus();
}

function closePromptSettings() {
  promptModalTemplateId = selectedRewritePromptTemplateId;
  promptModalInput.value = rewritePromptTemplate()?.systemPrompt || activeSystemPrompt;
  renderRewritePromptTemplateTabs();
  setModalOpen(promptModal, false);
}

async function saveAccountRewritePrompt() {
  if (!activeAccountId) return showToast("请先选择账号", "error");
  const accountId = activeAccountId;
  const systemPrompt = promptModalInput.value.trim();
  savePromptButton.disabled = true;
  try {
    const response = await fetch(`/api/accounts/${encodeURIComponent(accountId)}/rewrite-prompt`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ templateId: promptModalTemplateId, systemPrompt }),
    });
    const payload = await readJson(response);
    if (activeAccountId !== accountId) return;
    applyRewritePromptConfig(payload);
    closePromptSettings();
    showToast("提示词已保存", "success");
  } catch (error) {
    if (activeAccountId === accountId) showToast(responseMessage(error, "提示词保存失败"), "error");
  } finally {
    savePromptButton.disabled = false;
  }
}

function toggleAccountSidebar() {
  const layout = document.querySelector(".tool-layout");
  const collapsed = !layout.classList.contains("is-account-collapsed");
  accountSidebarContentRevealCleanup?.();
  accountSidebarContentRevealCleanup = null;
  if (collapsed) {
    cancelAccountDeleteHold();
    closeAccountDeleteReveal();
    layout.classList.add("is-account-sidebar-content-hidden");
    layout.classList.add("is-account-collapsed");
    window.revealActiveWorkspaceNavigation?.();
  } else {
    layout.classList.remove("is-account-collapsed");
    if (window.matchMedia?.("(min-width: 901px) and (prefers-reduced-motion: no-preference)")?.matches) {
      const revealTimer = window.setTimeout(() => {
        accountSidebarContentRevealCleanup = null;
        layout.classList.remove("is-account-sidebar-content-hidden");
      }, 120);
      accountSidebarContentRevealCleanup = () => window.clearTimeout(revealTimer);
    } else {
      layout.classList.remove("is-account-sidebar-content-hidden");
    }
  }
  toggleAccountSidebarButton.setAttribute("aria-label", collapsed ? "展开账号栏" : "收起账号栏");
  toggleAccountSidebarButton.title = collapsed ? "展开账号栏" : "收起账号栏";
  localStorage.setItem("accountSidebarCollapsed", String(collapsed));
}

function restoreAccountSidebar() {
  // A saved "false" is the only explicit request to keep the full rail open.
  // Missing, empty, or legacy values fall back to the compact rail.
  const collapsed = localStorage.getItem("accountSidebarCollapsed") !== "false";
  const layout = document.querySelector(".tool-layout");
  layout.classList.toggle("is-account-collapsed", collapsed);
  layout.classList.toggle(
    "is-account-sidebar-content-hidden",
    collapsed && window.matchMedia?.("(min-width: 901px) and (prefers-reduced-motion: no-preference)")?.matches === true,
  );
  toggleAccountSidebarButton.setAttribute("aria-label", collapsed ? "展开账号栏" : "收起账号栏");
  toggleAccountSidebarButton.title = collapsed ? "展开账号栏" : "收起账号栏";
}

async function createBlankScript() {
  if (!activeAccountId) return showToast("请先选择账号", "error");
  const accountId = activeAccountId;
  newScriptButton.disabled = true;
  try {
    const response = await fetch(`/api/accounts/${encodeURIComponent(accountId)}/scripts`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    });
    const script = await readJson(response);
    if (activeAccountId !== accountId) return;
    activeScriptId = script.id;
    loadCoverStateForScript();
    resetTitleStateForScript();
    resetWritingStateForScript();
    resetPublishContext();
    await loadScripts(accountId, script.id);
    showToast("空白脚本已创建", "success");
  } catch (error) {
    showToast(responseMessage(error, "创建空白脚本失败"), "error");
  } finally {
    newScriptButton.disabled = false;
  }
}

function applyLinkedTaskSelection(task, script) {
  activeTaskId = task.taskId;
  activeScriptId = script.id;
  activeScript = script;
  pendingScriptId = null;
  resetDeleteScriptControl();
  loadCoverStateForScript();
  loadTitleStateForScript();
  resetPublishContext();
  saveWorkspaceActiveSelection(activeAccountId, activeScriptId);
  scripts = [script, ...scripts.filter((item) => item.id !== script.id)];
  renderScriptList();
  setDemoTaskState("processing");
  renderTaskStatusCard(task);
}

async function retryFailedTask() {
  if (!activeScriptId || activeScript?.source !== "link" || activeScript.processingStatus !== "failed") return;
  const accountId = activeAccountId;
  const scriptId = activeScriptId;
  retryTaskButton.disabled = true;
  deleteTaskButton.disabled = true;
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/retry`, { method: "POST" });
    const payload = await readJson(response);
    if (activeAccountId !== accountId || activeScriptId !== scriptId || !payload.script || !payload.taskId) return;
    applyLinkedTaskSelection(payload, payload.script);
    await pollTask(payload.taskId, scriptId, accountId);
  } catch (error) {
    if (activeAccountId === accountId && activeScriptId === scriptId) {
      showToast(responseMessage(error, "重试任务失败"), "error");
    }
  } finally {
    retryTaskButton.disabled = false;
    deleteTaskButton.disabled = false;
  }
}

async function deleteFailedTask() {
  if (!activeScriptId || activeScript?.source !== "link" || activeScript.processingStatus !== "failed") return;
  const accountId = activeAccountId;
  const scriptId = activeScriptId;
  retryTaskButton.disabled = true;
  deleteTaskButton.disabled = true;
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/task`, { method: "DELETE" });
    await readJson(response);
    if (activeAccountId !== accountId || activeScriptId !== scriptId) return;
    scripts = scripts.filter((item) => item.id !== scriptId);
    resetActiveScriptSelection();
    renderScriptList();
    const nextScriptId = scripts[0]?.id;
    if (nextScriptId) await selectScript(nextScriptId, accountId);
    else setDemoTaskState("empty", { title: "已删除这条失败任务", hint: "去「创作」新建一条脚本。" });
    showToast("失败任务已删除", "success");
  } catch (error) {
    if (activeAccountId === accountId && activeScriptId === scriptId) {
      showToast(responseMessage(error, "删除任务失败"), "error");
    }
  } finally {
    retryTaskButton.disabled = false;
    deleteTaskButton.disabled = false;
  }
}

stageNavigator.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-stage]");
  if (!button || !activeScriptId || pendingScriptId) return;
  const scriptId = activeScriptId;
  const stage = button.dataset.stage;
  const requestVersion = (stageRequestVersions.get(scriptId) || 0) + 1;
  stageRequestVersions.set(scriptId, requestVersion);
  button.disabled = true;
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(activeScriptId)}/stage`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ stage }),
    });
    const script = await readJson(response);
    if (activeScriptId !== scriptId || pendingScriptId || stageRequestVersions.get(scriptId) !== requestVersion) return;
    activeScript = script;
    scripts = scripts.map((item) => item.id === script.id ? script : item);
    window.WorkbenchPlugins?.clearStageSelection?.();
    renderStage(script.stage || stage);
    renderScriptList();
  } catch (error) {
    if (activeScriptId === scriptId && !pendingScriptId && stageRequestVersions.get(scriptId) === requestVersion) {
      showToast(responseMessage(error, "阶段保存失败"), "error");
    }
  } finally {
    button.disabled = false;
  }
});

newTaskButton.addEventListener("click", openNewTaskForm);
toggleAccountSidebarButton.addEventListener("click", toggleAccountSidebar);

function openAccountCreateModal() {
  accountNameInput.value = "";
  document.querySelector('[name="onboardingStage"][value="existing"]').checked = true;
  setModalOpen(accountCreateModal, true);
  accountNameInput.focus();
}
newAccountButton.addEventListener("click", openAccountCreateModal);
document.querySelector("#workspaceGateCreate").addEventListener("click", openAccountCreateModal);
document.querySelector("#workspaceGateRetry").addEventListener("click", () => bootstrapWorkspace());

document.querySelector("#closeAccountCreateButton").addEventListener("click", () => setModalOpen(accountCreateModal, false));
cancelAccountCreateButton.addEventListener("click", () => setModalOpen(accountCreateModal, false));
cancelAccountDeleteButton.addEventListener("click", closeAccountDeleteModal);
confirmAccountDeleteButton.addEventListener("click", () => confirmAccountDeletion());
cancelAccountEditButton.addEventListener("click", closeAccountEditModal);
saveAccountEditButton.addEventListener("click", () => saveAccountEdit());
saveAccountCreateButton.addEventListener("click", async () => {
  const name = accountNameInput.value.trim();
  if (!name) return showToast("请填写工作台名称", "error");
  saveAccountCreateButton.disabled = true;
  try {
    const response = await fetch("/api/accounts", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, onboardingStage: document.querySelector('[name="onboardingStage"]:checked')?.value || "existing" }),
    });
    const account = await readJson(response);
    const wasEmpty = window.workspaceAccountState === "empty";
    activeAccountId = account.id;
    activeScriptId = null;
    setModalOpen(accountCreateModal, false);
    await loadAccounts();
    if (wasEmpty) window.selectWorkspaceModule?.("today");
    showToast("工作台已创建", "success");
    try {
      await window.onboardingModule?.accountCreated?.(account);
    } catch (error) {
      showToast(responseMessage(error, "工作台已创建，起步引导暂时无法打开，请在首页重试"), "error");
    }
  } catch (error) {
    showToast(responseMessage(error, "创建工作台失败"), "error");
  } finally {
    saveAccountCreateButton.disabled = false;
  }
});

scriptActionsButton.addEventListener("click", () => {
  if (scriptActionsButton.disabled) return;
  const open = scriptActionsPanel.hidden;
  hideScriptStatusMenus();
  setScriptActionsOpen(open);
  if (open) scriptWorkflowStatusButton.focus();
});
// WebKit does not focus buttons on pointer activation. Keep focus inside
// this menu before its deferred focusout handler can close it mid-click.
scriptActionsControl.addEventListener("pointerdown", (event) => {
  const button = event.target.closest?.("button");
  if (event.button !== 0 || !button || button.disabled || !scriptActionsControl.contains(button)) return;
  event.preventDefault();
  button.focus({ preventScroll: true });
});
scriptActionsControl.addEventListener("focusout", () => {
  window.setTimeout(() => {
    if (!scriptActionsControl.contains(document.activeElement)) setScriptActionsOpen(false);
  }, 0);
});
newScriptButton.addEventListener("click", openNewTaskForm);
retryTaskButton.addEventListener("click", () => retryFailedTask());
deleteTaskButton.addEventListener("click", () => deleteFailedTask());
deleteScriptButton.addEventListener("click", () => deleteCurrentScript());
scriptStatusFilterButton.addEventListener("click", () => {
  setScriptStatusMenuOpen(scriptStatusFilterControl, scriptStatusFilterButton, scriptStatusFilterMenu, scriptStatusFilterMenu.hidden);
});
scriptStatusFilterMenu.addEventListener("click", (event) => {
  const option = event.target.closest?.("[data-script-status-filter]");
  if (option) selectScriptStatusFilter(option.dataset.scriptStatusFilter);
});
scriptWorkflowStatusButton.addEventListener("click", () => {
  if (scriptWorkflowStatusButton.disabled) return;
  setScriptStatusMenuOpen(scriptMoveControl, scriptMoveButton, scriptMoveMenu, false);
  setScriptStatusMenuOpen(scriptWorkflowStatusControl, scriptWorkflowStatusButton, scriptWorkflowStatusMenu, scriptWorkflowStatusMenu.hidden);
});
scriptWorkflowStatusMenu.addEventListener("click", async (event) => {
  const option = event.target.closest?.("[data-workflow-status]");
  const status = option?.dataset.workflowStatus;
  if (!status || !workflowStatusLabels[status] || !activeScriptId || !activeScript || pendingScriptId) return;
  const scriptId = activeScriptId;
  const accountId = activeAccountId;
  scriptWorkflowStatusButton.disabled = true;
  try {
    const response = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/workflow-status`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ workflowStatus: status }),
    });
    const saved = await readJson(response);
    window.topicsModule?.invalidate?.();
    if (activeAccountId !== accountId || activeScriptId !== scriptId || pendingScriptId) return;
    activeScript = saved;
    scripts = scripts.map((script) => script.id === saved.id ? saved : script);
    hideScriptStatusMenus();
    renderScriptWorkflowStatusControl();
    const visible = visibleScripts();
    renderScriptList();
    if (!visible.some((script) => script.id === scriptId)) {
      if (visible[0]) await selectScript(visible[0].id, accountId);
      else {
        resetActiveScriptSelection();
        setDemoTaskState("empty");
      }
    }
    showToast("运营状态已更新", "success");
  } catch (error) {
    if (activeAccountId === accountId && activeScriptId === scriptId) showToast(responseMessage(error, "运营状态保存失败"), "error");
  } finally {
    if (activeAccountId === accountId && activeScriptId === scriptId) renderScriptWorkflowStatusControl();
  }
});
scriptMoveButton.addEventListener("click", () => {
  if (scriptMoveButton.disabled) return;
  setScriptStatusMenuOpen(scriptWorkflowStatusControl, scriptWorkflowStatusButton, scriptWorkflowStatusMenu, false);
  setScriptStatusMenuOpen(scriptMoveControl, scriptMoveButton, scriptMoveMenu, scriptMoveMenu.hidden);
});
scriptMoveMenu.addEventListener("click", (event) => {
  const option = event.target.closest?.("[data-move-account-id]");
  if (!option || option.disabled) return;
  moveCurrentScript(option.dataset.moveAccountId);
});
wireScriptStatusMenuDismissal(scriptStatusFilterControl, scriptStatusFilterMenu);


scrollSyncButton.addEventListener("click", () => { isScrollSyncLocked = !isScrollSyncLocked; renderScrollSyncControl(); });
rewritePromptTemplateTabs.forEach((tab) => {
  tab.addEventListener("click", () => selectRewritePromptTemplate(tab.dataset.rewritePromptTemplate));
});
cancelPromptButton.addEventListener("click", closePromptSettings);
savePromptButton.addEventListener("click", saveAccountRewritePrompt);
titlePromptSettingsButton.addEventListener("click", openTitlePromptSettings);
titleGenerateButton.addEventListener("click", generateTitles);
document.querySelector("#closeTitlePromptButton").addEventListener("click", closeTitlePromptSettings);
cancelTitlePromptButton.addEventListener("click", closeTitlePromptSettings);
saveTitlePromptButton.addEventListener("click", saveTitlePromptSettings);
for (const platform of titlePlatforms) {
  const editor = publishDraftEditors[platform];
  publishDraftTabs[platform].addEventListener("click", () => selectPublishDraftPlatform(platform));
  editor.save.addEventListener("click", () => savePublishDraft(platform));
  editor.restore.addEventListener("click", () => restoreSelectedTitle(platform));
  editor.main.addEventListener("input", () => handlePublishDraftInput(platform));
  editor.description.addEventListener("input", () => handlePublishDraftInput(platform));
  const controls = publishPlatformControls[platform];
  controls.fill.addEventListener("click", () => handlePublishAction(platform));
}

function publishDropFileIsValid(file, kind) {
  const rules = PUBLISH_DROP_FILE_RULES[kind];
  const name = typeof file?.name === "string" ? file.name : "";
  const extension = name.slice(name.lastIndexOf(".")).toLowerCase();
  const contentType = String(file?.type || "").split(";", 1)[0].trim().toLowerCase();
  return Boolean(rules?.extensions.includes(extension) && rules.mimeTypes[extension]?.includes(contentType));
}

function publishDropError(kind, message) {
  showToast(message || `请拖入支持的${PUBLISH_DROP_FILE_RULES[kind].label}文件。`, "error");
}

async function savePublishAssetFile(file, buildChange) {
  if (!file) return;
  const selectionContext = {
    accountId: activeAccountId,
    scriptId: activeScriptId,
    contextVersion: publishContextVersion,
  };
  try {
    await Promise.resolve();
    if (pendingScriptId || !publishContextIsCurrent(
      selectionContext.accountId,
      selectionContext.scriptId,
      selectionContext.contextVersion,
    )) return;
    await savePublishAssets(buildChange({ name: file.name, file }), selectionContext);
  } catch (error) {
    if (publishContextIsCurrent(
      selectionContext.accountId,
      selectionContext.scriptId,
      selectionContext.contextVersion,
    )) showToast(responseMessage(error, "无法读取所选文件。"), "error");
  }
}

async function handlePublishAssetFile(input, buildChange) {
  const file = input.files?.[0];
  if (!file) return;
  try {
    await savePublishAssetFile(file, buildChange);
  } finally {
    input.value = "";
  }
}

function wirePublishAssetDropZone(dropZone, input, kind, buildChange) {
  const clearHighlight = () => dropZone.classList.toggle("is-drag-over", false);
  const filesFrom = (event) => Array.from(event.dataTransfer?.files || []);
  const fileDragIsPresent = (event) => {
    const types = Array.from(event.dataTransfer?.types || []);
    return types.includes("Files") || filesFrom(event).length > 0;
  };

  dropZone.addEventListener("dragenter", (event) => {
    if (!fileDragIsPresent(event)) return;
    event.preventDefault();
    if (!input.disabled) dropZone.classList.add("is-drag-over");
  });
  dropZone.addEventListener("dragover", (event) => {
    if (!fileDragIsPresent(event)) return;
    event.preventDefault();
    if (!input.disabled) {
      event.dataTransfer.dropEffect = "copy";
      dropZone.classList.add("is-drag-over");
    } else {
      clearHighlight();
    }
  });
  dropZone.addEventListener("dragleave", (event) => {
    if (!dropZone.contains?.(event.relatedTarget)) clearHighlight();
  });
  dropZone.addEventListener("drop", async (event) => {
    const files = filesFrom(event);
    if (!files.length) return;
    event.preventDefault();
    clearHighlight();
    if (input.disabled) return;
    if (files.length !== 1) {
      publishDropError(kind, `一次只能拖入一个${PUBLISH_DROP_FILE_RULES[kind].label}文件。`);
      return;
    }
    if (!publishDropFileIsValid(files[0], kind)) {
      publishDropError(kind);
      return;
    }
    await savePublishAssetFile(files[0], buildChange);
  });
}

publishVideoInput.addEventListener("change", () => (
  handlePublishAssetFile(publishVideoInput, (upload) => ({ video: upload }))
));
publishPortraitCoverInput.addEventListener("change", () => (
  handlePublishAssetFile(publishPortraitCoverInput, (upload) => ({ coverAspect: "3:4", cover: upload }))
));
publishLandscapeCoverInput.addEventListener("change", () => (
  handlePublishAssetFile(publishLandscapeCoverInput, (upload) => ({ coverAspect: "4:3", cover: upload }))
));
wirePublishAssetDropZone(publishVideoDropZone, publishVideoInput, "video", (upload) => ({ video: upload }));
wirePublishAssetDropZone(publishPortraitCoverDropZone, publishPortraitCoverInput, "image", (upload) => ({ coverAspect: "3:4", cover: upload }));
wirePublishAssetDropZone(publishLandscapeCoverDropZone, publishLandscapeCoverInput, "image", (upload) => ({ coverAspect: "4:3", cover: upload }));

coverPromptInput.addEventListener("input", () => {
  coverDemo.prompt = coverPromptText();
  coverPromptInput.__coverPromptText = coverDemo.prompt;
  coverPromptInput.value = coverDemo.prompt;
  saveCoverState();
  updateCoverMention(coverMentionTargets.cover);
});
coverPromptInput.addEventListener("blur", () => {
  window.setTimeout(() => hideCoverMention(coverMentionPopup), 120);
});
coverPromptInput.addEventListener("keydown", (event) => {
  if (handleCoverMentionKeydown(coverMentionTargets.cover, event)) return;
  deleteCoverMentionToken(event);
});
coverMentionList.addEventListener("click", (event) => {
  const option = event.target.closest?.("[data-cover-mention-id]");
  if (!option) return;
  const image = coverDemo.uploadedImages.find((item) => item.id === option.dataset.coverMentionId);
  if (image) insertCoverMention(coverMentionTargets.cover, image);
});
coverRatioButton.addEventListener("click", toggleCoverRatioMenu);
coverRatioButton.addEventListener("blur", () => {
  window.setTimeout(hideCoverRatioMenu, 120);
});
document.addEventListener("pointerdown", (event) => {
  if (coverRatioMenu.hidden || coverRatioControl.contains(event.target)) return;
  hideCoverRatioMenu();
}, true);
document.addEventListener("pointerdown", (event) => {
  if (
    scriptStatusFilterControl.contains(event.target)
    || scriptActionsControl.contains(event.target)
  ) return;
  hideScriptStatusMenus();
}, true);
coverRatioMenu.addEventListener("click", (event) => {
  const option = event.target.closest?.("[data-cover-ratio]");
  if (option) selectCoverRatio(option.dataset.coverRatio);
});
coverReferencePicker.addEventListener("click", openCoverTemplateModal);
coverSaveTemplateButton.addEventListener("click", openCoverTemplateNameModal);
coverTemplateGrid.addEventListener("click", (event) => {
  const deleteButton = event.target.closest?.("[data-cover-template-delete]");
  if (deleteButton) return handleCoverTemplateDelete(deleteButton.dataset.coverTemplateDelete);
  const card = event.target.closest?.("[data-cover-template]");
  if (card) selectCoverTemplate(card.dataset.coverTemplate);
});
coverTemplateCloseButton.addEventListener("click", closeCoverTemplateModal);
cancelCoverTemplateSaveButton.addEventListener("click", closeCoverTemplateNameModal);
confirmCoverTemplateSaveButton.addEventListener("click", saveCurrentCoverTemplate);
coverUploadArea.addEventListener("click", () => {
  if (coverDemo.uploadedImages.length >= COVER_REFERENCE_MAX) {
    return showToast(`最多上传 ${COVER_REFERENCE_MAX} 张参考图`, "error");
  }
  coverFileInput.click();
});
function handleCoverReferenceFiles(files) {
  const selectedFiles = Array.from(files || []);
  if (!selectedFiles.length) return;
  const remaining = COVER_REFERENCE_MAX - coverDemo.uploadedImages.length;
  if (selectedFiles.length > remaining) {
    showToast(`最多上传 ${COVER_REFERENCE_MAX} 张参考图，已忽略 ${selectedFiles.length - remaining} 张`, "error");
  }
  const selected = selectedFiles.slice(0, remaining);
  if (!selected.length) {
    coverFileInput.value = "";
    return;
  }
  let pending = selected.length;
  const images = [];
  selected.forEach((file) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result !== "string") return;
      images.push({ name: file.name || "参考图", data: reader.result });
      pending -= 1;
      if (pending === 0) uploadCoverReferences(images);
    };
    reader.readAsDataURL(file);
  });
}
coverFileInput.addEventListener("change", () => {
  handleCoverReferenceFiles(coverFileInput.files);
});
function wireCoverReferenceDropZone(dropZone) {
  const clearHighlight = () => dropZone.classList.toggle("is-drag-over", false);
  const filesFrom = (event) => Array.from(event.dataTransfer?.files || []);
  const fileDragIsPresent = (event) => {
    const types = Array.from(event.dataTransfer?.types || []);
    return types.includes("Files") || filesFrom(event).length > 0;
  };

  dropZone.addEventListener("dragenter", (event) => {
    if (!fileDragIsPresent(event)) return;
    event.preventDefault();
    dropZone.classList.add("is-drag-over");
  });
  dropZone.addEventListener("dragover", (event) => {
    if (!fileDragIsPresent(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    dropZone.classList.add("is-drag-over");
  });
  dropZone.addEventListener("dragleave", (event) => {
    if (!dropZone.contains?.(event.relatedTarget)) clearHighlight();
  });
  dropZone.addEventListener("drop", (event) => {
    const files = filesFrom(event);
    if (!files.length) return;
    event.preventDefault();
    clearHighlight();
    handleCoverReferenceFiles(files);
  });
}
wireCoverReferenceDropZone(coverUploadArea);
async function uploadCoverReferences(images) {
  coverFileInput.value = "";
  try {
    const items = await postCoverReferences(images);
    const startIndex = coverDemo.uploadedImages.length + 1;
    items.forEach((item, index) => {
      coverDemo.uploadedImages.push({
        id: `upload-${startIndex + index}`,
        name: item.name,
        url: item.url,
      });
    });
    if (!coverDemo.activeImageId || !coverDemo.uploadedImages.some((image) => image.id === coverDemo.activeImageId)) {
      coverDemo.activeImageId = coverDemo.uploadedImages[0]?.id || "";
    }
    renderCoverReferenceState();
    saveCoverState();
    if (items.length < images.length) showToast(`已上传 ${items.length} 张参考图`, "success");
  } catch (error) {
    showToast(responseMessage(error, "参考图上传失败"), "error");
  }
}
async function postCoverReferences(images) {
  const response = await fetch("/api/cover/references", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ images }),
  });
  const payload = await response.json();
  if (!response.ok) throw payload;
  return Array.isArray(payload.items) ? payload.items : [];
}
coverUploadThumbs.addEventListener("click", (event) => {
  const thumb = event.target.closest?.("[data-cover-upload-thumb]");
  if (!thumb) return;
  event.stopPropagation?.();
  const image = coverDemo.uploadedImages.find((item) => item.id === thumb.dataset.coverUploadThumb);
  if (!image || image.id === coverDemo.activeImageId) return;
  coverDemo.activeImageId = image.id;
  renderCoverReferenceState();
  saveCoverState();
});
coverUploadRemove.addEventListener("click", clearCoverReference);
coverTitleGenerateButton.addEventListener("click", () => generateCoverTitle());
coverGenerateButton.addEventListener("click", () => generateCover());

for (const modal of [promptModal, titlePromptModal, writePromptModal, accountCreateModal, accountEditModal, coverTemplateModal, coverTemplateNameModal, accountDeleteModal]) {
  modal.addEventListener("click", (event) => {
    if (event.target !== modal) return;
    if (modal === coverTemplateModal) closeCoverTemplateModal();
    else if (modal === coverTemplateNameModal) closeCoverTemplateNameModal();
    else if (modal === accountDeleteModal) closeAccountDeleteModal();
    else if (modal === accountEditModal) closeAccountEditModal();
    else if (modal === writePromptModal) closeWritePromptModal();
    else setModalOpen(modal, false);
  });
}
document.addEventListener("keydown", (event) => {
  if (event.key === "Tab" && !accountCreateModal.hidden) {
    const controls = [...accountCreateModal.querySelectorAll('button:not(:disabled), input:not(:disabled)')]
      .filter((item) => item.type !== "radio" || item.checked);
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
  if (event.key !== "Escape") return;
  if (!scriptActionsPanel.hidden) setScriptActionsOpen(false, true);
  cancelAccountDeleteHold();
  closeAccountDeleteReveal();
  hideCoverMention();
  hideCoverRatioMenu();
  hideScriptStatusMenus();
  [promptModal, titlePromptModal, writePromptModal, accountCreateModal, accountEditModal, coverTemplateModal, coverTemplateNameModal, accountDeleteModal].forEach((modal) => {
    if (modal.hidden) return;
    if (modal === coverTemplateModal) closeCoverTemplateModal();
    else if (modal === coverTemplateNameModal) closeCoverTemplateNameModal();
    else if (modal === accountDeleteModal) closeAccountDeleteModal();
    else if (modal === accountEditModal) closeAccountEditModal();
    else if (modal === writePromptModal) closeWritePromptModal();
    else setModalOpen(modal, false);
  });
});

// #downloadForm is a plain section now, so a stray submit must never navigate.
form.addEventListener("submit", (event) => event.preventDefault());

generateRewritesButton.addEventListener("click", async () => {
  if (!activeTaskId || activeScript?.source !== "link") return showToast("请先完成视频处理", "error");
  const scriptId = activeScriptId;
  const taskId = activeTaskId;
  const accountId = activeAccountId;
  const model = selectedRewriteModel;
  const previousRewriteActionLabel = generateRewritesButton.textContent;
  const previous = rewriteModelState(model);
  activeRewriteModels[model] = { ...previous, content: "", available: false, status: "running", errorMessage: "" };
  renderActiveRewriteModel();
  try {
    const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/rewrite`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ systemPrompt: activeSystemPrompt, model }) });
    if (!response.ok) throw await response.json();
    if (activeAccountId !== accountId || activeScriptId !== scriptId || pendingScriptId) return;
    const workspace = await readJson(response);
    activeRewriteModels[model] = workspace?.rewrites?.[model] || previous;
    if (model === selectedRewriteModel) renderActiveRewriteModel();
  } catch (error) {
    activeRewriteModels[model] = previous;
    if (model === selectedRewriteModel) renderActiveRewriteModel();
    showToast(responseMessage(error, "仿写生成失败"), "error");
  } finally {
    if (model === selectedRewriteModel) {
      generateRewritesButton.disabled = false;
      if (generateRewritesButton.textContent === "正在生成…") generateRewritesButton.textContent = previousRewriteActionLabel;
    }
  }
});

workspaceTitle.addEventListener("click", startWorkspaceTitleEdit);
workspaceTitle.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  startWorkspaceTitleEdit();
});
workspaceTitleInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    return commitWorkspaceTitleEdit();
  }
  if (event.key === "Escape") {
    event.preventDefault();
    return cancelWorkspaceTitleEdit();
  }
});
workspaceTitleInput.addEventListener("blur", () => commitWorkspaceTitleEdit());
rewriteDraft.addEventListener("input", () => {
  rewriteDraftVersion += 1;
  rewriteDraftDirty = true;
  if (activeScript?.source === "link") linkRewriteDraftVersion += 1;
  rewriteDraftState = "自动保存中";
  renderRewriteDraft();
  scheduleRewriteDraftSave();
});
rewriteDraft.addEventListener("blur", () => {
  window.clearTimeout(rewriteDraftSaveTimer);
  rewriteDraftSaveTimer = null;
  return flushRewriteDraftSave();
});
writeStructureGenerateButton.addEventListener("click", () => openWritePromptModal("structure"));
writeContentGenerateButton.addEventListener("click", () => openWritePromptModal("content"));
writeContentAgentButton.addEventListener("click", openWritingAgent);
writeStructureMemoryButton.addEventListener("click", () => sinkWritingMemory("structure"));
writeContentMemoryButton.addEventListener("click", () => sinkWritingMemory("content"));
writeReferenceCopiesButton?.addEventListener("click", openWriteReferenceCopiesModal);
writeReferenceCopiesCancel?.addEventListener("click", closeWriteReferenceCopiesModal);
writeReferenceCopiesSave?.addEventListener("click", saveWriteReferenceCopies);
/* 点击遮罩或按 Esc 关闭，和其他弹窗保持一致。 */
writeReferenceCopiesModal?.addEventListener("click", (event) => {
  if (event.target === writeReferenceCopiesModal) closeWriteReferenceCopiesModal();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && writeReferenceCopiesModal && !writeReferenceCopiesModal.hidden) {
    closeWriteReferenceCopiesModal();
  }
});
writeStructurePromptButton.addEventListener("click", () => openWritePromptSettings("structure"));
writeContentPromptButton.addEventListener("click", () => openWritePromptSettings("content"));
splitStructureGenerateButton.addEventListener("click", () => openWritePromptModal("structure"));
splitStructureMemoryButton.addEventListener("click", () => sinkWritingMemory("structure"));
splitStructurePromptButton.addEventListener("click", () => openWritePromptSettings("structure"));
for (const { id, tab } of splitPanelTabs) {
  tab.addEventListener("click", () => selectSplitPanelTab(id));
}
cancelWritePromptButton.addEventListener("click", () => closeWritePromptModal());
writePromptAntiSimilarityInput.addEventListener("change", () => {
  if (writingPromptNode !== "content") return;
  renderWritePromptContext("content");
});
saveWritePromptButton.addEventListener("click", () => {
  if (writingPromptSaveMode === "save") saveWritePrompt();
  else saveWritePromptAndGenerate();
});
writeContentDraft.addEventListener("input", () => {
  writeContentDirty = true;
  writeContentSaveStatus = "自动保存中";
  renderWriteContentSaveState();
  scheduleWriteContentSave();
});
writeContentDraft.addEventListener("blur", () => {
  window.clearTimeout(writeContentSaveTimer);
  writeContentSaveTimer = null;
  saveWritingContent();
});
toggleSplitVideo.addEventListener("click", () => setSplitPanelVisible("video", !splitPanelVisibility.video));
toggleSplitTranscript.addEventListener("click", () => setSplitPanelVisible("transcript", !splitPanelVisibility.transcript));
toggleWriteStructure.addEventListener("click", () => setWritePanelVisible("structure", !writePanelVisibility.structure));
toggleWriteContent.addEventListener("click", () => setWritePanelVisible("content", !writePanelVisibility.content));
splitPlaybackToggle.addEventListener("click", toggleSplitPlayback);
splitFullscreenToggle.addEventListener("click", toggleSplitFullscreen);
document.addEventListener("fullscreenchange", renderSplitFullscreenControl);
splitVideo.addEventListener("click", () => {
  if (!splitVideo.src || splitVideo.paused) return;
  splitVideo.pause();
});
splitVideo.addEventListener("loadedmetadata", () => {
  const duration = Number(splitVideo.duration);
  splitMediaDuration = Number.isFinite(duration) && duration > 0 ? duration : 0;
  splitTrack.hidden = splitEffectiveDuration() <= 0;
  renderSplitTimelineTicks(splitEffectiveDuration());
  const restore = splitPendingSourceRestore;
  splitPendingSourceRestore = null;
  setSplitActiveTime(restore ? restore.time : activeTime, { seekVideo: Boolean(restore) });
  if (restore?.resumePlayback) splitVideo.play().catch(() => renderSplitPlaybackControl());
});
splitVideo.addEventListener("seeked", () => {
  if (!splitTrackSeekPending || splitTrackSeekTarget === null) return;
  if (Math.abs(splitVideo.currentTime - splitTrackSeekTarget) > 0.1) return;
  splitTrackSeekPending = false;
  splitTrackSeekTarget = null;
});
splitVideo.addEventListener("play", () => { renderSplitPlaybackControl(); startSplitPlaybackSync(); });
splitVideo.addEventListener("pause", () => { renderSplitPlaybackControl(); cancelSplitAnimationFrame(); });
splitVideo.addEventListener("ended", () => { renderSplitPlaybackControl(); cancelSplitAnimationFrame(); });
document.addEventListener("keydown", (event) => {
  if (
    event.code !== "Space" || event.repeat || workspaceContent.hidden || splitStage.hidden || splitVideo.hidden
    || !splitVideo.src || isSplitTextEditingTarget(event.target)
  ) return;
  event.preventDefault();
  if (document.activeElement === splitWorkbench) splitWorkbench.blur();
  toggleSplitPlayback();
});
splitTrack.addEventListener("pointerdown", (event) => {
  event.preventDefault();
  splitTrackIsDragging = true;
  splitTrack.setPointerCapture?.(event.pointerId);
  updateSplitTimeFromPointer(event);
  const move = (moveEvent) => {
    if (moveEvent.pointerId === event.pointerId) updateSplitTimeFromPointer(moveEvent);
  };
  const release = (releaseEvent) => {
    if (releaseEvent.pointerId !== event.pointerId) return;
    const targetTime = updateSplitTimeFromPointer(releaseEvent, { seekVideo: false });
    splitTrackIsDragging = false;
    splitTrackSeekPending = true;
    splitTrackSeekTarget = targetTime;
    setSplitActiveTime(targetTime, { seekVideo: true, scrollSegment: true });
    splitTrack.releasePointerCapture?.(event.pointerId);
    document.removeEventListener("pointermove", move);
    document.removeEventListener("pointerup", release);
    document.removeEventListener("pointercancel", release);
  };
  document.addEventListener("pointermove", move);
  document.addEventListener("pointerup", release);
  document.addEventListener("pointercancel", release);
});
if (typeof window.ResizeObserver === "function") {
  const splitTrackResizeObserver = new window.ResizeObserver(() => {
    if (!splitStage.hidden) {
      setSplitActiveTime(activeTime);
      syncSplitVideoColumnSize();
    }
  });
  splitTrackResizeObserver.observe(splitTrack);
  splitTrackResizeObserver.observe(splitWorkbench);
}
// The structure fields grow with their text, so any surface that changes the
// panel width (window resize, a hidden partner panel) has to re-measure them.
if (typeof window.ResizeObserver === "function") {
  const structureResizeObserver = new window.ResizeObserver(scheduleStructureRegrow);
  for (const view of structureViews) structureResizeObserver.observe(view.body);
}
sourceTranscript.addEventListener("scroll", () => { syncEditorScroll(sourceTranscript, rewriteDraft); });
rewriteDraft.addEventListener("scroll", () => { syncEditorScroll(rewriteDraft, sourceTranscript); });

// Each editor keeps its scrollbar visible until scrolling has been idle for 500ms.
for (const editor of [sourceTranscript, rewriteDraft]) {
  let scrollbarHideTimer;
  editor.addEventListener("scroll", () => {
    editor.classList.add("is-scrolling");
    clearTimeout(scrollbarHideTimer);
    scrollbarHideTimer = setTimeout(() => {
      editor.classList.remove("is-scrolling");
    }, 500);
  }, { passive: true });
}

// Keep the title scrollbar visible only during scrolling, including momentum.
const titleCandidateScroller = document.querySelector(".title-platform-groups");
let titleScrollbarHideTimer;
titleCandidateScroller?.addEventListener("scroll", () => {
  titleCandidateScroller.classList.add("is-scrolling");
  clearTimeout(titleScrollbarHideTimer);
  titleScrollbarHideTimer = setTimeout(() => {
    titleCandidateScroller.classList.remove("is-scrolling");
  }, 500);
}, { passive: true });

renderScrollSyncControl();
renderRewriteDraft();
setDemoTaskState("empty");
loadCoverStateForScript();
resetTitleStateForScript();
resetWritingStateForScript();
renderCoverResults();
restoreAccountSidebar();

// Guide navigation uses existing save paths and refuses to discard unsaved work.
window.prepareOnboardingNavigation = async () => {
  if (window.settingsModule?.confirmAccountChange?.() === false) return false;
  if (window.reviewModule?.state?.noteDirty) {
    showToast("请先在复盘页保存笔记，再继续引导。", "info");
    return false;
  }
  await flushRewriteDraftSave();
  await saveWritingContent();
  await saveStructureDraft();
  const publishDirty = [...publishDraftBuffers.values()].some(value => value?.dirty);
  if (rewriteDraftDirty || rewriteDraftState === "自动保存中" || writeContentDirty || writeContentSaveInFlight
      || (structureDraft && structureDraftDirty(structureDraft)) || publishDirty) {
    showToast("当前内容尚未保存，请先保存后继续。", "info");
    return false;
  }
  return true;
};

// The 首页 module opens the script list through this hook after a stat click.
window.selectScriptStatusFilter = selectScriptStatusFilter;
// 首页 / 选题 own a 新建脚本 entry: it navigates to the 创作 module.
window.openNewScriptPanel = openNewTaskForm;
// The 创作 panel creates a script and hands it back by id, so it lands in 脚本.
window.openScriptById = async (scriptId, accountId = activeAccountId) => {
  if (!scriptId) return;
  window.selectWorkspaceModule?.("scripts");
  await selectScript(scriptId, accountId);
};
window.isCreateViewActive = () => createViewActive;
// 插件宿主读取当前脚本的归属与标识；插件自行取脚本正文，宿主不暴露编辑器实现。
window.WorkbenchScriptContext = () => ({
  scriptId: activeScriptId || null,
  accountId: activeAccountId || null,
  title: (activeScript && activeScript.title) || "",
  stage: (activeScript && activeScript.stage) || "",
});

/* 创作 and 脚本 share one column, so the module decides which half is on screen. */
window.addEventListener?.("workspace-module-change", (event) => {
  if (event?.detail?.module === "create") {
    enterCreateView();
    return;
  }
  createViewActive = false;
  renderWorkspaceView();
  window.resumeWritingReturnSync?.();
});

workspaceEmptyCreateButton.addEventListener("click", () => {
  window.selectWorkspaceModule?.("create");
  enterCreateView();
});

async function bootstrapWorkspace() {
  setWorkspaceAccountState("loading");
  try {
    await loadAccounts({ awaitInitialTitleState: true });
  } catch (error) {
    setWorkspaceAccountState("error");
    document.querySelector("#workspaceGateRetry").focus();
    renderAccountList("账号读取失败");
    renderScriptList("账号读取失败");
    showToast(responseMessage(error, "账号读取失败"), "error");
  } finally {
    document.body?.classList?.remove?.("is-app-loading");
    // The account identity changes the footer height after boot; reveal the
    // active first-level entry once the final compact rail geometry exists.
    window.revealActiveWorkspaceNavigation?.();
  }
}

bootstrapWorkspace();


// Save existing editor drafts before a process restart; never discard failed saves.
window.prepareWorkbenchUpdate = async ({ discardUnsaved = false } = {}) => {
  const unsaved = [];
  if (window.settingsModule?.hasUnsavedChanges?.()) unsaved.push("设置");
  if (window.reviewModule?.state?.noteDirty) unsaved.push("复盘笔记");
  if (window.hasUnsavedCreation?.()) unsaved.push("创作草稿");
  if (unsaved.length && !discardUnsaved) {
    const error = new Error(`还有未保存的${unsaved.join("、")}，请先保存后更新。`);
    error.code = "UNSAVED_WORKBENCH_FORMS";
    throw error;
  }
  await commitWorkspaceTitleEdit();
  if (workspaceTitleEdit) throw new Error("标题尚未保存，请保存成功后再更新。");
  if (!(await flushStructureDraft())) throw new Error("脚本结构尚未保存，请先完成保存。");
  await flushRewriteDraftSave();
  while (linkRewriteSaveInFlight || linkRewriteQueuedSave || writeContentSaveInFlight) {
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  if (writeContentDirty) await saveWritingContent();
  for (const platform of titlePlatforms) {
    if (publishDraftBuffers.get(publishDraftBufferKey(platform))?.dirty) await savePublishDraft(platform);
  }
  if (rewriteDraftDirty || writeContentDirty || writeContentSaveInFlight
      || [...publishDraftBuffers.values()].some(draft => draft?.dirty)) {
    throw new Error("内容保存失败，请保存成功后再更新。");
  }
  saveWorkspaceActiveSelection();
  return true;
};

window.addEventListener("focus", () => {
  const platform = publishDraftPlatform;
  const key = publishLoginKey(platform);
  if (!publishStage.hidden && publishLoginReturnChecks.has(key) && !publishAssetsLocked()) {
    publishLoginReturnChecks.delete(key);
    void checkPublishStatus(platform);
  }
});

window.addEventListener("beforeunload", event => {
  if ([...publishDraftBuffers.values()].some(buffer => buffer.dirty)) { event.preventDefault(); event.returnValue = ""; }
});
