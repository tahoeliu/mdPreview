#!/usr/bin/env python3
import importlib.util
import os
import shutil
import threading
import sys
import tempfile
import time
import types
from pathlib import Path

sys.modules['webview'] = types.SimpleNamespace()
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('markdown_viewer', ROOT / 'markdown_viewer.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class FakeLoadedEvent:
    """Minimal stand-in for pywebview's Event (loaded)."""
    def __init__(self):
        self._items = []
    def __add__(self, fn):
        self._items.append(fn)
        return self
    def set(self):
        for fn in list(self._items):
            fn()
    def is_set(self):
        return bool(self._items) and any(True for _ in self._items)


class FakeWin:
    def __init__(self):
        self.events = types.SimpleNamespace(loaded=FakeLoadedEvent())
        self.calls = []
        self.titles = []
    def evaluate_js(self, js):
        self.calls.append(js)
        return None
    def set_title(self, t):
        self.titles.append(t)
    def show(self):
        pass


def test_subscribe_js_ready_marks_window_on_loaded():
    win = FakeWin()
    mod._subscribe_js_ready(win)
    assert id(win) not in mod._windows_js_ready
    win.events.loaded.set()
    assert id(win) in mod._windows_js_ready, 'loaded event must mark window ready'
    mod._windows_js_ready.discard(id(win))


def test_concurrent_add_recent_file_no_loss():
    """10 threads adding distinct recent files concurrently must all survive."""
    import tempfile
    tmp = tempfile.mkdtemp()
    paths = [os.path.join(tmp, 'cfg_test_%d.md' % i) for i in range(10)]
    for pth in paths:
        with open(pth, 'w') as f:
            f.write('x')
    cfg = mod.load_config()
    saved = dict(cfg)
    try:
        barrier = threading.Barrier(10)
        def worker(pth):
            barrier.wait()
            mod.add_recent_file(pth)
        threads = [threading.Thread(target=worker, args=(pth,)) for pth in paths]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        recent = mod.load_config().get('recent_files', [])
        missing = [pth for pth in paths if pth not in recent]
        assert not missing, 'recent entries lost: %s' % missing
    finally:
        mod.save_config(saved)
        shutil.rmtree(tmp, ignore_errors=True)


def test_save_prompt_delete_action_closes_panel():
    """The Delete button in the native save panel must record 'delete' and end the modal."""
    if not mod.HAS_COCOA:
        return
    calls = []
    class FakePanel:
        def orderOut_(self, arg):
            calls.append('orderOut')
    holder = {'panel': FakePanel()}
    actions = mod._SavePromptActions.alloc().initWithHolder_(holder)
    actions.deleteClicked_(None)
    assert holder.get('action') == 'delete'
    assert calls == ['orderOut'], 'Delete must close the panel so the modal ends'


def test_smoke_test_app_rejects_bad_path():
    """A nonexistent app must fail the pre-install smoke test."""
    if not mod.HAS_COCOA:
        return
    assert mod._smoke_test_app('/tmp/definitely-not-an-app-xyz.app') is False


def test_auto_install_without_staging_fails_safely():
    """Auto-install with no staged update must fail cleanly, not touch anything."""
    cfg = mod.load_config()
    saved = dict(cfg)
    cfg.pop('pending_staging_app', None)
    cfg.pop('pending_update_version', None)
    mod.save_config(cfg)
    try:
        res = mod._perform_auto_install()
        assert res.get('success') is False
    finally:
        mod.save_config(saved)


def test_update_main_window_resident_ready_immediate():
    """A resident (already-ready) window must evaluate immediately — no flat 300ms sleep."""
    win = FakeWin()
    api = mod.MarkdownAPI(None)
    api.is_untitled = True
    mod._window_apis[id(win)] = api
    mod._windows_js_ready.add(id(win))  # resident window: JS bridge already up
    t1 = None
    try:
        mod.update_main_window(win, api, '/tmp/x.md')
        t1 = time.time()
        deadline = time.time() + 1.0
        while not win.calls and time.time() < deadline:
            time.sleep(0.01)
        latency = time.time() - t1
        assert 'reloadContent();' in win.calls, 'ready window must evaluate immediately'
        assert latency < 0.15, 'resident open should evaluate within ~150ms, took %.3fs' % latency
        assert api.file_path == '/tmp/x.md'
        assert not api.is_untitled
    finally:
        mod._windows_js_ready.discard(id(win))
        mod._window_apis.clear()


def test_update_main_window_waits_for_js_ready():
    """A cold-started window must wait for the loaded event before evaluating."""
    win = FakeWin()
    api = mod.MarkdownAPI(None)
    api.is_untitled = True
    mod._window_apis[id(win)] = api
    mod._windows_js_ready.discard(id(win))
    mod._subscribe_js_ready(win)  # create_window() does this in the real app
    try:
        mod.update_main_window(win, api, '/tmp/y.md')
        time.sleep(0.12)
        assert not win.calls, 'must wait until the JS bridge is ready'
        win.events.loaded.set()  # JS bridge comes up
        deadline = time.time() + 1.0
        while not win.calls and time.time() < deadline:
            time.sleep(0.01)
        assert 'reloadContent();' in win.calls, 'must evaluate right after loaded fires'
        assert api.file_path == '/tmp/y.md'
    finally:
        mod._windows_js_ready.discard(id(win))
        mod._window_apis.clear()


def test_safe_save_encoding_and_draft():
    with tempfile.TemporaryDirectory() as d:
        old_draft = mod.DRAFT_DIR
        mod.DRAFT_DIR = str(Path(d) / 'Drafts')
        target = Path(d) / 'gbk.md'
        target.write_bytes('标题'.encode('gb18030'))
        api = mod.MarkdownAPI(str(target))
        data = api.get_initial_content()
        assert data['content'] == '标题'
        assert data['encoding'] == 'gb18030'
        api.set_dirty(True)
        api.store_content('标题更新')
        assert list(Path(mod.DRAFT_DIR).glob('*.md'))
        result = api.save_file(str(target), '标题更新')
        assert result['success']
        assert target.read_bytes().decode('gb18030') == '标题更新'
        assert not Path(str(target) + '.bak').exists()
        assert not list(Path(mod.DRAFT_DIR).glob('*.md'))
        mod.DRAFT_DIR = old_draft


def test_encoding_detection_survives_corrupt_utf16_bom():
    """A file with a UTF-16 BOM but corrupt/truncated content must not crash."""
    with tempfile.TemporaryDirectory() as d:
        cases = [
            ('corrupt_le.md', b'\xff\xfe\xfd\x80 broken \xc3'),
            ('corrupt_be.md', b'\xfe\xff\xd8\x00 broken'),
            ('truncated.md', b'\xff\xfea\x00b'),
            ('empty.md', b''),
            ('binary.md', b'\x00\x01\x02\xff\xfe garbage'),
        ]
        for fname, data in cases:
            p = Path(d) / fname
            p.write_bytes(data)
            content, enc = mod._detect_text_encoding(str(p))
            assert isinstance(content, str), fname
            assert enc, fname
            assert content != '' or data == b'', fname


def test_close_window_last_clean_hides_instead_of_destroying():
    """Cmd+W / File > Close on the last clean window should hide it, not quit/destroy."""
    api = mod.MarkdownAPI('/tmp/last_clean.md')
    api.is_dirty = False
    calls = []
    destroyed = []
    hidden = []
    fake_win = type('W', (), {
        'destroy': lambda self: destroyed.append(True),
        'hide': lambda self: hidden.append(True),
        'uid': 'last_clean',
    })()
    api.window = fake_win
    mod._window_apis[id(fake_win)] = api
    mod._QUIT_REQUESTED.clear()
    old_dispatch = mod._dispatch_js_to
    try:
        mod._dispatch_js_to = lambda window, js: calls.append(js)
        result = api.close_window()
        assert result['success']
        assert 'convertToBlankDocument()' in calls
        assert not destroyed, 'last clean window should not be destroyed'
        assert hidden, 'last clean window should be hidden'
        assert id(fake_win) in mod._window_apis
        assert api.is_untitled, 'window should be reset to Untitled'
    finally:
        mod._dispatch_js_to = old_dispatch
        mod._window_apis.clear()
        mod._hidden_windows.clear()


def test_save_detects_external_modification_conflict():
    with tempfile.TemporaryDirectory() as d:
        old_draft = mod.DRAFT_DIR
        mod.DRAFT_DIR = str(Path(d) / 'Drafts')
        target = Path(d) / 'conflict.md'
        target.write_text('original', encoding='utf-8')
        api = mod.MarkdownAPI(str(target))
        data = api.get_initial_content()
        assert data['content'] == 'original'
        target.write_text('external change', encoding='utf-8')
        result = api.save_file(str(target), 'my edit')
        assert not result['success']
        assert result['conflict']
        assert target.read_text('utf-8') == 'external change'
        mod.DRAFT_DIR = old_draft


def test_force_save_overwrites_conflict_and_updates_baseline():
    with tempfile.TemporaryDirectory() as d:
        old_draft = mod.DRAFT_DIR
        mod.DRAFT_DIR = str(Path(d) / 'Drafts')
        target = Path(d) / 'force.md'
        target.write_text('original', encoding='utf-8')
        api = mod.MarkdownAPI(str(target))
        api.get_initial_content()
        target.write_text('external change', encoding='utf-8')
        result = api.save_file(str(target), 'my edit', force=True)
        assert result['success']
        assert target.read_text('utf-8') == 'my edit'
        assert api.file_content == 'my edit'
        second = api.save_file(str(target), 'next edit')
        assert second['success']
        assert target.read_text('utf-8') == 'next edit'
        mod.DRAFT_DIR = old_draft


def test_conflict_check_uses_mtime_size_fast_path_without_full_read():
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / 'fast.md'
        target.write_text('original', encoding='utf-8')
        api = mod.MarkdownAPI(str(target))
        api.get_initial_content()
        original_detect = mod._detect_text_encoding
        calls = []
        try:
            def fail_if_called(path):
                calls.append(path)
                raise AssertionError('fast path should not read unchanged disk content')
            mod._detect_text_encoding = fail_if_called
            assert api._has_external_save_conflict(str(target)) is False
            assert calls == []
        finally:
            mod._detect_text_encoding = original_detect


def test_conflict_check_falls_back_to_content_when_stat_changes():
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / 'stat-change.md'
        target.write_text('original', encoding='utf-8')
        api = mod.MarkdownAPI(str(target))
        api.get_initial_content()
        api.baseline_mtime_ns = -1
        result = api.save_file(str(target), 'internal edit')
        assert result['success']
        assert target.read_text('utf-8') == 'internal edit'


def test_save_as_new_path_bypasses_original_conflict():
    with tempfile.TemporaryDirectory() as d:
        old_draft = mod.DRAFT_DIR
        mod.DRAFT_DIR = str(Path(d) / 'Drafts')
        original = Path(d) / 'original.md'
        copy = Path(d) / 'copy.md'
        original.write_text('original', encoding='utf-8')
        api = mod.MarkdownAPI(str(original))
        api.get_initial_content()
        original.write_text('external change', encoding='utf-8')
        result = api.save_file(str(copy), 'my edit')
        assert result['success']
        assert original.read_text('utf-8') == 'external change'
        assert copy.read_text('utf-8') == 'my edit'
        assert api.file_path == str(copy)
        assert api.file_content == 'my edit'
        mod.DRAFT_DIR = old_draft


def test_save_as_same_conflicted_path_is_blocked():
    with tempfile.TemporaryDirectory() as d:
        old_draft = mod.DRAFT_DIR
        mod.DRAFT_DIR = str(Path(d) / 'Drafts')
        target = Path(d) / 'same.md'
        target.write_text('original', encoding='utf-8')
        api = mod.MarkdownAPI(str(target))
        api.get_initial_content()
        target.write_text('external change', encoding='utf-8')
        result = api.save_file(str(target), 'my edit')
        assert result.get('conflict') is True
        assert target.read_text('utf-8') == 'external change'
        mod.DRAFT_DIR = old_draft


def test_deleted_file_save_recreates_without_false_conflict():
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / 'deleted.md'
        target.write_text('original', encoding='utf-8')
        api = mod.MarkdownAPI(str(target))
        api.get_initial_content()
        target.unlink()
        result = api.save_file(str(target), 'new content')
        assert result['success']
        assert target.read_text('utf-8') == 'new content'
        assert api.file_content == 'new content'


def test_external_encoding_change_is_detected_as_conflict():
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / 'encoding.md'
        target.write_text('标题', encoding='utf-8')
        api = mod.MarkdownAPI(str(target))
        api.get_initial_content()
        target.write_bytes('标题外部'.encode('gb18030'))
        result = api.save_file(str(target), '标题内部')
        assert result.get('conflict') is True
        assert target.read_bytes().decode('gb18030') == '标题外部'


def test_save_as_missing_parent_directory_succeeds_and_updates_baseline():
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / 'file.md'
        target.write_text('original', encoding='utf-8')
        api = mod.MarkdownAPI(str(target))
        api.get_initial_content()
        missing_parent = Path(d) / 'missing' / 'file.md'
        result = api.save_file(str(missing_parent), 'new content')
        # _safe_write_text creates missing parent directories by design, so assert success
        # and baseline update for Save As into a new directory.
        assert result['success']
        assert missing_parent.read_text('utf-8') == 'new content'
        assert api.file_path == str(missing_parent)
        assert api.file_content == 'new content'


def test_draft_recovery_sets_dirty_and_preserves_disk_baseline():
    with tempfile.TemporaryDirectory() as d:
        old_draft = mod.DRAFT_DIR
        mod.DRAFT_DIR = str(Path(d) / 'Drafts')
        target = Path(d) / 'draft.md'
        target.write_text('disk clean', encoding='utf-8')
        mod._write_draft(str(target), 'draft dirty')
        # Ensure draft is newer than file on filesystems with coarse timestamp granularity.
        import os, time
        future = time.time() + 2
        draft_path = next(Path(mod.DRAFT_DIR).glob('*.md'))
        os.utime(draft_path, (future, future))
        api = mod.MarkdownAPI(str(target))
        data = api.get_initial_content()
        assert data['draftRecovered'] is True
        assert data['content'] == 'draft dirty'
        assert api.is_dirty is True
        assert api.file_content == 'disk clean'
        target.write_text('external after recovery', encoding='utf-8')
        result = api.save_file(str(target), 'draft dirty')
        assert result.get('conflict') is True
        mod.DRAFT_DIR = old_draft


def test_open_existing_file_focuses_instead_of_duplicate_window():
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / 'same.md'
        target.write_text('same', encoding='utf-8')
        api = mod.MarkdownAPI(str(target))
        fake_win = type('W', (), {'show': lambda self: None})()
        api.window = fake_win
        old_opened = set(mod._opened_files)
        old_apis = dict(mod._window_apis)
        old_initial = mod._initial_file_handled
        try:
            mod._opened_files.add(str(target.resolve()))
            mod._window_apis[id(fake_win)] = api
            mod._initial_file_handled = True
            mod.handle_opened_file(str(target), None, None)
            assert id(fake_win) in mod._window_apis
        finally:
            mod._opened_files = old_opened
            mod._window_apis = old_apis
            mod._initial_file_handled = old_initial


def test_open_file_does_not_reuse_dirty_untitled_window(): 
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / 'opened.md'
        target.write_text('opened', encoding='utf-8')
        api = mod.MarkdownAPI(None)
        api.is_dirty = True
        fake_win = type('W', (), {'uid': 'main'})()
        called = []
        old_initial = mod._initial_file_handled
        old_update = mod.update_main_window
        old_thread = mod.threading.Thread
        try:
            mod._initial_file_handled = False
            mod.update_main_window = lambda *args: called.append('update')
            class FakeThread:
                def __init__(self, target=None, args=(), daemon=None):
                    self.target = target
                    self.args = args
                    self.daemon = daemon
                    called.append(('thread', args))
                def start(self):
                    called.append('start')
            mod.threading.Thread = FakeThread
            mod.handle_opened_file(str(target), fake_win, api)
            assert 'update' not in called
            assert any(isinstance(item, tuple) and item[0] == 'thread' for item in called)
        finally:
            mod._initial_file_handled = old_initial
            mod.update_main_window = old_update
            mod.threading.Thread = old_thread


def test_open_file_reuses_clean_untitled_window():
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / 'opened.md'
        target.write_text('opened', encoding='utf-8')
        api = mod.MarkdownAPI(None)
        fake_win = type('W', (), {'uid': 'main'})()
        called = []
        old_initial = mod._initial_file_handled
        old_update = mod.update_main_window
        old_thread = mod.threading.Thread
        try:
            mod._initial_file_handled = False
            mod.update_main_window = lambda *args: called.append('update')
            class FakeThread:
                def __init__(self, target=None, args=(), daemon=None):
                    called.append(('thread', args))
                def start(self):
                    called.append('start')
            mod.threading.Thread = FakeThread
            mod.handle_opened_file(str(target), fake_win, api)
            assert 'update' in called
            assert not any(isinstance(item, tuple) and item[0] == 'thread' for item in called)
        finally:
            mod._initial_file_handled = old_initial
            mod.update_main_window = old_update
            mod.threading.Thread = old_thread


def test_version_compare():
    assert mod._is_newer('1.2.4', '1.2.3')
    assert mod._is_newer('1.3.0', '1.2.9')
    assert not mod._is_newer('1.2.3', '1.2.3')
    assert not mod._is_newer('1.2.3', '1.2.4')


def test_quit_watchdog_force_exit_when_no_windows():
    """The watchdog must os._exit once the app is in the quitting state."""
    import subprocess
    code = '''
import os, sys, time, types, importlib.util
sys.modules['webview'] = types.SimpleNamespace()
spec = importlib.util.spec_from_file_location('m', sys.argv[1])
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
mod._window_apis = {}
mod._QUIT_REQUESTED.set()
mod._start_quit_watchdog()
# Simulate the app being stuck: main thread just sleeps; watchdog should
# force-exit after QUIT_FORCE_EXIT_DELAY.
start = time.time()
while time.time() - start < mod.QUIT_FORCE_EXIT_DELAY + 5:
    time.sleep(0.2)
os._exit(9)  # should never be reached
'''
    result = subprocess.run(
        [sys.executable, '-c', code, str(Path(__file__).resolve().parents[1] / 'markdown_viewer.py')],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, f'watchdog did not force-exit: rc={result.returncode}'


def test_quit_watchdog_ignores_secondary_window_close():
    """Closing one window while others remain must NOT force the app to exit."""
    import subprocess
    code = '''
import os, sys, time, types, importlib.util
sys.modules['webview'] = types.SimpleNamespace()
spec = importlib.util.spec_from_file_location('m', sys.argv[1])
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
# Two windows still open -> not quitting
mod._window_apis = {1: 'main', 2: 'secondary'}
mod._QUIT_REQUESTED.set()
mod._start_quit_watchdog()
time.sleep(min(mod.QUIT_FORCE_EXIT_DELAY + 1, 2.0))
# If the watchdog force-exited, we never reach here -> returncode != 0.
print('still alive, ok')
'''
    result = subprocess.run(
        [sys.executable, '-c', code, str(Path(__file__).resolve().parents[1] / 'markdown_viewer.py')],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0 and 'still alive' in result.stdout


def test_on_window_closing_prompts_dirty_doc_before_close():
    """Dirty documents must block native close until the user chooses an action."""
    with tempfile.TemporaryDirectory() as d:
        old_draft = mod.DRAFT_DIR
        mod.DRAFT_DIR = str(Path(d) / 'Drafts')
        api = mod.MarkdownAPI(None)
        api.is_dirty = True
        api.cached_content = 'unsaved content'
        fake_win = type('W', (), {'uid': 'dirty'})()
        api.window = fake_win
        mod._window_apis[id(fake_win)] = api
        mod._QUIT_REQUESTED.clear()
        calls = []
        old_dispatch = mod._dispatch_js_to
        try:
            mod._dispatch_js_to = lambda window, js: calls.append(js)
            assert mod.on_window_closing(fake_win) is False
            assert 'promptBeforeClose(true)' in calls
            assert id(fake_win) in mod._window_apis
            assert not mod._QUIT_REQUESTED.is_set()
            drafts = list(Path(mod.DRAFT_DIR).glob('*.md'))
            assert drafts, 'draft should be written before showing close prompt'
        finally:
            mod._dispatch_js_to = old_dispatch
            mod._window_apis.clear()
            mod.DRAFT_DIR = old_draft


def test_force_close_discard_removes_dirty_draft():
    with tempfile.TemporaryDirectory() as d:
        old_draft = mod.DRAFT_DIR
        mod.DRAFT_DIR = str(Path(d) / 'Drafts')
        target = Path(d) / 'discard.md'
        target.write_text('clean', encoding='utf-8')
        api = mod.MarkdownAPI(str(target))
        api.get_initial_content()
        api.set_dirty(True)
        api.store_content('dirty')
        assert list(Path(mod.DRAFT_DIR).glob('*.md'))
        fake_win = type('W', (), {'destroy': lambda self: None})()
        api.window = fake_win
        result = api.force_close_window(discard=True)
        assert result['success']
        assert not api.is_dirty
        assert api.cached_content == api.file_content
        assert not list(Path(mod.DRAFT_DIR).glob('*.md'))
        mod.DRAFT_DIR = old_draft


def test_force_close_last_window_hides_instead_of_destroying():
    """Don't-Save on a dirty LAST window must hide it (app stays resident), not quit."""
    api = mod.MarkdownAPI('/tmp/last_dirty.md')
    api.is_dirty = True
    calls = []
    destroyed = []
    hidden = []
    fake_win = type('W', (), {
        'destroy': lambda self: destroyed.append(True),
        'hide': lambda self: hidden.append(True),
        'uid': 'last_dirty',
    })()
    api.window = fake_win
    mod._window_apis[id(fake_win)] = api
    mod._QUIT_REQUESTED.clear()
    old_dispatch = mod._dispatch_js_to
    try:
        mod._dispatch_js_to = lambda window, js: calls.append(js)
        result = api.force_close_window(discard=True)
        assert result['success']
        assert 'convertToBlankDocument()' in calls
        assert not destroyed, 'last dirty window must not be destroyed (would quit app)'
        assert hidden, 'last dirty window should be hidden'
        assert id(fake_win) in mod._window_apis
        assert not api.is_dirty, 'discard should clear dirty'
        assert api.is_untitled, 'window should be reset to Untitled'
    finally:
        mod._dispatch_js_to = old_dispatch
        mod._window_apis.clear()
        mod._hidden_windows.clear()


def test_on_window_closing_allows_confirmed_dirty_doc(): 
    """After Save/Don't Save confirmation, close must proceed without re-prompting."""
    with tempfile.TemporaryDirectory() as d:
        old_draft = mod.DRAFT_DIR
        mod.DRAFT_DIR = str(Path(d) / 'Drafts')
        api = mod.MarkdownAPI(None)
        api.is_dirty = True
        api.close_confirmed = True
        api.cached_content = 'unsaved content'
        fake_win = type('W', (), {'uid': 'confirmed'})()
        api.window = fake_win
        mod._window_apis[id(fake_win)] = api
        mod._QUIT_REQUESTED.clear()
        assert mod.on_window_closing(fake_win) is True
        assert id(fake_win) not in mod._window_apis
        assert not mod._QUIT_REQUESTED.is_set()
        mod._window_apis.clear()
        mod.DRAFT_DIR = old_draft


def test_on_window_closing_writes_draft_without_requesting_app_quit():
    """Confirmed window close must persist drafts without marking the app as quitting."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        old_draft = mod.DRAFT_DIR
        mod.DRAFT_DIR = str(Path(d) / 'Drafts')
        api = mod.MarkdownAPI(None)
        api.is_dirty = True
        api.close_confirmed = True
        api.cached_content = 'unsaved content'
        fake_win = type('W', (), {'uid': 'x'})()
        api.window = fake_win
        mod._window_apis[id(fake_win)] = api
        mod._QUIT_REQUESTED.clear()
        assert mod.on_window_closing(fake_win) is True
        assert not mod._QUIT_REQUESTED.is_set()
        drafts = list(Path(mod.DRAFT_DIR).glob('*.md'))
        assert drafts, 'draft should be written on close'
        assert 'unsaved content' in drafts[0].read_text('utf-8')
        mod._window_apis.clear()
        mod.DRAFT_DIR = old_draft


def test_app_lifecycle_methods_are_registered_in_delegate_patch():
    source = (ROOT / 'markdown_viewer.py').read_text(encoding='utf-8')
    assert "b'applicationShouldTerminateAfterLastWindowClosed:'" in source
    assert "b'applicationShouldTerminate:'" in source
    assert "b'applicationShouldHandleReopen:hasVisibleWindows:'" in source
    assert 'return False' in source[source.index('def applicationShouldTerminateAfterLastWindowClosed_'):source.index('def applicationShouldTerminate_')]
    assert '_QUIT_REQUESTED.set()' in source[source.index('def applicationShouldTerminate_'):source.index('def applicationShouldHandleReopen_hasVisibleWindows_')]


def test_delegate_patch_uses_selector_install_not_classaddmethod():
    # Regression guard: objc.classAddMethod raises BadPrototypeError for
    # selectors that already exist on pywebview's AppDelegate (e.g.
    # applicationShouldTerminate:), which previously aborted the whole patch
    # and left application:openFiles: unregistered, breaking Finder open.
    source = (ROOT / 'markdown_viewer.py').read_text(encoding='utf-8')
    block = source[source.index('def patch_app_delegate'):source.index('def main')]
    assert 'objc.classAddMethod(' not in block
    assert 'objc.selector(' in block
    assert 'instancesRespondToSelector_' in block
    assert "b'application:openFiles:'" in block
    assert 'replyToOpenOrPrint_' in block


def test_delegate_install_mechanism_overrides_existing_selector():
    try:
        import objc
        from AppKit import NSObject
    except Exception:
        return  # pyobjc unavailable in this environment

    class _FakeAppDelegate(NSObject):
        def applicationShouldTerminate_(self, app):
            return True

    def _replacement_terminate(self, app):
        return 1

    def _open_files(self, app, filenames):
        pass

    _FakeAppDelegate.applicationShouldTerminate_ = objc.selector(
        _replacement_terminate, selector=b'applicationShouldTerminate:', signature=b'I@:@')
    _FakeAppDelegate.application_openFiles_ = objc.selector(
        _open_files, selector=b'application:openFiles:', signature=b'v@:@@')
    assert _FakeAppDelegate.instancesRespondToSelector_(b'applicationShouldTerminate:')
    assert _FakeAppDelegate.instancesRespondToSelector_(b'application:openFiles:')
    inst = _FakeAppDelegate.alloc().init()
    assert inst.applicationShouldTerminate_(None) == 1


def test_last_clean_window_hides_instead_of_closing():
    # A clean last-window close keeps the app alive by blanking + HIDING the
    # window (not destroying it and not keeping a dead anchor window).
    source = (ROOT / 'markdown_viewer.py').read_text(encoding='utf-8')
    block = source[source.index('def on_window_closing'):source.index('def _is_app_quitting')]
    assert '_hide_last_window(window, api)' in block
    assert '_is_last_window(window)' in block
    assert 'not _QUIT_REQUESTED.is_set()' in block
    # Confirmed dirty close and app-quit must still be allowed through.
    assert 'api.close_confirmed' in block
    assert 'return False' in block
    # The hide helper blanks + hides, never destroys.
    helper = source[source.index('def _hide_last_window'):source.index('def _reopen_hidden_window')]
    assert 'convertToBlankDocument()' in helper
    assert 'reset_to_untitled()' in helper
    assert 'window.hide()' in helper
    assert 'window.destroy' not in helper


def test_reopen_hidden_window_shows_hidden_blank_window():
    # Dock click should un-hide the hidden blank window instead of creating a
    # new one (the reason Dock clicks previously appeared to do nothing).
    api = mod.MarkdownAPI(None)
    api.is_untitled = True
    api.is_dirty = False
    shown = []
    fake_win = type('W', (), {'show': lambda self: shown.append(True), 'uid': 'hidden1'})()
    api.window = fake_win
    mod._window_apis[id(fake_win)] = api
    mod._hidden_windows[id(fake_win)] = fake_win
    try:
        assert mod._reopen_hidden_window() is True
        assert shown, 'hidden window should be shown on reopen'
        assert id(fake_win) not in mod._hidden_windows, 'window should leave hidden set'
    finally:
        mod._window_apis.clear()
        mod._hidden_windows.clear()


def test_handle_opened_file_reuses_hidden_blank_window():
    """Double-click after last-window-close must reuse the hidden window,
    not create a second one (which would leak a hidden Untitled window)."""
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / 'doc.md'
        target.write_text('# doc', encoding='utf-8')
        api = mod.MarkdownAPI(None)
        api.is_untitled = True
        api.is_dirty = False
        shown = []
        titles = []
        fake_win = type('W', (), {
            'show': lambda self: shown.append(True),
            'uid': 'hidden_reuse',
            'evaluate_js': lambda self, script: None,
            'set_title': lambda self, title: titles.append(title),
        })()
        api.window = fake_win
        mod._window_apis[id(fake_win)] = api
        mod._hidden_windows[id(fake_win)] = fake_win
        mod._main_window_ref = fake_win
        mod._main_api_ref = api
        mod._initial_file_handled = True
        mod._QUIT_REQUESTED.clear()
        mod._windows_js_ready.add(id(fake_win))  # resident window: JS bridge already up
        try:
            mod.handle_opened_file(str(target), fake_win, api)
            assert shown, 'reused hidden window should be shown'
            assert api.file_path and api.file_path.endswith('doc.md')
            assert not api.is_untitled
            assert id(fake_win) not in mod._hidden_windows, 'hidden set must not leak'
            import time
            time.sleep(0.6)  # allow the async do_update thread to set the title
            assert titles and titles[-1] == 'doc.md'
        finally:
            mod._window_apis.clear()
            mod._hidden_windows.clear()
            mod._main_window_ref = None
            mod._main_api_ref = None
            mod._windows_js_ready.discard(id(fake_win))
            mod._initial_file_handled = False
            mod._opened_files.clear()


def test_window_close_behavior_exits_when_last_window_really_closes():
    # If a window truly closes (confirmed dirty close / app quit), we still run
    # pywebview's standard cleanup and stop the runloop so the process exits.
    source = (ROOT / 'markdown_viewer.py').read_text(encoding='utf-8')
    assert 'def patch_window_close_behavior' in source
    assert source.count('patch_window_close_behavior()') >= 1
    block = source[source.index('def patch_window_close_behavior'):source.index('def main')]
    assert 'app.stop_(self)' in block
    assert 'objc.selector(' in block
    assert "b'windowWillClose:'" in block
    assert 'instancesRespondToSelector_' in block
    assert 'BrowserView.instances == {}' in block
    assert 'setDelegate_(None)' in block
    # No dead anchor window is kept in webview.windows.
    assert 'webview.windows[:] = [i.pywebview_window]' not in block


def test_create_window_safely_runs_creation_off_main_thread():
    # pywebview only instantiates the native window when create_window is
    # called from a non-'MainThread' Python thread; cocoa then builds a
    # non-master window via AppHelper.callAfter on the AppKit main thread.
    source = (ROOT / 'markdown_viewer.py').read_text(encoding='utf-8')
    block = source[source.index('def _create_window_safely'):source.index('def update_main_window')]
    assert "threading.current_thread().name == 'MainThread'" in block
    assert 'threading.Thread(' in block
    assert 'create_window(file_path, x, y)' in block


def test_window_close_override_mechanism_works():
    try:
        import objc
        from AppKit import NSObject
    except Exception:
        return  # pyobjc unavailable in this environment

    class _FakeWinDelegate(NSObject):
        def windowWillClose_(self, notification):
            pass

    def _replacement(self, notification):
        pass

    _FakeWinDelegate.windowWillClose_ = objc.selector(
        _replacement, selector=b'windowWillClose:', signature=b'v@:@')
    assert _FakeWinDelegate.instancesRespondToSelector_(b'windowWillClose:')
    _FakeWinDelegate.alloc().init().windowWillClose_(None)


def test_menu_and_alert_strings_are_bilingual():
    # Menus, update alerts and buttons must be wrapped in _t() so the UI is
    # bilingual. Regression guard for the i18n audit.
    source = (ROOT / 'markdown_viewer.py').read_text(encoding='utf-8')
    checks = [
        '_t("Preferences…", "偏好设置…")',
        '_t("Open File…", "打开文件…")',
        '_t("Save As…", "另存为…")',
        '_t("Find Previous", "查找上一个")',
        '_t("You\'re up to date!", "已是最新版本！")',
        '_t(\'Download\', \'下载\')',
        '有可用更新',
        '检查更新',
    ]
    for c in checks:
        assert c in source, 'missing bilingual string: %s' % c


def test_view_menu_zoom_and_width_shortcuts():
    # View menu: Zoom In ⌘= / Zoom Out ⌘-; width moved to ⌘. / ⌘,;
    # Preferences (⌘,) must not clash with width anymore.
    source = (ROOT / 'markdown_viewer.py').read_text(encoding='utf-8')
    assert '"zoomIn:", "="' in source
    assert '"zoomOut:", "-"' in source
    assert '"increaseWidth:", "."' in source
    assert '"decreaseWidth:", ","' in source
    assert 'def zoomIn_(self, sender)' in source
    assert 'def zoomOut_(self, sender)' in source
    assert "_dispatch_js('zoomIn()')" in source
    assert "_dispatch_js('zoomOut()')" in source
    assert 'showPreferences:", ","' in source
    assert '# Cmd+Shift+,' in source  # Preferences moved to ⌘⇧, to avoid clash


def test_default_handler_registration_has_lsregister_fallback():
    source = (ROOT / 'markdown_viewer.py').read_text(encoding='utf-8')
    block = source[source.index('def set_as_default_for_md'):source.index('def get_app_info')]
    assert 'from LaunchServices import' in block
    assert 'from CoreServices import' in block
    assert 'lsregister' in block
    assert "'-f', app_path" in block


if __name__ == '__main__':
    test_safe_save_encoding_and_draft()
    test_encoding_detection_survives_corrupt_utf16_bom()
    test_close_window_last_clean_hides_instead_of_destroying()
    test_save_detects_external_modification_conflict()
    test_force_save_overwrites_conflict_and_updates_baseline()
    test_conflict_check_uses_mtime_size_fast_path_without_full_read()
    test_conflict_check_falls_back_to_content_when_stat_changes()
    test_save_as_new_path_bypasses_original_conflict()
    test_save_as_same_conflicted_path_is_blocked()
    test_deleted_file_save_recreates_without_false_conflict()
    test_external_encoding_change_is_detected_as_conflict()
    test_save_as_missing_parent_directory_succeeds_and_updates_baseline()
    test_draft_recovery_sets_dirty_and_preserves_disk_baseline()
    test_open_existing_file_focuses_instead_of_duplicate_window()
    test_open_file_does_not_reuse_dirty_untitled_window()
    test_open_file_reuses_clean_untitled_window()
    test_version_compare()
    test_quit_watchdog_force_exit_when_no_windows()
    test_quit_watchdog_ignores_secondary_window_close()
    test_on_window_closing_prompts_dirty_doc_before_close()
    test_force_close_discard_removes_dirty_draft()
    test_force_close_last_window_hides_instead_of_destroying()
    test_subscribe_js_ready_marks_window_on_loaded()
    test_save_prompt_delete_action_closes_panel()
    test_concurrent_add_recent_file_no_loss()
    test_smoke_test_app_rejects_bad_path()
    test_auto_install_without_staging_fails_safely()
    test_update_main_window_resident_ready_immediate()
    test_update_main_window_waits_for_js_ready()
    test_on_window_closing_allows_confirmed_dirty_doc()
    test_on_window_closing_writes_draft_without_requesting_app_quit()
    test_app_lifecycle_methods_are_registered_in_delegate_patch()
    test_delegate_patch_uses_selector_install_not_classaddmethod()
    test_delegate_install_mechanism_overrides_existing_selector()
    test_last_clean_window_hides_instead_of_closing()
    test_reopen_hidden_window_shows_hidden_blank_window()
    test_handle_opened_file_reuses_hidden_blank_window()
    test_window_close_behavior_exits_when_last_window_really_closes()
    test_window_close_override_mechanism_works()
    test_create_window_safely_runs_creation_off_main_thread()
    test_menu_and_alert_strings_are_bilingual()
    test_view_menu_zoom_and_width_shortcuts()
    test_default_handler_registration_has_lsregister_fallback()
    print('Python smoke tests passed')
