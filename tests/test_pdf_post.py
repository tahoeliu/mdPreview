import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

@unittest.skipUnless(sys.platform=='darwin','需要 PDFKit')
class PDFTests(unittest.TestCase):
    def test_continuous_limit(self):
        import Foundation, Quartz, mdPreview
        import struct
        with tempfile.TemporaryDirectory(dir=ROOT/'WorkSpace/cache') as directory:
            source=Path(directory)/'tall.pdf'; target=Path(directory)/'split.pdf'
            context=Quartz.CGPDFContextCreateWithURL(Foundation.NSURL.fileURLWithPath_(str(source)), Quartz.CGRectMake(0,0,500,29000),None)
            Quartz.CGPDFContextBeginPage(context,None)
            Quartz.CGPDFContextEndPage(context); Quartz.CGPDFContextClose(context)
            self.assertEqual(mdPreview._pdf_to_a4_longpage(str(source),str(target)),3)
            doc=Quartz.PDFDocument.alloc().initWithURL_(Foundation.NSURL.fileURLWithPath_(str(target)))
            self.assertEqual(doc.pageCount(),3)
            for i in range(3): self.assertLessEqual(doc.pageAtIndex_(i).boundsForBox_(0).size.height,14000)

    def test_link_fallback_and_invalid_input(self):
        import Foundation, Quartz
        from mdpreview_core.export import pdf_post
        with tempfile.TemporaryDirectory(dir=ROOT/'WorkSpace/cache') as directory:
            target=Path(directory)/'out.pdf'
            pdf_post.finalize(ROOT/'tests/fixtures/native-long.pdf', target,
                              {'pageNumbers':False, 'links':[{'text':'HHeading One','url':'https://example.com'}]})
            doc=Quartz.PDFDocument.alloc().initWithURL_(Foundation.NSURL.fileURLWithPath_(str(target)))
            self.assertGreater(sum(str(a.type())=='Link' for i in range(doc.pageCount()) for a in doc.pageAtIndex_(i).annotations()),0)
            with self.assertRaises(ValueError): pdf_post.finalize(Path(directory)/'missing.pdf',target,{})

    def test_metadata_links_outline_and_atomic_failure(self):
        import Foundation, Quartz
        from mdpreview_core.export import pdf_post
        source=ROOT/'tests/fixtures/native-long.pdf'
        with tempfile.TemporaryDirectory(dir=ROOT/'WorkSpace/cache') as directory:
            target=Path(directory)/'out.pdf'
            meta={'title':'输出测试','author':'测试','headings':[{'level':1,'text':'HHeading One'}], 'pageNumbers':True}
            pdf_post.finalize(source,target,meta)
            doc=Quartz.PDFDocument.alloc().initWithURL_(Foundation.NSURL.fileURLWithPath_(str(target)))
            self.assertGreater(doc.pageCount(),1)
            self.assertEqual(doc.documentAttributes()[Quartz.PDFDocumentTitleAttribute],'输出测试')
            self.assertGreater(doc.outlineRoot().numberOfChildren(),0)
            for i in range(doc.pageCount()): self.assertIn(f'{i+1} / {doc.pageCount()}',str(doc.pageAtIndex_(i).string()))
            original=target.read_bytes()
            with patch.object(pdf_post,'atomic_write',side_effect=OSError('disk')):
                with self.assertRaises(OSError): pdf_post.finalize(source,target,meta)
            self.assertEqual(target.read_bytes(),original)
            from mdpreview_core.export.print_engine import Completion
            state=Completion(); state.finish(True); state.close()
            with self.assertRaises(RuntimeError): pdf_post.finalize(source,target,meta,state.commit_guard)
            self.assertEqual(target.read_bytes(),original)

if __name__=='__main__': unittest.main(verbosity=2)
