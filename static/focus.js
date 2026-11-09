/* Temporary presentation mode; preserve the existing frame and its CSS size. */
(() => {
  'use strict';
  const root = document.documentElement;
  const i18n = window.WorkhubI18n;
  const button = document.getElementById('focus-toggle');
  if (!button) return;
  const widthProperty = '--workhub-focus-frame-width';
  const heightProperty = '--workhub-focus-frame-height';
  let active = false;
  let captured = null;
  let previousScroll = null;

  function render() {
    const label = active ? '恢复工作台界面' : '收起工作台界面（保持项目尺寸）';
    button.setAttribute('data-i18n-aria-label', label);
    button.setAttribute('data-i18n-title', label);
    button.setAttribute('aria-label', i18n ? i18n.t(label) : label);
    button.title = i18n ? i18n.t(label) : label;
    button.setAttribute('aria-expanded', String(!active));
    button.setAttribute('aria-pressed', String(active));
  }

  function visibleProjectSize() {
    const page = document.getElementById('spaces-page');
    const frame = document.getElementById('site-frame');
    if (!page || page.hidden || !frame || frame.hidden) return null;
    const box = frame.getBoundingClientRect();
    const visibility = window.getComputedStyle?.(frame).visibility;
    if (visibility === 'hidden' || visibility === 'collapse') return null;
    if (!Number.isFinite(box.width) || !Number.isFinite(box.height) || box.width <= 0 || box.height <= 0) return null;
    return {width: box.width, height: box.height};
  }

  function enter() {
    if (active) return;
    // Read geometry before changing any chrome/layout styles. Keep fractional
    // CSS pixels: rounding can otherwise cross a project's responsive breakpoint.
    captured = visibleProjectSize();
    previousScroll = {x: window.scrollX || 0, y: window.scrollY || 0};
    if (captured) {
      root.style.setProperty(widthProperty, captured.width + 'px');
      root.style.setProperty(heightProperty, captured.height + 'px');
    }
    active = true;
    root.classList.toggle('workhub-focus-project', Boolean(captured));
    root.classList.add('workhub-focus-mode');
    render();
    button.focus({preventScroll: true});
    window.scrollTo({left: 0, top: 0, behavior: 'instant'});
  }

  function exit(options = {}) {
    if (!active) return;
    active = false;
    root.classList.remove('workhub-focus-mode', 'workhub-focus-project');
    root.style.removeProperty(widthProperty);
    root.style.removeProperty(heightProperty);
    captured = null;
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
    getCapturedSize: () => captured ? {...captured} : null,
  };
  render();
})();
