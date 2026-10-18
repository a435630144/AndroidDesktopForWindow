# -*- coding: utf-8 -*-
"""组件跨度目录（WIDGET_CATALOG）——小组件尺寸的网格一等公民（M3，指导文档 §3.2）。

背景（反馈 P3「时钟碰撞形状不对」）：旧实现按像素尺寸 / 单元格尺寸 round
换算跨度，撞上 round() 银行家舍入——clock 300×160 @ 120×142 得 (2,1)：
碰撞边界（2 列）与视觉边界（接近 2.5 列）不一致，图标按 2 列避让、时钟
自己按 1 行排内容，视觉上半行溢出。

M3 起跨度是声明式配置：每种组件类型在 catalog 里登记「可用尺寸列表」，
第一项为默认。像素尺寸由 span × cell_size 精确推导（pixel_size），
碰撞 = 视觉边界，不再有任何 round。

依赖方向：本模块被 grid_flow.widget_span 引用；需要 cell_size 时函数内
延迟 `from . import grid_flow`，避免循环导入。
"""
from __future__ import annotations

from typing import List, Optional, Tuple

Span = Tuple[int, int]

# 每种组件类型的可用跨度列表（列, 行），第一项 = 默认。
# 2026-10-18 D3 决策：clock 默认 2×2（时间行 + 日期行刚好铺满，
# 字号可随 cell 缩放）；后续 notes/panel 等接入时在此登记。
# 2026-10-19 v6 §6.1（反馈 7b 前半）：notes 2×2、panel 3×4 登记入网格——
# 锚定时位置 = cell_pos、尺寸 = span × cell（pixel_size 精确推导），
# 碰撞边界 = 视觉边界；悬浮态仍用 entry 的像素 w/h（可交互组件要键盘
# 焦点，见 storage.DEFAULT_WIDGETS 注释）。
WIDGET_CATALOG = {
    "clock": [(2, 2)],
    "notes": [(2, 2)],
    "panel": [(3, 4)],
}


def spans(wtype: str) -> List[Span]:
    """该组件类型登记的可用跨度列表；未登记返回 []（调用方回退 legacy）。"""
    return [tuple(s) for s in WIDGET_CATALOG.get(wtype, [])]


def default_span(wtype: str) -> Optional[Span]:
    """该组件类型的默认跨度（列表第一项）；未登记返回 None。"""
    lst = spans(wtype)
    return lst[0] if lst else None


def pixel_size(storage, wtype: str, span: Optional[Span] = None) -> Optional[Span]:
    """span 对应的像素尺寸 = span × cell_size（精确推导，无 round）。

    span 缺省用 default_span；未登记类型返回 None。
    """
    if span is None:
        span = default_span(wtype)
    if span is None:
        return None
    from . import grid_flow  # 延迟导入，打破 grid_flow <-> widget_catalog 循环
    cw, ch = grid_flow.cell_size(storage)
    return int(span[0]) * cw, int(span[1]) * ch
