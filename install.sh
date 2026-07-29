#!/bin/bash
#
# mdPreview - Installation Script
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$SCRIPT_DIR/build/mdPreview.app"
DEST_PATH="/Applications/mdPreview.app"

echo "============================================"
echo "  mdPreview - Installation"
echo "============================================"
echo ""

if [ ! -d "$APP_PATH" ]; then
    echo "Error: App not built. Run ./build.sh first."
    exit 1
fi

echo "Copying mdPreview.app to /Applications..."
if [ -d "$DEST_PATH" ]; then
    echo "  Existing app found, replacing..."
    rm -rf "$DEST_PATH"
fi
cp -R "$APP_PATH" "$DEST_PATH"
echo "  Done."
echo ""

xattr -rd com.apple.quarantine "$DEST_PATH" 2>/dev/null || true

echo "Installation complete!"
echo ""
echo "============================================"
echo "  Set as default .md viewer"
echo "============================================"
echo ""
echo "To make mdPreview the default app for .md files:"
echo ""
echo "  1. Find any .md file in Finder"
echo "  2. Right-click → Get Info"
echo "  3. Open With → select mdPreview"
echo "  4. Click 'Change All...'"
echo ""
echo "Keyboard shortcuts:"
echo "  Cmd+S  - Save file"
echo "  Cmd+E  - Toggle Rendered/Source view"
echo ""
