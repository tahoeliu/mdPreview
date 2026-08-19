#!/bin/bash
# build.sh — Build mdPreview.app with the canonical PyInstaller pipeline.
set -euo pipefail

cd "$(dirname "$0")"

VERSION="$(cat VERSION)"
PYTHON="${PYTHON:-python3}"

echo "=== Building mdPreview ${VERSION} ==="
"$PYTHON" -m PyInstaller mdPreview.spec --noconfirm --clean

# Stop Spotlight/LaunchServices from registering this build as a duplicate
# "Open With" handler. Without this, every rebuilt dist/mdPreview.app can
# pollute Finder's right-click menu with another mdPreview entry.
touch dist/.metadata_never_index

echo ""
echo "Build complete: dist/mdPreview.app"
