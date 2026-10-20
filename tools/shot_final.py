# -*- coding: utf-8 -*-
"""效果图拍摄：启动完整应用 -> 临时显示时钟/面板（不改动用户偏好）-> 最小化其他窗口
-> 截图 -> 还原。产出 dist/shots/ 下的效果图。
用法：python tools/shot_final.py
"""
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from src import win32_layer
from src.desktop_window import DesktopWindow
from src.storage import Storage
from src.widget_layer import WidgetLayer

u = ctypes.windll.user32
u.GetWindow.restype = wintypes.HWND
u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
u.GetClassNameW.restype = ctypes.c_int
u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u.GetWindowRect.restype = wintypes.BOOL
u.IsWindowVisible.restype = wintypes.BOOL
u.IsWindowVisible.argtypes = [wintypes.HWND]
u.IsIconic.restype = wintypes.BOOL
u.IsIconic.argtypes = [wintypes.HWND]
u.ShowWindow.restype = wintypes.BOOL
u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]

GW_CHILD, GW_HWNDNEXT = 5, 2
SW_MINIMIZE, SW_RESTORE = 6, 9
KEEP_CLASSES = {"Progman", "WorkerW", "SHELLDLL_DefView", "Shell_TrayWnd",
                "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow"}
SHOT_DIR = str(ROOT / "dist" / "shots")

app = QApplication(sys.argv)
storage = Storage()
storage.ensure_desktop_clone()
window = DesktopWindow(storage)
window.show_desktop()
layer = WidgetLayer(storage)


def cls(h):
    b = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(h, b, 256)
    return b.value


def our_hwnds():
    out = {int(window.winId())}
    for w in layer.widgets.values():
        out.add(int(w.winId()))
    if window._popup is not None:
        out.add(int(window._popup.winId()))
    return out


def _close_all_widgets():
    for wid, w in list(layer.widgets.items()):
        layer._band_guard.untrack(w)
        w.close()
        layer.widgets.pop(wid, None)


def prepare_widgets():
    """临时显示时钟 / 面板（用新版默认尺寸与落位），返回原始 widgets 列表。"""
    original = [dict(w) for w in storage.widgets]
    _close_all_widgets()
    for w in storage.widgets:
        if w.get("type") in ("clock", "panel"):
            w["hidden"] = False
            w.pop("x", None)
            w.pop("y", None)
            if w.get("type") == "clock":
                w["w"], w["h"] = 300, 160
            else:
                w["w"], w["h"] = 400, 620
    for entry in storage.widgets:
        layer._place_default(entry)
        layer._spawn(entry)
    return original


def restore_widgets(original):
    _close_all_widgets()
    storage._data["widgets"] = original
    storage.save()


def minimize_others():
    """【安全禁令·2026-10-17】绝不移动/最小化/关闭用户的任何窗口。
    事故：探针为"清理测试环境"把用户窗口移到屏幕外，进程被 SIGTERM 时
    还原代码没跑，导致用户 Edge/Chrome/微信等全部滞留屏幕外无法使用。
    测试点被占用时用实时选点（参考 probe9.driver_band）或跳过场景，
    永远不要动用户的窗口。"""
    return []


def restore_all(hwnds):
    for h in hwnds:
        u.ShowWindow(h, SW_RESTORE)


def shoot(name):
    from PIL import ImageGrab
    path = "%s/%s.png" % (SHOT_DIR, name)
    ImageGrab.grab().save(path)
    print("[shot]", path, flush=True)


original_widgets = prepare_widgets()


def phase_shoot1():
    mins = minimize_others()
    QTimer.singleShot(1200, lambda: _after_min(mins))


def _after_min(mins):
    shoot("桌面带效果_深色版")
    # 打开一个文件夹弹窗再拍一张；没有文件夹就临时合并前两个条目，拍完解散
    folder = next((e for e in storage.layout if e.get("type") == "folder"), None)
    temp_folder = False
    if folder is None:
        apps = [e for e in storage.layout if e.get("type") == "app"]
        if len(apps) >= 2:
            window._on_merge(apps[1]["id"], apps[0]["id"])
            folder = next((e for e in storage.layout if e.get("type") == "folder"), None)
            temp_folder = True
    if folder is not None:
        window.open_folder(folder["id"])
        QTimer.singleShot(700, lambda: _shoot_popup(mins, temp_folder))
    else:
        _shoot_popup(mins, False)


def _shoot_popup(mins, temp_folder):
    shoot("文件夹弹窗")
    QTimer.singleShot(400, lambda: _done(mins, temp_folder))


def _done(mins, temp_folder):
    if window._popup is not None:
        window._popup.close()
    if temp_folder:
        folder = next((e for e in storage.layout if e.get("type") == "folder"), None)
        if folder is not None:
            window._on_dissolve(folder["id"])
    restore_all(mins)
    restore_widgets(original_widgets)
    print("[done] windows restored:", len(mins), flush=True)
    win32_layer.restore_native_icons()
    app.quit()


QTimer.singleShot(2500, phase_shoot1)
app.exec()
sys.exit(0)
