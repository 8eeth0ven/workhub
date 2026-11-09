'use strict';
// Behavior and color accessibility checks without user data, network, or a browser.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.join(__dirname,'..'),source=fs.readFileSync(path.join(root,'static/theme.js'),'utf8');
function runtime({saved=null,blocked=false}={}){
 const values=new Map(saved===null?[]:[['workhub-theme',saved]]),attributes=new Map(),listeners=new Map(),messages=[],changes=[],storageReads=[],storageWrites=[];
 const selector={value:'moss',addEventListener(name,callback){listeners.set('select:'+name,callback);}};
 const frame={src:'http://127.0.0.1:43001/index.html',contentWindow:{postMessage(data,origin){messages.push({data:JSON.parse(JSON.stringify(data)),origin});}}};
 const state={search:'keep this search',draft:' 未提交内容 \n',project:'project-original'};
 const document={readyState:'loading',documentElement:{setAttribute(name,value){attributes.set(name,value);}},querySelectorAll(query){assert.equal(query,'iframe');return [frame,{src:'about:blank'}];},getElementById(id){assert.equal(id,'workhub-theme');return selector;},addEventListener(name,callback){listeners.set('document:'+name,callback);}};
 const window={WorkhubI18n:{onChange(callback){listeners.set('language',callback);}},addEventListener(name,callback){listeners.set('window:'+name,callback);},dispatchEvent(event){changes.push(JSON.parse(JSON.stringify(event.detail)));}};
 const localStorage={getItem(key){storageReads.push(key);assert.equal(key,'workhub-theme');if(blocked)throw Error('blocked');return values.get(key)??null;},setItem(key,value){storageWrites.push({key,value});assert.equal(key,'workhub-theme');if(blocked)throw Error('blocked');values.set(key,value);}};
 const context={window,document,localStorage,location:{href:'http://127.0.0.1:8787/'},URL,console,CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},fetch(){throw Error('theme changes must not make network requests');}};
 vm.createContext(context);vm.runInContext(source,context);
 return {api:window.WorkhubTheme,attributes,listeners,messages,changes,values,frame,selector,state,storageReads,storageWrites};
}
{
 const r=runtime({saved:'fog'});assert.equal(r.attributes.get('data-workhub-theme'),'fog','saved palette must apply before DOMContentLoaded');assert.equal(r.api.getTheme(),'fog');assert.equal(r.storageWrites.length,0,'restoring a preference is read-only');
 r.listeners.get('document:DOMContentLoaded')();assert.equal(r.selector.value,'fog');const frameSource=r.frame.src,snapshot=JSON.stringify(r.state);
 let subscribed=0;const unsubscribe=r.api.onChange(()=>subscribed++);assert.equal(r.api.setTheme('sand'),'sand');assert.equal(subscribed,1);assert.equal(r.frame.src,frameSource);assert.equal(JSON.stringify(r.state),snapshot);assert.equal(r.selector.value,'sand');assert.equal(r.values.get('workhub-theme'),'sand');
 assert.deepEqual(r.messages.at(-1),{data:{type:'workhub:theme',theme:'sand'},origin:'http://127.0.0.1:43001'});assert.deepEqual(r.changes.at(-1),{theme:'sand',source:'api'});
 r.listeners.get('document:load')({target:{...r.frame,tagName:'IFRAME'}});assert.equal(r.messages.at(-1).data.theme,'sand');r.listeners.get('language')();assert.equal(r.selector.value,'sand');
 unsubscribe();const beforeWrites=r.storageWrites.length;r.listeners.get('window:storage')({key:'workhub-theme',newValue:'graphite'});assert.equal(r.api.getTheme(),'graphite');assert.equal(subscribed,1);assert.equal(r.storageWrites.length,beforeWrites,'cross-tab sync must not loop by writing storage');
 r.listeners.get('window:storage')({key:'workhub-language',newValue:'en'});assert.equal(r.api.getTheme(),'graphite');assert.equal(r.api.setTheme('arbitrary-css-value'),'moss');assert.equal(r.attributes.get('data-workhub-theme'),'moss');
 r.listeners.get('window:storage')({key:'workhub-theme',newValue:null});assert.equal(r.api.getTheme(),'moss');
}
{
 const blocked=runtime({blocked:true});assert.equal(blocked.api.getTheme(),'moss');assert.doesNotThrow(()=>blocked.api.setTheme('fog'));assert.equal(blocked.attributes.get('data-workhub-theme'),'fog');assert.equal(runtime({saved:'invalid'}).api.getTheme(),'moss');
}
function luminance(hex){const rgb=hex.replace('#','').match(/../g).map(value=>parseInt(value,16)/255).map(value=>value<=0.04045?value/12.92:((value+.055)/1.055)**2.4);return .2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2];}
function contrast(a,b){const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
const css=fs.readFileSync(path.join(root,'static/design-system.css'),'utf8');
for(const name of ['moss','fog','graphite','sand']){
 const block=css.match(new RegExp(':root\\[data-workhub-theme="'+name+'"\\]\\s*\\{([^}]+)\\}'))?.[1];assert(block,name+' palette must be canonical');const tokens=Object.fromEntries([...block.matchAll(/(--wh-[\w-]+):\s*(#[a-f0-9]{6})/gi)].map(match=>[match[1],match[2]]));
 for(const [text,background]of [['--wh-ink','--wh-bg'],['--wh-muted','--wh-bg'],['--wh-ink','--wh-surface'],['--wh-muted','--wh-surface'],['--wh-on-accent','--wh-accent'],['--wh-on-accent','--wh-accent-hover'],['--wh-sidebar-ink','--wh-sidebar-bg'],['--wh-sidebar-muted','--wh-sidebar-bg'],['--wh-sidebar-ink','--wh-sidebar-active'],['--wh-sidebar-muted','--wh-sidebar-active']]){
  const ratio=contrast(tokens[text],tokens[background]);assert(ratio>=4.5,`${name} ${text}/${background} contrast ${ratio.toFixed(2)} < 4.5`);
 }
 assert(!/--wh-(font|radius|space|text|title)[\w-]*:/.test(block),'palette must not change geometry or type');
}
console.log('Theme checks passed: pre-paint restore, enum validation, persistence, blocked storage, cross-tab sync, unchanged frames/input, exact-origin messages, and four-palette text/button/sidebar contrast.');
