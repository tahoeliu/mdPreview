#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
: "${MDPREVIEW_VERIFY_APP:?必须指定待验收应用，不会自动安装}"
: "${MDPREVIEW_VERIFY_ARCH:?必须明确arm64/x86_64/universal}"
: "${MDPREVIEW_COMPAT_MATRIX:?必须提供完整人工兼容性证据JSON}"
: "${MDPREVIEW_COLD_START_RESULT:?必须提供原生冷启动实测JSON}"
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/WorkSpace/browsers"
export MDPREVIEW_VERIFY_APP MDPREVIEW_COLD_START_RESULT
VERSION="$(<VERSION)"
for file in WorkSpace/tests/test_output_quality.py WorkSpace/tests/test_release_signatures.py WorkSpace/tests/test_release_zip.py WorkSpace/tests/test_security_review_native.py WorkSpace/tests/test_security_review.js WorkSpace/tests/test_release_headless.js WorkSpace/tests/perf.spec.js WorkSpace/tests/accessibility.spec.js WorkSpace/tests/release-playwright.config.js; do
  [[ -f "$file" ]] || { printf '缺失必要门禁：%s\n' "$file" >&2; exit 1; }
done
node -e 'require.resolve("@axe-core/playwright")'
node scripts/extract-i18n.mjs --check
node scripts/vendor.mjs --check
node -e 'const fs=require("fs"),cp=require("child_process");for(const name of fs.readdirSync("WorkSpace/tests").filter(x=>/^test_.*\.js$/.test(x)&&x!=="test_vendor.js")){const r=cp.spawnSync(process.execPath,["WorkSpace/tests/"+name],{encoding:"utf8"});process.stdout.write(r.stdout+r.stderr);if(r.status!==0||/Uncaught/.test(r.stderr))process.exit(1);}'
.venv/bin/python scripts/test-python.py
.venv/bin/python WorkSpace/tests/test_output_quality.py
.venv/bin/python WorkSpace/tests/test_release_signatures.py
.venv/bin/python WorkSpace/tests/test_release_zip.py
.venv/bin/python WorkSpace/tests/test_security_review_native.py
node node_modules/@playwright/test/cli.js test --config=playwright.config.js
node node_modules/@playwright/test/cli.js test --config=WorkSpace/tests/release-playwright.config.js --project=webkit
.venv/bin/python scripts/check_release.py --app "$MDPREVIEW_VERIFY_APP"
.venv/bin/python scripts/verify-native.py --app "$MDPREVIEW_VERIFY_APP"
node scripts/verify-architecture.mjs "$MDPREVIEW_VERIFY_APP" "$MDPREVIEW_VERIFY_ARCH"
node scripts/verify-matrix.mjs "$MDPREVIEW_COMPAT_MATRIX" "$MDPREVIEW_VERIFY_APP" "$VERSION"
.venv/bin/python -c 'from mdpreview_core.release_sig import configured; assert configured(), "生产发布公钥未配置"'
printf '%s\n' '所有必要门禁通过；未执行安装或发布。'
