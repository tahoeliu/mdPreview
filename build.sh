#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
VERSION="$(cat VERSION)"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
BUILD_DIR="${MDPREVIEW_BUILD_DIR:-$ROOT/WorkSpace/build/release-$VERSION}"
DIST_DIR="${MDPREVIEW_DIST_DIR:-$ROOT/WorkSpace/dist/release-$VERSION}"
mkdir -p "$BUILD_DIR" "$DIST_DIR"
export PYINSTALLER_CONFIG_DIR="$ROOT/WorkSpace/cache/pyinstaller"
mkdir -p "$PYINSTALLER_CONFIG_DIR"
touch "$BUILD_DIR/.metadata_never_index" "$DIST_DIR/.metadata_never_index"
"$PYTHON" scripts/check_release.py --source
# 构建前设置源码入口权限；不修改已签名或已安装的应用包。
chmod u+x scripts/mdpreview
"$PYTHON" -m PyInstaller mdPreview.spec --noconfirm --clean --workpath "$BUILD_DIR" --distpath "$DIST_DIR"
"$ROOT/quicklook/build.sh" "$DIST_DIR/mdPreview.app"
/usr/bin/codesign --verify --deep --strict "$DIST_DIR/mdPreview.app"
"$PYTHON" scripts/check_release.py --app "$DIST_DIR/mdPreview.app"
echo "Built: $DIST_DIR/mdPreview.app"
