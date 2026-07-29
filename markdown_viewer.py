#!/usr/bin/env python3
"""
Minimal Markdown Viewer for macOS
"""

import sys
import os
import json
import time
import threading
import traceback
import webview

LOG_FILE = '/tmp/mdviewer_debug.log'
CONFIG_FILE = os.path.expanduser('~/.mdviewer_config.json')


def log(msg):
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(f'[{time.strftime("%H:%M:%S")}] {msg}\n')
    except:
        pass


try:
    from AppKit import NSApplication, NSObject, NSAlert, NSColor, NSMutableAttributedString
    from PyObjCTools import AppHelper
    import objc
    HAS_COCOA = True
    log('Cocoa imported successfully')
except ImportError as e:
    HAS_COCOA = False
    log(f'Cocoa import failed: {e}')


class MarkdownAPI:
    def __init__(self, file_path=None):
        self.file_path = file_path
        self.cached_content = ''  # JS pushes content here periodically
        self.file_content = ''    # Last known file content
        self.window = None        # Set after window creation
        self.is_dirty = False     # JS-maintained dirty flag

    def get_initial_content(self):
        log(f'get_initial_content: file_path={self.file_path}')
        cfg = load_config()
        page_width = cfg.get('page_width', 720)
        base = {'pageWidth': page_width}
        if self.file_path and os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.file_content = content
                self.cached_content = content
                self.is_dirty = False
                return {**base, 'path': self.file_path, 'content': content}
            except Exception as e:
                return {**base, 'path': self.file_path, 'content': f'# Error\n\nCould not read file: {e}'}
        else:
            return {**base, 'path': 'Untitled.md', 'content': '# Markdown Viewer\n\nNo file opened.'}

    def store_content(self, content):
        """Called by JS to keep Python in sync — avoids evaluate_js on close"""
        self.cached_content = content
        return True

    def set_dirty(self, dirty):
        """Called by JS whenever the document dirty state changes"""
        self.is_dirty = bool(dirty)
        return True

    def save_file(self, path, content):
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.file_content = content
            self.cached_content = content
            self.is_dirty = False
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def save_page_width(self, width):
        """Persist the user's preferred page width"""
        cfg = load_config()
        cfg['page_width'] = int(width)
        save_config(cfg)
        return True


def get_resource_path(filename):
    """Find resource files — works in dev mode and pyinstaller bundle"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, filename)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, filename)


def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {}


def save_config(cfg):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f)
    except:
        pass


# --- Global state ---
_opened_files = set()
_initial_file_handled = False
_window_apis = {}  # id(pywebview_window) -> MarkdownAPI
_main_window_ref = None
_main_api_ref = None


def on_window_closing(window):
    """pywebview 'closing' event handler.

    Return False to CANCEL the close (window stays open).
    Return True/None to ALLOW the close.
    Runs synchronously on the main thread (closing event uses should_lock=True),
    so it is safe to show a modal NSAlert here.
    """
    if not HAS_COCOA:
        return True
    try:
        api = _window_apis.get(id(window)) or _main_api_ref
        log(f'on_window_closing: api={api is not None}, '
            f'is_dirty={getattr(api, "is_dirty", None)}, '
            f'file_path={getattr(api, "file_path", None)}')

        if not (api and api.file_path and api.is_dirty):
            return True  # nothing to save, allow close

        alert = NSAlert.alloc().init()
        alert.setMessageText_("Do you want to save the changes made to the document?")
        alert.setInformativeText_(os.path.basename(api.file_path))
        alert.addButtonWithTitle_("Save")
        alert.addButtonWithTitle_("Don't Save")
        alert.addButtonWithTitle_("Cancel")

        # Make "Don't Save" text red
        buttons = alert.buttons()
        if buttons.count() >= 2:
            dontSaveBtn = buttons.objectAtIndex_(1)
            redAttrs = {"NSColor": NSColor.redColor()}
            redTitle = NSMutableAttributedString.alloc().initWithString_attributes_("Don't Save", redAttrs)
            dontSaveBtn.setAttributedTitle_(redTitle)

        response = alert.runModal()
        # 1000 = Save, 1001 = Don't Save, 1002 = Cancel
        if response == 1000:
            api.save_file(api.file_path, api.cached_content)
            log(f'Saved on close: {api.file_path}')
            return True
        elif response == 1001:
            log(f'Closing without save: {api.file_path}')
            return True
        else:
            log(f'Close cancelled: {api.file_path}')
            return False  # cancel the close

    except Exception as e:
        log(f'on_window_closing error: {e}')
        log(traceback.format_exc())
        return True


def create_window(file_path=None):
    if file_path:
        file_path = os.path.abspath(file_path)
        if file_path in _opened_files:
            log(f'File already open, skipping: {file_path}')
            return
        _opened_files.add(file_path)

    api = MarkdownAPI(file_path)
    html_path = get_resource_path('index.html')
    title = os.path.basename(file_path) if file_path else 'Markdown Viewer'

    log(f'Creating window for: {file_path or "(empty)"}')
    try:
        win = webview.create_window(
            title=title,
            url=html_path,
            js_api=api,
            width=900,
            height=680,
            min_size=(500, 400),
            text_select=True,
            confirm_close=False,
        )
        api.window = win
        _window_apis[id(win)] = api
        if HAS_COCOA:
            win.events.closing += on_window_closing
        log(f'Window created OK: {file_path}')
        return win
    except Exception as e:
        log(f'create_window error: {e}')
        log(traceback.format_exc())


def update_main_window(main_window, main_api, file_path):
    """Update the main window with a new file"""
    log(f'Updating main window with: {file_path}')
    main_api.file_path = file_path
    _opened_files.add(file_path)

    def do_update():
        for attempt in range(20):
            time.sleep(0.3)
            try:
                main_window.evaluate_js('reloadContent();')
                main_window.set_title(os.path.basename(file_path))
                log(f'Main window updated (attempt {attempt + 1})')
                return
            except Exception as e:
                log(f'Update attempt {attempt + 1}: {e}')

    threading.Thread(target=do_update, daemon=True).start()


def handle_opened_file(file_path, main_window=None, main_api=None):
    """Handle a file opened via Apple Event or argv"""
    global _initial_file_handled

    if not file_path or not os.path.exists(file_path):
        return

    valid_extensions = ('.md', '.markdown', '.mdown', '.mkd', '.mkdown')
    if not file_path.lower().endswith(valid_extensions):
        log(f'Skipping non-markdown file: {file_path}')
        return

    if not _initial_file_handled and main_window and main_api:
        _initial_file_handled = True
        update_main_window(main_window, main_api, file_path)
    else:
        _initial_file_handled = True
        # pywebview requires window creation from a background thread during running event loop
        threading.Thread(target=create_window, args=(file_path,), daemon=True).start()


if HAS_COCOA:

    def setup_view_menu():
        """Add Increase/Decrease Width menu items under the View menu."""
        try:
            from AppKit import NSApplication, NSMenuItem
            from Foundation import NSObject

            main_menu = NSApplication.sharedApplication().mainMenu()
            if not main_menu:
                log('Menu not ready yet, retrying in 0.5s...')
                _view_menu_handler.performSelector_withObject_afterDelay_(
                    'setupViewMenuRetry:', None, 0.5
                )
                return

            # Find the View menu — check submenu titles since item titles are "NSMenuItem"
            view_menu = None
            for i in range(main_menu.numberOfItems()):
                item = main_menu.itemAtIndex_(i)
                sub = item.submenu()
                if sub and sub.title() in ('View', '显示', '视图'):
                    view_menu = sub
                    break

            if not view_menu:
                log('View menu not found')
                return

            # Add separator + Increase Width (Cmd+=)
            view_menu.addItem_(NSMenuItem.separatorItem())

            inc_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Increase Width", "increaseWidth:", "="
            )
            inc_item.setKeyEquivalentModifierMask_(1 << 20)  # Cmd
            view_menu.addItem_(inc_item)

            # Decrease Width (Cmd+-)
            dec_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Decrease Width", "decreaseWidth:", "-"
            )
            dec_item.setKeyEquivalentModifierMask_(1 << 20)  # Cmd
            view_menu.addItem_(dec_item)

            # Use the pre-created handler for menu actions
            inc_item.setTarget_(_view_menu_handler)
            dec_item.setTarget_(_view_menu_handler)

            log('View menu items added (Increase/Decrease Width)')
        except Exception as e:
            log(f'setup_view_menu error: {e}')
            log(traceback.format_exc())

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
            ref = _main_window_ref
            if not ref:
                return
            browser = BrowserView.instances.get(ref.uid)
            if browser and browser.webview:
                browser.webview.evaluateJavaScript_completionHandler_(js_code, None)
        except Exception as e:
            log(f'_dispatch_js error: {e}')

    # Dynamically create an ObjC class to handle menu actions
    from Foundation import NSObject

    class ViewMenuHandler(NSObject):
        def increaseWidth_(self, sender):
            _dispatch_js('adjustPageWidth(40)')

        def decreaseWidth_(self, sender):
            _dispatch_js('adjustPageWidth(-40)')

        def setupViewMenuRetry_(self, sender):
            setup_view_menu()

    _view_menu_handler = ViewMenuHandler.alloc().init()

    def patch_app_delegate():
        try:
            import webview.platforms.cocoa as cocoa
            AppDelegateClass = cocoa.BrowserView.AppDelegate

            if AppDelegateClass.instancesRespondToSelector_(b'application:openFiles:'):
                log('AppDelegate already has application:openFiles:')
                return

            def application_openFiles_(self, application, filenames):
                global _initial_file_handled
                count = filenames.count()
                log(f'application:openFiles: called, count={count}')
                for i in range(count):
                    path = filenames.objectAtIndex_(i)
                    log(f'  File [{i}]: {path}')
                    handle_opened_file(path, _main_window_ref, _main_api_ref)
                application.replyToOpenOrPrint_(0)

            objc.classAddMethod(
                AppDelegateClass,
                b'application:openFiles:',
                application_openFiles_,
            )
            log('Patched AppDelegate with application:openFiles:')
        except Exception as e:
            log(f'patch_app_delegate error: {e}')
            log(traceback.format_exc())


def main():
    global _initial_file_handled
    global _main_window_ref, _main_api_ref

    log('=== Markdown Viewer starting ===')
    log(f'argv: {sys.argv}')

    if HAS_COCOA:
        patch_app_delegate()

    file_path = None
    valid_extensions = ('.md', '.markdown', '.mdown', '.mkd', '.mkdown')
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg and os.path.exists(arg) and arg.lower().endswith(valid_extensions):
                file_path = os.path.abspath(arg)
                log(f'Found markdown file in argv: {file_path}')
                break

    if file_path:
        _initial_file_handled = True

    main_api = MarkdownAPI(file_path)
    html_path = get_resource_path('index.html')
    title = os.path.basename(file_path) if file_path else 'Markdown Viewer'

    log('Creating main window...')
    main_window = webview.create_window(
        title=title,
        url=html_path,
        js_api=main_api,
        width=900,
        height=680,
        min_size=(500, 400),
        text_select=True,
        confirm_close=False,
    )
    main_api.window = main_window
    _window_apis[id(main_window)] = main_api
    _main_window_ref = main_window
    _main_api_ref = main_api

    if HAS_COCOA:
        # Official pywebview mechanism: subscribe to the 'closing' event.
        # Returning False from the handler cancels the close.
        main_window.events.closing += on_window_closing
        log('Subscribed on_window_closing to main window closing event')
        setup_view_menu()

    log('Starting webview...')
    webview.start(debug=False)
    log('Webview exited.')


if __name__ == '__main__':
    main()
