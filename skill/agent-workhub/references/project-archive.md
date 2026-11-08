# 项目档案协议

项目档案把“谁执行、收到什么委托、交付了什么、证据在哪里”关联起来。仅存与当前任务直接有关的输入和产物，不自动搬运完整聊天、私有环境或其他项目历史。CLI 的 `--project` 使用该项目的真实绝对路径。

## 会话与原始委托

1. 记录实际 Agent 名称、可核实的会话 ID、任务标题和来源引用。无法核实时保留未知，不用迁移者身份、当前文件位置或文章风格倒推创作者。
2. 为项目的具体用途保存原始任务提示词，例如“实现入口”“验证计划”“版本宣发”。原话来自当前请求、用户指定文件或经授权提取的必要片段，并记录来源。不要把系统自动注入的工具说明当成用户委托。
3. 按项目和用途使用稳定的 `prompt-key`。后续重构另存 `derived`，其 `derived-from` 引用原档案的 UUID；同键记录发生变化时追加 revision，旧版本保留；完全相同的再次归档复用旧记录。原始提示词与给下一个 Agent 的执行提示词应明确区分。
4. 原文含凭据时默认拒绝归档，不把凭据作为“保真”要求写入数据库。显式使用 `--redact-sensitive` 会保存标记为 derived 的脱敏副本、原输入哈希和保存文本哈希，不保存原始凭据；必须说明它不是逐字原文。

已安装全局命令时可替换下列 `python3 workhub.py` 入口；命令从工作台仓库执行，变量由实际任务提供：

```sh
python3 workhub.py register --path "$WORKHUB_PROJECT_DIR"
python3 workhub.py archive-session --project "$WORKHUB_PROJECT_DIR" \
  --agent codex --session-id "$WORKHUB_SESSION_ID" --title "本轮任务" \
  --source user-provided --source-ref "task-note.txt:1"

python3 workhub.py archive-prompt --project "$WORKHUB_PROJECT_DIR" \
  --title "实现任务原始委托" --content-file /path/to/task-prompt.txt \
  --agent codex --session-id "$WORKHUB_SESSION_ID" --purpose implementation \
  --record-type original --prompt-key implementation \
  --source user-provided --source-ref "task-note.txt:1"

python3 workhub.py archive-prompt --project "$WORKHUB_PROJECT_DIR" \
  --title "后续执行版本" --content-file /path/to/derived-prompt.txt \
  --record-type derived --prompt-key implementation \
  --derived-from "$WORKHUB_ORIGINAL_PROMPT_ID"
```

`WORKHUB_ORIGINAL_PROMPT_ID` 来自原始 `archive-prompt` 返回值。没有真实会话 ID 时，可先保存已知 Agent、提示词和来源；不要为了满足 `archive-session` 的必填项而编造会话。

根据文件或记忆重构的提示词必须标为派生/重构并写明来源。找不到原文就承认缺失，不生成一份“原话”来补档，也不编造 `derived-from` UUID。

## 发布物保留与状态

公众号稿或其他发布物应保留主入口 HTML、编辑版、图片源和实际执行过的检查说明，并关联 Agent、会话与提示词。主稿和编辑版是同一篇正文的不同表现，不重复计为两篇；目录页、索引页和仓库建议不是正文。

```sh
python3 workhub.py archive-artifact --project "$WORKHUB_PROJECT_DIR" \
  --title "本轮更新图文稿" --directory "$WORKHUB_PUBLICATION_DIR" \
  --entry article.html --file editor.html --version release-1 --status draft --kind publication \
  --source local-delivery --source-ref "checks.md" \
  --agent codex --session-id "$WORKHUB_SESSION_ID" \
  --prompt-id "$WORKHUB_ORIGINAL_PROMPT_ID" --image images/cover.png

python3 workhub.py archive-list --project "$WORKHUB_PROJECT_DIR"
```

归档以主入口为起点，只收集其本地图片/CSS依赖；需要保留编辑版或纯文档时，用可重复的 `--file` 显式指定，它们各自引用的资源也会保留。不会因为选择某个目录就收集兄弟稿件或公开整个目录。允许类型包含 HTML、CSS、图片、Markdown、文本和 PDF；单次上限为 256 个文件、80 MiB，不收集 JS、隐藏文件或 `.env`。快照不等于全项目备份；缺少图片或不支持的资源需要如实处理，不能把快照成功冒充内容验收。

状态按证据使用：

| 状态 | 含义 |
| --- | --- |
| `unknown` | 默认状态；生成或发布情况缺少足够记录。历史文件存在本身不足以断言是否已发布。 |
| `draft` | 已知为本地草稿/待交付内容，有对应任务或产物依据。 |
| `reviewed` | 有明确的检查记录；应说明检查范围，不代表平台发布。 |
| `published` | 有实际平台发布凭证，必须显式提供 `source-ref`；不能仅凭 HTML、截图或文件名标记。 |

导入历史产物时，日期若仅来自文件夹名称，要标注为批次标签；文件 mtime 不自动等于生成日期，迁移会话不自动等于创作会话。找不到来源或发布凭证就保留未知，后续有证据再补充。

## 档案与深度评议

档案提供可追溯材料，不自动让主张成立。重要里程碑按“具体主张 → 原始依据 → 反例/缺口 → 验证动作 → 再评议”闭环。每个未决问题落实为能执行的检查，完成后记录真实结果，再用新证据更新评议。

无法判断时保留未知或未评分。模型调用成功、JSON 结构有效、归档成功、图片齐全都不能替代项目验收或平台发布。旧版本及其理由保留；修订后的提示词或后续汇总不得覆盖当时的原始委托。

原始提示词默认不发给评议器。若用户需要模型参考其中内容，先选必要且适合发送的摘要，注明来自原始还是派生版本；不要把“已经本地归档”当成外发许可。另见 [项目评议协议](socratic-review.md)。
