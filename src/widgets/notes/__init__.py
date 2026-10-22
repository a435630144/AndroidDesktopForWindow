# -*- coding: utf-8 -*-
"""便签组件（v10 C1：从 src/widgets_notes.py 原样搬入并拆包，逻辑零改动）。

结构（对齐 docs/组件开发指南.md 的模块化布局）：
  notes.py  组件类 + text_rect/draw
  draw.py   draw_preview（组件库预览）
span/分类/settings 声明仍在 src/widget_registry.py。
"""
from .notes import HEAD_H, MAX_LEN, NotesWidget, draw, text_rect   # noqa: F401
from .draw import draw_preview                                     # noqa: F401
