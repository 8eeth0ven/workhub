/* Opt-in color bridge for a child page. No business DOM, navigation, or requests. */
(() => {
  'use strict';
  if (window.WorkhubEmbeddedTheme) return;
  const themes = Object.freeze(['moss', 'fog', 'graphite', 'sand', 'orange', 'teal', 'rose', 'indigo']);
  const supported = value => themes.includes(value);
  const key = 'workhub-theme';
  const allowedParents = new Set(['http://127.0.0.1:8787']);
  // Additional origins require explicit local-page configuration. Referrer is
  // deliberately not used as trust, and configuration can only add loopback.
  const script = document.currentScript;
  const configured = script?.getAttribute('data-workhub-parent-origin') || document.documentElement.getAttribute('data-workhub-parent-origin');
  if (configured) {
    try {
      const value = configured.trim(), url = new URL(value);
      if (['http:', 'https:'].includes(url.protocol) && ['127.0.0.1', 'localhost', '[::1]', '::1'].includes(url.hostname) && !url.username && !url.password && !url.search && !url.hash && url.pathname === '/' && (url.origin === value || url.origin + '/' === value)) allowedParents.add(url.origin);
    } catch {}
  }
  let theme = 'moss';
  try { const saved = localStorage.getItem(key); if (supported(saved)) theme = saved; } catch {}
  function apply(value, persist = true) {
    if (!supported(value)) return false;
    theme = value;
    document.documentElement.setAttribute('data-workhub-theme', theme);
    try { if (persist) localStorage.setItem(key, theme); } catch {}
    return true;
  }
  function request(type = 'workhub:theme-request') {
    if (window.parent === window) return;
    for (const origin of allowedParents) window.parent.postMessage({type}, origin);
  }
  window.addEventListener('message', event => {
    if (window.parent === window || event.source !== window.parent || !allowedParents.has(event.origin) || !event.data || typeof event.data !== 'object' || event.data.type !== 'workhub:theme' || !supported(event.data.theme)) return;
    apply(event.data.theme);
  });
  window.addEventListener('storage', event => {
    if (event.key === key && (event.newValue === null || supported(event.newValue))) apply(event.newValue || 'moss', false);
  });
  window.addEventListener('pageshow', () => request());
  window.WorkhubEmbeddedTheme = {themes, getTheme: () => theme, requestTheme: request};
  apply(theme, false);
  request();
  const ready = () => request('workhub:theme-ready');
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready, {once: true});
  else ready();
})();
