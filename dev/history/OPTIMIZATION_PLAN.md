# mdPreview 2.0 产品化完整路线图

基线：1.5.0（工作区有大量未提交改动）· 编写日期：2026-11-06
目标：让 mdPreview 成为**可对外发布、质量对标付费软件的开源 macOS Markdown 阅读与分享工具**
约束：**GitHub 开源（MIT）**；**继续使用 ad-hoc 签名，不购买 Apple Developer ID**

> 本文档分两部分：
> - **第一部分（§1–§4）给人看**：产品判断、全局问题清单、目标架构。
> - **第二部分（§5–§6）给执行 AI 看**：33 张按依赖顺序排列的任务卡，每张都写明改哪些文件、怎么做、怎样算完成。
>
> 证据标记：**【实测】** 本机真实运行验证过；**【代码】** 读源码可确定；**【推断】** 需要执行时先验证。

---

# 第一部分：产品与架构

## 1. 产品判断

### 1.1 一句话定位
**"双击就能读，一键发给任何人"**：面向收到 `.md` 文件的普通人（AI 导出、README、会议纪要），提供零门槛阅读，以及专业级的打印、PDF、Word 和富文本分享。

### 1.2 价值来自哪里
用户拿到 mdPreview 后依次经历四步，每一步都可能流失：

| 环节 | 用户期望 | 现状 | 主要差距 |
|---|---|---|---|
| ① 安装、打开 | 下载后双击能用 | ad-hoc 签名，Gatekeeper 拒绝打开【实测】；只有 arm64 版本【实测】 | **漏斗最大的流失点** |
| ② 阅读 | 渲染正确、好看、记得读到哪 | 公式不渲染；远程图片默认加载（有隐私问题）；不记阅读位置；相对 `.md` 链接点了没反应 | 中 |
| ③ 分享 | 打印好看、PDF 专业、Word 别人能打开、能贴进微信或飞书 | 五种输出各用一套逻辑；打印字号大约 20%；PDF 是一张超长单页；Word 多数软件打不开；没有富文本复制 | **核心价值的短板** |
| ④ 小改 | 顺手改几个字、插一张图 | 源码模式没有格式快捷键，拖入图片会插入不可移植的路径 | 中 |

**护城河 = 零门槛打开 × 专业级输出。** 编辑功能保持"够用"，不和 Typora 比拼所见即所得。

### 1.3 竞品对照
- **Marked 2**（付费）：核心卖点就是导出质量，mdPreview 的输出要以它为标杆。
- **Typora**（付费）：重在编辑，mdPreview 不和它正面竞争。
- **QLMarkdown 等 Quick Look 插件**（免费）：只能看，不能打印或导出，mdPreview 可以把它们的场景也覆盖掉。
- **Obsidian / VS Code**：对"只想看一个文件"的用户太重。

---

## 2. 全局问题清单（含你之前没提到的）

按维度列出，每条后面标注对应的任务卡编号。

### 2.1 输出与分享（已讨论过，此处汇总）
- 打印正文约 12.5pt，偏大约 20%【实测】→ T03
- 屏幕上按 ⌘= 放大后再打印，H2 会比 H1 还大，标题层级错乱【实测】→ T03
- 打印时代码块、表头的灰色底丢失【实测】→ T03
- 在 CSS 里设置 `@page margin` 会导致表格右侧被裁掉，所以页边距只能在原生打印设置里定【实测】→ T04
- 导出 PDF 走屏幕媒体：字号随窗口宽度变化，输出一张超长单页，和打印结果不一致【代码】→ T05
- Word 导出靠 altChunk 嵌入 HTML，只有桌面版 Word 能正常显示，Mermaid 图会丢【代码，兼容面属推断】→ T10
- PNG 导出用 html2canvas，暗色模式下可能出现白底配浅色字【推断】→ T09
- "纯文本"导出的其实是 Markdown 源码【代码】→ T08
- HTML 导出是手写的第二套 CSS，缺语法高亮等样式；`lang="en"` 写死；字体栈只有 Apple 字体【代码】→ T07
- 缺少"复制为富文本"→ T12

### 2.2 你没提到、但会影响口碑的问题

**隐私与安全**
1. **远程图片打开即加载【代码】**：`rewriteRelativeImages` 对 `https:` 图片直接放行。Markdown 里嵌一个 1×1 追踪像素，用户一打开文件就会暴露 IP 和打开时间。这与 README 宣称的 "No tracking" 和 "Work offline" 相矛盾。macOS 邮件、Thunderbird 默认都会拦截远程内容 → T15
2. **没有内容安全策略 CSP【代码】**：`index.html` 没有 CSP，还有 5 处内联 `onclick`（`index.html:38,43,66`、`app.js:728,2180`）。目前只靠 DOMPurify 一层防护，缺少纵深防御 → T16
3. **更新包只校验 GitHub 提供的 SHA-256**：GitHub 账号或 Release 一旦被篡改，校验值会一起被改。没有 Apple 签名时，**自有的发布签名是唯一的供应链保护**。可以用已经依赖的 `pyobjc-framework-Security` 做 ECDSA 验签，零新增依赖 → T27

**开源合规**
4. **第三方许可证缺失【实测】**：`vendor/licenses/` 只有 `dompurify.txt`，而 marked、mermaid、turndown、html-docx-js、html2canvas、marked-footnote 的许可证都没有随应用分发；`Credits.rtf` 只有一行。MIT 和 Apache 许可都要求分发时保留版权声明，**这是开源发布的硬伤** → T30

**基础交互不符合 macOS 惯例**
5. **⌘, 被占用来"收窄页面宽度"【代码】**：⌘, 在所有 Mac 应用里都是"设置"，而本应用**没有设置窗口**，各项设置散落在快捷键里。⌘. 在 macOS 里通常表示"取消"→ T17
6. **字号不记忆，宽度却记忆**，两者不一致；窗口固定 900×680 打开，不记住窗口位置，不记阅读进度，重启后不恢复之前打开的文档 → T19
7. **拖入图片的 bug【代码】**：`handleImageDrop` 插入的是 `f.path || f.name`，结果要么是绝对路径（文档发给别人就看不到图，还暴露用户名），要么只有文件名（图片不在同一目录时直接显示不出来）。图片也没有复制到文档旁边 → T18
8. **不能粘贴截图**（剪贴板里的图片会被丢弃）；源码模式没有 ⌘B/⌘I/⌘K、列表自动续行、Tab 缩进；只能查找不能替换 → T18
9. **外部程序修改文件后不会自动刷新**。这在和 AI 或脚本协作时很常见（比如 Claude Code 正在写某个 `.md`，你开着 mdPreview 看）→ T20
10. **拖入 `.md` 文件不会打开**：drop 处理只接受图片 → T14

**可用性与包容性**
11. **无障碍**：`app.js` 中 aria 属性只有约 8 处；欢迎页文字颜色 `#aaa` 配白底，对比度不满足 WCAG AA；没有适配"减弱动态效果"→ T22
12. **国际化**：文案以 `t('英文','中文')` 的形式散落在代码中，无法新增语言（繁体中文、日文用户也是潜在受众）→ T23
13. **中文排版**：字体栈没有显式写中文字体，`lang` 固定为 en，在 Windows 上打开导出的 HTML 时中文字形可能出错 → T21

**性能与可观测性**
14. **没有任何性能基线**：启动埋点 `startup_ready` 存在，但本机找不到日志输出【实测】；大文档下 Mermaid 会一次性全部渲染 → T24
15. **用户遇到问题时没有反馈渠道**：没有"帮助"菜单、诊断信息导出、报告问题入口；JS 报错不会落到日志里 → T25

**分发（在 ad-hoc 前提下仍可以大幅改善）**
16. **curl 下载的文件不带隔离属性（quarantine），Gatekeeper 不会拦截**。因此"一行命令安装"可以完全绕开"无法打开"的弹窗，这是 ad-hoc 签名下最有效的分发方式 → T27
17. Homebrew cask 放在主仓库，没有 tap 仓库，也没有处理隔离属性 → T27
18. Release 只有 DMG，没有 zip、`SHA256SUMS`、发布签名；Release 流程是手动的 → T27、T31

**开源社区基建**
19. 没有 CONTRIBUTING、SECURITY、Issue/PR 模板、CHANGELOG、中文 README、FUNDING；仓库根目录堆着 7 个第三方 js 文件，新贡献者难以理清结构 → T31
20. 应用内没有"新版本说明"、示例文档和快捷键一览，新用户发现不了已有功能 → T26

**能力边界的拓展**（让产品从"又一个预览器"变成"不可替代"）
21. **Quick Look 空格预览**：在 Finder 里选中 `.md` 按空格即可预览。这是"只想看一眼"场景的终极形态 → T28（需先验证 ad-hoc 下是否可行）
22. **命令行 `mdpreview`**：`mdpreview README.md` 直接打开；`mdpreview export --pdf a.md` 可以无头导出，开发者和自动化场景会很喜欢 → T29
23. **公式渲染**（AI 输出最常见的缺陷）→ T11；**GitHub Alerts 提示块和代码复制按钮** → T13

**工程**
24. 单体文件：`app.js` 4116 行、`mdPreview.py` 3655 行 → 所有新功能写在新模块里，最后统一收口（T32）
25. 输出质量没有自动化测试。本次的打印探针证明这部分可以被量化 → T01
26. **当前工作区有大量未提交改动**（几十个文件），任何优化开始前都必须先固化基线 → T00

---

## 3. v2.0 发布验收标准（Definition of Done）

全部满足才能对外发布 2.0：

1. **安装**：一行命令安装，全程无 Gatekeeper 弹窗；DMG 内附图文首次打开指引；Homebrew tap 可用；universal2 版本能在 Rosetta（x86_64）下通过自检。
2. **输出**：§6 中所有输出相关的自动化断言通过；兼容性矩阵（T33）全部截图存档且人工确认。
3. **隐私**：默认不访问网络（远程图片、更新检查都可以在设置里控制，并在隐私说明中写清）；提供 CSP。
4. **合规**：所有第三方许可证随应用分发并能在"关于"中查看；有 SECURITY.md。
5. **体验**：设置窗口（⌘,）、阅读位置记忆、外部修改自动刷新、图片粘贴和拖入、公式渲染。
6. **质量**：`./verify-all.sh` 全绿；CI 在 macOS runner 上全绿；冷启动到首屏 < 1.5s（M 系列芯片）。
7. **社区**：中英 README、CHANGELOG、Issue 模板、自动化 Release（含 SHA256SUMS 与签名）。

---

## 4. 目标架构

### 4.1 目录结构（目标）
```
mdPreview/
├── app/                         # 前端（WKWebView 内运行）
│   ├── index.html
│   ├── css/
│   │   ├── tokens.css           # 颜色/字号/间距变量（浅色、暗色、输出三套）
│   │   ├── content.css          # 文档排版（唯一来源：屏幕/打印/HTML/富文本共用）
│   │   ├── print.css            # @media print
│   │   └── app.css              # 界面外壳（TOC、查找栏、弹窗、提示）
│   ├── js/
│   │   ├── app.js               # 现有主文件（逐步瘦身）
│   │   ├── bridge.js            # 所有 pywebview.api 调用的唯一出口
│   │   ├── i18n.js + locales/   # 文案
│   │   ├── render/              # pipeline、mermaid、katex、alerts、links、images
│   │   ├── output/              # prepare、html、txt、docx、richtext
│   │   ├── editor/              # 源码模式快捷键、粘贴图片
│   │   └── settings.js
│   └── vendor/                  # marked、dompurify、mermaid、katex、docx、turndown + licenses/
├── mdpreview_core/              # Python
│   ├── api.py  windows.py  menus.py  config.py
│   ├── export/ print_engine.py  pdf_post.py  snapshot.py
│   ├── clipboard.py  watcher.py  diagnostics.py  release_sig.py
│   └── storage.py images.py release.py（已有）
├── mdPreview.py                 # 启动入口（逐步瘦身到 < 500 行）
├── quicklook/                   # Swift Quick Look 扩展（T28，可选）
├── cli/mdpreview                # 命令行脚本（T29）
└── tests/  scripts/  docs/  .github/
```
> 迁移原则：**不做一次性大重构**。新代码直接写到新位置；旧代码在修改到时顺手迁出；T32 统一收尾。移动静态资源路径时，必须同步修改 `index.html`、`mdPreview.spec`、`build.sh`、`get_resource_path`、`scripts/vendor.mjs`、`vendor/checksums.json` 和测试服务器 `scripts/test-server.cjs`。

### 4.2 输出数据流（目标）
```
Markdown ─► MarkdownPipeline ─► 渲染 DOM ─► prepareForOutput()（浅色、Mermaid 重渲、公式、图片解码、字体就绪）
                                              ├─► 打印     ：print.css → NSPrintOperation(面板)
                                              ├─► PDF      ：print.css → NSPrintOperation(存文件) → 页码/书签/元数据
                                              ├─► PNG      ：createPDF(屏幕媒体，全高) → CoreGraphics 栅格化
                                              ├─► HTML     ：内联 tokens+content+print.css
                                              └─► 富文本   ：计算样式内联 → NSPasteboard(HTML+RTF+纯文本)
Markdown tokens（marked.lexer）──────────────────► Word：docx 库生成原生 OOXML
渲染 DOM ─► 纯文本序列化 ───────────────────────► TXT
```

---

# 第二部分：执行手册（给执行 AI）

## 5. 执行规则（每张卡都适用）

1. **先读后写**：每张卡开头列出的"涉及文件"必须先读完相关函数再动手。行号仅供参考，以函数名为准（基于 1.5.0）。
2. **一卡一提交**：每完成一张卡提交一次，提交信息格式为 `T07: HTML export uses shared stylesheet`。不要把多张卡混在一起提交。
3. **测试先行**：每张卡的"验收"一节就是要写的测试。先写测试，看到失败，再实现。
4. **每张卡完成后必须运行**：
   ```bash
   npm test
   ```
   ```bash
   .venv/bin/python scripts/test-python.py
   ```
   涉及 UI 时再运行 `npm run test:e2e`；涉及原生打印、导出时运行 T01 的输出测试。
5. **禁止事项**：
   - 不得修改 `/Applications` 下已安装的应用（WORKFLOW.md 规定）
   - 不得在 CSS 中使用 `@page { margin }`（实测会导致裁切）
   - 不得放宽 `MarkdownPipeline.clean()` 的全局 DOMPurify 配置；新渲染器（KaTeX）使用单独的受限配置
   - 新增第三方库必须经过 `scripts/vendor.mjs` 复制，并写入 `vendor/checksums.json` 和许可证目录
   - 所有 `window.pywebview.api.xxx` 调用必须经过 T02 的 `bridge.js`
   - 不得引入网络请求，除非卡片明确要求（更新检查、用户点击"加载远程图片"）
6. **不确定就停**：标记为【验证门】的步骤，如果验证失败，按卡片里的"降级方案"执行，不要自行发挥。
7. **macOS 原生 API 都在主线程调用**：使用 `AppHelper.callAfter`，参照现有 `export_as_write` 的写法。

## 6. 任务卡

依赖关系总览：
```
T00 ─► T01 ─► T02 ─┬─► T03 ─► T04 ─► T05 ─► T06 ─┬─► T07 T08 T09 T10 T12
                   │                              └─► T33
                   ├─► T11 T13 T14 T15 T16 T21 T22 T23 T24
                   ├─► T17 ─► T19 T20 T25 T26
                   ├─► T18
                   └─► T27 T28 T29 T30 T31 ─► T32 ─► T33
```
（同一行的卡互不依赖，可以按任意顺序做。）

---

### T00 固化基线
**目标**：在任何优化开始前，把当前未提交的工作安全地保存下来。
**步骤**
1. `git status` 确认改动范围；`git switch -c release/2.0` 新建分支。
2. 检查 `.gitignore` 是否覆盖 `WorkSpace/`、`outputs/`、`.venv/`、`node_modules/`、`.coverage`、`__pycache__/`、`.workbuddy/`、`WORKFLOW.md.bak`、`.DS_Store`。
3. 运行 `npm test` 和 `.venv/bin/python scripts/test-python.py`，记录结果。
4. 提交：`T00: baseline 1.5.0 working tree`。
**验收**：工作区干净；两套测试结果记录在提交说明里。

---

### T01 输出测试基础设施
**目标**：让打印/PDF/Word/HTML 的质量可以被自动化度量，作为之后所有输出卡的回归保护。
**新增文件**
- `tests/fixtures/output/`：`zh-longform.md`（3000 字以上中英混排，含 H1–H4）、`wide-table.md`（10 列 30 行）、`long-code.md`（单个 120 行代码块）、`mermaid.md`、`math.md`（同时包含 `$`、`$$`、`\(`、`\[` 四种写法）、`footnotes.md`、`images.md`（相对路径本地图片 + 一张 https 图片）、`frontmatter.md`、`alerts.md`、`ai-export-chatgpt.md`、`ai-export-claude.md`（各取一份真实 AI 导出的内容，删去隐私信息）
- `scripts/output_probe.py`：在已有的 `scripts/print_probe.py`（附录 B）基础上扩展成命令行工具：
  ```
  .venv/bin/python -I scripts/output_probe.py --html <file> --css <a.css,b.css> --out <pdf> [--dark] [--font-size 22px] [--json]
  ```
  输出 JSON：`{pages, page_size, glyph_heights:{h1,h2,h3,body,code,table}, text_bboxes_outside_margin: n, link_count, dark_text_ratio}`
  - 字形高度：用 `Quartz.PDFDocument` 的 `page.string()` 找到标记文字（如 `HHeading One`），取 `characterBoundsAtIndex_` 的高度
  - 越界检测：逐字符检查 bbox 是否落在页面边距之外
  - `--dark`：给 WKWebView 设置 `NSAppearanceNameDarkAqua`
- `tests/test_output_quality.py`：调用 probe，断言见后续各卡。macOS 以外的平台或缺少 PyObjC 时 `skip`。
**验收**：`tests/test_output_quality.py` 能运行，并打印出当前基线数据（这一步只建立基线，暂不加断言）。

---

### T02 前端桥接层 bridge.js
**目标**：集中管理所有原生调用，统一错误处理和超时；为后续卡提供 `bridge.call(name, ...args)`。
**涉及文件**：`app.js`（搜索 `window.pywebview.api`，约 60 处）、`index.html`
**步骤**
1. 新建 `frontend/bridge.js`：
   ```js
   (function () {
     function ready() { return !!(window.pywebview && window.pywebview.api); }
     async function call(name, ...args) {
       if (!ready()) throw new Error('bridge-not-ready');
       const fn = window.pywebview.api[name];
       if (typeof fn !== 'function') throw new Error('bridge-missing:' + name);
       return await fn(...args);
     }
     function callSafe(name, ...args) { return call(name, ...args).catch(e => { logError('bridge', name, e); return null; }); }
     function logError(scope, what, err) {
       try { if (ready() && window.pywebview.api.log_js_error) window.pywebview.api.log_js_error(scope, String(what), String(err && err.stack || err)); } catch (_) {}
     }
     window.addEventListener('error', e => logError('window', e.message, e.error));
     window.addEventListener('unhandledrejection', e => logError('promise', 'unhandled', e.reason));
     window.Bridge = { ready, call, callSafe, logError };
   })();
   ```
2. 在 `index.html` 中，于 `app.js` 之前加载 `bridge.js`。
3. Python `MarkdownAPI` 增加 `log_js_error(self, scope, what, stack)`：写入现有日志，单条截断到 4KB，**不得记录文档内容**。
4. 把 `app.js` 中的 `window.pywebview.api.X(...)` 逐个替换为 `Bridge.call('X', ...)`；原先有 `if (window.pywebview && ...)` 判断的地方改为 `if (Bridge.ready())`。
**验收**：`grep -c "window.pywebview.api" app.js` 结果为 0（`bridge.js` 除外）；全部测试通过。

---

### T03 样式拆分与打印样式
**目标**：建立唯一的文档样式来源；修复打印字号和层级问题。
**涉及文件**：`styles.css`、`index.html`、`mdPreview.spec`、`build.sh`（资源清单）
**步骤**
1. 把 `styles.css` 拆分成四个文件（保留原选择器，只移动位置）：
   - `css/tokens.css`：在 `:root` 中定义变量，例如 `--fg:#333; --fg-strong:#1d1d1f; --fg-muted:#666; --bg:#fff; --code-bg:#f5f5f7; --border:#e0e0e0; --link:#007aff; --content-font-size:16px; --content-line-height:1.8; --font-sans: ...; --font-mono: ...`；暗色值放在 `@media (prefers-color-scheme: dark) { :root:not([data-output]) {...} }` 中；输出模式放在 `:root[data-output] { 全部浅色值 }`。
   - `css/content.css`：所有 `.markdown ...`、`.tok-*`、`.mermaid-diagram`、`.math-*`、`.frontmatter`、`.footnotes` 规则，**颜色全部改为引用变量**。
   - `css/app.css`：其余界面规则。
   - `css/print.css`：见第 3 步。
2. 字体栈（写入 tokens）：
   ```css
   --font-sans: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Segoe UI", "Microsoft YaHei", "Noto Sans CJK SC", "Helvetica Neue", Arial, sans-serif;
   --font-mono: "SF Mono", Menlo, Consolas, "Cascadia Mono", "Noto Sans Mono", monospace;
   ```
3. `css/print.css`：
   ```css
   @media print {
     :root { --content-font-size: var(--print-font-size, 10.5pt) !important; --content-line-height: 1.6 !important; }
     html, body { background:#fff !important; color:#000 !important; height:auto !important; overflow:visible !important; }
     .toc-sidebar, .toc-toggle, .find-bar, .status, .modal-overlay, .image-lightbox, .mode-indicator,
     .edit-hint-bubble, .update-bubble, .welcome-overlay, .code-lang-label, .code-copy-btn, .remote-image-bar { display:none !important; }
     .scroll-wrap { position:static !important; overflow:visible !important; }
     .page { max-width:none !important; width:auto !important; margin:0 !important; padding:0 !important; }
     .markdown { font-size:var(--content-font-size) !important; line-height:var(--content-line-height) !important; min-height:0 !important; color:#000 !important; orphans:3; widows:3; }
     .markdown h1 { font-size:calc(var(--content-font-size) * 1.75); }
     .markdown h2 { font-size:calc(var(--content-font-size) * 1.4); }
     .markdown h3 { font-size:calc(var(--content-font-size) * 1.2); }
     .markdown h4 { font-size:calc(var(--content-font-size) * 1.05); }
     .markdown h1,.markdown h2,.markdown h3,.markdown h4 { break-after:avoid; page-break-after:avoid; }
     .print-h1-new-page .markdown h1:not(:first-child) { break-before:page; }
     .markdown pre,.markdown code,.markdown th,.markdown .math-block,.mermaid-diagram,.markdown-alert { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
     .markdown pre { break-inside:auto; white-space:pre-wrap !important; } .markdown pre.print-short { break-inside:avoid; }
     .markdown pre code { white-space:pre-wrap !important; overflow:visible !important; }
     .markdown table { break-inside:auto; } .markdown tr { break-inside:avoid; } .markdown thead { display:table-header-group; }
     .markdown img,.mermaid-diagram,.math-block { break-inside:avoid; }
     .markdown img { max-height:240mm; object-fit:contain; }
     .markdown a { color:#0645ad !important; text-decoration:none !important; }
     .print-show-urls .markdown a[href^="http"]::after { content:" (" attr(href) ")"; font-size:.85em; color:#555; word-break:break-all; }
     .print-hide-frontmatter .markdown .frontmatter { display:none !important; }
   }
   ```
   **注意**：删除旧 `styles.css` 中的 `@media print` 段，不要出现两套。
4. `index.html` 按顺序引入：tokens → content → app → print。同步更新打包资源清单。
5. 屏幕字号逻辑不变（`applyFontSize()` 继续设置 `--content-font-size`）；print.css 用 `!important` 覆盖，从而与屏幕缩放解耦。
**验收**（加入 `tests/test_output_quality.py`）
- 打印正文字形高度在 8.0–8.8（对应约 10.5pt；基线是 9.5）
- 严格满足 h1 > h2 > h3 > body
- 设置 `--content-font-size:22px` 后打印，各项字形高度与未设置时的差值 < 0.2
- 代码块区域存在非白色像素（栅格化后采样代码块位置）
- 屏幕视觉不变：e2e 截图与改动前对比无明显差异

---

### T04 原生打印引擎
**目标**：用自己的打印实现替换 pywebview 的 `print_webview()`，控制纸张、边距和背景。
**涉及文件**：`app.js` 中的 `printDocument()`（约第 2144 行）；`mdPreview.py` 菜单中的 `printDocument_`（约第 2660 行）；新建 `mdpreview_core/export/print_engine.py`
**步骤**
1. 新建 `print_engine.py`：
   ```python
   import AppKit, Foundation
   PAPER = {'a4': (595.28, 841.89), 'letter': (612.0, 792.0)}
   MARGINS_MM = {'narrow': (12, 12, 14, 12), 'normal': (18, 16, 20, 16), 'wide': (25, 25, 25, 25)}  # 上 右 下 左

   def default_paper():
       region = Foundation.NSLocale.currentLocale().objectForKey_(Foundation.NSLocaleCountryCode) or ''
       return 'letter' if region in ('US', 'CA', 'MX', 'PH') else 'a4'

   def make_print_info(paper='auto', margins='normal', save_to=None):
       info = AppKit.NSPrintInfo.sharedPrintInfo().copy()
       key = default_paper() if paper == 'auto' else paper
       w, h = PAPER[key]
       info.setPaperSize_(Foundation.NSMakeSize(w, h))
       t, r, b, l = (v * 72.0 / 25.4 for v in MARGINS_MM[margins])
       info.setTopMargin_(t); info.setRightMargin_(r); info.setBottomMargin_(b); info.setLeftMargin_(l)
       info.setHorizontalPagination_(AppKit.NSFitPagination)
       info.setVerticalPagination_(AppKit.NSAutoPagination)
       info.setHorizontallyCentered_(False); info.setVerticallyCentered_(False)
       if save_to:
           d = info.dictionary()
           d[AppKit.NSPrintJobDisposition] = AppKit.NSPrintSaveJob
           d[AppKit.NSPrintJobSavingURL] = Foundation.NSURL.fileURLWithPath_(save_to)
       return info

   def enable_background_printing(webview):
       prefs = webview.configuration().preferences()
       if prefs.respondsToSelector_('setShouldPrintBackgrounds:'):   # macOS 13.3+
           prefs.setShouldPrintBackgrounds_(True)

   def run(webview, window, info, show_panel, on_done):
       """on_done(success: bool) 在主线程回调"""
       enable_background_printing(webview)
       op = webview.printOperationWithPrintInfo_(info)          # 公开 API，macOS 11+
       op.setShowsPrintPanel_(show_panel); op.setShowsProgressPanel_(True)
       op.view().setFrame_(webview.bounds())                    # 防止部分系统版本打印空白【验证门】
       delegate = _PrintDelegate.alloc().initWithCallback_(on_done)
       op.runOperationModalForWindow_delegate_didRunSelector_contextInfo_(window, delegate, b'printOperationDidRun:success:contextInfo:', None)
   ```
   `_PrintDelegate` 是 `NSObject` 子类，选择器签名为 `v@:@Z^v`（参考附录 B 的写法），回调中调用 `on_done(bool(success))`，并持有自身引用，避免被 GC 回收。
2. `MarkdownAPI` 增加 `print_document(self, options)`：在主线程获取 webview（参照 `export_as_write` 中 `cocoa_mod.BrowserView.instances` 的取法），调用 `run(..., show_panel=True)`，通过 `threading.Event` 等待完成（不设 15 秒的硬超时；打印面板打开期间用户可能停留很久）。
3. JS `printDocument()` 改为：
   ```js
   async function printDocument() {
     const opts = await Bridge.call('get_output_settings');
     const restore = await OutputPrep.prepare('print', opts);   // T06；T06 之前先用最小实现：加 data-output、切预览、隐藏 TOC
     try { await Bridge.call('print_document', opts); } finally { restore(); }
   }
   ```
4. 打印前由 JS 给 `<pre>` 打标：行数 ≤ 25 的加 `print-short` 类；按选项给 `<html>` 加 `print-show-urls`、`print-hide-frontmatter`、`print-h1-new-page` 类，并设置 `--print-font-size`。
**【验证门】** 若 `printOperationWithPrintInfo_` 输出空白：改用 pywebview 同款私有 API `_printOperationWithPrintInfo_` 作为回退（用 `respondsToSelector_` 判断）。
**验收**：⌘P 弹出系统打印面板；选择"存储为 PDF"后，T03 的断言依然成立；用 output_probe 检测越界文字为 0；边距与选项一致（栅格化后检查左边第一个非白像素的位置，正常边距约 45pt）。

---

### T05 PDF 导出 = 打印到文件 + 后处理
**目标**：PDF 与打印结果完全一致，真分页，带页码、书签和元数据。
**涉及文件**：`mdPreview.py` 中的 `export_as_write`（pdf 分支）和 `_pdf_to_a4_longpage`；`app.js` 中的 `exportAsWrite`；新建 `mdpreview_core/export/pdf_post.py`
**步骤**
1. `export_as_write` 的 pdf 分支改为：`make_print_info(save_to=临时路径)` → `run(show_panel=False)` → `pdf_post.finalize(临时路径, 最终路径, meta)` → 原子写。
2. JS 端在 pdf 导出时传入 `meta = { title, headings: [{level, text}], pageNumbers: true, author: '' }`，`headings` 从渲染后的 DOM 收集（只取 h1–h3，text 去掉首尾空白）。
3. `pdf_post.py`：
   ```python
   import Quartz, Foundation, AppKit
   def finalize(src, dst, meta):
       doc = Quartz.PDFDocument.alloc().initWithURL_(Foundation.NSURL.fileURLWithPath_(src))
       if meta.get('pageNumbers'):
           doc = _stamp_page_numbers(src)      # 返回新的 PDFDocument
       _add_outline(doc, meta.get('headings', []))
       doc.setDocumentAttributes_({
           Quartz.PDFDocumentTitleAttribute: meta.get('title') or '',
           Quartz.PDFDocumentCreatorAttribute: 'mdPreview ' + APP_VERSION,
           Quartz.PDFDocumentAuthorAttribute: meta.get('author') or '',
       })
       if not doc.writeToURL_(Foundation.NSURL.fileURLWithPath_(dst)):
           raise IOError('write pdf failed')
   ```
   - `_stamp_page_numbers`：用 `CGPDFContextCreateWithURL` 新建 PDF，逐页 `CGPDFContextBeginPage` → `CGContextDrawPDFPage` → 用 `NSGraphicsContext.graphicsContextWithCGContext_flipped_(ctx, False)` 设为当前上下文 → 用 `NSAttributedString` 以 8pt、`#888` 在页面底部居中绘制 `"{i} / {n}"`（y = 底边距的一半）→ `EndPage`。完成后重新打开并返回。
   - `_add_outline`：`root = Quartz.PDFOutline.alloc().init()`；维护层级栈；对每个标题用 `doc.findString_withOptions_(text, NSCaseInsensitiveSearch)` 得到全部匹配，**选择第一个页码 ≥ 上一个标题页码的匹配**；`PDFDestination.alloc().initWithPage_atPoint_(page, (0, bounds.origin.y + bounds.size.height + 10))`；按 level 挂到对应父节点；最后 `doc.setOutlineRoot_(root)`。匹配不到的标题跳过，不报错。
4. 保留"连续长页 PDF"作为导出面板中的一个选项（`pdf_layout: 'paged' | 'continuous'`）。continuous 模式沿用旧的 `_pdf_to_a4_longpage`，但当总高度超过 14000pt 时，按 14000pt 切成多页并提示用户。
5. 删除 15 秒轮询，改用 `threading.Event().wait(timeout=600)`。
6. **【验证门】链接**：用 probe 统计 PDF 中的 Link 注释数量。如果为 0，在 JS 中收集 `a[href^=http]` 的文字，在后处理中用 `findString` 定位并添加 `PDFAnnotation`（子类型 Link，设置 `setURL_`）。
**验收**
- `zh-longform.md` 导出后页数 > 1，纸张为 A4 或 Letter
- 每页底部能提取到 `n / N` 文字
- `doc.outlineRoot().numberOfChildren() > 0`
- 标题属性等于文档名
- 与"⌘P → 存储为 PDF"相比，第 1 页栅格化后的像素差 < 1%
- Acrobat Reader 可以打开（人工检查，记录在 T33）

---

### T06 输出准备钩子与导出设置
**目标**：所有输出共用同一套准备与恢复逻辑；导出选项可以配置并持久化。
**新增**：`frontend/output/prepare.js`、Python 端的 `get_output_settings` / `set_output_settings`
**步骤**
1. `OutputPrep.prepare(kind, opts)` 返回 `restore()`：
   - 处于源码模式时调用现有的 `showPreviewForCapture()`（`app.js` 约第 2122 行），`restore` 时调用 `restoreSourceMode()`
   - 给 `<html>` 设置 `data-output="print|pdf|png|html|richtext"`（触发 tokens.css 中的浅色变量）
   - 隐藏 TOC 和所有浮层（沿用 `exportAsWrite` 中已有的 stash/restore 逻辑，把它搬到这里）
   - **Mermaid**：如果当前是暗色主题，用 `theme:'default'` 重新渲染所有图（复用 `renderMermaidDiagrams`，需先清空 `mermaidSvgCache`），`restore` 时再恢复原主题
   - **懒渲染的内容（T11、T24）全部强制渲染**
   - `await Promise.all([...document.images].map(i => i.decode().catch(() => {})))`；`await document.fonts.ready`；再等两个 `requestAnimationFrame`
   - 根据选项添加 `print-*` 类，设置 `--print-font-size`（small=9.5pt / normal=10.5pt / large=12pt）
2. 配置项（`config.json` 中的 `output` 字段，默认值如下）：
   ```json
   {"paper":"auto","margins":"normal","font":"normal","page_numbers":true,"show_urls":false,
    "hide_frontmatter":true,"h1_new_page":false,"pdf_layout":"paged","png_width":"original"}
   ```
   读写复用现有的 `load_config` / `update_config`（带锁）。
3. 导出面板：扩展 `_run_format_panel`（`mdPreview.py` 约第 395 行）的附加视图。根据所选格式显示对应的 `NSPopUpButton` 和 `NSButton`（复选框）。布局沿用 `_layout_format_acc` 的计算方式；用户点"保存"时把选项写回配置。现有的 `tests/test_format_panel_layout.py` 需要同步扩展。
**验收**：暗色模式下导出的 PDF 中，Mermaid 的 SVG 填充色不是暗色（检查栅格化后图区域的平均亮度 > 200）；暗色模式下打印正文为黑色；选项重启后仍然保留。

---

### T07 HTML 导出重写
**涉及**：`buildHtml()`（`app.js` 约第 1885 行）
**步骤**
1. 构建时把 `tokens.css` + `content.css` + `print.css` 的文本读入（可用 `fetch('css/content.css')`，或由 Python 提供 `get_export_css()`），**原样内联**到 `<style>` 中。删除手写的那套 CSS。
2. `<html lang>`：统计正文中 CJK 字符（`/[㐀-鿿]/`）的占比，超过 10% 设为 `zh-CN`，否则设为 `en`；如果有 Front Matter 中的 `lang` 字段，以它为准。
3. 外层包装 `<main class="page"><article class="markdown">…</article></main>`，使 content.css 的选择器生效。
4. 加入 `<meta name="generator" content="mdPreview X.Y.Z">`；标题数 ≥ 5 时，在顶部生成 `<nav class="export-toc">` 目录（`<details>` 可折叠）。
5. 暗色：内联的 tokens.css 自带 `prefers-color-scheme` 暗色值，但需要去掉 `:root:not([data-output])` 的限定，或在导出时专门生成一份不带限定的版本。
6. KaTeX 公式（T11）导出时需要一并内联 KaTeX 的 CSS 和字体（转为 base64 的 woff2，只内联文档实际用到的字体文件）。
**验收**（jsdom 测试）：输出中不含 `<link` 和 `<script`；包含 `.tok-keyword`；`lang` 正确；无外部 URL（https 图片除外）；用 Playwright 分别以 chromium 和 webkit 打开截图，与预览视觉一致。

---

### T08 纯文本导出修正
**新增**：`frontend/output/plaintext.js` 中的 `toPlainText(rootEl)`
**规则**：标题输出为独立一行，前后各空一行；`ul` 项前缀 `• `，`ol` 项前缀 `1. `（按缩进层级每级加 2 个空格）；任务列表用 `[ ]` / `[x]`；表格每行单元格用 `\t` 连接；链接输出 `文本 (URL)`（文本与 URL 相同时只输出一次）；代码块原样输出，前后空一行；图片输出 `[图片: alt]`；Mermaid 输出 `[图表]`；公式输出 LaTeX 原文；脚注放到文末。
导出面板中的格式名称保持"纯文本"；另外新增一个格式"Markdown 源文件"（等同于现有的 md 导出）。
**验收**：用 fixtures 生成的 txt 中不含 `**`、`##`、`|---`；包含 `• `；与快照文件一致。

---

### T09 PNG 导出改为原生实现
**目标**：去掉 html2canvas，渲染效果与屏幕 100% 一致。
**步骤**
1. 复用现有的 createPDF 流程（屏幕媒体，按全文档高度），但先执行 `OutputPrep.prepare('png')`（浅色），并把 `.page` 宽度固定为：`png_width=mobile` 时 540px（导出 2× 后为 1080px），`original` 时用当前宽度。
2. 新建 `mdpreview_core/export/snapshot.py`：把 PDF 第 1 页用 `CGBitmapContextCreate` 按 2× 栅格化（白底），通过 `CGImageDestination` 写成 PNG。
3. 像素限制：宽 × 高 > 120M 像素时，按高度切成多张图片，命名为 `name-1.png`、`name-2.png`……，并在状态栏提示；或者自动降到 1× 缩放（导出面板中二选一，默认切图）。
4. 删除 `buildPng`、`sanitizeCloneColors`、`convertColorFunction` 和 `html2canvas.min.js`（同步更新 vendor 清单、spec、checksums）。
**验收**：暗色模式下导出的 PNG，正文区域平均亮度 > 200 且文字像素是深色；`long-code.md` 导出成功；`grep html2canvas -r app.js` 无结果。

---

### T10 Word 导出：原生 OOXML
**目标**：生成的 docx 在 Word、Pages、WPS、Google Docs、LibreOffice、飞书/钉钉预览中都能完整显示，并且标题使用 Word 的内置标题样式。
**步骤**
1. `npm i -D docx@latest`，在 `scripts/vendor.mjs` 中把它的浏览器 UMD 构建（在 `node_modules/docx/dist/` 下查找 `*.umd.*js`，以实际文件名为准）复制为 `vendor/docx.umd.js`，并复制许可证。
2. 新建 `frontend/output/docx.js`，对外提供 `buildDocxFromMarkdown(markdown, ctx)`，返回 base64 字符串：
   - 用 `marked.lexer(markdown)`（使用与 `MarkdownPipeline` 相同的扩展配置，以识别公式和脚注 token）
   - 映射表：

   | token | docx |
   |---|---|
   | heading(depth) | `new Paragraph({ heading: HeadingLevel['HEADING_'+depth], children: runs })` |
   | paragraph | `Paragraph`；`strong` → `bold`，`em` → `italics`，`del` → `strike`，`codespan` → `font: mono` 加浅灰底纹 `shading`，`link` → `ExternalHyperlink` |
   | list / list_item | 使用 `numbering` 配置（bullet 和 decimal 各一套，最多 4 级）；任务项文本前加 `☐ ` 或 `☑ ` |
   | code | 单行单列 `Table`，单元格底纹为 `F5F5F7`，等宽 9pt；如果有语法高亮的 token 颜色，就按 token 拆分 run 并设置 color |
   | table | `Table`，首行设 `tableHeader: true`（跨页重复表头），宽度 100%，按对齐方式设置段落对齐 |
   | blockquote | 段落左边框 + 左缩进 |
   | image | 通过 `Bridge.call('read_image_for_export', src)` 拿到 base64 → `ImageRun`；按页面可用宽度（约 16cm）等比缩放，需要先用 `Image()` 读取原始尺寸 |
   | mermaid（`code` 且 lang=mermaid） | 取预览 DOM 中对应的 SVG → 在 canvas 上按 2× 绘制 → PNG → `ImageRun` |
   | 公式 | 取 KaTeX 渲染出的节点，同样栅格化为 PNG（第一版）；行内公式的高度按字号对齐 |
   | footnote | docx 的 `footnotes` 配置加 `FootnoteReferenceRun` |
   | hr | 段落下边框 |
   | html | 剥离标签后作为纯文本段落 |
   - 默认样式：正文按 `output.font` 选项取 10.5/11/12pt；西文字体 `Calibri`，东亚字体 `PingFang SC`（在 run 上设置 `font: { ascii, eastAsia, hAnsi }`，Windows 上缺字体时会自动回退）；行距 1.3；段后 6pt。
   - 文档属性：`title`、`creator: 'mdPreview'`。
3. `exportAsWrite` 的 docx 分支改为调用新实现；旧的 `buildDocx` 和 `html-docx-js.js` 保留一个版本，通过隐藏配置 `output.legacy_docx=true` 启用；**下一个版本删除**。
**验收**（Python 测试）：`zipfile` 打开 docx 后 `word/document.xml` 中不含 `altChunk`；含 `w:pStyle w:val="Heading1"`；表格数量、图片数量（`word/media/*`）与 fixture 一致；如果安装了 `textutil`，`textutil -convert txt` 输出包含正文关键字。人工兼容性检查记录在 T33。

---

### T11 数学公式（KaTeX）
**步骤**
1. vendor `katex.min.js`、`katex.min.css`、`fonts/*.woff2`，以及 `contrib/mhchem.min.js`（可选）。
2. `frontend/markdown-pipeline.js` 的 `mathExtensions` 中新增两个 token：
   - 行内 `\(...\)`：`/^\\\((.+?)\\\)/`
   - 块级 `\[...\]`：`/^\\\[([\s\S]+?)\\\](?:[ \t]*\n|$)/`
   渲染出的 HTML 与现有 `$` 形式完全一致（class 相同、`data-raw` 保存原文），保证回写 Markdown 时原样保留。**同时要确认反斜杠转义 `\\(` 不会被误识别**，为此补充测试。
3. 新建 `frontend/render/math.js`：
   ```js
   async function renderMath(root, { eager = false } = {}) {
     const nodes = root.querySelectorAll('.math-inline:not([data-rendered]), .math-block:not([data-rendered])');
     if (!nodes.length) return;
     await ensureLib('katex.min.js', 'katex');  // 复用 app.js 中的 ensureLib；首次使用时插入 katex.min.css
     for (const el of nodes) {
       const tex = el.textContent; const display = el.classList.contains('math-block');
       const html = katex.renderToString(tex, { displayMode: display, throwOnError: false, output: 'htmlAndMathml', trust: false, strict: 'ignore' });
       el.innerHTML = MarkdownPipeline.cleanMath(html);
       el.setAttribute('data-rendered', '1');
     }
   }
   ```
4. `markdown-pipeline.js` 新增 `cleanMath(html)`：单独的 DOMPurify 配置——允许 `span`、`math`、`semantics`、`mrow`、`mi`、`mo`、`mn`、`msup`、`msub`、`mfrac`、`msqrt`、`mroot`、`mtable`、`mtr`、`mtd`、`mtext`、`mspace`、`annotation`、`svg`、`path`、`line` 等 KaTeX 输出会用到的标签，允许 `style`、`class`、`aria-hidden`、`encoding`；禁止所有 URL 属性。
5. 公式的 CSS：渲染完成的节点去掉原来的等宽灰框（`.math-inline[data-rendered]` 设为 `background:none; border:0; font-family:inherit`）；渲染出错的节点（KaTeX 会输出 `.katex-error`）保留源码样式并标红。
6. 编辑行为：预览模式下点击公式时，显示 `data-raw` 中的原文供编辑（沿用现有 `contenteditable=false` 的处理方式，不新增编辑能力）。
**验收**：`math.md` 中四种写法都能渲染出 `.katex` 节点；预览模式编辑后保存，Markdown 中公式原文逐字节不变；错误公式不会中断渲染；打印 PDF 中公式可见。

---

### T12 复制为富文本
**步骤**
1. 菜单"编辑 → 复制为富文本"，快捷键 ⇧⌘C；同时在"编辑"菜单中加入"复制为 Markdown"（⌥⌘C）。
2. JS `copyAsRichText()`：
   - 有选区时取选区的 `cloneContents()`，否则取整个 `#content`
   - 执行 `OutputPrep.prepare('richtext')`（浅色）
   - 把副本放进一个隐藏容器（挂在 `.markdown` 下，确保样式命中），遍历所有元素，读取 `getComputedStyle` 中以下属性并写入 `style` 属性：`color, background-color, font-size, font-weight, font-style, font-family, line-height, text-decoration, margin-*, padding-*, border-*, border-collapse, text-align, white-space, list-style-type, vertical-align`；只写与父元素不同的值，以控制体积
   - Mermaid 图和公式转成 PNG 的 data URL `<img>`（复用 T10 的栅格化函数）
   - 删除 `class`、`id`、`data-*`、`contenteditable`
   - 纯文本使用 T08 的 `toPlainText`
   - 调用 `Bridge.call('set_clipboard_rich', html, plain)`
3. 新建 `mdpreview_core/clipboard.py`：
   ```python
   def set_rich(html, plain):
       pb = AppKit.NSPasteboard.generalPasteboard(); pb.clearContents()
       data = html.encode('utf-8')
       attr, _ = AppKit.NSAttributedString.alloc().initWithHTML_documentAttributes_(Foundation.NSData.dataWithBytes_length_(data, len(data)), None)
       rtf = attr.RTFFromRange_documentAttributes_((0, attr.length()), {}) if attr else None
       pb.setString_forType_(html, AppKit.NSPasteboardTypeHTML)
       if rtf: pb.setData_forType_(rtf, AppKit.NSPasteboardTypeRTF)
       pb.setString_forType_(plain, AppKit.NSPasteboardTypeString)
   ```
   必须在主线程执行（`AppHelper.callAfter` + Event 等待）。`initWithHTML_` 如果遇到 data URL 图片导致卡顿，就在生成 RTF 时把 img 去掉（HTML 格式中保留图片）。
**验收**：单元测试检查内联样式存在、无 class 属性；人工在微信、飞书、钉钉、邮件、Word、备忘录中各粘贴一次，标题、粗体、表格、代码底色都保留（记录到 T33）。

---

### T13 GitHub Alerts、代码复制按钮、任务列表
1. **Alerts**：在 marked 中加一个 `walkTokens`（或 blockquote renderer 扩展），识别首行为 `[!NOTE]`、`[!TIP]`、`[!IMPORTANT]`、`[!WARNING]`、`[!CAUTION]` 的引用块，输出 `<div class="markdown-alert markdown-alert-note" data-raw="...">`，内部包含 `<p class="markdown-alert-title">` 和图标（内联 SVG，取 Octicons 风格的简单图形，或改用 emoji 以避免版权问题）。回写 Markdown 时：Turndown 需要新增一条规则，把它还原为 `> [!NOTE]` 格式（`data-raw` 优先）。颜色变量写在 tokens.css 中，需同时提供暗色版本。DOMPurify 中加入 `markdown-alert` 相关 class（class 本来就允许）。
2. **代码复制按钮**：在 `renderMarkdown` 之后为每个 `pre` 加上 `<button class="code-copy-btn" contenteditable="false" aria-label="复制代码">`，位置在语言标签左侧，鼠标悬停 `pre` 时显示；点击复制 `code.textContent`，显示"已复制"1.5 秒。打印和导出时隐藏（已在 print.css 和导出清理中处理）。**HTML 导出和 Turndown 回写时必须移除该按钮**（加入 `buildHtml` 的移除列表和 turndown 的 remove 规则）。
3. **任务列表**：预览模式下的复选框可以点击，点击后修改源码中对应行的 `[ ]` / `[x]`（通过 checkbox 在全部任务项中的序号，定位到源码中第 N 个任务标记），并标记文档为已修改。
**验收**：`alerts.md` 往返（渲染 → 回写）后与原文一致；复制按钮不会出现在导出的 HTML 和 docx 中；勾选任务后保存，源码对应位置被修改。

---

### T14 相对文档链接与拖入打开
1. 链接点击处理（`app.js` 约第 3942 行，`document.addEventListener('click', ...)` 末尾）：若 `href` 不是外部链接、不是 `#` 锚点：
   - 拆出 `path#hash`；URL 解码；基于当前文件目录解析出绝对路径
   - 调用 `Bridge.call('open_linked_document', absPath, hash, e.metaKey)`
2. Python `open_linked_document(path, hash, same_window)`：
   - 规范化路径（`os.path.realpath`），只允许打开 `.md`、`.markdown`、`.mdown`、`.mkd`、`.mkdown`、`.txt`；其他类型用 `NSWorkspace.openURL`（即系统默认程序）打开，**打开前弹出确认**（防止文档诱导用户执行 `.command`、`.app`）
   - 文件不存在时返回错误，JS 显示"找不到链接的文件"
   - 打开新窗口时复用 `handle_opened_file`；打开后通过 `evaluate_js` 调用 `scrollToHash(hash)`
3. 拖入：`handleImageDrop` 改为通用的 `handleDrop`——拖入的是 Markdown 文件就调用 `open_linked_document`；是图片则交给 T18 处理；其他类型忽略。
**验收**：e2e 测试点击 `./docs/b.md#section` 会调用桥接方法并带上正确参数；Python 测试覆盖路径解析、`../` 和后缀白名单。

---

### T15 远程图片隐私控制
1. 设置项 `remote_images: 'ask' | 'always' | 'never'`，默认 `'ask'`。
2. 在 `rewriteRelativeImages`（`app.js` 约第 840 行）中：当模式不是 `always` 时，对 `http(s)` 图片把 `src` 移到 `data-remote-src`，替换为一个占位 SVG data URL（灰框 + 图片图标，按 alt 文字显示）。
3. 存在远程图片且模式为 `ask` 时，在文档顶部显示一条提示条 `.remote-image-bar`："此文档包含 N 张远程图片，加载后对方服务器会知道你打开了此文件。[加载] [总是加载]"。"加载"只对当前文档生效；"总是加载"写入设置。
4. 导出：HTML 保留原始远程 URL；PDF、PNG、Word、富文本在导出前询问是否加载远程图片（未加载就显示占位图）。
5. 回写 Markdown 时使用 `data-remote-src` 还原原始 URL（**这是最容易丢数据的地方，必须有测试**）。
**验收**：用 e2e 测试服务器记录请求，默认打开 `images.md` 时没有对远程图片的请求；点击"加载"后才有；预览编辑后保存，图片 URL 不变。

---

### T16 CSP 与去除内联事件
1. 把 5 处内联 `onclick` 改为 `addEventListener`：`index.html:38,43,66`；`app.js:728`（frontmatter 折叠按钮，改用事件委托：`content.addEventListener('click', e => { if (e.target.closest('.frontmatter-toggle')) ... })`）；`app.js:2180`（弹窗关闭按钮，改为创建元素后绑定事件）。
2. `index.html` 的 `<head>` 中加入：
   ```html
   <meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' file: data: blob: https:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'">
   ```
3. **【验证门】** 页面从 `file://` 加载时，WebKit 对 `'self'` 的判定可能不同。如果脚本无法加载，`script-src` 改为 `'self' file:`；确认 pywebview 注入的桥接脚本仍然正常（它通过原生 `evaluateJavaScript` 执行，通常不受 CSP 限制）；确认 Mermaid 不需要 `unsafe-eval`。如果需要，就**只放开 Mermaid**——在 Mermaid 渲染完成后不再执行其他动态代码，并在本卡记录原因。
4. `img-src` 中的 `https:` 与 T15 配合：远程图片的拦截发生在 JS 层，CSP 这里只作为兜底。
**验收**：`grep -n "onclick=" app.js index.html` 无结果；e2e 中注入 `<img src=x onerror=alert(1)>`、`<script>` 均不执行；全部功能 e2e 通过；控制台没有 CSP 违规报错。

---

### T17 快捷键修正与设置窗口
1. **快捷键调整**（菜单与 JS 后备处理同时修改，并更新 README 和 T26 的快捷键表）：

   | 功能 | 原 | 新 |
   |---|---|---|
   | 设置 | 无 | **⌘,** |
   | 加宽页面 / 收窄页面 | ⌘. / ⌘, | **⌥⌘= / ⌥⌘-** |
   | 重置宽度 | ⌘0 | **⌥⌘0** |
   | 重置字号 | 无 | **⌘0** |
   | 预览/源码切换 | ⌘E | 保持 ⌘E（同时在设置中说明） |

2. **设置窗口**：使用现有的 modal 机制（`.modal-overlay`），新建 `frontend/settings.js`，按分组展示：
   - **通用**：界面语言（跟随系统 / English / 简体中文 / 繁體中文）、启动时恢复上次打开的文档、自动检查更新（默认开启，说明会访问 GitHub）
   - **阅读**：默认字号、默认宽度、远程图片（询问 / 总是 / 从不）、外部修改时自动刷新
   - **导出**：T06 中的全部选项
   - **隐私**：说明本应用会访问哪些网络地址（仅 GitHub 更新检查，以及用户允许的远程图片）
   - **关于**：版本号、致谢（第三方许可证，来自 T30）、GitHub 链接、"导出诊断信息"
   Python 提供 `get_settings()` / `set_settings(patch)`，对应 `config.json` 的 `settings` 字段，写入时校验字段类型与取值范围，丢弃未知字段。
3. 菜单：在应用菜单中加入"设置…"（⌘,），点击后执行 JS `openSettings()`。
**验收**：⌘, 打开设置窗口；修改设置后重启应用，设置仍然保留；旧快捷键不再触发宽度调整；`tests/test_format_panel_layout.py` 等现有测试通过。

---

### T18 编辑增强：图片粘贴与拖入、源码模式快捷键、替换
1. **图片保存**：Python `save_image_asset(doc_path, base64_data, ext, suggested_name)`：
   - 文档未保存过（Untitled）时返回 `need_save`，JS 提示"请先保存文档再插入图片"并打开保存面板
   - 目标目录：`<文档目录>/assets/`（如不存在则创建）；文件名：`<文档名>-YYYYMMDD-HHMMSS[-n].<ext>`，只允许 `[A-Za-z0-9._-]` 字符（用 `re.sub` 替换其他字符）
   - 写入使用原子写；返回相对路径 `assets/xxx.png`
2. **粘贴**：在 `paste` 事件中，如果 `clipboardData.items` 里有 `image/*` 类型且没有文字内容，就读取为 base64 → 保存 → 在光标处插入 `![](assets/xxx.png)`。
3. **拖入**：拖入图片文件时同样复制到 `assets/`（通过 `FileReader` 读取后保存），插入相对路径。**不再插入绝对路径**。
4. **源码模式快捷键**（只在 `#textarea` 获得焦点时生效，修改文字时使用 `document.execCommand('insertText')` 以保留撤销栈）：
   - ⌘B → `**选中文字**`；⌘I → `*选中文字*`；⌘K → `[选中文字](|)`，光标放在括号内；没有选中文字时插入一对标记，光标置于中间；再次按下时如果选区两侧已有标记，则去掉标记
   - Enter：当前行是 `- `、`* `、`1. `、`- [ ] `、`> ` 开头时，新行自动带上相同前缀（有序列表序号加 1）；当前行只有前缀而没有内容时，删除前缀并结束列表
   - Tab / ⇧Tab：对选中的所有行增加或减少两个空格的缩进
5. **查找替换**：查找栏增加"替换"输入框和"替换 / 全部替换"按钮，只在源码模式下显示；全部替换作为一次撤销操作。
**验收**：JS 单元测试覆盖各种快捷键的边界情况（空选区、跨行选区、已有标记的选区）；Python 测试覆盖文件名清洗和同名冲突时追加 `-n`；e2e 测试粘贴图片后 Markdown 中出现相对路径。

---

### T19 窗口与阅读状态
1. **字号持久化**：模仿 `save_page_width`，新增 `save_font_size`，启动时读取（`app.js` 约第 1310 行的 `contentFontSize` 初始化处）。
2. **窗口位置**：在 `on_window_closing` 中通过 `window.native`（NSWindow）读取 `frame()`，保存到 `config.window_frame`；`create_window` 时如果没有传入 x、y，就使用保存的值（叠加现有的级联偏移量），并检查位置是否在当前任意屏幕内（`NSScreen.screens()`），不在就居中。
3. **阅读位置**：JS 在滚动时（防抖 500ms）调用 `Bridge.callSafe('save_reading_position', {ratio, headingId})`；Python 以 `sha256(path)` 作为键，保存在 `reading_positions` 中（LRU 300 条，**不保存路径明文**）。打开文档并渲染完成后，优先按 `headingId` 恢复位置，找不到再按 `ratio` 恢复。
4. **会话恢复**：设置项"启动时恢复上次打开的文档"开启时，退出前把仍然打开的文件路径列表保存到 `config.session`，下次启动时依次打开（跳过已不存在的文件）。
5. **原生标签页【验证门】**：在窗口创建后调用 `nswindow.setTabbingMode_(NSWindowTabbingModePreferred)`，并在 Window 菜单中保留"合并所有窗口"。如果与 pywebview 的窗口生命周期冲突（关闭标签页时没有触发保存确认、或窗口状态错乱），就放弃这一项，并在本卡中记录原因。
**验收**：Python 测试覆盖 LRU 淘汰、屏幕边界校验；人工验证重启后能恢复窗口位置、字号和阅读位置。

---

### T20 外部修改自动刷新
1. 新建 `mdpreview_core/watcher.py`：一个后台线程，每 1 秒对所有已打开的文件执行 `os.stat`，比较 `(st_mtime_ns, st_size)`；不引入 watchdog 等新依赖。
2. 检测到变化后：
   - 如果这次变化是应用自己保存造成的（与 `_record_baseline_stat` 记录的基线一致），忽略
   - 文档没有未保存修改，且设置中开启了自动刷新：通过 `evaluate_js('reloadFromDisk()')` 重新加载，保持当前滚动位置（使用 T19 的 headingId 逻辑），状态栏提示"文件已在外部更新"
   - 文档有未保存修改：调用现有的冲突处理流程（`native_conflict_prompt`），不自动覆盖
   - 文件被删除或重命名：标题栏显示"（已删除）"，保存时走"另存为"
3. 窗口关闭时从监视列表中移除；整个应用退出时线程结束（daemon 线程）。
**验收**：Python 测试中修改临时文件后，回调在 2 秒内被触发；dirty 状态下不触发自动刷新；自己保存不触发。

---

### T21 中文排版
1. 渲染完成后根据内容设置 `document.documentElement.lang`（规则与 T07 相同）。
2. 在 content.css 中，`:lang(zh) .markdown`：`line-height: 1.8`；`text-align: justify`（可选，需对比效果后决定）；`text-autospace: normal`（Safari 18.4 及以上支持，旧版本会自动忽略）。
3. 中文标题去掉负字距（`letter-spacing:-0.5px` 只对 `:lang(en)` 生效）。
4. 粗体在 PingFang 下字重 600 比 700 更协调：`:lang(zh) .markdown strong { font-weight: 600 }`。
**验收**：e2e 截图对比；`zh-longform.md` 打印后人工确认效果。

---

### T22 无障碍
1. 对比度：`.welcome-overlay` 文字改为 `#6e6e73`（浅色）和 `#a1a1a6`（暗色）；所有提示文字的对比度不低于 4.5:1。
2. `@media (prefers-reduced-motion: reduce)` 下关闭所有 `transition` 和 `animation`。
3. TOC：`nav` 内改用 `<ul>` 结构；当前所在章节加 `aria-current="true"`。
4. 查找栏的输入框加 `aria-label`，结果计数区域加 `role="status"`。
5. 所有图标按钮都要有 `aria-label`（使用 i18n 文案）。
6. 键盘：Tab 顺序合理；所有弹窗打开时聚焦第一个控件，按 Esc 关闭并把焦点还给原来的位置（`modalOverlay` 已有部分实现，扩展到设置窗口和提示条）。
**验收**：Playwright 中运行 `@axe-core/playwright`（开发依赖），检测结果中没有 serious 或 critical 级别的问题。

---

### T23 国际化
1. 新建 `frontend/i18n.js` 和 `locales/en.json`、`zh-Hans.json`、`zh-Hant.json`。键名使用语义化名称（如 `export.failed`）。
2. 为了降低迁移风险，保留 `t(en, zh)` 的函数签名：内部以英文原文作为键，在字典中查找当前语言的译文，查不到时退回到传入的 `en` 或 `zh`。先把现有调用全部收录进字典（写一个脚本 `scripts/extract-i18n.mjs`，用正则提取 `t('...', '...')`，生成 en 和 zh-Hans 的 json），再把繁体中文的翻译补上（可以用 OpenCC 的规则转换后人工校对用词）。
3. Python 的 `_t(en, zh)` 也做同样处理，读取同一份 locales 目录（菜单使用）。
4. 语言选择：设置中的"界面语言"选项优先，否则跟随系统（沿用 `_is_chinese_locale`，并扩展识别 `zh-Hant`、`zh-TW`、`zh-HK`）。
**验收**：测试检查三个 json 的键集合完全一致；把语言切换为繁体中文后，菜单和界面中没有简体字残留（用一份常见简繁对照字表检查）。

---

### T24 性能
1. **基线**：新增 `tests/e2e/perf.spec.js`（只在 webkit 项目中运行），分别生成 100KB、1MB、5MB 的 Markdown（混合标题、表格、代码），测量：首次渲染耗时、切换到源码模式、切回预览、滚动 TOC 高亮更新。结果写入 `WorkSpace/perf.json`。
2. **懒渲染**：Mermaid 和 KaTeX 改为 `IntersectionObserver`（`rootMargin: '800px'`），元素进入视口附近时才渲染；`OutputPrep.prepare` 会强制渲染全部内容（T06）。
3. **启动**：确认 `startup_ready(ms)` 写入日志，并记录"进程启动 → 首屏渲染完成"的时间；确保启动时不加载 `turndown.js`（检查当前是否在启动阶段被加载）、不加载 mermaid 和 katex。
4. **预算**（写进测试）：1MB 文档首次渲染 < 1500ms；5MB 文档不崩溃，且 30 秒内完成渲染；冷启动 < 1.5s。如果没有达到预算，先找出瓶颈（用 `performance.mark` 分段计时）并记录，暂不修改架构。
**验收**：perf 测试通过并产出 json；e2e 测试确认滚动到 Mermaid 图之前没有调用 `mermaid.render`。

---

### T25 诊断与反馈
1. 新增"帮助"菜单：
   - **mdPreview 帮助**：打开 GitHub README
   - **快捷键一览**（T26）
   - **打开示例文档**（T26）
   - **报告问题…**：打开 `https://github.com/tahoeliu/mdPreview/issues/new?template=bug.yml&version=X&os=Y&arch=Z`，**只带版本号、系统版本、芯片架构，不带任何文档内容**
   - **导出诊断信息…**：生成一个 zip，包含版本号、系统版本、芯片架构、`config.json`（去掉 `recent_files`、`session`、`reading_positions` 等含路径的字段）、日志最后 2000 行（写入前把用户主目录路径替换为 `~`）。保存到用户选择的位置
2. 日志统一：Python 日志写到 `~/Library/Logs/mdPreview/mdPreview.log`（按大小轮转，现有的轮转逻辑已存在，需确认路径与 Cask 中 `zap` 的路径一致——目前 Cask 写的是 `~/Library/Logs/mdPreview.log`，二者要统一）。
3. 未捕获的 Python 异常：设置 `sys.excepthook` 和 `threading.excepthook`，写入日志。
**验收**：诊断 zip 中搜索不到用户名（`os.getlogin()`）和文档正文片段；Issue 链接参数正确。

---

### T26 新用户引导
1. **示例文档**：`resources/Welcome.md`（中英各一份，按系统语言选择），一页内展示所有能力：标题、表格、代码、Mermaid、公式、Alerts、脚注、任务列表，以及"如何导出、打印、复制为富文本"。在"帮助 → 打开示例文档"中以只读副本打开（复制到临时目录，避免用户误改）。
2. **首次启动**（配置中没有 `onboarded` 字段时）：欢迎页显示三个按钮——"打开文件…"、"查看示例"、"设为 .md 默认打开方式"（调用已有的 `set_as_default_for_md`）。
3. **快捷键一览**：一个弹窗，内容由同一份快捷键定义表生成（菜单定义与这张表共用数据源，避免两处不一致）。
4. **更新后说明**：版本号变化后的第一次启动，在状态栏提示"已更新到 X.Y.Z · 查看新功能"，点击后打开内置的 `CHANGELOG.md` 中对应版本那一节（渲染显示）。
**验收**：删除配置后首次启动出现引导；更新版本号后出现提示。

---

### T27 分发（ad-hoc 签名下的最佳方案）与发布签名
**背景**：ad-hoc 签名的应用如果带有 `com.apple.quarantine` 属性（浏览器下载的文件都会带），Gatekeeper 会拦截。但 **curl 下载的文件不会被加上这个属性**，应用内更新器用 urllib 下载的文件同样不会。因此要把"一行命令安装"作为首选安装方式。
1. **Release 产物**：`mdPreview-X.Y.Z-universal.dmg`、`mdPreview-X.Y.Z-universal.zip`（`ditto -c -k --keepParent`）、`SHA256SUMS`、`SHA256SUMS.sig`。
2. **发布签名**（ECDSA P-256，不需要 Apple 证书）：
   - 一次性操作：`openssl ecparam -name prime256v1 -genkey -noout -out release-key.pem`；导出公钥 `openssl ec -in release-key.pem -pubout -outform DER | tail -c 65 > release-pub.raw`（65 字节的未压缩公钥），以 base64 形式写入 `mdpreview_core/release_sig.py` 的常量 `RELEASE_PUBKEY_B64`。**私钥只保存在本地和 GitHub Actions secret 中，绝不提交到仓库。**
   - 签名：`openssl dgst -sha256 -sign release-key.pem -out SHA256SUMS.sig SHA256SUMS`（输出 DER 格式的 ECDSA 签名）
   - 验证（`release_sig.py`，使用已依赖的 `pyobjc-framework-Security`）：
     ```python
     import Security, Foundation, base64
     def verify(message: bytes, der_sig: bytes) -> bool:
         raw = base64.b64decode(RELEASE_PUBKEY_B64)
         attrs = {Security.kSecAttrKeyType: Security.kSecAttrKeyTypeECSECPrimeRandom,
                  Security.kSecAttrKeyClass: Security.kSecAttrKeyClassPublic,
                  Security.kSecAttrKeySizeInBits: 256}
         key, err = Security.SecKeyCreateWithData(Foundation.NSData.dataWithBytes_length_(raw, len(raw)), attrs, None)
         if key is None: return False
         ok, err = Security.SecKeyVerifySignature(key, Security.kSecKeyAlgorithmECDSASignatureMessageX962SHA256,
                       Foundation.NSData.dataWithBytes_length_(message, len(message)),
                       Foundation.NSData.dataWithBytes_length_(der_sig, len(der_sig)), None)
         return bool(ok)
     ```
     （PyObjC 对输出参数 `error` 的返回形式以实际为准；写测试时先用 openssl 生成的样本验证一遍。）
   - 更新流程（`mdpreview_core/release.py` 及 `scripts/install_update.py`）：先下载 `SHA256SUMS` 和 `.sig` → 验签 → 再比对 dmg 或 zip 的 SHA-256。**验签失败就中止更新**。保留现有的 GitHub API 摘要比对作为第二道校验。
3. **一行命令安装**：`scripts/get.sh`（放在仓库中，README 引用 raw 链接）：
   - `set -euo pipefail`；检查 macOS 版本 ≥ 13
   - 通过 GitHub API 获取最新版本号 → curl 下载 zip、`SHA256SUMS` 和 `.sig`
   - 用 `shasum -a 256 -c` 校验；验签：`openssl dgst -sha256 -verify <(内嵌 PEM 公钥) -signature SHA256SUMS.sig SHA256SUMS`
   - 如果 mdPreview 正在运行，提示用户先退出；`ditto` 解压到 `/Applications`（没有写权限时改装到 `~/Applications`）
   - 运行 `xattr -dr com.apple.quarantine`（保险起见）；调用 `lsregister -f` 注册应用
   - 输出"安装完成，可以用 `open -a mdPreview 文件.md` 打开"
   - README 中的用法：`curl -fsSL https://raw.githubusercontent.com/tahoeliu/mdPreview/main/scripts/get.sh | bash`
4. **Homebrew tap**：新建仓库 `tahoeliu/homebrew-tap`，把 `Casks/mdpreview.rb` 移过去（主仓库中删除，README 说明 `brew install --cask tahoeliu/tap/mdpreview`）。Cask 中加入：
   ```ruby
   postflight do
     system_command "/usr/bin/xattr", args: ["-dr", "com.apple.quarantine", "#{appdir}/mdPreview.app"], sudo: false
   end
   caveats "mdPreview 使用 ad-hoc 签名（开源项目，未购买 Apple 开发者证书）。"
   ```
   `zap` 中的路径与 T25 统一的日志路径保持一致。
5. **DMG**：背景图上画出"拖到 Applications"的箭头，并附上"首次打开指引"——macOS 15 及以上：先双击，出现提示后打开"系统设置 → 隐私与安全性"，点击"仍要打开"；同时在 DMG 中放一个 `如果无法打开.txt`，里面写一行终端命令 `xattr -dr com.apple.quarantine /Applications/mdPreview.app`。README 中配截图说明。
6. **universal2**：`mdPreview.spec` 设置 `target_arch='universal2'`；构建环境改用 python.org 的 universal2 版 Python 3.13（`.venv` 需要重建）；检查所有依赖的二进制扩展是否都包含两种架构：`lipo -archs` 遍历应用包内的所有 `.so` 和 `.dylib`。**【验证门】** 如果某个依赖没有 universal2 wheel，就分别构建 arm64 和 x86_64 两个版本，用 `lipo -create` 合并主程序（或者直接发布两个 DMG）。验证：`arch -x86_64 mdPreview.app/Contents/MacOS/mdPreview --selftest`（沿用现有的 selftest 机制）。
7. 更新器下载 zip 而不是 dmg（不需要挂载，更可靠），沿用现有的事务式安装和回滚逻辑。
**验收**：在一台全新的用户账户上执行一行命令安装，全程没有 Gatekeeper 弹窗；验签测试覆盖"签名正确""签名被篡改""公钥不匹配"三种情况；`lipo -archs` 输出 `x86_64 arm64`。

---

### T28 Quick Look 扩展（可选，有验证门）
**【验证门，先做】**
1. 用 Xcode 命令行新建一个最小的 Quick Look Preview Extension（`QLPreviewingController`，基于视图，内部放一个 `WKWebView`，只显示一段固定的 HTML）。
2. 嵌入一个最小的宿主 App，用 ad-hoc 签名（`codesign -s - --entitlements ...`，appex 需要 `com.apple.security.app-sandbox`）。
3. 安装到 `/Applications`，运行一次宿主 App，再执行 `qlmanage -r` 和 `pluginkit -m -v -p com.apple.quicklook.preview`，检查扩展是否已注册；用 `qlmanage -p test.md` 预览。

验证通过，才做正式实现：
- 新建 `quicklook/` 目录；扩展在 Swift 中读取 `.md` 文件（大于 2MB 的只读取前 2MB），通过 `WKWebView` 加载打包进扩展的 `preview.html` + `content.css` + `marked` + `purify` + `markdown-pipeline.js`（与主应用是同一份文件，构建时复制），以 `postMessage` 把 Markdown 文本传给页面渲染。**不加载 Mermaid 和 KaTeX**（保持轻量，这两类内容显示源码），远程图片一律拦截。
- 构建：`build.sh` 中加一步 `xcodebuild`，把产物 appex 放进 `mdPreview.app/Contents/PlugIns/`，最后对整个 App 重新 ad-hoc 签名（`codesign --deep` 不推荐，改为先签 appex 再签 App）。
- `Info.plist` 中 `QLSupportedContentTypes`：`net.daringfireball.markdown`。

验证失败：在本卡记录失败现象，跳过本卡；README 中推荐用户使用现有的开源 Quick Look 插件作为替代。

---

### T29 命令行工具
1. `cli/mdpreview`（shell 脚本），打包到 `mdPreview.app/Contents/Resources/bin/mdpreview`：
   - `mdpreview [文件...]` → `open -a mdPreview "$@"`
   - `mdpreview export <in.md> --to pdf|html|docx|txt|png [-o out]` → 调用 `"$APP/Contents/MacOS/mdPreview" --headless-export in out format`
2. 无头导出（`main()` 中解析参数）：启动时不显示窗口（创建一个隐藏窗口，参考 `_maybe_run_selftest` 的机制），加载文档 → 渲染 → 走与 GUI 完全相同的导出代码 → 退出。退出码：0 成功，1 参数错误，2 渲染或导出失败；错误信息输出到 stderr。
3. 菜单"mdPreview → 安装命令行工具…"：创建符号链接 `/usr/local/bin/mdpreview`（没有写权限时改为 `~/.local/bin`，并提示用户把该目录加入 PATH）。
**验收**：脚本测试 `mdpreview export fixtures/zh-longform.md --to pdf -o /tmp/x.pdf` 返回 0，产物页数大于 1；导出过程中不显示任何窗口。

---

### T30 依赖治理与许可证合规
1. `scripts/vendor.mjs` 重写：用一份清单（包名、npm 包中的源文件路径、目标路径、许可证文件路径）统一管理**所有**第三方库，包括 marked、marked-footnote、dompurify、mermaid、turndown、katex（含 css 和字体）、docx；对于已经不再需要的 html-docx-js 和 html2canvas，等对应卡完成后从清单中删除。所有第三方库移到 `vendor/`，根目录不再放第三方 js。
2. 把 marked、mermaid、turndown 都改为通过 npm 安装，由脚本复制（目前它们是直接放在根目录的文件，版本来源不明）。marked 升级到最新稳定版：**注意 `cjkEmStrong` 依赖 `marked.Tokenizer.prototype.emStrong` 的内部签名，升级后必须运行全部中文粗体相关测试**；如果不兼容，就先停在当前大版本，并在本卡记录原因。
3. 生成 `THIRD_PARTY_NOTICES.md`：遍历清单，写入每个库的名称、版本、许可证类型和许可证全文。Mermaid 的打包产物中还包含其他依赖，从 `node_modules/mermaid/package.json` 的依赖树中收集各依赖的许可证，或者至少注明"Mermaid 及其打包的依赖，见 mermaid 许可证"。
4. 打包：`THIRD_PARTY_NOTICES.md` 放入 App 的 Resources 目录；设置的"关于 → 致谢"中渲染显示；`Credits.rtf` 由脚本根据该文件生成（标准"关于"面板会显示它）。
5. CI 中加入 `npm audit --audit-level=high` 和 `pip-audit`（检查 requirements-lock）。
**验收**：`vendor/licenses/` 中的许可证文件数等于清单中库的数量；`node scripts/vendor.mjs && git diff --exit-code vendor/` 结果稳定（同样的输入产生同样的输出，可复现）。

---

### T31 开源社区基建与发布自动化
1. **README**：`README.md`（英文）与 `README.zh-CN.md`（中文）互相链接。顶部内容依次为：一句话定位、动图演示（打开 → 阅读 → 导出 PDF → 粘贴到飞书）、三种安装方式（一行命令 / Homebrew / DMG，并说明 ad-hoc 签名的原因和首次打开方法）、功能对比表、隐私声明、FAQ。
2. 新增 `CONTRIBUTING.md`（开发环境搭建：从 WORKFLOW.md 整理；测试命令；任务卡式的提交规范）、`CODE_OF_CONDUCT.md`（Contributor Covenant）、`SECURITY.md`（漏洞报告方式：GitHub 私密安全公告；支持的版本范围）、`CHANGELOG.md`（Keep a Changelog 格式，从 git 历史中补全 1.4.x–1.5.0 的内容）。
3. `.github/ISSUE_TEMPLATE/bug.yml`（必填：版本、系统版本、芯片架构、重现步骤；可选：附上诊断 zip）、`feature.yml`、`config.yml`（把一般讨论引导到 Discussions）；`.github/PULL_REQUEST_TEMPLATE.md`；`.github/FUNDING.yml`（GitHub Sponsors 和其他赞助渠道）。
4. `.github/workflows/release.yml`：推送 `v*` 标签时触发，在 `macos-14` runner 上：安装 universal2 Python 和 Node → `npm ci` → 运行测试 → `./build_dmg.sh` → 打包 zip → 生成 `SHA256SUMS` → 用 secret 中的私钥签名 → 从 CHANGELOG 中提取对应版本的说明 → `gh release create` 上传所有产物 → 用 `HOMEBREW_TAP_TOKEN` 更新 tap 仓库中的 Cask 版本号和 sha256。
5. `docs/index.html`（GitHub Pages）：下载按钮直接指向最新 Release 的 latest 链接；加入 Open Graph 元信息（已有 `social-preview.svg`，需另外导出 png 版本，因为部分平台不支持 svg）；关键词覆盖"mac markdown viewer / 打开 md 文件 / markdown 转 pdf / markdown 转 word"。
6. 推广清单（写进 `RELEASE.md` 作为每次大版本发布的检查项，由人工执行）：GitHub topics、awesome-mac 的 PR、Hacker News 的 Show HN、Reddit r/macapps、V2EX、少数派、即刻、Product Hunt。
**验收**：用测试标签（如 `v2.0.0-rc.1`）完整跑通一次发布流水线，产物齐全；tap 仓库中的 Cask 被自动更新。

---

### T32 模块化收尾
1. `app.js` 中剩余的大块逻辑按 §4.1 的结构迁出（每次只迁移一个职责，迁移后运行全部测试再提交），目标是 `app.js` < 1500 行，作为启动和组装模块的入口。
2. `mdPreview.py` 中的菜单（`setup_all_menus` 及处理类）→ `mdpreview_core/menus.py`；窗口管理（`create_window`、`_focus_*`、`on_window_closing` 等）→ `windows.py`；`MarkdownAPI` → `api.py`；配置相关 → `config.py`。目标是 `mdPreview.py` < 500 行。
3. 加载方式：前端继续使用多个 `<script defer>`（每个模块挂一个 `window.Xxx` 命名空间），**不引入打包工具**，以降低构建复杂度。
**验收**：行数达标；全部测试通过；打包后的应用通过 `scripts/verify-native.py`。

---

### T33 发布门禁与兼容性矩阵
1. `verify-all.sh` 加入：`tests/test_output_quality.py`、perf 测试、许可证校验（T30）、`lipo` 架构检查、验签自测（用测试密钥签一份样本再验证）。
2. 人工兼容性矩阵 `WorkSpace/compat/<版本>/`（每格附截图，结论记录在 `RELEASE.md` 中）：

   | 格式 | 检查对象 |
   |---|---|
   | PDF | 预览.app、Safari、Chrome、Acrobat Reader、iOS 文件 App、微信内置预览、打印到实体 A4 纸 |
   | Word | Word（Mac 和 Windows）、Pages、WPS、Google Docs、LibreOffice、飞书和钉钉的文件预览 |
   | HTML | Safari、Chrome、Edge（Windows）、手机浏览器、暗色模式 |
   | PNG | 通过微信发送（压缩后是否可读）、iPhone 相册 |
   | 富文本 | 微信、飞书、钉钉、Outlook、Gmail、Word、Notion、备忘录 |
   | 安装 | 新用户账户分别用一行命令、Homebrew、DMG 安装；macOS 13、14、15、26；Apple 芯片和 Intel（或 Rosetta） |

3. 发布前对照 §3 的验收标准逐条勾选。

---

## 附录 A：打印实测数据（1.5.0）

测试方法：用真实 WKWebView 加载 `styles.css` 和样例文档，按 pywebview 的打印参数输出 A4 PDF，用 PDFKit 测量大写字母 H 的字形框高度（单位 pt，用于相对比较）。正文的绝对字号根据中文字宽换算。

| 元素 | 现状 | 屏幕放大到 22px 后打印 | 方案 CSS |
|---|---|---|---|
| H1 | 15.0 | 15.0 | 13.8 |
| H2 | 13.0 | **17.8（大于 H1）** | 11.4 |
| H3 | 8.0 | 10.7 | 7.0 |
| 正文 | 9.5（约 12.5pt） | 9.5 | 8.3（约 10.9pt） |
| 代码 | 6.0 | 8.2 | 5.2 |
| 表格 | 8.2 | 11.3 | 7.2 |

其他实测结论：现状打印中代码块和表头的底色丢失；在 CSS 中加入 `@page margin` 会导致表格右侧被裁切；签名为 `Signature=adhoc`，`spctl` 结果为 rejected；主程序只有 arm64 架构；`vendor/licenses` 中只有 dompurify 一个许可证文件。

## 附录 B：打印探针脚本要点（T01 的起点）

完整脚本：`scripts/print_probe.py`（用法：`.venv/bin/python -I scripts/print_probe.py <仓库根目录> <输出.pdf> [额外CSS]`）。T01 在它的基础上扩展为 `scripts/output_probe.py`。关键做法：
- 创建一个屏幕外的 `NSWindow`（位置 x=-3000），内含 `WKWebView`，用 `loadHTMLString_baseURL_` 加载测试页面
- 在 `webView_didFinishNavigation_` 回调中延迟 0.5 秒再打印
- `NSPrintInfo` 字典中设置 `NSPrintJobDisposition = NSPrintSaveJob` 和 `NSPrintJobSavingURL`；关闭打印面板和进度面板
- 用 `runOperationModalForWindow_delegate_didRunSelector_contextInfo_` 运行，回调选择器的签名为 `objc.selector(fn, signature=b'v@:@Z^v')`
- 测量：`Quartz.PDFDocument` → `pageAtIndex_(0).string()` 找到标记文字 → `characterBoundsAtIndex_` 取高度
- 运行方式：`.venv/bin/python -I scripts/output_probe.py ...`（必须使用项目的 .venv，系统自带的 Python 没有 PyObjC）

## 附录 C：关键代码位置索引（1.5.0）

| 功能 | 位置 |
|---|---|
| 字号调整 | `app.js` 中 `applyFontSize` / `zoomIn` / `zoomOut`（约第 1310 行） |
| 宽度调整与持久化 | `app.js` 中 `adjustPageWidth`（约第 1292 行）；`mdPreview.py` 中 `save_page_width`（约第 1106 行） |
| 图片拖入 | `app.js` 中 `handleImageDrop`（约第 1354 行） |
| 远程/相对图片处理 | `app.js` 中 `rewriteRelativeImages`（约第 840 行） |
| Mermaid | `app.js` 中 `initMermaid` / `renderMermaidDiagrams`（约第 200–270 行） |
| Markdown 管线与净化 | `frontend/markdown-pipeline.js` |
| HTML / Word / PNG 导出 | `app.js` 中 `buildHtml`（约第 1885 行）、`buildDocx`、`buildPng` |
| 导出主流程 | `app.js` 中 `exportAsWrite`（约第 2040 行）、`showPreviewForCapture`、`restoreSourceMode`、`printDocument`（约第 2144 行） |
| 链接点击 | `app.js` 中 `document.addEventListener('click', ...)`（约第 3942 行） |
| 全局快捷键 | `app.js` 中 `keydown` 监听（约第 3911 行） |
| PDF 原生实现 | `mdPreview.py` 中 `_pdf_to_a4_longpage`（约第 595 行）、`export_as_write`（约第 1012 行） |
| 导出格式面板 | `mdPreview.py` 中 `_run_format_panel`（约第 395 行）、`export_as_choose`（约第 983 行） |
| 配置 | `mdPreview.py` 中 `load_config` / `update_config`（约第 1540–1570 行） |
| 菜单 | `mdPreview.py` 中 `setup_all_menus`（约第 2196 行）；"打印"菜单项约第 2371 行；菜单处理方法约第 2599–2700 行 |
| 窗口创建与关闭 | `mdPreview.py` 中 `create_window`（约第 1971 行）、`on_window_closing`（约第 1804 行） |
| 更新下载 | `mdPreview.py` 约第 3250–3300 行；`mdpreview_core/release.py`；`scripts/install_update.py` |
| pywebview 打印实现（被替换的对象） | `.venv/lib/python3.13/site-packages/webview/platforms/cocoa.py` 中 `print_webview` |
