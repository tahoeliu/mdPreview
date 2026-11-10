#!/usr/bin/env python3
"""Quitting must never wait on a window nobody can see.

A window that does not answer the quit question must not block quitting forever:
  - a clean window that stays silent is simply skipped;
  - a window with unsaved work that stays silent cancels the quit and is brought to the front;
  - after either, quitting works again (no stuck state).
Also: every window that exists is moved onto a screen if it was stranded off-screen.
"""
import os
import sys
import threading
import time
import unittest
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import mdPreview as mv  # noqa: E402


class FakeApi:
    def __init__(self, name, dirty=False):
        self.name, self.is_dirty, self.window, self.document_id = name, dirty, object(), name


class QuitFlowTests(unittest.TestCase):
    def setUp(self):
        self.asked, self.focused = [], []
        self.saved = (dict(mv._window_apis), mv._QUIT_ACK_SECONDS)
        mv._QUIT_ACK_SECONDS = 0.15
        mv._window_apis.clear()
        mv._quit_confirmation_queue.clear()
        mv._quit_confirmation_active = False
        mv._QUIT_APPROVED.clear()
        self.terminated = threading.Event()
        self.silent = set()          # windows that never answer
        def dispatch(window, js):
            if js == 'confirmQuitDocument()':
                api = next((a for a in mv._window_apis.values() if a.window is window), None)
                self.asked.append(api.name)
                if api.name not in self.silent:
                    threading.Thread(target=lambda: (time.sleep(0.01), mv._finish_quit_confirmation(api, True)), daemon=True).start()
        self.patches = [
            mock.patch.object(mv, '_dispatch_js_to', side_effect=dispatch),
            mock.patch.object(mv, '_ensure_windows_visible', return_value=0),
            mock.patch.object(mv, '_focus_window', side_effect=lambda w: self.focused.append(w) or True),
            mock.patch.object(mv, 'AppHelper', mock.MagicMock(callAfter=lambda fn, *a, **k: fn(*a, **k))),
            mock.patch.object(mv, 'NSApplication', mock.MagicMock(sharedApplication=lambda: mock.MagicMock(terminate_=lambda _: self.terminated.set()))),
        ]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in self.patches: p.stop()
        mv._cancel_quit_ack()
        mv._window_apis.clear(); mv._window_apis.update(self.saved[0]); mv._QUIT_ACK_SECONDS = self.saved[1]
        mv._quit_confirmation_queue.clear(); mv._quit_confirmation_active = False; mv._QUIT_APPROVED.clear()

    def add(self, name, dirty=False):
        api = FakeApi(name, dirty); mv._window_apis[name] = api; return api

    def test_all_windows_answer_then_quit_proceeds(self):
        self.add('a'); self.add('b', dirty=True)
        mv._begin_quit_confirmation()
        self.assertTrue(self.terminated.wait(2))
        self.assertEqual(self.asked[0], 'b')                       # the one with unsaved work is asked first
        self.assertIn(mv._window_apis['b'].window, self.focused)    # and is brought to the front

    def test_a_silent_clean_window_is_skipped(self):
        self.add('ghost'); self.add('b')
        self.silent.add('ghost')
        mv._begin_quit_confirmation()
        self.assertTrue(self.terminated.wait(2), 'quit must not hang on a window that never answers')

    def test_a_silent_window_with_unsaved_work_cancels_the_quit_and_is_shown(self):
        ghost = self.add('ghost', dirty=True)
        self.silent.add('ghost')
        mv._begin_quit_confirmation()
        time.sleep(0.6)
        self.assertFalse(self.terminated.is_set(), 'unsaved work must never be thrown away silently')
        self.assertIn(ghost.window, self.focused)                   # the person can see the window
        self.assertFalse(mv._quit_confirmation_active, 'the quit attempt is over, so quitting can be tried again')

    def test_quitting_works_again_after_a_cancelled_attempt(self):
        ghost = self.add('ghost', dirty=True)
        self.silent.add('ghost')
        mv._begin_quit_confirmation(); time.sleep(0.6)
        self.silent.clear()
        mv._begin_quit_confirmation()
        self.assertTrue(self.terminated.wait(2))

    def test_an_answered_prompt_stops_the_silence_timer(self):
        api = self.add('slow', dirty=True)
        self.silent.add('slow')
        mv._begin_quit_confirmation()
        # the window says it is now asking the person: waiting for the person must not time out
        mv.MarkdownAPI.quit_prompt_started(api, api.document_id)
        time.sleep(0.5)
        self.assertTrue(mv._quit_confirmation_active)
        self.assertFalse(self.terminated.is_set())
        mv._finish_quit_confirmation(api, False)                  # the person pressed Cancel
        self.assertFalse(mv._quit_confirmation_active)


@unittest.skipUnless(sys.platform == 'darwin', 'needs macOS')
class StrandedWindowTests(unittest.TestCase):
    def test_off_screen_windows_are_moved_onto_the_screen_and_visible_ones_are_left_alone(self):
        from AppKit import NSApplication, NSWindow, NSMakeRect, NSScreen, NSBackingStoreBuffered
        NSApplication.sharedApplication()
        rects = [[r.origin.x, r.origin.y, r.size.width, r.size.height] for r in (s.visibleFrame() for s in NSScreen.screens())]
        main = NSScreen.mainScreen().visibleFrame()
        def make(x, y):
            w = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(NSMakeRect(x, y, 900, 600), 15, NSBackingStoreBuffered, False)
            w.orderFront_(None); w.setFrameOrigin_((x, y)); return w
        ok, lost1, lost2 = make(main.origin.x + 100, main.origin.y + 100), make(9000, -9000), make(-9000, 9000)
        before = ok.frame().origin.x
        moved = mv._move_stranded_windows([ok, lost1, lost2], rects, main)
        self.assertEqual(moved, 2)
        self.assertEqual(ok.frame().origin.x, before)
        def seen(w):
            f = w.frame()
            return any(min(f.origin.x + f.size.width, r[0] + r[2]) - max(f.origin.x, r[0]) >= 100 and min(f.origin.y + f.size.height, r[1] + r[3]) - max(f.origin.y, r[1]) >= 100 for r in rects)
        self.assertTrue(seen(lost1) and seen(lost2))
        self.assertNotEqual((lost1.frame().origin.x, lost1.frame().origin.y), (lost2.frame().origin.x, lost2.frame().origin.y))


if __name__ == '__main__':
    unittest.main()
