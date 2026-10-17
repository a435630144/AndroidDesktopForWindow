# -*- coding: utf-8 -*-
"""探针2：坐实 4 件事
1. QIcon.pixmap(79,79) 到底返回什么（60 放大 vs 60 原样）——确认模糊根因
2. QFileIconProvider 能否直接解析 CLSID 路径
3. SHParseDisplayName + SHGetFileInfo(SHGFI_PIDL) 能否提取此电脑/回收站图标
4. SHGetImageList(jumbo 256) 能否拿到 256 高清 HICON + HICON→QPixmap 转换
"""
import ctypes
import os
import sys
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QFileInfo, QSize, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QFileIconProvider

from src import appsource

app = QApplication([])
u32 = ctypes.windll.user32
sh32 = ctypes.windll.shell32
g32 = ctypes.windll.gdi32


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [("hIcon", wintypes.HANDLE), ("iIcon", ctypes.c_int),
                ("dwAttributes", wintypes.DWORD),
                ("szDisplayName", wintypes.WCHAR * 260), ("szTypeName", wintypes.WCHAR * 80)]


print("========== 1. QIcon.pixmap(79) 实测 ==========")
prov = QFileIconProvider()
desktop = appsource.shell_known_folder("desktop")
sample = None
for name in os.listdir(desktop):
    if name.lower().endswith((".jpg", ".png")):
        sample = os.path.join(desktop, name)
        break
ic = prov.icon(QFileInfo(sample))
pm79 = ic.pixmap(QSize(79, 79))
print("  file:", os.path.basename(sample))
print("  availableSizes:", [(s.width(), s.height()) for s in ic.availableSizes()])
print("  pixmap(79,79) -> %dx%d (60=原样未缩放, 79=被放大)" % (pm79.width(), pm79.height()))
pm320 = ic.pixmap(QSize(320, 320))
print("  pixmap(320,320) -> %dx%d" % (pm320.width(), pm320.height()))

print()
print("========== 2. QFileIconProvider 解析 CLSID ==========")
for clsid in ("::{20D04FE0-3AEA-1069-A2D8-08002B30309D}",):
    i = prov.icon(QFileInfo(clsid))
    print("  %s -> null=%s sizes=%s" % (clsid[:20], i.isNull(),
                                        [(s.width(), s.height()) for s in i.availableSizes()]))

print()
print("========== 3. SHParseDisplayName + PIDL 图标 ==========")


def pidl_for(name: str):
    pidl = ctypes.c_void_p()
    hr = sh32.SHParseDisplayName(name, None, ctypes.byref(pidl), 0, None)
    if hr != 0 or not pidl.value:
        return None
    return pidl


SHGFI_PIDL = 0x000000008
SHGFI_ICON = 0x000000100
SHGFI_SYSICONINDEX = 0x00004000
SHGFI_LARGEICON = 0x000000000


def icon_from_pidl(pidl, flags):
    info = SHFILEINFOW()
    ok = sh32.SHGetFileInfoW(ctypes.c_void_p(pidl.value), 0, ctypes.byref(info),
                             ctypes.sizeof(info), flags)
    if not ok:
        return None
    return info


for label, clsid in (("此电脑", "::{20D04FE0-3AEA-1069-A2D8-08002B30309D}"),
                     ("回收站", "::{645FF040-5081-101B-9F08-00AA002F954E}")):
    pidl = pidl_for(clsid)
    if pidl is None:
        print("  %-6s SHParseDisplayName 失败" % label)
        continue
    info = icon_from_pidl(pidl, SHGFI_PIDL | SHGFI_ICON | SHGFI_LARGEICON)
    big = info.hIcon if info else None
    info2 = icon_from_pidl(pidl, SHGFI_PIDL | SHGFI_SYSICONINDEX)
    idx = info2.iIcon if info2 else None
    print("  %-6s hicon=%s sysindex=%s" % (label, big, idx))

print()
print("========== 4. IImageList jumbo + HICON->QPixmap ==========")

IID_IImageList = "{46EB5926-582E-4017-9F49-EAD8A5D63231}"


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


def make_guid(s):
    import uuid as _uuid
    g = GUID()
    ctypes.memmove(ctypes.byref(g), _uuid.UUID(s).bytes_le, 16)
    return g


shell32_ord = ctypes.WinDLL("shell32")
try:
    get_image_list = shell32_ord[727]  # SHGetImageList
    get_image_list.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    get_image_list.restype = ctypes.c_long
    ilist = ctypes.c_void_p()
    hr = get_image_list(4, ctypes.byref(make_guid(IID_IImageList)), ctypes.byref(ilist))
    print("  SHGetImageList(SHIL_JUMBO=4) hr=0x%08x ilist=%s" % (hr & 0xFFFFFFFF, ilist.value))
except Exception as e:
    print("  SHGetImageList ordinal 727 err:", e)
    ilist = ctypes.c_void_p()

if ilist.value:
    vtbl = ctypes.cast(ilist, ctypes.POINTER(ctypes.c_void_p))[0]
    GetIcon = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_int,
                               ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))
    geticon = GetIcon(vtbl[12])
    hicon = ctypes.c_void_p()
    hr = geticon(ilist, 0, 1, ctypes.byref(hicon))  # ILD_TRANSPARENT=1
    print("  IImageList.GetIcon(0) hr=0x%08x hicon=%s" % (hr & 0xFFFFFFFF, hicon.value))

    # HICON -> QPixmap（DrawIconEx 进 32bpp DIB，直接读内存）
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    def hicon_to_pixmap(h, px):
        hdr = BITMAPINFOHEADER()
        hdr.biSize = ctypes.sizeof(hdr)
        hdr.biWidth = px
        hdr.biHeight = -px
        hdr.biPlanes = 1
        hdr.biBitCount = 32
        hdr.biCompression = 0
        bits = ctypes.c_void_p()
        hdc = g32.CreateCompatibleDC(None)
        bmp = g32.CreateDIBSection(hdc, ctypes.byref(hdr), 0, ctypes.byref(bits), None, 0)
        old = g32.SelectObject(hdc, bmp)
        u32.DrawIconEx(hdc, 0, 0, ctypes.c_void_p(h), px, px, 0, None, 3)  # DI_NORMAL
        raw = bytes((ctypes.c_ubyte * (px * px * 4)).from_address(bits.value))
        g32.SelectObject(hdc, old)
        g32.DeleteObject(bmp)
        g32.DeleteDC(hdc)
        img = QImage(raw, px, px, QImage.Format_ARGB32).copy()
        return QPixmap.fromImage(img)

    if hicon.value:
        pm = hicon_to_pixmap(hicon.value, 256)
        print("  pixmap: %dx%d hasAlpha=%s" % (pm.width(), pm.height(), pm.hasAlpha()))
        # 采样中心与角落像素，验证不是全黑/全透明
        for (x, y) in ((128, 128), (10, 10), (200, 60)):
            print("    px(%d,%d) = %s" % (x, y, pm.toImage().pixel(x, y)))
        pm.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "hicon_probe.png"))
        print("  saved hicon_probe.png")

print()
print("========== 5. DefView 当前可见性 ==========")
progman = u32.FindWindowW("Progman", None)
dv = u32.FindWindowExW(progman, None, "SHELLDLL_DefView", None)
lv = u32.FindWindowExW(dv, None, "SysListView32", None)
print("  progman=%s defview=%s listview=%s" % (progman, dv, lv))
print("  defview visible:", bool(u32.IsWindowVisible(dv)) if dv else None)
print("  listview visible:", bool(u32.IsWindowVisible(lv)) if lv else None)
print("done")
