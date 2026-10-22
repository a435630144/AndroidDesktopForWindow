# -*- coding: utf-8 -*-
"""探针十二：整理模式下全屏网格采样，找出我方窗口不可命中的区域。

用法：进入整理模式 -> 每 80px 物理采样 WindowFromPoint -> 报告非我方窗口的点。
"""
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

from src import appsource, win32_layer  # noqa: E402
from src.desktop_window import DesktopWindow  # noqa: E402
from src.storage import Storage  # noqa: E402

STATE_PATH = Path(os.path.expandvars(r"%APPDATA%\PhoneDesktop\state.json"))
STATE_BACKUP = None

u32 = ctypes.windll.user32
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetClassNameW.restype = ctypes.c_int
u32.WindowFromPoint.argtypes = [wintypes.POINT]
u32.WindowFromPoint.restype = wintypes.HWND
u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.GetWindowRect.restype = wintypes.BOOL
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.IsWindowVisible.restype = wintypes.BOOL
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
SHELL_CLASSES = {"Progman", "WorkerW", "Windows.UI.Core.CoreWindow", "Shell_TrayWnd",
                 "Shell_SecondaryTrayWnd", "DV2ControlHost", "Button", "IME",
                 "MSCTFIME UI", "SysShadow", "tooltips_class32"}
MOVED = []


def p(msg):
    print("    %s" % msg, flush=True)


def describe(h):
    if not h:
        return "0"
    cls = ctypes.create_unicode_buffer(128)
    u32.GetClassNameW(wintypes.HWND(h), cls, 128)
    return "hwnd=%d(%s)" % (h, cls.value)


def wfp(x, y):
    pt = wintypes.POINT(x, y)
    return int(u32.WindowFromPoint(pt) or 0)


def _pid_of(hwnd):
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return pid.value


def _protected_pids():
    k = ctypes.windll.kernel32
    pids = {os.getpid()}
    TH32CS_SNAPPROCESS = 0x2

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.CHAR * 260)]

    table = {}
    snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    ok = k.Process32First(snap, ctypes.byref(entry))
    while ok:
        table[entry.th32ProcessID] = entry.th32ParentProcessID
        ok = k.Process32Next(snap, ctypes.byref(entry))
    k.CloseHandle(snap)
    cur = os.getpid()
    while cur in table and table[cur] and cur not in pids:
        pids.add(cur)
        cur = table[cur]
    return pids


def minimize_others():
    """【安全禁令·2026-10-17】绝不移动/最小化/关闭用户的任何窗口。
    事故：探针为"清理测试环境"把用户窗口移到屏幕外，进程被 SIGTERM 时
    还原代码没跑，导致用户 Edge/Chrome/微信等全部滞留屏幕外无法使用。
    测试点被占用时用实时选点（参考 probe9.driver_band）或跳过场景，
    永远不要动用户的窗口。"""
    return []


def restore_others(moved):
    for hwnd, (l, t, r, b) in moved:
        try:
            u32.SetWindowPos(wintypes.HWND(hwnd), None, l, t, r - l, b - t,
                             0x0001 | 0x0004 | 0x0010)
        except Exception:
            pass
    p("[环境] 还原 %d 个窗口" % len(moved))


def main():
    global STATE_BACKUP, MOVED
    if STATE_PATH.exists():
        STATE_BACKUP = STATE_PATH.read_bytes()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    storage = Storage()
    storage.migrate_to_native_mode()

    desktop = appsource.shell_known_folder("desktop")
    jpg = lnk = None
    try:
        for n in sorted(os.listdir(desktop)):
            if jpg is None and n.lower().endswith(".jpg"):
                jpg = os.path.join(desktop, n)
            if lnk is None and n.lower().endswith(".lnk"):
                lnk = os.path.join(desktop, n)
    except Exception:
        pass
    storage._data["layout"] = []
    if jpg:
        storage.add_app(appsource.desktop_file_entry(jpg), col=0, row=0)
    if lnk:
        storage.add_app(appsource.desktop_file_entry(lnk), col=1, row=0)
    storage.save()

    window = DesktopWindow(storage)
    window.show_desktop()

    def run():
        time.sleep(0.3)
        MOVED = minimize_others()
        time.sleep(0.5)
        storage.set_setting("hide_native_icons", True)
        storage.set_setting("auto_clone_desktop", True)
        window.apply_native_icons_setting()
        time.sleep(0.6)
        window.rebuild()
        time.sleep(0.4)

        mh = int(window.winId())
        r = wintypes.RECT()
        u32.GetWindowRect(wintypes.HWND(mh), ctypes.byref(r))
        p("主窗口=%d rect=(%d,%d,%d,%d)" % (mh, r.left, r.top, r.right, r.bottom))

        bad = []
        total = 0
        step = 80
        for y in range(r.top + 20, r.bottom - 20, step):
            for x in range(r.left + 20, r.right - 20, step):
                total += 1
                h = wfp(x, y)
                if h != mh:
                    cls = ctypes.create_unicode_buffer(128)
                    if h:
                        u32.GetClassNameW(wintypes.HWND(h), cls, 128)
                    bad.append((x, y, h, cls.value))
        p("网格采样 %d 点，非我方窗口 %d 点：" % (total, len(bad)))
        for (x, y, h, c) in bad[:60]:
            p("  (%d,%d) -> hwnd=%d(%s) pid=%d" % (x, y, h, c, _pid_of(h) if h else 0))
        if not bad:
            p("  ✓ 全部命中我方窗口")
        QTimer.singleShot(300, finish)

    def finish():
        try:
            restore_others(MOVED)
        except Exception:
            pass
        try:
            if STATE_BACKUP is not None:
                STATE_PATH.write_bytes(STATE_BACKUP)
            else:
                STATE_PATH.unlink(missing_ok=True)
        except Exception as e:
            print("state restore failed:", e)
        win32_layer.restore_native_icons()
        app.quit()

    QTimer.singleShot(1500, run)
    app.exec()


if __name__ == "__main__":
    main()
