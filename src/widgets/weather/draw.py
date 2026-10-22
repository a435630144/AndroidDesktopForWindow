# -*- coding: utf-8 -*-
"""天气组件的组件库预览（v10 C1 从 widgets_weather.py 拆出）。

与桌面渲染复用同一个 `draw()`；预览用示例数据（不联网、不读缓存）。
"""
import datetime

from PySide6.QtGui import QPainter

from . import weather_api as wa
from .weather import draw


def draw_preview(p: QPainter, rect, dpr: float = 1.0) -> None:
    """组件库预览：示例数据（不联网、不读缓存）。"""
    today = datetime.date.today()
    demo = wa.WeatherModel(
        city="北京", temp=23.0, feels=22.0, humidity=55, wind=8.0, code=1,
        daily=(wa.Daily(code=61, tmax=22.0, tmin=14.0),
               wa.Daily(code=3, tmax=24.0, tmin=13.0),
               wa.Daily(code=0, tmax=27.0, tmin=16.0)),
        fetched_at=0.0)
    draw(p, rect, demo, "live")
