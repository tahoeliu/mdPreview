"""无头窗口复用正式渲染与输出；桥接面只暴露导出所需能力。"""
import json
import os
import sys
import threading
from pathlib import Path


def run(arguments, api_type, resource_path):
    if len(arguments) != 3:
        print('headless: expected INPUT OUTPUT FORMAT', file=sys.stderr)
        return 1
    source, target, fmt = arguments
    source = Path(source).resolve()
    # 目录按真实路径解析（/tmp、/var 都是符号链接）；最终文件名保持不跟随，写入端仍拒绝符号链接。
    target = Path(os.path.abspath(target))
    target = Path(os.path.realpath(target.parent)) / target.name
    if fmt not in ('pdf', 'html', 'docx', 'txt', 'png') or not source.is_file() or not target.parent.is_dir() or target.exists():
        print('headless: invalid format/path or output already exists', file=sys.stderr)
        return 1
    try:
        text = source.read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError):
        print('headless: input must be readable UTF-8', file=sys.stderr)
        return 1
    import webview
    from .export.settings import defaults
    result = {'code': 2}
    done = threading.Event()
    from .export.print_engine import Completion
    api = api_type()
    api.file_path = str(source)
    api.is_untitled = False
    lifecycle = Completion()
    api._headless_lifecycle = lifecycle
    api.get_output_settings = defaults
    state_lock = threading.RLock()
    trace_enabled = bool(os.environ.get('MDPREVIEW_HEADLESS_TRACE'))

    def trace(stage):
        if trace_enabled:
            print('headless-trace: ' + str(stage)[:80], file=sys.stderr, flush=True)
    output = {'started': False, 'success': False}

    def finish(success=False):
        with state_lock:
            if done.is_set():
                return
            lifecycle.close()
            completion = getattr(api, '_output_completion', None)
            if completion:
                completion.close()
            result['code'] = 0 if success is True and output['success'] else 2
            done.set()
        if result['code']:
            print('headless: render or export failed', file=sys.stderr)
        api.window.destroy()
    class ExportAPI:
        def headless_trace(self, stage):
            trace(stage)
        def get_initial_content(self):
            trace('get_initial_content')
            return {'path': str(source), 'content': text, 'headless': True, 'outputPath': str(target), 'outputFormat': fmt,
                    'documentId': api.document_id, 'revision': 0, 'isZh': False,
                    'settings': {'language': 'en', 'remote_images': 'never', 'auto_update': False, 'auto_reload': False}}
        def get_output_settings(self):
            return defaults()
        def get_export_css(self):
            return api.get_export_css()
        def get_math_export_css(self, families):
            return api.get_math_export_css(families)
        def read_image_for_export(self, *args):
            return api.read_image_for_export(*args)
        def export_as_write(self, path, kind, content='', page=None):
            with state_lock:
                if done.is_set() or output['started'] or Path(os.path.abspath(path)) != target or kind != fmt or target.exists():
                    return {'success': False, 'error': 'headless-output-refused'}
                output['started'] = True
            response = api.export_as_write(str(target), fmt, content, page)
            with state_lock:
                output['success'] = response.get('success') is True and all(
                    Path(item).is_file() for item in response.get('paths', [str(target)]))
            return response
        def startup_ready(self, ms):
            return None
        def save_reading_position(self, *args):
            return None
        def set_dirty(self, *args):
            return None
        def store_content(self, *args):
            return {'success': True}
        def report_frontend_error(self, *args):
            print('headless: frontend error', file=sys.stderr)
        def headless_finish(self, success):
            finish(success)
    # 使用本地页面的查询标志，在应用启动前设置禁联网策略。
    # 打包后 index.html 经符号链接指向 Resources；WebKit 只对真实路径授予读取权限。
    url = Path(resource_path('index.html')).resolve().as_uri() + '?headless=1'
    window = webview.create_window('mdPreview export', url=url, js_api=ExportAPI(), hidden=True,
                                  width=900, height=680, confirm_close=False)
    api.window = window
    if trace_enabled:
        trace('window-created:' + url.split('/Contents/')[-1][:60])
        for name in ('loaded', 'shown', 'closed'):
            getattr(window.events, name).__iadd__(lambda *args, label=name: trace('event:' + label))
    try:
        timeout_seconds = min(900, max(5, int(os.environ.get('MDPREVIEW_HEADLESS_TIMEOUT', '90'))))
    except ValueError:
        timeout_seconds = 90

    def watchdog():
        if not done.wait(timeout_seconds):
            print('headless: timeout', file=sys.stderr)
            finish(False)
    threading.Thread(target=watchdog, daemon=True).start()
    webview.start(debug=False)
    return result['code']
