#!/bin/bash
# build.sh — Build mdPreview.app with the canonical PyInstaller pipeline.
set -euo pipefail

cd "$(dirname "$0")"

VERSION="$(cat VERSION)"
PYTHON="/Users/liutianhao.29/.workbuddy/binaries/python/envs/markdown-viewer/bin/python"

echo "=== Building mdPreview ${VERSION} ==="
"$PYTHON" -m PyInstaller mdPreview.spec --noconfirm --clean

echo ""
echo "Build complete: dist/mdPreview.app"
