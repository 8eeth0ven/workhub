# Project archive validation

The archive stores explicit project session references, original prompts and derived versions, and a manifest of selected publication files. Source attribution and platform publication status are supplied facts; neither is inferred from filenames or from a later file organizer.

Validation covers:

- SQLite persistence, concurrent revision writes, exact UTF-8 prompt whitespace and hashes, original/derived links, and project boundaries.
- Rejection of unsupported request fields and credential-like original input; explicit redaction produces a labeled derivative rather than silently replacing the original.
- Host/Origin, JSON and request-marker guards; isolated snapshot origins with a scriptless CSP and no backend API access.
- Explicit entry dependencies and selected attachments, traversal/symlink exclusion, snapshot tamper checks, embedded image validation, and primary image counts independent of editor duplicates.
- Interface behavior through dependency-free Node tests: raw text copying, filtering and language state, version details, unsaved form content, explicit redaction consent and controlled preview URLs. Fixtures are fictional and model calls are not triggered.
- Review provenance: agent reports remain reports, the model does not claim independent checks, questions need a reason and actionable check, duplicates are rejected, and a changed policy invalidates earlier evidence fingerprints.

Run the current suite with:

```sh
python3 -m unittest discover -s tests -v
node tests/test_i18n.cjs
node tests/test_archives_ui.cjs
python3 scripts/audit_release.py
git diff --check
```

The installed local service was also checked through its real HTTP endpoints: registered article bodies matched snapshot hashes, image references resolved, existing journal/site/review records remained present, and provider configuration was retained. These private installation records are kept outside the release repository.

The browser automation bridge timed out during this update. A new desktop/mobile visual walkthrough and screenshots were **not completed**. Node interaction tests and HTTP checks do not substitute for that visual inspection. The new publication package remains a draft with this limitation recorded.
