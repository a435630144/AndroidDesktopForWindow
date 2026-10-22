# -*- coding: utf-8 -*-
"""日历组件的组件库预览（v10 C1 从 widgets_calendar.py 拆出）。

与桌面渲染复用同一个 `draw()`；预览取当天日期。
"""
import datetime

from PySide6.QtGui import QPainter

from .calendar import build_model, draw


def draw_preview(p: QPainter, rect, dpr: float = 1.0) -> None:
    now = datetime.date.today()
    draw(p, rect, build_model(now.year, now.month, 0, today=now))
