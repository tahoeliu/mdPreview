#!/bin/bash
# Unregister every mdPreview*.app from Launch Services except the installed one,
# so "Open With" only lists /Applications/mdPreview.app.
set -uo pipefail
KEEP="${MDPREVIEW_INSTALL_PATH:-/Applications/mdPreview.app}"
LSR=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
"$LSR" -dump 2>/dev/null \
  | sed -n 's/^path:[[:space:]]*\(.*\.app\) (0x[0-9a-f]*)$/\1/p' \
  | grep -E '/mdPreview[^/]*\.app$' | sort -u \
  | while IFS= read -r p; do
      [ "$p" = "$KEEP" ] && continue
      "$LSR" -u "$p" >/dev/null 2>&1 && echo "unregistered: $p"
    done
