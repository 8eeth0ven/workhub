---
name: agent-workhub
description: 为 Codex、Z Code、Claude Code 共用的本机门户记录项目工作、接入可内嵌切换的本地网站，并复用 radar、library、brief 网页模板。适用于已接入项目的工作记录、网站接入、统一设计体系复用和可配置模型的苏格拉底项目评议。
---

# 统一项目工作记录

这是项目工作记录协议。项目身份是其真实绝对目录，同一项目由多个 Agent 处理时共用项目记录，但每次任务必须使用独立的 `run-id`。记录是真实已发生的工作；不能把计划写成成果，不能从项目文件存在推断其历史工作已完成。

## 开工与进展

本机全局接入后，命令入口是 `~/.local/bin/agent-workhub`；也可用 Python 3 执行本文件同目录的 `scripts/report.py`。后者会自动找到此技能所属仓库的后端，无需网站正在运行。

如果仅做了项目级接入而没有全局命令，把下列示例中的命令入口替换为 `python3` 加项目规则里给出的 `scripts/report.py` 绝对路径。

项目类任务开始前先登记项目，然后记一条开工事件。以下示例从项目根目录执行；为当前任务生成一次 UUID，并在后续命令中复用它。Agent 名称使用实际客户端，如 `codex`、`zcode`、`claude`。

```sh
WORKHUB_RUN_ID=$(python3 -c 'import uuid; print(uuid.uuid4())')
"$HOME/.local/bin/agent-workhub" register --path "$PWD"
"$HOME/.local/bin/agent-workhub" record --project "$PWD" --agent codex --run-id "$WORKHUB_RUN_ID" --status running --task "当前任务的简短名称" --summary "开始处理：任务的具体目标"
```

有实质进展时再记 `running` 事件；完成时记 `completed`；遇到外部阻塞记 `blocked`；用户暂停时记 `paused`。复用本任务的 `run-id`，不结束其他 Agent 的任务。不要每次工具调用都记一条。每个独立子 Agent 使用自己的任务 ID，主 Agent 负责记录最终汇总。

```sh
"$HOME/.local/bin/agent-workhub" record --project "$PWD" --agent codex --run-id "$WORKHUB_RUN_ID" --status completed --task "当前任务的简短名称" --summary "已完成的具体行为和结果" --details "证据：文件或产物路径；验证：实际执行的检查及结果；剩余：未完成内容或下一步。"
```

这里的 `completed` 表示该次任务完成，不表示整个项目从此完工。最终对用户的回复仍应说明结果，写入看板不能替代交付。若 shell 会话不连续，保存并显式传递同一个任务 ID；不要在每次记录时重新生成。

## 接入更多项目

在此技能所属仓库运行 `python3 scripts/install.py --project /项目/绝对路径`，为指定项目追加 `AGENTS.md`、`CLAUDE.md` 的必读入口并登记项目。使用 `--global` 可安装本用户的全局入口；原有规则会保留，修改前备份，重复执行不会重复追加。`--dry-run` 只查看计划。

仅通过这些客户端实际加载的全局规则或项目规则生效。其他机器、云端 Agent 或未读取规则的客户端，需同步此仓库和项目入口并重新运行安装器；本机安装不能强制远程客户端读取文件。既有会话未必重新载入新增全局规则，下一次会话应先确认入口可见。

## 项目网站与模板复用

项目包含网站时，除记录工作进展，还必须登记实际网站，让用户在主门户中直接内嵌切换。新建信息收集站、看板、资料库或项目简报前，先查看门户的模板库及此仓库的 `templates/`；用户指定模板时按其选择，否则根据任务选合适布局：

- `radar`：信息收集、动态跟踪、项目看板。
- `library`：资料库、参考资源与内容索引。
- `brief`：项目简报、阶段成果与结构化说明。

左侧导航已有页面标题时，内容区不再重复大标题、英文口号或说明横幅；直接展示内容，必要操作并入紧凑工具栏，减少顶部留白。

三套模板只改变信息布局，共用同一字体、字阶、配色、间距、控件与导航规范。新建或修改项目网站前，先读 [统一设计规范](references/design-system.md)，以 `static/design-system.css` 为唯一设计来源；不要为每个项目重新换皮。实际内容、栏目和数据源由用户任务决定。已有静态目录站由门户附加统一阅读主题；有独立后端的网站在其源码中接入主题，保持原有交互。`--template` 只登记分类，不会改写网站或生成页面。

先将 `WORKHUB_REPO` 设为此技能所属仓库的真实绝对路径（本文件所在目录的上两级）；生成模板与接入网站是两个独立步骤：

```sh
python3 "$WORKHUB_REPO/scripts/site_templates.py" create --template radar --output /项目/绝对路径/网页 --name "网站名称"
python3 "$WORKHUB_REPO/scripts/install.py" --project /项目/绝对路径 --site-dir /项目/绝对路径/网页 --site-name "网站名称" --template radar
```

已有静态网站使用 `--site-dir` 指定包含 `index.html` 的目录；已有开发服务器使用 `--site-url` 指定实际已运行的本机 HTTP(S) 地址，两者互斥：

```sh
python3 "$WORKHUB_REPO/scripts/install.py" --project /项目/绝对路径 --site-url http://127.0.0.1:3000 --site-name "开发网站"
```

登记后在门户中验证网站能加载、切换和交互。`localhost` 指访问者所在电脑，不能声称它在其他机器或云端天然可用。若自有本机网站因 `X-Frame-Options` 或 CSP 拒绝内嵌，调整该站允许门户来源的配置，或改接静态目录；不增加通用绕过代理。对未启动的开发服务器应如实说明需要启动，不能把登记成功当成网站可用。

## 中控台项目评议

用户启用模型评议后，在重要里程碑记录后按 [项目评议协议](references/socratic-review.md) 调用其配置的模型；查看目标、假设、证据、反例、后果和问题边界，区分有证据的发现与待核实问题。支持云端 API、本机模型或显式配置的 CLI，以实际后端配置为准；未配置时不冒充模型输出。对“资料不足”的项目补充真实背景，不编造分数或成果；后续记录会让旧评价过期。

## 中英文界面约定 / Bilingual interface rules

门户和可复用模板统一支持简体中文与 English，沿用同一套设计体系，不能为不同语言或不同站点另换皮肤。语言入口放在紧凑顶部工具栏，选择保存在浏览器本地并在刷新后恢复；切换时保留当前页面、选中网站、筛选与未提交输入。模板按门户的语言同步协议更新界面，已有第三方站点保留自己的语言行为。

只翻译导航、控件、固定状态/维度标签、空状态和界面提示；项目名称、工作记录、网站正文和已有模型评议保留原文。不要为了界面切换而重写数据、重新请求模型、改变 CLI/API 协议或增加重复的大页头。维护文档时保留中英文互跳入口，技术边界和隐私说明在两种语言中一致。

Use one design system for Simplified Chinese and English. Persist the interface-language choice and preserve the current page, site, filters and unfinished input. Translate interface labels and messages; keep project material and existing reviews in their original language. A language switch must not rewrite records, trigger model calls or change CLI/API contracts.

## 记录边界和失败

只写用户项目工作的必要摘要、产物路径、验证及阻塞原因，不读取或记录凭据、令牌、完整聊天、私有环境变量。现有规则与用户授权范围保持不变。

写入命令必须以退出码 `0` 为成功依据。失败时保留错误和待补记摘要，在结束回复中明确指出未同步，并在恢复后用同一任务 ID 补记；本技能没有静默离线队列，不得声称已自动重试。SQLite 数据默认保存在 `~/.local/share/agent-workhub`，可用环境变量 `AGENT_WORKHUB_HOME` 指定位置；工作记录保存在本机。用户启用评议后，必要项目资料会发送至配置的 API 或 CLI，具体发送范围与密钥要求见评议协议；不会自动上传完整仓库或完整对话。克隆仓库或启动门户不会自动安装全局规则或开启外部模型调用。
