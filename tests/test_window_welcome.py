import os
import tempfile
import unittest
from unittest import mock

import mdPreview as app


class WelcomeWindowTests(unittest.TestCase):
    def test_open_prefers_originating_clean_blank_window(self):
        with tempfile.NamedTemporaryFile(suffix='.md') as file:
            api = app.MarkdownAPI(None)
            window = mock.Mock()
            with mock.patch.object(app, '_initial_file_handled', True), \
                 mock.patch.object(app, '_opened_files', set()), \
                 mock.patch.object(app, 'update_main_window') as reuse, \
                 mock.patch.object(app, '_create_window_safely') as create:
                app.handle_opened_file(file.name, window, api, prefer_blank=True)
                reuse.assert_called_once_with(window, api, os.path.abspath(file.name))
                create.assert_not_called()

    def test_dirty_blank_is_not_replaced(self):
        with tempfile.NamedTemporaryFile(suffix='.md') as file:
            api = app.MarkdownAPI(None)
            api.is_dirty = True
            with mock.patch.object(app, '_initial_file_handled', True), \
                 mock.patch.object(app, '_opened_files', set()), \
                 mock.patch.object(app, '_reuse_hidden_window_for_file', return_value=False), \
                 mock.patch.object(app, '_create_window_safely') as create:
                app.handle_opened_file(file.name, mock.Mock(), api, prefer_blank=True)
                create.assert_called_once()

    def test_untitled_window_title_and_saved_title(self):
        api = app.MarkdownAPI(None)
        api.window = mock.Mock()
        with mock.patch.object(app, '_set_represented_file'):
            api.set_dirty(True)
            api.window.set_title.assert_called_with('mdPreview')
            api.file_path = '/tmp/example.md'
            api.set_dirty(False)
            api.window.set_title.assert_called_with('example.md')


if __name__ == '__main__':
    unittest.main()
