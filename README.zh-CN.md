# mdPreview — macOS 上极简的 Markdown 阅读与编辑器

[English](README.md) · [更新日志](CHANGELOG.md) · [参与贡献](CONTRIBUTING.md) · [安全](SECURITY.md)

<div align="center">

**在 Mac 上打开、阅读、编辑并分享 Markdown 文件——干净、专注的窗口。**

[下载 macOS 版](https://github.com/tahoeliu/mdPreview/releases/latest) · 免费 · 开源（MIT）· 离线可用

</div>

<p align="center">
  <img src="images/screenshot-reading.png" alt="带大纲的阅读视图" width="49%">
  &nbsp;
  <img src="images/screenshot-mermaid.png" alt="Mermaid 图表与公式" width="49%">
</p>

---

## 为什么用 mdPreview？

Markdown 文件到处都是：AI 对话导出、README、会议纪要、研究笔记、个人知识库。可是打开一个 `.md` 文件，对很多人仍然显得“太技术”。

**双击 Markdown 文件，像普通文档一样阅读**——不用浏览器，不用账号，也不用笨重的编辑器。要分享时，导出排版规范的 PDF 或 Word，或者“复制为富文本”粘贴到邮件、备忘录、Word、聊天软件里。

| 你想… | mdPreview |
|---|---|
| 阅读 AI 生成的回答（ChatGPT、Claude、Gemini 等） | 正确渲染表格、代码、公式、Mermaid 图和脚注 |
| 读长文档 | 大纲侧栏、记住读到哪里、文件被修改时自动刷新 |
| 发给不用 Markdown 的人 | PDF、Word、HTML、PNG、纯文本，或**复制为富文本** |
| 打印 | 紧凑的 10.5pt 排版、真正的分页、页码 |
| 顺手改几个字 | 切到源码模式（`⌘E`），或直接在预览里编辑 |
| 保护隐私 | 无账号、无遥测、无云端，离线可用 |

## 安装

**方式 A——一行命令，不弹安全提示（推荐）。** 打开“终端”，运行：

```bash
curl -fsSL https://raw.githubusercontent.com/tahoeliu/mdPreview/main/scripts/get.sh | bash
```

脚本很短，建议先读一遍。它会为你的 Mac（Apple 芯片或 Intel）下载最新版本，校验“校验和清单”的 ECDSA 签名与压缩包校验和，检查应用身份，然后安装到“应用程序”。用 `curl` 下载的文件不会被 macOS 隔离，所以不会出现 Gatekeeper 弹窗。脚本从不使用 `sudo`，也不改动隔离属性。

**方式 B——Homebrew：**

```bash
brew install --cask --no-quarantine tahoeliu/tap/mdpreview
```

**方式 C——磁盘映像：** 从 [Releases](https://github.com/tahoeliu/mdPreview/releases/latest) 下载 `mdPreview-<版本>-arm64.dmg`（Apple 芯片）或 `-x86_64.dmg`（Intel），把应用拖进“应用程序”。

> **为什么 macOS 会拦截磁盘映像里的应用？** mdPreview 是免费开源软件，使用 *ad-hoc* 签名，而不是付费的 Apple 开发者证书，因此没有经过公证；通过浏览器下载的副本首次打开会被拦截。请打开“**系统设置 → 隐私与安全性**”，点击 mdPreview 旁的“**仍要打开**”（macOS 15 及以上；13、14 也可以按住 Control 点按 → 打开）。只需操作一次。方式 A、B 不会出现这个提示。

发布签名密钥指纹（公钥的 SHA-256）公布在 [SECURITY.md](SECURITY.md)。

需要 macOS 13 或更高版本。界面支持英文、简体中文、繁體中文、日本語、한국어、Deutsch、Français、Español。Apple 芯片版本由维护者实测；Intel 版本由 CI 在 Intel 机器上构建并做冒烟测试。

### 设为 `.md` 的默认打开方式

在“访达”里选中任意 `.md` 文件 → **文件 → 显示简介 → 打开方式 → mdPreview → 全部更改…**

## 功能

### 阅读
- 大纲侧栏、深色模式、可调字号（`⌘=` / `⌘-`，重置 `⌘0`）和阅读宽度（`⌥⌘=` / `⌥⌘-`）
- 记住窗口位置、字号以及每篇文档的阅读位置
- 其他程序（包括 AI 代理）修改文件后自动刷新
- **为长篇 AI 回答而做：** 长文档里显示剩余阅读时间与进度，**折叠任意章节**、超长代码块和表格自动折叠、**跳转到标题**（`⌘J`），**从剪贴板新建**（`⌥⌘N`）
- 查找（`⌘F`）、多窗口、点击链接打开相关 `.md`、把 `.md` 拖进窗口即可打开
- 表格、任务列表（可点击勾选）、脚注、Front Matter、带复制按钮的代码高亮
- **公式**（KaTeX：`$…$`、`$$…$$`、`\(…\)`、`\[…\]`）、**Mermaid** 图表、GitHub 风格提示块（`> [!NOTE]`）
- 认真对待中文排版（按语言选择字体与间距）

### 编辑
- 点一下渲染页面，顶部就滑出细工具条（加粗、标题、列表、链接、表格，可增删行列），不需要懂 Markdown 语法；`Esc` 回到阅读，“视图 → 始终显示格式工具条”（`⌥⌘T`）可固定显示；也可切到源码（`⌘E`），支持 `⌘B` / `⌘I` / `⌘K`、列表自动续行和 Tab 缩进
- **粘贴为 Markdown**（`⇧⌘V`）：把网页、文档、AI 对话里的格式化文字粘贴成干净的 Markdown
- 粘贴或拖入图片：保存在文档旁的 `assets/` 并用相对路径引用
- 草稿自动保存；保存时不会覆盖你在磁盘写入期间继续输入的内容

### 分享
通过 **文件 → 导出为…** 导出，或 `⌘P` 打印：

| 格式 | 说明 |
|---|---|
| **PDF** | 真正分页（A4 或 Letter）、紧凑的 10.5pt 正文且不受屏幕缩放影响、页码、按标题生成书签、中文文字可搜索可复制、保留链接 |
| **Word（.docx）** | 原生 Word 文档：真正的标题样式、表头跨页重复的表格、图片、脚注；公式和图表以图片呈现 |
| **HTML** | 单个自包含文件（图片内嵌），带打印样式，支持深色模式 |
| **PNG** | 一张浅色主题的长图 |
| **纯文本 / Markdown** | 真正的纯文本（没有 `##`、`**`），或 Markdown 源文本 |
| **复制为富文本**（`⇧⌘C`） | 同时把 HTML、RTF 和纯文本放进剪贴板，粘贴到邮件、备忘录、Word 或聊天软件时保留标题、表格和代码格式 |

导出选项（纸张、边距、字号、页码、Front Matter 等）在“设置”（`⌘,`）里，并会被记住。

### 命令行
**mdPreview → 安装命令行工具…** 会添加 `mdpreview`：

```bash
mdpreview notes.md                                  # 用应用打开
mdpreview export notes.md --to pdf -o notes.pdf     # 无头导出：pdf、html、docx、txt、png
```

## 快捷键

| 快捷键 | 功能 | 快捷键 | 功能 |
|---|---|---|---|
| `⌘N` | 新建 | `⌘F` / `⌘G` / `⇧⌘G` | 查找 / 下一个 / 上一个 |
| `⌘O` | 打开 | `⌘=` / `⌘-` / `⌘0` | 放大 / 缩小 / 重置文字 |
| `⌘S` / `⇧⌘S` | 保存 / 另存为 | `⌥⌘=` / `⌥⌘-` / `⌥⌘0` | 加宽 / 变窄 / 重置宽度 |
| `⌘P` | 打印 | `⌥⌘O` | 显示 / 隐藏大纲 |
| `⌘E` | 预览 ⇄ 源码 | `⌃⌘F` | 全屏 |
| `⇧⌘V` | 粘贴为 Markdown | `⇧⌘C` / `⌥⌘C` | 复制为富文本 / 复制为 Markdown |
| `⌘,` | 设置 | `⌘I` | 属性 |

“帮助”菜单里有完整列表、示例文档、**报告问题…**（只预填版本号和系统版本）和**导出诊断信息…**。

## 隐私

- 无账号、无广告、无遥测、无云同步、不上传任何文档。
- **默认不加载远程图片**——会出现一条提示栏，可选择“加载”或“总是加载”，因为加载图片会让对方服务器知道你打开了这份文件。Mermaid、公式等其余内容全部本地渲染。
- 唯一的联网行为是可选的**检查更新**：向 GitHub 发布接口发一次请求，默认开启，可在“设置”里关闭。更新包在安装前会用发布签名密钥校验。
- 诊断压缩包只含白名单设置和结构化事件，绝不包含文档内容或路径；分享前请自行检查。

## 安全

Markdown 里可以夹带 HTML。所有渲染内容都经过 DOMPurify 与 URL 过滤，页面运行在严格的内容安全策略（CSP）之下（无内联脚本、无 `eval`）。第三方库均经过固定版本、校验和，并连同许可证列在 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 常见问题

**需要懂 Markdown 吗？** 不需要。当阅读器用即可，想改时再切到源码。

**真的免费吗？** 是的，MIT 协议开源。如果它帮你省了时间，给项目点个 Star 能让更多人发现它。

**离线能用吗？** 可以。除了可选的检查更新，不需要任何网络。

**支持“访达”空格键预览（Quick Look）吗？** 支持：扩展已内置，首次启动时自动登记。如果没有出现，请在“系统设置 → 通用 → 登录项与扩展 → Quick Look”里启用 mdPreview Quick Look。验证范围见 [`quicklook/`](quicklook/README.md)。

**能替代 Typora / VS Code 吗？** 不能——它是专注的阅读器，带有顺手的编辑和出色的分享能力，不是写作工作室，也不是 IDE。

## 从源码构建

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
npm ci --ignore-scripts && npm run vendor
npm test && .venv/bin/python scripts/test-python.py
./build.sh            # → WorkSpace/dist/release-<版本>/mdPreview.app
```

项目结构和规则见 [CONTRIBUTING.md](CONTRIBUTING.md)，发布与验证流程见 [RELEASE.md](RELEASE.md)。

## 许可证

MIT，见 [LICENSE](LICENSE)。作者：[Tahoe Liu](https://github.com/tahoeliu)。
