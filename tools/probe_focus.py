# -*- coding: utf-8 -*-
"""一次性深度探针：便签窗口为何无法激活 / 获焦。

手段：
  1. 深度状态：GWL_STYLE（WS_DISABLED / WS_CHILD / WS_POPUP）、GWL_EXSTYLE、
     GWL_OWNER 属主窗口、IsWindowEnabled、DWM cloaked、GUI 线程信息
  2. WH_CALLWNDPROC 线程钩子：记录便签窗口与主窗口在真实点击前后的
     完整消息流（WM_MOUSEACTIVATE / WM_ACTIVATE / WM_SETFOCUS /
     WM_WINDOWPOSCHANGING+CHANGED / WM_NCHITTEST ...）
  3. 真实鼠标点击便签中心，然后对比 GetForegroundWindow / GetActiveWindow /
     Qt 层 isActiveWindow / focusWidget
  4. 手动 SetForegroundWindow / SetActiveWindow + GetLastError
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src import win32_layer  # noqa: E402
from src.desktop_window import DesktopWindow  # noqa: E402
from src.storage import Storage  # noqa: E402
from src.widget_layer import WidgetLayer  # noqa: E402

STATE_PATH = Path(os.path.expandvars(r"%APPDATA%\DesktopOrganizerDemo\state.json"))
STATE_BACKUP = None

u32 = ctypes.windll.user32
u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
u32.GetWindowLongW.restype = wintypes.LONG
u32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
u32.GetWindow.restype = wintypes.HWND
u32.IsWindowEnabled.argtypes = [wintypes.HWND]
u32.IsWindowEnabled.restype = wintypes.BOOL
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.IsWindowVisible.restype = wintypes.BOOL
u32.GetForegroundWindow.restype = wintypes.HWND
u32.GetActiveWindow.restype = wintypes.HWND
u32.SetActiveWindow.argtypes = [wintypes.HWND]
u32.SetActiveWindow.restype = wintypes.HWND
u32.SetForegroundWindow.argtypes = [wintypes.HWND]
u32.SetForegroundWindow.restype = wintypes.BOOL
k32 = ctypes.windll.kernel32
k32.GetLastError.restype = wintypes.DWORD
u32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u32.SetCursorPos.restype = wintypes.BOOL
u32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                            wintypes.DWORD, ctypes.c_void_p]
u32.WindowFromPoint.argtypes = [wintypes.POINT]
u32.WindowFromPoint.restype = wintypes.HWND
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.GetWindowThreadProcessId.restype = wintypes.DWORD
k32.GetCurrentThreadId.restype = wintypes.DWORD
u32.SetWindowsHookExW.restype = wintypes.HHOOK
u32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p,
                                  wintypes.HINSTANCE, wintypes.DWORD]
u32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
u32.UnhookWindowsHookEx.restype = wintypes.BOOL
u32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
u32.CallNextHookEx.restype = wintypes.LPARAM
u32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.c_void_p]
u32.GetGUIThreadInfo.restype = wintypes.BOOL

WM_MOUSEACTIVATE, WM_ACTIVATE, WM_SETFOCUS, WM_KILLFOCUS = 0x21, 0x1C, 0x07, 0x08
WM_NCHITTEST, WM_MOUSEMOVE = 0x84, 0x200
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x201, 0x202
WM_WINDOWPOSCHANGING, WM_WINDOWPOSCHANGED = 0x46, 0x47
WM_ACTIVATEAPP = 0x1C
WM_NCMOUSEMOVE = 0xA0
GWL_STYLE, GWL_EXSTYLE, GWL_OWNER = -16, -20, 4
WH_CALLWNDPROC = 4
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x2, 0x4

WS_DISABLED = 0x08000000
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000

MSG_NAMES = {0x01: "WM_CREATE", 0x05: "WM_SIZE", WM_ACTIVATE: "WM_ACTIVATE",
             0x1C: "WM_ACTIVATEAPP", WM_SETFOCUS: "WM_SETFOCUS",
             WM_KILLFOCUS: "WM_KILLFOCUS", 0x14: "WM_ERASEBKGND",
             WM_NCHITTEST: "WM_NCHITTEST", WM_MOUSEACTIVATE: "WM_MOUSEACTIVATE",
             0x20: "WM_SETCURSOR", WM_MOUSEMOVE: "WM_MOUSEMOVE",
             WM_NCMOUSEMOVE: "WM_NCMOUSEMOVE", WM_LBUTTONDOWN: "WM_LBUTTONDOWN",
             WM_LBUTTONUP: "WM_LBUTTONUP", 0x46: "WM_WINDOWPOSCHANGING",
             0x47: "WM_WINDOWPOSCHANGED", 0x83: "WM_NCPAINT", 0x85: "WM_DRAWITEM"}


class CWPSTRUCT(ctypes.Structure):
    _fields_ = [("lParam", wintypes.LPARAM), ("wParam", wintypes.WPARAM),
                ("message", wintypes.UINT), ("hwnd", wintypes.HWND)]


class WINDOWPOS(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("hwndInsertAfter", wintypes.HWND),
                ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("cx", ctypes.c_int), ("cy", ctypes.c_int),
                ("flags", wintypes.UINT)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]


LOG = []
WATCH = set()
HOOK_REF = None


def hwnd_str(h):
    return str(int(h)) if h else "0"


def hook_proc(nCode, wParam, lParam):
    try:
        cwp = ctypes.cast(lParam, ctypes.POINTER(CWPSTRUCT)).contents
        h = int(cwp.hwnd or 0)
        if h in WATCH and nCode >= 0:
            m = int(cwp.message)
            name = MSG_NAMES.get(m, hex(m))
            extra = ""
            if m in (WM_WINDOWPOSCHANGING, WM_WINDOWPOSCHANGED):
                wp = ctypes.cast(cwp.lParam, ctypes.POINTER(WINDOWPOS)).contents
                flags = int(wp.flags)
                swp = []
                if flags & 0x0001: swp.append("NOSIZE")
                if flags & 0x0002: swp.append("NOMOVE")
                if flags & 0x0004: swp.append("NOZORDER")
                if flags & 0x0010: swp.append("NOACTIVATE")
                if flags & 0x0100: swp.append("NOOWNERZORDER")
                if flags & 0x0200: swp.append("NOSENDCHANGING")
                if flags & 0x00100: swp.append("SHOWWINDOW")
                if flags & 0x0080: swp.append("HIDEWINDOW")
                extra = " insertAfter=%d flags=0x%x[%s]" % (
                    int(wp.hwndInsertAfter or 0), flags, "|".join(swp) or "0")
            elif m == WM_MOUSEACTIVATE:
                ma = int(cwp.lParam & 0xFFFF)  # hittest 在低位？实际 MAKELONG(hittest, mouse)
                ma_ret = int(cwp.lParam >> 16) & 0xFFFF
                extra = " (wParam=top=%s lParam=%s)" % (hwnd_str(cwp.wParam), cwp.lParam)
            elif m in (WM_ACTIVATE, WM_ACTIVATEAPP):
                extra = " wParam=%s lParam=%s" % (hwnd_str(cwp.wParam), cwp.lParam)
            elif m in (WM_SETFOCUS, WM_KILLFOCUS):
                extra = " -> %s" % hwnd_str(cwp.wParam)
            elif m == WM_NCHITTEST:
                extra = " x=%d y=%d ret=%d" % (
                    int(cwp.lParam & 0xFFFF), int((cwp.lParam >> 16) & 0xFFFF),
                    int(cwp.lParam >> 32) if False else 0)
            LOG.append("%-20s hwnd=%-8s%s" % (name, hwnd_str(h), extra))
    except Exception as e:
        LOG.append("hook err: %r" % e)
    return u32.CallNextHookEx(None, nCode, wParam, lParam)


def dump_state(tag, hwnd):
    style = u32.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF
    ex = u32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
    owner = int(u32.GetWindow(hwnd, GWL_OWNER) or 0)
    parent = int(u32.GetWindow(hwnd, 1) or 0)  # GA_PARENT
    enabled = bool(u32.IsWindowEnabled(hwnd))
    vis = bool(u32.IsWindowVisible(hwnd))
    tid = u32.GetWindowThreadProcessId(hwnd, None)
    cloaked = ctypes.c_ulong(0)
    dwm = ctypes.windll.dwmapi
    dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, ctypes.c_uint,
                                          ctypes.c_void_p, ctypes.c_uint]
    hr = dwm.DwmGetWindowAttribute(wintypes.HWND(hwnd), 14, ctypes.byref(cloaked), 4)
    s = []
    if style & WS_DISABLED: s.append("WS_DISABLED")
    if style & WS_CHILD: s.append("WS_CHILD")
    if style & WS_POPUP: s.append("WS_POPUP")
    if style & WS_VISIBLE: s.append("WS_VISIBLE")
    print("[%s] hwnd=%s style=0x%08x[%s] exstyle=0x%08x owner=%s parent=%s "
          "enabled=%s visible=%s tid=%d cloaked=%d(hr=%d)"
          % (tag, hwnd_str(hwnd), style, "|".join(s) or "-", ex,
             hwnd_str(owner), hwnd_str(parent), enabled, vis, tid,
             cloaked.value, hr), flush=True)


def foreground():
    for _ in range(20):
        h = u32.GetForegroundWindow()
        if h:
            return int(h)
        time.sleep(0.05)
    return 0


def click_at(x, y):
    u32.SetCursorPos(x, y)
    time.sleep(0.08)
    u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
    time.sleep(0.08)
    u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
    time.sleep(0.25)


def main():
    global STATE_BACKUP, HOOK_REF
    if STATE_PATH.exists():
        STATE_BACKUP = STATE_PATH.read_bytes()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    storage = Storage()
    storage.migrate_to_native_mode()
    window = DesktopWindow(storage)
    window.show_desktop()
    layer = WidgetLayer(storage)
    notes = layer.widgets.get("notes")

    def run():
        print("==== 便签组件 ====", flush=True)
        if notes is None:
            print("notes widget 不存在（state 中 hidden？）", flush=True)
            QTimer.singleShot(100, quit)
            return
        notes.show()
        time.sleep(0.4)
        nh = int(notes.winId())
        mh = int(window.winId())
        print("notes hwnd=%d main hwnd=%d" % (nh, mh), flush=True)
        dump_state("notes", nh)
        dump_state("main", mh)

        # 装线程钩子
        global WATCH
        WATCH = {nh, mh}
        proto = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int,
                                   wintypes.WPARAM, wintypes.LPARAM)
        HOOK_REF = proto(hook_proc)
        hhook = u32.SetWindowsHookExW(WH_CALLWNDPROC, HOOK_REF, None,
                                      k32.GetCurrentThreadId())
        print("hook installed: %s" % hhook, flush=True)

        g = notes.geometry()
        d = app.primaryScreen().devicePixelRatio()
        cx, cy = int((g.x() + g.width() // 2) * d), int((g.y() + g.height() // 2) * d)
        pt = wintypes.POINT(cx, cy)
        wfp = int(u32.WindowFromPoint(pt) or 0)
        print("click point=(%d,%d) WindowFromPoint=%d (notes=%d)" % (cx, cy, wfp, nh),
              flush=True)

        gti = GUITHREADINFO()
        gti.cbSize = ctypes.sizeof(GUITHREADINFO)
        if u32.GetGUIThreadInfo(k32.GetCurrentThreadId(), ctypes.byref(gti)):
            print("GUIThreadInfo: flags=0x%x active=%s focus=%s capture=%s"
                  % (gti.flags, hwnd_str(gti.hwndActive), hwnd_str(gti.hwndFocus),
                     hwnd_str(gti.hwndCapture)), flush=True)

        print("fg before = %s (main=%s)" % (hwnd_str(foreground()), hwnd_str(mh)), flush=True)
        LOG.append("---- CLICK START ----")
        click_at(cx, cy)
        LOG.append("---- CLICK END ----")
        fg = foreground()
        aw = int(u32.GetActiveWindow() or 0)
        print("after click: fg=%s activeWindow=%s notes.isActiveWindow=%s "
              "notes.hasFocus=%s focusWidget=%s"
              % (hwnd_str(fg), hwnd_str(aw), notes.isActiveWindow(),
                 notes.hasFocus(),
                     QApplication.focusWidget()), flush=True)

        # 手动激活尝试
        r = u32.SetForegroundWindow(wintypes.HWND(nh))
        err = k32.GetLastError()
        print("SetForegroundWindow(notes) = %s err=%d fg_now=%s"
              % (r, err, hwnd_str(foreground())), flush=True)
        r2 = u32.SetActiveWindow(wintypes.HWND(nh))
        print("SetActiveWindow(notes) = %s err=%d" % (hwnd_str(r2), k32.GetLastError()),
              flush=True)
        time.sleep(0.2)
        print("final: fg=%s active=%s qtActive=%s" % (
            hwnd_str(foreground()), hwnd_str(u32.GetActiveWindow()),
            notes.isActiveWindow()), flush=True)

        print("\n==== 消息流（点击前后） ====", flush=True)
        for line in LOG:
            print("  " + line, flush=True)

        if hhook:
            u32.UnhookWindowsHookEx(hhook)
        QTimer.singleShot(100, quit)

    def quit():
        try:
            if STATE_BACKUP is not None:
                STATE_PATH.write_bytes(STATE_BACKUP)
            else:
                STATE_PATH.unlink(missing_ok=True)
        except Exception as e:
            print("state restore failed:", e)
        win32_layer.restore_native_icons()
        app.quit()

    QTimer.singleShot(1200, run)
    app.exec()


if __name__ == "__main__":
    main()
