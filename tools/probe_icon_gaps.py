# -*- coding: utf-8 -*-
"""只读探针：逐个桌面条目取图标，找出「空图标」的失败模式。

不改布局、不写 state.json，只读枚举 + 取图标。
用法：python tools/probe_icon_gaps.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from src import appsource

app = QApplication(sys.argv)

items = appsource.scan_desktop_files()
print("桌面条目数 =", len(items))
print()

bad = []
for it in items:
    name = it.get("name", "")
    path = it.get("icon_path") or it.get("target") or ""
    icon = appsource._qicon_for(it)
    pm = appsource.icon_pixmap(it, 48, 1.25)
    # 统计非透明像素
    img = pm.toImage().convertToFormat(4)  # ARGB32
    solid = 0
    total = img.width() * img.height()
    for y in range(0, img.height(), 3):
        for x in range(0, img.width(), 3):
            if img.pixelColor(x, y).alpha() > 20:
                solid += 1
    ratio = solid / max(1, (img.height() // 3 + 1) * (img.width() // 3 + 1))
    is_short = appsource.is_shortcut(it)
    tgt = appsource.shortcut_target_path(it) if is_short else None
    flag = "  " if ratio > 0.05 else "!!"
    if ratio <= 0.05:
        bad.append((name, path, is_short, tgt))
    print("%s %-28s ratio=%.3f short=%-5s pm=%dx%d icon_null=%s path=%s%s" % (
        flag, name[:28], ratio, is_short, pm.width(), pm.height(),
        icon.isNull(), os.path.basename(path), (" -> " + tgt) if tgt else ""))

print()
print("疑似空图标:", len(bad))
for b in bad:
    print("   ", b)
