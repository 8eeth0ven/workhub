/* Keep recorded projects visible even before they have a website. */
(() => {
  'use strict';
  function groupProjects(projects, sites, query = '') {
    const groups = new Map();
    for (const project of projects) {
      groups.set(String(project.id), {project, sites: []});
    }
    for (const site of sites) {
      const id = String(site.project_id || 'unassigned');
      // A stale site response cannot re-admit a removed project.
      if (!groups.has(id)) continue;
      groups.get(id).sites.push(site);
    }
    const needle = query.trim().toLocaleLowerCase();
    const matches = values => values.filter(Boolean).join(' ').toLocaleLowerCase().includes(needle);
    return [...groups.values()].flatMap(group => {
      const projectMatches = matches([group.project.name, group.project.description]);
      const entries = projectMatches ? group.sites : group.sites.filter(site => matches([site.name, site.description]));
      if (!projectMatches && !entries.length) return [];
      return [{project: group.project, sites: entries, hasWebsite: group.sites.length > 0}];
    });
  }
  window.WorkhubSiteNavigation = Object.freeze({groupProjects});
})();
