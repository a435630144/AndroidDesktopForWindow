# -*- coding: utf-8 -*-
"""生成 Dock 栏展示图（输出 `docs/images/08-dock.png`）。

与 `shot_readme.py` 同一套硬约束：

  * **真实 QPA**（`QT_QPA_PLATFORM` 必须清掉：offscreen 插件缺中文字体，
    DEVLOG 坑 #60），配合 `WA_DontShowOnScreen` 不真上屏；
  * `attach_to_desktop` 换成 noop——出图不能动用户桌面带；
  * Dock 是分层半透明窗，用 `render(..., DrawChildren)` 取像素
    （`grab()` 不含透明底，坑 #95）；
  * 临时 Storage，不碰真实 `state.json`。

一张图讲一件事：**四向位置 + hover 放大**。上半是底部 Dock（hover 第 3 项），
下半并排顶部 / 左侧 / 右侧，用来证明"换向后条带贴边、图标方向正确"。

跑法：python tools/shot_dock.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 必须早于 PySide6 导入：外部若带 offscreen，中文字会渲染成方块
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QPoint, QRectF, Qt            # noqa: E402
from PySide6.QtGui import (QColor, QLinearGradient, QPainter,  # noqa: E402
                           QPixmap)
from PySide6.QtWidgets import QApplication               # noqa: E402

OUT_DIR = ROOT / "docs" / "images"
STATE = Path(tempfile.gettempdir()) / "shot_dock_state.json"

DPR = 2
W, H = 1200, 560          # 画布逻辑尺寸（局部特写，Dock 才看得清）

sys.path.insert(0, str(ROOT / "tools"))
import demo_apps                                         # noqa: E402

# 演示条目：7 个真实应用（图标是 `assets/demo_icons/` 里的导出版，
# 清单见 `tools/demo_apps.py`）。挑形状差异大的——圆/圆角方/异形图标排一排，
# hover 放大和间距才看得出效果；全用系统工具的话七个图标糊成一片蓝。
ITEMS = demo_apps.entries(demo_apps.DOCK)

WALL_TOP = QColor(38, 54, 96)
WALL_BOTTOM = QColor(18, 24, 44)


def wallpaper(p: QPainter, rect):
    g = QLinearGradient(rect.topLeft(), rect.bottomRight())
    g.setColorAt(0.0, WALL_TOP)
    g.setColorAt(1.0, WALL_BOTTOM)
    p.fillRect(rect, g)


def make_dock(storage, items, position, hover=None, width=1200, height=220):
    """建一个真控件，用真实 paintEvent 渲到 **整个画布大小** 的 pixmap。

    关键：窗口 geometry 是条带矩形（屏幕坐标），所以 `render` 的落点必须
    是条带矩形左上角——直接画到 (0,0) 会得到"条带缩在角落"的假图。
    """
    from src import dock
    storage.set_setting("dock_position", position)
    win = dock.DockWindow(storage)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.set_items(items, save=False)
    bar = win.apply_geometry((width, height))
    if hover is not None and items:
        win._hover_index = hover
        win._set_hover_t(1.0)
    pm = QPixmap(width * DPR, height * DPR)
    pm.setDevicePixelRatio(DPR)
    pm.fill(Qt.transparent)
    wp = QPainter(pm)
    wallpaper(wp, QRectF(0, 0, width, height))
    wp.end()
    win.render(pm, QPoint(int(bar[0]), int(bar[1])))
    win.close()
    return pm


def main() -> int:
    app = QApplication.instance() or QApplication([])   # noqa: F841

    # 出图不能动用户桌面带
    from src import dock, win32_layer
    win32_layer.attach_to_desktop = lambda *a, **k: False
    dock.win32_layer.attach_to_desktop = lambda *a, **k: False

    from src.storage import Storage
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=STATE)
    st.set_setting("dock_enabled", True)
    st.set_setting("dock_seeded", True)

    canvas = QPixmap(W * DPR, H * DPR)
    canvas.fill(QColor(14, 16, 22))
    canvas.setDevicePixelRatio(DPR)
    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)

    # ---------- 上半：底部 Dock + hover ----------
    top = QRectF(16, 14, W - 32, 210)
    p.save()
    p.setClipRect(top)
    wallpaper(p, top)
    p.restore()
    pm = make_dock(st, ITEMS, "bottom", hover=2, width=int(top.width()),
                   height=int(top.height()))
    p.drawPixmap(int(top.x()), int(top.y()), pm)

    # ---------- 下半：顶部 / 左侧 / 右侧 ----------
    from src import theme
    # 三个方向各放 5 个：`dock.MIN_SLOTS` 就是 5，条目少于 5 时条带仍按 5 槽
    # 撑长——塞 3 个进去会看到"条带比图标长一截"的空槽，且竖向条带
    # (5×40 + 间隙 + 内边距 ≈ 240) 装不进 150 高的盒子，直接被画布切掉。
    labels = (("top", "顶部"), ("left", "左侧"), ("right", "右侧"))
    box_w, box_h = (W - 32 - 24) / 3.0, 262
    for i, (pos, label) in enumerate(labels):
        x = 16 + i * (box_w + 12)
        y = 282
        rect = QRectF(x, y, box_w, box_h)
        p.save()
        p.setClipRect(rect)
        wallpaper(p, rect)
        p.restore()
        small = make_dock(st, ITEMS[:5], pos, hover=None,
                          width=int(box_w), height=int(box_h))
        p.drawPixmap(int(x), int(y), small)
        p.setPen(theme.TEXT_DIM)
        p.setFont(theme.ui_font(12))
        p.drawText(QRectF(x, y - 20, box_w, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   "Dock 位置：" + label)

    p.end()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "08-dock.png"
    canvas.save(str(out), "PNG")
    print("saved", out, canvas.width(), "x", canvas.height())
    return 0


if __name__ == "__main__":
    sys.exit(main())
