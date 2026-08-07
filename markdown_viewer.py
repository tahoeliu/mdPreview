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
        self.is_untitled = not file_path  # True for blank "New File" documents

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
            return {**base, 'path': 'Untitled.md', 'content': ''}

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
            self.file_path = path
            self.file_content = content
            self.cached_content = content
            self.is_dirty = False
            self.is_untitled = False
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def save_as_dialog(self, content):
        """Show a native macOS Save panel; return the chosen path or None."""
        if not HAS_COCOA:
            return {'success': False, 'error': 'Cocoa not available'}
        try:
            from AppKit import NSSavePanel, NSOKButton
            panel = NSSavePanel.savePanel()
            panel.setTitle_('Save')
            panel.setCanCreateDirectories_(True)
            # Default directory: Desktop
            desktop = os.path.expanduser('~/Desktop')
            panel.setDirectoryURL_(
                __import__('Foundation').NSURL.fileURLWithPath_(desktop)
            )
            # Default filename
            panel.setNameFieldStringValue_('Untitled.md')
            # Restrict to .md files
            panel.setAllowedFileTypes_(['md'])
            response = panel.runModal()
            if response == NSOKButton:
                chosen_url = panel.URL()
                chosen_path = chosen_url.path()
                result = self.save_file(chosen_path, content)
                if result.get('success'):
                    return {'success': True, 'path': chosen_path}
                return result
            else:
                return {'success': False, 'cancelled': True}
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
        _set_active_window(window)
        api = _window_apis.get(id(window)) or _main_api_ref

        # Only prompt if there are unsaved changes
        if not (api and api.is_dirty):
            # No save prompt needed — close immediately. Update checks run silently after launch.
            return _allow_close(window)

        # Determine document name for the alert
        if api.file_path and not api.is_untitled:
            doc_name = os.path.basename(api.file_path)
        else:
            doc_name = 'Untitled.md'

        alert = NSAlert.alloc().init()
        alert.setMessageText_("Do you want to save the changes made to the document?")
        alert.setInformativeText_(doc_name)
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
            # Save
            if api.file_path and not api.is_untitled:
                # Existing file — save in place
                api.save_file(api.file_path, api.cached_content)
                # Save completed — close immediately. Update checks run silently after launch.
                return _allow_close(window)
            else:
                # Untitled document — show Save panel
                result = api.save_as_dialog(api.cached_content)
                if result.get('success'):
                    # Update window title to the saved filename
                    try:
                        window.set_title(os.path.basename(result['path']))
                    except Exception:
                        pass
                    # Save completed — close immediately. Update checks run silently after launch.
                    return _allow_close(window)
                else:
                    return False  # user cancelled the save panel → keep window open
        elif response == 1001:
            # Don't Save closes the window, but it did trigger a save prompt,
            # so it intentionally does NOT run the automatic update check.
            return _allow_close(window)
        else:
            return False  # cancel the close

    except Exception:
        return _allow_close(window)


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
    title = os.path.basename(file_path) if file_path else 'Untitled.md'

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
                # Insert "Check for Updates…" right after About (index 1)
                update_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Check for Updates…", "checkForUpdates:", "")
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
            ref = _get_target_window()
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

        def newFile_(self, sender):
            # Open a new blank window
            import threading
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
            pass


def main():
    global _initial_file_handled
    global _main_window_ref, _main_api_ref, _active_window_ref

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
    title = os.path.basename(file_path) if file_path else 'Untitled.md'

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
    _active_window_ref = main_window
    _window_count[0] = 1  # count the main window so subsequent windows are offset

    if HAS_COCOA:
        # Official pywebview mechanism: subscribe to the 'closing' event.
        # Returning False from the handler cancels the close.
        main_window.events.closing += on_window_closing
        setup_view_menu()
        setup_file_menu()

    # Check if a previous update was downloaded and offer to install it.
    # New-version checks are delayed and quiet so startup/close is not interrupted.
    if HAS_COCOA:
        _check_pending_install()
        _schedule_startup_update_check()

    webview.start(debug=False)


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
    by using the HTML redirect instead: releases/latest → releases/tag/vX.Y.Z
    """
    import urllib.request
    url = 'https://github.com/tahoeliu/mdPreview/releases/latest'
    req = urllib.request.Request(url, headers={'User-Agent': 'mdPreview'})
    # Don't follow redirects automatically — we want the Location header
    opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
    # Use a custom handler that stops at the redirect
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
    """Remember that an update is available and gently surface it in the menu."""
    global _available_update_version
    _available_update_version = remote_version
    if HAS_COCOA:
        def _update_menu():
            try:
                if _update_menu_item:
                    _update_menu_item.setTitle_(f'Update Available: {remote_version}…')
                _dispatch_js(f"showStatus({json.dumps('mdPreview ' + remote_version + ' is available')})")
            except Exception:
                pass
        AppHelper.callAfter(_update_menu)


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

    If user clicks Download, starts the download in a background thread
    (showing a brief 'Downloading…' message) and returns immediately.
    The actual download is non-blocking; on next launch the install
    prompt appears.
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
            # Download in a background thread — never block the main thread
            def _bg_download():
                dmg_path = _download_dmg(remote_version)
                if dmg_path:
                    cfg = load_config()
                    cfg['pending_update_dmg'] = dmg_path
                    cfg['pending_update_version'] = remote_version
                    save_config(cfg)
            threading.Thread(target=_bg_download, daemon=True).start()
            return True
        return False
    except Exception:
        return False


def _download_dmg(version):
    """Download the latest DMG to ~/Downloads. Returns the local path or None."""
    try:
        import urllib.request
        url = 'https://github.com/tahoeliu/mdPreview/releases/latest/download/mdPreview.dmg'
        downloads_dir = os.path.expanduser('~/Downloads')
        if not os.path.isdir(downloads_dir):
            os.makedirs(downloads_dir, exist_ok=True)
        dmg_path = os.path.join(downloads_dir, 'mdPreview.dmg')
        req = urllib.request.Request(url, headers={'User-Agent': 'mdPreview'})
        with urllib.request.urlopen(req, timeout=60) as resp:
            with open(dmg_path, 'wb') as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
        # Verify it's a real file (not an error page)
        if os.path.getsize(dmg_path) < 1000000:  # < 1MB = probably an error
            os.remove(dmg_path)
            return None
        return dmg_path
    except Exception:
        return None


def _schedule_startup_update_check():
    """Schedule a low-friction automatic update check after app launch.

    Automatic checks are intentionally quiet:
    - wait STARTUP_UPDATE_DELAY seconds after launch
    - run at most once every CHECK_INTERVAL (7 days)
    - fail silently on network errors
    - if an update exists, only update the menu title and show a brief status
      message; the blocking download prompt is shown only after the user
      explicitly chooses the update menu item.
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


def _check_pending_install():
    """On app launch, check if a DMG was downloaded previously and offer to install."""
    if not HAS_COCOA:
        return
    try:
        cfg = load_config()
        dmg_path = cfg.get('pending_update_dmg', '')
        version = cfg.get('pending_update_version', '')
        if not dmg_path or not os.path.exists(dmg_path):
            # Clean up stale entry
            if 'pending_update_dmg' in cfg:
                del cfg['pending_update_dmg']
                del cfg['pending_update_version']
                save_config(cfg)
            return

        local = _get_current_version()
        # Only prompt if the downloaded version is actually newer
        if not _is_newer(version, local):
            # Already updated — clean up
            cfg.pop('pending_update_dmg', None)
            cfg.pop('pending_update_version', None)
            save_config(cfg)
            return

        # Show install prompt
        alert = NSAlert.alloc().init()
        alert.setMessageText_(f'mdPreview {version} is ready to install!')
        alert.setInformativeText_(f'You have version {local}. The update has been downloaded. Install now?')
        alert.addButtonWithTitle_('Install')
        alert.addButtonWithTitle_('Later')
        response = alert.runModal()
        if response == 1000:  # Install
            # Mount the DMG (same as double-clicking it)
            import subprocess
            subprocess.Popen(['open', dmg_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # Clean up the pending flag
            cfg.pop('pending_update_dmg', None)
            cfg.pop('pending_update_version', None)
            save_config(cfg)
            # Quit the app so the user can install the new version
            NSApplication.sharedApplication().terminate_(None)
    except Exception:
        pass


if __name__ == '__main__':
    main()
