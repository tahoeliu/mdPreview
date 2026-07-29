# mdPreview - macOS Markdown Viewer

<div align="center">

A **minimalist Markdown viewer** for macOS with live rendering and editing capabilities.

[![Python Version](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS-lightgrey.svg)]()

</div>

## 🎯 Want a simple way to view Markdown files on macOS?

Here's the deal: You've got some Markdown files (those `.md` things) and you just want to see them formatted nicely without opening a browser or running through complex installation steps.

**mdPreview** is exactly that — a simple, clean Markdown viewer that just works:

- **Double-click any `.md` file** and it opens instantly
- **Read it beautifully formatted** with tables, code blocks, and everything
- **Edit it with one click** if you need to make changes
- **Save with ⌘+S** and you're done

No bells, no whistles, no setup required. Just clean, focused reading and writing.

## 📥 Download & Install

Just download and drag to Applications:

[📥 Download mdPreview.dmg](dist/mdPreview-1.1.0.dmg) *(14MB)*

**Three simple steps:**
1. Click the download link above
2. Open the `.dmg` file 
3. Drag mdPreview to your Applications folder

Done. Now double-click any `.md` file and watch the magic happen.

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

## 🚀 Installation

### Quick Install

```bash
cd MarkdownViewer
./build.sh
./install.sh
```

### File Association

After installation, associate `.md` files with mdPreview:

1. Find any `.md` file in Finder
2. Right-click → Get Info
3. Select mdPreview from "Open with"
4. Click "Change All"

Now all `.md` files will open with mdPreview by default.

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `⌘ + S` | Save file |
| `⌘ + E` | Toggle Edit/Preview mode |

## 🛠️ Tech Stack

- **Python 3.13+** - Core application logic
- **pywebview** - Native macOS WKWebView wrapper
- **marked.js** - Markdown rendering engine
- **macOS Native** - AppKit integration and native UI

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

## 🔧 Development

### Prerequisites

- Python 3.13 or higher
- pywebview (`pip install pywebview`)
- macOS 10.13 or later

### Building from Source

```bash
# Install dependencies
pip install pywebview

# Build the app
./build.sh

# Install to Applications
./install.sh
```

## 📝 Supported Markdown Features

- Headers (H1-H6)
- Bold and italic text
- Lists (ordered and unordered)
- Links and images
- Code blocks with syntax highlighting
- Tables
- Blockquotes
- Horizontal rules
- HTML content
- Mermaid diagrams

## 🤝 Contributing

Contributions are welcome! Feel free to submit issues and pull requests.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [marked.js](https://marked.js.org/) - Markdown parsing
- [pywebview](https://pywebview.flowrl.com/) - Native window wrapper
- [Mermaid](https://mermaid.js.org/) - Diagram generation

---

<div align="center">

**For a world worth debugging.**

</div>