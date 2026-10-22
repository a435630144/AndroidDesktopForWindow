# -*- coding: utf-8 -*-
"""桌面面板组件（v10 C1：从 src/widgets_panel.py 原样搬入，逻辑零改动）。

结构（对齐 docs/组件开发指南.md 的模块化布局）：
  panel.py  组件类 + 三张卡（DiskCard / WeatherCard / RecentCard）
没有 draw.py——桌面面板**没有 draw_preview**（v9 起组件库对它走兜底卡，
不造一个空文件假装对齐）。span/分类/settings 声明仍在 src/widget_registry.py。
"""
from .panel import (DesktopPanel, DiskCard, RecentCard,   # noqa: F401
                    WeatherCard)
