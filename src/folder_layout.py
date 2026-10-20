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

这三条一起解释了用户给的两个例子：
    2 个 -> 2×2      （列收缩到 2，行数吃到下限 2）
    3 个 -> 3×2      （列铺满 3，行数仍是下限 2）

**2026-10-21 反馈 3 覆盖了"超出就加行"**：

    比如文件夹的规格是 3*3，可以放入 9 个元素，超出的元素处理方式
    采用左右分页，分页方法与逻辑参考桌面分页。现在是继续渲染。

旧实现溢出时 `rows += 1`，3×3 装了 12 个成员就长成 3×4、3×5…弹窗
一路变高（甚至顶出屏幕）。现在尺寸**封顶在上限**，溢出的成员进
下一页（左滑/右滑翻页，与桌面分页同一手感）：

  - `capacity(frame)`   = 列 × 行（3×3 = 9）
  - `grid_shape(n)`     = min(上限, 按数量收缩)，n > 容量时不再加行
  - `page_count(n)`     = ceil(n / 容量)
  - `page_items(...)`   = 第 p 页的成员切片 + 全局起始下标（payload 用）

「按数量收缩」（2 个 -> 2×2）仍然保留：只在**未满页**时收缩，满页
之后尺寸固定，翻页不改变弹窗大小（否则每页都跳尺寸）。
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


def capacity(frame=DEFAULT_FRAME) -> int:
    """一页能放多少成员（列 × 行）。3×3 = 9。"""
    fc, fr = frame_pair(frame)
    return int(fc) * int(fr)


def grid_shape(n: int, frame=DEFAULT_FRAME):
    """成员数 + 尺寸上限 -> 实际 (cols, rows)。

    纯函数：文件夹弹窗只用它排成员格，所以"2 个为什么是 2×2"
    这类争议可以脱离 GUI 直接断言。

    反馈 3：**满页即封顶**——n 超过容量时返回上限本身，不再加行；
    多出来的成员由 `page_items()` 分页承载。
    """
    n = max(0, int(n))
    fc, fr = frame_pair(frame)
    if n > fc * fr:
        return fc, fr
    cols = max(FRAME_MIN, min(fc, max(FRAME_MIN, n)))
    rows = max(FRAME_MIN, min(fr, max(FRAME_MIN, -(-n // cols))))
    return cols, rows


def page_count(n: int, frame=DEFAULT_FRAME) -> int:
    """总页数（至少 1；空文件夹也算 1 页，便于画空态）。"""
    cap = capacity(frame)
    return max(1, -(-max(0, int(n)) // cap))


def clamp_page(page: int, n: int, frame=DEFAULT_FRAME) -> int:
    """页号夹到 [0, page_count-1]。"""
    return max(0, min(int(page), page_count(n, frame) - 1))


def page_items(items, page: int, frame=DEFAULT_FRAME):
    """取第 page 页的成员切片，返回 `(slice, 全局起始下标)`。

    全局下标是成员 payload（`M:<fid>:<idx>`）的索引来源——分页后
    每页都从 0 重排的局部下标会让"拖出第 2 页第 1 个"取错成员
    （取到第 1 页第 1 个）。所以切片必须带 offset 交给调用方。
    """
    seq = list(items or [])
    n = len(seq)
    cap = capacity(frame)
    page = clamp_page(page, n, frame)
    lo = page * cap
    return seq[lo:lo + cap], lo


def label(cols: int, rows: int) -> str:
    """尺寸的可读文案（右键菜单 / 设置页提示共用）。"""
    return "%d × %d" % (int(cols), int(rows))
