# mdPreview - macOS Markdown Viewer & Editor

<div align="center">

**Simple, fast, and free Markdown viewer for macOS** - Perfect for developers, writers, and anyone who works with `.md` files.

[![Python Version](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS-lightgrey.svg)]()
[![Download](https://img.shields.io/badge/download-14MB-orange.svg)](https://github.com/tahoeliu/mdPreview/releases/latest/download/mdPreview.dmg)

**⭐ Star this repo if you find it useful!**

</div>

> **mdPreview is a free, open-source Markdown viewer and editor for macOS** that opens, previews, and edits `.md` files with native live rendering — no account, no internet connection, and zero configuration required.

## 🎯 The Simplest Markdown Viewer for macOS

**Stop struggling with Markdown files in plain text editors!** mdPreview gives you instant, beautiful Markdown rendering with one simple double-click.

Whether you're a **developer** reading README files, a **writer** working with Markdown documents, or just someone who wants to **view formatted Markdown** on macOS - this app is for you.

<table width="100%">
  <tr>
    <td align="center" width="33%" valign="top">
      <h3>🚀 Instant Preview</h3>
      <p>Double-click any <code>.md</code> file → beautiful, live rendering in a clean, native macOS window. No waiting, no web browser, no clutter.</p>
      <p><sub>Great for reading README files, reviewing docs, or just browsing Markdown notes.</sub></p>
    </td>
    <td align="center" width="33%" valign="top">
      <h3>✏️ Easy Editing</h3>
      <p>Switch between view and edit with one click. Tables, code blocks, lists — everything round-trips cleanly between preview and source.</p>
      <p><sub>Perfect for writing technical docs, taking notes, or tweaking README files on the fly.</sub></p>
    </td>
    <td align="center" width="33%" valign="top">
      <h3>🆓 Completely Free</h3>
      <p>No ads. No tracking. No hidden costs. Open source on GitHub — the code is yours to inspect, fork, or improve.</p>
      <p><sub>Built for developers, writers, and anyone who works with Markdown daily.</sub></p>
    </td>
  </tr>
</table>

## 📥 Download & Install

**Get mdPreview in 3 simple steps:**

[📥 **Download mdPreview.dmg**](https://github.com/tahoeliu/mdPreview/releases/latest/download/mdPreview.dmg) *(14MB)*

1. Click the download button above
2. Open the downloaded `.dmg` file
3. Drag **mdPreview** to your **Applications** folder

**That's it!** Now double-click any Markdown file and watch it render beautifully.

### Make mdPreview Your Default Markdown Viewer

After installation:

1. Find any `.md` file in Finder
2. Right-click → **Get Info**
3. Click the arrow next to "Open with"
4. Select **mdPreview** from the dropdown
5. Click **"Change All..."** button

Now every `.md` file will open automatically with mdPreview!

---

<div align="center">

**For the curious minds who refuse to accept the default.**

</div>

---

## ✨ Features

- **🖱️ Double-click to Open** - Associate `.md` files with mdPreview for instant rendering
- **⚡ Real-time Rendering** - Powered by marked.js with full Markdown support (tables, code blocks, quotes, etc.)
- **✏️ Edit Mode** - One-click toggle to edit Markdown source directly
- **⌨️ Keyboard Shortcuts** - Cmd+S to save, Cmd+E to switch edit/preview modes
- **🎨 Minimalist Interface** - Clean, focused reading and writing experience
- **📱 Native macOS Integration** - Seamless integration with macOS file system and UI
- **🌙 Dark Mode Support** - Respects your macOS appearance preferences
- **🔍 Search Functionality** - Quickly find content in your Markdown files

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `⌘ + S` | Save file |
| `⌘ + E` | Toggle Edit/Preview mode |

## 📝 Supported Markdown Features

mdPreview supports standard Markdown syntax including:

- ✅ Headers (H1-H6)
- ✅ Bold and italic text
- ✅ Lists (ordered and unordered)
- ✅ Links and images
- ✅ Code blocks with syntax highlighting
- ✅ Tables
- ✅ Blockquotes
- ✅ Horizontal rules
- ✅ HTML content
- ✅ Mermaid diagrams

## 🛠️ Tech Stack

- **Python 3.13+** - Core application logic
- **pywebview** - Native macOS WKWebView wrapper
- **marked.js** - Markdown rendering engine
- **macOS Native** - AppKit integration and native UI

## 🔧 Development

### Build from Source

```bash
# Install dependencies
pip install pywebview

# Build the app
./build.sh

# Install to Applications
./install.sh
```

### Prerequisites

- Python 3.13 or higher
- pywebview (`pip install pywebview`)
- macOS 10.13 or later

## 📁 Project Structure

```
MarkdownViewer/
├── markdown_viewer.py    # Main application logic
├── index.html           # WebView interface
├── marked.min.js        # Markdown renderer
├── turndown.js          # HTML to Markdown converter
├── mermaid.min.js       # Diagram support
├── app_icon.icns        # Application icon
├── Info.plist          # macOS app metadata
├── build.sh            # Build script
├── install.sh          # Installation script
└── README.md           # This file
```

## 🌟 Why Choose mdPreview?

**Compared to other Markdown viewers:**

| Feature | mdPreview | Text Editors | Online Tools |
|---------|-----------|--------------|--------------|
| Native macOS Experience | ✅ | ❌ | ❌ |
| Offline Use | ✅ | ✅ | ❌ |
| File Association | ✅ | ❌ | ❌ |
| Zero Configuration | ✅ | ❌ | ❌ |
| No Internet Required | ✅ | ✅ | ❌ |
| Lightweight | ✅ | ✅ | ✅ |
| Beautiful Rendering | ✅ | ❌ | ✅ |

## 🆚 mdPreview vs Other Markdown Apps for Mac

Looking for a **free Markdown editor for Mac**, a **Typora alternative**, or a lightweight **MacDown replacement**? Here's how mdPreview compares:

| Feature | **mdPreview** | Typora | MacDown | Bear | VS Code |
|---------|:---:|:---:|:---:|:---:|:---:|
| Free & open-source (MIT) | ✅ | ❌ (paid) | ✅ | ❌ (subscription) | ✅ |
| Native macOS app | ✅ | ✅ | ✅ | ✅ | ❌ (Electron) |
| Double-click `.md` to open | ✅ | ✅ | ✅ | ✅ | ❌ |
| Offline / no account | ✅ | ✅ | ✅ | ❌ | ✅ |
| Lightweight (<20 MB) | ✅ | ⚠️ | ✅ | ✅ | ❌ |
| Mermaid diagram support | ✅ | ⚠️ | ❌ | ❌ | ⚠️ |
| Live edit + preview | ✅ | ✅ | ✅ | ✅ | ⚠️ (extension) |

**Best for:** anyone who wants a simple, fast, and completely free way to **view and edit Markdown on Mac** — without subscriptions or a heavy IDE.

---

## 🤝 Contributing

Contributions are welcome! Feel free to:

- 🐛 Report bugs via [GitHub Issues](https://github.com/tahoeliu/mdPreview/issues)
- 💡 Suggest new features
- 🔧 Submit pull requests
- 📖 Improve documentation

## ❓ Frequently Asked Questions

**What is mdPreview?**  
mdPreview is a free, open-source Markdown viewer and editor for macOS. It renders `.md` files with live preview, supports editing, dark mode, in-file search, and Mermaid diagrams, and runs fully offline.

**Is mdPreview free?**  
Yes. mdPreview is MIT-licensed and completely free — no ads, no tracking, no subscription.

**Which macOS versions are supported?**  
macOS 10.13 (High Sierra) and later.

**How do I set mdPreview as the default Markdown viewer on Mac?**  
Right-click any `.md` file → *Get Info* → *Open with* → select **mdPreview** → click *Change All…*.

**Does mdPreview work offline?**  
Yes. mdPreview requires no internet connection and sends no data externally.

**What Markdown features are supported?**  
Headers, bold/italic, lists, links, images, fenced code with syntax highlighting, tables, blockquotes, inline HTML, and Mermaid diagrams.

**How is mdPreview built?**  
It uses Python 3.13+, pywebview (native WKWebView), and marked.js for rendering.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [marked.js](https://marked.js.org/) - Markdown parsing library
- [pywebview](https://pywebview.flowrl.com/) - Native window wrapper
- [Mermaid](https://mermaid.js.org/) - Diagram generation library

## 📢 Share mdPreview

If you find mdPreview useful, please consider:

- ⭐ **Star this repository** on GitHub
- 🔗 **Share it** with friends and colleagues
- 🐦 **Tweet** about it on social media
- 📝 **Write a review** if you publish about it

## 🔗 Related Projects

- [Typora](https://typora.io/) - Professional Markdown editor
- [MacDown](https://macdown.uranusjr.com/) - Open source Markdown editor for macOS
- [VS Code](https://code.visualstudio.com/) - Code editor with Markdown support

---

<div align="center">

**For a world worth debugging.**

[⬆ Back to Top](#mdpreview---macos-markdown-viewer--editor)

</div>

---

**Keywords:** macOS Markdown viewer, Markdown reader, Markdown editor, Markdown app, Markdown preview, Markdown rendering, free Markdown editor for Mac, open source Markdown, Typora alternative, MacDown replacement, minimalist Markdown tool, Tahoe Liu

*Author: [Tahoe Liu](https://github.com/tahoeliu) · License: MIT*
