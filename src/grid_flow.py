# -*- coding: utf-8 -*-
"""图标网格让位引擎（Live Reflow）——纯逻辑，零 Qt 依赖，可离线单测。

设计依据 design.md 2.2「占用格集合上的置换」：
  稀疏网格的让位不需要解碰撞，只需在**固定的占用格集合**上重新分配图标。
    cells       = sorted(occupied cells)          # 拖动全程不变
    order       = [ids sorted by (row, col)]      # 当前阅读序
    new_order   = order 去掉 dragged，按目标格插入
    new_layout  = zip(new_order, cells)

性质（tests/test_grid_flow.py 全量断言）：
  - 占用格集合守恒 -> 永不重叠、永不丢图标、空位保留
  - 跨行 / 空格 / 占用格 / 原地 统一处理
  - O(n log n)，每次 dragMove 全量重算无压力

与 DesktopWindow 的关系：_cell()/_origin() 已下沉到本模块（cell_size/origin），
两边共用同一份几何定义，避免 DRY 违背导致的网格与图标错位。
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

Cell = Tuple[int, int]


# ---------- 阅读序 ----------
def _cell_of(entry: dict) -> Cell:
    return int(entry.get("col", 0)), int(entry.get("row", 0))


def reading_order(entries: Iterable[dict], cols: int) -> List[dict]:
    """按 (row, col) 稳定排序（同一行内从左到右，行间从上到下）。"""
    return sorted(entries, key=lambda e: (int(e.get("row", 0)), int(e.get("col", 0))))


def occupied_cells(entries: Iterable[dict], cols: int) -> List[Cell]:
    """排序去重后的占用格集合。cols 仅用于签名对称（调用方已夹紧 col）。"""
    seen = set()
    for e in entries:
        seen.add(_cell_of(e))
    return sorted(seen)


# ---------- 让位求解 ----------
def reflow_order(entries: Sequence[dict], cols: int, dragged_id: str,
                 target: Cell, extra_occupied: Iterable[Cell] = ()) -> Optional[List[str]]:
    """计算拖动 dragged_id 到 target 后的新阅读序（entry id 列表）。

    target 越界会被夹紧到 [0, cols-1] x [0, +inf)。
    dragged_id 不存在时返回 None（调用方应忽略本次预览）。
    原地拖动返回与原顺序相同的列表（恒等）。

    extra_occupied：额外的固定占用格集合（锚定小组件的占位，2026-10-18
    「小组件占据格子挤走图标」）。target 落在其中时，先就近解析到最近的
    非占用格——小组件的格子不给图标用。
    """
    if cols < 1:
        return None
    by_id = {e.get("id"): e for e in entries}
    if dragged_id not in by_id:
        return None

    extra = set(extra_occupied or ())
    tcol = max(0, min(int(cols) - 1, int(target[0])))
    trow = max(0, int(target[1]))
    target = (tcol, trow)
    if target in extra:
        target = nearest_free_cell(target, set(occupied_cells(entries, cols)) | extra, cols)

    order = [e["id"] for e in reading_order(entries, cols)]
    if dragged_id not in order:
        return None
    rest = [i for i in order if i != dragged_id]

    cells = occupied_cells(entries, cols)

    # 统一插入规则：k = 第一个 >= target 的占用格下标（夹紧到 [0, len(rest)]）
    #   - target 被占用  -> k = 该格下标，dragged 正好落上目标格，占用者及其后整体后移
    #   - target 为空    -> k = 第一个严格大于 target 的格下标，dragged 落到该格
    #   - target == 老格 -> k = 老格下标，等价于恒等（移回去恢复原序）
    k = len(cells)
    for idx, c in enumerate(cells):
        if c >= target:
            k = idx
            break
    k = max(0, min(len(rest), k))
    return rest[:k] + [dragged_id] + rest[k:]


def nearest_free_cell(target: Cell, occupied: set, cols: int) -> Cell:
    """曼哈顿距离升序找第一个非占用格（同距时阅读序优先）。

    extra_occupied 场景下把落在小组件占位上的落点解析到最近可用格；
    行范围取占用格最大行 +2，保证屏幕外沿也有解。
    """
    occupied = set(occupied)
    max_row = max((r for _, r in occupied), default=0) + 2
    tc, tr = int(target[0]), int(target[1])
    for dist in range(0, cols + max_row + 4):
        for dc in range(-dist, dist + 1):
            for dr in (-dist, dist) if dist > 0 else (0,):
                c, r = tc + dc, tr + dr
                if 0 <= c < cols and 0 <= r <= max_row and (c, r) not in occupied:
                    return c, r
    return max(0, min(tc, cols - 1)), tr


def apply_order(entries: Sequence[dict], order: Sequence[str]) -> None:
    """把 order（阅读序）按原占用格集合就地写回 col/row。

    前提：order 是 entries 的一个排列（reflow_order 的返回值即满足）。
    """
    if not order:
        return
    cells = occupied_cells(entries, 1 << 30)
    if len(cells) != len(order):
        return  # 防御：调用方传了不完整顺序，宁可不写也别写坏布局
    by_id = {e.get("id"): e for e in entries}
    for eid, (c, r) in zip(order, cells):
        e = by_id.get(eid)
        if e is not None:
            e["col"], e["row"] = c, r


# ---------- 网格几何（与 DesktopWindow 共用，勿重复实现） ----------
def origin() -> Cell:
    """网格原点（桌面整理窗口控件坐标）。"""
    return 26, 22


def cell_size(storage) -> Cell:
    """单元格尺寸：与 AppIcon(setFixedSize(s+24m, s+40m)) 对齐。

    s = DPI × 用户缩放双感知的图标边长；m = 外围 chrome 缩放。
    2026-10-18 chrome 从 28/46 收紧到 24/40（用户反馈"图标大小不对"——
    留白占比过大显图标小），行高再多 2px 间隙消除相邻标签重叠。
    """
    s = int(storage.icon_metric())
    m = float(storage.icon_chrome_scale())
    return s + int(round(24 * m)), s + int(round(40 * m)) + 2


def snap_point(storage, x: int, y: int, screen_size: Tuple[int, int]) -> Cell:
    """把任意坐标吸附到最近的网格格点，并夹紧在屏幕内。"""
    ox, oy = origin()
    cw, ch = cell_size(storage)
    if cw <= 0 or ch <= 0:
        return max(0, int(x)), max(0, int(y))
    col = int(round((x - ox) / cw))
    row = int(round((y - oy) / ch))
    sx = ox + col * cw
    sy = oy + row * ch
    sw, sh = int(screen_size[0]), int(screen_size[1])
    return max(0, min(sx, max(0, sw - 40))), max(0, min(sy, max(0, sh - 40)))


# ---------- 锚定小组件占位（widget 作为网格一等公民） ----------
def widget_span(storage, widget: dict) -> Cell:
    """widget 占据几列几行（按当前像素尺寸 / 单元格尺寸换算，至少 1×1）。"""
    cw, ch = cell_size(storage)
    w = int(widget.get("w", 260))
    h = int(widget.get("h", 140))
    return max(1, int(round(w / max(1, cw)))), max(1, int(round(h / max(1, ch))))


def widget_cells(storage) -> set:
    """所有可见锚定 widget 占据的格子集合（从 storage.widgets 读，解耦：
    小组件只写 storage，DesktopWindow 直接读，无需实例引用）。"""
    cells = set()
    for w in storage.widgets:
        if not w.get("anchored") or w.get("hidden"):
            continue
        col = max(0, int(w.get("col", 0)))
        row = max(0, int(w.get("row", 0)))
        cs, rs = widget_span(storage, w)
        for dc in range(cs):
            for dr in range(rs):
                cells.add((col + dc, row + dr))
    return cells


def find_widget_slot(storage, widget: dict) -> Cell:
    """为锚定 widget 找第一个容得下它的左上空格（排除已有 widget 占位
    与图标占位）。找不到时退回 (0, 0)（极端拥挤场景， displace 会兜底）。"""
    cs, rs = widget_span(storage, widget)
    blocked = widget_cells(storage)
    for e in storage.layout:
        blocked.add((int(e.get("col", 0)), int(e.get("row", 0))))
    cols = storage.columns
    for row in range(0, 64):
        for col in range(0, cols - cs + 1):
            rect = {(col + dc, row + dr) for dc in range(cs) for dr in range(rs)}
            if not (rect & blocked):
                return col, row
    return 0, 0
