"""CJK 文本映射修复：部首码位 → 真正的汉字（搜索、复制、书签都依赖它）。"""
import os
import random
import sys
import tempfile
import unicodedata
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mdpreview_core.export import pdf_text  # noqa: E402
from mdpreview_core.export.cjk_radicals import RADICAL_TO_IDEOGRAPH  # noqa: E402

FIXTURE = ROOT / 'tests' / 'fixtures' / 'cjk-sample.pdf'
PHRASE = '正文用于验证分页'


class TableTests(unittest.TestCase):
    def test_table_shape(self):
        self.assertGreater(len(RADICAL_TO_IDEOGRAPH), 200)
        for radical, ideograph in RADICAL_TO_IDEOGRAPH.items():
            self.assertTrue(0x2E80 <= radical <= 0x2FD5, hex(radical))
            self.assertTrue(0x2E80 <= ideograph <= 0xA000 and ideograph not in RADICAL_TO_IDEOGRAPH, hex(ideograph))

    def test_kangxi_radicals_agree_with_unicode_nfkc(self):
        for radical, ideograph in RADICAL_TO_IDEOGRAPH.items():
            if 0x2F00 <= radical <= 0x2FD5:
                self.assertEqual(unicodedata.normalize('NFKC', chr(radical)), chr(ideograph), hex(radical))

    def test_known_characters(self):
        for radical, ideograph in {0x2F42: '文', 0x2F64: '用', 0x2F00: '一', 0x2EDA: '页'}.items():
            self.assertEqual(chr(RADICAL_TO_IDEOGRAPH[radical]), ideograph)


class CanonicalTests(unittest.TestCase):
    def test_radicals_become_ideographs(self):
        self.assertEqual(pdf_text.canonical('正⽂⽤于验证分⻚'), '正文用于验证分页')

    def test_length_preserved_and_plain_text_untouched(self):
        for text in ('hello world', '普通中文：文用页', 'emoji 😀 mixed 𠀀', ''):
            self.assertEqual(len(pdf_text.canonical(text)), len(text))
        self.assertEqual(pdf_text.canonical('hello 普通中文 😀'), 'hello 普通中文 😀')

    def test_compatibility_ideographs_fold(self):
        self.assertEqual(pdf_text.canonical('豈'), '豈')

    def test_idempotent(self):
        once = pdf_text.canonical('⽂⻚豈')
        self.assertEqual(pdf_text.canonical(once), once)


class CMapTests(unittest.TestCase):
    HEAD = b'/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n1 begincodespacerange\n<00><FF>\nendcodespacerange\n'
    TAIL = b'endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n'

    def cmap(self, body):
        return self.HEAD + body + self.TAIL

    def test_bfchar_and_bfrange_are_normalised_and_expanded(self):
        text = self.cmap(b'1 beginbfchar\n<01> <2F42>\nendbfchar\n2 beginbfrange\n<10><12><2F64>\n<20><20><0041>\nendbfrange\n')
        fixed = pdf_text._rewrite_cmap(text)
        self.assertIsNotNone(fixed)
        self.assertIn(b'<01> <6587>', fixed)
        self.assertIn(b'<10> <7528>', fixed)          # 2F64 -> 用
        self.assertNotIn(b'2F42', fixed.upper())
        self.assertIn(b'<20> <0041>', fixed)          # 无关映射保留
        self.assertTrue(fixed.startswith(self.HEAD) and fixed.endswith(self.TAIL))

    def test_array_form(self):
        text = self.cmap(b'1 beginbfrange\n<01><02>[<2F42> <0042>]\nendbfrange\n')
        fixed = pdf_text._rewrite_cmap(text)
        self.assertIn(b'<01> <6587>', fixed)
        self.assertIn(b'<02> <0042>', fixed)

    def test_nothing_to_fix_returns_none(self):
        self.assertIsNone(pdf_text._rewrite_cmap(self.cmap(b'1 beginbfchar\n<01> <6587>\nendbfchar\n')))
        self.assertIsNone(pdf_text._rewrite_cmap(b'not a cmap'))

    def test_blocks_are_chunked_to_100(self):
        body = b'1 beginbfrange\n<0000><00FF><2F00>\nendbfrange\n'
        fixed = pdf_text._rewrite_cmap(self.cmap(body))
        self.assertEqual(len(fixed.split(b'beginbfchar')) - 1, 3)  # 256 项 -> 100+100+56
        for block in fixed.split(b'beginbfchar')[1:]:
            self.assertLessEqual(block.count(b'\n<'), 100)

    def test_two_byte_codes_keep_their_width(self):
        fixed = pdf_text._rewrite_cmap(self.cmap(b'1 beginbfchar\n<0001> <2F42>\nendbfchar\n'))
        self.assertIn(b'<0001> <6587>', fixed)

    def test_malformed_ranges_raise(self):
        with self.assertRaises(ValueError):
            pdf_text._rewrite_cmap(self.cmap(b'1 beginbfrange\n<10><05><2F42>\nendbfrange\n'))
        with self.assertRaises(ValueError):
            pdf_text._rewrite_cmap(self.cmap(b'1 beginbfrange\n<0000><FFFF><2F00>\nendbfrange\n'.replace(b'FFFF', b'1FFFF')))


@unittest.skipUnless(sys.platform == 'darwin', 'PDFKit is macOS-only')
class RepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = FIXTURE.read_bytes()
        cls.fixed = pdf_text.repair(cls.original)

    @staticmethod
    def open(data):
        import Foundation
        import Quartz
        return Quartz.PDFDocument.alloc().initWithData_(Foundation.NSData.dataWithBytes_length_(data, len(data)))

    def test_fixture_really_has_the_problem(self):
        self.assertNotIn(PHRASE, str(self.open(self.original).string()))

    def test_repair_yields_real_characters(self):
        before, after = self.open(self.original), self.open(self.fixed)
        self.assertEqual(before.pageCount(), after.pageCount())
        self.assertIn(PHRASE, str(after.string()))
        for index in range(before.pageCount()):
            self.assertEqual(pdf_text.canonical(str(before.pageAtIndex_(index).string())), str(after.pageAtIndex_(index).string()))

    def test_incremental_update_keeps_original_bytes(self):
        self.assertGreater(len(self.fixed), len(self.original))
        self.assertTrue(self.fixed.startswith(self.original))
        self.assertTrue(self.fixed.rstrip().endswith(b'%%EOF'))
        self.assertIn(b'/Prev ', self.fixed[len(self.original):])

    def test_idempotent(self):
        self.assertEqual(pdf_text.repair(self.fixed), self.fixed)

    def test_unusable_input_is_returned_unchanged(self):
        rng = random.Random(7)
        cases = [b'', b'%PDF-1.4\n', b'%PDF-1.4\n%%EOF', bytes(rng.randrange(256) for _ in range(5000)),
                 self.original[:-100], self.original[: len(self.original) // 2],
                 self.original.replace(b'startxref', b'startxrfe'),
                 self.original.replace(b'trailer', b'trailXr'),
                 self.original.replace(b'/ToUnicode', b'/ToUnicodX')]
        for data in cases:
            with self.subTest(size=len(data)):
                self.assertEqual(pdf_text.repair(data), data)

    def test_encrypted_pdf_is_left_alone(self):
        data = self.original.replace(b'trailer', b'trailer\n<< /Encrypt 1 0 R >>\n%', 1)
        self.assertEqual(pdf_text.repair(data), data)

    def test_non_flate_unknown_filter_skipped(self):
        data = self.original.replace(b'/Filter /FlateDecode', b'/Filter /LZWDecode')
        self.assertEqual(pdf_text.repair(data), data)

    def test_fuzzed_streams_never_raise(self):
        rng = random.Random(11)
        for _ in range(60):
            data = bytearray(self.original)
            for _ in range(rng.randrange(1, 8)):
                data[rng.randrange(len(data))] = rng.randrange(256)
            result = pdf_text.repair(bytes(data))
            self.assertIsInstance(result, bytes)


@unittest.skipUnless(sys.platform == 'darwin', 'PDFKit is macOS-only')
class FinalizeIntegration(unittest.TestCase):
    def test_headings_with_radical_lookalikes_get_bookmarks_and_text_is_searchable(self):
        import Foundation
        import Quartz
        from mdpreview_core.export import pdf_post
        with tempfile.TemporaryDirectory() as folder:
            out = Path(os.path.realpath(folder)) / 'out.pdf'
            meta = {'title': '测试', 'pageNumbers': True, 'headings': [{'level': 1, 'text': 'CLI 多页输出'}],
                    'links': []}
            pdf_post.finalize(FIXTURE, out, meta)
            doc = Quartz.PDFDocument.alloc().initWithURL_(Foundation.NSURL.fileURLWithPath_(str(out)))
            self.assertIn(PHRASE, str(doc.string()))
            self.assertNotIn('⽂', str(doc.string()))
            self.assertNotIn('⻚', str(doc.string()))
            root = doc.outlineRoot()
            self.assertIsNotNone(root)
            self.assertGreaterEqual(root.numberOfChildren(), 1)
            self.assertEqual(root.childAtIndex_(0).label(), 'CLI 多页输出')


if __name__ == '__main__':
    unittest.main(verbosity=2)
