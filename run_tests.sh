#!/bin/bash
# run_tests.sh — Regression + security + performance gates for mdPreview.
set -euo pipefail

cd "$(dirname "$0")"
NODE="${NODE:-node}"
PYTHON="${PYTHON:-python3}"

"$NODE" tests/regression.test.js
"$NODE" tests/security.test.js
"$NODE" tests/performance.benchmark.js
"$PYTHON" tests/python_smoke.test.py
