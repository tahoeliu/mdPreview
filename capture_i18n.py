"""主应用和捕获功能共享的中英文文案；不依赖 AppKit 或主线程。"""

import os
import re
import sys


def _preferred_language(languages):
    if isinstance(languages, str):
        languages = [languages]
    for language in languages or ():
        if isinstance(language, str) and language.strip():
            return language.strip()
    return None


def is_chinese_locale():
    """优先 AppleLanguages、preferredLanguages，再回退到环境变量。"""
    if sys.platform == "darwin":
        pool = None
        try:
            import Foundation
            # WebView/转换工作线程也会调用；不要求 AppKit 或已有自动释放池。
            pool = Foundation.NSAutoreleasePool.alloc().init()
            try:
                language = _preferred_language(
                    Foundation.NSUserDefaults.standardUserDefaults().objectForKey_("AppleLanguages"))
            except Exception:
                language = None
            if not language:
                try:
                    language = _preferred_language(Foundation.NSLocale.preferredLanguages())
                except Exception:
                    language = None
            if language:
                return language.lower().startswith("zh")
        except Exception:
            # 纯 Python 测试或 Foundation 不可用时仍可使用捕获核心。
            pass
        finally:
            if pool is not None:
                # PyObjC owns this alloc/init proxy and releases it on deletion.
                # Calling drain() as well causes a second release on deallocation.
                del pool
    language = (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES")
                or os.environ.get("LANG", ""))
    return language.strip().lower().startswith("zh")


def t(en, zh):
    """按与主应用相同的系统语言选择文案，中文之外使用英文。"""
    return zh if is_chinese_locale() else en


# 精确匹配，不对子串作全局替换。动态参数在翻译模板之后插入。
_TRANSLATIONS = {
    "空格": "Space",
    "录入快捷键": "Record Shortcut",
    "未知键 ({})": "Unknown Key ({})",
    "暂不支持此按键，请使用字母、数字、方向键、空格或 F1–F20。": "Use a letter, number, arrow key, Space, or F1–F20.",
    "请搭配 Control、Option 或 Command；不能仅使用字母或 Shift。": "Include Control, Option, or Command; a letter or Shift alone is not allowed.",
    "Command＋Q 相关组合用于退出、锁屏或注销，请选择其他按键。": "Command+Q combinations are reserved for quitting, locking, or logging out. Choose another key.",
    "此组合常用于系统或编辑操作，请添加 Control 或选择其他按键。": "This combination is used for system or editing actions. Add Control or choose another key.",
    "Control＋空格用于切换输入法，请选择其他组合。": "Control+Space switches input sources. Choose another combination.",
    "请按": "Press",
    "设置立即生效；录入快捷键期间会暂停捕获。": "Changes apply immediately; capture pauses while recording a shortcut.",
    "粘贴并存为MD": "Paste as .MD",
    "用一个快捷键，将剪贴板内容保存为 Markdown 文件。": "Save clipboard content as Markdown with a shortcut.",
    "开启此功能": "Enable Capture",
    "通过全局快捷键快速保存": "Save quickly with a global shortcut",
    "文件自动保存路径": "Save Folder",
    "请选择保存文件夹": "Choose a save folder",
    "选择…": "Choose…",
    "自动复制新文件地址": "Copy File Path",
    "保存成功后，复制文件的完整路径": "Copy the full path after saving",
    "快捷键": "Shortcut",
    "录入保存快捷键": "Record Save Shortcut",
    "点击后按组合键；Esc 取消，Delete 清除。字母按美式键位显示。": "Click and press a shortcut. Esc cancels; Delete clears. Letters use the US keyboard layout.",
    "恢复默认": "Restore Default",
    "恢复为 Control＋Command＋V（⌃⌘V）": "Restore Control+Command+V (⌃⌘V)",
    "Esc 取消录入 · Delete 清除 · 默认 ⌃⌘V": "Esc cancels · Delete clears · Default ⌃⌘V",
    "设置未保存：{}": "Settings not saved: {}",
    "设置已保存。": "Settings saved.",
    "设置未保存，请重试。": "Settings not saved. Please try again.",
    "选择文件夹": "Choose Folder",
    "选择 Markdown 文件的自动保存位置": "Choose where to automatically save Markdown files",
    "无法开始录入：{}": "Cannot start recording: {}",
    "无法获得键盘焦点，请重新点击录入。": "Cannot focus the shortcut field. Click to record again.",
    "请按快捷键 …": "Press a shortcut …",
    "请按组合键；Esc 取消，Delete 清除。字母按美式键位显示。": "Press a shortcut. Esc cancels; Delete clears. Letters use the US keyboard layout.",
    "恢复快捷键失败：{}": "Failed to restore shortcut: {}",
    "已取消录入，保留原快捷键。": "Recording cancelled. Original shortcut kept.",
    "仅在 mdPreview 运行时生效。保存成功后可自动复制文件路径。": "Works only while mdPreview is running. File paths can be copied automatically after saving.",
    "功能未启用：": "Capture not enabled: ",
    "未保存更改：": "Changes not saved: ",
    "已保存。": "Saved.",
    "快捷键已清除，当前不会触发保存。": "Shortcut cleared. Shortcut capture is inactive.",
    "读取剪贴板失败：": "Failed to read clipboard: ",
    "这份剪贴板内容已保存，请先复制新内容。": "This clipboard content has already been saved. Copy new content first.",
    "转换引擎尚未就绪，请稍后重试。": "The conversion engine is not ready. Try again shortly.",
    "剪贴板正在变化，请重试。": "The clipboard is changing. Please try again.",
    "剪贴板中没有可转换的文字。": "The clipboard contains no text to convert.",
    "剪贴板内容超过 16 MB，未保存。": "Clipboard content exceeds 16 MB. Nothing was saved.",
    "转换超时，未创建文件": "Conversion timed out. No file was created",
    "转换失败，未创建文件": "Conversion failed. No file was created",
    "设置已变化，本次保存已取消。": "Settings changed. This save was cancelled.",
    "已保存：": "Saved: ",
    "文件已保存，但路径未复制。": "File saved, but its path was not copied.",
    "已保存，文件路径已复制。": "Saved. File path copied.",
    "mdPaste 已捕获，路径已复制": "mdPaste captured, path copied",
    "文件已保存；检测到新复制内容，未覆盖剪贴板。": "File saved. New clipboard content detected; clipboard left unchanged.",
    " 来源含不支持的格式，请检查文件内容。": " The source contains unsupported formatting. Please check the file content.",
    "未完成保存：": "Save did not complete: ",
    "不支持的 keycode；请选择字母、数字、空格、方向键或 F1–F20": "Unsupported keycode; choose a letter, number, Space, arrow key, or F1–F20",
    "modifiers 必须为 Carbon Command/Control/Option/Shift 修饰位": "modifiers must use Carbon Command/Control/Option/Shift flags",
    "快捷键必须包含 Command、Control 或 Option": "The shortcut must include Command, Control, or Option",
    "禁止 Command+Q 相关退出、注销或锁屏组合": "Command+Q combinations for quitting, logging out, or locking are not allowed",
    "此组合保留给系统或常见编辑操作，请添加 Control 或更换按键": "This combination is reserved for system or common editing actions; add Control or choose another key",
    "此组合保留给系统截图或录屏": "This combination is reserved for system screenshots or screen recording",
    "Control+空格保留给输入法切换": "Control+Space is reserved for switching input sources",
    "Control+方向键保留给系统桌面或窗口切换": "Control+arrow keys are reserved for switching desktops or windows",
    "capture.json 必须包含 JSON 对象": "capture.json must contain a JSON object",
    "未知捕获配置字段：": "Unknown capture settings fields: ",
    " 必须为布尔值": " must be a boolean",
    "directory 必须为非空目录路径": "directory must be a non-empty folder path",
    "清除快捷键时 modifiers 必须为 0": "modifiers must be 0 when clearing the shortcut",
    "capture.json 必须为普通文件": "capture.json must be a regular file",
    "capture.json 超过 64 KiB 限制": "capture.json exceeds the 64 KiB limit",
    "配置目录路径过长": "The configured folder path is too long",
    "content 必须为字符串": "content must be a string",
    "Markdown 内容超过 16 MiB UTF-8 限制": "Markdown content exceeds the 16 MiB UTF-8 limit",
    "Markdown 内容不能为空或纯空白": "Markdown content cannot be empty or whitespace only",
    "now 必须为 datetime.datetime": "now must be a datetime.datetime",
    "directory 不能为空": "directory cannot be empty",
    "callback 必须可调用": "callback must be callable",
    "CarbonHotKey 必须在主线程操作": "CarbonHotKey must be used on the main thread",
    "CarbonHotKey 已关闭": "CarbonHotKey is closed",
    "{} 失败，OSStatus={}": "{} failed, OSStatus={}",
    "Carbon 全局热键仅支持 macOS": "Carbon global hotkeys are only supported on macOS",
    "无法加载 HIToolbox：": "Unable to load HIToolbox: ",
    "GetApplicationEventTarget 返回空目标": "GetApplicationEventTarget returned a null target",
    "捕获热键回调失败": "Capture hotkey callback failed",
    "进程热键标识已耗尽，请重启应用": "Process hotkey IDs exhausted; restart the application",
    "移除旧热键失败 OSStatus={}；回滚新热键失败 OSStatus={}，请 close() 清理": "Failed to remove old hotkey OSStatus={}; failed to roll back new hotkey OSStatus={}; use close() to clean up",
    "UnregisterEventHotKey（保留旧热键）": "UnregisterEventHotKey (old hotkey retained)",
}

_ERROR_PREFIXES = {
    "功能未启用：": "Capture not enabled: ",
    "未保存更改：": "Changes not saved: ",
    "读取剪贴板失败：": "Failed to read clipboard: ",
    "未完成保存：": "Save did not complete: ",
    "设置未保存：": "Settings not saved: ",
    "无法开始录入：": "Cannot start recording: ",
    "恢复快捷键失败：": "Failed to restore shortcut: ",
    "无法加载 HIToolbox：": "Unable to load HIToolbox: ",
}


def _localize_english(text):
    if text in _TRANSLATIONS:
        return _TRANSLATIONS[text]
    for prefix, translated in _ERROR_PREFIXES.items():
        if text.startswith(prefix):
            return translated + _localize_english(text[len(prefix):])
    # 文件名和未知配置字段是原始数据，前缀之后的内容绝不递归翻译。
    for prefix in ("已保存：", "未知捕获配置字段："):
        if text.startswith(prefix):
            return _TRANSLATIONS[prefix] + text[len(prefix):]
    for field in ("enabled", "copy_path"):
        if text == field + " 必须为布尔值":
            return field + _TRANSLATIONS[" 必须为布尔值"]
    match = re.fullmatch(r"未知键 \((-?\d+)\)", text)
    if match:
        return _TRANSLATIONS["未知键 ({})"].format(match[1])
    if re.fullmatch(r"[⌃⌥⇧⌘]*空格", text):
        return text[:-2] + "Space"
    if text == "请按 …":
        return "Press …"
    match = re.fullmatch(r"(\w+(?:（保留旧热键）)?) 失败，OSStatus=(-?\d+)", text)
    if match:
        return _TRANSLATIONS["{} 失败，OSStatus={}"].format(_localize_english(match[1]), match[2])
    match = re.fullmatch(r"移除旧热键失败 OSStatus=(-?\d+)；回滚新热键失败 OSStatus=(-?\d+)，请 close\(\) 清理", text)
    if match:
        return _TRANSLATIONS["移除旧热键失败 OSStatus={}；回滚新热键失败 OSStatus={}，请 close() 清理"].format(*match.groups())
    quality = " 来源含不支持的格式，请检查文件内容。"
    if text.endswith(quality) and text[:-len(quality)] in _TRANSLATIONS:
        return _TRANSLATIONS[text[:-len(quality)]] + _TRANSLATIONS[quality]
    return text


def localize(text):
    """翻译已知中文 UI 文案、模板及带动态错误的前缀；未知内容原样返回。

    用于 panel 的标题、状态、错误和提示，不用于路径控件的实际数据。
    `已保存：` 后的文件名保持原样；优先 localize(模板).format(动态参数)，
    以避免将路径或实际文件名当成待翻译文案。中文环境始终返回原文。
    """
    return text if is_chinese_locale() else _localize_english(text)
