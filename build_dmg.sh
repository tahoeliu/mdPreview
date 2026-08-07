#!/bin/bash
# build_dmg.sh — Build mdPreview.app, create standard drag-and-drop DMG
set -e

cd "$(dirname "$0")"

VERSION="$(cat VERSION)"
PYTHON="/Users/liutianhao.29/.workbuddy/binaries/python/envs/markdown-viewer/bin/python"

echo "=== Building mdPreview.app ==="
pkill -f mdPreview 2>/dev/null || true
sleep 1
rm -rf build dist/mdPreview.app
$PYTHON -m PyInstaller mdPreview.spec --noconfirm --clean

echo ""
echo "=== Creating DMG ==="
rm -f "dist/mdPreview-${VERSION}.dmg"

STAGE=$(mktemp -d)
# Standard layout: app + Applications shortcut + installation guide
cp -R dist/mdPreview.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp "安装指引.txt" "$STAGE/"

hdiutil create -volname "mdPreview" -srcfolder "$STAGE" -format UDZO -ov "dist/mdPreview-${VERSION}.dmg"
rm -rf "$STAGE"

echo ""
echo "=== Done ==="
ls -lh "dist/mdPreview-${VERSION}.dmg"
echo ""
echo "To install locally:"
echo "  rm -rf /Applications/mdPreview.app"
echo "  cp -R dist/mdPreview.app /Applications/"
echo "  xattr -cr /Applications/mdPreview.app"
echo "  open /Applications/mdPreview.app"
