"""原生 PDF 后处理；所有变更完成后才原子替换目标文件。"""
import re
from pathlib import Path
from mdpreview_core.storage import atomic_write, atomic_create
from mdpreview_core.export import pdf_text


def _utf16_length(text):
    return len(text.encode('utf-16-le')) // 2


def find_text(doc, needle):
    """在“规范化”的页面文本里不区分大小写地查找，返回 [(页序号, 页, 选区)]。

    PDFKit 的 findString 搜的是 PDF 里的原始文本，而 macOS 常把 文/页 等字存成部首码位，
    搜不到就会丢书签和链接；这里先规范化页面文本，再按 UTF-16 偏移取选区。
    """
    if not needle:
        return []
    pattern = re.compile(re.escape(pdf_text.canonical(needle)), re.IGNORECASE)
    found = []
    for index in range(doc.pageCount()):
        page = doc.pageAtIndex_(index)
        text = pdf_text.canonical(str(page.string() or ''))
        for match in pattern.finditer(text):
            start = _utf16_length(text[:match.start()])
            selection = page.selectionForRange_((start, _utf16_length(match.group(0))))
            if selection is not None:
                found.append((index, page, selection))
    return found


def finalize(src, dst, meta, commit_guard=None, no_clobber=False):
    import AppKit
    import Foundation
    import Quartz
    doc = Quartz.PDFDocument.alloc().initWithURL_(Foundation.NSURL.fileURLWithPath_(str(src)))
    if not doc or not doc.pageCount():
        raise ValueError('invalid-pdf')
    if meta.get('pageNumbers', True):
        original = doc
        data = Foundation.NSMutableData.data()
        consumer = Quartz.CGDataConsumerCreateWithCFData(data)
        context = Quartz.CGPDFContextCreate(consumer, None, None)
        for index in range(original.pageCount()):
            page = original.pageAtIndex_(index)
            bounds = page.boundsForBox_(Quartz.kPDFDisplayBoxMediaBox)
            import struct
            box = struct.pack('dddd', bounds.origin.x, bounds.origin.y, bounds.size.width, bounds.size.height)
            Quartz.CGPDFContextBeginPage(context, {Quartz.kCGPDFContextMediaBox: Foundation.NSData.dataWithBytes_length_(box, len(box))})
            Quartz.CGContextDrawPDFPage(context, page.pageRef())
            AppKit.NSGraphicsContext.saveGraphicsState()
            try:
                AppKit.NSGraphicsContext.setCurrentContext_(AppKit.NSGraphicsContext.graphicsContextWithCGContext_flipped_(context, False))
                attrs = {AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(8),
                         AppKit.NSForegroundColorAttributeName: AppKit.NSColor.grayColor()}
                text = Foundation.NSString.stringWithString_(f'{index+1} / {original.pageCount()}')
                width = text.sizeWithAttributes_(attrs).width
                text.drawAtPoint_withAttributes_(((bounds.size.width-width)/2, 20), attrs)
            finally:
                AppKit.NSGraphicsContext.restoreGraphicsState()
            Quartz.CGPDFContextEndPage(context)
        Quartz.CGPDFContextClose(context)
        doc = Quartz.PDFDocument.alloc().initWithData_(data)
        # 重画保留正文矢量；链接注释显式复制回新页。
        for index in range(original.pageCount()):
            for annotation in original.pageAtIndex_(index).annotations() or []:
                if str(annotation.type()) == 'Link':
                    doc.pageAtIndex_(index).addAnnotation_(annotation.copy())
    if not any(str(a.type()) == 'Link' for i in range(doc.pageCount())
               for a in doc.pageAtIndex_(i).annotations() or []):
        from urllib.parse import urlsplit
        for link in meta.get('links', []):
            url, text = str(link.get('url', '')), str(link.get('text', '')).strip()
            if not text or urlsplit(url).scheme not in ('http', 'https'):
                continue
            for _, page, selection in find_text(doc, text):
                note = Quartz.PDFAnnotation.alloc().initWithBounds_forType_withProperties_(
                    selection.boundsForPage_(page), Quartz.PDFAnnotationSubtypeLink, None)
                note.setURL_(Foundation.NSURL.URLWithString_(url))
                border = Quartz.PDFBorder.alloc().init()
                border.setLineWidth_(0)
                note.setBorder_(border)
                page.addAnnotation_(note)
    root = Quartz.PDFOutline.alloc().init()
    stack = [(0, root)]
    previous = 0
    for heading in meta.get('headings', []):
        text = str(heading.get('text', ''))[:1024]
        level = int(heading.get('level', 1))
        if not text or level not in (1, 2, 3):
            continue
        chosen = next(((i, pg, sel) for i, pg, sel in find_text(doc, text) if i >= previous), None)
        if chosen is None:
            continue
        previous, page, selection = chosen
        bounds = selection.boundsForPage_(page)
        item = Quartz.PDFOutline.alloc().init()
        item.setLabel_(text)
        item.setDestination_(Quartz.PDFDestination.alloc().initWithPage_atPoint_(page, (bounds.origin.x, bounds.origin.y+bounds.size.height)))
        while stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1]
        parent.insertChild_atIndex_(item, parent.numberOfChildren())
        stack.append((level, item))
    doc.setOutlineRoot_(root)
    version = (Path(__file__).resolve().parents[2]/'VERSION').read_text().strip()
    doc.setDocumentAttributes_({Quartz.PDFDocumentTitleAttribute: str(meta.get('title', '')),
                               Quartz.PDFDocumentCreatorAttribute: 'mdPreview '+version,
                               Quartz.PDFDocumentAuthorAttribute: str(meta.get('author', ''))})
    data = doc.dataRepresentation()
    if data is None:
        raise OSError('pdf-serialization-failed')
    payload = _repair_text_maps(doc, bytes(data))
    from contextlib import nullcontext
    with commit_guard() if commit_guard else nullcontext():
        (atomic_create if no_clobber else atomic_write)(dst, payload)


def _repair_text_maps(doc, payload):
    """把 ToUnicode 里的部首改回真正的汉字；PDFKit 复核每页文本，任何不一致都保留原文件。"""
    import Foundation
    import Quartz
    fixed = pdf_text.repair(payload)
    if fixed == payload:
        return payload
    check = Quartz.PDFDocument.alloc().initWithData_(Foundation.NSData.dataWithBytes_length_(fixed, len(fixed)))
    if check is None or check.pageCount() != doc.pageCount():
        return payload
    for index in range(doc.pageCount()):
        expected = pdf_text.canonical(str(doc.pageAtIndex_(index).string() or ''))
        if str(check.pageAtIndex_(index).string() or '') != expected:
            return payload
    return fixed
