"""主线程生成富文本后一次提交剪贴板，转换失败不清空旧内容。"""
import threading
from html.parser import HTMLParser


class _WithoutImages(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != 'img':
            self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if tag.lower() != 'img':
            self.parts.append('</' + tag + '>')

    def handle_data(self, data):
        self.parts.append(data)

    def handle_entityref(self, name):
        self.parts.append('&' + name + ';')

    def handle_charref(self, name):
        self.parts.append('&#' + name + ';')


def set_rich(html, plain):
    import AppKit
    import Foundation
    from PyObjCTools import AppHelper
    if not isinstance(html, str) or not isinstance(plain, str) or len(html.encode('utf-8')) > 64 * 1024 * 1024:
        return {'success': False, 'error': 'invalid-clipboard-payload'}
    event = threading.Event()
    result = {}
    def write():
        try:
            parser = _WithoutImages()
            parser.feed(html)
            parser.close()
            data = ''.join(parser.parts).encode('utf-8')
            attr, _ = AppKit.NSAttributedString.alloc().initWithHTML_documentAttributes_(Foundation.NSData.dataWithBytes_length_(data, len(data)), None)
            if attr is None:
                raise ValueError('rtf-conversion-failed')
            rtf = attr.RTFFromRange_documentAttributes_((0, attr.length()), {})
            item = AppKit.NSPasteboardItem.alloc().init()
            if not item.setString_forType_(html, AppKit.NSPasteboardTypeHTML) or not item.setString_forType_(plain, AppKit.NSPasteboardTypeString):
                raise ValueError('clipboard-item-failed')
            if rtf is not None and not item.setData_forType_(rtf, AppKit.NSPasteboardTypeRTF):
                raise ValueError('clipboard-rtf-failed')
            pb = AppKit.NSPasteboard.generalPasteboard()
            previous = []
            for old in pb.pasteboardItems() or []:
                copy = AppKit.NSPasteboardItem.alloc().init()
                for kind in old.types():
                    value = old.dataForType_(kind)
                    if value is None or not copy.setData_forType_(value, kind):
                        raise ValueError('clipboard-backup-failed')
                previous.append(copy)
            pb.clearContents()
            try:
                if not pb.writeObjects_([item]):
                    raise OSError('clipboard-write-failed')
            except Exception:
                pb.clearContents()
                if previous and not pb.writeObjects_(previous):
                    raise OSError('clipboard-restore-failed')
                raise
            result['success'] = True
        except Exception:
            result.update(success=False, error='clipboard-write-failed')
        finally:
            event.set()
    if Foundation.NSThread.isMainThread():
        write()
    else:
        try:
            AppHelper.callAfter(write)
        except Exception:
            return {'success': False, 'error': 'clipboard-dispatch-failed'}
        event.wait()
    return result
