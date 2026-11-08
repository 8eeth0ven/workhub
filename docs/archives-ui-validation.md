# Project archives UI validation

`Project archives` adds three compact views: agent sessions, prompt versions, and publication artifacts. It uses the existing Workhub visual tokens and Chinese/English selector; archived names, source references, prompt text, and publication titles remain verbatim.

## Behavior and boundaries

- Project, agent, and text filters remain selected across refreshes and language changes. Search/project scope is sent to the archive API; bounded results show a hint when more records are available.
- Work-log agent usage is displayed separately from registered sessions. Missing original session IDs, original timestamps, generation dates, source verification, or publication status remain unknown. Registration time is explicitly labeled as registration time.
- Original and derived prompts are labeled separately. Copying preserves leading/trailing whitespace and literal markup. Version history is read through `/api/archives/prompt`; creating a derived version appends a revision and reference rather than overwriting text.
- Session/prompt forms require project, title, and source facts. Session records additionally require agent and original session ID. Prompt bodies are never trimmed or translated. Sensitive input is rejected unless the user explicitly chooses a redacted derived copy.
- No UI action scans a home folder or imports full chat history. Artifact folders are registered by an agent/CLI. Publication cards show backend image counts first, with an array-length fallback, and preserve unknown states.
- Artifact previews use only backend-returned HTTP(S) loopback URLs, reject credentials/non-loopback sources, and run in an iframe without script permission. They remain inside the portal. Language changes preserve the current preview URL, selected prompt, open version details, and form inputs.
- Archive requests use archive endpoints only. No archive action starts a model review or sends prompt text to an external service. Demo mode disables mutations in the UI; the server independently rejects all demo POST requests.

## Checks completed

```sh
node --check static/archives.js
node --check static/app.js
node tests/test_archives_ui.cjs
node tests/test_i18n.cjs
```

The archive Node test executes the module with temporary DOM/API fixtures and verifies literal copying, unknown publication state, work-log/session separation, version and language state, form drafts and POST header, no review calls, and controlled preview rejection. HTML IDs, DOM references, and translation dictionary keys were also checked.

A temporary isolated demo integration returned HTTP 200 with three fictional sessions, four fictional prompts, and one fictional artifact. The browser-facing payload was marked `is_demo:true`. No personal archive database was read.

## Browser acceptance

1. Open all three archive tabs in the isolated demo; filter by project/agent/text and switch languages.
2. Copy a prompt, open its history, and switch languages with details expanded. Confirm original text, selected revision, and filters remain unchanged.
3. Open a publication preview; confirm the portal remains visible, script execution is disabled, and image counts/status match the backend inventory.
4. In a temporary normal database, enter a session/prompt form, switch language mid-draft, and save. Confirm append-only revision semantics and source metadata.
5. Verify a missing file/reference, an unknown generation time, and an unknown publication status are never represented as a completed publication.

The main thread owns real-data import, browser acceptance, runtime upgrade, and publication. No private session text or real artifacts were added to this repository by this UI task.
