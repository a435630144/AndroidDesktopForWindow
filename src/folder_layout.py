# -*- coding: utf-8 -*-
"""文件夹尺寸模型（v7 反馈 14，纯函数·零 Qt 依赖）。

用户原话（2026-10-20 17 条反馈之 14）：

    文件夹默认展开 3×3，可右键单设 / 设置页改全局默认；
    最小 2×2；按实际数量收缩（2 个 → 2×2，3 个 → 3×2）；排队优先排满一行。

因此「文件夹大小」不是一个固定框，而是**上限**：

  - 上限（frame）默认 3×3，用户可改到 2×2 ~ 6×6；
  - 实际列数 = min(上限列, max(2, 成员数))      -> 2 个成员 = 2 列
  - 实际行数 = min(上限行, max(2, ceil(n/列)))  -> 3 个成员 = 3 列 2 行
  - 行数下限 2 就是"最小 2×2"的来源（1 个成员也是 2×2 的空框）
  - 超过上限容量时**只增加行**（列数保持视觉节奏），成员一个都不丢

这三条一起解释了用户给的两个例子：
    2 个 -> 2×2      （列收缩到 2，行数吃到下限 2）
    3 个 -> 3×2      （列铺满 3，行数仍是下限 2）
"""

FRAME_MIN = 2
FRAME_MAX = 6
DEFAULT_FRAME = (3, 3)

# 右键子菜单提供的档位（够用且不制造选择困难）
FRAME_PRESETS = ((2, 2), (3, 2), (3, 3), (4, 3), (4, 4))


def frame_pair(raw, fallback=DEFAULT_FRAME):
    """任意输入 -> 合法的 (cols, rows) 上限对（夹到 2..6，非法回退）。"""
    out = []
    for i in (0, 1):
        val = None
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            try:
                val = int(raw[i])
            except (TypeError, ValueError):
                val = None
        if val is None:
            val = int(fallback[i])
        out.append(max(FRAME_MIN, min(FRAME_MAX, val)))
    return out[0], out[1]


def grid_shape(n: int, frame=DEFAULT_FRAME):
    """成员数 + 尺寸上限 -> 实际 (cols, rows)。

    纯函数：文件夹弹窗只用它排成员格，所以"2 个为什么是 2×2"
    这类争议可以脱离 GUI 直接断言。
    """
    n = max(0, int(n))
    fc, fr = frame_pair(frame)
    cols = max(FRAME_MIN, min(fc, max(FRAME_MIN, n)))
    rows = max(FRAME_MIN, min(fr, max(FRAME_MIN, -(-n // cols))))
    # 超出上限容量：只加行，保证所有成员都有格位（永不丢成员）
    while cols * rows < n:
        rows += 1
    return cols, rows


def label(cols: int, rows: int) -> str:
    """尺寸的可读文案（右键菜单 / 设置页提示共用）。"""
    return "%d × %d" % (int(cols), int(rows))
