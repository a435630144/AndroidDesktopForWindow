# -*- coding: utf-8 -*-
"""探针十 v2：坐实「逐像素 alpha 命中测试」并验证修复方案（干净环境版）。

假设：主窗口是 WA_TranslucentBackground 分层窗口，Windows 命中测试跳过
全透明像素（无论 WM_NCHITTEST 返回什么），导致：
  - 拖到空白格释放 -> drop 落不到我们窗口（问题3）
  - 空白区按下 -> 点击穿透 -> 橡皮筋不启动（问题4）

验证（整理模式）：
  1. 空白点 SendMessage(WM_NCHITTEST) vs WindowFromPoint 差异
  2. 修复候选 A：setMask(全窗矩形) 后 WindowFromPoint 是否归我们
  3. 端到端：拖动期间给窗口加 mask，drop 是否落下、图标是否移动
  4. 修复候选 B：SetWindowRgn(全窗) 后是否归我们
  5. 修复候选 C：paintEvent 全窗填充 alpha=1 后是否归我们（alpha>0 即可命中）
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

from PySide6.QtCore import QPoint, QRect, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src import appsource, win32_layer  # noqa: E402
from src.desktop_window import DesktopWindow  # noqa: E402
from src.storage import Storage  # noqa: E402

STATE_PATH = Path(os.path.expandvars(r"%APPDATA%\PhoneDesktop\state.json"))
STATE_BACKUP = None

u32 = ctypes.windll.user32
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetClassNameW.restype = ctypes.c_int
u32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.SendMessageW.restype = wintypes.LPARAM
u32.WindowFromPoint.argtypes = [wintypes.POINT]
u32.WindowFromPoint.restype = wintypes.HWND
u32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u32.SetCursorPos.restype = wintypes.BOOL
u32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                            wintypes.DWORD, ctypes.c_void_p]
u32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
u32.GetWindow.restype = wintypes.HWND
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.IsWindowVisible.restype = wintypes.BOOL
u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
u32.GetWindowLongW.restype = wintypes.LONG
u32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
u32.SetWindowRgn.restype = ctypes.c_int
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.GetWindowThreadProcessId.restype = wintypes.DWORD
u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.GetWindowRect.restype = wintypes.BOOL
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x2, 0x4
WM_NCHITTEST = 0x84
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000

SHELL_CLASSES = {"Progman", "WorkerW", "Windows.UI.Core.CoreWindow", "Shell_TrayWnd",
                 "Shell_SecondaryTrayWnd", "DV2ControlHost", "Button", "IME",
                 "MSCTFIME UI", "SysShadow"}


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


def hit_test_send(hwnd, x, y):
    lparam = (int(y) << 16) | (int(x) & 0xFFFF)
    return int(u32.SendMessageW(wintypes.HWND(hwnd), WM_NCHITTEST, 0, lparam))


def _pid_of(hwnd):
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return pid.value


def _protected_pids():
    """自身 + 全部祖先进程（agent / WorkBuddy 宿主），绝不能把它们的窗口移走。"""
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
    if cur and cur not in pids:
        pids.add(cur)
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


def point_clear(x, y):
    """(x,y) 物理点没有被外来应用窗口遮挡（我方窗口或 shell 桌面层均可）。"""
    h = wfp(x, y)
    if not h:
        return False, 0
    if _pid_of(h) == os.getpid():
        return True, h
    cls = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(wintypes.HWND(h), cls, 256)
    if cls.value in SHELL_CLASSES or cls.value in ("SHELLDLL_DefView", "SysListView32"):
        return True, h
    return False, h


def driver_drag(x1, y1, x2, y2, steps=25, step_delay=0.035, hold=0.12):
    samples = []

    def run():
        u32.SetCursorPos(x1, y1)
        time.sleep(0.1)
        u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
        time.sleep(hold)
        for i in range(1, steps + 1):
            t = i / steps
            x = int(x1 + (x2 - x1) * t)
            y = int(y1 + (y2 - y1) * t)
            u32.SetCursorPos(x, y)
            h = wfp(x, y)
            cls = ctypes.create_unicode_buffer(128)
            if h:
                u32.GetClassNameW(wintypes.HWND(h), cls, 128)
            samples.append((x, y, h, cls.value))
            time.sleep(step_delay)
        time.sleep(0.12)
        u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)

    threading.Thread(target=run, daemon=True).start()
    return samples


def main():
    global STATE_BACKUP, MOVED
    MOVED = []
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

    def run():
        time.sleep(0.3)
        MOVED = minimize_others()
        time.sleep(0.4)
        # 整理模式
        storage.set_setting("hide_native_icons", True)
        storage.set_setting("auto_clone_desktop", True)
        window.apply_native_icons_setting()
        time.sleep(0.5)
        window.rebuild()
        time.sleep(0.3)

        mh = int(window.winId())
        ex = u32.GetWindowLongW(wintypes.HWND(mh), GWL_EXSTYLE) & 0xFFFFFFFF
        p("主窗口 exstyle=0x%08x LAYERED=%s (主窗口=%d)"
          % (ex, bool(ex & WS_EX_LAYERED), mh))

        d = window.devicePixelRatio()
        # 空白点：屏幕中部偏左（无图标处）
        ex_x, ex_y = int(700 * d), int(700 * d)
        ok, h = point_clear(ex_x, ex_y)
        p("空白点 (%d,%d) 环境校验: %s -> %s" % (ex_x, ex_y, "OK" if ok else "被占用!",
                                                describe(h)))

        ids = list(window.icons.keys())
        icon = window.icons[ids[0]]
        g = icon.geometry()
        ix, iy = int((g.x() + g.width() // 2) * d), int((g.y() + 30) * d)
        ok2, h2 = point_clear(ix, iy)
        p("图标点 (%d,%d) 环境校验: %s -> %s" % (ix, iy, "OK" if ok2 else "被占用!",
                                                describe(h2)))

        p("\n==== 1. 空白点对比（整理模式，无拖动） ====")
        p("点(%d,%d) SendMessage(WM_NCHITTEST)->%d  WindowFromPoint->%s"
          % (ex_x, ex_y, hit_test_send(mh, ex_x, ex_y), describe(wfp(ex_x, ex_y))))
        p("图标点(%d,%d) SendMessage->%d  WindowFromPoint->%s"
          % (ix, iy, hit_test_send(mh, ix, iy), describe(wfp(ix, iy))))

        p("\n==== 2. 修复候选 A：setMask(全窗) ====")
        window.setMask(QRect(QPoint(0, 0), window.size()))
        time.sleep(0.4)
        p("setMask 后空白点 WindowFromPoint->%s (主窗口=%d)"
          % (describe(wfp(ex_x, ex_y)), mh))
        p("setMask 后图标点 WindowFromPoint->%s" % describe(wfp(ix, iy)))
        pm = window.grab()
        opaque = 0
        img = pm.toImage()
        for yy in range(0, img.height(), 8):
            for xx in range(0, img.width(), 8):
                if (img.pixel(xx, yy) >> 24) & 0xFF:
                    opaque += 1
        p("setMask 后窗口 grab 不透明采样点=%d（应仍很少：mask 不影响视觉）" % opaque)

        p("\n==== 3. 端到端：带 mask 拖动 ====")
        old = (icon.entry.get("col"), icon.entry.get("row"))
        eid = icon.entry["id"]
        cell = window._cell()
        origin = window._origin()
        x2 = int((origin[0] + 3 * cell[0] + cell[0] // 2) * d)
        y2 = int((origin[1] + 1 * cell[1] + 30) * d)
        ok3, h3 = point_clear(x2, y2)
        p("拖动 (%d,%d)->(%d,%d) 原位置=%s 目标点环境=%s -> %s"
          % (ix, iy, x2, y2, old, "OK" if ok3 else "被占用!", describe(h3)))
        samples = driver_drag(ix, iy, x2, y2)
        QTimer.singleShot(3000, lambda: check3(mh, eid, old, ex_x, ex_y, samples, x2, y2))

    def check3(mh, eid, old, ex_x, ex_y, samples, x2, y2):
        e = storage.find_entry(eid)
        new = (e.get("col"), e.get("row"))
        p("带 mask 拖动结果: %s -> %s %s" % (old, new,
                                            "✓ 成功" if new != old else "✗ 未移动"))
        mine = sum(1 for (_, _, h, _) in samples if h == mh)
        shell = sum(1 for (_, _, h, c) in samples
                    if c in ("SysListView32", "Progman", "SHELLDLL_DefView"))
        p("[驱动线程] 沿途 %d 采样: 我方窗口=%d 原生桌面层=%d 其他=%d"
          % (len(samples), mine, shell, len(samples) - mine - shell))
        p("[驱动线程] 终点 (%d,%d) 下窗口=%s" % (x2, y2, describe(wfp(x2, y2))))

        p("\n==== 4. 修复候选 B：SetWindowRgn(全窗) ====")
        window.clearMask()
        time.sleep(0.4)
        p("clearMask 后空白点 WindowFromPoint->%s" % describe(wfp(ex_x, ex_y)))
        gdi32 = ctypes.windll.gdi32
        gdi32.CreateRectRgn.restype = wintypes.HANDLE
        rgn = gdi32.CreateRectRgn(0, 0, 3000, 3000)
        r = u32.SetWindowRgn(wintypes.HWND(mh), wintypes.HANDLE(rgn), True)
        p("SetWindowRgn 返回=%d" % r)
        time.sleep(0.4)
        p("SetWindowRgn 后空白点 WindowFromPoint->%s (主窗口=%d)"
          % (describe(wfp(ex_x, ex_y)), mh))
        u32.SetWindowRgn(wintypes.HWND(mh), None, True)
        time.sleep(0.4)
        p("还原后空白点 WindowFromPoint->%s" % describe(wfp(ex_x, ex_y)))

        p("\n==== 5. 修复候选 C：alpha=1 全窗填充 ====")
        orig_paint = window.paintEvent

        def fill_paint(ev):
            orig_paint(ev)
            # 全窗 SourceOver 填充 alpha=1：空白像素 alpha 0 -> 1（仍不可见，但可命中）
            qp = QPainter(window)
            qp.fillRect(window.rect(), QColor(0, 0, 0, 1))
            qp.end()

        window.paintEvent = fill_paint
        window.update()  # 触发一次全窗重绘，让填充进 surface
        time.sleep(0.5)
        p("alpha=1 填充后空白点 WindowFromPoint->%s (主窗口=%d)"
          % (describe(wfp(ex_x, ex_y)), mh))
        p("alpha=1 填充后图标点 WindowFromPoint->%s" % describe(wfp(ix, iy)))
        pm2 = window.grab()
        img2 = pm2.toImage()
        op2 = 0
        for yy in range(0, img2.height(), 8):
            for xx in range(0, img2.width(), 8):
                if (img2.pixel(xx, yy) >> 24) & 0xFF:
                    op2 += 1
        p("alpha=1 填充后 grab 不透明采样点=%d" % op2)
        window.paintEvent = orig_paint
        window.update()
        time.sleep(0.5)
        p("还原绘制后空白点 WindowFromPoint->%s（backing store 可能不清空，仅供参考）"
          % describe(wfp(ex_x, ex_y)))
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
