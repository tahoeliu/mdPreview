#!/bin/bash
# build_dmg.sh — Build mdPreview.app, create DMG with only the installer visible
set -e

cd "$(dirname "$0")"

VERSION="1.2.5"
PYTHON="/Users/liutianhao.29/.workbuddy/binaries/python/envs/markdown-viewer/bin/python"

echo "=== Building mdPreview.app ==="
pkill -f mdPreview 2>/dev/null || true
sleep 1
rm -rf build dist/mdPreview.app
$PYTHON -m PyInstaller mdPreview.spec --noconfirm --clean

echo ""
echo "=== Preparing installer script ==="
# Ensure the script exists and is executable
chmod +x "Double-click to install.command"
# Hide the .command extension in Finder
SetFile -a E "Double-click to install.command"
# Set custom app icon on the installer script
$PYTHON -c "
from AppKit import NSWorkspace, NSImage
icon_src = 'app_icon.icns'
target = 'Double-click to install.command'
img = NSImage.alloc().initWithContentsOfFile_(icon_src)
if img:
    NSWorkspace.sharedWorkspace().setIcon_forFile_options_(img, target, 0)
    print('Icon set on installer script')
else:
    print('WARNING: could not load icon')
"

echo ""
echo "=== Creating DMG ==="
rm -f "dist/mdPreview-${VERSION}.dmg"

STAGE=$(mktemp -d)
# Hide the app inside a dot-directory so Finder won't show it
mkdir "$STAGE/.app"
cp -R dist/mdPreview.app "$STAGE/.app/"
# Copy installer script with resource fork preserved (ditto preserves forks)
ditto "Double-click to install.command" "$STAGE/Double-click to install.command"
chmod +x "$STAGE/Double-click to install.command"

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
