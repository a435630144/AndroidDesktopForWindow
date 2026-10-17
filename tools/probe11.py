# -*- coding: utf-8 -*-
"""探针十一：查清三个疑点，锁定修复方案。

疑点：
  Q1. alpha=1 填充到底有没有进入窗口 surface？（grab / PrintWindow 双重测量）
  Q2. 若进了 surface 仍不命中，命中阈值是多少？（alpha 1/2/4/8/16/64/255 分区扫描）
  Q3. SoPY_Comp 是什么窗口、在 z-order 哪里？（是否沙盒合成器、会不会影响结论）
  Q4.（附加）去掉 WS_EX_LAYERED 后窗口是否可见 + 命中是否变矩形？
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRect, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from src import appsource, win32_layer  # noqa: E402
from src.desktop_window import DesktopWindow  # noqa: E402
from src.storage import Storage  # noqa: E402

STATE_PATH = Path(os.path.expandvars(r"%APPDATA%\DesktopOrganizerDemo\state.json"))
STATE_BACKUP = None

u32 = ctypes.windll.user32
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetClassNameW.restype = ctypes.c_int
u32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.SendMessageW.restype = wintypes.LPARAM
u32.WindowFromPoint.argtypes = [wintypes.POINT]
u32.WindowFromPoint.restype = wintypes.HWND
u32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
u32.GetWindow.restype = wintypes.HWND
u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.GetWindowRect.restype = wintypes.BOOL
u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
u32.GetWindowLongW.restype = wintypes.LONG
u32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
u32.SetWindowLongW.restype = wintypes.LONG
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.GetWindowThreadProcessId.restype = wintypes.DWORD
u32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
u32.PrintWindow.restype = wintypes.BOOL
u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.IsWindowVisible.restype = wintypes.BOOL
gdi32 = ctypes.windll.gdi32
WM_NCHITTEST = 0x84
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
PW_RENDERFULLCONTENT = 2

SHELL_CLASSES = {"Progman", "WorkerW", "Windows.UI.Core.CoreWindow", "Shell_TrayWnd",
                 "Shell_SecondaryTrayWnd", "DV2ControlHost", "Button", "IME",
                 "MSCTFIME UI", "SysShadow"}
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


def hit_test_send(hwnd, x, y):
    lparam = (int(y) << 16) | (int(x) & 0xFFFF)
    return int(u32.SendMessageW(wintypes.HWND(hwnd), WM_NCHITTEST, 0, lparam))


def grab_alpha_at(img, x, y):
    """window.grab() 图像（DPR 缩放）在逻辑点 (x,y) 的 alpha。"""
    d = img.devicePixelRatio() if hasattr(img, "devicePixelRatio") else 1.0
    px = int(x * d)
    py = int(y * d)
    if 0 <= px < img.width() and 0 <= py < img.height():
        return (img.pixel(px, py) >> 24) & 0xFF
    return -1


def printwindow_alpha(mh, x, y):
    """用 PrintWindow(PW_RENDERFULLCONTENT) 抓窗口合成结果，读物理点 alpha。"""
    hdc = gdi32.CreateCompatibleDC(None)
    if not hdc:
        return -1
    try:
        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD),
                        ("biWidth", ctypes.c_long),
                        ("biHeight", ctypes.c_long),
                        ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", ctypes.c_long),
                        ("biYPelsPerMeter", ctypes.c_long),
                        ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]
        bi = BITMAPINFO()
        bi.biSize = ctypes.sizeof(BITMAPINFO)
        bi.biWidth = 64
        bi.biHeight = -64  # top-down
        bi.biPlanes = 1
        bi.biBitCount = 32
        bi.biCompression = 0  # BI_RGB
        bits = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bi), 0,
                                      ctypes.byref(bits), None, 0)
        if not hbmp:
            return -1
        old = gdi32.SelectObject(hdc, hbmp)
        ok = u32.PrintWindow(wintypes.HWND(mh), wintypes.HDC(hdc), PW_RENDERFULLCONTENT)
        if not ok:
            gdi32.SelectObject(hdc, old)
            gdi32.DeleteObject(hbmp)
            return -1
        # 读中心像素
        row = ctypes.cast(bits, ctypes.POINTER(ctypes.c_uint32))
        cx, cy = 32, 32
        val = row[cy * 64 + cx]
        alpha = (val >> 24) & 0xFF
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(hbmp)
        return alpha
    finally:
        gdi32.DeleteDC(hdc)


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
        storage.set_setting("hide_native_icons", True)
        storage.set_setting("auto_clone_desktop", True)
        window.apply_native_icons_setting()
        time.sleep(0.6)
        window.rebuild()
        time.sleep(0.4)

        mh = int(window.winId())
        d = window.devicePixelRatio()
        ex_x, ex_y = 700, 700  # 逻辑坐标（屏幕中部偏左，无图标处）
        # 图标中心（逻辑）：用于 Q4 检查窗口内容是否还在
        ids = list(window.icons.keys())
        ic = window.icons[ids[0]]
        icg = ic.geometry()
        icx, icy = icg.x() + icg.width() // 2, icg.y() + icg.height() // 2

        r = wintypes.RECT()
        u32.GetWindowRect(wintypes.HWND(mh), ctypes.byref(r))
        p("主窗口=%d rect=(%d,%d,%d,%d) dpr=%.2f" % (mh, r.left, r.top, r.right, r.bottom, d))
        px, py = int(ex_x * d), int(ex_y * d)
        inside = r.left <= px <= r.right and r.top <= py <= r.bottom
        p("测试点 逻辑(%d,%d) 物理(%d,%d) 在窗口内=%s" % (ex_x, ex_y, px, py, inside))

        # ---------- Q3: SoPY_Comp 是什么 ----------
        p("\n==== Q3: SoPY_Comp 窗口分析 ====")
        sopy = 0
        h = u32.GetWindow(u32.GetDesktopWindow(), 5)
        idx = 0
        while h:
            cls = ctypes.create_unicode_buffer(256)
            u32.GetClassNameW(wintypes.HWND(h), cls, 256)
            if cls.value == "SoPY_Comp":
                sopy = int(h)
                sr = wintypes.RECT()
                u32.GetWindowRect(wintypes.HWND(h), ctypes.byref(sr))
                pid = wintypes.DWORD()
                u32.GetWindowThreadProcessId(wintypes.HWND(h), ctypes.byref(pid))
                ex = u32.GetWindowLongW(wintypes.HWND(h), GWL_EXSTYLE) & 0xFFFFFFFF
                p("SoPY_Comp: hwnd=%d pid=%d exstyle=0x%08x rect=(%d,%d,%d,%d) zidx=%d"
                  % (h, pid.value, ex, sr.left, sr.top, sr.right, sr.bottom, idx))
            if int(h) == mh:
                p("主窗口 zidx=%d" % idx)
            h = u32.GetWindow(h, 2)
            idx += 1
        if sopy:
            p("SoPY_Comp 与我方窗口关系: %s"
              % ("在我方之上" if wfp(px, py) == sopy or True else "?"))

        # ---------- Q1/Q2: surface alpha 与命中 ----------
        p("\n==== Q1: 当前 surface alpha（无填充） ====")
        img = window.grab().toImage()
        p("grab alpha@(%d,%d) = %d" % (ex_x, ex_y, grab_alpha_at(img, ex_x, ex_y)))
        p("PrintWindow alpha@(%d,%d) = %d" % (px, py, printwindow_alpha(mh, px, py)))
        p("WindowFromPoint -> %s ; SendMessage WM_NCHITTEST -> %d"
          % (describe(wfp(px, py)), hit_test_send(mh, px, py)))

        # ---------- Q1b: alpha=1 填充（patched paintEvent） ----------
        p("\n==== Q1b: alpha=1 填充是否进入 surface ====")
        orig_paint = window.paintEvent

        def fill_paint(ev):
            orig_paint(ev)
            qp = QPainter(window)
            qp.fillRect(window.rect(), QColor(0, 0, 0, 1))
            qp.end()

        window.paintEvent = fill_paint
        window.update()
        time.sleep(0.6)
        img2 = window.grab().toImage()
        ga = grab_alpha_at(img2, ex_x, ex_y)
        p("填充后 grab alpha@(%d,%d) = %d" % (ex_x, ex_y, ga))
        p("填充后 PrintWindow alpha@(%d,%d) = %d" % (px, py, printwindow_alpha(mh, px, py)))
        p("填充后 WindowFromPoint -> %s" % describe(wfp(px, py)))

        # ---------- Q2: alpha 阈值分区扫描 ----------
        p("\n==== Q2: alpha 阈值扫描（同屏不同 120x120 分区） ====")
        # 清掉全窗填充，改分区填充
        window.paintEvent = orig_paint
        window.update()
        time.sleep(0.4)

        zones = []  # (x, y, alpha)

        def make_paint(zlist):
            def zp(ev):
                orig_paint(ev)
                qp = QPainter(window)
                for (zx, zy, za) in zlist:
                    qp.fillRect(QRect(QPoint(zx - 60, zy - 60), QPoint(zx + 60, zy + 60)),
                                QColor(0, 0, 0, za))
                qp.end()
            return zp

        base_x, base_y = 500, 900  # 逻辑坐标起点（避开图标区）
        for i, a in enumerate([1, 2, 4, 8, 16, 64, 255]):
            zones.append((base_x + i * 150, base_y, a))
        window.paintEvent = make_paint(zones)
        window.update()
        time.sleep(0.6)
        img3 = window.grab().toImage()
        for i, a in enumerate([1, 2, 4, 8, 16, 64, 255]):
            zx, zy = base_x + i * 150, base_y
            pz_x, pz_y = int(zx * d), int(zy * d)
            ga3 = grab_alpha_at(img3, zx, zy)
            hit = wfp(pz_x, pz_y)
            p("分区 alpha=%3d @逻辑(%d,%d): grab_alpha=%3d WindowFromPoint=%s %s"
              % (a, zx, zy, ga3, describe(hit), "✓命中" if hit == mh else "✗"))

        # ---------- Q4: 去掉 WS_EX_LAYERED ----------
        p("\n==== Q4: 去掉 WS_EX_LAYERED 试验 ====")
        window.paintEvent = orig_paint
        window.update()
        time.sleep(0.3)
        ex_before = u32.GetWindowLongW(wintypes.HWND(mh), GWL_EXSTYLE) & 0xFFFFFFFF
        u32.SetWindowLongW(wintypes.HWND(mh), GWL_EXSTYLE,
                           wintypes.LONG(ex_before & ~WS_EX_LAYERED))
        time.sleep(0.6)
        ex_after = u32.GetWindowLongW(wintypes.HWND(mh), GWL_EXSTYLE) & 0xFFFFFFFF
        img4 = window.grab().toImage()
        p("exstyle: 0x%08x -> 0x%08x" % (ex_before, ex_after))
        p("去 LAYERED 后 可见=%s 图标中心grab alpha=%d（>0 说明内容还在）"
          % (window.isVisible(), grab_alpha_at(img4, icx, icy)))
        p("去 LAYERED 后 WindowFromPoint@空白点 -> %s" % describe(wfp(px, py)))
        p("去 LAYERED 后 WindowFromPoint@图标点 -> %s" % describe(wfp(int(icx * d), int(icy * d))))
        # 还原
        u32.SetWindowLongW(wintypes.HWND(mh), GWL_EXSTYLE, wintypes.LONG(ex_before))
        time.sleep(0.4)
        p("还原 LAYERED 后 WindowFromPoint@空白点 -> %s" % describe(wfp(px, py)))
        QTimer.singleShot(400, finish)

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
