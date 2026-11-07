"""watcher、reading_state、csp_bridge 的单元测试（不依赖真实窗口）。"""
import math
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mdpreview_core import csp_bridge, reading_state  # noqa: E402
from mdpreview_core.watcher import Watcher  # noqa: E402


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, 'a.md')
        Path(self.path).write_text('one', encoding='utf-8')
        self.w = Watcher()
        self.w.stop.set()  # 测试里手动 poll，不让线程干扰
        self.addCleanup(lambda: None)

    def test_stamp_missing_file_is_none(self):
        self.assertIsNone(Watcher.stamp(os.path.join(self.dir.name, 'nope')))
        self.assertIsNotNone(Watcher.stamp(self.path))

    def test_change_triggers_callback_once(self):
        seen = []
        self.w.entries['k'] = (self.path, Watcher.stamp(self.path), lambda p, s: seen.append((p, s)))
        self.w.poll()
        self.assertEqual(seen, [])
        Path(self.path).write_text('two!', encoding='utf-8')
        self.w.poll()
        self.w.poll()
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], self.path)

    def test_deletion_reports_none_stamp(self):
        seen = []
        self.w.entries['k'] = (self.path, Watcher.stamp(self.path), lambda p, s: seen.append(s))
        os.remove(self.path)
        self.w.poll()
        self.assertEqual(seen, [None])

    def test_failing_callback_does_not_stop_others(self):
        other = os.path.join(self.dir.name, 'b.md')
        Path(other).write_text('x', encoding='utf-8')
        seen = []

        def boom(path, stamp):
            raise RuntimeError('boom')
        self.w.entries['a'] = (self.path, Watcher.stamp(self.path), boom)
        self.w.entries['b'] = (other, Watcher.stamp(other), lambda p, s: seen.append(p))
        Path(self.path).write_text('changed', encoding='utf-8')
        Path(other).write_text('changed too', encoding='utf-8')
        self.w.poll()
        self.assertEqual(seen, [other])

    def test_removed_entry_is_not_called(self):
        seen = []
        self.w.entries['k'] = (self.path, Watcher.stamp(self.path), lambda p, s: seen.append(1))
        Path(self.path).write_text('changed', encoding='utf-8')
        self.w.remove('k')
        self.w.poll()
        self.assertEqual(seen, [])

    def test_entry_replaced_during_poll_is_skipped(self):
        seen = []
        entry = (self.path, Watcher.stamp(self.path), lambda p, s: seen.append('old'))
        self.w.entries['k'] = entry
        Path(self.path).write_text('changed', encoding='utf-8')
        original = self.w.stamp

        def swap(path):
            self.w.entries['k'] = (self.path, (0, 0), lambda p, s: seen.append('new'))
            return original(path)
        with mock.patch.object(Watcher, 'stamp', staticmethod(swap)):
            self.w.poll()
        self.assertEqual(seen, [])

    def test_watch_starts_single_daemon_thread_that_detects_change(self):
        w = Watcher()
        done = threading.Event()
        w.watch('k', self.path, lambda p, s: done.set())
        first = w.thread
        w.watch('k2', self.path, lambda p, s: None)
        self.assertIs(w.thread, first)
        self.assertTrue(first.daemon)
        time.sleep(0.05)
        Path(self.path).write_text('changed by someone', encoding='utf-8')
        self.assertTrue(done.wait(5))
        w.stop.set()
        first.join(3)


class ReadingStateTests(unittest.TestCase):
    def test_key_is_hash_not_path(self):
        key = reading_state.position_key('/tmp/some secret/doc.md')
        self.assertEqual(len(key), 64)
        self.assertNotIn('secret', key)

    def test_validation(self):
        for bad in (None, 'x', [], {'ratio': -0.1}, {'ratio': 1.1}, {'ratio': math.nan},
                    {'ratio': math.inf}, {'ratio': '0.5'}, {'ratio': True and 'a'}, {'ratio': 0.5, 'headingId': 5},
                    {'ratio': 0.5, 'headingId': 'x' * 513}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    reading_state.remember({}, '/tmp/a.md', bad)

    def test_remember_and_replace(self):
        values = reading_state.remember({}, '/tmp/a.md', {'ratio': 0.25, 'headingId': 'intro'})
        key = reading_state.position_key('/tmp/a.md')
        self.assertEqual(values[key]['ratio'], 0.25)
        again = reading_state.remember(values, '/tmp/a.md', {'ratio': 1})
        self.assertEqual(len(again), 1)
        self.assertEqual(again[key]['ratio'], 1)

    def test_lru_keeps_newest_300(self):
        values = {}
        with mock.patch('time.time', side_effect=[float(i) for i in range(400)]):
            for i in range(350):
                values = reading_state.remember(values, f'/tmp/doc{i}.md', {'ratio': 0})
        self.assertEqual(len(values), 300)
        self.assertNotIn(reading_state.position_key('/tmp/doc0.md'), values)
        self.assertIn(reading_state.position_key('/tmp/doc349.md'), values)

    def test_invalid_stored_entries_are_dropped(self):
        good = reading_state.position_key('/tmp/g.md')
        stored = {good: {'updatedAt': 1}, 'short': {'updatedAt': 1}, 'Z' * 64: {'updatedAt': 1},
                  'a' * 64: 'not a dict', 'b' * 64: {'updatedAt': 'x'}}
        result = reading_state.remember(stored, '/tmp/new.md', {'ratio': 0.5})
        self.assertEqual(set(result), {good, reading_state.position_key('/tmp/new.md')})
        self.assertEqual(reading_state.remember('garbage', '/tmp/a.md', {'ratio': 0})
                         [reading_state.position_key('/tmp/a.md')]['ratio'], 0)

    def test_visible_frame(self):
        screens = [(0, 0, 1440, 900)]
        self.assertTrue(reading_state.visible_frame([100, 100, 900, 680], screens))
        self.assertFalse(reading_state.visible_frame([5000, 100, 900, 680], screens))
        self.assertFalse(reading_state.visible_frame([100, 100, 300, 680], screens))
        self.assertFalse(reading_state.visible_frame([100, 100, 900, 200], screens))
        self.assertFalse(reading_state.visible_frame([1, 2, 3], screens))
        self.assertFalse(reading_state.visible_frame('x', screens))
        self.assertFalse(reading_state.visible_frame([100, 100, 900, math.nan], screens))
        self.assertFalse(reading_state.visible_frame([100, 100, 900, '680'], screens))


class FakeWindow:
    def __init__(self, fail=False):
        self.uid = 'uid'
        self._callbacks = {}
        self.scripts = []
        self.fail = fail
        self.gui = types.SimpleNamespace(evaluate_js=self.evaluate)

    def evaluate(self, script, uid, flag):
        self.scripts.append(script)
        if self.fail:
            raise RuntimeError('native down')
        return 'native-result'


class CspBridgeTests(unittest.TestCase):
    def test_run_body_sync_wraps_body_in_function(self):
        window = FakeWindow()
        self.assertEqual(csp_bridge.run_body(window, 'return 1;'), 'native-result')
        self.assertTrue(window.scripts[0].startswith('(function(){'))
        self.assertIn('return 1;', window.scripts[0])

    def test_run_expression_returns_explicitly(self):
        window = FakeWindow()
        csp_bridge.run_expression(window, 'document.title')
        self.assertIn('return (\ndocument.title\n);', window.scripts[0])

    def test_async_callback_settles_once(self):
        window = FakeWindow()
        results = []
        identity = csp_bridge.run_body(window, 'return 1;', results.append)
        self.assertIn(identity, window._callbacks)
        self.assertIn('pywebview._runBody(', window.scripts[0])
        window._callbacks[identity]({'success': True})
        self.assertEqual(results, [{'success': True}])
        self.assertNotIn(identity, window._callbacks)

    def test_native_failure_reports_error_once(self):
        window = FakeWindow(fail=True)
        results = []
        identity = csp_bridge.run_body(window, 'return 1;', results.append)
        self.assertEqual(results, [{'success': False, 'error': 'native-javascript-failed'}])
        self.assertNotIn(identity, window._callbacks)

    def test_timeout_settles_with_error(self):
        window = FakeWindow()
        results = []
        with mock.patch('threading.Timer') as timer:
            identity = csp_bridge.run_body(window, 'return 1;', results.append)
            fire = timer.call_args.args[1]
        fire()
        fire()  # 第二次必须被忽略
        self.assertEqual(results, [{'success': False, 'error': 'javascript-timeout'}])
        self.assertNotIn(identity, window._callbacks)


class InstallTests(unittest.TestCase):
    TEMPLATE = ('header\n  _createApi: function (funcList) { new Function("x"); },\n'
                '  _jsApiCallback: function (funcName, params, id) {},\ntail')

    def _fake_modules(self, template):
        util = types.ModuleType('webview.util')
        util.load_js_files = lambda window, platform: (template, 'finish')

        class Window:
            pass
        window_mod = types.ModuleType('webview.window')
        window_mod.Window = Window
        cocoa = types.ModuleType('webview.platforms.cocoa')
        cocoa.calls = []
        cocoa.js_bridge_call = lambda window, name, params, identity: cocoa.calls.append(name)
        platforms = types.ModuleType('webview.platforms')
        platforms.cocoa = cocoa
        package = types.ModuleType('webview')
        package.util, package.window, package.platforms = util, window_mod, platforms
        modules = {'webview': package, 'webview.util': util, 'webview.window': window_mod,
                   'webview.platforms': platforms, 'webview.platforms.cocoa': cocoa}
        return modules, util, Window, cocoa

    def test_install_patches_template_and_bridge(self):
        modules, util, Window, cocoa = self._fake_modules(self.TEMPLATE)
        with mock.patch.dict(sys.modules, modules):
            csp_bridge.install(lambda name: str(ROOT / name))
            self.assertTrue(Window._mdpreview_csp)
            code, finish = util.load_js_files(None, None)
            self.assertNotIn('new Function(', code)
            self.assertIn('_createApi: null', code)
            self.assertEqual(finish, 'finish')
            # 幂等：再次安装不重复包装。
            wrapped = util.load_js_files
            csp_bridge.install(lambda name: str(ROOT / name))
            self.assertIs(util.load_js_files, wrapped)
            # 异步回调：解析 JSON、坏 JSON、未知回调、其他调用转交原函数。
            got = []
            window = types.SimpleNamespace(_callbacks={'a': got.append, 'b': got.append})
            cocoa.js_bridge_call(window, 'pywebviewAsyncCallback', '{"x": 1}', 'a')
            cocoa.js_bridge_call(window, 'pywebviewAsyncCallback', '{bad', 'b')
            cocoa.js_bridge_call(window, 'pywebviewAsyncCallback', None, 'missing')
            self.assertEqual(got, [{'x': 1}, {'success': False, 'error': 'invalid-javascript-result'}])
            cocoa.js_bridge_call(window, 'other', 'p', 'id')
            self.assertEqual(cocoa.calls, ['other'])

    def test_unsupported_template_refuses_instead_of_falling_back(self):
        modules, util, Window, cocoa = self._fake_modules('no template here')
        with mock.patch.dict(sys.modules, modules):
            csp_bridge.install(lambda name: str(ROOT / name))
            with self.assertRaisesRegex(RuntimeError, 'unsupported-pywebview-api-template'):
                util.load_js_files(None, None)

    def test_evaluate_requires_ready_bridge_and_rejects_callbacks(self):
        modules, util, Window, cocoa = self._fake_modules(self.TEMPLATE)
        with mock.patch.dict(sys.modules, modules):
            csp_bridge.install(lambda name: str(ROOT / name))
            ready = threading.Event()
            window = FakeWindow()
            window.events = types.SimpleNamespace(_pywebviewready=ready)
            with mock.patch.object(ready, 'wait', return_value=False):
                with self.assertRaisesRegex(RuntimeError, 'bridge-not-ready'):
                    Window.evaluate_js(window, '1')
            with mock.patch.object(ready, 'wait', return_value=True):
                self.assertEqual(Window.evaluate_js(window, '1'), 'native-result')
                with self.assertRaises(TypeError):
                    Window.evaluate_js(window, '1', lambda r: None)


if __name__ == '__main__':
    unittest.main(verbosity=2)
