# -*- coding: utf-8 -*-
"""开机自启（macOS 版）。

macOS 没有 Windows 那种 Run 注册表键，标准做法是在
~/Library/LaunchAgents/ 放一个 plist，登录时由 launchd 拉起。

和 Windows 版的区别：
  * 不需要管理员权限；
  * plist 里必须写绝对路径；
  * macOS 上没有 pythonw，也不存在"无控制台"这回事 —— 源码方式运行会带一个
    终端窗口，想要干净就打包成 .app（见 build_app.sh）。
"""

from __future__ import annotations

import os
import plistlib
import sys

APP_NAME = "KeyLock"
LABEL = "com.keylock.autostart"


def plist_path():
    return os.path.expanduser("~/Library/LaunchAgents/%s.plist" % LABEL)


def launch_command(extra_args=()):
    """要写进 plist 的 ProgramArguments 列表。"""
    if getattr(sys, "frozen", False):
        return [sys.executable] + list(extra_args)
    interpreter = sys.executable
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    return [interpreter, script] + list(extra_args)


def build_plist(extra_args=()):
    """构造 plist 内容。单独抽出来是为了能在任何平台上测序列化。"""
    return {
        "Label": LABEL,
        "ProgramArguments": launch_command(extra_args),
        "RunAtLoad": True,
        "ProcessType": "Interactive",
    }


def is_enabled():
    return os.path.exists(plist_path())


def current_command():
    try:
        with open(plist_path(), "rb") as handle:
            payload = plistlib.load(handle)
    except (OSError, ValueError):
        return None
    return " ".join(payload.get("ProgramArguments") or [])


def enable():
    path = plist_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as handle:
        plistlib.dump(build_plist(), handle)
    os.replace(tmp, path)
    return path


def disable():
    path = plist_path()
    try:
        os.remove(path)
    except OSError:
        pass
    return path


def set_enabled(enabled):
    if enabled:
        enable()
    else:
        disable()
    return is_enabled()
