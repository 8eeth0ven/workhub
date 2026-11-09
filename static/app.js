'use strict';
const I=window.WorkhubI18n;
const t=(key,params)=>I.t(key,params);
const ICONS = {
 questions:'<path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 4M12 17v.2"/><circle cx="12" cy="12" r="9"/>',
 layout:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
 folder:'<path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10H3Z"/><path d="M3 10h18"/>',
 activity:'<path d="M3 12h4l3-8 4 16 3-8h4"/>',
 book:'<path d="M12 6c-3-2-6-2-9-1v14c3-1 6-1 9 1 3-2 6-2 9-1V5c-3-1-6-1-9 1Zm0 0v14"/>',
 shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 12 3 3 5-6"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',
 layers:'<path d="m12 3 9 5-9 5-9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/>',
 flag:'<path d="M5 21V4c5-4 9 4 14 0v11c-5 4-9-4-14 0"/>',
 grid:'<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/>',
 list:'<path d="M9 6h12M9 12h12M9 18h12M3 6h1M3 12h1M3 18h1"/>',
 search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
 refresh:'<path d="M20 8a8 8 0 1 0 0 8M20 3v5h-5"/>',
 close:'<path d="m6 6 12 12M6 18 18 6"/>',
 copy:'<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V4H4v12h4"/>',
 info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7v.5"/>',
 plug:'<path d="M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0Zm6 9v4"/>',
 wifi:'<path d="M2 8a16 16 0 0 1 20 0M5 12a11 11 0 0 1 14 0M9 16a5 5 0 0 1 6 0M12 20v.1"/>',
 check:'<path d="m5 12 4 4L19 6"/>'
};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
function element(tag, className, text) {const node=document.createElement(tag);if(className) node.className=className;if(text!==undefined) node.textContent=String(text);return node;}
function icon(name) {const span=element('span');span.setAttribute('aria-hidden','true');span.innerHTML=`<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ICONS.folder}</svg>`;return span;}
$$('[data-icon]').forEach(node=>node.replaceChildren(icon(node.dataset.icon).firstChild));
const STATUS = {running:'进行中',completed:'最近任务完成',blocked:'有任务受阻',paused:'已暂停',registered:'已接入'};
const AGENTS = {codex:{name:'Codex',symbol:'⌘'},claude:{name:'Claude Code',symbol:'✳'},zcode:{name:'Z Code',symbol:'z'}};
const dateFormatter={format:value=>I.formatDate(value)};
const timeFormatter={format:value=>I.formatDate(value,{hour:'2-digit',minute:'2-digit',second:'2-digit'})};
let state={projects:[],events:[],stats:{},agents:[]};
let loaded=false,fetching=false,lastSync=null,selectedProject=null,toastTimer=null,integrations=null;
let view='grid';
try{view=localStorage.getItem('workhub-project-view')==='list'?'list':'grid';}catch{}
function agentInfo(name){return AGENTS[String(name).toLowerCase()] || {name:String(name || 'Agent'),symbol:String(name || 'A').slice(0,1).toUpperCase()};}
function agentClass(name){return ['codex','claude','zcode'].includes(String(name).toLowerCase())?String(name).toLowerCase():'';}
function validDate(value){const d=new Date(value);return Number.isNaN(d.getTime())?null:d;}
function formattedDate(value){const d=validDate(value);return d?dateFormatter.format(d):t('时间未记录');}
function relativeDate(value){const d=validDate(value);if(!d) return t('暂无更新');const seconds=Math.max(0,Math.floor((Date.now()-d.getTime())/1000));if(seconds<60)return t('刚刚');if(seconds<3600)return I.formatRelative(-Math.floor(seconds/60),'minute');if(seconds<86400)return I.formatRelative(-Math.floor(seconds/3600),'hour');if(seconds<604800)return I.formatRelative(-Math.floor(seconds/86400),'day');return formattedDate(value);}
function statusPill(status){const s=Object.hasOwn(STATUS,status)?status:'registered';const pill=element('span',`status-pill ${s}`);pill.append(element('span','mini-dot'),document.createTextNode(t(STATUS[s])));return pill;}
function agentChip(name){const info=agentInfo(name);const chip=element('span',`agent-chip ${agentClass(name)}`);chip.append(element('span','',info.symbol),document.createTextNode(info.name));return chip;}
function showToast(message){clearTimeout(toastTimer);$('#toast').textContent=message;$('#toast').hidden=false;toastTimer=setTimeout(()=>{$('#toast').hidden=true;},2800);}
function openGuide(){const dialog=$('#guide-dialog');if(!dialog.open) dialog.showModal();}
$$('[data-guide]').forEach(button=>button.addEventListener('click',openGuide));
$$('[data-close]').forEach(button=>button.addEventListener('click',()=>document.getElementById(button.dataset.close).close()));
$$('dialog').forEach(dialog=>dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close();}));
$('#project-dialog').addEventListener('close',()=>{selectedProject=null;});
$$('[data-copy]').forEach(button=>button.addEventListener('click',async()=>{const text=button.dataset.copy;try{if(navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);else{const area=element('textarea');area.value=text;area.style.position='fixed';area.style.opacity='0';document.body.append(area);area.select();const copied=document.execCommand('copy');area.remove();if(!copied)throw new Error('Clipboard unavailable');}showToast(t('命令已复制，请替换项目路径后运行'));}catch{showToast(t('复制未成功，请手动选择命令'));}}));
function switchPage(page){if(!['spaces','records','templates','reviews','archives'].includes(page))return;['spaces','records','templates','reviews','archives'].forEach(name=>{document.getElementById(`${name}-page`).hidden=name!==page;});$$('.nav-item').forEach(item=>item.classList.toggle('active',item.dataset.page===page));$('#breadcrumb-page').textContent=t({spaces:'项目空间',records:'工作记录',templates:'版式工坊',reviews:'项目评议',archives:'项目档案'}[page]);window.scrollTo({top:0,behavior:'instant'});try{localStorage.setItem('workhub-current-page',page);}catch{}window.dispatchEvent(new CustomEvent('workhub:page',{detail:{page}}));}
$$('.nav-item').forEach(button=>button.addEventListener('click',()=>switchPage(button.dataset.page)));
function setView(next){view=next;try{localStorage.setItem('workhub-project-view',view);}catch{}$('#project-grid').classList.toggle('list-mode',view==='list');$('#grid-view').classList.toggle('selected',view==='grid');$('#list-view').classList.toggle('selected',view==='list');$('#grid-view').setAttribute('aria-pressed',String(view==='grid'));$('#list-view').setAttribute('aria-pressed',String(view==='list'));}
$('#grid-view').addEventListener('click',()=>setView('grid'));
$('#list-view').addEventListener('click',()=>setView('list'));
setView(view);
function filters(){return {query:$('#project-search').value.trim().toLocaleLowerCase(),agent:$('#agent-filter').value,status:$('#status-filter').value};}
function filteredProjects(){const {query,agent,status}=filters();return state.projects.filter(project=>(!agent||(project.agents||[]).includes(agent))&&(!status||project.status===status)&&(!query||[project.name,project.path,project.last_summary,project.description].filter(Boolean).join(' ').toLocaleLowerCase().includes(query)));}
function renderStats(){const stats=state.stats||{};const numbers={projects:stats.project_count??state.projects.length,running:stats.running_count??state.projects.filter(p=>p.status==='running').length,events:stats.event_count??state.events.length,blocked:stats.blocked_count??state.projects.filter(p=>p.status==='blocked').length};Object.entries(numbers).forEach(([key,value])=>{$(`#stat-${key}`).textContent=Number.isFinite(Number(value))?new Intl.NumberFormat(I.getLocale()).format(Number(value)):'0';});$('#nav-project-count').textContent=String(state.projects.length);}
function renderAgentFilter(){const current=$('#agent-filter').value;const names=[...new Set([...(state.agents||[]),...state.projects.flatMap(p=>p.agents||[])])].sort();const options=[element('option','',t('全部 Agent'))];options[0].value='';names.forEach(name=>{const option=element('option','',agentInfo(name).name);option.value=name;options.push(option);});$('#agent-filter').replaceChildren(...options);if(names.includes(current))$('#agent-filter').value=current;}
function projectCard(project,index){const card=element('button','project-card');card.type='button';card.setAttribute('aria-label',t('查看项目 {name} 的详情',{name:project.name}));card.addEventListener('click',()=>openProject(project.id));const top=element('div','card-top');const projectIcon=element('span',`project-icon tint-${index%4}`);projectIcon.append(icon('folder'));top.append(projectIcon,statusPill(project.status));const path=element('div','project-path',project.path||t('路径未记录'));path.title=project.path||'';const summary=element('div','project-summary',project.last_summary||project.description||t('已接入，等待第一条工作记录。'));const bottom=element('div','card-bottom');const agents=element('div','agent-chips');(project.agents||[]).slice(0,3).forEach(agent=>agents.append(agentChip(agent)));if(!(project.agents||[]).length)agents.append(element('span','agent-chip',t('等待 Agent')));const time=element('time','card-time',relativeDate(project.updated_at));if(validDate(project.updated_at))time.dateTime=project.updated_at;time.title=formattedDate(project.updated_at);bottom.append(agents,time,element('span','card-chevron','↗'));card.append(top,element('div','project-name',project.name||t('未命名项目')),path,summary,bottom);return card;}
function emptyProjects(filtered){const empty=element('div','empty-state');const pictogram=element('span','empty-icon');pictogram.append(icon(filtered?'search':'folder'));empty.append(pictogram,element('h3','',filtered?t('没有匹配的项目'):t('你的下一项进展，从这里开始')),element('p','',filtered?t('试着换一个关键词，或清除筛选条件。'):t('接入一个项目，让 Agent 的每次推进自动汇集到这个工作台。')));const button=element('button','button button-dark',filtered?t('清除筛选'):t('接入第一个项目'));button.addEventListener('click',filtered?()=>{$('#project-search').value='';$('#agent-filter').value='';$('#status-filter').value='';renderProjectsAndActivity();}:openGuide);empty.append(button);return empty;}
function renderProjectsAndActivity(){const projects=filteredProjects();$('#project-result-count').textContent=String(projects.length);const filter=filters();const filtering=Boolean(filter.query||filter.agent||filter.status);$('#project-grid').replaceChildren(...(projects.length?projects.map(projectCard):[emptyProjects(filtering)]));renderActivity(projects);}
function renderActivity(projects){const {agent,status,query}=filters();const projectIds=new Set(projects.map(p=>String(p.id)));const events=state.events.filter(event=>projectIds.has(String(event.project_id))&&(!agent||event.agent===agent)&&(!status||event.status===status));const list=$('#activity-list');if(!events.length){list.replaceChildren(element('div','activity-empty',agent||status||query?t('当前筛选下还没有工作记录。'):t('这里还很安静。\nAgent 提交第一条记录后，最新进展就会出现在这里。')));}else{list.replaceChildren(...events.slice(0,10).map(event=>{const item=element('button','activity-item');item.type='button';item.addEventListener('click',()=>openProject(event.project_id));const info=agentInfo(event.agent);item.append(element('span',`activity-avatar ${agentClass(event.agent)}`,info.symbol));const content=element('div','activity-content');const meta=element('div','activity-meta');const time=element('time','activity-time',relativeDate(event.created_at));time.title=formattedDate(event.created_at);if(validDate(event.created_at))time.dateTime=event.created_at;meta.append(element('span','activity-agent',info.name),time);const project=element('div','activity-project');project.append(icon('folder'),element('span','',event.project_name||state.projects.find(p=>String(p.id)===String(event.project_id))?.name||t('项目')));content.append(meta,element('div','activity-summary',event.summary||t(STATUS[event.status]||'工作更新')||t('工作更新')),project);item.append(content);return item;}));}$('#activity-footer').textContent=events.length?t('展示最近 {count} 条',{count:Math.min(events.length,10)})+(state.has_more?t(' · 更多记录保存在本机'):''):t('只展示真实记录');}
function detailField(label,value,mono=false){const row=element('div','detail-field');row.append(element('span','detail-label',label));if(value instanceof Node){const holder=element('div','detail-value');holder.append(value);row.append(holder);}else row.append(element('span',`detail-value${mono?' mono':''}`,value));return row;}
function openProject(id){selectedProject=String(id);renderProjectDetail();const dialog=$('#project-dialog');if(!dialog.open)dialog.showModal();}
function renderProjectDetail(){if(!selectedProject)return;const project=state.projects.find(p=>String(p.id)===selectedProject);const detail=$('#project-detail');if(!project){detail.replaceChildren(element('p','detail-description',t('该项目当前不可用，请刷新后重试。')));return;}const projectIcon=element('div','project-icon detail-project-icon');projectIcon.append(icon('folder'));const title=element('h2','detail-title',project.name);title.id='detail-title';const fields=element('div','detail-fields');const chips=element('div','agent-chips');(project.agents||[]).forEach(agent=>chips.append(agentChip(agent)));if(!chips.childNodes.length)chips.append(document.createTextNode(t('等待首次记录')));fields.append(detailField(t('项目路径'),project.path||t('未记录'),true),detailField(t('协作 Agent'),chips),detailField(t('最近更新'),formattedDate(project.updated_at)+t('（北京时间）')),detailField(t('累计记录'),t('{count} 条',{count:project.event_count||0})));const heading=element('h3','detail-history-heading',t('工作时间线'));const events=state.events.filter(event=>String(event.project_id)===selectedProject);heading.append(element('span','',t('最近 {count} 条',{count:events.length})));const timeline=element('div','detail-timeline');events.forEach(event=>{const block=element('article',`detail-event ${event.status}`);const meta=element('div','detail-event-meta');meta.append(agentChip(event.agent),statusPill(event.status),element('time','',formattedDate(event.created_at)));block.append(meta,element('div','detail-event-summary',event.summary||t('工作更新')));if(event.task)block.append(element('div','detail-task',t('任务 · {task}',{task:event.task})));if(event.details)block.append(element('div','detail-event-description',event.details));timeline.append(block);});if(!events.length)timeline.append(element('p','detail-description',t('项目已接入，尚未提交工作记录。')));const nodes=[projectIcon,title,statusPill(project.status),element('p','detail-description',project.description||project.last_summary||t('Agent 的进展将汇总为可追溯的工作时间线。')),fields,heading,timeline];if((project.event_count||0)>events.length)nodes.push(element('p','detail-limit',t('此处展示工作台最近同步的记录。完整历史保存在本机，可运行 ~/.local/bin/agent-workhub events --project /项目路径 --limit 1000 查看。')));const reviewButton=element('button','button button-outline detail-review-button',t('查看项目评议 ↗'));reviewButton.addEventListener('click',()=>{const id=project.id;$('#project-dialog').close();window.WorkhubReviews?.openProject(id);});nodes.splice(6,0,reviewButton);detail.replaceChildren(...nodes);}
function renderConnections(){const holder=$('#agent-connections');const entries=integrations?.integrations;if(Array.isArray(entries)&&entries.length){holder.replaceChildren(...entries.map(entry=>{const name=entry.agent||entry.name||'Agent';const info=agentInfo(name);const row=element('div','agent-connection');row.append(element('span','agent-symbol',info.symbol),element('span','',entry.name||info.name));const ready=Boolean(entry.ready);const description=element('span','connection-description',entry.is_demo?t('演示'):ready?t('已接入'):t('待接入'));row.append(description,element('span',`mini-dot ${ready?'green':'gray'}`));row.title=ready?t('已检查到全局规则入口及 skill'):t('尚未检查到完整接入配置');return row;}));return;}const active=new Set(state.agents||[]);holder.replaceChildren(...['codex','zcode','claude'].map(agent=>{const info=agentInfo(agent),row=element('div','agent-connection');row.append(element('span','agent-symbol',info.symbol),element('span','',info.name),element('span','connection-description',active.has(agent)?t('有工作记录'):t('暂无记录')),element('span',`mini-dot ${active.has(agent)?'green':'gray'}`));row.title=t('此状态基于工作记录；全局入口是否安装请查看接入指南。');return row;}));}
function setConnection(online){const status=$('#connection-status');status.className=`connection-status${online?'':' offline'}`;status.querySelector('span').textContent=online?t('已连接本机'):t('连接已断开');$('#error-banner').hidden=online;if(!online)$('#error-message').textContent=loaded?t('暂时无法连接本机服务，当前保留上次同步的数据。'):t('本机服务暂不可用。请先运行 python3 workhub.py serve，再重新连接。');}
async function sync(){if(fetching)return;fetching=true;$('#refresh-button').disabled=true;try{const response=await fetch('/api/state',{cache:'no-store',signal:AbortSignal.timeout(4500)});if(!response.ok)throw new Error(`HTTP ${response.status}`);const incoming=await response.json();if(!Array.isArray(incoming.projects)||!Array.isArray(incoming.events))throw new Error('Invalid state');state={...incoming,agents:Array.isArray(incoming.agents)?incoming.agents:[]};loaded=true;if(incoming.is_demo){document.body.dataset.demo='true';$('#demo-banner').hidden=false;}lastSync=new Date();setConnection(true);renderStats();renderAgentFilter();renderProjectsAndActivity();renderConnections();renderProjectDetail();renderSites();window.dispatchEvent(new CustomEvent('workhub:state',{detail:state}));$('#last-sync').textContent=t('上次同步 {time}',{time:timeFormatter.format(lastSync)});}catch{setConnection(false);if(!loaded){$('#project-result-count').textContent='0';$('#project-grid').replaceChildren(element('div','empty-state',t('工作记录暂时无法读取。连接恢复后会自动更新。')));$('#activity-list').replaceChildren(element('div','activity-empty',t('等待重新连接本机服务…')));}}finally{fetching=false;$('#refresh-button').disabled=false;}}
async function syncIntegrations(){try{const response=await fetch('/api/integrations',{cache:'no-store',signal:AbortSignal.timeout(3000)});if(response.ok){integrations=await response.json();renderConnections();}}catch{if(loaded)renderConnections();}}
['project-search','agent-filter','status-filter'].forEach(id=>document.getElementById(id).addEventListener(id==='project-search'?'input':'change',()=>{if(loaded)renderProjectsAndActivity();}));
$('#refresh-button').addEventListener('click',()=>{sync();syncIntegrations();});
$('#retry-button').addEventListener('click',()=>{sync();syncIntegrations();});
document.addEventListener('visibilitychange',()=>{if(!document.hidden){sync();syncIntegrations();}});
sync();syncIntegrations();setInterval(()=>{if(!document.hidden)sync();},5000);setInterval(()=>{if(!document.hidden)syncIntegrations();},30000);

// Sites retain their own files and runtime; the portal switches only this frame.
let siteState={sites:[],templates:[]},sitesLoaded=false,siteFetchBusy=false,activeSiteId=null,activeSiteSource='',frameTimer=null,siteLoadFailed=false,sitesLastSync=null,sitesOnline=null;
const FRAME_SANDBOX='allow-scripts allow-same-origin allow-forms allow-downloads allow-popups';
try{activeSiteId=localStorage.getItem('workhub-current-site');const page=localStorage.getItem('workhub-current-page');if(page)switchPage(page);}catch{}
function safeFrameUrl(value){if(typeof value!=='string'||!value.trim())return null;try{const url=new URL(value,location.origin);return ['http:','https:'].includes(url.protocol)?url.href:null;}catch{return null;}}
function renderSites(){
  if(!sitesLoaded)return;
  const groups=window.WorkhubSiteNavigation.groupProjects(state.projects,siteState.sites,$('#site-search').value);
  const counter=$('#site-count');
  counter.textContent=String(siteState.sites.length);
  counter.title=t('{projects} 个项目 · {sites} 个网站',{projects:state.projects.length,sites:siteState.sites.length});
  counter.setAttribute('aria-label',counter.title);
  const list=$('#site-list');
  if(!groups.length){
    list.replaceChildren(element('div','site-list-empty',$('#site-search').value.trim()?t('没有匹配的项目或网站。'):t('还没有接入项目或网站。')));
    return;
  }
  const nodes=groups.map(({project,sites})=>{
    const group=element('div','site-group');
    group.append(element('div','site-group-title',project.name||t('项目网站')));
    if(!sites.length){
      const button=element('button','site-item site-project-records');
      button.type='button';
      button.setAttribute('aria-label',t('查看项目 {name} 的详情',{name:project.name}));
      const symbol=element('span','site-item-icon');symbol.append(icon('book'));
      const info=element('span','site-item-info');
      info.append(element('strong','',t('尚未接入网站')),element('span','',t(project.event_count>0?'已有工作记录 · 查看详情':'已登记项目 · 查看详情')));
      button.append(symbol,info,element('span','site-item-arrow','→'));
      button.addEventListener('click',()=>{switchPage('records');openProject(project.id);});
      group.append(button);
    }
    sites.forEach(site=>{
      const button=element('button',`site-item${String(site.id)===activeSiteId?' selected':''}`);
      button.type='button';button.setAttribute('aria-pressed',String(String(site.id)===activeSiteId));
      const symbol=element('span','site-item-icon');symbol.append(icon('folder'));
      const info=element('span','site-item-info');
      info.append(element('strong','',site.name||project.name||t('项目网站')),element('span','',site.description||({directory:t('本机项目网站'),url:t('已接入网站')}[site.kind])||t('项目网站')));
      button.append(symbol,info,element('span','site-item-arrow','↗'));
      button.addEventListener('click',()=>selectSite(String(site.id)));
      group.append(button);
    });
    return group;
  });
  list.replaceChildren(...nodes);
}

function siteSource(site){
  // An explicit null means the backend could not prepare this preview; do not
  // fall back to a stale URL left over from an earlier directory runtime.
  return safeFrameUrl(Object.hasOwn(site,'preview_url')?site.preview_url:site.url);
}
function updateFrameHelp(site){
  const warning=typeof site.embedding_warning==='string'?I.translateKnown(site.embedding_warning.trim()):'';
  $('#frame-help').textContent=[warning,t('页面空白时，请检查原站服务是否运行，以及是否允许 iframe 嵌入。')].filter(Boolean).join(' ');
  $('#frame-help').hidden=!activeSiteSource;
}
function clearSiteSelection(message){
  clearTimeout(frameTimer);activeSiteId=null;activeSiteSource='';siteLoadFailed=false;
  try{localStorage.removeItem('workhub-current-site');}catch{}
  $('#site-frame').src='about:blank';$('#site-frame').hidden=true;
  $('#site-empty').hidden=false;
  $('#site-empty-text').textContent=message||t('选择左侧项目，网站会直接在这里展开。还没有网站？从一套喜欢的版式开始。');
  $('#current-site-name').textContent=t('选择一个项目网站');$('#current-site-url').textContent='';
  $('#reload-site').disabled=true;$('#site-review-button').disabled=true;$('#site-live-dot').className='mini-dot gray';
  $('#site-live-dot').title=t('尚未选择网站');$('#frame-notice').hidden=true;$('#frame-help').hidden=true;
}
function selectSite(id){
  const site=siteState.sites.find(item=>String(item.id)===String(id));if(!site)return;
  const source=siteSource(site);activeSiteId=String(id);
  try{localStorage.setItem('workhub-current-site',activeSiteId);}catch{}
  $('#current-site-name').textContent=site.name||t('项目网站');
  $('#current-site-url').textContent=source||t('网站预览暂不可用');
  $('#reload-site').disabled=!source;$('#site-review-button').disabled=!site.project_id;
  // A URL or an iframe load event does not establish cross-origin availability.
  $('#site-live-dot').className='mini-dot gray';
  $('#site-live-dot').title=source?t('已配置嵌入地址；请查看页面内容确认可用性'):t('网站预览暂不可用');
  $('#site-empty').hidden=Boolean(source);$('#site-frame').hidden=!source;
  if(!source){
    clearTimeout(frameTimer);activeSiteSource='';$('#site-frame').src='about:blank';
    $('#site-empty-text').textContent=I.translateKnown(site.embedding_warning)||t('这个项目还没有可用的网站地址。请先接入网站目录或 URL。');
    $('#frame-notice').hidden=true;$('#frame-help').hidden=true;renderSites();return;
  }
  if(source!==activeSiteSource){activeSiteSource=source;loadSiteFrame();}
  updateFrameHelp(site);renderSites();
}
function loadSiteFrame(){
  clearTimeout(frameTimer);siteLoadFailed=false;
  $('#frame-notice').textContent=t('正在载入项目网站…');$('#frame-notice').hidden=false;
  $('#site-frame').title=t('项目网站 · {name}',{name:$('#current-site-name').textContent});
  $('#site-frame').src=activeSiteSource;
  frameTimer=setTimeout(()=>{$('#frame-notice').textContent=t('页面仍在载入。如果网站未显示，请检查原站是否运行，以及是否允许嵌入显示。');},9000);
}
$('#site-frame').addEventListener('load',()=>{
  clearTimeout(frameTimer);
  // Browsers also fire load for some refused/failed cross-origin frames. Stop
  // the loading hint only; keep the persistent diagnostics and neutral status.
  if(activeSiteSource&&!siteLoadFailed)$('#frame-notice').hidden=true;
});
$('#site-frame').addEventListener('error',()=>{
  clearTimeout(frameTimer);siteLoadFailed=true;$('#frame-notice').hidden=false;
  const site=siteState.sites.find(item=>String(item.id)===activeSiteId);
  $('#frame-notice').textContent=site?.embedding_warning||t('网站暂时无法加载，请检查原站是否运行后刷新。');
});
$('#reload-site').addEventListener('click',()=>{if(activeSiteSource)loadSiteFrame();});
$('#site-search').addEventListener('input',renderSites);
['go-templates','empty-go-templates'].forEach(id=>document.getElementById(id).addEventListener('click',()=>switchPage('templates')));
function templatePresentation(template){
 const names={radar:t('信息雷达'),library:t('知识资料库'),brief:t('分析简报')};
 const categories={radar:t('信息收集'),library:t('知识管理'),brief:t('研究分析')};
 const descriptions={radar:t('汇集线索、来源与待处理信息，按优先级追踪动态。'),library:t('分类管理项目资料、参考链接和可检索的知识卡片。'),brief:t('呈现关键发现、证据、进展与下一步行动。')};
 return {name:names[template.id]||template.name||template.id,category:categories[template.id]||template.category,description:descriptions[template.id]||template.description};
}
let activeTemplate=null;
function renderTemplates(){const grid=$('#template-grid');if(!siteState.templates.length){const empty=element('div','empty-state');empty.append(element('h3','',t('版式尚未就绪')),element('p','',t('可用版式由本机模板目录提供，连接恢复后自动更新。')));grid.replaceChildren(empty);return;}grid.replaceChildren(...siteState.templates.map((template,index)=>{const card=element('button',`template-card template-tint-${index%3}`);card.type='button';card.setAttribute('aria-label',t('预览{name}版式',{name:templatePresentation(template).name}));const visual=element('div','template-card-visual');const previewUrl=safeFrameUrl(template.preview_url);if(previewUrl){const preview=element('iframe','template-thumbnail');preview.setAttribute('sandbox',FRAME_SANDBOX);preview.src=previewUrl;preview.title=t('{name}版式缩略预览',{name:templatePresentation(template).name});preview.loading='lazy';preview.tabIndex=-1;preview.setAttribute('aria-hidden','true');visual.append(preview);}else{visual.append(element('span','template-visual-placeholder',t('版式预览')));}const label=element('span','template-card-label',templatePresentation(template).category||t('可复用版式'));visual.append(label);const body=element('div','template-card-body');const title=element('div','template-card-title');title.append(element('h2','',templatePresentation(template).name),element('span','','↗'));body.append(title,element('p','',templatePresentation(template).description||t('可复用的网站排版。')),element('span','template-action',t('查看版式与生成命令')));card.append(visual,body);card.addEventListener('click',()=>openTemplate(template));return card;}));}
function openTemplate(template){activeTemplate=template;const preview=safeFrameUrl(template.preview_url);$('#template-detail').hidden=false;$('#template-detail-title').textContent=templatePresentation(template).name;const supported=['radar','library','brief'].includes(template.id);const templateId=supported?template.id:String(template.id||'radar').replace(/[^a-zA-Z0-9_-]/g,'');$('#template-command').textContent=`python3 scripts/site_templates.py create --template ${templateId} --output /path/to/project --name Project-site --language ${I.getLocale()}`;$('#template-frame').title=t('{name} · 完整版式预览',{name:templatePresentation(template).name});$('#template-frame').hidden=!preview;if(preview)$('#template-frame').src=preview;$('#template-detail').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});}
$('#close-template-preview').addEventListener('click',()=>{activeTemplate=null;$('#template-detail').hidden=true;$('#template-frame').src='about:blank';});
$('#copy-template-command').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('#template-command').textContent);showToast(t('已复制版式生成命令'));}catch{showToast(t('请手动选择生成命令复制'));}});
async function syncSites(){
  if(siteFetchBusy)return;siteFetchBusy=true;
  try{
    const response=await fetch('/api/sites',{cache:'no-store',signal:AbortSignal.timeout(4000)});
    if(!response.ok)throw new Error('Sites unavailable');
    const incoming=await response.json();
    if(!Array.isArray(incoming.sites)||!Array.isArray(incoming.templates))throw new Error('Invalid sites data');
    const templatesChanged=JSON.stringify(siteState.templates)!==JSON.stringify(incoming.templates);
    siteState=incoming;sitesLoaded=true;
    sitesLastSync=new Date();sitesOnline=true;$('#sites-sync').textContent=t('上次同步 {time}',{time:timeFormatter.format(sitesLastSync)});
    if(activeSiteId){
      const selected=siteState.sites.find(site=>String(site.id)===activeSiteId);
      if(!selected)clearSiteSelection(t('上次查看的网站已从项目空间移除。请选择其他网站，或接入一个新网站。'));
      else if((siteSource(selected)||'')!==activeSiteSource||!siteSource(selected))selectSite(activeSiteId);
      else updateFrameHelp(selected);
    }
    renderSites();
    if(templatesChanged||!$('#template-grid .template-card'))renderTemplates();
  }catch{
    if(!sitesLoaded){
      $('#site-list').replaceChildren(element('div','site-list-empty',t('网站列表暂不可用。\n本机服务恢复后会自动连接。')));
      $('#template-grid').replaceChildren(element('div','empty-state',t('版式列表暂不可用，请检查本机服务。')));
    }
    sitesOnline=false;$('#sites-sync').textContent=t('网站列表暂时离线');
  }finally{siteFetchBusy=false;}
}
syncSites();setInterval(()=>{if(!document.hidden)syncSites();},10000);

$('#site-review-button').addEventListener('click',()=>{const site=siteState.sites.find(item=>String(item.id)===activeSiteId);if(site?.project_id)window.WorkhubReviews?.openProject(site.project_id);});

I.onChange(()=>{
 const activePage=$('.nav-item.active')?.dataset.page||'spaces';
 $('#breadcrumb-page').textContent=t({spaces:'项目空间',records:'工作记录',templates:'版式工坊',reviews:'项目评议',archives:'项目档案'}[activePage]);
 if(loaded){renderStats();renderAgentFilter();renderProjectsAndActivity();renderConnections();renderProjectDetail();}
 renderSites();renderTemplates();
 if(sitesOnline===false)$('#sites-sync').textContent=t('网站列表暂时离线');else if(sitesLastSync)$('#sites-sync').textContent=t('上次同步 {time}',{time:timeFormatter.format(sitesLastSync)});
 ['frame-notice','site-empty-text'].forEach(id=>{const el=document.getElementById(id);if(el)el.textContent=I.translateKnown(el.textContent);});
 $('#site-live-dot').title=I.translateKnown($('#site-live-dot').title);
 $('#site-frame').title=activeSiteId?t('项目网站 · {name}',{name:$('#current-site-name').textContent}):t('当前项目网站');
 if(lastSync)$('#last-sync').textContent=t('上次同步 {time}',{time:timeFormatter.format(lastSync)});
 if(lastSync)setConnection(!$('#connection-status').classList.contains('offline'));
 if(activeSiteId){const site=siteState.sites.find(item=>String(item.id)===activeSiteId);if(site){updateFrameHelp(site);if(!siteSource(site))$('#site-empty-text').textContent=I.translateKnown(site.embedding_warning)||t('这个项目还没有可用的网站地址。请先接入网站目录或 URL。');}}
 if(activeTemplate){const id=String(activeTemplate.id||'radar').replace(/[^a-zA-Z0-9_-]/g,'');$('#template-command').textContent=`python3 scripts/site_templates.py create --template ${id} --output /path/to/project --name Project-site --language ${I.getLocale()}`;$('#template-detail-title').textContent=templatePresentation(activeTemplate).name;$('#template-frame').title=t('{name} · 完整版式预览',{name:templatePresentation(activeTemplate).name});}
 if(!$('#toast').hidden)$('#toast').textContent=I.translateKnown($('#toast').textContent);
});
