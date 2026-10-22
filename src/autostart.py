# -*- coding: utf-8 -*-
"""开机自启动：写入 HKCU\\...\\Run 注册表项（当前用户，无需管理员权限）。

v10 D1（反馈 4）：值名随产品名改为 `PhoneDesktop`。旧值名（`LEGACY_APP_NAME`）
在启动时清掉——它可能指向已被删掉的旧安装目录，
留着就是一条"开机尝试启动一个不存在的程序"的死记录。
"""
import os
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "PhoneDesktop"
LEGACY_APP_NAME = "DesktopOrganizerDemo"


def _command() -> str:
    """生成开机启动命令：打包后指向 exe，开发态指向 python + main.py。"""
    if getattr(sys, "frozen", False):
        return '"%s"' % sys.executable
    script = os.path.abspath(sys.argv[0])
    return '"%s" "%s"' % (sys.executable, script)


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_enabled(on: bool):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass


def drop_legacy() -> bool:
    """删掉改名前的 Run 值（幂等）。返回是否真的删了东西。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, LEGACY_APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def sync_on_startup(storage):
    """设置中开启了自启但注册表项丢失（如换目录运行）时自动修复。"""
    try:
        drop_legacy()
    except Exception:
        pass
    try:
        if storage.get_setting("autostart") and not is_enabled():
            set_enabled(True)
    except Exception:
        pass
