# Finder spacebar preview

A Quick Look *preview extension* that renders `.md` files with the same pipeline as the app (marked + DOMPurify + KaTeX), offline and sandboxed.

## Status

| Part | State |
|---|---|
| Preview page (`web/`) | **Tested** in Chromium and WebKit: rendering, math, front matter, 2 MB files, dark mode, remote images blocked, script/iframe/`javascript:` injection ignored, CSP blocks network (`tests/e2e/quicklook.spec.js`, runs in CI) |
| Extension compiles, signs (ad-hoc, sandboxed, no network entitlement), embeds, registers with `pluginkit` | **Verified** on macOS 26.5 / arm64 |
| macOS launching it from Finder | **Verified** on macOS 26.5: with the app in /Applications, `pluginkit -a` + `pluginkit -e use`, Finder's preview pane rendered a `.md` file through the extension and the extension recorded `ok` in its container. A sandboxed WKWebView needs the `network.client` entitlement to start its web process (the page itself has a CSP that forbids all network). Other macOS versions are not verified |

The extension is now built into every release (`scripts/build.sh` calls `quicklook/build.sh`) and the app registers and enables it with `pluginkit` on first launch (`scripts/get.sh` does the same). Whether macOS then shows it in Finder depends on the system's extension switch; see the verification notes in the changelog and RELEASE.md.

## Try it yourself

```bash
scripts/build.sh                                 # normal app build
quicklook/build.sh WorkSpace/dist/release-$(cat VERSION)/mdPreview.app
```

Install that app, open System Settings > General > Login Items & Extensions > Quick Look and enable **mdPreview Quick Look**, then select a `.md` file in Finder and press Space.

To check it programmatically after enabling it:

```bash
.venv/bin/python scripts/verify-quicklook.py --app path/to/mdPreview.app
```

It registers the extension, previews a sample file through `QLPreviewView` (the same system path Finder uses), and reads back a content-free diagnostic (`ok`, element counts, duration) the extension writes inside its own sandbox container.

If it works for you, wiring `quicklook/build.sh` into `scripts/build.sh` and `release.yml` (and `pluginkit -a` into `scripts/get.sh`) is all that remains.

## Files

- `PreviewViewController.swift` — view-based `QLPreviewingController` hosting a `WKWebView`
- `web/` — the preview page; `resources.txt` lists the app files it reuses (shared by `scripts/build.sh` and the browser tests)
- `build.sh` (this folder) — compiles with `swiftc` (Command Line Tools are enough), embeds, signs, re-seals the app
- `tools/preview-host.swift` — minimal `QLPreviewView` host used by the verification script
