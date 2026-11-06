# mdPreview development workflow

源码、运行资源和开发文档保留在仓库；测试、CI 配置、Credits.rtf 与缓存产物仅放在 WorkSpace/。
WorkSpace/ 与历史 outputs/ 保持 Git 忽略；不得删除用户备份或清理无关历史产物。
同名测试冲突先归档 WorkSpace/backups/，再合并；测试入口为 WorkSpace/tests/。
由于 WorkSpace/ 不提交，干净克隆需另行提供本地测试与 Credits 资源；WorkSpace/.github/ 不会被 GitHub Actions 自动执行。
Use Python 3.13 and Node 22+; install requirements-dev.txt and npm ci.
Run npm test and .venv/bin/python scripts/test-python.py. Tests isolate app data.
Build with ./build.sh or ./build_dmg.sh; outputs default to WorkSpace/build and WorkSpace/dist.
Build roots get Spotlight exclusion markers before producing application bundles.
Do not replace /Applications during development tests.
Ad-hoc signing and GitHub sharing are the chosen distribution policy.
Apple Developer ID/notarization remain optional. Never claim untested architecture/OS support.
Updates require the exact GitHub release asset digest and rollback on failure.
