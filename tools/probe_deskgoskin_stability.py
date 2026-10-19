# -*- coding: utf-8 -*-
"""实验：隐藏 DeskGo TXMiniSkin 后轮询 12 秒，看它是否抢回 / 重建。
结束无条件恢复。
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


def defview():
    progman = int(user32.FindWindowW("Progman", None) or 0)
    c = user32.GetWindow(progman, GW_CHILD)
    while c:
        if cls(c) == "SHELLDLL_DefView":
            return int(c)
        c = user32.GetWindow(c, GW_HWNDNEXT)
    return 0


def skins():
    """DefView 下全部 TXMiniSkin（可能重建出新窗口）。"""
    out = []
    dv = defview()
    if not dv:
        return out
    g = user32.GetWindow(dv, GW_CHILD)
    while g:
        if cls(g) == "TXMiniSkin":
            out.append(int(g))
        g = user32.GetWindow(g, GW_HWNDNEXT)
    return out


targets = skins()
print("初始 TXMiniSkin:", targets)
try:
    for h in targets:
        user32.ShowWindow(h, SW_HIDE)
    for i in range(13):
        cur = skins()
        vis = [(h, bool(user32.IsWindowVisible(h))) for h in cur]
        print("  t=%2ds 现有skin=%s" % (i, vis))
        time.sleep(1)
finally:
    for h in skins():
        user32.ShowWindow(h, SW_SHOW)
    print("已恢复:", [(h, bool(user32.IsWindowVisible(h))) for h in skins()])
