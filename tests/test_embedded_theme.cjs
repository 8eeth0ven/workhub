'use strict';
// The child bridge is tested with enum messages and temporary state only.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.join(__dirname,'..'),source=fs.readFileSync(path.join(root,'static/embedded-theme.js'),'utf8');
function runtime({saved=null,blocked=false,configured=null,standalone=false}={}){
 const values=new Map(saved===null?[]:[['workhub-theme',saved]]),attrs=new Map(),events=new Map(),requests=[],writes=[];
 const parent={postMessage(data,origin){requests.push({data:JSON.parse(JSON.stringify(data)),origin});}};
 const window={parent,addEventListener(name,callback){events.set(name,callback);}};
 if(standalone)window.parent=window;
 Object.defineProperty(window,'location',{get(){return Object.freeze({href:'http://127.0.0.1:43201/page.html'});},set(){throw Error('theme bridge must not navigate');}});
 const document={readyState:'loading',referrer:'https://untrusted-referrer.example/page',currentScript:{getAttribute(name){return name==='data-workhub-parent-origin'?configured:null;}},documentElement:{getAttribute:name=>attrs.get(name)||null,setAttribute(name,value){attrs.set(name,value);}},addEventListener(name,callback){events.set('document:'+name,callback);},getElementById(){throw Error('must not touch business DOM');}};
 const localStorage={getItem(key){assert.equal(key,'workhub-theme');if(blocked)throw Error('blocked');return values.get(key)||null;},setItem(key,value){assert.equal(key,'workhub-theme');writes.push(value);if(blocked)throw Error('blocked');values.set(key,value);}};
 const context={window,document,localStorage,URL,console,fetch(){throw Error('no business/network request is permitted');}};
 vm.createContext(context);vm.runInContext(source,context);
 const send=(origin,value,sourceWindow=parent,type='workhub:theme')=>events.get('message')({origin,source:sourceWindow,data:{type,theme:value}});
 return {api:window.WorkhubEmbeddedTheme,attrs,events,requests,writes,values,send,parent,window,context};
}
{
 const r=runtime({saved:'sand'});assert.equal(r.api.getTheme(),'sand');assert.equal(r.attrs.get('data-workhub-theme'),'sand');assert.deepEqual(r.requests,[{data:{type:'workhub:theme-request'},origin:'http://127.0.0.1:8787'}]);r.events.get('document:DOMContentLoaded')();assert.equal(r.requests.at(-1).data.type,'workhub:theme-ready');
 r.send('http://127.0.0.1:8787','orange',{});r.send('http://localhost:8787','orange');r.send('http://127.0.0.1:8899','orange');r.send('https://untrusted-referrer.example','orange');r.send('null','orange');r.send('http://127.0.0.1:8787','arbitrary-css-value');assert.equal(r.api.getTheme(),'sand');
 for(const theme of ['moss','fog','graphite','sand','orange','teal','rose','indigo']){r.send('http://127.0.0.1:8787',theme);assert.equal(r.attrs.get('data-workhub-theme'),theme);assert.equal(r.values.get('workhub-theme'),theme);}
 const requests=r.requests.length;r.events.get('pageshow')();assert.equal(r.requests.length,requests+1);assert.equal(r.requests.at(-1).origin,'http://127.0.0.1:8787');
 const count=r.requests.length;vm.runInContext(source,r.context);assert.equal(r.requests.length,count,'duplicate inclusion must not register or request twice');
 r.events.get('storage')({key:'workhub-theme',newValue:'rose'});assert.equal(r.api.getTheme(),'rose');r.events.get('storage')({key:'workhub-theme',newValue:null});assert.equal(r.api.getTheme(),'moss');
}
{
 const r=runtime({blocked:true});r.send('http://127.0.0.1:8787','orange');assert.equal(r.api.getTheme(),'orange');
 const local=runtime({configured:'http://localhost:8899'});local.send('http://localhost:8899','teal');assert.equal(local.api.getTheme(),'teal');assert(local.requests.some(item=>item.origin==='http://localhost:8899'));
 for(const configured of ['https://remote.example','http://user:pass@127.0.0.1:8899','http://127.0.0.1:8899/not-an-origin','javascript:invalid']){const rejected=runtime({configured});assert.equal(rejected.requests.length,1);rejected.send('http://127.0.0.1:8899','orange');assert.equal(rejected.api.getTheme(),'moss');}
 const standalone=runtime({standalone:true,saved:'indigo'});standalone.send('http://127.0.0.1:8787','orange');assert.equal(standalone.api.getTheme(),'indigo');assert.equal(standalone.requests.length,0);
}
const css=fs.readFileSync(path.join(root,'static/embedded-theme.css'),'utf8').replace(/\/\*[\s\S]*?\*\//g,'');
const allowed=new Set(['color','background-color','border-color','outline-color','color-scheme','scrollbar-color']);
for(const match of css.matchAll(/(?:^|[;{])\s*([\w-]+)\s*:/g)){const property=match[1];assert(property.startsWith('--')||allowed.has(property),'embedded compatibility must remain color-only: '+property);}
assert(css.includes(':not([data-workhub-native])'),'native apps must bypass generic overrides');assert(!/(?:fill|stroke|filter|font-size|line-height)\s*:/.test(css),'media and typography must not be recolored/resized through presentation rules');
console.log('Embedded theme checks passed: fixed-parent trust, explicit loopback configuration, invalid/source/referrer rejection, eight palettes, ready/request handshake, duplicate guard, no navigation/business DOM/network, and color-only CSS.');
