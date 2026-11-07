/* Shared layout runtime. Project content stays in its original language. */
(() => {
  'use strict';
  const mode = document.body.dataset.template;
  const $ = id => document.getElementById(id);
  const supported = value => value === 'zh-CN' || value === 'en';
  const messages = {
    'zh-CN': {
      language: '界面语言', search: '搜索', searchContent: '搜索内容', placeholder: '搜索标题、摘要、标签…',
      radar: '信息雷达', library: '知识资料库', brief: '分析简报', sources: '来源分布', categories: '分类目录',
      informationStats: '信息统计', informationCategories: '信息分类', informationItems: '信息条目',
      libraryStats: '资料统计', libraryItems: '资料列表', briefStats: '简报统计', outline: '本期目录',
      filterColumn: '按栏目筛选', allColumns: '全部栏目', all: '全部', reset: '重置', close: '关闭', sourceLink: '查看来源 ↗',
      sort: '排序方式', dateDesc: '日期：从新到旧', dateAsc: '日期：从旧到新', titleSort: '标题：A–Z',
      documents: '篇资料', categoryCount: '个分类', tagCount: '个标签', items: '信息条目',
      informationCategoryCount: '信息分类', uniqueSources: '独立来源', themes: '主题标签',
      briefs: '篇简报', columns: '个栏目', topics: '个主题',
      emptyMatch: '没有符合条件的内容，请调整搜索或分类。',
      emptyItems: '这里已经准备好了。将真实内容写入 data.json，开始你的第一个条目。',
      waitingSources: '等待来源', untitled: '未命名', uncategorized: '未分类', unknownSource: '未注明来源',
      view: '查看：{title}', focus: '本期焦点 · {category}', loading: '正在读取本地内容…',
      demo: '版式预览 · 以下为模板演示数据，供选择排版使用',
      local: '本地项目 · 内容由项目 data.json 提供',
      loadError: '内容加载失败。请检查项目 data.json。', invalidItems: '数据格式不正确：items 必须为数组。',
      footerDemo: '模板预览 · {count} 条内容', footerLocal: '本地工作空间 · {count} 条内容'
    },
    en: {
      language: 'Interface language', search: 'Search', searchContent: 'Search content', placeholder: 'Search titles, summaries, or tags…',
      radar: 'Information radar', library: 'Knowledge library', brief: 'Research brief', sources: 'Sources', categories: 'Categories',
      informationStats: 'Information statistics', informationCategories: 'Information categories', informationItems: 'Information items',
      libraryStats: 'Library statistics', libraryItems: 'Library items', briefStats: 'Brief statistics', outline: 'In this issue',
      filterColumn: 'Filter by section', allColumns: 'All sections', all: 'All', reset: 'Reset', close: 'Close', sourceLink: 'View source ↗',
      sort: 'Sort order', dateDesc: 'Date: newest first', dateAsc: 'Date: oldest first', titleSort: 'Title: A–Z',
      documents: 'documents', categoryCount: 'categories', tagCount: 'tags', items: 'Information items',
      informationCategoryCount: 'Categories', uniqueSources: 'Distinct sources', themes: 'Topic tags',
      briefs: 'briefs', columns: 'sections', topics: 'topics',
      emptyMatch: 'No matching content. Try a different search or category.',
      emptyItems: 'Your workspace is ready. Add real content to data.json to create the first item.',
      waitingSources: 'Waiting for sources', untitled: 'Untitled', uncategorized: 'Uncategorized', unknownSource: 'Source not specified',
      view: 'View: {title}', focus: 'In focus · {category}', loading: 'Loading local content…',
      demo: 'Layout preview · The following sample data demonstrates this template',
      local: 'Local project · Content is supplied by the project’s data.json',
      loadError: 'Content could not be loaded. Please check the project’s data.json.', invalidItems: 'Invalid data: items must be an array.',
      footerDemo: 'Template preview · {count} items', footerLocal: 'Local workspace · {count} items'
    }
  };
  const storageKey = 'workhub-language';
  let language = supported(document.documentElement.lang) ? document.documentElement.lang : 'zh-CN';
  try { const saved = localStorage.getItem(storageKey); if (supported(saved)) language = saved; } catch {}
  const t = (key, params = {}) => String(messages[language][key] ?? messages['zh-CN'][key] ?? key)
    .replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? ''));
  const node = (tag, text, cls) => {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (cls) el.className = cls;
    return el;
  };
  const empty = (el, text) => el.replaceChildren(node('p', text, 'state empty'));
  let data = null, items = [], category = null, currentItem = null, failure = null;
  const dialog = $('dlg');
  const status = node('div', '', 'template-status');
  document.body.prepend(status);
  const count = key => new Set(items.map(i => i[key]).filter(Boolean)).size;
  const tags = item => item.tags || [];
  const itemTitle = item => item.title || t('untitled');
  const itemCategory = item => item.category || t('uncategorized');
  const itemSource = item => item.source || t('unknownSource');
  const safeUrl = raw => {
    try { const u = new URL(raw); return ['http:', 'https:'].includes(u.protocol) ? u.href : null; }
    catch { return null; }
  };
  function fillDialog(item, show = true) {
    currentItem = item;
    const title = mode === 'radar' ? 'dt' : mode === 'library' ? 'dTitle' : 'd-title';
    const summary = mode === 'radar' ? 'ds' : mode === 'library' ? 'dSum' : 'd-sum';
    $(title).textContent = itemTitle(item);
    $(summary).textContent = item.summary;
    const meta = `${itemCategory(item)} · ${itemSource(item)} · ${item.date}`;
    if (mode === 'radar') {
      $('dm').textContent = meta;
      $('dg').textContent = tags(item).map(value => '#' + value).join('  ');
    } else if (mode === 'library') {
      $('dCat').textContent = itemCategory(item);
      $('dSrc').textContent = itemSource(item);
      $('dDate').textContent = item.date;
      $('dTags').replaceChildren(...tags(item).map(value => node('span', value)));
      const url = safeUrl(item.url);
      $('dUrlWrap').hidden = !url;
      $('dUrl').removeAttribute('href');
      if (url) { $('dUrl').href = url; $('dUrl').textContent = t('sourceLink'); }
    } else {
      $('d-meta').textContent = meta;
      $('d-tags').textContent = tags(item).map(value => '#' + value).join('  ');
      const url = safeUrl(item.url);
      $('d-link').hidden = !url;
      $('d-link').removeAttribute('href');
      if (url) $('d-link').href = url;
    }
    if (show && !dialog.open) dialog.showModal();
  }
  function clickable(el, item) {
    el.tabIndex = 0;
    el.setAttribute('role', 'button');
    el.setAttribute('aria-label', t('view', {title:itemTitle(item)}));
    el.onclick = () => fillDialog(item);
    el.onkeydown = event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); fillDialog(item); }
    };
    return el;
  }
  function filters() {
    const categories = [null, ...new Set(items.map(i => i.category))];
    if (mode === 'brief') {
      const select = $('cat');
      select.setAttribute('aria-label', t('filterColumn'));
      select.replaceChildren(...categories.map((value, index) => {
        const option = node('option', value === null ? t('allColumns') : value || t('uncategorized'));
        option.value = String(index); return option;
      }));
      select.value = String(Math.max(0, categories.indexOf(category)));
      select.onchange = () => { category = categories[Number(select.value)] ?? null; render(); };
    } else {
      const box = $(mode === 'radar' ? 'tabs' : 'cats');
      box.replaceChildren(...categories.map(value => {
        const total = value === null ? items.length : items.filter(i => i.category === value).length;
        const label = value === null ? t('all') : value || t('uncategorized');
        const button = node('button', `${label}  ${total}`, mode === 'radar' ? 'tab' : '');
        button.classList.toggle('on', value === category);
        button.setAttribute('aria-pressed', String(value === category));
        button.onclick = () => { category = value; filters(); render(); };
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
      ? [[t('items'), items.length], [t('informationCategoryCount'), count('category')], [t('uniqueSources'), count('source')], [t('themes'), totalTags]]
      : [[t('briefs'), items.length], [t('columns'), count('category')], [t('topics'), totalTags]];
    $('stats').replaceChildren(...entries.map(([label, value]) => {
      const el = node(mode === 'radar' ? 'div' : 'span', undefined, mode === 'radar' ? 'stat' : '');
      el.append(node('b', value), node('span', label));
      return el;
    }));
  }
  function render() {
    const query = $('q').value.trim().toLocaleLowerCase(language);
    const visible = items.filter(i => (category === null || i.category === category)
      && [i.title, i.summary, i.source, ...i.tags].join(' ').toLocaleLowerCase(language).includes(query));
    if (mode === 'library') {
      const sort = $('sort').value;
      visible.sort((a, b) => sort === 'title' ? itemTitle(a).localeCompare(itemTitle(b), language)
        : a.date.localeCompare(b.date) * (sort === 'date-asc' ? 1 : -1));
    }
    const box = $(mode === 'radar' ? 'list' : 'grid');
    box.replaceChildren();
    if (mode === 'brief') { $('lead').replaceChildren(); $('toc').replaceChildren(); $('empty').hidden = true; }
    if (!visible.length) empty(box, t(items.length ? 'emptyMatch' : 'emptyItems'));
    visible.forEach((item, index) => {
      if (mode === 'brief') $('toc').append(clickable(node('li', itemTitle(item)), item));
      const card = clickable(node('article', undefined, 'card'), item);
      const meta = node('p', `${itemCategory(item)} · ${itemSource(item)} · ${item.date}`, 'meta');
      const label = node(mode === 'library' ? 'div' : 'p', itemCategory(item), 'cat');
      const heading = node(mode === 'library' ? 'h4' : 'h3', itemTitle(item));
      const body = node('p', item.summary);
      const tagRow = node('p', undefined, 'tags');
      item.tags.forEach(value => tagRow.append(node('span', value, 'tag')));
      if (mode === 'library') card.append(label, heading, body, meta);
      else card.append(meta, heading, body, tagRow);
      if (mode === 'brief' && index === 0) {
        const lead = $('lead');
        lead.append(node('p', t('focus', {category:itemCategory(item)}), 'meta'), node('h2', itemTitle(item)), node('p', item.summary, 'sum'), tagRow);
        clickable(lead, item);
      } else box.append(card);
    });
    if (mode === 'radar') {
      const sources = new Map();
      visible.forEach(i => sources.set(i.source, (sources.get(i.source) || 0) + 1));
      $('src').replaceChildren(...[...sources].sort((a,b) => b[1]-a[1]).map(([source, number]) => {
        const li = node('li'); li.append(node('span', source || t('unknownSource')), node('b', number)); return li;
      }));
      if (!sources.size) empty($('src'), t('waitingSources'));
    }
  }
  function applyLanguage(value, persist = true) {
    if (!supported(value)) return;
    language = value;
    document.documentElement.lang = language;
    try { if (persist) localStorage.setItem(storageKey, language); } catch {}
    document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll('[data-i18n-aria]').forEach(el => { el.setAttribute('aria-label', t(el.dataset.i18nAria)); });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => { el.setAttribute('placeholder', t(el.dataset.i18nPlaceholder)); });
    $('language-select').value = language;
    status.textContent = failure ? t(failure) : !data ? t('loading') : t(data.is_demo === true ? 'demo' : 'local');
    if (data) {
      const heading = document.querySelector('header h1');
      heading.textContent = data.name || t(mode);
      document.title = data.name || t(mode);
      const intro = document.querySelector('header p');
      intro.textContent = data.description || '';
      intro.hidden = !data.description;
      const foot = document.querySelector('footer');
      if (foot) foot.textContent = t(data.is_demo === true ? 'footerDemo' : 'footerLocal', {count:items.length});
      filters(); stats(); render();
      if (currentItem && dialog.open) fillDialog(currentItem, false);
    } else {
      document.querySelector('header h1').textContent = t(mode);
      document.title = t(mode);
      document.querySelector('header p').hidden = true;
    }
  }
  function trustedParentMessage(event) {
    if (window.parent === window || event.source !== window.parent || !event.data || event.data.type !== 'workhub:language' || !supported(event.data.language)) return;
    let trusted = false;
    try {
      const origin = new URL(event.origin);
      if (!['http:', 'https:'].includes(origin.protocol)) return;
      const sameOrigin = origin.origin === window.location.origin;
      let referrerOrigin = '';
      try { referrerOrigin = document.referrer ? new URL(document.referrer).origin : ''; } catch {}
      const loopback = ['127.0.0.1', 'localhost', '[::1]', '::1'].includes(origin.hostname);
      trusted = sameOrigin || origin.origin === referrerOrigin || loopback;
    } catch { return; }
    if (trusted) applyLanguage(event.data.language);
  }
  window.addEventListener('message', trustedParentMessage);
  window.addEventListener('storage', event => {
    if (event.key === storageKey && supported(event.newValue)) applyLanguage(event.newValue, false);
  });
  $('language-select').onchange = () => applyLanguage($('language-select').value);
  $(mode === 'library' ? 'dClose' : 'close').onclick = () => dialog.close();
  $('q').oninput = render;
  if ($('sort')) $('sort').onchange = render;
  if ($('go')) $('go').onclick = render;
  if ($('reset')) $('reset').onclick = () => { $('q').value = ''; category = null; filters(); render(); };
  async function load() {
    try {
      const response = await fetch('./data.json', {cache:'no-store'});
      if (!response.ok) throw new Error('loadError');
      const incoming = await response.json();
      if (!incoming || !Array.isArray(incoming.items)) throw new Error('invalidItems');
      data = incoming;
      items = data.items.map((item, index) => ({id:String(item.id ?? index), title:String(item.title ?? ''), summary:String(item.summary ?? ''), category:String(item.category ?? ''), source:String(item.source ?? ''), url:String(item.url ?? ''), date:String(item.date ?? ''), tags:Array.isArray(item.tags) ? item.tags.map(String) : []}));
      status.classList.toggle('demo', data.is_demo === true);
      if ($('loading')) $('loading').hidden = true;
      if ($('app')) $('app').hidden = false;
      applyLanguage(language, false);
    } catch (error) {
      failure = error.message === 'invalidItems' ? 'invalidItems' : 'loadError';
      status.classList.add('error');
      if ($('loading')) $('loading').hidden = true;
      applyLanguage(language, false);
    }
  }
  applyLanguage(language, false);
  load();
})();
