# 离线前端依赖

依赖版本以 `package.json` 和 `package-lock.json` 为准；复制规则在 `scripts/vendor.mjs`。运行 `npm ci --ignore-scripts` 后执行 `npm run vendor`，使用 `npm run vendor:check` 无写入校验。生成过程不访问网络，不写根目录缓存，不覆盖根目录旧库。

- `manifest.json`：库、固定版本、npm 源路径、目标路径、SHA-256、递归依赖及许可证来源。
- `checksums.json`：所有生成资源、许可证、清单及根目录 `THIRD_PARTY_NOTICES.md` 的 SHA-256。
- `licenses/`：按包名和版本归档许可证，覆盖直接依赖和传递依赖；原有 `dompurify.txt` 保留，不作为当前清单条目。
- `bundled-notices/`：浏览器预构建包内嵌版权/许可证声明原文。
- `license-sources/`：npm 包遗漏的许可证，按精确上游提交补齐；来源记录在脚本和清单。
- `WorkSpace/Credits.rtf`：从同一份完整声明自动生成，按工作区约定不提交。

## 集成资源

| 用途 | 路径 |
|---|---|
| marked 12.0.0 | `vendor/marked.min.js` |
| marked-footnote 1.4.0 | `vendor/marked-footnote.umd.js` |
| DOMPurify 3.4.16 | `vendor/purify.min.js` |
| Mermaid 11.16.0 | `vendor/mermaid.min.js` |
| Turndown 7.2.5 | `vendor/turndown.js` |
| KaTeX 0.19.1 | `vendor/katex/katex.min.js`、`vendor/katex/katex.min.css`、`vendor/katex/fonts/*` |
| docx 9.15.2 | `vendor/docx.umd.js`，全局 `docx` |
| legacy html-docx-js 0.3.1 | `vendor/html-docx-js.js` |

保留 marked 12，避免 `cjkEmStrong` 对 `Tokenizer.prototype.emStrong` 内部签名的依赖被升级破坏。Mermaid 私有 marked 是独立依赖，不用于 Markdown 主管线。Mermaid 的安装依赖树与上游预构建包不一定使用完全相同的版本；同时收集源码映射中的组件（额外固定 js-yaml 4.1.1 作为许可证来源）和包内嵌声明，不假称两者等同。

html2canvas 不再列入依赖或生成清单。根目录旧 JS 仍保留，待主代理完成应用接线及打包集成再清理；legacy html-docx-js 按 T10 保留一个版本。`index.html`、`app.js`、`mdPreview.py`、spec/打包与关于面板接入不属于本次依赖准备。

## 获取过程说明

首次 npm 查询及安装有停滞；包下载后使用 npm 离线元数据生成锁文件并补齐安装。npm 清理临时目录遇到沙箱 safe-delete 警告，未绕过清理限制。`lodash._createassigner@3.1.1` 空目录通过 `npm pack` 获取真实包并核对锁文件 SHA-512 后展开。marked-footnote npm 包没有许可证文件；raw.githubusercontent.com TLS 请求失败，随后通过 GitHub API 取得 npm gitHead `faab750f00af4788397948286fb8f7fe0c929a7e` 下小写 `license` 原文。没有替换为猜测版本或手写许可证。

## 本次验证

- `npm test`：通过，包括中文粗体 51 项、T30 重复生成/哈希/许可证/字体引用，以及 docx 浏览器 UMD 实际生成无 altChunk 的 OOXML、KaTeX 渲染冒烟。
- `.venv/bin/python -B scripts/test-python.py`：执行失败。运行环境阻止临时文件删除/重命名及 coverage 文件写入，提权重跑仍受限；首套 bridge 测试中的 PDF success 分支同时失败，不能声明 Python 回归全绿。该部分及应用集成留给主代理复核。
- 测试文件位于 `WorkSpace/tests/test_vendor.js`，按仓库规则留在忽略目录，不强制加入 Git。
- 环境清理阻塞：Python tempfile 探针因清理被拒绝而回退至根目录，遗留 `29uwqfo7`、`d_3isicx`、`lqmpghhu`、`rbqksf59`、`zzl4b68_`（均为 4 字节 `blat`），不属于交付资源；Git 状态刷新同样留下无人占用的空 `.git/index.lock`。经提权申请清理仍被 Security Center 的 safe-delete state lock 拒绝，未绕过限制，独立提交因此阻塞。需先由用户修复清理权限并移除这些残留，再仅暂存本卡文件提交。
