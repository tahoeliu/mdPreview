"""独立捕获核心；不读取剪贴板，不在导入或构造时注册全局热键。"""

import ctypes
import datetime
import itertools
import json
import logging
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile
import threading
from capture_i18n import localize


MAX_CONTENT_BYTES = 16 * 1024 * 1024
MAX_SETTINGS_BYTES = 64 * 1024
CMD, SHIFT, OPTION, CTRL = 256, 512, 2048, 4096
SUPPORTED_KEYCODES = frozenset({
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17,
    18, 19, 20, 21, 22, 23, 25, 26, 28, 29, 31, 32, 34, 35, 37,
    38, 40, 45, 46, 49, 64, 79, 80, 90, 96, 97, 98, 99, 100,
    101, 103, 105, 106, 107, 109, 111, 113, 118, 120, 122,
    123, 124, 125, 126,
})


def validate_shortcut(keycode, modifiers):
    """校验 Carbon 虚拟键码/修饰位；成功返回 True，失败抛 ValueError。

    仅支持字母、数字、空格、方向键及 F1–F20；包括功能键在内，
    必须含 Command、Control、Option 之一。不接受 Cocoa 修饰位。
    系统自定义快捷键的冲突最终由 RegisterEventHotKey 报告。
    """
    if type(keycode) is not int or keycode not in SUPPORTED_KEYCODES:
        raise ValueError(localize("不支持的 keycode；请选择字母、数字、空格、方向键或 F1–F20"))
    if (type(modifiers) is not int or modifiers < 0
            or modifiers & ~(CMD | CTRL | OPTION | SHIFT)):
        raise ValueError(localize("modifiers 必须为 Carbon Command/Control/Option/Shift 修饰位"))
    if not modifiers & (CMD | CTRL | OPTION):
        raise ValueError(localize("快捷键必须包含 Command、Control 或 Option"))
    if keycode == 12 and modifiers & CMD:
        raise ValueError(localize("禁止 Command+Q 相关退出、注销或锁屏组合"))
    if modifiers & CMD and not modifiers & CTRL:
        if keycode in (0, 6, 7, 8, 9, 13, 4, 46, 49):
            raise ValueError(localize("此组合保留给系统或常见编辑操作，请添加 Control 或更换按键"))
    if modifiers & CMD and modifiers & SHIFT and keycode in (20, 21, 23, 26):
        raise ValueError(localize("此组合保留给系统截图或录屏"))
    if keycode == 49 and modifiers & CTRL and not modifiers & (CMD | OPTION):
        raise ValueError(localize("Control+空格保留给输入法切换"))
    if keycode in (123, 124, 125, 126) and modifiers & CTRL and not modifiers & (CMD | OPTION):
        raise ValueError(localize("Control+方向键保留给系统桌面或窗口切换"))
    return True


def _settings_values(values):
    if not isinstance(values, dict):
        raise ValueError(localize("capture.json 必须包含 JSON 对象"))
    result = {
        "enabled": False, "directory": str(Path.home() / "Desktop"),
        "copy_path": True, "keycode": 9, "modifiers": 4352,
    }
    unknown = values.keys() - result.keys()
    if unknown:
        raise ValueError(localize("未知捕获配置字段：") + ", ".join(map(str, unknown)))
    result.update(values)
    for field in ("enabled", "copy_path"):
        if type(result[field]) is not bool:
            raise ValueError(field + localize(" 必须为布尔值"))
    directory = result["directory"]
    if not isinstance(directory, str) or not directory.strip() or "\0" in directory:
        raise ValueError(localize("directory 必须为非空目录路径"))
    if result["keycode"] is None:
        if result["modifiers"] != 0:
            raise ValueError(localize("清除快捷键时 modifiers 必须为 0"))
    else:
        validate_shortcut(result["keycode"], result["modifiers"])
    return result


class CaptureSettings:
    """path 为独立配置文件路径，建议命名 capture.json，不是目录。

    load() 返回完整配置 dict；文件不存在时返回默认值，不写入文件。
    save(values) 校验并原子替换配置，返回完整 dict；缺省字段使用默认值。
    不创建父目录；JSON、编码、校验、权限和 I/O 错误均向调用方传播。
    """

    def __init__(self, path):
        self.path = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))

    def load(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return _settings_values({})
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError(localize("capture.json 必须为普通文件"))
            data = stream.read(MAX_SETTINGS_BYTES + 1)
        if len(data) > MAX_SETTINGS_BYTES:
            raise ValueError(localize("capture.json 超过 64 KiB 限制"))
        return _settings_values(json.loads(data.decode("utf-8")))

    def save(self, values):
        result = _settings_values(values)
        # 在 JSON 编码前限制输入，避免不受控的字符串扩容。
        if len(result["directory"]) > MAX_SETTINGS_BYTES:
            raise ValueError(localize("配置目录路径过长"))
        data = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(data) > MAX_SETTINGS_BYTES:
            raise ValueError(localize("capture.json 超过 64 KiB 限制"))
        fd, temporary = tempfile.mkstemp(prefix=".capture-settings-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.lexists(temporary):
                os.unlink(temporary)
        return result


def save_markdown(directory, content, now=None):
    """返回已发布文件的绝对路径 str；now 可注入 datetime.datetime。

    UTF-8 内容上限 16 MiB，分块编码；空字符串/纯空白拒绝。
    选定目录先严格 resolve，再以目录 fd 固定写入目标，不创建目录。
    临时文件完整写入并 fsync 后通过硬链接发布，所有已有文件及软链
    均视为名称冲突（-2、-3…），绝不 replace 已存在的目标。
    """
    if not isinstance(content, str):
        raise TypeError(localize("content 必须为字符串"))
    if len(content) > MAX_CONTENT_BYTES:
        raise ValueError(localize("Markdown 内容超过 16 MiB UTF-8 限制"))
    if not content or content.isspace():
        raise ValueError(localize("Markdown 内容不能为空或纯空白"))
    if now is None:
        now = datetime.datetime.now()
    if not isinstance(now, datetime.datetime):
        raise TypeError(localize("now 必须为 datetime.datetime"))
    if not os.fspath(directory):
        raise ValueError(localize("directory 不能为空"))
    resolved = Path(directory).expanduser().resolve(strict=True)
    directory_fd = os.open(resolved, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = None
    try:
        while True:
            candidate = ".capture-" + secrets.token_hex(16) + ".tmp"
            try:
                fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory_fd)
            except FileExistsError:
                continue
            temporary = candidate
            break
        with os.fdopen(fd, "wb") as stream:
            size = 0
            for offset in range(0, len(content), 65536):
                chunk = content[offset:offset + 65536].encode("utf-8")
                size += len(chunk)
                if size > MAX_CONTENT_BYTES:
                    raise ValueError(localize("Markdown 内容超过 16 MiB UTF-8 限制"))
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        stem = "mdPaste-" + now.strftime("%m%d-%H%M%S")
        index = 1
        while True:
            filename = stem + ("" if index == 1 else "-" + str(index)) + ".md"
            try:
                os.link(temporary, filename, src_dir_fd=directory_fd,
                        dst_dir_fd=directory_fd, follow_symlinks=False)
            except FileExistsError:
                index += 1
                continue
            return str(resolved / filename)
    finally:
        try:
            if temporary is not None:
                os.unlink(temporary, dir_fd=directory_fd)
        finally:
            os.close(directory_fd)


class HotKeyError(RuntimeError):
    """Carbon 热键错误（包含操作名及 OSStatus）。"""


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


_EventHandler = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_KEYBOARD = int.from_bytes(b"keyb", "big")
_SIGNATURE = int.from_bytes(b"mdCp", "big")
_RELEASED = 6
_NOT_HANDLED = -9874
# handler 未成功移除之前强引用实例，防止 C 调用已释放的 Python 回调。
_LIVE_HOTKEYS = set()
_HOTKEY_IDS = itertools.count(1)


class CarbonHotKey:
    """主线程接口，需由宿主运行 macOS 应用事件循环。

    构造只保存 callback；set(keycode, modifiers) 成功返回 True，失败抛错。
    相同组合不重复注册；更换组合先注册新键，成功后才解除旧键。
    suspend() 解除注册但保留期望组合，resume() 重新注册，均幂等。
    暂停期间 set() 只更新期望组合。close() 幂等、终止使用并释放 handler；
    释放失败抛错且保留引用，可再次 close()。应显式 close()，不依赖析构。
    callback 无参数，仅响应 hotkeyReleased；异常保存在 last_callback_error
    并记录日志，绝不会跨越 C ABI。不会自动切线程。
    """

    def __init__(self, callback):
        if not callable(callback):
            raise TypeError(localize("callback 必须可调用"))
        self.callback = callback
        self.last_callback_error = None
        self._lib = None
        self._target = None
        self._handler_ref = ctypes.c_void_p()
        self._handler_callback = _EventHandler(self._dispatch)
        self._refs = {}
        self._active_id = None
        self._shortcut = None
        self._suspended = False
        self._closed = False

    def _check(self):
        if threading.current_thread() is not threading.main_thread():
            raise HotKeyError(localize("CarbonHotKey 必须在主线程操作"))
        if self._closed:
            raise HotKeyError(localize("CarbonHotKey 已关闭"))

    @staticmethod
    def _status(operation, status):
        if status != 0:
            raise HotKeyError(localize("{} 失败，OSStatus={}").format(operation, status))

    def _ensure_handler(self):
        if self._handler_ref.value:
            return
        if self._lib is None:
            if sys.platform != "darwin":
                raise HotKeyError(localize("Carbon 全局热键仅支持 macOS"))
            try:
                self._lib = ctypes.CDLL(
                    "/System/Library/Frameworks/Carbon.framework/Frameworks/HIToolbox.framework/HIToolbox")
                void = ctypes.c_void_p
                uint = ctypes.c_uint32
                signatures = {
                    "GetApplicationEventTarget": (void, []),
                    "RegisterEventHotKey": (ctypes.c_int32, [uint, uint, _EventHotKeyID, void, uint, ctypes.POINTER(void)]),
                    "UnregisterEventHotKey": (ctypes.c_int32, [void]),
                    "InstallEventHandler": (ctypes.c_int32, [void, _EventHandler, uint, ctypes.POINTER(_EventTypeSpec), void, ctypes.POINTER(void)]),
                    "RemoveEventHandler": (ctypes.c_int32, [void]),
                    "GetEventParameter": (ctypes.c_int32, [void, uint, uint, ctypes.POINTER(uint), uint, ctypes.POINTER(uint), void]),
                }
                for name, (restype, argtypes) in signatures.items():
                    function = getattr(self._lib, name)
                    function.restype = restype
                    function.argtypes = argtypes
            except (OSError, AttributeError) as error:
                self._lib = None
                raise HotKeyError(localize("无法加载 HIToolbox：") + str(error)) from error
        self._target = self._lib.GetApplicationEventTarget()
        if not self._target:
            raise HotKeyError(localize("GetApplicationEventTarget 返回空目标"))
        event_type = _EventTypeSpec(_KEYBOARD, _RELEASED)
        self._status("InstallEventHandler", self._lib.InstallEventHandler(
            self._target, self._handler_callback, 1, ctypes.byref(event_type),
            None, ctypes.byref(self._handler_ref)))
        _LIVE_HOTKEYS.add(self)

    def _dispatch(self, call_ref, event, user_data):
        try:
            identifier = _EventHotKeyID()
            status = self._lib.GetEventParameter(
                event, int.from_bytes(b"----", "big"), int.from_bytes(b"hkid", "big"),
                None, ctypes.sizeof(identifier), None, ctypes.byref(identifier))
            if status != 0:
                self._status("GetEventParameter", status)
            if (self._closed or self._suspended or identifier.signature != _SIGNATURE
                    or identifier.id != self._active_id):
                return _NOT_HANDLED
            self.callback()
            return 0
        except BaseException as error:
            self.last_callback_error = error
            try:
                logging.getLogger(__name__).exception(localize("捕获热键回调失败"))
            except BaseException:
                # 即使日志处理器自身出错，也不得让异常跨越 C ABI。
                pass
            return _NOT_HANDLED

    def set(self, keycode, modifiers):
        self._check()
        validate_shortcut(keycode, modifiers)
        shortcut = (keycode, modifiers)
        if self._suspended:
            self._shortcut = shortcut
            return True
        if self._active_id is not None and self._shortcut == shortcut:
            return True
        self._ensure_handler()
        identifier = next(_HOTKEY_IDS)
        if identifier > 0xFFFFFFFF:
            raise HotKeyError(localize("进程热键标识已耗尽，请重启应用"))
        reference = ctypes.c_void_p()
        self._status("RegisterEventHotKey", self._lib.RegisterEventHotKey(
            keycode, modifiers, _EventHotKeyID(_SIGNATURE, identifier), self._target,
            0, ctypes.byref(reference)))
        self._refs[identifier] = reference
        if self._active_id is not None:
            old = self._active_id
            status = self._lib.UnregisterEventHotKey(self._refs[old])
            if status != 0:
                rollback = self._lib.UnregisterEventHotKey(reference)
                if rollback == 0:
                    del self._refs[identifier]
                else:
                    raise HotKeyError(localize("移除旧热键失败 OSStatus={}；回滚新热键失败 OSStatus={}，请 close() 清理").format(status, rollback))
                self._status(localize("UnregisterEventHotKey（保留旧热键）"), status)
            del self._refs[old]
        self._active_id = identifier
        self._shortcut = shortcut
        return True

    def suspend(self):
        self._check()
        if self._suspended:
            return
        # 包括此前回滚失败留下的引用；任何失败都保留可重试的状态。
        for identifier, reference in list(self._refs.items()):
            self._status("UnregisterEventHotKey", self._lib.UnregisterEventHotKey(reference))
            del self._refs[identifier]
            if identifier == self._active_id:
                self._active_id = None
        self._suspended = True

    def resume(self):
        self._check()
        if not self._suspended:
            return True
        self._suspended = False
        try:
            if self._shortcut is not None:
                return self.set(*self._shortcut)
            return True
        except BaseException:
            self._suspended = True
            raise

    def close(self):
        if threading.current_thread() is not threading.main_thread():
            raise HotKeyError(localize("CarbonHotKey 必须在主线程操作"))
        if self._closed:
            return
        self.suspend()
        if self._handler_ref.value:
            self._status("RemoveEventHandler", self._lib.RemoveEventHandler(self._handler_ref))
            self._handler_ref = ctypes.c_void_p()
        self._closed = True
        _LIVE_HOTKEYS.discard(self)
