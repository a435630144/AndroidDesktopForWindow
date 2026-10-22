# -*- coding: utf-8 -*-
"""待办组件的组件库预览（v10 C1 从 widgets_todo.py 拆出）。

与桌面渲染复用同一个 `draw()`；预览用示例数据，不读存储、不触发落盘。
"""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ...widget_glass import paint_glass, PREVIEW_RADIUS
from .todo import draw

DEMO_ITEMS = [
    {"id": "d1", "text": "写周报", "done": False},
    {"id": "d2", "text": "交房租", "done": True},
    {"id": "d3", "text": "买牛奶", "done": False},
]


def draw_preview(painter: QPainter, rect, dpr: float = 1.0) -> None:
    """组件库缩略图：固定三条示例待办。"""
    rect = QRectF(rect)
    paint_glass(painter, rect, PREVIEW_RADIUS)
    draw(painter, rect, DEMO_ITEMS)
