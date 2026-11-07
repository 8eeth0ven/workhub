# Bilingual layout validation

All three layouts use the same design system and support `zh-CN` and `en`. A compact language selector uses the shared `workhub-language` preference. The page updates `document.lang`, accessible labels, placeholders, filters, sorting labels, metrics, source links, dialogs, loading/error/empty states and footer text. User-supplied names, descriptions, titles, summaries, tags and categories retain their original text.

The selector fits into a compact layout header. It adds no marketing banner or duplicate large page heading. Layout-specific structure remains unchanged.

## Portal synchronization

The template accepts the following message:

```js
{ type: 'workhub:language', language: 'en' } // or 'zh-CN'
```

Messages must come from `window.parent`. Accepted origins are the template’s own origin, its actual referrer origin, or an HTTP(S) loopback origin (`127.0.0.1`, `localhost`, `::1`). The loopback case supports locally served project frames when the portal uses `no-referrer`. Other origins, opaque origins, unrelated windows and unsupported locale values are ignored. A standalone template ignores parent messages.

Language changes preserve the current search query, category, sorting choice and open detail dialog. Storage restrictions do not prevent in-memory switching. Storage change events synchronize same-origin tabs. No cross-origin DOM access is attempted.

## Standalone generation

`scripts/site_templates.py create` accepts `--language en` or `--language zh-CN`. The generated page records the default locale and supported locales in its manifest. Canonical design CSS, compact-shell CSS and the shared runtime are copied locally, so the generated site has no dependency on a portal address. The read-only demo uses the same complete assets.

## Checks

- Seven template behavior tests execute the actual generated runtime in a minimal DOM fixture. They cover all layouts, initial English, language persistence, blocked storage, project text preservation, filter and dialog preservation, trusted/hostile parent messages, standalone isolation and translated empty/error states.
- Three design-system tests cover independent generation and real HTML/CSS/JS/JSON requests from an ordinary static server, canonical theme copies and existing-site protection.
- Two read-only demo tests cover isolated fixture data and complete layout resources.
- Shared runtime JavaScript syntax check passes.
- Release audit checks repository candidates without reading private configuration; no findings.

Fixtures, home directories, data and listeners are temporary. These checks do not invoke an external model, install global Agent rules or register background services. Browser-level visual checks are performed by the integrating task.
