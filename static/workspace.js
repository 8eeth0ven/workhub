/* User-controlled admission only. No client-history discovery or CLI execution. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const I = window.WorkhubI18n, t = (key, params) => I.t(key, params);
  const dialog = $('workspace-dialog'), form = $('workspace-form');
  const message = $('workspace-message');
  let busy = false;
  function text(tag, value, cls) {
    const node = document.createElement(tag);
    node.textContent = value;
    if (cls) node.className = cls;
    return node;
  }
  function feedback(value, error = false) {
    message.textContent = value;
    message.hidden = !value;
    message.classList.toggle('error', error);
  }
  function show() {
    feedback('');
    renderProjects();
    if (!dialog.open) dialog.showModal();
  }
  async function request(action, payload) {
    const response = await fetch('/api/workspace/' + action, {
      method: 'POST', headers: {'Content-Type':'application/json', 'X-Workhub-Request':'1'},
      body: JSON.stringify(payload), signal: AbortSignal.timeout(8000),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(I.errorMessage(data.error || '项目操作未成功。'));
    return data;
  }
  async function refresh() {
    await window.WorkhubDashboard.refresh();
    renderProjects();
  }
  function renderProjects() {
    const box = $('workspace-projects');
    const projects = window.WorkhubDashboard.projects();
    if (!projects.length) {
      box.replaceChildren(text('p', t('尚未手动添加项目。'), 'workspace-muted'));
      return;
    }
    box.replaceChildren(...projects.map(project => {
      const row = text('div', '', 'workspace-project');
      const info = text('div', '', 'workspace-project-info');
      info.append(text('strong', project.name), text('span', project.path), text('small', (project.source_agents || []).map(agent => ({codex:'Codex',zcode:'Z Code',claude:'Claude CLI',other:t('其他')})[agent] || agent).join(' · ')));
      const remove = text('button', t('从中控移除'), 'button button-outline button-compact');
      remove.type = 'button';
      remove.disabled = busy;
      remove.onclick = async () => {
        if (busy) return;
        busy = true; remove.disabled = true;
        try {
          await request('remove', {id:project.id});
          await refresh();
          feedback(t('已从中控移除，项目文件与历史记录保留。'));
        } catch (error) { feedback(error.message || t('项目操作未成功。'), true); }
        finally { busy = false; renderProjects(); }
      };
      row.append(info, remove);
      return row;
    }));
  }
  function updateSiteFields() {
    const kind = $('workspace-site-kind').value;
    $('workspace-site-fields').hidden = kind === 'none';
    $('workspace-site-target').required = kind !== 'none';
    $('workspace-site-target').placeholder = kind === 'url' ? 'http://127.0.0.1:3000' : t('已有网站的绝对目录路径');
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    const agents = [...form.querySelectorAll('input[name="workspace-agent"]:checked')].map(el => el.value);
    if (!agents.length) { feedback(t('至少选择一个项目来源。'), true); return; }
    const payload = {path:$('workspace-path').value.trim(), agents, theme_mode:$('workspace-shared-theme').checked?'shared':'original'};
    if ($('workspace-name').value.trim()) payload.name = $('workspace-name').value.trim();
    const kind = $('workspace-site-kind').value;
    if (kind !== 'none') payload.site = {kind, target:$('workspace-site-target').value.trim()};
    busy = true; $('workspace-submit').disabled = true; feedback(t('正在添加…'));
    try {
      await request('add', payload);
      await refresh();
      form.reset(); updateSiteFields();
      feedback(t('已加入中控；只有手动添加的项目会显示。'));
    } catch (error) { feedback(error.message || t('项目操作未成功。'), true); }
    finally { busy = false; $('workspace-submit').disabled = false; renderProjects(); }
  });
  document.querySelectorAll('[data-workspace-add]').forEach(button => button.addEventListener('click', show));
  $('workspace-site-kind').addEventListener('change', updateSiteFields);
  window.addEventListener('workhub:state', () => { if (dialog.open) renderProjects(); });
  I.onChange(() => { renderProjects(); updateSiteFields(); if (!message.hidden) message.textContent = I.translateKnown(message.textContent); });
  window.WorkhubWorkspace = {open:show};
  updateSiteFields();
})();
