#!/bin/bash
# build_dmg.sh — Build mdPreview.app, create standard drag-and-drop DMG
set -e

cd "$(dirname "$0")"

VERSION="$(cat VERSION)"
PYTHON="${PYTHON:-python3}"

echo "=== Building mdPreview.app ==="
if pgrep -x mdPreview >/dev/null 2>&1; then
  echo "mdPreview is running. Please quit it before building the DMG."
  exit 1
fi
rm -rf build dist/mdPreview.app
"$PYTHON" -m PyInstaller mdPreview.spec --noconfirm --clean

echo ""
echo "=== Creating DMG ==="
rm -f "dist/mdPreview-${VERSION}.dmg"

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
cp -R dist/mdPreview.app "$MNT/"
ln -s /Applications "$MNT/Applications"
cp "INSTALL.txt" "$MNT/"
hdiutil detach "$MNT"
hdiutil convert "$RAW" -format UDZO -o "dist/mdPreview-${VERSION}.dmg"
rm -f "$RAW"

echo ""
echo "=== Done ==="
ls -lh "dist/mdPreview-${VERSION}.dmg"
echo ""
echo "To install locally:"
echo "  rm -rf /Applications/mdPreview.app"
echo "  cp -R dist/mdPreview.app /Applications/"
echo "  xattr -cr /Applications/mdPreview.app"
echo "  open /Applications/mdPreview.app"
