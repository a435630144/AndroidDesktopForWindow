# -*- coding: utf-8 -*-
"""问题反馈 1：图标尺寸为中 / 小时不应贴网格左上角，而应在 cell 内居中。

病根：`grid_flow.entry_pos` 网格模式直接返回 `cell_pos(col,row)`（cell 左上
角）。图标 widget 尺寸 = cell × 档位（small .58 / medium .74），小档时 widget
比 cell 小 40%+，左上角对齐会让整套图标整体偏左上、格间留白全部堆在右下。

契约：
  C1 small 档：entry_pos = cell_pos + ((cw-w)//2, (ch-h)//2)
  C2 medium 档同式；C3 large 档偏移为 (0,0)（widget == cell）
  C4 左右留白对称、上下留白对称（视觉居中）
  C5 图标视觉中心与 cell 中心重合（误差 <= 1px）
  C6 无界模式不受影响（fx/fy 原样，自由摆布不允许被居中改写）
  C7 切无界（to_free_coords）生成的 fx/fy = 居中后的网格位置（不跳变）
  C8 居中后点图标中心，反算仍落在原 cell（命中判定不漂移）

运行：python tests/test_icon_center.py   （offscreen）
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import grid_flow, grid_sizing

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


class FakeStorage:
    """grid_flow 的依赖面：settings / layout / widgets / columns / takeover。"""

    def __init__(self, tier="medium"):
        self._s = {
            "columns": "auto",
            "layout_mode": "grid",
            "icon_tier": tier,
            "takeover_desktop": True,
            "extra_pages": [],
        }
        self.layout = []
        self.widgets = []

    def get_setting(self, key):
        return self._s.get(key)

    def set_setting(self, key, value):
        self._s[key] = value

    def takeover(self):
        return bool(self._s["takeover_desktop"])

    def icon_metric(self):
        return 72

    def ui_scale(self):
        return 1.0

    def icon_tier(self):
        return self._s.get("icon_tier") or "medium"

    @property
    def columns(self):
        m = grid_flow.current_metrics()
        return m.cols if m is not None else 10


def entry(eid, col, row):
    return {"id": eid, "type": "app", "col": col, "row": row}


def main():
    grid_flow.set_page(0)

    for tier in ("small", "medium", "large"):
        st = FakeStorage(tier)
        m = grid_flow.set_grid(st, (1920, 1080))
        lay = grid_sizing.icon_layout(m.cw, m.ch, tier)
        e = entry("a", 3, 2)
        cx, cy = grid_flow.cell_pos(st, 3, 2)
        px, py = grid_flow.entry_pos(st, e)
        want_dx = (m.cw - lay.widget_w) // 2
        want_dy = (m.ch - lay.widget_h) // 2
        check("C/%s 偏移 = 居中留白 (%d,%d)" % (tier, want_dx, want_dy),
              (px - cx, py - cy) == (want_dx, want_dy),
              "got %s" % ((px - cx, py - cy),))
        # 视觉中心与 cell 中心重合
        icon_cx = px + lay.widget_w / 2.0
        icon_cy = py + lay.widget_h / 2.0
        cell_cx = cx + m.cw / 2.0
        cell_cy = cy + m.ch / 2.0
        check("C5/%s 图标中心 == cell 中心" % tier,
              abs(icon_cx - cell_cx) <= 1 and abs(icon_cy - cell_cy) <= 1,
              "icon(%.1f,%.1f) cell(%.1f,%.1f)"
              % (icon_cx, icon_cy, cell_cx, cell_cy))

    # C1b small 档的留白必须 > 0（回归点：旧实现偏移恒为 0）
    st = FakeStorage("small")
    m = grid_flow.set_grid(st, (1920, 1080))
    lay = grid_sizing.icon_layout(m.cw, m.ch, "small")
    cx, cy = grid_flow.cell_pos(st, 0, 0)
    px, py = grid_flow.entry_pos(st, entry("a", 0, 0))
    check("C1b small 档留白非零（旧 bug 回归点）",
          px > cx and py > cy, "dx=%d dy=%d" % (px - cx, py - cy))

    # C4 四边留白对称
    right = m.cw - ((m.cw - lay.widget_w) // 2) - lay.widget_w
    bottom = m.ch - ((m.ch - lay.widget_h) // 2) - lay.widget_h
    check("C4 左右留白差 <=1", abs(right - (px - cx)) <= 1,
          "left=%d right=%d" % (px - cx, right))
    check("C4 上下留白差 <=1", abs(bottom - (py - cy)) <= 1,
          "top=%d bottom=%d" % (py - cy, bottom))

    # C6 无界模式不被改写
    st6 = FakeStorage("medium")
    grid_flow.set_grid(st6, (1920, 1080))
    st6.set_setting("layout_mode", "free")
    e6 = {"id": "b", "type": "app", "col": 1, "row": 0, "fx": 137, "fy": 246}
    check("C6 无界模式 position = fx/fy 原样",
          grid_flow.entry_pos(st6, e6) == (137, 246),
          "%s" % (grid_flow.entry_pos(st6, e6),))

    # C7 切无界不跳变（生成式与网格居中一致）
    st7 = FakeStorage("small")
    m7 = grid_flow.set_grid(st7, (1920, 1080))
    e7 = entry("c", 4, 1)
    st7.layout.append(e7)
    grid_pos = grid_flow.entry_pos(st7, e7)
    n = grid_flow.to_free_coords(st7)
    free_pos = grid_flow.entry_pos(st7, e7)
    check("C7 切无界生成 %d 个坐标" % n, n == 1, "n=%d" % n)
    check("C7 切无界视觉不跳变", free_pos == grid_pos, "%s vs %s"
          % (free_pos, grid_pos))

    # C8 反算命中不漂移
    st8 = FakeStorage("small")
    m8 = grid_flow.set_grid(st8, (1920, 1080))
    lay8 = grid_sizing.icon_layout(m8.cw, m8.ch, "small")
    e8 = entry("d", 5, 3)
    px8, py8 = grid_flow.entry_pos(st8, e8)
    centre = (px8 + lay8.widget_w // 2, py8 + lay8.widget_h // 2)
    check("C8 点图标中心反算回原格", grid_flow.pos_cell(st8, *centre) == (5, 3),
          "%s" % (grid_flow.pos_cell(st8, *centre),))

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL icon_center PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
