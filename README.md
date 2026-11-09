# mdPreview — a Markdown viewer and editor for Mac

**mdPreview is a free, open-source Markdown viewer and editor for macOS.** Double-click a `.md` file and it opens as a clean, readable page: headings, tables, pictures and maths in place of the messy `#` and `**` signs. You can also edit it, and share it as a PDF, Word file, web page or rich text.

<p align="center">
  <a href="https://tahoeliu.github.io/mdPreview/"><strong>→ Visit the official website: tahoeliu.github.io/mdPreview</strong></a>
  <br>
  <a href="https://tahoeliu.github.io/mdPreview/">Learn more</a> · <a href="https://github.com/tahoeliu/mdPreview/releases/latest">Download for Mac</a> · <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <img src="docs/images/readme/screenshot-reading.png" alt="mdPreview on Mac showing a Markdown document with a section outline on the left" width="49%">
  &nbsp;
  <img src="docs/images/readme/screenshot-mermaid.png" alt="mdPreview on Mac rendering diagrams and maths from Markdown" width="49%">
</p>

---

## At a glance

| | |
|---|---|
| **What it is** | A Markdown viewer and editor for Mac |
| **Price** | Free, MIT open-source licence |
| **Works on** | macOS 13 or later, Apple silicon and Intel |
| **Latest version** | 2.0.0 |
| **Languages** | English, 简体中文, 繁體中文, 日本語, 한국어, Deutsch, Français, Español |
| **Internet** | Works offline. No account, no ads, no tracking |
| **Website** | [tahoeliu.github.io/mdPreview](https://tahoeliu.github.io/mdPreview/) |

## What is a Markdown viewer?

Markdown is a simple way to write documents in plain text. It is used in notes, README files and most answers from AI chat tools such as ChatGPT and Claude. A Markdown viewer turns those plain-text symbols into a properly formatted page.

**mdPreview is that viewer.** It is built for people who read Markdown, not only for programmers.

## How do I open a .md file on Mac?

Double-click it. If Finder opens it in another app, right-click the file, choose **Get Info**, open **Open with**, pick **mdPreview** and click **Change All…**. Every `.md` file will then open in mdPreview.

## How do I read ChatGPT or Claude answers without the messy symbols?

Copy the answer, then in mdPreview choose **File → New from Clipboard** (`⌥⌘N`). It appears rendered straight away, with headings, tables and code blocks in place. Or save the chat as a `.md` file and double-click it.

## How do I convert Markdown to PDF, Word or HTML on Mac?

Use **File → Export As…**:

- **PDF**: real pagination on A4 or Letter, page numbers, bookmarks from headings, and searchable Chinese text.
- **Word (.docx)**: real heading styles, tables with repeating header rows, images and footnotes.
- **HTML**: one self-contained page that opens in any browser, with an outline and dark mode.
- **Plain text** or **Markdown**: the content without the formatting symbols, or the source.

To paste into Mail, Notes, Word or a chat app, use **Copy as Rich Text** (`⇧⌘C`). The headings and tables come with it.

## Features

**Reading**
- A section outline on the side, and `⌘J` to jump to any heading.
- Fold away sections you have finished with.
- Light or dark appearance, adjustable text size and reading width, and a choice of reading font.
- Remembers where you stopped, and refreshes itself when the file changes on disk.
- Renders tables, task lists, footnotes, maths (KaTeX), Mermaid diagrams and GitHub-style alerts.

**Editing, without learning Markdown**
- Click into the page and a simple toolbar appears, like a word processor's: bold, italic, lists, links, quotes and tables.
- Or switch to the plain text view with `⌘E` if you want to see the Markdown itself.
- Paste or drop an image and it is saved next to the document.

**Sharing and privacy**
- Share through the standard macOS share menu (**File → Share…**).
- Your documents stay on your Mac. Pictures from the internet are not loaded until you allow them.

## Install

**Option 1: one line in Terminal (recommended).** Open Terminal, paste this, and press Return:

```bash
curl -fsSL https://raw.githubusercontent.com/tahoeliu/mdPreview/main/scripts/get.sh | bash
```

The script downloads the newest version, checks that it is genuine and installs it into your Applications folder. macOS shows no security warning this way. [Read the script first](scripts/get.sh) if you like.

**Option 2: download the disk image.** From the [Releases page](https://github.com/tahoeliu/mdPreview/releases/latest), get `mdPreview-…-arm64.dmg` (Apple silicon) or `mdPreview-…-x86_64.dmg` (Intel), and drag the app into Applications. The first time, open **System Settings → Privacy & Security** and click **Open Anyway** next to mdPreview. You only need to do this once.

**Option 3: let your AI assistant install it.** Give it [docs/install.md](docs/install.md).

Already have an older version? mdPreview updates itself: it checks for new versions and installs them after verifying the release signature.

## Questions people ask

**Is mdPreview free?** Yes. It is free and open source under the MIT licence.

**Does it work offline?** Yes. The only thing that uses the internet is the optional check for updates, which you can switch off in Settings.

**Do I need to know Markdown?** No. You can use it as a reader. Switch to the plain text view only if you want to.

**Can I preview a file in Finder without opening it?** Yes. Select a `.md` file and press the Space bar. If nothing appears, see the [Quick Look notes](quicklook/README.md).

**Is it a replacement for Typora, MacDown or VS Code?** It is a focused reader with simple editing and easy sharing. It is not a full writing studio or a coding environment.

**Which Macs does it support?** Macs running macOS 13 or later, with Apple silicon or Intel processors.

## Get the full picture

- **Official website:** [tahoeliu.github.io/mdPreview](https://tahoeliu.github.io/mdPreview/) — screenshots, a tour of features, and the install guide.
- **What's new:** [CHANGELOG.md](CHANGELOG.md).
- **Help and feedback:** use **Help → Report an Issue…** in the app, or open an [issue on GitHub](https://github.com/tahoeliu/mdPreview/issues).
- **Contribute:** see [CONTRIBUTING.md](.github/CONTRIBUTING.md). Security reports go through [SECURITY.md](.github/SECURITY.md).

<details>
<summary>For developers: building from source</summary>

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements/lock.txt
npm ci --ignore-scripts && npm run vendor
npm test && .venv/bin/python scripts/test-python.py
scripts/build.sh      # → WorkSpace/dist/release-<version>/mdPreview.app
```

Project layout is in [CONTRIBUTING.md](.github/CONTRIBUTING.md) and the release process is in [RELEASE.md](dev/RELEASE.md). Update verification is described in [SECURITY.md](.github/SECURITY.md) and third-party code is listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

</details>

---

Made by [Tahoe Liu](https://github.com/tahoeliu) · [mdPreview website](https://tahoeliu.github.io/mdPreview/) · Released under the [MIT licence](LICENSE).

**Keywords:** Markdown viewer for Mac, Markdown editor macOS, open .md files on Mac, Markdown reader, read ChatGPT answers Mac, Claude Markdown viewer, Markdown to PDF Mac, Markdown to Word, Markdown to HTML, free Markdown app, open source Markdown viewer, Typora alternative, MacDown alternative, Mermaid viewer, KaTeX Markdown, offline Markdown reader.
