# -*- coding: utf-8 -*-
"""只读探针：Dump 桌面图标宿主窗口链的真实状态。

用途：确认「隐藏原生图标」到底藏没藏对窗口。
不移动、不关闭、不显示/隐藏任何窗口——纯 Get* 查询。

用法：python tools/probe_native_icons.py
"""
import ctypes
import sys
from ctypes import wintypes

user32 = ctypes.windll.user32

user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.GetWindow.restype = wintypes.HWND
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowLongW.restype = wintypes.LONG
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

GW_CHILD, GW_HWNDNEXT = 5, 2
GWL_STYLE = -16
WS_VISIBLE = 0x10000000
LVM_GETITEMCOUNT = 0x1000 + 4


def cls(h):
    b = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, b, 256)
    return b.value


def txt(h):
    b = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(h, b, 512)
    return b.value


def rect(h):
    r = wintypes.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def children(h):
    out, c = [], user32.GetWindow(h, GW_CHILD)
    while c:
        out.append(int(c))
        c = user32.GetWindow(c, GW_HWNDNEXT)
    return out


def describe(h, depth=0):
    st = user32.GetWindowLongW(h, GWL_STYLE) & 0xFFFFFFFF
    vis = bool(user32.IsWindowVisible(h))
    style_vis = bool(st & WS_VISIBLE)
    extra = ""
    if cls(h) == "SysListView32":
        n = user32.SendMessageW(h, LVM_GETITEMCOUNT, 0, 0)
        extra = " items=%s" % n
    print("%s[%s] class=%-20s vis=%s(style=%s) rect=%s%s" % (
        "  " * depth, h, cls(h), vis, style_vis, rect(h), extra))
    for c in children(h):
        describe(c, depth + 1)


def main():
    progman = int(user32.FindWindowW("Progman", None) or 0)
    print("Progman =", progman, cls(progman))
    print("---- Progman 子树 ----")
    if progman:
        for c in children(progman):
            describe(c, 1)
    print()
    print("---- 全部顶层 WorkerW ----")
    h = user32.GetWindow(user32.GetDesktopWindow(), GW_CHILD)
    idx = 0
    while h:
        if cls(h) == "WorkerW":
            print("WorkerW", int(h), rect(h))
            for c in children(h):
                describe(c, 1)
            idx += 1
        h = user32.GetWindow(h, GW_HWNDNEXT)
    print("WorkerW 总数 =", idx)
    print()
    print("---- 我们的进程窗口 ----")
    # 按类名含 Qt 的顶层窗口列出（不区分进程，够用）
    h = user32.GetWindow(user32.GetDesktopWindow(), GW_CHILD)
    while h:
        if "Qt" in cls(h):
            print("  Qt window", int(h), rect(h), repr(txt(h)))
        h = user32.GetWindow(h, GW_HWNDNEXT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
