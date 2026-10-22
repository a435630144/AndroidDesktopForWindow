# -*- coding: utf-8 -*-
"""时钟组件的组件库预览（v10 C1 从 widgets_clock.py 拆出）。

与桌面渲染复用同一个 `draw()`（组件库预览与桌面不同源是 v9 明令禁止的退化）；
预览固定 09:41，避免预览每秒闪一次。
"""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ...widget_glass import paint_glass, PREVIEW_RADIUS
from .clock import ClockModel, draw


def draw_preview(painter: QPainter, rect, dpr: float = 1.0) -> None:
    """组件库缩略图：固定 09:41，避免预览每秒闪一次。"""
    rect = QRectF(rect)
    paint_glass(painter, rect, PREVIEW_RADIUS)
    m = ClockModel(hhmm="09:41", ss="07", date="10月21日", weekday="星期三")
    draw(painter, rect, m)
