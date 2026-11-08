# Changelog

All notable changes to mdPreview. Format based on [Keep a Changelog](https://keepachangelog.com/); versions follow [Semantic Versioning](https://semver.org/).

## [2.0.0] - 2026-11-07

A rebuild of everything that happens when you *share* a document, plus a more reliable, more private and much faster core.

### Added
- **Made for long AI answers:** a hairline progress bar and a quiet "N min left · 63%" pill appear only in long documents; a closing "End · about N min read" mark; calmer heading rhythm and body contrast. Nothing is injected into the document or its exports.
- **Fold sections:** a small arrow beside each heading collapses its whole section; very long code blocks and tables show only their head with a *Show all* button. Folding never changes the file or any export.
- **Reading font:** sans-serif or serif, in Settings.
- **Share-ready HTML export:** a single self-contained page with a sticky outline on wide screens, reading time, dark mode and print styles.
- **Finder spacebar preview (Quick Look)** is bundled; the app registers and enables it on first launch (if it does not appear, enable *mdPreview Quick Look* in System Settings → General → Login Items & Extensions → Quick Look).
- **Eight interface languages:** English, 简体中文, 繁體中文, 日本語, 한국어, Deutsch, Français and Español — menus, dialogs, the sample document and Settings, chosen automatically from the system or in Settings. (Translations beyond Chinese and English have not had a native-speaker review; corrections are welcome.)
- **More native behaviour:** *File → Share…* (the system share sheet; shares the file, or the current text when it is unsaved), the document icon in the title bar (drag it out, ⌘-click for the path), a one-time offer on first launch to make mdPreview the default for Markdown files (also in the app menu), the system serif font (New York) for the serif reading font, and the system accent colour for the caret and controls.
- Outline width adapts to the longest heading and the window; long headings stay on one line with an ellipsis and show in full on hover.
- Slightly faster start (the update-verification code is loaded only when checking for updates).
- A new project website under `docs/` (English and 中文).
- **Go to Heading** (`⌘J`): type a few letters to jump anywhere in a long document.
- **New from Clipboard** (`⌥⌘N`, also a button on the empty screen): copy an answer from any chat app and read it rendered immediately.
- **Edit like Word:** documents open for reading; click into the text and a slim formatting bar appears at the top (bold, italic, strikethrough, code, link, H1–H3, lists, quote, and *Insert table* with add/remove row and column). `Esc`, *Done* or clicking outside the text returns to reading. *View → Always Show Formatting Bar* (`⌥⌘T`) keeps it visible. No Markdown syntax needed; changes are written back as clean Markdown.
- **Appearance** setting: follow the system, or force light or dark.
- **One native output pipeline** for print and PDF: real pagination on A4 or Letter, configurable margins, a compact 10.5 pt body that no longer follows the on-screen text size, page numbers, bookmarks from headings, document title and creator metadata, link annotations kept. Code and table backgrounds now print; dark mode never leaks into output.
- **Native Word export** (OOXML): real Heading styles, tables with repeating header rows, images, footnotes (one per reference), and formulas/diagrams as images. Replaces the HTML-in-a-container approach that only desktop Word could open.
- **Copy as Rich Text** (`⇧⌘C`) and **Copy as Markdown** (`⌥⌘C`).
- **Math rendering** with KaTeX, including the `\(…\)` and `\[…\]` forms AI tools emit.
- GitHub-style alerts (`> [!NOTE]`), code copy buttons, click-to-tick task lists.
- Relative `.md` links open in mdPreview; dropping a `.md` file onto a window opens it.
- Paste or drop images: saved to `assets/` next to the document and linked with relative paths. Source-mode `⌘B`/`⌘I`/`⌘K`, list continuation and Tab indenting.
- **Settings** (`⌘,`) with persistent export options; reading position, window position and text size are remembered; open documents reload when changed on disk.
- `mdpreview export` command-line tool (headless: pdf, html, docx, txt, png) and an in-app installer for it.
- Help menu: keyboard shortcuts, sample document, *Report an Issue…* (version and OS only) and *Export Diagnostics…*.
- English, Simplified Chinese and Traditional Chinese interface; language-aware Chinese typography.
- **One-line installer** (`scripts/get.sh`), per-architecture ZIP releases (arm64 and x86_64), a Homebrew tap template, and an experimental Quick Look extension (opt-in, see `quicklook/`).
- Release signing: every release carries `SHA256SUMS` signed with a pinned ECDSA key; the updater and installer verify it.

### Changed
- HTML export is a single self-contained file sharing the app's document styles (correct `lang`, cross-platform font stack, dark mode, optional outline). PNG export uses a native snapshot and is always light. "Plain text" export is now real plain text; "Markdown source" is a separate format.
- Remote images are no longer loaded automatically (a bar offers *Load* / *Always load*). A strict Content-Security-Policy is enforced and inline event handlers are gone.
- Full screen is `⌃⌘F`; page width is `⌥⌘=` / `⌥⌘-` / `⌥⌘0`; `⌘,` opens Settings; `⌘0` resets text size.
- The disk image and installers are architecture-labelled; INSTALL.txt documents the macOS 15+ first-launch steps.
- Tests, fixtures and CI now live in the repository (`tests/`, `.github/`).

### Fixed
- A heading titled "Mermaid" no longer stops every diagram from rendering (heading ids could shadow the lazily loaded library).
- Settings no longer clips its title and Save/Close buttons in short windows; option values are localized.
- Menus: duplicate Full Screen and tab items removed, Undo/Redo added; the unsaved-changes prompt says "Don't Save" for existing files; Replace buttons no longer show in preview mode.
- Opening a file from the command line no longer opens two windows; exported files follow your umask instead of being owner-only.
- **Large documents**: an 800 KB document spent ~19 s in parsing (a quadratic routine in the Markdown library); it now takes ~1 s. A realistic 1 MB document renders in under a second.
- **Chinese text in exported PDFs** was stored with look-alike radical characters (`⽂` instead of `文`), breaking search and copy and silently losing bookmarks for headings containing such characters. The text map is now repaired.
- Exporting through a symlinked directory (such as `/tmp`) from the command line failed.
- Contrast failures (links, outline, code comments, strikethrough, dialog buttons) found by automated accessibility checks in light and dark mode; added a document title.
- Saving a file that was deleted on disk no longer silently recreates it.

### Security
- Updated DOMPurify to 3.4.17 (advisories including an SVG/SMIL guard bypass), Mermaid to 11.17.2, js-yaml to 4.3.2 and docx to 9.15.3. Removed the unmaintained `html-docx-js` (and its vulnerable dependencies) and `html2canvas`.
- Added a supply-chain trail: pinned and checksummed vendor files, third-party licenses shipped in the app, and signed updates.

### Removed
- `html2canvas` (PNG export) and `html-docx-js` (legacy Word export).

## [1.5.0] and earlier

See the [GitHub Releases](https://github.com/tahoeliu/mdPreview/releases) page.
