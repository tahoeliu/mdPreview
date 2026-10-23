"""Application-scoped capture. UI/pasteboard on main thread, conversion off-thread."""
import json
import os
import threading
import time
from capture_core import CaptureSettings, CarbonHotKey, save_markdown, MAX_CONTENT_BYTES
from capture_i18n import localize


class CaptureController:
    def __init__(self, settings_path, get_context, quitting, pasteboard=None, schedule=None):
        from AppKit import NSPasteboard
        from PyObjCTools import AppHelper
        self.store = CaptureSettings(settings_path)
        self.get_context = get_context
        self.quitting = quitting
        self.pb = pasteboard or NSPasteboard.generalPasteboard()
        self.schedule = schedule or AppHelper.callAfter
        self.hotkey = CarbonHotKey(self.trigger)
        self.panel = None
        self.recording = False
        self.busy = False
        self.generation = 0
        self.last_trigger = 0
        self.last_captured_change = None
        self.last_output_change = None
        self.last_message = localize('仅在 mdPreview 运行时生效。保存成功后可自动复制文件路径。')
        try:
            self.settings = self.store.load()
            self._activate(self.settings)
        except Exception as exc:
            self.settings = CaptureSettings(os.path.join(os.path.dirname(settings_path), '.missing-defaults')).load()
            self.last_message = localize('功能未启用：' + str(exc))

    def _activate(self, settings):
        if settings['enabled'] and settings['keycode'] is not None:
            self.hotkey.set(settings['keycode'], settings['modifiers'])
            self.hotkey.resume()
        else:
            self.hotkey.suspend()

    def update_settings(self, changes):
        old = dict(self.settings)
        new = dict(old, **changes)
        try:
            from capture_core import _settings_values
            new = _settings_values(new)
            # Even during recording, registration must succeed BEFORE persistence.
            self._activate(new)
            os.makedirs(self.store.path.parent, exist_ok=True)
            self.store.save(new)
        except Exception as exc:
            try:
                self._activate(old)
                if self.recording:
                    self.hotkey.suspend()
            except Exception:
                self.hotkey.suspend()
            return False, localize('未保存更改：' + str(exc))
        self.settings = new
        self.generation += 1
        if self.recording:
            self.hotkey.suspend()
        return True, localize('已保存。' if new['keycode'] is not None else '快捷键已清除，当前不会触发保存。')

    def begin_recording(self):
        self.hotkey.suspend()
        self.recording = True

    def end_recording(self):
        self.recording = False
        self._activate(self.settings)

    def show(self):
        if self.panel is None:
            from capture_panel import CapturePanel
            self.panel = CapturePanel(self)
            self.panel.set_status(self.last_message)
        self.panel.show()

    def notify(self, message, error=False):
        message = localize(message)
        self.last_message = message
        if self.panel:
            self.panel.set_status(message, error)
        # Non-activating native HUD; never focuses or changes an editor document.
        try:
            from capture_panel import show_capture_hud
            show_capture_hud(message, error)
        except Exception:
            pass

    def trigger(self):
        try:
            self._trigger()
        except Exception as exc:
            self._failed('读取剪贴板失败：' + str(exc))

    def _trigger(self):
        if self.quitting() or self.recording or self.busy or not self.settings['enabled']:
            return
        now = time.monotonic()
        if now - self.last_trigger < .7:
            return
        self.last_trigger = now
        change = int(self.pb.changeCount())
        if change in (self.last_output_change, self.last_captured_change):
            self.notify('这份剪贴板内容已保存，请先复制新内容。')
            return
        context = self.get_context()
        if not context:
            self.notify('转换引擎尚未就绪，请稍后重试。', True)
            return
        window, api = context
        clip = api.read_clipboard()
        if int(self.pb.changeCount()) != change:
            self.notify('剪贴板正在变化，请重试。', True)
            return
        if not clip or clip.get('format') == 'none' or not clip.get('content', '').strip():
            self.notify('剪贴板中没有可转换的文字。', True)
            return
        if len(clip['content'].encode('utf-8')) > MAX_CONTENT_BYTES:
            self.notify('剪贴板内容超过 16 MB，未保存。', True)
            return
        self.busy = True
        generation = self.generation
        settings = dict(self.settings)
        def worker():
            result = {}
            event = threading.Event()
            def converted(value):
                result['value'] = value
                event.set()
            try:
                script = 'window.convertClipboardToMarkdown(' + json.dumps(clip, ensure_ascii=True) + ')'
                window.evaluate_js(script, callback=converted)
                if not event.wait(12):
                    raise RuntimeError('转换超时，未创建文件')
                value = result.get('value')
                if not isinstance(value, dict) or not isinstance(value.get('markdown'), str):
                    raise RuntimeError('转换失败，未创建文件')
                self.schedule(self._commit, value, settings, generation, change)
            except Exception as exc:
                self.schedule(self._failed, str(exc))
        threading.Thread(target=worker, daemon=True, name='md-capture').start()

    def _failed(self, message):
        self.busy = False
        self.notify(message, True)

    def _commit(self, value, settings, generation, change):
        try:
            if self.quitting() or generation != self.generation or self.recording:
                self.notify('设置已变化，本次保存已取消。')
                return
            path = save_markdown(settings['directory'], value['markdown'])
            self.last_captured_change = change
            message = localize('已保存：') + os.path.basename(path)
            if settings['copy_path']:
                if int(self.pb.changeCount()) == change:
                    self.pb.clearContents()
                    if not self.pb.setString_forType_(path, 'public.utf8-plain-text'):
                        self.notify('文件已保存，但路径未复制。', True)
                        return
                    self.last_output_change = int(self.pb.changeCount())
                    message = 'mdPaste 已捕获，路径已复制'
                else:
                    message = '文件已保存；检测到新复制内容，未覆盖剪贴板。'
            message = localize(message)
            if value.get('quality'):
                message += localize(' 来源含不支持的格式，请检查文件内容。')
            self.notify(message)
        except Exception as exc:
            self.notify('未完成保存：' + str(exc), True)
        finally:
            self.busy = False

    def close(self):
        self.generation += 1
        self.hotkey.close()
