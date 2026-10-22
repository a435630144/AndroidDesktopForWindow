# -*- coding: utf-8 -*-
"""图标尺寸对齐系统桌面（2026-10-19 反馈 4）。

诉求："最好能算出电脑原桌面的图标大小，接管后网格模式的默认图标大小
刚好跟原桌面一致。"

契约（v7 §3.1 起档位语义反转，本文件已同步）：
  N1 cell 与档位完全无关；档位只改图标本体（小 35 / 中 48 / 大 69 @cell 84）
  N2 cell = (native + 2*CHROME_X) / FIT_BASE（不含档位）
  N3 icon_match_native=True 时 grid_metrics.compute 用 native 反推
  N4 关闭该项 -> 回到屏幕驱动公式（旧行为不变）
  N5 native_icon_size() 返回合法区间整数（真机读取 explorer 的 IconSize）

运行：python tests/test_native_icon_match.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import grid_metrics, grid_sizing

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


class _St:
    def __init__(self, match=True, tier="medium"):
        self._s = {"icon_match_native": match, "columns": "auto",
                   "icon_tier": tier, "icon_size": 72, "icon_scale": 1.0}

    def get_setting(self, k):
        return self._s.get(k)

    def icon_tier(self):
        return self._s["icon_tier"]

    def icon_metric(self):
        return 72

    def ui_scale(self):
        return 1.0


def main():
    # ---------- N1 v7：cell 与档位完全无关 ----------
    cells = {tier: grid_sizing.cell_for_native(48, tier)
             for tier in ("small", "medium", "large")}
    check("N1 三档 cell 完全一致（档位不再改格距）",
          len(set(cells.values())) == 1,
          "cells=%s" % (cells,))
    check("N1 cell == (84,91)", cells["medium"] == (84, 91),
          "got %s" % (cells["medium"],))
    # 档位只改"图标在格子里的占比"
    boxes = {tier: grid_sizing.icon_layout(*cells[tier], tier).icon_box
             for tier in ("small", "medium", "large")}
    check("N1 小档图标 35px", boxes["small"] == 35, "got %s" % (boxes["small"],))
    check("N1 中档图标 48px（= 原生）", boxes["medium"] == 48,
          "got %s" % (boxes["medium"],))
    check("N1 大档图标 69px", boxes["large"] == 69, "got %s" % (boxes["large"],))

    # 中档 == 原生边长，对多个 native 值都成立（换屏自动跟随）
    bad = []
    for n in (32, 48, 64):
        cw, ch = grid_sizing.cell_from_native(n)
        fit = grid_sizing.fit_for(n, cw, "medium")
        got = grid_sizing.icon_layout(cw, ch, fit).icon_box
        if abs(got - n) > 1:
            bad.append((n, got))
    check("N1b 32/48/64 中档都精确命中原生", not bad, "bad=%s" % (bad,))

    # ---------- N2 公式（v7：除以 FIT_BASE，不含档位） ----------
    cw, ch = grid_sizing.cell_from_native(48)
    want_w = int(round((48 + 2 * grid_sizing.CHROME_X) / grid_sizing.FIT_BASE))
    check("N2 cell 宽 = (native + 2*CHROME_X)/FIT_BASE", cw == want_w,
          "cw=%d want=%d" % (cw, want_w))
    check("N2 cell 高随标签行增加", ch > cw - 2, "ch=%d cw=%d" % (ch, cw))

    # ---------- N3 默认走 native ----------
    m = grid_metrics.compute(_St(match=True), (1920, 1040), native_px=48)
    lay = grid_sizing.icon_layout(m.cw, m.ch, "medium")
    check("N3 开启对齐时网格按原生图标反推", lay.icon_box == 48,
          "cell=%sx%s box=%d" % (m.cw, m.ch, lay.icon_box))
    check("N3b 1920 宽仍是 20+ 列",
          m.cols >= 20, "cols=%d" % m.cols)

    # ---------- N4 关闭 -> 旧公式 ----------
    m2 = grid_metrics.compute(_St(match=False), (1920, 1040), native_px=48)
    cw_old, ch_old = grid_sizing.cell_for_screen(1920, 1040)
    check("N4 关闭后回到屏幕驱动公式",
          (m2.cw, m2.ch) == (cw_old, ch_old),
          "got=%s want=%s" % ((m2.cw, m2.ch), (cw_old, ch_old)))

    # ---------- N5 真机读取 ----------
    try:
        from src import win32_layer
        n = win32_layer.native_icon_size()
        check("N5 native_icon_size 在合法区间", 16 <= n <= 256, "n=%d" % n)
        h, v = win32_layer.native_icon_spacing()
        check("N5b 原生间距可读", h >= 16 and v >= 16, "%sx%s" % (h, v))
    except Exception as exc:
        check("N5 真机读取不崩", False, repr(exc))

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL native_icon_match PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
