# -*- coding: utf-8 -*-
"""待办清单组件（v10 C1：从 src/widgets_todo.py 原样搬入并拆包，逻辑零改动）。

结构（对齐 docs/组件开发指南.md 的模块化布局）：
  todo.py   组件类 + 数据/几何/绘制三层
  draw.py   draw_preview（组件库预览）+ DEMO_ITEMS 示例数据
span/分类/settings 声明仍在 src/widget_registry.py。

**导入顺序有讲究**：先 `from .draw`（子模块）会把包属性 `draw` 设成**模块**，
所以 `draw` 函数必须放在后面绑才覆盖得掉——调这两行顺序前先想清楚。
"""
from .draw import DEMO_ITEMS, draw_preview                # noqa: F401
from .todo import (MAX_ITEMS, ROW_H, TodoWidget,          # noqa: F401
                   add_item, check_rect, delete_rect, draw, layout,
                   load_items, remove_item, row_rect, serialize,
                   text_color, toggle_item)
