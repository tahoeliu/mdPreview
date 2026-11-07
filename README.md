# mdPreview — A Minimal Markdown Viewer & Editor for macOS

[简体中文](README.zh-CN.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Release gates](RELEASE.md)

> **Development branch status:** signed ZIP updates, CLI export and release gates are under development. No production release public key is configured: signed installation is disabled, not silently downgraded. Native acceptance, browser performance budgets and universal2 compatibility have not been verified. The separate Homebrew tap has not been created. No end-to-end demo GIF is available yet.

### Installation channels

- **DMG:** inspect the existing Releases assets below. Ad-hoc signing is not Apple notarization; follow macOS prompts only after verifying the source.
- **Command-line installer:** `scripts/get.sh` currently fails closed until the publisher trust root is configured. Standalone curl-to-shell installation is not ready; do not advertise it as working.
- **Homebrew:** the local Cask is retained; no uncreated tap or unverified installation command is advertised.

### Privacy and export verification

Automatic update checks are off by default. Remote images require permission. Manual update checks contact GitHub. Diagnostic archives contain allowlisted settings and structured events only, never arbitrary raw log text. Headless export disables remote access and dialogs. Word, rich-text and native output interoperability still require the manual matrix in RELEASE.md.

### CLI (development)

Run `bash scripts/mdpreview export input.md --to pdf -o output.pdf` against an installed app, or set `MDPREVIEW_APP` to an explicitly selected application bundle. Existing output files are refused. Exit codes: 0 success, 1 invalid arguments, 2 rendering/export failure. Native hidden-window acceptance is pending.

### Frequently asked questions

**Why are signed updates disabled?** A maintainer must independently verify and configure the production P-256 public key. Missing trust roots, invalid signatures and digest mismatches are fatal.

**Is universal2 supported?** Not yet verified. Architecture labels require inspection of every bundled Mach-O binary and native compatibility evidence.

**Quick Look?** The optional extension has not passed its installation gate and is not implemented in this branch.

**Where are the tests and CI?** Local test resources and workflow templates live under ignored `WorkSpace/`; GitHub does not automatically run them there. Missing release gates are failures, not green skips.

<div align="center">

**Open, read, edit, and export Markdown files on Mac — with a clean, distraction-free interface.**

[Download mdPreview for macOS](https://github.com/tahoeliu/mdPreview/releases/latest/download/mdPreview.dmg)

</div>

---

## The easiest way to open `.md` files on Mac

Markdown files are everywhere now: AI chat exports, product notes, README files, technical docs, meeting summaries, research notes, and personal knowledge bases.

But for many people, opening a `.md` file still feels unnecessarily technical.

**mdPreview makes Markdown feel simple.**

Double-click a Markdown file and read it in a beautiful native macOS window — no browser, no account, no setup, no heavy editor.

<p align="center">
  <img src="images/screenshot-reading.png" alt="Clean reading view with outline" width="49%">
  &nbsp;
  <img src="images/screenshot-mermaid.png" alt="Mermaid diagrams and math rendering" width="49%">
</p>
<p align="center">
  <em>Left: clean reading view with outline &nbsp;•&nbsp; Right: Mermaid diagrams & math rendering</em>
</p>

---

## Why mdPreview?

### Minimal by design

mdPreview is built around one idea:

> Your document should be the focus, not the app.

The interface stays quiet and clean. No side panels unless you need them. No workspace setup. No project management. No account login. No visual clutter.

Just open a Markdown file and read.

### Made for non-technical users

You do not need to understand Markdown syntax to use mdPreview.

If someone sends you a `.md` file, or if you export a response from ChatGPT, Claude, Gemini, or another AI tool, mdPreview lets you open it like a normal document.

### Useful when you need more

When reading is not enough, mdPreview also lets you edit, search, navigate long documents, and export your file into formats that are easier to share.

---

## What you can do with mdPreview

| Need | What mdPreview does |
|---|---|
| Read AI-generated content | Open ChatGPT / Claude Markdown exports cleanly |
| Read long documents | Use the built-in outline / table of contents |
| Edit content | Switch between preview and source editing |
| Paste formatted content | Paste rich text from web pages, docs, or AI chats and convert it cleanly into Markdown |
| Share with others | Export to PDF, Word, PNG, HTML, plain text, or Markdown |
| Work offline | No internet connection required |
| Keep things private | No login, no tracking, no cloud upload |

---

## Highlights in the latest version

mdPreview has recently become more useful, safer, and more comfortable for everyday writing and reading.

### Cleaner reading experience

- Minimal macOS-style interface
- Better typography for long-form reading
- Dark Mode support
- Adjustable text size with keyboard shortcuts
- A collapsible outline for long documents

### Better editing workflow

- One-click switch between rendered preview and Markdown source
- Unsaved-change indicator in the window title
- Autosaved drafts to help recover work after unexpected quits
- Safer save behavior designed to avoid accidental data loss

### More export options

Export your Markdown document as:

- PDF
- Word document
- PNG image
- Web page
- Plain text
- Markdown

This makes mdPreview useful not only for reading Markdown, but also for sharing documents with people who do not use Markdown.

### Better support for modern Markdown

mdPreview supports common Markdown features including:

- Headings
- Lists
- Tables
- Links and images
- Code blocks
- Blockquotes
- Mermaid diagrams
- Footnotes
- Inline and block-style math text
- Front matter

### Safer rendering

Markdown files can contain HTML and diagrams. mdPreview includes safer rendering behavior for risky content, including additional cleanup around embedded HTML and Mermaid output.

The goal is simple: open Markdown files with less worry.

---

## Download & install

### 1. Download

[Download mdPreview.dmg](https://github.com/tahoeliu/mdPreview/releases/latest/download/mdPreview.dmg)

### 2. Install

Open the `.dmg` file and drag **mdPreview** into your **Applications** folder.

### 3. Open it the first time

Because mdPreview is an open-source app and may not be signed with an Apple Developer certificate, macOS may show a security warning the first time you open it.

First verify the asset source and publisher-provided integrity information. Follow the controls offered by your macOS version; a right-click override is not available in every version. This development branch has not passed fresh-account Gatekeeper acceptance. Do not disable system protections to bypass an unexplained verification failure.

---

## Make mdPreview the default app for Markdown files

If you want every `.md` file to open with mdPreview:

1. Find any `.md` file in Finder
2. Right-click it and choose **Get Info**
3. Find **Open with**
4. Select **mdPreview**
5. Click **Change All...**

Now Markdown files will open in mdPreview by default.

---

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `⌘ N` | New file |
| `⌘ O` | Open file |
| `⌘ W` | Close window |
| `⌘ S` | Save |
| `⌘ ⇧ S` | Save As |
| `⌘ P` | Print |
| `⌘ E` | Switch between preview and source |
| `⌘ ⇧ V` | Paste as Markdown |
| `⌘ F` | Find |
| `⌘ G` | Find next |
| `⌘ ⇧ G` | Find previous |
| `⌘ =` | Increase text size |
| `⌘ -` | Decrease text size |
| `⌘ ⌥ =` | Increase reading width |
| `⌘ ⌥ -` | Decrease reading width |
| `⌘ ,` | Settings |
| `⌘ 0` | Reset reading width |
| `⌘ ⌥ O` | Toggle outline |
| `⌘ ⌥ F` | Enter full screen |
| `⌘ I` | Show file properties |

---

## Who is mdPreview for?

mdPreview is a good fit if you:

- Receive Markdown files but do not want to open a code editor
- Save AI-generated answers as `.md` files
- Want a lightweight Typora or MacDown alternative
- Need a simple Markdown reader for macOS
- Prefer offline tools
- Like clean, minimal interfaces
- Want a free and open-source app

It is intentionally not a full writing studio, project manager, or IDE.

It is a focused Markdown viewer and editor.

---

## Feature scope and verification

| Capability | This development branch | Remaining acceptance |
|---|---|---|
| Local reading and source editing | Implemented | Current packaged-app regression |
| Mermaid and KaTeX | Vendored and integrated | Native fonts and large-document rendering |
| PDF / Word / HTML / TXT / PNG | Shared output pipeline | Third-party viewer matrix |
| Rich-text copying | HTML / RTF / text integration | Native clipboard and target applications |
| CLI export | Hidden-window entry and shared pipeline | Native visibility and zero-network observation |
| Signed updates | Fail closed without publisher key | Production verifier and rollback testing |

No current pricing or feature claims are made about third-party products without a dated comparison.

---

## Privacy

mdPreview runs locally on your Mac.

- No account
- No ads
- No telemetry
- No cloud sync
- No document upload
- No internet required for normal use

Your Markdown files stay on your computer.

---

## FAQ

### What is mdPreview?

mdPreview is a free, open-source Markdown viewer and editor for macOS. It lets you open, read, edit, and export `.md` files in a clean native Mac interface.

### Do I need to know Markdown?

No. You can use mdPreview simply as a reader. If you want to edit the source text, you can switch to edit mode anytime.

### Is mdPreview free?

Yes. mdPreview is free and open source under the MIT License.

### Does it work offline?

Yes. mdPreview works offline and does not require an account.

### Why does macOS say the app cannot be opened?

Ad-hoc signing is not Apple notarization. Verify the download source and follow the controls offered by your macOS version; this branch does not claim that one override works across all supported systems.

### Can I export Markdown to PDF or Word?

Yes. mdPreview supports exporting Markdown documents to PDF, Word, PNG, HTML, plain text, and Markdown.

### Is this a replacement for VS Code?

Not exactly. VS Code is a full development environment. mdPreview is for people who want a simple, focused way to read and edit Markdown files.

---

## For developers

mdPreview is built with:

- Python 3.13
- macOS 13 or later (architecture/OS combinations must be tested before claiming support)
- Node 22+ for development tests; no Node runtime needed in the app
- pywebview
- WKWebView on macOS
- marked.js
- Mermaid
- Native macOS menus and file dialogs

### Build from source

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
npm ci
npm test
.venv/bin/python scripts/test-python.py
./build_dmg.sh
# Build only. Installation and release require separate approval and acceptance.
```

### Project structure

```text
mdPreview/
├── mdPreview.py    # Python app, window, menu, and file APIs
├── index.html            # WebView shell
├── css/                  # Screen, content and print styles
├── app.js                # Application integration
├── frontend/             # Bridge, rendering, output, language and CLI modules
├── mdpreview_core/       # Native output, storage, diagnostics and release logic
├── vendor/               # Locked libraries, fonts, licences and checksums
├── WorkSpace/            # Local tests, evidence and inactive CI templates
├── app_icon.icns         # Application icon
├── Info.plist            # macOS app metadata
├── VERSION               # App version
├── build.sh              # Build script
├── install.sh            # Local install script
└── README.md
```

---

## Contributing

Contributions are welcome.

You can help by:

- Reporting bugs
- Suggesting improvements
- Improving documentation
- Testing new releases
- Opening pull requests

Please use [GitHub Issues](https://github.com/tahoeliu/mdPreview/issues) for bug reports and feature requests.

---

## License

mdPreview is released under the MIT License.

See [LICENSE](LICENSE) for details.

---

<div align="center">

**A minimal Markdown app for people who just want to read the file.**

Made by [Tahoe Liu](https://github.com/tahoeliu)

[Download mdPreview](https://github.com/tahoeliu/mdPreview/releases/latest/download/mdPreview.dmg) · [Back to top](#mdpreview--a-minimal-markdown-viewer--editor-for-macos)

</div>

---

**Keywords:** macOS Markdown viewer, Markdown reader for Mac, free Markdown editor for Mac, minimal Markdown app, open .md files on Mac, AI Markdown viewer, ChatGPT Markdown viewer, Claude Markdown export, Typora alternative, MacDown alternative, open source Markdown viewer, Mermaid Markdown viewer


## Reliability work in 1.5.0

Revision-aware saves preserve edits made while disk writes are pending. Each
untitled document has its own recoverable draft. Markdown math/footnotes and
formatted table cells retain their source when editing the rendered document.
HTML and Word exports render the current document revision; local raster images
inside the document directory are embedded in HTML for portable sharing.
Those historical notes are not the current export contract: this branch adds paged
PDF and KaTeX typesetting, whose latest native acceptance remains pending.

The renderer uses vendored DOMPurify and rejects unsafe URLs and UI-ID shadowing.
Updates verify the exact versioned GitHub asset size/SHA-256, app identity, and
code signature; installation keeps a recoverable previous app until UI readiness.
Distribution intentionally uses ad-hoc signing, without Developer ID notarization.

After an authorized build, run `./verify-all.sh` with the explicit candidate app,
architecture, compatibility matrix and native cold-start evidence described in
RELEASE.md. It checks regressions, WebKit budgets and native/CLI outputs; it does
not build, install or publish automatically.
Builds are generated under WorkSpace/; tests never replace /Applications or use
real application drafts. Successful unit tests alone are not release certification.
