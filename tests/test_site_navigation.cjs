'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const base=path.join(__dirname,'..','static');
const context={window:{}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(base,'site-navigation.js'),'utf8'),context);
const group=context.window.WorkhubSiteNavigation.groupProjects;
const projects=[{id:'notes',name:'Notes',event_count:3},{id:'app',name:'Research app',event_count:0}];
const sites=[{id:'one',project_id:'app',name:'Library',description:'Resources'},{id:'two',project_id:'app',name:'Radar'},{id:'orphan',project_id:'pending',project_name:'Pending project',name:'Pending website'}];
const original=JSON.stringify({projects,sites});
let result=group(projects,sites);
assert.equal(result.length,3);
assert.equal(result[0].project.id,'notes');
assert.equal(result[0].sites.length,0);
assert.equal(result[0].hasWebsite,false);
assert.equal(result[1].sites.length,2);
assert.equal(result[2].project.name,'Pending project');
assert.equal(group(projects,sites,'  NOTES ')[0].sites.length,0);
assert.equal(group(projects,sites,'resources')[0].sites[0].id,'one');
assert.equal(group(projects,sites,'research')[0].sites.length,2);
assert.equal(group(projects,sites,'absent').length,0);
assert.equal(group([],sites).length,2); // Website response can arrive first.
assert.equal(group(projects,[]).length,2);
assert.equal(group([],[]).length,0);
assert.equal(JSON.stringify({projects,sites}),original);

// Exercise the real renderer: an unconnected project opens its existing record,
// while a website still selects the same embedded site. Neither is fabricated.
class Node{
  constructor(tag,className='',text=''){this.tag=tag;this.className=className;this.textContent=text;this.children=[];this.attributes={};this.events={};}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(key,value){this.attributes[key]=value;}
  addEventListener(name,callback){this.events[name]=callback;}
}
const list=new Node('div'),counter=new Node('span'),search={value:''},actions=[];
Object.assign(context,{
  sitesLoaded:true,siteState:{sites},state:{projects},activeSiteId:'one',
  $:selector=>({'#site-list':list,'#site-count':counter,'#site-search':search})[selector],
  element:(tag,className,text)=>new Node(tag,className,text),icon:()=>new Node('span'),
  t:(key,params={})=>key.replace(/\{(\w+)\}/g,(_,name)=>params[name]),
  switchPage:page=>actions.push(['page',page]),openProject:id=>actions.push(['project',id]),selectSite:id=>actions.push(['site',id]),
});
const app=fs.readFileSync(path.join(base,'app.js'),'utf8');
vm.runInContext(app.slice(app.indexOf('function renderSites(){'),app.indexOf('\nfunction siteSource')),context);
context.renderSites();
assert.equal(list.children.length,3);
assert.equal(counter.textContent,'3');
assert.equal(counter.title,'2 个项目 · 3 个网站');
const missing=list.children[0].children[1];
assert(missing.className.includes('site-project-records'));
assert.equal(missing.children[1].children[0].textContent,'尚未接入网站');
assert.equal(missing.children[1].children[1].textContent,'已有工作记录 · 查看详情');
missing.events.click();assert.deepEqual(actions,[['page','records'],['project','notes']]);
const site=list.children[1].children[1];
assert.equal(site.attributes['aria-pressed'],'true');
site.events.click();assert.deepEqual(actions.at(-1),['site','one']);
search.value='nothing';context.renderSites();
assert.equal(list.children[0].textContent,'没有匹配的项目或网站。');
console.log('Project navigation checks passed: all projects, unconnected states, race ordering, search, unchanged source data, records navigation and website selection.');
