# -*- coding: utf-8 -*-
"""grid_metrics 单元测试：网格自适应（GridMetrics）纯函数契约。

运行：python tests/test_grid_metrics.py   （offscreen，无需显示桌面）

覆盖指导文档_网格与交互_v5.md §1：
  - 公式：cols/rows 按工作区 ÷ 单元格计算，剩余空间均分 -> 四边等距
  - clamp：cols ∈ [2, 24]，rows ∈ [1, 12]（配合 M6 分页）
  - 边界：小屏 / 大图标 / 超大屏
  - columns 手动覆盖（settings 为 int）与 "auto" 默认
  - cell 尺寸与 grid_flow.cell_size 同源（DRY）
  - 任务栏四边（availableGeometry 已反映任务栏，原点须落在工作区内）
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

failures = []


def check(name, cond):
    print("[%s] %s" % ("PASS" if cond else "FAIL", name))
    if not cond:
        failures.append(name)


class _St:
    """最小 fake storage：只提供 grid_metrics/grid_flow 需要的访问器。"""

    def __init__(self, columns="auto", icon_size=72, dpr=1.0, icon_scale=1.0):
        self._s = {"columns": columns, "icon_size": icon_size,
                   "icon_scale": icon_scale}
        self._dpr = dpr

    def get_setting(self, k):
        return self._s.get(k)

    def icon_metric(self):
        return int(round(self._s["icon_size"] * self._dpr * self._s["icon_scale"]))

    def icon_chrome_scale(self):
        return self._dpr * self._s["icon_scale"]


def main():
    from src import grid_metrics, grid_flow

    # ---------- 1. 公式：1920x1040 @100%（工作区，任务栏在底部）----------
    st = _St(dpr=1.0)                       # cell = 96x114
    m = grid_metrics.compute(st, (1920, 1040))
    check("100%: cols=19", m.cols == 19)
    check("100%: rows=8", m.rows == 8)
    check("100%: ox=48（左右均分）", m.ox == 48)
    check("100%: oy=64（上下均分）", m.oy == 64)
    check("100%: cell 与 grid_flow.cell_size 同源",
          (m.cw, m.ch) == grid_flow.cell_size(st))

    # ---------- 2. 公式：1536x810 @125%（工作区）----------
    st = _St(dpr=1.25)                      # cell = 120x142
    m = grid_metrics.compute(st, (1536, 810))
    check("125%: cols=12", m.cols == 12)
    check("125%: rows=5", m.rows == 5)
    check("125%: ox=48（左右均分）", m.ox == 48)
    check("125%: oy=50（上下均分）", m.oy == 50)

    # ---------- 3. 四边等距性质（任意尺寸）----------
    st = _St(dpr=1.0)
    for W, H in ((4000, 3000), (2560, 1400), (1920, 1040), (1536, 810)):
        m = grid_metrics.compute(st, (W, H))
        left, right = m.ox, W - m.ox - m.cols * m.cw
        top, bottom = m.oy, H - m.oy - m.rows * m.ch
        check("%dx%d: 左右等距" % (W, H), left == right)
        check("%dx%d: 上下等距" % (W, H), top == bottom)
        check("%dx%d: 网格不超出工作区" % (W, H),
              m.cols * m.cw + 2 * m.ox <= W and m.rows * m.ch + 2 * m.oy <= H)
        check("%dx%d: 原点非负" % (W, H), m.ox >= 0 and m.oy >= 0)

    # ---------- 4. clamp 上界（超大屏）----------
    m = grid_metrics.compute(st, (8000, 6000))
    check("超大屏: cols<=24", m.cols <= 24)
    check("超大屏: rows<=12", m.rows <= 12)
    check("超大屏: cols==24（触顶）", m.cols == 24)

    # ---------- 5. clamp 下界（小屏）----------
    m = grid_metrics.compute(st, (300, 200))
    check("小屏: cols>=2", m.cols >= 2)
    check("小屏: rows>=1", m.rows >= 1)

    # ---------- 6. 大图标：cell 变大 -> cols 变少 ----------
    st_big = _St(dpr=1.0, icon_size=200)    # cell = 224x242
    m_big = grid_metrics.compute(st_big, (1920, 1040))
    check("大图标: cell=224x242", (m_big.cw, m_big.ch) == (224, 242))
    check("大图标: cols 变小", m_big.cols == (1920 - 52) // 224)

    # ---------- 7. columns 手动覆盖 ----------
    st_manual = _St(dpr=1.0, columns=6)
    m = grid_metrics.compute(st_manual, (1920, 1040))
    check("手动覆盖: cols=6", m.cols == 6)
    check("手动覆盖: rows 仍自动", m.rows == 8)
    check("手动覆盖: 仍四边等距",
          m.ox == 1920 - m.ox - 6 * m.cw)

    # ---------- 8. "auto" 显式值与省略等价 ----------
    check("auto 与省略等价",
          grid_metrics.compute(_St(dpr=1.0, columns="auto"), (1920, 1040)).cols
          == grid_metrics.compute(_St(dpr=1.0), (1920, 1040)).cols)

    # ---------- 9. columns_override 参数优先于 settings ----------
    m = grid_metrics.compute(_St(dpr=1.0, columns=6), (1920, 1040),
                             columns_override=4)
    check("columns_override 参数优先", m.cols == 4)

    # ---------- 10. 非法 columns 值回退自动 ----------
    check("columns='' 回退自动",
          grid_metrics.compute(_St(dpr=1.0, columns=""), (1920, 1040)).cols == 19)
    check("columns=None 回退自动",
          grid_metrics.compute(_St(dpr=1.0, columns=None), (1920, 1040)).cols == 19)

    # ---------- 11. 任务栏四边（availableGeometry 反映任务栏）----------
    # 任务栏左侧 60px：工作区 x 偏移由调用方处理，本函数只关心 (W,H)；
    # 任务栏底部 40px：H 变小，rows 相应减少，原点仍在工作区内
    m = grid_metrics.compute(_St(dpr=1.0), (1920, 1000))
    check("任务栏底部: rows 减少", m.rows == (1000 - 44) // 114)
    check("任务栏底部: 网格不越底界", m.rows * m.ch + m.oy <= 1000)

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL %s PASSED" % "grid_metrics")
    return 0


if __name__ == "__main__":
    sys.exit(main())
