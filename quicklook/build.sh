#!/bin/bash
# 编译 Finder 空格预览扩展并嵌入已构建的 mdPreview.app：
#   quicklook/build.sh path/to/mdPreview.app
# 只使用 Command Line Tools 里的 swiftc；扩展与应用同为 ad-hoc 签名，架构跟随应用主程序。
# 预览页的资源直接取自仓库里主应用使用的文件，保证两处渲染一致。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="${1:?usage: quicklook/build.sh path/to/mdPreview.app}"
[[ -x "$APP/Contents/MacOS/mdPreview" ]] || { echo "not an application bundle: $APP" >&2; exit 1; }
ARCH="$(lipo -archs "$APP/Contents/MacOS/mdPreview")"
case "$ARCH" in arm64|x86_64) ;; *) echo "expected a single-architecture app, got: $ARCH" >&2; exit 1 ;; esac
VERSION="$(cat "$ROOT/VERSION")"
APPEX="$APP/Contents/PlugIns/MDPreviewQuickLook.appex"
[[ "$APPEX" == */Contents/PlugIns/MDPreviewQuickLook.appex ]] || exit 1
rm -rf "$APPEX"
mkdir -p "$APPEX/Contents/MacOS" "$APPEX/Contents/Resources/web/fonts"

swiftc -parse-as-library -module-name MDPreviewQuickLook -target "$ARCH-apple-macos13.0" -O \
  -o "$APPEX/Contents/MacOS/MDPreviewQuickLook" "$ROOT/quicklook/PreviewViewController.swift" \
  -framework Cocoa -framework Quartz -framework WebKit -Xlinker -e -Xlinker _NSExtensionMain

sed "s/__VERSION__/$VERSION/g" "$ROOT/quicklook/Info.plist" > "$APPEX/Contents/Info.plist"
WEB="$APPEX/Contents/Resources/web"
while read -r source first second; do
  [[ -z "$source" || "$source" == \#* ]] && continue
  if [[ "$source" == @fonts ]]; then
    # 只带 woff2：WKWebView 优先使用它，其余格式只会增大体积。
    cp "$ROOT/$first/"*.woff2 "$WEB/$second/"
  else
    cp "$ROOT/$source" "$WEB/$first"
  fi
done < "$ROOT/quicklook/resources.txt"

codesign --force --sign - --entitlements "$ROOT/quicklook/quicklook.entitlements" "$APPEX"
codesign --force --sign - "$APP"
codesign --verify --deep --strict "$APP"
echo "Quick Look extension embedded: $APPEX ($ARCH)"
