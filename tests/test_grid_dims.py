# -*- coding: utf-8 -*-
"""B1 尺寸地基：`solve_dims` 契约（v7 §3.2，验收 D1~D11）。

**零 Qt 依赖**——`grid_sizing.solve_dims` 是纯函数，本文件不建 QApplication。

锁死的用户模型（2026-10-20 02:51 用户原话闭环）：

  - 列数是**唯一**改变 cell 尺寸的旋钮：`cw = UW // cols`，`ch = cw*aspect`
  - 行数**只裁剪**"网格用几行"，cell 一个像素都不动（D7 是本轮最关键的断言）
  - 行列都只能"变大格子"，上限就是自动值（D3 / D9）

本机参考：2048x1152 @125%、native 48px -> cell 84x91、23 列 x 12 行、原点 (58,30)。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.grid_sizing import (  # noqa: E402
    MAX_COLS,
    MIN_COLS,
    cell_from_native,
    icon_layout,
    solve_dims,
)

FAILED = []
W, H = 2048, 1152          # 本机工作区（逻辑像素，任务栏已扣除）
NATIVE = 48                # HKCU Bags\1\Desktop\IconSize
EDGE_X, EDGE_Y = 26, 22    # 默认边距
UW, UH = W - 2 * EDGE_X, H - 2 * EDGE_Y


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra), flush=True)
    if not cond:
        FAILED.append(name)


def main():
    cw0, ch0 = cell_from_native(NATIVE)

    # ---------- D0：cell 公式锚点（规格表 §3.2 基准行）----------
    check("D0 cell_from_native(48) == (84,91)", (cw0, ch0) == (84, 91),
          "got %s" % ((cw0, ch0),))

    # ---------- D1：自动模式 ----------
    d = solve_dims(W, H, native_px=NATIVE)
    check("D1 自动 cols == cols_auto", d.cols == d.cols_auto,
          "%s vs %s" % (d.cols, d.cols_auto))
    check("D1 自动 rows == rows_auto", d.rows == d.rows_auto,
          "%s vs %s" % (d.rows, d.rows_auto))
    check("D1 自动 = 23 列 x 12 行", (d.cols, d.rows) == (23, 12),
          "got %s" % ((d.cols, d.rows),))
    check("D1 整行不溢出可用宽", d.cols * d.cw + 2 * EDGE_X <= W + 2,
          "%d > %d" % (d.cols * d.cw + 2 * EDGE_X, W))
    check("D1 自动模式 cell == 基准", (d.cw, d.ch) == (cw0, ch0),
          "got %s" % ((d.cw, d.ch),))
    check("D1 自动原点居中 (58,30)", (d.ox, d.oy) == (58, 30),
          "got %s" % ((d.ox, d.oy),))

    # ---------- D2：手动 18 列（唯一改变 cell 的旋钮）----------
    d18 = solve_dims(W, H, native_px=NATIVE, cols=18)
    check("D2 18 列 cols == 18", d18.cols == 18, "got %s" % (d18.cols,))
    check("D2 18 列格子变宽", d18.cw > d.cw, "%d vs %d" % (d18.cw, d.cw))
    check("D2 18 列 aspect 守恒 ±0.01",
          abs(d18.ch / d18.cw - d.ch / d.cw) <= 0.01,
          "%.4f vs %.4f" % (d18.ch / d18.cw, d.ch / d.cw))
    check("D2 18 列行数自动下调", d18.rows < d.rows,
          "%d vs %d" % (d18.rows, d.rows))
    check("D2 18 列 = 110x119 / 9 行",
          (d18.cw, d18.ch, d18.rows) == (110, 119, 9),
          "got %s" % ((d18.cw, d18.ch, d18.rows),))
    check("D2 18 列整行不溢出", d18.cols * d18.cw <= UW,
          "%d > %d" % (d18.cols * d18.cw, UW))

    # ---------- D3：超上限夹到 cols_auto（且与自动完全等价）----------
    d_hi = solve_dims(W, H, native_px=NATIVE, cols=999)
    check("D3 超上限 cols == cols_auto", d_hi.cols == d.cols_auto,
          "got %s" % (d_hi.cols,))
    check("D3 超上限 cw 与自动一致", d_hi.cw == d.cw,
          "%d vs %d" % (d_hi.cw, d.cw))
    check("D3 超上限 ch 与自动一致", d_hi.ch == d.ch,
          "%d vs %d" % (d_hi.ch, d.ch))

    # ---------- D4：下限 ----------
    d_one = solve_dims(W, H, native_px=NATIVE, cols=1, rows=1)
    check("D4 1 列不崩", d_one.cols == 1 and d_one.cw >= 1,
          "got %s" % ((d_one.cols, d_one.cw),))
    check("D4 1 行不崩", d_one.rows == 1, "got %s" % (d_one.rows,))

    # ---------- D5：图标跟着 cell 变大（fit 固定）----------
    box_auto = icon_layout(d.cw, d.ch, 0.57).icon_box
    box_18 = icon_layout(d18.cw, d18.ch, 0.57).icon_box
    check("D5 18 列图标同步变大", box_18 > box_auto,
          "%d vs %d" % (box_18, box_auto))

    # ---------- D6：自动 ⇄ 手动往返 ----------
    check("D6 回自动 = 自动结果",
          solve_dims(W, H, NATIVE).cols == d.cols
          and solve_dims(W, H, NATIVE, cols=d.cols_auto).cw == d.cw,
          "")

    # ---------- D7：行数裁剪**不动格子**（本轮最关键）----------
    d10 = solve_dims(W, H, 48, rows=10)
    check("D7 裁剪后 rows == 10", d10.rows == 10, "got %s" % (d10.rows,))
    check("D7 裁剪不动 cols/cw/ch（逐字段相等）",
          (d10.cols, d10.cw, d10.ch) == (d.cols, d.cw, d.ch),
          "%s vs %s" % ((d10.cols, d10.cw, d10.ch),
                        (d.cols, d.cw, d.ch)))

    # ---------- D8：裁剪后仍垂直居中 ----------
    check("D8 裁剪后仍居中",
          d10.oy == EDGE_Y + (UH - 10 * d10.ch) // 2,
          "%d vs %d" % (d10.oy, EDGE_Y + (UH - 10 * d10.ch) // 2))
    check("D8 裁剪后原点 = 121", d10.oy == 121, "got %s" % (d10.oy,))

    # ---------- D9：先改列再填行 -> 夹到新 rows_auto ----------
    d18_12 = solve_dims(W, H, 48, cols=18, rows=12)
    check("D9 18 列填 12 行被夹到 rows_auto",
          d18_12.rows == d18.rows_auto,
          "%s vs %s" % (d18_12.rows, d18_12.rows_auto))
    check("D9 夹紧后不出现行溢出",
          d18_12.rows * d18_12.ch <= UH + d18_12.ch // 2,
          "%d > %d" % (d18_12.rows * d18_12.ch, UH))

    # ---------- D10：极窄兜底不无限溢出 ----------
    d_narrow = solve_dims(W, H, NATIVE, cols=1)
    check("D10 1 列 oy >= 0", d_narrow.oy >= 0, "got %s" % (d_narrow.oy,))
    check("D10 1 列行数不超自动上限",
          d_narrow.rows <= d.rows_auto + 1, "got %s" % (d_narrow.rows,))

    # ---------- D11：native_px 32~96 扫一遍 ----------
    bad = []
    for npx in range(32, 97, 2):
        dd = solve_dims(W, H, npx)
        if not (MIN_COLS <= dd.cols_auto <= MAX_COLS):
            bad.append((npx, dd.cols_auto))
        if not (1 <= dd.rows_auto <= 12):
            bad.append((npx, "rows=%s" % (dd.rows_auto,)))
        if dd.cw < 1 or dd.ch < 1:
            bad.append((npx, (dd.cw, dd.ch)))
    check("D11 native 32~96 全部合法", not bad, "bad=%s" % (bad[:4],))

    # ---------- D12：origin 手动模式夹到完整工作区（可贴边）----------
    d_origin = solve_dims(W, H, NATIVE, origin=(0, 0))
    check("D12 手动原点 (0,0) 不被 edge 拦住",
          (d_origin.ox, d_origin.oy) == (0, 0),
          "got %s" % ((d_origin.ox, d_origin.oy),))
    d_far = solve_dims(W, H, NATIVE, origin=(99999, 99999))
    check("D12 原点超界夹紧",
          d_far.ox <= W - d_far.cols * d_far.cw
          and d_far.oy <= H - d_far.rows * d_far.ch,
          "got %s" % ((d_far.ox, d_far.oy),))


crashed = None
try:
    main()
except Exception:                      # 坑 #38：异常绝不能被吞成"通过"
    import traceback
    traceback.print_exc()
    crashed = "exception"
finally:
    print("-" * 60)
    if FAILED:
        print("FAILED: %d -> %s" % (len(FAILED), FAILED))
    if crashed or FAILED:
        sys.stdout.flush()
        os._exit(1)
    print("ALL grid_dims PASSED")
    sys.stdout.flush()
    os._exit(0)
