# Project control and related-project discovery

The existing project space has two views: **Overview** and **Project websites**. Navigation still has six destinations. The overview is a compact list; expanding one project reveals evidence, its personal next step and reference search. Changing views keeps the original iframe and its inputs mounted.

## Add projects

- Select an existing Codex, Z Code or Claude CLI directory, then add it manually. Available client activity timestamps order recent candidates; they are not live execution status.
- **Connect GitHub** lists up to 100 recent public repositories for a user or organization. You can also enter `owner/repo`. Selecting a candidate does not add it. A connection does not clone or execute code.
- Link a repository to an already admitted local project to keep one overview row. Remote-only repositories have no invented local directory or Agent work events.
- Removing a local project hides its linked repository. Disconnecting preserves source files and saved information; project removal disables scheduled discovery.

Public repositories require no key. For a private repository you can access, set `GH_TOKEN` or `GITHUB_TOKEN` in the local service environment and enter its name directly. Permissions are read-only Metadata, Issues, Pull requests and Actions as needed. Credentials are never returned to the browser.

## Evidence and next steps

**Refresh snapshot** reads Git/GitHub on demand. Page polling reads the local cache. The snapshot distinguishes local HEAD from GitHub’s default-branch HEAD, and only associates Actions with the same SHA. Open PRs/issues are bounded recent samples, not complete histories.

Failed refreshes retain earlier available data with a stale marker. GitHub snapshots older than 15 minutes are not used for current recommendations. A finished run is not proof of success or project acceptance.

Recommendations are grounded rules: inspect a failing check, review uncommitted changes, or consider an open issue. They are not a complete code review or fabricated completion events. Save a next step and P0–P3 priority, or copy a continuation brief back to an Agent. Local projects can open the existing project-review feature; a model is only used after an explicit review submission.

## Related projects

Expand **Discover related projects**, enter keywords, and search immediately or save a schedule:

- Off by default; the interval defaults to **daily**, with **6 hours / daily / weekly** available.
- Runs only while the local Workhub service is running. A restart checks an overdue configuration once. No OS task or Codex automation is created.
- Only the user’s keywords are submitted. This version searches public GitHub repository names, descriptions and READMEs, excluding forks and archived projects, with at most 10 results.
- Keyword relevance is a discovery hint, not implementation equivalence or a similarity percentage. Results retain their source, query, observation time and incomplete-result flag.
- Numeric repository IDs deduplicate findings across renames and result order changes. Errors retain previous results. Changed keywords make previous-query results visibly stale.
- SQLite leases and configuration generations prevent duplicate work and stale requests overwriting new settings. Searches share a minimum 7-second spacing; the timer dispatches at most once every 15 seconds. Removing/disabling a project stops future runs.

Nothing automatically clones, installs, executes or admits a reference project. Plans, queries and snapshots stay in the local Workhub database.

### Lessons, differences and next steps

Results stay in project details. Each candidate initially shows its name and one topic. Expand it for **Worth studying / Differences from this project / Next validation step**. Additional topics and source evidence remain collapsed. **Use as next-step draft** only fills the draft; save it to keep the plan. Nothing executes automatically.

- Each search reads public READMEs for at most the first **3** candidates and the current project. Other candidates use public descriptions. README files are limited to 64 KiB and analyzed text to 32,000 characters. Notes retain the document SHA, retrieval time, short excerpts and source links, not full README copies. Anonymous rate limits, unavailable or oversized documents cause fallback.
- A manually linked GitHub repository supplies the current public README. Optional **Project focus** stays local and is not appended to external search keywords. Without a baseline, differences remain unknown. Private repositories, local code and chats are not comparison inputs.
- Inspectable rules identify documentation leads for session continuity, events, workspaces, approvals, search, schedules, extensions and project organization. Notes describe claims and experiments, not model reviews or verified runtime capabilities. Insufficient evidence produces no invented advantage. Stars are not feature-quality evidence.
- Shared capabilities are labeled as shared claims. Undocumented capabilities are not declared unimplemented. Fenced code, explicitly negative statements and roadmap entries are excluded from capability matches. Rules can still miss or misidentify claims: check the source and implementation.
- Public profiles use anonymous GitHub requests, at most 8 additional ordinary API calls per search. External material is rendered as text. Credential patterns, emails, personal paths and credential-bearing URLs are redacted; clearly sensitive search keywords are rejected. Errors omit upstream bodies. A changed project focus marks earlier comparisons stale.

Existing references include [GitRec](https://github.com/gorse-io/gitrec) for related repositories and [OSSInsight](https://github.com/pingcap/ossinsight) for repository comparison. This implementation retains public evidence from the [GitHub README API](https://docs.github.com/en/rest/repos/contents#get-a-repository-readme); repository metrics are not capability evaluations.

Local results may also contain a separate `document_review` annotation layer bound to the current query and source observation time. Reviewer, time and sources must be explicit. Reviewed candidates appear first, with other raw matches collapsed; original order, query and automatic comparisons remain intact. A new search does not inherit the previous annotations. There is no general review editor or automatic review job: Codex added this local layer for a user-requested trial, not for every search. Discovery settings also collapse once results exist.

## References and compatibility

[DeepSeek Harness](https://www.deepseek.com/harness/zh/), [dsh-worktable](https://github.com/Aisland-SJL/dsh-worktable/blob/main/README.zh.md) and [dsh-superagent-prototype](https://github.com/deepseek-ai/dsh-superagent-prototype) provide established architectural and interaction references. This release borrows selected patterns; it is not a DSH host plugin, native session bridge or copy of its layout engine.

The compact list and on-demand detail follow [GitHub Projects](https://docs.github.com/en/issues/planning-and-tracking-with-projects/customizing-views-in-your-project/changing-the-layout-of-a-view), [Linear display options](https://linear.app/docs/display-options) and [Apple disclosure controls](https://developer.apple.com/design/human-interface-guidelines/disclosure-controls). Discovery uses the existing [GitHub repository search API](https://docs.github.com/en/rest/search/search#search-repositories).

Implementation: `project_control.py`, `project_discovery.py`, `project_comparison.py`, `project_catalog.py` and the existing local HTTP guards. Verification uses synthetic directories/databases and a fake GitHub outside the publishing tree, including race conditions, stale data, 320–1440px layouts, themes, languages and iframe input retention. Public screenshots contain fictitious projects only.
