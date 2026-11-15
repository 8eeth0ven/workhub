[简体中文](installation.md) | [English](installation.en.md)

# Installation and configuration

Workhub uses the Python 3.10+ standard library. The foreground portal and site generator do not require third-party Python packages or frontend dependencies. Run commands from the cloned repository's root. Code derives paths from its own location and `Path.home()`; no contributor-specific directory needs to be edited into the source.

## Start with the foreground portal

```sh
python3 workhub.py serve --host 127.0.0.1 --port 8787
```

Open `http://127.0.0.1:8787`. If another application uses that port, choose a different one. Cloning or serving Workhub does not modify global Agent rules, scan other projects, install a background service or call a model.

The default state directory is `~/.local/share/agent-workhub`. Set `AGENT_WORKHUB_HOME` to use an independent data directory. Tests and demos should use temporary directories so fictional or test records do not mix with real work.

The top toolbar switches between Simplified Chinese and English. The choice is saved in browser-local storage for the current portal origin. Changing language keeps the current page, selected website, filters and unfinished input. Only the interface is translated; project content and existing reviews keep their original language. CLI commands, API routes and model configuration are unaffected.

## Optionally install Agent entries

Preview the plan before running the installation you need. Only explicitly running the installer writes these rule files.

```sh
python3 scripts/install.py --global --dry-run
python3 scripts/install.py --global
```

Global installation creates links to one shared skill under `.codex/skills`, `.agents/skills`, `.zcode/skills` and `.claude/skills`. It appends a Workhub marker block to the user's Codex, Z Code and Claude Code instruction files. Existing content is preserved and backed up under the state directory's `backups/`. Unrelated same-name skills or commands, and symlink targets, are not overwritten. Repeating installation does not append duplicate blocks.

To connect one project, set `PROJECT_DIR` to its actual absolute directory:

```sh
python3 scripts/install.py --project "$PROJECT_DIR" --name "Project name"
```

This appends instruction entries to that directory's `AGENTS.md` and `CLAUDE.md` and registers the project. It does not recursively rewrite other projects. A client must actually load the relevant instructions for the protocol to apply; an existing session may need to reload. The installer's `--home` option supports a temporary installation root for testing. It does not distribute a skill to a remote client.

After moving the repository, run the installer again to update locally generated absolute paths. Those installation paths belong in the user's local configuration, not in a published repository.

Use `archive-session`, `archive-prompt` and `archive-artifact` to retain a project's agent, session provenance, original task instructions and deliverables. Inspect them with `archive-list --project "$PROJECT_DIR"`. Original and derived prompts keep separate revisions; artifact snapshots follow explicitly selected entries and dependencies. See [Project archives](project-archive.en.md) for parameters, status and privacy boundaries.

## Connect websites and create layouts

Use `--site-dir` for an existing static site or `--site-url` for a running development server. These options are mutually exclusive:

```sh
python3 scripts/install.py --project "$PROJECT_DIR" \
  --site-dir "$PROJECT_DIR/site" --site-name "Project website" --template library
python3 scripts/install.py --project "$PROJECT_DIR" \
  --site-url http://127.0.0.1:3000 --site-name "Development website"
```

Creating a layout and registering a website are separate steps. The generator protects existing nonempty directories. By default it creates an empty real-content structure rather than copying demo entries:

```sh
python3 scripts/site_templates.py create --template radar --language en \
  --output "$PROJECT_DIR/site" --name "Information board"
```

Use `--language en` for an initially English interface, or `--language zh-CN` for Simplified Chinese (the default). An existing browser language preference takes priority. List layouts in English with `python3 scripts/site_templates.py list --language en`.

All three layouts share `static/design-system.css`. When the sidebar already names a page, the content area does not repeat it as a large heading. See the skill's [design-system reference](../skill/agent-workhub/references/design-system.md) for the complete visual rules. Supported templates receive the portal's interface-language choice; site content is not machine-translated.

## Optional background service

On macOS and Linux, session mode runs an independent background process. It does not require a chat or browser window to stay open. Run these commands only when you explicitly want a background service:

```sh
python3 scripts/service.py install --mode session --port 8787
python3 scripts/service.py status
python3 scripts/service.py stop
python3 scripts/service.py start
python3 scripts/service.py uninstall
```

`start`, `status` and `stop` read the saved mode and port from the state directory. Before stopping a process, the script checks its PID, start time and command; it does not kill processes by port. Session mode does not configure automatic login startup. Run `start` again after logging out or rebooting. Logs and process records remain in the state directory, outside Git.

The optional macOS `--mode launchd` uses a user LaunchAgent and synchronizes the backend, review module and static resources into the state directory's `runtime/`. The operating system can still restrict a background process from reading project directories. Do not disable system protections to force access; choose a session process or foreground service according to what works in your environment. Linux does not use launchd. On Windows, start by verifying the foreground portal; complete compatibility of background services and skill symlinks is not promised.

Passing an explicit `--home` to the service script always stages test configuration only: it starts no process and does not operate real launchd jobs. `--dry-run` writes no files.

## Optional model reviews

Open **Project reviews → Model access**, choose API or local CLI, fill in the relevant fields, and save. **Test connection** checks the draft without saving it or sending project content. API options include GLM, OpenAI-compatible, Anthropic and local endpoints. CLI options include detected Codex, Claude Code, Z Code, or an advanced custom argument array. Clients need their existing login; Workhub does not install or sign into them. Z Code uses its current client model.

Manual configuration remains available:

Copy an appropriate `examples/provider-*.json` file into `llm.json` in the state directory, fill in your configuration, and make it readable and writable only by your user:

```sh
WORKHUB_DATA_DIR="${AGENT_WORKHUB_HOME:-$HOME/.local/share/agent-workhub}"
chmod 600 "$WORKHUB_DATA_DIR/llm.json"
```

`AGENT_WORKHUB_HOME` should refer to your actual state directory; if unset, the command uses the default. Configuration supports `provider`, `api_keys` or `api_key`, `base_url`, `model`, and the backend's timeout, output and concurrency limits. Reviewers can use cloud APIs, a local model or an explicitly configured CLI. See [Providers and reviewers](providers.en.md) for complete examples and adapter boundaries.

When `llm.json` exists, it takes precedence. Legacy `glm.json` is read only when the new file is absent; the files are not merged. `WORKHUB_LLM_PROVIDER`, `WORKHUB_LLM_API_KEYS` / `WORKHUB_LLM_API_KEY`, `WORKHUB_LLM_BASE_URL` and `WORKHUB_LLM_MODEL` can override corresponding fields. Legacy `GLM_*` variables are used only for GLM compatibility fallback.

A CLI provider's `command` is an argument array explicitly saved by a trusted local user, with optional `cwd` and output format. Native adapters wrap detected clients; advanced custom commands still follow the JSON input/output contract. Shell command strings and credentials in arguments are rejected. OpenAI-compatible HTTP is accepted only with explicit local-HTTP permission and a literal loopback address; public endpoints use HTTPS.

After the user enables reviews, `python3 workhub.py review --project "$PROJECT_DIR"` sends limited registered project material to the selected reviewer. Missing configuration and failed calls are reported as such; Workhub does not invent local scores and present them as model output. Switching the interface language does not start another review or translate an existing one. See [Privacy](privacy.en.md) for the data scope and release checks.


## Manually add a workspace project

Choose **Add existing project** in Project spaces, enter its actual directory, select Codex, Z Code or Claude CLI, and optionally connect a website. Only manually added projects and their records appear. Existing database registrations are not automatically admitted after upgrading; their records remain intact.

Explicit CLI alternatives, selected by the user rather than run automatically by an agent:

```sh
python3 workhub.py workspace-add --path /path/to/project --agent codex --agent claude
python3 workhub.py workspace-remove --id PROJECT_ID
```

`register`, `record` and `site-add` still preserve project metadata and history without admitting projects. Removing an entry does not delete source directories, records or sites. Websites keep their original appearance unless the user opts into theme adaptation through the UI or `workspace-add --shared-theme`.
