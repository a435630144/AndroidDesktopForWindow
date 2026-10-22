# -*- coding: utf-8 -*-
"""系统监控组件的组件库预览（v10 C1 从 widget_monitor.py 拆出）。

与桌面渲染复用同一个 `draw()`；预览用固定示例数据（不采样、不联网、
不跑定时器）。
"""
from PySide6.QtGui import QPainter

from .monitor import Snapshot, draw


def draw_preview(p: QPainter, rect, dpr: float = 1.0) -> None:
    """组件库预览：固定示例数据（不采样、不联网、不跑定时器）。"""
    demo = Snapshot(cpu=42.0, mem=63.0, disk=55.0)
    draw(p, rect, demo)
