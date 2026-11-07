"""项目内的 pywebview CSP 适配；不修改安装依赖，不允许字符串求值。"""
import json
import uuid
import threading


def run_body(window, body, callback=None):
    """body是可信固定函数体，可声明变量并显式return；不猜最后表达式。"""
    source = '(function(){\n' + body + '\n})()'
    if callback is None:
        return window.gui.evaluate_js(source, window.uid, False)
    identity = uuid.uuid4().hex
    lock = threading.Lock()
    settled = False
    timer = None

    def settle(result):
        nonlocal settled
        with lock:
            if settled:
                return
            settled = True
            window._callbacks.pop(identity, None)
            if timer:
                timer.cancel()
        callback(result)

    window._callbacks[identity] = settle
    timer = threading.Timer(30, lambda: settle({'success': False, 'error': 'javascript-timeout'}))
    timer.daemon = True
    timer.start()
    source = 'pywebview._runBody(' + json.dumps(identity) + ', function(){\n' + body + '\n}); void 0;'
    try:
        window.gui.evaluate_js(source, window.uid, False)
    except Exception:
        settle({'success': False, 'error': 'native-javascript-failed'})
    return identity


def run_expression(window, expression, callback=None):
    """只接受调用方明确给出的单个表达式，不支持多语句末值兼容。"""
    return run_body(window, 'return (\n' + expression + '\n);', callback)


def install(resource_path):
    import webview.util as util
    from webview.window import Window
    if getattr(Window, '_mdpreview_csp', False):
        return
    original = util.load_js_files
    with open(resource_path('frontend/csp-api.js'), encoding='utf-8') as stream:
        adapter = stream.read()

    def load(window, platform):
        code, finish = original(window, platform)
        start = code.find('  _createApi: function (funcList) {')
        end = code.find('  _jsApiCallback: function (funcName, params, id) {', start)
        if start < 0 or end < start or 'new Function(' not in code[start:end]:
            raise RuntimeError('unsupported-pywebview-api-template')
        # 明确匹配受支持的模板边界；上游改动时拒绝启动而非回退unsafe-eval。
        code = code[:start] + '  _createApi: null,\n' + code[end:]
        return code + '\n' + adapter, finish

    def evaluate(window, script, callback=None):
        if not window.events._pywebviewready.wait(15):
            raise RuntimeError('bridge-not-ready')
        if callback is None:
            # 直接交给原生JS引擎执行程序，保留最后表达式结果；不经过JS eval包装。
            return window.gui.evaluate_js(script, window.uid, False)
        raise TypeError('evaluate_js callback unsupported; use run_body or run_expression explicitly')

    import webview.platforms.cocoa as cocoa
    original_bridge = cocoa.js_bridge_call

    def bridge_call(window, name, params, identity):
        if name == 'pywebviewAsyncCallback':
            callback = window._callbacks.pop(identity, None)
            if callback:
                try:
                    result = json.loads(params) if params is not None else None
                except (ValueError, TypeError):
                    result = {'success': False, 'error': 'invalid-javascript-result'}
                callback(result)
            return
        return original_bridge(window, name, params, identity)

    cocoa.js_bridge_call = bridge_call
    util.load_js_files = load
    Window.evaluate_js = evaluate
    Window._mdpreview_csp = True
