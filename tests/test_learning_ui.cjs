'use strict';
// Temporary cards and DOM only: no real acknowledgements, projects or models.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.join(__dirname,'..'),html=fs.readFileSync(path.join(root,'static/index.html'),'utf8');
const nodes=new Map(),windowEvents=new Map(),documentEvents=new Map(),requests=[],intervals=[],copied=[],toasts=[];
class Element{
 constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.attributes={};this.dataset={};this.handlers={};this.value='';this.hidden=false;this.disabled=false;this.checked=false;this.open=false;this.scrollTop=0;this._text='';this.className='';}
 set id(value){this._id=value;nodes.set(value,this);}get id(){return this._id;}
 set textContent(value){this._text=String(value);this.children=[];}get textContent(){return this._text+this.children.map(child=>child.textContent??String(child)).join('');}
 set innerHTML(value){throw new Error('Learning content must never use innerHTML');}
 append(...children){this.children.push(...children);}replaceChildren(...children){this._text='';this.children=[...children];}
 setAttribute(key,value){this.attributes[key]=String(value);}getAttribute(key){return this.attributes[key]??null;}
 addEventListener(name,callback){this.handlers[name]=callback;}
 querySelectorAll(selector){const result=[];for(const child of this.children){if(child.tagName?.toLowerCase()===selector||selector.startsWith('.')&&child.className?.split(' ').includes(selector.slice(1)))result.push(child);if(child.querySelectorAll)result.push(...child.querySelectorAll(selector));}return result;}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 select(){}remove(){}
}
for(const [,tag,id] of html.matchAll(/<([\w-]+)[^>]*\bid="([^"]+)"[^>]*>/g)){const node=new Element(tag);node.id=id;}
nodes.get('learning-page').hidden=true;
const unsafe='字面内容 <script>doNotExecute()</script> & <img src=x onerror=run()>\n 保留换行';
const base={project_id:'p1',project_name:'Fictional Project A',card_key:'cache',revision:1,title:'缓存为何要有版本',concept:'缓存',explanation:unsafe,implementation:'读取 revision 后，再决定是否复用内容。',terms:[{term:'revision <b>literal</b>',definition:'内容版本'}],steps:['先取当前版本','再比较缓存版本'],example:'const value = "<script>literal</script>";',self_check:['如果内容更新，旧确认还能沿用吗？'],sources:[{path:'src/example.js',line:12,symbol:'readCard',note:'虚构来源'}],status:'pending',understood:false,needs_review:false,acknowledgement:null};
let cards=[{...base,id:'c1'},{...base,id:'c2',project_id:'p2',project_name:'Fictional Project B',title:'读取文件',status:'understood',understood:true},{...base,id:'c3',card_key:'review',title:'需要复习的卡片',revision:2,status:'needs_review',understood:true,needs_review:true,previous_understood_revision:1}];
const projects=[{id:'p1',name:'Fictional Project A'},{id:'p2',name:'Fictional Project B'}];
let postError=null,listError=false,demo=false,delayedPost=null;
const clone=value=>JSON.parse(JSON.stringify(value));
function status(card){return card.needs_review?'needs_review':card.status;}
function stats(list){return {total:list.length,pending:list.filter(c=>status(c)==='pending').length,understood:list.filter(c=>status(c)==='understood').length,needs_review:list.filter(c=>status(c)==='needs_review').length};}
function response(data,status=200){return {ok:status>=200&&status<300,status,json:async()=>clone(data)};}
const document={hidden:false,body:new Element('body'),documentElement:{lang:''},title:'',getElementById:id=>nodes.get(id),createElement:tag=>new Element(tag),querySelectorAll(){return [];},addEventListener(name,callback){documentEvents.set(name,callback);},execCommand(){return true;}};
const context={document,window:{addEventListener(name,callback){windowEvents.set(name,callback);},showToast:text=>toasts.push(text)},location:{href:'http://127.0.0.1:8899/'},localStorage:{getItem(){return null;},setItem(){}},navigator:{clipboard:{writeText:async value=>copied.push(value)}},URL,URLSearchParams,Intl,Date,console,AbortSignal:{timeout(){}},setTimeout(){return 1;},clearTimeout(){},setInterval(callback,ms){intervals.push({callback,ms});},state:{projects},switchPage(page){nodes.get('learning-page').hidden=page!=='learning';windowEvents.get('workhub:page')?.({detail:{page}});},fetch:async(url,options={})=>{
 requests.push({url,...options});assert(url.startsWith('/api/learning'),'learning UI must not call models or other APIs');
 if(options.method==='POST'){
  if(delayedPost)await delayedPost;
  if(postError)return response({error:'safe server error <script>literal</script>'},postError);
  const body=JSON.parse(options.body),card=cards.find(c=>c.id===body.card_id);
  if(body.revision!==card.revision)return response({error:'revision changed'},409);
  card.understood=body.understood;card.needs_review=false;card.status=body.understood?'understood':'pending';card.acknowledgement=body.understood?{revision:body.revision,created_at:'2026-11-09T00:00:00Z'}:null;return response({card});
 }
 if(url.startsWith('/api/learning/card')){const id=new URL(url,context.location.href).searchParams.get('id');return response({card:cards.find(c=>c.id===id),history:[{revision:1,title:'初版'},{revision:2,title:'新版'}]});}
 if(listError)return response({error:'temporary unavailable'},503);
 const params=new URL(url,context.location.href).searchParams;let list=cards.filter(c=>!params.get('project_id')||c.project_id===params.get('project_id'));
 if(params.get('q'))list=list.filter(c=>JSON.stringify(c).includes(params.get('q')));const scoped=stats(list);
 if(params.get('status'))list=list.filter(c=>status(c)===params.get('status'));
 return response({cards:list,projects,stats:scoped,global_stats:stats(cards),is_demo:demo});
}};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(root,'static/i18n.js'),'utf8'),context);vm.runInContext(fs.readFileSync(path.join(root,'static/learning.js'),'utf8'),context);
const flush=async()=>{for(let i=0;i<9;i++)await new Promise(setImmediate);};
const countPosts=()=>requests.filter(r=>r.method==='POST').length;
const checkbox=nodes.get('learning-understood');
async function toggle(value,event={isTrusted:true}){checkbox.checked=value;await checkbox.handlers.change(event);await flush();}
(async()=>{
 await flush();assert.equal(requests.length,1,'only one initial list request for the sidebar count');assert.equal(countPosts(),0);assert.equal(nodes.get('nav-learning-count').textContent,'2');
 const timer=intervals.find(i=>i.ms===15000);assert(timer);const initial=requests.length;timer.callback();await flush();assert.equal(requests.length,initial,'hidden learning page is not polled');
 nodes.get('learning-page').hidden=false;windowEvents.get('workhub:page')({detail:{page:'learning'}});await flush();
 assert.equal(nodes.get('learning-detail-title').textContent,base.title);assert(!checkbox.checked);assert(!checkbox.disabled);assert(nodes.get('learning-detail-body').textContent.includes(unsafe));assert.equal(nodes.get('learning-detail-body').querySelectorAll('a').length,0);assert.equal(countPosts(),0,'opening and reading must never acknowledge');
 await toggle(true,{isTrusted:false});assert.equal(countPosts(),0,'synthetic dispatch must not acknowledge');assert(!checkbox.checked);
 const detail=nodes.get('learning-detail-body'),sameNode=detail.children[0];detail.scrollTop=123;detail.querySelector('details').open=true;
 await context.window.WorkhubLearning.refresh();await flush();assert.strictEqual(detail.children[0],sameNode,'unchanged polls keep existing detail nodes');assert.equal(detail.scrollTop,123);assert(detail.querySelector('details').open);
 const sameList=nodes.get('learning-card-list').children[0];cards[0]={...cards[0],agent:'another-agent',run_id:'new-provenance-run',updated_at:'2026-11-09T04:00:00Z'};
 await context.window.WorkhubLearning.refresh();await flush();assert.strictEqual(detail.children[0],sameNode,'metadata-only updates preserve mounted knowledge and text selection');assert.strictEqual(nodes.get('learning-card-list').children[0],sameList,'metadata-only updates preserve list button keyboard focus');assert.equal(detail.scrollTop,123);assert(detail.querySelector('details').open);
 nodes.get('learning-project-filter').value='p1';nodes.get('learning-search').value='缓存';const beforeLanguage=requests.length;
 context.window.WorkhubI18n.setLocale('en');assert.equal(requests.length,beforeLanguage);assert.equal(nodes.get('learning-project-filter').value,'p1');assert.equal(nodes.get('learning-search').value,'缓存');assert.equal(nodes.get('learning-detail-title').textContent,base.title);assert(detail.textContent.includes(unsafe));assert(detail.textContent.includes('Concept in plain language'));assert.equal(detail.scrollTop,123);assert(detail.querySelector('details').open);assert(!checkbox.checked);
 detail.querySelectorAll('button')[0].handlers.click();await flush();assert.equal(copied.at(-1),'src/example.js:12 · readCard');
 nodes.get('learning-search').value='';context.window.WorkhubI18n.setLocale('zh-CN');
 const beforeAcknowledgement=detail.children[0];await toggle(true);assert(checkbox.checked);assert.strictEqual(detail.children[0],beforeAcknowledgement,'acknowledgement-only changes do not rebuild knowledge');assert.equal(countPosts(),1);const posted=requests.find(r=>r.method==='POST');assert.equal(posted.url,'/api/learning/ack');assert.equal(posted.headers['X-Workhub-Request'],'1');assert.equal(posted.headers['Content-Type'],'application/json');assert.deepEqual(JSON.parse(posted.body),{card_id:'c1',revision:1,understood:true});
 await toggle(false);assert(!checkbox.checked);assert.equal(countPosts(),2);assert.equal(cards[0].understood,false);
 postError=500;await toggle(true);assert(!checkbox.checked,'failed saves restore the previous checkbox');assert(!nodes.get('learning-error').hidden);assert(nodes.get('learning-error-raw').textContent.includes('<script>literal</script>'));assert.equal(nodes.get('learning-detail-title').textContent,base.title);postError=null;
 cards[0]={...cards[0],revision:2,explanation:'新版内容',status:'needs_review',needs_review:true,understood:false,previous_understood_revision:1};listError=true;
 await toggle(true);assert(!checkbox.checked,'a stale revision must never become checked');assert(checkbox.disabled,'a failed conflict refresh must keep the stale acknowledgement disabled');const conflictPosts=countPosts();await toggle(true);assert.equal(countPosts(),conflictPosts);listError=false;await context.window.WorkhubLearning.refresh();await flush();assert(!checkbox.disabled);assert(detail.textContent.includes('新版内容'));assert(nodes.get('learning-ack-message').textContent.includes('最新版本'));assert.equal(JSON.parse(requests.filter(r=>r.method==='POST').at(-1).body).revision,1);assert.equal(cards[0].understood,false);
 const beforeConfirm=countPosts();context.window.WorkhubI18n.setLocale('en');await flush();assert.equal(countPosts(),beforeConfirm);assert(!checkbox.checked);assert(nodes.get('learning-ack-message').textContent.includes('latest revision'));
 await toggle(true);assert(checkbox.checked);assert.equal(JSON.parse(requests.filter(r=>r.method==='POST').at(-1).body).revision,2);
 nodes.get('learning-project-filter').value='p2';await nodes.get('learning-project-filter').handlers.change();await flush();assert.equal(nodes.get('learning-stat-total').textContent,'1');assert.equal(nodes.get('nav-learning-count').textContent,'1','global sidebar count does not shrink with project filters');assert.equal(nodes.get('learning-project-filter').value,'p2');
 nodes.get('learning-project-filter').value='';nodes.get('learning-status-filter').value='needs_review';await nodes.get('learning-status-filter').handlers.change();await flush();assert.equal(nodes.get('learning-card-list').querySelectorAll('button').length,1);context.window.WorkhubLearning.selectCard('c3');await flush();assert(!checkbox.checked,'old acknowledgements do not apply to a revised card even if understood was true');assert(detail.textContent.includes('新版')||nodes.get('learning-detail-meta').textContent.includes('1'));
 const retained=detail.children[0];listError=true;await context.window.WorkhubLearning.refresh();await flush();assert.strictEqual(detail.children[0],retained);assert(!nodes.get('learning-error').hidden);assert.equal(nodes.get('learning-status-filter').value,'needs_review');listError=false;
 demo=true;await context.window.WorkhubLearning.refresh();await flush();assert(checkbox.disabled);assert(nodes.get('learning-ack-status').textContent.includes('read-only'));const demoPosts=countPosts();await toggle(true);assert.equal(countPosts(),demoPosts);assert(!checkbox.checked);
 const visibleRequests=requests.length;document.hidden=true;timer.callback();await flush();assert.equal(requests.length,visibleRequests,'background tabs are not polled');document.hidden=false;documentEvents.get('visibilitychange')();await flush();assert(requests.length>visibleRequests);
 const app=fs.readFileSync(path.join(root,'static/app.js'),'utf8');assert(app.includes("'archives','learning'"));assert(app.includes("learning:'边做边学'"));assert(html.includes('id="nav-learning-count"'));assert(html.includes('src="/learning.js"'));assert(html.includes('href="/learning.css"'));
 console.log('Learning UI checks passed: read-only loading, manual acknowledgement/uncheck, revision conflicts, failure rollback, literal XSS-safe content, source copying, unchanged polls/scroll, language/filter state, global counts, visible-page polling and demo safeguards.');
})().catch(error=>{console.error(error);process.exitCode=1;});
