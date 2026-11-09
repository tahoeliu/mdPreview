#!/usr/bin/env python3
"""
Minimal Markdown Viewer for macOS
"""

import sys
import os
# 在WebView/窗口/更新逻辑加载前冻结当前启动副本，采样失败永久禁用本进程更新。
_STARTUP_BUNDLE_SNAPSHOT = None
if getattr(sys, 'frozen', False):
    try:
        from pathlib import Path
        from types import MappingProxyType
        from mdpreview_core.release import bundle_snapshot
        _STARTUP_BUNDLE_SNAPSHOT = MappingProxyType(bundle_snapshot(Path(sys.executable).resolve().parents[2]))
    except (OSError, ValueError):
        pass
import json
import re
import time
_PROCESS_START = time.monotonic()
import threading
import tempfile
import shutil
import hashlib
import logging
import uuid
from logging.handlers import RotatingFileHandler
from contextlib import contextmanager, nullcontext
from urllib.parse import urlsplit
from mdpreview_core.storage import atomic_write, atomic_create, DraftStore
from mdpreview_core.images import export_image
if '--install-update-helper' in sys.argv:
    from scripts.install_update import main as install_helper
    sys.argv.remove('--install-update-helper')
    install_helper()
    sys.exit(0)
import webview


def version_tuple(*args, **kwargs):  # 更新校验模块只在检查更新时才加载，缩短冷启动
    from mdpreview_core.release import version_tuple as impl
    return impl(*args, **kwargs)


def verify_bundle(*args, **kwargs):
    from mdpreview_core.release import verify_bundle as impl
    return impl(*args, **kwargs)


def verify_asset(*args, **kwargs):
    from mdpreview_core.release import verify_asset as impl
    return impl(*args, **kwargs)

_START_T0 = time.time()  # cold-start profiling

APP_SUPPORT_DIR = os.environ.get('MDPREVIEW_DATA_DIR') or os.path.expanduser('~/Library/Application Support/mdPreview')
CONFIG_FILE = os.path.join(APP_SUPPORT_DIR, 'config.json')
LEGACY_CONFIG_FILE = os.path.expanduser('~/.mdviewer_config.json')
LOG_FILE = os.path.join(APP_SUPPORT_DIR, 'Logs', 'mdPreview.log') if os.environ.get('MDPREVIEW_DATA_DIR') else os.path.expanduser('~/Library/Logs/mdPreview/mdPreview.log')
DRAFT_DIR = os.path.join(APP_SUPPORT_DIR, 'Drafts')
UPDATE_STAGING_DIR = os.path.join(APP_SUPPORT_DIR, 'UpdateStaging')


def _setup_logging():
    if '--headless-export' in sys.argv:
        return
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        logging.basicConfig(handlers=[RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3)],
                            level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    except OSError:
        pass


def _uncaught_exception(exc_type, exc_value, traceback):
    from mdpreview_core.diagnostics import record
    record('uncaught', error=exc_type.__name__)
    logging.error('uncaught exception; details excluded for privacy')


def _uncaught_thread(args):
    from mdpreview_core.diagnostics import record
    record('thread-uncaught', error=args.exc_type.__name__)
    logging.error('uncaught thread exception; details excluded for privacy')


sys.excepthook = _uncaught_exception
threading.excepthook = _uncaught_thread


def log_exception(context):
    try:
        logging.exception(context)
    except Exception:
        pass


_setup_logging()


def _is_chinese_locale():
    language = os.environ.get('MDPREVIEW_LANGUAGE')
    if not language:
        try:
            from Foundation import NSLocale
            language = str(NSLocale.preferredLanguages()[0])
        except Exception:
            language = os.environ.get('LC_ALL') or os.environ.get('LANG', '')
    return language.lower().startswith('zh')


def _locale_bundle():
    language = load_config().get('settings', {}).get('language', 'system')
    if language == 'system':
        language = os.environ.get('MDPREVIEW_LANGUAGE')
        if not language:
            try:
                from Foundation import NSLocale
                language = str(NSLocale.preferredLanguages()[0])
            except Exception:
                language = os.environ.get('LC_ALL') or os.environ.get('LANG', 'en')
    tag = str(language).replace('_', '-').lower()
    if tag.startswith(('zh-hant', 'zh-tw', 'zh-hk', 'zh-mo')):
        locale = 'zh-Hant'
    elif tag.startswith('zh'):
        locale = 'zh-Hans'
    else:
        locale = next((code for code in ('ja', 'ko', 'de', 'fr', 'es') if tag == code or tag.startswith(code + '-')), 'en')
    try:
        with open(get_resource_path('frontend/' + locale + '.json'), encoding='utf-8') as stream:
            messages = json.load(stream)
    except (OSError, ValueError):
        messages = {}
    return {'locale': locale, 'messages': messages}


def _apply_appearance(value):
    """Force light/dark (or follow the system) for the whole app; the web view's
    prefers-color-scheme follows NSApp's appearance, so no CSS duplication is needed."""
    if not HAS_COCOA:
        return
    def apply():
        try:
            from AppKit import NSApplication, NSAppearance
            name = {'light': 'NSAppearanceNameAqua', 'dark': 'NSAppearanceNameDarkAqua'}.get(value)
            NSApplication.sharedApplication().setAppearance_(NSAppearance.appearanceNamed_(name) if name else None)
        except Exception:
            log_exception('apply appearance failed')
    from PyObjCTools import AppHelper
    AppHelper.callAfter(apply)


def _t(en, zh):
    bundle = _locale_bundle()
    return bundle['messages'].get(en, zh if bundle['locale'] == 'zh-Hans' else en)


_TITLEBAR_STATE = {'overlay': False, 'height': 0}
_DRAG_STRIP_CLASS = []


def _drag_strip_class():
    """A transparent view that lets the window be dragged by the title bar area even though the page extends under it."""
    if _DRAG_STRIP_CLASS:
        return _DRAG_STRIP_CLASS[0]
    from AppKit import NSView

    class MdpTitlebarDragView(NSView):
        def mouseDownCanMoveWindow(self):
            return True

        def acceptsFirstMouse_(self, event):
            return True

        def mouseDown_(self, event):
            try:
                if event.clickCount() == 2:
                    self.window().performZoom_(None)      # double-click the title bar: zoom, as in any Mac app
                else:
                    self.window().performWindowDragWithEvent_(event)
            except Exception:
                pass

    _DRAG_STRIP_CLASS.append(MdpTitlebarDragView)
    return MdpTitlebarDragView


def _ensure_drag_strip(win, height):
    from AppKit import NSMakeRect
    frame = win.contentView().superview()
    strip = getattr(win, '_mdp_drag_strip', None)
    width = frame.frame().size.width
    top = frame.frame().size.height
    left = 76.0                                              # leave the traffic lights alone
    if strip is None or strip.superview() is None:
        strip = _drag_strip_class().alloc().initWithFrame_(NSMakeRect(left, top - height, max(0.0, width - left), height))
        strip.setAutoresizingMask_(2 | 8)                    # width-sizable, pinned to the top
        frame.addSubview_(strip)
        try:
            win._mdp_drag_strip = strip
        except Exception:
            pass
    strip.setFrame_(NSMakeRect(left, top - height, max(0.0, width - left), height))


def _begin_window_drag():
    """Main thread: start dragging the front window (used when the page's own top bar is grabbed)."""
    try:
        from AppKit import NSApplication
        from webview.platforms.cocoa import BrowserView
        ref = _get_target_window()
        browser = BrowserView.instances.get(ref.uid) if ref else None
        event = NSApplication.sharedApplication().currentEvent()
        if browser is not None and event is not None:
            browser.window.performWindowDragWithEvent_(event)
    except Exception:
        log_exception('window drag failed')


def _blend_titlebar(window):
    """Main thread only. Lets the page extend under a transparent title bar: the title bar takes the page's own colour
    (white / dark), with no grey strip and no hairline, in both the active and the inactive state."""
    try:
        from webview.platforms.cocoa import BrowserView
        browser = BrowserView.instances.get(window.uid)
        if browser is None:
            return
        win = browser.window
        if not (win.styleMask() & (1 << 15)):
            win.setStyleMask_(win.styleMask() | (1 << 15))
        win.setTitlebarAppearsTransparent_(True)
        for view in win.contentView().superview().subviews():
            if view.className() == 'NSTitlebarContainerView':
                layer = view.layer()
                if layer is not None:
                    layer.setBackgroundColor_(None)
                for sub in view.subviews():
                    if sub.className() == '_NSTitlebarDecorationView':
                        sub.setHidden_(True)
        _TITLEBAR_STATE['overlay'] = True
        _ensure_drag_strip(win, max(1.0, win.frame().size.height - win.contentLayoutRect().size.height))
        _TITLEBAR_STATE['height'] = round(max(0.0, win.frame().size.height - win.contentLayoutRect().size.height))
    except Exception:
        log_exception('title bar blend failed')


def _set_represented_file(window, path):
    """标题栏文件图标（代理图标）：可拖出文件，⌘点击标题显示路径。"""
    if not HAS_COCOA or window is None:
        return
    def apply():
        try:
            from webview.platforms.cocoa import BrowserView
            browser = BrowserView.instances.get(window.uid)
            if browser is not None:
                browser.window.setRepresentedFilename_(path if path and os.path.isfile(path) else '')
                _blend_titlebar(window)
        except Exception:
            pass
    try:
        from PyObjCTools import AppHelper
        AppHelper.callAfter(apply)
    except Exception:
        pass


def _is_privacy_sensitive_user_path(path):
    """String-only check for macOS privacy-gated user folders; does not touch disk."""
    if not path:
        return False
    try:
        target = os.path.abspath(os.path.expanduser(path))
        protected_roots = [
            os.path.abspath(os.path.expanduser('~/Desktop')),
            os.path.abspath(os.path.expanduser('~/Documents')),
            os.path.abspath(os.path.expanduser('~/Downloads')),
        ]
        return any(target == root or target.startswith(root + os.sep) for root in protected_roots)
    except Exception:
        return False


def _default_save_directory(preferred=None):
    """Choose the save panel folder: last explicit choice, then Desktop, then Home.

    Do not preflight Desktop/Documents/Downloads with os.path.isdir/os.path.exists;
    those checks themselves can trigger macOS TCC prompts before the user acts.
    """
    candidates = []
    if preferred:
        candidates.append(preferred)
    try:
        cfg = load_config()
        if cfg.get('last_save_dir'):
            candidates.append(cfg.get('last_save_dir'))
        for recent_path in cfg.get('recent_files', [])[:10]:
            if recent_path:
                candidates.append(os.path.dirname(os.path.abspath(recent_path)))
    except Exception:
        pass
    candidates.append(os.path.expanduser('~/Desktop'))
    candidates.append(os.path.expanduser('~'))
    seen = set()
    for directory in candidates:
        try:
            directory = os.path.abspath(os.path.expanduser(directory))
            if directory in seen:
                continue
            seen.add(directory)
            if _is_privacy_sensitive_user_path(directory):
                return directory
            if os.path.isdir(directory):
                return directory
        except Exception:
            continue
    return os.path.expanduser('~')


def _remember_save_directory(path):
    if '--headless-export' in sys.argv:
        return
    if path:
        update_config({'last_save_dir': os.path.dirname(os.path.abspath(path))})


def _fsync_directory(directory):
    """Best-effort fsync for a directory after an atomic rename."""
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        pass


def _safe_write_text(path, content, encoding='utf-8'):
    raw = content.encode(encoding)
    if encoding == 'utf-16-le':
        raw = b'\xff\xfe' + raw
    elif encoding == 'utf-16-be':
        raw = b'\xfe\xff' + raw
    atomic_write(path, raw)


def _detect_text_encoding(path):
    """Detect a practical Markdown text encoding while preserving common BOMs."""
    with open(path, 'rb') as f:
        raw = f.read()
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw.decode('utf-8-sig'), 'utf-8-sig'
    if raw.startswith(b'\xff\xfe') or raw.startswith(b'\xfe\xff'):
        # A UTF-16 BOM does not guarantee valid UTF-16 content (truncated or
        # byte-corrupted files). Fall back to the generic detectors rather than
        # crashing the viewer when a file with a UTF-16 BOM is unreadable.
        try:
            return raw.decode('utf-16'), 'utf-16-le' if raw.startswith(b'\xff\xfe') else 'utf-16-be'
        except UnicodeDecodeError:
            pass
    for enc in ('utf-8', 'gb18030', 'latin-1'):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace'), 'utf-8'


def _safe_read_text(path):
    """Read text file with encoding detection."""
    content, _ = _detect_text_encoding(path)
    return content


def _draft_key(path):
    label = os.path.abspath(path) if path else 'Untitled.md'
    return hashlib.sha256(label.encode('utf-8')).hexdigest()[:24]


def _write_draft(path, content, document_id=None, revision=0, baseline_digest=None):
    try:
        if document_id:
            DraftStore(DRAFT_DIR).write(path, document_id, revision, content, baseline_digest)
            return os.path.join(DRAFT_DIR, DraftStore.key(path, document_id) + '.json')
        # Compatibility with named drafts made by releases before 1.5.
        if not path:
            raise ValueError('Untitled drafts require document identity')
        destination = os.path.join(DRAFT_DIR, _draft_key(path) + '.md')
        _safe_write_text(destination, content)
        return destination
    except Exception:
        log_exception('write draft failed')
        return None


def _read_draft(path):
    """Read draft content if it exists. Returns (content, mtime) or (None, None)."""
    try:
        draft_path = os.path.join(DRAFT_DIR, _draft_key(path) + '.md')
        if os.path.exists(draft_path):
            content = _safe_read_text(draft_path)
            mtime = os.path.getmtime(draft_path)
            return content, mtime
    except Exception:
        log_exception('read draft failed')
    return None, None


def _check_draft_for_file(file_path, document_id=None):
    if not file_path:
        return None
    record = DraftStore(DRAFT_DIR).read(file_path, document_id)
    original = _safe_read_text(file_path) if os.path.exists(file_path) else None
    if record and record['content'] != original:
        return record['content']
    legacy, modified = _read_draft(file_path)
    if legacy is not None and legacy != original and (original is None or modified > os.path.getmtime(file_path)):
        return legacy
    return None


def _edited_title(name, dirty):
    # Append the TextEdit-style Edited marker to a window title.
    return (name or 'Untitled.md') + (' - ' + _t('Edited', '已编辑') if dirty else '')


def _remove_draft(path, document_id=None):
    try:
        if document_id:
            DraftStore(DRAFT_DIR).remove(path, document_id)
        legacy = os.path.join(DRAFT_DIR, _draft_key(path) + '.md')
        if path and os.path.exists(legacy):
            os.remove(legacy)
    except Exception:
        log_exception('remove draft failed')


try:
    from AppKit import NSApplication, NSObject, NSAlert, NSColor, NSMutableAttributedString, NSImage
    from PyObjCTools import AppHelper
    import objc
    HAS_COCOA = True
except ImportError:
    HAS_COCOA = False


if HAS_COCOA:

    def _find_button_stack(view, depth=0):
        """Find the NSStackView holding an NSAlert's buttons (macOS 11+).

        NSAlert lays its buttons out vertically by default. macOS 11+ keeps
        them in an NSStackView inside the alert window; flipping that stack to
        horizontal (a public API) yields the TextEdit-style one-row button
        layout. Returns None on older macOS or if not found.
        """
        try:
            from AppKit import NSStackView, NSButton
            if depth > 8:
                return None
            subs = view.subviews()
            for i in range(subs.count()):
                sv = subs.objectAtIndex_(i)
                if isinstance(sv, NSStackView):
                    arr = sv.arrangedSubviews()
                    has_btn = any(isinstance(arr.objectAtIndex_(j), NSButton)
                                  for j in range(arr.count()))
                    if has_btn:
                        return sv
                found = _find_button_stack(sv, depth + 1)
                if found is not None:
                    return found
            return None
        except Exception:
            return None

    def _format_disclaimer(ext):
        # md / txt / html are written as plain text and match the preview
        # exactly, so they never need the experimental warning.
        if ext in ('md', 'txt', 'html'):
            return ''
        return _t('Experimental; output may differ from preview.', '实验性功能，输出效果可能与预览不同。')

    # Measured from a real Save panel on macOS 26 Tahoe at 2x retina:
    # the Where popup's left edge sits at x = 80pt from the accessory view's
    # left edge. Used to right-align the Format label and place the popup.
    _MEASURED_LABEL_WIDTH = 90.0

    def _measure_label_width():
        """Pixel position of the Where popup column in NSSavePanel.

        On macOS 26 Tahoe the system label column ends and the popup column
        begins at ~80pt from the accessory view's left edge (pixel-measured
        from a real Save dialog). This is the only knob we need: the popup
        starts at this x, and the Format label is right-aligned into
        0..label_w.
        """
        try:
            return float(_MEASURED_LABEL_WIDTH)
        except Exception:
            return 80.0

    def _layout_format_acc(acc, label, popup, disclaimer, ext, label_w=None):
        """Position Format row to match the historical v1.4.0/v1.4.2 geometry.

        v1.4.0 (no disclaimer): acc 360x64, label y=22, popup y=18.
        v1.4.2 (with disclaimer): acc 360x82, label y=42, popup y=38, disclaimer y=12.

        Those values produced visually balanced rows on prior macOS versions
        and remain the only known-working geometry. The label is now
        right-aligned into 0..label_w so the popup can start at label_w and
        line up with the Where popup above.
        """
        from AppKit import NSMakeRect, NSRightTextAlignment
        if label_w is None:
            label_w = _measure_label_width()
        has = bool(_format_disclaimer(ext))
        if has:
            acc_h = 82.0
            ly = 42.0
            py = 38.0
            dy = 12.0
        else:
            acc_h = 64.0
            ly = 22.0
            py = 18.0
            dy = None
        acc_w = acc.frame().size.width
        popup_w = max(120.0, acc_w - label_w - 20.0)
        try:
            label.setAlignment_(NSRightTextAlignment)
        except Exception:
            pass
        label.setFrame_(NSMakeRect(0, ly, label_w - 4.0, 20))
        popup.setFrame_(NSMakeRect(label_w, py, popup_w, 25))
        if has:
            disclaimer.setFrame_(NSMakeRect(label_w, dy, popup_w, 18))
            disclaimer.setHidden_(False)
        else:
            disclaimer.setHidden_(True)
        acc.setFrame_(NSMakeRect(0, 0, acc_w, acc_h))

    def _layout_output_controls(holder, ext):
        from AppKit import NSMakeRect
        acc = holder['acc']
        rows = holder.get('output_controls', [])
        visible = [row for row in rows if ext in row[3]]
        offset = len(visible) * 28
        if not rows:
            return
        for key in ('label', 'popup', 'disclaimer'):
            control = holder[key]
            frame = control.frame()
            control.setFrame_(NSMakeRect(frame.origin.x, frame.origin.y + offset, frame.size.width, frame.size.height))
        width = acc.frame().size.width
        for row in rows:
            key, label, control, formats, choices = row
            hidden = row not in visible
            label.setHidden_(hidden); control.setHidden_(hidden)
            if not hidden:
                y = offset - (visible.index(row)+1)*28 + 8
                label.setFrame_(NSMakeRect(0,y+3,holder['label_w']-4,20))
                control.setFrame_(NSMakeRect(holder['label_w'],y,width-holder['label_w']-20,25))
        acc.setFrame_(NSMakeRect(0,0,width,acc.frame().size.height+offset))

    def _make_output_controls(holder):
        from AppKit import NSPopUpButton, NSButton, NSTextField, NSSwitchButton, NSMakeRect, NSRightTextAlignment
        from mdpreview_core.export.settings import CHOICES
        specs = [('paper',_t('Paper','纸张'),('pdf',)), ('margins',_t('Margins','边距'),('pdf',)), ('font',_t('Font size','字号'),('pdf',)),
                 ('pdf_layout',_t('PDF layout','PDF布局'),('pdf',)), ('page_numbers',_t('Page numbers','页码'),('pdf',)),
                 ('show_urls',_t('Show links','显示链接'),('pdf',)), ('hide_frontmatter',_t('Hide metadata','隐藏元数据'),('pdf','html','png')),
                 ('h1_new_page',_t('Start heading 1 on new page','一级标题另页'),('pdf',)), ('png_width',_t('PNG width','PNG宽度'),('png',))]
        names = {'auto':_t('Auto','自动'),'a4':'A4','letter':'Letter','narrow':_t('Narrow','窄'),'normal':_t('Normal','标准'),'wide':_t('Wide','宽'),
                 'small':_t('Small','小'),'large':_t('Large','大'),'paged':_t('Paged','分页'),'continuous':_t('Continuous long page','连续长页'),
                 'original':_t('Current width','当前宽度'),'mobile':_t('Phone 540px','手机 540px')}
        values = MarkdownAPI().get_output_settings()
        rows = []
        for key, title, formats in specs:
            label = NSTextField.labelWithString_(title)
            label.setAlignment_(NSRightTextAlignment)
            choices = CHOICES.get(key)
            if choices:
                control = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(0,0,240,25))
                for value in choices: control.addItemWithTitle_(names[value])
                control.selectItemAtIndex_(choices.index(values[key]))
            else:
                control = NSButton.alloc().initWithFrame_(NSMakeRect(0,0,240,25))
                control.setButtonType_(NSSwitchButton); control.setTitle_(title); control.setState_(int(values[key]))
                label.setStringValue_('')   # the label column is narrow; a checkbox carries its own title so it is never cut off
            holder['acc'].addSubview_(label); holder['acc'].addSubview_(control)
            rows.append((key,label,control,formats,choices))
        holder['output_controls'] = rows

    class _FormatPopupActions(NSObject):
        """Action target for the save panel's format popup: switches the panel's
        allowed file type and renames the file field's extension."""

        def initWithHolder_(self, holder):
            self = objc.super(_FormatPopupActions, self).init()
            self._holder = holder
            return self

        def formatChanged_(self, sender):
            try:
                h = self._holder or {}
                idx = sender.indexOfSelectedItem()
                formats = h.get('formats', [])
                if idx < 0 or idx >= len(formats):
                    return
                ext = formats[idx][1]
                acc = h.get('acc')
                label = h.get('label')
                popup = h.get('popup')
                disclaimer = h.get('disclaimer')
                label_w = h.get('label_w')
                if acc is not None and label is not None and popup is not None and disclaimer is not None:
                    try:
                        _layout_format_acc(acc, label, popup, disclaimer, ext, label_w)
                        _layout_output_controls(h, ext)
                        panel = h.get('panel')
                        if panel is not None:
                            try:
                                panel.contentView().layoutSubtreeIfNeeded_()
                            except Exception:
                                pass
                    except Exception:
                        pass
                panel = h.get('panel')
                if panel is not None:
                    try:
                        panel.setAllowedFileTypes_([ext])
                    except Exception:
                        pass
                    try:
                        nf = panel.nameField()
                        name = nf.stringValue() or ''
                        base = name.rsplit('.', 1)[0] if '.' in name else name
                        nf.setStringValue_(base + '.' + ext)
                    except Exception:
                        pass
            except Exception:
                log_exception('format popup changed failed')

    def _run_format_panel(holder, base_name, formats, title, name_label=None):
        """Native save panel with a format popup in its accessory view.

        Layout: the label column width is measured at runtime from a "Where:"
        NSTextField via sizeToFit(), then the popup is placed immediately after
        it. This aligns with the panel's built-in rows without hardcoding
        any per-macOS pixel values.

        Formats: list of (display_label, extension_key). On OK, holder gets
        'path' + 'format' (the extension key); on cancel, 'cancelled'; on
        failure, 'error'. 面板在主线程执行，等待用户完成，不设交互超时。
        """
        try:
            from AppKit import (NSSavePanel, NSPopUpButton, NSView, NSTextField,
                                NSMakeRect, NSColor, NSFont, NSOKButton)
            from PyObjCTools import AppHelper

            completed = threading.Event()

            def _do():
                try:
                    panel = NSSavePanel.savePanel()
                    panel.setTitle_(title)
                    if name_label:
                        try:
                            panel.setNameFieldLabel_(name_label)
                        except Exception:
                            pass
                    try:
                        panel.setPrompt_(title)
                    except Exception:
                        pass
                    panel.setCanCreateDirectories_(True)
                    try:
                        from Foundation import NSURL
                        panel.setDirectoryURL_(NSURL.fileURLWithPath_(_default_save_directory()))
                    except Exception:
                        pass

                    label_w = _measure_label_width()

                    # --- Format label (right-aligned in 0..label_w) ---
                    label = NSTextField.labelWithString_(_t('Format:', '格式：'))
                    label.setTextColor_(NSColor.secondaryLabelColor())

                    # --- Format popup (starts at label_w) ---
                    popup = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(0, 0, 260, 25))
                    popup.setAutoresizingMask_(2)  # NSViewWidthSizable
                    for f in formats:
                        popup.addItemWithTitle_(f[0])

                    # --- Disclaimer (shown only for docx/png/pdf) ---
                    disclaimer = NSTextField.labelWithString_(_format_disclaimer(formats[0][1]))
                    disclaimer.setTextColor_(NSColor.tertiaryLabelColor())
                    try:
                        disclaimer.setFont_(NSFont.systemFontOfSize_(11))
                    except Exception:
                        pass
                    disclaimer.setAutoresizingMask_(2)

                    # --- Plain NSView as the accessory container ---
                    acc = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 360, 50))
                    _layout_format_acc(acc, label, popup, disclaimer, formats[0][1], label_w)
                    acc.addSubview_(label)
                    acc.addSubview_(popup)
                    acc.addSubview_(disclaimer)

                    holder['formats'] = formats
                    holder['panel'] = panel
                    holder['acc'] = acc
                    holder['label'] = label
                    holder['popup'] = popup
                    holder['disclaimer'] = disclaimer
                    holder['label_w'] = label_w
                    _make_output_controls(holder)
                    _layout_output_controls(holder, formats[0][1])

                    actions = _FormatPopupActions.alloc().initWithHolder_(holder)
                    popup.setTarget_(actions)
                    popup.setAction_('formatChanged:')

                    panel.setAccessoryView_(acc)
                    panel.setAllowedFileTypes_([formats[0][1]])
                    panel.setNameFieldStringValue_(base_name + '.' + formats[0][1])
                    if panel.runModal() == NSOKButton:
                        url = panel.URL()
                        if url:
                            holder['path'] = url.path()
                            idx = popup.indexOfSelectedItem()
                            holder['format'] = formats[idx][1] if 0 <= idx < len(formats) else formats[0][1]
                            options = {}
                            for key, label, control, supported, choices in holder['output_controls']:
                                if holder['format'] in supported:
                                    options[key] = choices[control.indexOfSelectedItem()] if choices else bool(control.state())
                            if not MarkdownAPI().set_output_settings(options)['success']:
                                holder['error'] = 'output-settings-write-failed'
                            return
                    holder['cancelled'] = True
                except Exception as e:
                    holder['error'] = str(e)
                finally:
                    completed.set()

            AppHelper.callAfter(_do)
            completed.wait()
        except Exception as e:
            holder['error'] = str(e)

    class _SavePromptActions(NSObject):
        """Action target for the custom save panel's controls.

        whereChanged_ handles the Where popup (common folders or Browse…),
        delete/cancel/saveClicked_ record the outcome and end the modal.
        """

        def initWithHolder_(self, holder):
            self = objc.super(_SavePromptActions, self).init()
            self._holder = holder
            return self

        def whereChanged_(self, sender):
            try:
                holder = self._holder or {}
                popup = sender
                title = popup.titleOfSelectedItem() or ''
                if title == _t('Browse…', '浏览…'):
                    from AppKit import NSOpenPanel, NSOKButton
                    panel = NSOpenPanel.openPanel()
                    panel.setTitle_(_t('Choose Folder', '选择文件夹'))
                    panel.setCanChooseFiles_(False)
                    panel.setCanChooseDirectories_(True)
                    panel.setAllowsMultipleSelection_(False)
                    panel.setCanCreateDirectories_(True)
                    if panel.runModal() == NSOKButton:
                        url = panel.URL()
                        if url:
                            directory = url.path()
                            holder['base_dir'] = directory
                            popup.addItemWithTitle_(os.path.basename(directory) or directory)
                            popup.selectItemWithTitle_(os.path.basename(directory) or directory)
                    return
                for t, d in holder.get('dirs', []):
                    if t == title:
                        holder['base_dir'] = d
                        return
            except Exception:
                log_exception('save panel where action failed')

        def deleteClicked_(self, sender):
            try:
                holder = self._holder or {}
                holder['action'] = 'delete'
                panel = holder.get('panel')
                if panel is not None:
                    panel.orderOut_(None)
                try:
                    from AppKit import NSApp
                    NSApp.stopModalWithCode_(2)
                except Exception:
                    pass
            except Exception:
                log_exception('save panel delete action failed')

        def cancelClicked_(self, sender):
            try:
                holder = self._holder or {}
                holder['action'] = 'cancel'
                panel = holder.get('panel')
                if panel is not None:
                    panel.orderOut_(None)
                try:
                    from AppKit import NSApp
                    NSApp.stopModalWithCode_(0)
                except Exception:
                    pass
            except Exception:
                log_exception('save panel cancel action failed')

        def saveClicked_(self, sender):
            try:
                holder = self._holder or {}
                name = ''
                directory = holder.get('base_dir') or _default_save_directory()
                field = holder.get('name_field')
                if field is not None:
                    name = (field.stringValue() or '').strip()
                if not name:
                    name = 'untitled'
                if not name.lower().endswith('.md'):
                    name += '.md'
                holder['path'] = os.path.join(directory, name)
                holder['action'] = 'save'
                panel = holder.get('panel')
                if panel is not None:
                    panel.orderOut_(None)
                try:
                    from AppKit import NSApp
                    NSApp.stopModalWithCode_(1)
                except Exception:
                    pass
            except Exception:
                log_exception('save panel save action failed')


def _pdf_to_a4_longpage(src_path, dst_path):
    """连续 PDF 缩至 A4 宽度，超过 14000pt 分段并原子保存。"""
    from Foundation import NSURL
    from Quartz import (CGPDFDocumentCreateWithURL, CGPDFDocumentGetPage,
                        CGPDFPageGetBoxRect, CGPDFContextCreateWithURL,
                        CGContextDrawPDFPage, CGPDFContextBeginPage,
                        CGPDFContextEndPage, CGPDFContextClose,
                        CGContextSaveGState, CGContextRestoreGState,
                        CGContextScaleCTM, CGContextTranslateCTM,
                        CGRectMake, kCGPDFMediaBox)
    A4_W = 595.28  # A4 portrait width in points
    M = 36.0  # side margins
    src = CGPDFDocumentCreateWithURL(NSURL.fileURLWithPath_(src_path))
    if src is None:
        raise ValueError('cannot open source pdf')
    page = CGPDFDocumentGetPage(src, 1)
    r = CGPDFPageGetBoxRect(page, kCGPDFMediaBox)
    src_w, src_h = r.size.width, r.size.height
    if src_w <= 0 or src_h <= 0:
        raise ValueError('bad source page size')
    pw = A4_W - 2 * M
    sx = min(1.0, pw / src_w)
    import math
    import struct
    from Foundation import NSMutableData, NSData
    from Quartz import CGDataConsumerCreateWithCFData, CGPDFContextCreate, kCGPDFContextMediaBox
    content_h = src_h * sx
    segment_h = 14000 - 2 * M
    count = max(1, math.ceil(content_h / segment_h))
    data = NSMutableData.data()
    ctx = CGPDFContextCreate(CGDataConsumerCreateWithCFData(data), None, None)
    if ctx is None:
        raise ValueError('cannot create output pdf context')
    for index in range(count):
        page_h = min(segment_h, content_h-index*segment_h) + 2*M
        box = struct.pack('dddd', 0, 0, A4_W, page_h)
        CGPDFContextBeginPage(ctx, {kCGPDFContextMediaBox: NSData.dataWithBytes_length_(box, len(box))})
        CGContextSaveGState(ctx)
        from Quartz import CGContextClipToRect
        CGContextClipToRect(ctx, CGRectMake(M, M, A4_W-2*M, page_h-2*M))
        CGContextScaleCTM(ctx, sx, sx)
        CGContextTranslateCTM(ctx, M/sx, (page_h-M+index*segment_h)/sx-src_h)
        CGContextDrawPDFPage(ctx, page)
        CGContextRestoreGState(ctx)
        CGPDFContextEndPage(ctx)
    CGPDFContextClose(ctx)
    atomic_write(dst_path, bytes(data))
    return count


_pending_link_hashes = {}


class MarkdownAPI:
    def __init__(self, file_path=None):
        self.document_id = str(uuid.uuid4())
        self.revision = 0
        self.saved_revision = 0
        self._session_lock = threading.RLock()
        self._save_lock = threading.Lock()
        self._output_lock = threading.Lock()
        self._output_completion = None
        self.file_path = file_path
        self.pending_hash = _pending_link_hashes.pop(os.path.realpath(file_path), '') if file_path else ''
        self.cached_content = ''  # JS pushes content here periodically
        self.file_content = ''    # Last known file content
        self.window = None        # Set after window creation
        self.is_dirty = False     # JS-maintained dirty flag
        self.is_untitled = not file_path  # True for blank "New File" documents
        self.read_error = None
        self.recovery_conflict = False
        self.encoding = 'utf-8'    # Preserve the source file encoding on save
        self.baseline_mtime_ns = None
        self.baseline_size = None
        self.close_confirmed = False  # True after the user explicitly chooses to close

    def _record_baseline_stat(self, path):
        from mdpreview_core.watcher import watcher
        if path and self.window:
            watcher.watch(id(self), path, self._external_change)
        try:
            stat = os.stat(path)
            self.baseline_mtime_ns = getattr(stat, 'st_mtime_ns', int(stat.st_mtime * 1_000_000_000))
            self.baseline_size = stat.st_size
        except Exception:
            self.baseline_mtime_ns = None
            self.baseline_size = None

    def finish_quit_document(self, approved, document_id=None):
        if document_id and document_id != self.document_id:
            return False
        _finish_quit_confirmation(self, bool(approved))
        return True

    def read_image_for_export(self, src, document_id=None):
        if document_id and document_id != self.document_id:
            return {'success': False, 'error': 'Document changed'}
        try:
            return {'success': True, 'data': export_image(self.file_path, src)}
        except (OSError, ValueError) as exc:
            return {'success': False, 'error': str(exc)}

    def selftest_paths(self):
        if '--selftest-integrity' not in sys.argv or not os.environ.get('MDPREVIEW_DATA_DIR'):
            raise PermissionError('Native test mode is disabled')
        return {'html': os.path.join(APP_SUPPORT_DIR, 'export.html'),
                'pdf': os.path.join(APP_SUPPORT_DIR, 'export.pdf')}

    def native_integrity_completed(self, result):
        self.selftest_paths()
        _safe_write_text(os.path.join(APP_SUPPORT_DIR, 'native-result.json'), json.dumps(result))
        if result.get('success'):
            AppHelper.callAfter(lambda: NSApplication.sharedApplication().terminate_(None))
        else:
            os._exit(4)
        return True

    def log_js_error(self, scope, what, stack):
        """仅记录白名单诊断字段；不信任前端传入的文本或原始堆栈。"""
        try:
            safe_scope = scope if isinstance(scope, str) and scope in ('bridge', 'window', 'promise') else 'unknown'
            safe_what = 'unhandled' if safe_scope == 'promise' else 'error'
            if (safe_scope == 'bridge' and isinstance(what, str) and not what.startswith('_')
                    and what in MarkdownAPI.__dict__ and callable(MarkdownAPI.__dict__[what])):
                safe_what = what
            payload = {}
            if isinstance(stack, str) and len(stack) <= 16384:
                try:
                    payload = json.loads(stack)
                except (ValueError, RecursionError):
                    pass
            if not isinstance(payload, dict):
                payload = {}
            types = ('Error', 'TypeError', 'RangeError', 'ReferenceError', 'SyntaxError', 'URIError', 'EvalError', 'AggregateError')
            error_type = payload.get('type') if payload.get('type') in types else 'Error'
            script_pattern = re.compile(r'(?:app\.js|(?:frontend|vendor)/[A-Za-z0-9_./-]+\.js)')
            frames = []
            raw_frames = payload.get('frames', [])
            for frame in raw_frames[:16] if isinstance(raw_frames, list) else []:
                if not isinstance(frame, dict):
                    continue
                file, line, column = frame.get('file'), frame.get('line'), frame.get('column')
                if (isinstance(file, str) and script_pattern.fullmatch(file) is not None and type(line) is int and type(column) is int
                        and 0 <= line <= 9999999 and 0 <= column <= 9999999):
                    frames.append({'file': file, 'line': line, 'column': column})
            message = '[js] ' + json.dumps({'scope': safe_scope, 'what': safe_what,
                                           'type': error_type, 'frames': frames}, separators=(',', ':'))
            logging.error('%s', message.encode('utf-8')[:4096].decode('utf-8', errors='ignore'))
            return True
        except Exception:
            return False

    def startup_ready(self, ms):
        """只记录本进程首次首屏，后续文档加载不混入冷启动。"""
        if _UI_READY.is_set():
            return
        try:
            from mdpreview_core.diagnostics import record
            elapsed = (time.monotonic() - _PROCESS_START) * 1000
            record('startup', milliseconds=elapsed)
            logging.info('[startup] process to first screen: %dms; JS: %dms', int(elapsed), int(ms))
        except Exception:
            pass
        _UI_READY.set()
        if '--update-ready' in sys.argv:
            try:
                marker = sys.argv[sys.argv.index('--update-ready') + 1]
                if os.path.commonpath([os.path.realpath(marker), os.path.realpath(UPDATE_STAGING_DIR)]) == os.path.realpath(UPDATE_STAGING_DIR):
                    _safe_write_text(marker, json.dumps({'pid': os.getpid(), 'version': _get_current_version()}))
            except Exception:
                log_exception('ready marker failed')
        return True

    def get_initial_content(self):
        _set_represented_file(self.window, self.file_path)
        cfg = load_config()
        preferences = self.get_settings()
        page_width = preferences['page_width']
        if preferences['appearance'] != 'system':
            _apply_appearance(preferences['appearance'])
        from mdpreview_core.reading_state import position_key
        position = cfg.get('reading_positions', {}).get(position_key(self.file_path), {}) if self.file_path else {}
        base = {'i18n': _locale_bundle(), 'readingPosition': position, 'pageWidth': page_width, 'settings': preferences, 'fontSize': preferences['font_size'],
                'hash': self.pending_hash, 'isZh': _is_chinese_locale() if preferences['language'] == 'system' else preferences['language'].startswith('zh'),
                'documentId': self.document_id, 'revision': self.revision,
                'recoverableDrafts': [draft for draft in DraftStore(DRAFT_DIR).recoverable()
                                      if draft['documentId'] not in {api.document_id for api in _window_apis.values()}]}
        if self.file_path and os.path.exists(self.file_path):
            try:
                content, encoding = _detect_text_encoding(self.file_path)
                self.read_error = None
                self.recovery_conflict = False
                self.encoding = encoding
                self.file_content = content
                self._record_baseline_stat(self.file_path)
                # Check for a newer draft (unsaved changes from a previous session)
                draft_content = _check_draft_for_file(self.file_path, self.document_id)
                if draft_content is not None:
                    # Draft is newer and different — load it so the user
                    # doesn't lose unsaved work from a crash/quit.
                    self.cached_content = draft_content
                    self.is_dirty = True
                    self.saved_revision = -1
                    record = DraftStore(DRAFT_DIR).read(self.file_path, self.document_id)
                    if record and record.get('baselineHash'):
                        self.recovery_conflict = record['baselineHash'] != hashlib.sha256(content.encode('utf-8')).hexdigest()
                    add_recent_file(self.file_path)
                    return {**base, 'path': self.file_path, 'content': draft_content,
                            'encoding': encoding, 'draftRecovered': True, 'externalConflict': self.recovery_conflict}
                self.cached_content = content
                self.is_dirty = False
                self.saved_revision = self.revision
                add_recent_file(self.file_path)
                return {**base, 'path': self.file_path, 'content': content, 'encoding': encoding}
            except Exception as e:
                log_exception('read file failed')
                self.read_error = str(e)
                return {**base, 'path': self.file_path, 'content': '', 'readError': str(e), 'encoding': self.encoding}
        else:
            return {**base, 'path': 'Untitled.md', 'content': self.cached_content if self.is_dirty else '', 'encoding': self.encoding,
                    'draftRecovered': self.is_dirty}

    def store_content(self, content, revision=None, document_id=None):
        with self._session_lock:
            if document_id and document_id != self.document_id:
                return {'success': False, 'stale': True}
            revision = self.revision + 1 if revision is None else int(revision)
            if revision < self.revision:
                return {'success': False, 'stale': True, 'revision': self.revision}
            self.revision = revision
            self.cached_content = content
            self.is_dirty = revision > self.saved_revision or content != self.file_content
            if self.is_dirty and not _write_draft(self.file_path, content, self.document_id, revision, hashlib.sha256(self.file_content.encode('utf-8')).hexdigest()):
                return {'success': False, 'error': 'draft-write-failed'}
            return {'success': True, 'revision': revision, 'documentId': self.document_id}

    def discard_draft(self):
        with self._session_lock:
            _remove_draft(self.file_path, self.document_id)
            self.is_dirty = False
        return True

    def recover_untitled(self, document_id):
        with self._session_lock:
            if not self.is_untitled or self.is_dirty:
                return {'success': False, 'error': 'Close or save the current document first'}
            if any(api is not self and api.document_id == document_id for api in _window_apis.values()):
                return {'success': False, 'error': 'This draft is already open'}
            record = DraftStore(DRAFT_DIR).read(None, document_id)
            if not record:
                return {'success': False, 'error': 'Draft not found'}
            self.document_id = document_id
            self.revision = record['revision']
            self.saved_revision = -1
            self.cached_content = record['content']
            self.is_dirty = True
            return {'success': True, 'data': self.get_initial_content()}

    def set_dirty(self, dirty, revision=None, document_id=None):
        with self._session_lock:
            if document_id and document_id != self.document_id:
                return False
            if revision is not None:
                if int(revision) < self.revision:
                    return False
                self.revision = int(revision)
                if not dirty and self.revision > self.saved_revision:
                    # Only save_file is allowed to acknowledge a revision.
                    return False
            self.is_dirty = bool(dirty)
            try:
                if self.window:
                    name = os.path.basename(self.file_path) if self.file_path else 'Untitled.md'
                    self.window.set_title(_edited_title(name, self.is_dirty))
                    _set_represented_file(self.window, self.file_path)
            except Exception:
                log_exception('set dirty title failed')
            return True

    def read_clipboard(self):
        """Read the best available clipboard flavor for 'Paste as Markdown'.

        A copy operation normally puts several flavors of the same content on
        the pasteboard. Priority: text/markdown (zero-loss) > HTML (convert
        via turndown) > plain text (insert as-is). RTF-only content (e.g. some
        native apps) intentionally falls back to plain text in v1.

        Called from JS on paste; the pywebview JS bridge runs on a background
        thread, and reading the general pasteboard there is safe on modern
        macOS. Returns {'format': 'markdown'|'html'|'text'|'none', 'content': str,
        'plain': str}. `plain` is the best plain-text flavor, included so JS can
        tell rich HTML/Markdown apart from an app's plain-text HTML wrapper.
        """
        try:
            from AppKit import NSPasteboard
        except Exception:
            return {'format': 'none', 'content': '', 'plain': ''}
        try:
            pb = NSPasteboard.generalPasteboard()
            types = [str(t) for t in (pb.types() or [])]
            if not types:
                return {'format': 'none', 'content': '', 'plain': ''}

            def _get(t):
                val = pb.stringForType_(t)
                return str(val) if val is not None else ''

            plain = ''
            for t in ('public.utf8-plain-text', 'public.plain-text', 'public.text', 'NSStringPboardType'):
                if t in types:
                    plain = _get(t)
                    if plain:
                        break

            for t in ('text/markdown', 'public.markdown', 'net.daringfireball.markdown'):
                if t in types and _get(t):
                    return {'format': 'markdown', 'content': _get(t), 'plain': plain}
            for t in ('public.html', 'text/html', 'com.microsoft.word.html'):
                if t in types and _get(t):
                    return {'format': 'html', 'content': _get(t), 'plain': plain}
            if plain:
                return {'format': 'text', 'content': plain, 'plain': plain}
            return {'format': 'none', 'content': '', 'plain': ''}
        except Exception:
            log_exception('read clipboard failed')
            return {'format': 'none', 'content': '', 'plain': ''}

    def _cancel_document_output(self):
        if self._output_completion is not None:
            self._output_completion.close()
        self._reload_candidate = None

    def reset_to_untitled(self):
        """Turn the current window into a blank Untitled document without closing it.

        Used when the user closes the last open document window but is not
        quitting the app. The window stays alive as a blank document so Finder
        double-click and Dock reopen can reuse/create windows without a cold
        start.
        """
        try:
            self._cancel_document_output()
            from mdpreview_core.watcher import watcher
            watcher.remove(id(self))
            if self.file_path:
                with _state_lock:
                    _opened_files.discard(os.path.abspath(self.file_path))
            self.document_id = str(uuid.uuid4())
            self.pending_hash = ''
            self.revision = 0
            self.saved_revision = 0
            self.encoding = 'utf-8'
            self.read_error = None
            self.recovery_conflict = False
            self.file_path = None
            self.is_untitled = True
            self.is_dirty = False
            self.cached_content = ''
            self.file_content = ''
            self.close_confirmed = False
            if self.window:
                self.window.set_title('Untitled.md')
                _set_represented_file(self.window, None)
        except Exception:
            log_exception('reset to untitled failed')
        return True

    def _has_external_save_conflict(self, path):
        if not path or self.is_untitled or not self.file_path:
            return False
        if os.path.realpath(path) != os.path.realpath(self.file_path) or not os.path.exists(path):
            return False
        if self.recovery_conflict:
            return True
        # mtime/size are not proof of equality (sync tools may preserve both).
        disk_content, _ = _detect_text_encoding(path)
        return disk_content != self.file_content

    def save_file(self, path, content, force=False, revision=None, document_id=None):
        with self._save_lock:
            try:
                with self._session_lock:
                    identity = self.document_id
                    if document_id and document_id != identity:
                        return {'success': False, 'stale': True, 'error': 'Document changed'}
                    save_revision = self.revision if revision is None else int(revision)
                    if save_revision < self.saved_revision:
                        return {'success': False, 'stale': True, 'error': 'Older save snapshot'}
                    previous_path = self.file_path
                    if previous_path and not self.is_untitled and os.path.realpath(path) == os.path.realpath(previous_path) and not os.path.exists(path):
                        return {'success': False, 'deleted': True, 'error': 'use-save-as'}
                    if self.read_error and previous_path and os.path.realpath(path) == os.path.realpath(previous_path):
                        return {'success': False, 'error': 'Original file could not be read; use Save As to a new path'}
                    encoding = self.encoding or 'utf-8'
                    if not force and self._has_external_save_conflict(path):
                        return {'success': False, 'conflict': True, 'path': path,
                                'message': 'The file has changed on disk.'}
                _safe_write_text(path, content, encoding=encoding)
                with self._session_lock:
                    if identity != self.document_id:
                        return {'success': False, 'stale': True, 'error': 'Document changed during save'}
                    self.file_path = path
                    self.file_content = content
                    self.saved_revision = save_revision
                    if self.revision <= save_revision:
                        self.revision = save_revision
                        self.cached_content = content
                    self.is_dirty = self.revision > save_revision or self.cached_content != content
                    self.is_untitled = False
                    self.recovery_conflict = False
                    self.deleted_on_disk = False
                    self._record_baseline_stat(path)
                    _remove_draft(previous_path, identity)
                    if previous_path != path:
                        _remove_draft(path, identity)
                    if self.is_dirty:
                        _write_draft(path, self.cached_content, identity, self.revision, hashlib.sha256(content.encode('utf-8')).hexdigest())
                    with _state_lock:
                        if previous_path: _opened_files.discard(os.path.abspath(previous_path))
                        _opened_files.add(os.path.abspath(path))
                add_recent_file(path)
                _remember_save_directory(path)
                return {'success': True, 'encoding': encoding, 'revision': save_revision,
                        'documentId': identity, 'dirty': self.is_dirty}
            except Exception as exc:
                log_exception('save file failed')
                return {'success': False, 'error': str(exc)}

    def save_as_choose(self, default_name=''):
        """Save As with a native format popup (md/html/pdf/txt).

        Returns {'success': True, 'path': ..., 'format': 'md'|'html'|'pdf'|'txt'}
        or {'success': False, 'cancelled': True}. The caller (JS) decides the
        content per format and writes it via export_as_write.
        """
        if not HAS_COCOA:
            return {'success': False, 'error': 'Cocoa not available'}
        if not _format_panel_lock.acquire(blocking=False):
            # A save/export panel is already up — never stack a second modal.
            return {'success': False, 'cancelled': True}
        try:
            base = os.path.splitext(os.path.basename(default_name or 'Untitled'))[0] or 'Untitled'
            formats = [
                (_t('Markdown (.md)', 'Markdown (.md)'), 'md'),
                (_t('Plain Text (.txt)', '纯文本 (.txt)'), 'txt'),
                (_t('Web Page (.html)', '网页 (.html)'), 'html'),
                (_t('Word Document (.docx)', 'Word 文档 (.docx)'), 'docx'),
                (_t('PNG Image (.png)', 'PNG 图片 (.png)'), 'png'),
                (_t('PDF', 'PDF'), 'pdf'),
            ]
            holder = {}
            _run_format_panel(holder, base, formats, _t('Save', '保存'))
            if holder.get('cancelled'):
                return {'success': False, 'cancelled': True}
            if 'error' in holder:
                return {'success': False, 'error': holder['error']}
            return {'success': True, 'path': holder['path'], 'format': holder.get('format', 'md')}
        except Exception as e:
            log_exception('save as choose failed')
            return {'success': False, 'error': str(e)}
        finally:
            _format_panel_lock.release()

    def export_as_choose(self, default_name=''):
        """Export As with a native format popup (md/html/pdf/txt/docx/png)."""
        if not HAS_COCOA:
            return {'success': False, 'error': 'Cocoa not available'}
        if not _format_panel_lock.acquire(blocking=False):
            # A save/export panel is already up — never stack a second modal.
            return {'success': False, 'cancelled': True}
        try:
            base = os.path.splitext(os.path.basename(default_name or 'Untitled'))[0] or 'Untitled'
            formats = [
                (_t('Web Page (.html)', '网页 (.html)'), 'html'),
                (_t('Word Document (.docx)', 'Word 文档 (.docx)'), 'docx'),
                (_t('PNG Image (.png)', 'PNG 图片 (.png)'), 'png'),
                (_t('PDF', 'PDF'), 'pdf'),
                (_t('Plain Text (.txt)', '纯文本 (.txt)'), 'txt'),
                (_t('Markdown Source (.md)', 'Markdown 源文件 (.md)'), 'md'),
            ]
            holder = {}
            _run_format_panel(holder, base, formats, _t('Export As', '导出为'), _t('Export As:', '导出为：'))
            if holder.get('cancelled'):
                return {'success': False, 'cancelled': True}
            if 'error' in holder:
                return {'success': False, 'error': holder['error']}
            return {'success': True, 'path': holder['path'], 'format': holder.get('format', 'html')}
        except Exception as e:
            log_exception('export as choose failed')
            return {'success': False, 'error': str(e)}
        finally:
            _format_panel_lock.release()

    def set_clipboard_rich(self, html, plain):
        from mdpreview_core.clipboard import set_rich
        return set_rich(html, plain)

    def get_math_export_css(self, families):
        import base64
        import re
        if not isinstance(families, list) or len(families) > 32 or any(not isinstance(f, str) or not re.fullmatch(r'KaTeX_(?:Size[1-4]|[A-Za-z]+)', f) for f in families):
            raise ValueError('invalid-math-fonts')
        with open(get_resource_path('vendor/katex/katex.min.css'), encoding='utf-8') as stream:
            css = stream.read()
        def embed(match):
            block = match.group(0)
            family = re.search(r'font-family\s*:\s*[\"\']?(KaTeX_(?:Size[1-4]|[A-Za-z]+))', block)
            if not family or family.group(1) not in families:
                return ''
            font = re.search(r'url\([\"\']?fonts/([A-Za-z0-9_-]+\.woff2)[\"\']?\)', block)
            if not font:
                raise ValueError('missing-math-font')
            with open(get_resource_path('vendor/katex/fonts/' + font.group(1)), 'rb') as stream:
                data = base64.b64encode(stream.read()).decode('ascii')
            return re.sub(r'src\s*:[^;}]+', 'src:url(data:font/woff2;base64,' + data + ') format(\"woff2\")', block)
        return re.sub(r'@font-face\s*\{[^}]+\}', embed, css)

    def get_export_css(self):
        with open(get_resource_path('VERSION'), encoding='utf-8') as stream:
            version = stream.read().strip()
        chunks = []
        for name in ('tokens', 'content', 'print'):
            with open(get_resource_path('css/' + name + '.css'), encoding='utf-8') as stream:
                chunks.append(stream.read())
        return {'css': '\n'.join(chunks), 'version': version}

    def get_output_settings(self):
        from mdpreview_core.export.settings import defaults, validate
        with _config_lock:
            values = defaults()
            saved = load_config().get('output', {})
            if isinstance(saved, dict):
                for key, value in saved.items():
                    if validate({key: value}):
                        values[key] = value
            return values

    def set_output_settings(self, options):
        from mdpreview_core.export.settings import validate
        if not validate(options):
            return {'success': False, 'error': 'invalid-output-options'}
        with _config_lock:
            values = self.get_output_settings()
            values.update(options)
            update_config({'output': values})
            return {'success': load_config().get('output') == values}

    def print_document(self, options=None):
        from mdpreview_core.export import print_engine
        if not self._output_lock.acquire(blocking=False):
            return {'success': False, 'error': 'output-busy'}
        state = print_engine.Completion()
        self._output_completion = state
        options = options or self.get_output_settings()
        def start():
            if state.result is not None:
                return
            try:
                import webview.platforms.cocoa as cocoa_mod
                bv = cocoa_mod.BrowserView.instances.get(getattr(self.window, 'uid', None))
                if bv is None:
                    state.finish(False, 'closed')
                    return
                info = print_engine.make_print_info(options.get('paper', 'auto'), options.get('margins', 'normal'))
                print_engine.run(bv.webview, bv.window, info, True, state.finish)
            except Exception:
                state.finish(False, 'native-print-failed')
        try:
            AppHelper.callAfter(start)
            return state.wait()
        finally:
            self._output_completion = None
            self._output_lock.release()

    def _no_clobber_output(self):
        return getattr(self, '_headless_lifecycle', None) is not None

    @contextmanager
    def _export_commit_guard(self, completion=None):
        lifecycle = getattr(self, '_headless_lifecycle', None)
        with lifecycle.commit_guard() if lifecycle else nullcontext():
            with completion.commit_guard() if completion else nullcontext():
                yield

    def _export_paged_pdf(self, path, page):
        from mdpreview_core.export import print_engine, pdf_post
        if not self._output_lock.acquire(blocking=False):
            return {'success': False, 'error': 'output-busy'}
        state = print_engine.Completion()
        self._output_completion = state
        temporary = None
        options = (page or {}).get('options') or self.get_output_settings()
        def start():
            if state.result is not None:
                return
            try:
                import webview.platforms.cocoa as cocoa_mod
                bv = cocoa_mod.BrowserView.instances.get(getattr(self.window, 'uid', None))
                if bv is None:
                    state.finish(False, 'closed')
                    return
                info = print_engine.make_print_info(options.get('paper', 'auto'), options.get('margins', 'normal'), temporary)
                def done(success):
                    if not state.finish(success) and os.path.exists(temporary):
                        os.unlink(temporary)
                print_engine.run(bv.webview, bv.window, info, False, done)
            except Exception:
                state.finish(False, 'pdf-generation-failed')
        try:
            fd, temporary = tempfile.mkstemp(suffix='.pdf')
            os.close(fd)
            AppHelper.callAfter(start)
            result = state.wait(600)
            if result is None:
                state.finish(False, 'timeout')
                return state.result
            if not result['success']:
                return result
            meta = dict((page or {}).get('meta') or {})
            meta['pageNumbers'] = options.get('page_numbers', True)
            pdf_post.finalize(temporary, path, meta, lambda: self._export_commit_guard(state), no_clobber=self._no_clobber_output())
            _remember_save_directory(path)
            return {'success': True, 'path': path}
        except Exception:
            return {'success': False, 'error': 'pdf-write-failed'}
        finally:
            try:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
            finally:
                self._output_completion = None
                self._output_lock.release()

    def export_as_write(self, path, fmt, content='', page=None):
        """Write the exported document. md/html/txt are written as text; pdf is
        generated from the current WKWebView render (async). `page` is an
        optional {width, height} dict (CSS px) telling createPDF how much of
        the document to capture — without it only the visible viewport is
        printed."""
        if not HAS_COCOA:
            return {'success': False, 'error': 'Cocoa not available'}
        try:
            if fmt == 'pdf' and ((page or {}).get('options') or self.get_output_settings()).get('pdf_layout', 'paged') != 'continuous':
                return self._export_paged_pdf(path, page)
            if fmt in ('pdf', 'png'):
                from PyObjCTools import AppHelper
                from WebKit import WKPDFConfiguration
                from mdpreview_core.export.print_engine import Completion
                if not self._output_lock.acquire(blocking=False):
                    return {'success': False, 'error': 'output-busy'}
                result_holder = {}
                completed = Completion()
                self._output_completion = completed

                def _run_pdf():
                    if completed.result is not None:
                        return
                    try:
                        import webview.platforms.cocoa as cocoa_mod
                        bv = cocoa_mod.BrowserView.instances.get(getattr(self.window, 'uid', None))
                        webview_native = bv.webview if bv is not None else None
                        if webview_native is None:
                            result_holder['error'] = 'No webview available'
                            completed.finish(False, 'closed')
                            return
                        config = WKPDFConfiguration.alloc().init()
                        if page:
                            w = int(page.get('width') or 0)
                            h = int(page.get('height') or 0)
                            if w > 0 and h > 0:
                                from AppKit import NSMakeRect
                                config.setRect_(NSMakeRect(float(page.get('x') or 0), float(page.get('y') or 0), w, h))

                        def handler(data, error):
                            try:
                                if error is not None:
                                    result_holder['error'] = str(error)
                                    return
                                if data is None or len(data) == 0:
                                    result_holder['error'] = 'Empty PDF data'
                                    return
                                if completed.result is None:
                                    result_holder['data'] = bytes(data)
                            except Exception as e:
                                result_holder['error'] = str(e)
                            finally:
                                completed.finish('data' in result_holder, 'pdf-generation-failed')

                        webview_native.createPDFWithConfiguration_completionHandler_(config, handler)
                    except Exception:
                        completed.finish(False, 'pdf-generation-failed')

                try:
                    AppHelper.callAfter(_run_pdf)
                    result = completed.wait(600)
                    if result is None:
                        completed.finish(False, 'timeout')
                        return completed.result
                    if not result['success']:
                        return result
                    if fmt == 'png':
                        from mdpreview_core.export import snapshot
                        paths = snapshot.render(result_holder['data'], path, commit_guard=lambda: self._export_commit_guard(completed), no_clobber=self._no_clobber_output())
                        _remember_save_directory(path)
                        return {'success': True, 'path': paths[0], 'paths': paths, 'split': len(paths) > 1}
                    with tempfile.TemporaryDirectory() as directory:
                        source = os.path.join(directory, 'source.pdf')
                        converted = os.path.join(directory, 'continuous.pdf')
                        with open(source, 'wb') as stream:
                            stream.write(result_holder['data'])
                        count = _pdf_to_a4_longpage(source, converted)
                        from mdpreview_core.export import pdf_post
                        meta = dict((page or {}).get('meta') or {})
                        meta['pageNumbers'] = False
                        pdf_post.finalize(converted, path, meta, lambda: self._export_commit_guard(completed), no_clobber=self._no_clobber_output())
                    _remember_save_directory(path)
                    return {'success': True, 'path': path, 'pages': count, 'split': count > 1}
                finally:
                    self._output_completion = None
                    self._output_lock.release()

            if fmt == 'docx':
                # JS produces base64 payloads for these binary formats.
                import base64
                try:
                    payload = content
                    if payload.startswith('data:'):
                        payload = payload.split(',', 1)[1]
                    raw = base64.b64decode(payload)
                except Exception as e:
                    log_exception('export base64 decode failed')
                    return {'success': False, 'error': 'Invalid payload: %s' % str(e)}
                if len(raw) == 0:
                    return {'success': False, 'error': 'Empty file data'}
                with self._export_commit_guard():
                    (atomic_create if self._no_clobber_output() else atomic_write)(path, raw)
                _remember_save_directory(path)
                return {'success': True, 'path': path}

            with self._export_commit_guard():
                (atomic_create if self._no_clobber_output() else atomic_write)(path, content.encode('utf-8'))
            _remember_save_directory(path)
            return {'success': True, 'path': path}
        except Exception as e:
            log_exception('export as write failed')
            return {'success': False, 'error': str(e)}

    def save_reading_position(self, position, document_id=None):
        from mdpreview_core.reading_state import remember
        if document_id and document_id != self.document_id:
            return False
        if self.is_untitled or not self.file_path:
            return False
        try:
            with _config_lock:
                values = load_config().get('reading_positions', {})
                update_config({'reading_positions': remember(values, self.file_path, position)})
            return True
        except (ValueError, OSError):
            return False

    def _external_change(self, path, stamp):
        with self._save_lock, self._session_lock:
            if self.file_path != path or not self.window or self.close_confirmed:
                return
            from mdpreview_core.watcher import watcher
            if watcher.stamp(path) != stamp:
                return
            if stamp == (self.baseline_mtime_ns, self.baseline_size):
                return
            self.recovery_conflict = True
            identity = self.document_id
            if stamp is None:
                self.deleted_on_disk = True
                window = self.window
                if HAS_COCOA:
                    AppHelper.callAfter(lambda: window.set_title(os.path.basename(path) + _t(' (deleted)', '（已删除）')))
        _dispatch_js_to(self.window, 'handleExternalChange('+json.dumps(identity)+','+json.dumps(stamp is None)+')')

    def reload_from_disk(self, document_id, revision):
        with self._save_lock, self._session_lock:
            if document_id != self.document_id or self.is_dirty or revision != self.revision:
                return {'success': False, 'conflict': True}
            if not self.file_path or not os.path.isfile(self.file_path):
                return {'success': False, 'deleted': True}
            try:
                before = os.stat(self.file_path)
                content, encoding = _detect_text_encoding(self.file_path)
                after = os.stat(self.file_path)
                stamp = (after.st_mtime_ns, after.st_size, after.st_ino)
                if stamp != (before.st_mtime_ns, before.st_size, before.st_ino):
                    return {'success': False, 'conflict': True}
                candidate = {'id': uuid.uuid4().hex, 'document': document_id, 'revision': revision,
                             'content': content, 'encoding': encoding, 'stamp': stamp}
                self._reload_candidate = candidate
                return {'success': True, 'content': content, 'documentId': self.document_id,
                        'candidateId': candidate['id']}
            except (OSError, UnicodeError):
                return {'success': False, 'error': 'reload-failed'}

    def ack_reload_from_disk(self, candidate_id, document_id, revision):
        with self._save_lock, self._session_lock:
            candidate = getattr(self, '_reload_candidate', None)
            if (not candidate or candidate['id'] != candidate_id or document_id != self.document_id
                    or candidate['document'] != document_id or candidate['revision'] != revision
                    or self.revision != revision or self.is_dirty):
                return {'success': False, 'conflict': True}
            self._reload_candidate = None
            self.recovery_conflict = True
            try:
                stamp = os.stat(self.file_path)
                current, encoding = _detect_text_encoding(self.file_path)
                if ((stamp.st_mtime_ns, stamp.st_size, stamp.st_ino) != candidate['stamp']
                        or current != candidate['content']):
                    return {'success': False, 'conflict': True}
                self.file_content = self.cached_content = current
                self.encoding = encoding
                self.baseline_mtime_ns, self.baseline_size = candidate['stamp'][:2]
                self.recovery_conflict = False
                self.deleted_on_disk = False
                return {'success': True}
            except (OSError, UnicodeError):
                return {'success': False, 'conflict': True}

    def save_image_asset(self, doc_path, base64_data, ext, suggested_name='', document_id=None):
        from mdpreview_core.images import save_asset
        with self._session_lock:
            if document_id and document_id != self.document_id:
                return {'success': False, 'error': 'stale-document'}
            if self.is_untitled or not self.file_path:
                return {'success': False, 'need_save': True}
            if not isinstance(doc_path, str) or os.path.realpath(doc_path) != os.path.realpath(self.file_path):
                return {'success': False, 'error': 'invalid-document'}
            try:
                return save_asset(self.file_path, base64_data, ext)
            except (OSError, ValueError):
                return {'success': False, 'error': 'image-save-failed'}

    def get_credits(self):
        from pathlib import Path
        return Path(get_resource_path('THIRD_PARTY_NOTICES.md')).read_text(encoding='utf-8')

    def get_diagnostics(self):
        from mdpreview_core.watcher import watcher
        return {'version': self.get_export_css()['version'], 'python': sys.version.split()[0],
                'cocoa': HAS_COCOA, 'windows': len(_window_apis),
                'watcher': bool(watcher.thread and watcher.thread.is_alive()),
                'auto_update': self.get_settings()['auto_update']}

    def report_issue(self):
        from mdpreview_core.diagnostics import issue_url
        return self.open_external_link(issue_url(_get_current_version()))

    def export_diagnostics(self):
        if not HAS_COCOA:
            return {'success': False, 'error': 'native-unavailable'}
        from AppKit import NSSavePanel, NSOKButton
        from Foundation import NSThread
        from PyObjCTools import AppHelper
        from mdpreview_core.diagnostics import archive
        selected = {}
        completed = threading.Event()

        def choose():
            try:
                panel = NSSavePanel.savePanel()
                panel.setTitle_(_t('Export Diagnostics', '导出诊断信息'))
                panel.setNameFieldStringValue_('mdPreview-diagnostics.zip')
                panel.setAllowedFileTypes_(['zip'])
                if panel.runModal() == NSOKButton:
                    selected['path'] = str(panel.URL().path())
            finally:
                completed.set()
        try:
            if NSThread.isMainThread():
                choose()
            else:
                AppHelper.callAfter(choose)
                completed.wait()
            if 'path' not in selected:
                return {'success': False, 'cancelled': True}
            atomic_write(selected['path'], archive(_get_current_version(), load_config()))
            return {'success': True}
        except Exception:
            return {'success': False, 'error': 'diagnostics-export-failed'}

    def install_cli(self):
        from pathlib import Path
        source = Path(get_resource_path('bin/mdpreview'))
        if not source.is_file():
            return {'success': False, 'error': 'packaged-cli-required'}
        try:
            if not os.access(source, os.X_OK):
                return {'success': False, 'error': 'packaged-cli-not-executable'}
            folder = Path('/usr/local/bin')
            if not folder.is_dir() or not os.access(folder, os.W_OK):
                folder = Path.home() / '.local/bin'
                folder.mkdir(parents=True, exist_ok=True)
            target = folder / 'mdpreview'
            if target.exists() or target.is_symlink():
                return {'success': False, 'error': 'cli-target-exists'}
            target.symlink_to(source)
            return {'success': True, 'path': str(target), 'addToPath': str(folder)}
        except OSError:
            return {'success': False, 'error': 'cli-install-failed'}

    def get_onboarding(self):
        config = load_config()
        version = _get_current_version()
        return {'first': not config.get('onboarded', False), 'version': version,
                'updated': bool(config.get('last_seen_version') and config['last_seen_version'] != version)}

    def acknowledge_onboarding(self):
        update_config({'onboarded': True, 'last_seen_version': _get_current_version()})
        return {'success': True}

    def get_shortcuts(self):
        with open(get_resource_path('frontend/shortcuts.json'), encoding='utf-8') as stream:
            items = json.load(stream)
        try:
            parts = self.get_settings()['toggle_shortcut'].split('+')
            names = {'cmd': 'command', 'alt': 'option', 'shift': 'shift', 'ctrl': 'control'}
            for item in items:
                if item.get('action') == 'toggleView:':
                    item['key'] = parts[-1]
                    item['modifiers'] = [names[x] for x in parts[:-1]]
        except Exception:
            pass
        return items

    def get_example(self):
        with open(get_resource_path('frontend/welcome.json'), encoding='utf-8') as stream:
            examples = json.load(stream)
            return examples.get(_locale_bundle()['locale']) or examples['en']

    def get_release_notes(self):
        import re
        with open(get_resource_path('CHANGELOG.md'), encoding='utf-8') as stream:
            text = stream.read()
        version = _get_current_version()
        match = re.search(r'^## \[?' + re.escape(version) + r'\]?(?:\s[^\n]*)?\n(.*?)(?=^## |\Z)', text, re.M | re.S)
        return {'version': version, 'content': match.group(1).strip() if match else '', 'available': bool(match)}

    def get_i18n(self):
        return _locale_bundle()

    def get_settings(self):
        from mdpreview_core.settings import settings
        return settings(load_config())

    def set_settings(self, patch):
        from mdpreview_core.settings import validated
        try:
            patch = validated(patch)
        except ValueError:
            return {'success': False, 'error': 'invalid-settings'}
        with _config_lock:
            values = self.get_settings()
            values.update(patch)
            update_config({'settings': values})
            if 'appearance' in patch:
                _apply_appearance(values['appearance'])
            if 'toggle_shortcut' in patch:
                try:
                    from PyObjCTools import AppHelper
                    AppHelper.callAfter(_apply_toggle_shortcut, values['toggle_shortcut'])
                except Exception:
                    pass
            return {'success': load_config().get('settings') == values, 'settings': values}

    def save_font_size(self, size):
        return self.set_settings({'font_size': size})

    def open_linked_document(self, path, hash='', same_window=False):
        if not isinstance(path, str) or not isinstance(hash, str) or type(same_window) is not bool:
            return {'success': False, 'error': 'invalid-link'}
        if not os.path.isabs(path):
            if self.is_untitled or not self.file_path:
                return {'success': False, 'error': 'need-save'}
            path = os.path.join(os.path.dirname(self.file_path), path)
        path = os.path.realpath(path)
        if not os.path.exists(path):
            return {'success': False, 'error': 'not-found'}
        if path.lower().endswith(('.md', '.markdown', '.mdown', '.mkd', '.mkdown', '.txt')) and os.path.isfile(path):
            if same_window and self.is_dirty:
                return {'success': False, 'error': 'dirty-document'}
            if same_window and self.window:
                update_main_window(self.window, self, path, hash)
            else:
                _pending_link_hashes[path] = hash
                handle_opened_file(path)
                for api in list(_window_apis.values()):
                    if api.file_path and os.path.realpath(api.file_path) == path:
                        api.pending_hash = hash
                        if id(api.window) in _windows_js_ready:
                            _dispatch_js_to(api.window, 'scrollToHash('+json.dumps(hash)+')')
            return {'success': True}
        if not HAS_COCOA:
            return {'success': False, 'error': 'native-confirmation-unavailable'}
        result = {}; done = threading.Event()
        def confirm():
            try:
                from AppKit import NSAlert, NSAlertFirstButtonReturn, NSWorkspace
                from Foundation import NSURL
                alert = NSAlert.alloc().init()
                alert.setMessageText_(_t('Open this file with the default application?', '使用系统默认程序打开此文件？'))
                alert.setInformativeText_(path)
                alert.addButtonWithTitle_(_t('Cancel', '取消')); alert.addButtonWithTitle_(_t('Open', '打开'))
                if alert.runModal() == NSAlertFirstButtonReturn + 1:
                    result['success'] = bool(NSWorkspace.sharedWorkspace().openURL_(NSURL.fileURLWithPath_(path)))
                else:
                    result.update(success=False, cancelled=True)
            except Exception:
                result.update(success=False, error='open-link-failed')
            finally:
                done.set()
        from Foundation import NSThread
        if NSThread.isMainThread(): confirm()
        else: AppHelper.callAfter(confirm); done.wait()
        return result

    def save_page_width(self, width):
        """Persist the user's preferred page width"""
        self.set_settings({'page_width': max(360, min(2016, int(width)))})
        return True

    def open_file_dialog(self):
        """Show a native Open panel and open the selected Markdown file."""
        if not HAS_COCOA:
            return {'success': False, 'error': 'Cocoa not available'}
        try:
            from AppKit import NSOpenPanel, NSOKButton
            from PyObjCTools import AppHelper

            result_holder = {}
            completed = threading.Event()

            def _run_panel():
                try:
                    panel = NSOpenPanel.openPanel()
                    panel.setTitle_(_t('Open File', '打开文件'))
                    panel.setCanChooseFiles_(True)
                    panel.setCanChooseDirectories_(False)
                    panel.setAllowsMultipleSelection_(True)
                    panel.setAllowedFileTypes_(['md', 'markdown', 'mdown', 'mkd', 'mkdown', 'txt'])
                    response = panel.runModal()
                    if response != NSOKButton:
                        result_holder['cancelled'] = True
                        return
                    urls = panel.URLs()
                    paths = []
                    for i in range(urls.count()):
                        paths.append(urls.objectAtIndex_(i).path())
                    result_holder['paths'] = paths
                except Exception as e:
                    result_holder['error'] = str(e)
                finally:
                    completed.set()

            # NSOpenPanel 必须在主线程运行，等待用户选择或取消。
            AppHelper.callAfter(_run_panel)
            completed.wait()

            if 'error' in result_holder:
                log_exception('open file dialog failed')
                return {'success': False, 'error': result_holder['error']}
            if result_holder.get('cancelled'):
                return {'success': False, 'cancelled': True}

            opened = []
            for path in result_holder.get('paths', []):
                handle_opened_file(path, _main_window_ref, _main_api_ref)
                opened.append(path)
            return {'success': True, 'paths': opened}
        except Exception as e:
            log_exception('open file dialog failed')
            return {'success': False, 'error': str(e)}

    def close_window(self):
        """Handle File > Close / Cmd+W (clean path — JS prompts first when dirty).

        For the last real window we keep the app resident by blanking + hiding
        it; otherwise the window is destroyed through the normal closing flow.
        """
        try:
            window = self.window
            if window is None:
                return {'success': False}
            if self.is_dirty and not self.close_confirmed:
                _dispatch_js_to(window, 'promptBeforeClose(true)')
                return {'success': False, 'confirmation_required': True}
            self._cancel_document_output()
            if _is_last_window(window):
                _hide_last_window(window, self)
                return {'success': True}
            if not _allow_close(window):
                return {'success': False}
            try:
                window.destroy()
            except Exception:
                pass
            return {'success': True}
        except Exception:
            log_exception('close window failed')
            return {'success': False}

    def force_close_window(self, discard=False):
        """Force-close the window (post save-prompt / quit). discard=True drops
        unsaved changes without prompting again."""
        try:
            if discard:
                self.is_dirty = False
                self.close_confirmed = True
                try:
                    self.cached_content = self.file_content or ''
                except Exception:
                    pass
                try:
                    _remove_draft(self.file_path, self.document_id)
                except Exception:
                    pass
            return self.close_window()
        except Exception:
            log_exception('force close window failed')
            return {'success': False}

    def native_save_prompt(self):
        """TextEdit-style keep/save prompt, two-step flow.

        Step 1: a simple native NSAlert (sheet) asking whether to save, with
        vertical buttons Delete (red) / Save / Cancel (top to bottom).
        Step 2: if the user chooses Save, a document that already has a path
        is saved in place immediately; only untitled documents open the
        standard NSSavePanel to pick a name & location.
        Returns {'action': 'save', 'path': ...}, {'action': 'delete'} or
        {'action': 'cancel'}.
        """
        if not HAS_COCOA:
            return {'action': 'cancel'}
        try:
            from AppKit import (NSAlert, NSSavePanel, NSColor, NSOKButton)
            from Foundation import NSURL
            from PyObjCTools import AppHelper

            result_holder = {}
            completed = threading.Event()
            is_untitled = self.is_untitled or not self.file_path
            if is_untitled:
                base_name = 'untitled'
                base_dir = _default_save_directory()
                initial_name = 'untitled.md'
            else:
                base_name = os.path.splitext(os.path.basename(self.file_path or ''))[0] or 'untitled'

            def _run_save_panel():
                try:
                    panel = NSSavePanel.savePanel()
                    panel.setTitle_(_t('Save', '保存'))
                    panel.setCanCreateDirectories_(True)
                    panel.setDirectoryURL_(NSURL.fileURLWithPath_(base_dir))
                    panel.setNameFieldStringValue_(initial_name)
                    panel.setAllowedFileTypes_(['md'])
                    if panel.runModal() == NSOKButton:
                        url = panel.URL()
                        if url:
                            result_holder['path'] = url.path()
                            result_holder['action'] = 'save'
                            return
                    result_holder['action'] = 'cancel'
                except Exception:
                    log_exception('native save panel failed')
                    result_holder['action'] = 'cancel'
                finally:
                    completed.set()

            def handler(code):
                try:
                    code = int(code)
                    if code == 1000:  # Delete
                        result_holder['action'] = 'delete'
                    elif code == 1002:  # Save
                        if is_untitled:
                            # Untitled document: ask for a name & location.
                            AppHelper.callAfter(_run_save_panel)
                        else:
                            # Already has a path: save in place, no Save As panel.
                            result_holder['action'] = 'save'
                            result_holder['path'] = self.file_path
                    else:  # Cancel / Esc
                        result_holder['action'] = 'cancel'
                except Exception:
                    result_holder['action'] = 'cancel'
                finally:
                    if 'action' in result_holder:
                        completed.set()

            def _run():
                try:
                    import webview.platforms.cocoa as cocoa_mod
                    bv = cocoa_mod.BrowserView.instances.get(getattr(self.window, 'uid', None))
                    host = bv.window if bv is not None else None
                    if host is None:
                        from AppKit import NSApp
                        host = NSApp.mainWindow()

                    alert = NSAlert.alloc().init()
                    alert.setMessageText_(
                        (_t('Do you want to save the changes you made to "%s"?',
                           '是否保存对"%s"所做的更改？') % base_name) if not is_untitled else
                        (_t('Do you want to keep this new document "%s"?',
                           '是否保留这个新文档"%s"？') % base_name))
                    alert.setInformativeText_(
                        _t("Your changes will be lost if you don't save them.",
                           '若不保存，您的更改将丢失。'))
                    # Native vertical layout (top to bottom): Delete, Save, Cancel.
                    # Response codes: First=Delete(1000), Second=Cancel(1001),
                    # Third=Save(1002).
                    # "Delete" only fits a brand-new document; for an existing file it
                    # would read as deleting the file itself.
                    alert.addButtonWithTitle_(_t('Delete', '删除') if is_untitled else _t("Don't Save", '不保存'))
                    alert.addButtonWithTitle_(_t('Cancel', '取消'))
                    alert.addButtonWithTitle_(_t('Save', '保存'))
                    buttons = alert.buttons()
                    try:
                        del_btn = buttons.objectAtIndex_(0)
                        del_btn.setHasDestructiveAction_(True)
                        del_btn.setBezelColor_(NSColor.systemRedColor())
                        del_btn.setKeyEquivalent_('')
                        buttons.objectAtIndex_(2).setKeyEquivalent_('\r')  # Save
                    except Exception:
                        pass

                    alert.beginSheetModalForWindow_completionHandler_(host, handler)
                except Exception as e:
                    log_exception('native save alert run failed')
                    result_holder['action'] = 'cancel'
                    result_holder['error'] = str(e)
                    completed.set()

            AppHelper.callAfter(_run)
            completed.wait()
            return result_holder
        except Exception:
            log_exception('native save prompt failed')
            return {'action': 'cancel'}

    def native_conflict_prompt(self, path=''):
        """Native save-conflict alert (sheet): Save Current / Save As / Cancel.

        Shown when the file on disk changed since it was opened or last
        saved. Vertical layout (right to left on macOS): Save Current (red,
        destructive) / Save As / Cancel (default, triggered by Enter).
        Returns {'action': 'overwrite'}, {'action': 'save_as'} or
        {'action': 'cancel'}. The JS side performs the chosen action; Save As
        opens the regular Save-As panel there.
        """
        if not HAS_COCOA:
            return {'action': 'cancel'}
        try:
            from AppKit import NSAlert, NSColor
            from PyObjCTools import AppHelper

            result_holder = {}
            completed = threading.Event()
            name = os.path.basename(path or self.file_path or '') or 'Untitled.md'

            def handler(code):
                try:
                    code = int(code)
                    if code == 1000:  # Save Current (overwrite)
                        result_holder['action'] = 'overwrite'
                    elif code == 1001:  # Save As
                        result_holder['action'] = 'save_as'
                    else:  # Cancel / Esc
                        result_holder['action'] = 'cancel'
                except Exception:
                    result_holder['action'] = 'cancel'
                finally:
                    if 'action' in result_holder:
                        completed.set()

            def _run():
                try:
                    import webview.platforms.cocoa as cocoa_mod
                    bv = cocoa_mod.BrowserView.instances.get(getattr(self.window, 'uid', None))
                    host = bv.window if bv is not None else None
                    if host is None:
                        from AppKit import NSApp
                        host = NSApp.mainWindow()

                    alert = NSAlert.alloc().init()
                    alert.setMessageText_(
                        (_t('The file "%s" has changed on disk since it was opened or last saved.',
                           '文件"%s"自打开或上次保存以来已在磁盘上发生变化。') % name))
                    alert.setInformativeText_(
                        _t('Save Current overwrites the changed file. Save As keeps it untouched and saves this document to a new path.',
                           '「保存当前」将用当前窗口内容覆盖磁盘文件；「另存为」保持磁盘文件不变，将本文档保存到新路径。'))
                    # Response codes follow button order: First=Save Current(1000),
                    # Second=Save As(1001), Third=Cancel(1002).
                    # Colors (right to left): Save Current red/destructive,
                    # Save As blue default (Enter), Cancel plain gray (Esc).
                    alert.addButtonWithTitle_(_t('Save Current', '保存当前'))
                    alert.addButtonWithTitle_(_t('Save As', '另存为'))
                    alert.addButtonWithTitle_(_t('Cancel', '取消'))
                    buttons = alert.buttons()
                    try:
                        del_btn = buttons.objectAtIndex_(0)
                        del_btn.setHasDestructiveAction_(True)
                        del_btn.setBezelColor_(NSColor.systemRedColor())
                        del_btn.setKeyEquivalent_('')
                        buttons.objectAtIndex_(1).setKeyEquivalent_('\r')  # Save As: default (blue)
                        buttons.objectAtIndex_(2).setKeyEquivalent_('')    # Cancel: plain gray
                    except Exception:
                        pass
                    alert.beginSheetModalForWindow_completionHandler_(host, handler)
                except Exception as e:
                    log_exception('native conflict alert run failed')
                    result_holder['action'] = 'cancel'
                    result_holder['error'] = str(e)
                    completed.set()

            AppHelper.callAfter(_run)
            completed.wait()
            return result_holder
        except Exception:
            log_exception('native conflict prompt failed')
            return {'action': 'cancel'}

    def open_external_link(self, url):
        """Open a URL with the system default handler."""
        try:
            import webbrowser
            normalized = ''.join(ch for ch in str(url) if ord(ch) > 32 and ord(ch) != 127)
            if urlsplit(normalized).scheme.lower() not in ('http', 'https', 'mailto', 'tel'):
                return {'success': False, 'error': 'Unsupported link protocol'}
            webbrowser.open(normalized)
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_chrome_color(self):
        """Tells the page how tall the (transparent) title bar is, so its top bar and outline start below the traffic lights.
        AppKit work happens on the main thread; this call only schedules it and returns the last known height."""
        if not HAS_COCOA:
            return {'overlay': False, 'height': 0}
        try:
            from PyObjCTools import AppHelper
            ref = _get_target_window()
            if ref is not None:
                AppHelper.callAfter(_blend_titlebar, ref)
        except Exception:
            pass
        return {'overlay': bool(_TITLEBAR_STATE['overlay']), 'height': _TITLEBAR_STATE['height']}

    def begin_window_drag(self):
        """The page's top bar was grabbed on an empty spot: move the window."""
        if not HAS_COCOA:
            return {'success': False}
        from PyObjCTools import AppHelper
        AppHelper.callAfter(_begin_window_drag)
        return {'success': True}

    def share_document(self, x=None, y=None):
        """Open the Share sheet next to the footer button that asked for it."""
        if not HAS_COCOA:
            return {'success': False}
        from PyObjCTools import AppHelper
        AppHelper.callAfter(_share_active_document, x, y)
        return {'success': True}

    def set_as_default_for_md(self):
        """Register mdPreview as the default handler for .md/.markdown files."""
        if not HAS_COCOA:
            return {'success': False, 'error': 'Cocoa not available'}
        try:
            bundle_id = 'tahoeliu.mdpreview'
            extensions = ['md', 'markdown', 'mdown', 'mkd', 'mkdown']
            utis = [
                'net.daringfireball.markdown',
            ]

            try:
                try:
                    from LaunchServices import (
                        LSSetDefaultRoleHandlerForContentType,
                        LSSetDefaultRoleHandlerForExtension,
                        kLSRolesAll,
                    )
                except Exception:
                    from CoreServices import (
                        LSSetDefaultRoleHandlerForContentType,
                        LSSetDefaultRoleHandlerForExtension,
                        kLSRolesAll,
                    )

                for ext in extensions:
                    LSSetDefaultRoleHandlerForExtension(ext, kLSRolesAll, bundle_id)
                for uti in utis:
                    LSSetDefaultRoleHandlerForContentType(uti, kLSRolesAll, bundle_id)
                return {'success': True, 'method': 'launchservices-api'}
            except Exception as api_error:
                # Some frozen Python environments do not ship the PyObjC
                # LaunchServices/CoreServices bridge modules. Still force the
                # app bundle back into the LaunchServices database so Finder and
                # Open With see the updated CFBundleDocumentTypes metadata.
                import subprocess
                app_path = '/Applications/mdPreview.app'
                lsregister = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'
                result = subprocess.run(
                    [lsregister, '-f', app_path],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    return {
                        'success': False,
                        'error': result.stderr.strip() or str(api_error),
                        'method': 'lsregister',
                    }
                return {
                    'success': True,
                    'method': 'lsregister',
                    'warning': 'Registered the app bundle. If macOS still opens .md elsewhere, choose mdPreview once from Finder > Open With.',
                }
        except Exception as e:
            log_exception('set as default failed')
            return {'success': False, 'error': str(e)}

    def get_app_info(self):
        """Return app metadata (version, etc.) for the About panel."""
        return {'version': _get_current_version()}

    def perform_auto_install(self):
        """Called from JS when user clicks the update bubble."""
        return _perform_auto_install()

    def download_update_with_progress(self, version):
        """Manual update download with progress updates shown in the page."""
        return _manual_download_update_with_progress(version)

    def get_file_properties(self):
        """Return file properties for the Properties dialog"""
        if not self.file_path or not os.path.exists(self.file_path):
            return {
                'name': os.path.basename(self.file_path) if self.file_path else 'Untitled.md',
                'location': '',
                'size': 0,
                'sizeFormatted': '0 B',
                'modified': '',
                'created': '',
                'exists': False,
                'encoding': self.encoding,
            }
        try:
            stat = os.stat(self.file_path)
            size = stat.st_size
            # Format size
            if size < 1024:
                sizeFmt = f'{size} B'
            elif size < 1024 * 1024:
                sizeFmt = f'{size / 1024:.1f} KB'
            else:
                sizeFmt = f'{size / (1024 * 1024):.1f} MB'

            import datetime
            modified = datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            created = datetime.datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')

            return {
                'name': os.path.basename(self.file_path),
                'location': os.path.dirname(self.file_path),
                'size': size,
                'sizeFormatted': sizeFmt,
                'modified': modified,
                'created': created,
                'exists': True,
                'ext': os.path.splitext(self.file_path)[1].lstrip('.'),
                'encoding': self.encoding,
            }
        except Exception:
            log_exception('get file properties failed')
            return {'name': 'Unknown', 'location': '', 'size': 0, 'sizeFormatted': '0 B',
                    'modified': '', 'created': '', 'exists': False, 'encoding': self.encoding}


def get_resource_path(filename):
    """Find resource files — works in dev mode and pyinstaller bundle"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, filename)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, filename)


def load_config():
    try:
        path = CONFIG_FILE if os.path.exists(CONFIG_FILE) else LEGACY_CONFIG_FILE
        if os.path.exists(path):
            with open(path, 'r') as f:
                cfg = json.load(f)
            if path == LEGACY_CONFIG_FILE:
                save_config(cfg)
            return cfg
    except Exception:
        log_exception('load config failed')
    return {}


def save_config(cfg):
    with _config_lock:
        try:
            os.makedirs(APP_SUPPORT_DIR, exist_ok=True)
            _safe_write_text(CONFIG_FILE, json.dumps(cfg))
        except Exception:
            log_exception('save config failed')


def update_config(changes=None, remove=()):
    with _config_lock:
        cfg = load_config()
        cfg.update(changes or {})
        for key in remove:
            cfg.pop(key, None)
        save_config(cfg)
        return cfg


def add_recent_file(path):
    if not path:
        return
    # Serialize the whole read-modify-write so concurrent windows never lose
    # each other's recent-file entries.
    with _config_lock:
        try:
            path = os.path.abspath(path)
            cfg = load_config()
            # Do not preflight historical paths with os.path.exists(). On macOS,
            # merely probing Desktop/Documents/Downloads can trigger a TCC prompt
            # during save, before the user explicitly opens a recent item.
            recent = [p for p in cfg.get('recent_files', []) if p != path]
            recent.insert(0, path)
            cfg['recent_files'] = recent[:10]
            save_config(cfg)
        except Exception:
            log_exception('add recent file failed')


# --- Global state ---
_opened_files = set()
_initial_file_handled = False
_window_apis = {}  # id(pywebview_window) -> MarkdownAPI
_main_window_ref = None
_main_api_ref = None
_active_window_ref = None
_menus_setup = False
_view_menu_setup = False
_file_menu_setup = False
_app_menu_setup = False
_update_menu_item = None
_available_update_version = None
_properties_panel_ref = None
_about_window_ref = None
_window_count = [0]  # list-based counter so it stays mutable inside ObjC callbacks
# Windows that were "closed" by the user but kept alive hidden so the app can
# stay resident without a cold start. Each entry is id(window) -> window.
# Keeping a real (hidden) NSWindow alive is the ONLY reliable way to stay
# resident in pywebview: destroying every window leaves webview.windows empty,
# which makes the next create_window take the fragile 'master' path.
_hidden_windows = {}
WINDOW_OFFSET = 30  # px to offset each new window
WINDOW_BASE_X = 100  # starting position
WINDOW_BASE_Y = 80

# Windows whose JS bridge is fully initialized (pywebview's window.events.loaded
# fired after _pywebviewready). evaluate_js only works reliably after this.
# update_main_window() waits on this instead of blind polling, so a reused
# resident window (already ready) loads a file with ZERO artificial delay,
# while a cold-started window is only delayed by actual page-load time.
_windows_js_ready = set()
WINDOW_JS_READY_TIMEOUT = 6.0  # hard cap for waiting on JS readiness

# Guards for multi-window concurrency: the window-registry collections and the
# config file are shared across threads (bridge threads + UI thread), so every
# read-modify-write must be serialized to avoid lost updates / races.
_state_lock = threading.RLock()
_config_lock = threading.RLock()
# Guards the native save/export panels: only one modal format panel may be up
# at a time. Two overlapping runModal sessions make buttons unresponsive
# (the second panel's clicks get eaten by the first modal session).
_format_panel_lock = threading.Lock()


def _mark_window_js_ready(window):
    try:
        with _state_lock:
            _windows_js_ready.add(id(window))
    except Exception:
        pass


def _subscribe_js_ready(window):
    """Subscribe to pywebview's loaded event (fires when the JS bridge is up)."""
    try:
        window.events.loaded += (lambda: _mark_window_js_ready(window))
    except Exception:
        pass


# ── Quit safety machinery ────────────────────────────────────────────────────
# Root cause of the long-standing "freezes on quit": pywebview's cocoa
# evaluate_js blocks the calling thread forever when the main runloop has
# stopped (after app.stop_ during teardown). pywebview's internal JS-bridge
# result threads are NON-daemon, so Python interpreter shutdown joins them
# forever and the process never exits. Fixes below (see patch_evaluate_js,
# on_window_closing, _start_quit_watchdog).
_QUIT_REQUESTED = threading.Event()  # set only by true app quit paths, not normal window close
QUIT_FORCE_EXIT_DELAY = 1.5          # seconds of "quitting" before force exit
EVALUATE_JS_TIMEOUT = 1.0            # max seconds to wait for a JS round-trip


def _set_active_window(window):
    """Remember the frontmost pywebview window for menu action dispatch."""
    global _active_window_ref
    if window:
        _active_window_ref = window


def _get_target_window():
    """Return the best window target for menu-triggered JavaScript calls."""
    if HAS_COCOA:
        try:
            from AppKit import NSApplication
            import webview.platforms.cocoa as cocoa
            key_window = NSApplication.sharedApplication().keyWindow()
            if key_window:
                for browser in cocoa.BrowserView.instances.values():
                    if browser.window == key_window and id(browser.pywebview_window) in _window_apis:
                        _set_active_window(browser.pywebview_window)
                        return browser.pywebview_window
        except Exception:
            pass
    if _active_window_ref and id(_active_window_ref) in _window_apis:
        return _active_window_ref
    if _main_window_ref and id(_main_window_ref) in _window_apis:
        return _main_window_ref
    for api in list(_window_apis.values()):
        if api.window:
            return api.window
    return None


def _focus_window(window):
    """Show (or unhide) a window and remember it as the active one."""
    try:
        if not window:
            return False
        with _state_lock:
            _hidden_windows.pop(id(window), None)
        window.show()
        _set_active_window(window)
        return True
    except Exception:
        log_exception('focus window failed')
        return False


def _focus_existing_file(file_path):
    target = os.path.abspath(file_path)
    for api in list(_window_apis.values()):
        if api.file_path and os.path.abspath(api.file_path) == target and api.window:
            return _focus_window(api.window)
    return False


def _forget_window(window):
    """Remove a closed window and its file from the app registries."""
    global _active_window_ref, _main_window_ref, _main_api_ref
    with _state_lock:
        api = _window_apis.pop(id(window), None)
        _hidden_windows.pop(id(window), None)
        _windows_js_ready.discard(id(window))
        if api and api.file_path and not api.is_untitled:
            _opened_files.discard(os.path.abspath(api.file_path))
        if _active_window_ref is window:
            _active_window_ref = _main_window_ref if (_main_window_ref and id(_main_window_ref) in _window_apis) else None
        if _main_window_ref is window:
            _main_window_ref = None
            _main_api_ref = None


def _allow_close(window):
    """Allow the close and perform successful-close cleanup."""
    from mdpreview_core.watcher import watcher
    api = _window_apis.get(id(window))
    if api:
        api._cancel_document_output()
        watcher.remove(id(api))
    _forget_window(window)
    return True


def _is_last_window(window):
    """True if this is the only real document window currently open."""
    return len(_window_apis) == 1 and id(window) in _window_apis


def _hide_last_window(window, api):
    """Turn the last window into a hidden blank Untitled document.

    Called when the user closes the last window but is not quitting the app.
    Instead of destroying the window (which leaves pywebview with an empty
    window list and fragile 'master' recreation), we blank its content and
    HIDE it. The NSWindow stays alive, so:
      - the app stays resident with a healthy window-manager state;
      - the red close button / Cmd+W visibly "close" the window;
      - Dock click or a later Finder double-click un-hides it (or reuses it).
    """
    if api:
        api.reset_to_untitled()
    try:
        _dispatch_js_to(window, 'reloadContent()')
    except Exception:
        log_exception('blank window dispatch failed')
    try:
        with _state_lock:
            _hidden_windows[id(window)] = window
        window.hide()
        logging.info('last window hidden; app stays resident')
    except Exception:
        log_exception('hide last window failed')


def _reopen_hidden_window():
    """Show the most recently hidden blank window, if any. Returns True on success."""
    if not _hidden_windows:
        return False
    # Iterate a copy; show the most recently hidden first.
    for wid, window in list(_hidden_windows.items()):
        if id(window) in _window_apis and api_for_window(window):
            try:
                _dispatch_js_to(window, 'convertToBlankDocument()')
            except Exception:
                pass
            return _focus_window(window)
    return False


def api_for_window(window):
    return _window_apis.get(id(window))


def _sync_content_before_close(window, api):
    """Avoid synchronous JS evaluation during close.

    The close event runs on the UI path. Pulling the full Markdown from JS
    here can force a full DOM-to-Markdown Turndown conversion while the user is
    trying to close the app, which can freeze WKWebView on larger documents. JS
    keeps api.cached_content fresh via debounced store_content() calls instead,
    so close/save prompts use the cached value and never block on full-page JS.
    """
    return


def on_window_closing(window):
    """pywebview 'closing' event handler.

    This is the single choke point for window close attempts:
      - window close button  -> windowShouldClose_  -> events.closing
      - File > Close (Cmd+W) -> JS closeWindow() -> window.destroy() -> close
      - app quit teardown may also close windows after applicationShouldTerminate_

    It runs synchronously on the UI path, so it must stay non-blocking. Dirty
    documents are intercepted and handed back to JS for an async Save / Don't
    Save / Cancel prompt. Once the user confirms close, we:
      1. Ask JS to stop all timers / pending bridge traffic so no new
         JS->Python calls fire during WKWebView teardown.
      2. Persist a draft of unsaved content (cached_content is kept fresh by
         debounced JS store_content() calls).
      3. Remove only this window from registries; normal last-window close does
         not mark the app as quitting.
    """
    try:
        _set_active_window(window)
        api = _window_apis.get(id(window)) or _main_api_ref
        if api and api.is_dirty and not api.close_confirmed:
            if api.cached_content is not None:
                try:
                    _write_draft(api.file_path, api.cached_content, api.document_id, api.revision, hashlib.sha256(api.file_content.encode('utf-8')).hexdigest())
                except Exception:
                    log_exception('write draft during close prompt failed')
            try:
                _dispatch_js_to(window, 'promptBeforeClose(true)')
            except Exception:
                pass
            return False
        _save_window_geometry(window)
        # If this is the last window and the user is not explicitly quitting,
        # keep the app alive by blanking it and HIDING it instead of closing.
        # Hiding (rather than destroying) keeps the NSWindow/pywebview state
        # healthy so Finder double-click and Dock reopen work reliably, and the
        # red close button still visibly "closes" the window for the user.
        if (not _QUIT_REQUESTED.is_set() and _is_last_window(window) and
                not (api and api.close_confirmed)):
            _hide_last_window(window, api)
            return False
        try:
            _dispatch_js_to(window, 'prepareForClose()')
        except Exception:
            pass
        if api and api.is_dirty and api.cached_content is not None:
            try:
                _write_draft(api.file_path, api.cached_content, api.document_id, api.revision, hashlib.sha256(api.file_content.encode('utf-8')).hexdigest())
            except Exception:
                log_exception('write draft during close failed')
        return _allow_close(window)
    except Exception:
        log_exception('window closing failed')
        return False


def _is_app_quitting():
    """True only during an explicit app quit, not normal last-window close."""
    if not _QUIT_REQUESTED.is_set():
        return False
    try:
        import webview.platforms.cocoa as cocoa
        if not cocoa.BrowserView.app.isRunning():
            return True
        if not _window_apis and cocoa.BrowserView.instances == {}:
            return True
    except Exception:
        return not _window_apis
    return False


def _start_quit_watchdog():
    """Guarantee the process terminates on quit.

    Normal quit: closing event -> window teardown -> app.stop_ -> start()
    returns -> interpreter shutdown. That path can still deadlock if a
    non-daemon pywebview bridge thread is blocked in evaluate_js while the
    runloop is gone (the historical 'freezes on quit' bug). The watchdog is a
    daemon thread, so it keeps running while the main thread is stuck joining
    non-daemon threads; once the app is in the quitting state for longer than
    QUIT_FORCE_EXIT_DELAY, it force-exits. All user data is already persisted
    to drafts/config before the close was allowed, so os._exit is safe.
    """
    def _watch():
        quitting_since = None
        while True:
            if not _QUIT_REQUESTED.wait(timeout=0.5):
                quitting_since = None
                continue
            if _is_app_quitting():
                now = time.monotonic()
                if quitting_since is None:
                    quitting_since = now
                elif now - quitting_since >= QUIT_FORCE_EXIT_DELAY:
                    os._exit(0)
            else:
                # Some windows are still open -> this was not a real quit.
                quitting_since = None
                _QUIT_REQUESTED.clear()

    threading.Thread(target=_watch, daemon=True, name='quit-watchdog').start()


def patch_evaluate_js():
    """Make pywebview's cocoa evaluate_js deadlock-proof.

    Stock implementation: AppHelper.callAfter(eval) + Semaphore.acquire().
    If the main runloop is gone (teardown after app.stop_), 'eval' never runs
    and the semaphore never releases -> the calling thread blocks forever.
    pywebview's JS-bridge result threads are non-daemon, so interpreter
    shutdown joins them forever -> process never exits. The patched version
    returns immediately when the runloop is not running and bounds the wait
    with EVALUATE_JS_TIMEOUT, so a stuck call degrades to None instead of
    hanging the process.
    """
    if not HAS_COCOA:
        return
    try:
        import webview.platforms.cocoa as cocoa
        BrowserView = cocoa.BrowserView

        def _safe_evaluate_js(self, script, parse_json=True):
            if not self.webview or not BrowserView.app.isRunning():
                raise RuntimeError('native-javascript-window-closed')

            class JSResult:
                result = None
                error = None
                result_semaphore = threading.Semaphore(0)

            def handler(result, error):
                JSResult.error = error
                if parse_json and result:
                    try:
                        JSResult.result = json.loads(result)
                    except Exception:
                        JSResult.result = result
                else:
                    JSResult.result = result
                try:
                    JSResult.result_semaphore.release()
                except Exception:
                    pass

            def eval_():
                try:
                    self.webview.evaluateJavaScript_completionHandler_(script, handler)
                except Exception as error:
                    JSResult.error = error
                    try:
                        JSResult.result_semaphore.release()
                    except Exception:
                        pass

            cocoa.AppHelper.callAfter(eval_)
            if not JSResult.result_semaphore.acquire(timeout=EVALUATE_JS_TIMEOUT):
                raise TimeoutError('native-javascript-timeout')
            if JSResult.error is not None:
                raise RuntimeError('native-javascript-execution-failed')
            return JSResult.result

        BrowserView.evaluate_js = _safe_evaluate_js
    except Exception:
        log_exception('patch evaluate_js failed')


def _saved_window_geometry():
    from mdpreview_core.reading_state import visible_frame
    frame = load_config().get('window_frame')
    if not HAS_COCOA:
        return {}
    try:
        from AppKit import NSScreen
        screens = [screen.visibleFrame() for screen in NSScreen.screens()]
        rects = [[r.origin.x, r.origin.y, r.size.width, r.size.height] for r in screens]
        if visible_frame(frame, rects):
            # Cocoa 的原点在屏幕下方；pywebview 使用主屏顶部坐标。
            top = NSScreen.screens()[0].frame().size.height
            return {'x': int(frame[0]), 'y': int(top-frame[1]-frame[3]), 'width': int(frame[2]), 'height': int(frame[3])}
    except Exception:
        pass
    return {}


def _save_window_geometry(window):
    try:
        import webview.platforms.cocoa as cocoa
        browser = cocoa.BrowserView.instances.get(getattr(window, 'uid', None))
        native = browser.window if browser is not None else window.native
        frame = native.frame()
        update_config({'window_frame': [frame.origin.x, frame.origin.y, frame.size.width, frame.size.height]})
    except Exception:
        pass


def create_window(file_path=None, x=None, y=None):
    if file_path:
        file_path = os.path.abspath(file_path)
        if file_path in _opened_files:
            _focus_existing_file(file_path)
            return
        with _state_lock:
            _opened_files.add(file_path)

    geometry = _saved_window_geometry()
    if x is None and y is None and geometry:
        x, y = geometry['x'], geometry['y']
        offset = (_window_count[0] * WINDOW_OFFSET) % 150
        candidate = load_config().get('window_frame', [])
        try:
            from AppKit import NSScreen
            from mdpreview_core.reading_state import visible_frame
            screens = [screen.visibleFrame() for screen in NSScreen.screens()]
            shifted = [candidate[0]+offset, candidate[1]-offset, candidate[2], candidate[3]]
            if visible_frame(shifted, [[r.origin.x, r.origin.y, r.size.width, r.size.height] for r in screens]):
                x += offset; y += offset
        except Exception:
            pass
    # Calculate cascade offset if x,y not specified
    if x is None or y is None:
        count = _window_count[0]
        offset = count * WINDOW_OFFSET
        x = WINDOW_BASE_X + (offset % 150)
        y = WINDOW_BASE_Y + (offset % 150)

    api = MarkdownAPI(file_path)
    html_path = get_resource_path('index.html')
    title = os.path.basename(file_path) if file_path else 'Untitled.md'

    try:
        win = webview.create_window(
            title=title,
            url=html_path,
            js_api=api,
            width=geometry.get('width', 900),
            height=geometry.get('height', 680),
            min_size=(680, 400),
            text_select=True,
            confirm_close=False,
            x=x,
            y=y,
        )
        api.window = win
        with _state_lock:
            _window_apis[id(win)] = api
        _set_active_window(win)
        if HAS_COCOA:
            win.events.closing += on_window_closing
            _subscribe_js_ready(win)
        _window_count[0] += 1
        return win
    except Exception:
        # Do NOT swallow: window creation failure is exactly the kind of
        # silent break that killed double-click-open before (NSWindow must be
        # created on the main thread). Log it so it is diagnosable.
        log_exception('create_window failed')


def _create_window_safely(file_path=None, x=None, y=None):
    """Create a window from whatever thread we are on.

    pywebview's webview.create_window only instantiates the native window
    when called from a Python thread whose name is not 'MainThread' (it
    short-circuits and only registers the window otherwise). And on cocoa, a
    NON-master window is created via AppHelper.callAfter(create), which hops
    back to the AppKit main thread — which is where NSWindow must be
    instantiated.

    So this always calls create_window from a background thread. The 'master
    uid' trap is handled by patch_window_close_behavior: it keeps exactly one
    anchor window in webview.windows after the last window closes, so a
    freshly created window always gets a 'child_*' uid and cocoa always uses
    the callAfter path (never tries to build the NSWindow on our thread).
    """
    if threading.current_thread().name == 'MainThread':
        threading.Thread(
            target=create_window, args=(file_path, x, y), daemon=True
        ).start()
    else:
        create_window(file_path, x, y)


def update_main_window(main_window, main_api, file_path, hash=''):
    """Update the main window with a new file (reused hidden window path)."""
    file_path = os.path.abspath(file_path)
    main_api.reset_to_untitled()
    main_api.file_path = file_path
    main_api.pending_hash = hash or _pending_link_hashes.pop(os.path.realpath(file_path), '')
    main_api.is_untitled = False
    with _state_lock:
        _opened_files.add(file_path)
        _hidden_windows.pop(id(main_window), None)
    _set_active_window(main_window)
    try:
        main_window.show()
    except Exception:
        pass

    def do_update():
        # Event-driven readiness: for a reused resident window the JS bridge is
        # already up (id in _windows_js_ready), so evaluate_js fires IMMEDIATELY.
        # For a cold-started window we fast-poll (50ms) until pywebview's loaded
        # event marks it ready, capped by WINDOW_JS_READY_TIMEOUT. The old code
        # slept a flat 300ms per attempt regardless of state, which wasted time
        # on every resident-window open.
        deadline = time.time() + WINDOW_JS_READY_TIMEOUT
        while True:
            if id(main_window) in _windows_js_ready:
                try:
                    from mdpreview_core.csp_bridge import run_body
                    run_body(main_window, 'reloadContent();')
                    main_window.set_title(_edited_title(os.path.basename(file_path), main_api.is_dirty))
                    _set_represented_file(main_window, file_path)
                    return
                except Exception:
                    pass
            if time.time() > deadline:
                return
            time.sleep(0.05)

    threading.Thread(target=do_update, daemon=True).start()


def _reuse_hidden_window_for_file(file_path):
    """Reuse the hidden blank window (from a last-window close) for a new file.

    Prevents leaking a hidden window: instead of creating a brand-new window
    next to the hidden one, the hidden window is shown, loaded with the file and
    given the file's title.
    """
    for wid, window in list(_hidden_windows.items()):
        api = _window_apis.get(wid)
        if api and api.is_untitled and not api.is_dirty and api.window:
            try:
                update_main_window(window, api, file_path)
            except Exception:
                log_exception('reuse hidden window failed')
            return True
    return False


def handle_opened_file(file_path, main_window=None, main_api=None):
    """Handle a file opened via Apple Event or argv"""
    global _initial_file_handled

    if not file_path or not os.path.exists(file_path):
        return

    valid_extensions = ('.md', '.markdown', '.mdown', '.mkd', '.mkdown', '.txt')
    if not file_path.lower().endswith(valid_extensions):
        return

    file_path = os.path.abspath(file_path)
    if file_path in _opened_files:
        _focus_existing_file(file_path)
        return

    # Prefer reusing a hidden blank window (kept alive after last-window
    # close) over creating a brand-new one, so we never leak hidden windows.
    if _reuse_hidden_window_for_file(file_path):
        _initial_file_handled = True
        return

    can_reuse_main_window = (
        not _initial_file_handled and main_window and main_api and
        main_api.is_untitled and not main_api.is_dirty
    )
    if can_reuse_main_window:
        _initial_file_handled = True
        update_main_window(main_window, main_api, file_path)
    else:
        _initial_file_handled = True
        # NSWindow must be created on the main thread; _create_window_safely
        # hops to the main thread if needed (background threads were fine on
        # old pywebview but now raise NSInternalInconsistencyException).
        _create_window_safely(file_path)


if HAS_COCOA:

    def _make_md_icon():
        """16pt template image with 'md' text (Retina-sharp via drawing handler).

        Measures the actual glyph size and centers it, so BOTH letters ('md')
        always fit inside the 16x16 canvas — drawInRect was clipping the 'd'.
        """
        try:
            from AppKit import (NSImage, NSFont, NSColor, NSDictionary, NSMakePoint,
                                NSFontAttributeName, NSForegroundColorAttributeName)
            from Foundation import NSString

            text = NSString.stringWithString_('md')
            canvas = 16
            # Largest font size that fits the canvas (step 0.5 down until it does).
            font_size = 12.0
            attrs = None
            text_size = None
            while font_size >= 8.0:
                attrs = NSDictionary.dictionaryWithObjects_forKeys_(
                    [NSFont.boldSystemFontOfSize_(font_size), NSColor.labelColor()],
                    [NSFontAttributeName, NSForegroundColorAttributeName])
                text_size = text.sizeWithAttributes_(attrs)
                if text_size.width <= canvas and text_size.height <= canvas:
                    break
                font_size -= 0.5

            def draw(rect):
                x = (rect.size.width - text_size.width) / 2.0
                # Slightly below optical center: drawAtPoint's y is the baseline,
                # and the glyph's visual center sits a touch high when fully
                # centered, so nudge down 2px.
                y = (rect.size.height - text_size.height) / 2.0 - 2.0
                text.drawAtPoint_withAttributes_(NSMakePoint(x, y), attrs)
                return True

            img = NSImage.imageWithSize_flipped_drawingHandler_((canvas, canvas), False, draw)
            img.setTemplate_(True)  # adapts to light/dark menu appearance
            return img
        except Exception:
            log_exception('make md icon failed')
            return None

    def _make_symbol_icon(name):
        try:
            from AppKit import NSImage
            icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, '')
            if icon is not None:
                icon.setTemplate_(True)
            return icon
        except Exception:
            return None

    def _set_symbol_icon(item, name):
        icon = _make_symbol_icon(name)
        if icon is not None:
            item.setImage_(icon)

    def setup_all_menus():
        """Set up all custom menu items. Called once menus are ready."""
        global _view_menu_setup, _file_menu_setup, _app_menu_setup, _update_menu_item
        try:
            from AppKit import NSApplication, NSMenuItem, NSMenu
            from Foundation import NSObject

            main_menu = NSApplication.sharedApplication().mainMenu()
            if not main_menu:
                _view_menu_handler.performSelector_withObject_afterDelay_(
                    'setupAllMenusRetry:', None, 0.5
                )
                return

            # ── App menu: About + Check for Updates ──
            # Connect the default "About mdPreview" item to our handler
            app_menu_item = main_menu.itemAtIndex_(0)
            app_menu = app_menu_item.submenu()
            if app_menu and app_menu.numberOfItems() > 0 and not _app_menu_setup:
                about_item = app_menu.itemAtIndex_(0)
                if about_item:
                    about_item.setAction_('showAbout:')
                    about_item.setTarget_(_view_menu_handler)
                for idx in range(app_menu.numberOfItems() - 1, 0, -1):
                    item = app_menu.itemAtIndex_(idx)
                    title = str(item.title() or '')
                    action = str(item.action() or '')
                    if title in ('Preferences…', 'Preferences...', '偏好设置…', '偏好设置...') or action == 'showPreferences:':
                        app_menu.removeItemAtIndex_(idx)
                # Insert "Check for Updates…" after the standard About item.
                update_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Check for Updates…", "检查更新…"), "checkForUpdates:", "")
                update_item.setTarget_(_view_menu_handler)
                app_menu.insertItem_atIndex_(update_item, 1)
                _update_menu_item = update_item
                _app_menu_setup = True

            # ── View menu: Increase/Decrease Width ──
            if not _view_menu_setup:
                view_menu = None
                for i in range(main_menu.numberOfItems()):
                    item = main_menu.itemAtIndex_(i)
                    sub = item.submenu()
                    if sub and sub.title() in ('View', '显示', '视图', _t('View', '显示')):
                        view_menu = sub
                        break

                if view_menu:
                    # Rebuild the whole menu so separators and native items have
                    # a stable order.
                    first_section_end = view_menu.numberOfItems()
                    for idx in range(view_menu.numberOfItems()):
                        if view_menu.itemAtIndex_(idx).isSeparatorItem():
                            first_section_end = idx + 1
                            break
                    while view_menu.numberOfItems() > first_section_end:
                        view_menu.removeItemAtIndex_(first_section_end)
                    # Every document is its own window, so drop AppKit's tab
                    # and system full-screen items (ours is added below);
                    # otherwise "Enter Full Screen" appears twice.
                    while first_section_end > 0:
                        view_menu.removeItemAtIndex_(0)
                        first_section_end -= 1

                    # Section 2: Preview/Source + Outline.
                    toggle_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                        _t("Toggle Preview / Source", "切换预览 / 源码"), "toggleView:", "e")
                    toggle_item.setKeyEquivalentModifierMask_(1 << 20)  # Command
                    global _toggle_menu_item
                    _toggle_menu_item = toggle_item
                    try:
                        from mdpreview_core.settings import settings as _settings_of
                        _apply_toggle_shortcut(_settings_of(load_config()).get('toggle_shortcut'))
                    except Exception:
                        pass
                    md_icon = _make_md_icon()
                    if md_icon is not None:
                        toggle_item.setImage_(md_icon)
                    toggle_item.setTarget_(_view_menu_handler)
                    view_menu.insertItem_atIndex_(toggle_item, first_section_end)
                    outline_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Show/Hide Outline", "显示/隐藏大纲"), "toggleOutline:", "o")
                    outline_item.setKeyEquivalentModifierMask_((1 << 20) | (1 << 19))  # Cmd+Option+O
                    _set_symbol_icon(outline_item, 'list.bullet.rectangle')
                    view_menu.insertItem_atIndex_(outline_item, first_section_end + 1)
                    bar_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Always Show Formatting Bar", "始终显示格式工具条"), "toggleFormatBar:", "t")
                    bar_item.setKeyEquivalentModifierMask_((1 << 20) | (1 << 19))  # Cmd+Option+T
                    try:
                        bar_item.setState_(1 if __import__('mdpreview_core.settings', fromlist=['settings']).settings(load_config()).get('format_bar') else 0)
                    except Exception:
                        pass
                    view_menu.insertItem_atIndex_(bar_item, first_section_end + 2)
                    view_menu.insertItem_atIndex_(NSMenuItem.separatorItem(), first_section_end + 3)

                    # Section 3: Full Screen.
                    fullscreen_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Enter Full Screen", "进入全屏幕"), "toggleFullScreen:", "f")
                    fullscreen_item.setKeyEquivalentModifierMask_((1 << 20) | (1 << 18))  # Ctrl+Cmd+F，macOS 标准全屏快捷键
                    _set_symbol_icon(fullscreen_item, 'arrow.up.left.and.arrow.down.right')
                    view_menu.insertItem_atIndex_(fullscreen_item, first_section_end + 3)
                    view_menu.insertItem_atIndex_(NSMenuItem.separatorItem(), first_section_end + 4)

                    # Section 4: width and text-size controls.
                    inc_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Increase Width", "加宽"), "increaseWidth:", "=")
                    inc_item.setKeyEquivalentModifierMask_((1 << 20) | (1 << 19))
                    _set_symbol_icon(inc_item, 'arrow.left.and.right')
                    view_menu.insertItem_atIndex_(inc_item, first_section_end + 5)
                    dec_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Decrease Width", "变窄"), "decreaseWidth:", "-")
                    dec_item.setKeyEquivalentModifierMask_((1 << 20) | (1 << 19))
                    _set_symbol_icon(dec_item, 'arrow.left.and.right')
                    view_menu.insertItem_atIndex_(dec_item, first_section_end + 6)
                    reset_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Reset Width", "重置宽度"), "resetWidth:", "0")
                    reset_item.setKeyEquivalentModifierMask_((1 << 20) | (1 << 19))
                    _set_symbol_icon(reset_item, 'arrow.uturn.left')
                    view_menu.insertItem_atIndex_(reset_item, first_section_end + 7)
                    zoom_in_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Bigger Text", "放大文字"), "zoomIn:", "=")
                    zoom_in_item.setKeyEquivalentModifierMask_(1 << 20)
                    _set_symbol_icon(zoom_in_item, 'textformat.size.larger')
                    view_menu.insertItem_atIndex_(zoom_in_item, first_section_end + 8)
                    zoom_out_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Smaller Text", "缩小文字"), "zoomOut:", "-")
                    zoom_out_item.setKeyEquivalentModifierMask_(1 << 20)
                    _set_symbol_icon(zoom_out_item, 'textformat.size.smaller')
                    view_menu.insertItem_atIndex_(zoom_out_item, first_section_end + 9)
                    outline_item.setTarget_(_view_menu_handler)
                    inc_item.setTarget_(_view_menu_handler)
                    dec_item.setTarget_(_view_menu_handler)
                    reset_item.setTarget_(_view_menu_handler)
                    zoom_in_item.setTarget_(_view_menu_handler)
                    zoom_out_item.setTarget_(_view_menu_handler)
                    reset_font = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('重置字号', 'resetFontSize:', '0')
                    reset_font.setKeyEquivalentModifierMask_(1 << 20)
                    reset_font.setTarget_(_view_menu_handler)
                    view_menu.addItem_(reset_font)
                    preferences = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('设置…', 'openSettings:', ',')
                    preferences.setKeyEquivalentModifierMask_(1 << 20)
                    preferences.setTarget_(_view_menu_handler)
                    main_menu.itemAtIndex_(0).submenu().insertItem_atIndex_(preferences, 1)
                    _view_menu_setup = True

            # ── File menu: Properties ──
            if not _file_menu_setup:
                file_menu = None
                file_menu_index = -1
                for i in range(main_menu.numberOfItems()):
                    item = main_menu.itemAtIndex_(i)
                    sub = item.submenu()
                    if sub and sub.title() in ('File', '文件', _t('File', '文件')):
                        file_menu = sub
                        file_menu_index = i
                        break

                if not file_menu:
                    # Create File menu since it doesn't exist
                    file_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("File", "文件"), None, "")
                    file_menu = NSMenu.alloc().initWithTitle_(_t("File", "文件"))
                    file_item.setSubmenu_(file_menu)
                    # Insert at the beginning (before the empty title item or Edit)
                    main_menu.insertItem_atIndex_(file_item, 1)
                    file_menu_index = 1

                if file_menu:
                    file_menu.addItem_(NSMenuItem.separatorItem())
                    open_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Open File…", "打开文件…"), "openFile:", "o")
                    open_item.setTarget_(_view_menu_handler)
                    file_menu.addItem_(open_item)
                    clip_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("New from Clipboard", "从剪贴板新建"), "newFromClipboard:", "n")
                    clip_item.setKeyEquivalentModifierMask_((1 << 20) | (1 << 19))  # Option+Command+N
                    clip_item.setTarget_(_view_menu_handler)
                    file_menu.addItem_(clip_item)
                    recent_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Open Recent", "打开最近"), None, "")
                    recent_menu = NSMenu.alloc().initWithTitle_(_t("Open Recent", "打开最近"))
                    for recent_path in load_config().get('recent_files', [])[:10]:
                        # Avoid os.path.exists() here: probing privacy-gated
                        # folders like Desktop can trigger a TCC prompt while
                        # the menu is merely being built. Open-time errors are
                        # handled when the user explicitly selects the item.
                        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(os.path.basename(recent_path), "openRecentFile:", "")
                        item.setRepresentedObject_(recent_path)
                        item.setToolTip_(recent_path)
                        item.setTarget_(_view_menu_handler)
                        recent_menu.addItem_(item)
                    recent_item.setSubmenu_(recent_menu)
                    file_menu.addItem_(recent_item)
                    close_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Close", "关闭"), "closeWindow:", "w")
                    close_item.setTarget_(_view_menu_handler)
                    file_menu.addItem_(close_item)
                    file_menu.addItem_(NSMenuItem.separatorItem())
                    # Save / Save As: native menu items are needed because macOS
                    # may consume Cmd+S before the webview keydown handler sees it.
                    save_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Save", "保存"), "saveFile:", "s")
                    save_item.setTarget_(_view_menu_handler)
                    file_menu.addItem_(save_item)
                    save_as_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Save As…", "另存为…"), "saveAsFile:", "s")
                    save_as_item.setKeyEquivalentModifierMask_((1 << 20) | (1 << 17))  # Cmd+Shift+S
                    save_as_item.setTarget_(_view_menu_handler)
                    file_menu.addItem_(save_as_item)
                    file_menu.addItem_(NSMenuItem.separatorItem())
                    export_as_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                        _t("Export As…", "导出为…"), "exportAs:", "")
                    export_as_item.setTarget_(_view_menu_handler)
                    try:
                        from AppKit import NSImage
                        icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                            'square.and.arrow.up', '')
                        if icon is not None:
                            export_as_item.setImage_(icon)
                    except Exception:
                        pass
                    file_menu.addItem_(export_as_item)
                    print_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Print…", "打印…"), "printDocument:", "p")
                    print_item.setTarget_(_view_menu_handler)
                    file_menu.addItem_(print_item)
                    share_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Share…", "共享…"), "shareDocument:", "")
                    share_item.setTarget_(_view_menu_handler)
                    try:
                        _set_symbol_icon(share_item, 'square.and.arrow.up')
                    except Exception:
                        pass
                    file_menu.addItem_(share_item)
                    file_menu.addItem_(NSMenuItem.separatorItem())
                    # New File
                    new_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("New", "新建"), "newFile:", "n")
                    new_item.setTarget_(_view_menu_handler)
                    file_menu.addItem_(new_item)
                    # Properties
                    props_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Properties", "属性"), "showProperties:", "i")
                    props_item.setKeyEquivalentModifierMask_(1 << 20)
                    file_menu.addItem_(props_item)
                    props_item.setTarget_(_view_menu_handler)
                    _file_menu_setup = True

            # ── Edit menu: Find ──
            if not _app_menu_setup or not getattr(_view_menu_handler, '_edit_menu_setup', False):
                edit_menu = None
                for i in range(main_menu.numberOfItems()):
                    item = main_menu.itemAtIndex_(i)
                    sub = item.submenu()
                    if sub and sub.title() in ('Edit', '编辑', _t('Edit', '编辑')):
                        edit_menu = sub
                        break

                if edit_menu and not getattr(_view_menu_handler, '_edit_menu_setup', False):
                    # "Paste as Markdown": insert right after the native Paste
                    # item (or at the top of the Edit menu if it is absent).
                    # Cmd+Shift+V overrides macOS' default "Paste and Match Style".
                    # Undo / Redo go to the first responder (the web view), which
                    # owns the editing history. Add them when AppKit's menu has none.
                    existing_actions = [str(edit_menu.itemAtIndex_(i).action() or '')
                                        for i in range(edit_menu.numberOfItems())]
                    if 'undo:' not in existing_actions:
                        undo_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t('Undo', '撤销'), 'undo:', 'z')
                        undo_item.setKeyEquivalentModifierMask_(1 << 20)
                        redo_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t('Redo', '重做'), 'redo:', 'z')
                        redo_item.setKeyEquivalentModifierMask_((1 << 20) | (1 << 17))
                        edit_menu.insertItem_atIndex_(undo_item, 0)
                        edit_menu.insertItem_atIndex_(redo_item, 1)
                        edit_menu.insertItem_atIndex_(NSMenuItem.separatorItem(), 2)
                    paste_insert_at = 0
                    for idx in range(edit_menu.numberOfItems()):
                        it = edit_menu.itemAtIndex_(idx)
                        act = str(it.action() or '')
                        if act == 'paste:':
                            paste_insert_at = idx + 1
                            break
                    paste_md_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                        _t("Paste as Markdown", "粘贴为 Markdown"), "pasteAsMarkdown:", "v")
                    paste_md_item.setKeyEquivalentModifierMask_((1 << 20) | (1 << 17))  # Cmd+Shift
                    _set_symbol_icon(paste_md_item, 'doc.richtext')
                    paste_md_item.setTarget_(_view_menu_handler)
                    edit_menu.insertItem_atIndex_(paste_md_item, paste_insert_at)
                    for label, action, modifier in [(_t('Copy as Rich Text', '复制为富文本'), 'copyAsRichText:', 1 << 17), (_t('Copy as Markdown', '复制为 Markdown'), 'copyAsMarkdown:', 1 << 19)]:
                        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(label, action, 'c')
                        item.setKeyEquivalentModifierMask_((1 << 20) | modifier)
                        item.setTarget_(_view_menu_handler)
                        edit_menu.insertItem_atIndex_(item, paste_insert_at + 1)

                    edit_menu.addItem_(NSMenuItem.separatorItem())
                    find_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Find", "查找"), "findAction:", "f")
                    find_item.setTarget_(_view_menu_handler)
                    edit_menu.addItem_(find_item)
                    find_next_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Find Next", "查找下一个"), "findNextAction:", "g")
                    find_next_item.setTarget_(_view_menu_handler)
                    edit_menu.addItem_(find_next_item)
                    find_prev_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Find Previous", "查找上一个"), "findPrevAction:", "g")
                    find_prev_item.setKeyEquivalentModifierMask_((1 << 20) | (1 << 17))  # Cmd+Shift+G
                    find_prev_item.setTarget_(_view_menu_handler)
                    edit_menu.addItem_(find_prev_item)
                    goto_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Go to Heading…", "跳转到标题…"), "openGoToHeading:", "j")
                    goto_item.setKeyEquivalentModifierMask_(1 << 20)  # Cmd+J
                    goto_item.setTarget_(_view_menu_handler)
                    edit_menu.addItem_(goto_item)
                    _view_menu_handler._edit_menu_setup = True

            if not getattr(_view_menu_handler, '_help_menu_setup', False):
                help_menu = NSMenu.alloc().initWithTitle_(_t('Help', '帮助'))
                help_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t('Help', '帮助'), None, '')
                help_item.setSubmenu_(help_menu)
                for title, action in [(_t('mdPreview Help', 'mdPreview 帮助'), 'appHelp:'),
                                      (_t('Keyboard Shortcuts', '快捷键一览'), 'keyboardShortcuts:'),
                                      (_t('Open Example', '打开示例文档'), 'openExample:'),
                                      (_t('Report Issue…', '报告问题…'), 'reportIssue:'),
                                      (_t('Export Diagnostics…', '导出诊断信息…'), 'exportDiagnostics:')]:
                    item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, '')
                    item.setTarget_(_view_menu_handler)
                    help_menu.addItem_(item)
                main_menu.addItem_(help_item)
                NSApplication.sharedApplication().setHelpMenu_(help_menu)
                cli_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t('Install Command Line Tool…', '安装命令行工具…'), 'installCommandLine:', '')
                cli_item.setTarget_(_view_menu_handler)
                main_menu.itemAtIndex_(0).submenu().addItem_(cli_item)
                default_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t('Set as Default for Markdown Files…', '设为 Markdown 文件的默认打开方式…'), 'setDefaultMarkdownApp:', '')
                default_item.setTarget_(_view_menu_handler)
                main_menu.itemAtIndex_(0).submenu().addItem_(default_item)
                _view_menu_handler._help_menu_setup = True
            with open(get_resource_path('frontend/shortcuts.json'), encoding='utf-8') as stream:
                shortcuts = {item['action']: item for item in json.load(stream)}
            masks = {'command': 1 << 20, 'shift': 1 << 17, 'option': 1 << 19, 'control': 1 << 18}
            def apply_shortcuts(menu):
                for item in menu.itemArray():
                    shortcut = shortcuts.get(str(item.action() or ''))
                    if shortcut:
                        item.setKeyEquivalent_(shortcut['key'])
                        item.setKeyEquivalentModifierMask_(sum(masks[m] for m in shortcut['modifiers']))
                        item.setTitle_(_t(shortcut['en'], shortcut['zh']))
                    if item.submenu():
                        apply_shortcuts(item.submenu())
            apply_shortcuts(main_menu)
            # pywebview 创建的系统标准菜单是英文的：按界面语言重新命名（匹配英文原标题）
            standard_titles = {
                'Edit': _t('Edit', '编辑'), 'View': _t('View', '显示'), 'Undo': _t('Undo', '撤销'), 'Redo': _t('Redo', '重做'),
                'Cut': _t('Cut', '剪切'), 'Copy': _t('Copy', '复制'), 'Paste': _t('Paste', '粘贴'), 'Select All': _t('Select All', '全选'),
                'AutoFill': _t('AutoFill', '自动填充'), 'Start Dictation…': _t('Start Dictation…', '开始听写…'),
                'Emoji & Symbols': _t('Emoji & Symbols', '表情与符号'), 'Services': _t('Services', '服务'),
                'Hide mdPreview': _t('Hide mdPreview', '隐藏 mdPreview'), 'Hide Others': _t('Hide Others', '隐藏其他'),
                'Show All': _t('Show All', '全部显示'), 'Quit mdPreview': _t('Quit mdPreview', '退出 mdPreview'),
                'Quit and Keep Windows': _t('Quit and Keep Windows', '退出并保留窗口'), 'About mdPreview': _t('About mdPreview', '关于 mdPreview'),
            }
            def localize_standard(menu):
                for item in menu.itemArray():
                    title = str(item.title() or '')
                    if title not in standard_titles and item.submenu():
                        title = str(item.submenu().title() or '')
                    if title in standard_titles and standard_titles[title] != title:
                        item.setTitle_(standard_titles[title])
                        if item.submenu():
                            item.submenu().setTitle_(standard_titles[title])
                    if item.submenu():
                        localize_standard(item.submenu())
            localize_standard(main_menu)
        except Exception:
            log_exception('setup menus failed')

    def setup_view_menu():
        """Legacy — delegates to setup_all_menus."""
        setup_all_menus()

    def setup_file_menu():
        """Legacy — delegates to setup_all_menus."""
        setup_all_menus()

    def _dispatch_js_to(window, js_code):
        """Execute JS directly on a specific window's WKWebView (main thread safe).

        Uses evaluateJavaScript:completionHandler: directly (async) instead of
        pywebview's evaluate_js(), which can deadlock on the main thread or after
        the runloop stops.
        """
        if not window or not HAS_COCOA:
            return
        try:
            from webview.platforms.cocoa import BrowserView
            browser = BrowserView.instances.get(window.uid)
            if browser and browser.webview:
                browser.webview.evaluateJavaScript_completionHandler_(js_code, None)
        except Exception:
            pass

    def _dispatch_js(js_code):
        """Execute JS directly on WKWebView from the main thread.
        
        We bypass pywebview's evaluate_js() because it uses
        AppHelper.callAfter + semaphore.acquire() which deadlocks
        when called from the main thread (menu handler).
        Instead, we call WKWebView.evaluateJavaScript:completionHandler:
        directly — it's async and safe on the main thread.
        """
        try:
            from webview.platforms.cocoa import BrowserView
            ref = _get_target_window()
            if not ref:
                return
            browser = BrowserView.instances.get(ref.uid)
            if browser and browser.webview:
                browser.webview.evaluateJavaScript_completionHandler_(js_code, None)
        except Exception:
            log_exception('dispatch js failed')

    def _current_file_properties():
        ref = _get_target_window()
        api = _window_apis.get(id(ref)) if ref else None
        if api is None:
            api = _main_api_ref
        return api.get_file_properties() if api is not None else {
            'name': 'Untitled.md',
            'location': '',
            'size': 0,
            'sizeFormatted': '0 B',
            'modified': '',
            'created': '',
            'exists': False,
            'encoding': '',
        }

    def _show_native_properties_panel():
        """Show file properties in a standard native macOS window."""
        global _properties_panel_ref
        try:
            from AppKit import (
                NSBackingStoreBuffered, NSColor, NSFont, NSImage, NSImageScaleProportionallyUpOrDown,
                NSImageView, NSMakeRect, NSTextField, NSWindow,
                NSWindowStyleMaskClosable, NSWindowStyleMaskTitled,
            )
            props = _current_file_properties()
            name = props.get('name') or 'Untitled.md'
            location = props.get('location') or ''
            path_value = os.path.join(location, name) if location else name
            rows = [
                (_t('Name', '名称'), name),
                (_t('Path', '路径'), path_value),
                (_t('Size', '大小'), f"{props.get('sizeFormatted') or '0 B'} ({props.get('size') or 0} {_t('bytes', '字节')})"),
                (_t('Encoding', '编码'), props.get('encoding') or '-'),
                (_t('Modified', '修改时间'), props.get('modified') or '-'),
                (_t('Created', '创建时间'), props.get('created') or '-'),
            ]

            width = 560
            row_h = 30
            top_pad = 26
            bottom_pad = 24
            left_w = 150
            right_x = left_w + 14
            right_w = width - right_x - 20
            label_w = 78
            value_w = right_w - label_w - 8
            label_font = NSFont.systemFontOfSize_(12)
            value_font = NSFont.systemFontOfSize_(12)
            path_label = _t('Path', '路径')
            try:
                from AppKit import NSFontAttributeName
                from Foundation import NSString
                path_text = NSString.stringWithString_(str(path_value))
                path_width = path_text.sizeWithAttributes_({NSFontAttributeName: value_font}).width
            except Exception:
                path_width = len(str(path_value)) * 7
            path_needs_wrap = path_width > value_w
            row_heights = [52 if label == path_label and path_needs_wrap else row_h for label, _ in rows]
            height = top_pad + bottom_pad + sum(row_heights)
            panel = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, width, height),
                NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
                NSBackingStoreBuffered,
                False,
            )
            panel.setTitle_(_t('File Properties', '文件属性'))
            panel.setReleasedWhenClosed_(False)
            panel.setBackgroundColor_(NSColor.whiteColor())
            content = panel.contentView()
            content.setWantsLayer_(True)
            content.layer().setBackgroundColor_(NSColor.whiteColor().CGColor())

            icon_size = 72
            icon_x = (left_w - icon_size) / 2 + 8
            icon_y = (height - icon_size) / 2
            icon_view = NSImageView.alloc().initWithFrame_(NSMakeRect(icon_x, icon_y, icon_size, icon_size))
            icon = NSImage.alloc().initWithContentsOfFile_(get_resource_path('doc_icon.icns'))
            if icon is not None:
                icon_view.setImage_(icon)
            icon_view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
            content.addSubview_(icon_view)

            y = height - top_pad
            for (label, value), current_row_h in zip(rows, row_heights):
                is_wrapped_path = label == path_label and path_needs_wrap
                value_h = 46 if is_wrapped_path else 24
                row_bottom = y - current_row_h
                label_field = NSTextField.labelWithString_(label)
                label_field.setFrame_(NSMakeRect(right_x, row_bottom + current_row_h - 22, label_w, 18))
                label_field.setFont_(label_font)
                label_field.setTextColor_(NSColor.secondaryLabelColor())
                content.addSubview_(label_field)

                value_field = NSTextField.alloc().initWithFrame_(NSMakeRect(right_x + label_w + 8, row_bottom + current_row_h - value_h - 2, value_w, value_h))
                value_field.setStringValue_(str(value))
                value_field.setFont_(value_font)
                value_field.setEditable_(False)
                value_field.setSelectable_(True)
                value_field.setBezeled_(False)
                value_field.setDrawsBackground_(False)
                value_field.setLineBreakMode_(0 if is_wrapped_path else 4)
                value_field.setUsesSingleLineMode_(not is_wrapped_path)
                content.addSubview_(value_field)
                y = row_bottom

            panel.center()
            panel.makeKeyAndOrderFront_(None)
            _properties_panel_ref = panel
        except Exception:
            log_exception('show native properties failed')
            try:
                from AppKit import NSAlert
                alert = NSAlert.alloc().init()
                alert.setMessageText_(_t('File Properties', '文件属性'))
                alert.setInformativeText_(_t('Could not open the native properties window.', '无法打开原生属性窗口。'))
                alert.runModal()
            except Exception:
                pass

    # Dynamically create an ObjC class to handle menu actions
    from Foundation import NSObject

    class ViewMenuHandler(NSObject):
        def toggleView_(self, sender):
            _dispatch_js('toggleView()')

        def increaseWidth_(self, sender):
            _dispatch_js('adjustPageWidth(40)')

        def decreaseWidth_(self, sender):
            _dispatch_js('adjustPageWidth(-40)')

        def shareDocument_(self, sender):
            _share_active_document()

        def setDefaultMarkdownApp_(self, sender):
            _set_default_markdown_app(announce=True)

        def installCommandLine_(self, sender):
            _dispatch_js("Bridge.call('install_cli').then(r=>showStatus(r.success?'CLI: '+r.path+' — PATH: '+r.addToPath:r.error,!r.success))")

        def appHelp_(self, sender):
            _dispatch_js("Bridge.callSafe('open_external_link','https://github.com/tahoeliu/mdPreview#readme')")

        def keyboardShortcuts_(self, sender):
            _dispatch_js('Onboarding.shortcuts()')

        def openExample_(self, sender):
            _dispatch_js('Onboarding.example()')

        def reportIssue_(self, sender):
            _dispatch_js("Bridge.callSafe('report_issue')")

        def exportDiagnostics_(self, sender):
            _dispatch_js('Onboarding.diagnostics()')

        def openSettings_(self, sender):
            _dispatch_js('openSettings()')

        def resetFontSize_(self, sender):
            _dispatch_js('resetFontSize()')

        def resetWidth_(self, sender):
            _dispatch_js('resetPageWidth()')

        def zoomIn_(self, sender):
            _dispatch_js('zoomIn()')

        def zoomOut_(self, sender):
            _dispatch_js('zoomOut()')

        def toggleOutline_(self, sender):
            _dispatch_js('toggleToc()')

        def toggleFormatBar_(self, sender):
            try:
                sender.setState_(0 if sender.state() else 1)
            except Exception:
                pass
            _dispatch_js('toggleFormatBar()')

        def showProperties_(self, sender):
            _show_native_properties_panel()

        def saveFile_(self, sender):
            _dispatch_js('saveFile()')

        def saveAsFile_(self, sender):
            _dispatch_js('saveAsFile()')

        def openFile_(self, sender):
            _dispatch_js('openFile()')

        def openRecentFile_(self, sender):
            try:
                path = sender.representedObject()
                handle_opened_file(str(path), _main_window_ref, _main_api_ref)
            except Exception:
                log_exception('open recent file failed')

        def closeWindow_(self, sender):
            global _properties_panel_ref, _about_window_ref
            try:
                if _properties_panel_ref and _properties_panel_ref.isVisible():
                    _properties_panel_ref.close()
                    return
            except Exception:
                pass
            # Dismiss the standard About panel with Cmd+W. It is not a normal
            # document window, so the default close path would otherwise ignore it.
            try:
                if _about_window_ref is not None and _about_window_ref.isVisible():
                    _about_window_ref.close()
                    return
            except Exception:
                pass
            _dispatch_js('closeWindow()')

        def exportAs_(self, sender):
            _dispatch_js('exportAs()')

        def printDocument_(self, sender):
            _dispatch_js('printDocument()')

        def newFile_(self, sender):
            # Open a new blank window (main-thread safe).
            _create_window_safely(None)

        def newFromClipboard_(self, sender):
            # AI-era entry: copy an answer anywhere, open it rendered at once.
            def run():
                win = create_window(None)
                if not win:
                    return
                deadline = time.time() + 10
                while time.time() < deadline and id(win) not in _windows_js_ready:
                    time.sleep(0.05)
                _dispatch_js_to(win, 'pasteClipboardAndRead()')
            threading.Thread(target=run, daemon=True).start()

        def findAction_(self, sender):
            _dispatch_js('openFindBar()')

        def copyAsRichText_(self, sender):
            _dispatch_js('copyAsRichText()')

        def copyAsMarkdown_(self, sender):
            _dispatch_js('copyAsMarkdown()')

        def pasteAsMarkdown_(self, sender):
            _dispatch_js('pasteAsMarkdown()')

        def findNextAction_(self, sender):
            _dispatch_js('findNext()')

        def openGoToHeading_(self, sender):
            _dispatch_js('openGoToHeading()')

        def findPrevAction_(self, sender):
            _dispatch_js('findPrev()')

        def checkForUpdates_(self, sender):
            """Manual update check — user explicitly asked, so alerts are OK."""
            global _available_update_version
            if _available_update_version:
                AppHelper.callAfter(_show_update_alert, _available_update_version)
                return
            def _do_check():
                try:
                    remote = _fetch_latest_version()
                    if not remote:
                        AppHelper.callAfter(_manual_check_error)
                        return
                    local = _get_current_version()
                    if _is_newer(remote, local):
                        AppHelper.callAfter(_show_update_alert, remote)
                    else:
                        _clear_update_available()
                        AppHelper.callAfter(_manual_check_up_to_date)
                except Exception:
                    AppHelper.callAfter(_manual_check_error)
            threading.Thread(target=_do_check, daemon=True).start()

        def showAbout_(self, sender):
            """Show a custom native About window with a plain white background."""
            global _about_window_ref
            try:
                from AppKit import (
                    NSApp, NSBackingStoreBuffered, NSFont, NSImage, NSImageScaleProportionallyUpOrDown,
                    NSImageView, NSMakeRect, NSTextField, NSWindow, NSWindowStyleMaskClosable,
                    NSWindowStyleMaskTitled, NSColor, NSCenterTextAlignment,
                    NSParagraphStyleAttributeName, NSFullSizeContentViewWindowMask,
                    NSFontAttributeName, NSLineBreakByWordWrapping
                )
                from Foundation import NSURL, NSMutableParagraphStyle, NSMakeRange

                if _about_window_ref is not None and _about_window_ref.isVisible():
                    _about_window_ref.makeKeyAndOrderFront_(None)
                    return

                width = 300
                height = 278
                panel = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                    NSMakeRect(0, 0, width, height),
                    NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSFullSizeContentViewWindowMask,
                    NSBackingStoreBuffered,
                    False,
                )
                panel.setTitlebarAppearsTransparent_(True)
                panel.setTitle_(_t('About mdPreview', '关于 mdPreview'))
                panel.setReleasedWhenClosed_(False)
                panel.setBackgroundColor_(NSColor.whiteColor())
                content = panel.contentView()
                content.setWantsLayer_(True)
                content.layer().setBackgroundColor_(NSColor.whiteColor().CGColor())

                icon_size = 82
                icon_view = NSImageView.alloc().initWithFrame_(NSMakeRect((width - icon_size) / 2, 146, icon_size, icon_size))
                icon = NSImage.alloc().initWithContentsOfFile_(get_resource_path('app_icon.icns'))
                if icon is not None:
                    icon_view.setImage_(icon)
                icon_view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
                content.addSubview_(icon_view)

                title_font = NSFont.systemFontOfSize_weight_(20, 0.35)
                text_font = NSFont.systemFontOfSize_(13)
                small_font = NSFont.systemFontOfSize_(12)

                title = NSTextField.labelWithString_('mdPreview')
                title.setFrame_(NSMakeRect(0, 100, width, 26))
                title.setAlignment_(NSCenterTextAlignment)
                title.setFont_(title_font)
                title.setTextColor_(NSColor.labelColor())
                content.addSubview_(title)

                version = NSTextField.labelWithString_('Version ' + _get_current_version())
                version.setFrame_(NSMakeRect(0, 72, width, 20))
                version.setAlignment_(NSCenterTextAlignment)
                version.setFont_(text_font)
                version.setTextColor_(NSColor.secondaryLabelColor())
                content.addSubview_(version)

                credit = NSTextField.labelWithString_('Opensourced on GitHub\n©tahoeliu')
                credit.setFrame_(NSMakeRect(0, 12, width, 44))
                credit.setAlignment_(NSCenterTextAlignment)
                credit.setFont_(small_font)
                credit.setTextColor_(NSColor.secondaryLabelColor())
                credit.setEditable_(False)
                credit.setSelectable_(True)
                credit.setBezeled_(False)
                credit.setDrawsBackground_(False)
                credit.setUsesSingleLineMode_(False)
                credit.setLineBreakMode_(NSLineBreakByWordWrapping)
                try:
                    credit.cell().setWraps_(True)
                except Exception:
                    pass
                content.addSubview_(credit)

                try:
                    github_url = NSURL.URLWithString_('https://github.com/tahoeliu/mdPreview')
                    mail_url = NSURL.URLWithString_('mailto:tianoncall@gmail.com')
                    credit.setAllowsEditingTextAttributes_(True)
                    line_text = 'Opensourced on GitHub\n©tahoeliu'
                    attr = NSMutableAttributedString.alloc().initWithString_(line_text)
                    paragraph = NSMutableParagraphStyle.alloc().init()
                    paragraph.setAlignment_(NSCenterTextAlignment)
                    attr.addAttribute_value_range_(NSFontAttributeName, small_font, NSMakeRange(0, attr.length()))
                    attr.addAttribute_value_range_(NSParagraphStyleAttributeName, paragraph, NSMakeRange(0, attr.length()))
                    gh_start = line_text.index('GitHub')
                    attr.addAttribute_value_range_('NSLink', github_url, NSMakeRange(gh_start, len('GitHub')))
                    ct_start = line_text.index('©tahoeliu')
                    attr.addAttribute_value_range_('NSLink', mail_url, NSMakeRange(ct_start, len('©tahoeliu')))
                    credit.setAttributedStringValue_(attr)
                except Exception:
                    pass

                panel.center()
                panel.makeKeyAndOrderFront_(None)
                _about_window_ref = panel
            except Exception:
                log_exception('show custom about failed')
                try:
                    NSApplication.sharedApplication().orderFrontStandardAboutPanel_(sender)
                except Exception:
                    pass

        def setupAllMenusRetry_(self, sender):
            setup_all_menus()

    _view_menu_handler = ViewMenuHandler.alloc().init()

    def patch_app_delegate():
        try:
            import webview.platforms.cocoa as cocoa
            AppDelegateClass = cocoa.BrowserView.AppDelegate

            def applicationShouldTerminateAfterLastWindowClosed_(self, application):
                return False

            def applicationShouldTerminate_(self, application):
                if _QUIT_APPROVED.is_set():
                    from mdpreview_core.settings import settings
                    from mdpreview_core.watcher import watcher
                    if settings(load_config())['restore_session']:
                        update_config({'session': [api.file_path for api in list(_window_apis.values()) if api.file_path and not api.is_untitled]})
                    watcher.stop.set()
                    _QUIT_REQUESTED.set()
                    return 1
                _begin_quit_confirmation()
                return 0  # NSTerminateCancel until each document has approved.

            def applicationShouldHandleReopen_hasVisibleWindows_(self, application, flag):
                """Dock icon click.

                Standard macOS document-app behavior: clicking the Dock icon
                must NOT spawn a new document when windows already exist. It
                only un-hides a hidden blank window (from a previous
                close-last-window) or, as a defensive fallback when the app has
                no windows at all, creates one.
                """
                try:
                    if _reopen_hidden_window():
                        return True
                    if _window_apis:
                        # Windows exist (visible or hidden); app activation
                        # already brings them forward — do not create a new one.
                        return True
                    _create_window_safely(None)
                    return True
                except Exception:
                    log_exception('handle reopen failed')
                    return True

            def application_openFiles_(self, application, filenames):
                global _initial_file_handled
                count = filenames.count()
                logging.info('openFiles received: %d file(s)', count)
                for i in range(count):
                    path = str(filenames.objectAtIndex_(i))
                    handle_opened_file(path, _main_window_ref, _main_api_ref)
                application.replyToOpenOrPrint_(0)

            # NOTE: do NOT use objc.classAddMethod here. pywebview's AppDelegate
            # already defines applicationShouldTerminate_ (signature I@:@), and
            # classAddMethod raises BadPrototypeError for existing selectors,
            # which previously aborted the whole patch and left
            # application:openFiles: unregistered — breaking Finder double-click
            # open ("cannot open files in the Markdown Document format").
            # Class-attribute assignment via objc.selector both adds new methods
            # and overrides existing ones, with explicit ObjC signatures.
            def _install(py_name, sel_name, func, signature):
                wrapped = objc.selector(func, selector=sel_name, signature=signature)
                setattr(AppDelegateClass, py_name, wrapped)
                if not AppDelegateClass.instancesRespondToSelector_(sel_name):
                    raise RuntimeError('selector not installed: %r' % sel_name)

            installs = [
                ('applicationShouldTerminateAfterLastWindowClosed_',
                 b'applicationShouldTerminateAfterLastWindowClosed:',
                 applicationShouldTerminateAfterLastWindowClosed_, b'c@:@'),
                ('applicationShouldTerminate_',
                 b'applicationShouldTerminate:',
                 applicationShouldTerminate_, b'I@:@'),
                ('applicationShouldHandleReopen_hasVisibleWindows_',
                 b'applicationShouldHandleReopen:hasVisibleWindows:',
                 applicationShouldHandleReopen_hasVisibleWindows_, b'c@:@c'),
                ('application_openFiles_',
                 b'application:openFiles:',
                 application_openFiles_, b'v@:@@'),
            ]
            for py_name, sel_name, func, signature in installs:
                try:
                    _install(py_name, sel_name, func, signature)
                except Exception:
                    log_exception('install delegate method failed: %r' % sel_name)
        except Exception:
            log_exception('patch app delegate failed')

    def patch_window_close_behavior():
        """Override windowWillClose_ to keep per-window teardown correct.

        pywebview's WindowDelegate.windowWillClose_ stops the NSApp runloop when
        the last window closes, which exits webview.start() and lets main() hit
        os._exit(0). With the blank-Untitled behavior in on_window_closing(), a
        clean last-window close is intercepted before it reaches here, so the
        app normally stays alive with a valid Untitled window. For the rare case
        where the last window really does close (e.g. the user forced close of a
        dirty document), we mirror pywebview's own cleanup and stop the runloop so
        the process exits cleanly instead of leaving a dead anchor window that
        breaks subsequent window creation.
        """
        try:
            import webview.platforms.cocoa as cocoa
            WD = cocoa.BrowserView.WindowDelegate

            def windowWillClose_(self, notification):
                i = cocoa.BrowserView.get_instance('window', notification.object())
                if i is None:
                    return
                # Per-window teardown (mirrors pywebview's own cleanup).
                i.webview.setNavigationDelegate_(None)
                i.webview.setUIDelegate_(None)
                del cocoa.BrowserView.instances[i.uid]
                if i.pywebview_window in webview.windows:
                    webview.windows.remove(i.pywebview_window)
                i.webview.loadHTMLString_baseURL_('', None)
                i.webview.removeFromSuperview()
                i.webview = None
                i.closed.set()
                if cocoa.BrowserView.instances == {}:
                    cocoa.BrowserView.app.setDelegate_(None)
                    cocoa.BrowserView._shared_app_delegate = None
                    cocoa.BrowserView.app.stop_(self)
                    cocoa.BrowserView.app.abortModal()

            WD.windowWillClose_ = objc.selector(
                windowWillClose_, selector=b'windowWillClose:', signature=b'v@:@')
            if not WD.instancesRespondToSelector_(b'windowWillClose:'):
                raise RuntimeError('windowWillClose: not installed')
        except Exception:
            log_exception('patch window close behavior failed')


def _start_log(stage):
    try:
        logging.info('[startup] %s: %.0fms' % (stage, (time.time() - _START_T0) * 1000))
    except Exception:
        pass


def _register_quicklook():
    """Finder 空格预览：把应用内置的预览扩展登记并启用（每个版本/位置只做一次）。"""
    if os.environ.get('MDPREVIEW_DATA_DIR') or not getattr(sys, 'frozen', False):
        return
    appex = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(sys.executable))), 'PlugIns', 'MDPreviewQuickLook.appex')
    if not os.path.isdir(appex):
        return
    stamp = _get_current_version() + '|' + appex
    config = load_config()
    if config.get('quicklook_registered') == stamp:
        return
    import subprocess
    for args in (['/usr/bin/pluginkit', '-a', appex], ['/usr/bin/pluginkit', '-e', 'use', '-i', 'tahoeliu.mdpreview.quicklook']):
        subprocess.run(args, capture_output=True, timeout=20, check=False)
    config['quicklook_registered'] = stamp
    save_config(config)


def main():
    global _initial_file_handled
    global _main_window_ref, _main_api_ref, _active_window_ref

    if '--headless-export' in sys.argv:
        from mdpreview_core.headless import run
        arguments = sys.argv[sys.argv.index('--headless-export') + 1:]
        os.environ['MDPREVIEW_DISABLE_UPDATES'] = '1'
        try:
            from mdpreview_core.csp_bridge import install
            install(get_resource_path)
            patch_evaluate_js()
            code = run(arguments, MarkdownAPI, get_resource_path)
        except Exception:
            print('headless: initialization or native export failed', file=sys.stderr)
            code = 2
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)
    from mdpreview_core.csp_bridge import install
    install(get_resource_path)
    _start_log('main entered')
    if HAS_COCOA:
        try:
            # One document per window: hides AppKit's "Show Tab Bar" menu items.
            from AppKit import NSWindow
            NSWindow.setAllowsAutomaticWindowTabbing_(False)
        except Exception:
            log_exception('disable window tabbing failed')
        patch_app_delegate()
        patch_window_close_behavior()
        patch_evaluate_js()

    file_paths = []
    valid_extensions = ('.md', '.markdown', '.mdown', '.mkd', '.mkdown', '.txt')
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg and os.path.exists(arg) and arg.lower().endswith(valid_extensions):
                file_paths.append(os.path.abspath(arg))
    file_path = file_paths[0] if file_paths else None

    if file_path:
        _initial_file_handled = True
        # macOS also delivers argv files as application:openFiles:; register
        # the path now so that event focuses this window instead of opening a
        # duplicate.
        with _state_lock:
            _opened_files.add(os.path.abspath(file_path))

    main_api = MarkdownAPI(file_path)
    html_path = get_resource_path('index.html')
    title = os.path.basename(file_path) if file_path else 'Untitled.md'

    _start_log('before create_window')
    geometry = _saved_window_geometry()
    main_window = webview.create_window(
        title=title,
        url=html_path,
        js_api=main_api,
        width=geometry.get('width', 900),
        height=geometry.get('height', 680),
        x=geometry.get('x'), y=geometry.get('y'),
        min_size=(680, 400),
        text_select=True,
        confirm_close=False,
    )
    _start_log('after create_window')
    main_api.window = main_window
    _window_apis[id(main_window)] = main_api
    _main_window_ref = main_window
    _main_api_ref = main_api
    _active_window_ref = main_window
    _window_count[0] = 1  # count the main window so subsequent windows are offset

    for extra_path in file_paths[1:]:
        create_window(extra_path)

    if HAS_COCOA:
        # Official pywebview mechanism: subscribe to the 'closing' event.
        # Returning False from the handler cancels the close.
        main_window.events.closing += on_window_closing
        _subscribe_js_ready(main_window)
        setup_view_menu()
        setup_file_menu()

    # Post-startup tasks: run after the runloop starts so they don't delay
    # window display. These are non-critical for the initial render.
    if HAS_COCOA:
        def _post_startup():
            time.sleep(0.5)
            try:
                from mdpreview_core.settings import settings
                if settings(load_config())['restore_session']:
                    for saved_path in load_config().get('session', [])[:300]:
                        if isinstance(saved_path, str) and os.path.isfile(saved_path):
                            handle_opened_file(saved_path, main_window, main_api)
                _check_pending_install()
            except Exception:
                pass
            try:
                _register_quicklook()
            except Exception:
                pass
            try:
                time.sleep(1.2)
                _offer_default_handler()
            except Exception:
                pass
        threading.Thread(target=_post_startup, daemon=True).start()
        if not os.environ.get('MDPREVIEW_DISABLE_UPDATES'):
            _schedule_startup_update_check()
    _start_quit_watchdog()
    _maybe_run_selftest(main_window)

    _start_log('before webview.start')
    webview.start(debug=False)
    _start_log('after webview.start')

    # ── Instant exit ──
    # At this point webview.start() has returned, meaning all windows are
    # closed, the runloop has stopped, all drafts/config are persisted by
    # on_window_closing. The Python interpreter would now try to join
    # non-daemon pywebview bridge threads (which can be stuck in semaphore
    # waits for EVALUATE_JS_TIMEOUT), causing a 1-2 second hang with a
    # spinning cursor. Since there is nothing left to do, exit immediately.
    os._exit(0)


def _maybe_run_selftest(main_window):
    """Hidden self-test flags to verify the quit path end-to-end.

    --selftest-close : closes the main window via window.destroy() after a
                       short delay (exercises the red-close-button path).
    --selftest-quit  : calls NSApplication terminate after a delay (exercises
                       the Cmd+Q / Quit-menu path).
    Both modes are used by the test harness: the process must exit on its own
    (no forced kill) within a reasonable timeout.
    """
    if not HAS_COCOA:
        return

    def _close_after(delay):
        time.sleep(delay)
        try:
            main_window.destroy()
        except Exception:
            os._exit(3)

    def _quit_after(delay):
        time.sleep(delay)
        try:
            AppHelper.callAfter(lambda: NSApplication.sharedApplication().terminate_(None))
        except Exception:
            os._exit(3)

    if '--selftest-integrity' in sys.argv:
        def run_integrity():
            if not _UI_READY.wait(120):
                os._exit(5)
            with open(get_resource_path('tests/native-check.js')) as stream:
                script = stream.read()
            _dispatch_js_to(main_window, script)
        threading.Thread(target=run_integrity, daemon=True).start()
    elif '--selftest-close' in sys.argv:
        threading.Thread(target=_close_after, args=(4.0,), daemon=True).start()
    elif '--selftest-quit' in sys.argv:
        threading.Thread(target=_quit_after, args=(4.0,), daemon=True).start()


# ── Auto-update check ──
DOWNLOAD_URL = 'https://github.com/tahoeliu/mdPreview/releases/latest'
CHECK_INTERVAL = 604800  # 7 days
STARTUP_UPDATE_DELAY = 30  # seconds


def _get_current_version():
    """Read the app's version from Info.plist (works in PyInstaller bundle)."""
    try:
        from Foundation import NSBundle
        info = NSBundle.mainBundle().infoDictionary()
        value = info.get('CFBundleShortVersionString') if info else None
        if value:
            return value
        return open(get_resource_path('VERSION')).read().strip()
    except Exception:
        try:
            return open(get_resource_path('VERSION')).read().strip()
        except OSError:
            return '0.0.0'


def _fetch_latest_version():
    """Get the latest release version by following the GitHub releases/latest redirect.

    This avoids the GitHub API rate limit (60 req/hour for unauthenticated API calls)
    by using the HTML redirect instead: releases/latest -> releases/tag/vX.Y.Z
    """
    import urllib.request
    url = 'https://github.com/tahoeliu/mdPreview/releases/latest'
    req = urllib.request.Request(url, headers={'User-Agent': 'mdPreview'})
    # Don't follow redirects automatically — we want the Location header
    class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None  # don't follow — let it raise
    opener = urllib.request.build_opener(NoRedirectHandler)
    try:
        opener.open(req, timeout=5)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            location = e.headers.get('Location', '')
            # location = 'https://github.com/tahoeliu/mdPreview/releases/tag/v1.2.4'
            tag = location.rstrip('/').split('/')[-1]  # 'v1.2.4'
            return tag.lstrip('v') if tag else None
    except Exception:
        pass
    return None


def _is_newer(remote, local):
    """Compare dot-separated version strings."""
    try:
        r = [int(x) for x in remote.split('.')]
        l = [int(x) for x in local.split('.')]
        # Pad to same length
        while len(r) < len(l): r.append(0)
        while len(l) < len(r): l.append(0)
        return r > l
    except Exception:
        return False


def _should_check_update():
    """Return True if enough time has passed since the last check."""
    cfg = load_config()
    from mdpreview_core.settings import settings
    if not settings(cfg)['auto_update']:
        return False
    last = cfg.get('last_update_check', 0)
    return (time.time() - last) >= CHECK_INTERVAL


def _mark_update_checked():
    cfg = load_config()
    update_config({'last_update_check': time.time()})


def _set_update_available(remote_version):
    """Remember that an update is available, auto-download, and show bubble."""
    global _available_update_version
    _available_update_version = remote_version
    if HAS_COCOA:
        def _update_menu():
            try:
                if _update_menu_item:
                    _update_menu_item.setTitle_(_t('Update Available: {version}...', '有可用更新：{version}…').format(version=remote_version))
            except Exception:
                pass
        AppHelper.callAfter(_update_menu)
    # Auto-download in background to hidden staging dir (silent by design:
    # no progress UI). When staging succeeds the install bubble appears.
    def _bg_download():
        result = _download_and_extract(remote_version)
        if result and 'staging_app' in result:
            update_config({'pending_staging_app': result['staging_app'], 'pending_update_version': result['version']}, remove=('pending_update_dmg',))
            if HAS_COCOA:
                AppHelper.callAfter(lambda: _dispatch_js('showUpdateBubble()'))
        # Failures stay silent: already logged inside _download_and_extract.
    threading.Thread(target=_bg_download, daemon=True).start()


def _clear_update_available():
    """Clear remembered update availability and restore the menu title."""
    global _available_update_version
    _available_update_version = None
    if HAS_COCOA:
        def _update_menu():
            try:
                if _update_menu_item:
                    _update_menu_item.setTitle_(_t('Check for Updates…', '检查更新…'))
            except Exception:
                pass
        AppHelper.callAfter(_update_menu)


def _show_update_alert(remote_version):
    """Show a modal alert offering to download the update.

    If user clicks Download, starts auto-download to staging dir in a
    background thread. When download completes, shows the update bubble.
    Returns True if the user clicked Download, False otherwise.
    """
    if not HAS_COCOA:
        return False
    try:
        local = _get_current_version()
        alert = NSAlert.alloc().init()
        alert.setMessageText_(_t('mdPreview {version} is available!', 'mdPreview {version} 已可用！').format(version=remote_version))
        alert.setInformativeText_(_t('You have version {version}. Would you like to download the update?', '当前版本为 {version}。是否下载更新？').format(version=local))
        alert.addButtonWithTitle_(_t('Download', '下载'))
        alert.addButtonWithTitle_(_t('Later', '稍后'))
        response = alert.runModal()
        if response == 1000:  # Download
            version_arg = json.dumps(remote_version)
            AppHelper.callAfter(lambda: _dispatch_js("showUpdateDownloadProgress(0)"))
            AppHelper.callAfter(lambda: _dispatch_js(f"window.pywebview.api.download_update_with_progress({version_arg})"))
            return True
        return False
    except Exception:
        return False


def _staged_version_acceptable(staged_version, local_version):
    try:
        return version_tuple(staged_version) >= version_tuple(local_version)
    except ValueError:
        return False


def _download_and_extract_unlocked(version, progress_callback=None, keep_dmg=False):
    from mdpreview_core.update_download import download, classify
    from mdpreview_core.release_sig import configured
    try:
        return download(version, _get_current_version(), UPDATE_STAGING_DIR, _publisher_team_id(), progress_callback)
    except Exception as error:
        code = classify(error)
        if code == 'unknown':
            log_exception('update download failed')
        if not configured():
            detail = _t('Updates are unavailable: this build has no release signing key.', '更新不可用：此版本未内置发布签名公钥。')
        elif code == 'network':
            detail = _t('Network error while downloading the update.', '下载更新时网络出错。')
        elif code == 'incomplete':
            detail = _t('The update download was incomplete or too large.', '更新包下载不完整或体积异常。')
        elif code == 'verify':
            detail = _t('The update could not be verified and was discarded.', '更新包校验失败，已丢弃。')
        else:
            detail = _t('Unexpected error while downloading the update.', '下载更新时发生未知错误。')
        return {'error': code, 'detail': detail}


def _manual_download_update_with_progress(version):
    """Download a manually requested update and report progress to the UI.

    Progress (percent) is shown in the top-right bubble. On failure the bubble
    shows a short reason and a status bar entry carries the detailed cause.
    On success the same "click to install" bubble as the auto-download path
    is shown.
    """
    def _progress(percent):
        if HAS_COCOA:
            AppHelper.callAfter(lambda p=percent: _dispatch_js(f'showUpdateDownloadProgress({int(p)})'))

    result = _download_and_extract(version, progress_callback=_progress, keep_dmg=True)
    if not result or 'staging_app' not in result:
        err = (result or {}).get('error', 'unknown')
        detail = (result or {}).get('detail', '')
        if HAS_COCOA:
            detail_js = json.dumps(detail or '')
            AppHelper.callAfter(
                lambda c=err, d=detail_js: _dispatch_js(f"showUpdateDownloadFailed('{c}', {d})")
            )
        return {'success': False, 'error': err, 'detail': detail}

    update_config({'pending_staging_app': result['staging_app'], 'pending_update_version': result['version'], 'pending_update_dmg': result.get('dmg_path', '')})
    if HAS_COCOA:
        AppHelper.callAfter(lambda: _dispatch_js('showUpdateBubble()'))
    return {'success': True}


def _schedule_startup_update_check():
    """Schedule a low-friction automatic update check after app launch.

    Automatic checks are intentionally quiet:
    - wait STARTUP_UPDATE_DELAY seconds after launch
    - run at most once every CHECK_INTERVAL (7 days)
    - fail silently on network errors
    - if an update exists, auto-download to staging dir and show a
      non-blocking update bubble in the top-right corner.
    """
    if not HAS_COCOA:
        return

    def _delayed_check():
        try:
            time.sleep(STARTUP_UPDATE_DELAY)
            if not _should_check_update():
                return
            remote = _fetch_latest_version()
            if not remote:
                # Network failure: do NOT consume the 7-day interval — the
                # next launch retries (one lightweight request is cheap).
                return
            _mark_update_checked()
            local = _get_current_version()
            if _is_newer(remote, local):
                _set_update_available(remote)
            else:
                _clear_update_available()
        except Exception:
            pass

    threading.Thread(target=_delayed_check, daemon=True).start()


def _manual_check_up_to_date():
    """Alert for manual check when already on latest version.

    Also offers "Re-download Latest": reinstalls the current latest release
    with the download progress shown in the update bubble (useful to repair
    an installation or pick up a re-uploaded DMG).
    """
    if not HAS_COCOA:
        return
    try:
        local = _get_current_version()
        alert = NSAlert.alloc().init()
        alert.setMessageText_(_t("You're up to date!", "已是最新版本！"))
        alert.setInformativeText_(_t('mdPreview {version} is the latest version.', 'mdPreview {version} 已是最新版本。').format(version=local))
        alert.addButtonWithTitle_(_t('Re-download Latest', '重新下载最新版'))
        alert.addButtonWithTitle_(_t('OK', '好'))
        response = alert.runModal()
        if response == 1000:  # Re-download Latest
            version_arg = json.dumps(local)
            AppHelper.callAfter(lambda: _dispatch_js("showUpdateDownloadProgress(0)"))
            AppHelper.callAfter(lambda: _dispatch_js(f"window.pywebview.api.download_update_with_progress({version_arg})"))
    except Exception:
        pass


def _manual_check_error():
    """Alert for manual check when the network request fails."""
    if not HAS_COCOA:
        return
    try:
        alert = NSAlert.alloc().init()
        alert.setMessageText_(_t('Could not check for updates.', '无法检查更新。'))
        alert.setInformativeText_(_t('Please check your internet connection and try again later.', '请检查网络连接后重试。'))
        alert.addButtonWithTitle_('OK')
        alert.runModal()
    except Exception:
        pass


_toggle_menu_item = None


def _apply_toggle_shortcut(spec):
    """Give the View ▸ Toggle Preview / Source menu item the user's chosen shortcut (e.g. 'cmd+shift+e')."""
    item = _toggle_menu_item
    if item is None or not spec:
        return
    parts = spec.split('+')
    masks = {'cmd': 1 << 20, 'shift': 1 << 17, 'ctrl': 1 << 18, 'alt': 1 << 19}
    mask = 0
    for name in parts[:-1]:
        mask |= masks.get(name, 0)
    item.setKeyEquivalent_(parts[-1])
    item.setKeyEquivalentModifierMask_(mask)


def _share_active_document(x=None, y=None):
    """Open the system Share sheet for the front document (file if saved and unchanged, else its text)."""
    try:
        from AppKit import NSSharingServicePicker
        from Foundation import NSURL, NSMakeRect
        from webview.platforms.cocoa import BrowserView
        ref = _get_target_window()
        api = _window_apis.get(id(ref)) if ref else None
        browser = BrowserView.instances.get(ref.uid) if ref else None
        if api is None or browser is None:
            return
        path = api.file_path
        if path and os.path.isfile(path) and not api.is_dirty:
            items = [NSURL.fileURLWithPath_(path)]
        else:
            text = api.cached_content or ''
            if not text.strip():
                return
            items = [text]
        picker = NSSharingServicePicker.alloc().initWithItems_(items)
        view = browser.webview
        bounds = view.bounds()
        flipped = bool(view.isFlipped())
        if x is None or y is None:
            ax, ay = bounds.size.width - 44, 6
        else:
            ax, ay = float(x), float(y)
        anchor = NSMakeRect(ax, ay if flipped else bounds.size.height - ay, 1, 1)
        picker.showRelativeToRect_ofView_preferredEdge_(anchor, view, 3 if flipped else 1)
    except Exception:
        log_exception('share failed')


def _current_markdown_handler():
    try:
        try:
            from LaunchServices import LSCopyDefaultRoleHandlerForContentType, kLSRolesAll
        except Exception:
            from CoreServices import LSCopyDefaultRoleHandlerForContentType, kLSRolesAll
        return LSCopyDefaultRoleHandlerForContentType('net.daringfireball.markdown', kLSRolesAll)
    except Exception:
        return None


def _set_default_markdown_app(announce=False):
    """由用户明确同意后才把 mdPreview 设为 .md 默认应用。"""
    result = MarkdownAPI().set_as_default_for_md()
    if announce:
        ok = bool(result.get('success'))
        _dispatch_js_to_active("showStatus(%s,%s)" % (json.dumps(_t('mdPreview is now the default for Markdown files.', 'mdPreview 已设为 Markdown 文件的默认打开方式。') if ok else _t('Could not change the default app. Use Finder: Get Info → Open with.', '无法更改默认应用，请在访达中“显示简介 → 打开方式”里设置。')), 'false' if ok else 'true'))
    return result


def _dispatch_js_to_active(code):
    try:
        ref = _get_target_window()
        if ref is not None:
            _dispatch_js_to(ref, code)
    except Exception:
        pass


def _offer_default_handler():
    """首次启动只问一次：要不要用 mdPreview 打开 .md 文件。"""
    if not HAS_COCOA or os.environ.get('MDPREVIEW_DATA_DIR') or os.environ.get('MDPREVIEW_DISABLE_UPDATES'):
        return
    if load_config().get('default_handler_offered'):
        return
    update_config({'default_handler_offered': True})
    current = (_current_markdown_handler() or '')
    if current.lower() == 'tahoeliu.mdpreview':
        return
    if 'mdpreview' in current.lower():
        # An earlier mdPreview build the user already chose: carry the choice over silently.
        _set_default_markdown_app()
        return
    def ask():
        try:
            from AppKit import NSAlert, NSAlertFirstButtonReturn
            alert = NSAlert.alloc().init()
            alert.setMessageText_(_t('Open Markdown files with mdPreview?', '用 mdPreview 打开 Markdown 文件？'))
            alert.addButtonWithTitle_(_t('Use mdPreview', '使用 mdPreview'))
            alert.addButtonWithTitle_(_t('Not Now', '暂不'))
            try:
                from AppKit import NSApp
                NSApp.activateIgnoringOtherApps_(True)  # an inactive app draws the main button grey
                alert.buttons()[0].setKeyEquivalent_('\r')
            except Exception:
                pass
            if alert.runModal() == NSAlertFirstButtonReturn:
                _set_default_markdown_app(announce=True)
        except Exception:
            log_exception('default handler offer failed')
    from PyObjCTools import AppHelper
    AppHelper.callAfter(ask)


def _try_set_default_handler():
    """On first launch, register mdPreview as the default app for .md files."""
    if not HAS_COCOA:
        return
    try:
        cfg = load_config()
        if cfg.get('default_handler_set'):
            return  # Already done
        api = MarkdownAPI()
        result = api.set_as_default_for_md()
        if result.get('success'):
            update_config({'default_handler_set': True})
    except Exception:
        log_exception('set default handler failed')


def _check_pending_install():
    """On app launch, check if a staged update exists and show the bubble."""
    if not HAS_COCOA or os.environ.get('MDPREVIEW_DISABLE_UPDATES'):
        return
    try:
        cfg = load_config()
        staging_app = cfg.get('pending_staging_app', '')
        version = cfg.get('pending_update_version', '')
        if staging_app and os.path.exists(staging_app):
            local = _get_current_version()
            if not _is_newer(version, local):
                # Already updated — clean up staging
                cfg.pop('pending_staging_app', None)
                cfg.pop('pending_update_version', None)
                update_config(remove=('pending_staging_app', 'pending_update_version', 'pending_update_dmg'))
                if os.path.commonpath([os.path.realpath(staging_app), os.path.realpath(UPDATE_STAGING_DIR)]) == os.path.realpath(UPDATE_STAGING_DIR):
                    shutil.rmtree(staging_app, ignore_errors=True)
                return
            # Show the update bubble (non-blocking)
            global _available_update_version
            _available_update_version = version
            if _update_menu_item:
                def _update_menu():
                    try:
                        _update_menu_item.setTitle_(_t('Update Available: {version}...', '有可用更新：{version}…').format(version=version))
                    except Exception:
                        pass
                AppHelper.callAfter(_update_menu)
            AppHelper.callAfter(lambda: _dispatch_js('showUpdateBubble()'))
        else:
            # Clean up stale config entries
            if 'pending_staging_app' in cfg or 'pending_update_dmg' in cfg:
                cfg.pop('pending_staging_app', None)
                cfg.pop('pending_update_version', None)
                cfg.pop('pending_update_dmg', None)
                update_config(remove=('pending_staging_app', 'pending_update_version', 'pending_update_dmg'))
    except Exception:
        log_exception('pending update recovery failed')


def _smoke_test_app(app_path, timeout=20):
    import subprocess
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix='mdpreview-smoke-') as temporary:
            marker = os.path.join(temporary, 'UpdateStaging', 'ready.json')
            environment = dict(os.environ, MDPREVIEW_DATA_DIR=temporary, MDPREVIEW_DISABLE_UPDATES='1')
            process = subprocess.Popen([os.path.join(app_path, 'Contents/MacOS/mdPreview'),
                                        '--update-ready', marker], env=environment,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    return False
                if os.path.exists(marker):
                    with open(marker) as stream:
                        return json.load(stream).get('pid') == process.pid
                time.sleep(0.1)
            return False
    except Exception:
        log_exception('smoke test failed')
        return False
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def _perform_auto_install():
    global _pending_install_plan
    import subprocess
    try:
        cfg = load_config()
        staged = cfg.get('pending_staging_app')
        version = cfg.get('pending_update_version')
        if not staged or os.path.commonpath([os.path.realpath(staged), os.path.realpath(UPDATE_STAGING_DIR)]) != os.path.realpath(UPDATE_STAGING_DIR):
            raise ValueError('No trusted staged application')
        from pathlib import Path
        from mdpreview_core.release_zip import extract_verified
        signed_job = Path(staged).parent.parent
        archives = list(signed_job.glob('mdPreview-*.zip'))
        if len(archives) != 1:
            raise ValueError('signed-archive-required')
        archive = archives[0]
        manifest, signature = signed_job / 'SHA256SUMS', signed_job / 'SHA256SUMS.sig'
        staged = str(extract_verified(archive, manifest, signature,
                                      signed_job / ('install-' + uuid.uuid4().hex)))
        team_id = _publisher_team_id()
        verify_bundle(staged, team_id, version)
        if not _smoke_test_app(staged):
            raise RuntimeError('Update did not reach a ready UI')
        if not getattr(sys, 'frozen', False):
            raise ValueError('update-requires-running-bundle')
        from mdpreview_core.release import installation_identity, check_startup_snapshot
        if _STARTUP_BUNDLE_SNAPSHOT is None:
            raise ValueError('startup-identity-unavailable-restart-required')
        destination = Path(_STARTUP_BUNDLE_SNAPSHOT['path'])
        check_startup_snapshot(destination, _STARTUP_BUNDLE_SNAPSHOT)
        destination_identity = installation_identity(destination)
        check_startup_snapshot(destination, _STARTUP_BUNDLE_SNAPSHOT)
        if destination_identity['version'] != _get_current_version():
            raise ValueError('running-bundle-version-mismatch')
        job = os.path.dirname(staged)
        plan = {'pid': os.getpid(), 'staging': staged, 'destination': str(destination),
                'destinationIdentity': destination_identity,
                'startupIdentity': dict(_STARTUP_BUNDLE_SNAPSHOT),
                'teamId': team_id, 'version': version,
                'archive': str(archive), 'manifest': str(manifest), 'signature': str(signature),
                'ready': os.path.join(UPDATE_STAGING_DIR, 'install-ready.json'),
                'log': os.path.join(UPDATE_STAGING_DIR, 'install.log')}
        plan_path = os.path.join(job, 'install-plan.json')
        _safe_write_text(plan_path, json.dumps(plan))
        def launch_helper():
            check_startup_snapshot(destination, _STARTUP_BUNDLE_SNAPSHOT)
            subprocess.Popen([os.path.join(staged, 'Contents/MacOS/mdPreview'),
                              '--install-update-helper', '--plan', plan_path],
                             start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            update_config(remove=('pending_staging_app', 'pending_update_version', 'pending_update_dmg'))
        _pending_install_plan = launch_helper
        AppHelper.callAfter(_begin_quit_confirmation)
        return {'success': True}
    except Exception as exc:
        log_exception('auto install failed')
        return {'success': False, 'error': str(exc), 'manual_install': True,
                'manual_dmg_path': load_config().get('pending_update_dmg', '')}





_QUIT_APPROVED = threading.Event()
_UI_READY = threading.Event()
_quit_confirmation_queue = []
_quit_confirmation_active = False


def _begin_quit_confirmation():
    global _quit_confirmation_active
    if _quit_confirmation_active:
        return
    _quit_confirmation_active = True
    for api in _window_apis.values():
        _dispatch_js_to(api.window, 'setQuitFrozen(true)')
    _quit_confirmation_queue[:] = list(_window_apis.values())
    _advance_quit_confirmation()


def _advance_quit_confirmation():
    if _quit_confirmation_queue:
        api = _quit_confirmation_queue[0]
        _dispatch_js_to(api.window, 'confirmQuitDocument()')
    else:
        global _pending_install_plan
        if _pending_install_plan:
            try:
                _pending_install_plan()
            except Exception:
                log_exception('update helper launch failed')
                _cancel_quit_confirmation()
                return
            _pending_install_plan = None
        _QUIT_APPROVED.set()
        AppHelper.callAfter(lambda: NSApplication.sharedApplication().terminate_(None))


def _finish_quit_confirmation(api, approved):
    global _quit_confirmation_active, _pending_install_plan
    if not _quit_confirmation_queue or _quit_confirmation_queue[0] is not api:
        return
    if not approved:
        _cancel_quit_confirmation()
        return
    _quit_confirmation_queue.pop(0)
    _advance_quit_confirmation()


_update_download_lock = threading.Lock()
_pending_install_plan = None


def _publisher_team_id():
    # Bundled apps carry the policy at the bundle root; the source tree keeps it in packaging/.
    path = get_resource_path('release-policy.json')
    if not os.path.exists(path):
        path = get_resource_path(os.path.join('packaging', 'release-policy.json'))
    with open(path) as stream:
        return json.load(stream).get('teamId')


def _download_and_extract(version, progress_callback=None, keep_dmg=False):
    if not _update_download_lock.acquire(blocking=False):
        return {'error': 'busy', 'detail': _t('An update is already downloading.', '更新正在下载中。')}
    try:
        return _download_and_extract_unlocked(version, progress_callback, keep_dmg)
    finally:
        _update_download_lock.release()


def _cancel_quit_confirmation():
    global _quit_confirmation_active, _pending_install_plan
    _quit_confirmation_queue.clear()
    _quit_confirmation_active = False
    _pending_install_plan = None
    _QUIT_APPROVED.clear()
    for api in _window_apis.values():
        _dispatch_js_to(api.window, 'setQuitFrozen(false)')


if __name__ == '__main__':
    main()
