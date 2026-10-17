# -*- coding: utf-8 -*-
"""应用来源：内置系统入口 + 开始菜单扫描 + 桌面文件克隆。

桌面文件克隆（df: 前缀 id）：
  原生桌面图标被隐藏后，由本模块枚举 用户桌面 + 公共桌面 的全部条目，
  生成带稳定 id（路径哈希）的克隆条目，第三方桌面完全掌控其摆放与样式。
  条目不删除文件：移除克隆仅影响布局，文件始终留在桌面文件夹中。
"""
import ctypes
import hashlib
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from PySide6.QtCore import QFileInfo, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QFileIconProvider

# Shell 已知目录 GUID（SHGetKnownFolderPath，正确处理 OneDrive 重定向 / 本地化）
_KNOWN_FOLDER_GUIDS = {
    "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "public_desktop": "{C4AA340D-F20F-4863-AFEF-F87EF2E6BA25}",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
}


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]


def shell_known_folder(name: str) -> str:
    """通过 Shell API 取系统已知目录；失败返回空串。"""
    guid_str = _KNOWN_FOLDER_GUIDS.get(name)
    if not guid_str:
        return ""
    try:
        guid = _GUID()
        # uuid.bytes_le 与 Windows GUID 内存布局一致（Data1/2/3 小端 + Data4 原样）
        ctypes.memmove(ctypes.byref(guid), uuid.UUID(guid_str).bytes_le, 16)
        path_ptr = ctypes.c_wchar_p()
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(path_ptr))
        if hr == 0 and path_ptr.value:
            return path_ptr.value
    except Exception:
        pass
    return ""

# 内置系统入口：target 为可启动字符串（命令 / 协议 / shell CLSID）
BUILTIN_APPS = [
    {"id": "sys-pc",       "name": "此电脑",     "target": "::{20D04FE0-3AEA-1069-A2D8-08002B30309D}", "builtin": True},
    {"id": "sys-recycle",  "name": "回收站",     "target": "::{645FF040-5081-101B-9F08-00AA002F954E}", "builtin": True},
    {"id": "sys-explorer", "name": "资源管理器", "target": "explorer", "icon_path": "%SystemRoot%\\explorer.exe", "builtin": True},
    {"id": "sys-control",  "name": "控制面板",   "target": "control", "icon_path": "%SystemRoot%\\System32\\control.exe", "builtin": True},
    {"id": "sys-settings", "name": "Windows 设置", "target": "ms-settings:", "icon_path": "%SystemRoot%\\ImmersiveControlPanel\\SystemSettings.exe", "builtin": True},
    {"id": "sys-notepad",  "name": "记事本",     "target": "notepad", "icon_path": "%SystemRoot%\\System32\\notepad.exe", "builtin": True},
    {"id": "sys-calc",     "name": "计算器",     "target": "calc", "icon_path": "%SystemRoot%\\System32\\calc.exe", "builtin": True},
    {"id": "sys-mspaint",  "name": "画图",       "target": "mspaint", "icon_path": "%SystemRoot%\\System32\\mspaint.exe", "builtin": True},
    {"id": "sys-cmd",      "name": "命令提示符", "target": "cmd", "icon_path": "%SystemRoot%\\System32\\cmd.exe", "builtin": True},
    {"id": "sys-edge",     "name": "Edge 浏览器", "target": "microsoft-edge:", "icon_path": "%ProgramFiles(x86)%\\Microsoft\\Edge\\Application\\msedge.exe", "builtin": True},
]

_SKIP_KEYWORDS = ("卸载", "uninstall", "帮助", "help", "readme", "说明文档")


def _expand(p: str) -> str:
    return os.path.expandvars(p) if "%" in p else p


def _desktop_folders() -> list:
    """用户桌面 + 公共桌面目录（Shell API 优先，中英文目录名兜底）。"""
    dirs = []
    for name in ("desktop", "public_desktop"):
        p = shell_known_folder(name)
        if p:
            dirs.append(Path(p))
    home = Path.home()
    pub = os.environ.get("PUBLIC", r"C:\Users\Public")
    for d in (home / "Desktop", home / "桌面", Path(pub) / "Desktop"):
        if d.exists():
            dirs.append(d)
    out, seen = [], set()
    for d in dirs:  # 去重（Shell API 与兜底可能指向同一目录）
        k = str(d).lower()
        if k not in seen:
            seen.add(k)
            out.append(d)
    return out


def _file_id(path: str) -> str:
    """桌面文件稳定 id：路径小写哈希（同一文件永远同一 id，重扫不重复）。"""
    return "df:" + hashlib.md5(path.lower().encode("utf-8")).hexdigest()[:12]


def desktop_file_entry(path) -> dict:
    """把桌面文件 / 文件夹 / 快捷方式转换成布局条目用的 app 字典。"""
    p = str(path)
    name = Path(p).stem or Path(p).name
    return {"id": _file_id(p), "name": name, "target": p, "icon_path": p, "kind": "file"}


def scan_desktop_files() -> list:
    """枚举桌面 + 公共桌面全部条目：文件夹优先，其余按名称排序。"""
    out, seen = [], set()
    for root in _desktop_folders():
        try:
            items = list(root.iterdir())
        except Exception:
            continue
        items.sort(key=lambda x: (not x.is_dir(), x.name.lower()))
        for it in items:
            if it.name.startswith("$") or it.name.lower() == "desktop.ini":
                continue
            key = str(it).lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(desktop_file_entry(it))
    return out


def on_desktop(path: str) -> bool:
    """路径是否已经位于某个桌面目录下。"""
    p = Path(path).resolve() if os.path.exists(path) else Path(path)
    return any(_is_under(p, d) for d in _desktop_folders())


def _is_under(p: Path, folder: Path) -> bool:
    try:
        p.resolve().relative_to(folder.resolve())
        return True
    except Exception:
        return False


def move_to_desktop(path: str) -> str:
    """把任意文件移入用户桌面（重名自动加序号），返回新路径。"""
    dest_dir = _desktop_folders()[0] if _desktop_folders() else Path.home() / "Desktop"
    src = Path(path)
    dest = dest_dir / src.name
    n = 2
    while dest.exists():
        dest = dest_dir / "%s (%d)%s" % (src.stem, n, src.suffix)
        n += 1
    shutil.move(str(src), str(dest))
    return str(dest)


def reveal_in_explorer(path: str):
    """在资源管理器中定位文件（选中状态）。"""
    try:
        subprocess.Popen(["explorer", '/select,"%s"' % path])
    except Exception:
        try:
            os.startfile(path)
        except Exception:
            pass


def _start_menu_dirs():
    dirs = []
    appdata = os.environ.get("APPDATA", "")
    programdata = os.environ.get("PROGRAMDATA", "")
    if appdata:
        dirs.append(Path(appdata) / "Microsoft/Windows/Start Menu/Programs")
    if programdata:
        dirs.append(Path(programdata) / "Microsoft/Windows/Start Menu/Programs")
    return [d for d in dirs if d.exists()]


def _desktop_dirs():
    home = Path.home()
    pub = os.environ.get("PUBLIC", r"C:\Users\Public")
    return [d for d in (home / "Desktop", home / "桌面", Path(pub) / "Desktop") if d.exists()]


def scan_installed_apps(limit: int = 300) -> list:
    """扫描开始菜单快捷方式 + 桌面文件，返回应用字典列表。"""
    apps, seen = [], set()
    for root in _start_menu_dirs():
        for lnk in sorted(root.rglob("*.lnk")):
            if len(apps) >= limit:
                break
            name = lnk.stem
            low = name.lower()
            if any(k in low for k in _SKIP_KEYWORDS):
                continue
            if name in seen:
                continue
            seen.add(name)
            apps.append({"id": "sm:" + str(lnk), "name": name,
                         "target": str(lnk), "icon_path": str(lnk)})
    for root in _desktop_dirs():
        try:
            files = sorted(root.iterdir())
        except Exception:
            continue
        for f in files:
            if f.suffix.lower() not in (".lnk", ".exe", ".url", ".bat"):
                continue
            if f.stem in seen:
                continue
            seen.add(f.stem)
            apps.append({"id": "dt:" + str(f), "name": f.stem,
                         "target": str(f), "icon_path": str(f)})
    return apps


def all_apps() -> list:
    """内置 + 扫描的全部应用（添加应用对话框用）。"""
    return [dict(a) for a in BUILTIN_APPS] + scan_installed_apps()


def launch(app: dict):
    """启动应用 / 系统入口（命令、协议、CLSID、.lnk 均可由 ShellExecute 处理）。"""
    target = app.get("target", "")
    if not target:
        return
    try:
        os.startfile(target)
    except Exception:
        pass


_ICON_PROVIDER = QFileIconProvider()
_ICON_CACHE = {}
_PIXMAP_CACHE = {}


def _qicon_for(app: dict) -> QIcon:
    """取应用图标 QIcon：shell 路径（含 CLSID）直接交给 QFileIconProvider，
    失败才生成字母占位图标。"""
    path = _expand(app.get("icon_path") or app.get("target", ""))
    if not path:
        return QIcon()
    key = (path,)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    icon = QIcon()
    try:
        # 不检查 exists()：QFileIconProvider 能解析 ::{GUID} 等 shell 命名空间路径，
        # 此电脑 / 回收站 的真实图标就是这样拿到的（exists() 会把它们误判为字母占位）
        icon = _ICON_PROVIDER.icon(QFileInfo(path))
    except Exception:
        icon = QIcon()
    _ICON_CACHE[key] = icon
    return icon


def icon_for(app: dict, size: int = 48) -> QIcon:
    """取应用图标（QIcon）。优先系统图标，失败时字母占位。"""
    icon = _qicon_for(app)
    if not icon.isNull():
        return icon
    letter = QIcon(_letter_pixmap(app.get("name", "?")[:1], size))
    return letter


def icon_pixmap(app: dict, logical_size: int, dpr: float = 1.0) -> QPixmap:
    """高清图标 pixmap：逻辑尺寸 = logical_size，物理像素 = logical_size * dpr。

    QIcon.pixmap(size) 在 Windows 上对大图标源会返回带 devicePixelRatio 的
    jumbo（256）pixmap，若调用方按物理宽度计算布局就会错位——这里统一归一化：
    取最大可用源 -> 缩放到目标物理像素 -> 设置 DPR，绘制时按逻辑尺寸居中即 crisp。
    """
    key = (app.get("icon_path") or app.get("target", ""), app.get("name", ""),
           logical_size, round(dpr, 2))
    if key in _PIXMAP_CACHE:
        return _PIXMAP_CACHE[key]
    dpr = max(dpr, 1.0)
    target_px = max(16, int(round(logical_size * dpr)))
    icon = _qicon_for(app)
    pm = QPixmap()
    if not icon.isNull():
        sizes = icon.availableSizes()
        if sizes:
            best = max(sizes, key=lambda s: s.width())  # 通常是 256/320（jumbo）
            src = icon.pixmap(best)
        else:
            src = icon.pixmap(QSize(target_px, target_px))
        if not src.isNull():
            if src.width() != target_px:
                src = src.scaled(target_px, target_px,
                                 Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pm = QPixmap(src)
            pm.setDevicePixelRatio(dpr)
    if pm.isNull():
        pm = _letter_pixmap(app.get("name", "?")[:1], target_px)
        pm.setDevicePixelRatio(dpr)
    _PIXMAP_CACHE[key] = pm
    return pm


def _letter_pixmap(ch: str, size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    hue = (sum(ord(c) for c in ch) * 47) % 360
    p.setBrush(QBrush(QColor.fromHsv(hue, 150, 205)))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(pm.rect(), size // 5, size // 5)
    p.setPen(QColor(255, 255, 255))
    font = QFont()
    font.setPixelSize(int(size * 0.5))
    font.setBold(True)
    p.setFont(font)
    p.drawText(pm.rect(), Qt.AlignCenter, ch)
    p.end()
    return pm
