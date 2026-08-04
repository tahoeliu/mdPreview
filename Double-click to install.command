#!/bin/bash
# mdPreview installer — copies app to /Applications and clears quarantine
# Double-click this file to install.

set -e

echo "========================================="
echo "  mdPreview Installer"
echo "========================================="
echo ""

# Find the app (hidden inside .app/ directory in the DMG)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$SCRIPT_DIR/.app/mdPreview.app"

if [ ! -d "$APP_PATH" ]; then
    APP_PATH="$SCRIPT_DIR/mdPreview.app"
fi

if [ ! -d "$APP_PATH" ]; then
    echo "ERROR: mdPreview.app not found."
    echo "Please make sure this file is in the same folder as the mdPreview app"
    exit 1
fi

# Remove old version if exists
if [ -d "/Applications/mdPreview.app" ]; then
    echo "Removing old version..."
    rm -rf "/Applications/mdPreview.app"
fi

# Copy to Applications
echo "Copying mdPreview to /Applications..."
cp -R "$APP_PATH" "/Applications/"

# Clear quarantine attribute (the key step!)
echo "Clearing security quarantine..."
xattr -cr "/Applications/mdPreview.app"

# Launch
echo "Launching mdPreview..."
open "/Applications/mdPreview.app"

echo ""
echo "Done! mdPreview is now installed and ready to use."
echo "You can close this window."
