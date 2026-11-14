/* Navigation panels have independent preferences; content frames stay mounted. */
(() => {
  'use strict';
  const workspaceKey = 'workhub-sidebar-collapsed';
  const sitesKey = 'workhub-site-navigator-collapsed';
  const root = document.documentElement;
  try { root.dataset.workhubSpaceMode = localStorage.getItem('workhub-space-mode') || (localStorage.getItem('workhub-current-site') ? 'website' : 'control'); }
  catch { root.dataset.workhubSpaceMode = 'control'; }

  let collapsed = false;
  let sitesCollapsed = false;
  let hasSitesPreference = false;
  try {
    collapsed = localStorage.getItem(workspaceKey) === 'true';
    const saved = localStorage.getItem(sitesKey);
    hasSitesPreference = saved !== null && saved !== undefined;
    sitesCollapsed = hasSitesPreference ? saved === 'true' : collapsed;
  } catch { sitesCollapsed = collapsed; }
  // Apply both saved states before paint, including the legacy outer-only case.
  root.classList.toggle('sidebar-collapsed', collapsed);
  root.classList.toggle('site-navigator-collapsed', sitesCollapsed);

  function init() {
    const toggle = document.getElementById('sidebar-toggle');
    const sidebar = document.getElementById('workspace-sidebar');
    const sitesToggle = document.getElementById('site-navigator-toggle');
    const sites = document.getElementById('project-site-navigator');
    const i18n = window.WorkhubI18n;
    function renderPanel(button, panel, hidden, className, showLabel, hideLabel) {
      root.classList.toggle(className, hidden);
      if (!button || !panel) return;
      if (hidden && panel.contains(document.activeElement)) button.focus();
      panel.hidden = hidden;
      button.setAttribute('aria-expanded', String(!hidden));
      const label = hidden ? showLabel : hideLabel;
      button.setAttribute('data-i18n-aria-label', label);
      button.setAttribute('data-i18n-title', label);
      button.setAttribute('aria-label', i18n ? i18n.t(label) : label);
      button.title = i18n ? i18n.t(label) : label;
    }
    function render() {
      renderPanel(toggle, sidebar, collapsed, 'sidebar-collapsed', '展开侧边栏', '收起侧边栏');
      renderPanel(sitesToggle, sites, sitesCollapsed, 'site-navigator-collapsed', '展开网站列表', '收起网站列表');
    }
    toggle?.addEventListener('click', () => {
      collapsed = !collapsed;
      if (!hasSitesPreference) sitesCollapsed = collapsed;
      render();
      try { localStorage.setItem(workspaceKey, String(collapsed)); } catch {}
    });
    sitesToggle?.addEventListener('click', () => {
      sitesCollapsed = !sitesCollapsed;
      hasSitesPreference = true;
      render();
      try { localStorage.setItem(sitesKey, String(sitesCollapsed)); } catch {}
    });
    window.addEventListener('storage', event => {
      if (event.key === workspaceKey) {
        collapsed = event.newValue === 'true';
        if (!hasSitesPreference) sitesCollapsed = collapsed;
      } else if (event.key === sitesKey) {
        hasSitesPreference = event.newValue !== null && event.newValue !== undefined;
        sitesCollapsed = hasSitesPreference ? event.newValue === 'true' : collapsed;
      } else if (event.key === null) {
        collapsed = false;
        sitesCollapsed = false;
        hasSitesPreference = false;
      } else return;
      render();
    });
    if (i18n) i18n.onChange(render);
    render();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once:true});
  else init();
})();
