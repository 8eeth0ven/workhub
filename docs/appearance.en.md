[简体中文](appearance.md) | [English](appearance.en.md)

# Appearance and embedded reading

## Interface language and appearance

Use the **简体中文 / English** selector in the top toolbar. Your choice is saved locally in the browser for the current Workhub origin and restored after a refresh. It changes navigation, controls, status labels and interface messages while keeping the current page, selected site, filters and unfinished input.

Project names, work records, website content and existing model reviews stay in their original language. Supported template iframes receive the portal's language choice; third-party websites keep their own language behavior. Documentation has matching language links at the top of each translated page. CLI commands, API paths and stored data are unchanged by the interface setting.

The default is pure-white **Codex Light**. The **Appearance** selector also offers **Codex Dark** and the eight existing palettes. The portal and all three layouts share color tokens; standalone generated sites include the same selector. Preferences are saved locally. Switching preserves search, draft input and frames, and never invokes a model.

The local directory server injects the restricted palette runtime and shared CSS; compatible templates follow the portal too. Generic embedded styles are color-only: they do not alter font sizes, layout, images, PDFs, video or charts. Native applications can set `body[data-workhub-native]` to skip generic overrides and map their own exact color variables.

Applications with their own backend can explicitly load these resources in their page:

```html
<link rel="stylesheet" href="http://127.0.0.1:8787/design-system.css">
<link rel="stylesheet" href="http://127.0.0.1:8787/embedded-theme.css">
<script defer src="http://127.0.0.1:8787/embedded-theme.js"></script>
```

The child runtime trusts only its actual parent at `http://127.0.0.1:8787` by default and requests the current palette through a ready/request handshake. For a custom port or a `localhost` alias, explicitly set an HTTP(S) loopback origin such as `data-workhub-parent-origin="http://127.0.0.1:8899"` on the script tag and update the resource URLs. Arbitrary referrers are not trusted. Third-party pages that have not opted in are not forced through cross-origin DOM manipulation. Directory pages can disable automatic injection with `?workhub_theme=original`.

Articles can remain light independently of the workspace. Add `<meta name="workhub-reading-theme" content="light">` to the head, or set `data-workhub-reading-theme="light"` on the html element. The directory preview honors this declaration without overwriting the saved workspace preference. Keep CSS out of Markdown source; attach the [reading-light stylesheet](../examples/reading-light/) to a renderer that supports custom CSS. WeChat publishing still requires inline styles and supported tags. The included article is a layout sample.
