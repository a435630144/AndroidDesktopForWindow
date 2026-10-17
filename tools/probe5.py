# -*- coding: utf-8 -*-
"""探针五： definitively 定位"点击不激活便签"。

改进：
  1. 点击前现场取证：WindowFromPoint / GetWindowRect / exstyle / z-order 索引
  2. WH_GETMESSAGE（ posted 输入消息）+ WH_CALLWNDPROC（sent 消息）双钩子，
     并验证句柄非 NULL
  3. 点击后：fg / active / 能否输入（带异常保护）
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
from src.storage import Storage  # noqa: E402
from src.widget_layer import WidgetLayer  # noqa: E402

STATE_PATH = Path(os.path.expandvars(r"%APPDATA%\DesktopOrganizerDemo\state.json"))
STATE_BACKUP = None
T0 = time.time()

u32 = ctypes.windll.user32
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetClassNameW.restype = ctypes.c_int
u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.GetWindowRect.restype = wintypes.BOOL
u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
u32.GetWindowLongW.restype = wintypes.LONG
u32.GetForegroundWindow.restype = wintypes.HWND
u32.WindowFromPoint.argtypes = [wintypes.POINT]
u32.WindowFromPoint.restype = wintypes.HWND
u32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u32.SetCursorPos.restype = wintypes.BOOL
u32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                            wintypes.DWORD, ctypes.c_void_p]
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.GetWindowThreadProcessId.restype = wintypes.DWORD
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.IsWindowVisible.restype = wintypes.BOOL
u32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
u32.GetWindow.restype = wintypes.HWND
u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
u32.ShowWindow.restype = wintypes.BOOL
u32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
u32.GetAncestor.restype = wintypes.HWND
u32.SetWindowsHookExW.restype = wintypes.HHOOK
u32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p,
                                  wintypes.HINSTANCE, wintypes.DWORD]
u32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
u32.UnhookWindowsHookEx.restype = wintypes.BOOL
k32 = ctypes.windll.kernel32
k32.GetCurrentThreadId.restype = wintypes.DWORD
k32.GetLastError.restype = wintypes.DWORD
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x2, 0x4
WH_GETMESSAGE, WH_CALLWNDPROC = 3, 4
GWL_STYLE, GWL_EXSTYLE = -16, -20
GA_PARENT = 1

LOG = []
WATCH = set()
HOOKS = []


def ts():
    return int((time.time() - T0) * 1000)


def describe(h):
    if not h:
        return "0"
    cls = ctypes.create_unicode_buffer(128)
    u32.GetClassNameW(wintypes.HWND(h), cls, 128)
    return "hwnd=%d(%s)" % (h, cls.value)


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
    time.sleep(0.3)


def log_msg(kind, name, h, extra=""):
    line = "    [%6dms] %-6s %-18s hwnd=%d%s" % (ts(), kind, name, h, extra)
    LOG.append(line)
    print(line, flush=True)


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt", wintypes.POINT)]


class CWPSTRUCT(ctypes.Structure):
    _fields_ = [("lParam", wintypes.LPARAM), ("wParam", wintypes.WPARAM),
                ("message", wintypes.UINT), ("hwnd", wintypes.HWND)]


class WINDOWPOS(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("hwndInsertAfter", wintypes.HWND),
                ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("cx", ctypes.c_int), ("cy", ctypes.c_int),
                ("flags", wintypes.UINT)]


NAMES = {0x01: "WM_CREATE", 0x06: "WM_PAINT", 0x07: "WM_SETFOCUS", 0x08: "WM_KILLFOCUS",
         0x1C: "WM_ACTIVATE", 0x21: "WM_MOUSEACTIVATE", 0x46: "WM_WINPOSCHANGING",
         0x47: "WM_WINPOSCHANGED", 0x84: "WM_NCHITTEST", 0x86: "WM_GETICON",
         0x200: "WM_MOUSEMOVE", 0x201: "WM_LBUTTONDOWN", 0x202: "WM_LBUTTONUP",
         0x281: "WM_IME_SETCONTEXT", 0x282: "WM_IME_REPORT", 0x3D: "WM_GETOBJECT",
         0x100: "WM_KEYDOWN", 0x101: "WM_KEYUP"}


def make_getmessage_proc():
    def proc(nCode, wParam, lParam):
        try:
            if nCode >= 0:
                m = ctypes.cast(lParam, ctypes.POINTER(MSG)).contents
                h = int(m.hwnd or 0)
                if h in WATCH:
                    log_msg("GETMSG", NAMES.get(int(m.message), hex(int(m.message))), h)
        except Exception as e:
            print("getmsg hook err %r" % e, flush=True)
        return u32.CallNextHookEx(None, nCode, wParam, lParam)
    return proc


def make_callwnd_proc():
    def proc(nCode, wParam, lParam):
        try:
            if nCode >= 0:
                cwp = ctypes.cast(lParam, ctypes.POINTER(CWPSTRUCT)).contents
                h = int(cwp.hwnd or 0)
                if h in WATCH:
                    m = int(cwp.message)
                    extra = ""
                    if m in (0x46, 0x47):
                        wp = ctypes.cast(cwp.lParam, ctypes.POINTER(WINDOWPOS)).contents
                        extra = " after=%d flags=0x%x" % (int(wp.hwndInsertAfter or 0),
                                                          int(wp.flags))
                    elif m in (0x1C, 0x21):
                        extra = " w=%s l=%s" % (int(cwp.wParam or 0), int(cwp.lParam or 0))
                    elif m in (0x07, 0x08):
                        extra = " -> %d" % int(cwp.wParam or 0)
                    log_msg("CALLWND", NAMES.get(m, hex(m)), h, extra)
        except Exception as e:
            print("callwnd hook err %r" % e, flush=True)
        return u32.CallNextHookEx(None, nCode, wParam, lParam)
    return proc


def install_hooks():
    proto = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int,
                               wintypes.WPARAM, wintypes.LPARAM)
    for kind, factory in ((WH_GETMESSAGE, make_getmessage_proc),
                          (WH_CALLWNDPROC, make_callwnd_proc)):
        ref = proto(factory())
        h = u32.SetWindowsHookExW(kind, ref, None, k32.GetCurrentThreadId())
        if not h:
            print("!!! 钩子安装失败 kind=%d err=%d" % (kind, k32.GetLastError()),
                  flush=True)
        else:
            print("钩子安装成功 kind=%d hhook=%s" % (kind, h), flush=True)
            HOOKS.append(h)
            HOOKS.append(ref)  # 防止被 GC


def main():
    global STATE_BACKUP, WATCH
    if STATE_PATH.exists():
        STATE_BACKUP = STATE_PATH.read_bytes()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    storage = Storage()
    storage.migrate_to_native_mode()
    layer = WidgetLayer(storage)
    notes = layer.widgets.get("notes")

    def run():
        # 最小化其它窗口
        h = u32.GetWindow(u32.GetDesktopWindow(), 5)
        seen = set()
        while h:
            if h not in seen:
                seen.add(h)
                try:
                    if u32.IsWindowVisible(h):
                        pid = wintypes.DWORD()
                        u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                        txt = ctypes.create_unicode_buffer(200)
                        u32.GetWindowTextW(h, txt, 200)
                        if pid.value != os.getpid() and txt.value.strip():
                            pass  # 【安全禁令】不最小化用户窗口
                except Exception:
                    pass
            h = u32.GetWindow(h, 2)
        time.sleep(0.6)

        nh = int(notes.winId())
        mh = int(layer._band_guard._items[0][0]) if layer._band_guard._items else 0
        WATCH = {nh}
        if mh:
            WATCH.add(mh)
        install_hooks()

        print("==== 点击前现场取证 ====", flush=True)
        r = wintypes.RECT()
        u32.GetWindowRect(wintypes.HWND(nh), ctypes.byref(r))
        g = notes.geometry()
        d = notes.devicePixelRatio()
        cx, cy = int((g.x() + g.width() // 2) * d), int((g.y() + g.height() // 2) * d)
        print("便签 Qt 几何=%s dpr=%.2f" % (g, d), flush=True)
        print("便签 Win32 矩形=(%d,%d)-(%d,%d)" % (r.left, r.top, r.right, r.bottom),
              flush=True)
        print("点击物理点=(%d,%d) 是否在矩形内=%s"
              % (cx, cy, r.left <= cx <= r.right and r.top <= cy <= r.bottom),
              flush=True)
        pt = wintypes.POINT(cx, cy)
        wfp = int(u32.WindowFromPoint(pt) or 0)
        print("WindowFromPoint -> %s (便签=%d)" % (describe(wfp), nh), flush=True)
        print("便签 exstyle=0x%08x style=0x%08x"
              % (u32.GetWindowLongW(wintypes.HWND(nh), GWL_EXSTYLE) & 0xFFFFFFFF,
                 u32.GetWindowLongW(wintypes.HWND(nh), GWL_STYLE) & 0xFFFFFFFF),
              flush=True)
        wins = win32_layer._enum_zorder()
        progman = win32_layer._progman()
        dv = win32_layer._find_defview()
        dvp = int(u32.GetAncestor(dv, GA_PARENT) or 0) if dv else 0
        for name, hh in (("Progman", progman), ("DefView父窗口", dvp),
                         ("SHELLDLL_DefView", dv), ("便签", nh), ("主窗口", mh)):
            if hh in wins:
                print("  z-index %-14s = %d / %d  %s"
                      % (name, wins.index(hh), len(wins), describe(hh)), flush=True)
        print("当前前台: %s" % describe(foreground()), flush=True)

        print("\n==== 真实点击 ====", flush=True)
        click_at(cx, cy)
        print("点击后 fg=%s 便签 active=%s" % (describe(foreground()),
                                              notes.isActiveWindow()), flush=True)
        try:
            notes.edit.setFocus()
            time.sleep(0.2)
            print("setFocus 后 hasFocus=%s" % notes.edit.hasFocus(), flush=True)
        except Exception as e:
            print("输入测试异常: %r" % e, flush=True)

        print("\n==== 消息流（全程） ====", flush=True)
        for line in LOG:
            print(line, flush=True)
        for hh in HOOKS[::2]:
            u32.UnhookWindowsHookEx(hh)
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

    QTimer.singleShot(1500, run)
    app.exec()


if __name__ == "__main__":
    main()
