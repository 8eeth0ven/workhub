# 安装与配置

Workhub 使用 Python 3.10+ 标准库。前台门户和模板生成不需要安装第三方 Python 包或前端依赖。命令均从克隆后的仓库根目录执行；代码根据自身位置和 `Path.home()` 推导路径，无需替换仓库中的个人目录。

## 先运行门户

```sh
python3 workhub.py serve --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765`。如果端口已被其他程序使用，选择其他端口。克隆仓库或启动门户不会修改 Agent 全局规则、扫描其他项目、安装后台服务或调用外部模型。

默认状态目录为 `~/.local/share/agent-workhub`；环境变量 `AGENT_WORKHUB_HOME` 可指定独立的数据目录。测试和演示应使用临时目录，避免混入实际项目记录。

## 选择是否安装 Agent 入口

先预览计划，再执行需要的安装。只有显式运行安装器才会写入这些规则文件。

```sh
python3 scripts/install.py --global --dry-run
python3 scripts/install.py --global
```

全局安装在 `.codex/skills`、`.agents/skills`、`.zcode/skills`、`.claude/skills` 下创建同一技能的链接，并给 Codex、Z Code、Claude Code 的用户规则文件追加 Workhub 标记块。原文保留，修改前备份到状态目录的 `backups/`。外来同名技能、命令或符号链接目标不会被覆盖；重复安装不会重复追加。

仅接入指定项目时，将 `PROJECT_DIR` 设为该项目的真实绝对路径：

```sh
python3 scripts/install.py --project "$PROJECT_DIR" --name "项目名称"
```

这会为该目录追加 `AGENTS.md`、`CLAUDE.md` 并登记项目，不递归改写其他项目。客户端需要实际读取相应文件才会应用协议；已打开的会话可能需要重新加载。安装器支持 `--home` 指定临时测试根目录；它不是把技能推送到远端客户端的功能。

仓库移动后需重新运行安装器，以更新本机生成的绝对路径。安装结果中的路径只存在于使用者的本机配置，不应提交到发布仓库。

## 本地网站和模板

已有静态站使用 `--site-dir`；已有开发服务器使用 `--site-url`，两者互斥：

```sh
python3 scripts/install.py --project "$PROJECT_DIR" \
  --site-dir "$PROJECT_DIR/site" --site-name "项目网站" --template library
python3 scripts/install.py --project "$PROJECT_DIR" \
  --site-url http://127.0.0.1:3000 --site-name "开发网站"
```

模板生成与网站登记分开执行。生成器保护已有非空目录，默认只生成空的真实内容结构，不复制演示条目。

```sh
python3 scripts/site_templates.py create --template radar \
  --output "$PROJECT_DIR/site" --name "信息看板"
```

三个布局共用 `static/design-system.css`。门户左侧已有标题时，内容区不重复大页头；具体规则见技能的统一设计规范。

## 可选后台服务

macOS 和 Linux 可使用独立会话后台进程；它不要求聊天或浏览器持续打开。以下命令仅在用户明确希望安装后台服务时执行：

```sh
python3 scripts/service.py install --mode session --port 8765
python3 scripts/service.py status
python3 scripts/service.py stop
python3 scripts/service.py start
python3 scripts/service.py uninstall
```

`start/status/stop` 从状态目录读取已保存模式和端口。停止前同时核验 PID、启动时间和命令，不按端口杀进程。该模式没有配置自动登录启动；退出登录或重启系统后运行 `start` 恢复。日志和进程记录保存在状态目录，不进入 Git。

macOS 的可选 `--mode launchd` 使用用户 LaunchAgent，并将后端、评议模块及静态资源同步到状态目录的 `runtime/`。后台进程仍可能受到系统对项目目录的访问限制；不要更改系统保护来强行读取，按实际可用性选择会话后台或前台运行。Linux 不使用 launchd。Windows 可从前台门户开始验证，本项目未承诺 Windows 后台服务与技能链接的完整兼容性。

服务脚本的显式 `--home` 永远只暂存测试配置，不启动进程或操作真实 launchd；`--dry-run` 不写入文件。

## 可选模型评议

先复制仓库 `examples/provider-*.json` 中适合的例子到状态目录的 `llm.json`，填入自己的配置，并将权限设置为仅本人可读写：

```sh
WORKHUB_DATA_DIR="${AGENT_WORKHUB_HOME:-$HOME/.local/share/agent-workhub}"
chmod 600 "$WORKHUB_DATA_DIR/llm.json"
```

这里 `AGENT_WORKHUB_HOME` 应指向实际状态目录；未自定义时使用 `~/.local/share/agent-workhub`。配置支持 `provider`、`api_keys`（或 `api_key`）、`base_url`、`model`，以及后端支持的超时、输出和并发限制。模型提供者包括云端 API、本机模型和显式配置的 CLI；以示例及当前后端实际支持为准。

`llm.json` 存在时优先使用；只有它不存在才回退到旧 `glm.json`，不混合两份配置。环境变量 `WORKHUB_LLM_PROVIDER`、`WORKHUB_LLM_API_KEYS` / `WORKHUB_LLM_API_KEY`、`WORKHUB_LLM_BASE_URL`、`WORKHUB_LLM_MODEL` 可覆盖对应字段；旧 `GLM_*` 仅用于 GLM 兼容回退。

CLI 提供者的 `command` 是用户在私有配置中指定的参数数组，可选配置 `cwd` 和输出格式；网页请求不能指定要执行的命令、提供者或工作目录。应先审查所选命令会如何处理输入。

用户启用评议后，命令 `python3 workhub.py review --project "$PROJECT_DIR"` 会将有限的已登记项目资料发送给所选模型。未配置或调用失败时如实显示状态，不生成冒充模型的本地评分。数据范围与发布前检查见 [隐私说明](privacy.md)。
