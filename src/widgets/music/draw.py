# -*- coding: utf-8 -*-
"""音乐控制器的组件库预览（v10 C2）。

与桌面渲染复用同一个 `draw()`；预览用固定示例数据（不碰媒体键、不跑定时器、
不选数据源）——组件库里点卡片不该给用户放歌。
"""
from PySide6.QtGui import QPainter

from ...media_session import MediaInfo
from .music import draw

PREVIEW_INFO = MediaInfo(title="演示曲目 · 一", artist="打开播放器后显示在这里",
                         playing=True, position=64.0, duration=210.0, demo=True)


def draw_preview(p: QPainter, rect, dpr: float = 1.0) -> None:
    """组件库预览：固定示例数据。"""
    draw(p, rect, PREVIEW_INFO)
