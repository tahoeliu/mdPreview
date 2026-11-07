#!/bin/bash
set -euo pipefail
# 仅调用本地已审计实现；唯一信任根在 release_sig.py，安装器先检查配置再联网。
# 未交付独立 curl 管道安装，不执行远程下载的脚本，也不取消系统隔离保护。
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[[ -f "$ROOT/scripts/install_signed.py" ]] || { printf '%s\n' 'Download and inspect the source checkout first; piping this script alone is unsupported.' >&2; exit 2; }
[[ "$(uname -s)" == Darwin ]] || exit 1
major=$(/usr/bin/sw_vers -productVersion)
[[ "${major%%.*}" -ge 13 ]] || exit 1
exec "${MDPREVIEW_PYTHON:-python3}" "$ROOT/scripts/install_signed.py" "$@"
