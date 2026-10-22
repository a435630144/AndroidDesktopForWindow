# -*- coding: utf-8 -*-
"""时钟组件（v10 C1：从 src/widgets_clock.py 原样搬入并拆包，逻辑零改动）。

结构（对齐 docs/组件开发指南.md 的模块化布局）：
  clock.py  组件类 + model/layout/draw
  draw.py   draw_preview（组件库预览）
span/分类/settings 声明仍在 src/widget_registry.py。

**导入顺序有讲究**：先 `from .draw`（子模块）会把包属性 `draw` 设成**模块**，
所以 `draw` 函数必须放在后面绑才覆盖得掉——调这两行顺序前先想清楚。
"""
from .draw import draw_preview                               # noqa: F401
from .clock import (ClockModel, ClockWidget, draw, layout,   # noqa: F401
                    model_now)
