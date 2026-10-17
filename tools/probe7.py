# -*- coding: utf-8 -*-
"""探针七（干净环境决定性实验）。

前置：已杀掉所有遗留 python 进程。本探针在点击前校验 WindowFromPoint
必须命中"当前便签窗口"，否则中止（防旧窗口混淆）。

实验：
  P1  守护开：点击便签中心 -> fg / active / 消息流 / 能否输入
  P2  守护关：停用 BandGuard -> 点击 -> 同上（对照）
  P3  守护开：再次点击 -> 验证是否稳定复现
  P4  主窗口图标：真实拖动 -> col/row 是否改变（问题3）
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
from PySide6.QtTest import QTest  # noqa: E402

from src import appsource, win32_layer  # noqa: E402
from src.desktop_window import DesktopWindow  # noqa: E402
from src.storage import Storage  # noqa: E402
from src.widget_layer import WidgetLayer  # noqa: E402

STATE_PATH = Path(os.path.expandvars(r"%APPDATA%\DesktopOrganizerDemo\state.json"))
STATE_BACKUP = None
T0 = time.time()

u32 = ctypes.windll.user32
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetClassNameW.restype = ctypes.c_int
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
u32.SetWindowsHookExW.restype = wintypes.HHOOK
u32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p,
                                  wintypes.HINSTANCE, wintypes.DWORD]
u32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
u32.UnhookWindowsHookEx.restype = wintypes.BOOL
k32 = ctypes.windll.kernel32
k32.GetCurrentThreadId.restype = wintypes.DWORD
k32.GetLastError.restype = wintypes.DWORD
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, MOUSEEVENTF_MOVE = 0x2, 0x4, 0x1
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
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(wintypes.HWND(h), ctypes.byref(pid))
    mine = pid.value == os.getpid()
    return "hwnd=%d(%s)%s" % (h, cls.value, " [OURS]" if mine else " [OTHER]")


def foreground():
    for _ in range(20):
        h = u32.GetForegroundWindow()
        if h:
            return int(h)
        time.sleep(0.05)
    return 0


def log_msg(kind, name, h, extra=""):
    line = "    [%6dms][%-6s] %-6s %-18s hwnd=%d%s" % (
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

    desktop = appsource.shell_known_folder("desktop")
    jpg = None
    try:
        for n in sorted(os.listdir(desktop)):
            if n.lower().endswith(".jpg"):
                jpg = os.path.join(desktop, n)
                break
    except Exception:
        pass
    storage._data["layout"] = []
    if jpg:
        storage.add_app(appsource.desktop_file_entry(jpg), col=0, row=0)
    storage.save()

    window = DesktopWindow(storage)
    window.show_desktop()
    layer = WidgetLayer(storage)
    notes = layer.widgets.get("notes")
    guard = layer._band_guard

    def minimize_others():
        """【安全禁令·2026-10-17】绝不最小化用户的任何窗口（ShowWindow(h,6)=MINIMIZE）。
        事故：探针为"清理测试环境"动用户窗口，进程被 SIGTERM 时还原没跑，
        用户窗口全部无法使用。便签点击测试用实时校验（WindowFromPoint 命中便签）
        处理占用，永远不要动用户的窗口。"""
        return

    def notes_center():
        g = notes.geometry()
        d = notes.devicePixelRatio()
        return int((g.x() + g.width() // 2) * d), int((g.y() + g.height() // 2) * d)

    def verify_hit(tag):
        """点击前校验：WindowFromPoint 必须命中当前便签。"""
        cx, cy = notes_center()
        pt = wintypes.POINT(cx, cy)
        wfp = int(u32.WindowFromPoint(pt) or 0)
        nh = int(notes.winId())
        ok = wfp == nh
        print("[%s] 点击点=(%d,%d) WindowFromPoint=%s 便签=%d %s"
              % (tag, cx, cy, describe(wfp), nh, "OK" if ok else "!! 不匹配 !!"),
              flush=True)
        return ok, cx, cy

    def timed_click(tag, cx, cy, then, hold_ms=120):
        CURRENT_TAG[0] = tag
        print("\n==== [%s] 点击（事件循环泵消息） ====" % tag, flush=True)
        u32.SetCursorPos(cx, cy)
        QTimer.singleShot(150, lambda: u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None))
        QTimer.singleShot(150 + hold_ms,
                          lambda: u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None))
        QTimer.singleShot(150 + hold_ms + 900, then)

    def check(tag):
        fg = foreground()
        print("[%s] 结果: fg=%s 便签active=%s" % (tag, describe(fg),
                                                notes.isActiveWindow()), flush=True)
        # 输入测试（ASCII，避免 QTest 中文崩溃）
        try:
            notes.edit.setFocus()
            QTest.keyClicks(notes.edit, "abc123")
            time.sleep(0.1)
            txt = notes.edit.toPlainText()
            print("[%s] 输入测试: hasFocus=%s 文本=%r" % (tag, notes.edit.hasFocus(), txt),
                  flush=True)
        except Exception as e:
            print("[%s] 输入测试异常: %r" % (tag, e), flush=True)
        # 2.5 秒后再查一次：守护是否把激活态便签拽回桌面带
        def recheck():
            fg2 = foreground()
            print("[%s] 2.5秒后: fg=%s 便签active=%s"
                  % (tag, describe(fg2), notes.isActiveWindow()), flush=True)
        QTimer.singleShot(2500, recheck)
        return fg == int(notes.winId())

    def p1():
        ok, cx, cy = verify_hit("P1守护开")
        if not ok:
            QTimer.singleShot(100, finish)
            return
        timed_click("P1守护开", cx, cy, lambda: (check("P1守护开"), p2()))

    def p2():
        guard._timer.stop()
        print("\n（已停用 BandGuard）", flush=True)
        QTimer.singleShot(1800, p2_click)

    def p2_click():
        ok, cx, cy = verify_hit("P2守护关")
        if not ok:
            QTimer.singleShot(100, finish)
            return
        timed_click("P2守护关", cx, cy, lambda: (check("P2守护关"), p3()))

    def p3():
        guard._timer.start()
        print("\n（已恢复 BandGuard）", flush=True)
        QTimer.singleShot(1800, p3_click)

    def p3_click():
        ok, cx, cy = verify_hit("P3守护开2")
        if not ok:
            QTimer.singleShot(100, p4)
            return
        timed_click("P3守护开2", cx, cy, lambda: (check("P3守护开2"), p4()))

    def p4():
        print("\n==== P4：主窗口图标真实拖动（问题3） ====", flush=True)
        storage.set_setting("hide_native_icons", True)
        storage.set_setting("auto_clone_desktop", True)
        window.apply_native_icons_setting()
        QTimer.singleShot(400, p4_drag)

    def p4_drag():
        window.rebuild()
        QTimer.singleShot(400, p4_drag2)

    def p4_drag2():
        ids = list(window.icons.keys())
        if not ids:
            print("没有图标", flush=True)
            QTimer.singleShot(100, finish)
            return
        src = window.icons[ids[0]]
        old = (src.entry.get("col"), src.entry.get("row"))
        g = src.geometry()
        d = window.devicePixelRatio()
        x1, y1 = int((g.x() + g.width() // 2) * d), int((g.y() + 20) * d)
        cell = window._cell()
        origin = window._origin()
        x2, y2 = int((origin[0] + 2 * cell[0] + cell[0] // 2) * d), \
            int((origin[1] + 1 * cell[1] + 20) * d)
        print("拖动 (%d,%d) -> (%d,%d)，原位置=%s" % (x1, y1, x2, y2, old), flush=True)
        CURRENT_TAG[0] = "P4拖动"
        u32.SetCursorPos(x1, y1)
        QTimer.singleShot(150, lambda: u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None))
        for i in range(1, 11):
            t = i / 10.0
            QTimer.singleShot(150 + i * 40, lambda tt=t: u32.SetCursorPos(
                int(x1 + (x2 - x1) * tt), int(y1 + (y2 - y1) * tt)))
        QTimer.singleShot(150 + 11 * 40,
                          lambda: u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None))
        QTimer.singleShot(150 + 11 * 40 + 800, lambda: p4_check(old))

    def p4_check(old):
        ids = list(window.icons.keys())
        e = storage.find_entry(ids[0])
        new = (e.get("col"), e.get("row"))
        print("P4 拖动结果: %s -> %s %s" % (old, new,
                                          "成功" if new != old else "!! 未移动 !!"),
              flush=True)
        QTimer.singleShot(100, finish)

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

    def run():
        minimize_others()
        time.sleep(0.6)
        nh = int(notes.winId())
        mh = int(window.winId())
        WATCH = {nh, mh}
        install_hooks()
        print("便签=%s 主窗口=%s 前台=%s" % (describe(nh), describe(mh),
                                            describe(foreground())), flush=True)
        QTimer.singleShot(300, p1)

    QTimer.singleShot(1500, run)
    app.exec()


if __name__ == "__main__":
    main()
