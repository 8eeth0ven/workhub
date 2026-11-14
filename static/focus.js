/* Content-first presentation; selecting a project keeps its frame mounted. */
(() => {
  'use strict';
  const root = document.documentElement;
  const i18n = window.WorkhubI18n;
  const button = document.getElementById('focus-toggle');
  if (!button) return;
  let active = false;
  let previousScroll = null;
  let currentPage = document.getElementById('spaces-page')?.hidden === false ? 'spaces' : null;
  let selected = {siteId: null, source: null};

  function hasSelectedFrame() {
    const spaces = document.getElementById('spaces-page');
    const frame = document.getElementById('site-frame');
    if (currentPage !== 'spaces' || !spaces || spaces.hidden || !frame || frame.hidden || !selected.siteId || !selected.source) return false;
    try {
      const source = new URL(selected.source, window.location.href);
      const actual = new URL(frame.getAttribute('src') || frame.src, window.location.href);
      return ['http:', 'https:'].includes(source.protocol) && source.href === actual.href;
    } catch { return false; }
  }

  function render() {
    const label = active ? '恢复工作台界面' : '收起界面并铺满窗口';
    button.setAttribute('data-i18n-aria-label', label);
    button.setAttribute('data-i18n-title', label);
    button.setAttribute('aria-label', i18n ? i18n.t(label) : label);
    button.title = i18n ? i18n.t(label) : label;
    button.setAttribute('aria-expanded', String(!active));
    button.setAttribute('aria-pressed', String(active));
  }

  function enter(options = {}) {
    if (document.documentElement.dataset.workhubSpaceMode === "control") return;
    if (active) return;
    previousScroll = {x: window.scrollX || 0, y: window.scrollY || 0};
    active = true;
    // CSS owns responsive sizing. Do not freeze pre-collapse dimensions or
    // navigate/replace the frame: its application and inputs stay mounted.
    root.classList.add('workhub-focus-mode');
    render();
    if (options.automatic !== true) {
      button.focus({preventScroll: true});
      window.scrollTo({left: 0, top: 0, behavior: 'instant'});
    }
  }

  function exit(options = {}) {
    if (!active) return;
    active = false;
    root.classList.remove('workhub-focus-mode');
    render();
    if (options.restoreScroll !== false && previousScroll) {
      window.scrollTo({left: previousScroll.x, top: previousScroll.y, behavior: 'instant'});
    }
    previousScroll = null;
  }

  function toggle() { if (active) exit(); else enter(); }
  button.addEventListener('click', toggle);
  window.addEventListener('workhub:page', event => {
    const page = event.detail?.page;
    const changed = currentPage !== page;
    currentPage = page;
    if (page !== 'spaces') exit({restoreScroll: false});
    else if (changed && hasSelectedFrame()) enter({automatic: true});
  });
  window.addEventListener('workhub:site', event => {
    const detail = event.detail || {};
    selected = {siteId: detail.siteId || null, source: detail.source || null};
    if (!hasSelectedFrame()) {
      if (currentPage === 'spaces') exit({restoreScroll: false});
      return;
    }
    // A user's expansion survives polling, reloads and language changes.
    // Selecting even the current project is an explicit return to its canvas.
    if (detail.reason === 'select' || detail.reason === 'restore') enter({automatic: true});
  });
  window.addEventListener('keydown', event => { if (active && event.key === 'Escape') exit(); });
  if (i18n) i18n.onChange(render);
  window.WorkhubFocus = {
    enter, exit, toggle,
    isActive: () => active,
  };
  render();
})();
