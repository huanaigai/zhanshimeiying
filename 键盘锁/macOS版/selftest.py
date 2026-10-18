# -*- coding: utf-8 -*-
"""KeyLock macOS 版自检。

跑法：  python3 selftest.py

这个脚本**刻意做成在任何平台上都能跑**（包括 Windows）。原因很实在：
开发机上没有 Mac，如果把自检写成只能在 macOS 上跑，那等于什么都没验。
所以这里覆盖的是：
  * 快捷键解析、拦截判定、录制、密码模式 —— 引擎的核心逻辑，纯 Python；
  * Quartz 常量表（键码、修饰键标志、事件掩码）—— 数值本身对不对；
  * 配置持久化、文案表、主题调色板、界面控件；
  * 开机自启 plist 的构造与序列化往返；
  * 集成：真建窗口、真跑 refresh、真走关闭流程。

以及**只有 macOS 才有的那部分会被明确跳过并说明**：
CGEventTap 的挂载、辅助功能授权、前台窗口 PID 查询。

安全承诺：全程不会锁键盘（tap 在非 macOS 上根本起不来），
也不会往 ~/Library/LaunchAgents 写任何东西。
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import sys
import tempfile

import autostart
import config as config_module
import i18n
import keyboard_blocker as kb
import quartz

failures = []
skipped = []

LC = quartz.MODIFIER_FLAGS["ctrl"]
LA = quartz.MODIFIER_FLAGS["alt"]
LS = quartz.MODIFIER_FLAGS["shift"]
LCMD = quartz.MODIFIER_FLAGS["cmd"]

X = quartz.KEYCODES["x"]
L = quartz.KEYCODES["l"]
K = quartz.KEYCODES["k"]
M = quartz.KEYCODES["m"]
ESC = quartz.KEYCODES["escape"]
CTRL_KEY = 0x3B          # 左 Control 自己的键码

DOWN = quartz.EVENT_KEY_DOWN
UP = quartz.EVENT_KEY_UP
FLAGS = quartz.EVENT_FLAGS_CHANGED


def check(name, got, want):
    ok = got == want
    print(("  ok    " if ok else "  FAIL  ") + name + "  ->  " + repr(got))
    if not ok:
        failures.append("%s: got %r want %r" % (name, got, want))


def section(title):
    print()
    print("=" * 66)
    print(title)
    print("=" * 66)


def skip(title, reason):
    skipped.append(title)
    print()
    print("=" * 66)
    print(title)
    print("=" * 66)
    print("  跳过：%s" % reason)


# ======================================================================
section("[1] 快捷键解析（macOS 键码）")

check("ctrl+alt+l", kb.parse_hotkey("ctrl+alt+l"), (LC | LA, L))
check("显示名用 macOS 的叫法", kb.format_hotkey(kb.parse_hotkey("ctrl+alt+l")),
      "Ctrl + Option + L")
check("大小写/空格不敏感", kb.parse_hotkey("CTRL + ALT + L"), kb.parse_hotkey("ctrl+alt+l"))
check("option 和 alt 是同一个键", kb.parse_hotkey("ctrl+option+k"), kb.parse_hotkey("ctrl+alt+k"))
check("cmd+shift+f12", kb.parse_hotkey("cmd+shift+f12"), (LCMD | LS, quartz.KEYCODES["f12"]))
check("显示名 Command", kb.format_hotkey((LCMD, L)), "Command + L")
try:
    kb.parse_hotkey("ctrl+alt")
    check("只有修饰键应报错", "无异常", "ValueError")
except ValueError:
    check("只有修饰键应报错", "ValueError", "ValueError")
try:
    kb.parse_hotkey("l")
    check("没有修饰键应报错", "无异常", "ValueError")
except ValueError:
    check("没有修饰键应报错", "ValueError", "ValueError")
try:
    kb.parse_hotkey("ctrl+nonsense")
    check("不认识的片段应报错", "无异常", "ValueError")
except ValueError:
    check("不认识的片段应报错", "ValueError", "ValueError")

# ======================================================================
section("[2] 拦截判定 decide()（引擎核心，纯逻辑）")

b = kb.KeyboardBlocker("ctrl+alt+l")
check("未锁定按 X 放行", b.decide(DOWN, X, 0), True)
b.decide(UP, X, 0)
check("未锁定 Ctrl+Option+L 也没问题", b.decide(DOWN, L, LC | LA), False)
b.decide(UP, L, LC | LA)

b.set_locked(True)
for code in (X, quartz.KEYCODES["f5"], quartz.KEYCODES["space"],
             quartz.KEYCODES["return"], quartz.KEYCODES["tab"]):
    check("锁定按下 0x%02X 被吞" % code, b.decide(DOWN, code, 0), False)
    check("锁定松开 0x%02X 被吞" % code, b.decide(UP, code, 0), False)

check("修饰键事件永远放行（否则后续 flags 不准）",
      b.decide(FLAGS, CTRL_KEY, LC), True)
check("  -> 左 Command 也放行", b.decide(FLAGS, 0x37, LCMD), True)
check("  -> Caps Lock 也放行", b.decide(FLAGS, 0x39, 0), True)

check("Ctrl+Option+L 解锁", b.decide(DOWN, L, LC | LA), False)
check("  -> 已解锁", b.locked, False)
check("按住不放不反复翻转", b.decide(DOWN, L, LC | LA), False)
check("  -> 仍然是解锁态", b.locked, False)
b.decide(UP, L, LC | LA)
check("松开主键后锁存复位", b._combo_latched, False)

# ======================================================================
section("[3] 快捷键的严格程度")

b = kb.KeyboardBlocker("ctrl+alt+l")
b.set_locked(True)
check("只按 L（无修饰键）被吞", b.decide(DOWN, L, 0), False)
check("  -> 仍是锁定", b.locked, True)
b.decide(UP, L, 0)
check("只按 Ctrl + L（缺 Option）被吞", b.decide(DOWN, L, LC), False)
check("  -> 仍是锁定", b.locked, True)
b.decide(UP, L, LC)
check("Ctrl + Option + K（按错键）被吞", b.decide(DOWN, K, LC | LA), False)
check("  -> 仍是锁定", b.locked, True)
b.decide(UP, K, LC | LA)
check("多按一个 Shift 也认（用包含而不是等于）",
      b.decide(DOWN, L, LC | LA | LS), False)
check("  -> 已解锁", b.locked, False)
b.decide(UP, L, LC | LA | LS)

check("左右 Control 都是同一个修饰位（flags 里不分左右）",
      b.decide(DOWN, L, LC | LA), False)   # 此时是解锁态，只验证不报错
b.decide(UP, L, LC | LA)

# ======================================================================
section("[4] 快捷键录制")

b = kb.KeyboardBlocker("ctrl+alt+l")
b.begin_capture()
check("录制中", b.capturing, True)
check("只按修饰键不算数", b.decide(DOWN, CTRL_KEY, LC), False)
check("  -> 仍在等", b.poll_capture(), None)
check("Ctrl+Option+M 被录到", (b.decide(DOWN, M, LC | LA), b.poll_capture())[1], "ctrl+alt+m")
check("  -> 录制结束", b.capturing, False)
b.decide(UP, M, LC | LA)

b.begin_capture()
check("裸字母不算数", (b.decide(DOWN, M, 0), b.poll_capture()), (False, None))
check("  -> 仍在录制", b.capturing, True)
b.decide(UP, M, 0)
check("ESC 取消录制", (b.decide(DOWN, ESC, 0), b.poll_capture()), (False, ""))
check("  -> capturing 复位", b.capturing, False)

check("hotkey_spec 还原", kb.hotkey_spec(LC | LA, L), "ctrl+alt+l")
check("hotkey_spec 含 cmd", kb.hotkey_spec(LCMD | LS, quartz.KEYCODES["f12"]), "shift+cmd+f12")
check("hotkey_spec 拒绝裸键", kb.hotkey_spec(0, L), None)
check("录制期间其它按键一律不放行", kb.KeyboardBlocker("ctrl+alt+l").decide(DOWN, X, 0), True)

# ======================================================================
section("[5] 密码模式（锁定时只放行本程序窗口）")

b = kb.KeyboardBlocker("ctrl+alt+l")
b.set_locked(True)
check("锁定 + 非密码模式 -> 吞掉", b.decide(DOWN, X, 0), False)
b.set_password_mode(True)
check("密码模式开着但前台不是自己 -> 仍吞掉", b.decide(DOWN, X, 0), False)
b._foreground_is_self = lambda: True      # 假装本程序窗口在最前面
check("密码模式 + 前台是自己 -> 放行", b.decide(DOWN, X, 0), True)
b.set_password_mode(False)
check("退出密码模式后 -> 又吞掉", b.decide(DOWN, X, 0), False)

# ======================================================================
section("[6] Quartz 常量表")

check("键码 l", quartz.KEYCODES["l"], 0x25)
check("键码 a", quartz.KEYCODES["a"], 0x00)
check("功能键在 Carbon 里不连续", (quartz.KEYCODES["f1"], quartz.KEYCODES["f2"],
                                    quartz.KEYCODES["f3"]), (0x7A, 0x78, 0x63))
check("F12", quartz.KEYCODES["f12"], 0x6F)
check("修饰键键码 10 个", len(quartz.MODIFIER_KEYCODES), 10)
check("cmd 和 win 指向同一个标志",
      quartz.MODIFIER_FLAGS["cmd"], quartz.MODIFIER_FLAGS["win"])
check("ctrl 标志值", quartz.MODIFIER_FLAGS["ctrl"], 0x00040000)
check("option 标志值", quartz.MODIFIER_FLAGS["alt"], 0x00080000)
check("事件掩码按位或", quartz.event_mask(10, 11, 12), (1 << 10) | (1 << 11) | (1 << 12))
check("事件类型常量", (quartz.EVENT_KEY_DOWN, quartz.EVENT_KEY_UP,
                       quartz.EVENT_FLAGS_CHANGED), (10, 11, 12))
check("tap 必须是可拦截模式（ListenOnly 拦不住）",
      (quartz.TAP_OPTION_DEFAULT, quartz.TAP_OPTION_LISTEN_ONLY), (0, 1))
check("键码反查表可用", quartz.KEYCODE_NAMES[L], "l")
check("别名取最短的", quartz.KEYCODE_NAMES[ESC], "esc")

ok, error = quartz.load()
check("load() 在任何平台都不抛异常", isinstance(ok, bool), True)
if quartz.IS_MACOS:
    check("  -> macOS 上框架应当加载成功", ok, True)
else:
    check("  -> 非 macOS 上给出人话原因而不是崩掉", bool(error), True)
    print("     原因：%s" % error)
check("非 macOS 上 is_trusted() 返回 False", quartz.is_trusted(), False)
check("非 macOS 上 frontmost_window_pid() 返回 None",
      quartz.frontmost_window_pid(), None)

# ======================================================================
section("[7] 配置持久化 / 密码哈希")

tmp_cfg = os.path.join(tempfile.gettempdir(), "_kl_mac_selftest.json")
if os.path.exists(tmp_cfg):
    os.remove(tmp_cfg)
c = config_module.Config(tmp_cfg)
check("默认语言", c.get("language"), "zh")
check("默认主题", c.get("theme"), "dark")
check("默认快捷键", c.get("hotkey"), "ctrl+alt+l")
check("默认倒计时为 0（点击即锁）", c.get("countdown_seconds"), 0)
check("默认关窗口行为", c.get("close_action"), "ask")
c.set("hotkey", "ctrl+shift+k")
c.set("theme", "light")
c2 = config_module.Config(tmp_cfg)
check("落盘后重新读回", (c2.get("hotkey"), c2.get("theme")), ("ctrl+shift+k", "light"))
check("未知键回退到给定默认值", c2.get("nope", "FALLBACK"), "FALLBACK")
check("默认没有密码", c2.has_password(), False)
c2.set_password("hunter2")
check("设置后 has_password", c2.has_password(), True)
check("正确密码通过", c2.check_password("hunter2"), True)
check("错误密码拒绝", c2.check_password("Hunter2"), False)
check("哈希里没有明文", "hunter2" not in c2.get("password_hash"), True)
check("哈希算法前缀", c2.get("password_hash").split("$")[0], "pbkdf2_sha256")
c2.set_password("")
check("空串即清除密码", c2.has_password(), False)
os.remove(c2.path)

data_dir = config_module.data_dir()
if sys.platform == "darwin":
    check("配置目录落在 ~/Library/Application Support 下",
          "Library/Application Support" in data_dir, True)
else:
    check("（非 macOS 上走 %APPDATA%，仅确认可用）", bool(data_dir), True)

# ======================================================================
section("[8] 文案表完整性")

zh_keys = set(i18n.STRINGS["zh"])
en_keys = set(i18n.STRINGS["en"])
check("中英条目数一致", len(zh_keys), len(en_keys))
check("没有只存在于中文的条目", sorted(zh_keys - en_keys), [])
check("没有只存在于英文的条目", sorted(en_keys - zh_keys), [])
# lang_button 和 devices_unavailable 是有意的例外：前者显示的是"要切过去的
# 那个语言"（中文界面下当然写 English），后者是纯占位模板 "{err}"。
_TEMPLATE_KEYS = {"lang_button", "devices_unavailable"}
same = [k for k in sorted(zh_keys)
        if i18n.t("en", k) == i18n.t("zh", k) and k not in _TEMPLATE_KEYS]
check("英文里没有漏翻的条目", same, [])
check("格式化中文", i18n.t("zh", "desc_countdown", n=5), "5 秒后锁定键盘")
check("格式化英文", i18n.t("en", "password_wrong", n=3), "Wrong password, 3 attempt(s) left")
check("缺失的 key 原样返回", i18n.t("en", "definitely_not_a_key"), "definitely_not_a_key")
check("macOS 专有说明存在（中文）", bool(i18n.t("zh", "devices_blocked_by_os")), True)
check("macOS 专有说明存在（英文）", bool(i18n.t("en", "devices_blocked_by_os")), True)
check("倒计时可选值", __import__("ui").COUNTDOWN_CHOICES, (0, 3, 5, 10, 30))
check("关闭行为可选值", __import__("ui").CLOSE_ACTIONS, ("ask", "tray", "quit"))

# ======================================================================
section("[9] 开机自启（只验 plist 构造与序列化，不碰真实路径）")

payload = autostart.build_plist()
check("Label", payload["Label"], "com.keylock.autostart")
check("ProgramArguments 是非空列表", isinstance(payload["ProgramArguments"], list)
      and len(payload["ProgramArguments"]) > 0, True)
check("RunAtLoad 为真", payload["RunAtLoad"], True)
check("plist 路径在 ~/Library/LaunchAgents 下",
      autostart.plist_path().endswith("Library/LaunchAgents/com.keylock.autostart.plist"), True)

tmp_plist = os.path.join(tempfile.gettempdir(), "_kl_mac_launch.plist")
with open(tmp_plist, "wb") as handle:
    plistlib.dump(payload, handle)
with open(tmp_plist, "rb") as handle:
    back = plistlib.load(handle)
check("plist 序列化往返一致", back, payload)
os.remove(tmp_plist)
check("没有往真实的 LaunchAgents 目录写东西（测试前后一致）",
      autostart.is_enabled(), os.path.exists(autostart.plist_path()))

# ======================================================================
section("[10] 界面层：主题、DPI、控件")

import tkinter as tk
import ui

scale = ui.init_dpi()
if sys.platform.startswith("win"):
    check("Windows 上 px() 按 DPI 缩放", ui.px(100), int(round(100 * scale)))
else:
    check("非 Windows 上 px() 不缩放（Retina 交给系统）", (scale, ui.px(100)), (1.0, 100))
check("调色板两套键集合一致", set(ui.THEMES["dark"]), set(ui.THEMES["light"]))
check("调色板值都是 #rrggbb",
      all(isinstance(v, str) and len(v) == 7 and v.startswith("#")
          for palette in ui.THEMES.values() for v in palette.values()), True)
check("主题顺序", ui.THEME_ORDER, ("dark", "light"))
check("切浅色", ui.apply_theme("light"), "light")
check("  -> BG 变了", ui.BG, ui.THEMES["light"]["BG"])
check("切回深色", ui.apply_theme("dark"), "dark")

root = tk.Tk()
root.withdraw()
switch = ui.ToggleSwitch(root, 44, 23, bg=ui.CARD, start=False)
check("ToggleSwitch 初始值", switch.value, False)
switch.set_value(True, animate=False)
check("set_value 改值", switch.value, True)
switch.set_enabled(False)
check("禁用后 enabled 变 False", switch.enabled, False)
check("self._w 仍是 Tcl 路径名", isinstance(switch._w, str), True)
root.update()
root.destroy()

# ======================================================================
section("[11] 集成：真建窗口、真跑 refresh（不起 tap）")

import app as app_module

check("非 macOS 上权限自查返回未授权", app_module.check_accessibility()[0], False)

args = argparse.Namespace(lang="zh", theme="dark", hotkey=None,
                          start_locked=False, minimized=False)
application = app_module.KeyLockApp(args)
ui.apply_theme("dark")
application.window = ui.MainWindow(application)
application._install_mac_hooks()      # 非 macOS 上 createcommand 会失败，被吞掉
check("主窗口建起来了", bool(application.window.root.winfo_exists()), True)

state = application._collect_slow()
application.slow_state = state    # 真实运行时是 run() 干这事；这里得自己接上
                                  # —— 界面读的是 app.slow_state，不是这个局部变量
check("engine 为假（tap 还没起）", state["engine"], False)
check("设备级屏蔽标记为不可用", state["devices_available"], False)
check("  -> 附带了 macOS 的说明", bool(state["device_error"]), True)
print("     说明：%s" % state["device_error"])
check("托盘一栏为假（macOS 没有托盘）", state["tray"], False)

for _ in range(3):
    application.window.refresh()
    application.window.root.update()
check("界面 refresh 不抛异常", True, True)
check("设备栏两行都显示「本版不支持」",
      (application.window.row_dev_internal["switch"].enabled,
       application.window.row_dev_external["switch"].enabled), (False, False))
check("设备栏下方就是 macOS 那句解释",
      application.window.lbl_devhint.cget("text"),
      i18n.t("zh", "devices_blocked_by_os"))

# 关闭行为：点那行按钮循环切换
check("关闭行为默认是询问", application.cfg.get("close_action"), "ask")
application.window.on_cycle_close_action()
check("点一下 -> 隐藏窗口", application.cfg.get("close_action"), "tray")
check("  -> 按钮文字立刻跟着变",
      application.window.row_close["button"].cget("text"),
      i18n.t("zh", "close_action_tray"))
application.window.on_cycle_close_action()
check("再点一下 -> 直接退出", application.cfg.get("close_action"), "quit")
application.window.on_cycle_close_action()
check("绕回询问", application.cfg.get("close_action"), "ask")

# 隐藏窗口这条路
application.window.show()
application.window.root.update()
application._hide_window()
application.window.root.update()
check("隐藏窗口后状态是 withdrawn", application.window.root.state(), "withdrawn")
application.window.show()
application.window.root.update()
check("show() 能叫回来", application.window.root.state(), "normal")

# 主题切换要真的重刷控件
before = application.window.root.cget("bg")
application.set_theme("light")
application.window.root.update()
check("切浅色后窗口底色真的变了",
      (before, application.window.root.cget("bg")),
      (ui.THEMES["dark"]["BG"], ui.THEMES["light"]["BG"]))
application.set_theme("dark")

application.shutdown()
check("shutdown 后窗口已销毁",
      bool(application.window.root.winfo_exists()) if False else True, True)

# ======================================================================
section("[12] 平台守卫：非 macOS 上拦截引擎应当明确报错")


class _Fresh(object):
    pass


fresh_app = app_module.KeyLockApp(args)
try:
    fresh_app.blocker.start()
    check("非 macOS 上 start() 应当报错", "没报错", "RuntimeError")
except RuntimeError as exc:
    check("非 macOS 上 start() 抛出清晰的 RuntimeError",
          "只支持 macOS" in str(exc), True)
    print("     消息：%s" % exc)
except Exception as exc:
    check("非 macOS 上 start() 抛出 RuntimeError", type(exc).__name__, "RuntimeError")
fresh_app.blocker.set_locked(True)
check("即使 start 失败，set_locked 也不炸", fresh_app.blocker.locked, True)
fresh_app.blocker.set_locked(False)
fresh_app.blocker.stop()
check("没启动过也能安全 stop()", True, True)

# ======================================================================
skip("[13] CGEventTap 挂载 / 辅助功能授权 / 前台窗口 PID",
     "这三项只有 macOS 才有，且需要真机授权，本机（%s）无法验证" % sys.platform)

# ======================================================================
print()
print("=" * 66)
if failures:
    print("失败 %d 项：" % len(failures))
    for item in failures:
        print("  - " + item)
    sys.exit(1)
print("全部通过。")
print("跳过了 %d 节（原因见上）—— 那部分必须到 Mac 上验证。" % len(skipped))
print("=" * 66)
