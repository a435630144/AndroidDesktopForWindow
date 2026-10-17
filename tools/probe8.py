# -*- coding: utf-8 -*-
"""探针八：定位图标拖动断点。

全链路插桩：
  - AppIcon.mousePressEvent / mouseMoveEvent（按下点 / 移动 / 阈值）
  - dragStarted / dragFinished 信号
  - DesktopWindow.nativeEvent 的 WM_NCHITTEST（拖拽期间是否返回 HTCLIENT）
  - DesktopWindow.dragEnterEvent / dropEvent / _drop_internal
场景：
  S1  最小场景：全新 app + 整理模式 + 直接拖动图标（便签不激活）
  S2  同样拖动，但先把便签点到前台（复现 P4 的失败环境）
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

from src import appsource, win32_layer  # noqa: E402
from src.desktop_window import DesktopWindow  # noqa: E402
from src.iconwidget import AppIcon  # noqa: E402
from src.storage import Storage  # noqa: E402
from src.widget_layer import WidgetLayer  # noqa: E402

STATE_PATH = Path(os.path.expandvars(r"%APPDATA%\DesktopOrganizerDemo\state.json"))
STATE_BACKUP = None
T0 = time.time()

u32 = ctypes.windll.user32
u32.GetForegroundWindow.restype = wintypes.HWND
u32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u32.SetCursorPos.restype = wintypes.BOOL
u32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                            wintypes.DWORD, ctypes.c_void_p]
u32.WindowFromPoint.argtypes = [wintypes.POINT]
u32.WindowFromPoint.restype = wintypes.HWND
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetClassNameW.restype = ctypes.c_int
u32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
u32.GetWindow.restype = wintypes.HWND
u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
u32.ShowWindow.restype = wintypes.BOOL
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.IsWindowVisible.restype = wintypes.BOOL
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x2, 0x4


def ts():
    return int((time.time() - T0) * 1000)


def p(msg):
    print("    [%6dms] %s" % (ts(), msg), flush=True)


def foreground():
    for _ in range(20):
        h = u32.GetForegroundWindow()
        if h:
            return int(h)
        time.sleep(0.05)
    return 0


def describe(h):
    if not h:
        return "0"
    cls = ctypes.create_unicode_buffer(128)
    u32.GetClassNameW(wintypes.HWND(h), cls, 128)
    return "hwnd=%d(%s)" % (h, cls.value)


def minimize_others():
    """【安全禁令·2026-10-17】绝不移动/最小化/关闭用户的任何窗口。
    事故：探针为"清理测试环境"把用户窗口移到屏幕外，进程被 SIGTERM 时
    还原代码没跑，导致用户 Edge/Chrome/微信等全部滞留屏幕外无法使用。
    测试点被占用时用实时选点（参考 probe9.driver_band）或跳过场景，
    永远不要动用户的窗口。"""
    return []


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
    storage.add_app({"id": "sys-pc", "name": "此电脑",
                     "target": "::{20D04FE0-3AEA-1069-A2D8-08002B30309D}",
                     "builtin": True}, col=1, row=0)
    storage.save()

    window = DesktopWindow(storage)
    window.show_desktop()
    layer = WidgetLayer(storage)
    notes = layer.widgets.get("notes")

    # ---------- 插桩 ----------
    orig_press = AppIcon.mousePressEvent
    orig_move = AppIcon.mouseMoveEvent

    def traced_press(self, e):
        p("icon.press pos=%s global=%s" % (e.pos(), e.globalPosition().toPoint()))
        orig_press(self, e)

    def traced_move(self, e):
        if self._press_pos is not None:
            p("icon.move pos=%s delta=%s" % (e.pos(),
                                             (e.pos() - self._press_pos).manhattanLength()))
        orig_move(self, e)

    AppIcon.mousePressEvent = traced_press
    AppIcon.mouseMoveEvent = traced_move

    orig_native = DesktopWindow.nativeEvent

    def traced_native(self, eventType, message):
        try:
            if eventType in (b"windows_generic_MSG", "windows_generic_MSG"):
                from ctypes import wintypes as wt
                msg = wt.MSG.from_address(int(message))
                if msg.message == 0x84:  # WM_NCHITTEST
                    x = ctypes.c_int16(msg.lParam & 0xFFFF).value
                    y = ctypes.c_int16((msg.lParam >> 16) & 0xFFFF).value
                    r = orig_native(self, eventType, message)
                    p("NCHITTEST (%d,%d) drag_active=%s organize=%s -> %s"
                      % (x, y, self._drag_active, self._organize_mode(), r[1]))
                    return r
        except Exception:
            pass
        return orig_native(self, eventType, message)

    DesktopWindow.nativeEvent = traced_native

    orig_drop_internal = DesktopWindow._drop_internal

    def traced_drop_internal(self, payload, pos):
        p("_drop_internal payload=%r pos=%s" % (payload, pos))
        return orig_drop_internal(self, payload, pos)

    DesktopWindow._drop_internal = traced_drop_internal

    orig_drag_enter = DesktopWindow.dragEnterEvent
    orig_drop = DesktopWindow.dropEvent

    def traced_drag_enter(self, e):
        p("dragEnter hasMime=%s" % e.mimeData().hasFormat("application/x-desktoporg-item"))
        return orig_drag_enter(self, e)

    def traced_drop(self, e):
        p("dropEvent pos=%s hasMime=%s" % (e.position().toPoint(),
                                           e.mimeData().hasFormat("application/x-desktoporg-item")))
        return orig_drop(self, e)

    DesktopWindow.dragEnterEvent = traced_drag_enter
    DesktopWindow.dropEvent = traced_drop

    def run():
        minimize_others()
        time.sleep(0.6)
        storage.set_setting("hide_native_icons", True)
        storage.set_setting("auto_clone_desktop", True)
        window.apply_native_icons_setting()
        QTimer.singleShot(500, rebuild_and_s1)

    def rebuild_and_s1():
        window.rebuild()
        QTimer.singleShot(400, s1)

    def do_drag(tag, then):
        print("\n==== [%s] 拖动 ====" % tag, flush=True)
        ids = list(window.icons.keys())
        src = window.icons[ids[0]]
        old = (src.entry.get("col"), src.entry.get("row"))
        g = src.geometry()
        d = window.devicePixelRatio()
        x1, y1 = int((g.x() + g.width() // 2) * d), int((g.y() + 20) * d)
        cell = window._cell()
        origin = window._origin()
        x2 = int((origin[0] + 2 * cell[0] + cell[0] // 2) * d)
        y2 = int((origin[1] + 1 * cell[1] + 20) * d)
        p("拖动 (%d,%d)->(%d,%d) 原位置=%s 前台=%s" % (x1, y1, x2, y2, old,
                                                      describe(foreground())))
        drag_t0 = [None]

        def on_start():
            drag_t0[0] = ts()
            p("!! dragStarted 信号")

        def on_finish():
            if drag_t0[0] is not None:
                p("!! dragFinished 信号（拖动耗时 %dms %s）"
                  % (ts() - drag_t0[0], "!! 线程卡住 !!" if ts() - drag_t0[0] > 2000 else ""))
            else:
                p("!! dragFinished 信号")

        src.dragStarted.connect(on_start)
        src.dragFinished.connect(on_finish)
        u32.SetCursorPos(x1, y1)
        QTimer.singleShot(150, lambda: u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None))
        for i in range(1, 13):
            t = i / 12.0
            QTimer.singleShot(150 + i * 45, lambda tt=t: u32.SetCursorPos(
                int(x1 + (x2 - x1) * tt), int(y1 + (y2 - y1) * tt)))
        QTimer.singleShot(150 + 13 * 45,
                          lambda: u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None))
        QTimer.singleShot(150 + 13 * 45 + 900, lambda: s1_check(tag, old, then))

    def s1_check(tag, old, then):
        ids = list(window.icons.keys())
        e = storage.find_entry(ids[0])
        new = (e.get("col"), e.get("row"))
        p("[%s] 拖动结果: %s -> %s %s" % (tag, old, new,
                                          "成功" if new != old else "!! 未移动 !!"))
        then()

    def s1():
        do_drag("S1便签未激活", s2_prepare)

    def s2_prepare():
        # 把便签点到前台（复现 P4 环境）
        print("\n==== 激活便签（复现 P4 环境） ====", flush=True)
        g = notes.geometry()
        d = notes.devicePixelRatio()
        cx, cy = int((g.x() + g.width() // 2) * d), int((g.y() + g.height() // 2) * d)
        pt = wintypes.POINT(cx, cy)
        wfp = int(u32.WindowFromPoint(pt) or 0)
        p("便签点击点=(%d,%d) WindowFromPoint=%s 便签=%d"
          % (cx, cy, describe(wfp), int(notes.winId())))
        u32.SetCursorPos(cx, cy)
        QTimer.singleShot(150, lambda: u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None))
        QTimer.singleShot(250, lambda: u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None))
        QTimer.singleShot(600, s2)

    def s2():
        p("当前前台=%s 便签active=%s" % (describe(foreground()), notes.isActiveWindow()))
        do_drag("S2便签前台", s3_prepare)

    def s3_prepare():
        # 便签前台后等待 3 秒再拖（排除刚激活的瞬态）
        print("\n==== 便签前台静置 3 秒 ====", flush=True)
        QTimer.singleShot(3000, s3)

    def s3():
        p("当前前台=%s 便签active=%s" % (describe(foreground()), notes.isActiveWindow()))
        do_drag("S3便签前台静置", s4_prepare)

    def s4_prepare():
        # 点桌面空白处让 Progman 回前台，再拖
        print("\n==== 点桌面空白区（Progman 回前台） ====", flush=True)
        u32.SetCursorPos(1800, 1000)
        QTimer.singleShot(150, lambda: u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None))
        QTimer.singleShot(250, lambda: u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None))
        QTimer.singleShot(600, s4)

    def s4():
        p("当前前台=%s 便签active=%s" % (describe(foreground()), notes.isActiveWindow()))
        do_drag("S4 Progman前台", finish)

    def finish():
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
