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
    # v7 B1：只读上限，供设置页显示「1 .. N」；旧消费方六字段零改动
    cols_auto: int = 0
    rows_auto: int = 0


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
    settings["icon_match_native"] 为真（默认）时走 **v7 两层模型**：
    `grid_sizing.solve_dims()` 用「原生图标 -> cell」反解，再由列数调
    格子大小、行数只裁剪。读不到 native 时退回 v6 屏幕驱动公式。

    行列来源优先级（v7 §3.2）：
      1. `columns_override` 参数（测试/临时覆盖）
      2. `settings["grid_dims_mode"] == "manual"` 的 `grid_cols` / `grid_rows`
      3. 旧键 `settings["columns"]`（int >= 2 视为手动列数，v6 遗留）
      4. 全自动

    storage 只需提供 get_setting / icon_metric / icon_chrome_scale
    （以及可选的 grid_* 访问器——缺失时按 auto 处理，旧 fake storage 仍可单测）。
    screen_size：availableGeometry 的 (W, H)，任务栏已由 Qt 扣除；
    窗口左上角在屏幕上的偏移由调用方处理（整理窗口铺满整个工作区）。
    """
    from . import grid_sizing  # 延迟导入：cell 公式的唯一实现，避免重复

    W, H = int(screen_size[0]), int(screen_size[1])
    chrome = float(storage.icon_chrome_scale())
    edge_x = int(round(26 * chrome))
    edge_y = int(round(22 * chrome))

    cols_req, rows_req, origin = _requested_dims(storage, columns_override)
    match_native = bool(storage.get_setting("icon_match_native"))
    native = int(native_px) if (match_native and native_px) else 0

    if native:
        d = grid_sizing.solve_dims(W, H, native, cols=cols_req, rows=rows_req,
                                   origin=origin, edge_x=edge_x, edge_y=edge_y)
        return GridMetrics(d.cols, d.rows, d.ox, d.oy, d.cw, d.ch,
                           d.cols_auto, d.rows_auto)

    # ---- 兜底路径（读不到原生图标尺寸）：v6 屏幕驱动公式 ----
    cw, ch = grid_sizing.cell_for_screen(W, H)
    cw, ch = max(1, int(cw)), max(1, int(ch))
    cols_auto = _clamp((W - 2 * edge_x) // cw, MIN_COLS, MAX_COLS)
    cols = cols_auto if cols_req is None else _clamp(int(cols_req),
                                                     MIN_COLS, cols_auto)
    rows_auto = _clamp((H - 2 * edge_y) // ch, MIN_ROWS, MAX_ROWS)
    rows = rows_auto if rows_req is None else _clamp(int(rows_req),
                                                     MIN_ROWS, rows_auto)
    if origin is None:
        ox = edge_x + (W - 2 * edge_x - cols * cw) // 2
        oy = edge_y + (H - 2 * edge_y - rows * ch) // 2
    else:
        ox = _clamp(int(origin[0]), 0, max(0, W - cols * cw))
        oy = _clamp(int(origin[1]), 0, max(0, H - rows * ch))
    return GridMetrics(cols, rows, max(0, ox), max(0, oy), cw, ch,
                       cols_auto, rows_auto)


def _requested_dims(storage, columns_override):
    """解析 (cols, rows, origin)。缺访问器/非法值一律按"自动"处理。

    v7 起**只认** `grid_dims_mode` + `grid_cols/grid_rows`（旧键 `columns`
    由 `Storage.set_setting` 做兼容转发，并在加载时迁移，这里不再读它——
    否则"自动模式"会被历史残留的整数列数永久劫持）。
    """
    cols = rows = origin = None
    mode = "auto"
    try:
        mode = storage.grid_dims_mode()
    except Exception:
        mode = "auto"
    if mode == "manual":
        try:
            cols = storage.grid_cols()
            rows = storage.grid_rows()
        except Exception:
            cols = rows = None
    try:
        origin = storage.grid_origin()
    except Exception:
        origin = None
    if columns_override is not None:
        try:
            cols = int(columns_override)
        except (TypeError, ValueError):
            cols = None
    # 兼容层：**不具备** `grid_dims_mode` 的旧 fake storage（单测桩）仍可按
    # 旧键 `columns` 指定列数。真实 `Storage` 永远有该访问器，所以"自动模式
    # 被历史整数劫持"的坑不会被这条路绕过。
    if cols is None and not hasattr(storage, "grid_dims_mode"):
        cols = _manual_columns(storage, columns_override)
    return cols, rows, origin
