/* Account-owned recommendations. Reads never trigger generation or collection. */
(() => {
  'use strict';
  const root = document.getElementById('topicRecommendationsContent');
  if (!root) return;
  const base = '/api/topic-recommendations';
  const state = { accountId: '', revision: 0, data: null, feed: null, page: 1, morePage: 1, source: 'all', busy: false, requestError: '', manualUpdate: false, timer: null, polls: 0, feedRevision: 0, loadRevision: 0, modalRevision: 0 };
  const categories = { hot: '热点优先', continuation: '延续验证', evergreen: '常青备选' };
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const text = value => typeof value === 'string' || typeof value === 'number' ? String(value) : Array.isArray(value) ? value.map(text).filter(Boolean).join('；') : value && typeof value === 'object' ? Object.values(value).map(text).filter(Boolean).join(' · ') : '';
  const date = value => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '暂无时间记录';
  const safeUrl = value => /^(https?:\/\/|\/[^/])/.test(value || '') ? value : '';
  const metric = value => value == null ? '暂无数据' : Number(value).toLocaleString('zh-CN');
  const btn = (label, action, key = '', cls = 'am-secondary-action', disabled = false) => `<button type="button" class="${cls}" data-tr-action="${action}" data-key="${esc(key)}"${disabled ? ' disabled' : ''}>${esc(label)}</button>`;
  const empty = message => `<p class="tr-empty">${esc(message)}</p>`;
  const active = () => !root.hidden;
  const current = (account, revision) => state.accountId === account && state.revision === revision;
  async function api(path = '', body, method = 'POST', account = state.accountId) {
    const response = await fetch(`${base}${path}${path.includes('?') ? '&' : '?'}accountId=${encodeURIComponent(account)}`, body === undefined ? {} : { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...body, accountId: account }) });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.error || '请求失败，请稍后重试');
    return data;
  }
  let dialog, restoreFocus;
  function closeModal() { state.modalRevision++; if (dialog) { dialog.remove(); dialog = null; } if (restoreFocus?.isConnected) restoreFocus.focus(); }
  function modal(title, html, footer = '', variant = '') {
    closeModal(); restoreFocus = document.activeElement;
    dialog = document.createElement('div'); dialog.className = 'prompt-modal tr-modal' + (variant ? ` tr-modal-${variant}` : '');
    dialog.innerHTML = `<section class="modal-card modal-card-wide" role="dialog" aria-modal="true" aria-labelledby="trModalTitle" tabindex="-1"><header class="modal-header"><h2 id="trModalTitle" class="modal-title">${esc(title)}</h2></header><div class="modal-content">${html}<p class="tr-modal-error" role="alert" hidden></p></div><footer class="modal-actions">${footer}${btn('关闭', 'close')}</footer></section>`;
    document.body.append(dialog); dialog.addEventListener('click', handleAction);
    dialog.addEventListener('click', e => { if (e.target === dialog) closeModal(); });
    dialog.addEventListener('keydown', e => {
      if (e.key === 'Escape') { e.preventDefault(); closeModal(); }
      if (e.key !== 'Tab') return;
      const nodes = [...dialog.querySelectorAll('button:not(:disabled),input:not(:disabled),select,textarea,a[href]')];
      if (!nodes.length) return;
      if (e.shiftKey && document.activeElement === nodes[0]) { e.preventDefault(); nodes.at(-1).focus(); }
      else if (!e.shiftKey && document.activeElement === nodes.at(-1)) { e.preventDefault(); nodes[0].focus(); }
    });
    dialog.querySelector('input,button,section').focus();
    return state.modalRevision;
  }
  function error(message) { if (!dialog) state.requestError = message; const el = dialog?.querySelector('.tr-modal-error') || root.querySelector('#trMessage'); if (el) { el.hidden = false; el.textContent = message; } }
  const allItems = () => [...(state.data?.items || []), ...(state.data?.history || [])];
  const itemTitle = item => item.section === 'today' ? item.generatedTitle || item.title : item.sourceWork?.title || item.title;
  const sourceLabels = work => [...new Set(Array.isArray(work.sources) ? work.sources : work.source ? [work.source] : [])].map(source => ({ monitor: '对标更新', radar: '关键词采集' }[source] || '')).filter(Boolean).join(' · ') || '已采集内容';
  const findItem = key => allItems().find(item => String(item.key) === key);
  const findWork = id => [...(state.feed?.items || []), ...allItems().map(i => i.sourceWork).filter(Boolean)].find(w => String(w.id) === id);
  function pager(page, pages, action, total) { return `<footer class="tr-pager"><span>共 ${total} 条</span>${btn('上一页', action, page - 1, 'am-secondary-action', page <= 1)}<span>${page} / ${Math.max(1, pages)}</span>${btn('下一页', action, page + 1, 'am-secondary-action', page >= pages)}</footer>`; }
  function workActions(w) { return `${btn('加入选题', 'work-topic', w.id)}${btn('拆解视频', 'breakdown', w.id, 'am-secondary-action', !safeUrl(w.shareUrl))}${btn(w.saved ? '已收藏' : '收藏', 'save', w.id, 'radar-text-button')}`; }
  function card(item) {
    const w = item.sourceWork; const key = item.key;
    return `<article class="tr-today-card"><div class="tr-kind"><span>${esc(categories[item.category] || '推荐方向')}</span><small>${item.isNewRecommendation === true ? '新推荐' : item.isNewRecommendation === false ? '持续推荐' : ''}</small></div><h3>${esc(item.generatedTitle || item.title)}</h3><p class="tr-reason">${esc(item.reason || '暂无推荐理由')}</p><div class="tr-angle"><span>切入角度</span><p>${esc(item.angle || '暂无具体切入角度')}</p></div><p class="tr-production">${esc(text(item.production) || '制作条件待确认')}</p>${w ? `<div class="tr-reference">${safeUrl(w.coverSrc) ? `<img src="${esc(w.coverSrc)}" alt="" loading="lazy">` : ''}<span>相关视频参考<small>${esc(w.authorName || '作者未知')}</small></span>${btn('查看 ↗', 'work', w.id, 'radar-text-button')}</div>` : '<p class="tr-production">暂无关联原始作品</p>'}<div class="tr-card-actions">${btn(item.topicId ? '已加入选题库' : '加入选题库', 'topic', key, 'am-primary-action', !!item.topicId)}${w ? btn('拆解视频', 'breakdown', w.id, 'am-secondary-action', !safeUrl(w.shareUrl)) : ''}</div></article>`;
  }
  function guideActions(source = 'all', view = false) {
    return `${source !== 'monitor' ? btn(view ? '查看内容采集' : '添加关键词采集', view ? 'guide-radar-view' : 'guide-radar') : ''}${source !== 'radar' ? btn(view ? '查看对标监控' : '添加对标博主', view ? 'guide-monitor-view' : 'guide-monitor') : ''}`;
  }
  function guidance(title, copy, actions) {
    return `<div class="tr-empty-guide"><p class="tr-intro">${esc(title)}</p>${copy ? `<p class="tr-intro">${esc(copy)}</p>` : ''}<div class="tr-actions tr-empty-guide-actions">${actions}</div></div>`;
  }
  function todayEmpty(running) {
    if (!state.accountId) return empty('请先选择账号。');
    if (!state.data) return empty('正在读取推荐…');
    if (running) return empty('正在生成推荐，请稍候…');
    const setup = state.data.summary?.setup;
    if (!setup) return empty('暂无今日推荐，可点击“更新推荐”。');
    if (setup.workCount > 0) return guidance('内容已就绪，可以生成今日推荐', '结合账号定位与已采集作品，筛选适合今天制作的方向。', `${!setup.profileReady ? btn('完善账号定位','guide-positioning') : ''}${btn('更新推荐','generate','','am-primary-action',state.busy)}`);
    if (setup.keywordCount + setup.bloggerCount > 0) return guidance('内容来源已添加，等待首批作品采集', '采集到作品后，即可结合账号定位生成推荐。', `${!setup.profileReady ? btn('完善账号定位','guide-positioning') : ''}${guideActions('all',true)}`);
    return guidance(setup.profileReady ? '先添加内容来源，为推荐积累参考' : '先完善账号定位，再添加内容来源', '补充账号定位，让推荐更贴合你的方向。关键词采集和对标监控可任选一种开始。', `${!setup.profileReady ? btn('完善账号定位','guide-positioning','','am-primary-action') : ''}${guideActions()}`);
  }
  function feedEmpty() {
    if (!state.accountId) return empty('请先选择账号。');
    const setup = state.data?.summary?.setup;
    if (!setup) return empty('暂无已采集作品。');
    const count = state.source === 'radar' ? setup.keywordCount : state.source === 'monitor' ? setup.bloggerCount : setup.keywordCount + setup.bloggerCount;
    return guidance(count ? '已添加来源，暂未采集到作品' : state.source === 'radar' ? '还没有关键词采集内容' : state.source === 'monitor' ? '还没有对标博主的作品' : '还没有可参考的内容', count ? '首批作品采集完成后将在这里展示。' : '添加内容来源，为选题推荐积累参考。', guideActions(state.source, count > 0));
  }
  function feedRows() {
    if (!state.feed) return empty('正在读取已采集内容…');
    return (state.feed.items || []).map(w => `<article class="monitor-work"><button type="button" class="monitor-thumb" data-tr-action="work" data-key="${esc(w.id)}" aria-label="查看作品详情">${safeUrl(w.coverSrc) ? `<img class="monitor-thumb-image" src="${esc(w.coverSrc)}" loading="lazy" alt="">` : '<span>暂无封面</span>'}</button><div class="monitor-work-copy"><button type="button" class="monitor-work-title" data-tr-action="work" data-key="${esc(w.id)}">${esc(w.title || '无标题')}</button><p class="monitor-work-meta">${esc(w.authorName || '作者未知')} · ${esc(date(w.publishedAt))} · ${esc(sourceLabels(w))}</p><div class="monitor-work-metrics">${[['点赞','likes'],['评论','comments'],['分享','shares'],['收藏','collects']].map(([label,key]) => `<span>${label} ${metric(w.metrics?.[key])}</span>`).join('')}</div></div><div class="monitor-work-actions">${workActions(w)}</div></article>`).join('') || feedEmpty();
  }
  function render() {
    const data = state.data || {}, summary = data.summary || {}, running = ['checking','pending','running'].includes(data.job?.status);
    // Skipping generation is a normal empty/unchanged state, not an error.
    const notice = state.requestError || (data.job?.status === 'skipped' && !state.manualUpdate && !data.noticeCode ? '' : data.notice);
    const subscribe = !state.requestError && data.noticeAction === 'subscribe';
    const items = (data.items || []).filter(i => !i.dismissed && !i.topicId);
    const today = items.filter(i => i.section === 'today').slice(0,3), more = items.filter(i => !today.includes(i));
    const pages = Math.max(1, Math.ceil(more.length / 5)); state.morePage = Math.min(state.morePage, pages);
    root.innerHTML = `<header class="radar-panel tr-header"><div><h2 class="am-section-title">选题推荐</h2><p>结合账号定位、复盘表现与已采集内容，找到今天值得做的选题</p><p id="trMessage" class="tr-message" role="status"${notice ? '' : ' hidden'}>${esc(text(notice))}</p>${subscribe ? btn('订阅积分套餐','subscribe','','am-secondary-action') : ''}</div><div class="tr-actions">${btn('推荐历史','history')}${btn('推荐设置','settings')}${btn(state.busy || data.job?.status === 'checking' ? '正在检查…' : running ? '正在生成…' : '更新推荐','generate','', 'am-primary-action', running || state.busy || !state.accountId)}</div></header><details class="radar-panel tr-basis"><summary><strong>账号判断依据</strong><span>${esc(text(summary.positioning) || '尚未设置账号定位')}</span><small>展开 / 收起⌄</small></summary><div class="tr-basis-grid"><div><label>账号定位</label><p>${esc(text(summary.positioning) || '暂无定位')}</p>${state.accountId ? btn('完善账号定位','guide-positioning') : ''}</div><div><label>目标受众</label><p>${esc(text(summary.audience) || '暂无受众信息')}</p></div><div><label>复盘与本周进度</label><p>${esc(summary.reviewCount ?? 0)} 条复盘记录</p><p>${esc(text(summary.week) || '暂无本周进度')}</p></div></div></details><section class="radar-panel tr-today"><div class="tr-heading"><h3>今天拍什么</h3><span>${data.generatedAt ? '生成于 ' + esc(date(data.generatedAt)) : '尚未生成推荐'}</span></div><p class="tr-intro">${today.length ? `优先看这 ${today.length} 个方向，选择适合今天制作的一条。` : "根据当前账号与已采集内容，为你筛选适合今天制作的方向。"}</p><div class="tr-today-grid">${today.map(card).join('')}</div>${!today.length ? todayEmpty(running) : ''}</section><section class="radar-panel tr-more"><div class="tr-heading"><h3>更多选题</h3><span>已排除今日优先推荐</span></div>${more.slice((state.morePage-1)*5,state.morePage*5).map(i => `<article class="tr-more-row"><div><h3>${esc(i.sourceWork?.title || i.title)}</h3><p><span>切入角度</span> ${esc(i.angle || i.reason || '暂无说明')}</p></div><small>${esc(text(i.production))}</small>${btn('加入选题库','topic',i.key)}</article>`).join('') || empty('暂无更多选题，生成推荐后将在这里展示。')}${pager(state.morePage,pages,'more-page',more.length)}</section><section class="radar-panel tr-feed"><div class="tr-heading"><h3>行业动态与参考</h3><span>当前账号已采集内容</span></div><div class="tr-tabs">${[['all','全部'],['radar','关键词视频'],['monitor','对标更新']].map(([key,label]) => `<button type="button" data-tr-action="source" data-key="${key}" aria-pressed="${state.source === key}">${label}</button>`).join('')}</div><div id="trFeedRows">${feedRows()}</div>${pager(state.page,state.feed?.pages || 1,'feed-page',state.feed?.total || 0)}</section>`;
  }
  async function loadFeed() {
    const account = state.accountId, revision = state.revision, feedRevision = ++state.feedRevision;
    if (!account) return;
    try { const data = await api('/feed?' + new URLSearchParams({source: state.source, page: state.page, pageSize: 6}), undefined, 'GET', account); if (!current(account,revision) || feedRevision !== state.feedRevision) return; state.feed = data; state.page = Number(data.page) || state.page; render(); }
    catch (e) { if (current(account,revision) && feedRevision === state.feedRevision) error(e.message); }
  }
  async function load() {
    const account = state.accountId, revision = state.revision, loadRevision = ++state.loadRevision;
    if (!account) { render(); return; }
    try { const data = await api('',undefined,'GET',account); if (!current(account,revision) || loadRevision !== state.loadRevision) return; state.data = data; render(); clearTimeout(state.timer); if (active() && ['checking','pending','running'].includes(data.job?.status) && state.polls++ < 120) state.timer = setTimeout(load,3000); }
    catch (e) { if (current(account,revision) && loadRevision === state.loadRevision) error(e.message); }
  }
  function snapshotsHtml(snapshots) {
    if (!Array.isArray(snapshots) || !snapshots.length) return empty('暂无原始指标快照');
    return `<div class="tr-snapshots"><table><thead><tr><th>采集时间</th><th>点赞</th><th>评论</th><th>分享</th><th>收藏</th></tr></thead><tbody>${snapshots.map(s => `<tr><td>${esc(date(s.at || s.collectedAt))}</td>${['likes','comments','shares','collects'].map(k => `<td>${metric(s.metrics?.[k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  function workHtml(w) {
    const snaps = (w.snapshots || []).filter(s => s.metrics?.likes != null && Number.isFinite(Number(s.metrics.likes)) && Number.isFinite(Date.parse(s.at || s.collectedAt))).sort((a,b) => Date.parse(a.at || a.collectedAt)-Date.parse(b.at || b.collectedAt));
    let chart = empty(`当前有 ${snaps.length} 次有效快照，积累至少两次后显示增长曲线。`);
    if (snaps.length >= 2) { const values = snaps.map(s => Number(s.metrics.likes)), min = Math.min(...values), max = Math.max(...values), start = Date.parse(snaps[0].at || snaps[0].collectedAt), end = Date.parse(snaps.at(-1).at || snaps.at(-1).collectedAt); chart = `<svg class="tr-chart" viewBox="0 0 600 160" role="img" aria-label="点赞历史快照曲线"><polyline fill="none" stroke="currentColor" stroke-width="2" points="${snaps.map((s,i) => `${20+560*(Date.parse(s.at || s.collectedAt)-start)/Math.max(1,end-start)},${140-120*(values[i]-min)/Math.max(1,max-min)}`).join(' ')}"/></svg><p class="tr-chart-axis">${esc(date(snaps[0].at || snaps[0].collectedAt))} — ${esc(date(snaps.at(-1).at || snaps.at(-1).collectedAt))} · ${min}–${max} 赞</p>`; }
    return `<h3>${esc(w.title)}</h3><p>${esc(w.authorName || '作者未知')} · ${esc(date(w.publishedAt))}</p><div class="tr-metrics">${[['点赞','likes'],['评论','comments'],['分享','shares'],['收藏','collects']].map(([label,key]) => `<div><span>${label}</span><strong>${metric(w.metrics?.[key])}</strong></div>`).join('')}</div><h4>点赞增长曲线</h4>${chart}${snapshotsHtml(w.snapshots)}${safeUrl(w.shareUrl) ? `<p><a href="${esc(w.shareUrl)}" target="_blank" rel="noopener noreferrer">查看原视频 ↗</a></p>` : ''}`;
  }
  function topicModal(item, work = false) {
    // Reuse the monitor form itself so labels, layout and shared styles stay aligned.
    closeModal(); restoreFocus = document.activeElement;
    dialog = document.getElementById('monitorTopicModal').cloneNode(true);
    dialog.id = 'trTopicModal'; dialog.hidden = false;
    const ids = {
      monitorTopicTitle: 'trModalTitle', monitorTopicHint: 'trTopicHint',
      monitorTopicTitleInput: 'trTitle', monitorTopicWeekSelect: 'trWeek',
      monitorTopicCategorySelect: 'trCategory', monitorTopicFormatSelect: 'trFormat',
      monitorTopicOutlineInput: 'trOutline', monitorTopicError: 'trTopicError',
      monitorTopicCancelButton: 'trTopicCancel', monitorTopicConfirmButton: 'trTopicConfirm',
    };
    dialog.querySelectorAll('[id], [for], [aria-labelledby]').forEach(node => {
      for (const attr of ['id', 'for', 'aria-labelledby']) {
        const old = node.getAttribute(attr);
        if (ids[old]) node.setAttribute(attr, ids[old]);
      }
    });
    dialog.querySelector('#trTitle').value = work ? item.title || '' : itemTitle(item);
    if (!work) dialog.querySelector('#trTitle').removeAttribute('maxlength');
    dialog.querySelector('#trOutline').value = item.angle || '';
    const errorNode = dialog.querySelector('#trTopicError');
    errorNode.classList.add('tr-modal-error'); errorNode.hidden = true; errorNode.textContent = '';
    const cancel = dialog.querySelector('#trTopicCancel');
    cancel.dataset.trAction = 'close';
    const confirm = dialog.querySelector('#trTopicConfirm');
    confirm.disabled = false;
    confirm.dataset.trAction = work ? 'confirm-work-topic' : 'confirm-topic';
    confirm.dataset.key = work ? item.id : item.key;
    const pickerConfigs = [
      ['trWeek', 'topicWeek', '计划安排', [['current','本周选题'],['next','下周选题']], 'current'],
      ['trCategory', 'topicCategory', '选题分类', [['highlight','重点'],['daily','日常'],['series','系列'],['test','测试']], 'daily'],
      ['trFormat', 'topicFormat', '内容形式', [['video','视频'],['article','图文']], 'video'],
    ];
    const pickers = [];
    const closePickers = () => pickers.forEach(({button, menu}) => {
      menu.hidden = true; button.setAttribute('aria-expanded', 'false');
    });
    pickerConfigs.forEach(([id, key, label, options, initial]) => {
      const field = dialog.querySelector(`[data-monitor-picker="${key}"]`);
      field.removeAttribute('data-monitor-picker');
      const host = field.querySelector('.topics-select-control');
      const input = dialog.querySelector('#' + id); input.value = initial;
      // The source form may already have initialized controls; rebuild with local IDs/listeners.
      host.innerHTML = `<button type="button" id="${id}Button" class="am-input topics-select-button" aria-haspopup="menu" aria-expanded="false" aria-label="${label}"><span class="topics-select-value"></span></button><div class="topics-select-menu" role="menu" aria-label="${label}" hidden></div>`;
      const button = host.querySelector('button'), menu = host.querySelector('.topics-select-menu');
      const render = () => {
        button.firstElementChild.textContent = options.find(([value]) => value === input.value)[1];
        menu.innerHTML = options.map(([value, name]) => `<button type="button" role="menuitemradio" aria-checked="${value === input.value}" class="${value === input.value ? 'is-current' : ''}" data-value="${value}">${value === input.value ? '✓ ' : ''}${name}</button>`).join('');
      };
      render(); pickers.push({button, menu});
      button.addEventListener('click', () => {
        const opening = menu.hidden; closePickers();
        menu.hidden = !opening; button.setAttribute('aria-expanded', String(opening));
      });
      menu.addEventListener('click', event => {
        const option = event.target.closest('[data-value]'); if (!option) return;
        input.value = option.dataset.value; render(); closePickers(); button.focus();
      });
    });
    document.body.append(dialog);
    dialog.addEventListener('click', event => {
      if (!event.target.closest('.topics-select-control')) closePickers();
      if (event.target === dialog) closeModal(); else handleAction(event);
    });
    dialog.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        event.preventDefault();
        const opened = pickers.find(({menu}) => !menu.hidden);
        if (opened) { closePickers(); opened.button.focus(); } else closeModal();
      }
      if (event.key === 'Tab') {
        const nodes = [...dialog.querySelectorAll('button:not(:disabled),input:not([type="hidden"]),textarea')].filter(node => node.getClientRects().length);
        if (event.shiftKey && document.activeElement === nodes[0]) { event.preventDefault(); nodes.at(-1).focus(); }
        else if (!event.shiftKey && document.activeElement === nodes.at(-1)) { event.preventDefault(); nodes[0].focus(); }
      }
    });
    dialog.querySelector('#trTitle').focus();
  }
  async function handleAction(event) {
    const button = event.target.closest('[data-tr-action]'); if (!button || button.disabled) return;
    const action = button.dataset.trAction, key = button.dataset.key, account = state.accountId, revision = state.revision;
    if (action === 'close') { closeModal(); return; }
    if (!account || (action === 'generate' && state.busy)) return;
    const item = findItem(key), work = findWork(key);
    const valid = () => current(account,revision);
    try {
      if (action === 'subscribe') { await window.accountModule?.openPlans?.(); return; }
      if (action === 'guide-positioning') { window.settingsModule?.openPositioning?.(); return; }
      if (action.startsWith('guide-')) {
        const module = action.includes('radar') ? 'radar' : 'monitor';
        window.selectWorkspaceModule?.(module);
        if (!action.endsWith('-view')) document.getElementById(module === 'radar' ? 'radarAddKeywordButton' : 'monitorAddBloggerButton')?.click();
        return;
      }
      if (action === 'more-page') { state.morePage = Number(key); render(); return; }
      if (action === 'source' || action === 'feed-page') { if (action === 'source') { state.source = key; state.page = 1; } else state.page = Number(key); state.feed = null; render(); await loadFeed(); return; }
      if (action === 'topic' && item) { topicModal(item); return; }
      if (action === 'work-topic' && work) { topicModal(work,true); return; }
      if (action === 'breakdown' && work?.shareUrl) { await window.breakdownModule?.start(work.shareUrl,work.title); return; }
      if (action === 'history') {
        const seen = new Set(), currentKeys = new Set((state.data?.items || []).map(i => i.key));
        const rows = allItems().filter(i => { if (seen.has(i.key)) return false; seen.add(i.key); return true; });
        modal('推荐历史',rows.map(i => `<article class="tr-more-row"><div><h3>${esc(itemTitle(i))}</h3><p>${i.topicId ? '已加入选题库' : i.dismissed ? '暂不考虑' : currentKeys.has(i.key) ? '推荐中' : '历史推荐'}</p></div>${i.dismissed ? btn('恢复推荐','restore',i.key) : !i.topicId ? btn('加入选题库','topic',i.key) : ''}</article>`).join('') || empty('暂无推荐历史'), '', 'history'); return;
      }
      if (action === 'settings') {
        const token = modal('推荐设置',empty('正在读取设置…')); const result = await api('/settings',undefined,'GET',account); if (!valid() || token !== state.modalRevision) return; const s = result.settings || result;
        modal('推荐设置', `<p class="tr-intro">设置仅用于当前账号的选题推荐。</p>${[['trAi','每天自动生成选题',s.aiEnabled],['trRadar','使用内容采集',s.sources?.radar],['trMonitor','使用对标监控',s.sources?.monitor]].map(([id,label,checked]) => `<label class="settings-switch-row"><span>${label}</span><input id="${id}" class="settings-switch" type="checkbox" role="switch"${checked ? ' checked' : ''}></label>`).join('')}<label class="home-field"><span>每日生成时间</span><input id="trTime" class="am-input" type="time" value="${esc(s.aiDailyTime || '10:30')}"></label>`, btn('保存设置','save-settings','','am-primary-action')); return;
      }
      if (action === 'work' && work?.sourceRecords?.length) {
        const ref = work.sourceRecords.find(r => r.source === 'monitor') || work.sourceRecords[0];
        const module = ref.source === 'monitor' ? window.monitorModule : window.radarModule;
        if (module?.openWork) { await module.openWork(account,ref.id); return; }
      }
      if (action === 'work') {
        const token = modal('作品详情',empty('正在读取…'));
        const data = await api(`/works/${encodeURIComponent(key)}`,undefined,'GET',account);
        if (!valid() || token !== state.modalRevision) return;
        modal('作品详情',workHtml(data.sourceWork || data)); return;
      }
      button.disabled = true;
      const modalToken = state.modalRevision;
      if (action === 'generate') {
        clearTimeout(state.timer); state.loadRevision++;
        state.busy = true; state.requestError = ''; state.manualUpdate = true; render();
        const data = await api('/generate',{},'POST',account);
        if (valid()) { state.loadRevision++; state.data = data; state.polls = 0; clearTimeout(state.timer);
          if (['checking','pending','running'].includes(data.job?.status)) state.timer = setTimeout(load, 1000);
        }
      }
      else if (action === 'save-settings') { if (window.WorkbenchDateTimePicker?.validateInputs(dialog.querySelector('#trTime')) === false) return; await api('/settings',{aiEnabled: dialog.querySelector('#trAi').checked,aiDailyTime: dialog.querySelector('#trTime').value,sources:{radar:dialog.querySelector('#trRadar').checked,monitor:dialog.querySelector('#trMonitor').checked}},'PATCH',account); if (valid() && modalToken === state.modalRevision) closeModal(); if (valid()) await load(); }
      else if (action.startsWith('confirm-')) { const title = dialog.querySelector('#trTitle').value.trim(); if (!title) throw new Error('请填写选题标题'); const body = {title,weekPlan:dialog.querySelector('#trWeek').value,category:dialog.querySelector('#trCategory').value,format:dialog.querySelector('#trFormat').value,outline:dialog.querySelector('#trOutline').value}; await api(`${action === 'confirm-work-topic' ? '/works' : ''}/${encodeURIComponent(key)}/topic`,body,'POST',account); if (valid() && modalToken === state.modalRevision) closeModal(); if (valid()) { await load(); window.topicsModule?.invalidate?.(); } }
      else if (action === 'dismiss' || action === 'restore') { await api(`/${encodeURIComponent(key)}/${action}`,{},'POST',account); if (valid() && modalToken === state.modalRevision) closeModal(); if (valid()) await load(); }
      else if (action === 'save' && work) { await api(`/works/${encodeURIComponent(key)}/saved`,{saved:!work.saved},'POST',account); if (valid()) await loadFeed(); }
    } catch(e) { if (valid()) error(e.message); }
    finally { if (valid()) { if (action === 'generate') state.busy = false; if (button.isConnected) button.disabled = false; if (action === 'generate') render(); } }
  }
  function onAccountChange(accountId) {
    state.revision++; state.accountId = accountId || ''; state.data = null; state.feed = null; state.page = 1; state.morePage = 1; state.source = 'all'; state.busy = false; state.requestError = ''; state.manualUpdate = false; state.polls = 0; clearTimeout(state.timer); closeModal(); render();
    if (active()) { load(); loadFeed(); }
  }
  root.addEventListener('click',handleAction);
  window.addEventListener('workspace-module-change',event => { clearTimeout(state.timer); if (event.detail?.module === 'topicRecommendations') { const id = typeof activeAccountId !== 'undefined' ? activeAccountId : state.accountId; if (id !== state.accountId) onAccountChange(id); else { state.polls = 0; load(); loadFeed(); } } });
  window.addEventListener('subscription-refreshed', () => { if (state.accountId && active()) { state.requestError = ''; load(); } });
  window.topicRecommendationsModule = { onAccountChange, refresh: load, render };
  render();
})();
