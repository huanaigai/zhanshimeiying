# -*- coding: utf-8 -*-
"""KeyLock 界面层（macOS 版）：主窗口 + 三个对话框。纯 tkinter，无第三方依赖。

这个文件和 Windows 版的 ui.py 是同一份，只差三处 macOS 适配：
  * init_dpi() 在非 Windows 上直接返回 1.0（Retina 缩放由系统自己处理）；
  * 字体换成 macOS 上真正存在的；
  * 去掉了「以管理员身份重启」按钮（macOS 版没有需要提权的功能）。

像素尺寸仍然统一过 px()，Windows 上才有非 1.0 的缩放系数。
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import messagebox

from i18n import LANGUAGE_ORDER, next_language, t

_IS_WINDOWS = sys.platform.startswith("win")

# ---------------------------------------------------------------- DPI
_SCALE = 1.0


def init_dpi():
    """必须在创建任何窗口之前调用。返回缩放系数（macOS 上恒为 1.0）。

    只有 Windows 需要显式声明 DPI 感知，否则整个窗口会被系统拉伸成糊的。
    macOS 的 Retina 缩放由系统处理，tkinter 拿到的就是逻辑坐标，别去动它。
    """
    global _SCALE
    if not _IS_WINDOWS:
        _SCALE = 1.0
        return _SCALE
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # PROCESS_SYSTEM_DPI_AWARE
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
        hdc = ctypes.windll.user32.GetDC(0)
        try:
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        finally:
            ctypes.windll.user32.ReleaseDC(0, hdc)
        if dpi:
            _SCALE = max(1.0, float(dpi) / 96.0)
    except Exception:
        _SCALE = 1.0
    return _SCALE


def px(value):
    return int(round(value * _SCALE))


# ---------------------------------------------------------------- 配色
# 两套调色板。键名就是模块级全局名，apply_theme() 会把选中的那套铺到全局。
# 浅色不是把深色反相：强调色（红/绿/黄）在浅底上要压暗一档才有对比度。
THEMES = {
    "dark": {
        "BG": "#0f172a",
        "CARD": "#1e293b",
        "EDGE": "#334155",
        "TEXT": "#e2e8f0",
        "MUTED": "#94a3b8",
        "DIM": "#64748b",
        "LOCK_COLOR": "#ef4444",
        "UNLOCK_COLOR": "#22c55e",
        "OFF_TRACK": "#475569",
        "KNOB": "#f8fafc",
        "WARN": "#fbbf24",
        "BTN_BG": "#334155",
        "BTN_ACTIVE": "#475569",
        "BTN_DANGER": "#7f1d1d",
        "BTN_DANGER_ACTIVE": "#991b1b",
        "FIELD_BG": "#0b1220",
        "OK_BG": "#22c55e",
        "OK_ACTIVE": "#16a34a",
        "OK_FG": "#04220f",
    },
    "light": {
        "BG": "#eef2f7",
        "CARD": "#ffffff",
        "EDGE": "#cbd5e1",
        "TEXT": "#0f172a",
        "MUTED": "#475569",
        "DIM": "#64748b",
        "LOCK_COLOR": "#dc2626",
        "UNLOCK_COLOR": "#15803d",
        "OFF_TRACK": "#cbd5e1",
        "KNOB": "#ffffff",
        "WARN": "#b45309",
        "BTN_BG": "#e2e8f0",
        "BTN_ACTIVE": "#cbd5e1",
        "BTN_DANGER": "#fecaca",
        "BTN_DANGER_ACTIVE": "#fca5a5",
        "FIELD_BG": "#ffffff",
        "OK_BG": "#16a34a",
        "OK_ACTIVE": "#15803d",
        "OK_FG": "#ffffff",
    },
}

THEME_ORDER = ("dark", "light")
_CURRENT_THEME = "dark"


def apply_theme(name):
    """把选中的调色板铺到模块级全局名上。返回真正生效的主题名。

    注意：这只会影响**之后**创建的控件。已经建好的 Tk 控件颜色是定死的，
    换主题时调用方必须重建控件树（MainWindow.rebuild 干这事）。
    """
    global _CURRENT_THEME
    if name not in THEMES:
        name = "dark"
    _CURRENT_THEME = name
    globals().update(THEMES[name])
    return name


def current_theme():
    return _CURRENT_THEME


def next_theme(name=None):
    """在深/浅之间切换。"""
    name = name or _CURRENT_THEME
    try:
        index = THEME_ORDER.index(name)
    except ValueError:
        return THEME_ORDER[0]
    return THEME_ORDER[(index + 1) % len(THEME_ORDER)]


apply_theme("dark")

FONT = "Segoe UI" if _IS_WINDOWS else "Helvetica Neue"
MONO = "Consolas" if _IS_WINDOWS else "Menlo"
COUNTDOWN_CHOICES = (0, 3, 5, 10, 30)
CLOSE_ACTIONS = ("ask", "tray", "quit")
DEFAULT_HOTKEY = "ctrl+alt+l"


def mix(color_a, color_b, ratio):
    a = tuple(int(color_a[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(color_b[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(
        int(round(a[i] + (b[i] - a[i]) * ratio)) for i in range(3)
    )


def round_rect_points(x1, y1, x2, y2, radius):
    return [
        x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
        x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
        x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
    ]


def center_on_parent(window, parent, width, height):
    parent.update_idletasks()
    x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
    y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 3)
    window.geometry("%dx%d+%d+%d" % (width, height, x, y))


# ---------------------------------------------------------------- 开关控件
class ToggleSwitch(tk.Canvas):
    """胶囊开关。按比例缩放，一个类同时给主开关和小设置项用。"""

    def __init__(self, master, width=160, height=80, bg=None, command=None,
                 on_color=None, off_color=None, start=False):
        # 默认值不能写成 bg=CARD：默认参数只在函数定义时求值一次，换主题后
        # 模块级 CARD 变了，这些默认值还是旧的。一律用 None 再在这里解析。
        bg = CARD if bg is None else bg
        on_color = LOCK_COLOR if on_color is None else on_color
        off_color = OFF_TRACK if off_color is None else off_color
        tk.Canvas.__init__(self, master, width=px(width), height=px(height),
                           bg=bg, highlightthickness=0, cursor="hand2")
        # 注意：不能用 self._w / self._h —— self._w 是 tkinter 内部存窗口路径名的属性，
        # 覆盖掉之后 pack/grid 会报 "bad argument ... must be name of window"。
        self._cw = px(width)
        self._ch = px(height)
        self._on_color = on_color
        self._off_color = off_color
        self._value = bool(start)
        self._enabled = True
        self._anim = 1.0 if start else 0.0
        self._command = command
        self._job = None
        self.bind("<Button-1>", self._on_click)
        self._draw()

    # ---- 属性
    @property
    def value(self):
        return self._value

    def set_value(self, value, animate=True):
        value = bool(value)
        target = 1.0 if value else 0.0
        if value == self._value:
            # 目标值没变。只有"直接跳到终点"且滑块还没到位时才重画，
            # 免得每 80ms 一次的 refresh 白白重绘。
            if not animate and self._anim != target:
                self._anim = target
                self._draw()
            return
        self._value = value
        if not animate:
            self._anim = 1.0 if value else 0.0
            self._draw()
            return
        self._schedule()

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled == self._enabled:
            return
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()

    @property
    def enabled(self):
        return self._enabled

    # ---- 交互
    def _on_click(self, _event):
        if not self._enabled:
            return
        self.set_value(not self._value)
        if self._command is not None:
            self._command(self._value)

    # ---- 绘制
    def _geom(self):
        pad = self._ch / 8.0
        return pad, pad, self._cw - pad, self._ch - pad, (self._ch - 2 * pad) / 2.0

    def _draw(self):
        if not self.winfo_exists():
            return
        self.delete("all")
        x1, y1, x2, y2, radius = self._geom()
        ratio = self._anim
        color = mix(self._off_color, self._on_color, ratio)
        if not self._enabled:
            color = mix(color, BG, 0.5)
        self.create_polygon(round_rect_points(x1, y1, x2, y2, radius),
                            smooth=True, fill=color, outline="")
        knob_radius = radius - self._ch * 0.0625
        knob_x = (x1 + radius) + ((x2 - radius) - (x1 + radius)) * ratio
        knob_y = (y1 + y2) / 2.0
        self.create_oval(knob_x - knob_radius, knob_y - knob_radius,
                         knob_x + knob_radius, knob_y + knob_radius,
                         fill=KNOB if self._enabled else DIM, outline="")

    def _schedule(self):
        if self._job is None:
            self._job = self.after(16, self._tick)

    def _tick(self):
        self._job = None
        if not self.winfo_exists():
            return
        target = 1.0 if self._value else 0.0
        if abs(self._anim - target) < 0.002:
            self._anim = target
            self._draw()
            return
        self._anim += (target - self._anim) * 0.25
        self._draw()
        self._schedule()


# ---------------------------------------------------------------- 小部件工厂
def make_button(parent, text, command, bg=None, active=None,
                fg=None, font=None, width=None, padx=None):
    # 同上：不能写 bg=BTN_BG 这种默认值，否则换主题时按钮颜色不会跟着变
    bg = BTN_BG if bg is None else bg
    active = BTN_ACTIVE if active is None else active
    fg = TEXT if fg is None else fg
    button = tk.Button(
        parent, text=text, command=command, bg=bg, fg=fg,
        activebackground=active, activeforeground=fg, relief="flat",
        font=font or (FONT, 9), cursor="hand2", highlightthickness=0, bd=0,
        padx=px(padx if padx is not None else 10),
        pady=px(4),
    )
    if width:
        button.configure(width=width)
    return button


# ---------------------------------------------------------------- 密码对话框
class PasswordDialog(tk.Toplevel):
    """mode="enter" 输入密码解锁；mode="set" 设置/清除密码。

    锁定状态下这个窗口能正常输入：调用方已经把拦截器切到"密码模式"
    （只放行发往本进程窗口的按键）。
    """

    ATTEMPTS = 5

    def __init__(self, parent, app, mode, on_done):
        tk.Toplevel.__init__(self, parent)
        self.app = app
        self.lang = app.cfg.get("language")
        self.mode = mode
        self.on_done = on_done
        self.attempts_left = self.ATTEMPTS
        self.entries = []

        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)
        self.attributes("-topmost", True)
        self.title(self._t("password_dialog_set_title" if mode == "set"
                           else "password_dialog_enter_title"))

        self._build()
        center_on_parent(self, parent, px(360), self.winfo_reqheight())
        self.update_idletasks()
        center_on_parent(self, parent, px(360), self.winfo_reqheight())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())
        self.bind("<Return>", lambda _e: self._confirm())
        self.grab_set()
        self.after(60, self._focus_first)

    def _t(self, key, **kwargs):
        return t(self.lang, key, **kwargs)

    def _build(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=px(18), pady=px(16))

        if self.mode == "enter":
            self.lbl_hint = tk.Label(wrap, bg=BG, fg=WARN, font=(FONT, 8),
                                     wraplength=px(320), justify="left")
            self.lbl_hint.pack(anchor="w", pady=(0, px(10)))
            self.lbl_hint.configure(text=self._t("password_hint_locked"))

        self.fields = []
        if self.mode == "set":
            self.fields = [("password_new", False), ("password_confirm", False)]
        else:
            self.fields = [("password_your", False)]

        for key, _flag in self.fields:
            tk.Label(wrap, text=self._t(key), bg=BG, fg=MUTED,
                     font=(FONT, 9), anchor="w").pack(fill="x")
            entry = tk.Entry(wrap, show="\u25cf", bg=FIELD_BG, fg=TEXT,
                             insertbackground=TEXT, relief="flat",
                             font=(FONT, 10), highlightthickness=1,
                             highlightbackground=EDGE, highlightcolor=UNLOCK_COLOR)
            entry.pack(fill="x", ipady=px(5), pady=(px(2), px(10)))
            self.entries.append(entry)

        self.lbl_error = tk.Label(wrap, bg=BG, fg=LOCK_COLOR, font=(FONT, 9),
                                  wraplength=px(320), justify="left")
        self.lbl_error.pack(anchor="w")

        row = tk.Frame(wrap, bg=BG)
        row.pack(fill="x", pady=(px(12), 0))
        self.btn_ok = make_button(row, self._t("password_ok"), self._confirm,
                                  bg=OK_BG, active=OK_ACTIVE, fg=OK_FG)
        self.btn_ok.pack(side="right")
        self.btn_cancel = make_button(row, self._t("password_cancel"), self._cancel)
        self.btn_cancel.pack(side="right", padx=(0, px(8)))
        if self.mode == "set" and self.app.cfg.has_password():
            self.btn_clear = make_button(row, self._t("password_clear_button"),
                                         self._clear, bg=BTN_DANGER,
                                         active=BTN_DANGER_ACTIVE)
            self.btn_clear.pack(side="left")

    def _focus_first(self):
        try:
            self.lift()
            self.focus_force()
            if self.entries:
                self.entries[0].focus_set()
        except tk.TclError:
            pass

    def _error(self, text):
        self.lbl_error.configure(text=text)
        try:
            self.bell()
        except tk.TclError:
            pass

    def _confirm(self):
        values = [entry.get() for entry in self.entries]
        if self.mode == "set":
            if not values[0]:
                self._error(self._t("password_empty"))
                return
            if values[0] != values[1]:
                self._error(self._t("password_mismatch"))
                return
            self._finish("ok", values[0])
            return
        if self.app.cfg.check_password(values[0]):
            self._finish("ok")
            return
        self.attempts_left -= 1
        self.entries[0].delete(0, "end")
        if self.attempts_left <= 0:
            self._finish("cancel")
            return
        self._error(self._t("password_wrong", n=self.attempts_left))

    def _clear(self):
        self._finish("clear")

    def _cancel(self):
        self._finish("cancel")

    def _finish(self, action, payload=None):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        if self.on_done is not None:
            self.on_done(action, payload)


# ---------------------------------------------------------------- 快捷键对话框
class HotkeyDialog(tk.Toplevel):
    """录制新的解锁快捷键。录制期间钩子会吞掉所有按键，所以不用担心漏字。"""

    def __init__(self, parent, app, on_done):
        tk.Toplevel.__init__(self, parent)
        self.app = app
        self.lang = app.cfg.get("language")
        self.on_done = on_done
        self.captured = None
        self._poll_job = None

        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)
        self.attributes("-topmost", True)
        self.title(self._t("hotkey_dialog_title"))
        self._build()
        center_on_parent(self, parent, px(380), self.winfo_reqheight())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())
        self.grab_set()

        self.app.blocker.begin_capture()
        self.after(60, self._focus_me)
        self._poll_job = self.after(60, self._poll)

    def _t(self, key, **kwargs):
        return t(self.lang, key, **kwargs)

    def _build(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=px(18), pady=px(16))

        self.lbl_hint = tk.Label(wrap, text=self._t("hotkey_dialog_hint"),
                                 bg=BG, fg=MUTED, font=(FONT, 9),
                                 wraplength=px(340), justify="left")
        self.lbl_hint.pack(anchor="w")

        box = tk.Frame(wrap, bg=CARD, highlightthickness=1, highlightbackground=EDGE)
        box.pack(fill="x", pady=px(12))
        self.lbl_value = tk.Label(box, text=self._t("hotkey_dialog_waiting"),
                                  bg=CARD, fg=TEXT, font=(MONO, 15, "bold"))
        self.lbl_value.pack(pady=px(16))

        self.lbl_current = tk.Label(wrap, text=self._t("hotkey_dialog_current",
                                                       hotkey=self.app.blocker.hotkey_display),
                                    bg=BG, fg=DIM, font=(FONT, 8))
        self.lbl_current.pack(anchor="w")

        self.lbl_error = tk.Label(wrap, bg=BG, fg=LOCK_COLOR, font=(FONT, 9),
                                  wraplength=px(340), justify="left")
        self.lbl_error.pack(anchor="w", pady=(px(6), 0))

        row = tk.Frame(wrap, bg=BG)
        row.pack(fill="x", pady=(px(12), 0))
        self.btn_ok = make_button(row, self._t("hotkey_dialog_ok"), self._confirm,
                                  bg=OK_BG, active=OK_ACTIVE, fg=OK_FG)
        self.btn_ok.pack(side="right")
        self.btn_cancel = make_button(row, self._t("hotkey_dialog_cancel"), self._cancel)
        self.btn_cancel.pack(side="right", padx=(0, px(8)))
        self.btn_default = make_button(row, self._t("hotkey_dialog_default"), self._reset)
        self.btn_default.pack(side="left")

    def _focus_me(self):
        try:
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def _poll(self):
        self._poll_job = None
        spec = self.app.blocker.poll_capture()
        if spec is not None:
            if spec == "":
                self._cancel()
                return
            self.captured = spec
            self.lbl_value.configure(text=self.app.pretty_hotkey(spec))
            self.lbl_error.configure(text="")
        if self.winfo_exists():
            self._poll_job = self.after(60, self._poll)

    def _reset(self):
        self.captured = DEFAULT_HOTKEY
        self.lbl_value.configure(text=self.app.pretty_hotkey(DEFAULT_HOTKEY))
        self.lbl_error.configure(text="")

    def _confirm(self):
        if not self.captured:
            self._error(self._t("hotkey_dialog_hint"))
            return
        self._finish(self.captured)

    def _error(self, text):
        self.lbl_error.configure(text=text)

    def _cancel(self):
        self._finish(None)

    def _finish(self, spec):
        if self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except tk.TclError:
                pass
            self._poll_job = None
        self.app.blocker.cancel_capture()
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        if self.on_done is not None:
            self.on_done(spec)


# ---------------------------------------------------------------- 关闭确认
class CloseChoiceDialog(tk.Toplevel):
    """点窗口的 X 时问一句：最小化到托盘 / 退出软件 / 取消。

    勾上「记住我的选择」就会把结果写进配置的 close_action，
    之后不再询问，也可以在设置里随时改回来。
    """

    def __init__(self, parent, app, on_done):
        tk.Toplevel.__init__(self, parent)
        self.app = app
        self.lang = app.cfg.get("language")
        self.on_done = on_done
        self.remember = tk.BooleanVar(value=False)

        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)
        self.attributes("-topmost", True)
        self.title(self._t("close_dialog_title"))
        self._build()
        center_on_parent(self, parent, px(420), self.winfo_reqheight())
        self.update_idletasks()
        center_on_parent(self, parent, px(420), self.winfo_reqheight())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _event: self._cancel())
        self.grab_set()
        self.after(60, self._focus_me)

    def _t(self, key, **kwargs):
        return t(self.lang, key, **kwargs)

    def _build(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=px(20), pady=px(18))

        tk.Label(wrap, text=self._t("close_dialog_message"), bg=BG, fg=TEXT,
                 font=(FONT, 11, "bold"), anchor="w", justify="left",
                 wraplength=px(360)).pack(fill="x")

        self.chk_remember = tk.Checkbutton(
            wrap, text=self._t("close_dialog_remember"), variable=self.remember,
            bg=BG, fg=MUTED, activebackground=BG, activeforeground=TEXT,
            selectcolor=CARD, font=(FONT, 9), anchor="w",
            highlightthickness=0, bd=0, cursor="hand2")
        self.chk_remember.pack(fill="x", pady=(px(14), px(4)))

        row = tk.Frame(wrap, bg=BG)
        row.pack(fill="x", pady=(px(12), 0))

        self.btn_tray = make_button(row, self._t("close_action_tray"),
                                    lambda: self._finish("tray"))
        self.btn_tray.pack(side="left")

        self.btn_quit = make_button(row, self._t("close_action_quit"),
                                    lambda: self._finish("quit"),
                                    bg=BTN_DANGER, active=BTN_DANGER_ACTIVE)
        self.btn_quit.pack(side="left", padx=(px(8), 0))

        self.btn_cancel = make_button(row, self._t("close_dialog_cancel"), self._cancel)
        self.btn_cancel.pack(side="right")

    def _focus_me(self):
        try:
            self.lift()
            self.focus_force()
            self.btn_tray.focus_set()
        except tk.TclError:
            pass

    def _cancel(self):
        self._finish("cancel")

    def _finish(self, action):
        remember = bool(self.remember.get())
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        if self.on_done is not None:
            self.on_done(action, remember)


# ---------------------------------------------------------------- 主窗口
class MainWindow(object):

    def __init__(self, app):
        self.app = app
        self.lang = app.cfg.get("language")
        self.captions = {}
        self._slow_signature = None

        self.root = tk.Tk()
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build()
        self.apply_language()
        self.refresh(force=True)
        self._fit_to_content()

    # -------------------------------------------------- 工具
    def _t(self, key, **kwargs):
        return t(self.lang, key, **kwargs)

    def _make_card(self, pad_top=12):
        card = tk.Frame(self.root, bg=CARD, highlightthickness=1,
                        highlightbackground=EDGE)
        card.pack(fill="x", padx=px(18), pady=(px(pad_top), 0))
        return card

    def _caption(self, parent, name, key):
        label = tk.Label(parent, bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w")
        label.pack(side="left")
        self.captions[name] = (label, key)
        return label

    def _setting_row(self, parent, name, caption_key, parts):
        """parts 按**从左到右**给出，内部反向 pack 到右侧容器里。"""
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=px(4))
        self._caption(row, name, caption_key)

        holder = tk.Frame(row, bg=CARD)
        holder.pack(side="right")

        built = {}
        for part in reversed(parts):
            kind = part[0]
            if kind == "value":
                widget = tk.Label(holder, bg=CARD, fg=TEXT, font=(FONT, 9), anchor="e")
                widget.pack(side="right")
                built["value"] = widget
            elif kind == "mono":
                widget = tk.Label(holder, bg=CARD, fg=TEXT, font=(MONO, 11, "bold"),
                                  anchor="e")
                widget.pack(side="right")
                built["value"] = widget
            elif kind == "button":
                widget = make_button(holder, self._t(part[1]), part[2] if len(part) > 2 else None)
                widget.pack(side="right", padx=(px(8), 0))
                built.setdefault("buttons", []).append(widget)
                built["button"] = widget
            elif kind == "switch":
                widget = ToggleSwitch(holder, 44, 23, bg=CARD,
                                      on_color=part[2] if len(part) > 2 else LOCK_COLOR,
                                      command=part[1])
                widget.pack(side="right")
                built["switch"] = widget
        return built

    def _admin_button(self, parent, text, command, danger=False):
        return make_button(parent, text, command,
                           bg=BTN_DANGER if danger else BTN_BG,
                           active=BTN_DANGER_ACTIVE if danger else BTN_ACTIVE)

    # -------------------------------------------------- 构建
    def _build(self):
        # 顶部
        self.lbl_title = tk.Label(self.root, bg=BG, fg=TEXT, font=(FONT, 18, "bold"))
        self.lbl_title.pack(pady=(px(16), px(2)))
        self.lbl_subtitle = tk.Label(self.root, bg=BG, fg=MUTED, font=(FONT, 9))
        self.lbl_subtitle.pack()

        # 卡1：大开关
        card1 = self._make_card(14)
        self.sw_main = ToggleSwitch(card1, 160, 80, bg=CARD, command=self._on_main_switch)
        self.sw_main.pack(pady=(px(14), px(4)))
        self.lbl_state = tk.Label(card1, bg=CARD, fg=TEXT, font=(FONT, 18, "bold"))
        self.lbl_state.pack()
        self.lbl_desc = tk.Label(card1, bg=CARD, fg=MUTED, font=(FONT, 9),
                                 wraplength=px(380), justify="center")
        self.lbl_desc.pack(pady=(px(2), 0))
        self.lbl_tap = tk.Label(card1, bg=CARD, fg=DIM, font=(FONT, 9))
        self.lbl_tap.pack(pady=(px(6), px(14)))

        # 卡2：设置
        card2 = self._make_card()
        self.lbl_settings = tk.Label(card2, bg=CARD, fg=TEXT, font=(FONT, 10, "bold"),
                                     anchor="w")
        self.lbl_settings.pack(fill="x", padx=px(14), pady=(px(10), px(4)))
        body = tk.Frame(card2, bg=CARD)
        body.pack(fill="x", padx=px(14), pady=(0, px(12)))

        self.row_hotkey = self._setting_row(
            body, "settings_hotkey", "settings_hotkey",
            [("mono",), ("button", "settings_hotkey_change", self.on_change_hotkey)])
        self.row_countdown = self._setting_row(
            body, "settings_countdown", "settings_countdown",
            [("button", "countdown_off", self.on_cycle_countdown)])
        self.row_password = self._setting_row(
            body, "settings_password", "settings_password",
            [("value",), ("button", "password_none", self.on_change_password)])
        self.row_autostart = self._setting_row(
            body, "settings_autostart", "settings_autostart",
            [("switch", self.on_toggle_autostart)])
        self.row_close = self._setting_row(
            body, "settings_close_action", "settings_close_action",
            [("button", "close_action_ask", self.on_cycle_close_action)])

        # 卡3：设备级屏蔽
        card3 = self._make_card()
        self.lbl_devices = tk.Label(card3, bg=CARD, fg=TEXT, font=(FONT, 10, "bold"),
                                    anchor="w")
        self.lbl_devices.pack(fill="x", padx=px(14), pady=(px(10), px(4)))
        dev_body = tk.Frame(card3, bg=CARD)
        dev_body.pack(fill="x", padx=px(14))
        self.row_dev_internal = self._setting_row(
            dev_body, "devices_internal", "devices_internal",
            [("value",), ("switch", self.on_toggle_device_internal, LOCK_COLOR)])
        self.row_dev_external = self._setting_row(
            dev_body, "devices_external", "devices_external",
            [("value",), ("switch", self.on_toggle_device_external, LOCK_COLOR)])
        self.lbl_devhint = tk.Label(card3, bg=CARD, fg=DIM, font=(FONT, 8),
                                    wraplength=px(380), justify="left", anchor="w")
        self.lbl_devhint.pack(fill="x", padx=px(14), pady=(px(4), px(12)))

        # 提示
        self.lbl_tip = tk.Label(self.root, bg=BG, fg=WARN, font=(FONT, 9),
                                wraplength=px(420), justify="center")
        self.lbl_tip.pack(pady=(px(12), 0))

        # 底部
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(side="bottom", fill="x", padx=px(18), pady=(px(10), px(14)))
        row = tk.Frame(footer, bg=BG)
        row.pack(fill="x")
        self.btn_lang = make_button(row, self._t("lang_button"), self.on_switch_language)
        self.btn_lang.pack(side="left")
        self.btn_theme = make_button(row, self._t("theme_to_light"), self.on_switch_theme)
        self.btn_theme.pack(side="left", padx=(px(8), 0))
        self.btn_quit = make_button(row, self._t("quit_button"), self.on_quit)
        self.btn_quit.pack(side="right")

        self.lbl_status = tk.Label(footer, bg=BG, fg=DIM, font=(FONT, 8),
                                   anchor="w", justify="left", wraplength=px(420))
        self.lbl_status.pack(fill="x", pady=(px(10), 0))
        self.lbl_banner = tk.Label(footer, bg=BG, fg=LOCK_COLOR, font=(FONT, 8),
                                   anchor="w", justify="left", wraplength=px(420))
        self.lbl_banner.pack(fill="x", pady=(px(4), 0))

    def _fit_to_content(self):
        self.root.update_idletasks()
        width = max(px(460), self.root.winfo_reqwidth())
        height = self.root.winfo_reqheight()
        screen_h = self.root.winfo_screenheight()
        height = min(height, screen_h - px(60))
        self.root.geometry("%dx%d" % (width, height))
        x = max(0, (self.root.winfo_screenwidth() - width) // 2)
        y = max(0, (screen_h - height) // 4)
        self.root.geometry("%dx%d+%d+%d" % (width, height, x, y))

    # -------------------------------------------------- 文案
    def apply_language(self):
        self.root.title(self._t("app_title"))
        self.lbl_title.configure(text=self._t("app_title"))
        self.lbl_subtitle.configure(text=self._t("subtitle"))
        self.lbl_settings.configure(text=self._t("settings_title"))
        self.lbl_devices.configure(text=self._t("devices_title"))
        self.lbl_tip.configure(text=self._t("mouse_tip"))
        self.btn_lang.configure(text=self._t("lang_button"))
        self.theme = self.app.cfg.get("theme")
        self.btn_theme.configure(
            text=self._t("theme_to_light" if self.theme == "dark" else "theme_to_dark"))
        self.btn_quit.configure(text=self._t("quit_button"))
        for name, (widget, key) in self.captions.items():
            widget.configure(text=self._t(key))
        self.row_hotkey["button"].configure(text=self._t("settings_hotkey_change"))
        self.row_password["button"].configure(
            text=self._t("password_clear_button") if self.app.cfg.has_password()
            else self._t("password_none"))
        self._slow_signature = None   # 强制下一次把慢状态重刷一遍

    def _caption_text(self, name, suffix=""):
        widget, key = self.captions[name]
        widget.configure(text=self._t(key) + (("  " + suffix) if suffix else ""))

    # -------------------------------------------------- 刷新
    def refresh(self, force=False):
        app = self.app
        if app.cfg.get("language") != self.lang:
            self.lang = app.cfg.get("language")
            self.apply_language()

        locked = app.blocker.locked
        counting = app.countdown_left > 0
        # 主开关不做过渡动画：锁 / 解锁是「立刻生效」的动作，滑块再滑一段会让人
        # 觉得状态变化被拖后了一拍。上面那些小设置开关照旧保留动画。
        self.sw_main.set_value(locked or counting, animate=False)

        if counting:
            self.lbl_state.configure(text=str(app.countdown_left), fg=WARN)
            self.lbl_desc.configure(text=self._t("desc_countdown", n=app.countdown_left))
            self.lbl_tap.configure(text=self._t("tap_hint_countdown"))
        elif locked:
            self.lbl_state.configure(text=self._t("state_locked"), fg=LOCK_COLOR)
            self.lbl_desc.configure(text=self._t("desc_locked"))
            self.lbl_tap.configure(text=self._t("tap_hint_locked"))
        else:
            self.lbl_state.configure(text=self._t("state_unlocked"), fg=UNLOCK_COLOR)
            self.lbl_desc.configure(text=self._t("desc_unlocked"))
            self.lbl_tap.configure(text=self._t("tap_hint_unlocked"))

        self.row_hotkey["value"].configure(text=app.blocker.hotkey_display)
        seconds = app.cfg.get("countdown_seconds")
        self.row_countdown["button"].configure(
            text=self._t("countdown_off") if not seconds
            else self._t("countdown_fmt", n=seconds))
        self.row_password["value"].configure(
            text=self._t("password_is_set") if app.cfg.has_password()
            else self._t("password_none"))
        action = app.cfg.get("close_action")
        if action not in CLOSE_ACTIONS:
            action = "ask"
        self.row_close["button"].configure(text=self._t("close_action_" + action))

        self._apply_slow(app.slow_state)

    def _apply_slow(self, state):
        if not state:
            return
        signature = (
            state.get("autostart"), state.get("tray"), state.get("admin"),
            state.get("busy"), state.get("device_error"),
            tuple(sorted((state.get("groups") or {}).items())),
            self.lang,
        )
        if signature == self._slow_signature:
            return
        self._slow_signature = signature

        self.row_autostart["switch"].set_value(bool(state.get("autostart")))

        groups = state.get("groups") or {}
        internal = groups.get("internal")
        external = groups.get("external")

        if internal is None:
            self._caption_text("devices_internal", self._t("devices_no_device"))
        else:
            self._caption_text("devices_internal",
                               self._t("devices_count", n=internal["count"]))
        if external is None:
            self._caption_text("devices_external", self._t("devices_no_device"))
        else:
            self._caption_text("devices_external",
                               self._t("devices_count", n=external["count"]))

        admin = bool(state.get("admin"))
        busy = bool(state.get("busy"))
        available = state.get("devices_available", False)

        for key, group in (("devices_internal", internal), ("devices_external", external)):
            switch = self.row_dev_internal["switch"] if key == "devices_internal" \
                else self.row_dev_external["switch"]
            usable = available and admin and not busy and group is not None and group["count"] > 0
            switch.set_enabled(usable)
            switch.set_value(bool(group and group["on"]))

        if not available:
            self.lbl_devhint.configure(
                text=self._t("devices_unavailable", err=state.get("device_error") or "?"))
        elif not admin:
            self.lbl_devhint.configure(text=self._t("devices_need_admin"))
        elif state.get("device_error"):
            self.lbl_devhint.configure(
                text=self._t("devices_error", err=state["device_error"]))
        elif busy:
            self.lbl_devhint.configure(text=self._t("devices_busy"))
        else:
            self.lbl_devhint.configure(text=state.get("device_hint") or "")

        # 底部状态行（macOS 版不提权限，那一栏没意义，去掉）
        parts = [self._t("engine_on") if state.get("engine") else self._t("engine_off")]
        if state.get("tray"):
            parts.append(self._t("tray_on"))
        self.lbl_status.configure(text="  ·  ".join(parts))

        active = [k for k, v in (("internal", internal), ("external", external))
                  if v and v["on"]]
        if active:
            names = " / ".join(self._t("devices_" + k) for k in active)
            self.lbl_banner.configure(
                text=self._t("devices_active", groups=names), fg=LOCK_COLOR)
        elif state.get("notice"):
            self.lbl_banner.configure(text=state["notice"], fg=WARN)
        else:
            self.lbl_banner.configure(text="")

    # -------------------------------------------------- 事件
    def _on_main_switch(self, value):
        self.app.request_lock() if value else self.app.request_unlock()

    def on_change_hotkey(self):
        self.app.open_hotkey_dialog()

    def on_cycle_countdown(self):
        current = self.app.cfg.get("countdown_seconds")
        try:
            index = COUNTDOWN_CHOICES.index(current)
        except ValueError:
            index = 0
        self.app.set_countdown(COUNTDOWN_CHOICES[(index + 1) % len(COUNTDOWN_CHOICES)])
        self.refresh()          # 别等下一次轮询，点了就立刻看到新值

    def on_change_password(self):
        self.app.open_password_dialog("set")

    def on_toggle_autostart(self, value):
        self.app.set_autostart(value)

    def on_cycle_close_action(self):
        current = self.app.cfg.get("close_action")
        try:
            index = CLOSE_ACTIONS.index(current)
        except ValueError:
            index = 0
        self.app.set_close_action(CLOSE_ACTIONS[(index + 1) % len(CLOSE_ACTIONS)])
        self.refresh()          # 同上，点了就立刻看到新值

    def on_toggle_device_internal(self, value):
        self.app.set_device_group("internal", value)

    def on_toggle_device_external(self, value):
        self.app.set_device_group("external", value)

    def on_switch_language(self):
        self.app.set_language(next_language(self.lang))

    def on_switch_theme(self):
        self.app.set_theme(next_theme(self.theme))

    def rebuild(self):
        """换主题时把整棵控件树重建一遍。

        Tk 控件的颜色是创建时定死的，光改模块里的调色板不会重刷已有控件。
        与其给每个控件记一个"颜色角色"再逐个 configure（漏一个就是一块颜色不对），
        不如直接重建 —— 界面状态都在 app / cfg 里，重建不会丢东西。
        """
        geometry = self.root.geometry()      # 记住当前位置和大小，重建后原样放回去
        for child in self.root.winfo_children():
            child.destroy()
        self.captions = {}
        self._slow_signature = None
        self.root.configure(bg=BG)
        self._build()
        self.apply_language()
        self.refresh(force=True)
        self.root.geometry(geometry)

    def on_restart_admin(self):
        """macOS 版没有需要提权的功能，这个按钮已经从界面上拿掉了。"""
        return

    def on_close(self):
        self.app.on_window_close()

    def on_quit(self):
        self.app.request_quit()

    def run(self):
        self.root.mainloop()

    # -------------------------------------------------- 杂项
    def show(self):
        try:
            self.root.deiconify()
            self.root.lift()
        except tk.TclError:
            pass

    def set_topmost(self, on):
        try:
            self.root.attributes("-topmost", bool(on))
        except tk.TclError:
            pass

    def hide(self):
        try:
            self.root.withdraw()
        except tk.TclError:
            pass

    def alert(self, message, title_key="alert_title"):
        messagebox.showinfo(self._t(title_key), message, parent=self.root)

    def confirm(self, message, title_key):
        return messagebox.askyesno(self._t(title_key), message, parent=self.root)
