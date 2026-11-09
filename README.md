# mdPreview

A calm, simple app for reading and editing Markdown files on your Mac.

[简体中文](README.zh-CN.md) · [What's new](CHANGELOG.md) · [Website](https://tahoeliu.github.io/mdPreview/) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

<p align="center">
  <img src="images/screenshot-reading.png" alt="A Markdown document open in mdPreview, with its outline on the left" width="49%">
  &nbsp;
  <img src="images/screenshot-mermaid.png" alt="Diagrams and maths drawn neatly in mdPreview" width="49%">
</p>

---

## What is Markdown?

Markdown is a simple way to write documents using plain text. You will see it in notes, README files, and most answers from AI chat tools like ChatGPT or Claude. Often it shows up as a messy wall of `#` and `**` signs.

**mdPreview turns that mess into a clean page.** Double-click a `.md` file and it opens like any other document: headings, tables, pictures and maths, all neatly laid out. No account, no sign-up, and it works without the internet.

## Who it's for

- **Anyone who receives AI answers** and wants to read them comfortably.
- **Anyone who writes notes** and wants to tidy them up without learning anything new.
- **Anyone who needs to share a document** with someone who has never seen Markdown.

## What you can do

**Read**
- Open any `.md` file with a double-click, or drag it onto the window.
- See a list of section titles on the side, and jump to any part of a long document.
- Fold away sections you have finished with.
- Pick a reading font, a text size and a light or dark look.
- It notices when the file changes and refreshes itself.

**Edit, without the code**
- Click into the page and a simple toolbar appears at the top, like the one in a word processor. Make text bold, add a list, insert a table, and more.
- Press `Esc` (or click outside the text) to go back to reading.
- If you prefer, switch to the plain text view with `⌘E` to see the Markdown itself.

**Share**
- **Save as PDF** for a tidy document that prints well.
- **Save as Word (.docx)** for someone who uses Microsoft Word or Pages.
- **Save as a web page (HTML)** that opens in any browser.
- **Copy as Rich Text** and paste straight into an email, a note or a chat. The headings and tables come with it.
- **Share…** sends the document through the standard macOS sharing menu.

## Install it

**The easiest way:** open the **Terminal** app (press `⌘ Space`, type *Terminal*, press Return), paste the line below, and press Return.

```bash
curl -fsSL https://raw.githubusercontent.com/tahoeliu/mdPreview/main/scripts/get.sh | bash
```

The script downloads the newest version, checks that it is genuine, and puts it in your Applications folder. Because it arrives this way, macOS doesn't show any security warnings. It is a short script, and you are welcome to read it first.

**Prefer clicking?** Download the file for your Mac from the [Releases page](https://github.com/tahoeliu/mdPreview/releases/latest):
- Apple chip Macs (most Macs from 2020 on): `mdPreview-…-arm64.dmg`
- Intel Macs: `mdPreview-…-x86_64.dmg`

Open the file and drag mdPreview into **Applications**. The first time you open it, macOS may say it can't verify the app. This is normal for free, open-source software. Go to **System Settings → Privacy & Security**, scroll down, and click **Open Anyway** next to mdPreview. You only need to do this once.

**Let your AI do it:** you can also ask an AI assistant to install mdPreview for you. Give it this page: [docs/install.md](docs/install.md).

mdPreview needs macOS 13 or later and is available in English, 简体中文, 繁體中文, 日本語, 한국어, Deutsch, Français and Español.

**Make it your default:** right-click any `.md` file in Finder, choose **Get Info**, open **Open with**, pick **mdPreview**, and click **Change All…**.

## A few handy shortcuts

| Keys | What it does |
|---|---|
| `⌘O` | Open a file |
| `⌘F` | Find text |
| `⌘E` | Switch between reading and plain text view |
| `⌘J` | Jump to a heading |
| `⌘=` / `⌘-` | Make text bigger or smaller |
| `⇧⌘C` | Copy as rich text (for email and notes) |
| `⌘P` | Print |
| `⌘,` | Settings |

The **Help** menu has the full list, along with a sample document to try.

## Your privacy

- No account, no ads, no tracking, no cloud storage.
- Your documents never leave your Mac.
- The app does check once in a while whether a newer version exists. You can turn this off in Settings.
- Pictures from the internet are not loaded automatically. A bar asks whether you want them, because loading a picture tells its website that you opened the document.

## Questions people often ask

**Do I need to know Markdown?** No. Just read. Switch to the plain text view only if you want to.

**Is it really free?** Yes. It is free and open source under the MIT licence. If it helps you, a star on GitHub helps others find it.

**Does it work offline?** Yes. The only thing that needs the internet is the optional check for updates.

**Can I see it in Finder without opening it?** Yes. Select a `.md` file in Finder and press the Space bar to preview it. If it doesn't show up, see the [Quick Look notes](quicklook/README.md).

**Is it a replacement for Word or VS Code?** No. It is a focused reader with simple editing and easy sharing. It is not a full writing studio or a coding tool.

## Found a problem, or want to help?

- Use **Help → Report an Issue…** in the app, or open an issue on [GitHub](https://github.com/tahoeliu/mdPreview/issues).
- Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

<details>
<summary>For developers: building from source</summary>

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
npm ci --ignore-scripts && npm run vendor
npm test && .venv/bin/python scripts/test-python.py
./build.sh            # → WorkSpace/dist/release-<version>/mdPreview.app
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the project layout and [RELEASE.md](RELEASE.md) for how releases are made and checked. Security details, including how updates are verified, are in [SECURITY.md](SECURITY.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

</details>

---

Made by [Tahoe Liu](https://github.com/tahoeliu). Released under the [MIT licence](LICENSE).
