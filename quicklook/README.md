# Finder spacebar preview (experimental, not in official builds)

A Quick Look *preview extension* that renders `.md` files with the same pipeline as the app (marked + DOMPurify + KaTeX), offline and sandboxed.

## Status

| Part | State |
|---|---|
| Preview page (`web/`) | **Tested** in Chromium and WebKit: rendering, math, front matter, 2 MB files, dark mode, remote images blocked, script/iframe/`javascript:` injection ignored, CSP blocks network (`tests/e2e/quicklook.spec.js`, runs in CI) |
| Extension compiles, signs (ad-hoc, sandboxed, no network entitlement), embeds, registers with `pluginkit` | **Verified** on macOS 26.5 / arm64 |
| macOS actually launching it from Finder | **Not verified.** Our automated attempt never saw the system start the extension. New third-party Quick Look extensions generally also have to be enabled by the user (System Settings > General > Login Items & Extensions > Quick Look), which cannot be scripted or observed in CI |

Because of that last row the extension is **not built into official releases** and the README does not advertise it. Nothing here runs unless you build it.

## Try it yourself

```bash
./build.sh                                        # normal app build
quicklook/build.sh WorkSpace/dist/release-$(cat VERSION)/mdPreview.app
```

Install that app, open System Settings > General > Login Items & Extensions > Quick Look and enable **mdPreview Quick Look**, then select a `.md` file in Finder and press Space.

To check it programmatically after enabling it:

```bash
.venv/bin/python scripts/verify-quicklook.py --app path/to/mdPreview.app
```

It registers the extension, previews a sample file through `QLPreviewView` (the same system path Finder uses), and reads back a content-free diagnostic (`ok`, element counts, duration) the extension writes inside its own sandbox container.

If it works for you, wiring `quicklook/build.sh` into `build.sh` and `release.yml` (and `pluginkit -a` into `scripts/get.sh`) is all that remains.

## Files

- `PreviewViewController.swift` — view-based `QLPreviewingController` hosting a `WKWebView`
- `web/` — the preview page; `resources.txt` lists the app files it reuses (shared by `build.sh` and the browser tests)
- `build.sh` — compiles with `swiftc` (Command Line Tools are enough), embeds, signs, re-seals the app
- `tools/preview-host.swift` — minimal `QLPreviewView` host used by the verification script
