# -*- coding: utf-8 -*-
"""v6 批次 C §1.3：网格 / 无界双模式的存储与换算（纯逻辑契约）。

覆盖指导文档_网格与无界双模式_v6.md §1.3：
  M1 layout_mode 归一化（默认 grid；free；非法值回退 grid）
  M2 to_free_coords：fx/fy = 所属页格点（切换瞬间视觉不跳变）+ 幂等
  M3 to_grid_coords：fx/fy 反算吸附 + 清空（网格模式整理不丢）
  M4 entry_pos 双模式：切换瞬间同位；无界页间偏移与网格同语言
  M5 widget_pos：锚定双模式 / 悬浮两模式都是 x/y
  M6 free_pos_cell 页感知：第 2 页条目吸附回第 2 页（不拽回第 0 页）
  M7 page_count 空白页：extra_pages 归一化 + 取大
  M8 free_slot：首个不重叠格点对齐位；全满回退左上角
  M9 切换往返：grid -> free -> grid 布局守恒（占用格集合不变）

运行：python tests/test_dual_mode.py   （offscreen）
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import grid_flow

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


class FakeStorage:
    """get_setting/layout/widgets/columns + cell_size 依赖面（icon_metric/
    ui_scale）——与 grid_metrics.compute 的依赖面一致。"""

    def __init__(self, layout=(), widgets=(), settings=None):
        self.layout = list(layout)
        self.widgets = list(widgets)
        self._settings = {"columns": "auto", "layout_mode": "grid",
                          "extra_pages": []}
        for k, v in (settings or {}).items():
            self._settings[k] = v

    def get_setting(self, key):
        return self._settings.get(key)

    def set_setting(self, key, value):
        self._settings[key] = value

    @property
    def columns(self):
        m = grid_flow.current_metrics()
        if m is not None:
            return m.cols
        return 10

    def icon_metric(self):
        return 48

    def ui_scale(self):
        return 1.0


def entry(eid, col, row):
    return {"id": eid, "type": "app", "col": col, "row": row}


def widget_entry(wid, col, row, cs=None, rs=None, anchored=True):
    e = {"id": wid, "type": "clock", "col": col, "row": row,
         "anchored": anchored, "x": 0, "y": 0}
    if cs is not None:
        e["colspan"], e["rowspan"] = cs, rs
    return e


def main():
    # 固定网格几何：1920x1040 -> cell 由 grid_sizing 公式推导
    st = FakeStorage()
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)
    cw, ch = grid_flow.cell_size(st)
    ox, oy = grid_flow.origin()
    rpp = grid_flow.rows_per_page()
    canvas_h = grid_flow.page_canvas_h(st)

    # ---------- M1：layout_mode 归一化 ----------
    check("M1 默认 grid", grid_flow.layout_mode(FakeStorage()) == "grid")
    check("M1 free 生效",
          grid_flow.layout_mode(FakeStorage(settings={"layout_mode": "free"})) == "free")
    check("M1 非法值回退 grid",
          grid_flow.layout_mode(FakeStorage(settings={"layout_mode": "鬼东西"})) == "grid")
    check("M1 大小写/空格容忍",
          grid_flow.layout_mode(FakeStorage(settings={"layout_mode": " FREE "})) == "free")

    # ---------- M2：to_free_coords 生成式 + 幂等 ----------
    st2 = FakeStorage(layout=[entry("a", 0, 0), entry("b", 1, 0),
                              entry("c", 0, rpp + 1)],   # c 在第 1 页
                      widgets=[widget_entry("clk", 2, 0)])
    st2._settings["layout_mode"] = "free"
    n = grid_flow.to_free_coords(st2)
    check("M2 四个对象都生成 fx/fy（3 条目 + 1 锚定组件）", n == 4, "n=%d" % n)
    # 2026-10-19 反馈 1：生成式含 icon 居中留白（widget 小于 cell）
    dx, dy = grid_flow.icon_center_offset(st2)
    a = st2.layout[0]
    check("M2 第 0 页条目 fx/fy = 所属页格点 + 居中留白",
          (a["fx"], a["fy"]) == (ox + dx, oy + dy), "%s" % ((a["fx"], a["fy"]),))
    c = st2.layout[2]
    check("M2 第 1 页条目 fy = 页内局部行（不是全局行像素）",
          (c["fx"], c["fy"]) == (ox + dx, oy + 1 * ch + dy),
          "%s" % ((c["fx"], c["fy"]),))
    check("M2 幂等：第二次不重算", grid_flow.to_free_coords(st2) == 0)

    # ---------- M3：to_grid_coords 只补缺、不换算（v7 B2 / 反馈 13） ----------
    # 旧契约是"按 fx/fy 反算吸附 + 清空 fx/fy"，两个动作都是破坏性的：
    # 用户无界摆好的位置被销毁，整理好的 col/row 被吸附结果覆盖。
    st3 = FakeStorage(layout=[{"id": "a", "col": 0, "row": 0,
                               "fx": ox + 2 * cw + cw // 3, "fy": oy + ch + ch // 3},
                              {"id": "b", "col": 5, "row": 5,
                               "fx": ox + cw, "fy": oy + 2 * ch}],
                      settings={"layout_mode": "free"})
    n3 = grid_flow.to_grid_coords(st3)
    a3, b3 = st3.layout
    check("M3 已有 col/row 不被 fx/fy 反算覆盖",
          (a3["col"], a3["row"]) == (0, 0) and (b3["col"], b3["row"]) == (5, 5),
          "%s / %s" % ((a3["col"], a3["row"]), (b3["col"], b3["row"])))
    check("M3 fx/fy 保留（无界摆位不丢）",
          (a3.get("fx"), a3.get("fy"))
          == (ox + 2 * cw + cw // 3, oy + ch + ch // 3),
          "%s" % ((a3.get("fx"), a3.get("fy")),))
    check("M3 正常切换补算计数为 0", n3 == 0, "n=%d" % n3)
    # 只对"根本没有 col/row"的条目补算（并发新增 / 极旧数据）
    st3b = FakeStorage(layout=[{"id": "c", "fx": ox + 2 * cw, "fy": oy + ch}],
                       settings={"layout_mode": "free"})
    n3b = grid_flow.to_grid_coords(st3b)
    c3 = st3b.layout[0]
    check("M3b 缺 col/row 时按 fx/fy 补算一次",
          (c3["col"], c3["row"]) == (2, 1) and n3b == 1,
          "%s n=%d" % ((c3["col"], c3["row"]), n3b))

    # ---------- M4：entry_pos 双模式 ----------
    st4 = FakeStorage(layout=[entry("a", 1, 0)])
    grid_flow.set_page(0)
    pos_grid = grid_flow.entry_pos(st4, st4.layout[0])
    dx4, dy4 = grid_flow.icon_center_offset(st4)
    check("M4 网格模式 = cell_pos + 居中留白",
          pos_grid == (ox + cw + dx4, oy + dy4), "%s" % (pos_grid,))
    st4._settings["layout_mode"] = "free"
    grid_flow.to_free_coords(st4)
    pos_free = grid_flow.entry_pos(st4, st4.layout[0])
    check("M4 切换瞬间视觉位置不变（无跳变）", pos_free == pos_grid,
          "%s vs %s" % (pos_free, pos_grid))
    # 无界页间偏移：第 1 页条目在当前页(0)视角应右移一格画布（默认左右翻页）
    st4b = FakeStorage(layout=[entry("z", 0, rpp)],  # 第 1 页
                       settings={"layout_mode": "free"})
    grid_flow.to_free_coords(st4b)
    pz = grid_flow.entry_pos(st4b, st4b.layout[0])
    canvas_w4 = grid_flow.page_canvas_w(st4b)
    check("M4 无界页间偏移 = 画布宽（与网格同一页几何）",
          pz == (ox + canvas_w4 + dx4, oy + dy4), "%s" % (pz,))

    # ---------- M5：widget_pos ----------
    st5 = FakeStorage(widgets=[widget_entry("clk", 2, 0),
                               widget_entry("note", 0, 0, anchored=False)])
    st5.widgets[1]["x"], st5.widgets[1]["y"] = 400, 300
    pw = grid_flow.widget_pos(st5, st5.widgets[0])
    check("M5 网格锚定 = cell_pos", pw == (ox + 2 * cw, oy), "%s" % (pw,))
    pn = grid_flow.widget_pos(st5, st5.widgets[1])
    check("M5 悬浮两种模式都是 x/y", pn == (400, 300), "%s" % (pn,))
    st5._settings["layout_mode"] = "free"
    grid_flow.to_free_coords(st5)
    pw2 = grid_flow.widget_pos(st5, st5.widgets[0])
    check("M5 无界锚定切换瞬间同位", pw2 == pw, "%s vs %s" % (pw2, pw))
    check("M5 无界悬浮不变", grid_flow.widget_pos(st5, st5.widgets[1]) == (400, 300))

    # ---------- M6：free_pos_cell 页感知 ----------
    cell = grid_flow.free_pos_cell(st5, ox + cw, oy + ch, page=2)
    check("M6 第 2 页坐标吸附回第 2 页全局行",
          cell == (1, 2 * rpp + 1), "%s" % (cell,))

    # ---------- M7：page_count 空白页 ----------
    st7 = FakeStorage(layout=[entry("a", 0, 0)])
    base = grid_flow.page_count(st7)
    check("M7 无空白页时 = 数据页数", base == 1)
    st7._settings["extra_pages"] = [3, 1, 3, -2, "x", 5]
    check("M7 空白页取大（归一化排序去重）",
          grid_flow.page_count(st7) == 6 and
          grid_flow.extra_pages(st7) == [1, 3, 5],
          "%s" % (grid_flow.extra_pages(st7),))

    # ---------- M8：free_slot ----------
    st8 = FakeStorage(layout=[{"id": "a", "col": 0, "row": 0,
                               "fx": ox, "fy": oy}],
                      settings={"layout_mode": "free"})
    slot = grid_flow.free_slot(st8, 0, cw, ch)
    check("M8 首个不重叠位跳过已占的 (ox,oy)", slot == (ox + cw, oy),
          "%s" % (slot,))
    # 全满：一行占满 -> 下一行
    full = [{"id": "e%d" % i, "fx": ox + i * cw, "fy": oy}
            for i in range(st8.columns)]
    st8.layout.extend(full)
    slot2 = grid_flow.free_slot(st8, 0, cw, ch)
    check("M8 第一行满 -> 第二行行首", slot2 == (ox, oy + ch), "%s" % (slot2,))

    # ---------- M9：切换往返守恒（v7 B2 / 反馈 13） ----------
    # 新契约：无界摆位**不回写**网格坐标，所以往返后 col/row 必须与
    # 出发前**逐条相等**（旧契约断言的是"吸附成新格"，那正是重叠的来源）。
    st9 = FakeStorage(layout=[entry("a", 0, 0), entry("b", 1, 0), entry("c", 2, 0)])
    before = {(e["id"], e["col"], e["row"]) for e in st9.layout}
    st9._settings["layout_mode"] = "free"
    grid_flow.to_free_coords(st9)
    # 无界模式把 a 拖到 (3,1) 格附近
    st9.layout[0]["fx"], st9.layout[0]["fy"] = ox + 3 * cw, oy + ch
    grid_flow.to_grid_coords(st9)
    after = {(e["id"], e["col"], e["row"]) for e in st9.layout}
    check("M9 往返后 col/row 逐条等于出发前（不叠不丢）",
          after == before, "%s vs %s" % (after, before))
    check("M9b 往返后 a 的无界摆位仍保留",
          (st9.layout[0].get("fx"), st9.layout[0].get("fy"))
          == (ox + 3 * cw, oy + ch),
          "%s" % ((st9.layout[0].get("fx"), st9.layout[0].get("fy")),))
    # 再切一次无界：仍用用户摆的 fx/fy，不被格点重新生成
    st9._settings["layout_mode"] = "grid"
    grid_flow.to_free_coords(st9)      # 幂等：已有 fx/fy 一个都不重算
    st9._settings["layout_mode"] = "free"
    check("M9c 再切无界沿用用户摆位",
          (st9.layout[0].get("fx"), st9.layout[0].get("fy"))
          == (ox + 3 * cw, oy + ch),
          "%s" % ((st9.layout[0].get("fx"), st9.layout[0].get("fy")),))

    grid_flow.set_page(0)
    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL dual_mode PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
