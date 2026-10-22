# -*- coding: utf-8 -*-
"""组件几何（v10 A8，反馈 21 / 22）：卡片、窗口、格盒三者的唯一换算层。

## 为什么需要这一层

v10 之前组件的像素尺寸**恒等于** `跨度 × 格子`（`widget_catalog.pixel_size`
与 `FloatingWidget._anchored_pixel_size` 各算一份，但数值相同）。这带来两
个用户可见的后果（2026-10-23 反馈 7 / 8）：

1. **两个组件并排时边缘贴死**——填满整格 = 相邻卡片之间零间隙，视觉上像
   一整块而不是两张卡；
2. **编辑手柄被窗口边界裁掉**——手柄圆心必须贴在卡片边缘上，而卡片边缘
   就是窗口边界，圆心有一半落在窗外，只能画成"半块碎点"。

## 三个矩形（别再各自算一遍）

    span 盒   = 跨度 × cell（**碰撞/占位的唯一形状**，网格用）
    卡片      = 盒 居中缩小到 `fill` 比例（**视觉边界**，玻璃画在这个矩形）
    窗口      = 卡片（静止态）/ 卡片外扩 `pad`（编辑态，给手柄留半个圆）

`fill` 是**全局设置**（`widget_fill`，默认 0.90）：所有组件同一套呼吸感。
之所以不做成每个组件一个值——间距是组件之间的关系，不是单个组件的属性；
两个组件各自 90% / 100% 时看上去仍然是"一个贴死一个留缝"，问题没解决。

`pad` 只出现在编辑态：静止态的窗口严格等于卡片，相邻组件窗口**永不重叠**
（重叠的透明外扩区会抢走邻居边缘的点击，那是另一种"盲区"）。

依赖方向：本模块 → grid_flow（函数内延迟导入，打破循环）。
`widget_base` / `widget_layer` / `grid_flow` 都从这里取数，不许各自推导。
"""
from __future__ import annotations

from typing import Optional, Tuple

# 填充比例（卡片占 span 盒的比例）。下限 0.6 再低就装不下内容；
# 上限 1.0 保留"填满"这个显式选择（老用户习惯 / 大屏）。
MIN_FILL = 0.60
MAX_FILL = 1.00
DEFAULT_FILL = 0.90

# 编辑控制点直径基准（逻辑像素）。v7 B5 定稿 10（iOS/安卓编辑框手柄
# 在 10~12），本机 125% 下逻辑 13。**搬到这里**是为了让"点径 / 外扩 /
# 虚线位置"由同一份数据推导——旧实现三处各自 +1 / +2，必然对不齐。
HANDLE_D_REF = 10

# 命中区最小边长（HIG 建议 22；桌面可放宽到 18 但仍然比可见圆大）
HANDLE_HIT_MIN = 20


def _scale(storage) -> float:
    try:
        s = float(storage.ui_scale())
    except (TypeError, ValueError, AttributeError):
        return 1.0
    return min(3.0, max(0.5, s))


def handle_size(storage) -> int:
    """控制点直径（逻辑像素，随用户缩放；dpr 由 Qt 承担一次）。"""
    return max(9, int(round(HANDLE_D_REF * _scale(storage))))


def handle_hit(storage) -> int:
    """控制点命中区边长：画得小、点得中。"""
    return max(HANDLE_HIT_MIN, handle_size(storage) + 9)


def pad(storage) -> int:
    """编辑态窗口相对卡片的外扩（逻辑像素）。

    必须 ≥ `handle_hit()/2`，否则命中区有一半落在窗外——用户点"看起来
    是圆"的地方不中，就是反馈 8 里"小球和虚线一起偏出去"却更难点中的原因。
    """
    half = (handle_hit(storage) + 1) // 2
    return max(6, half + 1)


def fill(storage) -> float:
    """当前填充比例（设置值夹到 [MIN_FILL, MAX_FILL]，脏值回退默认）。"""
    try:
        raw = storage.get_setting("widget_fill")
        v = DEFAULT_FILL if raw is None else float(raw)
    except (TypeError, ValueError, AttributeError):
        return DEFAULT_FILL
    return max(MIN_FILL, min(MAX_FILL, v))


def _cell(storage) -> Tuple[int, int]:
    from . import grid_flow
    cw, ch = grid_flow.cell_size(storage)
    return max(1, int(cw)), max(1, int(ch))


def span_box(storage, span) -> Tuple[int, int]:
    """跨度对应的**整格盒**尺寸（占位 / 碰撞形状，不含 fill）。"""
    cw, ch = _cell(storage)
    return int(span[0]) * cw, int(span[1]) * ch


def card_size(storage, span) -> Tuple[int, int]:
    """卡片尺寸 = 格盒 × fill（至少 1 像素）。"""
    bw, bh = span_box(storage, span)
    f = fill(storage)
    return max(1, int(round(bw * f))), max(1, int(round(bh * f)))


def window_size(storage, span, editing: bool = False) -> Tuple[int, int]:
    """窗口尺寸：静止 = 卡片；编辑 = 卡片 + 两侧 pad。"""
    w, h = card_size(storage, span)
    if not editing:
        return w, h
    p = pad(storage)
    return w + p * 2, h + p * 2


def box_inset(storage, span) -> Tuple[int, int]:
    """卡片在格盒内的左/上偏移（居中留缝，左右上下各半格间隙）。"""
    bw, bh = span_box(storage, span)
    w, h = card_size(storage, span)
    return (bw - w) // 2, (bh - h) // 2


def card_pos(storage, col: int, row: int, span) -> Tuple[int, int]:
    """格坐标 -> 卡片左上角像素（窗口控件坐标）。"""
    from . import grid_flow
    x, y = grid_flow.cell_pos(storage, int(col), int(row))
    dx, dy = box_inset(storage, span)
    return int(x) + dx, int(y) + dy


def window_pos(storage, col: int, row: int, span,
               editing: bool = False) -> Tuple[int, int]:
    """格坐标 -> 窗口左上角像素（编辑态把外扩量从位置里扣掉）。"""
    x, y = card_pos(storage, col, row, span)
    if not editing:
        return x, y
    p = pad(storage)
    return x - p, y - p


def span_from_pixels(storage, w: int, h: int) -> Optional[Tuple[int, int]]:
    """按卡片像素尺寸反推跨度（round 到最近的整卡）。

    反推必须用 `cw*fill` 而不是 `cw`——旧实现按整格反推，加了填充比例
    之后 2 格的卡片只有 1.8 格宽，round 会掉到 2（侥幸对）/3 格时掉到 2
    （错一格），碰撞形状与视觉再次分家。
    """
    cw, ch = _cell(storage)
    f = fill(storage)
    cw_f, ch_f = max(1.0, cw * f), max(1.0, ch * f)
    cs = max(1, int(round(max(1.0, float(w)) / cw_f)))
    rs = max(1, int(round(max(1.0, float(h)) / ch_f)))
    return cs, rs


def set_fill(storage, value) -> float:
    """写填充比例（夹紧 + 落盘交给调用方；幂等）。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = DEFAULT_FILL
    v = max(MIN_FILL, min(MAX_FILL, v))
    storage.set_setting("widget_fill", round(v, 4))
    return v
