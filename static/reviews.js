'use strict';
(() => {
  const I=window.WorkhubI18n;
  const t=(key,params)=>I.t(key,params);
  const byId=id=>document.getElementById(id);
  const node=(tag,className,text)=>{const el=document.createElement(tag);if(className)el.className=className;if(text!==undefined)el.textContent=String(text);return el;};
  const VERDICTS={ready:'依据较充分',needs_attention:'有待补全',insufficient_evidence:'资料不足',unreviewed:'尚未评议'};
  const CONFIDENCE={low:'低',medium:'中',high:'高'};
  const QUESTION_GROUPS=[
    {key:'clarification',label:'澄清概念',aliases:['clarify','clarification','concept','澄清','澄清概念']},
    {key:'assumptions',label:'追问假设',aliases:['assumption','assumptions','假设','追问假设']},
    {key:'evidence',label:'检验证据',aliases:['evidence','reasoning','reasons','证据','理由与证据','检验证据']},
    {key:'perspectives',label:'转换视角',aliases:['perspectives','perspective','alternatives','viewpoints','视角','其他视角','转换视角']},
    {key:'implications',label:'推演后果',aliases:['implications','implication','consequences','后果','影响与后果','推演后果']},
    {key:'reflection',label:'反思问题',aliases:['reflection','meta','questioning','反思','问题本身','反思问题']}
  ];
  const FALLBACK_DIMENSIONS=['目标清晰度','证据质量','覆盖完整性','验证充分度','行动可执行性'];
  let projects=[],reviews=[],provider={configured:false},rubric=[],serverJobs=[];
  let selectedId=null,detailFingerprint='',requestBusy=false,lastReviewError='',pendingSubmit=null;
  let detailRequest=0,jobRenderKey='',initialSelectionDone=false,jobHistoryNode=null,unresolvedNoticeNode=null;
  const jobDisclosureNodes=new Map();
  const drafts=new Map(),detailsCache=new Map(),liveJobs=new Map(),pollTimers=new Map(),pollFailures=new Map();
  const localDate=value=>I.formatDate(value);
  const textOf=value=>typeof value==='string'?value:(value&&typeof value==='object'?String(value.text??value.description??value.statement??value.title??value.reason??value.action??''):String(value??''));
  const reviewFor=id=>reviews.find(review=>String(review.project_id)===String(id))||null;
  const projectFor=id=>projects.find(project=>String(project.id)===String(id));
  const jobActive=job=>['queued','running'].includes(job.status);
  function jobTimestamp(job,field='created_at'){const value=Date.parse(job[field]||job._received_at||'');return Number.isFinite(value)?value:0;}
  function allJobs(){
    const jobs=new Map();serverJobs.forEach(job=>jobs.set(String(job.id||job.job_id),job));
    liveJobs.forEach((job,id)=>{const existing=jobs.get(String(id));if(!existing||jobTimestamp(job,'updated_at')>=jobTimestamp(existing,'updated_at'))jobs.set(String(id),job);});
    return [...jobs.values()].map((job,index)=>({job,index})).sort((a,b)=>jobTimestamp(b.job)-jobTimestamp(a.job)||jobTimestamp(b.job,'updated_at')-jobTimestamp(a.job,'updated_at')||a.index-b.index).map(item=>item.job);
  }
  function projectBusy(id){return allJobs().some(job=>jobActive(job)&&(!Array.isArray(job.project_ids)||!job.project_ids.length||job.project_ids.some(projectId=>String(projectId)===String(id))));}
  function setError(message){lastReviewError=message||'';byId('reviews-error').hidden=!message;byId('reviews-error-text').textContent=message||'';}
  async function api(url,options={}){
    const response=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(10000),...options});
    let data;try{data=await response.json();}catch{throw new Error(t('本机评议服务返回了无法读取的结果。'));}
    if(!response.ok)throw new Error(typeof data.error==='string'?I.errorMessage(data.error):t('评议请求未成功（HTTP {status}）。',{status:response.status}));
    return data;
  }
  function verdictBadge(review){const verdict=review&&Object.hasOwn(VERDICTS,review.verdict)?review.verdict:'unreviewed';return node('span',`review-verdict ${verdict}`,t(VERDICTS[verdict]));}
  function scoreText(score){return typeof score==='number'&&Number.isFinite(score)&&score>=0&&score<=4?`${score}/4`:t('待判断');}
  function dimensionLabel(dimension){const labels={goal:t('目标清晰度'),evidence:t('证据质量'),verification:t('验证充分度'),risks:t('覆盖与风险'),next_steps:t('下一步行动')};return labels[dimension.key]||(typeof dimension.key==='number'?t(dimension.label):dimension.label)||dimension.key||t('评价维度');}
  function dimensionsFor(review){if(Array.isArray(review?.dimensions)&&review.dimensions.length)return review.dimensions;const source=Array.isArray(rubric)&&rubric.length?rubric.slice(0,5):FALLBACK_DIMENSIONS;return source.map((item,index)=>({key:typeof item==='object'?item.key:index,label:typeof item==='object'?(item.label||item.name||FALLBACK_DIMENSIONS[index]):item,score:null,reason:t('尚未取得评议结果。'),evidence_ids:[]}));}
  function renderProvider(){
    const name=provider.provider||t('模型评议器'),model=provider.model||t('模型未标明');
    let configuration=t('尚未完成评议器配置。可配置 API、本地模型或显式 CLI 适配器，然后刷新。');
    if(provider.is_demo)configuration=t('演示结果，未调用模型。不会读取本机密钥或调用外部服务。');
    else if(provider.configured){
      const authentication=Number(provider.key_count)>0?t('{count} 个本机密钥已配置',{count:Number(provider.key_count)}):provider.mode==='cli'?t('CLI 适配器已配置'):provider.mode==='local'?t('本地模型服务已配置'):t('已配置，无 API Key');
      configuration=`${name} · ${model} · ${authentication}`;
    }
    byId('review-provider-description').textContent=configuration;
    byId('review-provider-status').textContent=provider.is_demo?t('演示 · 只读'):provider.configured?t('已配置'):t('待配置');
    byId('review-provider-status').classList.toggle('configured',Boolean(provider.configured)&&!provider.is_demo);
    byId('review-data-note-text').textContent=provider.is_demo?t('这里仅展示虚构项目与预置评议，所有评分和问题均为演示数据，未调用模型。'):t('发起评议时，项目名称、描述、近期工作记录和补充背景会交给所选评议器；CLI 或本地模型是否联网由其配置决定。密钥保留在本机后端。');
    updateButtons();
  }
  function updateButtons(){
    const anyActive=allJobs().some(jobActive);
    byId('review-all-button').disabled=!provider.configured||!projects.length||anyActive||Boolean(pendingSubmit);
    byId('review-all-button').title=provider.is_demo?t('演示模式仅供查看'):!provider.configured?t('先在本机配置评议器'):anyActive?t('等待当前评议完成'):'';
    const submit=byId('review-answer-submit');
    submit.disabled=!provider.configured||!selectedId||!byId('review-answer').value.trim()||projectBusy(selectedId)||Boolean(pendingSubmit);
    const reevaluate=byId('review-project-run');if(reevaluate){reevaluate.disabled=!provider.configured||projectBusy(selectedId)||Boolean(pendingSubmit);reevaluate.textContent=projectBusy(selectedId)?t('正在评议…'):t('重新评议此项目');}
  }
  function renderProjectList(){
    const query=byId('review-search').value.trim().toLowerCase(),filter=byId('review-status-filter').value;
    const visible=projects.filter(project=>{const review=reviewFor(project.id);const verdict=review?.verdict||'unreviewed';return (!filter||(filter==='stale'?Boolean(review?.is_stale):verdict===filter))&&(!query||[project.name,project.path,review?.headline,review?.summary].filter(Boolean).join(' ').toLowerCase().includes(query));});
    byId('reviews-project-count').textContent=`${visible.length} / ${projects.length}`;
    const list=byId('review-project-list');
    if(!visible.length){const empty=node('div','review-list-empty');empty.append(node('h3','',projects.length?t('没有匹配的项目'):t('还没有接入项目')),node('p','',projects.length?t('换个关键词或评价状态再试。'):t('接入项目后，即可从真实工作记录发起评议。')));list.replaceChildren(empty);return;}
    list.replaceChildren(...visible.map(project=>{
      const review=reviewFor(project.id),card=node('button',`review-project-card${String(project.id)===selectedId?' selected':''}`);card.type='button';card.setAttribute('aria-pressed',String(String(project.id)===selectedId));
      const heading=node('div','review-card-heading');heading.append(node('strong','',project.name||t('未命名项目')),verdictBadge(review));
      const headline=node('p','review-card-headline',review?.headline||t('尚未评议，先从已有记录建立依据。'));
      const dimensions=node('div','review-card-dimensions');dimensionsFor(review).slice(0,5).forEach(dimension=>{const item=node('div','review-card-dimension');const label=String(dimensionLabel(dimension));item.title=label;item.append(node('span','',label),node('strong','',scoreText(dimension.score)));dimensions.append(item);});
      const evidence=node('div','review-card-foot');evidence.append(node('span','',review?t('依据 {count} 条 · 置信度{confidence}',{count:Number(review.evidence_count)||0,confidence:t(CONFIDENCE[review.confidence]||'待判断')}):t('依据充足度：待评议')));
      if(projectBusy(project.id))evidence.append(node('span','review-card-pending',t('评议中')));
      else if(review?.is_stale)evidence.append(node('span','review-stale-tag',t('待更新')));
      card.append(heading,headline,dimensions,evidence);card.addEventListener('click',()=>selectProject(String(project.id)));return card;
    }));
  }
  function evidenceRefs(ids){const holder=node('div','review-evidence-refs');if(!Array.isArray(ids)||!ids.length){holder.append(node('span','review-evidence-missing',t('未标明直接依据')));return holder;}ids.forEach(id=>{const reference=node('span','review-evidence-ref',id);reference.title=t('模型引用的依据标识；请结合原始记录核对');holder.append(reference);});return holder;}
  function infoList(title,items,emptyText,className=''){
    const section=node('section',`review-section ${className}`);section.append(node('h3','',title));
    if(!Array.isArray(items)||!items.length)section.append(node('p','review-section-empty',emptyText));
    else{const list=node('ul','review-text-list');items.forEach(item=>{const li=node('li');li.append(node('span','',textOf(item)));if(item&&typeof item==='object'&&Array.isArray(item.evidence_ids))li.append(evidenceRefs(item.evidence_ids));list.append(li);});section.append(list);}return section;
  }
  function renderDetail(force=false){
    if(!selectedId)return;const project=projectFor(selectedId);if(!project)return;
    const cached=detailsCache.get(selectedId),review=reviewFor(selectedId)||cached?.review||null;
    const fingerprint=JSON.stringify([selectedId,project.name,project.path,review,cached?.evidence,projectBusy(selectedId),Boolean(provider.configured)]);
    if(!force&&fingerprint===detailFingerprint){renderAnswerHistory();updateButtons();return;}detailFingerprint=fingerprint;
    const disclosureState=new Map([...byId('review-detail-content').querySelectorAll('details')].map((el,index)=>[el.dataset.i18nDisclosure||String(index),el.open]));
    const wrapper=node('div','review-detail-body');
    const heading=node('div','review-detail-heading');const title=node('div');title.append(node('span','eyebrow',t('SOCRATIC PROJECT REVIEW')),node('h2','',project.name||t('未命名项目')),node('p','review-project-path',project.path||''));
    const run=node('button','button button-outline',projectBusy(selectedId)?t('正在评议…'):t('重新评议此项目'));run.id='review-project-run';run.addEventListener('click',()=>startReview({project_id:selectedId,force:true}));heading.append(title,run);wrapper.append(heading);
    if(!review){const empty=node('div','review-no-result');empty.append(verdictBadge(null),node('h3','',t('先了解已有依据，再讨论哪里需要补全。')),node('p','',t('这个项目尚无评议结果。发起评议后，所选评议器会阅读已登记的信息与近期记录，提出具体问题。资料不足时会明确保留判断。')));wrapper.append(empty);}
    else{
      if(review.is_demo)wrapper.append(node('p','review-demo-note',t('演示结果，未调用模型。以下判断、评分与问题均为预置示例。')));
      if(review.evidence_profile){const basis=review.evidence_profile;wrapper.append(node('p','review-data-note',t('评议依据：Agent 自述 {reports} 条、用户补充 {answers} 条；模型未独立执行验证。',{reports:basis.agent_reports||0,answers:basis.user_statements||0})));}
      const meta=node('div','review-detail-meta');meta.append(verdictBadge(review),node('span','',`${localDate(review.created_at)} · ${review.model||t('模型未标明')}`),node('span','',t('依据 {count} 条 · 置信度{confidence}',{count:Number(review.evidence_count)||0,confidence:t(CONFIDENCE[review.confidence]||'待判断')})));wrapper.append(meta);
      if(review.is_stale)wrapper.append(node('p','review-stale-notice',t('评议之后已有新记录或补充背景。这份结论可能已过期，可重新评议更新判断。')));
      wrapper.append(node('h3','review-headline',review.headline||t('项目评议')),node('p','review-summary',review.summary||t('本轮没有提供概述。')));
      const dimensionSection=node('section','review-section');dimensionSection.append(node('h3','',t('五维评价')));const dimensionList=node('div','review-dimension-list');dimensionsFor(review).forEach(dimension=>{const item=node('article','review-dimension');const dimensionHeading=node('div','review-dimension-heading');dimensionHeading.append(node('strong','',dimensionLabel(dimension)),node('span',`review-score${dimension.score==null?' unknown':''}`,scoreText(dimension.score)));item.append(dimensionHeading,node('p','',dimension.reason||t('本轮未说明判断理由。')),evidenceRefs(dimension.evidence_ids));dimensionList.append(item);});dimensionSection.append(dimensionList);wrapper.append(dimensionSection);
      const observations=node('div','review-observation-grid');observations.append(infoList(t('已知 / 已有依据'),review.strengths,t('本轮尚未识别可明确列出的依据。')),infoList(t('未证实的假设'),review.assumptions,t('本轮未单独列出假设，不代表已全部证实。')),infoList(t('尚未覆盖的盲点'),review.blind_spots,t('本轮未列出具体盲点，可继续补充背景。')));wrapper.append(observations);
      const questions=node('section','review-section');questions.append(node('h3','',t('六类追问')));const questionList=Array.isArray(review.questions)?review.questions:[];
      const assigned=new Set();QUESTION_GROUPS.forEach((group,index)=>{const groupNode=node('div','review-question-group');const groupHeading=node('h4');groupHeading.append(node('span','',String(index+1).padStart(2,'0')),document.createTextNode(t(group.label)));groupNode.append(groupHeading);const entries=questionList.filter((question,i)=>{const match=group.aliases.includes(String(question.kind||'').toLowerCase());if(match)assigned.add(i);return match;});if(!entries.length)groupNode.append(node('p','review-section-empty',t('本轮未提出此类问题。')));entries.forEach(question=>groupNode.append(questionNode(question)));questions.append(groupNode);});
      const other=questionList.filter((_,index)=>!assigned.has(index));if(other.length){const group=node('div','review-question-group');group.append(node('h4','',t('其他追问')));other.forEach(question=>group.append(questionNode(question)));questions.append(group);}wrapper.append(questions);
      const actions=node('section','review-section');actions.append(node('h3','',t('优先下一步')));const actionList=node('div','review-action-list');if(!Array.isArray(review.next_actions)||!review.next_actions.length)actionList.append(node('p','review-section-empty',t('本轮尚未给出可执行的下一步。')));else review.next_actions.forEach(action=>{const item=node('article','review-action');const priority=['high','medium','low'].includes(action.priority)?action.priority:'medium';item.append(node('span',`review-priority ${priority}`,{high:t('优先'),medium:t('随后'),low:t('可选')}[priority]));const body=node('div');body.append(node('strong','',action.action||textOf(action)),node('p','',action.reason||''));item.append(body);actionList.append(item);});actions.append(actionList);wrapper.append(actions);
      if(Array.isArray(cached?.evidence)&&cached.evidence.length){const disclosure=node('details','review-source-evidence');disclosure.append(node('summary','',t('查看本次采集依据（{count} 条）',{count:cached.evidence.length})));cached.evidence.slice(0,60).forEach(evidence=>{const item=node('div','review-source-item');item.append(node('strong','',evidence.id||evidence.kind||t('依据')),node('p','',String(evidence.text||'').slice(0,1500)));disclosure.append(item);});wrapper.append(disclosure);}
    }
    byId('review-detail-content').replaceChildren(wrapper);[...wrapper.querySelectorAll('details')].forEach((el,index)=>{el.open=disclosureState.get(el.dataset.i18nDisclosure||String(index))||false;});byId('review-answer-panel').hidden=false;renderAnswerHistory();updateButtons();
  }
  function questionNode(question){const article=node('article','review-question');article.append(node('div','review-question-title',`${question.id?question.id+' · ':''}${question.question||t('问题未提供')}`));if(question.why)article.append(node('p','',t('为什么问：{reason}',{reason:question.why})));if(question.suggested_check)article.append(node('p','review-question-check',t('建议核验：{check}',{check:question.suggested_check})));article.append(evidenceRefs(question.evidence_ids));return article;}
  function renderAnswerHistory(){
    const answers=detailsCache.get(selectedId)?.answers;const holder=byId('review-answer-history');
    if(!Array.isArray(answers)||!answers.length){holder.replaceChildren();return;}
    const wasOpen=holder.querySelector('details')?.open||false;const details=node('details','review-previous-answers');details.open=wasOpen;details.append(node('summary','',t('先前补充（{count} 条）',{count:answers.length})));answers.forEach(answer=>{const item=node('article','review-previous-answer');item.append(node('time','',localDate(answer.created_at)),node('p','',answer.text||answer.answer||''));details.append(item);});holder.replaceChildren(details);
  }
  function selectProject(id){
    if(selectedId)drafts.set(selectedId,byId('review-answer').value);
    selectedId=String(id);initialSelectionDone=true;byId('review-answer').value=drafts.get(selectedId)||'';byId('review-draft-status').textContent=byId('review-answer').value?t('草稿已保留'):'';
    detailFingerprint='';renderProjectList();renderDetail(true);fetchProjectDetail(selectedId);
  }
  async function fetchProjectDetail(id){const request=++detailRequest;try{const data=await api(`/api/reviews/project?id=${encodeURIComponent(id)}`);detailsCache.set(String(id),data);if(request===detailRequest&&selectedId===String(id))renderDetail();}catch{/* Detail enrichment is optional; the latest review remains usable. */}}
  function errorList(job){const errors=job.errors;if(!errors)return [];if(Array.isArray(errors))return errors.map(error=>typeof error==='string'?error:(error.error||error.message||textOf(error))).filter(Boolean);if(typeof errors==='object')return Object.values(errors).map(textOf).filter(Boolean);return [String(errors)];}
  function historicalGaps(jobs){
    // The backend reports a batch failure count, not per-project outcomes.
    // Preserve unresolved coverage without asserting which unknown item failed.
    const newerCoverage=new Set(),groups=[];
    jobs.forEach((job,index)=>{
      const ids=Array.isArray(job.project_ids)?[...new Set(job.project_ids.map(String))]:[];
      const failed=Number(job.failed)||0;
      if(index>0&&(failed>0||job.status==='failed')){
        const unresolved=ids.filter(id=>!newerCoverage.has(id)&&!(reviewFor(id)&&jobTimestamp({created_at:reviewFor(id).created_at})>=jobTimestamp(job)));
        if(unresolved.length)groups.push({job,project_ids:unresolved,failed});
        else if(!ids.length)groups.push({job,project_ids:[],failed,unknown:true});
      }
      ids.forEach(id=>newerCoverage.add(id));
    });
    return groups;
  }
  function jobCounts(job){const completed=Number(job.completed)||0,failed=Number(job.failed)||0,total=Number(job.total)||0;return t('已处理 {processed} / {total} · 成功 {completed} · 失败 {failed}',{processed:Math.min(total,completed+failed),total,completed,failed});}
  function jobStatusText(job){const failed=Number(job.failed)||0;return {queued:t('已排队'),running:t('正在评议'),completed:failed?t('本轮已结束，部分项目失败'):t('本轮评议完成'),failed:t('本轮已结束，部分项目失败')}[job.status]||t('任务状态待确认');}
  function jobPanelBody(job){
    const body=node('div','review-job-body');
    const errors=errorList(job);if(errors.length)body.append(node('p','review-job-errors',errors.slice(0,3).join('；')));
    if(Number(job.failed)>0||job.status==='failed'){
      const retry=node('button','review-inline-button',t('重试此批评议'));
      retry.disabled=!provider.configured||allJobs().some(jobActive);
      retry.addEventListener('click',()=>startReview(Array.isArray(job.project_ids)&&job.project_ids.length===1?{project_id:job.project_ids[0]}:{all:true}));body.append(retry);
    }
    return body;
  }
  function disclosedJob(job,current=false){
    const id=String(job.id||job.job_id);let disclosure=jobDisclosureNodes.get(id);
    if(!disclosure){disclosure=node('details','review-job-completion');disclosure.open=false;jobDisclosureNodes.set(id,disclosure);}
    const failed=Number(job.failed)>0||job.status==='failed';disclosure.className=`review-job-completion${current?' latest':''}${failed&&current?' has-failures':''}`;
    const summary=node('summary');const label=node('span','review-job-status',`${current?t('最近任务 · '):''}${jobStatusText(job)}`);summary.append(label,node('span','review-job-counts',jobCounts(job)),node('span','review-job-disclosure-hint',t('展开 / 收起')));
    const body=jobPanelBody(job);body.prepend(node('p','review-job-time',t('发起于 {time}',{time:localDate(job.created_at)})));
    disclosure.replaceChildren(summary,body);return disclosure;
  }
  function renderJobs(){
    const jobs=allJobs();const key=JSON.stringify([I.getLocale(),jobs,Boolean(provider.configured),reviews.map(review=>[review.project_id,review.created_at])]);if(key===jobRenderKey)return;jobRenderKey=key;
    const root=byId('reviews-jobs');if(!jobs.length){root.replaceChildren();return;}
    const current=jobs[0];const currentId=String(current.id||current.job_id),history=jobs.filter(job=>String(job.id||job.job_id)!==currentId);
    const primary=jobActive(current)?node('div','review-job active'):disclosedJob(current,true);
    if(jobActive(current)){
      const top=node('div','review-job-top');top.append(node('span','review-job-status',t('当前任务 · {status}',{status:jobStatusText(current)})),node('span','',jobCounts(current)));primary.append(top);
      if(Number(current.failed)>0){const partialKey='errors:'+currentId;let partial=jobDisclosureNodes.get(partialKey);if(!partial){partial=node('details','review-current-errors');jobDisclosureNodes.set(partialKey,partial);}partial.replaceChildren(node('summary','',t('本轮已出现 {count} 项失败，查看原因',{count:Number(current.failed)})),jobPanelBody(current));primary.append(partial);}
    }
    const children=[primary];
    const otherActive=history.filter(jobActive);if(otherActive.length)children.push(node('p','review-other-active',t('另有 {count} 个评议任务仍在进行，详情见先前任务。',{count:otherActive.length})));
    const gaps=historicalGaps(jobs);
    if(gaps.length){if(!unresolvedNoticeNode)unresolvedNoticeNode=node('details','review-unresolved');const notice=unresolvedNoticeNode;notice.replaceChildren();
      const unresolvedIds=[...new Set(gaps.flatMap(group=>group.project_ids))];
      notice.append(node('summary','',unresolvedIds.length?t('历史失败待核对：{count} 个项目未被后续任务覆盖',{count:unresolvedIds.length}):t('有历史失败尚无法按项目核对')));
      gaps.forEach(group=>{const item=node('div','review-unresolved-group');const names=group.project_ids.map(id=>projectFor(id)?.name||id);item.append(node('p','',t('先前批次失败 {count} 项。',{count:group.failed})+(names.length?t('尚未再次覆盖：')+names.join(I.getLocale()==='en'?', ':'、'):t('该批次未提供项目清单。'))));notice.append(item);});
      notice.append(node('p','review-unresolved-explanation',t('服务仅提供整批失败数，未标明逐项目结果；此处保留未再次覆盖的范围，需结合项目评议记录核对。')));children.push(notice);
    }
    if(history.length){
      if(!jobHistoryNode){jobHistoryNode=node('details','review-job-history');jobHistoryNode.open=false;}
      const summary=node('summary','',t('先前任务（{count}）',{count:history.length}));const content=node('div','review-job-history-content');
      history.forEach(job=>content.append(disclosedJob(job)));jobHistoryNode.replaceChildren(summary,content);children.push(jobHistoryNode);
    }
    root.replaceChildren(...children);
  }
  async function syncReviews(){
    if(requestBusy)return;requestBusy=true;byId('reviews-refresh').disabled=true;
    try{const data=await api('/api/reviews');reviews=Array.isArray(data.reviews)?data.reviews:[];provider=data.provider&&typeof data.provider==='object'?data.provider:{configured:false};rubric=Array.isArray(data.rubric)?data.rubric:[];serverJobs=Array.isArray(data.jobs)?data.jobs:[];setError('');renderProvider();renderProjectList();renderJobs();renderDetail();serverJobs.filter(jobActive).forEach(job=>startPolling(String(job.id||job.job_id)));if(!initialSelectionDone&&projects.length)selectProject(String(projects[0].id));}
    catch(error){setError(error.message||t('暂时无法连接本机评议服务，已保留上次结果。'));}
    finally{requestBusy=false;byId('reviews-refresh').disabled=false;}
  }
  async function startReview(payload){
    if(pendingSubmit||provider.is_demo)return;const projectId=payload.project_id?String(payload.project_id):null;
    pendingSubmit=projectId||'all';updateButtons();
    try{const data=await api('/api/reviews',{method:'POST',headers:{'Content-Type':'application/json','X-Workhub-Request':'1'},body:JSON.stringify(payload)});const jobId=String(data.job_id||data.id||'');if(!jobId)throw new Error(t('服务没有返回评议任务编号，请刷新检查任务状态。'));const job={...data,id:jobId,_received_at:new Date().toISOString(),status:data.status||'queued',project_ids:data.project_ids||(projectId?[projectId]:projects.map(project=>project.id))};liveJobs.set(jobId,job);setError('');if(payload.answer&&projectId){if(selectedId===projectId&&byId('review-answer').value.trim()===payload.answer){byId('review-answer').value='';byId('review-draft-status').textContent=t('已提交补充');}drafts.set(projectId,'');fetchProjectDetail(projectId);}renderJobs();renderProjectList();renderDetail();startPolling(jobId);}
    catch(error){setError(error.message||t('未能发起评议，请稍后重试。'));}
    finally{pendingSubmit=null;updateButtons();}
  }
  function startPolling(jobId){if(!jobId||pollTimers.has(jobId))return;pollTimers.set(jobId,setTimeout(()=>pollJob(jobId),1200));}
  async function pollJob(jobId){
    pollTimers.delete(jobId);
    try{const data=await api(`/api/reviews/job?id=${encodeURIComponent(jobId)}`);const job=data.job&&typeof data.job==='object'?data.job:data;liveJobs.set(jobId,{...job,id:job.id||jobId});pollFailures.delete(jobId);renderJobs();renderProjectList();updateButtons();if(jobActive(job))startPolling(jobId);else{await syncReviews();if(selectedId)fetchProjectDetail(selectedId);}}
    catch(error){const failures=(pollFailures.get(jobId)||0)+1;pollFailures.set(jobId,failures);if(failures<3)startPolling(jobId);else setError(t('评议状态暂时无法读取：{message} 点击重新连接后可继续检查，后台任务可能仍在运行。',{message:error.message}));}
  }
  byId('review-all-button').addEventListener('click',()=>startReview({all:true}));
  byId('review-answer').addEventListener('input',()=>{if(selectedId)drafts.set(selectedId,byId('review-answer').value);byId('review-draft-status').textContent=byId('review-answer').value?t('草稿已保留'):'';updateButtons();});
  byId('review-answer-submit').addEventListener('click',()=>{const answer=byId('review-answer').value.trim();if(selectedId&&answer)startReview({project_id:selectedId,answer});});
  byId('review-search').addEventListener('input',renderProjectList);byId('review-status-filter').addEventListener('change',renderProjectList);
  byId('reviews-refresh').addEventListener('click',()=>{syncReviews();if(selectedId)fetchProjectDetail(selectedId);});
  byId('reviews-retry').addEventListener('click',()=>{pollFailures.clear();syncReviews();allJobs().filter(jobActive).forEach(job=>startPolling(String(job.id||job.job_id)));});
  window.addEventListener('workhub:state',event=>{projects=Array.isArray(event.detail.projects)?event.detail.projects:[];renderProjectList();updateButtons();if(!initialSelectionDone&&projects.length)selectProject(String(projects[0].id));else renderDetail();});
  window.addEventListener('workhub:page',event=>{if(event.detail.page==='reviews')syncReviews();});
  window.WorkhubReviews={openProject(id){switchPage('reviews');selectProject(String(id));syncReviews();}};
  if(typeof state!=='undefined'&&Array.isArray(state.projects))projects=state.projects;
  I.onChange(()=>{detailFingerprint='';jobRenderKey='';renderProvider();renderProjectList();renderJobs();renderDetail(true);if(byId('review-answer').value)byId('review-draft-status').textContent=t('草稿已保留');else byId('review-draft-status').textContent=I.translateKnown(byId('review-draft-status').textContent);if(lastReviewError)setError(I.translateKnown(lastReviewError));});
  syncReviews();setInterval(()=>{if(!document.hidden&&!byId('reviews-page').hidden)syncReviews();},5000);
})();
