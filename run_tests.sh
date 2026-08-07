#!/bin/bash
# run_tests.sh — Lightweight regression tests for mdPreview.
set -euo pipefail

cd "$(dirname "$0")"
NODE="/Users/liutianhao.29/.workbuddy/binaries/node/versions/22.22.2/bin/node"

"$NODE" tests/regression.test.js
