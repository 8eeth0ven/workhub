/* Palette selection only: no layout changes, frame reloads, or project writes. */
(() => {
  'use strict';
  const key = 'workhub-theme';
  const themes = Object.freeze(['moss', 'fog', 'graphite', 'sand', 'orange', 'teal', 'rose', 'indigo']);
  const normalize = value => themes.includes(value) ? value : 'moss';
  const root = document.documentElement;
  let theme = 'moss';
  try { theme = normalize(localStorage.getItem(key)); } catch {}
  // This script runs synchronously before the stylesheets and first paint.
  root.setAttribute('data-workhub-theme', theme);
  const callbacks = new Set();

  function broadcastFrame(frame) {
    try {
      const url = new URL(frame.src, location.href);
      if (!['http:', 'https:'].includes(url.protocol) || !frame.contentWindow) return;
      frame.contentWindow.postMessage({type: 'workhub:theme', theme}, url.origin);
    } catch {}
  }
  function broadcastFrames() { document.querySelectorAll('iframe').forEach(broadcastFrame); }
  function renderControl() {
    const select = document.getElementById('workhub-theme');
    if (select) select.value = theme;
  }
  function setTheme(value, options = {}) {
    const next = normalize(value), changed = next !== theme;
    theme = next;
    root.setAttribute('data-workhub-theme', theme);
    if (options.persist !== false) { try { localStorage.setItem(key, theme); } catch {} }
    renderControl();
    if (changed) {
      callbacks.forEach(callback => callback(theme));
      window.dispatchEvent(new CustomEvent('workhub:theme-change', {detail: {theme, source: options.source || 'api'}}));
    }
    broadcastFrames();
    return theme;
  }
  function onChange(callback) { callbacks.add(callback); return () => callbacks.delete(callback); }
  window.WorkhubTheme = {themes, getTheme: () => theme, setTheme, onChange, broadcastFrames};
  document.addEventListener('load', event => { if (event.target?.tagName === 'IFRAME') broadcastFrame(event.target); }, true);
  // A child may become ready after the load broadcast. Reply only to the
  // exact mounted iframe and origin; request messages never change preferences.
  window.addEventListener('message', event => {
    if (!event.data || typeof event.data !== 'object' || !['workhub:theme-request', 'workhub:theme-ready'].includes(event.data.type)) return;
    const frame = [...document.querySelectorAll('iframe')].find(candidate => {
      if (candidate.contentWindow !== event.source || typeof candidate.src !== 'string' || !candidate.src.trim()) return false;
      try { const url = new URL(candidate.src, location.href); return ['http:', 'https:'].includes(url.protocol) && url.origin === event.origin; } catch { return false; }
    });
    if (frame) broadcastFrame(frame);
  });
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) setTheme(event.newValue, {persist: false, source: 'storage'});
  });
  function init() {
    const select = document.getElementById('workhub-theme');
    select?.addEventListener('change', () => setTheme(select.value, {source: 'selection'}));
    window.WorkhubI18n?.onChange(renderControl);
    renderControl();
    broadcastFrames();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
