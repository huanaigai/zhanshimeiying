# -*- coding: utf-8 -*-
"""配置持久化 + 解锁密码哈希（macOS 版）。

这个文件和 Windows 版是同一份，只有 data_dir() 按平台分流：
macOS 走 ~/Library/Application Support/KeyLock，
Windows 走 %APPDATA%\\KeyLock。

"被禁用过的设备"那套记录是 Windows 设备级屏蔽专用的，macOS 上用不到，
但保留在这里不影响 —— 两个版本共用一份代码，少一处漂移。
"""

from __future__ import annotations

import binascii
import hashlib
import hmac
import json
import os
import sys
import tempfile
import threading
import time

APP_NAME = "KeyLock"

DEFAULTS = {
    "language": "zh",
    "theme": "dark",                 # "dark" | "light"
    "hotkey": "ctrl+alt+l",
    "countdown_seconds": 0,          # 0 = 点击后立即锁定（默认）
    "config_version": 3,             # 配置结构版本，用来做一次性迁移
    "autostart": False,
    "close_action": "ask",           # 关窗口时："ask" 每次询问 | "tray" 最小化到托盘 | "quit" 直接退出
    "password_hash": "",             # 空字符串 = 没设密码
    "device_group_internal": False,  # 设备级：屏蔽笔记本内置键盘
    "device_group_external": False,  # 设备级：屏蔽外接键盘
}

_PBKDF2_ROUNDS = 120000
DEVICE_STATE_FILE = "disabled_devices.json"


# ---------------------------------------------------------------- 路径
def data_dir():
    """配置目录，按平台分流。"""
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        path = tempfile.gettempdir()
    return path


def _atomic_write(path, text):
    """先写临时文件再 os.replace，避免掉电/崩溃时留下半个 JSON。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


# ---------------------------------------------------------------- 密码
def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return "pbkdf2_sha256$%d$%s$%s" % (
        _PBKDF2_ROUNDS,
        binascii.hexlify(salt).decode("ascii"),
        binascii.hexlify(digest).decode("ascii"),
    )


def verify_password(stored, password):
    """恒定时间比较，避免时序侧信道。"""
    if not stored:
        return False
    try:
        algo, rounds, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = binascii.unhexlify(salt_hex)
        expected = binascii.unhexlify(digest_hex)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- 配置
class Config(object):
    """极简的 dict 包装。线程安全，写盘是原子的。"""

    def __init__(self, path=None):
        self.path = path or os.path.join(data_dir(), "config.json")
        self._lock = threading.RLock()
        self._data = dict(DEFAULTS)
        self.load()

    def load(self):
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    raw = json.load(handle)
            except (OSError, ValueError):
                return self._data
            if isinstance(raw, dict):
                # v1 -> v2：倒计时的默认值从 3 秒改成 0 秒（点击开关立即锁定）。
                # 老配置里那个 3 是旧默认值、不是用户主动选的，所以这里替他改过来；
                # 想保留倒数的话，在设置里重新选 3/5/10/30 秒即可。
                if int(raw.get("config_version") or 1) < 2:
                    if raw.get("countdown_seconds") in (None, 3):
                        raw["countdown_seconds"] = 0
                    raw["config_version"] = 2
                if int(raw.get("config_version") or 1) < 3:
                    # v2 -> v3：关窗口的行为从"一个开关"改成"三选一 + 询问对话框"。
                    # 旧开关的默认值虽然是 True，但用户多半没主动动过，所以这里
                    # 统一给「每次询问」，把选择权交回用户手里。
                    raw.pop("minimize_to_tray", None)
                    if raw.get("close_action") not in ("tray", "quit"):
                        raw["close_action"] = "ask"
                    raw["config_version"] = 3
                for key, value in raw.items():
                    if key in DEFAULTS:
                        self._data[key] = value
            return self._data

    def save(self):
        with self._lock:
            try:
                _atomic_write(self.path, json.dumps(self._data, ensure_ascii=False, indent=2))
                return True
            except OSError:
                return False

    def get(self, key, default=None):
        with self._lock:
            if key in self._data:
                return self._data[key]
            return DEFAULTS.get(key, default)

    def set(self, key, value, save=True):
        with self._lock:
            self._data[key] = value
        if save:
            self.save()
        return value

    # ---- 密码快捷方法
    def has_password(self):
        return bool(self.get("password_hash"))

    def set_password(self, password):
        self.set("password_hash", hash_password(password) if password else "")

    def check_password(self, password):
        return verify_password(self.get("password_hash"), password)


# ---------------------------------------------------------------- 设备禁用记录
def device_state_path():
    return os.path.join(data_dir(), DEVICE_STATE_FILE)


def load_disabled_devices():
    """读出"被本程序禁用过、还没恢复"的设备实例 ID 列表。"""
    try:
        with open(device_state_path(), "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(raw, dict):
        return []
    items = raw.get("disabled") or []
    if not isinstance(items, list):
        return []
    return [str(item) for item in items]


def save_disabled_devices(instance_ids):
    try:
        _atomic_write(
            device_state_path(),
            json.dumps(
                {"disabled": list(instance_ids), "updated": time.time()},
                ensure_ascii=False,
                indent=2,
            ),
        )
        return True
    except OSError:
        return False


def clear_disabled_devices():
    try:
        os.remove(device_state_path())
    except OSError:
        pass
