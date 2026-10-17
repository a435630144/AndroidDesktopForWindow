# -*- coding: utf-8 -*-
"""只读探针：dump 桌面层 z-order 结构，坐实原生图标层与我方窗口的相对位置。"""
import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src import win32_layer  # noqa: E402
from src.storage import Storage  # noqa: E402
from src.desktop_window import DesktopWindow  # noqa: E402

u32 = ctypes.windll.user32
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetClassNameW.restype = ctypes.c_int
u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetWindowTextW.restype = ctypes.c_int
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.GetWindowThreadProcessId.restype = wintypes.DWORD
u32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
u32.GetWindow.restype = wintypes.HWND
u32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
u32.GetAncestor.restype = wintypes.HWND
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.IsWindowVisible.restype = wintypes.BOOL
GA_PARENT, GW_CHILD, GW_HWNDNEXT = 1, 5, 2


def desc(h):
    cls = ctypes.create_unicode_buffer(128)
    u32.GetClassNameW(wintypes.HWND(h), cls, 128)
    txt = ctypes.create_unicode_buffer(120)
    u32.GetWindowTextW(wintypes.HWND(h), txt, 120)
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(wintypes.HWND(h), ctypes.byref(pid))
    vis = "V" if u32.IsWindowVisible(h) else "h"
    return "hwnd=%-10d cls=%-28s title=%-24s pid=%-6d %s" % (
        h, cls.value, txt.value[:24], pid.value, vis)


def main():
    app = QApplication([])
    storage = Storage()
    storage.migrate_to_native_mode()
    window = DesktopWindow(storage)
    window.show_desktop()

    def run():
        time.sleep(0.3)
        progman = win32_layer._progman()
        wins = win32_layer._enum_zorder()
        total = len(wins)
        print("z-order 总数=%d，Progman 索引=%d" % (total, wins.index(progman)), flush=True)
        print("\n==== Progman 以上的全部窗口（桌面带区域） ====", flush=True)
        for i, h in enumerate(wins[:wins.index(progman)]):
            print("  [%3d] %s" % (i, desc(h)), flush=True)
        print("\n==== Progman 及以下（桌面层根部） ====", flush=True)
        for i, h in enumerate(wins[wins.index(progman):]):
            print("  [%3d] %s" % (wins.index(progman) + i, desc(h)), flush=True)

        # 枚举 Progman 的子孙窗口
        print("\n==== Progman 子窗口树 ====", flush=True)

        def walk(parent, depth=0):
            h = u32.GetWindow(parent, GW_CHILD)
            while h:
                print("  %s%s" % ("  " * depth, desc(int(h))), flush=True)
                walk(int(h), depth + 1)
                h = u32.GetWindow(h, GW_HWNDNEXT)

        walk(progman)

        # 所有 WorkerW 的子窗口树
        print("\n==== 全部 WorkerW 子窗口树 ====", flush=True)
        h = u32.GetWindow(u32.GetDesktopWindow(), GW_CHILD)
        while h:
            cls = ctypes.create_unicode_buffer(128)
            u32.GetClassNameW(h, cls, 128)
            if cls.value == "WorkerW":
                print("WorkerW: %s" % desc(int(h)), flush=True)
                walk(int(h), 1)
            h = u32.GetWindow(h, GW_HWNDNEXT)

        # 找到可交互的 SysListView32，看它的祖先链
        print("\n==== SysListView32 祖先链 ====", flush=True)

        def find_lv(parent, out):
            h = u32.GetWindow(parent, GW_CHILD)
            while h:
                cls = ctypes.create_unicode_buffer(128)
                u32.GetClassNameW(h, cls, 128)
                if cls.value == "SysListView32":
                    out.append(int(h))
                find_lv(int(h), out)
                h = u32.GetWindow(h, GW_HWNDNEXT)

        lvs = []
        find_lv(progman, lvs)
        h = u32.GetWindow(u32.GetDesktopWindow(), GW_CHILD)
        while h:
            cls = ctypes.create_unicode_buffer(128)
            u32.GetClassNameW(h, cls, 128)
            if cls.value == "WorkerW":
                find_lv(int(h), lvs)
            h = u32.GetWindow(h, GW_HWNDNEXT)
        for lv in lvs:
            chain = []
            cur = lv
            while cur:
                chain.append(int(cur))
                cur = u32.GetAncestor(cur, GA_PARENT)
            print("  SysListView32=%d 祖先链: %s" % (lv, chain), flush=True)
            for c in chain:
                if c in wins:
                    print("    %s  z-index=%d/%d" % (desc(c), wins.index(c), total),
                          flush=True)
        # 我方窗口位置
        mh = int(window.winId())
        print("\n我方主窗口: %s z-index=%s" % (desc(mh),
                                              wins.index(mh) if mh in wins else "不在"),
              flush=True)
        app.quit()

    QTimer.singleShot(1500, run)
    app.exec()


if __name__ == "__main__":
    main()
