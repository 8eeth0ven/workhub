[简体中文](privacy.md) | [English](privacy.en.md)

# Data and release boundaries

## Local storage

Project paths, names, descriptions, work records, supplemental answers and model reviews are stored in the user's state directory. It defaults to `~/.local/share/agent-workhub` and can be changed with `AGENT_WORKHUB_HOME`. The directory may also contain the database, instruction-file backups, model configuration, logs, session process records and an optional runtime copy.

Learning explanations, implementation notes, relative source references, knowledge revisions and user acknowledgements also stay in this private database. Reading, filtering, refreshing or acknowledging a card does not call a model. Coding agents submit new cards through the local CLI. Published source and demonstrations must exclude the user's real cards, source excerpts and understanding status.

Project archives can also retain the actual agent, session provenance, necessary task prompts and explicitly selected deliverable snapshots locally. Original instructions and rewritten `derived` versions remain separate, with their sources, revisions and hashes. Entire conversations are not copied. Prompts containing credentials are rejected by default; an explicitly requested redacted copy is marked as derived, and the original credential is not written to disk.

The interface-language preference is stored locally in the browser for the current portal origin. It is not written into project content, and changing language does not trigger a translation or model request. Project names, work records, website content and existing reviews remain in their original language.

Published source code should not contain real runtime material. Repository template demos use synthetic content; newly generated real sites default to `is_demo=false` and `items=[]`. Do not replace demo data with a personal database, or copy real project inventories, screenshots or configuration into the examples directory.

## When data leaves the machine

The local portal binds only to loopback by default. Cloning, foreground startup and skill installation do not independently call a model. When the user configures and enables reviews, the backend sends a limited project name, description, recent work summaries, supplemental answers and evidence identifiers to the configured API or CLI. It does not automatically read the full project repository, chat history or environment files.

The backend removes known credentials and some sensitive fields, but automatic redaction cannot guarantee that every sensitive detail is recognized. Before recording a summary, answering a follow-up or requesting a review, check that the material is suitable for the selected reviewer. A local model or CLI may have its own networking, logging and retention behavior; understand that behavior too.

Archived original prompts and deliverable files are not included in model-review requests by default. Local retention is not permission to send them elsewhere. If their contents are needed as context, first select a necessary summary suitable for the reviewer. Deliverable snapshots follow explicitly selected entries, local image/CSS dependencies and explicit attachments; choosing a directory does not read or expose its sibling articles.

Credentials are read only by the backend from private configuration or the environment. They do not belong in frontend code, work records, screenshots, Git or command arguments. Keep `llm.json` and the compatible `glm.json` private; examples use explicit placeholders. CLI commands come only from local user configuration. The web API does not accept command-execution parameters.

## Website visibility

The portal reads static-site directories that the user explicitly connects and provides loopback previews for them. Before connecting a directory, confirm that its contents are appropriate for browser access. Do not use a project root containing credentials and private configuration as a website root. The server rejects hidden files and paths escaping the selected directory, but those checks cannot determine the sensitivity of every business file.

Existing local services retain their own data, permissions and runtime behavior. `localhost` refers to the visitor's computer; a local address does not automatically work across machines. The portal does not provide a general-purpose proxy for bypassing another site's embedding rules or browser protections. Third-party websites also retain their own language behavior.

## Release checks

```sh
python3 scripts/audit_release.py
```

The scanner reads only candidate source files and files Git might track inside the release directory. It does not read the user's state directory, credential configuration or Agent history. In a Git repository, candidates are tracked files plus nonignored files that could be added. A private file that is already tracked remains blocked even after an ignore rule is added. Without Git metadata, the scanner uses a restricted source-tree walk and reports sensitive filenames and runtime artifacts.

Personal absolute home paths, suspected credentials or private keys, databases, private configuration and runtime copies cause a nonzero exit code. Reports contain only relative filenames, finding types and line numbers; suspected secret values are not echoed. This is a heuristic release check, not a replacement for reviewing the actual changes, examples and screenshots.

`.gitignore` excludes environment configuration, private model configuration, databases, logs, runtime directories, exports, reports and screenshots. Only reviewed documentation screenshots belong in `docs/images/`. Ordinary `git add` should not add ignored runtime files, but new ignore rules do not remove already tracked files. Inspect staged content before publishing.

For setup and provider-specific data paths, see [Installation](installation.en.md) and [Providers and reviewers](providers.en.md).
