#!/bin/bash
# 发布前的完整本地验收（不会安装、不会发布）：
#   MDPREVIEW_VERIFY_APP=path/to/mdPreview.app MDPREVIEW_VERIFY_ARCH=arm64 ./verify-all.sh
# 可选：MDPREVIEW_COMPAT_MATRIX=path/to/matrix.json —— 在 Word/WPS/微信等真实软件里人工验证导出文件的证据。
# 提供了就必须通过校验；没提供则明确提示“跨软件兼容性未独立验证”，README 也不会声称它。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
: "${MDPREVIEW_VERIFY_APP:?必须指定待验收应用，不会自动安装}"
: "${MDPREVIEW_VERIFY_ARCH:?必须明确 arm64 或 x86_64}"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$ROOT/WorkSpace/browsers}"
export MDPREVIEW_DISABLE_UPDATES=1
VERSION="$(<VERSION)"
PY=.venv/bin/python

echo '== 静态与供应链检查'
$PY -m ruff check mdpreview_core scripts mdPreview.py --select F821,E9
node scripts/extract-i18n.mjs --check
node scripts/vendor.mjs --check
npm audit --audit-level=high

echo '== 单元与浏览器测试'
npm test
$PY scripts/test-python.py
node node_modules/@playwright/test/cli.js test --config=playwright.config.js

echo '== 对已构建应用的原生验收'
$PY scripts/check_release.py --app "$MDPREVIEW_VERIFY_APP"
$PY scripts/verify-native.py --app "$MDPREVIEW_VERIFY_APP"
$PY scripts/verify-headless.py --app "$MDPREVIEW_VERIFY_APP"
$PY scripts/verify-update-e2e.py --app "$MDPREVIEW_VERIFY_APP"
node scripts/verify-architecture.mjs "$MDPREVIEW_VERIFY_APP" "$MDPREVIEW_VERIFY_ARCH"

echo '== 冷启动实测与性能/无障碍预算'
COLD="$(mktemp -u "$ROOT/WorkSpace/cold-start.XXXXXX.json")"
$PY scripts/measure-cold-start.py --app "$MDPREVIEW_VERIFY_APP" --out "$COLD"
MDPREVIEW_COLD_START_RESULT="$COLD" MDPREVIEW_VERIFY_APP="$MDPREVIEW_VERIFY_APP" \
  node node_modules/@playwright/test/cli.js test --config=tests/release-playwright.config.js --project=webkit

echo '== 发布公钥与（可选）人工兼容性矩阵'
if [[ -n "${MDPREVIEW_COMPAT_MATRIX:-}" ]]; then
  node scripts/verify-matrix.mjs "$MDPREVIEW_COMPAT_MATRIX" "$MDPREVIEW_VERIFY_APP" "$VERSION"
else
  echo '提示：未提供 MDPREVIEW_COMPAT_MATRIX，跨软件（Word/WPS/微信等）与跨系统兼容性未经独立验证。'
fi
$PY -c 'from mdpreview_core.release_sig import configured; assert configured(), "生产发布公钥未配置"'

printf '%s\n' '所有门禁通过；未执行安装或发布。'
