# 提供方适配验证记录

> 历史开发验证记录：测试专用文件保存在发布目录之外；以下测试命令说明当时实际执行的检查。

发布版新增 GLM、OpenAI-compatible、Anthropic native、Ollama 和显式本地 CLI 五类入口，共用 `build_prompt`、证据脱敏与 `normalize_result`。旧 GLM 文件和环境保留兼容；新私有配置优先 `llm.json`。公共状态只包含提供方类型、显示名、模型、是否配置、Key 数和端点主机，不提供凭据或 CLI 参数。

新增 `tests/test_providers.py` 的 14 项行为测试，覆盖：

- 新旧配置及通用环境优先级；切换厂商时不转发旧 GLM Key。
- OpenAI 请求路径、Bearer 认证、模型与输出参数；自定义 HTTPS 网关及关闭 JSON 模式。
- Anthropic 原生 `/messages`、`x-api-key`、API 版本、顶层 system 与 text-block 解析。
- 真实临时 loopback HTTP 服务收到的 Ollama `/v1/chat/completions`，无虚构 Authorization。
- 非回环明文 HTTP、含凭据 URL、模型/Key 占位符和错误配置的拒绝。
- 请求重试与响应大小上限、安全错误摘要和可配置并发上限。
- 临时 Python CLI 收到完整 stdin 评议合同；shell 元字符保持字面值。
- CLI stderr、参数与启动错误不进入公开错误；stdout 必须是 UTF-8 JSON。
- 默认 JSON 与显式 result 包装格式。
- stdout 超限实时终止，而非无限读取后检查。
- 超时停止本次命令进程组，其子进程不能继续写入临时验证标记。
- CLI 结果经过相同证据不足约束，配置变化使旧缓存不再复用。

已有 `tests/test_assessments.py` 增补浏览器 POST 不能指定 CLI command 的断言。其原有资料不足不评分、证据引用、历史过期、脱敏及失败不伪造结果等测试继续通过。

实际执行：

```sh
python3 -m py_compile assessments.py workhub.py
python3 -m unittest discover -s tests -v
```

该次发布副本全仓回归为 **58 项通过**，约 6.5 秒。其他模块后续新增测试时，总数可以增加。

这些测试仅使用模拟 opener、临时项目与数据库、临时 loopback HTTP 和自有 Python 子进程；未读取开发者已有真实 LLM Key，未调用外部模型、未载入个人项目数据库，未改变原应用服务。协议和包装契约有测试覆盖，但不等于每一个远端厂商、模型或用户 CLI 已完成真实端到端验证。API 和 CLI 运行边界详见 [提供方配置](providers.md)。
