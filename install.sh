#!/bin/bash
# install.sh — Install the canonical PyInstaller build to /Applications.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$SCRIPT_DIR/dist/mdPreview.app"
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
ditto "$APP_PATH" "$DEST_PATH"
xattr -cr "$DEST_PATH" 2>/dev/null || true

echo "  Done."
echo ""
echo "Installation complete!"
echo ""
echo "Keyboard shortcuts:"
echo "  Cmd+N        - New file"
echo "  Cmd+S        - Save file"
echo "  Cmd+E        - Toggle Rendered/Source view"
echo "  Cmd+F        - Find"
echo "  Cmd+G        - Find next"
echo "  Cmd+Shift+G  - Find previous"
echo "  Cmd+I        - File properties"
