[简体中文](appearance.md) | [English](appearance.en.md)

# 外观与嵌入阅读

## 界面语言与外观

顶部工具栏可选择「简体中文 / English」，语言偏好保存在当前门户来源的浏览器本地存储中，刷新后沿用。切换只改变导航、控件、状态标签与界面提示，不翻译或改写项目名称、工作记录、网站正文和已有模型评议；当前页面、站点、筛选与未提交输入保持不变。门户会把语言选择同步给支持该协议的模板 iframe，已有第三方网站保留自己的语言行为。

文档也可通过每页顶部入口在中英文之间切换。英文版见 [README.en.md](../README.en.md)；CLI 命令、API 路径与持久化数据结构不因界面语言改变。

默认采用纯白的 **Codex 明亮**，顶部「配色」可切换 **Codex 深色**，并保留原有八种配色。门户和三个项目模板共用颜色变量，偏好在浏览器本地保存；切换不重载 iframe、不丢搜索或输入，也不触发模型。生成的独立模板同样带外观选择器。

目录站会由本机服务注入受限配色运行时和共享 CSS，支持该协议的模板也会跟随门户。通用嵌入样式只改颜色，不修改字号、排版、图片、PDF、视频或图表；原生应用可标记 `body[data-workhub-native]`，跳过通用强覆盖并自行映射颜色变量。

有独立后端的项目可在自己的页面显式加载：

```html
<link rel="stylesheet" href="http://127.0.0.1:8787/design-system.css">
<link rel="stylesheet" href="http://127.0.0.1:8787/embedded-theme.css">
<script defer src="http://127.0.0.1:8787/embedded-theme.js"></script>
```

子页默认只信任父窗口 `http://127.0.0.1:8787` 的受支持主题消息，并用 ready/request 握手取得当前配色。自定义端口或 `localhost` 别名需在脚本标签明确指定 `data-workhub-parent-origin="http://127.0.0.1:8899"` 等 HTTP(S) 回环 origin，同时调整资源地址；不会把任意 referrer 当作信任来源。未接入资源的第三方页面不会被强制修改跨域 DOM。目录站可用 `?workhub_theme=original` 关闭自动注入。

公众号或长文可固定明亮外观，在页面 head 中声明：

```html
<meta name="workhub-reading-theme" content="light">
```

也可在 html 上设置 `data-workhub-reading-theme="light"`。目录预览会尊重此声明，即使门户为深色，文章仍保持明亮；它不会覆盖全局保存的外观偏好。已有网页需在其源码加入声明，Markdown 文件本身不写 CSS。可复用的白底示例及 Markdown 样式见 [reading-light](../examples/reading-light/)；微信粘贴模板仍需全内联样式和白名单标签。示例仅用于排版演示。
