'use strict';
// Dependency-free behavioral checks; no servers, user data, or model calls.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'..','static','i18n.js'),'utf8');
function runtime({stored=null,unavailable=false}={}){
  const values=new Map(stored===null?[]:[['workhub-language',stored]]),messages=[],listeners=new Map();
  const label={textContent:'',getAttribute:()=> '项目空间'};
  const input={attributes:{placeholder:'查找项目网站…'},getAttribute:()=> '查找项目网站…',setAttribute(name,value){this.attributes[name]=value;}};
  const selector={value:'',addEventListener(name,callback){listeners.set('select:'+name,callback);}};
  const frame={tagName:'IFRAME',src:'http://127.0.0.1:43210/site/index.html',contentWindow:{postMessage(payload,origin){messages.push({payload:JSON.parse(JSON.stringify(payload)),origin});}}};
  const document={documentElement:{lang:''},title:'',querySelectorAll(query){if(query==='[data-i18n]')return [label];if(query==='[data-i18n-placeholder]')return [input];if(query==='iframe')return [frame];return [];},getElementById:id=>id==='workhub-language'?selector:null,addEventListener(name,callback){listeners.set('document:'+name,callback);}};
  const window={addEventListener(name,callback){listeners.set('window:'+name,callback);}};
  const localStorage={getItem(key){assert.equal(key,'workhub-language');if(unavailable)throw new Error('storage blocked');return values.get(key)||null;},setItem(key,value){assert.equal(key,'workhub-language');if(unavailable)throw new Error('storage blocked');values.set(key,value);}};
  const context={window,document,localStorage,location:{href:'http://127.0.0.1:8899/'},URL,Intl,Date,console};
  vm.createContext(context);vm.runInContext(source,context);
  return {api:window.WorkhubI18n,document,selector,label,input,frame,messages,values,listeners};
}
{
  const r=runtime({stored:'en'}),i=r.api;
  assert.equal(i.getLocale(),'en');assert.equal(r.document.documentElement.lang,'en');assert.equal(r.document.title,'Workhub · Project workspace');assert.equal(r.label.textContent,'Project spaces');assert.equal(r.input.attributes.placeholder,'Find project websites…');
  const keys=Object.keys(i.dictionaries.en).sort();assert.deepEqual(keys,Object.keys(i.dictionaries['zh-CN']).sort());assert(keys.length>300);
  for(const key of keys){const tokens=value=>[...value.matchAll(/\{(\w+)\}/g)].map(match=>match[1]).sort();assert.deepEqual(tokens(i.dictionaries.en[key]),tokens(i.dictionaries['zh-CN'][key]),key);}
  assert.equal(i.t('查看项目 {name} 的详情',{name:'实际项目 <script>原文</script>'}),'View details for 实际项目 <script>原文</script>');assert.equal(i.t('unknown interface key'),'unknown interface key');
  let changes=0;const unsubscribe=i.onChange(()=>changes++);const originalSource=r.frame.src;i.setLocale('zh-CN');assert.equal(changes,1);assert.equal(r.label.textContent,'项目空间');assert.equal(r.values.get('workhub-language'),'zh-CN');assert.equal(r.frame.src,originalSource);
  assert.deepEqual(r.messages.at(-1),{payload:{type:'workhub:language',language:'zh-CN'},origin:'http://127.0.0.1:43210'});unsubscribe();i.setLocale('en');assert.equal(changes,1);
  r.listeners.get('document:load')({target:r.frame});assert.equal(r.messages.at(-1).payload.language,'en');
  assert.match(i.formatDate('2026-11-07T12:00:00Z',{month:'short'}),/Nov/);assert.equal(i.formatDate('invalid'),'Time not recorded');assert.equal(i.formatRelative(-2,'minute'),'2 minutes ago');
  i.setLocale('unknown-locale');assert.equal(i.getLocale(),'zh-CN');assert.match(i.formatDate('2026-11-07T12:00:00Z',{month:'short'}),/11月/);
  i.setLocale('en');assert.equal(i.translateKnown('已排队'),'Queued');assert.equal(i.errorMessage('服务器原始错误'),'Server details: 服务器原始错误');
}
{
  const r=runtime({unavailable:true});assert.equal(r.api.getLocale(),'zh-CN');assert.doesNotThrow(()=>r.api.setLocale('en'));assert.equal(r.api.getLocale(),'en');assert.equal(r.selector.value,'en');
  const unknown=runtime({stored:'unrecognized'});assert.equal(unknown.api.getLocale(),'zh-CN');
}
console.log('i18n checks passed: dictionary parity, placeholders, literal interpolation, persistence, unavailable storage, unknown locale, dates, callbacks, and exact-origin iframe messages.');
