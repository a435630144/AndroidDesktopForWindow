# -*- coding: utf-8 -*-
"""探针九：用独立驱动线程模拟真实鼠标拖动（修正探针 artifact）。

关键修正：QDrag.exec() 内部是 Windows 原生消息循环，Qt 定时器在拖动期间
不触发——此前用 QTimer 驱动光标移动全部停摆。真实用户的鼠标移动与
Qt 事件循环无关，因此改用独立 Python 线程按真实时序移动光标。

场景：
  S1 原生模式（用户默认）：拖图标 -> col/row 改变？
  S2 整理模式：拖图标 -> col/row 改变？
  S3 橡皮筋框选 + 多选整体拖动（整理模式）
全链路插桩（dragStarted/dragEnter/drop/_drop_internal/NCHITTEST）。
"""
import ctypes
import os
import sys
import threading
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

# 【安全禁令·2026-10-17】探针绝不读写用户的 state.json——用临时状态文件，
# 避免进程被终止时把测试布局写进用户数据。
STATE_PATH = Path(os.environ.get("TEMP", ".")) / "desktoporg_probe_state.json"
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


def wfp(x, y):
    """光标下真实窗口（物理坐标）。"""
    pt = wintypes.POINT(x, y)
    return int(u32.WindowFromPoint(pt) or 0)


SHELL_CLASSES = {"Progman", "WorkerW", "Windows.UI.Core.CoreWindow", "Shell_TrayWnd",
                 "Shell_SecondaryTrayWnd", "DV2ControlHost", "Button", "IME",
                 "MSCTFIME UI", "SysShadow"}
# 无标题但必须放过的系统类窗口（工具提示等）
UNSAFE_UNSAFE = {"tooltips_class32", "SysHeader32", "ScrollBar", "ComboLBox"}


def kill_stale_pythons():
    """【安全禁令·2026-10-17】绝不移动/最小化/关闭用户的任何窗口。
    事故：探针为"清理测试环境"把用户窗口移到屏幕外，进程被 SIGTERM 时
    还原代码没跑，导致用户 Edge/Chrome/微信等全部滞留屏幕外无法使用。
    测试点被占用时用实时选点（参考 probe9.driver_band）或跳过场景，
    永远不要动用户的窗口。"""
    return []


def _pid_of(hwnd):
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return pid.value


def _protected_pids():
    """自身 + 全部祖先进程（agent / WorkBuddy 宿主），绝不能移走。"""
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


def point_clear(x, y):
    """(x,y) 物理点没有被外来应用窗口遮挡（我方窗口或 shell 桌面层均可）。"""
    pt = wintypes.POINT(x, y)
    h = int(u32.WindowFromPoint(pt) or 0)
    if not h:
        return False, 0
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(wintypes.HWND(h), ctypes.byref(pid))
    if pid.value == os.getpid():
        return True, h
    cls = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(wintypes.HWND(h), cls, 256)
    if cls.value in SHELL_CLASSES or cls.value in ("SHELLDLL_DefView", "SysListView32"):
        return True, h  # 原生桌面层：本就该在（原生模式空白区穿透是设计行为）
    return False, h


def driver_drag(x1, y1, x2, y2, steps=25, step_delay=0.035, hold=0.12, expect_hwnd=None):
    """独立线程按真实时序驱动鼠标拖动（与 Qt 事件循环完全解耦）。
    沿途采样 WindowFromPoint，记录光标下真实窗口。
    expect_hwnd: 按压点必须是该窗口（我方主窗口），否则外来窗口会截胡，
    直接放弃本次拖动并报告，避免假阴性。绝不移动外来窗口。"""
    samples = []

    def run():
        if expect_hwnd is not None:
            u32.SetCursorPos(x1, y1)
            time.sleep(0.08)
            h0 = wfp(x1, y1)
            if h0 != expect_hwnd:
                print("    [驱动线程] 放弃：按压点(%d,%d)被 %s 占据（非我方窗口）"
                      % (x1, y1, describe(h0)), flush=True)
                return
            print("    [驱动线程] 释放点(%d,%d)当前=%s"
                  % (x2, y2, describe(wfp(x2, y2))), flush=True)
        u32.SetCursorPos(x1, y1)
        time.sleep(0.1)
        u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
        time.sleep(hold)
        for i in range(1, steps + 1):
            t = i / steps
            x = int(x1 + (x2 - x1) * t)
            y = int(y1 + (y2 - y1) * t)
            u32.SetCursorPos(x, y)
            pt = wintypes.POINT(x, y)
            h = int(u32.WindowFromPoint(pt) or 0)
            cls = ctypes.create_unicode_buffer(64)
            u32.GetClassNameW(wintypes.HWND(h), cls, 64)
            samples.append((x, y, h, cls.value))
            time.sleep(step_delay)
        time.sleep(0.12)
        u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
        time.sleep(0.3)
        # 采样去重输出
        uniq = []
        for s in samples:
            if not uniq or uniq[-1][2:] != s[2:]:
                uniq.append(s)
        print("    [驱动线程] 光标下窗口采样: %s"
              % " -> ".join("(%d,%d)%d:%s" % (x, y, h, c) for x, y, h, c in uniq),
              flush=True)

    threading.Thread(target=run, daemon=True).start()


def driver_drag_path(points, hold=0.12):
    """沿路径点拖动（用于橡皮筋）。"""
    def run():
        u32.SetCursorPos(points[0][0], points[0][1])
        time.sleep(0.1)
        u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
        time.sleep(hold)
        for x, y in points[1:]:
            u32.SetCursorPos(x, y)
            time.sleep(0.03)
        time.sleep(0.12)
        u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
    threading.Thread(target=run, daemon=True).start()


def driver_band(press_candidates, release_candidates, mh):
    """橡皮筋驱动：实时选点——按压/释放前现场校验光标下必须是我方窗口，
    被漂移浮层（HRNETFLOWTRAY 等）占据就换候选点。返回 None=放弃。"""
    def run():
        chosen_p = None
        for (px, py) in press_candidates:
            u32.SetCursorPos(px, py)
            time.sleep(0.06)
            if wfp(px, py) == mh:
                chosen_p = (px, py)
                break
        if chosen_p is None:
            print("    [驱动线程] 所有候选按压点均被占据，放弃框选", flush=True)
            return
        chosen_r = None
        for (rx, ry) in release_candidates:
            if wfp(rx, ry) == mh:
                chosen_r = (rx, ry)
                break
        if chosen_r is None:
            print("    [驱动线程] 所有候选释放点均被占据，放弃框选", flush=True)
            return
        px, py = chosen_p
        rx, ry = chosen_r
        print("    [驱动线程] 框选 (%d,%d)->(%d,%d)" % (px, py, rx, ry), flush=True)
        u32.SetCursorPos(px, py)
        time.sleep(0.1)
        u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
        time.sleep(0.12)
        u32.SetCursorPos((px + rx) // 2, (py + ry) // 2)
        time.sleep(0.06)
        u32.SetCursorPos(rx, ry)
        time.sleep(0.12)
        u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
    threading.Thread(target=run, daemon=True).start()


def main():
    global STATE_BACKUP
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
    storage.add_app({"id": "sys-pc", "name": "此电脑",
                     "target": "::{20D04FE0-3AEA-1069-A2D8-08002B30309D}",
                     "builtin": True}, col=2, row=0)
    storage.save()

    window = DesktopWindow(storage)
    window.show_desktop()
    layer = WidgetLayer(storage)
    mh = int(window.winId())  # 主窗口 hwnd：驱动线程实时校验按压点用

    # ---------- 插桩（调用原版） ----------
    orig_press = AppIcon.mousePressEvent
    orig_move = AppIcon.mouseMoveEvent
    drag_t0 = [None]

    def traced_press(self, e):
        p("icon.press global=%s" % e.globalPosition().toPoint())
        orig_press(self, e)

    def traced_move(self, e):
        if self._press_pos is not None:
            p("icon.move global=%s delta=%d" % (e.globalPosition().toPoint(),
                                                (e.pos() - self._press_pos).manhattanLength()))
        orig_move(self, e)

    AppIcon.mousePressEvent = traced_press
    AppIcon.mouseMoveEvent = traced_move

    orig_drag_enter = DesktopWindow.dragEnterEvent
    orig_drag_move = DesktopWindow.dragMoveEvent
    orig_drag_leave = DesktopWindow.dragLeaveEvent
    orig_drop = DesktopWindow.dropEvent
    orig_drop_internal = DesktopWindow._drop_internal
    move_count = [0]

    def traced_drag_enter(self, e):
        p("dragEnter(主窗口) hasMime=%s drag_active=%s"
          % (e.mimeData().hasFormat("application/x-desktoporg-item"), self._drag_active))
        return orig_drag_enter(self, e)

    def traced_drag_move(self, e):
        move_count[0] += 1
        if move_count[0] <= 3 or move_count[0] % 20 == 0:
            p("dragMove(主窗口) #%d pos=%s drag_active=%s"
              % (move_count[0], e.position().toPoint(), self._drag_active))
        return orig_drag_move(self, e)

    def traced_drag_leave(self, e):
        p("dragLeave(主窗口) !! drag_active=%s" % self._drag_active)
        return orig_drag_leave(self, e)

    def traced_drop(self, e):
        p("dropEvent(主窗口) pos=%s drag_active=%s" % (e.position().toPoint(),
                                                       self._drag_active))
        return orig_drop(self, e)

    def traced_drop_internal(self, payload, pos):
        p("_drop_internal payload=%r pos=%s" % (payload, pos))
        return orig_drop_internal(self, payload, pos)

    DesktopWindow.dragEnterEvent = traced_drag_enter
    DesktopWindow.dragMoveEvent = traced_drag_move
    DesktopWindow.dragLeaveEvent = traced_drag_leave
    DesktopWindow.dropEvent = traced_drop
    DesktopWindow._drop_internal = traced_drop_internal

    orig_native = DesktopWindow.nativeEvent
    ht_count = [0]

    def traced_native(self, eventType, message):
        try:
            if eventType in (b"windows_generic_MSG", "windows_generic_MSG"):
                from ctypes import wintypes as wt
                msg = wt.MSG.from_address(int(message))
                if msg.message == 0x84:
                    ht_count[0] += 1
                    x = ctypes.c_int16(msg.lParam & 0xFFFF).value
                    y = ctypes.c_int16((msg.lParam >> 16) & 0xFFFF).value
                    r = orig_native(self, eventType, message)
                    if self._drag_active:
                        p("NCHITTEST(%d,%d) drag_active=True -> %s" % (x, y, r[1]))
                    return r
        except Exception:
            pass
        return orig_native(self, eventType, message)

    DesktopWindow.nativeEvent = traced_native

    def connect_drag_signals():
        move_count[0] = 0
        for icon in window.icons.values():
            try:
                icon.dragStarted.disconnect()
                icon.dragFinished.disconnect()
            except Exception:
                pass
            icon.dragStarted.connect(lambda: (drag_t0.__setitem__(0, ts()),
                                              p("!! dragStarted")))
            icon.dragFinished.connect(lambda: p("!! dragFinished（耗时 %dms）"
                                                % (ts() - (drag_t0[0] or ts()))))

    orig_icon_drag_enter = AppIcon.dragEnterEvent
    orig_icon_drag_move = AppIcon.dragMoveEvent

    def traced_icon_drag_enter(self, e):
        p("dragEnter(图标 %s) hasMime=%s" % (self.entry.get("app", {}).get("name", "?"),
                                             e.mimeData().hasFormat("application/x-desktoporg-item")))
        return orig_icon_drag_enter(self, e)

    def traced_icon_drag_move(self, e):
        p("dragMove(图标 %s)" % self.entry.get("app", {}).get("name", "?"))
        return orig_icon_drag_move(self, e)

    AppIcon.dragEnterEvent = traced_icon_drag_enter
    AppIcon.dragMoveEvent = traced_icon_drag_move

    MOVED = []

    def relocate_if_needed():
        """测试点被用户窗口占据时，把布局搬到全屏净空的网格基位。
        【安全禁令】绝不移动用户窗口——只搬我们自己的测试布局。"""
        d = window.devicePixelRatio()
        cell = window._cell()
        org = window._origin()

        def cell_pt(col, row, fx=0.5, fy=20):
            return (int((org[0] + col * cell[0] + cell[0] * fx) * d),
                    int((org[1] + row * cell[1] + fy) * d))

        for base_col in range(0, 15):
            for base_row in range(0, 8):
                pts = [cell_pt(base_col + i, base_row) for i in range(3)]
                pts.append(cell_pt(base_col + 3, base_row + 1))
                if all(wfp(x, y) == mh for (x, y) in pts):
                    if (base_col, base_row) != (0, 0):
                        for i, e in enumerate(storage.layout):
                            e["col"], e["row"] = base_col + i, base_row
                        storage.save()
                        window.rebuild()
                        time.sleep(0.3)
                        p("[环境] 布局搬到净空基位 col=%d row=%d" % (base_col, base_row))
                    return True
        return False

    def run():
        # 先切整理模式（全窗口可命中）再定净空基位；用户窗口绝不动
        storage.set_setting("hide_native_icons", True)
        storage.set_setting("auto_clone_desktop", True)
        window.apply_native_icons_setting()
        time.sleep(0.5)
        window.rebuild()
        time.sleep(0.3)
        if relocate_if_needed():
            QTimer.singleShot(200, s1)
        else:
            p("[环境] 全屏找不到净空测试区（用户窗口占满？），终止本次验证")
            QTimer.singleShot(300, finish)

    def verify(tag, x1, y1, x2=None, y2=None):
        ok1, h1 = point_clear(x1, y1)
        line = "[%s] 起点(%d,%d)->%s" % (tag, x1, y1, "OK" if ok1 else "✗ 被 %s 占据" % describe(h1))
        if x2 is not None:
            ok2, h2 = point_clear(x2, y2)
            line += " 终点(%d,%d)->%s" % (x2, y2, "OK" if ok2 else "✗ 被 %s 占据" % describe(h2))
        p(line)
        return ok1 and (x2 is None or ok2)

    def icon_point(idx, dx_frac=0.5, dy=20):
        ids = list(window.icons.keys())
        icon = window.icons[ids[idx]]
        g = icon.geometry()
        d = window.devicePixelRatio()
        return (int((g.x() + g.width() * dx_frac) * d),
                int((g.y() + dy) * d)), icon

    def target_point(col, row, dy=20):
        cell = window._cell()
        origin = window._origin()
        d = window.devicePixelRatio()
        return (int((origin[0] + col * cell[0] + cell[0] // 2) * d),
                int((origin[1] + row * cell[1] + dy) * d))

    def s1():
        print("\n==== S1 原生模式拖动（用户默认模式） ====", flush=True)
        storage.set_setting("hide_native_icons", False)
        storage.set_setting("auto_clone_desktop", False)
        window.apply_native_icons_setting()
        QTimer.singleShot(500, s1_drag)

    def s1_drag():
        window.rebuild()
        QTimer.singleShot(300, s1_drag2)

    def s1_drag2():
        connect_drag_signals()
        (x1, y1), icon = icon_point(0)
        ec, er = int(icon.entry.get("col", 0)), int(icon.entry.get("row", 0))
        x2, y2 = target_point(ec + 3, er + 1)
        old = (icon.entry.get("col"), icon.entry.get("row"))
        eid = icon.entry["id"]
        p("拖动 (%d,%d)->(%d,%d) 原位置=%s 前台=%s"
          % (x1, y1, x2, y2, old, describe(foreground())))
        if not verify("S1", x1, y1, x2, y2):
            p("✗ 测试点被外来窗口占据，跳过 S1")
            QTimer.singleShot(300, s2)
            return
        driver_drag(x1, y1, x2, y2, expect_hwnd=mh)
        QTimer.singleShot(2500, lambda: s1_check(eid, old))

    def s1_check(eid, old):
        e = storage.find_entry(eid)
        new = (e.get("col"), e.get("row"))
        p("S1 结果: %s -> %s %s" % (old, new, "✓ 拖动成功" if new != old else "✗ 未移动"))
        QTimer.singleShot(300, s2)

    def s2():
        print("\n==== S2 整理模式拖动 ====", flush=True)
        storage.set_setting("hide_native_icons", True)
        storage.set_setting("auto_clone_desktop", True)
        window.apply_native_icons_setting()
        QTimer.singleShot(500, s2_drag)

    def s2_drag():
        window.rebuild()
        QTimer.singleShot(300, s2_drag2)

    def s2_drag2():
        connect_drag_signals()
        (x1, y1), icon = icon_point(0)
        ec, er = int(icon.entry.get("col", 0)), int(icon.entry.get("row", 0))
        x2, y2 = target_point(ec + 4, er + 2)
        old = (icon.entry.get("col"), icon.entry.get("row"))
        eid = icon.entry["id"]
        p("拖动 (%d,%d)->(%d,%d) 原位置=%s" % (x1, y1, x2, y2, old))
        if not verify("S2", x1, y1, x2, y2):
            p("✗ 测试点被外来窗口占据，跳过 S2")
            QTimer.singleShot(300, s3)
            return
        driver_drag(x1, y1, x2, y2, expect_hwnd=mh)
        QTimer.singleShot(2500, lambda: s2_check(eid, old))

    def s2_check(eid, old):
        e = storage.find_entry(eid)
        new = (e.get("col"), e.get("row"))
        p("S2 结果: %s -> %s %s" % (old, new, "✓ 拖动成功" if new != old else "✗ 未移动"))
        QTimer.singleShot(300, s3)

    def s3():
        print("\n==== S3 橡皮筋框选 + 多选整体拖动 ====", flush=True)
        window._selected.clear()
        d = window.devicePixelRatio()
        # 从所有图标的实际位置算包围盒（不假设固定网格原点），框选矩形套住全部图标
        from PySide6.QtCore import QRect as _QR
        bb = None
        for ic in window.icons.values():
            r = _QR(ic.pos(), ic.size())
            bb = r if bb is None else bb.united(r)
        if bb is None:
            p("✗ 无图标可框选"); QTimer.singleShot(300, finish); return
        # 候选按压点：包围盒左侧外、5 个不同高度（实时选点，避开漂移浮层）
        press_cands = [(int((bb.left() - 14) * d),
                        int((bb.top() + (i + 0.5) * bb.height() / 5) * d))
                       for i in range(5)]
        # 候选释放点：包围盒右侧外、5 个不同高度
        rel_cands = [(int((bb.right() + 14) * d),
                      int((bb.top() + (i + 0.5) * bb.height() / 5) * d))
                     for i in range(5)]
        # 预检：至少要有可用的按压/释放候选
        if not any(wfp(x, y) == mh for (x, y) in press_cands):
            p("✗ 框选左侧候选全被占据，跳过 S3")
            QTimer.singleShot(300, finish); return
        if not any(wfp(x, y) == mh for (x, y) in rel_cands):
            p("✗ 框选右侧候选全被占据，跳过 S3")
            QTimer.singleShot(300, finish); return
        driver_band(press_cands, rel_cands, mh)
        QTimer.singleShot(1800, s3_check)

    def s3_check():
        p("框选后 selected=%d/%d" % (len(window._selected), len(window.icons)))
        for eid, ic in window.icons.items():
            e = storage.find_entry(eid)
            p("[调试] 图标 %s pos=%s size=%s entry=(%s,%s) 选中=%s"
              % (eid[:16], ic.pos(), ic.size(), e.get("col"), e.get("row"),
                 eid in window._selected))
        if len(window._selected) < 3:
            p("✗ 框选失败")
            QTimer.singleShot(300, finish)
            return
        p("✓ 框选选中 %d 个" % len(window._selected))
        before = {i: (storage.find_entry(i).get("col"), storage.find_entry(i).get("row"))
                  for i in window._selected}
        (x1, y1), icon = icon_point(0)
        ec, er = int(icon.entry.get("col", 0)), int(icon.entry.get("row", 0))
        x2, y2 = target_point(ec + 5, er + 3)
        p("多选拖动 (%d,%d)->(%d,%d)" % (x1, y1, x2, y2))
        driver_drag(x1, y1, x2, y2, expect_hwnd=mh)
        QTimer.singleShot(2500, lambda: s3_check2(before))

    def s3_check2(before):
        moved = sum(1 for i in window._selected
                    if (storage.find_entry(i).get("col"),
                        storage.find_entry(i).get("row")) != before.get(i))
        p("S3 多选拖动: %d/%d 移动 %s" % (moved, len(before),
                                          "✓ 成功" if moved >= 3 else "✗ 失败"))
        QTimer.singleShot(300, finish)

    def finish():
        print("\n==== 还原环境 ====", flush=True)
        restore_others(MOVED)
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
