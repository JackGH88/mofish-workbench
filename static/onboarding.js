/* 首页账号起步：只导航。所有完成状态由服务端的业务证据归并。 */
(() => {
  'use strict';
  const root = document.getElementById('homeOnboarding');
  if (!root) return;
  const modal = document.getElementById('onboardingModal');
  const keys = ['preparation', 'sources', 'creation', 'publication', 'review'];
  const labels = ['账号准备', '准备内容来源', '首次创作', '制作与发布', '数据复盘'];
  const state = { account: '', view: null, version: 0, error: '', module: 'today', guided: false, draft: {}, step: 0, login: null, connection: {}, busy: false };
  let queue = Promise.resolve(), draftTimer, pollTimer, refreshTimer, draftRevision = 0, modalEpoch = 0, enhancementVersion = 0, connectionKey = '';
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const toast = (message, type='success') => window.showToast?.(message, type);
  async function api(url, options={}) {
    const response = await fetch(url, {...options, headers: {'Content-Type':'application/json', ...options.headers}});
    const result = await response.json();
    if (!response.ok) throw new Error(result?.detail?.message || result?.detail || '请求未完成，请稍后重试');
    return result;
  }
  const path = account => '/api/accounts/' + encodeURIComponent(account);
  const button = (text, action, primary=false, disabled=false) => `<button type="button" class="am-${primary?'primary':'secondary'}-action" data-ob-action="${action}" ${disabled?'disabled':''}>${text}</button>`;
  const link = (text, action) => `<button type="button" class="home-link-button" data-ob-action="${action}">${text}</button>`;
  function nextAction(v) {
    if (v.currentStep === 'preparation') return {title:'完成账号准备，让后续创作更适合你', copy:'连接抖音、同步作品，确认账号定位和目标人群。没有作品也可以先完善定位。', action:'prepare', label:'继续账号准备', route:'账号连接与定位向导'};
    if (v.currentStep === 'sources') return {title:'准备内容来源，为选题积累参考', copy:'添加采集关键词和对标博主，为后续选题积累参考内容。', action:'radar', label:'添加内容采集', secondary:'monitor', secondLabel:'添加对标监控', route:'完成条件：至少一个采集关键词 + 一个对标博主'};
    if (v.currentStep === 'creation') return {title:v.current.hasTopics?'选题已准备好，去创作第一篇脚本':'去本周选题，添加第一条想做的内容', copy:'在对应模块完成选题与创作。保存一篇有效脚本后，这一步才会完成。', action:v.current.hasTopics?'create':'topics', label:v.current.hasTopics?'前往创作 →':'添加选题 →', secondary:v.current.hasTopics?'topics':'create', secondLabel:v.current.hasTopics?'查看选题':'已有想法，直接创作', route:v.current.hasTopics?'首页 → 本周选题 → 创作 → 脚本':'首页 → 本周选题 → 创作 → 脚本'};
    if (v.currentStep === 'publication') return {title:'脚本已保存，去准备标题、封面和发布素材', copy:'进入脚本工作台继续编辑、完善标题与封面，完成拍摄剪辑后，在发布阶段准备素材并记录结果。', action:'scripts', label:'前往脚本工作台 →', secondary:'publish', secondLabel:'直接前往发布', route:'脚本 → 编辑 / 标题 / 封面 / 发布'};
    if (v.currentStep === 'review') return {title:'去复盘页查看表现，记录下一次尝试', copy:'同步作品数据，查看详情并保存一条复盘观察。暂未提供的指标不视为零。', action:'review', label:'前往复盘 →', route:'首页 → 复盘 → 作品详情'};
    return {title:'你已走通一次完整的运营流程', copy:'之后按自己的节奏创作，需要更多灵感时，再去内容采集和对标监控发现内容方向。', action:'topics', label:'开始下一次选题 →', route:'起步已完成 · 可以关闭引导'};
  }
  function render() {
    // Old collapsed preferences no longer hide the five-step guide.
    const v = state.view ? {...state.view, collapsed:false} : null;
    root.hidden = !state.account || v?.visible === false || Boolean(v?.dismissed);
    if (root.hidden) return;
    if (state.error) root.innerHTML = `<div class="home-panel-head"><h3 class="home-panel-title">账号起步引导</h3>${button('重试','retry')}</div><p class="home-advice-hint">${esc(state.error)}${v?'；已有进度保留。':''}</p>`;
    else if (!v) root.innerHTML = '<h3 class="home-panel-title">账号起步引导</h3><p class="home-advice-hint">正在读取进度…</p>';
    else {
      const next = nextAction(v), count=keys.filter(k=>v.steps[k].completed).length;
      const primaryAction=button(next.label,next.action,true);
      const secondaryAction=!v.collapsed&&next.secondary?button(next.secondLabel,next.secondary):'';
      const actions=v.currentStep==='sources'?`<div class="onboarding-source-options">${[
        ['radar','内容采集','添加内容采集','至少添加一个关键词，持续发现相关内容。',v.current.hasKeywords],
        ['monitor','对标监控','添加对标监控','至少添加一个对标博主，关注新作品和选题。',v.current.hasBloggers]
      ].map(([action,title,label,copy,done])=>`<div class="onboarding-source-option"><div class="onboarding-source-heading"><strong>${title}</strong><span class="onboarding-source-status ${done?'is-done':''}">${done?'✓ 已添加':'待添加'}</span></div><p class="home-advice-hint">${copy}</p><div>${button(label,action,!done)}</div></div>`).join('')}</div>`:primaryAction+secondaryAction;
      const missing=[];
      if(v.steps.preparation.completed&&!v.current.profileReady) missing.push('当前定位缺失，可重新完善');
      if(v.steps.creation.completed&&!v.current.hasScript) missing.push('原脚本已不在当前账号，入口将打开脚本列表');
      if(v.steps.review.completed&&!v.current.hasReview) missing.push('原复盘记录已变更，学习进度保留');
      root.innerHTML = `<div class="home-panel-head"><div class="home-panel-title-row"><h3 class="home-panel-title">${count===keys.length?'账号起步已完成':'账号起步引导'}</h3><span class="home-panel-count">${count} / ${keys.length}</span></div>${link('我已知悉使用，关闭引导！','dismiss')}</div>${v.collapsed?'':`<div class="onboarding-track">${keys.map((k,i)=>`<div class="onboarding-step ${v.steps[k].completed?'is-done':v.currentStep===k?'is-current':''}"><span class="onboarding-number">${v.steps[k].completed?'✓':i+1}</span><div><strong>${labels[i]}</strong><small>${v.steps[k].completed?'已完成':v.currentStep===k?'当前步骤':'待开始'}</small></div></div>`).join('')}</div>`}<div class="onboarding-next"><div><h4>${next.title}</h4>${v.collapsed?'':`<p class="home-advice-hint">${next.copy}</p>`}</div><div class="onboarding-actions">${actions}</div></div>${missing.length?`<div class="onboarding-foot"><p class="home-advice-hint">${missing.join('；')}。</p>${!v.current.profileReady?link('完善定位','prepare'):''}</div>`:''}${v.collapsed?'':`<div class="onboarding-foot"><span>${next.route}</span><span>根据已保存成果更新，打开页面不计为完成</span></div>`}`;
    }
  }
  async function refresh() {
    const account=state.account, version=++state.version;
    if(!account)return;
    try {
      const view=await api(path(account)+'/onboarding');
      if(account!==state.account||version!==state.version)return;
      if(view.collection?.status==='login_required'&&state.view?.collection?.status!=='login_required'){state.login=null;state.connection.checked=true;}
      state.view=view;state.error='';render();
      // Poll only read-only progress while collection or a guided workflow is visible.
      clearTimeout(pollTimer);
      if (view.visible && (view.collection?.running || (state.guided && state.module!=='today'))) pollTimer=setTimeout(refresh,5000);
      updateConnection();
    } catch(e) {if(account===state.account&&version===state.version){state.error=e.message;render();}}
  }
  function changed() {clearTimeout(refreshTimer);refreshTimer=setTimeout(refresh,150);}
  function persist(patch, account=state.account) {
    const payload=JSON.parse(JSON.stringify(patch));
    const task=queue.catch(()=>{}).then(()=>api(path(account)+'/onboarding',{method:'PUT',body:JSON.stringify(payload)}));
    queue=task;
    return task;
  }
  function saveDraft() {clearTimeout(draftTimer);return persist({draft:state.draft,preparationStep:state.step});}
  function connectionView() {
    const c=state.view?.collection||{}, local=state.connection;
    const started=local.attempted||['queued','running','success','partial','failed','login_required'].includes(c.status);
    const base={secondary:started?'先完善定位':'跳过，先完善定位', reopen:Boolean(local.opened), disabled:false};
    const result=(message,label,action,extra={})=>({...base,message,label,action,...extra});
    if(local.pending==='login')return result('正在打开抖音登录页…','打开中…','login',{disabled:true,reopen:false});
    if(local.pending==='check')return result('正在检查登录状态…','检查中…','check',{disabled:true,reopen:false});
    if(local.pending==='sync')return result('正在启动作品同步…','启动中…','sync',{disabled:true,reopen:false});
    if(c.running||['queued','running'].includes(c.status))return result('作品正在同步，你可以先完善账号定位。','继续完善定位','position',{secondary:'',reopen:false});
    if(c.status==='success'&&!local.error)return result(c.lastResult?.count===0&&c.lastResult?.scope==='recent30'?'近 30 天暂无作品，可以先完善定位。':'作品已同步，接下来确认你的内容方向。','继续完善定位','position',{secondary:'',reopen:false});
    if(local.error)return result(local.error,local.errorAction==='sync'?'重试同步':local.errorAction==='check'?'我已登录，检查连接':'去登录抖音',local.errorAction);
    if(['failed','partial'].includes(c.status)&&state.login?.status==='logged_in')return result(c.status==='partial'?'部分作品已同步，已有数据已保留。':'同步暂未完成，已有数据已保留。','重试同步','sync');
    if(state.login?.status==='logged_in')return result('已连接抖音。同步最近 30 天的作品，用于后续复盘。','同步近 30 天作品','sync',{reopen:false});
    if(local.opened)return result(local.checked?'尚未检测到登录，请先在抖音页面完成登录。':'完成登录后，回到这里检查连接。','我已登录，检查连接','check');
    return result(started?'请先重新确认登录，已有同步数据会保留。':'在打开的抖音页面登录你要运营的账号。','去登录抖音','login');
  }
  function connectionVisual(ui) {
    const c=state.view?.collection||{};
    const active=Boolean(state.connection.pending||c.running||['queued','running'].includes(c.status));
    let kind='browser', title='在专用浏览器中登录';
    if(active){kind='sync';title=state.connection.pending==='check'?'检查账号连接':state.connection.pending==='login'?'打开登录页面':'同步作品数据';}
    else if(state.connection.error||['partial','failed','login_required'].includes(c.status)){kind='alert';title='需要再确认一下';}
    else if(c.status==='success'){kind='check';title='作品同步完成';}
    else if(ui.action==='sync'){kind='sync';title='账号已连接';}
    else if(ui.action==='check'){kind='browser';title='登录后，回到这里';}
    const paths={browser:'<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M3 9h18M7 6.5h.01M10 6.5h.01M10 13l3 2-3 2"/>',check:'<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',sync:'<path d="M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1"/>',alert:'<circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 17h.01"/>'};
    return `<span class="onboarding-connection-icon${active?' is-active':''}" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${paths[kind]}</svg></span><div class="onboarding-connection-copy"><strong>${title}</strong><p>${esc(ui.message)}</p>${ui.reopen?link('重新打开登录页','login'):''}</div>`;
  }
  function updateConnection() {
    if(modal.open&&state.step===0&&connectionKey!==JSON.stringify(connectionView()))drawModal();
  }
  function field(label,key,placeholder='',area=false) {return `<label class="am-field"><span>${label}</span>${area?`<textarea class="am-textarea" data-ob-field="${key}" maxlength="2000" placeholder="${esc(placeholder)}">${esc(state.draft[key])}</textarea>`:`<input class="am-input" data-ob-field="${key}" maxlength="2000" placeholder="${esc(placeholder)}" value="${esc(state.draft[key])}">`}</label>`;}
  function resizePositioningFields() {
    if (!modal.open) return;
    for (const field of modal.querySelectorAll('textarea[data-ob-field]')) {
      field.style.height='0px';
      field.style.height=Math.max(76,(field.scrollHeight || 76) + (field.offsetHeight - field.clientHeight))+'px';
    }
  }
  window.addEventListener('resize',resizePositioningFields);
  if (typeof ResizeObserver !== 'undefined') {
    let width=-1;
    new ResizeObserver(entries=>{const next=entries[0].contentRect.width;if(next!==width){width=next;resizePositioningFields();}}).observe(modal);
  }
  function drawModal() {
    let title,body,footer;
    if(state.step===0){
      const ui=connectionView();connectionKey=JSON.stringify(ui);
      title='连接你的抖音账号';
      body=`<p class="home-advice-hint">同步作品和表现，为后续复盘提供数据。</p><div class="onboarding-connection" role="status" aria-live="polite">${connectionVisual(ui)}</div>`;
      footer=`${ui.secondary?link(ui.secondary,'position'):'<span></span>'}${button(ui.label,ui.action,true,ui.disabled)}`;
    }
    else if(state.step===1){title='账号准备 · 说说你的方向';body=`<p class="home-advice-hint">历史作品反映过去的内容，接下来的方向由你确认。</p>${field('你擅长什么，或提供什么？','offer','例如：AI 办公工具实操')}${field('你希望谁来看，他有什么问题？','audience','例如：想减少重复工作的职场新人')}${field('你希望账号实现什么目标？','goal','例如：建立专业影响力，获得培训咨询')}`;footer=`${link('← 返回连接','connect')}${button('整理定位草稿','draft',true)}`;}
    else{title='账号准备 · 确认定位';body=`<p class="home-advice-hint">以下根据你的回答整理，可手动修改，也可使用 Agent 完善。确认保存后才应用于后续创作。</p>${field('商业定位','businessPositioning','',true)}${field('面向人群','targetAudience','',true)}<div class="onboarding-actions-row">${button('Agent完善','enhance',false,state.busy)}<span class="home-advice-hint">${state.busy?'正在完善…':'沿用现有 Agent 完善功能'}</span></div>`;footer=`${link('← 修改回答','position')}${button('保存定位，完成账号准备','saveProfile',true,state.busy)}`;}
    modal.innerHTML=`<header class="onboarding-modal-header"><h2>${title}</h2><button type="button" class="onboarding-close am-modal-dismiss" data-ob-action="close" aria-label="关闭账号准备"><svg class="am-modal-close-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true" focusable="false"><path d="M6 6l12 12M18 6 6 18"/></svg></button></header><div class="onboarding-modal-body">${body}</div><footer class="onboarding-modal-footer">${footer}</footer>`;
    resizePositioningFields();
  }
  async function prepare() {
    const account=state.account, epoch=++modalEpoch;
    await queue.catch(()=>{});await refresh();
    if(account!==state.account||epoch!==modalEpoch||!state.view)return;
    state.draft={...state.view.draft};state.step=state.view.preparationStep;state.login=null;state.connection={};
    // Read existing saved positioning rather than replacing it with an empty setup form.
    if(!state.draft.businessPositioning&&!state.draft.targetAudience){
      const p=await api(path(account)+'/positioning');
      if(account!==state.account||epoch!==modalEpoch)return;
      if(p.hasPositioning)state.draft.businessPositioning=p.profile.businessPositioning;
      if(p.hasAudience)state.draft.targetAudience=p.profile.targetAudience;
      if(p.hasPositioning||p.hasAudience)state.step=2;
    }
    drawModal();modal.showModal();resizePositioningFields();
  }
  async function closeModal() {
    await saveDraft();modalEpoch++;modal.close();await refresh();
  }
  async function navigate(action) {
    const account=state.account;
    await refresh();if(account!==state.account)return;
    if(window.prepareOnboardingNavigation && !await window.prepareOnboardingNavigation())return;
    if(account!==state.account)return;
    state.guided=true;
    if(action==='home'){window.selectWorkspaceModule?.('today');return;}
    if(action==='scripts'||action==='publish'){
      const id=state.view?.targets.scriptId;
      window.selectScriptStatusFilter?.('all');
      window.selectWorkspaceModule?.('scripts');
      if(id){try{await window.openScriptById?.(id,account);if(account===state.account&&action==='publish')document.getElementById('publishStageButton')?.click();}catch(e){toast('脚本已不可用，已返回脚本列表','info');}}
    }else{
      window.selectWorkspaceModule?.(action);
      if(action==='review'&&state.view?.targets.workId)await window.reviewModule?.actions?.openAdviceWork?.(state.view.targets.workId,account);
    }
  }
  async function action(name) {
    const account=state.account, epoch=modalEpoch;
    if(name==='retry')return refresh();
    if(name==='prepare')return prepare();
    if(['topics','create','scripts','publish','review','home','radar','monitor'].includes(name))return navigate(name);
    if(name==='dismiss'&&state.view){await persist({dismissed:true});return refresh();}
    if(name==='close')return closeModal();
    if(name==='connect'||name==='position'){
      if(name==='position'&&state.step===0)await persist({connectionSkipped:state.login?.status!=='logged_in'});
      if(account!==state.account||epoch!==modalEpoch)return;
      state.step=name==='connect'?0:1;await saveDraft();if(account===state.account&&epoch===modalEpoch)drawModal();return;
    }
    if(name==='draft'){
      if(!['offer','audience','goal'].every(k=>state.draft[k]?.trim()))throw new Error('请先简要回答三个问题');
      state.draft.businessPositioning=`围绕${state.draft.offer.trim()}提供内容与价值。\n账号目标：${state.draft.goal.trim()}。`;
      state.draft.targetAudience=state.draft.audience.trim();
      if(state.draft.businessPositioning.length>2000)throw new Error('整理后的定位超过 2000 字，请精简回答');
      state.step=2;await saveDraft();if(account===state.account&&epoch===modalEpoch)drawModal();return;
    }
    if(['login','check','sync'].includes(name)){
      if(state.connection.pending)return;
      if(name==='sync'&&(state.login?.status!=='logged_in'||state.view?.collection?.running))return;
      state.connection={...state.connection,pending:name,error:''};updateConnection();
      try {
        const result=await api(path(account)+(name==='login'?'/publish-login':name==='check'?'/publish-status?platform=douyin':'/review/collect?scope=recent30'),name==='check'?{}:{method:'POST',...(name==='login'?{body:JSON.stringify({platform:'douyin'})}:{})});
        if(account!==state.account||epoch!==modalEpoch)return;
        if(name==='login'){state.login=null;state.connection.opened=true;state.connection.checked=false;}
        if(name==='check'){state.login=result;state.connection.checked=true;state.connection.opened=true;}
        if(name==='sync'){
          state.connection.attempted=true;
          state.view.collection={...state.view.collection,status:'queued',running:true};
          toast('已开始同步作品');await refresh();
        }
      }catch(e){
        if(account!==state.account||epoch!==modalEpoch)return;
        state.connection.error=name==='login'?'暂时无法打开登录页，请重试。':name==='check'?'暂时无法检查，请重试。':'同步暂未启动，已有数据已保留。';
        state.connection.errorAction=name;
        if(name==='sync')state.connection.attempted=true;
      }finally{
        if(account===state.account&&epoch===modalEpoch){state.connection.pending='';updateConnection();}
      }
      return;
    }
    if(name==='enhance'){
      if(state.busy)return;
      const revision=draftRevision, enhancement=++enhancementVersion;
      state.busy=true;drawModal();
      try {
        const result=await api(path(account)+'/positioning/enhance',{method:'POST',body:JSON.stringify({businessPositioning:state.draft.businessPositioning,targetAudience:state.draft.targetAudience})});
        if(account!==state.account||epoch!==modalEpoch||revision!==draftRevision){if(account===state.account)toast('输入已变化，保留你的最新修改','info');return;}
        state.draft={...state.draft,...result};await saveDraft();toast('定位草稿已完善，请确认后保存');
      }finally{if(account===state.account&&enhancement===enhancementVersion){state.busy=false;if(modal.open)drawModal();}}return;
    }
    if(name==='saveProfile'){
      if(!state.draft.businessPositioning?.trim()||!state.draft.targetAudience?.trim())throw new Error('请填写商业定位和面向人群');
      await saveDraft();await api(path(account)+'/positioning',{method:'PUT',body:JSON.stringify({businessPositioning:state.draft.businessPositioning,targetAudience:state.draft.targetAudience})});
      if(account!==state.account||epoch!==modalEpoch)return;
      modalEpoch++;modal.close();await refresh();toast('定位已保存，账号准备完成');
    }
  }
  function click(e){const el=e.target.closest('[data-ob-action]');if(!el||el.disabled)return;el.disabled=true;Promise.resolve(action(el.dataset.obAction)).catch(e=>toast(e.message,'error')).finally(()=>{el.disabled=false;});}
  root.addEventListener('click',click);modal.addEventListener('click',click);
  modal.addEventListener('cancel',e=>{e.preventDefault();closeModal().catch(e=>toast('草稿保存失败：'+e.message,'error'));});
  modal.addEventListener('input',e=>{const key=e.target.dataset.obField;if(!key)return;resizePositioningFields();state.draft[key]=e.target.value;draftRevision++;clearTimeout(draftTimer);draftTimer=setTimeout(()=>saveDraft().catch(e=>toast('草稿保存失败：'+e.message,'error')),350);});
  function onAccountChange(account) {
    if(account===state.account)return;
    if(modal.open){saveDraft().catch(e=>toast(e.message,'error'));modal.close();}
    clearTimeout(draftTimer);clearTimeout(pollTimer);clearTimeout(refreshTimer);modalEpoch++;draftRevision++;
    Object.assign(state,{account:account||'',view:null,error:'',draft:{},login:null,connection:{},guided:false,busy:false});state.version++;render();return refresh();
  }
  window.addEventListener('workspace-module-change',e=>{state.module=e.detail.module;if(state.account)changed();});
  window.onboardingModule={onAccountChange,refresh:changed,prepare,async accountCreated(account){await onAccountChange(account.id);await persist({collapsed:false});window.selectWorkspaceModule?.('today');await prepare();}, state, helpers:{nextAction,connectionView}};
  if(typeof activeAccountId!=='undefined'&&activeAccountId)onAccountChange(activeAccountId);
})();
