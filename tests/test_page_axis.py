# -*- coding: utf-8 -*-
"""翻页方向（2026-10-19 反馈 5）：默认左右，可切上下。

页容量不变（一页仍是 cols × rows_per_page 个格），只换页与页之间的
滑行轴——row 仍编码「第几页 + 页内行」，零数据迁移。

契约：
  A1 默认 page_axis = horizontal
  A2 左右：第 1 页整体右移一个网格宽（cols*cw），页内 y 不变
  A3 上下：第 1 页整体下移 rows*ch（旧行为）
  A4 pos_cell 在当前页内与 cell_pos 互逆（两个方向都成立）
  A5 page_offset 方向正确
  A6 无界模式（entry_pos）同样按轴滑行

运行：python tests/test_page_axis.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import grid_flow
from src.grid_metrics import GridMetrics

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


class St:
    def __init__(self, axis="horizontal", mode="grid"):
        self._s = {"page_axis": axis, "layout_mode": mode, "columns": 12,
                   "icon_size": 48, "icon_scale": 1.0, "takeover_desktop": True}

    def get_setting(self, k):
        return self._s.get(k)

    @property
    def columns(self):
        return self._s["columns"]

    def takeover(self):
        return True

    def icon_metric(self):
        return 48

    def ui_scale(self):
        return 1.0


def main():
    saved = grid_flow._current_metrics
    try:
        grid_flow._current_metrics = GridMetrics(
            cols=12, rows=8, ox=20, oy=18, cw=80, ch=96)

        # ---------- A1 默认 ----------
        check("A1 默认左右翻页",
              grid_flow.page_axis(St()) == "horizontal")

        st = St("horizontal")
        grid_flow.set_page(0)
        x0, y0 = grid_flow.cell_pos(st, 3, 2)              # 第 0 页
        x1, y1 = grid_flow.cell_pos(st, 3, 8 + 2)          # 第 1 页同格
        check("A2 左右：第 1 页右移一个网格宽",
              x1 - x0 == 12 * 80 and y1 == y0, "dx=%d dy=%d" % (x1 - x0, y1 - y0))
        check("A2b 页宽 = cols*cw", grid_flow.page_canvas_w(st) == 12 * 80)

        st_v = St("vertical")
        xv0, yv0 = grid_flow.cell_pos(st_v, 3, 2)
        xv1, yv1 = grid_flow.cell_pos(st_v, 3, 8 + 2)
        check("A3 上下：第 1 页下移 rows*ch",
              yv1 - yv0 == 8 * 96 and xv1 == xv0,
              "dx=%d dy=%d" % (xv1 - xv0, yv1 - yv0))

        # ---------- A4 反算互逆 ----------
        for axis in ("horizontal", "vertical"):
            s = St(axis)
            grid_flow.set_page(1)
            ok = True
            for col, row in ((0, 9), (5, 12), (11, 15)):
                x, y = grid_flow.cell_pos(s, col, row)
                c2, r2 = grid_flow.pos_cell(s, x + 2, y + 2)
                if (c2, r2) != (col, row):
                    ok = False
                    break
            check("A4 %s 方向 cell_pos/pos_cell 互逆" % axis, ok)

        # ---------- A5 page_offset ----------
        grid_flow.set_page(0)
        check("A5 左右偏移 = (dx>0, 0)",
              grid_flow.page_offset(st, 2) == (2 * 12 * 80, 0),
              "%s" % (grid_flow.page_offset(st, 2),))
        check("A5b 上下偏移 = (0, dy>0)",
              grid_flow.page_offset(st_v, 2) == (0, 2 * 8 * 96),
              "%s" % (grid_flow.page_offset(st_v, 2),))

        # ---------- A6 无界模式 ----------
        s_free = St("horizontal", mode="free")
        grid_flow.set_page(0)
        e = {"col": 1, "row": 8, "fx": 100, "fy": 200}
        x_free, y_free = grid_flow.entry_pos(s_free, e)
        check("A6 无界模式页间按横向滑行",
              x_free == 100 + 12 * 80 and y_free == 200,
              "pos=(%d,%d)" % (x_free, y_free))
    finally:
        grid_flow._current_metrics = saved
        grid_flow.set_page(0)

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL page_axis PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
