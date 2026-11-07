# Contributing to Workhub

- Read `skill/agent-workhub/SKILL.md` before changing project workflow or templates.
- Keep shared visual tokens in `static/design-system.css`; layouts share one design system.
- Use temporary data directories for tests. Do not read a contributor's private configuration or project history.
- Global installation, background services and external model calls require an explicit user request; cloning and serving the UI must not perform them.
- Preserve existing Agent rules when updating installation behavior.
- Run the relevant tests and `python3 scripts/audit_release.py` before publishing.
