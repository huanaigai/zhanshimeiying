# -*- coding: utf-8 -*-
"""键盘拦截引擎（macOS 版）。

原理
----
在 HID 层挂一个 CGEventTap（CGEventTapCreate + kCGHIDEventTap），回调里返回
NULL 就把这次按键彻底吞掉 —— 任何程序都收不到。和 Windows 版的
WH_KEYBOARD_LL 是同一个思路。

和 Windows 版的两点不同
----------------------
1. **修饰键事件必须放行。** macOS 的按键事件自带完整的修饰键 flags，
   只要修饰键本身正常送达系统，后续事件上的 flags 就是准的。
   如果我们把 Control 的按下也吞掉，系统就不知道 Control 按下了，
   后面那个 L 事件的 flags 里就不会有 Control —— 解锁快捷键反而认不出来。
   放行修饰键本身不会产生任何字符，是安全的。

2. **需要「辅助功能」授权。** 没授权时 CGEventTapCreate 直接返回 NULL，
   不是抛异常，所以要显式检查并给出人话提示。

线程模型
--------
事件 tap 跑在独立线程自己的 CFRunLoop 里，和界面的 Tk 主循环互不干扰，
和 Windows 版把钩子放在独立线程的消息循环里是一个套路。

可测性
------
`decide()` 是整个引擎的核心判断，是纯函数（只依赖入参和自身状态），
不碰任何系统 API。所以它可以在 Windows 上完整跑单测，
只有 CGEventTap 那一层必须到 Mac 上才能验。
"""

from __future__ import annotations

import os
import sys
import threading
import time

import quartz
from quartz import (EVENT_FLAGS_CHANGED, EVENT_KEY_DOWN, EVENT_KEY_UP,
                    EVENT_TAP_DISABLED_BY_TIMEOUT,
                    EVENT_TAP_DISABLED_BY_USER_INPUT)

ESCAPE_KEYCODE = quartz.KEYCODES["escape"]


# ---------------------------------------------------------------- 快捷键解析
def parse_hotkey(spec):
    """把 "ctrl+alt+l" 解析成 (修饰键掩码, 主键码)。"""
    flags = 0
    keycode = None
    modifiers = 0
    for raw in str(spec).lower().replace(" ", "").split("+"):
        part = raw.strip()
        if not part:
            continue
        if part in quartz.MODIFIER_FLAGS:
            flags |= quartz.MODIFIER_FLAGS[part]
            modifiers += 1
        elif part in quartz.KEYCODES:
            keycode = quartz.KEYCODES[part]
        else:
            raise ValueError("无法识别的快捷键片段: %r" % raw)
    if keycode is None:
        raise ValueError("快捷键缺少主键，例如 ctrl+alt+l")
    if not flags:
        raise ValueError("快捷键至少要有一个修饰键（ctrl / alt / shift / cmd）")
    return flags, keycode


def _modifier_names(flags):
    return [name for name in quartz.MODIFIER_ORDER
            if quartz.MODIFIER_FLAGS[name] & flags]


def format_hotkey(parsed):
    """(修饰键掩码, 主键码) -> "Ctrl + Option + L"。"""
    flags, keycode = parsed
    parts = [quartz.MODIFIER_DISPLAY[name] for name in _modifier_names(flags)]
    parts.append(keycode_name(keycode))
    return " + ".join(parts)


_DISPLAY_OVERRIDES = {
    "escape": "Esc", "esc": "Esc", "return": "Return", "enter": "Return",
    "tab": "Tab", "space": "Space", "delete": "Delete",
}


def keycode_name(keycode):
    """键码 -> 给人看的名字。

    键码表里的名字是**配置用的**小写形式（"l" / "f12"），直接拿去显示会变成
    「Ctrl + Option + l」，很难看。所以这里单独做一次显示名转换：
    单字母大写，多字母首字母大写。
    """
    name = quartz.KEYCODE_NAMES.get(keycode)
    if name is None:
        return "KeyCode 0x%02X" % keycode
    if name in _DISPLAY_OVERRIDES:
        return _DISPLAY_OVERRIDES[name]
    if len(name) == 1:
        return name.upper()
    return name.capitalize()


def hotkey_spec(flags, keycode):
    """(修饰键掩码, 主键码) -> "ctrl+alt+l"。用于录制快捷键。"""
    names = _modifier_names(flags)
    name = quartz.KEYCODE_NAMES.get(keycode)
    if not names or name is None:
        return None
    if name in ("escape", "esc"):
        return None          # Esc 是"取消录制"，不能当快捷键
    return "+".join(names + [name])


# ---------------------------------------------------------------- 引擎
class KeyboardBlocker(object):
    """全局键盘拦截器（macOS / CGEventTap）。状态读写都是单条赋值。"""

    def __init__(self, hotkey="ctrl+alt+l"):
        self.hotkey_spec = hotkey
        self.required_flags, self.keycode = parse_hotkey(hotkey)
        self.hotkey_display = format_hotkey((self.required_flags, self.keycode))

        self._locked = False
        self._password_mode = False
        self._own_pid = os.getpid()
        self._combo_latched = False

        # 快捷键被按下时先问上层（跑在 tap 线程里，上层只许往队列丢东西）
        self.on_hotkey = None

        # 快捷键录制
        self._capturing = False
        self._captured = None

        self._thread = None
        self._run_loop = None
        self._tap = None
        self._callback = None      # 必须持引用，否则 C 回调被 GC 掉
        self._ready = threading.Event()
        self._error = None

    # -------------------------------------------------- 对外 API
    @property
    def locked(self):
        return self._locked

    def set_locked(self, value):
        self._locked = bool(value)

    def toggle(self):
        self._locked = not self._locked
        return self._locked

    def set_hotkey(self, spec):
        flags, keycode = parse_hotkey(spec)
        self.hotkey_spec = spec
        self.required_flags = flags
        self.keycode = keycode
        self.hotkey_display = format_hotkey((flags, keycode))
        self._combo_latched = False
        return self.hotkey_display

    def set_password_mode(self, enabled):
        self._password_mode = bool(enabled)

    # ---- 快捷键录制
    def begin_capture(self):
        self._captured = None
        self._capturing = True

    def cancel_capture(self):
        self._capturing = False
        self._captured = None

    def poll_capture(self):
        """返回 None=还在等；""=用户取消了；其它=录到的快捷键字符串。"""
        spec = self._captured
        if spec is None:
            return None
        self._captured = None
        self._capturing = False
        return spec

    @property
    def capturing(self):
        return self._capturing

    # -------------------------------------------------- 核心判断（纯函数）
    def _is_hotkey(self, keycode, flags):
        if keycode != self.keycode:
            return False
        # 用"至少包含"而不是"完全等于"：多按了一个 Shift 也应该认
        return (flags & self.required_flags) == self.required_flags

    def decide(self, event_type, keycode, flags):
        """返回 True = 放行，False = 吞掉。

        这是整个引擎的核心，不碰任何系统 API，因此可以在任何平台上单测。
        """
        # 修饰键事件一律放行，让系统维护修饰键状态（见模块开头第 1 点）
        if event_type == EVENT_FLAGS_CHANGED:
            return True

        is_down = (event_type == EVENT_KEY_DOWN)

        # ---- 录制模式：吞掉所有按键，只把"修饰键 + 主键"记下来
        if self._capturing:
            if is_down:
                if keycode == ESCAPE_KEYCODE:
                    self._captured = ""          # 空串 = 用户取消
                    self._capturing = False
                elif keycode not in quartz.MODIFIER_KEYCODES:
                    spec = hotkey_spec(flags, keycode)
                    if spec is not None:
                        self._captured = spec
                        self._capturing = False
            return False

        # ---- 快捷键
        if is_down and self._is_hotkey(keycode, flags):
            if not self._combo_latched:
                self._combo_latched = True
                handler = self.on_hotkey
                if handler is None:
                    self._locked = not self._locked
                else:
                    try:
                        handler()
                    except Exception:
                        pass        # tap 回调里绝不能把异常抛回系统
            return False

        if not is_down and keycode == self.keycode:
            self._combo_latched = False

        if not self._locked:
            return True

        # ---- 锁定时：密码模式且前台是本程序窗口 -> 放行，让用户能输密码
        if self._password_mode and self._foreground_is_self():
            return True
        return False

    def _foreground_is_self(self):
        """前台窗口是不是本程序自己的。查不出来就当不是（保守）。"""
        pid = quartz.frontmost_window_pid()
        return pid is not None and pid == self._own_pid

    # -------------------------------------------------- 生命周期
    def is_alive(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if not quartz.IS_MACOS:
            raise RuntimeError("键盘拦截目前只支持 macOS")
        ok, error = quartz.load()
        if not ok:
            raise RuntimeError(error)
        if not quartz.is_trusted():
            # 顺手弹一次系统引导；用户还得去系统设置里手动勾
            quartz.request_trust()
        if self.is_alive():
            return
        self._error = None
        self._ready = threading.Event()
        self._callback = quartz.CGEventTapCallBack(self._on_tap)
        self._thread = threading.Thread(target=self._pump, name="KeyLockTap", daemon=True)
        self._thread.start()
        if not self._ready.wait(5.0):
            raise RuntimeError("事件 tap 启动超时")
        if self._error:
            raise self._error

    def stop(self):
        """卸载事件 tap，键盘立刻恢复正常。可安全地重复调用。"""
        self._locked = False
        thread = self._thread
        if thread is None:
            return
        # 等 run loop 引用出现。CFRunLoopStop 在 CFRunLoopRun 真正跑起来之前
        # 调用会被丢掉，所以这里既等引用、又留一点点余量。
        deadline = time.time() + 2.0
        while self._run_loop is None and time.time() < deadline:
            time.sleep(0.01)
        run_loop_ref = self._run_loop
        if run_loop_ref:
            time.sleep(0.05)
            try:
                quartz.stop_run_loop(run_loop_ref)
            except Exception:
                pass
        thread.join(timeout=3.0)
        self._thread = None
        self._run_loop = None

    # -------------------------------------------------- tap 线程
    def _pump(self):
        try:
            mask = quartz.event_mask(EVENT_KEY_DOWN, EVENT_KEY_UP, EVENT_FLAGS_CHANGED)
            self._tap = quartz.create_event_tap(mask, self._callback)
            if not self._tap:
                raise RuntimeError(
                    "CGEventTapCreate 返回空 —— 通常是没给「辅助功能」权限。\n"
                    "打开 系统设置 → 隐私与安全性 → 辅助功能，把 KeyLock 勾上，"
                    "然后重新启动本程序。")
            source = quartz.create_run_loop_source(self._tap)
            if not source:
                raise RuntimeError("CFMachPortCreateRunLoopSource 返回空")
            self._run_loop = quartz.current_run_loop()
            quartz.add_source(self._run_loop, source)
            quartz.release(source)
        except Exception as exc:
            self._error = exc
            self._ready.set()
            self._cleanup_tap()
            return

        self._ready.set()
        try:
            quartz.run_loop()
        finally:
            self._cleanup_tap()

    def _cleanup_tap(self):
        tap = self._tap
        self._tap = None
        if tap:
            try:
                quartz.release(tap)
            except Exception:
                pass

    def _on_tap(self, proxy, event_type, event, user_info):
        """跑在 tap 线程。返回 event 放行，返回 None 吞掉。"""
        try:
            if event_type in (EVENT_TAP_DISABLED_BY_TIMEOUT,
                              EVENT_TAP_DISABLED_BY_USER_INPUT):
                # 系统因为回调太慢（或用户输入）把 tap 关了，必须自己重新打开，
                # 否则拦截会静悄悄地失效。
                if self._tap:
                    quartz.enable_tap(self._tap)
                return event
            keycode = quartz.keycode_of(event)
            flags = quartz.flags_of(event)
            if self.decide(event_type, keycode, flags):
                return event
            return None
        except Exception:
            # 回调里出任何问题都放行 —— 宁可漏拦，也不能因为自己的 bug 把用户键盘锁死
            return event
