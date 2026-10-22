# -*- coding: utf-8 -*-
"""探针六：决定性实验。

改进：
  1. 点击由 QTimer 驱动（事件循环持续泵消息），钩子能真正捕获输入消息
  2. DPI 虚拟化校验：SetCursorPos 后用 GetPhysicalCursorPos 核对真实位置
  3. 对照实验：BandGuard 开 / 关 两种状态下点击便签
  4. 捕获 WM_NCHITTEST / WM_MOUSEACTIVATE / WM_ACTIVATE / 鼠标 post 消息
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

STATE_PATH = Path(os.path.expandvars(r"%APPDATA%\PhoneDesktop\state.json"))
STATE_BACKUP = None
T0 = time.time()

u32 = ctypes.windll.user32
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetClassNameW.restype = ctypes.c_int
u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.GetWindowRect.restype = wintypes.BOOL
u32.GetForegroundWindow.restype = wintypes.HWND
u32.WindowFromPoint.argtypes = [wintypes.POINT]
u32.WindowFromPoint.restype = wintypes.HWND
u32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u32.SetCursorPos.restype = wintypes.BOOL
u32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
u32.GetCursorPos.restype = wintypes.BOOL
u32.GetPhysicalCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
u32.GetPhysicalCursorPos.restype = wintypes.BOOL
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

LOG = []
WATCH = set()
HOOK_REFS = []
CURRENT_TAG = [""]


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


def log_msg(kind, name, h, extra=""):
    line = "    [%6dms][%s] %-6s %-18s hwnd=%d%s" % (
        ts(), CURRENT_TAG[0], kind, name, h, extra)
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


NAMES = {0x07: "WM_SETFOCUS", 0x08: "WM_KILLFOCUS", 0x1C: "WM_ACTIVATE",
         0x21: "WM_MOUSEACTIVATE", 0x46: "WM_WINPOSCHANGING", 0x47: "WM_WINPOSCHANGED",
         0x84: "WM_NCHITTEST", 0x200: "WM_MOUSEMOVE", 0x201: "WM_LBUTTONDOWN",
         0x202: "WM_LBUTTONUP", 0x100: "WM_KEYDOWN", 0x101: "WM_KEYUP"}


def make_getmessage_proc():
    def proc(nCode, wParam, lParam):
        try:
            if nCode >= 0:
                m = ctypes.cast(lParam, ctypes.POINTER(MSG)).contents
                h = int(m.hwnd or 0)
                if h in WATCH:
                    log_msg("GETMSG", NAMES.get(int(m.message), hex(int(m.message))), h)
        except Exception as e:
            print("getmsg err %r" % e, flush=True)
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
            print("callwnd err %r" % e, flush=True)
        return u32.CallNextHookEx(None, nCode, wParam, lParam)
    return proc


def install_hooks():
    proto = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int,
                               wintypes.WPARAM, wintypes.LPARAM)
    for kind, factory in ((WH_GETMESSAGE, make_getmessage_proc),
                          (WH_CALLWNDPROC, make_callwnd_proc)):
        ref = proto(factory())
        h = u32.SetWindowsHookExW(kind, ref, None, k32.GetCurrentThreadId())
        print("hook kind=%d -> %s (err=%d)" % (kind, h, k32.GetLastError()), flush=True)
        if h:
            HOOK_REFS.append(ref)


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
    guard = layer._band_guard

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
        mh = int(guard._items[0][0]) if guard._items else 0
        WATCH = {nh, mh}
        install_hooks()

        g = notes.geometry()
        d = notes.devicePixelRatio()
        cx, cy = int((g.x() + g.width() // 2) * d), int((g.y() + g.height() // 2) * d)

        # DPI 虚拟化校验
        u32.SetCursorPos(cx, cy)
        time.sleep(0.1)
        p1 = wintypes.POINT()
        p2 = wintypes.POINT()
        u32.GetCursorPos(ctypes.byref(p1))
        u32.GetPhysicalCursorPos(ctypes.byref(p2))
        print("==== DPI 校验 ====", flush=True)
        print("SetCursorPos(%d,%d) -> GetCursorPos=(%d,%d) GetPhysicalCursorPos=(%d,%d)"
              % (cx, cy, p1.x, p1.y, p2.x, p2.y), flush=True)
        pt = wintypes.POINT(cx, cy)
        print("WindowFromPoint -> %s (便签=%d)" % (describe(int(u32.WindowFromPoint(pt) or 0)), nh),
              flush=True)
        print("当前前台: %s" % describe(foreground()), flush=True)

        def timed_click(tag, then):
            """QTimer 驱动点击：事件循环持续泵消息，钩子可捕获。"""
            CURRENT_TAG[0] = tag
            print("\n==== [%s] 点击 ====" % tag, flush=True)
            u32.SetCursorPos(cx, cy)
            QTimer.singleShot(120, lambda: u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None))
            QTimer.singleShot(240, lambda: u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None))
            QTimer.singleShot(700, then)

        def check(tag):
            print("[%s] 结果: fg=%s 便签active=%s" % (tag, describe(foreground()),
                                                    notes.isActiveWindow()), flush=True)

        def phase_guard_on():
            timed_click("守护开", lambda: (check("守护开"), phase_guard_off()))

        def phase_guard_off():
            # 停用守护后等一个周期，再点
            guard._timer.stop()
            print("\n（已停用 BandGuard）", flush=True)
            QTimer.singleShot(2000, lambda: timed_click("守护关", lambda: (
                check("守护关"), finish())))

        def finish():
            print("\n==== 全部消息流 ====", flush=True)
            for line in LOG:
                print(line, flush=True)
            try:
                if STATE_BACKUP is not None:
                    STATE_PATH.write_bytes(STATE_BACKUP)
                else:
                    STATE_PATH.unlink(missing_ok=True)
            except Exception as e:
                print("state restore failed:", e)
            win32_layer.restore_native_icons()
            app.quit()

        QTimer.singleShot(300, phase_guard_on)

    QTimer.singleShot(1500, run)
    app.exec()


if __name__ == "__main__":
    main()
