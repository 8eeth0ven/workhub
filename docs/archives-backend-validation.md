# 项目档案后端验收

新增 `archives.py`，通过增量 `archive_entries` SQLite 表保存项目会话元数据、提示词原文和图文产物。已有项目、工作事件、站点和评议表不被替换或清空。写入使用事务、唯一版本约束与内容指纹；重复登记同一内容幂等，变化后新增 revision，旧记录保持可读。

## 保存的内容及来源边界

- 会话记录包含项目、Agent、明确提供的会话 ID、标题、引用与来源。原始时间未知时为 null；`created_at` 是本次登记时间。工作日志中的 Agent 使用记录单独返回 `agent_usage`，带 `source: worklog`，不会据此制造会话 ID。
- 提示词保留用户明确提供的 UTF-8 文本，包括前后空白和换行，不重写或翻译。`original_hash` 对原输入计算 SHA-256，`content_hash` 对实际保存文本计算。`prompt_key` 关联同一提示词的版本，`derived_from` 只能指向同项目的归档 UUID，自动标为 derived，保留原版。
- 来源可明确为 unknown。用户提供的 source/source_ref 是可追溯引用，仍标为未独立核验。不会把文件存在、工作事件状态或模型返回成功解释成历史完整或已经发布。
- 不扫描 HOME、项目历史或 Agent 聊天数据库，不提供完整聊天导入字段。提示词原文和会话内容不会自动进入模型评议；本模块不调用模型。用户另行选择材料后的评议由对应流程处理。

识别到常见凭据格式时默认拒绝保存，并返回不含凭据值的错误。只有显式 `--redact-sensitive` / `redact_sensitive:true` 才保存脱敏派生副本：原始凭据不落盘，保留输入 hash，`redacted:true`，类型为 derived。该检查识别已覆盖的格式，不声称能判断任意未标记文本是否包含秘密。

## 图文包与图片核验

图文产物的状态默认 unknown，可明确登记 draft、reviewed、published；published 需要提供来源引用，不根据 HTML 或图片生成推断发布状态。`generated_at` 仅保存明确提供的生成时间，不能用登记时间替代。

只复制显式主 entry，以及它实际引用的本地图片、CSS 等允许资源。编辑版、文字稿等必须通过 `--file` 显式附带，然后同样跟随其资源引用；不会因 directory 是共享父目录而复制兄弟稿件。快照上限 256 个文件、80 MiB，每文件最多 25 MiB，不接收 JS、隐藏文件、任意目录列表或符号链接。每文件保存 SHA-256、大小和 MIME，主稿保存原文 hash，整包保存 manifest hash。原来源移动或删除后，归档快照仍可读取。

`image_count` 是主稿 `<img>` 槽位数，包含 data URI；编辑版不会让主稿数翻倍。`embedded_image_count` 是主稿内嵌图数，`attachment_image_count` 统计附带 HTML 图片，`image_file_count` 是唯一图片实体文件数。主稿 `verified_image_count`、`missing_image_count` 和 `unverified_image_count` 分别报告核验、缺失或无法核验数量。

本地图核验登记存在性及快照完整性；data URI 做 base64 或百分号解码，再核对 PNG、JPEG、GIF、WebP、SVG 格式签名。无效内嵌图保留失败状态，不补造正常结果；内嵌内容保留在原 HTML，不额外展开图片。外部图片不联网抓取，标为未核验。图片数量、来源时间、发表状态和文件存在性各自记录，互不推导。

只读阅读使用独立 loopback origin。服务只接受登记 manifest 中的路径，每次读取校验字节 hash，拒绝目录穿越、符号链接和快照篡改。CSP sandbox 禁止脚本、表单、外部连接和嵌套网页，仅允许该快照 origin 的样式/图片与 data 图片，避免把任意图文 JavaScript 放在具备后端写权限的同源页面执行。

## API、CLI 与运行资源

- `GET /api/archives?project_id=…&q=…`：各类最新档案、数量、搜索及工作日志 Agent 汇总。
- `GET /api/archives/projects`：项目与各类档案数，不伪造无记录项目的提示词。
- `GET /api/archives/prompt?id=…`：所选原文与同键版本历史。
- `GET /api/archives/artifact?id=…`：所选图文版本及同入口版本历史。
- `POST /api/archives/session|prompt|artifact`：同现有本机 Host/Origin、JSON、`X-Workhub-Request:1` 校验，最大请求体 128 KiB；无 CORS。
- `archive-session`、`archive-prompt --content-file`、`archive-artifact --entry --file`、`archive-list` 提供对应 CLI。项目必须事先登记；命令不自动扫其他目录。

后台服务的 runtime 包含 `archives.py`，只同步产品代码与资源，不复制个人档案或数据目录。图文预览随主服务关闭，不遗留监听端口。

## 实际验证

新增 10 项临时数据回归覆盖：未知来源及原始时间；真实工作日志不制造会话；提示词精确空白、hash、版本与重开持久化；敏感输入拒绝/显式脱敏；项目边界与十次并发 revision；共享目录只保留所选依赖；缺图及显式发表状态；data 图签名、主稿/编辑版计数、图文版本；源文件及快照 symlink/篡改拒绝；HTTP 写保护、搜索、历史与独立 CSP 阅读；CLI UTF-8 原文及运行包模块。

`python3 -m unittest discover -s tests -v` 全仓 80 项通过。`python3 scripts/audit_release.py` 检查通过，未发现发布阻断内容。测试仅使用临时目录、数据库、文件和本机端口；没有读取真实凭据、调用外部模型或向发布仓库导入私人会话、提示词、产物目录。真实历史导入与浏览器现场验收由主线程在本机完成。
