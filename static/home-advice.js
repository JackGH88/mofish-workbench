/* Account advice reads cached results; only explicit actions request generation. */
(() => {
  const root = document.getElementById('homeAdvicePanel');
  if (!root) return;
  const state = {accountId:'', view:null, error:'', busy:false, confirm:null, timer:null, version:0, accountVersion:0};
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const stamp = value => value ? new Date(value).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai',hour12:false}) : '暂无';
  const base = id => '/api/accounts/'+encodeURIComponent(id)+'/home/advice';
  async function api(url, method='GET', body) {
    const response = await fetch(url, {method, ...(body ? {headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail?.message || data.message || '请求失败，请稍后重试。');
    return data;
  }
  function render() {
    const view=state.view, advice=view?.advice, running=state.busy || view?.status==='running';
    root.innerHTML=`<div class="home-panel-head"><h3 class="home-panel-title">账号下一步建议</h3>
      <div class="home-advice-controls"><button type="button" class="home-link-button" data-advice-action="refresh" ${running || !view?.ready?'disabled':''}>${running?'更新中…':'更新'}</button>
      <button type="button" class="home-link-button" data-advice-action="auto" ${running?'disabled':''}>自动更新${view?.enabled?'已开':'已关'}</button></div></div>`;
    if (state.confirm) {
      const auto=state.confirm.type==='auto';
      root.innerHTML+=`<div class="home-advice-topic" role="status"><p class="home-advice-topic-title">${auto?'开启每日自动更新':'更新账号建议'}</p>
        <p class="home-advice-hint">${auto?'每天首次复盘成功同步且数据有变化时最多更新一次；当天手动更新成功也计入。':'使用已保存的作品数据更新账号建议。'}</p>
        <div class="home-advice-actions"><button type="button" class="home-advice-add" data-advice-action="confirm" ${running?'disabled':''}>${auto?'确认开启':'确认更新'}</button><button type="button" class="home-link-button" data-advice-action="cancel">取消</button></div></div>`;
    }
    if (state.error || view?.error) root.innerHTML+=`<p class="home-advice-hint" role="alert">${esc(state.error || view.error)}</p>`;
    if (advice && view?.reason) root.innerHTML+=`<p class="home-advice-hint">${esc(view.reason)}</p>`;
    if (!advice) {
      root.innerHTML+=`<p class="home-advice-title">${running?'正在分析账号作品':view?.ready?'还没有生成建议':'暂无账号分析建议'}</p>
        <p class="home-advice-hint">${esc(view?.reason || (view?.ready?'点击更新，结合账号定位与自身复盘生成下一条内容建议。':state.accountId?'正在读取账号数据…':'请先选择账号。'))}</p>`;
      if (view && !view.ready) {
        const nextStep = {
          profile_incomplete: ['settings', '完善账号定位 →'],
          insufficient_data: ['review', '查看作品复盘 →'],
        }[view.reasonCode];
        if (nextStep) root.innerHTML+=`<div class="home-advice-actions"><button class="home-link-button" type="button" data-advice-action="${nextStep[0]}">${nextStep[1]}</button></div>`;
      }
    } else {
      root.innerHTML+=`<div class="home-advice-recommendation"><p class="home-advice-eyebrow">优先尝试 · 内容方向</p>
        <h4 class="home-advice-title">${esc(advice.title)}</h4><p class="home-advice-hint">${esc(advice.reason)}</p></div>
        <div class="home-advice-evidence">${(advice.evidence||[]).map(m=>`<span>${esc(m.label)} <strong>${esc(m.value)}${esc(m.unit)}</strong><small>（${esc(m.count)} 篇有效）</small></span>`).join('')}</div>
        <div class="home-advice-topic"><p class="home-advice-eyebrow">下一条可以拍</p><p class="home-advice-topic-title">${esc(advice.topicTitle)}</p><p class="home-advice-hint">${esc(advice.angle)}</p></div>
        <div class="home-advice-actions"><button type="button" class="home-advice-add" data-advice-action="topic">${advice.topicId?'查看选题':'＋ 加入选题'}</button>
        <details class="home-advice-details"><summary>查看分析依据 ↗</summary><div class="home-advice-detail-body">
        <p>范围：${esc(advice.window?.from)} 至 ${esc(advice.window?.to)} 发布的 ${esc(advice.workCount)} 篇公开视频。指标为截至采集时的累计表现。</p>
        <p>数据采集时间：${esc(stamp(advice.oldestCollectedAt || advice.collectedAt))} 至 ${esc(stamp(advice.collectedAt))}</p>
        ${advice.groupLabel?`<p>分组依据：${esc(advice.groupLabel)}</p>`:''}
        <p>数据观察：${esc(advice.reason)}</p><p>待验证假设：${esc(advice.hypothesis)}</p>
        <p>样本门槛不代表统计显著性，建议需通过后续作品验证。</p>
        ${(advice.references||[]).map(r=>`<button class="home-link-button" type="button" data-advice-work="${esc(r.id)}">${esc(r.title)} →</button>`).join('')}</div></details></div>
        <p class="home-advice-meta">${esc(advice.window?.from)} 至 ${esc(advice.window?.to)} · ${esc(advice.workCount)} 篇作品<br>建议生成：${esc(stamp(advice.generatedAt))}${view.stale?'<br>分析输入已变化，当前展示上次建议。':''}</p>`;
    }
    if (view?.attemptedAt) root.innerHTML+=`<p class="home-advice-meta">最近尝试：${esc(stamp(view.attemptedAt))} · ${({running:'生成中',failed:'更新失败',ready:'已完成'})[view.status]||'等待更新'}</p>`;
  }
  async function load() {
    const id=state.accountId, version=++state.version;
    if (!id) return;
    try {
      const view=await api(base(id));
      if (id!==state.accountId || version!==state.version) return;
      state.view=view; state.error='';
    } catch(error) {
      if(id!==state.accountId || version!==state.version)return;
      state.error=error.message;
    }
    if(id!==state.accountId || version!==state.version)return;
    render();
    window.clearTimeout(state.timer);
    if(state.view?.status==='running' && !document.getElementById('homeContent')?.hidden)
      state.timer=window.setTimeout(load,2500);
  }
  function onAccountChange(id) {
    window.clearTimeout(state.timer);
    state.accountId=String(id||''); state.version++; state.accountVersion++; state.view=null; state.error=''; state.confirm=null; state.busy=false;
    render(); if(id) load();
  }
  async function action(kind) {
    const id=state.accountId, epoch=state.accountVersion;
    const current=()=>id===state.accountId && epoch===state.accountVersion;
    if(!id || state.busy)return;
    if(kind==='cancel'){state.confirm=null;render();return;}
    if(kind==='settings'){window.settingsModule?.openPositioning?.();return;}
    if(kind==='review'){window.selectWorkspaceModule?.('review');return;}
    if(kind==='topic') {
      const advice=state.view?.advice, topics=window.topicsModule;
      if(!advice || !topics)return;
      if(advice.topicId) {
        await topics.refresh();
        if(!current())return;
        const topic=topics.state.topics.find(t=>t.id===advice.topicId);
        if(!topic){state.error='关联选题已删除，请更新建议后重新安排。';render();return;}
        topics.actions.selectWeek(topic.weekStart);
        window.selectWorkspaceModule?.('topics'); topics.actions.openTopicEditor(topic.id);
      } else {
        topics.actions.beginAdviceDraft?.(advice,id);
        window.selectWorkspaceModule?.('topics');
      }
      return;
    }
    if(kind==='auto' && !state.view?.enabled){state.confirm={type:'auto'};state.error='';render();return;}
    state.busy=true;state.error='';render();
    try {
      if(kind==='confirm') {
        const choice=state.confirm;
        if(!choice)return;
        const view=await api(base(id)+(choice.type==='auto'?'/config':'/refresh'),choice.type==='auto'?'PUT':'POST',
          {enabled:true});
        if(!current())return;
        state.view=view;state.confirm=null;
      } else if(kind==='auto' && state.view?.enabled) {
        const view=await api(base(id)+'/config','PUT',{enabled:false});
        if(!current())return;
        state.view=view;
      } else {
        const view=await api(base(id)+'/refresh','POST',{});
        if(!current())return;
        state.view=view;
      }
    }catch(error){if(current())state.error=error.message;}
    finally{if(current()){state.busy=false;render();if(state.view?.status==='running')load();}}
  }
  root.addEventListener('click',async event=>{
    const button=event.target.closest('[data-advice-action]');
    if(button){try { await action(button.dataset.adviceAction); } catch (error) { state.error=error.message; render(); } return;}
    const work=event.target.closest('[data-advice-work]');
    if(work){window.selectWorkspaceModule?.('review');window.reviewModule?.actions?.openAdviceWork?.(work.dataset.adviceWork,state.accountId);}
  });
  window.addEventListener('workspace-module-change',event=>{
    window.clearTimeout(state.timer);
    if(event?.detail?.module==='today')load();
  });
  window.addEventListener('focus',()=>{if(!document.getElementById('homeContent')?.hidden)load();});
  window.homeAdviceModule={onAccountChange,refresh:load,state};
  render();
})();
