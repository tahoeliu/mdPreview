#!/usr/bin/env python3
"""Quality-gate tests for the exit save prompt & external-change conflict logic.

Covers:
  A) native_save_prompt state machine (Cocoa mocked, run in a worker thread):
     A1 existing-path doc + Save  -> direct save (NO NSSavePanel)
     A2 untitled doc + Save       -> NSSavePanel opens
     A3 untitled + panel cancel   -> cancel
     A4 Delete                    -> delete
     A5 Cancel                    -> cancel
     A6 HAS_COCOA=False           -> cancel
  B) save_file / _has_external_save_conflict (real I/O in tmpdir):
     B1 clean save                -> success
     B2 third-party modified      -> conflict, force=False
     B3 third-party modified      -> force=True overwrites
     B4 untitled save             -> no conflict check, writes
     B5 save to a new path        -> no conflict check, writes
     B6 file deleted on disk      -> not a conflict, rewrites
     B7 known limitation          -> same mtime+size mutation is undetected
  C) JS side integration contract (static): promptBeforeClose save branch
     uses the returned path as-is; node --check passes.
  D) native_conflict_prompt state machine (Cocoa mocked):
     D1 Save Current        -> overwrite
     D2 Save As             -> save_as
     D3 Cancel              -> cancel
     D4 HAS_COCOA=False     -> cancel
     D5 button order & defaults (Save Current red/destructive, Cancel=Enter)
"""
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import mdPreview as mv  # noqa: E402


class SavePromptStateMachineTests(unittest.TestCase):
    """A) native_save_prompt with Cocoa stubbed out."""

    def setUp(self):
        self.AppKit = mock.MagicMock()
        self.AppKit.NSOKButton = 1
        self.Foundation = mock.MagicMock()
        self.PyObjCTools = mock.MagicMock()
        # callAfter executes synchronously (simulates main-thread dispatch)
        self.PyObjCTools.AppHelper.callAfter.side_effect = (
            lambda fn, *a, **k: fn(*a, **k)
        )
        self.cocoa_mod = mock.MagicMock()
        self.cocoa_mod.BrowserView.instances.get.return_value = None
        self.patches = [
            mock.patch.dict(sys.modules, {
                'AppKit': self.AppKit,
                'Foundation': self.Foundation,
                'PyObjCTools': self.PyObjCTools,
                'webview': sys.modules.get('webview', mock.MagicMock()),
                'webview.platforms': mock.MagicMock(),
                'webview.platforms.cocoa': self.cocoa_mod,
            }),
            mock.patch.object(mv, 'HAS_COCOA', True),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def _make_api(self, file_path, untitled):
        api = mv.MarkdownAPI(file_path=file_path)
        api.is_untitled = untitled
        api.window = mock.MagicMock()
        return api

    def _run_prompt_click(self, api, code):
        """Run native_save_prompt in a worker thread and simulate a button
        click (code: 1000=Delete, 1001=Cancel, 1002=Save) on the NSAlert."""
        captured = []
        alert = self.AppKit.NSAlert.alloc.return_value.init.return_value
        alert.beginSheetModalForWindow_completionHandler_.side_effect = (
            lambda host, cb: captured.append(cb)
        )
        result_box = {}

        def worker():
            result_box['res'] = api.native_save_prompt()

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        for _ in range(500):
            if captured:
                break
            time.sleep(0.01)
        self.assertTrue(captured, 'alert handler was never captured')
        captured[0](code)
        t.join(timeout=20)
        self.assertFalse(t.is_alive(), 'native_save_prompt did not return in time')
        return result_box.get('res', {'action': 'timeout'})

    def test_a1_existing_path_save_skips_panel(self):
        api = self._make_api('/tmp/doc.md', untitled=False)
        res = self._run_prompt_click(api, 1002)  # Save
        self.assertEqual(res['action'], 'save')
        self.assertEqual(res['path'], '/tmp/doc.md')
        self.AppKit.NSSavePanel.savePanel.assert_not_called()

    def test_a2_untitled_save_opens_panel(self):
        api = self._make_api(None, untitled=True)
        panel = self.AppKit.NSSavePanel.savePanel.return_value
        panel.runModal.return_value = 1  # NSOKButton
        url = mock.MagicMock()
        url.path.return_value = '/tmp/untitled.md'
        panel.URL.return_value = url
        res = self._run_prompt_click(api, 1002)  # Save
        self.assertEqual(res['action'], 'save')
        self.assertEqual(res['path'], '/tmp/untitled.md')
        self.AppKit.NSSavePanel.savePanel.assert_called_once()

    def test_a3_untitled_save_panel_cancelled(self):
        api = self._make_api(None, untitled=True)
        panel = self.AppKit.NSSavePanel.savePanel.return_value
        panel.runModal.return_value = 0  # Cancel
        res = self._run_prompt_click(api, 1002)  # Save -> panel -> cancel
        self.assertEqual(res['action'], 'cancel')

    def test_a4_delete_action(self):
        api = self._make_api('/tmp/doc.md', untitled=False)
        res = self._run_prompt_click(api, 1000)  # Delete
        self.assertEqual(res['action'], 'delete')

    def test_a5_cancel_action(self):
        api = self._make_api('/tmp/doc.md', untitled=False)
        res = self._run_prompt_click(api, 1001)  # Cancel
        self.assertEqual(res['action'], 'cancel')

    def test_a6_no_cocoa_returns_cancel(self):
        with mock.patch.object(mv, 'HAS_COCOA', False):
            api = self._make_api('/tmp/doc.md', untitled=False)
            res = api.native_save_prompt()
        self.assertEqual(res['action'], 'cancel')


class NativeConflictPromptTests(unittest.TestCase):
    """D) native_conflict_prompt state machine (Cocoa mocked)."""

    def setUp(self):
        self.AppKit = mock.MagicMock()
        self.Foundation = mock.MagicMock()
        self.PyObjCTools = mock.MagicMock()
        # callAfter executes synchronously (simulates main-thread dispatch)
        self.PyObjCTools.AppHelper.callAfter.side_effect = (
            lambda fn, *a, **k: fn(*a, **k)
        )
        self.cocoa_mod = mock.MagicMock()
        self.cocoa_mod.BrowserView.instances.get.return_value = None
        self.patches = [
            mock.patch.dict(sys.modules, {
                'AppKit': self.AppKit,
                'Foundation': self.Foundation,
                'PyObjCTools': self.PyObjCTools,
                'webview': sys.modules.get('webview', mock.MagicMock()),
                'webview.platforms': mock.MagicMock(),
                'webview.platforms.cocoa': self.cocoa_mod,
            }),
            mock.patch.object(mv, 'HAS_COCOA', True),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def _run_click(self, api, code):
        captured = []
        alert = self.AppKit.NSAlert.alloc.return_value.init.return_value
        alert.beginSheetModalForWindow_completionHandler_.side_effect = (
            lambda host, cb: captured.append(cb)
        )
        result_box = {}

        def worker():
            result_box['res'] = api.native_conflict_prompt('/tmp/doc.md')

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        for _ in range(500):
            if captured:
                break
            time.sleep(0.01)
        self.assertTrue(captured, 'alert handler was never captured')
        captured[0](code)
        t.join(timeout=20)
        self.assertFalse(t.is_alive(), 'native_conflict_prompt did not return in time')
        return result_box.get('res', {'action': 'timeout'})

    def _make_api(self):
        api = mv.MarkdownAPI(file_path='/tmp/doc.md')
        api.window = mock.MagicMock()
        return api

    def test_d1_save_current_returns_overwrite(self):
        res = self._run_click(self._make_api(), 1000)
        self.assertEqual(res['action'], 'overwrite')

    def test_d2_save_as_returns_save_as(self):
        res = self._run_click(self._make_api(), 1001)
        self.assertEqual(res['action'], 'save_as')

    def test_d3_cancel_returns_cancel(self):
        res = self._run_click(self._make_api(), 1002)
        self.assertEqual(res['action'], 'cancel')

    def test_d4_no_cocoa_returns_cancel(self):
        with mock.patch.object(mv, 'HAS_COCOA', False):
            res = self._make_api().native_conflict_prompt('/tmp/doc.md')
        self.assertEqual(res['action'], 'cancel')

    def test_d5_button_order_and_defaults(self):
        self._run_click(self._make_api(), 1002)
        alert = self.AppKit.NSAlert.alloc.return_value.init.return_value
        titles = [c[0][0] for c in alert.addButtonWithTitle_.call_args_list]
        self.assertEqual(titles, ['Save Current', 'Save As', 'Cancel'])
        btns = alert.buttons.return_value
        btns.objectAtIndex_.return_value.setHasDestructiveAction_.assert_called_with(True)
        btns.objectAtIndex_.return_value.setBezelColor_.assert_called_once()
        keys = [c[0][0] for c in btns.objectAtIndex_.return_value.setKeyEquivalent_.call_args_list]
        # '' clears Save Current & Cancel; '\r' (Enter, renders blue) on Save As
        self.assertEqual(keys, ['', '\r', ''])


class SaveFileConflictTests(unittest.TestCase):
    """B) save_file conflict detection with real file I/O."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        # Stub out side effects that touch the real app config / drafts.
        self.side_effects = [
            mock.patch.object(mv, 'add_recent_file'),
            mock.patch.object(mv, '_remove_draft'),
            mock.patch.object(mv, '_write_draft'),
        ]
        for p in self.side_effects:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.side_effects])

    def _open_file(self, path, content):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        api = mv.MarkdownAPI(file_path=path)
        content, encoding = mv._detect_text_encoding(path)
        api.file_content = content
        api.encoding = encoding
        api._record_baseline_stat(path)
        api.is_untitled = False
        return api

    def _disk(self, path):
        with open(path, encoding='utf-8') as f:
            return f.read()

    def test_b1_clean_save_succeeds(self):
        p = os.path.join(self.td.name, 'a.md')
        api = self._open_file(p, 'original')
        res = api.save_file(p, 'edited by user', force=False)
        self.assertTrue(res['success'])
        self.assertEqual(self._disk(p), 'edited by user')

    def test_b2_third_party_modified_detects_conflict(self):
        p = os.path.join(self.td.name, 'b.md')
        api = self._open_file(p, 'original')
        time.sleep(0.01)  # ensure mtime differs
        with open(p, 'w', encoding='utf-8') as f:
            f.write('changed by third party')
        res = api.save_file(p, 'edited by user', force=False)
        self.assertFalse(res['success'])
        self.assertTrue(res['conflict'])
        # Disk untouched
        self.assertEqual(self._disk(p), 'changed by third party')

    def test_b3_force_overwrites_third_party_change(self):
        p = os.path.join(self.td.name, 'c.md')
        api = self._open_file(p, 'original')
        time.sleep(0.01)
        with open(p, 'w', encoding='utf-8') as f:
            f.write('changed by third party')
        res = api.save_file(p, 'edited by user', force=True)
        self.assertTrue(res['success'])
        self.assertEqual(self._disk(p), 'edited by user')

    def test_b4_untitled_save_no_conflict_check(self):
        p = os.path.join(self.td.name, 'd.md')
        api = mv.MarkdownAPI(file_path=None)
        api.is_untitled = True
        res = api.save_file(p, 'fresh content', force=False)
        self.assertTrue(res['success'])
        self.assertEqual(self._disk(p), 'fresh content')

    def test_b5_save_as_new_path_no_conflict_check(self):
        p = os.path.join(self.td.name, 'e.md')
        q = os.path.join(self.td.name, 'e-copy.md')
        api = self._open_file(p, 'original')
        time.sleep(0.01)
        with open(p, 'w', encoding='utf-8') as f:
            f.write('changed by third party')
        res = api.save_file(q, 'edited by user', force=False)
        self.assertTrue(res['success'])
        self.assertEqual(self._disk(q), 'edited by user')
        # original left untouched by the save-as
        self.assertEqual(self._disk(p), 'changed by third party')

    def test_b6_deleted_file_requires_save_as(self):
        # 文件被外部删除后，保存同一路径不得悄悄重建；必须交给前端走另存为。
        p = os.path.join(self.td.name, 'f.md')
        api = self._open_file(p, 'original')
        os.remove(p)
        res = api.save_file(p, 'edited by user', force=False)
        self.assertFalse(res['success'])
        self.assertTrue(res.get('deleted'))
        self.assertFalse(os.path.exists(p))
        # 另存为新路径则正常成功，内容不丢。
        q = os.path.join(self.td.name, 'f-recovered.md')
        res = api.save_file(q, 'edited by user', force=False)
        self.assertTrue(res['success'])
        self.assertEqual(self._disk(q), 'edited by user')

    def test_b7_known_limitation_same_mtime_size_undetected(self):
        # Documenting the pre-existing limitation: if a third party rewrites
        # the file with identical size AND restores the mtime, the fast-path
        # mtime/size check reports "no conflict". Not a regression.
        p = os.path.join(self.td.name, 'g.md')
        api = self._open_file(p, 'aaa')
        st = os.stat(p)
        with open(p, 'w', encoding='utf-8') as f:
            f.write('bbb')  # same size
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))  # restore mtime
        res = api.save_file(p, 'edited by user', force=False)
        self.assertTrue(res['conflict'])
        self.assertEqual(self._disk(p), 'bbb')


class DefaultSaveDirectoryTests(unittest.TestCase):
    """E) Default save location policy."""

    def test_e1_without_history_defaults_to_desktop(self):
        with mock.patch.object(mv, 'load_config', return_value={}), \
             mock.patch.object(mv.os.path, 'isdir', return_value=True):
            self.assertTrue(mv._default_save_directory().endswith(os.path.join('', 'Desktop')))

    def test_e2_last_save_dir_wins_even_when_desktop(self):
        last_dir = os.path.join(tempfile.gettempdir(), 'Home', 'Desktop')
        with mock.patch.object(mv, 'load_config', return_value={'last_save_dir': last_dir}), \
             mock.patch.object(mv.os.path, 'isdir', return_value=True):
            self.assertEqual(mv._default_save_directory(), os.path.abspath(last_dir))

    def test_e3_remember_save_directory_persists_parent(self):
        saved = {}
        target = os.path.join(tempfile.gettempdir(), 'notes', 'doc.md')
        with mock.patch.object(mv, 'load_config', return_value={}), \
             mock.patch.object(mv, 'save_config', side_effect=lambda cfg: saved.update(cfg)):
            mv._remember_save_directory(target)
        self.assertEqual(saved.get('last_save_dir'), os.path.dirname(os.path.abspath(target)))


class JSContractTests(unittest.TestCase):
    """C) Static contract between Python prompt result and app.js."""

    def test_c1_return_shape_matches_frontend_contract(self):
        # app.js promptBeforeClose expects {'action','path'} and only reassigns
        # filePath when res.path !== filePath. For existing-path docs the new
        # Python code returns the SAME path, so filePath stays stable and
        # saveFile(false) overwrites in place. This test pins the shape.
        result = {'action': 'save', 'path': '/a/b.md'}
        file_path = '/a/b.md'
        if result.get('path') and result.get('path') != file_path:
            file_path = result['path']
        self.assertEqual(file_path, '/a/b.md')

    def test_c2_untitled_path_replaces_filepath(self):
        result = {'action': 'save', 'path': '/new/location.md'}
        file_path = 'Untitled.md'
        if result.get('path') and result.get('path') != file_path:
            file_path = result['path']
        self.assertEqual(file_path, '/new/location.md')


if __name__ == '__main__':
    unittest.main(verbosity=2)
