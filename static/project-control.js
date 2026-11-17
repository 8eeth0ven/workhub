/* One project-space overview; details appear only when a project is opened. */
(() => {
  'use strict';
  const I=window.WorkhubI18n,$=id=>document.getElementById(id),t=(key,values)=>I.t(key,values);


  const discoveryDrafts=new Map(),discoveryOpened=new Set(),comparisonOpened=new Set();
  const localized=value=>typeof value==='string'?value:value?.[I.getLocale()==='en'?'en':'zh']||'';
  function comparisonNode(row,repo){
    const data=repo.comparison,key=row.id+':'+repo.github_id,box=el('details','','control-comparison');box.open=comparisonOpened.has(key);
    box.addEventListener('toggle',()=>{if(box.open)comparisonOpened.add(key);else comparisonOpened.delete(key);});
    const summary=el('summary');summary.append(el('strong',repo.full_name),el('small',data?.notes?.length?localized(data.notes[0].title):t('待核对具体功能')));box.append(summary,link(t('打开来源项目'),repo.url));
    box.append(el('p',repo.description,'workspace-muted'));
    if(!data){box.append(el('p',t('旧结果尚无比较，重新检索后生成。'),'workspace-muted'));return box;}
    box.append(el('p',t(data.method==='agent_document_review_v1'?'本次由 Codex 补充复核公开文档，未运行外部项目。':data.coverage==='readme'?'依据公开 README 的规则归纳，未经运行验证。':'仅依据公开描述，未深入读取 README。'),'workspace-muted'));
    if(data.observed_at)box.append(el('small',t('资料读取：{time}',{time:date(data.observed_at)})));
    if(data.license)box.append(el('small',t('许可证：{license}',{license:data.license})));
    if(!data.notes.length)box.append(el('p',t('现有材料不足以提出具体借鉴点，先查看来源；不据此生成优化结论。'),'workspace-muted'));
    const more=el('details','','control-comparison-more');more.append(el('summary',t('更多借鉴点')));
    for(const [index,note] of (data.notes||[]).entries()){
      const entry=el('section','','control-comparison-note');entry.append(el('strong',localized(note.title)));
      const list=el('dl');for(const [label,value] of [['值得借鉴',note.benefit],['与本项目的差别',note.difference],['下一步验证',note.next_step]]){list.append(el('dt',t(label)),el('dd',localized(value)));}entry.append(list);
      const sources=el('details','','control-comparison-sources');sources.append(el('summary',t('来源依据')));
      for(const [label,evidence] of [['参考项目依据',note.evidence],['本项目依据',note.baseline_evidence]]){if(!evidence)continue;const quote=el('blockquote',evidence.text);const url=evidence.url+(evidence.kind==='readme'?'?plain=1#L'+evidence.line:'');sources.append(el('small',t(label)),quote,link(t('查看证据'),url));if(evidence.sha)sources.append(el('small','README SHA · '+evidence.sha.slice(0,12)));}entry.append(sources);
      entry.append(button('填入下一步',()=>{const current=drafts.get(row.id);drafts.set(row.id,{text:localized(note.next_step),priority:current?.priority??row.plan?.priority??2});render(true);feedback(t('已填入草稿，保存后生效。'));}));(index===0?box:more).append(entry);
    }
    if(data.notes.length>1)box.append(more);
    return box;
  }
  function discoveryNode(row) {
    const config=row.discovery||{},data=config.results,draft=discoveryDrafts.get(row.id);
    const box=el('details','','control-discovery');box.open=discoveryOpened.has(row.id);
    box.append(el('summary',t('发现相似项目')+(data?' · '+data.repositories.length:'')));
    box.addEventListener('toggle',()=>{if(box.open)discoveryOpened.add(row.id);else discoveryOpened.delete(row.id);});
    box.append(el('p',t('检索公开项目，展开查看借鉴点、差别与下一步。'),'workspace-muted'));
    const form=el('form'),field=el('label',t('检索关键词')),keywords=el('input');keywords.maxLength=200;keywords.placeholder='multi project agent workspace';keywords.value=draft?.keywords??config.keywords??'';field.append(keywords);
    const focusField=el('label',t('本项目定位（可选，仅用于本机比较）')),focus=el('textarea');focus.maxLength=1000;focus.rows=2;focus.value=draft?.project_focus??config.project_focus??'';focusField.append(focus);
    const options=el('div','','control-discovery-options'),label=el('label'),enabled=el('input');enabled.type='checkbox';enabled.checked=draft?.enabled??config.enabled??false;label.append(enabled,document.createTextNode(t('定时检索')));
    const interval=el('select');interval.setAttribute('aria-label',t('定时检索'));for(const [hours,text] of [[6,'每 6 小时'],[24,'每天'],[168,'每周']]){const option=el('option',t(text));option.value=String(hours);interval.append(option);}interval.value=String(draft?.interval_hours??config.interval_hours??24);options.append(label,interval);
    const remember=()=>discoveryDrafts.set(row.id,{keywords:keywords.value,project_focus:focus.value,enabled:enabled.checked,interval_hours:Number(interval.value)});keywords.addEventListener('input',remember);focus.addEventListener('input',remember);enabled.addEventListener('change',remember);interval.addEventListener('change',remember);
    const save=button('保存检索设置',()=>form.requestSubmit());
    const run=button(config.running?'检索中…':'立即检索',async()=>{
      run.disabled=true;try{const answer=await post('discovery-run',{id:row.id,keywords:keywords.value.trim(),project_focus:focus.value.trim()});if(answer.retry_after)feedback(t('请在 {seconds} 秒后重试。',{seconds:answer.retry_after}));else{discoveryDrafts.delete(row.id);await load(true);}}catch(error){feedback(error.message,true);}finally{run.disabled=false;}
    });run.disabled=Boolean(config.running)||isDemo();
    form.append(field,focusField,options,save,run);form.addEventListener('submit',async event=>{event.preventDefault();save.disabled=true;try{await post('discovery-save',{id:row.id,keywords:keywords.value.trim(),project_focus:focus.value.trim(),enabled:enabled.checked,interval_hours:Number(interval.value)});discoveryDrafts.delete(row.id);feedback(t('已保存检索设置。'));await load(true);}catch(error){feedback(error.message,true);}finally{save.disabled=false;}});
    if(data){const settings=el('details','','control-discovery-settings');settings.append(el('summary',t('检索设置')+' · '+config.keywords),form);box.append(settings);}else box.append(form);
    if(config.last_run_at)box.append(el('p',t('上次检索：{time}',{time:date(config.last_run_at)}),'workspace-muted'));
    if(config.enabled&&config.next_run_at)box.append(el('p',t('下次检索：{time}',{time:date(config.next_run_at)}),'workspace-muted'));
    if(config.last_error)box.append(el('p',I.translateKnown(config.last_error),'control-error'));
    if(data){
      if(config.stale)box.append(el('p',t('结果对应旧设置或上次读取失败，重新检索可更新。'),'control-error'));
      const review=data.document_review,validReview=review&&review.keywords===data.keywords&&review.source_observed_at===data.observed_at;
      const reviewed=validReview?(review.repositories||[]).filter(item=>item.comparison?.method==='agent_document_review_v1'&&data.repositories.some(original=>original.github_id===item.github_id)):[];
      box.append(el('p',t(reviewed.length?'自动检索结果保留；以下优先展示本次文档复核，未经运行验证。':'最多深入读取前 3 个项目的 README，其余仅参考描述；材料未提及不代表没有实现。'),'workspace-muted'));
      if(reviewed.length)box.append(el('small',t('本次文档复核 · {count} 项 · {time}',{count:reviewed.length,time:date(review.reviewed_at)})));
      if(data.baseline?.readme_sha)box.append(el('small',t('本项目公开 README：{sha}',{sha:data.baseline.readme_sha.slice(0,12)})));
      else box.append(el('p',t('本项目公开 README 不可用，比较将保留未知；可补充项目定位。'),'workspace-muted'));
      if(data.keywords!==config.keywords)box.append(el('p',t('上次结果的关键词：{keywords}',{keywords:data.keywords}),'workspace-muted'));
      box.append(el('p',t('本次新增 {count} 条线索',{count:data.new_count||0}),'workspace-muted'));
      if(data.incomplete)box.append(el('p',t('结果未完整返回，可缩小关键词范围。'),'workspace-muted'));
      if(!data.repositories.length)box.append(el('p',t('本次未找到匹配项目。'),'workspace-muted'));
      const list=el('div','','control-related'),selected=new Set(reviewed.map(item=>item.github_id));
      const append=(target,repositories)=>{for(const repo of repositories){const entry=el('article');entry.append(comparisonNode(row,repo));target.append(entry);}};
      append(list,reviewed.length?reviewed:data.repositories);box.append(list);
      if(reviewed.length){const rest=data.repositories.filter(item=>!selected.has(item.github_id));if(rest.length){const other=el('details','','control-related-other'),otherList=el('div','','control-related');other.append(el('summary',t('其他原始命中（{count}）',{count:rest.length})),el('p',t('保留原始命中，关键词共现不代表功能相似。'),'workspace-muted'));append(otherList,rest);other.append(otherList);box.append(other);}}
      box.append(link(t('查询来源'),data.source_url));
    }
    return box;
  }
  let projects=[],expanded=null,loading=false,mode='control',busy=false,feedbackTimer,editing=false,batchPending=false,loadVersion=0,listScroll=0;
  const selected=new Set();let removeDraft=[];const projectKey=row=>row.kind+':'+row.id;const isDemo=()=>document.body.dataset.demo==='true';
  const drafts=new Map(),panel=$('control-panel'),dialog=$('control-github-dialog');
  const el=(tag,value='',cls='')=>{const node=document.createElement(tag);node.textContent=value;if(cls)node.className=cls;return node;};
  const date=value=>value?new Date(value).toLocaleString(I.getLocale()):'—';
  function link(label,url){
    const node=el('a',label);
    try{const parsed=new URL(url);if(parsed.protocol!=='https:'||!['github.com','api.github.com'].includes(parsed.hostname)||parsed.username||parsed.password)return el('span',label);node.href=parsed.href;}catch{return el('span',label);}
    node.target='_blank';node.rel='noopener noreferrer';return node;
  }
  function button(label,action,cls='button button-outline'){
    const node=el('button',t(label),cls);node.type='button';if(isDemo()&&!['工作记录','项目评议','项目网页','复制继续任务','填入下一步'].includes(label))node.disabled=true;node.addEventListener('click',action);return node;
  }
  function feedback(value,error=false){clearTimeout(feedbackTimer);$('control-feedback').textContent=value;$('control-feedback').hidden=!value;$('control-feedback').classList.toggle('error',error);if(value&&!error)feedbackTimer=setTimeout(()=>{$('control-feedback').hidden=true;},5000);}
  async function post(action,payload){
    if(isDemo())throw new Error(t('演示模式只读，无法修改项目。'));
    const response=await fetch('/api/control/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Workhub-Request':'1'},body:JSON.stringify(payload),signal:AbortSignal.timeout(30000)});
    const data=await response.json();if(!response.ok)throw new Error(I.translateKnown(data.error||'读取失败，请重试。'));return data;
  }
  function setMode(next,{focus=true}={}){
    mode=next==='website'?'website':'control';document.documentElement.dataset.workhubSpaceMode=mode;
    panel.hidden=mode!=='control';$('site-workspace').hidden=mode!=='website';
    const foot=document.querySelector('#spaces-page > .portal-footnote');if(foot)foot.hidden=mode!=='website';
    $('control-mode').setAttribute('aria-pressed',String(mode==='control'));
    $('website-mode').setAttribute('aria-pressed',String(mode==='website'));
    if(focus||mode!=='website')window.WorkhubFocus?.exit({restoreScroll:false});
    if(focus&&mode==='website')window.WorkhubPanels?.showSites();
    if(mode==='control')load();
    window.dispatchEvent(new CustomEvent('workhub:space-mode',{detail:{mode}}));
  }
  function signal(row){
    if(row.refreshing)return t('正在刷新…');
    if(!row.snapshot)return t('待刷新');
    if(row.snapshot.local?.stale||row.snapshot.github?.stale||row.snapshot.errors?.length)return t('旧快照');
    if(row.recommendations.some(r=>r.priority<2))return t('需要关注');
    if(row.recommendations.some(r=>r.kind==='waiting'))return t('等待检查');
    if(row.plan?.next_step)return t('已有下一步');
    return row.discovery?.results?.new_count>0&&!row.discovery.stale?t('有新参考'):t('待安排下一步');
  }
  function detailNode(row){
    const details=el('article','','control-detail-project');
    const body=el('div','','control-row-body'),facts=el('div','','control-facts');
    const snapshot=row.snapshot,local=snapshot?.local,github=snapshot?.github;
    if(!snapshot)facts.append(el('p',t('尚未读取快照'),'workspace-muted'));
    if(row.path)facts.append(el('p',row.path,'control-path'));
    if(local){facts.append(el('p',t('本地分支：{branch} · {sha}',{branch:local.branch,sha:(local.head_sha||'—').slice(0,10)})),el('p',t('未提交改动：{count} 项',{count:local.changed_count})));}
    if(github){
      facts.append(el('p',t('GitHub 默认分支：{branch} · {sha}',{branch:github.repository.default_branch,sha:(github.head_sha||'—').slice(0,10)})));
      const failed=new Set((github.errors||[]).map(x=>x.source));
      facts.append(el('p',failed.has('pull_requests')&&!github.stale_fields?.includes('pull_requests')?t('PR 暂不可读'):t('最近开放 PR：{count} 条（样本）',{count:github.pull_requests.length})),el('p',failed.has('issues')&&!github.stale_fields?.includes('issues')?t('Issue 暂不可读'):t('最近开放 Issue：{count} 条（样本）',{count:github.issues.length})));
      if(github.head_sha&&!failed.has('actions')&&!github.actions.length)facts.append(el('p',t('暂无当前 SHA 的 Actions 记录'),'workspace-muted'));
      if(github.errors?.length)facts.append(el('p',t('快照未完整读取，保留上次可用数据。'),'control-error'));
    }
    for(const error of snapshot?.errors||[])facts.append(el('p',I.translateKnown(error),'control-error'));
    const actions=el('div','','control-row-actions');const refresh=button(row.refreshing?'正在刷新…':'刷新快照',async()=>{refresh.disabled=true;try{await post('refresh',{id:row.id});await load(true);}catch(error){feedback(error.message,true);}finally{refresh.disabled=false;}});refresh.disabled=row.refreshing||isDemo();actions.append(refresh);
    if(row.repository){actions.append(link(t('打开 GitHub'),row.repository.url));actions.append(button('取消仓库连接',async()=>{try{await post('disconnect',{id:row.id});feedback(t('已取消连接，源仓库与本地文件保留。'));await load(true);}catch(error){feedback(error.message,true);}}));}
    if(row.kind==='local'){actions.append(button('工作记录',()=>window.WorkhubDashboard.openProject(row.id)));actions.append(button('项目评议',()=>window.WorkhubReviews?.openProject(row.id)));actions.append(button('项目网页',()=>{if(!window.WorkhubDashboard.openProjectSite(row.id))setMode('website',{focus:false});}));}
    facts.append(actions);
    const suggested=el('details','','control-evidence');suggested.append(el('summary',t('基于证据的建议')));
    if(!row.recommendations.length)suggested.append(el('p',t('目前没有可据此提出的具体建议。'),'workspace-muted'));
    for(const item of row.recommendations){const entry=el('div','','control-suggestion');entry.append(el('strong',t(item.title)),el('p',t(item.reason)));if(item.url)entry.append(link(t('查看证据'),item.url));suggested.append(entry);}
    facts.append(suggested,discoveryNode(row));
    const form=el('form','','control-plan'),label=el('label',t('下一步'));const input=el('textarea');input.maxLength=2000;input.rows=3;
    const draft=drafts.get(row.id);input.value=draft?.text??row.plan?.next_step??'';label.append(input);
    const priorityLabel=el('label',t('优先级')),priority=el('select');for(let i=0;i<4;i++){const option=el('option','P'+i);option.value=String(i);priority.append(option);}priority.value=String(draft?.priority??row.plan?.priority??2);priorityLabel.append(priority);
    const remember=()=>drafts.set(row.id,{text:input.value,priority:Number(priority.value)});input.addEventListener('input',remember);priority.addEventListener('change',remember);
    const save=button('保存下一步',()=>form.requestSubmit(),'button button-dark');
    const copy=button('复制继续任务',async()=>{
      const text=[row.name,row.repository?.url||row.path,local?.head_sha?'Local HEAD: '+local.head_sha:'',github?.head_sha?'GitHub default HEAD: '+github.head_sha:'',snapshot?.observed_at?'Snapshot observed: '+snapshot.observed_at:'',t('下一步')+': '+(input.value.trim()||t(row.recommendations[0]?.title||'待安排下一步'))].filter(Boolean).join('\n');
      try{await navigator.clipboard.writeText(text);feedback(t('已复制项目事实与下一步。'));}catch{feedback(t('无法复制，请手动选择下一步文本。'),true);}
    });
    form.append(label,priorityLabel,save,copy);form.addEventListener('submit',async event=>{event.preventDefault();save.disabled=true;try{await post('plan',{id:row.id,next_step:input.value,priority:Number(priority.value)});drafts.delete(row.id);feedback(t('已保存下一步。'));await load(true);}catch(error){feedback(error.message,true);}finally{save.disabled=false;}});
    body.append(facts,form);details.append(body);if(isDemo())details.querySelectorAll('input,textarea,select').forEach(n=>n.disabled=true);return details;
  }
  function visibleProjects(){
    const query=$('control-search').value.trim().normalize('NFKC').toLowerCase(),filter=$('control-filter').value;
    return projects.filter(row=>(!query||[row.name,row.path,row.repository?.full_name].join(' ').normalize('NFKC').toLowerCase().includes(query))&&(filter==='all'||filter==='attention'&&row.recommendations.some(x=>x.priority<2)||filter==='waiting'&&row.recommendations.some(x=>x.kind==='waiting')||filter==='unplanned'&&!row.plan?.next_step));
  }
  function cardContent(row){
    const box=el('span','','control-card-content'),head=el('span','','control-card-heading');head.append(el('strong',row.name),el('small',row.kind==='github'?'GitHub':t('本地项目')));
    const planned=typeof row.plan?.next_step==='string'&&row.plan.next_step.trim()?row.plan.next_step:'',work=typeof row.latest_work?.summary==='string'&&row.latest_work.summary.trim()?row.latest_work.summary:'',status=el('span',signal(row),'control-signal');status.title=t('快照状态：{state}',{state:signal(row)});status.setAttribute('aria-label',status.title);
    box.append(head,status,el('span',planned||work||t(row.recommendations[0]?.title||'待安排下一步'),'control-next-preview'));
    const observed=row.snapshot?.observed_at,workTime=row.latest_work?.updated_at,stamp=observed||workTime;if(stamp&&!Number.isNaN(new Date(stamp).getTime())){const time=el('time',`${t(observed?'快照读取':'项目记录更新')} · ${date(stamp)}`,'control-time');time.dateTime=stamp;time.title=observed?t('快照读取时间：{time}',{time:date(stamp)}):t('项目记录更新时间：{time}；不代表工作发生或 Git 快照读取时间。',{time:date(stamp)});time.setAttribute('aria-label',time.title);box.append(time);}return box;
  }
  let lastOpened='';
  function openDetail(row){if(editing||batchPending)return;lastOpened=projectKey(row);listScroll=panel.scrollTop;expanded=lastOpened;render(true);panel.scrollTop=0;$('control-back').focus({preventScroll:true});}
  function returnToList(){expanded=null;render(true);panel.scrollTop=listScroll;Array.from($('control-grid').querySelectorAll('[data-project-key]')).find(n=>n.dataset.projectKey===lastOpened)?.focus({preventScroll:true});}
  function cardNode(row){
    const card=el('article','','control-card'),key=projectKey(row);
    if(editing){const label=el('label','','control-card-select'),check=el('input');check.type='checkbox';check.checked=selected.has(key);check.disabled=batchPending||isDemo();check.setAttribute('aria-label',t('选择项目 {name}',{name:row.name}));check.dataset.projectKey=key;
      check.addEventListener('change',()=>{if(batchPending||isDemo())return;if(check.checked){if(selected.size>=100){check.checked=false;feedback(t('每次最多选择 100 个项目。'),true);return;}selected.add(key);}else selected.delete(key);card.classList.toggle('selected',check.checked);renderSelection();});label.append(check,cardContent(row));card.append(label);card.classList.toggle('selected',selected.has(key));
    }else{const open=el('button','','control-card-open');open.type='button';open.dataset.projectKey=key;open.setAttribute('aria-label',t('查看项目 {name} 的详情',{name:row.name}));open.append(cardContent(row));open.addEventListener('click',()=>openDetail(row));card.append(open);}return card;
  }
  function pruneSelection(rows=visibleProjects()){const allowed=new Set(rows.map(projectKey));let removed=0;for(const key of selected)if(!allowed.has(key)){selected.delete(key);removed++;}return removed;}
  function renderSelection(){
    const rows=visibleProjects(),count=selected.size;$('control-edit').textContent=t(editing?'完成编辑':'编辑项目');$('control-edit').setAttribute('aria-pressed',String(editing));$('control-edit').disabled=isDemo()||batchPending;
    $('control-bulk-toolbar').hidden=!editing;$('control-selected-count').textContent=t('已选择 {count} 个项目',{count});$('control-select-visible').disabled=batchPending||!rows.length||rows.length>100;$('control-select-clear').disabled=batchPending||!count;$('control-remove-selected').disabled=batchPending||!count;$('control-remove-selected').textContent=t(batchPending?'正在移除…':'从中控移除所选');
    $('control-selection-note').textContent=t(rows.length>100?'每次最多选择 100 个项目，请缩小筛选范围。':'筛选变化会取消不可见项目的选择。只从中控移除，保留文件、记录与远端仓库。');
    for(const id of ['control-search','control-filter','control-add-github'])$(id).disabled=batchPending||(id==='control-add-github'&&isDemo());
    $('control-grid').querySelectorAll('input').forEach(n=>n.disabled=batchPending||isDemo());document.querySelectorAll('[data-workspace-add]').forEach(n=>n.disabled=batchPending||isDemo());
    $('control-remove-confirm').disabled=batchPending;$('control-remove-cancel').disabled=batchPending;
  }
  function render(force=false){
    if(!force&&panel.contains(document.activeElement)&&document.activeElement.matches('input,textarea,select'))return;
    if(expanded&&!projects.some(row=>projectKey(row)===expanded))expanded=null;
    $('control-list-view').hidden=Boolean(expanded);$('control-detail-view').hidden=!expanded;
    if(expanded){const row=projects.find(row=>projectKey(row)===expanded);$('control-detail-name').textContent=row.name;$('control-detail').replaceChildren(detailNode(row));}
    else{const rows=visibleProjects();pruneSelection(rows);$('control-grid').replaceChildren(...rows.map(cardNode));if(!rows.length)$('control-grid').append(el('p',t(projects.length?'没有匹配的项目。':'先添加已有项目或连接 GitHub 仓库。'),'control-empty'));}
    renderSelection();
  }
  async function load(force=false){
    if(batchPending)return;const version=++loadVersion;loading=true;
    try{const response=await fetch('/api/control',{cache:'no-store',signal:AbortSignal.timeout(6000)});if(!response.ok)throw new Error();const data=await response.json();if(!Array.isArray(data.projects))throw new Error();if(version!==loadVersion)return;projects=data.projects;if(expanded&&!projects.some(row=>projectKey(row)===expanded)){expanded=null;force=true;}render(force);return true;}
    catch{if(version===loadVersion)feedback(t('读取失败，请重试。'),true);return false;}finally{if(version===loadVersion)loading=false;}
  }
  function cancelRemoval(){if(batchPending)return;removeDraft=[];$('control-remove-dialog').close();$('control-remove-selected').focus({preventScroll:true});}
  function prepareRemoval(){
    if(batchPending||isDemo())return;pruneSelection();removeDraft=visibleProjects().filter(row=>selected.has(projectKey(row))).map(row=>({id:row.id,kind:row.kind}));if(!removeDraft.length||removeDraft.length>100)return;
    $('control-remove-summary').textContent=t('确认从中控移除这 {count} 个项目？',{count:removeDraft.length});$('control-remove-names').replaceChildren(...removeDraft.slice(0,10).map(item=>el('li',projects.find(row=>projectKey(row)===projectKey(item))?.name||item.id)));if(removeDraft.length>10)$('control-remove-names').append(el('li',t('另有 {count} 个所选项目',{count:removeDraft.length-10})));$('control-remove-error').hidden=true;I.apply($('control-remove-dialog'));$('control-remove-dialog').showModal();$('control-remove-cancel').focus();
  }
  async function removeSelection(){
    if(batchPending||isDemo()||!removeDraft.length)return;batchPending=true;++loadVersion;renderSelection();$('control-remove-error').hidden=true;const items=removeDraft.map(item=>({...item}));let succeeded=false;
    try{const data=await post('remove-batch',{items});const expected=items.map(projectKey).sort(),actual=Array.isArray(data.items)?data.items.map(projectKey).sort():[];if(data.ok!==true||JSON.stringify(expected)!==JSON.stringify(actual))throw new Error(t('移除结果未能核对，保留当前选择并刷新后再确认。'));
      const removed=new Set(expected);projects=projects.filter(row=>!removed.has(projectKey(row)));for(const key of removed)selected.delete(key);for(const item of items){drafts.delete(item.id);discoveryDrafts.delete(item.id);}if(removed.has(expanded))expanded=null;removeDraft=[];succeeded=true;$('control-remove-dialog').close();
    }catch(error){$('control-remove-error').textContent=error.message||t('项目操作未成功。');$('control-remove-error').hidden=false;feedback(t('移除结果未确认，当前选择已保留。'),true);}
    finally{batchPending=false;render(true);}
    if(succeeded){try{await window.WorkhubDashboard.refresh();}catch{}const refreshed=await load(true);feedback(t(refreshed?'已从中控移除 {count} 个项目，文件、工作记录与远端仓库保留。':'已从中控移除 {count} 个项目；列表刷新暂未完成，请稍后刷新。',{count:items.length}),!refreshed);$('control-edit').focus({preventScroll:true});}
  }
  $('control-back').addEventListener('click',returnToList);
  $('control-edit').addEventListener('click',()=>{if(batchPending||isDemo())return;editing=!editing;selected.clear();render(true);$('control-edit').focus({preventScroll:true});});
  $('control-select-visible').addEventListener('click',()=>{if(batchPending||isDemo())return;const rows=visibleProjects();if(rows.length>100)return;rows.forEach(row=>selected.add(projectKey(row)));render(true);$('control-select-visible').focus({preventScroll:true});});
  $('control-select-clear').addEventListener('click',()=>{if(batchPending)return;selected.clear();render(true);$('control-edit').focus({preventScroll:true});});
  $('control-remove-selected').addEventListener('click',prepareRemoval);$('control-remove-cancel').addEventListener('click',cancelRemoval);$('control-remove-confirm').addEventListener('click',removeSelection);$('control-remove-dialog').addEventListener('cancel',event=>{event.preventDefault();cancelRemoval();});
  $('control-mode').addEventListener('click',()=>setMode('control'));$('website-mode').addEventListener('click',()=>setMode('website'));
  const filterChanged=()=>{if(batchPending)return;const count=pruneSelection();render(true);if(count)feedback(t('已取消 {count} 个不可见项目的选择。',{count}));};$('control-search').addEventListener('input',filterChanged);$('control-filter').addEventListener('change',filterChanged);
  $('control-add-github').addEventListener('click',()=>{
    const select=$('control-local-link'),chosen=select.value;select.replaceChildren(el('option',t('作为独立 GitHub 项目')));select.firstChild.value='';
    for(const project of window.WorkhubDashboard.projects()){const option=el('option',project.name);option.value=project.id;select.append(option);}select.value=chosen;
    $('control-github-message').textContent='';try{if(!$('control-owner').value)$('control-owner').value=localStorage.getItem('workhub-github-owner')||'';}catch{}dialog.showModal();
  });
  $('control-close-github').addEventListener('click',()=>dialog.close());
  $('control-load-repositories').addEventListener('click',async()=>{
    if(busy)return;busy=true;$('control-load-repositories').disabled=true;$('control-github-message').textContent='';
    try{const data=await post('catalog',{owner:$('control-owner').value.trim()});try{localStorage.setItem('workhub-github-owner',$('control-owner').value.trim());}catch{}const select=$('control-repositories');select.replaceChildren(el('option',t('先读取仓库，或直接填写下方地址')));select.firstChild.value='';
      for(const repo of data.repositories){const option=el('option',repo.full_name);option.value=repo.full_name;select.append(option);}
      $('control-catalog-note').textContent=data.has_more?t('仅显示最近 100 个公开仓库；也可直接填写仓库名称。'):t('已读取 {count} 个公开仓库；选中后仍需加入中控。',{count:data.repositories.length});
    }catch(error){$('control-github-message').textContent=error.message;}finally{busy=false;$('control-load-repositories').disabled=false;}
  });
  $('control-repositories').addEventListener('change',()=>{if($('control-repositories').value)$('control-repository').value=$('control-repositories').value;});
  $('control-github-form').addEventListener('submit',async event=>{
    event.preventDefault();if(busy||!event.target.reportValidity())return;busy=true;$('control-connect-submit').disabled=true;
    try{const payload={full_name:$('control-repository').value.trim()};if($('control-local-link').value)payload.local_project_id=$('control-local-link').value;const data=await post('connect',payload);dialog.close();feedback(t('已连接仓库，正在读取快照。'));await post('refresh',{id:data.id});expanded=null;await load(true);const row=projects.find(row=>row.id===data.id);if(row)openDetail(row);}
    catch(error){$('control-github-message').textContent=error.message;}finally{busy=false;$('control-connect-submit').disabled=false;}
  });
  window.addEventListener('workhub:state',event=>{if(event.detail?.is_demo){document.body.dataset.demo='true';editing=false;selected.clear();removeDraft=[];}renderSelection();if(!$('spaces-page').hidden&&mode==='control')load();});
  window.addEventListener('workhub:page',event=>{if(event.detail.page==='spaces'){if(mode==='control'){window.WorkhubFocus?.exit({restoreScroll:false});load();}else if(mode==='website')window.WorkhubPanels?.showSites();}});
  window.addEventListener('workhub:site',event=>{if(event.detail.reason==='clear'&&mode==='website'){expanded=null;editing=false;selected.clear();setMode('website',{focus:false});}else if(['select','preview','fullscreen'].includes(event.detail.reason)||event.detail.reason==='restore'&&mode==='website')setMode('website',{focus:false});});
  window.addEventListener('workhub:workspace-removed',event=>{const ids=new Set(event.detail?.ids||[]);for(const id of ids)selected.delete('local:'+id);if(expanded&&ids.has(expanded.slice(6))&&expanded.startsWith('local:'))expanded=null;load(true);});
  I.onChange(()=>{I.apply(panel);I.apply(dialog);I.apply($('control-remove-dialog'));I.apply(document.querySelector('.space-modebar'));render(true);});
  I.apply(panel);I.apply(dialog);I.apply(document.querySelector('.space-modebar'));setMode('website',{focus:false});
  setInterval(()=>{if(!document.hidden&&!$('spaces-page').hidden&&mode==='control'&&projects.some(row=>row.refreshing||row.discovery?.running))load();},1800);
})();
