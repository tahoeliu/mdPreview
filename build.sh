#!/bin/bash
# build.sh — Build mdPreview.app with the canonical PyInstaller pipeline.
set -euo pipefail

cd "$(dirname "$0")"

VERSION="$(cat VERSION)"
PYTHON="${PYTHON:-python3}"

echo "=== Building mdPreview ${VERSION} ==="
if [ -n "${MDPREVIEW_CODESIGN_IDENTITY:-}" ]; then
  echo "Using codesign identity: ${MDPREVIEW_CODESIGN_IDENTITY}"
else
  echo "No MDPREVIEW_CODESIGN_IDENTITY set; build will use ad-hoc signing."
  echo "macOS Desktop/Documents/Downloads permissions may not persist across rebuilds."
fi
"$PYTHON" -m PyInstaller mdPreview.spec --noconfirm --clean

if command -v codesign >/dev/null 2>&1; then
  echo ""
  echo "=== Code signing diagnostics ==="
  /usr/bin/defaults read "dist/mdPreview.app/Contents/Info" CFBundleIdentifier 2>/dev/null || true
  /usr/bin/codesign -dv --verbose=2 "dist/mdPreview.app" 2>&1 | /usr/bin/grep -E "Identifier=|Authority=|TeamIdentifier=|Signature=|flags=" || true
fi

# Stop Spotlight/LaunchServices from registering this build as a duplicate
# "Open With" handler. Without this, every rebuilt dist/mdPreview.app can
# pollute Finder's right-click menu with another mdPreview entry.
touch dist/.metadata_never_index

echo ""
echo "Build complete: dist/mdPreview.app"
