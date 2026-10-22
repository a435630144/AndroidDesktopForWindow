# -*- coding: utf-8 -*-
"""系统监控组件（v10 C1：从 src/widget_monitor.py 原样搬入并拆包，逻辑零改动）。

结构（对齐 docs/组件开发指南.md 的模块化布局）：
  monitor.py  ctypes 采样（CPU/内存/磁盘）+ Snapshot/layout/draw + 组件类
  draw.py    draw_preview（组件库预览，固定示例数据）
span/分类/settings 声明仍在 src/widget_registry.py。
"""
from .draw import draw_preview                                    # noqa: F401
from .monitor import (ANIM_MS, DANGER_AT, MonitorWidget,          # noqa: F401
                      RING_KEYS, RING_LABELS, RING_STROKE_RATIO,
                      Snapshot, WARN_AT, WIDE_RATIO, draw, layout,
                      progress_color, sample, sample_cpu,
                      sample_disk, sample_memory)
