# -*- coding: utf-8 -*-
"""一次性探针：坐实 3 件事
1. QFileIconProvider 可用尺寸（是否导致放大模糊）
2. SHGetFileInfoW 对 shell CLSID 路径（此电脑/回收站）的提取能力
3. AppIcon 拖拽事件链为何断（mouseMoveEvent 是否到达、QDrag 是否执行）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QFileIconProvider
from PySide6.QtCore import QFileInfo

from src import appsource
from src.iconwidget import AppIcon
from src.storage import Storage

app = QApplication([])

print("========== 1. QFileIconProvider 可用尺寸 ==========")
desktop = appsource.shell_known_folder("desktop")
print("desktop:", desktop)
prov = QFileIconProvider()
try:
    items = os.listdir(desktop)[:6]
except Exception as e:
    items = []
    print("listdir err:", e)
for name in items:
    p = os.path.join(desktop, name)
    ic = prov.icon(QFileInfo(p))
    sizes = ic.availableSizes()
    print("  %-30s sizes=%s" % (name[:30], [(s.width(), s.height()) for s in sizes]))

print()
print("========== 2. SHGetFileInfoW 提取 CLSID 图标 ==========")
import ctypes
from ctypes import wintypes

u32 = ctypes.windll.user32
sh32 = ctypes.windll.shell32
SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000
SHGFI_SMALLICON = 0x000000001


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [("hIcon", wintypes.HANDLE),
                ("iIcon", ctypes.c_int),
                ("dwAttributes", wintypes.DWORD),
                ("szDisplayName", wintypes.WCHAR * 260),
                ("szTypeName", wintypes.WCHAR * 80)]


class BITMAP(ctypes.Structure):
    _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG),
                ("bmHeight", wintypes.LONG), ("bmWidthBytes", wintypes.LONG),
                ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                ("bmBits", wintypes.LPVOID)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


def try_shgfi(path, flags=SHGFI_ICON | SHGFI_LARGEICON):
    info = SHFILEINFOW()
    ok = sh32.SHGetFileInfoW(path, 0, ctypes.byref(info),
                             ctypes.sizeof(info), flags)
    if not ok or not info.hIcon:
        return None
    return info.hIcon


def hicon_size(h):
    info = ICONINFO()
    if not u32.GetIconInfo(ctypes.c_void_p(h), ctypes.byref(info)):
        return None
    bm = BITMAP()
    g32 = ctypes.windll.gdi32
    if info.hbmColor:
        g32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
        g32.GetObjectW(info.hbmColor, ctypes.sizeof(bm), ctypes.byref(bm))
        return (bm.bmWidth, bm.bmHeight)
    return None


for entry in appsource.BUILTIN_APPS[:3]:
    name, target = entry["name"], entry["target"]
    h = try_shgfi(target)
    print("  %-12s target=%-45s hicon=%s size=%s" % (name, target[:45], h, hicon_size(h) if h else None))

# exe 路径的图标（带 icon_path）
for entry in appsource.BUILTIN_APPS[2:5]:
    ip = os.path.expandvars(entry.get("icon_path", ""))
    h = try_shgfi(ip) if ip else None
    print("  %-12s icon_path=%-45s size=%s" % (entry["name"], ip[:45], hicon_size(h) if h else None))

# 对比真实 exe
h = try_shgfi(os.path.expandvars(r"%SystemRoot%\System32\notepad.exe"))
print("  notepad.exe hicon size=%s" % (hicon_size(h) if h else None,))

print()
print("========== 3. 拖拽事件链 ==========")
storage = Storage()
# 构造一个测试条目
entry = {"id": "probe-1", "type": "app", "col": 0, "row": 0,
         "app": {"id": "sys-notepad", "name": "记事本", "target": "notepad",
                 "icon_path": "%SystemRoot%\\System32\\notepad.exe"}}
icon = AppIcon(entry, 72)
icon.setParent(None)  # 顶层，避免 DesktopWindow 的 NCHITTEST 干扰
events = []
icon.dragStarted.connect(lambda: events.append("dragStarted"))
orig_exec = icon._exec_drag


def traced_exec():
    events.append("exec_drag_enter")
    # 不真正 exec（模态会卡住），只验证链路
    events.append("exec_drag_would_run")
    icon._press_pos = None


icon._exec_drag = traced_exec

from PySide6.QtTest import QTest  # noqa: E402  (可能不存在则忽略)

try:
    QTest.mousePress(icon, Qt.LeftButton, pos=QPoint(10, 10))
    events.append("pressed")
    QTest.mouseMove(icon, QPoint(80, 80))
    events.append("moved")
    QTest.mouseRelease(icon, Qt.LeftButton, pos=QPoint(80, 80))
    events.append("released")
except Exception as e:
    events.append("QTest err: %r" % e)

print("  events:", events)

# 再测：QApplication.startDragDistance
print("  startDragDistance:", QApplication.startDragDistance())

print()
print("========== 4. 桌面 listview 窗口查找 ==========")


def find_desktop_listview():
    progman = u32.FindWindowW("Progman", None)
    print("  progman:", progman)
    # Progman -> SHELLDLL_DefView
    dv = u32.FindWindowExW(progman, None, "SHELLDLL_DefView", None)
    print("  defview under progman:", dv)
    # 枚举 WorkerW
    workerw = u32.FindWindowExW(None, None, "WorkerW", None)
    found = []
    while workerw:
        d = u32.FindWindowExW(workerw, None, "SHELLDLL_DefView", None)
        if d:
            lv = u32.FindWindowExW(d, None, "SysListView32", None)
            found.append((int(workerw), int(d), int(lv) if lv else None))
        workerw = u32.FindWindowExW(None, workerw, "WorkerW", None)
    print("  workerw with defview:", found)
    return found


find_desktop_listview()
print()
print("done")
