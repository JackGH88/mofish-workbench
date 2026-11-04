/* 新建脚本面板：创作素材助手、创作设置、Agent 生成与回传结果。
   「链接仿写」已经独立成拆解视频（static/breakdown.js），这里只负责直接创建。
   The panel is the 创作 module's whole column: the script list belongs to 脚本. */
"use strict";

(() => {
  const DURATIONS = ["30秒以内", "30-60秒", "60-90秒", "90-120秒", "2分钟以上"];
  const PLATFORM_LABELS = { douyin: "抖音", channels: "视频号", both: "抖音 + 视频号" };
  const MAX_POINTS = 500;
  const el = (id) => document.getElementById(id);

  const libraryTabs = Array.from(document.querySelectorAll("[data-library-tab]"));
  const assetKindTabs = Array.from(document.querySelectorAll("[data-asset-kind]"));
  const endingPanel = el("draftEndingListPanel");
  const endingList = el("draftEndingList");
  const endingEmpty = el("draftEndingEmpty");
  const endingFooter = el("draftEndingFooter");
  const ASSET_KEYS = { hook: "hooks", structure: "structures", ending: "endings" };
  let assetContextVersion = 0;
  const hookPanel = el("draftHookListPanel");
  const structurePanel = el("draftStructureListPanel");
  const hookList = el("draftHookList");
  const structureList = el("draftStructureList");
  const hookEmpty = el("draftHookEmpty");
  const structureEmpty = el("draftStructureEmpty");
  const hookFooter = el("draftHookFooter");
  const structureFooter = el("draftStructureFooter");
  const topicSelect = el("draftTopicSelect");
  const topicApplyButton = el("draftTopicApplyButton");
  const topicInput = el("draftTopicInput");
  const formatSelect = el("draftFormatSelect");
  const platformSelect = el("draftPlatformSelect");
  const durationSelect = el("draftDurationSelect");
  const durationField = durationSelect.closest(".draft-field");
  const pointsInput = el("draftPointsInput");
  const pointsCount = el("draftPointsCount");
  const advancedInput = el("draftAdvancedInput");
  const advancedView = el("draftAdvancedView");
  advancedView?.addEventListener("click", () => {
    advancedInput.hidden = !advancedInput.hidden;
    advancedView.textContent = advancedInput.hidden ? "展开" : "收起";
    advancedView.setAttribute("aria-expanded", String(!advancedInput.hidden));
  });
  const selectionSummary = el("draftSelectionSummary");
  const agentButton = el("draftAgentButton");
  const manualButton = el("draftManualButton");
  const clearButton = el("draftClearButton");
  const promptButton = el("draftPromptButton");
  const actionHint = el("draftActionHint");
  const addAssetButton = el("draftAddAssetButton");
  const pendingButton = el("pendingExperiencesButton");
  const editorPendingButton = el("editorPendingExperiencesButton");
  const pendingModal = el("pendingExperiencesModal");
  const pendingList = el("pendingExperiencesList");
  const pendingEmpty = el("pendingExperiencesEmpty");
  const closePendingButton = el("closePendingExperiencesButton");
  const draftPendingButton = el("draftPendingButton");
  const preferencesSummary = el("draftPreferencesSummary");
  const preferencesHint = el("draftPreferencesHint");
  const preferencesView = el("draftPreferencesView");
  const preferencesManage = el("draftPreferencesManage");
  const preferencesList = el("draftPreferencesList");
  const experienceList = el("draftReferenceCopyList");
  const experienceEmpty = el("draftReferenceCopyEmpty");
  const referencePanel = el("draftReferenceCopyPanel");
  const referenceView = el("draftReferenceCopyView");
  const referenceManage = el("draftReferenceCopyManage");
  function setReferenceExpanded(expanded) {
    if (referencePanel) referencePanel.hidden = !expanded;
    if (referenceView) {
      referenceView.textContent = expanded ? "收起" : "展开";
      referenceView.setAttribute("aria-expanded", String(expanded));
    }
  }
  referenceView?.addEventListener("click", () => setReferenceExpanded(referencePanel?.hidden));
  referenceManage?.addEventListener("click", () => window.settingsModule?.openReferenceCopies?.());
  const assetModal = el("draftAssetModal");
  const assetModalTitle = el("draftAssetModalTitle");
  const assetNameInput = el("draftAssetNameInput");
  const assetContentInput = el("draftAssetContentInput");
  const assetFormatField = el("draftAssetFormatField");
  const assetFormatSelect = el("draftAssetFormatSelect");
  const assetNoteInput = el("draftAssetNoteInput");
  const assetExampleInput = el("draftAssetExampleInput");
  const assetError = el("draftAssetModalError");
  const saveAssetButton = el("saveDraftAssetButton");
  const deleteAssetButton = el("deleteDraftAssetButton");
  const cancelAssetButton = el("cancelDraftAssetButton");
  const promptModal = el("draftPromptModal");
  const promptModalInput = el("draftPromptModalInput");
  const closePromptButton = el("closeDraftPromptButton");
  const copyPromptButton = el("copyDraftPromptButton");

  const state = {
    libraryTab: "hook",
    accountId: "",
    assets: { hooks: [], structures: [], endings: [] },
    topics: [],
    topicsStatus: "loading",
    hook: null,
    topicHookSnapshot: null,
    topicHookPending: false,
    topicHookStatus: "",
    ending: null,
    structure: null,
    scriptId: "",
    busy: false,
    pending: { structure: [], content: [] },
    assetKind: "hook",
    editingAssetId: "",
    /* 爆款文案按篇勾选：默认不选，换账号就重新读。 */
    preferences: [],
    preferencesExpanded: false,
    preferencesStatus: "loading",
    preferencesError: "",
    referenceCopies: [],
    referenceCopyIds: [],
  };

  let assetRequestVersion = 0;
  let topicRequestVersion = 0;

  let openPicker = null;

  /* 选题「去创作」can arrive before the topic list has loaded for this account, or while
     the cached list is older than the topic (选题库也可以在选题页以外的模块写入). */
  let pendingPrefillTopicId = "";

  /* 选题 caches its week and does not refetch on every module visit, so creating the
     script has to invalidate it: the topic's row goes from 待创作 to the script state. */
  function refreshTopicsAfterCreation() {
    if (!topicSelect.value) return;
    window.topicsModule?.refresh?.();
  }

  function buildChevron() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "topics-select-chevron");
    svg.setAttribute("width", "12");
    svg.setAttribute("height", "12");
    svg.setAttribute("viewBox", "0 0 12 12");
    svg.setAttribute("fill", "none");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", "M3 4.5L6 7.5L9 4.5");
    path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", "1.5");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
    svg.append(path);
    return svg;
  }

  /* 这些字段沿用选题模块的下拉组件：原生 select 的弹层无法套用工作台样式。 */
  function createPicker(hostId, inputId, label, onChange) {
    const host = el(hostId);
    const input = el(inputId);
    if (!host || !input) return null;
    const control = document.createElement("button");
    control.type = "button";
    control.className = "am-input topics-select-button";
    control.id = inputId + "Button";
    control.setAttribute("aria-haspopup", "menu");
    control.setAttribute("aria-expanded", "false");
    control.setAttribute("aria-label", label);
    const valueNode = document.createElement("span");
    valueNode.className = "topics-select-value";
    const menu = document.createElement("div");
    menu.className = "topics-select-menu";
    menu.id = inputId + "Menu";
    menu.setAttribute("role", "menu");
    menu.setAttribute("aria-label", label);
    menu.hidden = true;
    control.append(valueNode, buildChevron());
    host.append(control, menu);

    const picker = {
      host,
      input,
      control,
      menu,
      options: [],
      labelFor(candidate) {
        const found = picker.options.find((item) => item.value === candidate);
        return found ? found.label : candidate;
      },
      render() {
        menu.replaceChildren(...picker.options.map((item) => {
          const selected = input.value === item.value;
          const button = document.createElement("button");
          button.type = "button";
          button.setAttribute("role", "menuitemradio");
          button.setAttribute("aria-checked", String(selected));
          button.dataset.option = item.value;
          button.classList.toggle("is-current", selected);
          button.textContent = (selected ? "✓ " : "") + item.label;
          button.addEventListener("click", () => {
            picker.select(item.value);
            control.focus?.({ preventScroll: true });
          });
          return button;
        }));
      },
      select(candidate, { silent = false } = {}) {
        const allowed = picker.options.map((item) => item.value);
        const next = allowed.includes(candidate) ? candidate : allowed[0] || "";
        input.value = next;
        valueNode.textContent = picker.labelFor(next) || "请选择";
        if (silent) return next;
        picker.close();
        if (typeof onChange === "function") onChange(next);
        return next;
      },
      setOptions(next, { selected = "" } = {}) {
        picker.options = next.slice();
        picker.select(selected || input.value, { silent: true });
        picker.render();
      },
      open() {
        if (openPicker && openPicker !== picker) openPicker.close();
        picker.render();
        menu.hidden = false;
        control.setAttribute("aria-expanded", "true");
        openPicker = picker;
      },
      close() {
        if (menu.hidden) return;
        menu.hidden = true;
        control.setAttribute("aria-expanded", "false");
        if (openPicker === picker) openPicker = null;
      },
      toggle() {
        if (menu.hidden) picker.open();
        else picker.close();
      },
    };
    control.addEventListener("click", () => picker.toggle());
    control.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowDown") return;
      event.preventDefault();
      picker.open();
      menu.querySelector("button")?.focus();
    });
    menu.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      picker.close();
      control.focus();
    });
    return picker;
  }

  function createTopicPicker() {
    const picker = createPicker("draftTopicPicker", "draftTopicSelect", "从选题库选择");
    const node = (tag, className, text = "") => {
      const item = document.createElement(tag);
      item.className = className;
      item.textContent = text;
      if (tag === "button") item.type = "button";
      return item;
    };
    const weekStart = () => {
      const date = new Date();
      date.setDate(date.getDate() - (date.getDay() + 6) % 7);
      return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
    };
    let scope = "week";
    const labels = { week: "本周待创作", pending: "全部待创作", all: "全部选题" };
    const statuses = { pending_creation: "待创作", pending: "待处理", editing: "待拍摄", ready_to_publish: "待发布", published: "已发布" };
    picker.menu.classList.add("draft-topic-menu");
    picker.menu.setAttribute("role", "dialog");
    picker.control.setAttribute("aria-haspopup", "dialog");
    picker.control.setAttribute("aria-controls", picker.menu.id);
    const top = node("div", "draft-topic-top");
    const searchWrap = node("div", "draft-topic-search-wrap");
    const icon = node("span", "draft-topic-search-icon");
    icon.setAttribute("aria-hidden", "true");
    const search = node("input", "draft-topic-search");
    search.type = "search";
    search.id = "draftTopicSearch";
    search.setAttribute("aria-label", "搜索选题");
    search.autocomplete = "off";
    searchWrap.append(icon, search);
    const tabs = node("div", "draft-topic-tabs");
    tabs.setAttribute("role", "group");
    tabs.setAttribute("aria-label", "选题范围");
    const buttons = Object.entries(labels).map(([value, label]) => {
      const button = node("button", "draft-topic-tab", label);
      button.dataset.scope = value;
      button.addEventListener("click", () => { scope = value; picker.render(); });
      tabs.append(button);
      return button;
    });
    const list = node("div", "draft-topic-results");
    list.id = "draftTopicResults";
    const foot = node("div", "draft-topic-foot");
    foot.setAttribute("aria-live", "polite");
    top.append(searchWrap, tabs);
    picker.menu.replaceChildren(top, list, foot);
    const select = picker.select.bind(picker);
    picker.select = (candidate, options = {}) => {
      const value = select(candidate, options);
      topicApplyButton.disabled = !value;
      return value;
    };
    picker.render = () => {
      const week = weekStart();
      const query = search.value.trim().toLocaleLowerCase();
      buttons.forEach(button => button.setAttribute("aria-pressed", String(button.dataset.scope === scope)));
      search.placeholder = "搜索" + labels[scope];
      const items = state.topics.filter(topic => scope === "all" || (
        !topic.scriptId && topic.status === "pending_creation" && (scope !== "week" || topic.weekStart === week)
      )).filter(topic => String(topic.title || "").toLocaleLowerCase().includes(query));
      list.replaceChildren();
      list.scrollTop = 0;
      const choice = (topic) => {
        const id = topic ? String(topic.id) : "";
        const button = node("button", "draft-topic-choice");
        button.dataset.topicId = id;
        button.setAttribute("aria-pressed", String(picker.input.value === id));
        const copy = node("span", "draft-topic-copy");
        const title = node("span", "draft-topic-title", topic ? topic.title || "未命名选题" : "不关联选题");
        title.title = title.textContent;
        copy.append(title);
        if (topic) {
          const date = topic.weekStart === week ? "本周" : topic.weekStart ? topic.weekStart.replaceAll("-", ".") + " 当周" : "未设置所属周";
          copy.append(node("span", "draft-topic-meta", date + " · " + (statuses[topic.status] || "待创作")));
        } else button.classList.add("draft-topic-none");
        button.append(copy);
        if (topic?.scriptId) button.append(node("span", "draft-topic-continue", "继续创作 ↗"));
        else button.append(node("span", "draft-topic-check", picker.input.value === id ? "✓" : ""));
        button.addEventListener("click", async () => {
          if (topic?.scriptId) {
            picker.close();
            try {
              window.selectScriptStatusFilter?.("all");
              await window.openScriptById(topic.scriptId, state.accountId);
            } catch (error) {
              window.showToast(window.responseMessage(error, "脚本打开失败，请重试"), "error");
            }
            return;
          }
          picker.select(id);
          picker.control.focus();
        });
        list.append(button);
      };
      choice(null);
      items.forEach(choice);
      if (!items.length) {
        const empty = node("div", "draft-topic-empty");
        let message = query ? "没有找到匹配的选题" : scope === "week" ? "本周暂无待创作选题" : "暂无待创作选题";
        if (state.topicsStatus === "loading") message = "正在读取选题…";
        else if (state.topicsStatus === "error") message = "选题读取失败，请重试";
        else if (!state.topics.length) message = "当前工作台还没有选题";
        empty.append(node("p", "", message));
        if (state.topicsStatus === "error" || (state.topicsStatus === "ready" && state.topics.length)) {
          const action = node("button", "draft-topic-empty-action", state.topicsStatus === "error" ? "重新加载" : query ? "清空搜索" : "查看历史待创作");
          action.addEventListener("click", () => {
            if (state.topicsStatus === "error") { loadTopics(state.accountId); return; }
            if (query) { search.value = ""; search.focus(); }
            else scope = "pending";
            picker.render();
          });
          if (state.topicsStatus === "error" || query || scope === "week") empty.append(action);
        }
        list.append(empty);
      }
      foot.textContent = state.topicsStatus === "ready" ? "共 " + items.length + " 条选题" : "";
    };
    search.addEventListener("input", () => picker.render());
    picker.reset = () => { scope = "week"; search.value = ""; picker.close(); };
    picker.host.addEventListener("focusout", event => {
      if (event.relatedTarget && !picker.host.contains(event.relatedTarget)) picker.close();
    });
    picker.control.addEventListener("keydown", event => {
      if (event.key === "Escape") { picker.close(); event.preventDefault(); }
    });
    return picker;
  }

  const topicPicker = createTopicPicker();
  const formatPicker = createPicker("draftFormatPicker", "draftFormatSelect", "内容形式", () => {
    applyFormatChange();
  });
  const platformPicker = createPicker("draftPlatformPicker", "draftPlatformSelect", "发布平台");
  const durationPicker = createPicker("draftDurationPicker", "draftDurationSelect", "目标时长");
  const assetFormatPicker = createPicker("draftAssetFormatPicker", "draftAssetFormatSelect", "适用形式");

  function applyFormatChange() {
    dropStructureForFormat(formatSelect.value);
    renderDurationOptions();
    renderStructures();
    renderSelectionSummary();
  }

  function renderDurationVisibility() {
    durationField.hidden = formatSelect.value === "article";
  }

  /* ---------------------------------------------------------------- 素材快照 */

  function assetSnapshot(asset) {
    if (!asset) return null;
    return {
      id: String(asset.id || ""),
      name: String(asset.name || ""),
      content: String(asset.content || ""),
      note: String(asset.note || asset.description || ""),
      example: String(asset.example || ""),
      steps: Array.isArray(asset.steps) ? asset.steps.slice() : [],
      format: String(asset.format || ""),
    };
  }

  function currentStructureFormat() {
    return formatSelect.value === "article" ? "article" : "video";
  }

  function structuresForFormat(format) {
    return state.assets.structures.filter((asset) => (asset.format || "video") === format);
  }

  /* ---------------------------------------------------------------- 渲染 */

  function renderLibraryTabs() {
    libraryTabs.forEach((button) => {
      const active = button.dataset.libraryTab === state.libraryTab;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", String(active));
    });
    hookPanel.hidden = state.libraryTab !== "hook";
    structurePanel.hidden = state.libraryTab !== "structure";
    endingPanel.hidden = state.libraryTab !== "ending";

  }

  function assetCardActions(card, asset, selected, onUse, onClear, useLabel) {
    const footer = document.createElement("footer");
    footer.className = "asset-card-actions";
    const use = document.createElement("button");
    use.type = "button";
    use.className = selected ? "asset-card-use is-selected" : "asset-card-use";
    use.textContent = selected ? "✓ 已选用" : useLabel;
    use.setAttribute("aria-pressed", String(selected));
    use.addEventListener("click", (event) => {
      event.stopPropagation();
      if (selected) onClear();
      else onUse();
    });
    footer.append(use);
    {
      for (const [label, action] of [["编辑", () => openAssetEditor(asset)], ["删除", () => removeAsset(asset)]]) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "asset-card-icon";
        button.textContent = label;
        button.setAttribute("aria-label", label + "素材 " + (asset.name || ""));
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          action();
        });
        footer.append(button);
      }
    }
    return footer;
  }

  function renderHooks() { renderTextAssets("hook"); }
  function renderEndings() { renderTextAssets("ending"); }
  function renderTextAssets(kind) {
    const [hookList, hookEmpty, hookFooter, label] = kind === "ending"
      ? [endingList, endingEmpty, endingFooter, "结尾引导"]
      : [el("draftHookList"), el("draftHookEmpty"), el("draftHookFooter"), "开头钩子"];
    hookList.replaceChildren();
    const assets = state.assets[ASSET_KEYS[kind]];
    hookEmpty.hidden = assets.length > 0;
    hookEmpty.textContent = assets.length ? "" : "还没有" + label + "，点右上角“＋ 添加”写一个。";
    for (const asset of assets) {
      const selected = Boolean(state[kind] && state[kind].id === asset.id && asset.id);
      const card = document.createElement("article");
      card.className = selected ? "asset-card is-selected" : "asset-card";
      const head = document.createElement("header");
      head.className = "asset-card-head";
      const title = document.createElement("h4");
      title.textContent = asset.name || "未命名";
      head.append(title);
      const hookTag = asset.description || asset.note || (asset.builtin ? "" : "自定义");
      if (hookTag) {
        const tag = document.createElement("span");
        tag.className = "asset-tag";
        tag.textContent = hookTag;
        head.append(tag);
      }
      const details = document.createElement("details");
      details.className = "draft-template-details";
      const summary = document.createElement("summary");
      summary.title = "展开或收起模板详情";
      summary.setAttribute("aria-label", (asset.name || "未命名") + "，展开或收起详情");
      summary.append(head);
      details.append(summary);
      card.append(details);
      const example = asset.example || asset.content;
      if (example) {
        const line = document.createElement("p");
        line.className = "asset-card-example";
        line.textContent = example;
        details.append(line);
      }
      card.append(assetCardActions(
        card,
        asset,
        selected,
        () => selectTextAsset(kind, asset),
        () => selectTextAsset(kind, null),
        "使用",
      ));
      hookList.append(card);
    }
    hookFooter.textContent = assets.length ? assets.length + " 个" + label : "";
  }

  function renderStructures() {
    structureList.replaceChildren();
    const assets = structuresForFormat("video");
    structureEmpty.hidden = assets.length > 0;
    structureEmpty.textContent = assets.length ? "" : "还没有视频结构模板，点右上角“＋ 添加”写一个。";
    for (const asset of assets) {
      const selected = Boolean(state.structure && state.structure.id === asset.id && asset.id);
      const card = document.createElement("article");
      card.className = selected ? "structure-card is-selected" : "structure-card";
      const head = document.createElement("header");
      head.className = "asset-card-head";
      const title = document.createElement("h4");
      title.textContent = asset.name || "未命名";
      head.append(title);
      const tag = document.createElement("span");
      tag.className = "asset-tag";
      tag.textContent = asset.description || asset.note || asset.tag || (asset.builtin ? "" : "自定义");
      head.append(tag);
      const details = document.createElement("details");
      details.className = "draft-template-details";
      const summary = document.createElement("summary");
      summary.title = "展开或收起模板详情";
      summary.setAttribute("aria-label", (asset.name || "未命名") + "，展开或收起详情");
      summary.append(head);
      details.append(summary);
      card.append(details);
      const steps = Array.isArray(asset.steps) && asset.steps.length
        ? asset.steps
        : String(asset.content || "").split("→").map((item) => item.trim()).filter(Boolean);
      if (steps.length) {
        const flow = document.createElement("p");
        flow.className = "structure-steps";
        steps.forEach((step, index) => {
          if (index) {
            const arrow = document.createElement("i");
            arrow.setAttribute("aria-hidden", "true");
            arrow.textContent = "→";
            flow.append(arrow);
          }
          const item = document.createElement("span");
          item.textContent = step;
          flow.append(item);
        });
        details.append(flow);
      }
      card.append(assetCardActions(
        card,
        asset,
        selected,
        () => selectStructure(asset),
        () => selectStructure(null),
        "使用",
      ));
      structureList.append(card);
    }
    structureFooter.textContent = assets.length
      ? assets.length + " 个结构模板"
      : "";
  }

  function selectionChip(label, name, onClear, onReplace) {
    const chip = document.createElement("span");
    chip.className = "draft-selection-chip";
    const text = document.createElement("span");
    const category = document.createElement("span");
    category.className = "draft-selection-category";
    category.textContent = label + " · ";
    const value = document.createElement("span");
    value.textContent = name;
    text.append(category, value);
    chip.append(text);
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "draft-selection-clear";
    clear.setAttribute("aria-label", "取消" + label);
    clear.textContent = "×";
    clear.addEventListener("click", onClear);
    chip.append(clear);
    return { chip, replace: onReplace };
  }

  function renderSelectionSummary() {
    selectionSummary.replaceChildren();
    if (state.topicHookStatus === "historical" || state.topicHookStatus === "changed") {
      const history = document.createElement("p");
      history.className = "draft-selection-hint";
      history.textContent = "选题生成时钩子：" + (state.topicHookSnapshot?.name || "未命名")
        + (state.topicHookStatus === "historical" ? "（已移除，仅保留历史）" : "（素材已更新，生成时版本已保留）");
      selectionSummary.append(history);
    }
    if (!state.hook && !state.structure && !state.ending) {
      const hint = document.createElement("p");
      hint.className = "draft-selection-hint";
      hint.textContent = "右侧未选择时由 Agent 推荐";
      selectionSummary.append(hint);
      return;
    }
    if (state.hook) {
      selectionSummary.append(selectionChip("开头钩子", state.hook.name || "未命名", () => selectHook(null)).chip);
    }
    if (state.structure) {
      selectionSummary.append(selectionChip("内容结构", state.structure.name || "未命名", () => selectStructure(null)).chip);
    }
    if (state.ending) {
      selectionSummary.append(selectionChip("结尾引导", state.ending.name || "未命名", () => selectTextAsset("ending", null)).chip);
    }
  }

  function renderPlatformOptions() {
    formatPicker.setOptions(
      [{ value: "video", label: "视频 / 口播" }, { value: "article", label: "图文" }],
      { selected: formatSelect.value || "video" },
    );
    assetFormatPicker.setOptions(
      [{ value: "video", label: "视频" }],
      { selected: assetFormatSelect.value || "video" },
    );
    const wanted = "douyin";
    const values = ["douyin", "channels", "both"];
    const current = platformSelect.value;
    platformPicker.setOptions(values.map((value) => ({ value, label: PLATFORM_LABELS[value] || value })), {
      selected: values.includes(current) ? current : wanted,
    });
  }

  function renderDurationOptions() {
    durationPicker.setOptions(DURATIONS.map((value) => ({ value, label: value })), {
      selected: durationSelect.value || "60-90秒",
    });
    renderDurationVisibility();
  }

  function resizePointsInput() {
    // Hidden panels have no usable dimensions; the observer retries when shown.
    if (!pointsInput.clientWidth) return;
    pointsInput.style.height = "auto";
    const borderHeight = pointsInput.offsetHeight - pointsInput.clientHeight;
    pointsInput.style.height = `${pointsInput.scrollHeight + borderHeight}px`;
  }

  function renderPointsCount() {
    pointsCount.textContent = pointsInput.value.length + " / " + MAX_POINTS;
    resizePointsInput();
  }

  function renderControls() {
    const disabled = state.busy;
    agentButton.disabled = disabled;
    manualButton.disabled = disabled;
    if (clearButton) clearButton.disabled = disabled;
    promptButton.disabled = disabled;
    addAssetButton.disabled = disabled;
    agentButton.textContent = disabled ? "正在打开…" : (window.WritingAssistants?.label() || "待配置Agent");
    actionHint.textContent = disabled
      ? "正在请求打开助手，请稍候…"
      : assistantRetry?.accountId === state.accountId
        ? "上次未能打开助手，再次点击将重试原任务；清空后可开始新任务。"
        : state.scriptId
        ? "已创建脚本，可继续调整设置后再次生成。"
        : "可先查看指令，再生成初稿。";
  }

  function renderAll() {
    renderLibraryTabs();
    renderHooks();
    renderEndings();
    renderStructures();
    renderSelectionSummary();
    renderPlatformOptions();
    renderDurationOptions();
    renderPointsCount();
    renderControls();
  }

  /* ---------------------------------------------------------------- 选用 */

  function selectHook(asset) {
    state.topicHookPending = false;
    selectTextAsset("hook", asset);
  }

  function selectTextAsset(kind, asset) {
    if (kind === "hook") state.topicHookPending = false;
    state[kind] = asset ? assetSnapshot(asset) : null;
    renderTextAssets(kind);
    renderSelectionSummary();
  }

  function selectStructure(asset) {
    state.structure = asset ? assetSnapshot(asset) : null;
    renderStructures();
    renderSelectionSummary();
  }

  function dropStructureForFormat(format) {
    if (!state.structure) return;
    const wanted = state.structure.format || "video";
    if (format === "article" && wanted !== "article") {
      state.structure = null;
      window.showToast("图文脚本不能用视频结构模板，请重新选择。", "info");
    }
    if (format === "video" && wanted === "article") {
      state.structure = null;
      window.showToast("视频脚本不能用图文结构模板，请重新选择。", "info");
    }
  }

  /* ---------------------------------------------------------------- 创作设置 */

  function clearDraftForm() {
    if (state.busy) return;
    openPicker?.close();
    pendingPrefillTopicId = "";
    assistantRetry = null;
    state.scriptId = "";
    state.topicHookSnapshot = null;
    state.topicHookStatus = "";
    state.topicHookPending = false;
    state.hook = state.structure = state.ending = null;
    state.referenceCopyIds = [];
    topicSelect.value = "";
    topicPicker.reset();
    renderTopics();
    topicInput.value = "";
    topicInput.classList.remove("is-invalid");
    pointsInput.value = "";
    advancedInput.value = "";
    formatSelect.value = "video";
    platformSelect.value = "douyin";
    durationSelect.value = "60-90秒";
    promptModal.hidden = true;
    promptModalInput.value = "";
    renderExperiences();
    renderAll();
  }

  function draftPayload() {
    const article = formatSelect.value === "article";
    return {
      title: topicInput.value.trim().slice(0, 120),
      scriptId: state.scriptId,
      topicId: topicSelect.value || "",
      topic: topicInput.value.trim(),
      contentFormat: article ? "article" : "video",
      platform: platformSelect.value || "",
      duration: article ? "" : durationSelect.value || "",
      points: pointsInput.value.slice(0, 4000),
      advanced: advancedInput.value.slice(0, 2000),
      hook: state.hook,
      ending: state.ending,
      structure: state.structure,
      referenceCopyIds: state.referenceCopyIds.slice(0, 50),
    };
  }

  function creationNeedsTopic() {
    return !topicInput.value.trim();
  }

  function focusTopic() {
    topicInput.focus();
    topicInput.classList.add("is-invalid");
    window.setTimeout(() => topicInput.classList.remove("is-invalid"), 1600);
  }

  function renderTopics() {
    const options = [{ value: "", label: "不关联选题" }];
    for (const topic of state.topics) {
      options.push({ value: String(topic.id), label: topic.title || "未命名选题" });
    }
    topicPicker.setOptions(options, { selected: topicSelect.value });
    topicApplyButton.disabled = !topicSelect.value;
  }

  /** Fill 创作设置 from one topic. Shared by 「应用到创作」 and the 去创作 entry. */
  function applyTopicToDraft(topic) {
    state.topicHookSnapshot = topic.hook || null;
    state.topicHookStatus = topic.hookAvailability || "";
    state.topicHookPending = topic.hookAvailability !== "historical" && Boolean(topic.hookId || topic.hook?.id);
    state.hook = null;
    resolveTopicHook();
    renderAll();
    topicInput.value = String(topic.title || "");
    topicInput.classList.remove("is-invalid");
    formatPicker.select(topic.format === "article" ? "article" : "video");
    const lines = [];
    if (topic.outline) lines.push("一句话大纲：" + topic.outline);
    if (topic.materials) lines.push("准备素材：" + topic.materials);
    pointsInput.value = lines.join("\n").slice(0, 4000);
    renderPointsCount();
  }

  function resolveTopicHook() {
    if (!state.topicHookPending) return;
    const id = state.topicHookSnapshot?.id;
    const current = state.assets.hooks.find((item) => item.id === id);
    if (current) {
      state.hook = current;
      state.topicHookPending = false;
    }
  }

  function applySelectedTopic() {
    const topic = state.topics.find((item) => item.id === topicSelect.value);
    if (!topic) {
      window.showToast("先选择一个选题。", "info");
      return;
    }
    applyTopicToDraft(topic);
  }

  function prefillFromTopic(topicId) {
    const wanted = String(topicId || "");
    if (!wanted) return false;
    const topic = state.topics.find((item) => item.id === wanted);
    if (!topic) return false;
    topicPicker.select(wanted, { silent: true });
    topicPicker.render();
    applyTopicToDraft(topic);
    return true;
  }

  /* ---------------------------------------------------------------- 素材库请求 */

  async function loadAssets(accountId) {
    const version = (assetRequestVersion += 1);
    try {
      const response = await fetch("/api/accounts/" + encodeURIComponent(accountId) + "/writing-assets");
      const payload = await window.readJson(response);
      if (version !== assetRequestVersion || state.accountId !== accountId) return;
      state.assets = {
        hooks: Array.isArray(payload.hooks) ? payload.hooks : [],
        endings: Array.isArray(payload.endings) ? payload.endings : [],
        structures: Array.isArray(payload.structures) ? payload.structures : [],
      };
      resolveTopicHook();
      if (state.topicHookPending) {
        state.topicHookStatus = "historical";
        state.topicHookPending = false;
      }
      keepSelectionsValid();
      renderAll();
    } catch (error) {
      if (version !== assetRequestVersion) return;
      window.showToast(window.responseMessage(error, "创作素材读取失败"), "error");
    }
  }

  /** 等待中的「去创作」: 读取返回后再带入，两次读取都没有这条选题时才提示。 */
  function flushPendingPrefill(loaded) {
    const pending = pendingPrefillTopicId;
    if (!pending) return;
    pendingPrefillTopicId = "";
    if (prefillFromTopic(pending)) return;
    window.showToast(
      loaded ? "这条选题在当前账号下找不到，请刷新后重试。" : "选题列表读取失败，请稍后重试。",
      "error",
    );
  }

  async function loadTopics(accountId) {
    const version = (topicRequestVersion += 1);
    state.topicsStatus = "loading";
    topicPicker.render();
    try {
      const response = await fetch("/api/accounts/" + encodeURIComponent(accountId) + "/topics");
      const payload = await window.readJson(response);
      if (version !== topicRequestVersion || state.accountId !== accountId) return;
      state.topicsStatus = "ready";
      state.topics = Array.isArray(payload.items) ? payload.items : [];
      renderTopics();
      flushPendingPrefill(true);
    } catch (_error) {
      if (version !== topicRequestVersion || state.accountId !== accountId) return;
      state.topicsStatus = "error";
      state.topics = [];
      renderTopics();
      flushPendingPrefill(false);
    }
  }

  function keepSelectionsValid() {
    for (const [kind, key] of Object.entries(ASSET_KEYS)) {
      if (!state[kind]) continue;
      const current = state.assets[key].find((item) => item.id === state[kind].id);
      if (kind === "hook" && state.topicHookSnapshot?.id === state[kind].id) {
        state.topicHookStatus = !current ? "historical"
          : current.content !== state.topicHookSnapshot.content || current.name !== state.topicHookSnapshot.name ? "changed" : "current";
      }
      state[kind] = current ? assetSnapshot(current) : null;
    }
  }

  /* ---------------------------------------------------------------- 素材弹窗 */

  let externalAssetDraft = null;

  // Share the library editor without changing the current script's selections.
  window.openWritingAssetDraft = (context) => {
    if (state.busy || !context?.isCurrent?.() || state.accountId !== context.accountId) return false;
    openAssetModal({ asset: { ...context.draft, kind: context.kind } });
    externalAssetDraft = context;
    state.editingAssetId = "";
    assetKindTabs.forEach(button => { button.disabled = true; });
    deleteAssetButton.hidden = true;
    assetModalTitle.textContent = { hook: "添加开头钩子", structure: "添加结构模板", ending: "添加结尾引导" }[context.kind];
    saveAssetButton.textContent = "确定添加";
    return true;
  };
  window.closeWritingAssetDraft = () => { if (externalAssetDraft) closeAssetModal(); };

  async function saveExternalAsset() {
    const context = externalAssetDraft;
    if (!context || context.saving) return;
    if (state.accountId !== context.accountId || !context.isCurrent()) { closeAssetModal(); return; }
    const note = assetNoteInput.value.trim();
    const body = { name: assetNameInput.value.trim(), content: context.kind === "structure" ? assetContentInput.value.trim() : note,
      note, example: context.kind === "structure" ? "" : assetExampleInput.value.trim() };
    if (context.kind === "structure") body.format = "video";
    if (!body.name) return showAssetError("请填写素材名称。");
    if (!body.content) return showAssetError(context.kind === "structure" ? "请填写结构内容。" : "请填写素材说明。");
    context.saving = true;
    saveAssetButton.disabled = true;
    saveAssetButton.textContent = "正在添加…";
    assetError.hidden = true;
    try {
      const saved = await context.save(body);
      window.dispatchEvent(new CustomEvent("writing-assets:changed", { detail: { accountId: context.accountId } }));
      if (context.isCurrent()) context.onSaved(saved);
      if (externalAssetDraft === context) {
        closeAssetModal();
        window.showToast("素材已添加", "success");
      }
    } catch (error) {
      if (externalAssetDraft === context && context.isCurrent()) showAssetError(window.responseMessage(error, "素材保存失败"));
    } finally {
      context.saving = false;
      if (externalAssetDraft === context) {
        saveAssetButton.disabled = false;
        saveAssetButton.textContent = "确定添加";
      }
    }
  }

  function setAssetKind(kind) {
    state.assetKind = ASSET_KEYS[kind] ? kind : "hook";
    assetKindTabs.forEach((button) => {
      button.disabled = Boolean(state.editingAssetId);
      const active = button.dataset.assetKind === state.assetKind;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", String(active));
    });
    assetFormatField.hidden = true;
    const isStructure = state.assetKind === "structure";
    el("draftAssetContentField").hidden = !isStructure;
    el("draftAssetExampleField").hidden = isStructure;
    el("draftAssetNoteLabel").textContent = isStructure
      ? "说明（选填，帮助 AI 理解结构的适用场景和写作要求）"
      : state.assetKind === "ending" ? "说明（AI 会参考这些要求设计结尾引导）" : "说明（AI 会参考这些要求设计开头）";
    el("draftAssetExampleLabel").textContent = state.assetKind === "ending"
      ? "示例（选填，AI 会参考示例的句式和语气生成结尾）"
      : "示例（选填，AI 会参考示例的句式和语气生成开头）";
    assetNoteInput.placeholder = isStructure ? "说明适用场景" : "说明这种表达方式的写作要求";
    assetContentInput.placeholder = state.assetKind === "structure"
      ? "用 → 连接每个环节" : state.assetKind === "ending" ? "填写结尾的写作要求或完整表达" : "填写开头的写作要求或完整表达";
  }

  function openAssetModal({ asset = null } = {}) {
    externalAssetDraft = null;
    saveAssetButton.disabled = false;
    saveAssetButton.textContent = "保存";
    state.editingAssetId = asset ? String(asset.id || "") : "";
    setAssetKind(asset ? asset.kind : state.libraryTab);
    assetModalTitle.textContent = asset ? "编辑素材" : "添加素材";
    assetNameInput.value = asset ? asset.name || "" : "";
    assetContentInput.value = asset ? asset.content || "" : "";
    assetFormatPicker.select("video", { silent: true });
    assetNoteInput.value = asset ? asset.note || asset.description || (asset.kind !== "structure" ? asset.content : "") || "" : "";
    assetExampleInput.value = asset ? asset.example || "" : "";
    assetError.hidden = true;
    assetError.textContent = "";
    deleteAssetButton.hidden = !asset;
    assetModal.hidden = false;
    assetNameInput.focus();
  }

  function openAssetEditor(asset) {
    openAssetModal({ asset });
  }

  function closeAssetModal() {
    externalAssetDraft = null;
    saveAssetButton.disabled = false;
    saveAssetButton.textContent = "保存";
    assetModal.hidden = true;
    state.editingAssetId = "";
  }

  function showAssetError(message) {
    assetError.textContent = message;
    assetError.hidden = false;
  }

  async function saveAsset() {
    if (externalAssetDraft) return saveExternalAsset();
    if (state.busy || !state.accountId) return;
    const accountId = state.accountId;
    const context = assetContextVersion;
    const editingId = state.editingAssetId;
    const kind = state.assetKind;
    const isStructure = kind === "structure";
    const note = assetNoteInput.value.trim();
    const body = {
      name: assetNameInput.value.trim(),
      content: isStructure ? assetContentInput.value.trim() : note,
      note,
      example: isStructure ? "" : assetExampleInput.value.trim(),
    };
    if (!body.name) return showAssetError("请填写素材名称。");
    if (!body.content) return showAssetError(isStructure ? "请填写结构内容。" : "请填写素材说明。");
    if (!editingId) body.kind = kind;
    if (kind === "structure") body.format = "video";
    const url = "/api/accounts/" + encodeURIComponent(accountId) + "/writing-assets" +
      (editingId ? "/" + encodeURIComponent(editingId) : "");
    state.busy = true;
    renderControls();
    try {
      const response = await fetch(url, {
        method: editingId ? "PATCH" : "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const saved = await window.readJson(response);
      if (context !== assetContextVersion || state.accountId !== accountId) return;
      if (state[kind]?.id === saved.id) state[kind] = assetSnapshot(saved);
      const pool = state.assets[ASSET_KEYS[kind]];
      const index = pool.findIndex((item) => item.id === saved.id);
      if (index < 0) pool.push(saved); else pool[index] = saved;
      closeAssetModal();
      await loadAssets(accountId);
      if (context !== assetContextVersion || state.accountId !== accountId) return;
      if (!editingId) {
        state.libraryTab = kind;
        state[kind] = assetSnapshot(saved);
      }
      window.showToast(editingId ? "素材已更新" : "素材已添加", "success");
    } catch (error) {
      if (context === assetContextVersion) showAssetError(window.responseMessage(error, "素材保存失败"));
    } finally {
      if (context === assetContextVersion) { state.busy = false; renderAll(); }
    }
  }

  async function removeAsset(asset) {
    if (!asset || state.busy || !state.accountId) return;
    const accountId = state.accountId;
    const context = assetContextVersion;
    if (!window.confirm("删除素材“" + (asset.name || "") + "”？已经生成的脚本不受影响。")) return;
    state.busy = true;
    renderControls();
    try {
      const response = await fetch("/api/accounts/" + encodeURIComponent(accountId) + "/writing-assets/" + encodeURIComponent(asset.id), { method: "DELETE" });
      if (!response.ok && response.status !== 204) await window.readJson(response);
      if (context !== assetContextVersion || state.accountId !== accountId) return;
      for (const [kind, key] of Object.entries(ASSET_KEYS)) {
        if (state[kind]?.id === asset.id) state[kind] = null;
        state.assets[key] = state.assets[key].filter((item) => item.id !== asset.id);
      }
      if (state.editingAssetId === asset.id) closeAssetModal();
      await loadAssets(accountId);
      if (context === assetContextVersion) window.showToast("素材已删除", "success");
    } catch (error) {
      if (context === assetContextVersion) window.showToast(window.responseMessage(error, "素材删除失败"), "error");
    } finally {
      if (context === assetContextVersion) { state.busy = false; renderAll(); }
    }
  }

  async function deleteEditingAsset() {
    const asset = currentEditingAsset();
    if (asset) await removeAsset(asset);
  }

  function currentEditingAsset() {
    if (!state.editingAssetId) return null;
    return state.assets[ASSET_KEYS[state.assetKind]].find((item) => String(item.id) === state.editingAssetId) || null;
  }

  /* ---------------------------------------------------------------- Agent */

  /* 创作 is not a script column: both creation paths hand the new script to 脚本, which
     is where its editor, stage tabs and saved state live. */
  async function openCreatedScript(scriptId, accountId) {
    if (!scriptId) return;
    window.selectWorkspaceModule?.("scripts");
    try {
      await window.openScriptById?.(scriptId, accountId);
    } catch (error) {
      window.showToast(window.responseMessage(error, "脚本已创建，请在脚本列表里打开它。"), "error");
    }
  }

  let assistantRetry = null;
  window.addEventListener("writing-assistant-change", renderControls);

  async function launchAgent() {
    if (!window.WritingAssistants?.isConfigured()) { window.WritingAssistants?.open(); return; }
    if (state.busy || !state.accountId) return;
    if (creationNeedsTopic()) {
      window.showToast("请先填写主题 / 想讲什么。", "error");
      focusTopic();
      return;
    }
    const accountId = state.accountId;
    const body = draftPayload();
    state.busy = true;
    renderControls();
    let createdScriptId = "";
    try {
      const retry = assistantRetry?.accountId === accountId ? assistantRetry : null;
      const url = retry ? `/api/scripts/${encodeURIComponent(retry.scriptId)}/writing-agent/${encodeURIComponent(retry.taskId)}/retry` : "/api/accounts/" + encodeURIComponent(accountId) + "/writing-agent";
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await window.readJson(response);
      if (state.accountId !== accountId || activeAccountId !== accountId) return;
      state.scriptId = payload.scriptId || state.scriptId;
      assistantRetry = payload.opened === false && payload.retryable !== false ? { accountId, scriptId: payload.scriptId, taskId: payload.taskId } : null;
      window.showToast(payload.message || "已请求打开助手，请检查预填内容并手动发送。", payload.opened === false ? "error" : "info");
      if (payload.opened === false) return;
      await refreshScriptList(accountId);
      refreshTopicsAfterCreation();
      createdScriptId = state.scriptId;
    } catch (error) {
      window.showToast(window.responseMessage(error, "未能打开助手，请重试。"), "error");
    } finally {
      state.busy = false;
      renderAll();
    }
    await openCreatedScript(createdScriptId, accountId);
  }

  async function refreshScriptList(accountId) {
    try {
      const response = await fetch("/api/accounts/" + encodeURIComponent(accountId) + "/scripts");
      const payload = await window.readJson(response);
      if (activeAccountId !== accountId) return;
      scripts = Array.isArray(payload.items) ? payload.items : [];
      renderScriptList();
    } catch (_error) {
      /* A list refresh is best effort; the next navigation reloads it. */
    }
  }

  async function createManualScript() {
    if (state.busy || !state.accountId) return;
    const accountId = state.accountId;
    const body = draftPayload();
    // 直接手写 always creates a fresh script, so the reuse id must not be sent.
    delete body.scriptId;
    state.busy = true;
    renderControls();
    let createdScriptId = "";
    try {
      const response = await fetch("/api/accounts/" + encodeURIComponent(accountId) + "/scripts/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const script = await window.readJson(response);
      if (activeAccountId !== accountId) return;
      state.scriptId = script.id;
      await loadScripts(accountId, script.id);
      window.showToast("已创建脚本，直接开始写吧。", "success");
      refreshTopicsAfterCreation();
      createdScriptId = script.id;
    } catch (error) {
      window.showToast(window.responseMessage(error, "创建脚本失败"), "error");
    } finally {
      state.busy = false;
      renderControls();
    }
    await openCreatedScript(createdScriptId, accountId);
  }

  async function previewPrompt() {
    if (state.busy || !state.accountId) return;
    if (creationNeedsTopic()) {
      window.showToast("请先填写主题 / 想讲什么。", "error");
      focusTopic();
      return;
    }
    const accountId = state.accountId;
    const version = experienceRequestVersion;
    state.busy = true;
    renderControls();
    try {
      const response = await fetch("/api/accounts/" + encodeURIComponent(accountId) + "/writing-agent/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draftPayload()),
      });
      const payload = await window.readJson(response);
      if (state.accountId !== accountId || experienceRequestVersion !== version) return;
      promptModalInput.value = String(payload.prompt || "");
      promptModal.hidden = false;
      promptModalInput.focus();
    } catch (error) {
      if (state.accountId !== accountId || experienceRequestVersion !== version) return;
      window.showToast(window.responseMessage(error, "生成指令读取失败"), "error");
    } finally {
      state.busy = false;
      renderControls();
    }
  }

  /* ---------------------------------------------------------------- 回传结果 */

  // 有效任务支持多次回传；页面可见时同步最新提交。
  const RETURN_SYNC_DELAY_MS = 3000;
  let returnSyncTimer = null;
  let returnSyncFailures = 0;
  function returnTaskActive() {
    const task = activeScript && activeScript.writingAgentTask;
    return Boolean(activeScriptId && activeAccountId && task?.taskId
      && ["awaiting", "applied", "pending_return"].includes(task.status));
  }

  function returnRevision(task) {
    return JSON.stringify([task?.status, task?.appliedAt, task?.submissionIds || []]);
  }

  function stopReturnSync() {
    returnSyncTimer = cancelPoll("writing-return", returnSyncTimer);
    returnSyncFailures = 0;
  }

  function resumeReturnSync() {
    if (!returnTaskActive()) {
      stopReturnSync();
      return;
    }
    if (returnSyncTimer !== null) return;
    const accountId = activeAccountId;
    const scriptId = activeScriptId;
    returnSyncTimer = schedulePoll("writing-return", () => {
      returnSyncTimer = null;
      if (activeAccountId !== accountId || activeScriptId !== scriptId) {
        resumeReturnSync();
        return;
      }
      syncWritingReturn();
    }, pollDelayFor(RETURN_SYNC_DELAY_MS, returnSyncFailures));
  }

  async function syncWritingReturn() {
    const scriptId = activeScriptId;
    const accountId = activeAccountId;
    const task = activeScript && activeScript.writingAgentTask;
    if (!returnTaskActive()) {
      resumeReturnSync();
      return;
    }
    if (document.hidden) {
      // 隐藏的标签页不发请求；schedulePoll 会把下一次尝试留到页面重新可见时。
      resumeReturnSync();
      return;
    }
    const revision = returnRevision(task);
    try {
      const response = await fetch("/api/scripts/" + encodeURIComponent(scriptId) + "/workspace");
      const payload = await window.readJson(response);
      const script = payload && payload.script;
      const stillCurrent = script && activeScriptId === scriptId && activeAccountId === accountId
        && activeScript?.writingAgentTask?.taskId === task.taskId
        && returnRevision(activeScript.writingAgentTask) === revision
        && script.writingAgentTask && script.writingAgentTask.taskId === task.taskId;
      if (stillCurrent && returnRevision(script.writingAgentTask) !== revision) {
        // Use the same guarded in-place update as global returns; a full reload can
        // overwrite local edits and steals focus/navigation from the current workspace.
        await window.refreshImportedScriptList(accountId, [{result: "updated", scriptId}]);
        if (activeAccountId === accountId) loadPendingExperiences(accountId);
      }
      returnSyncFailures = 0;
    } catch (_error) {
      /* A background refresh never interrupts editing. */
      returnSyncFailures += 1;
    }
    resumeReturnSync();
  }

  /* ---------------------------------------------------------------- 待确认经验 */

  function pendingCount() {
    return (state.pending.structure?.length || 0) + (state.pending.content?.length || 0);
  }

  function renderPendingExperiences() {
    const count = pendingCount();
    pendingButton.disabled = !count;
    pendingButton.textContent = count ? "待确认经验 " + count : "待确认经验";
    pendingButton.title = count ? "查看 Agent 建议的编写偏好" : "暂无待确认经验";
    // The draft panel needs its own entry: a newly created script has no 编写 stage yet.
    draftPendingButton.hidden = !count;
    draftPendingButton.disabled = !count;
    draftPendingButton.textContent = count ? "待确认经验 " + count : "待确认经验";
    // The 编辑 script card offers the same entry, so it carries the same count.
    if (editorPendingButton) {
      editorPendingButton.hidden = !count;
      editorPendingButton.disabled = !count;
      editorPendingButton.textContent = count ? "待确认经验 " + count : "待确认经验";
      editorPendingButton.title = count ? "查看 Agent 建议的编写偏好" : "暂无待确认经验";
    }
    pendingList.replaceChildren();
    pendingEmpty.hidden = count > 0;
    for (const node of ["structure", "content"]) {
      for (const item of state.pending[node] || []) {
        const row = document.createElement("li");
        row.className = "pending-experiences-item";
        const label = document.createElement("span");
        label.className = "pending-experiences-node";
        label.textContent = node === "structure" ? "结构" : "内容";
        const text = document.createElement("span");
        text.className = "pending-experiences-text";
        text.textContent = item.text || "";
        const actions = document.createElement("span");
        actions.className = "pending-experiences-actions";
        for (const [caption, adopt] of [["采用", true], ["忽略", false]]) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = adopt ? "am-primary-action" : "am-secondary-action";
          button.textContent = caption;
          button.addEventListener("click", () => resolvePendingExperience(item.id, adopt));
          actions.append(button);
        }
        row.append(label, text, actions);
        pendingList.append(row);
      }
    }
  }

  async function loadPendingExperiences(accountId) {
    try {
      const response = await fetch("/api/accounts/" + encodeURIComponent(accountId) + "/writing-pending");
      const payload = await window.readJson(response);
      if (state.accountId !== accountId) return;
      state.pending = {
        structure: Array.isArray(payload.structure) ? payload.structure : [],
        content: Array.isArray(payload.content) ? payload.content : [],
      };
      renderPendingExperiences();
    } catch (_error) {
      /* A pending-experience refresh never interrupts the editor. */
    }
  }

  async function resolvePendingExperience(id, adopt) {
    const accountId = state.accountId;
    if (!id || !accountId) return;
    try {
      const response = await fetch("/api/accounts/" + encodeURIComponent(accountId) + "/writing-pending/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: [id], adopt }),
      });
      await window.readJson(response);
      await loadPendingExperiences(accountId);
      window.showToast(adopt ? "已采用这条经验" : "已忽略这条经验", "success");
    } catch (error) {
      window.showToast(window.responseMessage(error, "经验处理失败"), "error");
    }
  }


  /* ---------------------------------------------------------------- 外部接口 */

  /* -------------------------------------------------------------- 爆款文案选择 */

  let experienceRequestVersion = 0;

  function renderReferenceCount() {
    const count = el("draftReferenceCopyCount");
    if (count) count.textContent = "已选 " + state.referenceCopyIds.length + " / " + state.referenceCopies.length + " 篇";
  }

  function renderExperiences() {
    if (!experienceList) return;
    experienceList.replaceChildren(...state.referenceCopies.map((item, index) => {
      const row = document.createElement("div");
      row.className = "draft-reference-row";
      const label = document.createElement("label");
      label.className = "draft-reference-option";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = item.id;
      input.checked = state.referenceCopyIds.includes(item.id);
      input.addEventListener("change", () => {
        if (input.checked) {
          if (!state.referenceCopyIds.includes(item.id)) state.referenceCopyIds.push(item.id);
        } else {
          state.referenceCopyIds = state.referenceCopyIds.filter((id) => id !== item.id);
        }
        renderReferenceCount();
      });
      const text = document.createElement("span");
      const title = item.title || "未命名文案";
      text.textContent = title;
      text.title = title;
      label.append(input, text);
      const detail = document.createElement("div");
      detail.id = "draftReferenceDetail-" + index;
      detail.className = "draft-reference-detail";
      detail.hidden = true;
      const body = document.createElement("p");
      body.textContent = item.content || "";
      detail.append(body);
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "draft-link-button draft-reference-toggle";
      toggle.textContent = "详情";
      toggle.setAttribute("aria-label", "查看文案详情：" + title);
      toggle.setAttribute("aria-expanded", "false");
      toggle.setAttribute("aria-controls", detail.id);
      toggle.addEventListener("click", () => {
        detail.hidden = !detail.hidden;
        toggle.textContent = detail.hidden ? "详情" : "收起";
        toggle.setAttribute("aria-expanded", String(!detail.hidden));
      });
      row.append(label, toggle, detail);
      return row;
    }));
    renderReferenceCount();
    if (experienceEmpty) experienceEmpty.hidden = state.referenceCopies.length > 0;
  }

  function renderPreferences() {
    if (!preferencesSummary) return;
    const ready = state.preferencesStatus === "ready";
    const label = document.createElement("span");
    label.textContent = "写作偏好 · ";
    const status = document.createElement("span");
    status.className = "draft-selection-hint";
    status.textContent = (ready
      ? "自动应用 " + state.preferences.length + " 条"
      : state.preferencesStatus === "error" ? "读取失败" : "正在读取…");
    preferencesSummary.replaceChildren(label, status);
    if (preferencesHint) {
      preferencesHint.textContent = state.preferencesError || "";
      preferencesHint.hidden = !preferencesHint.textContent;
    }
    if (preferencesView) {
      preferencesView.disabled = !ready || !state.preferences.length;
      preferencesView.textContent = state.preferencesExpanded ? "收起" : "展开";
      preferencesView.setAttribute("aria-expanded", String(state.preferencesExpanded));
    }
    if (preferencesManage) preferencesManage.disabled = !state.accountId;
    if (preferencesList) {
      preferencesList.hidden = !state.preferencesExpanded || !ready;
      preferencesList.replaceChildren(...state.preferences.map((item) => {
        const row = document.createElement("li");
        const body = document.createElement("p");
        body.textContent = (item.content || "").trim() || item.title;
        row.append(body);
        return row;
      }));
    }
  }

  preferencesView?.addEventListener("click", () => {
    state.preferencesExpanded = !state.preferencesExpanded;
    renderPreferences();
  });
  preferencesManage?.addEventListener("click", () => window.settingsModule?.openWritingPreferences?.());

  async function loadExperiences(accountId) {
    const version = (experienceRequestVersion += 1);
    state.preferences = [];
    state.preferencesExpanded = false;
    state.preferencesStatus = "loading";
    state.preferencesError = "";
    renderPreferences();
    try {
      const response = await fetch("/api/accounts/" + encodeURIComponent(accountId) + "/memories");
      const payload = await window.readJson(response);
      if (version !== experienceRequestVersion || state.accountId !== accountId) return;
      const items = Array.isArray(payload.items) ? payload.items : [];
      state.referenceCopies = items.filter((item) => item.category === "reference_copy" && item.enabled);
      // Keep invalid selections until explicitly removed; generation must not silently omit them.
      for (const id of state.referenceCopyIds) {
        if (!state.referenceCopies.some((item) => item.id === id)) state.referenceCopies.push({ id, title: "已停用、删除或不可读取，请取消选择", unavailable: true });
      }
      if (payload.directoryError) throw new Error(payload.directoryError);
      state.preferences = items.filter((item) => item.category === "preference" && item.enabled);
      state.preferencesStatus = "ready";
      state.preferencesError = (payload.errors || []).length ? "部分记忆文件无法读取，当前仅显示可应用的偏好，请到记忆管理检查。" : "";
      renderPreferences();
      if (experienceEmpty) experienceEmpty.textContent = (payload.errors || []).length ? "部分记忆文件无法读取，请到记忆管理检查。" : "当前账号还没有启用的爆款文案，可在拆解详情中收藏。";
      renderExperiences();
    } catch (error) {
      if (version !== experienceRequestVersion || state.accountId !== accountId) return;
      state.preferencesStatus = "error";
      state.preferencesError = "写作偏好读取失败：" + window.responseMessage(error, "请检查记忆目录");
      renderPreferences();
      if (experienceEmpty) { experienceEmpty.hidden = false; experienceEmpty.textContent = "爆款文案读取失败：" + responseMessage(error, "请检查记忆目录"); }
    }
  }

  window.hasUnsavedCreation = () => !state.scriptId && Boolean(topicInput.value.trim());

  window.loadDraftPanelData = (accountId) => {
    accountId = accountId || "";
    if (!accountId) {
      stopReturnSync();
      topicRequestVersion += 1;
      experienceRequestVersion += 1;
      state.pending = { structure: [], content: [] };
      state.preferences = [];
      state.preferencesStatus = "idle";
      state.preferencesError = "";
      pendingModal.hidden = true;
      topicInput.value = pointsInput.value = advancedInput.value = "";
      renderPendingExperiences();
      renderPreferences();
    }
    if (state.accountId !== accountId) {
      assetContextVersion += 1;
      assetRequestVersion += 1;
      state.topicHookSnapshot = null;
      state.topicHookStatus = "";
      state.topicHookPending = false;
      state.hook = state.structure = state.ending = null;
      state.assets = { hooks: [], structures: [], endings: [] };
      state.busy = false;
      closeAssetModal();
      renderAll();
      state.topics = [];
      topicSelect.value = "";
      topicPicker.reset();
      renderTopics();
    }
    state.accountId = accountId;
    setReferenceExpanded(false);
    promptModal.hidden = true;
    promptModalInput.value = "";
    state.referenceCopyIds = [];
    state.referenceCopies = [];
    renderExperiences();
    assistantRetry = null;
    state.scriptId = "";
    /* 一条选题只属于一个账号，切换账号后上一次等待带入的选题已经无意义。 */
    pendingPrefillTopicId = "";
    renderPlatformOptions();
    if (!accountId) return;
    loadAssets(accountId);
    loadTopics(accountId);
    loadPendingExperiences(accountId);
    loadExperiences(accountId);
  };

  window.addEventListener("writing-assets:changed", (event) => {
    if (event.detail?.accountId === state.accountId) loadAssets(state.accountId);
  });

  window.enterDraftPanel = () => {
    setReferenceExpanded(false);
    assistantRetry = null;
    state.scriptId = "";
    /* 新的一篇：爆款文案默认不选，不沿用上一次的勾选。 */
    state.referenceCopyIds = [];
    /* 记忆管理里刚改过的文案要在打开创作面板时就同步过来，而不是等下次切账号。 */
    if (state.accountId) {
      loadAssets(state.accountId);
      loadExperiences(state.accountId);
      loadTopics(state.accountId);
    }
    renderExperiences();
    renderAll();
  };

  /** 选题页「去创作」: open the creation view with this topic already applied. */
  window.prefillDraftTopic = (topicId) => {
    const wanted = String(topicId || "");
    if (!wanted) return;
    if (prefillFromTopic(wanted)) return;
    if (!state.accountId) return;
    // The cached list can be older than the topic itself: 选题库 is also written to from
    // 首页灵感 / 监控 / 雷达, and this panel only reads it on an account change. Re-read
    // once before claiming the topic is gone, so the first jump succeeds.
    pendingPrefillTopicId = wanted;
    loadTopics(state.accountId);
  };

  window.leaveDraftPanel = () => {
    topicPicker.close();
    closeAssetModal();
    promptModal.hidden = true;
  };

  window.refreshDraftPanel = () => {
    renderAll();
  };

  window.resumeWritingReturnSync = resumeReturnSync;
  window.refreshPendingExperiences = () => {
    if (state.accountId) loadPendingExperiences(state.accountId);
  };

  /* ---------------------------------------------------------------- 事件 */

  libraryTabs.forEach((button) => {
    button.addEventListener("click", () => {
      state.libraryTab = button.dataset.libraryTab;
      renderLibraryTabs();
    });
  });

  pointsInput.addEventListener("input", renderPointsCount);
  if (typeof ResizeObserver !== "undefined") {
    let pointsWidth = 0;
    const pointsResizeObserver = new ResizeObserver(() => {
      const width = pointsInput.clientWidth;
      if (width === pointsWidth) return;
      pointsWidth = width;
      resizePointsInput();
    });
    pointsResizeObserver.observe(pointsInput);
  }

  topicApplyButton.addEventListener("click", () => {
    applySelectedTopic();
  });

  addAssetButton.addEventListener("click", () => openAssetModal());
  cancelAssetButton.addEventListener("click", closeAssetModal);
  saveAssetButton.addEventListener("click", saveAsset);
  deleteAssetButton.addEventListener("click", deleteEditingAsset);
  assetKindTabs.forEach((button) => {
    button.addEventListener("click", () => { if (!state.editingAssetId) setAssetKind(button.dataset.assetKind); });
  });
  assetModal.addEventListener("click", (event) => {
    if (event.target === assetModal) closeAssetModal();
  });

  agentButton.addEventListener("click", launchAgent);
  manualButton.addEventListener("click", createManualScript);
  clearButton?.addEventListener("click", clearDraftForm);
  promptButton.addEventListener("click", previewPrompt);

  closePromptButton.addEventListener("click", () => {
    promptModal.hidden = true;
  });
  promptModal.addEventListener("click", (event) => {
    if (event.target === promptModal) promptModal.hidden = true;
  });
  copyPromptButton.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(promptModalInput.value);
      window.showToast("生成指令已复制", "success");
    } catch (_error) {
      promptModalInput.select();
      window.showToast("请手动复制选中的指令", "info");
    }
  });

  document.addEventListener("pointerdown", (event) => {
    if (openPicker && !event.target.closest?.(".topics-select-control")) openPicker.close();
  });
  pendingButton.addEventListener("click", () => {
    renderPendingExperiences();
    pendingModal.hidden = false;
    closePendingButton.focus();
  });
  draftPendingButton.addEventListener("click", () => {
    renderPendingExperiences();
    pendingModal.hidden = false;
    closePendingButton.focus();
  });
  editorPendingButton.addEventListener("click", () => {
    renderPendingExperiences();
    pendingModal.hidden = false;
    closePendingButton.focus();
  });
  closePendingButton.addEventListener("click", () => {
    pendingModal.hidden = true;
  });
  pendingModal.addEventListener("click", (event) => {
    if (event.target === pendingModal) pendingModal.hidden = true;
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!assetModal.hidden) {
      event.preventDefault();
      closeAssetModal();
      return;
    }
    if (!promptModal.hidden) {
      event.preventDefault();
      promptModal.hidden = true;
      return;
    }
    if (!pendingModal.hidden) {
      event.preventDefault();
      pendingModal.hidden = true;
    }
  });

  document.addEventListener("visibilitychange", () => {
    syncWritingReturn();
  });
  window.addEventListener("focus", () => {
    syncWritingReturn();
  });

  renderAll();
})();
