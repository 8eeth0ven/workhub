# Contributing to Workhub

Use Python 3.10 or newer. Read [AGENTS.md](AGENTS.md) for repository conventions and the [shared skill](skill/agent-workhub/SKILL.md) before changing project workflows or templates.

## Preview locally

```sh
python3 examples/demo.py --port 8899
```

Open [http://127.0.0.1:8899](http://127.0.0.1:8899). The isolated demo uses fictional records and preset reviews; it does not read private configuration or call a model.

## Keep changes consistent

- Keep visual tokens in `static/design-system.css`; templates and the portal share them.
- Update the Chinese and English README together. Use landscape images (width greater than height) and Codex Light for README screenshots, and distinguish real demo screenshots from illustrations.
- Use temporary data for validation. Keep development tests outside the published source tree; do not include real project histories, configuration or credentials.
- Preserve existing agent instructions. Cloning or previewing the UI must not install global rules, enable background services or call external models.

## Check before publishing

```sh
python3 scripts/audit_release.py
git diff --check
git diff --cached --name-only
```

Run checks appropriate to the change and state what was actually verified. For documentation changes, check local links, image rendering and mobile layout. Review the staged file list and screenshots; automated scanning does not replace that review. See [release audit](docs/release-audit.md) for the scanner's scope.
