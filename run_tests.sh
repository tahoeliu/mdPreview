#!/bin/bash
# run_tests.sh — Lightweight regression tests for mdPreview.
set -euo pipefail

cd "$(dirname "$0")"
NODE="${NODE:-node}"
PYTHON="${PYTHON:-python3}"

"$NODE" tests/regression.test.js
"$PYTHON" tests/python_smoke.test.py
