# -*- coding: utf-8 -*-
"""开机自启动：写入 HKCU\\...\\Run 注册表项（当前用户，无需管理员权限）。"""
import os
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "DesktopOrganizerDemo"


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


def sync_on_startup(storage):
    """设置中开启了自启但注册表项丢失（如换目录运行）时自动修复。"""
    try:
        if storage.get_setting("autostart") and not is_enabled():
            set_enabled(True)
    except Exception:
        pass
