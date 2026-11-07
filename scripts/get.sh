#!/bin/bash
# mdPreview installer for macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/tahoeliu/mdPreview/main/scripts/get.sh | bash
#
# What it does (and nothing else):
#   1. Finds the latest GitHub release (or MDPREVIEW_VERSION=x.y.z) for your CPU architecture.
#   2. Downloads SHA256SUMS, SHA256SUMS.sig and the app ZIP over HTTPS.
#   3. Verifies the ECDSA signature of SHA256SUMS against the public key embedded below,
#      then verifies the ZIP's SHA-256 against the signed list. Any mismatch aborts.
#   4. Checks the extracted bundle's identifier and version, then installs it into
#      /Applications (or ~/Applications if /Applications is not writable).
#
# Files downloaded with curl are not quarantined by macOS, so no Gatekeeper prompt appears.
# This script never removes or alters quarantine attributes and never uses sudo.
# Read it before you run it; it is short on purpose.
set -euo pipefail

REPO='tahoeliu/mdPreview'
API_URL="https://api.github.com/repos/${REPO}/releases/latest"
DOWNLOAD_BASE="https://github.com/${REPO}/releases/download"
CURL_PROTO='=https'
EXPECTED_BUNDLE_ID='tahoeliu.mdpreview'

# Release signing key (ECDSA P-256, SPKI). Its SHA-256 fingerprint is published in SECURITY.md.
read -r -d '' PUBLIC_KEY_PEM <<'PEM' || true
-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEDwgWgKGguwYf2m4CYnHLdojtIvVg
34t+pyqdDvDb5Qtj+rBnzQeuexkkaCo0keVNfN/U0zpI8UwpLjBdtz7QrA==
-----END PUBLIC KEY-----
PEM

fail() { printf 'mdPreview installer: %s\n' "$*" >&2; exit 1; }
info() { printf '%s\n' "$*"; }

[[ "$(uname -s)" == Darwin ]] || fail 'macOS is required.'
macos_major="$(/usr/bin/sw_vers -productVersion | cut -d. -f1)"
[[ "$macos_major" =~ ^[0-9]+$ && "$macos_major" -ge 13 ]] || fail 'macOS 13 or newer is required.'
for tool in curl openssl shasum ditto codesign awk; do
  command -v "$tool" >/dev/null 2>&1 || fail "required tool not found: $tool"
done

# Architecture: report the real CPU even when this shell runs under Rosetta.
if [[ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" == 1 ]]; then
  arch=arm64
else
  arch=x86_64
fi

curl_get() { curl --fail --silent --show-error --location --proto "$CURL_PROTO" --tlsv1.2 --max-time 600 "$@"; }

version="${MDPREVIEW_VERSION:-}"
if [[ -z "$version" ]]; then
  version="$(curl_get "$API_URL" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"v\([^"]*\)".*/\1/p' | head -n 1)"
fi
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || fail "could not determine a valid release version (got '${version}')."

name="mdPreview-${version}-${arch}.zip"
work="$(mktemp -d "${TMPDIR:-/tmp}/mdpreview-install.XXXXXX")"
trap 'rm -rf "$work"' EXIT INT TERM

info "Installing mdPreview ${version} (${arch})…"
curl_get --output "$work/SHA256SUMS" "${DOWNLOAD_BASE}/v${version}/SHA256SUMS"
curl_get --output "$work/SHA256SUMS.sig" "${DOWNLOAD_BASE}/v${version}/SHA256SUMS.sig"
curl_get --output "$work/$name" "${DOWNLOAD_BASE}/v${version}/${name}" \
  || fail "no ${arch} build is published for version ${version}."

printf '%s\n' "$PUBLIC_KEY_PEM" > "$work/key.pem"
if ! openssl dgst -sha256 -verify "$work/key.pem" -signature "$work/SHA256SUMS.sig" "$work/SHA256SUMS" >/dev/null 2>&1; then
  fail 'signature check FAILED: the checksum list was not signed by the mdPreview release key. Nothing was installed.'
fi
info "Signature OK (key fingerprint $(openssl pkey -pubin -in "$work/key.pem" -outform DER 2>/dev/null | shasum -a 256 | cut -c1-16)…)"

expected="$(awk -v n="$name" '$2 == n { print $1 }' "$work/SHA256SUMS")"
[[ "$expected" =~ ^[0-9a-f]{64}$ ]] || fail "${name} is not listed in the signed checksum list."
actual="$(shasum -a 256 "$work/$name" | awk '{ print $1 }')"
[[ "$actual" == "$expected" ]] || fail 'checksum mismatch: the download is corrupt or has been tampered with. Nothing was installed.'
info 'Checksum OK'

mkdir "$work/extracted"
ditto -x -k "$work/$name" "$work/extracted"
entries="$(ls -A "$work/extracted")"
[[ "$entries" == 'mdPreview.app' ]] || fail 'unexpected archive layout.'
app="$work/extracted/mdPreview.app"
plist="$app/Contents/Info.plist"
bundle_id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$plist" 2>/dev/null || true)"
bundle_version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$plist" 2>/dev/null || true)"
[[ "$bundle_id" == "$EXPECTED_BUNDLE_ID" ]] || fail "unexpected bundle identifier '${bundle_id}'."
[[ "$bundle_version" == "$version" ]] || fail "bundle version '${bundle_version}' does not match release ${version}."
codesign --verify --deep --strict "$app" 2>/dev/null || fail 'code signature check of the app failed.'

if pgrep -x mdPreview >/dev/null 2>&1; then
  fail 'mdPreview is running. Quit it and run the installer again.'
fi

dest_dir="${MDPREVIEW_INSTALL_DIR:-/Applications}"
if [[ ! -d "$dest_dir" || ! -w "$dest_dir" ]]; then
  [[ -z "${MDPREVIEW_INSTALL_DIR:-}" ]] || fail "cannot write to ${dest_dir}."
  dest_dir="$HOME/Applications"
  mkdir -p "$dest_dir"
fi
dest="$dest_dir/mdPreview.app"

backup=''
if [[ -e "$dest" ]]; then
  backup="$dest_dir/.mdPreview.app.previous.$$"
  mv "$dest" "$backup"
fi
if ditto "$app" "$dest"; then
  [[ -z "$backup" ]] || rm -rf "$backup"
else
  rm -rf "$dest"
  [[ -z "$backup" ]] || mv "$backup" "$dest"
  fail 'installation failed; the previous version was restored.'
fi

/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$dest" >/dev/null 2>&1 || true
info "Installed ${dest}"
info "Open a file with:  open -a mdPreview yourfile.md"
