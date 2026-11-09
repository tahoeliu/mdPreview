# mdPreview — Mac 上的 Markdown 阅读与编辑工具

**mdPreview 是一款免费、开源的 macOS Markdown 阅读与编辑工具。** 双击 `.md` 文件，它就会打开成一页干净易读的文档：标题、表格、图片和公式整齐排列，不再满屏都是 `#` 和 `**` 符号。你还可以直接编辑，并把文档分享为 PDF、Word、网页或富文本。

<p align="center">
  <a href="https://tahoeliu.github.io/mdPreview/zh.html"><strong>→ 访问官网（中文）：tahoeliu.github.io/mdPreview</strong></a>
  <br>
  <a href="https://tahoeliu.github.io/mdPreview/zh.html">了解更多</a> · <a href="https://github.com/tahoeliu/mdPreview/releases/latest">下载 Mac 版</a> · <a href="README.md">English</a>
</p>

<p align="center">
  <img src="docs/images/readme/screenshot-reading.png" alt="Mac 上的 mdPreview，左侧是文档大纲，右侧是排版好的 Markdown 文档" width="49%">
  &nbsp;
  <img src="docs/images/readme/screenshot-mermaid.png" alt="Mac 上的 mdPreview 渲染 Markdown 中的图表和公式" width="49%">
</p>

---

## 一览

| | |
|---|---|
| **是什么** | Mac 上的 Markdown 阅读与编辑工具 |
| **价格** | 免费，MIT 开源许可 |
| **适用系统** | macOS 13 或更高版本，支持 Apple 芯片和 Intel 芯片 |
| **最新版本** | 2.0.0 |
| **界面语言** | 简体中文、繁體中文、English、日本語、한국어、Deutsch、Français、Español |
| **网络** | 离线可用，无需账号，无广告，无追踪 |
| **官网** | [tahoeliu.github.io/mdPreview](https://tahoeliu.github.io/mdPreview/zh.html) |

## 什么是 Markdown 阅读器？

Markdown 是一种用纯文本写文档的简单格式，常见于笔记、README 文件，以及 ChatGPT、Claude 等 AI 聊天工具的回答。Markdown 阅读器的作用，就是把这些符号变成排版好的页面。

**mdPreview 就是这样一款阅读器**，它面向所有需要读 Markdown 的人，而不只是程序员。

## 怎样在 Mac 上打开 .md 文件？

直接双击。如果访达用别的 App 打开它，请右键点击文件，选择“显示简介”，在“打开方式”里选 mdPreview，再点“全部更改…”。之后所有 `.md` 文件都会用 mdPreview 打开。

## 怎样不看满屏符号，直接读 ChatGPT 或 Claude 的回答？

复制回答内容，然后在 mdPreview 里选择“**文件 → 从剪贴板新建**”（`⌥⌘N`），内容会立即排版显示，标题、表格和代码块都保持原样。也可以把对话保存为 `.md` 文件，再双击打开。

## 怎样在 Mac 上把 Markdown 转成 PDF、Word 或网页？

使用“**文件 → 导出为…**”：

- **PDF**：按 A4 或 Letter 真正分页，带页码，标题生成书签，中文可搜索、可复制。
- **Word（.docx）**：真正的标题样式，表格表头可跨页重复，保留图片和脚注。
- **HTML 网页**：单个自包含文件，任何浏览器都能打开，带大纲和深色模式。
- **纯文本**或 **Markdown**：去掉格式符号的正文，或原始 Markdown 源码。

要粘贴到邮件、备忘录、Word 或聊天软件里，请用“**复制为富文本**”（`⇧⌘C`），标题和表格会一起带过去。

## 功能

**阅读**
- 左侧大纲，按 `⌘J` 可跳转到任意标题。
- 读完的章节可以折叠起来。
- 浅色或深色外观，可调字号和阅读宽度，并可选择阅读字体。
- 记住读到哪里；文件在磁盘上被修改后自动刷新。
- 支持表格、任务列表、脚注、公式（KaTeX）、Mermaid 图表和 GitHub 风格提示块（Note、Tip、Important、Warning、Caution，以柔和的淡色卡片显示）。

**编辑，无需学习 Markdown**
- 在页面里点一下，即出现类似文字处理软件的简单工具条：加粗、斜体、列表、链接、引用和表格。
- 想看原始 Markdown 时，按 `⌘E` 切换到纯文本视图。
- 粘贴或拖入图片，会自动保存到文档旁边。

**分享与隐私**
- 通过 macOS 自带的分享菜单分享文档（“文件 → 分享…”）。
- 文档只保存在你的 Mac 上；网络图片在你允许之前不会加载。

## 安装

**方法一：终端一行命令（推荐）。** 打开“终端”，粘贴下面这行，然后按回车：

```bash
curl -fsSL https://raw.githubusercontent.com/tahoeliu/mdPreview/main/scripts/get.sh | bash
```

脚本会下载最新版本、确认其来源可靠，并安装到“应用程序”文件夹。这种方式不会弹出 macOS 安全提示。如果愿意，可以先[阅读脚本](scripts/get.sh)。

**方法二：下载磁盘映像。** 从 [Releases 页面](https://github.com/tahoeliu/mdPreview/releases/latest) 下载 `mdPreview-…-arm64.dmg`（Apple 芯片）或 `mdPreview-…-x86_64.dmg`（Intel 芯片），把应用拖进“应用程序”。第一次打开时，到“**系统设置 → 隐私与安全性**”，点击 mdPreview 旁边的“**仍要打开**”，只需操作一次。

**方法三：让 AI 助手帮你安装。** 把 [docs/install.md](docs/install.md) 交给它即可。

已经装过旧版本？mdPreview 会自动更新：它检查新版本，并在验证发布签名后安装。

## 常见问题

**mdPreview 免费吗？** 免费。它是 MIT 许可证下的开源软件。

**离线能用吗？** 能。只有可选的“检查更新”功能需要联网，可以在设置中关闭。

**需要懂 Markdown 吗？** 不需要。当阅读器用就好，想看源码时再切换。

**不打开文件，能在访达里预览吗？** 可以。选中 `.md` 文件，按空格键即可预览。如果没有反应，请参阅 [Quick Look 说明](quicklook/README.md)。

**能替代 Typora、MacDown 或 VS Code 吗？** 它是一款专注的阅读器，带有简单的编辑和方便的分享功能，不是完整的写作工具，也不是编程环境。

**支持哪些 Mac？** 运行 macOS 13 或更高版本的 Mac，无论是 Apple 芯片还是 Intel 芯片。

## 了解更多

- **官网（中文）：** [tahoeliu.github.io/mdPreview/zh.html](https://tahoeliu.github.io/mdPreview/zh.html)，包括截图、功能导览和安装指南。
- **更新内容：** [CHANGELOG.md](CHANGELOG.md)。
- **反馈问题：** 在 App 中使用“**帮助 → 报告问题…**”，或到 [GitHub 提交 issue](https://github.com/tahoeliu/mdPreview/issues)。
- **参与贡献：** 见 [CONTRIBUTING.md](.github/CONTRIBUTING.md)。安全问题请通过 [SECURITY.md](.github/SECURITY.md) 报告。

<details>
<summary>给开发者：从源码构建</summary>

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements/lock.txt
npm ci --ignore-scripts && npm run vendor
npm test && .venv/bin/python scripts/test-python.py
scripts/build.sh      # → WorkSpace/dist/release-<version>/mdPreview.app
```

项目结构见 [CONTRIBUTING.md](.github/CONTRIBUTING.md)，发布流程见 [RELEASE.md](dev/RELEASE.md)。更新校验方式见 [SECURITY.md](.github/SECURITY.md)，第三方代码清单见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

</details>

---

由 [Tahoe Liu](https://github.com/tahoeliu) 制作 · [mdPreview 官网](https://tahoeliu.github.io/mdPreview/zh.html) · 以 [MIT 许可证](LICENSE) 发布。

**关键词：** Mac Markdown 阅读器、Mac Markdown 编辑器、macOS 打开 md 文件、Markdown 转 PDF、Markdown 转 Word、Markdown 转网页、免费 Markdown 工具、开源 Markdown 阅读器、ChatGPT 回答阅读、Claude Markdown 阅读、离线 Markdown 阅读器。
