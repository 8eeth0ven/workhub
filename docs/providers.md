[简体中文](providers.md) | [English](providers.en.md)

# 配置模型 API 或本地 CLI

Workhub 使用同一套苏格拉底式评议提示和证据检查，提供五种适配入口。适配器的协议兼容，不等于每一家厂商、每个模型或每个 CLI 都已完成真实端到端测试。发布测试只使用模拟响应、本机临时 HTTP 服务和临时 Python 包装器，没有调用真实付费模型。

门户顶部语言选择只切换界面，保留项目资料与评议正文的原始语言；不会切换 provider、修改配置或为了翻译而重新调用模型。

| provider | 请求或包装协议 | 认证 | 边界 |
| --- | --- | --- | --- |
| `glm` | OpenAI 兼容 `chat/completions`，保留 GLM 套餐错误处理 | Bearer API Key | 根据自己的套餐选择普通或 CodingPlan 路由 |
| `openai` | OpenAI 兼容 `chat/completions` | Bearer API Key | 模型参数和 JSON 模式须由所用服务支持 |
| `anthropic` | 原生 `/v1/messages`，解析 `text` blocks | `x-api-key`、`anthropic-version` | 不发送 OpenAI 的 `response_format` |
| `ollama` | OpenAI 兼容 `/v1/chat/completions` | 本机通常不需要 Key | HTTP 只允许 localhost 或回环 IP |
| `cli` | 用户自行配置的本机命令包装器 | 由包装器处理自己的认证 | 当前进程组管理支持 macOS/Linux；CLI 必须满足下文约定 |

## 私有配置与优先级

将合适的 [示例](../examples) 复制为数据目录下的 `llm.json`，替换 `YOUR_API_KEY`、`MODEL` 和命令路径。示例占位符不会被当成可用 Key 或模型。默认目录为 `~/.local/share/agent-workhub`，可用 `AGENT_WORKHUB_HOME` 或根命令参数 `--data-dir` 指定。

```sh
mkdir -p "$HOME/.local/share/agent-workhub"
cp examples/provider-openai.json "$HOME/.local/share/agent-workhub/llm.json"
chmod 600 "$HOME/.local/share/agent-workhub/llm.json"
```

使用本机编辑器填写凭据，不将真实配置加入 Git。配置文件不能对其他用户开放读取；即使没有 Key 的 CLI 或 Ollama 配置，也使用 `0600`。命令不存在或服务未运行时，配置成功不代表请求已经成功。

配置文件按整个文件选择：存在 `llm.json` 就使用它，仅在缺失时回退 `glm.json`，两份文件不会混合。旧 `glm.json` 没有 provider 字段时仍视为 GLM。

以下环境变量覆盖所选文件中的同名设置：

| 环境变量 | 配置字段 |
| --- | --- |
| `WORKHUB_LLM_PROVIDER` | `provider` |
| `WORKHUB_LLM_API_KEYS` 或 `WORKHUB_LLM_API_KEY` | `api_keys` 或 `api_key` |
| `WORKHUB_LLM_BASE_URL` | `base_url` |
| `WORKHUB_LLM_MODEL` | `model` |
| `WORKHUB_LLM_REASONING_EFFORT` | `reasoning_effort` |
| `WORKHUB_LLM_MAX_TOKENS` | `max_tokens` |

多个 Key 可用 JSON 字符串数组、逗号或空白分隔，最多使用三个。复数变量优先于单数变量。仅在 provider 为 `glm` 时回退 `GLM_API_KEYS`、`GLM_API_KEY`、`GLM_BASE_URL`、`GLM_MODEL`、`GLM_REASONING_EFFORT` 和 `GLM_MAX_TOKENS`，避免切换到别的厂商时误发送 GLM 凭据。

未选择新 provider、没有 `llm.json` 且存在旧 GLM 配置或环境时，保持旧 GLM 行为；全新配置默认选择 OpenAI-compatible，但必须自行填写可用模型和 Key。

公网 API 地址使用 HTTPS，自定义兼容网关须明确配置，不跟随 HTTP 重定向。Ollama 可使用回环 HTTP；OpenAI-compatible 仅在 `allow_local_http: true` 且地址为字面回环 IP 时接受 HTTP，界面会为用户明确填写的本机地址保存此选项。API Key 不会出现在公共状态；模型设置只显示脱敏后的可编辑配置。

## API 配置

五类示例分别在 `examples/provider-openai.json`、`provider-glm.json`、`provider-anthropic.json`、`provider-ollama.json` 和 `provider-cli.json`。

OpenAI-compatible 的 `base_url` 为 API 根路径，适配器补充 `/chat/completions`。官方 OpenAI 默认使用 `max_completion_tokens`；其他兼容服务默认使用 `max_tokens`。`token_parameter` 可以显式设为这两者之一。默认不发送 `temperature`，避免向不支持该参数的推理模型发送固定采样值。`json_mode: false` 可禁止发送 `response_format`；仍会要求模型输出 JSON，返回结果必须通过相同结构检查。如果模型不支持 JSON 输出或所选参数，应改用适用模型、网关参数或包装器；不会自动猜测参数并无限重试。该适配器没有实现 Responses API、工具调用或流式协议。

GLM 保留普通 `/api/paas/v4` 与可自行选择的 `/api/coding/paas/v4` 基址，是否可用由用户套餐决定。GLM 输出预算至少 8192 tokens；GLM-5.2/5.3 系列按配置发送 `reasoning_effort`，不强制关闭思考。错误 `1113`（资源不可用）与 `1310`（套餐额度用尽）不重试；`1302` 并发限制仅作有限退避。额度或鉴权异常的 Key 会暂时避开，尝试其他已配置 Key。

Anthropic 使用顶层 `system`、用户 `messages` 和 `max_tokens`，从响应的 `content` 中拼接 `text` 块，忽略思考等非文本块。示例明确固定 `anthropic_version`；需要不同兼容版本时自行修改。此适配器不发送 `temperature` 或 OpenAI JSON 参数。

Ollama 的模型名必须是本机已经可用的模型。没有配置 Key 时不会发送虚构的 `Authorization`。能连接本机 Ollama，不代表所选模型能在时限内返回符合评议要求的结构化内容；首次加载或较慢硬件可能超时。

## 本地 CLI 的包装约定

模型接入内置已检测到的 Codex、Claude Code、Z Code 适配器，使用非交互调用、只读或计划模式、临时目录及 JSON 输出提取；检测到程序不代表已经登录或连通。Z Code 使用客户端当前模型。其他客户端可在高级设置保存遵循下述协议的自定义包装器；这些是可信本机用户的配置，不是通用 shell 执行接口。

`command` 必须是 JSON 字符串数组，例如示例中的 `['python3', '/absolute/path/to/wrapper.py']`（配置文件本身使用 JSON 双引号）。不经过 shell，不会自动展开 `$VAR`、`~`、管道、重定向或命令替换。使用可执行文件的真实路径或 PATH 中可用的命令；凭据通过包装器自己的安全配置或环境传递，避免写进参数。`cwd` 可指定现有目录，缺省为数据目录，命令本身和每个参数不会被工作项目自动修改。

stdin 是一个 UTF-8 JSON 对象，到 EOF 结束：

```json
{
  "protocol": "workhub.review.v1",
  "system": "完整的评议规则、五维评分和JSON返回约定",
  "evidence": {
    "project_id": "example",
    "project_name": "Example",
    "evidence": [{"id": "project:example", "kind": "project", "text": "必要项目资料"}],
    "sufficient_evidence": false,
    "source_fingerprint": "摘要指纹"
  }
}
```

包装器应把 `system` 作为评议规则，把 `evidence` 作为资料，调用自己配置的模型。stdout 只输出一个 UTF-8 JSON 对象，包含 `verdict`、`headline`、`summary`、`strengths`、`assumptions`、`questions`、`blind_spots`、`next_actions`、`dimensions` 和 `confidence`。精确字段要求随 stdin 的 `system` 一并给出；`dimensions` 必须含 `goal/evidence/verification/risks/next_steps` 五项，每项的 `score` 为 0–4 或 null、`reason` 为说明、`evidence_ids` 引用输入中存在的 ID。

默认 `output_format: "json"` 直接读取该对象。若包装器固定输出 `{"result": {...评议对象...}}`，可显式设为 `"result"`。多段聊天文本、进度日志、Markdown 代码围栏、登录提示及流式事件不能直接作为 stdout 结果；由包装器提取。stderr 被丢弃，不会被转交模型或显示在页面中；调试包装器时在本机单独运行，并控制自己的日志。

退出码非零、JSON 无效、超时或输出超限时，任务失败且不生成正常评价。超时会终止 Workhub 为本次命令创建的 Unix 进程组，不按进程名停止其他程序。stdout 持续按块读取并限制内存，超过上限立即终止本次命令，不是无限读取后再检查大小。

## 限制、并行与验证

`timeout_seconds` 范围 0.1–60，默认 55；每次 HTTP 尝试和每次 CLI 命令都受限制。`max_retries` 范围 0–2，仅用于 HTTP 的暂时性 429/5xx 等错误；网络错误、鉴权错误和 CLI 不会无限重试。多个 Key 的有限回退会增加整项任务的总耗时，后台队列时间不等同于单次请求时限。

`max_output_bytes` 为 1024–8388608，默认 2097152。`concurrency` 为 1–3，CLI 与 Ollama 默认 1，带 Key 的 API 默认最多 3。单进程配置并行上限与每 Key 一请求共同生效；Unix 文件锁协调同一数据目录中 CLI 与 hub 的同 Key 请求。非 Unix 后端仍有线程级 API 限制，但本地 CLI 适配目前不启用。

切换 provider、端点或 CLI 包装配置后，下一次显式评议会重新生成结果；相同配置和资料的最新结果可复用。现有的资料不足不评分、证据 ID 过滤、版本历史及过期提醒对所有 provider 都生效。不会因成功解析一个 JSON 就跳过评议结构验证。

验证只读配置状态：`python3 workhub.py review-list`。真实评议：`python3 workhub.py review --project /absolute/project/path` 或 `review --all`。API 路径仍为 `/api/reviews`，不需要为不同 provider 改前端调用方式。

协议资料：[OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)、[Anthropic Messages](https://platform.claude.com/docs/en/api/messages)、[Anthropic API 版本](https://platform.claude.com/docs/en/api/versioning)、[Ollama OpenAI 兼容接口](https://docs.ollama.com/api/openai-compatibility)。
