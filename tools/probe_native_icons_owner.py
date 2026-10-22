# -*- coding: utf-8 -*-
"""只读探针：确认桌面图标宿主窗口归属进程 + 原生图标当前可见性。"""
import ctypes
import sys
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindow.restype = wintypes.HWND
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

GW_CHILD, GW_HWNDNEXT = 5, 2
LVM_GETITEMCOUNT = 0x1004
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def cls(h):
    b = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, b, 256)
    return b.value


def pid_of(h):
    p = wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(p))
    return p.value


def exe_of(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return "?"
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return "?"
    finally:
        kernel32.CloseHandle(h)


progman = int(user32.FindWindowW("Progman", None) or 0)
dv = lv = 0
c = user32.GetWindow(progman, GW_CHILD)
while c:
    if cls(c) == "SHELLDLL_DefView":
        dv = int(c)
    c = user32.GetWindow(c, GW_HWNDNEXT)

if dv:
    c = user32.GetWindow(dv, GW_CHILD)
    while c:
        if cls(c) == "SysListView32":
            lv = int(c)
        print("DefView child:", int(c), cls(c), "pid=", pid_of(c), exe_of(pid_of(c)))
        c = user32.GetWindow(c, GW_HWNDNEXT)

print()
print("DefView", dv, "pid=", pid_of(dv) if dv else 0, exe_of(pid_of(dv)) if dv else "")
if lv:
    print("ListView", lv, "pid=", pid_of(lv), exe_of(pid_of(lv)))
    print("  visible      =", bool(user32.IsWindowVisible(lv)))
    print("  item_count   =", user32.SendMessageW(lv, LVM_GETITEMCOUNT, 0, 0))
else:
    print("!! 没找到 SysListView32")
print()
print("当前 PhoneDesktop 进程：")
import subprocess
subprocess.run(["tasklist", "/FI", "IMAGENAME eq PhoneDesktop.exe"])
