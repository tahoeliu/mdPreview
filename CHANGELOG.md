# Changelog

All notable changes to mdPreview. Format based on [Keep a Changelog](https://keepachangelog.com/); versions follow [Semantic Versioning](https://semver.org/).

## [2.0.7] - 2026-11-10

### Fixed
- **Quitting can no longer get stuck.** Before, one window that did not answer the "can I close?" question made the app wait forever, so Quit and the Dock icon did nothing. Now only windows with unsaved changes are asked, the one being asked is brought to the front first, a window that stays silent is skipped (or, if it has unsaved work, shown to you and the quit is cancelled), and you can always try quitting again.
- **Every window is always where you can see it.** A window left off-screen (for example after a display change) is moved back onto the screen when you switch to the app, when displays change, when you click the Dock icon, and before quitting.

## [2.0.6] - 2026-11-10

### Changed
- **A calmer reading style, closer to a chat app:** real bold for headings and key phrases, a steadier line rhythm, tighter paragraph and list spacing, quieter headings (they are only slightly larger than the text, set apart by weight), dark bullets and numbers that match the text, soft grey code chips without red text, and lighter text rendering so body text no longer looks heavy. Light and dark mode both checked. Exports and print are unchanged.
- **Task checkboxes are drawn the same way in both states** (same size, shape and colour), and share their colour with bullets and numbers.
- **Long tables are no longer folded:** every row is always shown and editable. (Very long code blocks still fold.)

### Improved
- **Callouts (NOTE, TIP, WARNING…) and front matter can now be edited right in the rendered page.** The callout label stays fixed. Formulas and diagrams stay read-only.
- **Tables are saved row by row:** changing one cell rewrites only that row. Every other row, the alignment row, escaped pipes, empty cells, Chinese text, bold, links and code keep their exact original text.

### Fixed
- **Editing a document with a folded long table or long code block could write the button label ("Show all 150 rows") into your file.** It no longer can.
- Editing a paragraph no longer adds blank lines between nested list items, and the invisible caret spacers after blocks are compact.

## [2.0.5] - 2026-11-10

### Fixed
- **Find no longer types into your document.** In source view, typing a search made the cursor jump into the text after the first letter, so the rest of the search ended up inside the document. Focus now stays in the Find box.
- **Find now jumps to and highlights matches inside tables, lists and footnotes** (before, only matches in ordinary paragraphs were shown).
- **⌘F again closes the Find box** (as ⎋ does), and the close button now sits at the far right end of the bar, after the Replace controls, instead of in the middle.
- **Clicking the Dock icon always gets you a window:** if every window was minimised or had been left off-screen, the click did nothing. Now the windows are brought back onto your screen (or a blank one is created if none exist).
- **New windows stay on the screen you are using,** also with two displays: they open beside the one you are reading, stepping down and to the right, and never pile on top of each other or drift off-screen. Windows keep their height instead of getting a little shorter each time.
- The outline button no longer overlaps the Find box or the "unsaved changes restored" note.

- **Editing no longer rewrites what you did not touch.** Saving after an edit in the rendered page now changes only the blocks you edited. Everything else keeps its exact original text: HTML comments, `<details>` blocks, reference-style links, footnote and link definitions, image titles, `~~~` fences, `***` rules, setext headings, list indentation and table alignment (before, any edit could rewrite or drop these).
- **Print and PDF:** the table's right and bottom border is always drawn, and the default page margins are wider (22 mm instead of 16–18 mm), which looks calmer and more like a document.
- The broken-image placeholder now has equal space above the icon and below its caption.
- **Chinese bold works next to full-width punctuation:** `**定位：**S1`, `这是**“引用”**文字` and `前**（备注）**后` are now bold, as people expect (before, the stars showed up as text).
- Turning a paragraph into a bulleted, numbered or task list no longer leaves stray trailing spaces in the saved Markdown.
- Nested lists no longer get extra blank lines inside list items, and lists with a blank line between items keep tidy spacing.
- Autolinks (`<https://…>`) and snake_case words are no longer rewritten when you edit the paragraph they are in.

### Changed
- **The scrollbar is hidden at rest.** A thin position marker appears only while you scroll and for about two seconds afterwards, together with the reading-progress note.
- **Top bars look like one family:** the Find bar and the "unsaved changes restored" note now use the same surface, hairline and controls as the format bar, in light and dark, and stack neatly below it instead of hiding behind it. The note is no longer bright yellow.
- **The code-block "Copy" button is now a small icon** that turns into a check mark after copying.

## [2.0.4] - 2026-11-10

### Fixed
- **Opening a second document from Finder now shows it:** new windows open next to the one you are reading, on the same screen. Before, a new window could appear on another display (where the last window had been left) and look as if nothing had opened.
- The outline button no longer overlaps the bar at the top of the source view.

## [2.0.3] - 2026-11-09

### Changed
- The outline is narrower by default (about a fifth of the window, 168–220 px), leaving more room for the page.
- Long outline headings fade out at the right edge instead of ending in an ellipsis; they still show in full on hover.
- In narrow windows the reading column sits centred between the outline and the window edge, instead of leaning to the right.

## [2.0.2] - 2026-11-09

### Improved
- **Long documents open faster:** the first screen is drawn immediately and the rest is filled in below while a small "Loading…" note with a spinner shows progress. The page stays read-only until it is complete, so nothing can be saved half-finished.
- **Finder preview shows more:** smaller body text, calmer headings and tighter margins, with an even more compact layout in a narrow preview pane.

### Fixed
- Quotes, list items and callouts no longer show a stray gap below their last paragraph.
- Images that cannot be loaded now show a clear placeholder (a torn-picture icon and the image description) instead of a thin line of text.
- The "Updated to … · See changes" note now fades away by itself after 10 seconds if you do not click it.

## [2.0.1] - 2026-11-09

A small polish release: calmer note blocks, a better README and steadier automated checks. No change to how files are read, edited or exported.

### Changed
- Notes, tips, important notes, warnings and cautions (`> [!NOTE]` and friends) are now softer on screen: muted colours, a lightly tinted rounded card with a thin accent bar, the title in the type colour, and even spacing above and below. Exports and print are unchanged.
- The README and project website show the whole app window instead of a cropped page, and the README is rewritten in plain language, with `llms.txt` and `sitemap.xml` so the project is easier to find.
- Automated checks are steadier on shared build machines (accessibility scan, speed budgets, retries); the window-based native check stays a local pre-release step.

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

- **A calmer top bar, modelled on a word processor:** a full-width strip with light line icons — Insert (table, divider), undo / redo, clear formatting, text style (body / title / heading / subheading), bold, italic, strikethrough, code, bulleted / numbered / task lists, indent, link, quote. Only what Markdown can express is offered (no fonts, sizes, colours or alignment). Table edits and every other change now undo and redo with ⌘Z / ⇧⌘Z.
- **A quiet end of page:** instead of a read-time line, every document ends with the mdPreview mark and three small actions — copy as rich text, copy as Markdown, Share.
- **Your own Preview / Source shortcut:** the first row of Settings; click it and press the combination you want (⌘E by default).
- Section arrows are smaller, lighter and sit right beside the heading; the divider line the preview used to draw above second-level headings is gone, so the page shows exactly what the Markdown says.

### Changed
- HTML export is a single self-contained file sharing the app's document styles (correct `lang`, cross-platform font stack, dark mode, optional outline). PNG export uses a native snapshot and is always light. "Plain text" export is now real plain text; "Markdown source" is a separate format.
- Remote images are no longer loaded automatically (a bar offers *Load* / *Always load*). A strict Content-Security-Policy is enforced and inline event handlers are gone.
- Full screen is `⌃⌘F`; page width is `⌥⌘=` / `⌥⌘-` / `⌥⌘0`; `⌘,` opens Settings; `⌘0` resets text size.
- The disk image and installers are architecture-labelled; INSTALL.txt documents the macOS 15+ first-launch steps.
- Tests, fixtures and CI now live in the repository (`tests/`, `.github/`).

### Fixed
- Editing a page with task lists no longer drops the `[x]` / `[ ]` markers; strikethrough typed in the preview is saved as `~~text~~`; a space next to bold text no longer turns into a non-breaking space in the Markdown; dividers are saved as `---`.
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
