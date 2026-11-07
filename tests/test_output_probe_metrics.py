"""用可控原生 PDF 验证测量器，而不是为应用输出设置质量门槛。"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', '需要 macOS PDFKit')
class ProbeMeasurementTests(unittest.TestCase):
    def test_controlled_pdf(self):
        try:
            import AppKit
            import Foundation
            import Quartz
        except ImportError:
            self.skipTest('缺少 PyObjC')
        spec = importlib.util.spec_from_file_location('output_probe', ROOT / 'scripts/output_probe.py')
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)
        with tempfile.TemporaryDirectory(dir=ROOT / 'WorkSpace/cache', prefix='probe-unit-') as directory:
            path = Path(directory) / 'known.pdf'
            context = Quartz.CGPDFContextCreateWithURL(
                Foundation.NSURL.fileURLWithPath_(str(path)), ((0, 0), (595, 842)), None)
            Quartz.CGPDFContextBeginPage(context, None)
            AppKit.NSGraphicsContext.saveGraphicsState()
            try:
                AppKit.NSGraphicsContext.setCurrentContext_(
                    AppKit.NSGraphicsContext.graphicsContextWithCGContext_flipped_(context, False))
                attrs = {AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(18),
                         AppKit.NSForegroundColorAttributeName: AppKit.NSColor.blackColor()}
                Quartz.CGContextSetRGBFillColor(context, .5, .5, .5, 1)
                Quartz.CGContextFillRect(context, ((30, 638), (10, 30)))
                for label, y in [('HHeading One', 740), ('HBody', 690), ('HCode', 640), ('HTd', 590)]:
                    AppKit.NSString.stringWithString_(label).drawAtPoint_withAttributes_((40, y), attrs)
                AppKit.NSString.stringWithString_('Outside').drawAtPoint_withAttributes_((1, 550), attrs)
                Quartz.CGContextSetRGBFillColor(context, 0, 0, 0, 1)
                Quartz.CGContextFillRect(context, ((40, 100), (200, 100)))
                Quartz.CGPDFContextSetURLForRect(context, Foundation.NSURL.URLWithString_('https://github.com/tahoeliu/mdPreview'), ((40, 690), (80, 20)))
            finally:
                AppKit.NSGraphicsContext.restoreGraphicsState()
            Quartz.CGPDFContextEndPage(context)
            Quartz.CGPDFContextClose(context)
            metrics = probe.measure_pdf(path)
            self.assertEqual(metrics['pages'], 1)
            self.assertEqual(metrics['page_size'], [595, 842])
            self.assertGreater(metrics['glyph_heights']['body'], 0)
            for key in ('code', 'table', 'h1'):
                self.assertAlmostEqual(metrics['glyph_heights'][key], metrics['glyph_heights']['body'], places=2)
            self.assertIsNone(metrics['glyph_heights']['h2'])
            self.assertGreater(metrics['text_bboxes_outside_margin'], 0)
            self.assertEqual(metrics['link_count'], 1)
            self.assertGreater(metrics['dark_text_ratio'], .5)
            self.assertLess(metrics['mean_luminance'], 250)
            self.assertTrue(125 <= metrics['code_background_luminance'][0] <= 130, metrics)


if __name__ == '__main__':
    unittest.main(verbosity=2)
