# -*- coding: utf-8 -*-
"""DPI 单一旋钮契约（v10 B2，反馈 2 / 15-b）。

判据由 B1 四格实测反推（`docs/实施计划_v10.md` §B1 实测矩阵）：

  1. **Qt 高 DPI 缩放已经生效**——125% 下 `primaryScreen().geometry()` 是
     1536×864（不是 1920×1080），即「逻辑值 × dpr = 物理值」由 Qt 完成一次。
     所以代码里再乘 dpr 就是**二次放大**（徽标 17 逻辑 → 21 逻辑 → 26 物理
     = ×1.5625）；实测 125% 徽标 26px / cell 105px 正是这个病。
  2. **cell 四格恒 84×91 逻辑**（100% 物理 84、125% 物理 105，恰好一次 dpr）
     ——本来是对的，B2 一个像素都不动。
  3. 因此「单一旋钮」= 用户图标缩放 `icon_scale`；dpr 只由 Qt 用一次。
     `ui_scale()` 语义 = 「chrome 相对逻辑基准的倍数」= 用户缩放，**不含 dpr**。

契约（本文件锁死）：
  D1 `ui_scale()` 与 dpr 无关；D2 `icon_metric()` 与 dpr 无关；
  D3 chrome/cell 比在所有 dpr 下守恒；D4 徽标物理尺寸 ∝ dpr¹（不是 dpr²）；
  D5 用户缩放仍是唯一有效旋钮（chrome 与图标同向、cell 不动）；
  D6 `screen_dpr()` 原子值仍保留（device-pixel 资产如 QPixmap 仍要用它）。

运行：python tests/test_dpi_scale.py   （offscreen，无需显示桌面；判据看退出码）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def main():
    from src import theme, grid_sizing
    from src.storage import Storage

    tmp = Path(tempfile.mkdtemp(prefix="dpi_scale_"))
    st = Storage(path=tmp / "state.json")
    st.set_setting("icon_size", 72)      # 基准（100% 逻辑值）
    st.set_setting("icon_scale", 1.0)
    st.set_setting("icon_match_native", True)

    cell = grid_sizing.cell_from_native(48)
    check("cell 基准 48 -> 84x91（不动）", cell == (84, 91), str(cell))

    orig_dpr = theme._DPR_CACHE
    try:
        # ---------- D1/D2：dpr 不参与逻辑值 ----------
        ratios, metrics, badges, physicals = [], [], [], []
        for dpr in (1.0, 1.25, 1.5, 2.0):
            theme._DPR_CACHE = dpr
            u = st.ui_scale()
            m = st.icon_metric()
            badge = int(round(17 * u))   # BADGE_PX=17（iconwidget._paint_select_badge）
            ratios.append(badge / float(cell[0]))
            metrics.append(m)
            badges.append(badge)
            physicals.append(badge * dpr)
            check("D1 ui_scale 与 dpr 无关 @%.2f" % dpr,
                  abs(u - 1.0) < 1e-9, "u=%.4f" % u)
            check("D2 icon_metric 与 dpr 无关 @%.2f" % dpr,
                  m == 72, "m=%d" % m)

        # ---------- D3：chrome/cell 比守恒 ----------
        spread = max(ratios) - min(ratios)
        check("D3 chrome/cell 比四档守恒（偏差 < 0.5%）",
              spread / max(ratios) < 0.005,
              "比值=%.5f 偏差=%.6f" % (ratios[0], spread / max(ratios)))
        check("D3 比值 = 1.0（与 100% 版式同比例，不再是 1.25）",
              abs(ratios[0] - 17.0 / 84.0) < 1e-9,
              "%.5f vs %.5f" % (ratios[0], 17.0 / 84.0))

        # ---------- D4：徽标物理 ∝ dpr¹ ----------
        # 旧实现 17×dpr 逻辑 × dpr 物理 = dpr²：125% 是 26.6，150% 是 38.25
        expect = [17.0, 21.25, 25.5, 34.0]
        ok_lin = all(abs(p - e) <= 0.5 for p, e in zip(physicals, expect))
        check("D4 徽标物理 17/21/26/34（∝dpr¹，非 dpr²）",
              ok_lin, str([round(p, 2) for p in physicals]))
        check("D4 125% 徽标物理不再是 26.6（旧实现的 dpr² 值）",
              abs(physicals[1] - 26.6) > 1.0, "%.2f" % physicals[1])

        # ---------- D5：用户缩放是唯一旋钮 ----------
        theme._DPR_CACHE = 1.25
        st.set_setting("icon_scale", 1.25)
        check("D5 用户缩放作用于 chrome", abs(st.ui_scale() - 1.25) < 1e-9,
              "u=%.4f" % st.ui_scale())
        check("D5 用户缩放作用于图标", st.icon_metric() == 90,
              "m=%d" % st.icon_metric())
        check("D5 用户缩放不动 cell",
              grid_sizing.cell_from_native(48) == (84, 91))
        check("D5 比值跟随用户缩放（1.25），与 dpr 无关",
              abs(int(round(17 * st.ui_scale())) / 84.0 - 0.25) < 0.01,
              "%.4f" % (int(round(17 * st.ui_scale())) / 84.0))
        st.set_setting("icon_scale", 1.0)

        # ---------- D6：dpr 原子值仍在（device-pixel 资产需要）----------
        theme._DPR_CACHE = 1.75
        check("D6 screen_dpr() 仍返回真实 dpr（QPixmap 等物理资产要用）",
              abs(theme.screen_dpr() - 1.75) < 1e-9,
              "%.2f" % theme.screen_dpr())

        # ---------- D7：网格几何只看逻辑尺寸，dpr 不参与 ----------
        from src import grid_metrics

        class _St:
            def __init__(self, s):
                self._s = s

            def get_setting(self, k, d=None):
                return {"icon_match_native": True,
                        "grid_dims_mode": "auto"}.get(k, d)

            def icon_metric(self):
                return 48

            def ui_scale(self):
                return 1.0

        m = grid_metrics.compute(_St(st), (1920, 1020), native_px=48)
        check("D7 1920x1020@任何dpr -> cols=22 rows=10（cell 不吃 dpr）",
              (m.cols, m.rows, m.cw, m.ch) == (22, 10, 84, 91),
              "%dx%d cell %dx%d" % (m.cols, m.rows, m.cw, m.ch))

        # ---------- D8：旧名转发（向后兼容，语义已归一到 ui_scale）----------
        if hasattr(st, "icon_chrome_scale"):
            theme._DPR_CACHE = 1.25
            check("D8 旧名 icon_chrome_scale() 转发 ui_scale()（同值=1.0）",
                  abs(st.icon_chrome_scale() - st.ui_scale()) < 1e-9,
                  "old=%.4f new=%.4f" % (st.icon_chrome_scale(), st.ui_scale()))
    finally:
        theme._DPR_CACHE = orig_dpr

    print()
    if failures:
        print("FAILED %d / %d" % (len(failures), len(failures) + 0))
        for f in failures:
            print("  -", f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
