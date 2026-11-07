# Bilingual interface validation

The portal supports `zh-CN` and `en` through its compact top-bar selector. The browser stores the preference under `workhub-language`; unavailable storage falls back to Chinese without blocking in-session switching. No language query parameter is added to project URLs.

## Implementation

- `static/i18n.js` owns both dictionaries, literal interpolation, document language/title, locale-aware dates, and fixed UI attributes. Dynamic project names, work records, answers, evidence text, and model conclusions remain verbatim.
- `window.WorkhubI18n` exposes `t`, `getLocale`, `setLocale`, `formatDate`, `formatRelative`, `onChange`, `apply`, and exact-origin iframe broadcasting.
- Language changes only update interface nodes. They preserve the current page, selected project/site/layout, search/filter values, dialog state, review drafts, and expanded evidence/answer/task details. They do not start reviews, fetch new data, or reload the selected website iframe.
- The portal sends `{type: 'workhub:language', language: 'zh-CN' | 'en'}` to each iframe on language changes and iframe load, using the iframe's actual HTTP(S) origin. Template runtimes consume the message; arbitrary site URLs are not modified.
- Known backend dimension keys have fixed bilingual labels; custom dimension labels and model reasoning remain unchanged. Unknown server errors retain original details under an English interface label when applicable.

## Automated checks

```sh
node --check static/i18n.js
node --check static/app.js
node --check static/reviews.js
node tests/test_i18n.cjs
```

The Node test covers dictionary and placeholder parity, literal interpolation, persistence, blocked storage, unknown locales, dates and relative times, callbacks, exact target origins, and iframe load rebroadcast. HTML IDs, static translation keys, and literal dynamic translation keys were checked for consistency.

## Browser regression checklist

Use the isolated demo (`python3 examples/demo.py --port 8899`); it has fictional content and cannot invoke a model.

1. Switch all four views Chinese → English → Chinese. Verify navigation, buttons, empty/error/loading states, guide, attributes, and dates.
2. Keep a site open and a search/filter applied. Confirm iframe `src`, selected site, and search remain unchanged while the template shell follows the language.
3. Keep a review draft, project/filter selection, and expanded evidence/previous-answer/task details. Switch languages and verify all state remains intact; project/model content stays in its original language.
4. Keep a layout detail preview or project dialog open; switch languages and verify the existing preview and dialog remain open.
5. Confirm local sync timestamps and offline labels update immediately without fetching. Reload to verify the language preference persists.
6. Check the compact toolbar and selector at desktop and narrow widths. No repeated content-area title was introduced.

Main-thread browser checks confirmed two-way portal/template switching, unchanged iframe source, preserved searches and sorting, review drafts/filters/selections, evidence/answer expansion, the selected layout preview, and English persistence after reload. Site-sync labels refresh locally on language changes; generated-site commands include the selected --language value. Final release verification remains with the main thread.
