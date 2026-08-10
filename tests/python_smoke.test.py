#!/usr/bin/env python3
import importlib.util
import sys
import tempfile
import types
from pathlib import Path

sys.modules['webview'] = types.SimpleNamespace()
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('markdown_viewer', ROOT / 'markdown_viewer.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_safe_save_encoding_backup_and_draft():
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
        assert Path(str(target) + '.bak').exists()
        assert not list(Path(mod.DRAFT_DIR).glob('*.md'))
        mod.DRAFT_DIR = old_draft


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


def test_on_window_closing_arms_watchdog_and_writes_draft():
    """on_window_closing must set the quit flag and persist a draft for dirty docs."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        old_draft = mod.DRAFT_DIR
        mod.DRAFT_DIR = str(Path(d) / 'Drafts')
        api = mod.MarkdownAPI(None)
        api.is_dirty = True
        api.cached_content = 'unsaved content'
        fake_win = type('W', (), {'uid': 'x'})()
        api.window = fake_win
        mod._window_apis[id(fake_win)] = api
        mod._QUIT_REQUESTED.clear()
        assert mod.on_window_closing(fake_win) is True
        assert mod._QUIT_REQUESTED.is_set()
        drafts = list(Path(mod.DRAFT_DIR).glob('*.md'))
        assert drafts, 'draft should be written on close'
        assert 'unsaved content' in drafts[0].read_text('utf-8')
        mod._window_apis.clear()
        mod.DRAFT_DIR = old_draft


if __name__ == '__main__':
    test_safe_save_encoding_backup_and_draft()
    test_version_compare()
    test_quit_watchdog_force_exit_when_no_windows()
    test_quit_watchdog_ignores_secondary_window_close()
    test_on_window_closing_arms_watchdog_and_writes_draft()
    print('Python smoke tests passed')
