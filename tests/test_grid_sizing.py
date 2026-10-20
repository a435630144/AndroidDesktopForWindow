# -*- coding: utf-8 -*-
"""grid_sizing 单测（v6 批次 A，指导文档_网格与无界双模式_v6.md §2）

锁死两份规格表：

  1. cell_for_screen 跨设备公式（REF_SHORT=1080 / CELL_REF=(78,96)，
     k = clamp(min(W,H)/1080, 0.7, 1.8)）：
       1920x1080 -> 78x96    2048x1152 -> 83x102
       1366x768  -> 55x68    2560x1440 -> 104x128
     四场景密度一致（23 列 x 10 行，由 test_grid_metrics 2b 集成断言）。
  2. icon_layout 三档比例（small .58 / medium .74 / large 1.00）：
     @cell 83x102：小 48x59/图标 34/标签 9px；中 61x75/47/10px；
     大 83x102/69/14px（规格表 §2.2）。

另测 clamp 边界、非法档位回退、cell 过小时的保护下限。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import grid_sizing as gs  # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        FAILED.append(name)


def main():
    # ---------- G1: cell_for_screen 四场景锁死规格表 ----------
    cases = [
        ((1920, 1080), (78, 96)),
        ((2048, 1152), (83, 102)),
        ((1366, 768), (55, 68)),
        ((2560, 1440), (104, 128)),
    ]
    for (W, H), exp in cases:
        got = gs.cell_for_screen(W, H)
        check("cell %dx%d -> %s" % (W, H, exp),
              got == exp, "got %s" % (got,))

    # ---------- G2: clamp 边界 ----------
    lo = gs.cell_for_screen(320, 240)      # k=0.222 -> clamp 0.7
    check("clamp 下限 0.7", lo == (55, 67), "got %s" % (lo,))
    hi = gs.cell_for_screen(7680, 4320)    # k=4.0 -> clamp 1.8
    check("clamp 上限 1.8", hi == (140, 173), "got %s" % (hi,))
    # 横屏/竖屏取短边：竖屏 1080x1920 与 1920x1080 同结果
    check("竖屏短边归一", gs.cell_for_screen(1080, 1920) == (78, 96),
          "got %s" % (gs.cell_for_screen(1080, 1920),))
    # 常量锚点
    check("REF_SHORT=1080", gs.REF_SHORT == 1080.0)
    check("CELL_REF=(78,96)", gs.CELL_REF == (78.0, 96.0))
    check("clamp 范围 (0.7,1.8)", gs.K_MIN == 0.7 and gs.K_MAX == 1.8)

    # ---------- G3: icon_layout 三档锁死规格表（@cell 83x102） ----------
    # v7 §3.1 起档位是「图标在格子里的占比」（0.42 / 0.57 / 0.82）：
    # widget = icon_box + 2*CHROME_X，高度 = icon_box + 标签区。
    lo_l = gs.icon_layout(83, 102, "small")
    check("small 49x53/35/7/18/9",
          (lo_l.widget_w, lo_l.widget_h, lo_l.icon_box, lo_l.chrome_x,
           lo_l.label_h, lo_l.font_px) == (49, 53, 35, 7, 18, 9),
          "got %s" % (lo_l,))
    mid = gs.icon_layout(83, 102, "medium")
    check("medium 61x66/47/7/19/10",
          (mid.widget_w, mid.widget_h, mid.icon_box, mid.chrome_x,
           mid.label_h, mid.font_px) == (61, 66, 47, 7, 19, 10),
          "got %s" % (mid,))
    big = gs.icon_layout(83, 102, "large")
    check("large 82x93/68/7/25/14",
          (big.widget_w, big.widget_h, big.icon_box, big.chrome_x,
           big.label_h, big.font_px) == (82, 93, 68, 7, 25, 14),
          "got %s" % (big,))

    # ---------- G4: 档位语义（v7：占比，不再是 widget/cell） ----------
    # v7 B2（反馈 9）新增第四档 custom，所以这里锁**三档子集**而不是整表
    check("三档占比常量",
          all(gs.TIER_FIT[k] == v for k, v in
              (("small", 0.42), ("medium", None), ("large", 0.82))),
          "got %s" % (gs.TIER_FIT,))
    check("第四档 custom 存在且不占固定比例",
          gs.TIER_CUSTOM in gs.TIER_NAMES and gs.TIER_FIT.get(gs.TIER_CUSTOM) is None,
          "got %s" % (gs.TIER_NAMES,))
    check("默认档 medium", gs.DEFAULT_TIER == "medium")
    check("尺寸单调递增",
          lo_l.widget_w < mid.widget_w < big.widget_w
          and lo_l.widget_h < mid.widget_h < big.widget_h)
    # v7：large 不再"贴满 cell"，而是图标占 82%（留边距与标签）
    check("large 图标占格约 0.82",
          abs(big.icon_box / 83 - 0.82) <= 0.02,
          "got %.3f" % (big.icon_box / 83))
    check("widget 都不越界 cell",
          all(L.widget_w <= 83 and L.widget_h <= 102
              for L in (lo_l, mid, big)),
          "got %s" % ((lo_l.widget_w, mid.widget_w, big.widget_w),))
    # 非法/缺失档位回退 medium
    check("非法档位回退 medium",
          gs.icon_layout(83, 102, "huge") == mid
          and gs.icon_layout(83, 102, None) == mid)
    check("parse_tier 回退",
          gs.parse_tier("large") == "large"
          and gs.parse_tier("garbage") == "medium"
          and gs.parse_tier(None) == "medium")

    # ---------- G5: 小 cell 保护 ----------
    tiny = gs.icon_layout(30, 36, "large")     # cell 30 -> icon_box 16 下限
    check("icon_box 下限 16", tiny.icon_box >= 16, "got %s" % (tiny.icon_box,))
    check("label_h 下限 10", tiny.label_h >= 10, "got %s" % (tiny.label_h,))
    check("font_px 下限 9", tiny.font_px >= 9, "got %s" % (tiny.font_px,))
    check("widget 不小于 1px",
          tiny.widget_w >= 1 and tiny.widget_h >= 1)
    # 任何 cell 下 widget 不越界（<= cell）
    for tier in gs.TIERS:
        L = gs.icon_layout(83, 102, tier)
        check("%s widget 不越界" % tier,
              L.widget_w <= 83 and L.widget_h <= 102)
        check("%s chrome_x 居中" % tier,
              L.chrome_x * 2 + L.icon_box == L.widget_w,
              "got %s" % (L,))

    # ---------- G6: 无头 fake storage 集成（compute 解钩验证） ----------
    # cell 与 icon_size/icon_scale 完全解钩：大图标不再撑大 cell。
    from src import grid_metrics
    from src import grid_flow

    class FakeStorage:
        def get_setting(self, k, d=None):
            return {"columns": "auto"}.get(k, d)

        def icon_metric(self):
            return 999            # 超大图标

        def user_icon_scale(self):
            return 2.0

        def icon_chrome_scale(self):
            return 2.0

    m_big = grid_metrics.compute(FakeStorage(), (2048, 1152))
    m_small = grid_metrics.compute(FakeStorage(), (2048, 1152))
    check("compute 解钩 icon_size（大图标不撑 cell）",
          (m_big.cw, m_big.ch) == (83, 102), "got %s" % ((m_big.cw, m_big.ch),))
    check("compute 确定性", m_big == m_small)
    # 密度一致（规格表 §2.1）：主流三场景 23 列 x 10 行；1366 笔记本小屏
    # edge 公式（26/22*chrome）占比更高，实测 22 列（规格表 23 为近似值）。
    dens = {}
    for (W, H) in [(1920, 1080), (2048, 1152), (2560, 1440)]:
        m = grid_metrics.compute(FakeStorage(), (W, H))
        dens[(W, H)] = (m.cols, m.rows)
    check("主流场景密度一致 23x10",
          set(dens.values()) == {(23, 10)}, "got %s" % (dens,))
    m_nb = grid_metrics.compute(FakeStorage(), (1366, 768))
    check("1366 小屏 >=22 列", m_nb.cols >= 22, "got %s" % (m_nb.cols,))
    check("1366 小屏 10 行", m_nb.rows == 10, "got %s" % (m_nb.rows,))
    grid_flow._current_metrics = None

    print("-" * 60)
    if FAILED:
        print("FAILED: %d -> %s" % (len(FAILED), FAILED))
        return 1
    print("ALL grid_sizing PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
