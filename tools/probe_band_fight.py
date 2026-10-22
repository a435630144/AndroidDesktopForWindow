# -*- coding: utf-8 -*-
"""探针四：坐实"点击激活后被拽回桌面带导致失活"。

插桩：
  1. monkeypatch win32_layer._insert_above：记录每次桌面带重插（时间戳/目标）
  2. WH_CALLWNDPROC 线程钩子：便签窗口全消息流（带 ms 时间戳）
  3. Qt 事件记录修正：记录任意对象的 MouseButtonPress / KeyPress（含对象类名）
场景（用户真实场景 B）：
  全新启动 -> 便签处于桌面带原位 -> 真实点击便签中心 ->
  观察 3 秒内的消息流 / 重插记录 / fg 变化 / 能否输入文字
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from src import win32_layer  # noqa: E402
from src.storage import Storage  # noqa: E402
from src.widget_layer import WidgetLayer  # noqa: E402

STATE_PATH = Path(os.path.expandvars(r"%APPDATA%\PhoneDesktop\state.json"))
STATE_BACKUP = None
T0 = time.time()

u32 = ctypes.windll.user32
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetClassNameW.restype = ctypes.c_int
u32.GetForegroundWindow.restype = wintypes.HWND
u32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u32.SetCursorPos.restype = wintypes.BOOL
u32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                            wintypes.DWORD, ctypes.c_void_p]
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.GetWindowThreadProcessId.restype = wintypes.DWORD
k32 = ctypes.windll.kernel32
k32.GetCurrentThreadId.restype = wintypes.DWORD
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x2, 0x4

INSERT_LOG = []   # (t, hwnd, above_of)
MSG_LOG = []      # (t, msg, hwnd, extra)
WATCH = set()
HOOK_REF = None


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


# ---------- 插桩 1：桌面带重插 ----------
_orig_insert = win32_layer._insert_above


def traced_insert(hwnd, above_of):
    ok = _orig_insert(hwnd, above_of)
    INSERT_LOG.append((ts(), int(hwnd), int(above_of)))
    print("    [%6dms] INSERT hwnd=%s above=%s -> %s"
          % (ts(), describe(int(hwnd)), describe(int(above_of)), ok), flush=True)
    return ok


win32_layer._insert_above = traced_insert


# ---------- 插桩 2：线程消息钩子 ----------
class CWPSTRUCT(ctypes.Structure):
    _fields_ = [("lParam", wintypes.LPARAM), ("wParam", wintypes.WPARAM),
                ("message", wintypes.UINT), ("hwnd", wintypes.HWND)]


class WINDOWPOS(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("hwndInsertAfter", wintypes.HWND),
                ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("cx", ctypes.c_int), ("cy", ctypes.c_int),
                ("flags", wintypes.UINT)]


NAMES = {0x01: "WM_CREATE", 0x05: "WM_SIZE", 0x06: "WM_PAINT", 0x07: "WM_SETFOCUS",
         0x08: "WM_KILLFOCUS", 0x1C: "WM_ACTIVATE", 0x21: "WM_MOUSEACTIVATE",
         0x46: "WM_WINPOSCHANGING", 0x47: "WM_WINPOSCHANGED", 0x84: "WM_NCHITTEST",
         0x86: "WM_GETICON", 0x201: "WM_LBUTTONDOWN", 0x202: "WM_LBUTTONUP",
         0x281: "WM_IME_SETCONTEXT", 0x282: "WM_IME_REPORT", 0x3D: "WM_GETOBJECT"}


def hook_proc(nCode, wParam, lParam):
    try:
        cwp = ctypes.cast(lParam, ctypes.POINTER(CWPSTRUCT)).contents
        h = int(cwp.hwnd or 0)
        if h in WATCH and nCode >= 0:
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
            MSG_LOG.append((ts(), NAMES.get(m, hex(m)), h, extra))
            print("    [%6dms] MSG %-18s hwnd=%d%s" % (ts(), NAMES.get(m, hex(m)),
                                                       h, extra), flush=True)
    except Exception as e:
        print("hook err %r" % e, flush=True)
    return u32.CallNextHookEx(None, nCode, wParam, lParam)


# ---------- 插桩 3：Qt 事件记录（任意对象） ----------
class _Recorder(QObject):
    def __init__(self):
        super().__init__()
        self.events = []

    def eventFilter(self, obj, ev):
        try:
            t = ev.type()
            if t in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
                self.events.append((ts(), "MousePress", type(obj).__name__))
            elif t == QEvent.KeyPress:
                self.events.append((ts(), "KeyPress", type(obj).__name__))
        except Exception:
            pass
        return False


def main():
    global STATE_BACKUP, HOOK_REF, WATCH
    if STATE_PATH.exists():
        STATE_BACKUP = STATE_PATH.read_bytes()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    storage = Storage()
    storage.migrate_to_native_mode()
    layer = WidgetLayer(storage)
    notes = layer.widgets.get("notes")
    rec = _Recorder()
    app.instance().installEventFilter(rec)

    def run():
        # 清理环境：最小化其它应用窗口（模拟"桌面可见"的用户场景）
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
                            u32.ShowWindow(h, 6)  # SW_MINIMIZE
                except Exception:
                    pass
            h = u32.GetWindow(h, 2)
        time.sleep(0.5)
        nh = int(notes.winId())
        WATCH = {nh}
        proto = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int,
                                   wintypes.WPARAM, wintypes.LPARAM)
        HOOK_REF = proto(hook_proc)
        u32.SetWindowsHookExW.restype = wintypes.HHOOK
        u32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p,
                                          wintypes.HINSTANCE, wintypes.DWORD]
        hhook = u32.SetWindowsHookExW(4, HOOK_REF, None, k32.GetCurrentThreadId())
        print("==== 场景 B：便签桌面带原位 + 真实点击 ====", flush=True)
        print("便签 %s 前台=%s" % (describe(nh), describe(foreground())), flush=True)
        g = notes.geometry()
        d = notes.devicePixelRatio()
        cx, cy = int((g.x() + g.width() // 2) * d), int((g.y() + g.height() // 2) * d)
        print("点击物理点=(%d,%d)" % (cx, cy), flush=True)
        print("--- 点击开始 ---", flush=True)
        click_at(cx, cy)
        print("--- 点击结束（已等 300ms） ---", flush=True)
        print("点击后 fg=%s notes.isActiveWindow=%s" % (describe(foreground()),
                                                       notes.isActiveWindow()),
              flush=True)
        # 用户真正关心的：能否输入
        notes.edit.setFocus()
        QTest.keyClicks(notes.edit, "测试abc")
        time.sleep(0.5)
        print("输入后文本=%r hasFocus=%s" % (notes.edit.toPlainText(),
                                             notes.edit.hasFocus()), flush=True)
        print("最终 fg=%s active=%s" % (describe(foreground()),
                                        notes.isActiveWindow()), flush=True)
        print("\n==== 汇总 ====", flush=True)
        print("桌面带重插记录:", flush=True)
        for t, h, a in INSERT_LOG:
            print("  [%6dms] insert hwnd=%d above=%d" % (t, h, a), flush=True)
        print("便签窗口消息流:", flush=True)
        for t, m, h, ex in MSG_LOG:
            print("  [%6dms] %-18s%s" % (t, m, ex), flush=True)
        print("Qt 事件:", flush=True)
        for t, k, o in rec.events:
            print("  [%6dms] %s -> %s" % (t, k, o), flush=True)
        if hhook:
            ctypes.windll.user32.UnhookWindowsHookEx(hhook)
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
