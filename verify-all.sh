#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/WorkSpace/browsers"
npm test
.venv/bin/python scripts/test-python.py
npm run test:e2e
./build_dmg.sh
.venv/bin/python scripts/verify-native.py
echo 'All enabled local distribution gates passed.'
