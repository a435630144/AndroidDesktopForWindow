# -*- coding: utf-8 -*-
"""探针三（修正版）：坐实 z-order 根因。

上一轮被 maximized Chrome 干扰（点击全落在 Chrome 上）。本轮：
  0. 开始前最小化所有非我方非 shell 的可见顶层窗口（Chrome 等），
     结束时恢复；同时打印 DefView / Progman / 我方窗口的 z-order 位置
  B. 原生模式：真实点击便签中心（不 raise）→ WindowFromPoint / fg / Qt 事件
  C. 原生模式：raise_() 便签后再点击 → 能否激活
  D. 整理模式（隐藏 DefView）：真实点击便签中心 → 能否激活
  E. 原生模式：真实点击主窗口图标 → 主窗口是否收到鼠标事件
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

from src import appsource, win32_layer  # noqa: E402
from src.desktop_window import DesktopWindow  # noqa: E402
from src.storage import Storage  # noqa: E402
from src.widget_layer import WidgetLayer  # noqa: E402

STATE_PATH = Path(os.path.expandvars(r"%APPDATA%\PhoneDesktop\state.json"))
STATE_BACKUP = None

u32 = ctypes.windll.user32
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetClassNameW.restype = ctypes.c_int
u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetWindowTextW.restype = ctypes.c_int
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
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x2, 0x4
SW_MINIMIZE, SW_RESTORE = 6, 9
GA_PARENT = 1
SHELL_CLASSES = {"Progman", "WorkerW", "Windows.UI.Core.CoreWindow", "Shell_TrayWnd",
                 "Shell_SecondaryTrayWnd", "DV2ControlHost", "Button"}

MINIMIZED = []  # 被我们最小化的窗口，结束时恢复


def describe(h):
    if not h:
        return "0"
    cls = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(wintypes.HWND(h), cls, 256)
    txt = ctypes.create_unicode_buffer(200)
    u32.GetWindowTextW(wintypes.HWND(h), txt, 200)
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(wintypes.HWND(h), ctypes.byref(pid))
    mine = pid.value == os.getpid()
    return "hwnd=%d class='%s' title='%s' pid=%d%s" % (
        h, cls.value, txt.value[:24], pid.value, " [OURS]" if mine else "")


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


def center_phys(widget):
    g = widget.geometry()
    d = widget.devicePixelRatio()
    return int((g.x() + g.width() // 2) * d), int((g.y() + g.height() // 2) * d)


def minimize_others(our_hwnds):
    """【安全禁令·2026-10-17】绝不移动/最小化/关闭用户的任何窗口。
    事故：探针为"清理测试环境"把用户窗口移到屏幕外，进程被 SIGTERM 时
    还原代码没跑，导致用户 Edge/Chrome/微信等全部滞留屏幕外无法使用。
    测试点被占用时用实时选点（参考 probe9.driver_band）或跳过场景，
    永远不要动用户的窗口。"""
    return []


def zorder_table(tag):
    wins = win32_layer._enum_zorder()
    print("[%s] z-order 总数=%d" % (tag, len(wins)), flush=True)
    progman = win32_layer._progman()
    dv = win32_layer._find_defview()
    dv_parent = int(u32.GetAncestor(dv, GA_PARENT) or 0) if dv else 0
    marks = {progman: "Progman", dv: "SHELLDLL_DefView",
             dv_parent: "DefView父窗口(WorkerW)"}
    for name, h in (("Progman", progman), ("DefView父窗口", dv_parent),
                    ("SHELLDLL_DefView", dv)):
        if h in wins:
            print("  %-18s z-index=%d  %s" % (name, wins.index(h), describe(h)),
                  flush=True)


class _Recorder(QObject):
    def __init__(self, sink, widget):
        super().__init__()
        self._sink = sink
        self._w = widget

    def eventFilter(self, obj, ev):
        try:
            if obj is self._w and ev.type() in (QEvent.MouseButtonPress,
                                                QEvent.MouseButtonDblClick):
                self._sink.append("MousePress")
        except Exception:
            pass
        return False


def main():
    global STATE_BACKUP
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

    def step0():
        print("\n==== 0. 清理环境 + z-order ====", flush=True)
        global MINIMIZED
        MINIMIZED = minimize_others({int(window.winId()), int(notes.winId())})
        time.sleep(0.6)
        zorder_table("原生模式")
        print("便签: %s" % describe(int(notes.winId())), flush=True)
        print("主窗口: %s" % describe(int(window.winId())), flush=True)
        print("当前前台: %s" % describe(foreground()), flush=True)
        QTimer.singleShot(100, step_b)

    def probe_click(tag, widget):
        """对 widget 中心做真实点击，返回 (WindowFromPoint, fg, qt_events)。"""
        cx, cy = center_phys(widget)
        pt = wintypes.POINT(cx, cy)
        wfp = int(u32.WindowFromPoint(pt) or 0)
        got = []
        rec = _Recorder(got, widget)
        app.instance().installEventFilter(rec)
        click_at(cx, cy)
        app.instance().removeEventFilter(rec)
        fg = foreground()
        print("[%s] 点击物理点=(%d,%d)" % (tag, cx, cy), flush=True)
        print("   WindowFromPoint -> %s" % describe(wfp), flush=True)
        print("   点击后前台     -> %s" % describe(fg), flush=True)
        print("   Qt 收到鼠标事件 -> %s ; widget.isActiveWindow=%s"
              % (got or "无", widget.isActiveWindow()), flush=True)
        return wfp, fg, got

    def step_b():
        print("\n==== B. 原生模式直接点击便签中心（不 raise） ====", flush=True)
        probe_click("B", notes)
        QTimer.singleShot(100, step_c)

    def step_c():
        print("\n==== C. raise_() 便签后点击 ====", flush=True)
        notes.raise_()
        time.sleep(0.3)
        probe_click("C", notes)
        QTimer.singleShot(100, step_d)

    def step_d():
        print("\n==== D. 整理模式（隐藏 DefView）点击便签 ====", flush=True)
        storage.set_setting("hide_native_icons", True)
        window.apply_native_icons_setting()
        time.sleep(0.5)
        zorder_table("整理模式")
        probe_click("D", notes)
        QTimer.singleShot(100, step_e)

    def step_e():
        print("\n==== E. 原生模式真实点击主窗口图标 ====", flush=True)
        storage.set_setting("hide_native_icons", False)
        window.apply_native_icons_setting()
        time.sleep(0.4)
        window.rebuild()
        time.sleep(0.3)
        ids = list(window.icons.keys())
        if not ids:
            print("没有图标可测", flush=True)
            QTimer.singleShot(100, finish)
            return
        icon = window.icons[ids[0]]
        g = icon.geometry()
        d = window.devicePixelRatio()
        cx, cy = int((g.x() + g.width() // 2) * d), int((g.y() + 20) * d)
        pt = wintypes.POINT(cx, cy)
        wfp = int(u32.WindowFromPoint(pt) or 0)
        print("图标点击点=(%d,%d) WindowFromPoint -> %s" % (cx, cy, describe(wfp)),
              flush=True)
        got = []
        rec = _Recorder(got, window)
        app.instance().installEventFilter(rec)
        click_at(cx, cy)
        app.instance().removeEventFilter(rec)
        print("主窗口 Qt 收到鼠标事件 -> %s" % (got or "无（被其它窗口吃掉）"), flush=True)
        QTimer.singleShot(100, finish)

    def finish():
        print("\n==== 恢复环境 ====", flush=True)
        for h in MINIMIZED:
            u32.ShowWindow(wintypes.HWND(h), SW_RESTORE)
        try:
            if STATE_BACKUP is not None:
                STATE_PATH.write_bytes(STATE_BACKUP)
            else:
                STATE_PATH.unlink(missing_ok=True)
        except Exception as e:
            print("state restore failed:", e)
        win32_layer.restore_native_icons()
        app.quit()

    QTimer.singleShot(1500, step0)
    app.exec()


if __name__ == "__main__":
    main()
