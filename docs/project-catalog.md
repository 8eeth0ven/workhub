# Existing project directory sources / 已有项目目录来源

The add-project dialog reads directory metadata on demand when it opens or the user refreshes. It does not scan client chat folders or import conversations. Selecting a candidate only fills the form; the user still clicks **Add to workspace**.

添加窗口打开或点击刷新时，按需读取已有项目目录。可以筛选 Codex、Z Code、Claude CLI；同一规范化目录合并来源，失效目录不显示。选择只填表，必须手动点击“加入中控”。列表失败不影响手工填写。

| Client | Metadata read | Fields used |
| --- | --- | --- |
| Codex | Latest `state_*.sqlite` project tables; compatible `.codex-global-state.json` project registry | `projects.name`, `project_roots.path`; JSON `local-projects` names/rootPaths or saved workspace roots |
| Codex CLI fallback | `threads` in the latest state database, only when no project registry is available | Distinct `cwd` only; no titles, prompts or messages |
| Z Code | `~/.zcode/v2/tasks-index.sqlite` | Join `projects`, `project_roots`, `hosts`; local hosts and non-deleted projects only; names and root paths |
| Claude CLI | `~/.claude.json` | Keys of the `projects` dictionary only; settings values are ignored |

SQLite connections use `mode=ro` and `query_only`; active WAL remains readable. The reader does not migrate or write client databases. JSON reads are size-bounded. Only existing absolute local directories are returned; URL and UNC candidates are skipped. Remote projects and roots without a local directory are not guessed.

The normal client location is the current user's home. `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, and Z Code's `ZCODE_DATA_BASE_DIR` are respected. These are server-side locations, never arbitrary file paths supplied through HTTP. The catalog endpoint has the same loopback Host/Origin restrictions as the rest of Workhub.

Client metadata formats can change. One unavailable source does not disable the others, and manual directory input remains available. The public demo and development fixtures use synthetic metadata rather than a contributor's client files.

## Primary references

- [Codex project schema](https://github.com/openai/codex/blob/main/codex-rs/state/migrations/0049_projects.sql), [project runtime](https://github.com/openai/codex/blob/main/codex-rs/state/src/runtime/projects.rs), [legacy cwd schema](https://github.com/openai/codex/blob/main/codex-rs/state/migrations/0001_threads.sql).
- [Z Code storage paths](https://github.com/zai-org/ZCode/blob/main/packages/services/src/paths.ts), [project schema](https://github.com/zai-org/ZCode/blob/main/packages/services/src/project-storage/schema.ts), [project reader](https://github.com/zai-org/ZCode/blob/main/packages/services/src/project-storage/project-repository.ts).
- [Claude directory documentation](https://code.claude.com/docs/en/claude-directory), [project configuration](https://code.claude.com/docs/en/mcp).
