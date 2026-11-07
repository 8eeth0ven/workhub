/* Shared, dependency-free data contract for all three Workhub layouts. */
(() => {
  'use strict';
  const mode = document.body.dataset.template;
  const $ = id => document.getElementById(id);
  const node = (tag, text, cls) => {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (cls) el.className = cls;
    return el;
  };
  const empty = (el, text) => el.replaceChildren(node('p', text, 'state empty'));
  let data, items = [], category = '全部';
  const dialog = $(mode === 'radar' ? 'dlg' : mode === 'library' ? 'dlg' : 'dlg');
  const count = key => new Set(items.map(i => i[key]).filter(Boolean)).size;
  const tags = item => item.tags || [];
  const safeUrl = raw => {
    try { const u = new URL(raw); return ['http:', 'https:'].includes(u.protocol) ? u.href : null; }
    catch { return null; }
  };
  function open(item) {
    const title = mode === 'radar' ? 'dt' : mode === 'library' ? 'dTitle' : 'd-title';
    const summary = mode === 'radar' ? 'ds' : mode === 'library' ? 'dSum' : 'd-sum';
    $(title).textContent = item.title;
    $(summary).textContent = item.summary;
    const meta = `${item.category} · ${item.source} · ${item.date}`;
    if (mode === 'radar') {
      $('dm').textContent = meta;
      $('dg').textContent = tags(item).map(t => '#' + t).join('  ');
    } else if (mode === 'library') {
      $('dCat').textContent = item.category;
      $('dSrc').textContent = item.source;
      $('dDate').textContent = item.date;
      $('dTags').replaceChildren(...tags(item).map(t => node('span', t)));
      const url = safeUrl(item.url);
      $('dUrlWrap').hidden = !url;
      $('dUrl').removeAttribute('href');
      if (url) { $('dUrl').href = url; $('dUrl').textContent = '查看来源 ↗'; }
    } else {
      $('d-meta').textContent = meta;
      $('d-tags').textContent = tags(item).map(t => '#' + t).join('  ');
      const url = safeUrl(item.url);
      $('d-link').hidden = !url;
      $('d-link').removeAttribute('href');
      if (url) $('d-link').href = url;
    }
    dialog.showModal();
  }
  function clickable(el, item) {
    el.tabIndex = 0;
    el.setAttribute('role', 'button');
    el.setAttribute('aria-label', '查看：' + item.title);
    el.onclick = () => open(item);
    el.onkeydown = event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(item); }
    };
    return el;
  }
  function filters() {
    const categories = ['全部', ...new Set(items.map(i => i.category))];
    if (mode === 'brief') {
      const select = $('cat');
      select.setAttribute('aria-label', '按栏目筛选');
      select.replaceChildren(...categories.map(c => {
        const option = node('option', c === '全部' ? '全部栏目' : c);
        option.value = c; return option;
      }));
      select.onchange = () => { category = select.value; render(); };
    } else {
      const box = $(mode === 'radar' ? 'tabs' : 'cats');
      box.replaceChildren(...categories.map(c => {
        const n = c === '全部' ? items.length : items.filter(i => i.category === c).length;
        const button = node('button', `${c}  ${n}`, mode === 'radar' ? 'tab' : '');
        button.classList.toggle('on', c === category);
        button.setAttribute('aria-pressed', String(c === category));
        button.onclick = () => { category = c; filters(); render(); };
        return button;
      }));
    }
  }
  function stats() {
    const totalTags = new Set(items.flatMap(tags)).size;
    if (mode === 'library') {
      $('stItems').textContent = items.length;
      $('stCats').textContent = count('category');
      $('stTags').textContent = totalTags;
      return;
    }
    const entries = mode === 'radar'
      ? [['信息条目', items.length], ['信息分类', count('category')], ['独立来源', count('source')], ['主题标签', totalTags]]
      : [['篇简报', items.length], ['个栏目', count('category')], ['个主题', totalTags]];
    $('stats').replaceChildren(...entries.map(([label, value]) => {
      const el = node(mode === 'radar' ? 'div' : 'span', undefined, mode === 'radar' ? 'stat' : '');
      el.append(node('b', value), node('span', label));
      return el;
    }));
  }
  function render() {
    const query = $('q').value.trim().toLocaleLowerCase();
    let visible = items.filter(i => (category === '全部' || i.category === category)
      && [i.title, i.summary, i.source, ...i.tags].join(' ').toLocaleLowerCase().includes(query));
    if (mode === 'library') {
      const sort = $('sort').value;
      visible.sort((a, b) => sort === 'title' ? a.title.localeCompare(b.title, 'zh')
        : (a.date.localeCompare(b.date)) * (sort === 'date-asc' ? 1 : -1));
    }
    const box = $(mode === 'radar' ? 'list' : 'grid');
    box.replaceChildren();
    if (mode === 'brief') { $('lead').replaceChildren(); $('toc').replaceChildren(); $('empty').hidden = true; }
    if (!visible.length) empty(box, items.length ? '没有符合条件的内容，请调整搜索或分类。' : '这里已经准备好了。将真实内容写入 data.json，开始你的第一个条目。');
    visible.forEach((item, index) => {
      if (mode === 'brief') {
        const entry = clickable(node('li', item.title), item);
        $('toc').append(entry);
      }
      const card = clickable(node('article', undefined, 'card'), item);
      const meta = node('p', `${item.category} · ${item.source} · ${item.date}`, 'meta');
      const label = node(mode === 'library' ? 'div' : 'p', item.category, 'cat');
      const heading = node(mode === 'library' ? 'h4' : 'h3', item.title);
      const body = node('p', item.summary);
      const tagRow = node('p', undefined, 'tags');
      item.tags.forEach(t => tagRow.append(node('span', t, 'tag')));
      if (mode === 'library') card.append(label, heading, body, meta);
      else card.append(meta, heading, body, tagRow);
      if (mode === 'brief' && index === 0) {
        const lead = $('lead');
        lead.append(node('p', '本期焦点 · ' + item.category, 'meta'), node('h2', item.title), node('p', item.summary, 'sum'), tagRow);
        clickable(lead, item);
      } else box.append(card);
    });
    if (mode === 'radar') {
      const sources = new Map();
      visible.forEach(i => sources.set(i.source, (sources.get(i.source) || 0) + 1));
      $('src').replaceChildren(...[...sources].sort((a,b) => b[1]-a[1]).map(([source, number]) => {
        const li = node('li'); li.append(node('span', source), node('b', number)); return li;
      }));
      if (!sources.size) empty($('src'), '等待来源');
    }
  }
  async function load() {
    const status = node('div', '正在读取本地内容…', 'template-status');
    document.body.prepend(status);
    try {
      const response = await fetch('./data.json', {cache:'no-store'});
      if (!response.ok) throw new Error('HTTP ' + response.status);
      data = await response.json();
      if (!Array.isArray(data.items)) throw new Error('items 必须为数组');
      items = data.items.map((i, n) => ({id:String(i.id ?? n), title:String(i.title ?? '未命名'), summary:String(i.summary ?? ''), category:String(i.category || '未分类'), source:String(i.source || '未注明来源'), url:String(i.url || ''), date:String(i.date || ''), tags:Array.isArray(i.tags) ? i.tags.map(String) : []}));
      status.textContent = data.is_demo === true ? '版式预览 · 以下为模板演示数据，供选择排版使用' : '本地项目 · 内容由项目 data.json 提供';
      status.classList.toggle('demo', data.is_demo === true);
      document.querySelector('header h1').textContent = data.name || {radar:'信息雷达',library:'知识资料库',brief:'分析简报'}[mode];
      document.title = data.name || document.querySelector('header h1').textContent;
      const intro = document.querySelector('header p') || node('p');
      intro.textContent = data.description || '';
      if (!intro.parentElement) document.querySelector('header').append(intro);
      const foot = document.querySelector('footer');
      if (foot) foot.textContent = `${data.is_demo === true ? 'WORKHUB TEMPLATE PREVIEW' : 'LOCAL WORKSPACE'} · ${items.length} 条内容`;
      if ($('loading')) $('loading').hidden = true;
      if ($('app')) $('app').hidden = false;
      filters(); stats(); render();
      $('q').setAttribute('aria-label', '搜索内容');
      $('q').oninput = render;
      if ($('sort')) { $('sort').setAttribute('aria-label', '排序方式'); $('sort').onchange = render; }
      if ($('go')) $('go').onclick = render;
      if ($('reset')) $('reset').onclick = () => { $('q').value = ''; category = '全部'; $('cat').value = category; render(); };
      $(mode === 'library' ? 'dClose' : 'close').onclick = () => dialog.close();
    } catch (error) {
      status.textContent = '内容加载失败：' + error.message + '。请检查项目 data.json。';
      status.classList.add('error');
      if ($('loading')) $('loading').hidden = true;
    }
  }
  load();
})();
