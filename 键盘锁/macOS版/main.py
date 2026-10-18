# -*- coding: utf-8 -*-
"""KeyLock 入口（macOS 版）。

用法:
    python3 main.py                     中文界面
    python3 main.py --lang en           英文界面
    python3 main.py --theme light       浅色主题
    python3 main.py --hotkey ctrl+alt+k 指定解锁快捷键
    python3 main.py --start-locked      启动即锁定
    python3 main.py --minimized         启动后隐藏窗口（Dock 图标保留）

第一次运行会请求「辅助功能」权限。没授权的话拦截功能起不来，
界面会弹出提示告诉你该去哪里勾。
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

APP_TITLE = "KeyLock"


def install_crash_handler():
    """打包成 .app 后没有控制台，异常必须自己弹窗，否则用户只会看到没反应。"""
    def handler(exc_type, exc_value, exc_tb):
        import traceback
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            with open(os.path.join(tempfile.gettempdir(), "KeyLock-error.log"),
                      "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError:
            pass
        try:
            import tkinter.messagebox as messagebox
            messagebox.showerror("KeyLock 启动失败", text[-1500:])
        except Exception:
            pass
    sys.excepthook = handler


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="KeyLock - 锁定全部键盘按键（macOS）")
    parser.add_argument("--lang", choices=("zh", "en"), default=None,
                        help="界面语言 / UI language")
    parser.add_argument("--theme", choices=("dark", "light"), default=None,
                        help="界面主题 / UI theme")
    parser.add_argument("--hotkey", default=None,
                        help="解锁快捷键，例如 ctrl+alt+l")
    parser.add_argument("--start-locked", action="store_true", help="启动即锁定")
    parser.add_argument("--minimized", action="store_true", help="启动后隐藏窗口")
    return parser.parse_args(argv)


def acquire_single_instance():
    """用带文件锁的 pid 文件保证只有一个实例。返回 (句柄, 是否是第一个)。

    两个实例同时挂 CGEventTap 会互相打架，所以必须挡住。
    非 macOS 上直接返回"是第一个"，这样 selftest 在别的平台也能 import 本模块。
    """
    if sys.platform != "darwin":
        return None, True
    try:
        import fcntl
    except ImportError:
        return None, True
    handle = None
    try:
        import config as config_module
        path = os.path.join(config_module.data_dir(), "keylock.lock")
        handle = open(path, "w")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.write(str(os.getpid()))
        handle.flush()
        return handle, True
    except Exception:
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
        return None, False


def main(argv=None):
    install_crash_handler()
    args = parse_args(argv)

    import ui
    ui.init_dpi()

    handle, is_first = acquire_single_instance()
    if not is_first:
        from i18n import t
        lang = args.lang or "zh"
        try:
            import tkinter.messagebox as messagebox
            messagebox.showinfo(t(lang, "alert_title"), t(lang, "already_running"))
        except Exception:
            print(t(lang, "already_running"))
        return 0

    import app as app_module
    application = app_module.KeyLockApp(args)
    if args.start_locked:
        application.blocker.set_locked(True)

    try:
        return application.run()
    finally:
        # 双保险：无论如何退出，都要把键盘恢复原样
        try:
            application.blocker.set_locked(False)
            application.blocker.stop()
        except Exception:
            pass
        handle = None


if __name__ == "__main__":
    sys.exit(main())
