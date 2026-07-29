#!/bin/bash
#
# Build script - assembles the mdPreview.app bundle
#

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$PROJECT_DIR/build"
APP_NAME="mdPreview.app"
APP_PATH="$BUILD_DIR/$APP_NAME"

echo "Building $APP_NAME..."

# Clean previous build
rm -rf "$APP_PATH"

# Create directory structure
mkdir -p "$APP_PATH/Contents/MacOS"
mkdir -p "$APP_PATH/Contents/Resources"

# Copy Info.plist
cp "$PROJECT_DIR/Info.plist" "$APP_PATH/Contents/Info.plist"

# Copy launcher script as the executable
cp "$PROJECT_DIR/markdown_viewer_launcher.sh" "$APP_PATH/Contents/MacOS/markdown_viewer"
chmod +x "$APP_PATH/Contents/MacOS/markdown_viewer"

# Copy Python script
cp "$PROJECT_DIR/markdown_viewer.py" "$APP_PATH/Contents/Resources/markdown_viewer.py"

# Copy HTML and JS resources
cp "$PROJECT_DIR/index.html" "$APP_PATH/Contents/Resources/index.html"
cp "$PROJECT_DIR/marked.min.js" "$APP_PATH/Contents/Resources/marked.min.js"
cp "$PROJECT_DIR/turndown.js" "$APP_PATH/Contents/Resources/turndown.js"

# Copy app icon
cp "$PROJECT_DIR/app_icon.icns" "$APP_PATH/Contents/Resources/app_icon.icns"

# Set permissions
chmod 755 "$APP_PATH/Contents/MacOS/markdown_viewer"
chmod 644 "$APP_PATH/Contents/Resources/"*

echo ""
echo "Build complete!"
echo "App location: $APP_PATH"
echo ""
echo "Or run directly:"
echo "  open \"$APP_PATH\" path/to/file.md"
