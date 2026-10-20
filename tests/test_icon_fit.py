# -*- coding: utf-8 -*-
"""B1 尺寸地基：档位只改图标占比（v7 §3.1，验收 A1~A5）。

病根：v6 的 `cell_for_native(native_px, tier)` 把档位除进了 cell —— 切档位
= 改格距 = 改列数行数。v7 拆成两层：

  层一 cell  = 只由 native_px 决定（`cell_from_native`，不含档位）
  层二 icon  = `icon_box = round(cell_w * icon_fit)`

本文件锁死"两层互不影响"，以及"中档恰好等于原生边长"这条回归锁。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import grid_sizing as gs  # noqa: E402
from src.storage import tier_for_fit  # noqa: E402

FAILED = []
NATIVE = 48


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra), flush=True)
    if not cond:
        FAILED.append(name)


def main():
    c1 = gs.cell_from_native(NATIVE)

    # ---------- A1：cell 与 fit 完全无关 ----------
    check("A1 cell_from_native 可复现", gs.cell_from_native(NATIVE) == c1,
          "got %s" % (c1,))
    check("A1 cell_from_native(48) == (84,91)", c1 == (84, 91),
          "got %s" % (c1,))
    check("A1 cell_for_native 不再随档位变",
          gs.cell_for_native(48, "small") == gs.cell_for_native(48, "large")
          == c1,
          "small=%s large=%s" % (gs.cell_for_native(48, "small"),
                                 gs.cell_for_native(48, "large")))
    check("A1 cell_for_native 省略档位也可调用",
          gs.cell_for_native(48) == c1, "got %s" % (gs.cell_for_native(48),))

    # ---------- A2：icon_box / cell_w ≈ fit ----------
    bad = []
    for fit in (0.42, 0.57, 0.82):
        lay = gs.icon_layout(c1[0], c1[1], fit)
        ratio = lay.icon_box / c1[0]
        if abs(ratio - fit) > 0.02:
            bad.append((fit, round(ratio, 4)))
    check("A2 icon_box/cell_w ≈ fit ±0.02", not bad, "bad=%s" % (bad,))
    check("A2 小档 35px", gs.icon_layout(84, 91, 0.42).icon_box == 35,
          "got %s" % (gs.icon_layout(84, 91, 0.42).icon_box,))
    check("A2 大档 69px", gs.icon_layout(84, 91, 0.82).icon_box == 69,
          "got %s" % (gs.icon_layout(84, 91, 0.82).icon_box,))
    check("A2 icon_box 随 fit 单调递增",
          gs.icon_layout(84, 91, 0.42).icon_box
          < gs.icon_layout(84, 91, 0.57).icon_box
          < gs.icon_layout(84, 91, 0.82).icon_box)

    # ---------- A3：改档位不改 cell（同一 cell 输入下输出 cell 恒定）----------
    # cell 由 solve_dims/current_metrics 给出，本函数不接收档位；此断言锁
    # "fit 不产生任何回写 cell 的副作用"（纯函数性）。
    snap = (c1, gs.cell_from_native(NATIVE), gs.cell_for_native(48, "small"))
    for fit in (0.42, 0.57, 0.82, 0.65):
        gs.icon_layout(c1[0], c1[1], fit)
    check("A3 icon_layout 无副作用（cell 快照不变）",
          snap == (c1, gs.cell_from_native(NATIVE),
                   gs.cell_for_native(48, "small")),
          "")

    # ---------- A4：中档 == 原生（±1px）——回归锁 ----------
    mid = gs.icon_layout(c1[0], c1[1], NATIVE / c1[0])
    check("A4 中档 fit 解算后 icon_box == 48", abs(mid.icon_box - NATIVE) <= 1,
          "got %s" % (mid.icon_box,))
    mid_tier = gs.icon_layout(84, 91, "medium")
    check("A4 档位串 medium 的 fallback 也是 48",
          abs(mid_tier.icon_box - NATIVE) <= 1, "got %s" % (mid_tier.icon_box,))
    check("A4 fit_for 解算中档",
          abs(gs.fit_for(NATIVE, c1[0], "medium") - NATIVE / c1[0]) < 1e-6,
          "got %s" % (gs.fit_for(NATIVE, c1[0], "medium"),))

    # ---------- A5：档位判定（存储侧纯函数）----------
    check("A5 tier_for_fit(0.42) == small", tier_for_fit(0.42) == "small",
          "got %s" % (tier_for_fit(0.42),))
    check("A5 tier_for_fit(48/84) == medium",
          tier_for_fit(48 / 84) == "medium", "got %s" % (tier_for_fit(48 / 84),))
    check("A5 tier_for_fit(0.82) == large", tier_for_fit(0.82) == "large",
          "got %s" % (tier_for_fit(0.82),))
    check("A5 tier_for_fit(0.65) 自定义 -> None", tier_for_fit(0.65) is None,
          "got %s" % (tier_for_fit(0.65),))
    check("A5 tier_for_fit(None) -> None", tier_for_fit(None) is None)

    # ---------- A6：parse_fit / 夹紧 ----------
    check("A6 parse_fit('medium') is None", gs.parse_fit("medium") is None)
    check("A6 parse_fit('small') == 0.42", gs.parse_fit("small") == 0.42,
          "got %s" % (gs.parse_fit("small"),))
    check("A6 parse_fit 夹紧上限 0.90", gs.parse_fit(5.0) == 0.90,
          "got %s" % (gs.parse_fit(5.0),))
    check("A6 parse_fit 夹紧下限 0.30", gs.parse_fit(0.01) == 0.30,
          "got %s" % (gs.parse_fit(0.01),))
    check("A6 非法档位串回退 medium(None)", gs.parse_fit("garbage") is None,
          "got %s" % (gs.parse_fit("garbage"),))

    # ---------- A7：三档比例表（v7 B2 起另有 custom 档，故锁子集） ----------
    check("A7 TIER_FIT 三档 = 0.42/None/0.82",
          all(gs.TIER_FIT[k] == v for k, v in
              (("small", 0.42), ("medium", None), ("large", 0.82))),
          "got %s" % (gs.TIER_FIT,))
    check("A7 TIER_FIT_FALLBACK 三档 = 0.42/0.57/0.82",
          all(gs.TIER_FIT_FALLBACK[k] == v for k, v in
              (("small", 0.42), ("medium", 0.57), ("large", 0.82))),
          "got %s" % (gs.TIER_FIT_FALLBACK,))
    check("A7b custom 档：parse_tier 保留、parse_fit 走兜底",
          gs.parse_tier("custom") == "custom"
          and gs.parse_fit("custom") is None,
          "tier=%s fit=%r" % (gs.parse_tier("custom"), gs.parse_fit("custom")))
    check("A7 FIT_BASE = 0.74（沿用 v6 中档，升级不跳格）",
          gs.FIT_BASE == 0.74, "got %s" % (gs.FIT_BASE,))


crashed = None
try:
    main()
except Exception:                      # 坑 #38
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
    print("ALL icon_fit PASSED")
    sys.stdout.flush()
    os._exit(0)
