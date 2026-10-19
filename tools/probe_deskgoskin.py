# -*- coding: utf-8 -*-
"""实验：临时隐藏 DeskGo 的 TXMiniSkin，看原生图标是否随之消失。

TXMiniSkin = 腾讯桌面整理（DesktopMgr64.exe）挂在 SHELLDLL_DefView 下的
全屏层。若它自己画了一份桌面图标，隐藏它就能区分「谁在画图标」。
结束无条件恢复（SW_SHOW）。
"""
import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.GetWindow.restype = wintypes.HWND
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]

GW_CHILD, GW_HWNDNEXT = 5, 2
SW_HIDE, SW_SHOW = 0, 5


def cls(h):
    b = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, b, 256)
    return b.value


def find_skin():
    progman = int(user32.FindWindowW("Progman", None) or 0)
    c = user32.GetWindow(progman, GW_CHILD)
    while c:
        if cls(c) == "SHELLDLL_DefView":
            g = user32.GetWindow(c, GW_CHILD)
            while g:
                if cls(g) == "TXMiniSkin":
                    return int(g)
                g = user32.GetWindow(g, GW_HWNDNEXT)
        c = user32.GetWindow(c, GW_HWNDNEXT)
    return 0


skin = find_skin()
print("TXMiniSkin =", skin)
if not skin:
    sys.exit(0)
try:
    user32.ShowWindow(skin, SW_HIDE)
    print("已隐藏，visible =", bool(user32.IsWindowVisible(skin)))
    time.sleep(1.2)
    import subprocess
    py = sys.executable
    subprocess.run([py, "tools/shot_once.py", "dist/shot_no_deskgoskin.png"])
finally:
    user32.ShowWindow(skin, SW_SHOW)
    print("已恢复，visible =", bool(user32.IsWindowVisible(skin)))
