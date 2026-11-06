#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
VERSION="$(cat "$ROOT/VERSION")"
APP_PATH="${1:-$ROOT/WorkSpace/dist/release-$VERSION/mdPreview.app}"
DEST_PATH="${MDPREVIEW_INSTALL_PATH:-/Applications/mdPreview.app}"
if pgrep -f "$DEST_PATH/Contents/MacOS/mdPreview" >/dev/null 2>&1; then
  echo 'Quit the installed mdPreview before replacing it.' >&2; exit 1
fi
"${PYTHON:-$ROOT/.venv/bin/python}" "$ROOT/scripts/install_local.py" "$APP_PATH" "$DEST_PATH"
"$ROOT/scripts/prune_launchservices.sh" || true
