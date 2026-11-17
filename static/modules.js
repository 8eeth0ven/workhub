/* Installation starts only on an explicit click; navigation never installs or opens a site. */
(() => {
  'use strict';
  const panel=document.getElementById('modules-panel'),I=window.WorkhubI18n;
  if(!panel||!I)return;
  const WORDS={
    'zh-CN':{search:'查找模块',placeholder:'查找模块或用途…',refresh:'刷新模块',loading:'正在读取模块…',count:'{shown} / {total} 个模块 · {connected} 个已接入',registered:'已接入',unregistered:'未接入',version:'可安装版本 {version}',versionUnknown:'版本未提供',preview:'预览',fullscreen:'全屏打开',download:'下载模块',docs:'使用文档',empty:'暂无可显示的模块。',noMatches:'没有符合检索条件的模块。',loadError:'模块暂时无法读取，请点击“刷新模块”重试。',cachedError:'刷新未完成，保留上次读取的模块。请稍后重试。',openError:'这个入口暂时无法打开，请刷新模块后重试。',linksUnavailable:'下载与文档链接暂不可用。',registeredHint:'已登记网站入口；服务是否可用请打开确认。',unregisteredHint:'尚无关联网站入口，不代表模块未安装。',previewLabel:'预览 {name}',fullscreenLabel:'全屏打开 {name}',downloadLabel:'下载 {name}',docsLabel:'阅读 {name} 的使用文档'},
    en:{search:'Find modules',placeholder:'Find a module or purpose…',refresh:'Refresh modules',loading:'Loading modules…',count:'{shown} / {total} modules · {connected} connected',registered:'Connected',unregistered:'Not connected',version:'Available version {version}',versionUnknown:'Version not provided',preview:'Preview',fullscreen:'Open fullscreen',download:'Download',docs:'Documentation',empty:'No modules are available.',noMatches:'No modules match this search.',loadError:'Modules could not be loaded. Choose Refresh modules to retry.',cachedError:'Refresh did not complete. The previous catalog is retained; try again shortly.',openError:'This entry could not be opened. Refresh the catalog and try again.',linksUnavailable:'Download and documentation links are unavailable.',registeredHint:'A website entry is registered; open it to check availability.',unregisteredHint:'No website entry is linked; this does not establish that the module is uninstalled.',previewLabel:'Preview {name}',fullscreenLabel:'Open {name} fullscreen',downloadLabel:'Download {name}',docsLabel:'Read documentation for {name}'}
  };
  Object.assign(WORDS['zh-CN'],{install:'安装并接入',retryInstall:'重试安装',enableService:'启用服务',readonly:'只读模式',submitting:'正在提交安装…',installing:'正在安装…',syncing:'安装完成，正在更新入口…',refreshEntry:'刷新入口',checkStatus:'检查状态',unconfirmed:'安装结果未确认，正在核对状态。',statusUnavailable:'状态暂时无法更新，安装结果尚未确认。',entryError:'安装已完成，入口刷新未完成，请重试。',notStarted:'当前没有安装任务，可重新点击安装。',failedGeneric:'安装未完成，请重试。',failureReason:'失败原因：{reason}',installLabel:'{action}：{name}',progressLabel:'{name} 安装进度','phase.queued':'等待安装','phase.downloading':'正在下载','phase.verifying':'正在校验','phase.installing':'正在安装','phase.building':'正在生成网页','phase.connecting':'正在接入 Workhub','phase.completed':'安装完成','phase.failed':'安装失败','phase.idle':'未开始安装'});
  Object.assign(WORDS.en,{install:'Install & connect',retryInstall:'Retry installation',enableService:'Enable service',readonly:'Read-only mode',submitting:'Submitting installation…',installing:'Installing…',syncing:'Installed; refreshing entry…',refreshEntry:'Refresh entry',checkStatus:'Check status',unconfirmed:'The installation result is unconfirmed. Checking status.',statusUnavailable:'Status could not be updated; the installation result remains unconfirmed.',entryError:'Installation completed, but the entry could not refresh. Try again.',notStarted:'There is no installation task. You can start again.',failedGeneric:'Installation did not complete. Try again.',failureReason:'Reason: {reason}',installLabel:'{action}: {name}',progressLabel:'Installation progress for {name}','phase.queued':'Queued','phase.downloading':'Downloading','phase.verifying':'Verifying','phase.installing':'Installing','phase.building':'Building website','phase.connecting':'Connecting to Workhub','phase.completed':'Installation completed','phase.failed':'Installation failed','phase.idle':'Not started'});
  let modules=[],query='',attempted=false,loaded=false,loading=false,opening=false,errorKey='';
  const locale=()=>I.getLocale()==='en'?'en':'zh-CN';
  const t=(key,values={})=>(Object.hasOwn(WORDS[locale()],key)?WORDS[locale()][key]:key).replace(/\{(\w+)\}/g,(match,name)=>Object.hasOwn(values,name)?String(values[name]):match);
  const element=(tag,cls='',value)=>{const node=document.createElement(tag);if(cls)node.className=cls;if(value!==undefined)node.textContent=String(value);return node;};
  const local=value=>value[locale()]||value[locale()==='en'?'zh-CN':'en'];
  function safeURL(value){
    if(typeof value!=='string'||value.length>2048||/[\\\u0000-\u0020\u007f]/.test(value))return '';
    try{const url=new URL(value);if(url.origin!=='https://github.com'||url.username||url.password||url.search)return '';
      const parts=url.pathname.split('/').filter(Boolean).map(part=>decodeURIComponent(part));
      if(parts.length<2||parts[0]!=='8eeth0ven'||parts[1]!=='workhub-model'||parts.some(part=>/[\\/%\u0000-\u0020\u007f]/.test(part)||part==='.'||part==='..'))return '';
      return url.href;
    }catch{return '';}
  }
  function parseCatalog(data){
    if(!data||!Array.isArray(data.modules)||data.modules.length>100)throw new Error('Invalid module catalog');
    const ids=new Set(),validText=(value,max)=>typeof value==='string'&&value.trim().length>0&&value.length<=max,
      bilingual=(value,max)=>value&&typeof value==='object'&&validText(value['zh-CN'],max)&&validText(value.en,max);
    return data.modules.map(row=>{
      if(!row||!validText(row.id,80)||!/^[a-z][a-z0-9-]*$/.test(row.id)||ids.has(row.id)||!bilingual(row.name,200)||!bilingual(row.description,1000)||!Array.isArray(row.site_ids)||row.site_ids.length>100||row.site_ids.some(id=>!validText(id,200)||/[\u0000-\u001f\u007f]/.test(id))||!(row.version==null||typeof row.version==='string'&&row.version.length<=80))throw new Error('Invalid module record');
      ids.add(row.id);return {id:row.id,name:{'zh-CN':row.name['zh-CN'],en:row.name.en},description:{'zh-CN':row.description['zh-CN'],en:row.description.en},version:row.version?.trim()||'',download_url:safeURL(row.download_url),documentation_url:safeURL(row.documentation_url),site_ids:[...new Set(row.site_ids)],installable:row.installable===true,needs_service:row.needs_service===true,installation:row.installation==null?null:parseJob(row.installation,row.id)};
    });
  }
  const ACTIVE=new Set(['queued','downloading','verifying','installing','building','connecting']),STATES=new Set([...ACTIVE,'completed','failed','idle']);
  const jobs=new Map(),versions=new Map(),submitting=new Set(),uncertain=new Set(),jobErrors=new Map(),reading=new Map(),completionPending=new Set(),completionNeeded=new Set(),completionHandled=new Set(),entryErrors=new Set();
  let entryRefreshTail=Promise.resolve();
  const ERROR_EN={unknown_module:'Unknown module.',installer_closed:'Workhub is closing. Try again shortly.',download_failed:'Download failed. Check the network and try again.',download_timeout:'The download timed out. Try again shortly.',download_network:'Could not connect. Check the network or proxy.',download_unavailable:'The download service is temporarily unavailable.',download_rate_limited:'The download service is rate limiting requests. Try again later.',download_not_found:'The published module package was not found.',download_denied:'The download service denied access.',download_tls:'The download connection certificate could not be verified.',download_redirect:'The download redirected to an untrusted address and was stopped.',archive_too_large:'The package exceeds the allowed size.',checksum_mismatch:'Package verification failed. No package code was run or installed.',invalid_archive:'The package does not match its published file list.',invalid_manifest:'The module manifest is invalid.',existing_install_invalid:'The existing version needs checking. Its files were preserved.',storage_unsafe:'The module storage directory could not be used safely.',build_failed:'The module page could not be prepared.',connect_failed:'The module has not been connected to the workspace.',service_failed:'The local service could not be started.',service_stopped:'The local service stopped. You can enable it again.',in_use:'Module data is in use. No lock was removed.',install_failed:'Installation did not complete. Try again.'};
  let readonlyCatalog=false,viewActive=false,pollTimer=null,polling=false,catalogVersion=0;
  const isReadonly=()=>readonlyCatalog||document.body.dataset.demo==='true';
  const isVisible=()=>viewActive&&!document.hidden&&!document.getElementById('modules-page')?.hidden;
  const bump=id=>versions.set(id,(versions.get(id)||0)+1);
  function parseJob(raw,id){
    if(!raw||typeof raw!=='object'||raw.module_id!==id||!STATES.has(raw.status)||(raw.id!==undefined&&raw.id!==id)||(raw.job_id!=null&&(typeof raw.job_id!=='string'||raw.job_id.length>120))||(raw.progress!=null&&(typeof raw.progress!=='number'||!Number.isFinite(raw.progress)||raw.progress<0||raw.progress>100))||(raw.error!=null&&(typeof raw.error!=='string'||raw.error.length>300))||(raw.message!=null&&(typeof raw.message!=='string'||raw.message.length>2000)))throw new Error('Invalid installation status');
    return {module_id:id,id,job_id:raw.job_id||'',status:raw.status,progress:raw.progress??null,error:raw.error||'',message:raw.message||''};
  }
  function jobKey(job){return job.module_id+':'+(job.job_id||'current');}
  function setJob(id,job){const old=jobs.get(id);bump(id);uncertain.delete(id);jobErrors.delete(id);if(job.status==='idle')jobs.delete(id);else jobs.set(id,job);if(job.status==='completed'&&(ACTIVE.has(old?.status)||submitting.has(id)||!modules.find(row=>row.id===id)?.site_ids.length))completionNeeded.add(id);}
  async function requestJSON(url,options={}){
    const response=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(10000),...options}),text=await response.text();if(text.length>1048576)throw new Error('Oversized response');let data;try{data=JSON.parse(text);}catch{throw new Error('Invalid response');}
    if(!response.ok){const error=new Error(typeof data?.message==='string'?data.message:typeof data?.error==='string'?data.error:'Request failed');error.code=typeof data?.error==='string'?data.error:'';error.httpStatus=response.status;throw error;}return data;
  }
  function targets(){return modules.filter(row=>ACTIVE.has(jobs.get(row.id)?.status)||uncertain.has(row.id)).map(row=>row.id);}
  function stopPoll(){if(pollTimer!==null)clearTimeout(pollTimer);pollTimer=null;}
  function schedulePoll(delay=1800){stopPoll();if(!isVisible()||isReadonly()||polling||!targets().length)return;pollTimer=setTimeout(()=>{pollTimer=null;pollJobs();},delay);}
  async function readJob(id){
    if(reading.has(id))return reading.get(id);const revision=versions.get(id)||0,previousError=jobErrors.get(id);
    const promise=(async()=>{try{const raw=await requestJSON('/api/modules/install?id='+encodeURIComponent(id)),job=parseJob(raw,id);if((versions.get(id)||0)!==revision)return;setJob(id,job);if(job.status==='idle')jobErrors.set(id,{key:'notStarted',detail:previousError?.detail||''});render();checkCompletions();}
      catch{if((versions.get(id)||0)===revision){jobErrors.set(id,{key:'statusUnavailable'});render();}}
      finally{reading.delete(id);}})();reading.set(id,promise);return promise;
  }
  async function pollJobs(){if(polling||!isVisible()||isReadonly())return;const ids=targets();if(!ids.length)return;polling=true;await Promise.allSettled(ids.map(readJob));polling=false;schedulePoll(jobErrors.size?5000:1800);}
  async function reconcile(id,retry=false){
    const job=jobs.get(id);if(!isVisible()||job?.status!=='completed'||completionPending.has(id))return;const key=jobKey(job);if(completionHandled.has(key)&&!retry)return;completionHandled.add(key);completionPending.add(id);entryErrors.delete(id);render();const previous=entryRefreshTail;let release;entryRefreshTail=new Promise(resolve=>release=resolve);await previous;
    try{if(!isVisible()){completionHandled.delete(key);return;}const dashboard=window.WorkhubDashboard;if(typeof dashboard?.refresh!=='function')throw new Error('Dashboard unavailable');await dashboard.refresh();if(!isVisible()){completionHandled.delete(key);return;}const ok=await load(true);if(!ok||!modules.find(row=>row.id===id)?.site_ids.length)throw new Error('Entry unavailable');completionNeeded.delete(id);entryErrors.delete(id);}
    catch{entryErrors.add(id);}
    finally{completionPending.delete(id);render();release();}
  }
  function checkCompletions(){if(isVisible())for(const id of completionNeeded)reconcile(id);}
  async function install(row){
    const id=row.id;if(isReadonly()||!row.installable||submitting.has(id)||completionPending.has(id)||jobs.get(id)?.status==='completed'&&completionNeeded.has(id)||ACTIVE.has(jobs.get(id)?.status))return;
    bump(id);submitting.add(id);completionNeeded.delete(id);uncertain.delete(id);jobErrors.delete(id);entryErrors.delete(id);for(const key of completionHandled)if(key.startsWith(id+':'))completionHandled.delete(key);render();
    try{const raw=await requestJSON('/api/modules/install',{method:'POST',headers:{'Content-Type':'application/json','X-Workhub-Request':'1'},body:JSON.stringify({id})}),job=parseJob(raw,id);if(job.status==='idle')throw new Error('No task accepted');setJob(id,job);}
    catch(error){uncertain.add(id);jobErrors.set(id,{key:'unconfirmed',detail:error.httpStatus?error.message.slice(0,600):''});}
    finally{submitting.delete(id);render();checkCompletions();schedulePoll(0);}
  }
  function installAction(row){
    const id=row.id,job=jobs.get(id),active=ACTIVE.has(job?.status),pending=submitting.has(id)||active||completionPending.has(id);let key='install',handler=()=>install(row);
    if(isReadonly())key='readonly';else if(completionPending.has(id))key='syncing';else if(submitting.has(id))key='submitting';else if(active)key='installing';else if(job?.status==='completed'&&(entryErrors.has(id)||!row.site_ids.length)){key='refreshEntry';handler=()=>reconcile(id,true);}else if(uncertain.has(id)||jobErrors.get(id)?.key==='statusUnavailable'){key='checkStatus';handler=async()=>{await readJob(id);schedulePoll();};}else if(job?.status==='failed')key='retryInstall';else if(row.needs_service)key='enableService';
    const button=element('button','whm-button whm-primary',t(key));button.type='button';button.dataset.whmFocus=id+':install';button.setAttribute('aria-label',t('installLabel',{action:t(key),name:local(row.name)}));button.disabled=isReadonly()||pending||(!row.installable&&!['refreshEntry','checkStatus'].includes(key));button.addEventListener('click',handler);return button;
  }
  function failureText(job){return t('failureReason',{reason:locale()==='en'&&Object.hasOwn(ERROR_EN,job.error)?ERROR_EN[job.error]:job.message||job.error||t('failedGeneric')});}
  function installationInfo(row){
    const id=row.id,job=jobs.get(id),box=element('div','whm-install-info');let text='';
    if(submitting.has(id))text=t('submitting');else if(completionPending.has(id))text=t('syncing');else if(uncertain.has(id))text=t('unconfirmed');else if(ACTIVE.has(job?.status)||job?.status==='failed'||job?.status==='completed'&&!row.site_ids.length)text=t('phase.'+job.status);
    if(text){const phase=element('p','whm-install-phase',text+(ACTIVE.has(job?.status)&&job.progress!==null?' · '+Math.round(job.progress)+'%':''));phase.setAttribute('role','status');phase.setAttribute('aria-live','polite');box.append(phase);}
    if(ACTIVE.has(job?.status)&&job.progress!==null){const progress=element('progress','whm-install-progress');progress.max=100;progress.value=job.progress;progress.setAttribute('aria-label',t('progressLabel',{name:local(row.name)}));box.append(progress);}
    if(job?.status==='failed'){const reason=element('p','whm-install-error',failureText(job).slice(0,600));reason.setAttribute('role','alert');box.append(reason);}
    const err=jobErrors.get(id);if(err?.detail){const reason=element('p','whm-install-error',t('failureReason',{reason:err.detail}));reason.setAttribute('role','status');box.append(reason);}if(err&&!uncertain.has(id)){const reason=element('p','whm-install-error',t(err.key));reason.setAttribute('role','status');box.append(reason);}
    if(entryErrors.has(id)){const reason=element('p','whm-install-error',t('entryError'));reason.setAttribute('role','status');box.append(reason);}return box;
  }
  function visibleModules(){const tokens=query.normalize('NFKC').trim().toLowerCase().split(/\s+/).filter(Boolean);return modules.filter(row=>{const hay=[row.id,...Object.values(row.name),...Object.values(row.description)].join(' ').normalize('NFKC').toLowerCase();return tokens.every(token=>hay.includes(token));});}
  panel.classList.add('whm-panel');
  const toolbar=element('div','whm-toolbar'),searchLabel=element('label','whm-search'),searchText=element('span','whm-sr'),search=element('input'),refresh=element('button','whm-button whm-refresh'),status=element('p','whm-status'),error=element('p','whm-error'),grid=element('div','whm-grid');
  search.type='search';search.id='whm-search';search.maxLength=500;search.autocomplete='off';searchLabel.append(searchText,search);refresh.type='button';refresh.id='whm-refresh';status.id='whm-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');error.id='whm-error';error.setAttribute('role','alert');error.hidden=true;grid.id='whm-grid';toolbar.append(searchLabel,refresh);panel.replaceChildren(toolbar,status,error,grid);
  function setOpening(value){opening=value;grid.querySelectorAll('[data-whm-open]').forEach(node=>node.disabled=value);}
  async function openModule(row,fullscreen){
    if(opening)return;errorKey='';error.hidden=true;setOpening(true);
    try{const dashboard=window.WorkhubDashboard;if(typeof dashboard?.openSite!=='function'||await dashboard.openSite(row.site_ids[0],{fullscreen})===false)throw new Error('Site unavailable');}
    catch{errorKey='openError';error.textContent=t(errorKey);error.hidden=false;}
    finally{setOpening(false);}
  }
  function action(row,fullscreen){const key=fullscreen?'fullscreen':'preview',button=element('button','whm-button'+(fullscreen?'':' whm-primary'),t(key));button.type='button';button.dataset.whmOpen=row.id+':'+key;button.dataset.whmFocus=row.id+':'+key;button.setAttribute('aria-label',t(key+'Label',{name:local(row.name)}));button.disabled=opening;button.addEventListener('click',()=>openModule(row,fullscreen));return button;}
  function externalLink(row,key,url){const link=element('a','whm-button',t(key));link.href=url;link.target='_blank';link.rel='noopener noreferrer';link.dataset.whmFocus=row.id+':'+key;link.setAttribute('aria-label',t(key+'Label',{name:local(row.name)}));return link;}
  function card(row){
    const article=element('article','whm-card'),title=element('h3','',local(row.name));title.id='whm-title-'+row.id;article.setAttribute('aria-labelledby',title.id);
    const description=element('p','whm-description',local(row.description)),meta=element('div','whm-meta'),connected=Boolean(row.site_ids.length),state=element('span','whm-connection',t(connected?'registered':'unregistered'));state.title=t(connected?'registeredHint':'unregisteredHint');
    meta.append(state,element('span','whm-version',row.version?t('version',{version:row.version}):t('versionUnknown')));
    const actions=element('div','whm-actions');if(connected){actions.append(action(row,false),action(row,true));if(row.needs_service||submitting.has(row.id)||ACTIVE.has(jobs.get(row.id)?.status)||uncertain.has(row.id))actions.append(installAction(row));}else{actions.append(installAction(row));if(row.documentation_url)actions.append(externalLink(row,'docs',row.documentation_url));}
    const info=installationInfo(row);article.append(title,description,meta);if(info.childNodes.length)article.append(info);article.append(actions);return article;
  }

  function render(){
    const focus=document.activeElement?.dataset?.whmFocus,rows=visibleModules();searchText.textContent=t('search');search.placeholder=t('placeholder');search.setAttribute('aria-label',t('search'));refresh.textContent=t('refresh');refresh.disabled=loading;panel.setAttribute('aria-busy',String(loading));
    status.textContent=loading?t('loading'):loaded?t('count',{shown:rows.length,total:modules.length,connected:modules.filter(row=>row.site_ids.length).length}):'';error.hidden=!errorKey;error.textContent=errorKey?t(errorKey):'';
    grid.replaceChildren(...rows.map(card));if(loaded&&!rows.length)grid.append(element('p','whm-empty',t(modules.length?'noMatches':'empty')));
    if(focus&&isVisible())Array.from(grid.querySelectorAll('[data-whm-focus]')).find(node=>node.dataset.whmFocus===focus)?.focus({preventScroll:true});
  }
  async function load(force=false){
    if(loading&&!force)return false;attempted=true;loading=true;errorKey='';const serial=++catalogVersion,atStart=new Map(versions);render();
    try{const data=await requestJSON('/api/modules'),rows=parseCatalog(data);if(serial!==catalogVersion)return false;modules=rows;readonlyCatalog=data.readonly===true||data.is_demo===true;loaded=true;
      for(const row of rows)if((versions.get(row.id)||0)===(atStart.get(row.id)||0)&&!submitting.has(row.id)){if(row.installation)setJob(row.id,row.installation);else if(!uncertain.has(row.id))jobs.delete(row.id);}
      return true;
    }catch{if(serial===catalogVersion)errorKey=loaded?'cachedError':'loadError';return false;}
    finally{if(serial===catalogVersion){loading=false;render();checkCompletions();schedulePoll();}}
  }
  function resume(){if(!isVisible()){stopPoll();return;}if(!attempted)load();else{render();checkCompletions();schedulePoll(0);}}
  search.addEventListener('input',()=>{query=search.value.slice(0,500);render();});refresh.addEventListener('click',()=>load());
  window.addEventListener('workhub:page',event=>{viewActive=event.detail?.page==='modules';resume();});
  document.addEventListener('visibilitychange',resume);
  I.onChange(render);const page=document.getElementById('modules-page');viewActive=Boolean(page&&!page.hidden);render();resume();
})();
