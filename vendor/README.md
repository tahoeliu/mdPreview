# 离线前端依赖

依赖版本以 `package.json` 和 `package-lock.json` 为准；复制规则在 `scripts/vendor.mjs`。运行 `npm ci --ignore-scripts` 后执行 `npm run vendor`，使用 `npm run vendor:check` 无写入校验。生成过程不访问网络，不写根目录缓存，不覆盖根目录旧库。

- `manifest.json`：库、固定版本、npm 源路径、目标路径、SHA-256、递归依赖及许可证来源。
- `checksums.json`：所有生成资源、许可证、清单及根目录 `THIRD_PARTY_NOTICES.md` 的 SHA-256。
- `licenses/`：按包名和版本归档许可证，覆盖直接依赖和传递依赖；原有 `dompurify.txt` 保留，不作为当前清单条目。
- `bundled-notices/`：浏览器预构建包内嵌版权/许可证声明原文。
- `license-sources/`：npm 包遗漏的许可证，按精确上游提交补齐；来源记录在脚本和清单。
- `Credits.rtf`：从同一份完整声明自动生成，随应用打包，显示在“关于”面板。

## 集成资源

| 用途 | 路径 |
|---|---|
| marked 12.0.0 | `vendor/marked.min.js` |
| marked-footnote 1.4.0 | `vendor/marked-footnote.umd.js` |
| DOMPurify 3.4.17 | `vendor/purify.min.js` |
| Mermaid 11.17.2 | `vendor/mermaid.min.js` |
| Turndown 7.2.5 | `vendor/turndown.js` |
| KaTeX 0.19.1 | `vendor/katex/katex.min.js`、`vendor/katex/katex.min.css`、`vendor/katex/fonts/*` |
| docx 9.15.3 | `vendor/docx.umd.js`，全局 `docx` |

保留 marked 12，避免 `cjkEmStrong` 对 `Tokenizer.prototype.emStrong` 内部签名的依赖被升级破坏。Mermaid 私有 marked 是独立依赖，不用于 Markdown 主管线。Mermaid 的安装依赖树与上游预构建包不一定使用完全相同的版本；同时收集源码映射中的组件（额外固定 js-yaml 4.3.2 作为许可证来源）和包内嵌声明，不假称两者等同。

