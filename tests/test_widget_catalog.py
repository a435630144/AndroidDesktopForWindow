# -*- coding: utf-8 -*-
"""widget_catalog / widget_span 单元测试：组件跨度一等公民（指导文档 §3.2，M3）。

运行：python tests/test_widget_catalog.py   （offscreen，无需显示桌面）

覆盖：
  - WIDGET_CATALOG：clock 2×2（D3）；v6 §6.1 起 notes 2×2、panel 3×4
  - widget_span 从 catalog 读，不再 round 像素（银行家舍入坑根除）
  - entry 已存 colspan/rowspan 优先（用户尺寸切换的持久化）
  - 非 catalog 类型回退 legacy 像素换算
  - pixel_size = span × cell 精确推导（碰撞 = 视觉边界）
  - widget_cells 按 span 精确展开（时钟 2×2 = 4 格，旧 round 只有 2 格）
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


class _St:
    """duck-typing 假 storage（对齐 test_grid_flow 的风格）。"""

    def __init__(self, cols=19, size=72, scale=1.25, widgets=None):
        self._s = {"columns": cols, "icon_size": size, "icon_scale": scale}
        self.widgets = widgets if widgets is not None else []

    def get_setting(self, k):
        return self._s.get(k)

    def icon_metric(self):
        return int(self._s["icon_size"] * 1.25)

    def icon_chrome_scale(self):
        return 1.25

    @property
    def columns(self):
        return self._s["columns"]


def main():
    from src import grid_flow
    from src import widget_catalog  # noqa: F401  （Red：模块不存在即失败）

    st = _St()
    cw, ch = grid_flow.cell_size(st)
    check("单元格尺寸（125% DPI 下 120x142）", (cw, ch) == (120, 142),
          "cell=%s" % ((cw, ch),))

    # ---------- 1. catalog 内容 ----------
    check("catalog: clock 默认跨度 2×2（D3）",
          widget_catalog.default_span("clock") == (2, 2))
    check("catalog: clock 可用尺寸列表 = [(2,2)]",
          widget_catalog.spans("clock") == [(2, 2)])
    # v6 §6.1（反馈 7b 前半）：notes 2×2、panel 3×4 登记入网格
    check("catalog: notes 默认跨度 2×2（v6 §6.1）",
          widget_catalog.default_span("notes") == (2, 2))
    check("catalog: panel 默认跨度 3×4（v6 §6.1）",
          widget_catalog.default_span("panel") == (3, 4))
    check("catalog: 完全未知类型无跨度", widget_catalog.spans("weather") == [])
    check("catalog: default_span 对未知类型返回 None",
          widget_catalog.default_span("weather") is None)

    # ---------- 2. widget_span 从 catalog 读（不再 round 像素） ----------
    clock = {"id": "clock", "type": "clock", "w": 300, "h": 160,
             "anchored": True, "col": 0, "row": 0}
    check("widget_span(clock) == (2,2)（catalog 一等公民）",
          grid_flow.widget_span(st, clock) == (2, 2))
    # 旧实现的银行家舍入：round(300/120)=2、round(160/142)=1 -> (2,1)
    check("widget_span(clock) != 旧 round 像素结果 (2,1)",
          grid_flow.widget_span(st, clock) != (2, 1))

    # ---------- 3. entry 已存跨度优先（尺寸切换持久化） ----------
    clock_4x2 = dict(clock, colspan=4, rowspan=2)
    check("widget_span 读 entry 已存 colspan/rowspan（4×2）",
          grid_flow.widget_span(st, clock_4x2) == (4, 2))

    # ---------- 4. 非 catalog 类型回退 legacy 像素换算 ----------
    weather = {"id": "w", "type": "weather", "w": 300, "h": 160,
               "anchored": True, "col": 0, "row": 0}
    check("widget_span(weather) 回退 legacy 像素换算 (2,1)",
          grid_flow.widget_span(st, weather) == (2, 1))

    # ---------- 5. pixel_size = span × cell 精确推导 ----------
    check("pixel_size(clock) == 2×cell（240×284 @125%）",
          widget_catalog.pixel_size(st, "clock") == (2 * cw, 2 * ch),
          "%s" % (widget_catalog.pixel_size(st, "clock"),))
    check("pixel_size(clock, span=(4,2)) == 4×2 cell",
          widget_catalog.pixel_size(st, "clock", (4, 2)) == (4 * cw, 2 * ch))
    check("pixel_size(notes) == 2×2 cell（v6 §6.1 登记后不再 None）",
          widget_catalog.pixel_size(st, "notes") == (2 * cw, 2 * ch))
    check("pixel_size(panel) == 3×4 cell",
          widget_catalog.pixel_size(st, "panel") == (3 * cw, 4 * ch))
    check("pixel_size(未知类型) 返回 None",
          widget_catalog.pixel_size(st, "weather") is None)

    # ---------- 6. widget_cells 按 span 精确展开 ----------
    st2 = _St(widgets=[clock])
    cells = grid_flow.widget_cells(st2)
    check("widget_cells(clock 2×2 @ (0,0)) == 4 格精确展开",
          cells == {(0, 0), (1, 0), (0, 1), (1, 1)}, "%s" % sorted(cells))
    st3 = _St(widgets=[dict(clock, col=3, row=2)])
    cells3 = grid_flow.widget_cells(st3)
    check("widget_cells(clock 2×2 @ (3,2)) 覆盖格正确",
          cells3 == {(3, 2), (4, 2), (3, 3), (4, 3)}, "%s" % sorted(cells3))
    st4 = _St(widgets=[dict(clock, hidden=True)])
    check("hidden 组件不占位", grid_flow.widget_cells(st4) == set())
    st5 = _St(widgets=[dict(clock, anchored=False)])
    check("非锚定组件不占位", grid_flow.widget_cells(st5) == set())

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL %s PASSED" % "widget_catalog")
    return 0


if __name__ == "__main__":
    sys.exit(main())
