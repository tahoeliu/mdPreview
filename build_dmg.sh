#!/bin/bash
# build_dmg.sh — Build mdPreview.app, create standard drag-and-drop DMG
set -e

cd "$(dirname "$0")"

VERSION="$(cat VERSION)"
PYTHON="${PYTHON:-python3}"
BUILD_DIR="${MDPREVIEW_BUILD_DIR:-build}"
DIST_DIR="${MDPREVIEW_DIST_DIR:-dist}"

echo "=== Building mdPreview.app ==="
if pgrep -x mdPreview >/dev/null 2>&1; then
  echo "mdPreview is running. Please quit it before building the DMG."
  exit 1
fi
rm -rf "$BUILD_DIR" "$DIST_DIR/mdPreview.app"
mkdir -p "$BUILD_DIR" "$DIST_DIR"
if [ -n "${MDPREVIEW_CODESIGN_IDENTITY:-}" ]; then
  echo "Using codesign identity: ${MDPREVIEW_CODESIGN_IDENTITY}"
else
  echo "No MDPREVIEW_CODESIGN_IDENTITY set; build will use ad-hoc signing."
  echo "macOS Desktop/Documents/Downloads permissions may not persist across rebuilds."
fi
"$PYTHON" -m PyInstaller mdPreview.spec --noconfirm --clean --workpath "$BUILD_DIR" --distpath "$DIST_DIR"

if command -v codesign >/dev/null 2>&1; then
  echo ""
  echo "=== Code signing diagnostics ==="
  /usr/bin/defaults read "$DIST_DIR/mdPreview.app/Contents/Info" CFBundleIdentifier 2>/dev/null || true
  /usr/bin/codesign -dv --verbose=2 "$DIST_DIR/mdPreview.app" 2>&1 | /usr/bin/grep -E "Identifier=|Authority=|TeamIdentifier=|Signature=|flags=" || true
fi

# Stop Spotlight/LaunchServices from registering this build as a duplicate
# "Open With" handler.
touch "$DIST_DIR/.metadata_never_index"

echo ""
echo "=== Creating DMG ==="
rm -f "$DIST_DIR/mdPreview-${VERSION}.dmg"

# NOTE: `hdiutil create -srcfolder` fails with "Resource busy" on the
# PyInstaller bundle layout (mutual symlinks between Contents/Resources
# and Contents/Frameworks). Workaround: build a raw HFS+ image, mount it,
# copy files in, unmount, then convert to compressed UDZO.
RAW="/tmp/mdPreview-${VERSION}-raw.dmg"
MNT="/tmp/mdPreview-${VERSION}-mnt"

rm -f "$RAW"
hdiutil create -size "80m" -fs HFS+ -volname "mdPreview" -ov "$RAW"
mkdir -p "$MNT"
hdiutil attach "$RAW" -mountpoint "$MNT"
# Standard layout: app + Applications shortcut + installation guide
cp -R "$DIST_DIR/mdPreview.app" "$MNT/"
ln -s /Applications "$MNT/Applications"
cp "INSTALL.txt" "$MNT/"
hdiutil detach "$MNT"
hdiutil convert "$RAW" -format UDZO -o "$DIST_DIR/mdPreview-${VERSION}.dmg"
rm -f "$RAW"

echo ""
echo "=== Done ==="
ls -lh "$DIST_DIR/mdPreview-${VERSION}.dmg"
echo ""
echo "To install locally:"
echo "  rm -rf /Applications/mdPreview.app"
echo "  cp -R \"$DIST_DIR/mdPreview.app\" /Applications/"
echo "  xattr -cr /Applications/mdPreview.app"
echo "  open /Applications/mdPreview.app"
