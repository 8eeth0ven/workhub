[简体中文](providers.md) | [English](providers.en.md)

# Configure a model API or local CLI

Workhub uses the same Socratic review instructions and evidence checks across five adapters. Protocol support does not mean every provider, model or CLI has passed a live end-to-end test. Release tests use simulated responses, temporary local HTTP servers and temporary Python wrappers; they do not call real paid models.

The portal's language selector changes the interface while preserving the original language of project material and review text. It does not switch providers, edit configuration or call a model again to translate a review.

| `provider` | Request or wrapper protocol | Authentication | Boundary |
| --- | --- | --- | --- |
| `glm` | OpenAI-compatible `chat/completions`, with GLM plan-error handling | Bearer API key | Choose the standard or CodingPlan route for your own plan. |
| `openai` | OpenAI-compatible `chat/completions` | Bearer API key | The service must support the selected model parameters and JSON mode. |
| `anthropic` | Native `/v1/messages`; reads `text` blocks | `x-api-key`, `anthropic-version` | Does not send OpenAI's `response_format`. |
| `ollama` | OpenAI-compatible `/v1/chat/completions` | A local service usually needs no key | Plain HTTP is allowed only for localhost or a loopback IP. |
| `cli` | A local command wrapper explicitly configured by the user | The wrapper manages its own authentication | Process-group management currently supports macOS/Linux; the wrapper must follow the contract below. |

## Private configuration and precedence

Copy a suitable [example](../examples) to `llm.json` in the data directory, then replace `YOUR_API_KEY`, `MODEL` and any command path. Placeholder values are not treated as usable keys or models. The default directory is `~/.local/share/agent-workhub`; override it with `AGENT_WORKHUB_HOME` or the root command's `--data-dir` option.

```sh
mkdir -p "$HOME/.local/share/agent-workhub"
cp examples/provider-openai.json "$HOME/.local/share/agent-workhub/llm.json"
chmod 600 "$HOME/.local/share/agent-workhub/llm.json"
```

Fill in credentials using a local editor, and keep the real configuration out of Git. Configuration must not be readable by other users: use `0600` even for a CLI or Ollama configuration without a key. A valid configuration does not establish that a command exists, a service is running or a request will succeed.

Configuration files are selected as a whole. If `llm.json` exists, it is used; only when it is absent does Workhub fall back to `glm.json`. The two files are not merged. A legacy `glm.json` without a `provider` field is still interpreted as GLM.

These environment variables override the corresponding fields in the selected file:

| Environment variable | Configuration field |
| --- | --- |
| `WORKHUB_LLM_PROVIDER` | `provider` |
| `WORKHUB_LLM_API_KEYS` or `WORKHUB_LLM_API_KEY` | `api_keys` or `api_key` |
| `WORKHUB_LLM_BASE_URL` | `base_url` |
| `WORKHUB_LLM_MODEL` | `model` |
| `WORKHUB_LLM_REASONING_EFFORT` | `reasoning_effort` |
| `WORKHUB_LLM_MAX_TOKENS` | `max_tokens` |

Multiple keys can be supplied as a JSON string array, or separated by commas or whitespace. At most three are used. The plural environment variable takes precedence over the singular one. Only the `glm` provider falls back to `GLM_API_KEYS`, `GLM_API_KEY`, `GLM_BASE_URL`, `GLM_MODEL`, `GLM_REASONING_EFFORT` and `GLM_MAX_TOKENS`; changing providers must not forward GLM credentials to a different service.

When no new provider has been selected, there is no `llm.json`, and legacy GLM configuration or environment variables exist, legacy GLM behavior is preserved. A new configuration defaults to OpenAI-compatible mode, but still requires a usable model and key.

Public API endpoints use HTTPS and require an explicit compatible gateway; redirects are not followed. Ollama accepts loopback HTTP. OpenAI-compatible HTTP requires `allow_local_http: true` and a literal loopback IP; the interface saves this option for an explicitly entered local address. Public status never contains API keys; Model access shows only redacted editable configuration.

## API adapters

Examples are provided in `examples/provider-openai.json`, `provider-glm.json`, `provider-anthropic.json`, `provider-ollama.json` and `provider-cli.json`.

For an OpenAI-compatible service, `base_url` is the API root; the adapter appends `/chat/completions`. For the official OpenAI endpoint, this adapter defaults to `max_completion_tokens`; other compatible endpoints default to `max_tokens`. Set `token_parameter` explicitly to either of those names if needed. The adapter does not send `temperature` by default, avoiding an unnecessary fixed sampling parameter for models that do not support it.

Set `json_mode: false` to omit `response_format`. The prompt still requests JSON, and the response must pass the same structural validation. If a model does not support JSON output or a selected parameter, use an appropriate model, gateway configuration or wrapper. Workhub does not guess new parameter combinations and retry indefinitely. This adapter does not implement the Responses API, tool calls or streaming.

GLM retains the standard `/api/paas/v4` base and the optional `/api/coding/paas/v4` base. Availability depends on the user's plan. GLM uses an output budget of at least 8192 tokens; the GLM-5.2/5.3 families receive the configured `reasoning_effort` rather than forcibly disabling reasoning. Error `1113` indicates unavailable resources and `1310` indicates exhausted plan quota; neither is retried. Error `1302` receives bounded concurrency backoff. Keys with quota or authentication errors are temporarily avoided while other configured keys are tried.

Anthropic requests use top-level `system`, user `messages` and `max_tokens`. The adapter joins response `text` blocks from `content`, ignoring thinking and other non-text blocks. The example explicitly pins `anthropic_version`; change it if your endpoint needs another compatible version. This adapter sends neither `temperature` nor OpenAI JSON parameters.

An Ollama model must already be available on the local service. When no key is configured, the adapter does not invent an `Authorization` header. Connecting to Ollama does not establish that the chosen model can produce a valid structured review before the timeout; initial loading or slower hardware may exceed it.

## Local CLI wrapper contract

Model access includes native adapters for detected Codex, Claude Code and Z Code clients. They use noninteractive invocation, read-only or plan modes, a temporary directory, and JSON-result extraction; detection does not prove login or connectivity. Z Code uses its current model. Other clients can use an advanced custom wrapper following the contract below. Commands explicitly saved by a trusted local user run with that user's permissions; this is local configuration, not a general shell endpoint.

`command` must be a JSON string array, for example `["python3", "/absolute/path/to/wrapper.py"]`. It is executed without a shell: `$VAR`, `~`, pipes, redirections and command substitutions are not expanded. Use an executable's real path or a command available on `PATH`. Pass credentials through the wrapper's own secure configuration or environment rather than command arguments. Optional `cwd` must name an existing directory; it defaults to the data directory. Project material cannot modify the command or its arguments.

stdin is one UTF-8 JSON object, terminated by EOF:

```json
{
  "protocol": "workhub.review.v1",
  "system": "Complete review rules, five dimensions and the JSON response contract",
  "evidence": {
    "project_id": "example",
    "project_name": "Example",
    "evidence": [{"id": "project:example", "kind": "project", "text": "Necessary project material"}],
    "sufficient_evidence": false,
    "source_fingerprint": "Evidence fingerprint"
  }
}
```

The wrapper should use `system` as review instructions and `evidence` as source material when calling its configured model. stdout must contain exactly one UTF-8 JSON object with `verdict`, `headline`, `summary`, `strengths`, `assumptions`, `questions`, `blind_spots`, `next_actions`, `dimensions` and `confidence`. The exact field requirements arrive in stdin's `system` value. `dimensions` must contain `goal`, `evidence`, `verification`, `risks` and `next_steps`; each has a `score` from 0 to 4 or null, a `reason`, and `evidence_ids` referring to IDs present in the input.

The default `output_format: "json"` reads that object directly. If the wrapper always emits `{"result": {...review object...}}`, explicitly set `output_format: "result"`. Chat transcripts, progress logs, Markdown code fences, login prompts and streaming events are not valid stdout results; the wrapper must extract the review. stderr is discarded, not sent to the model or displayed in the portal. Debug the wrapper separately on your machine and manage its logs deliberately.

A nonzero exit, invalid JSON, timeout or oversized output fails the task without producing a normal review. A timeout terminates only the Unix process group Workhub created for that invocation; it does not stop other programs by process name. stdout is read in bounded chunks, and the command is terminated as soon as the output limit is exceeded, rather than buffering an unlimited response first.

## Limits, concurrency and verification

`timeout_seconds` accepts 0.1–60 and defaults to 55. Each HTTP attempt and each CLI invocation is bounded. `max_retries` accepts 0–2 and applies only to transient HTTP failures such as certain 429/5xx responses. Network errors, authentication failures and CLI commands are not retried indefinitely. Finite fallback across multiple keys can increase the total review time; time spent in a background queue is separate from a single-request timeout.

`max_output_bytes` accepts 1024–8388608 and defaults to 2097152. `concurrency` accepts 1–3; CLI and Ollama default to 1, while keyed APIs default to at most 3. The configured per-process limit and the one-request-per-key restriction both apply. Unix file locks coordinate the same key across CLI and portal processes sharing a data directory. Non-Unix backends retain thread-level API limits, but the local CLI adapter is not enabled there.

Changing the provider, endpoint or CLI wrapper configuration causes the next explicit review to generate a new result. A latest result can be reused when both configuration and evidence are unchanged. The same insufficient-evidence behavior, evidence-ID filtering, version history and stale-result indicators apply to every provider. Successfully parsing JSON does not bypass review-structure validation.

Inspect read-only configuration status with `python3 workhub.py review-list`. Request a real review with `python3 workhub.py review --project /absolute/project/path` or `review --all`. The API path remains `/api/reviews`; changing providers does not require changing the frontend route.

Protocol references: [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [Anthropic Messages](https://platform.claude.com/docs/en/api/messages), [Anthropic API versions](https://platform.claude.com/docs/en/api/versioning), [Ollama's OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility).
