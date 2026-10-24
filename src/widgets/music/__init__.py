# -*- coding: utf-8 -*-
"""音乐控制器组件（v10 C2，反馈 9）。

结构（对齐 docs/组件开发指南.md 的模块化布局）：
  music.py   layout/marquee_offset/draw + MusicWidget（媒体键 + 定时器）
  draw.py    draw_preview（组件库预览，固定示例数据）
数据源在 `src/media_session.py`（本包只管画与交互）。
span/分类/settings 声明仍在 src/widget_registry.py。

**导入顺序有讲究**：先 `from .draw`（子模块）会把包属性 `draw` 设成**模块**，
所以 `draw` 函数必须放在后面绑才覆盖得掉——调这两行顺序前先想清楚。
"""
from .draw import draw_preview                                    # noqa: F401
from .music import (BAR_H, DIM_ALPHA, MARQUEE_PX_S, MusicWidget,  # noqa: F401
                    TICK_MS, bar_hit_rect, cover_pixmap, draw, layout,
                    marquee_offset)
