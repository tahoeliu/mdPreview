"""无头导出编排：用假 webview 驱动，验证参数校验、成功/失败/超时与输出保护。"""
import io
import os
import sys
import tempfile
import threading
import types
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mdpreview_core import headless  # noqa: E402


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class FakeWindow:
    def __init__(self):
        self.events = types.SimpleNamespace(loaded=FakeEvent(), shown=FakeEvent(), closed=FakeEvent())
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


class FakeAPI:
    def __init__(self):
        self.document_id = 'doc-1'
        self.window = None
        self.written = []

    def get_export_css(self):
        return {'css': ''}

    def get_math_export_css(self, families):
        return {'css': ''}

    def read_image_for_export(self, *args):
        return {'success': False}

    def export_as_write(self, path, fmt, content='', page=None):
        self.written.append((path, fmt))
        Path(path).write_text('exported', encoding='utf-8')
        return {'success': True, 'path': path}


class Harness:
    """安装假 webview；scenario(js_api, window) 在 webview.start 内同步运行。"""

    def __init__(self, scenario):
        self.scenario = scenario
        self.window = FakeWindow()
        self.js_api = None
        self.url = None

    def __enter__(self):
        module = types.ModuleType('webview')

        def create_window(title, url=None, js_api=None, **options):
            self.js_api, self.url = js_api, url
            self.options = options
            return self.window

        module.create_window = create_window
        module.start = lambda debug=False: self.scenario(self.js_api, self.window)
        self.patch = mock.patch.dict(sys.modules, {'webview': module})
        self.patch.start()
        return self

    def __exit__(self, *exc):
        self.patch.stop()


class HeadlessTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.dir.name = os.path.realpath(self.dir.name)  # /var 是符号链接，测试内统一用真实路径
        self.source = Path(self.dir.name) / 'in.md'
        self.source.write_text('# hi\n', encoding='utf-8')
        self.target = Path(self.dir.name) / 'out.txt'

    def run_headless(self, args, scenario=None, api=None):
        resource = lambda name: str(ROOT / name)  # noqa: E731
        err = io.StringIO()
        with redirect_stderr(err):
            if scenario is None:
                return headless.run(args, FakeAPI, resource), err.getvalue(), None
            with Harness(scenario) as harness:
                code = headless.run(args, api or FakeAPI, resource)
        return code, err.getvalue(), harness

    def test_argument_validation(self):
        bad_cases = [
            [],
            [str(self.source), str(self.target)],
            [str(self.source), str(self.target), 'exe'],
            [str(self.dir.name + '/missing.md'), str(self.target), 'txt'],
            [str(self.source), str(Path(self.dir.name) / 'nodir' / 'x.txt'), 'txt'],
        ]
        for args in bad_cases:
            with self.subTest(args=args):
                code, err, _ = self.run_headless(args)
                self.assertEqual(code, 1)
                self.assertIn('headless:', err)

    def test_existing_output_is_refused(self):
        self.target.write_text('keep me', encoding='utf-8')
        code, err, _ = self.run_headless([str(self.source), str(self.target), 'txt'])
        self.assertEqual(code, 1)
        self.assertEqual(self.target.read_text(encoding='utf-8'), 'keep me')

    def test_non_utf8_input_is_rejected(self):
        self.source.write_bytes(b'\xff\xfe\x00bad')
        code, err, _ = self.run_headless([str(self.source), str(self.target), 'txt'])
        self.assertEqual(code, 1)
        self.assertIn('UTF-8', err)

    def test_successful_export_flow(self):
        def scenario(js_api, window):
            data = js_api.get_initial_content()
            self.assertTrue(data['headless'])
            self.assertEqual(data['outputPath'], str(self.target))
            self.assertEqual(data['settings']['remote_images'], 'never')
            self.assertEqual(data['settings']['auto_update'], False)
            self.assertEqual(js_api.export_as_write(str(self.target), 'txt', 'x')['success'], True)
            js_api.headless_finish(True)
        code, err, harness = self.run_headless([str(self.source), str(self.target), 'txt'], scenario)
        self.assertEqual(code, 0, err)
        self.assertTrue(harness.window.destroyed)
        self.assertTrue(harness.options['hidden'])
        self.assertTrue(harness.url.endswith('index.html?headless=1'))
        self.assertTrue(self.target.is_file())

    def test_frontend_reports_failure(self):
        def scenario(js_api, window):
            js_api.get_initial_content()
            js_api.headless_finish(False)
        code, err, _ = self.run_headless([str(self.source), str(self.target), 'txt'], scenario)
        self.assertEqual(code, 2)
        self.assertIn('render or export failed', err)

    def test_success_claim_without_output_is_failure(self):
        # 前端声称成功，但从未真正写出文件：不能返回 0。
        def scenario(js_api, window):
            js_api.headless_finish(True)
        code, _, _ = self.run_headless([str(self.source), str(self.target), 'txt'], scenario)
        self.assertEqual(code, 2)

    def test_output_path_and_format_are_pinned(self):
        other = Path(self.dir.name) / 'elsewhere.txt'

        def scenario(js_api, window):
            self.assertEqual(js_api.export_as_write(str(other), 'txt', '')['error'], 'headless-output-refused')
            self.assertEqual(js_api.export_as_write(str(self.target), 'pdf', '')['error'], 'headless-output-refused')
            self.assertTrue(js_api.export_as_write(str(self.target), 'txt', '')['success'])
            # 只允许写一次。
            self.target.unlink()
            self.assertEqual(js_api.export_as_write(str(self.target), 'txt', '')['error'], 'headless-output-refused')
            js_api.headless_finish(False)
        self.run_headless([str(self.source), str(self.target), 'txt'], scenario)
        self.assertFalse(other.exists())

    def test_bridge_surface_is_minimal(self):
        captured = {}

        def scenario(js_api, window):
            captured['names'] = {n for n in dir(js_api) if not n.startswith('_')}
            js_api.headless_finish(False)
        self.run_headless([str(self.source), str(self.target), 'txt'], scenario)
        for forbidden in ('open_file_dialog', 'save_file', 'open_external_link', 'perform_auto_install',
                          'download_update_with_progress', 'set_as_default_for_md'):
            self.assertNotIn(forbidden, captured['names'])

    def test_watchdog_timeout_returns_2(self):
        def scenario(js_api, window):
            threading.Event().wait(3)  # 不调用 headless_finish
        with mock.patch.dict(os.environ, {'MDPREVIEW_HEADLESS_TIMEOUT': '5'}), \
                mock.patch.object(threading.Event, 'wait', autospec=True) as wait:
            # 让第一次 done.wait(timeout) 立即视为超时。
            wait.side_effect = lambda self_, timeout=None: False if timeout == 5 else None
            code, err, _ = self.run_headless([str(self.source), str(self.target), 'txt'], scenario)
        self.assertEqual(code, 2)

    def test_output_directory_symlink_is_resolved(self):
        # macOS 的 /tmp、/var 都是符号链接：通过链接目录导出必须成功。
        real = Path(self.dir.name) / 'real'
        real.mkdir()
        link = Path(self.dir.name) / 'link'
        link.symlink_to(real)
        wanted = link / 'out.txt'

        def scenario(js_api, window):
            data = js_api.get_initial_content()
            self.assertEqual(Path(data['outputPath']).parent, real.resolve())
            self.assertTrue(js_api.export_as_write(data['outputPath'], 'txt', '')['success'])
            js_api.headless_finish(True)
        code, err, _ = self.run_headless([str(self.source), str(wanted), 'txt'], scenario)
        self.assertEqual(code, 0, err)
        self.assertTrue((real / 'out.txt').is_file())

    def test_final_component_symlink_is_not_followed(self):
        victim = Path(self.dir.name) / 'victim.txt'
        victim.write_text('precious', encoding='utf-8')
        link = Path(self.dir.name) / 'out-link.txt'
        link.symlink_to(victim)
        code, _, _ = self.run_headless([str(self.source), str(link), 'txt'])
        self.assertEqual(code, 1)
        self.assertEqual(victim.read_text(encoding='utf-8'), 'precious')

    def test_trace_is_silent_unless_enabled(self):
        def scenario(js_api, window):
            js_api.get_initial_content()
            js_api.headless_trace('stage')
            js_api.headless_finish(False)
        _, err, _ = self.run_headless([str(self.source), str(self.target), 'txt'], scenario)
        self.assertNotIn('headless-trace', err)
        with mock.patch.dict(os.environ, {'MDPREVIEW_HEADLESS_TRACE': '1'}):
            _, err, _ = self.run_headless([str(self.source), str(Path(self.dir.name) / 'o2.txt'), 'txt'], scenario)
        self.assertIn('headless-trace: stage', err)


if __name__ == '__main__':
    unittest.main(verbosity=2)
