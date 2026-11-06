"""基于 print_probe 的 WKWebView 原生打印探针，仅在 WorkSpace 写出测试产物。

用法：.venv/bin/python -I -B scripts/output_probe.py --html sample.html
      --css css/tokens.css,css/content.css,css/app.css,css/print.css --out WorkSpace/outputs/sample.pdf --json
也可用 --markdown 加载当前应用渲染器；所有远程资源一律禁止访问。
字形框为 PDFKit 实测框，并非 CSS 字号；亮度由 PDF 栅格像素计算。
"""
import argparse
import html
import json
import math
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / 'WorkSpace'
MARKERS = {'h1': 'HHeading One', 'h2': 'HHeading Two', 'h3': 'HHeading Three',
           'body': 'HBody', 'code': 'HCode', 'table': 'HTd'}
MARGIN = 18.0


def options():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--html', type=Path)
    source.add_argument('--markdown', type=Path)
    parser.add_argument('--css', default='', help='按顺序加载的 CSS 路径，以逗号分隔')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--dark', action='store_true')
    parser.add_argument('--font-size', default=None)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--native-engine', action='store_true')
    args = parser.parse_args()
    args.out = args.out.resolve()
    if not args.out.is_relative_to(WORKSPACE.resolve()):
        parser.error('--out 必须在 WorkSpace 内')
    if args.out.exists():
        parser.error('目标已存在；请使用新文件名以保留历史证据')
    if args.font_size and not re.fullmatch(r'\d+(?:\.\d+)?(?:px|pt)', args.font_size):
        parser.error('--font-size 必须为数字加 px 或 pt')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    return args


def prepare_html(args):
    source = (args.html or args.markdown).resolve()
    if args.markdown:
        content = (ROOT / 'index.html').read_text(encoding='utf-8')
        base = ROOT
    else:
        content = source.read_text(encoding='utf-8')
        base = source.parent
    css = '\n'.join(Path(p).read_text(encoding='utf-8') for p in args.css.split(',') if p)
    # CSP 只用于测试隔离；不更改应用的实际配置或打印样式。
    security = ('<meta http-equiv="Content-Security-Policy" content="default-src file: data: blob:; '
                'script-src file: \'unsafe-inline\' \'unsafe-eval\'; style-src file: \'unsafe-inline\'; '
                'img-src file: data: blob:; connect-src \'none\'; frame-src \'none\'; object-src \'none\'">')
    injected = security + '<base href="' + html.escape(base.as_uri() + '/', quote=True) + '">'
    if css:
        injected += '<style>' + re.sub(r'</style', r'<\\/style', css, flags=re.I) + '</style>'
    if re.search(r'<head\b[^>]*>', content, re.I):
        content = re.sub(r'(<head\b[^>]*>)', lambda m: m[0] + injected, content, count=1, flags=re.I)
    else:
        content = '<head>' + injected + '</head>' + content
    return content, base


def measure_pdf(path):
    import Foundation
    import Quartz

    url = Foundation.NSURL.fileURLWithPath_(str(path))
    doc = Quartz.PDFDocument.alloc().initWithURL_(url)
    cgdoc = Quartz.CGPDFDocumentCreateWithURL(url)
    if not doc or not doc.pageCount() or not cgdoc:
        raise RuntimeError('原生打印未生成有效 PDF')
    heights = {key: [] for key in MARKERS}
    sizes, outside_examples = [], []
    outside = links = characters = total_pixels = 0
    luminance_sum = dark_ink = ink = 0
    code_luminance, code_background = [], []
    for number in range(doc.pageCount()):
        page = doc.pageAtIndex_(number)
        bounds = page.boundsForBox_(Quartz.kPDFDisplayBoxMediaBox)
        ox, oy = bounds.origin.x, bounds.origin.y
        width, height = bounds.size.width, bounds.size.height
        sizes.append([round(width, 2), round(height, 2)])
        text = str(page.string() or '')
        if not text.strip():
            raise RuntimeError(f'第 {number + 1} 页没有可提取文字，不能建立字形基线')
        rectangles = []
        # PDFKit 字形索引不包含 string() 插入的换行，逐个枚举真实字形。
        for index in range(page.numberOfCharacters()):
            rect = page.characterBoundsAtIndex_(index)
            if rect.size.width <= 0 or rect.size.height <= 0:
                continue
            x, y, w, h = rect.origin.x, rect.origin.y, rect.size.width, rect.size.height
            rectangles.append((x, y, w, h))
            characters += 1
            if x < ox + MARGIN - .5 or y < oy + MARGIN - .5 or x + w > ox + width - MARGIN + .5 or y + h > oy + height - MARGIN + .5:
                outside += 1
                if len(outside_examples) < 8:
                    outside_examples.append({'page': number + 1, 'bbox': [round(v, 2) for v in (x, y, w, h)]})
        code_rects = []
        for key, marker in MARKERS.items():
            start = 0
            while (position := text.find(marker, start)) >= 0:
                offset = len(text[:position].encode('utf-16-le')) // 2
                # selection 使用文本索引，先取首字符排版框，再按位置匹配真实墨迹框。
                selection = page.selectionForRange_(Foundation.NSMakeRange(offset, 1))
                layout = selection.boundsForPage_(page)
                lx, ly = layout.origin.x, layout.origin.y
                lw, lh = layout.size.width, layout.size.height
                candidates = [(x, y, w, h) for x, y, w, h in rectangles
                              if lx - .5 <= x <= lx + lw and ly - .5 <= y
                              and y + h <= ly + lh + .5 and x + w > lx]
                if not candidates:
                    raise RuntimeError(f'无法定位标记字形：{key}')
                x, y, w, h = min(candidates, key=lambda r: abs(r[0] - lx))
                heights[key].append(h)
                if key == 'code':
                    code_rects.append(Quartz.CGRectMake(x, y, w, h))
                start = position + len(marker)
        for annotation in page.annotations() or []:
            if str(annotation.type()) == 'Link':
                links += 1
        # 1 像素/pt，白底，固定 RGBA 字节序；以同一 PDF 做亮度分析。
        pw, ph = math.ceil(width), math.ceil(height)
        pixels = bytearray(pw * ph * 4)
        ctx = Quartz.CGBitmapContextCreate(pixels, pw, ph, 8, pw * 4,
                                          Quartz.CGColorSpaceCreateDeviceRGB(),
                                          Quartz.kCGImageAlphaPremultipliedLast | Quartz.kCGBitmapByteOrder32Big)
        if ctx is None:
            raise RuntimeError('无法建立 PDF 栅格上下文')
        Quartz.CGContextSetRGBFillColor(ctx, 1, 1, 1, 1)
        Quartz.CGContextFillRect(ctx, ((0, 0), (pw, ph)))
        Quartz.CGContextTranslateCTM(ctx, -ox, -oy)
        Quartz.CGContextDrawPDFPage(ctx, Quartz.CGPDFDocumentGetPage(cgdoc, number + 1))
        luminances = bytearray(pw * ph)
        for p in range(pw * ph):
            pos = p * 4
            luminances[p] = round(.2126 * pixels[pos] + .7152 * pixels[pos + 1] + .0722 * pixels[pos + 2])
        luminance_sum += sum(luminances)
        total_pixels += len(luminances)
        # 去重字符框内像素；白色像素排除后统计深色墨迹比例。
        text_mask = bytearray(pw * ph)
        for x, y, w, h in rectangles:
            left, right = max(0, math.floor(x - ox)), min(pw, math.ceil(x + w - ox))
            top, bottom = max(0, math.floor(height - (y + h - oy))), min(ph, math.ceil(height - (y - oy)))
            for row in range(top, bottom):
                text_mask[row * pw + left:row * pw + right] = b'\x01' * max(0, right - left)
        for p, selected in enumerate(text_mask):
            if selected and luminances[p] < 245:
                ink += 1
                dark_ink += luminances[p] < 128
        for rect in code_rects:
            x, y = rect.origin.x, rect.origin.y
            left = max(0, math.floor(x - ox))
            right = min(pw, left + 180)
            top = max(0, math.floor(height - (y + rect.size.height - oy) - 4))
            bottom = min(ph, math.ceil(height - (y - oy) + 4))
            values = [luminances[row * pw + col] for row in range(top, bottom) for col in range(left, right)]
            if values:
                code_luminance.append(round(statistics.mean(values), 3))
            # 采样首个代码字形左侧的内边距，避免把文字墨迹当作背景证据。
            padding_left, padding_right = max(0, left - 6), max(0, left - 2)
            padding = [luminances[row * pw + col] for row in range(top + 4, bottom - 4)
                       for col in range(padding_left, padding_right)]
            if padding:
                code_background.append(round(statistics.mean(padding), 3))
    return {'pages': int(doc.pageCount()), 'page_size': sizes[0], 'page_sizes': sizes,
            'glyph_heights': {k: round(statistics.median(v), 3) if v else None for k, v in heights.items()},
            'text_bboxes_outside_margin': outside, 'outside_examples': outside_examples,
            'link_count': links, 'dark_text_ratio': round(dark_ink / ink, 5) if ink else None,
            'mean_luminance': round(luminance_sum / total_pixels, 3),
            'code_region_luminance': code_luminance, 'code_background_luminance': code_background,
            'text_characters': characters,
            'measurement': {'margin_pt': MARGIN, 'bbox_tolerance_pt': .5, 'raster_scale': 1,
                            'dark_text_ratio': '字符框内亮度<128像素 / 字符框内亮度<245像素',
                            'glyph_heights': 'PDFKit 文本选区定位首字符墨迹框的中位高度(pt)，缺失标记为 null',
                            'version': 2, 'code_background': '代码首字形左侧内边距的平均亮度'}}


def run(args):
    import AppKit
    import Foundation
    import WebKit
    import objc
    from PyObjCTools import AppHelper

    content, base = prepare_html(args)
    state = {'finished': False, 'error': None, 'result': None}

    def finish(error=None):
        if state['finished']:
            return
        state['finished'] = True
        state['error'] = str(error) if error else None
        if error:
            print(f'原生探针失败：{error}', file=sys.stderr, flush=True)

    class Delegate(AppKit.NSObject):
        def webView_didFinishNavigation_(self, webview, navigation):
            setup = ''
            if args.markdown:
                source = args.markdown.resolve()
                setup = ('window.pywebview={api:{set_dirty:()=>true,store_content:()=>({success:true}),startup_ready:()=>true}};'
                         'await window.loadContent(' + json.dumps(str(source)) + ','
                         + json.dumps(source.read_text(encoding='utf-8')) + ',720,false,true);')
            font = json.dumps(args.font_size)
            script = '''(async()=>{try{
                SETUP
                if (FONT) document.documentElement.style.setProperty('--content-font-size',FONT);
                await document.fonts.ready;
                await Promise.all([...document.images].map(i=>i.decode().catch(()=>null)));
                // 屏幕外 WKWebView 可能暂停动画帧；字体和图片就绪后由原生端再等待 0.5 秒。
                window.__outputProbe={ready:true,images:[...document.images].map(i=>({loaded:i.complete&&i.naturalWidth>0,remote:/^https?:/.test(i.src)})),
                    mermaid:document.querySelectorAll('.mermaid-diagram svg').length,
                    math:document.querySelectorAll('.math-inline,.math-block').length,
                    katex:document.querySelectorAll('.katex').length};
            }catch(e){window.__outputProbe={error:String(e)+' '+String(e.stack||'')}}})(); void 0;'''.replace('FONT', font).replace('SETUP', setup)
            webview.evaluateJavaScript_completionHandler_(script, self.setupDone)

        @objc.python_method
        def setupDone(self, result, error):
            if error:
                finish(error)
            else:
                AppHelper.callLater(.1, self.checkReady)

        def checkReady(self):
            if not state['finished']:
                self.wv.evaluateJavaScript_completionHandler_('JSON.stringify(window.__outputProbe||{})', self.readyDone)

        @objc.python_method
        def readyDone(self, result, error):
            if error:
                finish(error)
                return
            data = json.loads(result or '{}')
            if data.get('error'):
                finish(data['error'])
            elif data.get('ready'):
                state['render'] = data
                AppHelper.callLater(.5, self.doPrint)
            else:
                AppHelper.callLater(.1, self.checkReady)

        def webView_didFailNavigation_withError_(self, webview, navigation, error):
            finish(error)

        def webView_didFailProvisionalNavigation_withError_(self, webview, navigation, error):
            finish(error)

        def doPrint(self):
            try:
                if args.native_engine:
                    sys.path.insert(0, str(ROOT))
                    from mdpreview_core.export import print_engine
                    info = print_engine.make_print_info('a4', 'normal', args.out)
                    self.print_delegate = print_engine.run(self.wv, self.win, info, False,
                                                          lambda success: self.done_success_ctx_(None, success, None))
                    return
                info = AppKit.NSPrintInfo.sharedPrintInfo().copy()
                info.setPaperSize_(Foundation.NSMakeSize(595.28, 841.89))
                info.setHorizontalPagination_(AppKit.NSFitPagination)
                info.setVerticalPagination_(AppKit.NSAutoPagination)
                info.setHorizontallyCentered_(False)
                info.setVerticallyCentered_(False)
                for edge in ('Top', 'Bottom', 'Left', 'Right'):
                    getattr(info, f'set{edge}Margin_')(MARGIN)
                info.dictionary()[AppKit.NSPrintJobDisposition] = AppKit.NSPrintSaveJob
                info.dictionary()[AppKit.NSPrintJobSavingURL] = Foundation.NSURL.fileURLWithPath_(str(args.out))
                # 保持 print_probe 的打印 API 和背景行为，不提前实现 T04。
                self.operation = self.wv._printOperationWithPrintInfo_(info)
                self.operation.setShowsPrintPanel_(False)
                self.operation.setShowsProgressPanel_(False)
                self.operation.runOperationModalForWindow_delegate_didRunSelector_contextInfo_(
                    self.win, self, 'done:success:ctx:', None)
            except Exception as error:
                finish(error)

        def done_success_ctx_(self, operation, success, context):
            if not success:
                finish('NSPrintOperation 返回失败')
                return
            try:
                state['result'] = measure_pdf(args.out)
                state['result'].update({'render': state['render'], 'dark': args.dark,
                                        'font_size_override': args.font_size, 'network': 'blocked',
                                        'engine': 'WKWebView NSPrintOperation + PDFKit + CoreGraphics'})
                finish()
            except Exception as error:
                finish(error)
        done_success_ctx_ = objc.selector(done_success_ctx_, signature=b'v@:@Z^v')

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    appearance = AppKit.NSAppearanceNameDarkAqua if args.dark else AppKit.NSAppearanceNameAqua
    app.setAppearance_(AppKit.NSAppearance.appearanceNamed_(appearance))
    window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        Foundation.NSMakeRect(-3000, 0, 1000, 800), AppKit.NSWindowStyleMaskBorderless,
        AppKit.NSBackingStoreBuffered, False)
    config = WebKit.WKWebViewConfiguration.alloc().init()
    config.setWebsiteDataStore_(WebKit.WKWebsiteDataStore.nonPersistentDataStore())
    webview = WebKit.WKWebView.alloc().initWithFrame_configuration_(Foundation.NSMakeRect(0, 0, 1000, 800), config)
    webview.setAppearance_(AppKit.NSAppearance.appearanceNamed_(appearance))
    window.setContentView_(webview)
    window.orderFront_(None)
    delegate = Delegate.alloc().init()
    delegate.wv, delegate.win = webview, window
    webview.setNavigationDelegate_(delegate)
    prepared = args.out.with_suffix('.input.html')
    if prepared.exists():
        raise FileExistsError(prepared)
    prepared.write_text(content, encoding='utf-8')
    webview.loadFileURL_allowingReadAccessToURL_(
        Foundation.NSURL.fileURLWithPath_(str(prepared)),
        Foundation.NSURL.fileURLWithPath_isDirectory_(str(base), True))
    AppHelper.callLater(45, lambda: finish('原生渲染或打印超过 45 秒'))
    app.finishLaunching()
    while not state['finished']:
        Foundation.NSRunLoop.currentRunLoop().runUntilDate_(Foundation.NSDate.dateWithTimeIntervalSinceNow_(.05))
    webview.setNavigationDelegate_(None)
    window.orderOut_(None)
    if state['error']:
        raise RuntimeError(state['error'])
    return state['result']


def main():
    args = options()
    if sys.platform != 'darwin':
        print('需要 macOS 和 PyObjC；请通过基线测试获得 skip 结果', file=sys.stderr)
        return 2
    try:
        result = run(args)
    except Exception as error:
        print(f'output_probe: {error}', file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=None if args.json else 2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
