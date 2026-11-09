/* Keep workspace navigation optional without reloading project content. */
(() => {
  'use strict';
  const key = 'workhub-sidebar-collapsed';
  const root = document.documentElement;
  let collapsed = false;
  try { collapsed = localStorage.getItem(key) === 'true'; } catch {}
  // This small script runs in the head so a saved preference applies before paint.
  root.classList.toggle('sidebar-collapsed', collapsed);

  function init() {
    const toggle = document.getElementById('sidebar-toggle');
    const sidebar = document.getElementById('workspace-sidebar');
    if (!toggle || !sidebar) return;
    const i18n = window.WorkhubI18n;
    function render() {
      if (collapsed && sidebar.contains(document.activeElement)) toggle.focus();
      root.classList.toggle('sidebar-collapsed', collapsed);
      sidebar.hidden = collapsed;
      toggle.setAttribute('aria-expanded', String(!collapsed));
      const label = collapsed ? '展开侧边栏' : '收起侧边栏';
      toggle.setAttribute('data-i18n-aria-label', label);
      toggle.setAttribute('data-i18n-title', label);
      toggle.setAttribute('aria-label', i18n ? i18n.t(label) : label);
      toggle.title = i18n ? i18n.t(label) : label;
    }
    toggle.addEventListener('click', () => {
      collapsed = !collapsed;
      render();
      try { localStorage.setItem(key, String(collapsed)); } catch {}
    });
    window.addEventListener('storage', event => {
      if (event.key === key) {
        collapsed = event.newValue === 'true';
        render();
      }
    });
    if (i18n) i18n.onChange(render);
    render();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once:true});
  else init();
})();
