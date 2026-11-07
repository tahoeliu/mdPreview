"""只用替身验证剪贴板，不访问系统剪贴板或临时目录。"""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mdpreview_core.clipboard import set_rich


class RichClipboardTests(unittest.TestCase):
    def fixture(self, main=True):
        appkit = MagicMock()
        foundation = MagicMock()
        helper = MagicMock()
        foundation.NSThread.isMainThread.return_value = main
        helper.callAfter.side_effect = lambda callback: callback()
        attr = MagicMock()
        attr.length.return_value = 2
        appkit.NSAttributedString.alloc.return_value.initWithHTML_documentAttributes_.return_value = (attr, None)
        pb = appkit.NSPasteboard.generalPasteboard.return_value
        pb.pasteboardItems.return_value = []
        pb.writeObjects_.return_value = True
        modules = {'AppKit': appkit, 'Foundation': foundation,
                   'PyObjCTools': SimpleNamespace(AppHelper=helper)}
        return modules, appkit, foundation, helper, pb

    def test_background_dispatch_and_no_images_in_rtf(self):
        modules, appkit, foundation, helper, pb = self.fixture(main=False)
        with patch.dict(sys.modules, modules):
            self.assertTrue(set_rich('<p>正文<img src="data:image/png;base64,YQ=="></p>', '正文')['success'])
        helper.callAfter.assert_called_once()
        data = foundation.NSData.dataWithBytes_length_.call_args.args[0]
        self.assertNotIn(b'<img', data)
        pb.clearContents.assert_called_once()

    def test_conversion_failure_keeps_clipboard(self):
        modules, appkit, _, _, pb = self.fixture()
        appkit.NSAttributedString.alloc.return_value.initWithHTML_documentAttributes_.return_value = (None, None)
        with patch.dict(sys.modules, modules):
            self.assertFalse(set_rich('<p>正文</p>', '正文')['success'])
        pb.clearContents.assert_not_called()

    def test_write_exception_restores_previous(self):
        modules, _, _, _, pb = self.fixture()
        old = MagicMock()
        old.types.return_value = ['text']
        old.dataForType_.return_value = b'old'
        pb.pasteboardItems.return_value = [old]
        pb.writeObjects_.side_effect = [RuntimeError('写入失败'), True]
        with patch.dict(sys.modules, modules):
            self.assertFalse(set_rich('<p>正文</p>', '正文')['success'])
        self.assertEqual(pb.writeObjects_.call_count, 2)

    def test_dispatch_failure_returns_without_waiting(self):
        modules, _, _, helper, pb = self.fixture(main=False)
        helper.callAfter.side_effect = RuntimeError('调度失败')
        with patch.dict(sys.modules, modules):
            self.assertFalse(set_rich('<p>正文</p>', '正文')['success'])
        pb.clearContents.assert_not_called()


if __name__ == '__main__':
    unittest.main()
