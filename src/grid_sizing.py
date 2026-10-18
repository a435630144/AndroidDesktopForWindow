# -*- coding: utf-8 -*-
"""网格尺寸体系（v6 批次 A，指导文档_网格与无界双模式_v6.md §2）。

**输入只有用户屏幕 availableGeometry**（DPI 感知后的逻辑像素）——
没有任何从某台机器反推的常数（用户反馈："公式不是以我的电脑为准，
而是去获取用户电脑的设置信息"）。

### cell 尺寸公式（§2.1，网格模式）

    REF_SHORT = 1080.0            # 参考屏逻辑短边（设计基准，非机器参数）
    CELL_REF  = (78.0, 96.0)      # 参考屏上的 cell（逻辑 px）
    k    = clamp(min(W, H) / REF_SHORT, 0.7, 1.8)   # 短边归一化
    cell = (round(78 * k), round(96 * k))

为什么不再乘 dpr：`availableGeometry` 返回的已是 DPI 感知的逻辑像素
（125% 缩放把 2560x1440 物理折算成 2048x1152 逻辑），cell 再乘 dpr
会让高 DPI 大屏的 cell 反而更大、列数更少——背离"按分辨率自适应"
的诉求。短边归一化保证任意分辨率/缩放的机器每屏格数密度一致：

    1920x1080 -> 78x96 -> 23 列 x 10 行
    2048x1152 -> 83x102 -> 23 列 x 10 行
    1366x768  -> 55x68  -> 23 列 x 10 行
    2560x1440 -> 104x128 -> 23 列 x 10 行

### 图标三档（§2.2）

widget 整体（图标 + 标签）按档位比例 x cell 渲染；AppIcon 内部自适应
（chrome 全部按 cell/widget 比例派生——旧绝对值 24m/40m 在 cell 变小后
会把图标挤成小点；标签改单行小字 elide，密度加密后必须瘦身）：

    档位   比例    @cell 83x102 -> widget / icon_box / label
    small  0.58    48x59 / 34 / 9px 单行
    medium 0.74    61x75 / 47 / 10px 单行（默认）
    large  1.00    83x102 / 69 / 14px 单行

icon_box = widget_w - 2*chrome_x（chrome_x=7，规格表锁定）；
label_h = widget_h - icon_box；font_px 随 icon_box 分档（9/10/14）。

无界模式（§1.2）不用本公式：图标 widget = settings["icon_px"] 用户
像素值直接生效；cell 仅供网格模式与快照回退。
"""
from __future__ import annotations

from typing import NamedTuple, Optional, Tuple

REF_SHORT = 1080.0
CELL_REF = (78.0, 96.0)
K_MIN, K_MAX = 0.7, 1.8

# 图标三档（§2.2）：widget 整体（含标签）相对 cell 的比例
TIERS = {"small": 0.58, "medium": 0.74, "large": 1.0}
DEFAULT_TIER = "medium"

# 规格表（@cell 83x102）锁死的派生常数：
CHROME_X = 7            # 图标方块左右留白 = widget_w - icon_box 的一半
ICON_BOX_MIN = 16       # 小 cell 下图标方块下限
LABEL_H_MIN = 10        # 标签区下限（单行小字）
FONT_BOX_TIERS = ((40, 9), (58, 10))   # (icon_box 上界, font_px)，其余 14


class IconLayout(NamedTuple):
    """一次图标 widget 尺寸方案（逻辑像素）。"""

    widget_w: int
    widget_h: int
    icon_box: int       # 图标方块边长（pixmap 绘制区）
    chrome_x: int       # 图标方块左侧留白（居中：(widget_w-icon_box)/2）
    label_h: int        # 标签区高度（widget_h - icon_box）
    font_px: int        # 标签字号（单行 elide）


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def cell_for_screen(W: int, H: int) -> Tuple[int, int]:
    """屏幕工作区尺寸 -> cell（cw, ch），短边归一化 + 密度跨设备一致。

    W/H 传 availableGeometry 的逻辑像素（任务栏已扣除）。
    """
    short = max(1, min(int(W), int(H)))
    k = _clamp(short / REF_SHORT, K_MIN, K_MAX)
    return int(round(CELL_REF[0] * k)), int(round(CELL_REF[1] * k))


def parse_tier(raw) -> str:
    """档位名归一：三档之一；None/空/非法 -> 默认 medium。"""
    if isinstance(raw, str):
        t = raw.strip().lower()
        if t in TIERS:
            return t
    return DEFAULT_TIER


def _font_for_box(icon_box: int) -> int:
    for upper, px in FONT_BOX_TIERS:
        if icon_box <= upper:
            return px
    return 14


def icon_layout(cw: int, ch: int, tier) -> IconLayout:
    """cell 尺寸 + 档位 -> 图标 widget 尺寸方案（规格表 §2.2）。

    widget = round(cell * TIERS[tier])；icon_box = widget_w - 2*CHROME_X
    （下限 ICON_BOX_MIN）；label_h = widget_h - icon_box（下限
    LABEL_H_MIN）；font_px 随 icon_box 分档。
    """
    t = parse_tier(tier)
    r = TIERS[t]
    cw, ch = max(1, int(cw)), max(1, int(ch))
    w = max(1, int(round(cw * r)))
    h = max(1, int(round(ch * r)))
    box = max(ICON_BOX_MIN, w - 2 * CHROME_X)
    # chrome_x 保持居中语义：若 box 触下限则至少为 0
    chrome_x = max(0, (w - box) // 2)
    label_h = max(LABEL_H_MIN, h - box)
    return IconLayout(w, h, box, chrome_x, label_h, _font_for_box(box))


def icon_px_default() -> int:
    """无界模式图标像素默认值（§2.3）。"""
    return 96
