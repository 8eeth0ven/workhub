[简体中文](README.md) · [English](README.en.md)

# Workhub

在同一个本地工作台切换项目网站、查看 Git 与 Agent 的工作记录，并为每个项目留下一步行动。

![隔离演示中，项目列表并排显示进展、关注原因和下一步](docs/images/project-control-light.png)

在仓库根目录运行服务，需要 Python 3.10 或更高版本。

```sh
python3 workhub.py serve --port 8787
```

打开终端显示的地址，选“添加已有项目”，再选本机目录。如想先看虚构项目，运行 `python3 examples/demo.py --port 8899`。

工作记录存入本机 SQLite。浏览项目无需模型密钥。启动项目评议时，选定的摘要和补充背景会交给你配置的 API、模型或 CLI。

[安装与 Agent 接入](docs/installation.md) · [GitHub 快照与项目推进](docs/project-control.md) · [模型设置](docs/providers.md) · [数据与隐私](docs/privacy.md) · [可选模块](https://github.com/8eeth0ven/workhub-model)
