# -*- coding: utf-8 -*-
"""一次性全屏截图（只读，不碰桌面层）。用法：python tools/shot_once.py 输出路径"""
import sys

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
out = sys.argv[1] if len(sys.argv) > 1 else "dist/shot_once.png"
screen = QApplication.primaryScreen()
pm = screen.grabWindow(0, 0, 0, screen.geometry().width(), screen.geometry().height())
ok = pm.save(out, "PNG")
print("saved", out, pm.width(), "x", pm.height(), "ok=", ok)
