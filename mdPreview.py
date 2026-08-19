#!/usr/bin/env python3
"""
Minimal Markdown Viewer for macOS
"""

import sys
import os
import json
import time
import threading
import tempfile
import shutil
import hashlib
import logging
import webview

_START_T0 = time.time()  # cold-start profiling

APP_SUPPORT_DIR = os.path.expanduser('~/Library/Application Support/mdPreview')
CONFIG_FILE = os.path.join(APP_SUPPORT_DIR, 'config.json')
LEGACY_CONFIG_FILE = os.path.expanduser('~/.mdviewer_config.json')
LOG_FILE = os.path.expanduser('~/Library/Logs/mdPreview.log')
DRAFT_DIR = os.path.join(APP_SUPPORT_DIR, 'Drafts')
UPDATE_STAGING_DIR = os.path.join(APP_SUPPORT_DIR, 'UpdateStaging')


def _setup_logging():
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        logging.basicConfig(
            filename=LOG_FILE,
            level=logging.INFO,
            format='%(asctime)s %(levelname)s %(message)s',
        )
    except Exception:
        pass


def log_exception(context):
    try:
        logging.exception(context)
    except Exception:
        pass


_setup_logging()


def _is_chinese_locale():
    lang = os.environ.get('LANG', '') or os.environ.get('LC_ALL', '')
    return lang.lower().startswith('zh')


def _t(en, zh):
    return zh if _is_chinese_locale() else en


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
    """Safely write text via temp file + fsync + atomic replace."""
    target = os.path.abspath(path)
    directory = os.path.dirname(target) or os.getcwd()
    os.makedirs(directory, exist_ok=True)
    fd = None
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix='.' + os.path.basename(target) + '.', suffix='.tmp', dir=directory)
        with os.fdopen(fd, 'w', encoding=encoding, newline='') as f:
            fd = None
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
        tmp_path = None
        _fsync_directory(directory)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


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
            return raw.decode('utf-16'), 'utf-16'
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


def _write_draft(path, content):
    """Persist an autosave draft under Application Support without touching originals."""
    try:
        os.makedirs(DRAFT_DIR, exist_ok=True)
        name = _draft_key(path) + '.md'
        draft_path = os.path.join(DRAFT_DIR, name)
        _safe_write_text(draft_path, content, encoding='utf-8')
        return draft_path
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


def _check_draft_for_file(file_path):
    """Check if a draft exists that is newer than the file.
    Returns draft content if recovery is needed, None otherwise."""
    if not file_path or not os.path.exists(file_path):
        return None
    draft_content, draft_mtime = _read_draft(file_path)
    if draft_content is None:
        return None
    file_mtime = os.path.getmtime(file_path)
    # Only offer recovery if draft is newer than the file
    if draft_mtime > file_mtime:
        # Verify the draft is actually different from the file
        file_content, _ = _detect_text_encoding(file_path)
        if draft_content != file_content:
            return draft_content
    return None


def _edited_title(name, dirty):
    # Append the TextEdit-style Edited marker to a window title.
    return (name or 'Untitled.md') + (' - ' + _t('Edited', '已编辑') if dirty else '')


def _remove_draft(path):
    try:
        draft_path = os.path.join(DRAFT_DIR, _draft_key(path) + '.md')
        if os.path.exists(draft_path):
            os.remove(draft_path)
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
        if ext == 'md':
            return ''
        return _t('Experimental; output may differ from preview.', '实验性功能，输出效果可能与预览不同。')

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
                disclaimer = h.get('disclaimer')
                if disclaimer is not None:
                    try:
                        disclaimer.setStringValue_(_format_disclaimer(ext))
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

        Formats: list of (display_label, extension_key). On OK, holder gets
        'path' + 'format' (the extension key); on cancel, 'cancelled'; on
        failure, 'error'. Runs the panel on the main thread and polls here
        (15s cap) — same pattern as the other native dialogs.
        """
        try:
            from AppKit import (NSSavePanel, NSPopUpButton, NSView, NSTextField,
                                NSMakeRect, NSColor, NSFont, NSOKButton)
            from PyObjCTools import AppHelper

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
                        # The Save/Export action button follows the dialog title.
                        panel.setPrompt_(title)
                    except Exception:
                        pass
                    panel.setCanCreateDirectories_(True)
                    acc = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 360, 82))
                    label = NSTextField.labelWithString_(_t('Format:', '格式：'))
                    label.setFrame_(NSMakeRect(0, 42, 60, 20))
                    label.setTextColor_(NSColor.secondaryLabelColor())
                    popup = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(60, 38, 260, 25))
                    for f in formats:
                        popup.addItemWithTitle_(f[0])
                    disclaimer = NSTextField.labelWithString_(_format_disclaimer(formats[0][1]))
                    disclaimer.setFrame_(NSMakeRect(60, 12, 300, 18))
                    disclaimer.setTextColor_(NSColor.tertiaryLabelColor())
                    try:
                        disclaimer.setFont_(NSFont.systemFontOfSize_(11))
                    except Exception:
                        pass
                    holder['formats'] = formats
                    holder['panel'] = panel
                    holder['disclaimer'] = disclaimer
                    actions = _FormatPopupActions.alloc().initWithHolder_(holder)
                    popup.setTarget_(actions)
                    popup.setAction_('formatChanged:')
                    acc.addSubview_(label)
                    acc.addSubview_(popup)
                    acc.addSubview_(disclaimer)
                    panel.setAccessoryView_(acc)
                    panel.setAllowedFileTypes_([formats[0][1]])
                    panel.setNameFieldStringValue_(base_name + '.' + formats[0][1])
                    if panel.runModal() == NSOKButton:
                        url = panel.URL()
                        if url:
                            holder['path'] = url.path()
                            idx = popup.indexOfSelectedItem()
                            holder['format'] = formats[idx][1] if 0 <= idx < len(formats) else formats[0][1]
                            return
                    holder['cancelled'] = True
                except Exception as e:
                    holder['error'] = str(e)

            AppHelper.callAfter(_do)
            # Poll for a RESULT key: holder is pre-populated with 'formats' and
            # 'panel' before the modal runs, so a non-empty check is not enough.
            for _ in range(150):
                if 'path' in holder or 'cancelled' in holder or 'error' in holder:
                    break
                time.sleep(0.1)
            if not ('path' in holder or 'cancelled' in holder or 'error' in holder):
                holder['cancelled'] = True
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
                directory = holder.get('base_dir') or os.path.expanduser('~/Desktop')
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
    """Scale a full-height PDF page down to A4 width as ONE continuous page.

    No pagination: the whole document stays on a single tall page whose width
    matches the A4 printable width, so content flows top-to-bottom without any
    page splits (no repeated lines, no clipped mid-line text). The source is a
    full-height page created by WKWebView's createPDF; PDF coordinates grow
    upward from the bottom-left, so the document top sits at source y = src_h.
    """
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
    page_h = src_h * sx + 2 * M
    media = CGRectMake(0, 0, A4_W, page_h)
    ctx = CGPDFContextCreateWithURL(NSURL.fileURLWithPath_(dst_path), media, None)
    if ctx is None:
        raise ValueError('cannot create output pdf context')
    CGPDFContextBeginPage(ctx, None)
    CGContextSaveGState(ctx)
    CGContextScaleCTM(ctx, sx, sx)
    # Source top (y = src_h) must land on the target's top margin line.
    CGContextTranslateCTM(ctx, M / sx, (page_h - M) / sx - src_h)
    CGContextDrawPDFPage(ctx, page)
    CGContextRestoreGState(ctx)
    CGPDFContextEndPage(ctx)
    CGPDFContextClose(ctx)


class MarkdownAPI:
    def __init__(self, file_path=None):
        self.file_path = file_path
        self.cached_content = ''  # JS pushes content here periodically
        self.file_content = ''    # Last known file content
        self.window = None        # Set after window creation
        self.is_dirty = False     # JS-maintained dirty flag
        self.is_untitled = not file_path  # True for blank "New File" documents
        self.encoding = 'utf-8'    # Preserve the source file encoding on save
        self.baseline_mtime_ns = None
        self.baseline_size = None
        self.close_confirmed = False  # True after the user explicitly chooses to close

    def _record_baseline_stat(self, path):
        try:
            stat = os.stat(path)
            self.baseline_mtime_ns = getattr(stat, 'st_mtime_ns', int(stat.st_mtime * 1_000_000_000))
            self.baseline_size = stat.st_size
        except Exception:
            self.baseline_mtime_ns = None
            self.baseline_size = None

    def startup_ready(self, ms):
        """JS calls this once the first screen has rendered (cold-start perf)."""
        try:
            logging.info('[startup] js first screen ready: %dms' % int(ms))
        except Exception:
            pass
        return True

    def get_initial_content(self):
        cfg = load_config()
        page_width = cfg.get('page_width', 720)
        base = {'pageWidth': page_width, 'isZh': _is_chinese_locale()}
        if self.file_path and os.path.exists(self.file_path):
            try:
                content, encoding = _detect_text_encoding(self.file_path)
                self.encoding = encoding
                self.file_content = content
                self._record_baseline_stat(self.file_path)
                # Check for a newer draft (unsaved changes from a previous session)
                draft_content = _check_draft_for_file(self.file_path)
                if draft_content is not None:
                    # Draft is newer and different — load it so the user
                    # doesn't lose unsaved work from a crash/quit.
                    self.cached_content = draft_content
                    self.is_dirty = True
                    add_recent_file(self.file_path)
                    return {**base, 'path': self.file_path, 'content': draft_content,
                            'encoding': encoding, 'draftRecovered': True}
                self.cached_content = content
                self.is_dirty = False
                add_recent_file(self.file_path)
                return {**base, 'path': self.file_path, 'content': content, 'encoding': encoding}
            except Exception as e:
                log_exception('read file failed')
                return {**base, 'path': self.file_path, 'content': f'# Error\n\nCould not read file: {e}', 'encoding': self.encoding}
        else:
            return {**base, 'path': 'Untitled.md', 'content': '', 'encoding': self.encoding}

    def store_content(self, content):
        """Called by JS to keep Python in sync — avoids evaluate_js on close"""
        self.cached_content = content
        if self.is_dirty:
            _write_draft(self.file_path, content)
        return True

    def discard_draft(self):
        """Discard the autosave draft for the current file (user chose to ignore recovered draft)."""
        if self.file_path:
            _remove_draft(self.file_path)
        return True

    def set_dirty(self, dirty):
        """Called by JS whenever the document dirty state changes"""
        self.is_dirty = bool(dirty)
        try:
            if self.window:
                name = os.path.basename(self.file_path) if self.file_path and not self.is_untitled else 'Untitled.md'
                self.window.set_title(_edited_title(name, self.is_dirty))
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

    def reset_to_untitled(self):
        """Turn the current window into a blank Untitled document without closing it.

        Used when the user closes the last open document window but is not
        quitting the app. The window stays alive as a blank document so Finder
        double-click and Dock reopen can reuse/create windows without a cold
        start.
        """
        try:
            if self.file_path:
                with _state_lock:
                    _opened_files.discard(os.path.abspath(self.file_path))
            self.file_path = None
            self.is_untitled = True
            self.is_dirty = False
            self.cached_content = ''
            self.file_content = ''
            self.close_confirmed = False
            if self.window:
                self.window.set_title('Untitled.md')
        except Exception:
            log_exception('reset to untitled failed')
        return True

    def _has_external_save_conflict(self, path):
        """Return True when the on-disk file differs from our last clean baseline."""
        if not path or self.is_untitled:
            return False
        target = os.path.abspath(path)
        current = os.path.abspath(self.file_path) if self.file_path else None
        if not current or target != current or not os.path.exists(target):
            return False
        try:
            stat = os.stat(target)
            mtime_ns = getattr(stat, 'st_mtime_ns', int(stat.st_mtime * 1_000_000_000))
            if self.baseline_mtime_ns == mtime_ns and self.baseline_size == stat.st_size:
                return False
        except Exception:
            pass
        disk_content, disk_encoding = _detect_text_encoding(target)
        self.encoding = disk_encoding
        return disk_content != self.file_content

    def save_file(self, path, content, force=False):
        try:
            previous_path = self.file_path
            encoding = self.encoding or 'utf-8'
            if not force and self._has_external_save_conflict(path):
                return {
                    'success': False,
                    'conflict': True,
                    'path': path,
                    'message': 'The file has changed on disk since it was opened or last saved.',
                }
            _safe_write_text(path, content, encoding=encoding)
            self.file_path = path
            self.file_content = content
            self.cached_content = content
            self._record_baseline_stat(path)
            self.is_dirty = False
            self.is_untitled = False
            _remove_draft(previous_path or path)
            if previous_path and previous_path != path:
                _remove_draft(path)
            add_recent_file(path)
            return {'success': True, 'encoding': encoding}
        except Exception as e:
            log_exception('save file failed')
            return {'success': False, 'error': str(e)}

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

    def export_as_write(self, path, fmt, content='', page=None):
        """Write the exported document. md/html/txt are written as text; pdf is
        generated from the current WKWebView render (async). `page` is an
        optional {width, height} dict (CSS px) telling createPDF how much of
        the document to capture — without it only the visible viewport is
        printed."""
        if not HAS_COCOA:
            return {'success': False, 'error': 'Cocoa not available'}
        try:
            if fmt == 'pdf':
                from PyObjCTools import AppHelper
                from WebKit import WKPDFConfiguration
                result_holder = {}

                def _run_pdf():
                    try:
                        import webview.platforms.cocoa as cocoa_mod
                        bv = cocoa_mod.BrowserView.instances.get(getattr(self.window, 'uid', None))
                        webview_native = bv.webview if bv is not None else None
                        if webview_native is None:
                            result_holder['error'] = 'No webview available'
                            return
                        config = WKPDFConfiguration.alloc().init()
                        if page:
                            w = int(page.get('width') or 0)
                            h = int(page.get('height') or 0)
                            if w > 0 and h > 0:
                                from AppKit import NSMakeRect
                                config.setRect_(NSMakeRect(0, 0, w, h))

                        def handler(data, error):
                            try:
                                if error is not None:
                                    result_holder['error'] = str(error)
                                    return
                                if data is None or len(data) == 0:
                                    result_holder['error'] = 'Empty PDF data'
                                    return
                                # createPDF produces one tall page covering the
                                # whole document; slice it into standard A4
                                # pages (scaled to the printable width).
                                tmp_fd, tmp_path = tempfile.mkstemp(suffix='.pdf')
                                os.close(tmp_fd)
                                try:
                                    with open(tmp_path, 'wb') as f:
                                        f.write(bytes(data))
                                    _pdf_to_a4_longpage(tmp_path, path)
                                finally:
                                    try:
                                        os.remove(tmp_path)
                                    except Exception:
                                        pass
                                result_holder['done'] = True
                            except Exception as e:
                                result_holder['error'] = str(e)

                        webview_native.createPDFWithConfiguration_completionHandler_(config, handler)
                    except Exception as e:
                        result_holder['error'] = str(e)

                AppHelper.callAfter(_run_pdf)
                for _ in range(150):
                    if 'done' in result_holder or 'error' in result_holder:
                        break
                    time.sleep(0.1)
                if result_holder.get('done'):
                    return {'success': True, 'path': path}
                return {'success': False, 'error': result_holder.get('error', 'PDF generation timed out')}

            if fmt in ('docx', 'png'):
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
                with open(path, 'wb') as f:
                    f.write(raw)
                return {'success': True, 'path': path}

            _safe_write_text(path, content, encoding='utf-8')
            return {'success': True, 'path': path}
        except Exception as e:
            log_exception('export as write failed')
            return {'success': False, 'error': str(e)}

    def save_page_width(self, width):
        """Persist the user's preferred page width"""
        cfg = load_config()
        cfg['page_width'] = int(width)
        save_config(cfg)
        return True

    def open_file_dialog(self):
        """Show a native Open panel and open the selected Markdown file."""
        if not HAS_COCOA:
            return {'success': False, 'error': 'Cocoa not available'}
        try:
            from AppKit import NSOpenPanel, NSOKButton
            from PyObjCTools import AppHelper

            result_holder = {}

            def _run_panel():
                try:
                    panel = NSOpenPanel.openPanel()
                    panel.setTitle_(_t('Open File', '打开文件'))
                    panel.setCanChooseFiles_(True)
                    panel.setCanChooseDirectories_(False)
                    panel.setAllowsMultipleSelection_(True)
                    panel.setAllowedFileTypes_(['md', 'markdown', 'mdown', 'mkd', 'mkdown'])
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

            # NSOpenPanel must be created and run on the main thread
            AppHelper.callAfter(_run_panel)
            # 15s timeout: if the panel never responds, treat it as a cancel
            for _ in range(150):
                if result_holder:
                    break
                time.sleep(0.1)
            if not result_holder:
                result_holder['cancelled'] = True

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
                    if self.file_path:
                        _remove_draft(self.file_path)
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
            is_untitled = self.is_untitled or not self.file_path
            if is_untitled:
                base_name = 'untitled'
                base_dir = os.path.expanduser('~/Desktop')
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
                        _t('Do you want to save the changes you made to "%s"?' % base_name,
                           '是否保存对"%s"所做的更改？' % base_name) if not is_untitled else
                        _t('Do you want to keep this new document "%s"?' % base_name,
                           '是否保留这个新文档"%s"？' % base_name))
                    alert.setInformativeText_(
                        _t("Your changes will be lost if you don't save them.",
                           '若不保存，您的更改将丢失。'))
                    # Native vertical layout (top to bottom): Delete, Save, Cancel.
                    # Response codes: First=Delete(1000), Second=Cancel(1001),
                    # Third=Save(1002).
                    alert.addButtonWithTitle_(_t('Delete', '删除'))
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

            AppHelper.callAfter(_run)
            for _ in range(150):  # 15s timeout; fall back to cancel
                if result_holder:
                    break
                time.sleep(0.1)
            return result_holder or {'action': 'cancel'}
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
                        _t('The file "%s" has changed on disk since it was opened or last saved.' % name,
                           '文件"%s"自打开或上次保存以来已在磁盘上发生变化。' % name))
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

            AppHelper.callAfter(_run)
            for _ in range(150):  # 15s timeout; fall back to cancel
                if result_holder:
                    break
                time.sleep(0.1)
            return result_holder or {'action': 'cancel'}
        except Exception:
            log_exception('native conflict prompt failed')
            return {'action': 'cancel'}

    def open_external_link(self, url):
        """Open a URL with the system default handler."""
        try:
            import webbrowser
            webbrowser.open(url)
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

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


def add_recent_file(path):
    if not path:
        return
    # Serialize the whole read-modify-write so concurrent windows never lose
    # each other's recent-file entries.
    with _config_lock:
        try:
            path = os.path.abspath(path)
            cfg = load_config()
            recent = [p for p in cfg.get('recent_files', []) if p != path and os.path.exists(p)]
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
    try:
        _dispatch_js_to(window, 'convertToBlankDocument()')
    except Exception:
        log_exception('blank window dispatch failed')
    if api:
        try:
            api.reset_to_untitled()
        except Exception:
            log_exception('blank window reset failed')
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
                    _write_draft(api.file_path, api.cached_content)
                except Exception:
                    log_exception('write draft during close prompt failed')
            try:
                _dispatch_js_to(window, 'promptBeforeClose(true)')
            except Exception:
                pass
            return False
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
                _write_draft(api.file_path, api.cached_content)
            except Exception:
                log_exception('write draft during close failed')
        return _allow_close(window)
    except Exception:
        log_exception('window closing failed')
        return _allow_close(window)


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
            try:
                if not self.webview or not BrowserView.app.isRunning():
                    return None
            except Exception:
                return None

            class JSResult:
                result = None
                result_semaphore = threading.Semaphore(0)

            def handler(result, error):
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
                except Exception:
                    try:
                        JSResult.result_semaphore.release()
                    except Exception:
                        pass

            try:
                cocoa.AppHelper.callAfter(eval_)
                if not JSResult.result_semaphore.acquire(timeout=EVALUATE_JS_TIMEOUT):
                    return None
                return JSResult.result
            except Exception:
                return None

        BrowserView.evaluate_js = _safe_evaluate_js
    except Exception:
        log_exception('patch evaluate_js failed')


def create_window(file_path=None, x=None, y=None):
    if file_path:
        file_path = os.path.abspath(file_path)
        if file_path in _opened_files:
            _focus_existing_file(file_path)
            return
        with _state_lock:
            _opened_files.add(file_path)

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
            width=900,
            height=680,
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


def update_main_window(main_window, main_api, file_path):
    """Update the main window with a new file (reused hidden window path)."""
    file_path = os.path.abspath(file_path)
    main_api.file_path = file_path
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
                    main_window.evaluate_js('reloadContent();')
                    main_window.set_title(_edited_title(os.path.basename(file_path), main_api.is_dirty))
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

    valid_extensions = ('.md', '.markdown', '.mdown', '.mkd', '.mkdown')
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
                    if sub and sub.title() in ('View', '显示', '视图'):
                        view_menu = sub
                        break

                if view_menu:
                    # Keep the existing first section (Tab navigation) intact,
                    # then rebuild the rest so separators and native items have
                    # a stable order.
                    first_section_end = view_menu.numberOfItems()
                    for idx in range(view_menu.numberOfItems()):
                        if view_menu.itemAtIndex_(idx).isSeparatorItem():
                            first_section_end = idx + 1
                            break
                    while view_menu.numberOfItems() > first_section_end:
                        view_menu.removeItemAtIndex_(first_section_end)

                    # Section 2: Preview/Source + Outline.
                    toggle_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                        _t("Toggle Preview / Source", "切换预览 / 源码"), "toggleView:", "e")
                    toggle_item.setKeyEquivalentModifierMask_(1 << 20)  # Command
                    md_icon = _make_md_icon()
                    if md_icon is not None:
                        toggle_item.setImage_(md_icon)
                    toggle_item.setTarget_(_view_menu_handler)
                    view_menu.insertItem_atIndex_(toggle_item, first_section_end)
                    outline_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Show/Hide Outline", "显示/隐藏大纲"), "toggleOutline:", "o")
                    outline_item.setKeyEquivalentModifierMask_((1 << 20) | (1 << 19))  # Cmd+Option+O
                    _set_symbol_icon(outline_item, 'list.bullet.rectangle')
                    view_menu.insertItem_atIndex_(outline_item, first_section_end + 1)
                    view_menu.insertItem_atIndex_(NSMenuItem.separatorItem(), first_section_end + 2)

                    # Section 3: Full Screen.
                    fullscreen_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Enter Full Screen", "进入全屏幕"), "toggleFullScreen:", "f")
                    fullscreen_item.setKeyEquivalentModifierMask_((1 << 20) | (1 << 19))  # Cmd+Option+F
                    _set_symbol_icon(fullscreen_item, 'arrow.up.left.and.arrow.down.right')
                    view_menu.insertItem_atIndex_(fullscreen_item, first_section_end + 3)
                    view_menu.insertItem_atIndex_(NSMenuItem.separatorItem(), first_section_end + 4)

                    # Section 4: width and text-size controls.
                    inc_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Increase Width", "加宽"), "increaseWidth:", ".")
                    inc_item.setKeyEquivalentModifierMask_(1 << 20)
                    _set_symbol_icon(inc_item, 'arrow.left.and.right')
                    view_menu.insertItem_atIndex_(inc_item, first_section_end + 5)
                    dec_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Decrease Width", "变窄"), "decreaseWidth:", ",")
                    dec_item.setKeyEquivalentModifierMask_(1 << 20)
                    _set_symbol_icon(dec_item, 'arrow.left.and.right')
                    view_menu.insertItem_atIndex_(dec_item, first_section_end + 6)
                    reset_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Reset Width", "重置宽度"), "resetWidth:", "0")
                    reset_item.setKeyEquivalentModifierMask_(1 << 20)
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
                    _view_menu_setup = True

            # ── File menu: Properties ──
            if not _file_menu_setup:
                file_menu = None
                file_menu_index = -1
                for i in range(main_menu.numberOfItems()):
                    item = main_menu.itemAtIndex_(i)
                    sub = item.submenu()
                    if sub and sub.title() in ('File', '文件'):
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
                    recent_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(_t("Open Recent", "打开最近"), None, "")
                    recent_menu = NSMenu.alloc().initWithTitle_(_t("Open Recent", "打开最近"))
                    for recent_path in load_config().get('recent_files', [])[:10]:
                        if not os.path.exists(recent_path):
                            continue
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
                    if sub and sub.title() in ('Edit', '编辑', '编辑'):
                        edit_menu = sub
                        break

                if edit_menu and not getattr(_view_menu_handler, '_edit_menu_setup', False):
                    # "Paste as Markdown": insert right after the native Paste
                    # item (or at the top of the Edit menu if it is absent).
                    # Cmd+Shift+V overrides macOS' default "Paste and Match Style".
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
                    _view_menu_handler._edit_menu_setup = True

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

        def resetWidth_(self, sender):
            _dispatch_js('resetPageWidth()')

        def zoomIn_(self, sender):
            _dispatch_js('zoomIn()')

        def zoomOut_(self, sender):
            _dispatch_js('zoomOut()')

        def toggleOutline_(self, sender):
            _dispatch_js('toggleToc()')

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

        def findAction_(self, sender):
            _dispatch_js('openFindBar()')

        def pasteAsMarkdown_(self, sender):
            _dispatch_js('pasteAsMarkdown()')

        def findNextAction_(self, sender):
            _dispatch_js('findNext()')

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
                    NSParagraphStyleAttributeName
                )
                from Foundation import NSURL, NSMutableParagraphStyle, NSMakeRange

                if _about_window_ref is not None and _about_window_ref.isVisible():
                    _about_window_ref.makeKeyAndOrderFront_(None)
                    return

                width = 420
                height = 248
                panel = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                    NSMakeRect(0, 0, width, height),
                    NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
                    NSBackingStoreBuffered,
                    False,
                )
                panel.setTitle_(_t('About mdPreview', '关于 mdPreview'))
                panel.setReleasedWhenClosed_(False)
                panel.setBackgroundColor_(NSColor.whiteColor())
                content = panel.contentView()
                content.setWantsLayer_(True)
                content.layer().setBackgroundColor_(NSColor.whiteColor().CGColor())

                icon_size = 82
                icon_view = NSImageView.alloc().initWithFrame_(NSMakeRect((width - icon_size) / 2, height - 104, icon_size, icon_size))
                icon = NSImage.alloc().initWithContentsOfFile_(get_resource_path('app_icon.icns'))
                if icon is not None:
                    icon_view.setImage_(icon)
                icon_view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
                content.addSubview_(icon_view)

                title_font = NSFont.systemFontOfSize_weight_(20, 0.35)
                text_font = NSFont.systemFontOfSize_(13)
                small_font = NSFont.systemFontOfSize_(12)

                title = NSTextField.labelWithString_('mdPreview')
                title.setFrame_(NSMakeRect(0, height - 136, width, 26))
                title.setAlignment_(NSCenterTextAlignment)
                title.setFont_(title_font)
                title.setTextColor_(NSColor.labelColor())
                content.addSubview_(title)

                version = NSTextField.labelWithString_('Version ' + _get_current_version())
                version.setFrame_(NSMakeRect(0, height - 162, width, 20))
                version.setAlignment_(NSCenterTextAlignment)
                version.setFont_(text_font)
                version.setTextColor_(NSColor.secondaryLabelColor())
                content.addSubview_(version)

                credit = NSTextField.labelWithString_('GitHub   ©tahoeliu')
                credit.setFrame_(NSMakeRect(0, 32, width, 20))
                credit.setAlignment_(NSCenterTextAlignment)
                credit.setFont_(small_font)
                credit.setTextColor_(NSColor.secondaryLabelColor())
                credit.setEditable_(False)
                credit.setSelectable_(False)
                credit.setBezeled_(False)
                credit.setDrawsBackground_(False)
                content.addSubview_(credit)

                try:
                    url = NSURL.URLWithString_('https://github.com/tahoeliu/mdPreview')
                    credit.setAllowsEditingTextAttributes_(True)
                    credit.setSelectable_(True)
                    attr = NSMutableAttributedString.alloc().initWithString_('GitHub   ©tahoeliu')
                    paragraph = NSMutableParagraphStyle.alloc().init()
                    paragraph.setAlignment_(NSCenterTextAlignment)
                    attr.addAttribute_value_range_('NSLink', url, NSMakeRange(0, 6))
                    attr.addAttribute_value_range_(NSParagraphStyleAttributeName, paragraph, NSMakeRange(0, attr.length()))
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
                _QUIT_REQUESTED.set()
                return 1  # NSTerminateNow; dirty windows are handled by close events.

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


def main():
    global _initial_file_handled
    global _main_window_ref, _main_api_ref, _active_window_ref

    _start_log('main entered')
    if HAS_COCOA:
        patch_app_delegate()
        patch_window_close_behavior()
        patch_evaluate_js()

    file_paths = []
    valid_extensions = ('.md', '.markdown', '.mdown', '.mkd', '.mkdown')
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg and os.path.exists(arg) and arg.lower().endswith(valid_extensions):
                file_paths.append(os.path.abspath(arg))
    file_path = file_paths[0] if file_paths else None

    if file_path:
        _initial_file_handled = True

    main_api = MarkdownAPI(file_path)
    html_path = get_resource_path('index.html')
    title = os.path.basename(file_path) if file_path else 'Untitled.md'

    _start_log('before create_window')
    main_window = webview.create_window(
        title=title,
        url=html_path,
        js_api=main_api,
        width=900,
        height=680,
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
                _check_pending_install()
            except Exception:
                pass
            try:
                _try_set_default_handler()
            except Exception:
                pass
        threading.Thread(target=_post_startup, daemon=True).start()
        _schedule_startup_update_check()
        # Clear leftover staging files from an interrupted update (only when no
        # update is pending — a pending install must keep its staged app).
        try:
            cfg0 = load_config()
            if not cfg0.get('pending_update_version'):
                if os.path.isdir(UPDATE_STAGING_DIR):
                    shutil.rmtree(UPDATE_STAGING_DIR, ignore_errors=True)
        except Exception:
            pass

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

    if '--selftest-close' in sys.argv:
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
        return info.get('CFBundleShortVersionString', '0.0.0')
    except Exception:
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
    last = cfg.get('last_update_check', 0)
    return (time.time() - last) >= CHECK_INTERVAL


def _mark_update_checked():
    cfg = load_config()
    cfg['last_update_check'] = time.time()
    save_config(cfg)


def _set_update_available(remote_version):
    """Remember that an update is available, auto-download, and show bubble."""
    global _available_update_version
    _available_update_version = remote_version
    if HAS_COCOA:
        def _update_menu():
            try:
                if _update_menu_item:
                    _update_menu_item.setTitle_(_t(f'Update Available: {remote_version}...', f'有可用更新：{remote_version}…'))
            except Exception:
                pass
        AppHelper.callAfter(_update_menu)
    # Auto-download in background to hidden staging dir
    def _bg_download():
        update = _download_and_extract(remote_version)
        if update:
            cfg = load_config()
            cfg['pending_staging_app'] = update['staging_app']
            cfg['pending_update_version'] = remote_version
            cfg.pop('pending_update_dmg', None)
            save_config(cfg)
            if HAS_COCOA:
                AppHelper.callAfter(lambda: _dispatch_js('showUpdateBubble()'))
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
        alert.setMessageText_(_t(f'mdPreview {remote_version} is available!', f'mdPreview {remote_version} 已可用！'))
        alert.setInformativeText_(_t(f'You have version {local}. Would you like to download the update?', f'当前版本为 {local}。是否下载更新？'))
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


def _download_and_extract(version, progress_callback=None, keep_dmg=False):
    """Download DMG to staging dir, extract .app, return staging and DMG paths."""
    import urllib.request
    import subprocess
    mount_dir = None
    dmg_path = None
    try:
        os.makedirs(UPDATE_STAGING_DIR, exist_ok=True)
        dmg_path = os.path.join(UPDATE_STAGING_DIR, 'mdPreview.dmg')
        url = 'https://github.com/tahoeliu/mdPreview/releases/latest/download/mdPreview.dmg'
        req = urllib.request.Request(url, headers={'User-Agent': 'mdPreview'})
        if progress_callback:
            progress_callback(0)
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get('Content-Length') or 0)
            done = 0
            last_percent = -1
            with open(dmg_path, 'wb') as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress_callback and total > 0:
                        percent = min(100, int(done * 100 / total))
                        if percent != last_percent:
                            last_percent = percent
                            progress_callback(percent)
        if progress_callback:
            progress_callback(100)
        if os.path.getsize(dmg_path) < 1000000:
            os.remove(dmg_path)
            return None
        # Mount and copy .app to staging
        mount_dir = tempfile.mkdtemp()
        subprocess.run(
            ['hdiutil', 'attach', '-nobrowse', '-mountpoint', mount_dir, dmg_path],
            capture_output=True, check=True
        )
        src_app = os.path.join(mount_dir, 'mdPreview.app')
        staging_app = os.path.join(UPDATE_STAGING_DIR, 'mdPreview.app')
        if os.path.exists(staging_app):
            shutil.rmtree(staging_app)
        shutil.copytree(src_app, staging_app)
        # Integrity check: the staged app must carry the expected version.
        plist = os.path.join(staging_app, 'Contents', 'Info.plist')
        staged_version = None
        try:
            import plistlib
            with open(plist, 'rb') as pf:
                staged_version = plistlib.load(pf).get('CFBundleShortVersionString')
        except Exception:
            pass
        if not staged_version or (version and _is_newer(version, staged_version)):
            log_exception('staged update failed version check: got %r want %r' % (staged_version, version))
            shutil.rmtree(staging_app, ignore_errors=True)
            return None
        return {'staging_app': staging_app, 'dmg_path': dmg_path if keep_dmg else ''}
    except Exception:
        log_exception('download and extract failed')
        return None
    finally:
        if mount_dir and os.path.exists(mount_dir):
            subprocess.run(['hdiutil', 'detach', mount_dir], capture_output=True)
            shutil.rmtree(mount_dir, ignore_errors=True)
        try:
            if dmg_path and os.path.exists(dmg_path) and not keep_dmg:
                os.remove(dmg_path)
        except Exception:
            pass


def _manual_download_update_with_progress(version):
    """Download a manually requested update and report progress to the UI."""
    def _progress(percent):
        if HAS_COCOA:
            AppHelper.callAfter(lambda p=percent: _dispatch_js(f'showUpdateDownloadProgress({int(p)})'))

    update = _download_and_extract(version, progress_callback=_progress, keep_dmg=True)
    if not update:
        if HAS_COCOA:
            AppHelper.callAfter(lambda: _dispatch_js("showUpdateDownloadFailed('download failed')"))
        return {'success': False, 'error': 'Download failed'}

    cfg = load_config()
    cfg['pending_staging_app'] = update['staging_app']
    cfg['pending_update_version'] = version
    cfg['pending_update_dmg'] = update.get('dmg_path', '')
    save_config(cfg)
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
            _mark_update_checked()
            remote = _fetch_latest_version()
            if not remote:
                return
            local = _get_current_version()
            if _is_newer(remote, local):
                _set_update_available(remote)
            else:
                _clear_update_available()
        except Exception:
            pass

    threading.Thread(target=_delayed_check, daemon=True).start()


def _manual_check_up_to_date():
    """Alert for manual check when already on latest version."""
    if not HAS_COCOA:
        return
    try:
        local = _get_current_version()
        alert = NSAlert.alloc().init()
        alert.setMessageText_(_t("You're up to date!", "已是最新版本！"))
        alert.setInformativeText_(_t(f'mdPreview {local} is the latest version.', f'mdPreview {local} 已是最新版本。'))
        alert.addButtonWithTitle_(_t('OK', '好'))
        alert.runModal()
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
            cfg['default_handler_set'] = True
            save_config(cfg)
    except Exception:
        log_exception('set default handler failed')


def _check_pending_install():
    """On app launch, check if a staged update exists and show the bubble."""
    if not HAS_COCOA:
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
                save_config(cfg)
                shutil.rmtree(staging_app, ignore_errors=True)
                return
            # Show the update bubble (non-blocking)
            global _available_update_version
            _available_update_version = version
            if _update_menu_item:
                def _update_menu():
                    try:
                        _update_menu_item.setTitle_(_t(f'Update Available: {version}...', f'有可用更新：{version}…'))
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
                save_config(cfg)
    except Exception:
        pass


def _smoke_test_app(app_path, timeout=5):
    """Launch an .app, verify its process stays alive, then quit it.

    Used before replacing the installed app so a broken update never lands on
    the user's machine. Only the smoke-test process (matched by app_path) is
    killed — the running old app is never touched.
    """
    import subprocess
    try:
        subprocess.run(['open', '-a', app_path], capture_output=True, timeout=5)
        marker = os.path.join(app_path, 'Contents', 'MacOS')
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = subprocess.run(['pgrep', '-f', marker], capture_output=True)
            if r.returncode == 0:
                subprocess.run(['pkill', '-f', marker], capture_output=True)
                return True
            time.sleep(0.3)
        # Didn't survive: kill anything left from the smoke run
        subprocess.run(['pkill', '-f', marker], capture_output=True)
        return False
    except Exception:
        log_exception('smoke test failed')
        return False


def _perform_auto_install():
    """Execute auto-install: write helper script, quit app, let script replace + restart.

    Hardened: the staged app is smoke-tested BEFORE any replacement; the helper
    script keeps the old app until the new one has launched successfully, and
    rolls back on failure.
    """
    import subprocess
    try:
        cfg = load_config()
        staging_app = cfg.get('pending_staging_app', '')
        version = cfg.get('pending_update_version', '')
        manual_dmg_path = cfg.get('pending_update_dmg', '')
        if not staging_app or not os.path.exists(staging_app):
            return {'success': False, 'error': 'No staged update found', 'manual_dmg_path': manual_dmg_path}

        app_dir = '/Applications'
        app_path = os.path.join(app_dir, 'mdPreview.app')
        if not os.access(app_dir, os.W_OK) or (os.path.exists(app_path) and not os.access(app_path, os.W_OK)):
            return {
                'success': False,
                'error': 'Permission denied while replacing /Applications/mdPreview.app',
                'manual_install': True,
                'manual_dmg_path': manual_dmg_path,
            }

        # Smoke-test the staged app first: never replace a working install
        # with a package that fails to launch.
        if not _smoke_test_app(staging_app):
            shutil.rmtree(staging_app, ignore_errors=True)
            cfg.pop('pending_staging_app', None)
            cfg.pop('pending_update_version', None)
            save_config(cfg)
            return {'success': False, 'error': 'Staged update failed launch test', 'manual_install': True, 'manual_dmg_path': manual_dmg_path}

        # Write helper script that runs after app exits. It keeps the old app
        # until the new one has been verified running (launch + pgrep), and
        # rolls back if the new app dies.
        script = (
            '#!/bin/bash\n'
            'sleep 2\n'
            f'APP=/Applications/mdPreview.app\n'
            f'OLD=/Applications/mdPreview.app.old\n'
            f'STAGING="{staging_app}"\n'
            'mv "$APP" "$OLD" 2>/dev/null\n'
            'cp -R "$STAGING" "$APP"\n'
            'if [ $? -eq 0 ]; then\n'
            '  xattr -cr "$APP"\n'
            '  open "$APP"\n'
            '  sleep 3\n'
            '  if pgrep -f "$APP/Contents/MacOS" >/dev/null 2>&1; then\n'
            '    echo "mdPreview update OK"\n'
            '    rm -rf "$OLD"\n'
            '  else\n'
            '    echo "mdPreview update FAILED to launch - rolling back"\n'
            '    rm -rf "$APP"\n'
            '    mv "$OLD" "$APP" 2>/dev/null\n'
            '  fi\n'
            'else\n'
            '  mv "$OLD" "$APP" 2>/dev/null\n'
            'fi\n'
            'rm -rf "$STAGING"\n'
        )
        script_path = os.path.join(UPDATE_STAGING_DIR, 'install_update.sh')
        os.makedirs(UPDATE_STAGING_DIR, exist_ok=True)
        with open(script_path, 'w') as f:
            f.write(script)
        os.chmod(script_path, 0o755)

        # Launch helper detached from this process
        subprocess.Popen(
            ['nohup', 'bash', script_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True
        )

        # Clean up config
        cfg.pop('pending_staging_app', None)
        cfg.pop('pending_update_version', None)
        cfg.pop('pending_update_dmg', None)
        save_config(cfg)

        # Quit the app so the helper can replace it
        if HAS_COCOA:
            from AppKit import NSApplication
            NSApplication.sharedApplication().terminate_(None)

        return {'success': True}
    except Exception as e:
        log_exception('auto install failed')
        try:
            manual_dmg_path = load_config().get('pending_update_dmg', '')
        except Exception:
            manual_dmg_path = ''
        return {'success': False, 'error': str(e), 'manual_install': True, 'manual_dmg_path': manual_dmg_path}


if __name__ == '__main__':
    main()
