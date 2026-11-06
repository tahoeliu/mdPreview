"""主线程原生打印及单次完成状态；交互面板不设置固定超时。"""
import threading

PAPER = {'a4': (595.28, 841.89), 'letter': (612.0, 792.0)}
MARGINS_MM = {'narrow': (12, 12, 14, 12), 'normal': (18, 16, 20, 16), 'wide': (25, 25, 25, 25)}
_active = {}


class Completion:
    def __init__(self):
        self.event = threading.Event()
        self.lock = threading.Lock()
        self.result = None

    def finish(self, success, error='cancelled'):
        with self.lock:
            if self.result is not None:
                return False
            self.result = {'success': True} if success else {
                'success': False, 'error': error, 'cancelled': error in ('cancelled', 'closed')}
            self.event.set()
            return True

    def wait(self, timeout=None):
        self.event.wait(timeout)
        return self.result


def default_paper():
    import Foundation
    region = Foundation.NSLocale.currentLocale().objectForKey_(Foundation.NSLocaleCountryCode)
    return 'letter' if region in ('US', 'CA', 'MX', 'PH') else 'a4'


def make_print_info(paper='auto', margins='normal', save_to=None):
    import AppKit
    import Foundation
    key = default_paper() if paper == 'auto' else paper
    if key not in PAPER or margins not in MARGINS_MM:
        raise ValueError('invalid-print-options')
    info = AppKit.NSPrintInfo.sharedPrintInfo().copy()
    info.setPaperSize_(Foundation.NSMakeSize(*PAPER[key]))
    info.setHorizontalPagination_(AppKit.NSFitPagination)
    info.setVerticalPagination_(AppKit.NSAutoPagination)
    info.setHorizontallyCentered_(False)
    info.setVerticallyCentered_(False)
    for edge, mm in zip(('Top', 'Right', 'Bottom', 'Left'), MARGINS_MM[margins]):
        getattr(info, 'set' + edge + 'Margin_')(mm * 72 / 25.4)
    if save_to:
        info.dictionary()[AppKit.NSPrintJobDisposition] = AppKit.NSPrintSaveJob
        info.dictionary()[AppKit.NSPrintJobSavingURL] = Foundation.NSURL.fileURLWithPath_(str(save_to))
    return info


def run(webview, window, info, show_panel, on_done):
    import AppKit
    import objc
    prefs = webview.configuration().preferences()
    if prefs.respondsToSelector_('setShouldPrintBackgrounds:'):
        prefs.setShouldPrintBackgrounds_(True)
    method = 'printOperationWithPrintInfo_' if webview.respondsToSelector_('printOperationWithPrintInfo:') else '_printOperationWithPrintInfo_'
    if not hasattr(webview, method):
        raise RuntimeError('native-print-unavailable')
    operation = getattr(webview, method)(info)
    operation.setShowsPrintPanel_(show_panel)
    operation.setShowsProgressPanel_(show_panel)
    # 保留 WebKit 自己的分页视图，不把全文打印视图裁剪为可见窗口。
    delegate = _delegate_class().alloc().init()
    delegate.callback = on_done
    delegate.operation = operation
    delegate.finished = False
    _active[id(delegate)] = delegate
    try:
        operation.runOperationModalForWindow_delegate_didRunSelector_contextInfo_(
            window, delegate, 'printOperationDidRun:success:contextInfo:', None)
    except Exception:
        _active.pop(id(delegate), None)
        raise
    return delegate


_delegate = None


def _delegate_class():
    global _delegate
    if _delegate is None:
        import AppKit
        import objc

        class PrintDelegate(AppKit.NSObject):
            def printOperationDidRun_success_contextInfo_(self, operation, success, context):
                if self.finished:
                    return
                self.finished = True
                try:
                    self.callback(bool(success))
                finally:
                    _active.pop(id(self), None)
            printOperationDidRun_success_contextInfo_ = objc.selector(
                printOperationDidRun_success_contextInfo_, signature=b'v@:@Z^v')
        _delegate = PrintDelegate
    return _delegate
