# -*- coding: utf-8 -*-
"""网格自适应（GridMetrics）——纯逻辑，零 Qt 依赖，可离线单测。

指导文档_网格与交互_v5.md §1（反馈 P1：网格没有完整填充屏幕）：

  病根：`grid_flow.origin()` 硬编码 (26, 22)、`storage.columns` 固定 10，
  与视口尺寸 / 图标大小完全脱钩——1920x1080 @100% 下 10 列只占屏幕右半，
  底部 1/3 留白；用户往空白区拖图标时 `_cell_at` 把 col 夹紧到最后一列，
  触发半幅布局平移（P2 的直接体感）。P1 与 P2 是同一个病根。

  方案：按工作区尺寸 ÷ 单元格大小自动算行列，剩余空间均分 -> 四边等距铺满：

    edge_x = round(26 * chrome_scale)              # 与旧 origin 同量级的最小边距
    edge_y = round(22 * chrome_scale)
    cols   = clamp((W - 2*edge_x) // cw, 2, 24)
    rows   = clamp((H - 2*edge_y) // ch, 1, 12)    # 单屏行数（配合 M6 分页）
    ox     = edge_x + (W - 2*edge_x - cols*cw) // 2  # 剩余空间均分
    oy     = edge_y + (H - 2*edge_y - rows*ch) // 2

  columns 设置语义："auto"（默认）自动计算；int（>=2）为手动覆盖
  （设置高级选项；指定后 GridMetrics 以手动值为准，rows 仍自动）。

    2026-10-19 v6 批次 A（指导文档_网格与无界双模式_v6.md §2.1）：
    cell 来源改为**屏幕驱动**——`grid_sizing.cell_for_screen(W, H)`
    （短边归一化公式），与 `icon_size / icon_scale` **完全解钩**：
    高 DPI 大屏不再 cell 更大列数更少，跨设备每屏格数密度一致。
    （旧实现 cell 来自 `grid_flow.cell_size(storage)` 的 icon 派生。）
"""
from __future__ import annotations

from typing import NamedTuple, Optional, Tuple

MIN_COLS, MAX_COLS = 2, 24
MIN_ROWS, MAX_ROWS = 1, 12


class GridMetrics(NamedTuple):
    """一次网格几何快照（窗口控件坐标，逻辑像素）。"""

    cols: int
    rows: int
    ox: int
    oy: int
    cw: int
    ch: int


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _manual_columns(storage, columns_override) -> Optional[int]:
    """解析手动列数覆盖：columns_override 参数优先于 settings["columns"]。

    仅接受 >= MIN_COLS 的整数；"auto" / 空串 / None / 非法值一律回退自动。
    """
    raw = columns_override
    if raw is None:
        raw = storage.get_setting("columns")
    if raw is None:
        return None
    if isinstance(raw, str):
        if raw.strip().lower() in ("", "auto"):
            return None
        try:
            raw = int(float(raw))
        except ValueError:
            return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if n >= MIN_COLS else None


def compute(storage, screen_size: Tuple[int, int],
            columns_override=None, native_px=None) -> GridMetrics:
    """按工作区尺寸计算网格几何（四边等距、精确铺满）。

    native_px：资源管理器当前桌面图标边长（逻辑 px）。给定且
    settings["icon_match_native"] 为真（默认）时，cell 由
    `grid_sizing.cell_for_native()` 反推——图标本体与原桌面 1:1 大小
    （2026-10-19 用户反馈 4）。None / 关闭该项时走旧的屏幕驱动公式。

    storage 只需提供 get_setting / icon_metric / icon_chrome_scale
    （与 grid_flow.cell_size 的依赖面一致——fake storage 可直接单测）。
    screen_size：availableGeometry 的 (W, H)，任务栏已由 Qt 扣除；
    窗口左上角在屏幕上的偏移由调用方处理（整理窗口铺满整个工作区）。
    """
    from . import grid_sizing  # 延迟导入：cell 公式的唯一实现，避免重复

    W, H = int(screen_size[0]), int(screen_size[1])
    match_native = bool(storage.get_setting("icon_match_native"))
    if match_native and native_px:
        try:
            tier = storage.icon_tier()
        except Exception:
            tier = grid_sizing.DEFAULT_TIER
        cw, ch = grid_sizing.cell_for_native(int(native_px), tier)
    else:
        cw, ch = grid_sizing.cell_for_screen(W, H)
    cw, ch = max(1, int(cw)), max(1, int(ch))
    chrome = float(storage.icon_chrome_scale())
    edge_x = int(round(26 * chrome))
    edge_y = int(round(22 * chrome))

    manual = _manual_columns(storage, columns_override)
    cols = manual if manual is not None else _clamp((W - 2 * edge_x) // cw,
                                                    MIN_COLS, MAX_COLS)
    rows = _clamp((H - 2 * edge_y) // ch, MIN_ROWS, MAX_ROWS)

    ox = edge_x + (W - 2 * edge_x - cols * cw) // 2
    oy = edge_y + (H - 2 * edge_y - rows * ch) // 2
    return GridMetrics(cols, rows, max(0, ox), max(0, oy), cw, ch)
