/* A read-only catalog. Opening a registered site is separate from installation. */
(() => {
  'use strict';
  const panel=document.getElementById('modules-panel'),I=window.WorkhubI18n;
  if(!panel||!I)return;
  const WORDS={
    'zh-CN':{search:'查找模块',placeholder:'查找模块或用途…',refresh:'刷新模块',loading:'正在读取模块…',count:'{shown} / {total} 个模块 · {connected} 个已接入',registered:'已接入',unregistered:'未接入',version:'版本 {version}',versionUnknown:'版本未提供',preview:'预览',fullscreen:'全屏打开',download:'下载模块',docs:'使用文档',empty:'暂无可显示的模块。',noMatches:'没有符合检索条件的模块。',loadError:'模块暂时无法读取，请点击“刷新模块”重试。',cachedError:'刷新未完成，保留上次读取的模块。请稍后重试。',openError:'这个入口暂时无法打开，请刷新模块后重试。',linksUnavailable:'下载与文档链接暂不可用。',registeredHint:'已登记网站入口；服务是否可用请打开确认。',unregisteredHint:'尚无关联网站入口，不代表模块未安装。',previewLabel:'预览 {name}',fullscreenLabel:'全屏打开 {name}',downloadLabel:'下载 {name}',docsLabel:'阅读 {name} 的使用文档'},
    en:{search:'Find modules',placeholder:'Find a module or purpose…',refresh:'Refresh modules',loading:'Loading modules…',count:'{shown} / {total} modules · {connected} connected',registered:'Connected',unregistered:'Not connected',version:'Version {version}',versionUnknown:'Version not provided',preview:'Preview',fullscreen:'Open fullscreen',download:'Download',docs:'Documentation',empty:'No modules are available.',noMatches:'No modules match this search.',loadError:'Modules could not be loaded. Choose Refresh modules to retry.',cachedError:'Refresh did not complete. The previous catalog is retained; try again shortly.',openError:'This entry could not be opened. Refresh the catalog and try again.',linksUnavailable:'Download and documentation links are unavailable.',registeredHint:'A website entry is registered; open it to check availability.',unregisteredHint:'No website entry is linked; this does not establish that the module is uninstalled.',previewLabel:'Preview {name}',fullscreenLabel:'Open {name} fullscreen',downloadLabel:'Download {name}',docsLabel:'Read documentation for {name}'}
  };
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
      ids.add(row.id);return {id:row.id,name:{'zh-CN':row.name['zh-CN'],en:row.name.en},description:{'zh-CN':row.description['zh-CN'],en:row.description.en},version:row.version?.trim()||'',download_url:safeURL(row.download_url),documentation_url:safeURL(row.documentation_url),site_ids:[...new Set(row.site_ids)]};
    });
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
    const actions=element('div','whm-actions');if(connected)actions.append(action(row,false),action(row,true));else{if(row.download_url)actions.append(externalLink(row,'download',row.download_url));if(row.documentation_url)actions.append(externalLink(row,'docs',row.documentation_url));if(!actions.childNodes.length)actions.append(element('p','whm-link-note',t('linksUnavailable')));}
    article.append(title,description,meta,actions);return article;
  }
  function render(){
    const focus=document.activeElement?.dataset?.whmFocus,rows=visibleModules();searchText.textContent=t('search');search.placeholder=t('placeholder');search.setAttribute('aria-label',t('search'));refresh.textContent=t('refresh');refresh.disabled=loading;panel.setAttribute('aria-busy',String(loading));
    status.textContent=loading?t('loading'):loaded?t('count',{shown:rows.length,total:modules.length,connected:modules.filter(row=>row.site_ids.length).length}):'';error.hidden=!errorKey;error.textContent=errorKey?t(errorKey):'';
    grid.replaceChildren(...rows.map(card));if(loaded&&!rows.length)grid.append(element('p','whm-empty',t(modules.length?'noMatches':'empty')));
    if(focus&&!panel.hidden)Array.from(grid.querySelectorAll('[data-whm-focus]')).find(node=>node.dataset.whmFocus===focus)?.focus({preventScroll:true});
  }
  async function load(){
    if(loading)return;attempted=true;loading=true;errorKey='';render();
    try{const response=await fetch('/api/modules',{cache:'no-store',signal:AbortSignal.timeout(6000)});if(!response.ok)throw new Error('Catalog unavailable');const raw=await response.text();if(raw.length>1048576)throw new Error('Catalog too large');modules=parseCatalog(JSON.parse(raw));loaded=true;}
    catch{errorKey=loaded?'cachedError':'loadError';}
    finally{loading=false;render();}
  }
  search.addEventListener('input',()=>{query=search.value.slice(0,500);render();});refresh.addEventListener('click',load);
  window.addEventListener('workhub:space-mode',event=>{if(event.detail?.mode==='modules'){if(!attempted)load();else render();}});
  I.onChange(render);render();if(document.documentElement.dataset.workhubSpaceMode==='modules')load();
})();
