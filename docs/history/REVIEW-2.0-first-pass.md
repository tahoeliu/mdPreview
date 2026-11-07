# mdPreview 2.0 验收审查

审查日期：2026-11-07 · 分支：`release/2.0`（HEAD `e1be34b`）· 对照文件：`OPTIMIZATION_PLAN.md` §3 发布验收标准 + T00–T33 任务卡

## 结论：**尚未达到对外发布标准**

产品层面的进步是实打实的：输出质量（打印、PDF、样式）已经实测达标，前端模块化、CSP、许可证合规、国际化都已落地。但存在 **7 个阻断项**，其中 2 个涉及代码安全和开源可复现性，必须最先处理。

---

## 一、已验证达标（本次亲自运行）

| 项 | 证据 |
|---|---|
| 打印字号与层级（T03） | 校准页实测字形高度：正文 8.08（目标 8.0–8.8，改动前 9.5）；H1 14.1 > H2 11.3 > H3 9.7 > 正文，层级严格递减 |
| 屏幕缩放与打印解耦 | `--font-size=22px` 下打印，各项数值与默认完全相同（改动前 H2 会大于 H1） |
| 暗色模式打印 | 暗色外观下打印结果与浅色一致；代码块和表头底色已能打印；页边距正常，越界文字 0 |
| 前端单元测试 | `npm test` 全部通过 |
| 浏览器端到端测试 | `playwright test` 32/32 通过（chromium + webkit），样式拆分前后像素差 < 0.5% |
| 文案、依赖校验 | `extract-i18n --check` 通过；`vendor --check`：8 个库、146 份依赖许可证、223 项 SHA-256 |
| 构建 | `build.sh` 构建成功，`check_release` 通过（39MB） |
| 启动性能 | 构建产物打开 4768 字长文：进程启动到首屏 739ms（标准 < 1.5s） |
| CSP 与内联事件（T16） | CSP 已生效；`onclick=` 在 html/js 中的出现次数为 0 |
| Word 导出（T10） | 默认走原生 OOXML（`docx` 库），默认 `legacy_docx: false`，覆盖标题样式、表头、脚注、图片、东亚字体 |
| 隐私默认值（T15） | `remote_images` 默认为 `ask` |
| `app.js` 瘦身 | 4116 → 1460 行（目标 < 1500） |

---

## 二、阻断项（必须修复才能发布）

### B1. 一半的工作没有进入版本控制【最紧急】
- 只有 T00–T09 被提交。**T10–T31 的全部实现都只存在于工作区**：31 个已修改文件，约 250 个未跟踪文件（`frontend/` 下 20 多个新模块、`mdpreview_core/` 下 10 个新模块、KaTeX、docx、许可证等）。一旦误操作，这些工作会全部丢失。
- 原因（见执行记录 `vendor/README.md` 第 38 行）：执行 AI 的沙箱禁止删除文件，留下了一个空的 **`.git/index.lock`**（时间戳 11-07 02:45），导致之后无法提交；同时 Python `tempfile` 的探测文件掉进了仓库根目录。
- 根目录垃圾文件：`29uwqfo7`、`45vhvhys`、`d_3isicx`、`lqmpghhu`、`rbqksf59`、`uy7uwmem`、`zzl4b68_`（每个 4 字节，内容是 `blat`）。
- **修复**：确认没有 git 进程在运行后，删除 `.git/index.lock` 和上述 7 个文件；然后按任务卡分组提交（至少做到每张卡一个提交，方便回溯）。

### B2. 测试和 CI 不在仓库里，干净克隆无法构建
- `WORKFLOW.md` 被改成："测试、CI 配置、Credits.rtf 与缓存产物仅放在 WorkSpace/"，而 `WorkSpace/` 被 Git 忽略。结果是：
  - 仓库里已经**没有 `tests/` 和 `.github/` 目录**；1.5.0 时存在的 `.github/workflows/ci.yml` 已经不在仓库里
  - `mdPreview.spec` 引用了 `WorkSpace/tests/native-check.js` 和 `WorkSpace/Credits.rtf` → **从 GitHub 克隆的人无法构建**
  - 贡献者拿不到任何测试，GitHub Actions 也永远不会运行
- 对开源项目来说这是致命的：CONTRIBUTING 和"可复现构建"都无从谈起。
- **修复**（需要你确认这条规则是否出自你的本意）：
  1. 把 `WorkSpace/tests/` 移回 `tests/`，`WorkSpace/.github/` 移回 `.github/`，并纳入提交
  2. `Credits.rtf` 改为构建时从 `THIRD_PARTY_NOTICES.md` 生成到构建目录，spec 引用生成后的路径
  3. `native-check.js` 放进 `tests/` 或 `scripts/`
  4. 只有运行产物（日志、报告、构建结果、缓存）留在 WorkSpace
  5. 用一个干净目录验证：`git clone` → `npm ci` → 建好 `.venv` → `npm test` → 运行 Python 测试 → `./build.sh`，全部能跑通

### B3. 命令行无头导出完全不可用（T29）
- 复现（用本次的构建产物）：
  ```bash
  WorkSpace/review-build/dist/mdPreview.app/Contents/MacOS/mdPreview --headless-export /tmp/a.md /tmp/a.txt txt
  ```
  结果：180 秒后输出 `headless: timeout`，退出码 2。**连 txt 都失败**；pdf、docx 也是同样结果。
- 现有测试没有发现，是因为 README 自己写明了"Native hidden-window acceptance is pending"——也就是说这部分从未真正跑通过。
- 可疑点（未验证）：隐藏窗口中 WKWebView 不触发 `requestAnimationFrame`（`frontend/output/prepare.js:62` 会等待两帧），或者隐藏窗口里 `get_initial_content` 根本没有被调用。建议在 `headless.js` 各个阶段把进度写到 stderr 来定位。
- **修复后的验收**：对 `zh-longform.md` 分别导出 5 种格式，每种 30 秒内完成、退出码 0；把这条命令加进 CI。

### B4. Python 测试未通过
运行 `scripts/test-python.py` 的结果：
- `test_print_engine.PrintTests.test_integration` 失败：它断言 `app.js` 里有 `Bridge.call('print_document'`，但代码已经迁到 `frontend/output.js`。属于测试过时，应改为检查实际所在的文件，或者改成行为测试。
- `test_integrity...test_update_lock_content_length_and_digest_failure` 失败：期望 `incomplete`，实际得到 `verify`。原因是没有配置公钥时，验签这一步先失败了。测试需要注入一个测试用公钥，才能覆盖后面的分支。
- **覆盖率 74%，低于门槛 90%**：`update_download.py` 18%、`csp_bridge.py` 42%、`release_sig.py` 56%、`watcher.py` 66%、`release_zip.py` 74%。偏偏这些都是安全和更新相关的模块，最需要测试。

### B5. 性能和无障碍门禁失败（T22、T24）
- `perf.spec.js` 中"WebKit 大文档性能预算"在 180 秒时超时：100KB / 1MB / 5MB 三档里至少有一档远远超出预算。这是真实的性能问题，大文件用户会觉得卡死。修复时要先找出是哪一档、卡在哪一步（渲染、切换模式、TOC），再修。
- `accessibility.spec.js` 无法运行：`@axe-core/playwright` 没有写进 `package.json` 的 devDependencies。

### B6. 分发方案没有实现（§3 第 1 条，T27）
这是对"受欢迎"影响最大的一条，目前离标准最远：
- **`scripts/get.sh` 并不是一行命令安装**：第 4 行明确写着"未交付独立 curl 管道安装……也不取消系统隔离保护"；它要求先下载完整源码，并依赖系统的 `python3` 里装有 PyObjC——**普通用户的 Mac 上没有，所以这个安装器在用户机器上根本跑不起来**。
- 执行 AI 出于它自身的安全策略，拒绝了"清除隔离属性"这一步。你已经明确选择了 ad-hoc 分发，**这件事需要你拍板**：
  - 方案 A（推荐）：按 T27 实现 curl 安装（下载 zip → 校验 SHA256 和签名 → 安装）。用 curl 下载本身就不会带隔离属性，所以不需要主动"绕过"任何东西；README 公开脚本内容，说明这样做的原因
  - 方案 B：只提供 DMG + 图文指引，接受首次打开时的拦截
- **发布公钥未配置**（`RELEASE_PUBKEY_B64 = ''`）：签名安装和**应用内更新都处于关闭状态**。需要你生成密钥对（私钥由你保管），公钥写进代码。
- `build_dmg.sh` 只生成 `mdPreview.dmg`，不生成新更新器需要的 zip、`SHA256SUMS`、`.sig`；也没有 `release.yml` 自动发布流程。
- 只有 arm64（构建产物用 `file` 检查确认）；spec 里没有设置 `target_arch`。
- Homebrew：Cask 还留在主仓库，版本仍是 1.4.9，没有 postflight，也没有建 tap 仓库。
- 兼容性注意：老版本（1.4.x、1.5.0）的更新器查找的是名为 `mdPreview.dmg` 的资产，并比对 GitHub 提供的摘要。**2.0 的 Release 必须继续附带同名的 `mdPreview.dmg`**，否则老用户永远收不到更新。目前 `build_dmg.sh` 还保留着这个文件名，要确保发布流程不要把它删掉。

### B7. 对外文档和版本号仍处于开发状态
- README 第 5–27 行是一大段"Development branch status……not ready……not verified"，不能作为对外首页。
- `VERSION` 仍是 1.5.0；`CHANGELOG.md` 只有 `## Unreleased`。
- `vendor/README.md` 第 30–40 行写的是执行 AI 的过程日志（沙箱拒绝、提权失败等），不属于产品文档，应该移到 WorkSpace 的执行记录里。

---

## 三、未达标但不阻断发布（建议在 2.0 内完成）

| # | 问题 | 证据 | 建议 |
|---|---|---|---|
| N1 | `mdPreview.py` 不减反增 | 3655 → **4446** 行（T32 目标 < 500） | 按 T32 把菜单、窗口、API、配置迁出到 `mdpreview_core/` |
| N2 | 旧版第三方文件仍在根目录，并被重复打包 | 根目录 7 个旧 js 仍在 git 中；构建产物里 `mermaid.min.js`（3.4MB）、`html-docx-js.js` 各有两份；`bridge.js:5` 的白名单仍包含 `html2canvas.min.js` 和根目录文件名 | 删除根目录旧文件，以及 spec 中的对应条目和白名单项；预计可减小约 4.5MB |
| N3 | KaTeX 字体冗余 | ttf、woff、woff2 各 20 个；WKWebView 只需要 woff2 | 只打包 woff2，约省 0.9MB |
| N4 | 兼容性矩阵（T33）没有证据 | `WorkSpace/compat/` 不存在；两份"AI 导出"样本是合成的（T01 记录中自己注明了） | 用真实 ChatGPT、Claude 导出替换；按矩阵完成人工检查 |
| N5 | Quick Look（T28） | 验证门没有执行 | 可以留到 2.1，但要在 README 中如实说明 |
| N6 | 自动更新默认关闭 | `settings.py` 中 `auto_update: False` | 公钥配置好后改为默认开启，并在隐私说明中写清楚 |
| N7 | 全屏快捷键不符合惯例 | `shortcuts.json` 中全屏是 ⌥⌘F | macOS 标准是 ⌃⌘F |

---

## 四、建议的修复顺序

1. **B1**：解锁，清理，提交（防止丢失工作，几分钟就能完成）
2. **B2**：测试和 CI 回到仓库，验证干净克隆能构建（这是开源项目的底线）
3. **B4、B5**：测试全绿，补齐覆盖率，找到大文档的性能瓶颈并修复，补上 axe 依赖
4. **B3**：修好无头导出
5. **B6**：你先就 curl 安装和发布密钥做决定，然后实现 zip、签名、release workflow、universal2 和 tap
6. **N1–N7**
7. **B7**：最后更新 README、CHANGELOG 和版本号，按 §3 逐条勾选后发布

## 附：本次审查产生的文件
- 构建产物：`WorkSpace/review-build/dist/mdPreview.app`（没有安装，没有覆盖 `/Applications`）
- 打印校准结果：`WorkSpace/outputs/review-174031/`
- 本次没有修改任何源代码，也没有删除任何文件
