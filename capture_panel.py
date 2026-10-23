"""AppKit 原生的「粘贴并存为MD」设置面板；所有副作用均交给 controller。"""

import weakref

import objc
import AppKit as AK
from Foundation import NSObject, NSThread, NSURL
from PyObjCTools import AppHelper
from capture_i18n import t, localize


_CMD, _CTRL, _OPTION, _SHIFT = 256, 4096, 2048, 512
_DEFAULT = {"keycode": 9, "modifiers": _CTRL | _CMD}
_KEYS = {
    0: "A", 1: "S", 2: "D", 3: "F", 4: "H", 5: "G", 6: "Z",
    7: "X", 8: "C", 9: "V", 11: "B", 12: "Q", 13: "W", 14: "E",
    15: "R", 16: "Y", 17: "T", 18: "1", 19: "2", 20: "3",
    21: "4", 22: "6", 23: "5", 25: "9", 26: "7", 28: "8",
    29: "0", 31: "O", 32: "U", 34: "I", 35: "P", 37: "L",
    38: "J", 40: "K", 45: "N", 46: "M", 49: "空格",
    122: "F1", 120: "F2", 99: "F3", 118: "F4", 96: "F5",
    97: "F6", 98: "F7", 100: "F8", 101: "F9", 109: "F10",
    103: "F11", 111: "F12", 105: "F13", 107: "F14", 113: "F15",
    106: "F16", 64: "F17", 79: "F18", 80: "F19", 90: "F20",
    123: "←", 124: "→", 125: "↓", 126: "↑",
}
_FUNCTION_KEYS = {code for code, title in _KEYS.items() if title.startswith("F") and len(title) > 1}
_MODIFIER_FLAGS = (
    (AK.NSEventModifierFlagControl, _CTRL, "⌃"),
    (AK.NSEventModifierFlagOption, _OPTION, "⌥"),
    (AK.NSEventModifierFlagShift, _SHIFT, "⇧"),
    (AK.NSEventModifierFlagCommand, _CMD, "⌘"),
)


def _on_main(function, *args):
    if NSThread.isMainThread():
        function(*args)
    else:
        AppHelper.callAfter(function, *args)


def _carbon_modifiers(flags):
    return sum(carbon for cocoa, carbon, _ in _MODIFIER_FLAGS if flags & cocoa)


def _symbols(modifiers):
    return "".join(symbol for _, carbon, symbol in _MODIFIER_FLAGS if modifiers & carbon)


def _shortcut_title(keycode, modifiers):
    if keycode is None:
        return "录入快捷键"
    return _symbols(modifiers) + _KEYS.get(keycode, "未知键 ({})".format(keycode))


def _validation_error(keycode, modifiers):
    from capture_core import validate_shortcut
    try:
        validate_shortcut(keycode, modifiers)
    except ValueError as exc:
        return str(exc)
    if keycode not in _KEYS:
        return "暂不支持此按键，请使用字母、数字、方向键、空格或 F1–F20。"
    if keycode not in _FUNCTION_KEYS and not modifiers & (_CMD | _CTRL | _OPTION):
        return "请搭配 Control、Option 或 Command；不能仅使用字母或 Shift。"
    if keycode == 12 and modifiers & _CMD:
        return "Command＋Q 相关组合用于退出、锁屏或注销，请选择其他按键。"
    # 保留系统与编辑操作；默认 ⌃⌘V 不在此限制内。
    if modifiers & _CMD and not modifiers & _CTRL:
        if keycode in (0, 6, 7, 8, 9, 12, 13, 4, 46, 49):
            return "此组合常用于系统或编辑操作，请添加 Control 或选择其他按键。"
    if keycode == 49 and modifiers & _CTRL and not modifiers & (_CMD | _OPTION):
        return "Control＋空格用于切换输入法，请选择其他组合。"
    return None


def _is_close_key(event):
    flags = event.modifierFlags() & (AK.NSEventModifierFlagCommand | AK.NSEventModifierFlagControl
                                    | AK.NSEventModifierFlagOption | AK.NSEventModifierFlagShift)
    return (event.type() == AK.NSEventTypeKeyDown and flags == AK.NSEventModifierFlagCommand
            and str(event.charactersIgnoringModifiers() or "").lower() == "w")


class _CaptureConfigWindow(AK.NSWindow):
    def performKeyEquivalent_(self, event):
        if _is_close_key(event):
            sheet = self.attachedSheet()
            if sheet is not None:
                sheet.cancel_(None)
            else:
                self.performClose_(None)
            return True
        return objc.super(_CaptureConfigWindow, self).performKeyEquivalent_(event)


def close_capture_config_if_active():
    """Route File > Close only when this configuration window owns keyboard focus."""
    key = AK.NSApplication.sharedApplication().keyWindow()
    if isinstance(key, _CaptureConfigWindow):
        sheet = key.attachedSheet()
        if sheet is not None:
            sheet.cancel_(None)
        else:
            key.performClose_(None)
        return True
    parent = key.sheetParent() if key is not None else None
    if isinstance(parent, _CaptureConfigWindow):
        key.cancel_(None)
        return True
    return False


class _CapturePanelTarget(NSObject):
    """仅在此代理上暴露 Objective-C action / delegate 选择器。"""

    @objc.python_method
    def bind(self, panel):
        self._panel_ref = weakref.ref(panel)
        return self

    @objc.python_method
    def panel(self):
        return self._panel_ref()

    def toggleEnabled_(self, sender):
        panel = self.panel()
        if panel is not None:
            panel._apply({"enabled": sender.state() == AK.NSControlStateValueOn})

    def toggleCopyPath_(self, sender):
        panel = self.panel()
        if panel is not None:
            panel._apply({"copy_path": sender.state() == AK.NSControlStateValueOn})

    def chooseDirectory_(self, sender):
        panel = self.panel()
        if panel is not None:
            panel._choose_directory()

    def recordShortcut_(self, sender):
        panel = self.panel()
        if panel is not None:
            panel._start_recording()

    def restoreDefault_(self, sender):
        panel = self.panel()
        if panel is not None:
            try:
                panel._apply(dict(_DEFAULT))
            finally:
                panel._stop_recording()

    def windowDidResignKey_(self, notification):
        panel = self.panel()
        if panel is not None:
            panel._stop_recording(cancelled=True)

    def windowWillClose_(self, notification):
        panel = self.panel()
        if panel is not None:
            panel._stop_recording(cancelled=True)
            if panel._directory_sheet is not None:
                panel._directory_sheet.cancel_(None)


class _CaptureShortcutButton(AK.NSButton):
    @objc.python_method
    def bind(self, panel):
        self._panel_ref = weakref.ref(panel)
        return self

    @objc.python_method
    def panel(self):
        return self._panel_ref()

    def acceptsFirstResponder(self):
        return True

    def resignFirstResponder(self):
        result = objc.super(_CaptureShortcutButton, self).resignFirstResponder()
        panel = self.panel()
        if result and panel is not None:
            panel._stop_recording(cancelled=True)
        return result

    def keyDown_(self, event):
        panel = self.panel()
        if panel is not None and panel._recording:
            panel._record_event(event)
        else:
            objc.super(_CaptureShortcutButton, self).keyDown_(event)

    def performKeyEquivalent_(self, event):
        panel = self.panel()
        if panel is not None and panel._recording and event.type() == AK.NSEventTypeKeyDown:
            panel._record_event(event)
            return True
        return objc.super(_CaptureShortcutButton, self).performKeyEquivalent_(event)

    def flagsChanged_(self, event):
        panel = self.panel()
        if panel is not None and panel._recording:
            self.setTitle_(localize((_symbols(_carbon_modifiers(event.modifierFlags())) or "请按") + " …"))
        else:
            objc.super(_CaptureShortcutButton, self).flagsChanged_(event)


class CapturePanel:
    """普通 Python 类。controller 提供 settings 及更新、暂停、恢复方法。

    show / refresh / set_status 可从任意线程调用，异步切回主线程。
    调用方应持有本对象；关闭窗口仅隐藏，show 可再次使用同一窗口。
    """

    @objc.python_method
    def __init__(self, controller):
        self.controller = controller
        self.window = None
        self._target = None
        self._recording = False
        self._directory_sheet = None
        self._status = ("设置立即生效；录入快捷键期间会暂停捕获。", False)

    @objc.python_method
    def show(self):
        _on_main(self._show)

    @objc.python_method
    def refresh(self):
        _on_main(self._refresh)

    @objc.python_method
    def set_status(self, text, error=False):
        _on_main(self._set_status, str(text), bool(error))

    @objc.python_method
    def _show(self):
        if self.window is None:
            self._build()
        self._refresh()
        self.window.makeKeyAndOrderFront_(None)
        AK.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    @objc.python_method
    def _label(self, parent, text, frame, size=13, secondary=False, weight=None):
        label = AK.NSTextField.labelWithString_(localize(text))
        label.setFrame_(frame)
        label.setFont_(AK.NSFont.systemFontOfSize_weight_(size, weight if weight is not None else AK.NSFontWeightRegular))
        label.setTextColor_(AK.NSColor.secondaryLabelColor() if secondary else AK.NSColor.labelColor())
        parent.addSubview_(label)
        return label

    @objc.python_method
    def _button(self, parent, title, frame, action, button_class=AK.NSButton):
        button = button_class.alloc().initWithFrame_(frame)
        button.setTitle_(localize(title))
        button.setBezelStyle_(AK.NSBezelStyleRounded)
        button.setFont_(AK.NSFont.systemFontOfSize_(13))
        button.setTarget_(self._target)
        button.setAction_(action)
        parent.addSubview_(button)
        return button

    @objc.python_method
    def _switch(self, parent, frame, label, action):
        switch = AK.NSSwitch.alloc().initWithFrame_(frame)
        switch.setTarget_(self._target)
        switch.setAction_(action)
        switch.setAccessibilityLabel_(localize(label))
        parent.addSubview_(switch)
        return switch

    @objc.python_method
    def _build(self):
        self._target = _CapturePanelTarget.alloc().init().bind(self)
        style = (AK.NSWindowStyleMaskTitled | AK.NSWindowStyleMaskClosable
                 | AK.NSWindowStyleMaskFullSizeContentView)
        window = _CaptureConfigWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            AK.NSMakeRect(0, 0, 600, 420), style, AK.NSBackingStoreBuffered, False
        )
        self.window = window
        window.setTitle_(t("Config Paste as .MD", "粘贴为MD配置"))
        window.setTitleVisibility_(AK.NSWindowTitleHidden)
        window.setTitlebarAppearsTransparent_(True)
        if hasattr(window, "setTitlebarSeparatorStyle_"):
            window.setTitlebarSeparatorStyle_(AK.NSTitlebarSeparatorStyleNone)
        # The requested white surface is intentional, including under dark macOS.
        window.setAppearance_(AK.NSAppearance.appearanceNamed_(AK.NSAppearanceNameAqua))
        window.setReleasedWhenClosed_(False)
        window.setDelegate_(self._target)
        window.setBackgroundColor_(AK.NSColor.whiteColor())
        window.center()
        root = window.contentView()
        root.setWantsLayer_(True)
        root.layer().setBackgroundColor_(AK.NSColor.whiteColor().CGColor())
        self._label(root, t("Config Paste as .MD", "粘贴为MD配置"),
                    AK.NSMakeRect(104, 385, 460, 21), 14, weight=AK.NSFontWeightSemibold)
        self._label(root, t("Save clipboard content as Markdown with a shortcut.",
                           "用快捷键，将剪贴板内容保存为 Markdown 文件。"),
                    AK.NSMakeRect(32, 337, 536, 20), 13, True)

        def card(y, height):
            view = AK.NSView.alloc().initWithFrame_(AK.NSMakeRect(28, y, 544, height))
            view.setWantsLayer_(True)
            view.layer().setCornerRadius_(10)
            view.layer().setBackgroundColor_(AK.NSColor.whiteColor().CGColor())
            view.layer().setBorderWidth_(0.5)
            view.layer().setBorderColor_(AK.NSColor.colorWithWhite_alpha_(0.88, 1).CGColor())
            root.addSubview_(view)
            return view

        enabled_group = card(259, 60)
        self._label(enabled_group, "开启此功能", AK.NSMakeRect(16, 22, 390, 19))
        self.enabled_switch = self._switch(enabled_group, AK.NSMakeRect(488, 17, 40, 26),
                                           "开启此功能", "toggleEnabled:")
        group = card(89, 158)
        for y in (53, 105):
            separator = AK.NSView.alloc().initWithFrame_(AK.NSMakeRect(16, y, 512, 0.5))
            separator.setWantsLayer_(True)
            separator.layer().setBackgroundColor_(AK.NSColor.colorWithWhite_alpha_(0.87, 1).CGColor())
            group.addSubview_(separator)

        self._label(group, "文件自动保存路径", AK.NSMakeRect(16, 122, 165, 19))
        self.path_control = AK.NSPathControl.alloc().initWithFrame_(AK.NSMakeRect(192, 120, 238, 24))
        self.path_control.setPathStyle_(AK.NSPathStylePopUp)
        self.path_control.setEditable_(False)
        self.path_control.setPlaceholderString_(localize("请选择保存文件夹"))
        self.path_control.setTarget_(self._target)
        self.path_control.setDoubleAction_("chooseDirectory:")
        self.path_control.setAccessibilityLabel_(localize("文件自动保存路径"))
        group.addSubview_(self.path_control)
        self.choose_button = self._button(group, "选择…", AK.NSMakeRect(438, 115, 92, 32), "chooseDirectory:")

        self._label(group, "自动复制新文件地址", AK.NSMakeRect(16, 76, 360, 19))
        self._label(group, "保存成功后，复制文件的完整路径", AK.NSMakeRect(16, 58, 430, 16), 11, True)
        self.copy_switch = self._switch(group, AK.NSMakeRect(488, 66, 40, 26),
                                        "自动复制新文件地址", "toggleCopyPath:")

        self._label(group, "快捷键", AK.NSMakeRect(16, 18, 165, 19))
        self.shortcut_button = self._button(group, "录入快捷键", AK.NSMakeRect(228, 10, 154, 32),
                                            "recordShortcut:", _CaptureShortcutButton).bind(self)
        self.shortcut_button.setFont_(AK.NSFont.systemFontOfSize_weight_(13, AK.NSFontWeightMedium))
        self.shortcut_button.setAccessibilityLabel_(localize("录入保存快捷键"))
        self.shortcut_button.setToolTip_(localize("点击后按组合键；Esc 取消，Delete 清除。字母按美式键位显示。"))
        self.default_button = self._button(group, "恢复默认", AK.NSMakeRect(389, 10, 141, 32), "restoreDefault:")
        self.default_button.setToolTip_(localize("恢复为 Control＋Command＋V（⌃⌘V）"))

        self.status_label = AK.NSTextField.wrappingLabelWithString_("")
        self.status_label.setFrame_(AK.NSMakeRect(32, 27, 536, 44))
        self.status_label.setFont_(AK.NSFont.systemFontOfSize_(11))
        root.addSubview_(self.status_label)
        controls = (self.enabled_switch, self.path_control, self.choose_button, self.copy_switch, self.shortcut_button, self.default_button)
        for current, following in zip(controls, controls[1:] + controls[:1]):
            current.setNextKeyView_(following)
        window.setInitialFirstResponder_(self.enabled_switch)
        self._set_status(*self._status)

    @objc.python_method
    def _refresh(self):
        if self.window is None:
            return
        settings = dict(self.controller.settings)
        self.enabled_switch.setState_(AK.NSControlStateValueOn if settings.get("enabled", False) else AK.NSControlStateValueOff)
        self.copy_switch.setState_(AK.NSControlStateValueOn if settings.get("copy_path", False) else AK.NSControlStateValueOff)
        directory = settings.get("directory", "")
        self.path_control.setURL_(NSURL.fileURLWithPath_isDirectory_(directory, True) if directory else None)
        self.path_control.setToolTip_(directory or localize("请选择保存文件夹"))
        if not self._recording:
            self.shortcut_button.setTitle_(localize(_shortcut_title(settings.get("keycode"), settings.get("modifiers", 0))))
        for control in (self.path_control, self.choose_button, self.copy_switch,
                        self.shortcut_button, self.default_button):
            control.setEnabled_(bool(settings.get('enabled', False)))

    @objc.python_method
    def _set_status(self, text, error):
        text = localize(text)
        self._status = (text, error)
        if self.window is not None:
            self.status_label.setStringValue_(text)
            self.status_label.setTextColor_(AK.NSColor.systemRedColor() if error else AK.NSColor.secondaryLabelColor())
            self.status_label.setToolTip_(text)

    @objc.python_method
    def _apply(self, changes):
        try:
            success, message = self.controller.update_settings(changes)
        except Exception as exc:
            success, message = False, "设置未保存：{}".format(exc)
        self._refresh()
        self._set_status(str(message or ("设置已保存。" if success else "设置未保存，请重试。")), not success)
        return bool(success)

    @objc.python_method
    def _choose_directory(self):
        self._stop_recording(cancelled=True)
        if self._directory_sheet is not None:
            return
        sheet = AK.NSOpenPanel.openPanel()
        sheet.setCanChooseFiles_(False)
        sheet.setCanChooseDirectories_(True)
        sheet.setAllowsMultipleSelection_(False)
        sheet.setCanCreateDirectories_(True)
        sheet.setPrompt_(localize("选择文件夹"))
        sheet.setMessage_(localize("选择 Markdown 文件的自动保存位置"))
        sheet.setAppearance_(self.window.appearance())
        directory = self.controller.settings.get("directory", "")
        if directory:
            sheet.setDirectoryURL_(NSURL.fileURLWithPath_isDirectory_(directory, True))
        self._directory_sheet = sheet

        def completed(result):
            self._directory_sheet = None
            if result == AK.NSModalResponseOK and sheet.URL() is not None:
                self._apply({"directory": str(sheet.URL().path())})

        sheet.beginSheetModalForWindow_completionHandler_(self.window, completed)

    @objc.python_method
    def _start_recording(self):
        if self._recording:
            return
        self._recording = True
        try:
            self.controller.begin_recording()
        except Exception as exc:
            self._set_status("无法开始录入：{}".format(exc), True)
            self._stop_recording()
            return
        if not self.window.makeFirstResponder_(self.shortcut_button):
            self._stop_recording()
            self._set_status("无法获得键盘焦点，请重新点击录入。", True)
            return
        self.shortcut_button.setTitle_(localize("请按快捷键 …"))
        self._set_status("请按组合键；Esc 取消，Delete 清除。字母按美式键位显示。", False)

    @objc.python_method
    def _stop_recording(self, cancelled=False):
        if not self._recording:
            return
        self._recording = False
        try:
            self.controller.end_recording()
        except Exception as exc:
            self._set_status("恢复快捷键失败：{}".format(exc), True)
        else:
            if cancelled:
                self._set_status("已取消录入，保留原快捷键。", False)
        finally:
            self._refresh()

    @objc.python_method
    def _record_event(self, event):
        if not self._recording or event.isARepeat():
            return
        keycode = int(event.keyCode())
        if keycode == 53:
            self._stop_recording(cancelled=True)
            return
        modifiers = _carbon_modifiers(event.modifierFlags())
        if keycode in (51, 117):
            changes = {"keycode": None, "modifiers": 0}
        else:
            error = _validation_error(keycode, modifiers)
            if error:
                self._set_status(error, True)
                return
            changes = {"keycode": keycode, "modifiers": modifiers}
        try:
            self._apply(changes)
        finally:
            self._stop_recording()


_hud = None
_hud_generation = 0
_hud_label = None


class _CaptureToastSurface(AK.NSView):
    """Draw only inside the rounded path; never fill a rectangular backing surface."""

    def isOpaque(self):
        return False

    def drawRect_(self, dirty):
        AK.NSColor.clearColor().set()
        AK.NSRectFillUsingOperation(self.bounds(), AK.NSCompositingOperationCopy)
        path = AK.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            AK.NSInsetRect(self.bounds(), 0.5, 0.5), 18, 18)
        workspace = AK.NSWorkspace.sharedWorkspace()
        alpha = 1.0 if workspace.accessibilityDisplayShouldReduceTransparency() else 0.50
        AK.NSColor.colorWithWhite_alpha_(1.0, alpha).setFill()
        path.fill()
        AK.NSColor.colorWithWhite_alpha_(0.0, 0.08).setStroke()
        path.setLineWidth_(0.5)
        path.stroke()


class _CaptureToastPanel(AK.NSPanel):
    def canBecomeKeyWindow(self):
        return False

    def canBecomeMainWindow(self):
        return False


def show_capture_hud(message, error=False):
    _on_main(_show_capture_hud, localize(str(message)), bool(error))


def _show_capture_hud(message, error=False):
    """Nonactivating material toast. Generation guards also cover in-flight fades."""
    global _hud, _hud_generation, _hud_label
    import time
    if _hud is None:
        _hud = _CaptureToastPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            AK.NSMakeRect(0, 0, 340, 56),
            AK.NSWindowStyleMaskBorderless | AK.NSWindowStyleMaskNonactivatingPanel,
            AK.NSBackingStoreBuffered, False)
        _hud.setReleasedWhenClosed_(False)
        _hud.setLevel_(AK.NSFloatingWindowLevel)
        _hud.setIgnoresMouseEvents_(True)
        _hud.setHidesOnDeactivate_(False)
        _hud.setOpaque_(False)
        _hud.setHasShadow_(True)
        _hud.setBackgroundColor_(AK.NSColor.clearColor())
        _hud.setCollectionBehavior_(AK.NSWindowCollectionBehaviorCanJoinAllSpaces
                                   | AK.NSWindowCollectionBehaviorFullScreenAuxiliary)
        material = _CaptureToastSurface.alloc().initWithFrame_(AK.NSMakeRect(0, 0, 340, 56))
        # An explicit transparent drawing surface avoids the visual-effect backdrop
        # extending beyond a CALayer-only corner radius. Keep text fully opaque.
        _hud.setAppearance_(AK.NSAppearance.appearanceNamed_(AK.NSAppearanceNameAqua))
        _hud.setContentView_(material)
        _hud_label = AK.NSTextField.wrappingLabelWithString_("")
        _hud_label.setFont_(AK.NSFont.systemFontOfSize_weight_(13, AK.NSFontWeightRegular))
        _hud_label.setAlignment_(AK.NSTextAlignmentCenter)
        _hud_label.setTextColor_(AK.NSColor.labelColor())
        material.addSubview_(_hud_label)
    screen = next((s for s in AK.NSScreen.screens()
                   if AK.NSPointInRect(AK.NSEvent.mouseLocation(), s.frame())), AK.NSScreen.mainScreen())
    rect = screen.visibleFrame() if screen else AK.NSMakeRect(0, 0, 800, 600)
    max_width = max(180, min(480, rect.size.width - 48))
    _hud_label.setStringValue_(message)
    _hud_label.setToolTip_(message)
    _hud_label.setAccessibilityLabel_(message)
    natural = _hud_label.cell().cellSize().width
    width = min(max_width, max(300, natural + 48))
    text_width = width - 48
    measured = _hud_label.cell().cellSizeForBounds_(AK.NSMakeRect(0, 0, text_width, 1000))
    text_height = min(max(18, measured.height), max(36, rect.size.height - 140))
    height = max(56, text_height + 28)
    _hud.setFrame_display_(AK.NSMakeRect(rect.origin.x + (rect.size.width - width) / 2,
                                        rect.origin.y + 40, width, height), False)
    _hud.contentView().setFrame_(AK.NSMakeRect(0, 0, width, height))
    _hud_label.setFrame_(AK.NSMakeRect(24, (height - text_height) / 2, text_width, text_height))
    _hud_label.setTextColor_(AK.NSColor.systemRedColor() if error else AK.NSColor.labelColor())
    _hud_generation += 1
    generation = _hud_generation
    _hud.setAlphaValue_(1)
    _hud.orderFrontRegardless()
    _hud.invalidateShadow()
    def begin_fade():
        if generation != _hud_generation:
            return
        workspace = AK.NSWorkspace.sharedWorkspace()
        if workspace.accessibilityDisplayShouldReduceMotion():
            _hud.orderOut_(None)
            return
        started = time.monotonic()
        def step():
            if generation != _hud_generation:
                return
            progress = min(1, (time.monotonic() - started) / 0.25)
            _hud.setAlphaValue_(1 - progress)
            if progress >= 1:
                _hud.orderOut_(None)
            else:
                AppHelper.callLater(1 / 30, step)
        step()
    AppHelper.callLater(4.5 if error else 2.2, begin_fade)
