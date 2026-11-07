"""T02：安全日志、资源门禁和原生完成信号。"""
import ast
import json
import logging
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mdPreview as mv


class BridgeTests(unittest.TestCase):
    def test_log_privacy_and_budget(self):
        api = mv.MarkdownAPI()
        payload = json.dumps({'type': 'TypeError', 'message': 'SECRET正文', 'frames': [
            {'file': 'app.js', 'line': 12, 'column': 34, 'function': 'SECRET'},
            {'file': '/Users/SECRET/app.js', 'line': 1, 'column': 2},
            {'file': 'app.js', 'line': 'SECRET', 'column': 2},
        ]})
        with self.assertLogs(level=logging.ERROR) as captured:
            self.assertTrue(api.log_js_error('bridge', 'save_file', payload))
            api.log_js_error('SECRET\n伪造日志', 'SECRET', 'Error: SECRET\n at SECRET (/Users/SECRET/app.js:1:2)')
            api.log_js_error('window', 'SECRET', {'stack': 'SECRET'})
            api.log_js_error(None, [], None)
            api.log_js_error('window', 'error', 'SECRET' * 100000)
            api.log_js_error('promise', 'unhandled', json.dumps({'type': 'SECRET', 'frames': [{'file': 'app.js', 'line': 1, 'column': 1}] * 2000}))
        text = '\n'.join(captured.output)
        self.assertNotIn('SECRET', text)
        self.assertNotIn('正文', text)
        self.assertNotIn('/Users/', text)
        self.assertIn('TypeError', text)
        self.assertIn('app.js', text)
        self.assertIn('save_file', text)
        for record in captured.records:
            self.assertLessEqual(len(record.getMessage().encode('utf-8')), 4096)
            self.assertNotIn('\n', record.getMessage())
        with mock.patch.object(mv.logging, 'error', side_effect=OSError('SECRET')):
            self.assertFalse(api.log_js_error('window', 'error', payload))

    def test_native_completion_waits(self):
        tree = ast.parse((ROOT / 'mdPreview.py').read_text())
        targets = {'_run_format_panel', 'export_as_write', 'open_file_dialog', 'native_save_prompt', 'native_conflict_prompt'}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in targets:
                source = ast.get_source_segment((ROOT / 'mdPreview.py').read_text(), node)
                self.assertNotIn('range(150)', source, node.name)
                self.assertIn('completed.wait(600)' if node.name == 'export_as_write' else 'completed.wait()', source, node.name)
                self.assertIn('completed.finish(' if node.name == 'export_as_write' else 'completed.set()', source, node.name)
                targets.remove(node.name)
        self.assertFalse(targets)

    def test_delayed_native_save_waits_for_second_panel(self):
        from test_save_prompt import SavePromptStateMachineTests
        harness = SavePromptStateMachineTests()
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        queue = []
        harness.PyObjCTools.AppHelper.callAfter.side_effect = lambda fn: queue.append(fn)
        panel = harness.AppKit.NSSavePanel.savePanel.return_value
        panel.runModal.return_value = 1
        panel.URL.return_value.path.return_value = '/tmp/t02.md'
        alert = harness.AppKit.NSAlert.alloc.return_value.init.return_value
        alert.beginSheetModalForWindow_completionHandler_.side_effect = lambda host, cb: queue.append(lambda: cb(1002))
        completed = mock.Mock()
        signalled = []
        completed.set.side_effect = lambda: signalled.append(True)

        def wait(timeout=None):
            self.assertIsNone(timeout, '用户面板不能使用固定超时')
            self.assertFalse(signalled)
            queue.pop(0)()
            self.assertFalse(signalled, '显示提示不是完成')
            queue.pop(0)()
            self.assertFalse(signalled, '未命名文档还需等待另存面板')
            queue.pop(0)()
            self.assertTrue(signalled)

        completed.wait.side_effect = wait
        with mock.patch.object(mv.threading, 'Event', return_value=completed):
            result = mv.MarkdownAPI().native_save_prompt()
        self.assertEqual(result, {'action': 'save', 'path': '/tmp/t02.md'})

    def test_pdf_callback_and_setup_failures_signal_completion(self):
        from test_save_prompt import SavePromptStateMachineTests
        harness = SavePromptStateMachineTests()
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        import webview.platforms.cocoa as cocoa
        view = mock.Mock()
        cocoa.BrowserView.instances.get.return_value = mock.Mock(webview=view)
        queue = []
        harness.PyObjCTools.AppHelper.callAfter.side_effect = lambda fn: queue.append(fn)
        for outcome in ('success', 'empty', 'callback-error', 'setup-error', 'no-webview'):
            with self.subTest(outcome=outcome):
                completed = mock.Mock()
                signalled = []
                completed.set.side_effect = lambda: signalled.append(True)
                cocoa.BrowserView.instances.get.return_value = None if outcome == 'no-webview' else mock.Mock(webview=view)
                def capture(config, callback):
                    if outcome == 'setup-error':
                        raise RuntimeError('测试错误')
                    queue.append(lambda: callback(b'pdf' if outcome == 'success' else b'', '错误' if outcome == 'callback-error' else None))
                view.createPDFWithConfiguration_completionHandler_.side_effect = capture
                def wait(timeout=None):
                    self.assertEqual(timeout,600)
                    self.assertFalse(signalled)
                    queue.pop(0)()
                    if queue:
                        self.assertFalse(signalled, '异步PDF未回调前不能完成')
                        queue.pop(0)()
                    self.assertTrue(signalled)
                completed.wait.side_effect = wait
                with mock.patch.object(mv.threading, 'Event', return_value=completed), mock.patch.dict(sys.modules, {'WebKit': mock.Mock()}), mock.patch.object(mv, '_pdf_to_a4_longpage',return_value=1), mock.patch('mdpreview_core.export.pdf_post.finalize'), mock.patch.object(mv, '_remember_save_directory'):
                    result = mv.MarkdownAPI().export_as_write('/tmp/t02.pdf', 'pdf',page={'options':{'pdf_layout':'continuous'}})
                self.assertEqual(result['success'], outcome == 'success')

    def test_release_resources(self):
        tree = ast.parse((ROOT / 'scripts/check_release.py').read_text())
        for name in ['check_source', 'check_app']:
            node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
            self.assertIn('frontend/bridge.js', ast.get_source_segment((ROOT / 'scripts/check_release.py').read_text(), node))
        spec = (ROOT / 'mdPreview.spec').read_text()
        self.assertIn("('frontend', 'frontend')", spec)


if __name__ == '__main__':
    unittest.main()
