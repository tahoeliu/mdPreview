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
        return raw.decode('utf-16'), 'utf-16'
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


def _create_backup(path):
    """Create a best-effort .bak next to an existing file before replacing it."""
    if not path or not os.path.exists(path):
        return None
    backup_path = path + '.bak'
    try:
        shutil.copy2(path, backup_path)
        return backup_path
    except Exception:
        log_exception('create backup failed')
        return None


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


class MarkdownAPI:
    def __init__(self, file_path=None):
        self.file_path = file_path
        self.cached_content = ''  # JS pushes content here periodically
        self.file_content = ''    # Last known file content
        self.window = None        # Set after window creation
        self.is_dirty = False     # JS-maintained dirty flag
        self.is_untitled = not file_path  # True for blank "New File" documents
        self.encoding = 'utf-8'    # Preserve the source file encoding on save

    def get_initial_content(self):
        cfg = load_config()
        page_width = cfg.get('page_width', 720)
        base = {'pageWidth': page_width, 'isZh': _is_chinese_locale()}
        if self.file_path and os.path.exists(self.file_path):
            try:
                content, encoding = _detect_text_encoding(self.file_path)
                self.encoding = encoding
                self.file_content = content
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
                self.window.set_title(('● ' if self.is_dirty else '') + name)
        except Exception:
            log_exception('set dirty title failed')
        return True

    def save_file(self, path, content):
        try:
            previous_path = self.file_path
            encoding = self.encoding or 'utf-8'
            backup_path = _create_backup(path)
            _safe_write_text(path, content, encoding=encoding)
            self.file_path = path
            self.file_content = content
            self.cached_content = content
            self.is_dirty = False
            self.is_untitled = False
            _remove_draft(previous_path or path)
            if previous_path and previous_path != path:
                _remove_draft(path)
            add_recent_file(path)
            return {'success': True, 'encoding': encoding, 'backup': backup_path}
        except Exception as e:
            log_exception('save file failed')
            return {'success': False, 'error': str(e)}

    def save_as_dialog(self, content):
        """Show a native macOS Save panel; return the chosen path or None."""
        if not HAS_COCOA:
            return {'success': False, 'error': 'Cocoa not available'}
        try:
            from AppKit import NSSavePanel, NSOKButton
            from PyObjCTools import AppHelper

            result_holder = {}

            def _run_panel():
                try:
                    panel = NSSavePanel.savePanel()
                    panel.setTitle_(_t('Save', '保存'))
                    panel.setCanCreateDirectories_(True)
                    desktop = os.path.expanduser('~/Desktop')
                    panel.setDirectoryURL_(
                        __import__('Foundation').NSURL.fileURLWithPath_(desktop)
                    )
                    panel.setNameFieldStringValue_('Untitled.md')
                    panel.setAllowedFileTypes_(['md'])
                    response = panel.runModal()
                    if response == NSOKButton:
                        chosen_url = panel.URL()
                        chosen_path = chosen_url.path()
                        result_holder['path'] = chosen_path
                    else:
                        result_holder['cancelled'] = True
                except Exception as e:
                    result_holder['error'] = str(e)

            AppHelper.callAfter(_run_panel)
            for _ in range(600):
                if result_holder:
                    break
                time.sleep(0.1)

            if 'error' in result_holder:
                return {'success': False, 'error': result_holder['error']}
            if result_holder.get('cancelled'):
                return {'success': False, 'cancelled': True}

            chosen_path = result_holder['path']
            result = self.save_file(chosen_path, content)
            if result.get('success'):
                return {'success': True, 'path': chosen_path}
            return result
        except Exception as e:
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
            # Wait for the panel to finish (max 60 seconds)
            for _ in range(600):
                if result_holder:
                    break
                time.sleep(0.1)

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

    def export_document(self, default_name, content, extension):
        if not HAS_COCOA:
            return {'success': False, 'error': 'Cocoa not available'}
        try:
            from AppKit import NSSavePanel, NSOKButton
            from PyObjCTools import AppHelper

            result_holder = {}

            def _run_panel():
                try:
                    panel = NSSavePanel.savePanel()
                    panel.setTitle_(_t('Export', '导出'))
                    panel.setCanCreateDirectories_(True)
                    panel.setNameFieldStringValue_(default_name)
                    panel.setAllowedFileTypes_([extension.lstrip('.')])
                    response = panel.runModal()
                    if response == NSOKButton:
                        result_holder['path'] = panel.URL().path()
                    else:
                        result_holder['cancelled'] = True
                except Exception as e:
                    result_holder['error'] = str(e)

            AppHelper.callAfter(_run_panel)
            for _ in range(600):
                if result_holder:
                    break
                time.sleep(0.1)

            if 'error' in result_holder:
                return {'success': False, 'error': result_holder['error']}
            if result_holder.get('cancelled'):
                return {'success': False, 'cancelled': True}

            path = result_holder['path']
            _safe_write_text(path, content, encoding='utf-8')
            return {'success': True, 'path': path}
        except Exception as e:
            log_exception('export document failed')
            return {'success': False, 'error': str(e)}

    def close_window(self):
        try:
            if self.window:
                self.window.destroy()
                return {'success': True}
        except Exception as e:
            log_exception('close window failed')
            return {'success': False, 'error': str(e)}
        return {'success': False, 'error': 'No window'}

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
            from CoreFoundation import CFStringCreateWithCString, kCFStringEncodingUTF8
            from LaunchServices import (
                LSSetDefaultRoleHandlerForContentType,
                LSSetDefaultRoleHandlerForExtension,
                kLSRolesAll, kLSRolesViewer, kLSRolesEditor,
            )
            import CoreFoundation

            bundle_id = 'com.workbuddy.mdpreview'

            # Register for common Markdown extensions
            extensions = ['md', 'markdown', 'mdown', 'mkd', 'mkdown']
            for ext in extensions:
                LSSetDefaultRoleHandlerForExtension(ext, kLSRolesAll, bundle_id)

            # Also register by UTI
            utis = ['net.daringfireball.markdown', 'com.apple.traditional-mac-plain-text']
            for uti in utis:
                LSSetDefaultRoleHandlerForContentType(uti, kLSRolesAll, bundle_id)

            return {'success': True}
        except Exception as e:
            log_exception('set as default failed')
            return {'success': False, 'error': str(e)}

    def get_app_info(self):
        """Return app metadata (version, etc.) for the About panel."""
        return {'version': _get_current_version()}

    def perform_auto_install(self):
        """Called from JS when user clicks the update bubble."""
        return _perform_auto_install()

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
    try:
        os.makedirs(APP_SUPPORT_DIR, exist_ok=True)
        _safe_write_text(CONFIG_FILE, json.dumps(cfg))
    except Exception:
        log_exception('save config failed')


def add_recent_file(path):
    if not path:
        return
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
_window_count = [0]  # list-based counter so it stays mutable inside ObjC callbacks
WINDOW_OFFSET = 30  # px to offset each new window
WINDOW_BASE_X = 100  # starting position
WINDOW_BASE_Y = 80

# ── Quit safety machinery ────────────────────────────────────────────────────
# Root cause of the long-standing "freezes on quit": pywebview's cocoa
# evaluate_js blocks the calling thread forever when the main runloop has
# stopped (after app.stop_ during teardown). pywebview's internal JS-bridge
# result threads are NON-daemon, so Python interpreter shutdown joins them
# forever and the process never exits. Fixes below (see patch_evaluate_js,
# on_window_closing, _start_quit_watchdog).
_QUIT_REQUESTED = threading.Event()  # set by every close/quit path
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
    try:
        if not window:
            return False
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
    api = _window_apis.pop(id(window), None)
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

    This is the single choke point for EVERY quit path:
      - window close button  -> windowShouldClose_  -> events.closing
      - Cmd+Q / Quit menu    -> applicationShouldTerminate_ -> events.closing
      - File > Close (Cmd+W) -> JS closeWindow() -> window.destroy() -> close

    It runs synchronously on the UI path, so it must stay non-blocking (no
    modal alerts, no save panels, no synchronous JS). What we DO here:
      1. Arm the quit watchdog (guaranteed process exit even if teardown
         deadlocks downstream in pywebview).
      2. Ask JS to stop all timers / pending bridge traffic so no new
         JS->Python calls fire during WKWebView teardown.
      3. Persist a draft of unsaved content (cached_content is kept fresh by
         debounced JS store_content() calls).
    """
    try:
        _set_active_window(window)
        _QUIT_REQUESTED.set()
        try:
            _dispatch_js_to(window, 'prepareForClose()')
        except Exception:
            pass
        api = _window_apis.get(id(window)) or _main_api_ref
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
    """True when the app has no live windows left and is expected to exit."""
    if not _window_apis:
        return True
    try:
        import webview.platforms.cocoa as cocoa
        if cocoa.BrowserView.instances == {}:
            return True
        if not cocoa.BrowserView.app.isRunning():
            return True
    except Exception:
        pass
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
        _window_apis[id(win)] = api
        _set_active_window(win)
        if HAS_COCOA:
            win.events.closing += on_window_closing
        _window_count[0] += 1
        return win
    except Exception:
        pass


def update_main_window(main_window, main_api, file_path):
    """Update the main window with a new file"""
    file_path = os.path.abspath(file_path)
    main_api.file_path = file_path
    main_api.is_untitled = False
    _opened_files.add(file_path)
    _set_active_window(main_window)

    def do_update():
        for attempt in range(20):
            time.sleep(0.3)
            try:
                main_window.evaluate_js('reloadContent();')
                main_window.set_title(os.path.basename(file_path))
                return
            except Exception:
                pass

    threading.Thread(target=do_update, daemon=True).start()


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

    if not _initial_file_handled and main_window and main_api:
        _initial_file_handled = True
        update_main_window(main_window, main_api, file_path)
    else:
        _initial_file_handled = True
        # pywebview requires window creation from a background thread during running event loop
        threading.Thread(target=create_window, args=(file_path,), daemon=True).start()


if HAS_COCOA:

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
                pref_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Preferences…", "showPreferences:", ",")
                pref_item.setTarget_(_view_menu_handler)
                app_menu.insertItem_atIndex_(pref_item, 1)
                # Insert "Check for Updates…" right after Preferences
                update_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Check for Updates…", "checkForUpdates:", "")
                update_item.setTarget_(_view_menu_handler)
                app_menu.insertItem_atIndex_(update_item, 2)
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
                    view_menu.addItem_(NSMenuItem.separatorItem())
                    outline_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Show/Hide Outline", "toggleOutline:", "o")
                    outline_item.setKeyEquivalentModifierMask_((1 << 20) | (1 << 19))  # Cmd+Option+O
                    view_menu.addItem_(outline_item)
                    view_menu.addItem_(NSMenuItem.separatorItem())
                    inc_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Increase Width", "increaseWidth:", "=")
                    inc_item.setKeyEquivalentModifierMask_(1 << 20)
                    view_menu.addItem_(inc_item)
                    dec_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Decrease Width", "decreaseWidth:", "-")
                    dec_item.setKeyEquivalentModifierMask_(1 << 20)
                    view_menu.addItem_(dec_item)
                    reset_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Reset Width", "resetWidth:", "0")
                    reset_item.setKeyEquivalentModifierMask_(1 << 20)
                    view_menu.addItem_(reset_item)
                    outline_item.setTarget_(_view_menu_handler)
                    inc_item.setTarget_(_view_menu_handler)
                    dec_item.setTarget_(_view_menu_handler)
                    reset_item.setTarget_(_view_menu_handler)
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
                    file_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("File", None, "")
                    file_menu = NSMenu.alloc().initWithTitle_("File")
                    file_item.setSubmenu_(file_menu)
                    # Insert at the beginning (before the empty title item or Edit)
                    main_menu.insertItem_atIndex_(file_item, 1)
                    file_menu_index = 1

                if file_menu:
                    file_menu.addItem_(NSMenuItem.separatorItem())
                    open_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Open File…", "openFile:", "o")
                    open_item.setTarget_(_view_menu_handler)
                    file_menu.addItem_(open_item)
                    recent_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Open Recent", None, "")
                    recent_menu = NSMenu.alloc().initWithTitle_("Open Recent")
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
                    close_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Close", "closeWindow:", "w")
                    close_item.setTarget_(_view_menu_handler)
                    file_menu.addItem_(close_item)
                    file_menu.addItem_(NSMenuItem.separatorItem())
                    # Save / Save As: native menu items are needed because macOS
                    # may consume Cmd+S before the webview keydown handler sees it.
                    save_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Save", "saveFile:", "s")
                    save_item.setTarget_(_view_menu_handler)
                    file_menu.addItem_(save_item)
                    save_as_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Save As…", "saveAsFile:", "s")
                    save_as_item.setKeyEquivalentModifierMask_((1 << 20) | (1 << 17))  # Cmd+Shift+S
                    save_as_item.setTarget_(_view_menu_handler)
                    file_menu.addItem_(save_as_item)
                    file_menu.addItem_(NSMenuItem.separatorItem())
                    export_html_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Export HTML…", "exportHTML:", "")
                    export_html_item.setTarget_(_view_menu_handler)
                    file_menu.addItem_(export_html_item)
                    export_text_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Export Text…", "exportText:", "")
                    export_text_item.setTarget_(_view_menu_handler)
                    file_menu.addItem_(export_text_item)
                    print_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Print…", "printDocument:", "p")
                    print_item.setTarget_(_view_menu_handler)
                    file_menu.addItem_(print_item)
                    file_menu.addItem_(NSMenuItem.separatorItem())
                    # New File
                    new_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("New", "newFile:", "n")
                    new_item.setTarget_(_view_menu_handler)
                    file_menu.addItem_(new_item)
                    # Properties
                    props_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Properties", "showProperties:", "i")
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
                    edit_menu.addItem_(NSMenuItem.separatorItem())
                    find_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Find", "findAction:", "f")
                    find_item.setTarget_(_view_menu_handler)
                    edit_menu.addItem_(find_item)
                    find_next_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Find Next", "findNextAction:", "g")
                    find_next_item.setTarget_(_view_menu_handler)
                    edit_menu.addItem_(find_next_item)
                    find_prev_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Find Previous", "findPrevAction:", "g")
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

    # Dynamically create an ObjC class to handle menu actions
    from Foundation import NSObject

    class ViewMenuHandler(NSObject):
        def increaseWidth_(self, sender):
            _dispatch_js('adjustPageWidth(40)')

        def decreaseWidth_(self, sender):
            _dispatch_js('adjustPageWidth(-40)')

        def resetWidth_(self, sender):
            _dispatch_js('resetPageWidth()')

        def toggleOutline_(self, sender):
            _dispatch_js('toggleToc()')

        def showProperties_(self, sender):
            _dispatch_js('showFileProperties()')

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
            _dispatch_js('closeWindow()')

        def showPreferences_(self, sender):
            _dispatch_js('showPreferences()')

        def exportHTML_(self, sender):
            _dispatch_js('exportHTML()')

        def exportText_(self, sender):
            _dispatch_js('exportText()')

        def printDocument_(self, sender):
            _dispatch_js('printDocument()')

        def newFile_(self, sender):
            # Open a new blank window
            threading.Thread(target=create_window, args=(None,), daemon=True).start()

        def findAction_(self, sender):
            _dispatch_js('openFindBar()')

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
                        _set_update_available(remote)
                        AppHelper.callAfter(_show_update_alert, remote)
                    else:
                        _clear_update_available()
                        AppHelper.callAfter(_manual_check_up_to_date)
                except Exception:
                    AppHelper.callAfter(_manual_check_error)
            threading.Thread(target=_do_check, daemon=True).start()

        def showAbout_(self, sender):
            """Show the standard macOS About panel.
            Reads app name, version, and icon from the .app bundle's Info.plist."""
            NSApplication.sharedApplication().orderFrontStandardAboutPanel_(sender)

        def setupAllMenusRetry_(self, sender):
            setup_all_menus()

    _view_menu_handler = ViewMenuHandler.alloc().init()

    def patch_app_delegate():
        try:
            import webview.platforms.cocoa as cocoa
            AppDelegateClass = cocoa.BrowserView.AppDelegate

            if AppDelegateClass.instancesRespondToSelector_(b'application:openFiles:'):
                return

            def application_openFiles_(self, application, filenames):
                global _initial_file_handled
                count = filenames.count()
                for i in range(count):
                    path = filenames.objectAtIndex_(i)
                    handle_opened_file(path, _main_window_ref, _main_api_ref)
                application.replyToOpenOrPrint_(0)

            objc.classAddMethod(
                AppDelegateClass,
                b'application:openFiles:',
                application_openFiles_,
            )
        except Exception:
            log_exception('patch app delegate failed')


def main():
    global _initial_file_handled
    global _main_window_ref, _main_api_ref, _active_window_ref

    if HAS_COCOA:
        patch_app_delegate()
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

    _start_quit_watchdog()
    _maybe_run_selftest(main_window)

    webview.start(debug=False)

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
                    _update_menu_item.setTitle_(f'Update Available: {remote_version}...')
            except Exception:
                pass
        AppHelper.callAfter(_update_menu)
    # Auto-download in background to hidden staging dir
    def _bg_download():
        staging_app = _download_and_extract(remote_version)
        if staging_app:
            cfg = load_config()
            cfg['pending_staging_app'] = staging_app
            cfg['pending_update_version'] = remote_version
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
                    _update_menu_item.setTitle_('Check for Updates…')
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
        alert.setMessageText_(f'mdPreview {remote_version} is available!')
        alert.setInformativeText_(f'You have version {local}. Would you like to download the update?')
        alert.addButtonWithTitle_('Download')
        alert.addButtonWithTitle_('Later')
        response = alert.runModal()
        if response == 1000:  # Download
            # Auto-download and extract to staging, then show bubble
            def _bg_download():
                staging_app = _download_and_extract(remote_version)
                if staging_app:
                    cfg = load_config()
                    cfg['pending_staging_app'] = staging_app
                    cfg['pending_update_version'] = remote_version
                    save_config(cfg)
                    AppHelper.callAfter(lambda: _dispatch_js('showUpdateBubble()'))
            threading.Thread(target=_bg_download, daemon=True).start()
            return True
        return False
    except Exception:
        return False


def _download_and_extract(version):
    """Download DMG to hidden staging dir, extract .app, return staging path."""
    import urllib.request
    import subprocess
    try:
        os.makedirs(UPDATE_STAGING_DIR, exist_ok=True)
        dmg_path = os.path.join(UPDATE_STAGING_DIR, 'mdPreview.dmg')
        url = 'https://github.com/tahoeliu/mdPreview/releases/latest/download/mdPreview.dmg'
        req = urllib.request.Request(url, headers={'User-Agent': 'mdPreview'})
        with urllib.request.urlopen(req, timeout=60) as resp:
            with open(dmg_path, 'wb') as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
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
        subprocess.run(['hdiutil', 'detach', mount_dir], capture_output=True)
        os.remove(dmg_path)
        shutil.rmtree(mount_dir, ignore_errors=True)
        return staging_app
    except Exception:
        log_exception('auto download and extract failed')
        return None


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
        alert.setMessageText_("You're up to date!")
        alert.setInformativeText_(f'mdPreview {local} is the latest version.')
        alert.addButtonWithTitle_('OK')
        alert.runModal()
    except Exception:
        pass


def _manual_check_error():
    """Alert for manual check when the network request fails."""
    if not HAS_COCOA:
        return
    try:
        alert = NSAlert.alloc().init()
        alert.setMessageText_('Could not check for updates.')
        alert.setInformativeText_('Please check your internet connection and try again later.')
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
                        _update_menu_item.setTitle_(f'Update Available: {version}...')
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


def _perform_auto_install():
    """Execute auto-install: write helper script, quit app, let script replace + restart."""
    import subprocess
    try:
        cfg = load_config()
        staging_app = cfg.get('pending_staging_app', '')
        version = cfg.get('pending_update_version', '')
        if not staging_app or not os.path.exists(staging_app):
            return {'success': False, 'error': 'No staged update found'}

        # Write helper script that runs after app exits
        script = (
            '#!/bin/bash\n'
            'sleep 2\n'
            f'mv /Applications/mdPreview.app /Applications/mdPreview.app.old 2>/dev/null\n'
            f'cp -R "{staging_app}" /Applications/mdPreview.app\n'
            'if [ $? -eq 0 ]; then\n'
            '  rm -rf /Applications/mdPreview.app.old\n'
            '  xattr -cr /Applications/mdPreview.app\n'
            '  open /Applications/mdPreview.app\n'
            f'  rm -rf "{staging_app}"\n'
            'else\n'
            '  mv /Applications/mdPreview.app.old /Applications/mdPreview.app 2>/dev/null\n'
            'fi\n'
            f'rm -rf "{staging_app}"\n'
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
        save_config(cfg)

        # Quit the app so the helper can replace it
        if HAS_COCOA:
            from AppKit import NSApplication
            NSApplication.sharedApplication().terminate_(None)

        return {'success': True}
    except Exception as e:
        log_exception('auto install failed')
        return {'success': False, 'error': str(e)}


if __name__ == '__main__':
    main()
