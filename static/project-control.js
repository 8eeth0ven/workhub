/* One project-space overview; details appear only when a project is opened. */
(() => {
  'use strict';
  const I=window.WorkhubI18n,$=id=>document.getElementById(id),t=(key,values)=>I.t(key,values);


  const discoveryDrafts=new Map(),discoveryOpened=new Set();
  function discoveryNode(row) {
    const config=row.discovery||{},data=config.results,draft=discoveryDrafts.get(row.id);
    const box=el('details','','control-discovery');box.open=discoveryOpened.has(row.id);
    box.append(el('summary',t('发现相似项目')+(data?' · '+data.repositories.length:'')));
    box.addEventListener('toggle',()=>{if(box.open)discoveryOpened.add(row.id);else discoveryOpened.delete(row.id);});
    box.append(el('p',t('检索公开 GitHub 项目，结果作为参考线索。'),'workspace-muted'));
    const form=el('form'),field=el('label',t('检索关键词')),keywords=el('input');keywords.maxLength=200;keywords.placeholder='multi project agent workspace';keywords.value=draft?.keywords??config.keywords??'';field.append(keywords);
    const options=el('div','','control-discovery-options'),label=el('label'),enabled=el('input');enabled.type='checkbox';enabled.checked=draft?.enabled??config.enabled??false;label.append(enabled,document.createTextNode(t('定时检索')));
    const interval=el('select');interval.setAttribute('aria-label',t('定时检索'));for(const [hours,text] of [[6,'每 6 小时'],[24,'每天'],[168,'每周']]){const option=el('option',t(text));option.value=String(hours);interval.append(option);}interval.value=String(draft?.interval_hours??config.interval_hours??24);options.append(label,interval);
    const remember=()=>discoveryDrafts.set(row.id,{keywords:keywords.value,enabled:enabled.checked,interval_hours:Number(interval.value)});keywords.addEventListener('input',remember);enabled.addEventListener('change',remember);interval.addEventListener('change',remember);
    const save=button('保存检索设置',()=>form.requestSubmit());
    const run=button(config.running?'检索中…':'立即检索',async()=>{
      run.disabled=true;try{const answer=await post('discovery-run',{id:row.id,keywords:keywords.value.trim()});if(answer.retry_after)feedback(t('请在 {seconds} 秒后重试。',{seconds:answer.retry_after}));else{discoveryDrafts.delete(row.id);await load(true);}}catch(error){feedback(error.message,true);}finally{run.disabled=false;}
    });run.disabled=Boolean(config.running);
    form.append(field,options,save,run);form.addEventListener('submit',async event=>{event.preventDefault();save.disabled=true;try{await post('discovery-save',{id:row.id,keywords:keywords.value.trim(),enabled:enabled.checked,interval_hours:Number(interval.value)});discoveryDrafts.delete(row.id);feedback(t('已保存检索设置。'));await load(true);}catch(error){feedback(error.message,true);}finally{save.disabled=false;}});box.append(form);
    if(config.last_run_at)box.append(el('p',t('上次检索：{time}',{time:date(config.last_run_at)}),'workspace-muted'));
    if(config.enabled&&config.next_run_at)box.append(el('p',t('下次检索：{time}',{time:date(config.next_run_at)}),'workspace-muted'));
    if(config.last_error)box.append(el('p',I.translateKnown(config.last_error),'control-error'));
    if(data){
      if(data.keywords!==config.keywords)box.append(el('p',t('上次结果的关键词：{keywords}',{keywords:data.keywords}),'workspace-muted'));
      box.append(el('p',t('本次新增 {count} 条线索',{count:data.new_count||0}),'workspace-muted'));
      if(data.incomplete)box.append(el('p',t('结果未完整返回，可缩小关键词范围。'),'workspace-muted'));
      if(!data.repositories.length)box.append(el('p',t('本次未找到匹配项目。'),'workspace-muted'));
      const list=el('div','','control-related');for(const repo of data.repositories){const entry=el('article');entry.append(link(repo.full_name,repo.url),el('p',repo.description),el('small',[repo.language,repo.stars!=null?'★ '+repo.stars:''].filter(Boolean).join(' · ')));list.append(entry);}box.append(list,link(t('查询来源'),data.source_url));
    }
    return box;
  }
  let projects=[],expanded=null,loading=false,mode='control',busy=false,feedbackTimer;
  const drafts=new Map(),panel=$('control-panel'),dialog=$('control-github-dialog');
  const el=(tag,value='',cls='')=>{const node=document.createElement(tag);node.textContent=value;if(cls)node.className=cls;return node;};
  const date=value=>value?new Date(value).toLocaleString(I.getLocale()):'—';
  function link(label,url){
    const node=el('a',label);
    try{const parsed=new URL(url);if(parsed.protocol!=='https:'||!['github.com','api.github.com'].includes(parsed.hostname)||parsed.username||parsed.password)return el('span',label);node.href=parsed.href;}catch{return el('span',label);}
    node.target='_blank';node.rel='noopener noreferrer';return node;
  }
  function button(label,action,cls='button button-outline'){
    const node=el('button',t(label),cls);node.type='button';node.addEventListener('click',action);return node;
  }
  function feedback(value,error=false){clearTimeout(feedbackTimer);$('control-feedback').textContent=value;$('control-feedback').hidden=!value;$('control-feedback').classList.toggle('error',error);if(value&&!error)feedbackTimer=setTimeout(()=>{$('control-feedback').hidden=true;},5000);}
  async function post(action,payload){
    const response=await fetch('/api/control/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Workhub-Request':'1'},body:JSON.stringify(payload),signal:AbortSignal.timeout(30000)});
    const data=await response.json();if(!response.ok)throw new Error(I.translateKnown(data.error||'读取失败，请重试。'));return data;
  }
  function setMode(next,{focus=true}={}){
    mode=next==='website'?'website':'control';document.documentElement.dataset.workhubSpaceMode=mode;
    panel.hidden=mode!=='control';$('site-workspace').hidden=mode==='control';
    const foot=document.querySelector('#spaces-page > .portal-footnote');if(foot)foot.hidden=mode==='control';
    $('control-mode').setAttribute('aria-pressed',String(mode==='control'));
    $('website-mode').setAttribute('aria-pressed',String(mode==='website'));
    try{localStorage.setItem('workhub-space-mode',mode);}catch{}
    if(mode==='control'){window.WorkhubFocus?.exit({restoreScroll:false});load();}
    else if(focus&&!$('site-frame').hidden)window.WorkhubFocus?.enter({automatic:true});
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
  function rowNode(row){
    const details=el('details','','control-row');details.name='workhub-control-project';details.open=expanded===row.id;
    const summary=el('summary');const name=el('span','','control-project-name');name.append(el('strong',row.name),el('small',row.kind==='github'?'GitHub':t('本地项目')));
    const next=row.plan?.next_step||t(row.recommendations[0]?.title||'待安排下一步');
    summary.append(name,el('span',signal(row),'control-signal'),el('span',next,'control-next-preview'),el('time',date(row.snapshot?.observed_at),'control-time'));
    details.append(summary);details.addEventListener('toggle',()=>{if(details.open)expanded=row.id;else if(expanded===row.id)expanded=null;});
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
    const actions=el('div','','control-row-actions');const refresh=button(row.refreshing?'正在刷新…':'刷新快照',async()=>{refresh.disabled=true;try{await post('refresh',{id:row.id});await load(true);}catch(error){feedback(error.message,true);}finally{refresh.disabled=false;}});refresh.disabled=row.refreshing;actions.append(refresh);
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
    body.append(facts,form);details.append(body);return details;
  }
  function render(force=false){
    if(!force&&panel.contains(document.activeElement)&&document.activeElement.matches('input,textarea,select'))return;
    const query=$('control-search').value.trim().toLowerCase(),filter=$('control-filter').value;
    const rows=projects.filter(row=>(!query||[row.name,row.path,row.repository?.full_name].join(' ').toLowerCase().includes(query))&&(filter==='all'||filter==='attention'&&row.recommendations.some(x=>x.priority<2)||filter==='waiting'&&row.recommendations.some(x=>x.kind==='waiting')||filter==='unplanned'&&!row.plan?.next_step));
    $('control-grid').replaceChildren(...rows.map(rowNode));
    if(!rows.length)$('control-grid').append(el('p',t(projects.length?'没有匹配的项目。':'先添加已有项目或连接 GitHub 仓库。'),'control-empty'));
  }
  async function load(force=false){
    if(loading)return;loading=true;
    try{const response=await fetch('/api/control',{cache:'no-store',signal:AbortSignal.timeout(6000)});if(!response.ok)throw new Error();const data=await response.json();if(!Array.isArray(data.projects))throw new Error();projects=data.projects;render(force);}
    catch{feedback(t('读取失败，请重试。'),true);}finally{loading=false;}
  }
  $('control-mode').addEventListener('click',()=>setMode('control'));$('website-mode').addEventListener('click',()=>setMode('website'));
  $('control-search').addEventListener('input',()=>render(true));$('control-filter').addEventListener('change',()=>render(true));
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
    try{const payload={full_name:$('control-repository').value.trim()};if($('control-local-link').value)payload.local_project_id=$('control-local-link').value;const data=await post('connect',payload);dialog.close();feedback(t('已连接仓库，正在读取快照。'));await post('refresh',{id:data.id});expanded=data.id;await load(true);}
    catch(error){$('control-github-message').textContent=error.message;}finally{busy=false;$('control-connect-submit').disabled=false;}
  });
  window.addEventListener('workhub:state',()=>{if(!$('spaces-page').hidden&&mode==='control')load();});
  window.addEventListener('workhub:page',event=>{if(event.detail.page==='spaces'&&mode==='control'){window.WorkhubFocus?.exit({restoreScroll:false});load();}});
  window.addEventListener('workhub:site',event=>{if(event.detail.reason==='select'||event.detail.reason==='restore'&&mode==='website')setMode('website');});
  I.onChange(()=>{I.apply(panel);I.apply(dialog);I.apply(document.querySelector('.space-modebar'));render(true);});
  let saved;try{saved=localStorage.getItem('workhub-space-mode');if(!saved&&localStorage.getItem('workhub-current-site'))saved='website';}catch{}
  I.apply(panel);I.apply(dialog);I.apply(document.querySelector('.space-modebar'));setMode(saved||'control',{focus:false});
  setInterval(()=>{if(!document.hidden&&!$('spaces-page').hidden&&mode==='control'&&projects.some(row=>row.refreshing||row.discovery?.running))load();},1800);
})();
