# mdPreview

一款安静、简单的 Mac 应用，用来阅读和编辑 Markdown 文件。

[English](README.md) · [更新日志](CHANGELOG.md) · [官网](https://tahoeliu.github.io/mdPreview/) · [参与贡献](CONTRIBUTING.md) · [安全](SECURITY.md)

<p align="center">
  <img src="images/screenshot-reading.png" alt="mdPreview 中打开的 Markdown 文档，左侧是大纲" width="49%">
  &nbsp;
  <img src="images/screenshot-mermaid.png" alt="mdPreview 中整齐呈现的图表和公式" width="49%">
</p>

---

## Markdown 是什么？

Markdown 是一种用纯文本写文档的简单方法。笔记、README 文件，以及 ChatGPT、Claude 等 AI 聊天工具的大部分回答，都是这种格式。直接打开时，它常常是一堆 `#` 和 `**` 符号，看着很乱。

**mdPreview 把这些符号变成干净的页面。** 双击一个 `.md` 文件，它就像普通文档一样打开：标题、表格、图片和公式都排得整整齐齐。不用注册账号，离线也能用。

## 适合谁用

- **收到 AI 回答、想舒服地读完它的人。**
- **经常记笔记、想整理得好看一点、又不想学新东西的人。**
- **需要把文档发给从没见过 Markdown 的人的人。**

## 能做什么

**阅读**
- 双击 `.md` 文件即可打开，也可以直接把文件拖进窗口。
- 左侧有章节目录，长文档可以一下跳到任意位置。
- 读完的章节可以折叠起来。
- 可以选择阅读字体、字号，以及浅色或深色外观。
- 文件被修改后，它会自动刷新。

**编辑，不用写代码**
- 在页面里点一下，顶部会出现一条简单的工具条，和文字处理软件很像。可以加粗文字、加列表、插入表格等等。
- 按 `Esc`（或点一下文字以外的地方），即可回到阅读状态。
- 如果想看原始的 Markdown 文本，按 `⌘E` 切换到纯文本视图。

**分享**
- **存为 PDF**：版面整齐，适合打印。
- **存为 Word（.docx）**：发给使用 Microsoft Word 或 Pages 的人。
- **存为网页（HTML）**：任何浏览器都能打开。
- **复制为富文本**：粘贴到邮件、备忘录或聊天窗口里，标题和表格会原样带过去。
- **分享…**：通过 macOS 自带的分享菜单发送文档。

## 安装

**最简单的方法：** 打开“终端”App（按 `⌘ 空格`，输入“终端”，再按回车），把下面这一行粘贴进去，然后按回车。

```bash
curl -fsSL https://raw.githubusercontent.com/tahoeliu/mdPreview/main/scripts/get.sh | bash
```

脚本会下载最新版本，确认它是正版，然后放进“应用程序”文件夹。通过这种方式安装，macOS 不会弹出安全提示。脚本很短，你也可以先读一遍。

**更喜欢点按钮？** 从 [Releases 页面](https://github.com/tahoeliu/mdPreview/releases/latest) 下载适合你 Mac 的文件：
- Apple 芯片的 Mac（大多数 2020 年之后的机器）：`mdPreview-…-arm64.dmg`
- Intel 芯片的 Mac：`mdPreview-…-x86_64.dmg`

打开文件，把 mdPreview 拖进“应用程序”。第一次打开时，macOS 可能提示无法验证这个 App。这对免费的开源软件来说很常见。去“**系统设置 → 隐私与安全性**”，往下找到 mdPreview，点击旁边的“**仍要打开**”。只需要操作这一次。

**让 AI 替你安装：** 也可以把这份安装说明交给 AI 助手，让它帮你装好：[docs/install.md](docs/install.md)。

mdPreview 需要 macOS 13 或更高版本，界面支持英文、简体中文、繁體中文、日本語、한국어、Deutsch、Français 和 Español。

**设为默认打开方式：** 在“访达”里右键任意 `.md` 文件，选择“显示简介”，打开“打开方式”，选 mdPreview，再点“全部更改…”。

## 几个常用快捷键

| 按键 | 作用 |
|---|---|
| `⌘O` | 打开文件 |
| `⌘F` | 查找文字 |
| `⌘E` | 在阅读和纯文本视图之间切换 |
| `⌘J` | 跳转到某个标题 |
| `⌘=` / `⌘-` | 放大或缩小文字 |
| `⇧⌘C` | 复制为富文本（适合邮件和备忘录） |
| `⌘P` | 打印 |
| `⌘,` | 设置 |

“帮助”菜单里有完整的快捷键列表，还附带一份可以练手的示例文档。

## 你的隐私

- 没有账号，没有广告，没有追踪，也没有云端存储。
- 你的文档不会离开你的 Mac。
- 应用偶尔会检查一下有没有新版本。这个功能可以在设置里关闭。
- 网络上的图片不会自动加载。页面上会出现一条提示，问你是否要加载。因为加载图片时，图片所在的网站会知道你打开了这份文档。

## 常见问题

**需要懂 Markdown 吗？** 不需要。只管阅读就好，想看原始文本时再切换。

**真的免费吗？** 是的。它是免费的开源软件，采用 MIT 许可证。如果它帮到了你，欢迎在 GitHub 上点个星，让更多人找到它。

**离线能用吗？** 能。只有可选的“检查更新”功能需要联网。

**不打开文件，能在访达里预览吗？** 可以。在访达里选中一个 `.md` 文件，按空格键即可预览。如果没有出现，请参阅 [Quick Look 说明](quicklook/README.md)。

**能替代 Word 或 VS Code 吗？** 不能。它是一个专注的阅读器，带有简单的编辑和方便的分享功能，不是完整的写作工具，也不是编程工具。

## 发现问题，或者想帮忙？

- 在 App 里使用“**帮助 → 报告问题…**”，或者到 [GitHub](https://github.com/tahoeliu/mdPreview/issues) 提一个 issue。
- 欢迎参与贡献，请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

<details>
<summary>给开发者：从源码构建</summary>

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
npm ci --ignore-scripts && npm run vendor
npm test && .venv/bin/python scripts/test-python.py
./build.sh            # → WorkSpace/dist/release-<version>/mdPreview.app
```

项目结构见 [CONTRIBUTING.md](CONTRIBUTING.md)，发布流程与验证方式见 [RELEASE.md](RELEASE.md)。安全相关细节（包括更新如何校验）见 [SECURITY.md](SECURITY.md) 和 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

</details>

---

由 [Tahoe Liu](https://github.com/tahoeliu) 制作。以 [MIT 许可证](LICENSE) 发布。
