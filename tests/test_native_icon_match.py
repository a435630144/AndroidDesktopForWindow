# -*- coding: utf-8 -*-
"""图标尺寸对齐系统桌面（2026-10-19 反馈 4）。

诉求："最好能算出电脑原桌面的图标大小，接管后网格模式的默认图标大小
刚好跟原桌面一致。"

契约：
  N1 native=48 / 三档 -> icon_layout().icon_box == 48（档位只改格距）
  N2 cell 由 native 反推：cw = (48+2*CHROME_X)/tier
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

    def icon_chrome_scale(self):
        return 1.0


def main():
    # ---------- N1 三档都等于原生边长 ----------
    for tier in ("small", "medium", "large"):
        cw, ch = grid_sizing.cell_for_native(48, tier)
        lay = grid_sizing.icon_layout(cw, ch, tier)
        check("N1 %s 档 icon_box == 48" % tier, lay.icon_box == 48,
              "cell=%sx%s box=%d" % (cw, ch, lay.icon_box))

    check("N1b 48 与 64 都精确命中",
          all(grid_sizing.icon_layout(*grid_sizing.cell_for_native(n, "medium"),
                                      "medium").icon_box == n for n in (32, 48, 64)),
          "32/48/64")

    # ---------- N2 公式 ----------
    cw, ch = grid_sizing.cell_for_native(48, "medium")
    want_w = int(round((48 + 2 * grid_sizing.CHROME_X)
                       / grid_sizing.TIERS["medium"]))
    check("N2 cell 宽 = (native + 2*CHROME_X)/tier", cw == want_w,
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
