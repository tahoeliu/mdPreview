#!/usr/bin/env python3
"""Quality-gate tests for the save/export format panel accessory view.

Covers:
  A) _format_disclaimer: md/txt/html -> no warning; docx/png/pdf -> warning
  B) _measure_label_width: returns positive width derived from Cocoa metrics
  C) _layout_format_acc: popup starts at the measured label column width;
     label is right-aligned and shorter than the popup column; accessory
     shrinks (50pt) when no disclaimer and grows (68pt) when one is needed.
  D) formatChanged_: switching formats re-lays-out the accessory view
     (grow/shrink + show/hide disclaimer).
  E) end-to-end save_as_choose / export_as_choose: initial format md/html
     produce a compact accessory view; panel is configured with the
     format popup.
"""
import os
import sys
import threading
import types
import unittest
from unittest import mock

# Import mdPreview with a fake Cocoa environment so the HAS_COCOA block
# (including _format_disclaimer / _layout_format_acc / _run_format_panel /
# ViewMenuHandler) actually gets defined and importable without pyobjc.


class _NSObject:
    """Dummy stand-in for AppKit.NSObject: real base class so subclasses
    (e.g. ViewMenuHandler) can be defined at import time, with alloc/init
    that return a live instance."""

    def __init__(self, *a, **k):
        pass

    @classmethod
    def alloc(cls, *a, **k):
        return object.__new__(cls)

    def init(self, *a, **k):
        return self


class _SuperProxy:
    """objc.super(...).init() stand-in that returns the real instance."""

    def __init__(self, cls, instance):
        self._instance = instance

    def init(self, *a, **k):
        return self._instance


_AppKit = mock.MagicMock()
_AppKit.NSObject = _NSObject
_AppKit.NSMakeRect = lambda x, y, w, h: (x, y, w, h)
_Foundation = mock.MagicMock()
_Foundation.NSObject = _NSObject  # ViewMenuHandler subclasses Foundation.NSObject
_PyObjCTools = mock.MagicMock()
_objc = types.ModuleType('objc')
_objc.super = _SuperProxy
_objc.selector = lambda f, **k: f
sys.modules.setdefault('AppKit', _AppKit)
sys.modules.setdefault('Foundation', _Foundation)
sys.modules.setdefault('PyObjCTools', _PyObjCTools)
sys.modules.setdefault('objc', _objc)
sys.modules.setdefault('webview', mock.MagicMock())

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import mdPreview as mv  # noqa: E402

assert mv.HAS_COCOA, 'test requires HAS_COCOA=True at import time'


def _fake_nsmakerect(x, y, w, h):
    return (x, y, w, h)


class FormatDisclaimerTests(unittest.TestCase):
    """A) which formats carry the experimental warning."""

    def test_plain_text_formats_have_no_warning(self):
        for ext in ('md', 'txt', 'html'):
            self.assertEqual(mv._format_disclaimer(ext), '', ext)

    def test_binary_formats_have_warning(self):
        for ext in ('docx', 'png', 'pdf'):
            self.assertNotEqual(mv._format_disclaimer(ext), '', ext)


class MeasureLabelWidthTests(unittest.TestCase):
    """B) _measure_label_width returns a positive, plausible width.

    Under the mocked Cocoa in this test the measurement is degenerate
    (mock NSTextField doesn't actually size). On real Cocoa this returns
    a real value around 60-90pt for "Where:". We just guard the function
    contract here (positive, not NaN, finite, has a sane upper bound).
    """

    def test_returns_positive_width(self):
        w = mv._measure_label_width()
        self.assertIsInstance(w, float)
        self.assertGreater(w, 0.0, 'width must be positive')
        self.assertLess(w, 500.0, 'width must be in a sane range')

    def test_returns_finite_value(self):
        import math
        w = mv._measure_label_width()
        self.assertFalse(math.isnan(w), 'width must not be NaN')
        self.assertTrue(math.isfinite(w), 'width must be finite')


class FormatAccLayoutTests(unittest.TestCase):
    """C) accessory-view geometry (one row: label left of popup)."""

    def setUp(self):
        self.acc = mock.MagicMock()
        self.acc.frame.return_value.size.width = 360.0
        self.label = mock.MagicMock()
        self.popup = mock.MagicMock()
        self.disclaimer = mock.MagicMock()
        self.label_w = 80.0  # the value _measure_label_width would return

    def _layout(self, ext):
        mv._layout_format_acc(
            self.acc, self.label, self.popup, self.disclaimer, ext, self.label_w,
        )

    def test_pdf_layout_shows_disclaimer_and_grows(self):
        self._layout('pdf')
        h = self.acc.setFrame_.call_args[0][0][3]
        self.assertEqual(h, 82.0, 'acc height should be 82 when disclaimer is shown (v1.4.2)')
        # popup left edge aligns with measured label column width
        px, py, pw, _ = self.popup.setFrame_.call_args[0][0]
        self.assertEqual(px, self.label_w)
        self.assertEqual(py, 38.0)
        # popup width fills remainder of acc width
        self.assertEqual(pw, 360.0 - self.label_w - 20.0)
        # label is right-aligned, fits inside label_w
        lx, ly, lw, _ = self.label.setFrame_.call_args[0][0]
        self.assertEqual(lx, 0.0, 'label must start at x=0')
        self.assertLessEqual(lx + lw, px, 'label must not overlap popup')
        # disclaimer shown below
        self.disclaimer.setHidden_.assert_called_once_with(False)

    def test_txt_layout_hides_disclaimer_and_shrinks(self):
        self._layout('txt')
        h = self.acc.setFrame_.call_args[0][0][3]
        self.assertEqual(h, 64.0, 'acc height should be 64 when no disclaimer (v1.4.0)')
        self.disclaimer.setHidden_.assert_called_once_with(True)
        px, py, _, _ = self.popup.setFrame_.call_args[0][0]
        self.assertEqual(px, self.label_w)
        self.assertEqual(py, 18.0)

    def test_md_and_html_match_txt(self):
        for ext in ('md', 'html'):
            self._layout(ext)
            h = self.acc.setFrame_.call_args[0][0][3]
            self.assertEqual(h, 64.0, ext)
            self.disclaimer.setHidden_.assert_called_once_with(True)
            self.disclaimer.reset_mock()


class FormatChangedLayoutTests(unittest.TestCase):
    """D) switching the popup re-lays-out the accessory view."""

    def setUp(self):
        self.acc = mock.MagicMock()
        self.acc.frame.return_value.size.width = 360.0
        self.label = mock.MagicMock()
        self.popup = mock.MagicMock()
        self.disclaimer = mock.MagicMock()
        self.panel = mock.MagicMock()
        self.label_w = 80.0
        self.formats = [
            ('Web Page (.html)', 'html'),
            ('Word Document (.docx)', 'docx'),
            ('PNG Image (.png)', 'png'),
            ('PDF', 'pdf'),
            ('Plain Text (.txt)', 'txt'),
        ]
        self.holder = {
            'formats': self.formats,
            'panel': self.panel,
            'acc': self.acc,
            'label': self.label,
            'popup': self.popup,
            'disclaimer': self.disclaimer,
            'label_w': self.label_w,
        }
        self.actions = mv._FormatPopupActions.alloc().initWithHolder_(self.holder)
        self.sender = mock.MagicMock()

    def _select(self, idx):
        self.sender.indexOfSelectedItem.return_value = idx
        self.actions.formatChanged_(self.sender)

    def test_switch_to_txt_shrinks_and_hides(self):
        self._select(1)  # docx (has disclaimer)
        h = self.acc.setFrame_.call_args[0][0][3]
        self.assertEqual(h, 82.0, 'docx should grow the view (v1.4.2)')
        self.disclaimer.setHidden_.assert_called_once_with(False)
        self.disclaimer.reset_mock()
        self._select(4)  # txt (no disclaimer)
        h = self.acc.setFrame_.call_args[0][0][3]
        self.assertEqual(h, 64.0, 'txt should shrink the view (v1.4.0)')
        self.disclaimer.setHidden_.assert_called_once_with(True)
        # popup keeps its place in the measured label column
        self.assertEqual(self.popup.setFrame_.call_args[0][0][0], self.label_w)

    def test_switch_back_to_pdf_grows_and_shows(self):
        self._select(3)  # pdf
        h = self.acc.setFrame_.call_args[0][0][3]
        self.assertEqual(h, 82.0)
        self.disclaimer.setHidden_.assert_called_once_with(False)

    def test_allowed_file_type_tracks_selection(self):
        self._select(2)  # png
        self.panel.setAllowedFileTypes_.assert_called_with(['png'])


class FormatPanelEndToEndTests(unittest.TestCase):
    """E) save_as_choose / export_as_choose produce a compact accessory view."""

    def setUp(self):
        self.AppKit = mock.MagicMock()
        self.AppKit.NSOKButton = 1
        self.AppKit.NSMakeRect = _fake_nsmakerect
        self.Foundation = mock.MagicMock()
        self.PyObjCTools = mock.MagicMock()
        # callAfter executes synchronously (simulates main-thread dispatch)
        self.PyObjCTools.AppHelper.callAfter.side_effect = (
            lambda fn, *a, **k: fn(*a, **k)
        )
        self.patches = [
            mock.patch.dict(sys.modules, {
                'AppKit': self.AppKit,
                'Foundation': self.Foundation,
                'PyObjCTools': self.PyObjCTools,
                # 'objc' intentionally NOT patched: _FormatPopupActions uses
                # objc.super(...).init() and needs the real _SuperProxy to
                # keep working during the modal flow.
                'webview': sys.modules.get('webview', mock.MagicMock()),
                'webview.platforms': mock.MagicMock(),
                'webview.platforms.cocoa': mock.MagicMock(),
            }),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

        # Fake Cocoa objects
        self.panel = self.AppKit.NSSavePanel.savePanel.return_value
        self.panel.runModal.return_value = 1  # NSOKButton
        url = mock.MagicMock()
        url.path.return_value = '/tmp/output.md'
        self.panel.URL.return_value = url
        self.popup = self.AppKit.NSPopUpButton.alloc.return_value.initWithFrame_.return_value
        self.popup.indexOfSelectedItem.return_value = 0
        self.acc = self.AppKit.NSView.alloc.return_value.initWithFrame_.return_value
        self.acc.frame.return_value.size.width = 360.0
        self.acc.setFrame_.side_effect = lambda rect: setattr(self.acc.frame.return_value.size, 'height', rect[3])
        for name, value in [('get_output_settings', __import__('mdpreview_core.export.settings',fromlist=['defaults']).defaults()), ('set_output_settings', {'success':True})]:
            patcher = mock.patch.object(mv.MarkdownAPI,name,return_value=value)
            patcher.start(); self.addCleanup(patcher.stop)

    def _run_choose(self, fn_name):
        api = mv.MarkdownAPI(file_path='/tmp/source.md')
        result = {}
        t = threading.Thread(
            target=lambda: result.update(res=getattr(api, fn_name)('Doc.md')),
            daemon=True,
        )
        t.start()
        t.join(timeout=20)
        self.assertFalse(t.is_alive(), '%s did not return in time' % fn_name)
        return result.get('res', {'error': 'timeout'})

    def test_save_as_initial_md_is_compact(self):
        res = self._run_choose('save_as_choose')
        self.assertTrue(res.get('success'), res)
        self.assertEqual(res['format'], 'md')
        # Initial format is md -> no disclaimer -> compact 64pt view (v1.4.0)
        h = self.acc.setFrame_.call_args[0][0][3]
        self.assertEqual(h, 64.0, 'Save As defaults to md and must be compact')
        self.panel.setAccessoryView_.assert_called_once()
        self.assertEqual(self.panel.setAllowedFileTypes_.call_args[0][0], ['md'])

    def test_export_as_initial_html_is_compact(self):
        res = self._run_choose('export_as_choose')
        self.assertTrue(res.get('success'), res)
        self.assertEqual(res['format'], 'html')
        h = self.acc.setFrame_.call_args[0][0][3]
        self.assertEqual(h, 92.0, 'HTML增加一行元数据设置')
        self.assertEqual(self.panel.setAllowedFileTypes_.call_args[0][0], ['html'])

    def test_pdf_first_format_grows(self):
        # Directly drive _run_format_panel with pdf as the first format.
        holder = {}
        t = threading.Thread(
            target=lambda: mv._run_format_panel(
                holder, 'Doc', [('PDF', 'pdf'), ('Plain Text (.txt)', 'txt')],
                'Export As'),
            daemon=True,
        )
        t.start()
        t.join(timeout=20)
        self.assertTrue('path' in holder, holder)
        h = self.acc.setFrame_.call_args[0][0][3]
        self.assertEqual(h, 306.0, 'PDF增加八行设置且不与格式行重叠')


if __name__ == '__main__':
    unittest.main()