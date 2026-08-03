#!/usr/bin/env python3
"""
Minimal Markdown Viewer for macOS
"""

import sys
import os
import json
import time
import threading
import webview

CONFIG_FILE = os.path.expanduser('~/.mdviewer_config.json')


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

    def get_initial_content(self):
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

    def open_external_link(self, url):
        """Open an external URL (http/https/mailto) in the default browser."""
        try:
            import webbrowser
            webbrowser.open(url)
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

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
            }
        except Exception:
            return {'name': 'Unknown', 'location': '', 'size': 0, 'sizeFormatted': '0 B',
                    'modified': '', 'created': '', 'exists': False}


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
_menus_setup = False
_view_menu_setup = False
_file_menu_setup = False
_window_count = [0]  # list-based counter so it stays mutable inside ObjC callbacks
WINDOW_OFFSET = 30  # px to offset each new window
WINDOW_BASE_X = 100  # starting position
WINDOW_BASE_Y = 80


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
            return True
        elif response == 1001:
            return True
        else:
            return False  # cancel the close

    except Exception:
        return True


def create_window(file_path=None, x=None, y=None):
    if file_path:
        file_path = os.path.abspath(file_path)
        if file_path in _opened_files:
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
    title = os.path.basename(file_path) if file_path else 'Markdown Viewer'

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
            x=x,
            y=y,
        )
        api.window = win
        _window_apis[id(win)] = api
        if HAS_COCOA:
            win.events.closing += on_window_closing
        _window_count[0] += 1
        return win
    except Exception:
        pass


def update_main_window(main_window, main_api, file_path):
    """Update the main window with a new file"""
    main_api.file_path = file_path
    _opened_files.add(file_path)

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
        global _view_menu_setup, _file_menu_setup
        try:
            from AppKit import NSApplication, NSMenuItem, NSMenu
            from Foundation import NSObject

            main_menu = NSApplication.sharedApplication().mainMenu()
            if not main_menu:
                _view_menu_handler.performSelector_withObject_afterDelay_(
                    'setupAllMenusRetry:', None, 0.5
                )
                return

            # ── App menu: About ──
            # Connect the default "About mdPreview" item to our handler
            app_menu_item = main_menu.itemAtIndex_(0)
            app_menu = app_menu_item.submenu()
            if app_menu and app_menu.numberOfItems() > 0:
                about_item = app_menu.itemAtIndex_(0)
                if about_item:
                    about_item.setAction_('showAbout:')
                    about_item.setTarget_(_view_menu_handler)

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
                    inc_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Increase Width", "increaseWidth:", "=")
                    inc_item.setKeyEquivalentModifierMask_(1 << 20)
                    view_menu.addItem_(inc_item)
                    dec_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Decrease Width", "decreaseWidth:", "-")
                    dec_item.setKeyEquivalentModifierMask_(1 << 20)
                    view_menu.addItem_(dec_item)
                    inc_item.setTarget_(_view_menu_handler)
                    dec_item.setTarget_(_view_menu_handler)
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
                    props_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Properties", "showProperties:", "i")
                    props_item.setKeyEquivalentModifierMask_(1 << 20)
                    file_menu.addItem_(props_item)
                    props_item.setTarget_(_view_menu_handler)
                    _file_menu_setup = True

        except Exception:
            pass

    def setup_view_menu():
        """Legacy — delegates to setup_all_menus."""
        setup_all_menus()

    def setup_file_menu():
        """Legacy — delegates to setup_all_menus."""
        setup_all_menus()

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
        except Exception:
            pass

    # Dynamically create an ObjC class to handle menu actions
    from Foundation import NSObject

    class ViewMenuHandler(NSObject):
        def increaseWidth_(self, sender):
            _dispatch_js('adjustPageWidth(40)')

        def decreaseWidth_(self, sender):
            _dispatch_js('adjustPageWidth(-40)')

        def showProperties_(self, sender):
            _dispatch_js('showFileProperties()')

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
            pass


def main():
    global _initial_file_handled
    global _main_window_ref, _main_api_ref

    if HAS_COCOA:
        patch_app_delegate()

    file_path = None
    valid_extensions = ('.md', '.markdown', '.mdown', '.mkd', '.mkdown')
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg and os.path.exists(arg) and arg.lower().endswith(valid_extensions):
                file_path = os.path.abspath(arg)
                break

    if file_path:
        _initial_file_handled = True

    main_api = MarkdownAPI(file_path)
    html_path = get_resource_path('index.html')
    title = os.path.basename(file_path) if file_path else 'Markdown Viewer'

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
    _window_count[0] = 1  # count the main window so subsequent windows are offset

    if HAS_COCOA:
        # Official pywebview mechanism: subscribe to the 'closing' event.
        # Returning False from the handler cancels the close.
        main_window.events.closing += on_window_closing
        setup_view_menu()
        setup_file_menu()

    webview.start(debug=False)


if __name__ == '__main__':
    main()
