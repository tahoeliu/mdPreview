#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
VERSION="$(cat VERSION)"
BUILD_DIR="${MDPREVIEW_BUILD_DIR:-$ROOT/WorkSpace/build/release-$VERSION}"
DIST_DIR="${MDPREVIEW_DIST_DIR:-$ROOT/WorkSpace/dist/release-$VERSION}"
export MDPREVIEW_BUILD_DIR="$BUILD_DIR" MDPREVIEW_DIST_DIR="$DIST_DIR"
./build.sh
TEMP="$(mktemp -d "$BUILD_DIR/dmg.XXXXXX")"
MOUNT="$TEMP/mount"
cleanup() { hdiutil detach "$MOUNT" >/dev/null 2>&1 || true; rm -rf "$TEMP"; }
trap cleanup EXIT INT TERM
mkdir -p "$MOUNT"
APP_KB="$(du -sk "$DIST_DIR/mdPreview.app" | awk '{print $1}')"
SIZE_MB="$((APP_KB / 1024 + APP_KB / 4096 + 32))"
hdiutil create -size "${SIZE_MB}m" -fs HFS+ -volname mdPreview -ov "$TEMP/raw.dmg"
hdiutil attach "$TEMP/raw.dmg" -nobrowse -mountpoint "$MOUNT"
ditto "$DIST_DIR/mdPreview.app" "$MOUNT/mdPreview.app"
ln -s /Applications "$MOUNT/Applications"
cp INSTALL.txt "$MOUNT/INSTALL.txt"
hdiutil detach "$MOUNT"
hdiutil convert "$TEMP/raw.dmg" -format UDZO -ov -o "$DIST_DIR/mdPreview-$VERSION.dmg"
cp "$DIST_DIR/mdPreview-$VERSION.dmg" "$DIST_DIR/mdPreview.dmg"
shasum -a 256 "$DIST_DIR/mdPreview.dmg" > "$DIST_DIR/mdPreview.dmg.sha256"
echo "Release asset: $DIST_DIR/mdPreview.dmg"
