"""Probe: how big does mdPreview's print CSS come out on paper via WKWebView printing?
Mirrors pywebview's print_webview() settings and saves to PDF, then measures glyph heights."""
import sys, os
import AppKit, Foundation, WebKit, Quartz, objc
from PyObjCTools import AppHelper

ROOT = sys.argv[1]
OUT = sys.argv[2]
EXTRA_CSS = sys.argv[3] if len(sys.argv) > 3 else ''
css = open(os.path.join(ROOT, 'styles.css'), encoding='utf-8').read()
html = """<!doctype html><html><head><meta charset=utf-8><style>%s</style><style>%s</style></head><body>
<div class=scroll-wrap><div class=page><div class=markdown>
<h1>HHeading One</h1><h2>HHeading Two</h2><h3>HHeading Three</h3>
<p>HBody paragraph text xxxx 中文正文测试 HHHH.</p>
<pre><code>HCode block line</code></pre>
<table><tr><th>HTh</th></tr><tr><td>HTd cell</td></tr></table>
</div></div></div></body></html>""" % (css, EXTRA_CSS)

class Delegate(AppKit.NSObject):
    def webView_didFinishNavigation_(self, wv, nav):
        AppHelper.callLater(0.5, self.doPrint)
    def doPrint(self):
        info = AppKit.NSPrintInfo.sharedPrintInfo().copy()
        info.setPaperSize_(Foundation.NSMakeSize(595.28, 841.89))
        info.setHorizontalPagination_(AppKit.NSFitPagination)
        info.setHorizontallyCentered_(False)
        info.setVerticallyCentered_(False)
        for m in ('Top', 'Bottom', 'Left', 'Right'):
            getattr(info, 'set%sMargin_' % m)(18.0)
        d = info.dictionary()
        d[AppKit.NSPrintJobDisposition] = AppKit.NSPrintSaveJob
        d[AppKit.NSPrintJobSavingURL] = Foundation.NSURL.fileURLWithPath_(OUT)
        op = self.wv._printOperationWithPrintInfo_(info)
        op.setShowsPrintPanel_(False)
        op.setShowsProgressPanel_(False)
        op.runOperationModalForWindow_delegate_didRunSelector_contextInfo_(self.win, self, 'done:success:ctx:', None)
    def done_success_ctx_(self, op, ok, ctx):
        AppHelper.callLater(0.3, self.measure)
    done_success_ctx_ = objc.selector(done_success_ctx_, signature=b'v@:@Z^v')
    def measure(self):
        doc = Quartz.PDFDocument.alloc().initWithURL_(Foundation.NSURL.fileURLWithPath_(OUT))
        page = doc.pageAtIndex_(0)
        s = page.string()
        print('pages:', doc.pageCount(), 'mediabox:', page.boundsForBox_(Quartz.kPDFDisplayBoxMediaBox).size)
        for label in ('HHeading One', 'HHeading Two', 'HHeading Three', 'HBody', 'HCode', 'HTh', 'HTd'):
            i = s.find(label)
            if i < 0:
                print(label, 'not found'); continue
            r = page.characterBoundsAtIndex_(i)  # bounds of 'H' glyph (cap height-ish box)
            # PDFKit returns the font line box; report its height (≈ font size * ~1.2)
            print('%-15s glyph box h=%.1fpt  (≈font %.1fpt)' % (label, r.size.height, r.size.height / 1.2))
        AppKit.NSApp.terminate_(None)

app = AppKit.NSApplication.sharedApplication()
app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
    Foundation.NSMakeRect(-3000, 0, 1000, 800), AppKit.NSWindowStyleMaskBorderless, AppKit.NSBackingStoreBuffered, False)
wv = WebKit.WKWebView.alloc().initWithFrame_configuration_(Foundation.NSMakeRect(0, 0, 1000, 800), WebKit.WKWebViewConfiguration.alloc().init())
win.setContentView_(wv)
win.orderFront_(None)
dl = Delegate.alloc().init(); dl.wv = wv; dl.win = win
wv.setNavigationDelegate_(dl)
wv.loadHTMLString_baseURL_(html, None)
AppHelper.callLater(20, lambda: (print('timeout'), AppKit.NSApp.terminate_(None)))
AppHelper.runEventLoop()
