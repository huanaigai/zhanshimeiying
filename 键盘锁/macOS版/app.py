# -*- coding: utf-8 -*-
"""KeyLock 控制器（macOS 版）。

和 Windows 版的差别：
  * 没有设备级屏蔽（macOS 没有对应能力），界面那一栏恒为灰并解释原因；
  * 没有托盘 —— macOS 的等价物是"隐藏窗口 + Dock 图标保留"，点 Dock 图标唤回；
  * 没有提权按钮（本版没有需要 root 的功能）。

线程模型和 Windows 版一致：
  * Tk 主线程  —— 界面、对话框、倒计时、配置读写
  * tap 线程   —— keyboard_blocker 自己的 CFRunLoop

tap 线程只往 self.commands 丢字符串，主线程在 _poll 里取出来处理，
除此之外它不碰任何界面对象。
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
import tkinter as tk

import autostart
import config as config_module
import quartz
import ui
from i18n import t
from keyboard_blocker import KeyboardBlocker, format_hotkey, parse_hotkey
from ui import CloseChoiceDialog, HotkeyDialog, MainWindow, PasswordDialog

DEFAULT_HOTKEY = "ctrl+alt+l"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class KeyLockApp(object):

    POLL_MS = 80
    SLOW_MS = 2000

    def __init__(self, args):
        self.args = args
        self.cfg = config_module.Config()
        self._apply_startup_overrides()

        self.blocker = KeyboardBlocker(self.cfg.get("hotkey"))
        self.blocker.on_hotkey = self._enqueue_toggle

        self.commands = queue.Queue()
        self.window = None
        self.slow_state = {}
        self.countdown_left = 0

        self._countdown_job = None
        self._poll_job = None
        self._slow_job = None
        self._notice = ""
        self._password_open = False
        self._hotkey_open = False
        self._close_dialog_open = False

    # -------------------------------------------------- 启动
    def _apply_startup_overrides(self):
        lang = getattr(self.args, "lang", None)
        if lang:
            self.cfg.set("language", lang)
        theme = getattr(self.args, "theme", None)
        if theme:
            self.cfg.set("theme", theme)
        hotkey = getattr(self.args, "hotkey", None)
        if hotkey:
            try:
                parse_hotkey(hotkey)
                self.cfg.set("hotkey", hotkey)
            except ValueError:
                pass

    @property
    def lang(self):
        return self.cfg.get("language")

    def pretty_hotkey(self, spec):
        try:
            return format_hotkey(parse_hotkey(spec))
        except ValueError:
            return str(spec).upper()

    def _enqueue_toggle(self):
        """跑在 tap 线程里，只做一件事：往队列丢一个字符串。"""
        self.commands.put("toggle")

    # -------------------------------------------------- 主循环
    def run(self):
        # 主题必须在建窗口之前铺好：Tk 控件的颜色是创建时取的
        ui.apply_theme(self.cfg.get("theme"))
        self.window = MainWindow(self)
        self._install_mac_hooks()

        try:
            self.blocker.start()
        except Exception as exc:
            self.window.alert(
                "%s\n\n%s" % (t(self.lang, "alert_title"), exc))
            # 拦截起不来也让界面开着，用户至少能看到提示、能改设置

        self.slow_state = self._collect_slow()
        self._slow_tick()
        self._poll()

        if getattr(self.args, "minimized", False):
            self._hide_window()

        self.window.run()
        return 0

    def _install_mac_hooks(self):
        """macOS 专有：点 Dock 图标唤回窗口、Cmd+Q 走正常退出流程。"""
        root = self.window.root
        for name, callback in (("::tk::mac::ReopenApplication", self._on_reopen),
                               ("::tk::mac::Quit", self.request_quit)):
            try:
                root.createcommand(name, callback)
            except Exception:
                pass

    def _on_reopen(self):
        if self.window is not None:
            self.window.show()

    def _poll(self):
        self._poll_job = None
        while True:
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle_command(command)
            except Exception as exc:
                self._notice = str(exc)
        if self.window is not None and self.window.root.winfo_exists():
            self.window.refresh()
            self._poll_job = self.window.root.after(self.POLL_MS, self._poll)

    def _handle_command(self, command):
        if command == "toggle":
            if self.countdown_left:
                self.cancel_countdown()
            elif self.blocker.locked:
                self.request_unlock()
            else:
                self.request_lock()
        elif command == "lock":
            self.request_lock()
        elif command == "unlock":
            self.request_unlock()
        elif command == "show":
            if self.window:
                self.window.show()
        elif command == "quit":
            self.request_quit()

    def _slow_tick(self):
        self._slow_job = None
        self.slow_state = self._collect_slow()
        if self.window is not None and self.window.root.winfo_exists():
            self._slow_job = self.window.root.after(self.SLOW_MS, self._slow_tick)

    def _collect_slow(self):
        try:
            autostart_on = autostart.is_enabled()
        except Exception:
            autostart_on = False
        return {
            "engine": self.blocker.is_alive(),
            "admin": True,               # macOS 版没有提权概念，恒为真
            "tray": False,               # 没有托盘，状态行不显示这一栏
            "autostart": autostart_on,
            "busy": False,
            "device_error": t(self.lang, "devices_blocked_by_os"),
            "notice": self._notice,
            "devices_available": False,  # 这一栏在 macOS 上恒为灰
            "groups": {},
        }

    def _slow_signature_reset(self):
        self.slow_state = self._collect_slow()

    # -------------------------------------------------- 锁定 / 解锁
    def request_lock(self):
        if self.blocker.locked or self.countdown_left:
            return
        seconds = int(self.cfg.get("countdown_seconds") or 0)
        if seconds <= 0:
            self._do_lock()
            return
        self.countdown_left = seconds
        self.window.set_topmost(True)
        self.window.show()
        self._tick_countdown()

    def _tick_countdown(self):
        self._countdown_job = None
        if self.countdown_left <= 0:
            self._do_lock()
            return
        self.window.refresh()
        self.countdown_left -= 1
        self._countdown_job = self.window.root.after(1000, self._tick_countdown)

    def cancel_countdown(self):
        if self._countdown_job is not None:
            try:
                self.window.root.after_cancel(self._countdown_job)
            except tk.TclError:
                pass
            self._countdown_job = None
        self.countdown_left = 0
        self.window.set_topmost(False)
        self.window.refresh(force=True)

    def _do_lock(self):
        self._countdown_job = None
        self.countdown_left = 0
        self.blocker.set_locked(True)
        self.window.set_topmost(True)
        self.window.show()
        self.window.refresh(force=True)

    def request_unlock(self):
        if self.countdown_left:
            self.cancel_countdown()
            return
        if not self.blocker.locked:
            return
        if self.cfg.has_password():
            self.open_password_dialog("enter")
        else:
            self._do_unlock()

    def _do_unlock(self):
        self.blocker.set_locked(False)
        self.window.set_topmost(False)
        self.window.refresh(force=True)

    def set_countdown(self, seconds):
        self.cfg.set("countdown_seconds", int(seconds))
        self.window.refresh(force=True)

    # -------------------------------------------------- 对话框
    def open_hotkey_dialog(self):
        if self._hotkey_open:
            return
        self._hotkey_open = True

        def done(spec):
            self._hotkey_open = False
            if spec:
                self.set_hotkey(spec)
            self.window.refresh(force=True)

        HotkeyDialog(self.window.root, self, done)

    def set_hotkey(self, spec):
        try:
            display = self.blocker.set_hotkey(spec)
        except ValueError as exc:
            self._notice = str(exc)
            return False
        self.cfg.set("hotkey", spec)
        self._notice = "%s -> %s" % (t(self.lang, "settings_hotkey"), display)
        return True

    def open_password_dialog(self, mode):
        if self._password_open:
            return
        self._password_open = True
        if self.blocker.locked:
            # 让拦截器进入"密码模式"：锁定时只放行发往本程序窗口的按键
            self.blocker.set_password_mode(True)

        def done(action, payload=None):
            self._password_open = False
            self.blocker.set_password_mode(False)
            if mode == "enter":
                if action == "ok":
                    self._do_unlock()
                else:
                    self.window.refresh(force=True)
                return
            if action == "ok":
                self.cfg.set_password(payload)
                self._notice = t(self.lang, "password_saved")
            elif action == "clear":
                self.cfg.set_password("")
                self._notice = t(self.lang, "password_cleared")
            self.window.apply_language()
            self.window.refresh(force=True)

        PasswordDialog(self.window.root, self, mode, done)

    def open_close_dialog(self):
        if self._close_dialog_open:
            return
        self._close_dialog_open = True

        def done(action, remember):
            self._close_dialog_open = False
            if action == "cancel":
                return
            if remember:
                self.set_close_action(action)
            if action == "tray":
                self._hide_window()
            else:
                self.request_quit()

        CloseChoiceDialog(self.window.root, self, done)

    # -------------------------------------------------- 设置项
    def set_language(self, lang):
        self.cfg.set("language", lang)
        self.window.apply_language()
        self.window.refresh(force=True)

    def set_theme(self, name):
        actual = ui.apply_theme(name)
        self.cfg.set("theme", actual)
        if self.window is not None:
            self.window.rebuild()
        return actual

    def set_autostart(self, enabled):
        try:
            actual = autostart.set_enabled(bool(enabled))
            self.cfg.set("autostart", actual)
            self._notice = ""
        except Exception as exc:
            self.cfg.set("autostart", False)
            self._notice = "开机自启设置失败：%s" % exc
        self._slow_signature_reset()

    def set_close_action(self, action):
        if action not in ("ask", "tray", "quit"):
            action = "ask"
        self.cfg.set("close_action", action)
        self._slow_signature_reset()

    # -------------------------------------------------- 关闭 / 退出
    def on_window_close(self):
        action = self.cfg.get("close_action")
        if action not in ("ask", "tray", "quit"):
            action = "ask"
        if action == "tray":
            self._hide_window()
        elif action == "quit":
            self.request_quit()
        else:
            self.open_close_dialog()

    def _hide_window(self):
        """隐藏窗口。macOS 的等价物是"收进 Dock"—— 图标还在，点一下就回来。"""
        self.window.hide()

    def request_quit(self, skip_confirm=False):
        if self.blocker.locked and not skip_confirm:
            if not self.window.confirm(t(self.lang, "quit_message"), "quit_title"):
                return
        self.shutdown()

    def shutdown(self):
        for job in (self._poll_job, self._slow_job, self._countdown_job):
            if job is not None:
                try:
                    self.window.root.after_cancel(job)
                except tk.TclError:
                    pass
        self._poll_job = self._slow_job = self._countdown_job = None

        self.blocker.set_locked(False)
        self.blocker.stop()
        self.cfg.save()
        try:
            self.window.root.destroy()
        except tk.TclError:
            pass


def check_accessibility():
    """启动前的自查：有没有「辅助功能」权限。返回 (是否已授权, 说明文字)。"""
    if not quartz.IS_MACOS:
        return False, "当前不是 macOS"
    ok, error = quartz.load()
    if not ok:
        return False, error
    if quartz.is_trusted():
        return True, ""
    return False, (
        "KeyLock 需要「辅助功能」权限才能拦截键盘。\n\n"
        "请打开 系统设置 → 隐私与安全性 → 辅助功能，"
        "把 KeyLock（或运行它的终端 / Python）勾上，然后重新启动本程序。")
