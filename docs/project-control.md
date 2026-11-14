# 多项目推进与外部参考

项目空间包含两个视图：**推进概览**和**项目网页**。侧栏仍为原来六个入口。概览用紧凑列表展示项目、关注状态、下一步与采集时间；展开一行才显示依据、个人计划和相似项目检索。切换视图保留 iframe，不重载项目网页，不改变原站内容或主题。

## 接入项目

- **本地**：点击“添加已有项目”，从 Codex、Z Code、Claude CLI 候选目录中选择后加入。目录列表按可读取的客户端活动时间排序，时间缺失时按名称排列；这不是 Agent 运行状态。
- **GitHub**：点击“连接 GitHub”，填写用户名 / 组织读取最近至多 100 个公开仓库，或直接填写 `owner/repo`。选择候选不建立成员关系，点击“加入中控”才连接。不克隆、不执行仓库代码。
- 可将一个仓库关联到已加入的本地项目；该本地项目仍占一行。GitHub 独立项目没有虚构的本地目录、Agent 完工事件或站点 iframe。
- 本地项目移出中控时，其关联仓库同时隐藏；源目录和历史资料保留。取消独立仓库连接不删除 GitHub 内容。移除会停用该项目的定时检索。

公开仓库不要求密钥。需要读取有权限的私有仓库时，可给本地服务进程配置 `GH_TOKEN` 或 `GITHUB_TOKEN`，再直接填写仓库名。Workhub 不读取或显示 GitHub 登录文件，不向浏览器回传凭据。所需权限按功能限定为 Metadata、Issues、Pull requests、Actions 的 read；没有写操作。

## 快照、建议和下一步

点击项目内“刷新快照”才读取 Git / GitHub。页面轮询只读取本机缓存，不重复触发远程请求。

| 信息 | 依据与边界 |
| --- | --- |
| 本地分支、HEAD、未提交改动 | 已加入目录的 Git 元数据；不自动提交或更改文件 |
| GitHub 默认分支 HEAD | 官方提交 API；与本地功能分支的 HEAD 分别展示 |
| 当前提交的 Actions | 必须对应同一默认分支 SHA；旧 SHA 的结果不能证明新提交通过 |
| 开放 PR / Issue | 最近 20 / 30 条的样本，标记分页边界；不是完整历史 |
| 已记录的阻塞 | Workhub 中真实登记的 `blocked` 事件，不从文件存在推断进展 |
| 建议 | 规则产生的候选行动，例如查看失败检查、核对差异、安排开放事项；不是自动完成记录或全面代码审查 |

失败保留旧快照，标明陈旧或部分不可读。超过 15 分钟的 GitHub 快照不作为当前行动结论。任务结束不等于成功，项目有工作记录也不等于已经验收。

可保存个人“下一步”和 P0–P3 优先级；后台更新不会覆盖编辑草稿。“复制继续任务”复制项目事实和下一步，供用户带回现有 Agent。需要更深入检查时，本地项目可进入已有“项目评议”；只有用户在那里提交才使用配置的模型。

## 相似项目检索

每个项目详情内的“发现相似项目”默认收起。填写想找的功能 / 想法关键词，可立即检索，也可勾选定时检索并保存。

- 默认未启用；周期默认 **每天**，可选 **每 6 小时 / 每天 / 每周**。
- 本地 Workhub 服务运行期间执行，关闭服务后不执行；重启对到期配置补查一次，不补跑所有错过的周期。不创建系统任务或 Codex 自动化。
- 只提交用户填写的关键词，当前版本检索公开 GitHub 仓库的名称、描述和 README；排除归档与 fork，只展示至多 10 条。没有自动外发本地代码或私有仓库名称。
- 关键词相关性不代表功能等价，不输出相似百分比。结果保留描述、原文链接、查询词、检索时间及上游“不完整结果”标记。
- 按 GitHub 数字仓库 ID 去重；更名或结果换序不算新发现。断网 / 限流保留旧结果，修改关键词后旧结果标为陈旧。
- SQLite 租约与配置版本阻止重复执行及旧请求覆盖新配置；共享搜索预算至少间隔 7 秒，定时器最多每 15 秒派发一次。用户关闭或移除后停止后续运行。

检索只提供参考，不克隆、安装、运行外部项目，也不自动把它加入中控。保存的查询、计划和快照都在 Workhub 本机数据库中。

## 实现与验证

核心实现为 `project_control.py`、`project_discovery.py`、`project_catalog.py`，HTTP 接口为 `/api/control` 与受保护的 `/api/control/*`。前端复用原项目空间及共享设计变量；`static/project-control.js` 只使用文本节点显示外部内容。

开发验证使用发布目录外的合成目录、临时数据库和假 GitHub：覆盖准入、移除、关联、草稿保留、相同 SHA 的 CI、陈旧快照、调度租约、去重与配置竞争。浏览器验证中英文、明暗主题、320–1440px 视口以及 iframe 输入保留。公开截图仅包含虚构项目。发布前仍执行 `python scripts/audit_release.py`。

## 借鉴来源与渐进范围

本轮是成熟模式的适配，不作原创声明：

- [DeepSeek Harness](https://www.deepseek.com/harness/zh/)：插件与事件分工；Workhub 当前未实现 DSH 宿主插件或会话协议兼容。
- [dsh-worktable](https://github.com/Aisland-SJL/dsh-worktable/blob/main/README.zh.md)：项目集中入口、保持项目独立、区分运行结束与成功。这里只采用适合现有中控的交互，没有复制分栏引擎或全套视觉。
- [dsh-superagent-prototype](https://github.com/deepseek-ai/dsh-superagent-prototype)：来源与工作单的证据关系；Workhub 不据此自动评论、发 PR 或执行委托。
- [GitHub Projects 表格视图](https://docs.github.com/en/issues/planning-and-tracking-with-projects/customizing-views-in-your-project/changing-the-layout-of-a-view)、[Linear 显示选项](https://linear.app/docs/display-options)、[Apple 按需展开](https://developer.apple.com/design/human-interface-guidelines/disclosure-controls)：默认少量字段，详情按需展开，保持原导航。
- [GitHub 仓库搜索 API](https://docs.github.com/en/rest/search/search#search-repositories)、[官方 gh search repos](https://cli.github.com/manual/gh_search_repos)：已有公开项目发现能力；GitHub Saved searches 本身不是定时任务。

原生客户端实时运行事件、跨客户端会话绑定及更多搜索源仍是后续适配事项，不能把当前的目录活动时间与 GitHub 快照称为完整 Agent 运行监控。
