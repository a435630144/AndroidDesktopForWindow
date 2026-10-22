# -*- coding: utf-8 -*-
"""天气组件（v10 C1：从 src/widgets_weather.py + src/weather_api.py 搬入并拆包）。

结构（对齐 docs/组件开发指南.md 的模块化布局）：
  weather.py      layout/draw_weather_icon/draw + WeatherWidget
  weather_api.py  Open-Meteo 免 key 客户端（三级降级 live/cached/empty；
                  网络出口只有 _http_json() 一处，测试 monkeypatch 即脱网）
  draw.py         draw_preview（组件库预览，示例数据不联网）
span/分类/settings 声明仍在 src/widget_registry.py。

**注意**：`weather_api` 同时是**插件 SDK 的公开子模块**（插件
`from deskorg import weather_api`）——SDK 别名路径见 widget_plugin.SDK_PATHS。

**导入顺序有讲究**：先 `from .draw`（子模块）会把包属性 `draw` 设成**模块**，
所以 `draw` 函数必须放在后面绑才覆盖得掉——调这两行顺序前先想清楚。
"""
from . import weather_api as wa                                 # noqa: F401
from .draw import draw_preview                                  # noqa: F401
from .weather import (DAY_LABELS, WIDE_RATIO, WeatherWidget,    # noqa: F401
                      draw, draw_weather_icon, layout)
