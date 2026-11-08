[简体中文](project-archive.md) | [English](project-archive.en.md)

# 保留项目的 Agent、委托与发布物

工作记录回答“做了什么”；项目档案进一步保留执行者、会话来源、项目专属提示词及可复核的交付物。它将本轮任务的依据与成果关联起来，不需要复制完整聊天。

## 一次任务的最小档案

- 实际 Agent 与可核实的会话 ID、任务标题、来源引用。
- 用户原始任务提示词及其来源；按项目和用途保留版本。
- 重构后的执行提示词另标 `derived` 并关联原始 UUID，原文不被改写覆盖。
- 发布物入口、编辑版、图片和检查说明，以及实际有证据支持的状态。

缺少历史来源时保留未知。不从文件目录、文章风格或后来整理文件的 Agent 推断创作者。只保存当前任务需要的原话，不保留完整会话、凭据或私有环境。

## CLI

以下变量由实际项目和任务提供；命令从 Workhub 仓库运行：

```sh
python3 workhub.py register --path "$WORKHUB_PROJECT_DIR"
python3 workhub.py archive-session --project "$WORKHUB_PROJECT_DIR" \
  --agent codex --session-id "$WORKHUB_SESSION_ID" --title "本轮实现" \
  --source user-provided --source-ref "task-note.txt:1"

python3 workhub.py archive-prompt --project "$WORKHUB_PROJECT_DIR" \
  --title "项目原始委托" --content-file /path/to/task-prompt.txt \
  --agent codex --session-id "$WORKHUB_SESSION_ID" \
  --purpose implementation --record-type original --prompt-key implementation \
  --source user-provided --source-ref "task-note.txt:1"
```

保存返回的提示词 UUID，作为后续 `--derived-from` 或发布物的 `--prompt-id`。`prompt-key` 是项目内同一用途的稳定键；记录变化时追加 revision，保留旧版本；完全相同的再次归档复用旧记录。派生版本示例：

```sh
python3 workhub.py archive-prompt --project "$WORKHUB_PROJECT_DIR" \
  --title "后续执行提示词" --content-file /path/to/derived-prompt.txt \
  --record-type derived --prompt-key implementation \
  --derived-from "$WORKHUB_ORIGINAL_PROMPT_ID"
```

原文包含凭据时默认拒绝。显式选择 `--redact-sensitive` 才会保存标为 derived 的脱敏副本，记录原输入哈希与保存文本哈希；原始凭据不落盘。脱敏内容不能声称是逐字原话。没有真实会话 ID 时先保存已知来源，不编造 ID 填表。

从文件或记忆重构的提示词也必须注明为派生版本，不能当成原始用户输入。原文或原始 UUID 缺失时如实保留缺口，不补造“原话”或关联 ID。

## 发布物与状态

```sh
python3 workhub.py archive-artifact --project "$WORKHUB_PROJECT_DIR" \
  --title "版本更新图文稿" --directory "$WORKHUB_PUBLICATION_DIR" \
  --entry article.html --file editor.html --version release-1 --kind publication --status draft \
  --source local-delivery --source-ref checks.md \
  --agent codex --session-id "$WORKHUB_SESSION_ID" \
  --prompt-id "$WORKHUB_ORIGINAL_PROMPT_ID" --image images/cover.png

python3 workhub.py archive-list --project "$WORKHUB_PROJECT_DIR"
```

`--entry` 是目录内的主入口，归档仅沿其本地图片/CSS依赖收集资源；用可重复的 `--file` 显式附带编辑版或纯文档，它们各自的依赖也会保留。`--image` 可重复指定图片，`--prompt-id` 可关联多个提示词。目录中的兄弟文章不会被自动收集或公开。允许类型为 HTML、CSS、图片、MD、TXT、PDF；每次最多 256 文件、80 MiB。不收 JS、隐藏文件或 `.env`，所以不把该功能当作任意动态应用的全量备份。

主稿、编辑版和正文片段只算同一篇文章；系列索引、目录与仓库建议不计为正文。图片是否齐全与稿件是否发布是不同的问题。

| 状态 | 需要的依据 |
| --- | --- |
| `unknown` | 默认；缺少足够记录时不推断生成或平台发布状态。 |
| `draft` | 已明确是本地草稿或待交付材料。 |
| `reviewed` | 有实际检查记录，并注明只覆盖哪些内容。 |
| `published` | 有真实平台发布凭证；必须显式给出 `source-ref`。 |

历史文件夹的日期仅能充当批次标签，除非有生成记录佐证。没有发布凭证时不能把文件存在写成“已发布”，也不能反过来断言“从未发布”。

## 深度评议如何使用档案

每轮按“具体主张 → 原始依据 → 反例/缺口 → 验证动作 → 再评议”推进。先说明主张和适用范围，再指向实际来源；指出证据不支持的部分和替代解释；将问题落实为可执行的检查；检查完成后记录结果，再更新评议。保留旧版本与结论变化的理由。

资料不足时留空评分、指出所缺材料；模型成功调用或返回有效 JSON 不等于项目验收通过。把建议写入档案，也不表示建议已经执行。

原始提示词默认不进入模型评议请求。用户需要它作为背景时，先选择必要、适合发送的摘要；本地存储不等于外发授权。详细数据边界见 [隐私说明](privacy.md)，Agent 执行规范见 [项目档案协议](../skill/agent-workhub/references/project-archive.md)。
