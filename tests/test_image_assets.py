"""图片写入验证只用替身，不创建或清理真实文件。"""
import base64
import unittest
from unittest.mock import patch, mock_open
from mdpreview_core.images import save_asset


class ImageAssetTests(unittest.TestCase):
    def test_unsaved(self):
        self.assertTrue(save_asset(None, '', 'png')['need_save'])

    def test_reject_mismatched_signature(self):
        with patch('pathlib.Path.is_file', return_value=True):
            with self.assertRaises(ValueError):
                save_asset('/document.md', base64.b64encode(b'not-image').decode(), 'png')

    def test_collision_does_not_overwrite(self):
        payload = base64.b64encode(b'\x89PNG\r\n\x1a\ncontent').decode()
        with patch('pathlib.Path.is_file', return_value=True), patch('pathlib.Path.mkdir'), patch('pathlib.Path.is_symlink', return_value=False), patch('mdpreview_core.images.tempfile.mkstemp', return_value=(7, '/assets/.temporary')), patch('mdpreview_core.images.os.fdopen', mock_open()), patch('mdpreview_core.images.os.fsync'), patch('mdpreview_core.images.os.unlink') as unlink, patch('mdpreview_core.images.os.link', side_effect=[FileExistsError(), None]) as link:
            result = save_asset('/document.md', payload, 'png')
        self.assertTrue(result['success'])
        self.assertTrue(result['path'].endswith('-1.png'))
        self.assertEqual(link.call_count, 2)
        unlink.assert_called_once_with('/assets/.temporary')


if __name__ == '__main__': unittest.main()
