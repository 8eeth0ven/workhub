# 项目学习卡

完成有实质内容的编码后，由当前编码 Agent 据实际代码整理少量学习卡。每张卡讲一个主题：一句话概念、人话解释、为什么需要它、本项目的实际实现、术语、步骤、小例子和一道可复述的自检问题。引用实际核对过的项目相对文件、行号与函数；不从任务标题猜代码，不把未验收行为说成已验证。隐私检查、服务重启等维护不必机械新增卡片。

用稳定 `card_key` 表示主题；讲解或实现实质改变才更新知识版本，不按每个 run 重复建卡。相同知识内容不增版本；Agent/run/工作事件来源另外保存。用户勾选绑定具体版本，旧版证据保留，后续变化等待重新确认。

**只有用户亲自在 Workhub 勾选，才记录“我已初步理解”。** Agent 不代勾、不根据测验答案或任务完成自动勾，也不把一次勾选写成熟练掌握。用户可取消。学习记录保存在本机，不因打开页面调用云模型或外发代码。

先把一张结构化卡保存为 UTF-8 JSON，再使用共享入口：

```sh
agent-workhub learn-add --project /path/to/project --file /path/to/card.json
agent-workhub learn-list --project /path/to/project --status pending
```

也可使用本 skill 的 `scripts/report.py` 作为命令入口。没有替用户勾选的 CLI。字段示意如下，内容和源码位置必须换为实际核对结果：

```json
{
  "card_key": "cache/invalidation",
  "title": "缓存什么时候需要失效？",
  "concept": "缓存复用已有结果；输入条件变化后需要重新计算。",
  "explanation": "用日常语言解释为什么有用，以及容易误解的地方。",
  "implementation": "说明本项目实际使用的键、检查顺序、函数与失效条件。",
  "terms": [{"term": "缓存键", "definition": "识别一份结果所对应输入的标识。"}],
  "steps": ["读取输入。", "构造缓存键。", "命中时复用，否则重新计算。"],
  "example": "输入版本变化后，旧结果不能当成新结果。",
  "self_check": "如果输入文件变了，代码凭什么知道旧结果不能继续用？",
  "sources": [{"path": "src/cache.py", "line": 42, "symbol": "get_result", "note": "替换为实际位置。"}],
  "agent": "codex",
  "run_id": "current-task-run-id",
  "source_event_ids": []
}
```

`--project` 决定所属项目；卡中不写 `understood` 等理解状态。事件 ID 只能引用同项目真实记录，源码路径不能是绝对路径、越界路径、隐藏配置或凭据文件。解释、术语、实现和示例按字面文本展示，不执行 HTML/脚本。不要把真实代码、学习状态或用户项目清单复制到发布仓库的演示数据。
