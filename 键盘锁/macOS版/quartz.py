# -*- coding: utf-8 -*-
"""Quartz / CoreFoundation 的 ctypes 绑定（macOS 版专用）。

这一层只做一件事：把 C API 变成 Python 能调的形状，**不放任何业务逻辑**。
"哪些按键该吞掉" 的判断全在 keyboard_blocker.py 里，那部分是纯 Python，
不依赖 macOS，可以直接在 Windows 上跑单测。

在非 macOS 上 import 本模块不会报错（常量和键码表照常可用），但任何真正
调用系统 API 的函数都会抛 RuntimeError —— 这样 selftest 能在任何平台跑
平台无关的那一半。
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys

IS_MACOS = sys.platform == "darwin"

# ================================================================ 常量
# --- CGEventType
EVENT_KEY_DOWN = 10
EVENT_KEY_UP = 11
EVENT_FLAGS_CHANGED = 12
EVENT_TAP_DISABLED_BY_TIMEOUT = 0xFFFFFFFE
EVENT_TAP_DISABLED_BY_USER_INPUT = 0xFFFFFFFF

# --- CGEventTapLocation / Placement / Options
HID_EVENT_TAP = 0             # 最早能看到事件的位置
HEAD_INSERT_EVENT_TAP = 0
TAP_OPTION_DEFAULT = 0        # 可修改、可吞掉事件
TAP_OPTION_LISTEN_ONLY = 1    # 只能看，拦不住 —— 别用这个

# --- CGEventField
FIELD_KEYCODE = 9

# --- CGEventFlags（修饰键位）
FLAG_SHIFT = 0x00020000
FLAG_CONTROL = 0x00040000
FLAG_OPTION = 0x00080000      # macOS 上的 Alt
FLAG_COMMAND = 0x00100000     # macOS 上的 ⌘

MODIFIER_FLAGS = {
    "ctrl": FLAG_CONTROL,
    "control": FLAG_CONTROL,
    "alt": FLAG_OPTION,       # 沿用 Windows 版的写法，"alt" 就是 Option
    "option": FLAG_OPTION,
    "opt": FLAG_OPTION,
    "shift": FLAG_SHIFT,
    "cmd": FLAG_COMMAND,
    "command": FLAG_COMMAND,
    "win": FLAG_COMMAND,      # 同样是沿用旧习惯
    "super": FLAG_COMMAND,
}

MODIFIER_ORDER = ("ctrl", "alt", "shift", "cmd")
MODIFIER_DISPLAY = {"ctrl": "Ctrl", "alt": "Option", "shift": "Shift", "cmd": "Command"}

# --- 虚拟键码（Carbon HIToolbox 的 kVK_*）
KEYCODES = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05,
    "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C,
    "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10, "t": 0x11,
    "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "6": 0x16, "5": 0x17,
    "=": 0x18, "9": 0x19, "7": 0x1A, "-": 0x1B, "8": 0x1C, "0": 0x1D,
    "]": 0x1E, "o": 0x1F, "u": 0x20, "[": 0x21, "i": 0x22, "p": 0x23,
    "return": 0x24, "enter": 0x24, "l": 0x25, "j": 0x26, "'": 0x27,
    "k": 0x28, ";": 0x29, "\\": 0x2A, ",": 0x2B, "/": 0x2C, "n": 0x2D,
    "m": 0x2E, ".": 0x2F, "tab": 0x30, "space": 0x31, "delete": 0x33,
    "escape": 0x35, "esc": 0x35,
}
# 功能键在 Carbon 里**不是**连续的，必须逐个列出来（网上不少代码在这里抄错）
KEYCODES.update({
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76, "f5": 0x60, "f6": 0x61,
    "f7": 0x62, "f8": 0x64, "f9": 0x65, "f10": 0x6D, "f11": 0x67, "f12": 0x6F,
})

KEYCODE_NAMES = {}
for _name, _code in KEYCODES.items():
    # 同一个键码有多个别名时，取最短的那个当显示名（"esc" 优于 "escape"）
    if _code not in KEYCODE_NAMES or len(_name) < len(KEYCODE_NAMES[_code]):
        KEYCODE_NAMES[_code] = _name

# 修饰键自己的键码。这些事件一律放行 —— 让系统正常维护修饰键状态，
# 后续按键事件上的 flags 才是准的。放行修饰键本身不会产生任何字符。
MODIFIER_KEYCODES = frozenset([
    0x36,  # 右 Command
    0x37,  # 左 Command
    0x38,  # 左 Shift
    0x39,  # Caps Lock
    0x3A,  # 左 Option
    0x3B,  # 左 Control
    0x3C,  # 右 Shift
    0x3D,  # 右 Option
    0x3E,  # 右 Control
    0x3F,  # Fn
])

# --- CGWindowList 选项
WINDOW_LIST_ON_SCREEN_ONLY = 1 << 0
WINDOW_LIST_EXCLUDE_DESKTOP = 1 << 4
NULL_WINDOW_ID = 0

CF_NUMBER_INT_TYPE = 9

# ================================================================ 类型
CFIndex = ctypes.c_long
CFTypeRef = ctypes.c_void_p
CFStringRef = ctypes.c_void_p
CFArrayRef = ctypes.c_void_p
CFDictionaryRef = ctypes.c_void_p
CFNumberRef = ctypes.c_void_p
CFRunLoopRef = ctypes.c_void_p
CFRunLoopSourceRef = ctypes.c_void_p
CFMachPortRef = ctypes.c_void_p
CGEventRef = ctypes.c_void_p
CGEventTapProxy = ctypes.c_void_p
CGEventMask = ctypes.c_uint64
CGEventFlags = ctypes.c_uint64
CGWindowID = ctypes.c_uint32

# 事件回调：返回 event 放行，返回 None 吞掉
CGEventTapCallBack = ctypes.CFUNCTYPE(CGEventRef, CGEventTapProxy, ctypes.c_uint32,
                                      CGEventRef, ctypes.c_void_p)


def event_mask(*event_types):
    """把若干 CGEventType 折成一个 CGEventMask 位图。"""
    mask = 0
    for event_type in event_types:
        mask |= 1 << event_type
    return mask


# ================================================================ 加载
_cf = None
_cg = None
_bind_error = ""
_bound = False
CFRunLoopCommonModes = None
_kCGWindowOwnerPID = None
_kAXTrustedCheckOptionPrompt = None


def _load_framework(candidates):
    for candidate in candidates:
        path = ctypes.util.find_library(candidate) or candidate
        try:
            return ctypes.CDLL(path)
        except OSError:
            continue
    return None


def _symbol(libs, name):
    """框架之间会互相 re-export，同一个符号可能在任意一个库里，挨个试。"""
    for lib in libs:
        if lib is None:
            continue
        try:
            return getattr(lib, name)
        except AttributeError:
            continue
    return None


def _const_ref(libs, name):
    """取一个导出的 CFTypeRef 常量：符号里存的是指针本身。"""
    for lib in libs:
        if lib is None:
            continue
        try:
            return ctypes.c_void_p.in_dll(lib, name).value
        except ValueError:
            continue
    return None


def load():
    """加载框架并绑定函数签名。返回 (成功?, 失败原因)。可重复调用。"""
    global _cf, _cg, _bound, _bind_error
    global CFRunLoopCommonModes, _kCGWindowOwnerPID, _kAXTrustedCheckOptionPrompt

    if _bound:
        return True, ""
    if not IS_MACOS:
        _bind_error = "当前不是 macOS，加载不了 Quartz"
        return False, _bind_error

    _cf = _load_framework([
        "CoreFoundation",
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
    ])
    # CGEventTap* 在 CoreGraphics，AX* 在 ApplicationServices（伞形框架，会 re-export）
    _cg = (_load_framework([
        "ApplicationServices",
        "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices",
    ]) or _load_framework([
        "CoreGraphics",
        "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics",
    ]))
    if _cf is None or _cg is None:
        _bind_error = "CoreFoundation / ApplicationServices 框架加载失败"
        return False, _bind_error

    try:
        _bind()
    except Exception as exc:
        _cf = _cg = None
        _bind_error = "%s: %s" % (type(exc).__name__, exc)
        return False, _bind_error

    CFRunLoopCommonModes = _const_ref([_cf], "kCFRunLoopCommonModes")
    _kCGWindowOwnerPID = _const_ref([_cg], "kCGWindowOwnerPID")
    _kAXTrustedCheckOptionPrompt = _const_ref([_cg, _cf], "kAXTrustedCheckOptionPrompt")
    _bound = True
    _bind_error = ""
    return True, ""


def _bind():
    cf, cg = _cf, _cg

    def sig(libs, name, restype, argtypes):
        fn = _symbol(libs, name)
        if fn is None:
            raise AttributeError("框架里找不到符号 %s" % name)
        fn.restype = restype
        fn.argtypes = argtypes
        return fn

    # ---- CoreFoundation
    global CFMachPortCreateRunLoopSource, CFRunLoopGetCurrent, CFRunLoopAddSource
    global CFRunLoopRun, CFRunLoopStop, CFRelease, CFRetain
    global CFArrayGetCount, CFArrayGetValueAtIndex, CFDictionaryGetValue
    global CFNumberGetValue, CFStringCreateWithCString, CFDictionaryCreate
    global AXIsProcessTrusted, AXIsProcessTrustedWithOptions

    CFMachPortCreateRunLoopSource = sig([cf], "CFMachPortCreateRunLoopSource",
                                        CFRunLoopSourceRef, [CFTypeRef, CFMachPortRef, CFIndex])
    CFRunLoopGetCurrent = sig([cf], "CFRunLoopGetCurrent", CFRunLoopRef, [])
    CFRunLoopAddSource = sig([cf], "CFRunLoopAddSource", None,
                             [CFRunLoopRef, CFRunLoopSourceRef, CFTypeRef])
    CFRunLoopRun = sig([cf], "CFRunLoopRun", None, [])
    CFRunLoopStop = sig([cf], "CFRunLoopStop", None, [CFRunLoopRef])
    CFRelease = sig([cf], "CFRelease", None, [CFTypeRef])
    CFRetain = sig([cf], "CFRetain", CFTypeRef, [CFTypeRef])
    CFArrayGetCount = sig([cf], "CFArrayGetCount", CFIndex, [CFArrayRef])
    CFArrayGetValueAtIndex = sig([cf], "CFArrayGetValueAtIndex", ctypes.c_void_p,
                                 [CFArrayRef, CFIndex])
    CFDictionaryGetValue = sig([cf], "CFDictionaryGetValue", ctypes.c_void_p,
                               [CFDictionaryRef, ctypes.c_void_p])
    CFNumberGetValue = sig([cf], "CFNumberGetValue", ctypes.c_bool,
                           [CFNumberRef, ctypes.c_int, ctypes.c_void_p])
    CFStringCreateWithCString = sig([cf], "CFStringCreateWithCString", CFStringRef,
                                    [CFTypeRef, ctypes.c_char_p, ctypes.c_uint32])
    CFDictionaryCreate = sig([cf], "CFDictionaryCreate", CFDictionaryRef,
                             [CFTypeRef, ctypes.POINTER(ctypes.c_void_p),
                              ctypes.POINTER(ctypes.c_void_p), CFIndex,
                              ctypes.c_void_p, ctypes.c_void_p])

    # ---- CoreGraphics
    global CGEventTapCreate, CGEventTapEnable, CGEventGetIntegerValueField
    global CGEventGetFlags, CGWindowListCopyWindowInfo

    CGEventTapCreate = sig([cg], "CGEventTapCreate", CFMachPortRef,
                           [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                            CGEventMask, CGEventTapCallBack, ctypes.c_void_p])
    CGEventTapEnable = sig([cg], "CGEventTapEnable", None, [CFMachPortRef, ctypes.c_bool])
    CGEventGetIntegerValueField = sig([cg], "CGEventGetIntegerValueField", ctypes.c_int64,
                                      [CGEventRef, ctypes.c_uint32])
    CGEventGetFlags = sig([cg], "CGEventGetFlags", CGEventFlags, [CGEventRef])
    CGWindowListCopyWindowInfo = sig([cg], "CGWindowListCopyWindowInfo", CFArrayRef,
                                     [ctypes.c_uint32, CGWindowID])

    # ---- 辅助功能授权（可能不在某些系统上，允许缺失）
    AXIsProcessTrusted = _symbol([cg, cf], "AXIsProcessTrusted")
    if AXIsProcessTrusted is not None:
        AXIsProcessTrusted.restype = ctypes.c_bool
        AXIsProcessTrusted.argtypes = []
    AXIsProcessTrustedWithOptions = _symbol([cg, cf], "AXIsProcessTrustedWithOptions")
    if AXIsProcessTrustedWithOptions is not None:
        AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
        AXIsProcessTrustedWithOptions.argtypes = [CFDictionaryRef]


def _require():
    if not _bound:
        ok, error = load()
        if not ok:
            raise RuntimeError(error)


# ================================================================ 对外封装
def create_event_tap(mask, callback):
    """挂上事件 tap。返回 CFMachPortRef，失败返回 None（多半是没授权）。"""
    _require()
    return CGEventTapCreate(HID_EVENT_TAP, HEAD_INSERT_EVENT_TAP,
                            TAP_OPTION_DEFAULT, mask, callback, None)


def create_run_loop_source(tap):
    _require()
    return CFMachPortCreateRunLoopSource(None, tap, 0)


def disable_tap(tap):
    _require()
    CGEventTapEnable(tap, False)


def enable_tap(tap):
    _require()
    CGEventTapEnable(tap, True)


def run_loop():
    _require()
    CFRunLoopRun()


def current_run_loop():
    _require()
    return CFRunLoopGetCurrent()


def add_source(run_loop_ref, source, modes=None):
    _require()
    CFRunLoopAddSource(run_loop_ref, source, modes or CFRunLoopCommonModes)


def stop_run_loop(run_loop_ref):
    _require()
    CFRunLoopStop(run_loop_ref)


def release(ref):
    _require()
    if ref:
        CFRelease(ref)


def keycode_of(event):
    _require()
    return int(CGEventGetIntegerValueField(event, FIELD_KEYCODE))


def flags_of(event):
    _require()
    return int(CGEventGetFlags(event))


# ---------------------------------------------------------------- 授权
def is_trusted():
    """当前进程有没有「辅助功能」权限。判断不了就当没有。"""
    if not IS_MACOS:
        return False
    ok, _error = load()
    if not ok or AXIsProcessTrusted is None:
        return False
    try:
        return bool(AXIsProcessTrusted())
    except Exception:
        return False


def request_trust():
    """弹一次系统授权引导（只会弹一次，之后要去系统设置里手动勾）。"""
    if not IS_MACOS:
        return False
    ok, _error = load()
    if not ok or AXIsProcessTrustedWithOptions is None or _kAXTrustedCheckOptionPrompt is None:
        return False
    try:
        true_ref = _const_ref([_cf], "kCFBooleanTrue")
        if not true_ref:
            return False
        keys = (ctypes.c_void_p * 1)(ctypes.c_void_p(_kAXTrustedCheckOptionPrompt))
        values = (ctypes.c_void_p * 1)(ctypes.c_void_p(true_ref))
        options = CFDictionaryCreate(None, keys, values, 1, None, None)
        if not options:
            return False
        try:
            return bool(AXIsProcessTrustedWithOptions(options))
        finally:
            CFRelease(options)
    except Exception:
        return False


# ---------------------------------------------------------------- 前台窗口
def frontmost_window_pid():
    """当前最前面那个窗口属于哪个进程。查不到返回 None。

    用于「密码模式」：锁定时只放行发往本程序窗口的按键，让用户能输密码。
    """
    if not IS_MACOS:
        return None
    ok, _error = load()
    if not ok or _kCGWindowOwnerPID is None:
        return None
    array = None
    try:
        options = WINDOW_LIST_ON_SCREEN_ONLY | WINDOW_LIST_EXCLUDE_DESKTOP
        array = CGWindowListCopyWindowInfo(options, NULL_WINDOW_ID)
        if not array:
            return None
        count = CFArrayGetCount(array)
        for index in range(count):
            window = CFArrayGetValueAtIndex(array, index)
            if not window:
                continue
            number = CFDictionaryGetValue(window, ctypes.c_void_p(_kCGWindowOwnerPID))
            if not number:
                continue
            value = ctypes.c_int(0)
            if CFNumberGetValue(ctypes.c_void_p(number), CF_NUMBER_INT_TYPE,
                                ctypes.byref(value)):
                return int(value.value)
        return None
    except Exception:
        return None
    finally:
        if array:
            try:
                CFRelease(array)
            except Exception:
                pass
