# Install mdPreview on this Mac (instructions for an AI agent)

You are an AI agent that can run commands on the user's Mac. The user asked you to install and open mdPreview, a small free Markdown reader and editor. Follow this page exactly. It is short on purpose.

**Goal:** the latest mdPreview is installed in `/Applications` (or `~/Applications`), opens without any macOS warning, and has shown the user a document. Be calm and efficient; the user is probably not technical, so keep every message to them short and plain.

## 0. Rules you must keep

- Use only the official installer: `https://raw.githubusercontent.com/tahoeliu/mdPreview/main/scripts/get.sh`. It downloads over HTTPS, verifies an ECDSA signature and a SHA-256 checksum against a pinned key, never uses `sudo`, and stops on any mismatch.
- **Do not** use `sudo`, turn off Gatekeeper (`spctl --master-disable`), edit security or privacy settings, remove quarantine attributes, or install from any other source. If something is blocked by the system or by a device-management policy, stop and tell the user (see section 5). Installing this way needs none of those, and doing them would only hide a real problem.
- Do not skip or edit the verification in the script. If verification fails, stop. Nothing is installed in that case.
- Do not send the user's documents anywhere. mdPreview works offline.

## 1. Check the machine

```bash
sw_vers -productVersion        # must be 13.0 or newer
uname -m                       # arm64 or x86_64 (the installer picks the right build)
pgrep -x mdPreview || echo "not running"
```

If macOS is older than 13, stop and tell the user: "mdPreview needs macOS 13 or newer."

If mdPreview is already running, quit it first (the installer refuses to replace a running app):

```bash
osascript -e 'tell application "mdPreview" to quit'
sleep 2
pgrep -x mdPreview && echo "still running"
```

If it is still running, ask the user to quit it, then continue.

## 2. Install

Read the script first if you want (about 120 lines), then run it:

```bash
curl -fsSL https://raw.githubusercontent.com/tahoeliu/mdPreview/main/scripts/get.sh | bash
```

Expected output ends with `Signature OK`, `Checksum OK` and `Installed /Applications/mdPreview.app` (or `~/Applications/mdPreview.app` if `/Applications` is not writable by this user; that is fine).

Files downloaded by `curl` are not quarantined by macOS, which is why no "unidentified developer" prompt appears. That is the reason to use this installer instead of a browser download.

Optional environment variables: `MDPREVIEW_VERSION=x.y.z` installs a specific version (useful if the GitHub API is rate limited and the latest version cannot be looked up); `MDPREVIEW_INSTALL_DIR=/some/folder` chooses the install folder.

## 3. Verify and open

```bash
APP=/Applications/mdPreview.app; [ -d "$APP" ] || APP="$HOME/Applications/mdPreview.app"
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist"
codesign --verify --deep --strict "$APP" && echo "signature ok"
```

Create a small sample document and open it with the app, so the user sees the result immediately:

```bash
SAMPLE="$HOME/Desktop/mdPreview welcome.md"
cat > "$SAMPLE" <<'EOF'
# Welcome to mdPreview

This is a Markdown file. It opens as a clean page, and you can **click anywhere to edit**, like a Word document.

> [!TIP]
> Press Command-E to see the Markdown source, and Command-J to jump to a heading in a long document.

## What you can do

- Read long documents calmly
- Edit with the toolbar at the top
- Export a PDF, Word file or web page from the File menu
EOF
open -a "$APP" "$SAMPLE"
```

Wait a few seconds, then confirm a window appeared:

```bash
sleep 3; pgrep -x mdPreview && echo "running"
```

## 4. Tell the user

Reply in the user's language, in two or three sentences:

- That mdPreview version X is installed and the sample file is open.
- That they can double-click any `.md` file from now on. If they want mdPreview as the default app: Finder, select a `.md` file, press Command-I, "Open with", choose mdPreview, "Change All…". (Offer this; do not change the default yourself without asking.)
- That the app is free, open source, and works offline.

## 5. If something goes wrong

| Symptom | What to do |
|---|---|
| `signature check FAILED` or `checksum mismatch` | Stop. Do not retry with other sources. Tell the user the download could not be verified and nothing was installed. |
| `no arm64 / x86_64 build is published` | The release has no build for this Mac. Stop and tell the user. |
| `curl` cannot reach GitHub (network, proxy, firewall) | Tell the user the connection to github.com failed; ask them to check the network or try again later. |
| GitHub API rate limit (HTTP 403) while finding the version | Look up the latest version at `https://github.com/tahoeliu/mdPreview/releases/latest`, then rerun with `MDPREVIEW_VERSION=<version>`. |
| `mdPreview is running` | Quit it (section 1) and rerun. |
| `cannot write to ...` | Rerun without `MDPREVIEW_INSTALL_DIR`; the installer falls back to `~/Applications`. |
| macOS still shows a warning when opening the app | This should not happen with this installer. Tell the user to open System Settings, Privacy & Security, and choose "Open Anyway" once for mdPreview. Do not change any security setting yourself. |
| A device-management profile (work or school Mac) blocks the app | Stop and tell the user to ask their administrator. Do not try to bypass it. |

When you finish, summarise in one line what happened (installed version, install location, opened or not). If you stopped early, say exactly which step failed.
