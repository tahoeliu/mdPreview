import sys
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

class PrintTests(unittest.TestCase):
    def test_completion_is_once_and_late_success_is_ignored(self):
        from mdpreview_core.export.print_engine import Completion
        for error in ('cancelled', 'closed', 'timeout', 'native-error'):
            state = Completion()
            self.assertTrue(state.finish(False, error))
            self.assertFalse(state.finish(True))
            self.assertEqual(state.wait(0), {'success': False, 'error': error, 'cancelled': error in ('cancelled', 'closed')})
        state = Completion()
        self.assertIsNone(state.wait(0))
        self.assertTrue(state.finish(True))
        self.assertEqual(state.wait(0), {'success': True})

    @unittest.skipUnless(sys.platform == 'darwin', '需要 macOS')
    def test_paper_margins(self):
        from mdpreview_core.export.print_engine import make_print_info
        info = make_print_info('a4', 'normal')
        self.assertAlmostEqual(info.paperSize().width, 595.28, delta=0.5)
        self.assertAlmostEqual(info.leftMargin(), 22*72/25.4)
        self.assertAlmostEqual(info.topMargin(), 22*72/25.4)
        with self.assertRaises(ValueError): make_print_info('bad', 'normal')

    @unittest.skipUnless(sys.platform == 'darwin', '需要 macOS')
    def test_native_delegate_success_cancel_failure(self):
        from unittest.mock import MagicMock, patch
        from mdpreview_core.export import print_engine as engine
        web = MagicMock()
        for success in (True, False):
            done = []
            delegate = engine.run(web, MagicMock(), MagicMock(), False, done.append)
            delegate.printOperationDidRun_success_contextInfo_(None, success, None)
            delegate.printOperationDidRun_success_contextInfo_(None, not success, None)
            self.assertEqual(done, [success])
            self.assertNotIn(id(delegate), engine._active)
        web.printOperationWithPrintInfo_.return_value.runOperationModalForWindow_delegate_didRunSelector_contextInfo_.side_effect = RuntimeError('failed')
        with self.assertRaises(RuntimeError): engine.run(web, None, None, False, lambda _: None)
        web.respondsToSelector_.return_value = False
        delegate = engine.run(web, MagicMock(), MagicMock(), True, lambda _: None)
        delegate.printOperationDidRun_success_contextInfo_(None, False, None)
        self.assertIn(engine.default_paper(), ('a4', 'letter'))
        info = engine.make_print_info('auto', 'wide', ROOT/'WorkSpace/outputs/test.pdf')
        self.assertGreater(info.leftMargin(), 60)

    def test_close_after_native_success_prevents_commit(self):
        from mdpreview_core.export.print_engine import Completion
        state=Completion(); state.finish(True); state.close()
        with self.assertRaises(RuntimeError):
            with state.commit_guard(): self.fail('关闭后不得进入提交')
        state=Completion()
        with state.commit_guard(): pass
        state.close()
        with self.assertRaises(RuntimeError):
            with state.commit_guard(): pass

    def test_integration(self):
        js = (ROOT/'frontend/output.js').read_text()
        app_js = (ROOT/'app.js').read_text()
        py = (ROOT/'mdPreview.py').read_text()
        self.assertIn("Bridge.call('print_document'", js)
        self.assertNotIn('window.print()', app_js)
        self.assertNotIn('window.print()', js)
        self.assertIn('def print_document(self', py)

if __name__ == '__main__': unittest.main(verbosity=2)
