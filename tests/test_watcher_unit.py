"""不创建磁盘文件；监听状态和回调的纯替身测试。"""
import unittest
from unittest.mock import Mock
from mdpreview_core.watcher import Watcher
from mdpreview_core.reading_state import visible_frame

class WatcherTests(unittest.TestCase):
    def test_changed_deleted_removed(self):
        watcher = Watcher()
        callback = Mock()
        watcher.entries['doc'] = ('document.md', (1, 10), callback)
        watcher.stamp = lambda path: (2, 20)
        watcher.poll()
        callback.assert_called_once_with('document.md', (2, 20))
        watcher.poll()
        self.assertEqual(callback.call_count, 1)
        watcher.stamp = lambda path: None
        watcher.poll()
        self.assertEqual(callback.call_count, 2)
        watcher.remove('doc')
        watcher.poll()
        self.assertEqual(callback.call_count, 2)

    def test_screen_bounds(self):
        self.assertTrue(visible_frame([20, 20, 900, 680], [[0, 0, 1440, 900]]))
        self.assertFalse(visible_frame([20000, 20, 900, 680], [[0, 0, 1440, 900]]))

if __name__ == '__main__': unittest.main()
