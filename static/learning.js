/* Coding notes stay literal; only the reader can acknowledge a revision. */
(() => {
  'use strict';
  const I = window.WorkhubI18n;
  const t = (key, params) => I.t(key, params);

  const $ = id => document.getElementById(id);
  if (!$('learning-page')) return;
  const statusLabels = {pending:'待理解', understood:'已初步理解', needs_review:'内容已更新，待复习'};
  let data = {cards:[], stats:{}, global_stats:{}, projects:[]};
  let stateProjects = [], selectedId = null, selected = null, history = [];
  let loaded = false, busy = false, queued = false, detailBusy = false, detailSequence = 0;
  let listSignature = '', detailSignature = '', headerSignature = '', projectSignature = '', searchTimer = null;
  let ackBusy = null, notice = null, serviceError = null, demo = false, detailStateCard = null;
  let removedMode = false, lastRemoved = null;

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }
  const sameId = (a,b) => String(a) === String(b);
  const visible = () => !document.hidden && !$('learning-page').hidden;
  const filters = () => ({project:$('learning-project-filter').value, status:$('learning-status-filter').value, query:$('learning-search').value.trim(), removed:removedMode});
  const filterKey = () => JSON.stringify(filters());
  const statusOf = card => card.needs_review || card.status === 'needs_review' ? 'needs_review' : card.understood === true && card.status === 'understood' ? 'understood' : 'pending';
  const acknowledged = card => Boolean(card && statusOf(card) === 'understood');
  const formatNumber = value => Number.isFinite(Number(value)) ? new Intl.NumberFormat(I.getLocale()).format(Number(value)) : '—';
  function literal(value) {
    if (value === null || value === undefined) return '';
    if (typeof value !== 'object') return String(value);
    const known = ['title','text','description','action','question','content'].filter(key => typeof value[key] === 'string');
    return known.length ? known.map(key => value[key]).join('\n') : JSON.stringify(value);
  }
  const items = value => Array.isArray(value) ? value : value === null || value === undefined || value === '' ? [] : [value];
  function badge(card) {
    const status = statusOf(card);
    return el('span','learning-status '+status,t(statusLabels[status]));
  }
  async function api(url, options = {}) {
    const response = await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(7000),...options});
    let result;
    try { result = await response.json(); } catch { result = {}; }
    if (!response.ok) {
      const error = new Error(typeof result.error === 'string' ? result.error : 'HTTP '+response.status);
      error.status = response.status;
      throw error;
    }
    return result;
  }
  function showError(key, detail = '') {
    serviceError = key ? {key,detail:String(detail || '')} : null;
    renderError();
  }
  function renderError() {
    const holder = $('learning-error'), opened = holder.querySelector('details')?.open;
    holder.hidden = !serviceError;
    if (!serviceError) return;
    $('learning-error-text').textContent = t(serviceError.key);
    const extra = $('learning-error-details');
    extra.hidden = !serviceError.detail;
    $('learning-error-raw').textContent = serviceError.detail;
    if (opened !== undefined) extra.open = opened;
  }
  function updateProjects(force = false) {
    const known = new Map();
    [...stateProjects,...(data.projects || [])].forEach(project => {
      if (project && project.id !== undefined) known.set(String(project.id),project);
    });
    const list = [...known.values()].sort((a,b) => String(a.name).localeCompare(String(b.name),I.getLocale()));
    const signature = JSON.stringify([I.getLocale(),list.map(p => [String(p.id),p.name])]);
    if (!force && signature === projectSignature) return;
    projectSignature = signature;
    const current = $('learning-project-filter').value;
    const all = el('option','',t('全部项目')); all.value = '';
    const options = [all,...list.map(project => {const option = el('option','',project.name || t('未命名项目'));option.value = String(project.id);return option;})];
    if (current && !known.has(current)) {const option=el('option','',current);option.value=current;options.push(option);}
    $('learning-project-filter').replaceChildren(...options);
    $('learning-project-filter').value = current;
  }
  function renderStats() {
    const stats = data.stats || {};
    for (const name of ['total','understood','pending','needs_review']) $('learning-stat-'+name).textContent = formatNumber(stats[name]);
    const global = data.global_stats && Object.keys(data.global_stats).length ? data.global_stats : stats;
    const pending = Number(global.pending), review = Number(global.needs_review);
    $('nav-learning-count').textContent = Number.isFinite(pending) && Number.isFinite(review) ? formatNumber(pending+review) : '—';
    $('nav-learning-count').title = t('待理解与待复习');
  }
  function matches(card) {
    const current = filters();
    if (current.project && !sameId(card.project_id,current.project)) return false;
    if (current.status && statusOf(card) !== current.status) return false;
    if (!current.query) return true;
    return JSON.stringify([card.title,card.concept,card.explanation,card.implementation,card.terms,card.steps,card.example,card.self_check,card.project_name,card.interview,card.market_signals]).toLocaleLowerCase().includes(current.query.toLocaleLowerCase());
  }
  function renderList(force = false) {
    const cards = data.cards.filter(matches);
    const visibleCards=cards.map(card=>[card.id,card.title || card.concept,card.project_name || stateProjects.find(p=>sameId(p.id,card.project_id))?.name,statusOf(card),card.revision]);
    const signature = JSON.stringify([I.getLocale(),loaded,filters(),selectedId,visibleCards]);
    if (!force && signature === listSignature) return;
    listSignature = signature;
    $('learning-result-count').textContent = formatNumber(cards.length);
    const nodes = cards.map(card => {
      const row = el('div','learning-card-row');
      const button = el('button','learning-card');button.type='button';
      button.setAttribute('aria-pressed',String(sameId(card.id,selectedId)));
      button.setAttribute('aria-label',t('学习卡片：{title}',{title:card.title || t('尚未提供')}));
      const meta = el('span','learning-card-meta');
      meta.append(el('span','learning-card-project',card.project_name || stateProjects.find(p => sameId(p.id,card.project_id))?.name || t('项目')),badge(card));
      button.append(el('span','learning-card-title',card.title || card.concept || t('尚未提供')),meta);
      button.addEventListener('click',() => {if(!removedMode)selectCard(card.id);});
      const actions=el('div','learning-card-actions');
      if(!demo && !removedMode){const edit=el('button','learning-action',t('编辑'));edit.type='button';edit.setAttribute('aria-label',t('编辑：{title}',{title:card.title}));edit.addEventListener('click',()=>openEditor(card));actions.append(edit);}
      if(!demo){const action=el('button','learning-action',t(removedMode?'恢复':'移除'));action.type='button';action.setAttribute('aria-label',t(removedMode?'恢复：{title}':'移除：{title}',{title:card.title}));action.addEventListener('click',()=>removedMode?restoreCard(card):removeCard(card));actions.append(action);}
      row.append(button,actions);return row;
    });
    if (!nodes.length) {
      const empty=el('div','learning-empty');
      const filtered=Boolean(filters().project || filters().status || filters().query);
      empty.append(el('h3','',!loaded?t('正在读取学习卡片…'):removedMode?t('回收站为空或没有匹配项'):filtered?t('没有匹配的学习卡片'):t('还没有学习卡片')));
      empty.append(el('p','',filtered?t('换个项目、状态或关键词再试。'):t('完成实际开发后，Agent 可整理概念、实现与来源，等待你确认理解。')));
      nodes.push(empty);
    }
    const scroll=$('learning-card-list').scrollTop;
    $('learning-card-list').replaceChildren(...nodes);
    $('learning-card-list').scrollTop=scroll;
  }
  function section(title) {const node=el('section','learning-section');node.append(el('h3','',t(title)));return node;}
  function prose(title, value) {const node=section(title);node.append(el('p',value?'':'learning-muted',literal(value) || t('尚未提供')));return node;}
  async function copyReference(value) {
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value);
      else {const area=el('textarea');area.value=value;document.body.append(area);area.select();const copied=document.execCommand('copy');area.remove();if(!copied)throw new Error('copy');}
      window.showToast?.(t('来源已复制'));
    } catch {window.showToast?.(t('复制未成功，请手动选择来源'));}
  }
  // Only source metadata is rendered as text. A project path is copy-only;
  // a market link must be an external HTTPS URL without credentials.
  function externalURL(value) {
    try {
      const u = new URL(typeof value === 'string' ? value : '');
      const host = u.hostname.toLowerCase();
      if (u.protocol !== 'https:' || u.username || u.password || !host || host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local') || host.includes(':') || /^[0-9.]+$/.test(host)) return '';
      return u.href;
    } catch { return ''; }
  }
  function evidenceRows(values) {
    const box=el('div','learning-evidence');
    const sources=Array.isArray(values)?values:[];
    for(const source of sources) {
      if (!source || typeof source !== 'object' || !source.path) continue;
      const reference=literal(source.path)+(source.line!==null&&source.line!==undefined?':'+literal(source.line):'')+(source.symbol?' · '+literal(source.symbol):'');
      const row=el('div','learning-source'),text=el('div','learning-source-text');text.append(el('code','',reference));
      if(source.note)text.append(el('p','',literal(source.note)));
      const button=el('button','learning-copy',t('复制来源'));button.type='button';button.addEventListener('click',()=>copyReference(reference));row.append(text,button);box.append(row);
    }
    if(!box.children.length) box.append(el('p','learning-muted',t('未提供项目依据')));
    return box;
  }
  function labelText(title,value) {
    const row=el('div','learning-interview-row');row.append(el('span','learning-interview-label',t(title)),el('p','',literal(value)));return row;
  }
  function listBlock(title,values) {
    const rows=Array.isArray(values)?values.filter(value=>typeof value==='string'&&value.trim()):[];
    if(!rows.length)return null;
    const block=el('div','learning-interview-block');block.append(el('p','learning-interview-label',t(title)));
    const ul=el('ul');for(const value of rows)ul.append(el('li','',literal(value)));block.append(ul);return block;
  }
  function disclosure(title,key,open=false) {
    const box=el('details','learning-interview-detail');box.dataset.disclosureKey=key;box.open=open;box.append(el('summary','',title));return box;
  }
  function interviewSections(card) {
    const info=card.interview&&typeof card.interview==='object'&&!Array.isArray(card.interview)?card.interview:{};
    const intro=section('面试思考');
    if(info.role_context)intro.append(labelText('岗位',info.role_context));
    if(info.talk_track)intro.append(labelText('面试表达',info.talk_track));
    const qs=Array.isArray(info.questions)?info.questions:[];
    const valid=qs.filter(q=>q&&typeof q==='object'&&typeof q.question==='string'&&q.question.trim());
    if(valid.length){
      intro.append(el('p','learning-interview-subtitle',t('面试问题')));
      valid.forEach((q,i)=>{
        const entry=disclosure(literal(q.question),'question:'+i,i===0);
        for(const block of [listBlock('回答要点',q.answer_points),listBlock('追问',q.follow_ups)])if(block)entry.append(block);
        entry.append(el('p','learning-interview-label',t('项目依据')),evidenceRows(q.evidence));intro.append(entry);
      });
    }
    if(!info.role_context&&!info.talk_track&&!valid.length)intro.append(el('p','learning-muted',t('暂无面试内容，需结合项目证据补充。')));
    const decisions=section('设计决策与取舍');
    const ds=Array.isArray(info.decisions)?info.decisions.filter(d=>d&&typeof d==='object'&&typeof d.choice==='string'&&d.choice.trim()):[];
    if(!ds.length)decisions.append(el('p','learning-muted',t('暂无设计决策记录。')));
    ds.forEach((d,i)=>{
      const entry=disclosure(literal(d.choice),'decision:'+i,false);
      for(const [field,label] of [['alternative','替代方案'],['reason','原因'],['tradeoff','取舍'],['failure_mode','可能失败的情况'],['validation','如何验证']])if(d[field])entry.append(labelText(label,d[field]));
      entry.append(el('p','learning-interview-label',t('项目依据')),evidenceRows(d.evidence));decisions.append(entry);
    });
    return [intro,decisions];
  }
  function marketSection(card) {
    const node=section('岗位与前沿需求');
    const signals=Array.isArray(card.market_signals)?card.market_signals.filter(s=>s&&typeof s==='object'):[];
    if(!signals.length){node.append(el('p','learning-muted',t('未提供岗位来源，尚不能判断当前需求。')));return node;}
    node.append(el('p','learning-muted',t('来源与岗位信息按标注日期核对，单条招聘信息不代表整个市场。')));
    signals.forEach((signal,i)=>{
      const label=[literal(signal.role),literal(signal.organization)].filter(Boolean).join(' · ') || t('尚未提供');
      const entry=disclosure(label,'market:'+i,false);
      for(const [field,title] of [['region','地区'],['accessed_on','核查日期'],['summary','相关需求'],['project_relevance','与项目的联系'],['limitations','范围与局限']])if(signal[field])entry.append(labelText(title,signal[field]));
      const url=externalURL(signal.url);
      if(url){const link=el('a','learning-market-link',t('查看原始来源'));link.href=url;link.target='_blank';link.rel='noopener noreferrer';entry.append(link);}
      else entry.append(el('p','learning-muted',t('来源链接无效或不安全')));
      node.append(entry);
    });
    return node;
  }
  function renderDetailHeader() {
    $('learning-detail-header').hidden=!selected;
    $('learning-ack-panel').hidden=!selected || removedMode;
    if(!selected)return;
    const project=selected.project_name || stateProjects.find(p=>sameId(p.id,selected.project_id))?.name || t('项目');
    const title=selected.title || selected.concept || t('尚未提供');
    const signature=JSON.stringify([I.getLocale(),title,project,statusOf(selected),selected.revision,selected.previous_understood_revision]);
    if(signature===headerSignature)return;
    headerSignature=signature;
    $('learning-detail-title').textContent=title;
    const meta=[el('span','',project),badge(selected),el('span','',t('版本 {revision}',{revision:selected.revision}))];
    if(selected.previous_understood_revision!==null&&selected.previous_understood_revision!==undefined)meta.push(el('span','',t('先前已理解版本 {revision}',{revision:selected.previous_understood_revision})));
    $('learning-detail-meta').replaceChildren(...meta);
  }
  function renderDetail(force = false) {
    renderDetailHeader();
    // Provenance/acknowledgement metadata is not knowledge content. Keep the
    // mounted body (including text selections and copy-button focus) when only
    // agent/run metadata, timestamps, or the checkbox state changes.
    const knowledge=selected?[selected.id,selected.revision,literal(selected.concept),literal(selected.explanation),literal(selected.why),literal(selected.implementation),items(selected.terms).map(term=>[literal(term.term),literal(term.definition),literal(term.english),literal(term.project_context),literal(term.distinction)]),items(selected.steps).map(literal),literal(selected.example),items(selected.self_check).map(literal),items(selected.sources).map(source=>[literal(source.path),source.line,literal(source.symbol),literal(source.note)]),selected.interview,selected.market_signals]:null;
    const historyRows=history.map(version=>[version.revision,literal(version.title)]);
    const signature=JSON.stringify([I.getLocale(),knowledge,historyRows]);
    if (!force && signature===detailSignature) {renderAck();return;}
    detailSignature=signature;
    const holder=$('learning-detail-body'),scroll=holder.scrollTop;
    const sameCard = selected && sameId(detailStateCard,selected.id);
    const disclosureState=new Map(sameCard?[...holder.querySelectorAll('details[data-disclosure-key]')].map(node=>[node.dataset.disclosureKey,node.open]):[]);
    const opened=Boolean(sameCard && holder.querySelector('details.learning-history')?.open);
    detailStateCard = selected ? selected.id : null;
    if (!selected) {
      const empty=el('div','learning-empty');empty.append(el('h3','',t('选择一张学习卡片')),el('p','',t('在这里查看概念、项目实现、术语与来源。')));holder.replaceChildren(empty);return;
    }
    const concept=section('概念与人话解释');
    if (selected.concept) concept.append(el('strong','learning-concept',literal(selected.concept)));
    concept.append(el('p',selected.explanation?'':'learning-muted',literal(selected.explanation) || t('尚未提供')));
    const nodes=[...interviewSections(selected),concept];
    if (selected.why) nodes.push(prose('为什么需要它',selected.why));
    nodes.push(prose('本项目怎样实现',selected.implementation));
    const terms=section('术语字典'),dictionary=el('dl','learning-terms');
    items(selected.terms).forEach(term=>{
      if(!term||typeof term!=='object')return;
      const dt=el('dt','',literal(term.term)),dd=el('dd','');
      if(term.english)dt.append(el('span','learning-term-english',' · '+literal(term.english)));
      dd.append(el('p','',literal(term.definition)));
      if(term.project_context)dd.append(labelText('项目中',term.project_context));
      if(term.distinction)dd.append(labelText('容易混淆',term.distinction));
      dictionary.append(dt,dd);
    });
    terms.append(dictionary.children.length?dictionary:el('p','learning-muted',t('尚未提供')));nodes.push(terms);
    const steps=section('实现步骤'),ordered=el('ol');items(selected.steps).forEach(step=>ordered.append(el('li','',literal(step))));steps.append(ordered.children.length?ordered:el('p','learning-muted',t('尚未提供')));nodes.push(steps);
    const example=section('小例子');example.append(el('pre','learning-example',literal(selected.example) || t('尚未提供')));nodes.push(example);
    const self=section('试着用自己的话说说'),questions=el('ul');items(selected.self_check).forEach(question=>questions.append(el('li','',literal(question))));self.append(questions.children.length?questions:el('p','learning-muted',t('尚未提供')));nodes.push(self);
    const sources=section('文件与实现来源');sources.append(el('p','learning-muted',t('来源仅作阅读定位，不会打开或执行本机文件。')));
    items(selected.sources).forEach(source=>{
      const reference=literal(source.path)+(source.line!==null && source.line!==undefined?':'+literal(source.line):'')+(source.symbol?' · '+literal(source.symbol):'');
      const row=el('div','learning-source'),text=el('div','learning-source-text');text.append(el('code','',reference));if(source.note)text.append(el('p','',literal(source.note)));
      const button=el('button','learning-copy',t('复制来源'));button.type='button';button.addEventListener('click',()=>copyReference(reference));row.append(text,button);sources.append(row);
    });
    if (!items(selected.sources).length) sources.append(el('p','learning-muted',t('没有附带来源。')));
    nodes.push(sources,marketSection(selected));
    if (history.length) {
      const disclosure=el('details','learning-history');disclosure.append(el('summary','',t('历史版本（{count}）',{count:history.length})));
      history.forEach(version=>disclosure.append(el('p','',t('版本 {revision}',{revision:version.revision})+(version.title?' · '+literal(version.title):''))));disclosure.open=opened;nodes.push(disclosure);
    }
    holder.replaceChildren(...nodes);holder.querySelectorAll('details[data-disclosure-key]').forEach(node=>{if(disclosureState.has(node.dataset.disclosureKey))node.open=disclosureState.get(node.dataset.disclosureKey);});holder.scrollTop=scroll;renderAck();
  }
  function renderAck() {
    if (!selected) return;
    const checkbox=$('learning-understood');
    const applying=ackBusy && sameId(ackBusy.id,selected.id) && Number(ackBusy.revision)===Number(selected.revision);
    checkbox.checked=applying?ackBusy.desired:acknowledged(selected);
    const staleConfirmation=notice && sameId(notice.id,selected.id) && notice.blockedRevision!==undefined && Number(notice.blockedRevision)===Number(selected.revision);
    checkbox.disabled=Boolean(ackBusy || detailBusy || demo || staleConfirmation || !Number.isInteger(Number(selected.revision)));
    const acknowledgement=selected.acknowledgement;
    const time=acknowledgement && (acknowledgement.created_at || acknowledgement.acknowledged_at || acknowledgement.updated_at);
    $('learning-ack-status').textContent=ackBusy?t('正在保存你的确认…'):detailBusy?t('正在读取当前版本…'):demo?t('演示卡片只读，不能保存理解确认。'):acknowledged(selected)?t('已初步理解当前版本，内容更新后会提醒复习。')+(time?' '+t('确认时间 {time}',{time:I.formatDate(time)}):''):statusOf(selected)==='needs_review'?t('内容更新后需要重新阅读，再次确认。'):'';
    const message=notice && sameId(notice.id,selected.id)?notice:null;
    $('learning-ack-message').hidden=!message;
    $('learning-ack-message').textContent=message?t(message.key):'';
    $('learning-outside-filter').hidden=data.cards.some(card=>sameId(card.id,selected.id)&&matches(card));
  }
  async function loadDetail(id, {blocking=false} = {}) {
    const sequence=++detailSequence;
    detailBusy=blocking || detailBusy;
    if(detailBusy)renderAck();
    try {
      const result=await api('/api/learning/card?id='+encodeURIComponent(id));
      if (sequence!==detailSequence || !sameId(selectedId,id)) return;
      if (!result.card || !sameId(result.card.id,id)) throw new Error(t('学习服务返回了无法读取的结果。'));
      selected=result.card;history=Array.isArray(result.history)?result.history:[];renderDetail();
    } catch(error) {if(sequence===detailSequence&&sameId(selectedId,id))showError('无法读取学习卡片详情，已保留已有内容。',error.message);}
    finally {if(sequence===detailSequence){detailBusy=false;renderAck();}}
  }
  function selectCard(id) {
    if (sameId(selectedId,id) && selected) return;
    const card=data.cards.find(value=>sameId(value.id,id));
    if (!card) return;
    selectedId=String(id);selected=card;history=[];notice=null;$('learning-detail-body').scrollTop=0;renderList();renderDetail();loadDetail(id,{blocking:true});
  }
  async function refresh() {
    if (busy) {queued=true;return;}
    const requested=filterKey();busy=true;$('learning-refresh').disabled=true;$('learning-card-list').setAttribute('aria-busy','true');
    try {
      const current=filters(),params=new URLSearchParams();
      if(current.removed)params.set('removed','1');if(current.project)params.set('project_id',current.project);if(current.status)params.set('status',current.status);if(current.query)params.set('q',current.query);
      const incoming=await api('/api/learning'+(params.size?'?'+params.toString():''));
      if (requested!==filterKey()) {queued=true;return;}
      if (!Array.isArray(incoming.cards)) throw new Error(t('学习服务返回了无法读取的结果。'));
      data={...incoming,projects:Array.isArray(incoming.projects)?incoming.projects:[]};loaded=true;demo=Boolean(incoming.is_demo || document.body.dataset.demo==='true');
      updateProjects();renderStats();renderList();showError('');
      if (visible() && !removedMode) {
        if (!selectedId && data.cards.length) selectCard((data.cards.find(card=>statusOf(card)==='pending') || data.cards.find(card=>statusOf(card)==='needs_review') || data.cards[0]).id);
        else if(selectedId && !ackBusy) await loadDetail(selectedId);
      }
      renderAck();
    } catch(error) {showError('学习服务暂不可用，已保留上次结果。',error.message);}
    finally {busy=false;$('learning-refresh').disabled=false;$('learning-card-list').setAttribute('aria-busy','false');if(queued){queued=false;refresh();}}
  }
  async function acknowledge(event) {
    // Programmatic dispatch is not a reader acknowledgement. Merely loading,
    // polling, translating, or showing a card never calls this endpoint.
    if (event.isTrusted===false || removedMode || !selected || ackBusy || detailBusy || demo || $('learning-understood').disabled) {renderAck();return;}
    const id=selected.id,revision=selected.revision,desired=Boolean($('learning-understood').checked);
    // A read begun before this explicit change must not overwrite its result.
    detailSequence++;
    ackBusy={id,revision,desired};notice=null;renderAck();
    let refreshAfter=false;
    try {
      const result=await api('/api/learning/ack',{method:'POST',headers:{'Content-Type':'application/json','X-Workhub-Request':'1'},body:JSON.stringify({card_id:id,revision,understood:desired})});
      if (!result.card || !sameId(result.card.id,id)) throw new Error(t('学习服务返回了无法读取的结果。'));
      const index=data.cards.findIndex(card=>sameId(card.id,id));if(index>=0&&Number(data.cards[index].revision)<=Number(result.card.revision))data.cards[index]=result.card;
      if(sameId(selectedId,id) && Number(selected?.revision)<=Number(result.card.revision))selected=result.card;
      if(statusOf(result.card)==='needs_review')notice={id,key:'内容已更新，请阅读最新版本后重新确认。'};
      else window.showToast?.(t(desired?'已保存初步理解确认':'已取消理解确认'));
      refreshAfter=true;renderList();renderDetail();
    } catch(error) {
      notice={id,key:error.status===409?'内容已更新，请阅读最新版本后重新确认。':'确认暂未保存，已恢复显示；请刷新核对。',...(error.status===409?{blockedRevision:revision}:{})};
      if(error.status===409)refreshAfter=true;
      else showError('确认暂未保存，已恢复显示；请刷新核对。',error.message);
    } finally {ackBusy=null;renderAck();if(refreshAfter)refresh();}
  }

  // Mutations always send the backend knowledge-field whitelist, never the
  // response metadata or acknowledgement, so unrelated content stays intact.
  const editableFields=['card_key','title','concept','explanation','implementation','terms','steps','example','self_check','sources','why','interview','market_signals','agent','run_id','source_event_ids'];
  const clone = value => JSON.parse(JSON.stringify(value));
  function knowledgePayload(card) {
    const result={};for(const key of editableFields)if(Object.prototype.hasOwnProperty.call(card,key))result[key]=clone(card[key]);return result;
  }
  async function mutateCard(action, card, payload) {
    return api('/api/learning/'+encodeURIComponent(card.id)+'/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Workhub-Request':'1'},body:JSON.stringify({project_id:card.project_id,expected_revision:card.revision,...(action==='edit'?{card:payload}:{expected_lifecycle_version:card.lifecycle_version})})});
  }
  function clearSelection(){detailSequence++;selectedId=null;selected=null;history=[];notice=null;renderDetail(true);}
  function updateUndo() {
    undoBox.replaceChildren();undoBox.hidden=!lastRemoved;
    if(lastRemoved){undoBox.append(el('span','',t('已移入回收站：{title}',{title:lastRemoved.title})));const undo=el('button','learning-action',t('撤销'));undo.type='button';undo.addEventListener('click',()=>restoreCard(lastRemoved));undoBox.append(undo);}
  }
  async function removeCard(card) {
    if(demo || removedMode || !window.confirm(t('将「{title}」移入回收站？之后可以恢复。',{title:card.title})))return;
    try {
      const result=await mutateCard('remove',card);if(!result.card)throw new Error('Invalid response');
      lastRemoved=result.card;updateUndo();if(sameId(selectedId,card.id))clearSelection();await refresh();
    } catch(error){showError(error.status===409?'卡片已更新，请刷新后重试。':'操作未完成，请重试。',error.message);if(error.status===409)refresh();}
  }
  async function restoreCard(card) {
    try {
      const result=await mutateCard('restore',card);if(!result.card)throw new Error('Invalid response');
      if(lastRemoved&&sameId(lastRemoved.id,card.id)){lastRemoved=null;updateUndo();}await refresh();window.showToast?.(t('已恢复学习卡片'));
    } catch(error){showError(error.status===409?'卡片已更新，请刷新后重试。':'操作未完成，请重试。',error.message);if(error.status===409)refresh();}
  }
  const trashButton=el('button','learning-trash learning-action',t('回收站'));trashButton.type='button';trashButton.setAttribute('aria-pressed','false');
  $('learning-refresh').before(trashButton);
  const undoBox=el('div','learning-undo');undoBox.hidden=true;undoBox.setAttribute('role','status');
  document.querySelector('.learning-workspace').before(undoBox);
  trashButton.addEventListener('click',()=>{removedMode=!removedMode;trashButton.textContent=t(removedMode?'返回学习卡片':'回收站');trashButton.setAttribute('aria-pressed',String(removedMode));loaded=false;clearSelection();listSignature='';renderList(true);refresh();});
  function editorField(container,label,value,multiline=false) {
    const wrap=el('label','learning-editor-field');wrap.append(el('span','',t(label)));
    const input=el(multiline?'textarea':'input');if(multiline)input.rows=3;input.value=typeof value==='string'?value:'';input.dataset.initialValue=input.value;wrap.append(input);container.append(wrap);return input;
  }
  async function openEditor(item) {
    if(demo||removedMode)return;
    let current;
    try {const result=await api('/api/learning/card?id='+encodeURIComponent(item.id));current=result.card;if(!current||!sameId(current.id,item.id))throw new Error('Invalid response');}
    catch(error){showError('无法读取学习卡片详情，已保留已有内容。',error.message);return;}
    const draft=knowledgePayload(current),dialog=el('dialog','learning-editor'),form=el('form','learning-editor-form');form.method='dialog';
    dialog.setAttribute('aria-label',t('编辑学习卡片'));form.append(el('h2','',t('编辑学习卡片')),el('p','learning-muted',t('保存会创建新版本，理解状态由你确认。')));
    const basic={};for(const [key,label,multi] of [['title','标题',false],['concept','概念',true],['explanation','解释',true],['implementation','项目实现',true]])basic[key]=editorField(form,label,draft[key],multi);
    const termsSection=el('section','learning-editor-group');termsSection.append(el('h3','',t('术语')));const terms=[];
    function addTerm(original={}){
      const box=el('div','learning-editor-item'),entry={original:clone(original)};for(const [key,label] of [['term','术语'],['definition','解释'],['english','英文'],['project_context','项目中'],['distinction','容易混淆']])entry[key]=editorField(box,label,original[key],key!=='term'&&key!=='english');
      const remove=el('button','learning-action',t('移除术语'));remove.type='button';remove.addEventListener('click',()=>{entry.removed=true;box.remove();});box.append(remove);termsSection.append(box);terms.push(entry);
    }
    for(const item of draft.terms||[])addTerm(item);const addTermButton=el('button','learning-action',t('添加术语'));addTermButton.type='button';addTermButton.addEventListener('click',()=>addTerm());termsSection.append(addTermButton);form.append(termsSection);
    const interview=el('section','learning-editor-group');interview.append(el('h3','',t('面试问题')));const info=draft.interview||{},talk=editorField(interview,'面试表达',info.talk_track,true),questions=[];
    const readField=(input, original) => input.value===input.dataset.initialValue ? original : input.value;
    function addQuestion(original={}) {
      const box=el('div','learning-editor-item'),entry={original:clone(original)};
      entry.question=editorField(box,'问题',original.question,true);
      for(const [key,label] of [['answer_points','回答要点'],['follow_ups','追问']]) {
        const group=el('div','learning-editor-group');group.append(el('h4','',t(label)));entry[key]=[];
        const addEntry=(value='')=>{
          const row=el('div','learning-editor-item'),item={original:value};item.input=editorField(row,label,value,true);
          const remove=el('button','learning-action',t('移除'+label));remove.type='button';remove.addEventListener('click',()=>{item.removed=true;row.remove();});
          row.append(remove);group.append(row);entry[key].push(item);
        };
        for(const value of original[key]||[])addEntry(value);
        const add=el('button','learning-action',t('添加'+label));add.type='button';add.addEventListener('click',()=>addEntry());group.append(add);box.append(group);
      }
      const remove=el('button','learning-action',t('移除问题'));remove.type='button';remove.addEventListener('click',()=>{entry.removed=true;box.remove();});box.append(remove);interview.append(box);questions.push(entry);
    }
    for(const item of info.questions||[])addQuestion(item);const addQuestionButton=el('button','learning-action',t('添加问题'));addQuestionButton.type='button';addQuestionButton.addEventListener('click',()=>addQuestion());interview.append(addQuestionButton);form.append(interview);
    const error=el('p','learning-editor-error');error.setAttribute('role','alert');error.hidden=true;form.append(error);
    const actions=el('div','learning-editor-actions'),cancel=el('button','learning-action',t('取消')),save=el('button','learning-save',t('保存'));cancel.type='button';save.type='submit';actions.append(cancel,save);form.append(actions);dialog.append(form);document.body.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});
    function editorPayload() {
      const payload=clone(draft);for(const key of Object.keys(basic))payload[key]=readField(basic[key],draft[key]);
      payload.terms=terms.filter(x=>!x.removed).map(entry=>{const value=clone(entry.original);for(const key of ['term','definition','english','project_context','distinction'])if(key in value||entry[key].value)value[key]=readField(entry[key],entry.original[key]);return value;});
      const questionValues=questions.filter(x=>!x.removed).map(entry=>{const value=clone(entry.original);value.question=readField(entry.question,entry.original.question);for(const key of ['answer_points','follow_ups']){const list=entry[key].filter(x=>!x.removed).map(x=>readField(x.input,x.original));if(key in value||list.length)value[key]=list;}return value;});
      if(draft.interview||talk.value||questionValues.length){payload.interview=clone(info);if('talk_track' in info||talk.value)payload.interview.talk_track=readField(talk,info.talk_track);if('questions' in info||questionValues.length)payload.interview.questions=questionValues;}
      return payload;
    }
    let saving=false;
    function mayDiscard(){return !saving && (JSON.stringify(editorPayload())===JSON.stringify(draft) || window.confirm(t('有未保存的更改，确定放弃吗？')));}
    cancel.addEventListener('click',()=>{if(mayDiscard())dialog.close();});
    dialog.addEventListener('cancel',event=>{if(!mayDiscard())event.preventDefault();});
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(save.disabled)return;
      const payload=editorPayload();
      saving=true;save.disabled=true;error.hidden=true;
      try {const result=await mutateCard('edit',current,payload);if(!result.card)throw new Error('Invalid response');dialog.close();await refresh();window.showToast?.(t('已保存新版本'));}
      catch(e){error.hidden=false;error.textContent=t(e.status===409?'卡片已在别处更新，草稿仍在。请复制内容后关闭并重新打开。':'保存失败，草稿仍在。')+(e.status===409?'':(' '+e.message));if(e.status!==409)save.disabled=false;}
      finally {saving=false;}
    });
    dialog.showModal();
  }

  $('learning-understood').addEventListener('change',acknowledge);
  $('learning-refresh').addEventListener('click',refresh);$('learning-retry').addEventListener('click',refresh);
  ['learning-project-filter','learning-status-filter'].forEach(id=>$(id).addEventListener('change',()=>{renderList();renderAck();refresh();}));
  $('learning-search').addEventListener('input',()=>{renderList();renderAck();clearTimeout(searchTimer);searchTimer=setTimeout(refresh,280);});
  window.addEventListener('workhub:page',event=>{if(event.detail.page==='learning')refresh();});
  window.addEventListener('workhub:state',event=>{stateProjects=Array.isArray(event.detail.projects)?event.detail.projects:[];demo=Boolean(event.detail.is_demo||demo);updateProjects();renderList();renderDetailHeader();renderAck();});
  document.addEventListener('visibilitychange',()=>{if(visible())refresh();});
  I.onChange(()=>{trashButton.textContent=t(removedMode?'返回学习卡片':'回收站');updateUndo();updateProjects(true);renderStats();renderList(true);renderDetail(true);renderError();});
  window.WorkhubLearning={refresh,selectCard,openProject(id){if(typeof switchPage==='function')switchPage('learning');$('learning-project-filter').value=String(id);renderList();refresh();}};
  if(typeof state!=='undefined'&&Array.isArray(state.projects))stateProjects=state.projects;
  updateProjects();renderDetail();refresh();
  setInterval(()=>{if(visible())refresh();},15000);
})();
