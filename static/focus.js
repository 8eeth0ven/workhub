/* Temporary presentation mode; the existing frame fills the available viewport. */
(() => {
  'use strict';
  const root = document.documentElement;
  const i18n = window.WorkhubI18n;
  const button = document.getElementById('focus-toggle');
  if (!button) return;
  let active = false;
  let previousScroll = null;

  function render() {
    const label = active ? '恢复工作台界面' : '收起界面并铺满窗口';
    button.setAttribute('data-i18n-aria-label', label);
    button.setAttribute('data-i18n-title', label);
    button.setAttribute('aria-label', i18n ? i18n.t(label) : label);
    button.title = i18n ? i18n.t(label) : label;
    button.setAttribute('aria-expanded', String(!active));
    button.setAttribute('aria-pressed', String(active));
  }

  function enter() {
    if (active) return;
    previousScroll = {x: window.scrollX || 0, y: window.scrollY || 0};
    active = true;
    // CSS owns responsive sizing. Do not freeze pre-collapse dimensions or
    // navigate/replace the frame: its application and inputs stay mounted.
    root.classList.add('workhub-focus-mode');
    render();
    button.focus({preventScroll: true});
    window.scrollTo({left: 0, top: 0, behavior: 'instant'});
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
  window.addEventListener('workhub:page', () => exit({restoreScroll: false}));
  window.addEventListener('keydown', event => { if (active && event.key === 'Escape') exit(); });
  if (i18n) i18n.onChange(render);
  window.WorkhubFocus = {
    enter, exit, toggle,
    isActive: () => active,
  };
  render();
})();
