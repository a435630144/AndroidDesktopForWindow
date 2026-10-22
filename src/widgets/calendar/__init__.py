# -*- coding: utf-8 -*-
"""日历组件（v10 C1：从 src/widgets_calendar.py 原样搬入并拆包，逻辑零改动）。

结构（对齐 docs/组件开发指南.md 的模块化布局）：
  calendar.py  month_matrix/shift_month/week_labels/build_model/layout/draw
               + 组件类（翻月写 cal_year/cal_month）
  draw.py      draw_preview（组件库预览，取当天）
span/分类/settings 声明仍在 src/widget_registry.py。

**导入顺序有讲究**：先 `from .draw`（子模块）会把包属性 `draw` 设成**模块**，
所以 `draw` 函数必须放在后面绑才覆盖得掉——调这两行顺序前先想清楚。
"""
from .draw import draw_preview                                    # noqa: F401
from .calendar import (CELL_FS_RATIO, CalendarModel,              # noqa: F401
                       CalendarWidget, TODAY_R, WEEKDAY_LABELS,
                       build_model, draw, layout, month_matrix,
                       shift_month, week_labels)
