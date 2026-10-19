# -*- coding: utf-8 -*-
"""只读探针：抓「运行中的桌面图标」实际屏幕像素，判断是绘制糊还是截图糊。

流程：起一次完整窗口（attach 桌面带）→ 定位某个图标的全局矩形 →
QScreen.grabWindow 取屏幕像素 → 存 4 倍放大图 → 退出并恢复原生图标。
用法：python tools/probe_icon_sharpness.py [名字关键字]
"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtWidgets import QApplication

from src import appsource, win32_layer
from src.desktop_window import DesktopWindow
from src.storage import Storage
from src.widget_layer import WidgetLayer

KEY = sys.argv[1] if len(sys.argv) > 1 else "微信"

app = QApplication(sys.argv)
storage = Storage()
win = DesktopWindow(storage)
layer = WidgetLayer(storage)
win.set_widget_layer(layer)
win.show_desktop()


def shoot():
    target = None
    for eid, icon in win.icons.items():
        name = (icon.entry.get("app") or {}).get("name") or icon.entry.get("name", "")
        if KEY in str(name):
            target = icon
            break
    if target is None:
        print("没找到图标:", KEY, "共", len(win.icons))
        QTimer.singleShot(100, quit_all)
        return
    rect = target.rect()
    gp = target.mapToGlobal(rect.topLeft())
    screen = QApplication.primaryScreen()
    dpr = max(1.0, screen.devicePixelRatio())
    pm = screen.grabWindow(0, gp.x(), gp.y(), rect.width(), rect.height())
    print("图标逻辑矩形:", gp.x(), gp.y(), rect.width(), rect.height(),
          "dpr=", dpr, "抓取物理尺寸:", pm.width(), pm.height())
    out = QImage(pm.width() * 4, pm.height() * 4, QImage.Format_ARGB32)
    out.fill(QColor(120, 60, 160))
    p = QPainter(out)
    p.drawPixmap(0, 0, pm.width() * 4, pm.height() * 4, pm)
    p.end()
    out.save("dist/icon_live_4x.png")
    print("saved dist/icon_live_4x.png")
    # 同时存一份 1:1 供参考
    pm.save("dist/icon_live_1x.png")
    QTimer.singleShot(100, quit_all)


def quit_all():
    try:
        win.hide_desktop()
    except Exception:
        pass
    win32_layer.restore_native_icons()
    app.quit()


QTimer.singleShot(1800, shoot)
sys.exit(app.exec())
