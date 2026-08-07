# mdPreview 待办事项路线图

> 仅保留尚未完成的待办事项；已完成的 v1.2.6 稳定性修复项已移除。

## P0：安全与发布前必做

- [ ] 撤销/轮换曾经暴露过的 GitHub token
- [ ] 检查 GitHub 仓库近期 commits、releases、actions、webhooks、deploy keys 是否异常
- [ ] 重新确认最新 GitHub Release 中的 DMG 是本人构建上传的产物
- [ ] 给 release asset 增加 SHA256 校验值
- [ ] 发布 v1.2.6 GitHub Release
- [ ] 上传 v1.2.6 DMG
- [ ] 下载线上 DMG 反向验证安装包内容

## v1.2.7：测试与发布流程完善

- [ ] 增加 round-trip 测试 fixture
  - [ ] `frontmatter.md`
  - [ ] `tables.md`
  - [ ] `mermaid.md`
  - [ ] `mixed-skill.md`
  - [ ] `find.md`
  - [ ] `edge-cases.md`
- [ ] 增加 Markdown 渲染 round-trip 测试
  - [ ] Markdown source → renderMarkdown
  - [ ] DOM → turndown
  - [ ] turndown markdown → renderMarkdown
  - [ ] 校验 frontmatter 不丢失
  - [ ] 校验 table 不丢失
  - [ ] 校验 mermaid 不丢失
- [ ] 增加发布前 smoke test 脚本
  - [ ] 检查 `VERSION`
  - [ ] 检查 app bundle 版本号
  - [ ] 检查 DMG 文件名版本号
  - [ ] 检查 DMG 内容包含 `mdPreview.app`
  - [ ] 检查 DMG 内容包含 `Applications` 快捷方式
  - [ ] 检查 DMG 内容包含 `安装指引.txt`
- [ ] 增加本地安装验证脚本
  - [ ] 安装到 `/Applications/mdPreview.app`
  - [ ] 清除 quarantine 属性
  - [ ] 读取安装版 Info.plist 版本号
  - [ ] 启动测试 Markdown 文件
- [ ] 将 `run_tests.sh` 纳入发布前流程
- [ ] 在 README 中补充测试命令
- [ ] 在 README 中补充 v1.2.6/v1.2.7 发布流程

## v1.3.0：前端架构拆分

- [ ] 拆分 `index.html` 中的 CSS 到 `styles.css`
- [ ] 创建 `js/` 目录
- [ ] 拆分应用状态逻辑到 `js/app-state.js`
- [ ] 拆分 pywebview 通信逻辑到 `js/bridge.js`
- [ ] 拆分 Markdown 渲染逻辑到 `js/markdown-renderer.js`
- [ ] 拆分 YAML frontmatter 逻辑到 `js/frontmatter.js`
- [ ] 拆分源码高亮逻辑到 `js/source-highlight.js`
- [ ] 拆分 Cmd+E 视图切换逻辑到 `js/view-toggle.js`
- [ ] 拆分 Find 功能到 `js/find.js`
- [ ] 拆分表格列宽拖拽逻辑到 `js/table-resize.js`
- [ ] 拆分保存与 dirty 状态逻辑到 `js/save.js`
- [ ] 更新 PyInstaller datas，确保新增 CSS/JS 被打包
- [ ] 更新测试脚本，使其能从拆分后的 JS 文件加载函数
- [ ] 验证离线运行不依赖网络资源

## v1.3.1：后端结构整理

- [ ] 将配置读写整理到 `config.py`
- [ ] 将 `MarkdownAPI` 整理到 `api.py`
- [ ] 将窗口注册、active window、opened files 逻辑整理到 `windows.py`
- [ ] 将 AppKit 菜单逻辑整理到 `menus.py`
- [ ] 将更新检查、下载、待安装提示整理到 `updates.py`
- [ ] 将 macOS/Cocoa 辅助函数整理到 `macos.py`
- [ ] 保留 `markdown_viewer.py` 作为主入口
- [ ] 更新 PyInstaller hiddenimports/datas
- [ ] 增加 Python import smoke test
- [ ] 验证打包后所有模块均可正常加载

## v1.3.2：编辑稳定性增强

- [ ] 明确渲染视图编辑能力边界
- [ ] 在 README 中说明推荐使用源码视图编辑
- [ ] 保存前自动清理 Find 高亮 `<mark>`
- [ ] Cmd+E 切换前自动清理 Find 高亮 `<mark>`
- [ ] 关闭前自动清理 Find 高亮 `<mark>`
- [ ] 渲染视图编辑后增加 DOM → Markdown 回归测试
- [ ] 表格编辑后增加 turndown 回归测试
- [ ] Mermaid 渲染后增加 turndown 回归测试
- [ ] frontmatter 渲染后增加 turndown 回归测试
- [ ] 评估是否将渲染视图设为默认只读

## v1.4.0：用户体验增强

- [ ] 实现暗色模式
- [ ] 使用 `prefers-color-scheme` 自动跟随系统外观
- [ ] 增加手动切换 Light/Dark 菜单项
- [ ] 增加最近打开文件列表
- [ ] 增加页面宽度设置面板
- [ ] Find 支持大小写匹配开关
- [ ] Find 支持全词匹配开关
- [ ] Find 支持替换功能
- [ ] Mermaid 语法错误时显示可读错误提示
- [ ] 增加文档统计
  - [ ] 字数
  - [ ] 行数
  - [ ] 字符数
  - [ ] 预计阅读时间
- [ ] 增加图片拖拽插入
- [ ] 增加图片粘贴插入
- [ ] 表格支持双击自动适配列宽
- [ ] 表格列宽拖拽结果可保存/恢复

## v1.4.1：更新体验完善

- [ ] 下载更新时显示“Downloading...”状态
- [ ] 下载完成后显示提示
- [ ] 下载失败后显示错误提示
- [ ] 下载过程中避免重复点击 Download
- [ ] 校验下载 DMG 文件大小
- [ ] 校验下载 DMG SHA256
- [ ] 待安装更新提示中展示 DMG 路径
- [ ] 增加“Reveal in Finder”按钮
- [ ] 增加“Skip this version”选项

## v1.5.0：签名、公证与自动发布

- [ ] 申请/配置 Apple Developer ID
- [ ] 对 app bundle 执行 Developer ID 签名
- [ ] 对 DMG 执行签名
- [ ] 提交 Apple notarization
- [ ] 对 app/DMG 执行 staple
- [ ] 增加签名验证脚本
- [ ] 增加公证验证脚本
- [ ] 配置 GitHub Actions 自动构建
- [ ] 配置 GitHub Actions 自动生成 DMG
- [ ] 配置 GitHub Actions 自动上传 release asset
- [ ] 自动生成 release notes
- [ ] 自动生成 SHA256SUMS

## 文档待办

- [ ] README 增加 `VERSION` 说明
- [ ] README 增加完整快捷键列表
- [ ] README 增加测试命令
- [ ] README 增加发布命令
- [ ] README 增加 DMG 验证方法
- [ ] README 修正 Dark Mode 描述，确保与实际功能一致
- [ ] `安装指引.txt` 增加 v1.2.6+ 安装说明
- [ ] 增加 `CHANGELOG.md`
- [ ] 增加 `SECURITY.md`
- [ ] 增加 token 安全处理说明
- [ ] 增加 release checklist 文档

## 暂不优先

- [ ] 暂不迁移到 Electron
- [ ] 暂不迁移到 Tauri
- [ ] 暂不实现完整 WYSIWYG 编辑器
- [ ] 暂不引入复杂前端构建系统
- [ ] 暂不扩展过多 Markdown 方言
