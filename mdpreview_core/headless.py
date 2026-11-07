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
    target = Path(os.path.abspath(target))
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
        def get_initial_content(self):
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
    url = Path(resource_path('index.html')).as_uri() + '?headless=1'
    window = webview.create_window('mdPreview export', url=url, js_api=ExportAPI(), hidden=True,
                                  width=900, height=680, confirm_close=False)
    api.window = window
    def watchdog():
        if not done.wait(180):
            print('headless: timeout', file=sys.stderr)
            finish(False)
    threading.Thread(target=watchdog, daemon=True).start()
    webview.start(debug=False)
    return result['code']
