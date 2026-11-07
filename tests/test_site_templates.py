"""Bilingual template behavior using temporary sites and a small DOM fixture."""
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class Tree(HTMLParser):
    """Read the actual template DOM; no browser or private data is required."""
    def __init__(self, text):
        super().__init__()
        self.root = {"tag": "document", "attrs": {}, "children": []}
        self.stack = [self.root]
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "children": []}
        self.stack[-1]["children"].append(node)
        if tag not in {"meta", "link", "input", "br", "hr", "img"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index]["tag"] == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, text):
        self.stack[-1]["children"].append(text)


HARNESS = r'''
const fs=require('fs'),vm=require('vm');
const f=JSON.parse(fs.readFileSync(0,'utf8'));
class Element{
 constructor(tag,attrs={}){this.tagName=tag;this.attrs={...attrs};this.children=[];this.own='';this.open=false;this._hidden=Object.hasOwn(attrs,'hidden');}
 get textContent(){return this.own+this.children.map(c=>typeof c==='string'?c:c.textContent).join('');}
 set textContent(v){this.own=String(v??'');this.children=[];}
 append(...children){this.children.push(...children);}
 prepend(...children){this.children.unshift(...children);}
 replaceChildren(...children){this.own='';this.children=[...children];}
 setAttribute(k,v){this.attrs[k]=String(v);}
 removeAttribute(k){delete this.attrs[k];}
 getAttribute(k){return this.attrs[k]??null;}
 get dataset(){const d={};for(const [k,v]of Object.entries(this.attrs))if(k.startsWith('data-'))d[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=v;return d;}
 get className(){return this.attrs.class||'';}set className(v){this.attrs.class=v;}
 get classList(){return{toggle:(c,on)=>{const s=new Set(this.className.split(/\s+/).filter(Boolean));if(on===undefined)on=!s.has(c);if(on)s.add(c);else s.delete(c);this.className=[...s].join(' ');},add:c=>{this.className+=(this.className?' ':'')+c;}};}
 get value(){if(this._value!==undefined)return this._value;if(this.tagName==='select'){const o=this.children.filter(c=>c.tagName==='option');return(o.find(c=>Object.hasOwn(c.attrs,'selected'))||o[0])?.value||'';}return this.attrs.value||'';}
 set value(v){this._value=String(v);}
 get hidden(){return this._hidden;}set hidden(v){this._hidden=Boolean(v);}
 get lang(){return this.attrs.lang||'';}set lang(v){this.attrs.lang=v;}
 showModal(){this.open=true;}close(){this.open=false;}
}
function inflate(n){if(typeof n==='string')return n;const e=new Element(n.tag,n.attrs);e.children=n.children.map(inflate);return e;}
const root=inflate(f.tree);
const all=(r)=>[r,...r.children.filter(c=>c instanceof Element).flatMap(all)];
const matches=(e,s)=>s[0]==='#'?e.attrs.id===s.slice(1):s[0]==='.'?e.className.split(/\s+/).includes(s.slice(1)):s[0]==='['?Object.hasOwn(e.attrs,s.slice(1,-1)):e.tagName===s;
function query(s,r=root){const parts=s.split(' ');let list=[r];for(const p of parts)list=list.flatMap(n=>all(n).filter(e=>matches(e,p)));return list;}
const document={documentElement:query('html')[0],body:query('body')[0],referrer:f.referrer||'',title:'',
 getElementById:id=>query('#'+id)[0]||null,querySelector:s=>query(s)[0]||null,querySelectorAll:s=>query(s),createElement:t=>new Element(t),createTextNode:s=>String(s)};
const stored=new Map(f.saved?[['workhub-language',f.saved]]:[]);
const localStorage={getItem:k=>{if(f.blockStorage)throw Error('blocked');return stored.get(k)||null;},setItem:(k,v)=>{if(f.blockStorage)throw Error('blocked');stored.set(k,v);}};
const events={},parent={};
const window={location:{origin:'https://fixture.example'},addEventListener:(k,fn)=>(events[k]??=[]).push(fn)};
window.parent=f.standalone?window:parent;
const sandbox={window,document,localStorage,URL,console,fetch:async()=>({ok:!f.fail,json:async()=>f.data})};
vm.runInNewContext(f.code,sandbox);
const get=id=>document.getElementById(id);
const snapshot=()=>({language:document.documentElement.lang,label:get('language-select').value,search:get('q').value,sort:get('sort')?.value||null,
 status:query('.template-status')[0].textContent,heading:query('header h1')[0].textContent,body:document.body.textContent,
 content:(get('list')||get('grid')).textContent,lead:get('lead')?.textContent||'',open:get('dlg').open,
 close:get(f.mode==='library'?'dClose':'close').textContent,placeholder:get('q').getAttribute('placeholder'),saved:stored.get('workhub-language')||null,
 selected:(get('tabs')||get('cats'))?.children.filter(c=>c instanceof Element&&c.attrs['aria-pressed']==='true').map(c=>c.textContent)||get('cat')?.value});
(async()=>{
 await new Promise(setImmediate);
 const initial=snapshot();
 if(f.action==='preserve'){
  get('q').value='needle';get('q').oninput();
  if(f.mode==='brief'){get('cat').value='1';get('cat').onchange();}
  else{(get('tabs')||get('cats')).children[1].onclick();}
  if(f.mode==='library'){get('sort').value='date-asc';get('sort').onchange();}
  const target=f.mode==='brief'?get('lead'):(get('list')||get('grid')).children[0];target.onclick();
  get('language-select').value='zh-CN';get('language-select').onchange();
 }else if(f.action==='messages'){
  const send=e=>events.message.forEach(fn=>fn(e));
  get('language-select').value='zh-CN';get('language-select').onchange();
  send({source:parent,origin:'https://untrusted.example',data:{type:'workhub:language',language:'en'}});const rejectedOrigin=snapshot().language;
  send({source:{},origin:'https://fixture.example',data:{type:'workhub:language',language:'en'}});const rejectedSource=snapshot().language;
  send({source:parent,origin:'null',data:{type:'workhub:language',language:'en'}});const rejectedOpaque=snapshot().language;
  send({source:parent,origin:'http://127.0.0.1:8888',data:{type:'workhub:language',language:'fr'}});const rejectedLocale=snapshot().language;
  send({source:parent,origin:'http://127.0.0.1:8888',data:{type:'workhub:language',language:'en'}});
  const loopback=snapshot().language;
  send({source:parent,origin:'https://fixture.example',data:{type:'workhub:language',language:'zh-CN'}});
  const sameOrigin=snapshot().language;
  send({source:parent,origin:'https://referrer.example',data:{type:'workhub:language',language:'en'}});
  console.log(JSON.stringify({initial,final:snapshot(),rejectedOrigin,rejectedSource,rejectedOpaque,rejectedLocale,loopback,sameOrigin}));return;
 }else if(f.action==='storage'){
  events.storage.forEach(fn=>fn({key:'workhub-language',newValue:'zh-CN'}));
 }
 console.log(JSON.stringify({initial,final:snapshot()}));
})().catch(e=>{console.error(e.stack);process.exitCode=1});
'''


@unittest.skipUnless(shutil.which("node"), "Node.js is required for template runtime behavior checks")
class BilingualTemplatesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="workhub-template-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        home = self.directory / "home"
        home.mkdir()
        self.env = {**os.environ, "HOME": str(home), "AGENT_WORKHUB_HOME": str(self.directory / "unused-data")}

    def generated(self, mode):
        output = self.directory / ("site-" + mode)
        completed = subprocess.run([sys.executable, str(ROOT / "scripts/site_templates.py"), "create",
                                    "--template", mode, "--output", str(output), "--name", "项目原文",
                                    "--description", "描述原文", "--language", "en"],
                                   capture_output=True, text=True, env=self.env, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return output

    def runtime(self, mode, **options):
        output = self.generated(mode)
        payload = {"mode":mode,"code":(output / "runtime.js").read_text(),
                   "tree":Tree((output / "index.html").read_text()).root,
                   "data":{"name":"项目原文","description":"描述原文","is_demo":False,"items":[
                       {"id":"one","title":"标题原文一","summary":"needle 原文","category":"分类甲","source":"来源原文","date":"2026-01-01","tags":["标签原文"]},
                       {"id":"two","title":"标题原文二","summary":"other 原文","category":"分类甲","source":"来源原文","date":"2026-01-02"},
                       {"id":"three","title":"标题原文三","summary":"needle 原文","category":"分类乙","source":"来源原文","date":"2026-01-03"}]},
                   **options}
        result = subprocess.run(["node", "-e", HARNESS], input=json.dumps(payload), capture_output=True,
                                text=True, env=self.env, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_three_layouts_start_in_english_and_preserve_content_and_filters(self):
        for mode in ("radar", "library", "brief"):
            with self.subTest(mode=mode):
                result = self.runtime(mode, action="preserve")
                self.assertEqual(result["initial"]["language"], "en")
                self.assertEqual(result["initial"]["heading"], "项目原文")
                self.assertEqual(result["initial"]["close"], "Close")
                self.assertEqual(result["initial"]["placeholder"], "Search titles, summaries, or tags…")
                final = result["final"]
                self.assertEqual(final["language"], "zh-CN")
                self.assertEqual(final["search"], "needle")
                self.assertTrue(final["open"], "language changes must keep the active detail dialog open")
                self.assertEqual(final["close"], "关闭")
                self.assertEqual(final["saved"], "zh-CN")
                content = final["lead"] + final["content"]
                self.assertIn("标题原文一", content)
                self.assertNotIn("标题原文二", content)
                self.assertNotIn("标题原文三", content)
                if mode == "library":
                    self.assertEqual(final["sort"], "date-asc")

    def test_parent_messages_require_parent_source_and_trusted_origin(self):
        result = self.runtime("radar", action="messages", referrer="https://referrer.example/page")
        for field in ("rejectedOrigin", "rejectedSource", "rejectedOpaque", "rejectedLocale"):
            self.assertEqual(result[field], "zh-CN", field)
        self.assertEqual(result["loopback"], "en", "no-referrer loopback previews remain supported")
        self.assertEqual(result["sameOrigin"], "zh-CN")
        self.assertEqual(result["final"]["language"], "en", "the actual referrer origin is permitted")

    def test_saved_locale_and_blocked_storage_have_predictable_fallbacks(self):
        saved = self.runtime("library", saved="zh-CN")
        self.assertEqual(saved["initial"]["language"], "zh-CN")
        blocked = self.runtime("brief", blockStorage=True, action="preserve")
        self.assertEqual(blocked["initial"]["language"], "en")
        self.assertEqual(blocked["final"]["language"], "zh-CN")
        self.assertIsNone(blocked["final"]["saved"])

    def test_storage_event_changes_ui_without_translating_project_content(self):
        result = self.runtime("radar", action="storage")
        self.assertEqual(result["final"]["language"], "zh-CN")
        self.assertEqual(result["final"]["heading"], "项目原文")
        self.assertIn("标题原文一", result["final"]["body"])

    def test_load_failure_is_localized(self):
        result = self.runtime("brief", fail=True, action="storage")
        self.assertIn("Content could not be loaded", result["initial"]["status"])
        self.assertIn("内容加载失败", result["final"]["status"])

    def test_standalone_page_rejects_parent_language_messages(self):
        result = self.runtime("radar", standalone=True, action="messages", referrer="https://referrer.example/page")
        self.assertEqual(result["initial"]["language"], "en")
        self.assertEqual(result["final"]["language"], "zh-CN")
        self.assertEqual(result["loopback"], "zh-CN")

    def test_empty_english_site_has_localized_identity_and_empty_state(self):
        result = self.runtime("library", data={"items":[],"is_demo":False})
        self.assertEqual(result["initial"]["heading"], "Knowledge library")
        self.assertIn("Your workspace is ready", result["initial"]["content"])
        self.assertIn("Local workspace", result["initial"]["body"])


if __name__ == "__main__":
    unittest.main()
