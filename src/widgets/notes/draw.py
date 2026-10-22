# -*- coding: utf-8 -*-
"""便签组件的组件库预览（v10 C1 从 widgets_notes.py 拆出）。

与桌面渲染复用同一个 `draw()`；预览用示例文字。
"""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ...widget_glass import paint_glass, PREVIEW_RADIUS
from .notes import draw


def draw_preview(painter: QPainter, rect, dpr: float = 1.0) -> None:
    """组件库缩略图：玻璃底 + 示例文字。"""
    r = QRectF(rect)
    paint_glass(painter, r, PREVIEW_RADIUS)
    draw(painter, r, "18:30 和小林吃饭\n\n· 带伞\n· 买牛奶")
