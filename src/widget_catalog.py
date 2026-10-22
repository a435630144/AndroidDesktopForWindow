# -*- coding: utf-8 -*-
"""组件跨度查询——**薄壳**（v8 C1 起）。

背景（反馈 P3「时钟碰撞形状不对」）：v5 以前按像素尺寸 / 单元格尺寸 round
换算跨度，撞上 round() 银行家舍入——clock 300×160 @ 120×142 得 (2,1)：
碰撞边界（2 列）与视觉边界（接近 2.5 列）不一致，图标按 2 列避让、时钟
自己按 1 行排内容，视觉上半行溢出。

v5 M3 起跨度是声明式配置，但配置本身放在本模块的 `WIDGET_CATALOG` 字典里，
与 `WIDGET_TYPES` / `WIDGET_NAMES` / `_place_default` 分散成四处（加一个
组件要改四个文件）。v8 C1 起**单一真相源搬到 `widget_registry`**：

    spans() / default_span()  →  registry.spans() / registry.default_span()

本模块只保留函数签名（`grid_flow` / `widget_base` 共 6 处调用点一行不改），
以及 `pixel_size()` 这个"跨度 × 格子大小"的换算。**不要再往这里加组件**，
新增组件请去 `src/widget_registry.py` 的 `REGISTRY` 追加一条 `WidgetSpec`。

依赖方向：本模块被 grid_flow.widget_span 引用；需要 cell_size 时函数内
延迟 `from . import grid_flow`，避免循环导入。
"""
from __future__ import annotations

from typing import List, Optional, Tuple

Span = Tuple[int, int]


def _reg():
    """延迟导入注册表：widget_registry → widgets_* → widget_base → grid_flow，
    而 grid_flow 在模块级不引用本模块（只有函数内引用），因此这里安全。"""
    from . import widget_registry
    return widget_registry


def spans(wtype: str) -> List[Span]:
    """该组件类型登记的可用跨度列表；未登记返回 []（调用方回退 legacy）。"""
    return _reg().spans(wtype)


def default_span(wtype: str) -> Optional[Span]:
    """该组件类型的默认跨度（列表第一项）；未登记返回 None。"""
    return _reg().default_span(wtype)


def pixel_size(storage, wtype: str, span: Optional[Span] = None) -> Optional[Span]:
    """span 对应的**卡片**像素尺寸（v10 A8：格盒 × 填充比例，精确推导）。

    span 缺省用 default_span；未登记类型返回 None。
    注意这不是"占位尺寸"——占位/碰撞永远按整格（`widget_geom.span_box`）。
    """
    if span is None:
        span = default_span(wtype)
    if span is None:
        return None
    from . import widget_geom  # 延迟导入，打破 grid_flow <-> widget_catalog 循环
    return widget_geom.card_size(storage, span)
