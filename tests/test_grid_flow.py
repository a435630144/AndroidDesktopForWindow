# -*- coding: utf-8 -*-
"""grid_flow 单元测试：图标网格实时让位（Live Reflow）的纯逻辑契约。

运行：python tests/test_grid_flow.py   （offscreen，无需显示桌面）

覆盖 design.md 2.2 的全部性质：
  - 占用格集合守恒（永不重叠 / 永不丢图标 / 空位保留）
  - 阅读序插入规则（占用格→插到占用者前；空格→按早于目标格的占用数插入）
  - 往返一致性、越界夹紧、随机压力无重叠
  - 网格吸附 snap_point 对齐与越界保护
"""
import os
import random
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

failures = []


def check(name, cond):
    print("[%s] %s" % ("PASS" if cond else "FAIL", name))
    if not cond:
        failures.append(name)


def mk(ids_cols_rows):
    """ids_cols_rows: [(id, col, row), ...] -> entries"""
    return [{"id": i, "col": c, "row": r, "type": "app"} for i, c, r in ids_cols_rows]


def cells_of(entries):
    return sorted((int(e["col"]), int(e["row"])) for e in entries)


def order_of(entries):
    return [e["id"] for e in sorted(entries, key=lambda e: (int(e["row"]), int(e["col"])))]


def main():
    from src import grid_flow

    COLS = 8

    # ---------- 1. 占用格集合守恒 ----------
    entries = mk([("a", 0, 0), ("b", 1, 0), ("c", 2, 0), ("d", 0, 1), ("e", 3, 1)])
    before = cells_of(entries)
    grid_flow.apply_order(entries, grid_flow.reflow_order(entries, COLS, "a", (2, 1)))
    check("reflow 保持占用格集合不变", cells_of(entries) == before)
    check("reflow 不丢图标", len(entries) == 5)

    # ---------- 2. 拖到占用格：dragged 落上目标格，占用者后移 ----------
    entries = mk([("a", 0, 0), ("b", 1, 0), ("c", 2, 0)])
    order = grid_flow.reflow_order(entries, COLS, "a", (2, 0))  # c 的格
    check("拖到占用格：顺序为 b,c,a", order == ["b", "c", "a"])
    grid_flow.apply_order(entries, order)
    by_id = {e["id"]: (e["col"], e["row"]) for e in entries}
    check("dragged 落上目标格 (2,0)", by_id["a"] == (2, 0))
    check("占用者 c 后移到 (1,0)", by_id["c"] == (1, 0))
    check("b 不动仍在 (0,0)", by_id["b"] == (0, 0))

    entries = mk([("a", 0, 0), ("b", 1, 0), ("c", 2, 0)])
    order = grid_flow.reflow_order(entries, COLS, "c", (0, 0))  # a 的格
    check("尾部拖到队首：顺序为 c,a,b", order == ["c", "a", "b"])
    grid_flow.apply_order(entries, order)
    by_id = {e["id"]: (e["col"], e["row"]) for e in entries}
    check("c 落上 (0,0)，a/b 整体后移", by_id["c"] == (0, 0) and by_id["a"] == (1, 0)
          and by_id["b"] == (2, 0))

    # ---------- 3. 拖到末尾空格：追加队尾 ----------
    entries = mk([("a", 0, 0), ("b", 1, 0)])
    order = grid_flow.reflow_order(entries, COLS, "a", (2, 0))
    check("拖到右侧空格追加队尾", order == ["b", "a"])

    # ---------- 4. 往返一致 ----------
    entries = mk([("a", 0, 0), ("b", 1, 0), ("c", 2, 0), ("d", 3, 0)])
    orig = order_of(entries)
    grid_flow.apply_order(entries, grid_flow.reflow_order(entries, COLS, "d", (0, 0)))
    check("d 移到队首", order_of(entries) == ["d", "a", "b", "c"])
    grid_flow.apply_order(entries, grid_flow.reflow_order(entries, COLS, "d", (3, 0)))
    check("d 移回原位恢复原序", order_of(entries) == orig)

    # ---------- 5. 往前拖：后者整体后移一格 ----------
    entries = mk([("a", 0, 0), ("b", 1, 0), ("c", 2, 0), ("d", 3, 0)])
    grid_flow.apply_order(entries, grid_flow.reflow_order(entries, COLS, "d", (1, 0)))
    check("d 前插到 b 前，bc 后移", order_of(entries) == ["a", "d", "b", "c"])
    by_id = {e["id"]: (e["col"], e["row"]) for e in entries}
    check("d 落到 (1,0)", by_id["d"] == (1, 0))
    check("a 仍在 (0,0)", by_id["a"] == (0, 0))
    check("b/c 后移占到 d 让出的格", by_id["b"] == (2, 0) and by_id["c"] == (3, 0))

    # ---------- 6. 原地拖动是恒等 ----------
    entries = mk([("a", 0, 0), ("b", 1, 0), ("c", 2, 0)])
    order = grid_flow.reflow_order(entries, COLS, "b", (1, 0))
    check("原地拖动顺序不变", order == ["a", "b", "c"])

    # ---------- 7. 越界夹紧 ----------
    entries = mk([("a", 0, 0), ("b", 1, 0)])
    order = grid_flow.reflow_order(entries, COLS, "a", (99, 0))
    check("col 越界夹紧到最后一列", order == ["b", "a"])
    entries = mk([("a", 0, 0), ("b", 1, 0)])
    order = grid_flow.reflow_order(entries, COLS, "a", (-5, 0))
    check("col 负值夹紧到 0", order == ["a", "b"])

    # ---------- 8. 单图标 ----------
    entries = mk([("only", 3, 2)])
    order = grid_flow.reflow_order(entries, COLS, "only", (5, 7))
    check("单图标拖到空格", order == ["only"])
    grid_flow.apply_order(entries, order)
    check("单图标保持原位（占用格集合只有一个）", cells_of(entries) == [(3, 2)])

    # ---------- 9. 不存在的 dragged ----------
    entries = mk([("a", 0, 0)])
    check("dragged 不存在返回 None",
          grid_flow.reflow_order(entries, COLS, "zzz", (1, 0)) is None)

    # ---------- 10. 随机压力：无重叠、无丢失 ----------
    rng = random.Random(20261018)
    ok = True
    for _ in range(200):
        n = rng.randint(1, 12)
        # 先造不重复的占用格集合（真实布局不会两图标占同一格）
        pool = [(c, r) for r in range(4) for c in range(COLS)]
        picked = rng.sample(pool, n)
        entries = mk([("i%d" % k, c, r) for k, (c, r) in enumerate(picked)])
        seen = set(picked)
        if len(entries) != len(seen):
            ok = False
        did = rng.choice(entries)["id"]
        tgt = (rng.randrange(COLS), rng.randrange(4))
        order = grid_flow.reflow_order(entries, COLS, did, tgt)
        if order is None or sorted(order) != sorted(e["id"] for e in entries):
            ok = False
            continue
        grid_flow.apply_order(entries, order)
        if cells_of(entries) != sorted(seen):
            ok = False
        if len({(e["col"], e["row"]) for e in entries}) != len(entries):
            ok = False
    check("200 轮随机拖动：无重叠 / 无丢失 / 占用格守恒", ok)

    # ---------- 11. 阅读序稳定 ----------
    entries = mk([("a", 2, 1), ("b", 0, 0), ("c", 1, 1)])
    check("reading_order 按 (row,col)",
          [e["id"] for e in grid_flow.reading_order(entries, COLS)] == ["b", "c", "a"])

    # ---------- 12. snap_point 对齐网格 ----------
    class _St:
        def __init__(self, cols=8, size=72, scale=1.0):
            self._s = {"columns": cols, "icon_size": size, "icon_scale": scale}

        def get_setting(self, k):
            return self._s.get(k)

        @property
        def columns(self):
            return self._s["columns"]

        def icon_metric(self):
            return int(self._s["icon_size"] * 1.25)

        def ui_scale(self):
            return 1.25

    st = _St()
    ox, oy = grid_flow.origin()
    cw, ch = grid_flow.cell_size(st)
    # 目标格 (2,1) 的左上角附近（偏移 1/3 格）应吸附到该格原点
    x, y = grid_flow.snap_point(st, ox + cw * 2 + cw // 3, oy + ch * 1 + ch // 3, (1920, 1080))
    check("snap_point 对齐列", x == ox + cw * 2)
    check("snap_point 对齐行", y == oy + ch * 1)
    # 格内任意位置（含 75%）仍判本格（v6 floor 语义：指针所在格）；
    # 越过格边（下一格 1/3 处）才到下一列
    x2, _ = grid_flow.snap_point(st, ox + cw * 2 + cw * 0.75, oy, (1920, 1080))
    check("snap_point 格内 75% 仍判本列", x2 == ox + cw * 2)
    x2b, _ = grid_flow.snap_point(st, ox + cw * 3 + cw // 3, oy, (1920, 1080))
    check("snap_point 越过格边到下一列", x2b == ox + cw * 3)
    # 越界保护
    x3, y3 = grid_flow.snap_point(st, -5000, -5000, (1920, 1080))
    check("snap_point 左上不越界", x3 >= 0 and y3 >= 0)
    x4, y4 = grid_flow.snap_point(st, 99999, 99999, (1920, 1080))
    check("snap_point 右下不越界", x4 <= 1920 and y4 <= 1080)

    # ---------- 13. reflow_moves：位移清单（指导文档 §2.2，iOS 局部让位） ----------
    # 语义与 reflow_order 的本质区别：dragged 精确落到 target（含空格），
    # 只有新旧位置之间（阅读序）的图标滑动一格，其余一律不动。
    def apply_moves(entries, moves):
        by_id = {e["id"]: e for e in entries}
        for eid, cell in moves.items():
            if eid in by_id:
                by_id[eid]["col"], by_id[eid]["row"] = cell

    # 13.1 指导文档验证例 1：行内 A B C D（全占），拖 A 到 (3,0)（D 占）
    entries = mk([("A", 0, 0), ("B", 1, 0), ("C", 2, 0), ("D", 3, 0)])
    moves = grid_flow.reflow_moves(entries, COLS, "A", (3, 0))
    check("例1 后移占用：位移集合 = B/C/D/A",
          moves == {"B": (0, 0), "C": (1, 0), "D": (2, 0), "A": (3, 0)})
    apply_moves(entries, moves)
    check("例1 落点：A 精确占 (3,0)，B/C/D 依次前移",
          [(e["id"], e["col"], e["row"])
           for e in sorted(entries, key=lambda e: (e["row"], e["col"]))]
          == [("B", 0, 0), ("C", 1, 0), ("D", 2, 0), ("A", 3, 0)])

    # 13.2 指导文档验证例 2：稀疏 A B C _ E，拖 A 到空格 (3,0)
    entries = mk([("A", 0, 0), ("B", 1, 0), ("C", 2, 0), ("E", 4, 0)])
    moves = grid_flow.reflow_moves(entries, COLS, "A", (3, 0))
    check("例2 后移空格：只有 B/C 前移，A 精确落空格",
          moves == {"B": (0, 0), "C": (1, 0), "A": (3, 0)})
    apply_moves(entries, moves)
    by_id = {e["id"]: (e["col"], e["row"]) for e in entries}
    occupied = set(by_id.values())
    check("例2 E 不动仍在 (4,0)", by_id["E"] == (4, 0))
    check("例2 空位从 (3,0) 移到 (2,0)（与 iOS 一致）",
          (3, 0) in occupied and (2, 0) not in occupied)

    # 13.3 前移占用：A B C D，拖 D 到 (1,0)（B 占）
    entries = mk([("A", 0, 0), ("B", 1, 0), ("C", 2, 0), ("D", 3, 0)])
    moves = grid_flow.reflow_moves(entries, COLS, "D", (1, 0))
    check("前移占用：D/B/C 动，A 不动",
          moves == {"D": (1, 0), "B": (2, 0), "C": (3, 0)})
    apply_moves(entries, moves)
    by_id = {e["id"]: (e["col"], e["row"]) for e in entries}
    check("前移占用落点：A(0,0) D(1,0) B(2,0) C(3,0)",
          (by_id["A"], by_id["D"], by_id["B"], by_id["C"])
          == ((0, 0), (1, 0), (2, 0), (3, 0)))

    # 13.4 前移空格：A _ C D（B 格空），拖 D 到空格 (1,0)
    entries = mk([("A", 0, 0), ("C", 2, 0), ("D", 3, 0)])
    moves = grid_flow.reflow_moves(entries, COLS, "D", (1, 0))
    check("前移空格：D 落 (1,0)，C 后移一位，A 不动",
          moves == {"D": (1, 0), "C": (3, 0)})
    apply_moves(entries, moves)
    by_id = {e["id"]: (e["col"], e["row"]) for e in entries}
    check("前移空格落点：A(0,0) D(1,0) C(3,0)，空位前移到 (2,0)",
          by_id["A"] == (0, 0) and by_id["D"] == (1, 0) and by_id["C"] == (3, 0)
          and (2, 0) not in by_id.values())

    # 13.5 原地恒等：拖到自己的老格 -> 无位移
    entries = mk([("A", 0, 0), ("B", 1, 0), ("C", 2, 0)])
    check("原地拖动返回空位移", grid_flow.reflow_moves(entries, COLS, "B", (1, 0)) == {})

    # 13.6 跨行：A B / C D，拖 A 到 (0,1)（C 占）
    entries = mk([("A", 0, 0), ("B", 1, 0), ("C", 0, 1), ("D", 1, 1)])
    moves = grid_flow.reflow_moves(entries, COLS, "A", (0, 1))
    check("跨行占用：A/B/C 动，D 不动",
          moves == {"B": (0, 0), "C": (1, 0), "A": (0, 1)})
    apply_moves(entries, moves)
    by_id = {e["id"]: (e["col"], e["row"]) for e in entries}
    check("跨行落点：B(0,0) C(1,0) A(0,1) D(1,1)",
          (by_id["B"], by_id["C"], by_id["A"], by_id["D"])
          == ((0, 0), (1, 0), (0, 1), (1, 1)))

    # 13.7 越界夹紧：col 99 -> 最后一列；col -5 -> 0
    entries = mk([("A", 0, 0), ("B", 1, 0)])
    moves = grid_flow.reflow_moves(entries, 4, "A", (99, 0))
    check("col 越界夹紧：A 落到 (3,0)，B 前移补位",
          moves == {"B": (0, 0), "A": (3, 0)})
    entries = mk([("A", 0, 0), ("B", 1, 0)])
    moves = grid_flow.reflow_moves(entries, 4, "B", (-5, 0))
    check("col 负值夹紧：B 落到 (0,0)，A 后移补位",
          moves == {"B": (0, 0), "A": (1, 0)})

    # 13.8 rows 夹紧（M6 分页预留）：target 行超上限时夹到 rows-1
    entries = mk([("A", 0, 0), ("B", 0, 1)])
    moves = grid_flow.reflow_moves(entries, COLS, "A", (0, 7), rows=2)
    check("row 越界夹紧到 rows-1：A 落 (0,1)，B 前移",
          moves == {"B": (0, 0), "A": (0, 1)})

    # 13.9 组件占位（extra_occupied）：target 落在小组件格上 -> 就近解析
    # (1,1) 在阅读序中位于 B(2,0) 之后 -> B 补位前移（iOS 行为）
    entries = mk([("A", 0, 0), ("B", 2, 0)])
    moves = grid_flow.reflow_moves(entries, COLS, "A", (1, 0),
                                   extra_occupied={(1, 0)})
    check("target 落在组件占位：解析到最近可用格 (1,1)，B 补位",
          moves == {"B": (0, 0), "A": (1, 1)})

    # 13.10 位移最小化：单格微移只动 1~2 个图标
    entries = mk([("A", 0, 0), ("B", 1, 0), ("C", 2, 0), ("D", 3, 0),
                  ("E", 4, 0), ("F", 5, 0)])
    moves = grid_flow.reflow_moves(entries, COLS, "C", (3, 0))  # 与 D 换位
    check("相邻交换只动 2 个图标", moves == {"C": (3, 0), "D": (2, 0)})
    entries = mk([("A", 0, 0), ("B", 1, 0), ("C", 2, 0), ("D", 3, 0),
                  ("E", 4, 0), ("F", 5, 0)])
    moves = grid_flow.reflow_moves(entries, COLS, "C", (4, 0))  # 跳过 D 落到 E
    check("隔格微移只动 3 个图标（C/D/E）",
          moves == {"D": (2, 0), "E": (3, 0), "C": (4, 0)})

    # 13.11 与旧 reflow_order 兼容：target 被占用时两者最终布局一致
    entries = mk([("A", 0, 0), ("B", 1, 0), ("C", 2, 0), ("D", 3, 0)])
    snap1 = [dict(e) for e in entries]
    grid_flow.apply_order(entries, grid_flow.reflow_order(entries, COLS, "A", (2, 0)))
    moves = grid_flow.reflow_moves(snap1, COLS, "A", (2, 0))
    apply_moves(snap1, moves)
    check("占用目标：reflow_moves 与 reflow_order 布局一致",
          cells_of(entries) == cells_of(snap1)
          and order_of(entries) == order_of(snap1))

    # 13.12 dragged 不存在 -> None
    entries = mk([("A", 0, 0)])
    check("dragged 不存在返回 None",
          grid_flow.reflow_moves(entries, COLS, "zzz", (1, 0)) is None)

    # 13.13 随机压力：无重叠 / 无丢失 / dragged 精确落 resolved target /
    #      run 外图标不动 / 占用集合合规（占用目标守恒；空格恰少一个洞）
    rng = random.Random(20261018)
    ok = True
    for _ in range(300):
        n = rng.randint(1, 12)
        pool = [(c, r) for r in range(4) for c in range(COLS)]
        picked = rng.sample(pool, n)
        entries = mk([("i%d" % k, c, r) for k, (c, r) in enumerate(picked)])
        did = rng.choice(entries)["id"]
        old_cell = {e["id"]: (e["col"], e["row"]) for e in entries}
        tgt = (rng.randrange(COLS), rng.randrange(4))
        before_set = set(picked)
        moves = grid_flow.reflow_moves(entries, COLS, did, tgt)
        if moves is None:
            ok = False
            continue
        # dragged 必须精确落在夹紧后的 target 上（恒等时老格即 target）
        tc = max(0, min(COLS - 1, tgt[0]))
        tr = max(0, tgt[1])
        if moves.get(did, old_cell[did]) != (tc, tr):
            ok = False
        apply_moves(entries, moves)
        after = {(e["col"], e["row"]) for e in entries}
        # 无重叠 / 无丢失
        if len(after) != len(entries) or sorted(e["id"] for e in entries) != sorted(old_cell):
            ok = False
        # 占用集合：target 被占用 -> 集合守恒；target 为空 -> 恰少一个洞、
        # 恰多出 target（洞在 run 末端——与 iOS「空位随拖动平移」一致）
        if (tc, tr) in before_set:
            if after != before_set:
                ok = False
        else:
            if (after - before_set) != {(tc, tr)} or len(before_set - after) != 1:
                ok = False
        # run 外图标不动（对照应用后的真实位置）
        by_id = {e["id"]: (e["col"], e["row"]) for e in entries}
        for eid, cell in old_cell.items():
            if eid != did and eid not in moves and by_id[eid] != cell:
                ok = False
    check("300 轮随机拖动：精确落点 / 最小位移 / 无重叠 / 占用集合合规", ok)

    # ---------- §14 clamp_widget_cell（v6 §4 组件 span 夹紧） ----------
    # 无 GridMetrics 快照（本文件不 set_grid）：columns 走 fake=10、
    # rows_per_page 走历史回退 8——与 clamp_widget_cell 的纯逻辑无关
    class _St:
        def __init__(self, cols):
            self._cols = cols

        @property
        def columns(self):
            return self._cols

    st = _St(10)
    rpp = grid_flow.rows_per_page()
    # 列夹紧：cs=3 时 col 不得越界
    check("C1 列夹紧到 [0, columns-cs]",
          grid_flow.clamp_widget_cell(st, 99, 0, 3, 2) == (7, 0)
          and grid_flow.clamp_widget_cell(st, -5, 0, 2, 2) == (0, 0))
    # 行夹紧：rs=2 贴页底最后一行 -> 整块上移一行（底边不越页）
    check("C2 行夹紧到页内（rs=2 贴底行上移一格）",
          grid_flow.clamp_widget_cell(st, 0, rpp - 1, 2, 2) == (0, rpp - 2))
    # 合法数据不动
    check("C3 合法占位原样返回",
          grid_flow.clamp_widget_cell(st, 2, 3, 2, 2) == (2, 3))
    # 次页组件：按所属页夹紧（不拽回第 0 页）
    check("C4 次页组件按所属页夹紧",
          grid_flow.clamp_widget_cell(st, 0, 2 * rpp - 1, 2, 2) == (0, 2 * rpp - 2))
    # 负行防御
    check("C5 负行夹到页首",
          grid_flow.clamp_widget_cell(st, 0, -3, 2, 2) == (0, 0))

    # ---------- §15 cell_by_overlap（v6 §5.2 面积判定） ----------
    # 无 GridMetrics 快照：几何走 cell_size/origin 的回退派生（动态取值，
    # 不写死像素——与 test_layout_anim T5c 同策）。rect = (x, y, w, h)
    # 窗口控件坐标。候选 = 当前页全部单元格。
    class _St2:
        def __init__(self, cols=10, metric=48, chrome=1.0):
            self._cols, self._metric, self._chrome = cols, metric, chrome

        @property
        def columns(self):
            return self._cols

        def get_setting(self, key):
            # 翻页轴 / 布局模式等设置读口（真实 Storage 同名方法）
            return {"page_axis": "horizontal", "layout_mode": "grid"}.get(key)

        def icon_metric(self):
            return self._metric

        def ui_scale(self):
            return self._chrome

    st2 = _St2()
    cw, ch = grid_flow.cell_size(st2)
    ox, oy = grid_flow.origin()
    rpp = grid_flow.rows_per_page()
    # O1 完全在格内 -> 该格
    check("O1 图标完全在格内 -> 精确落该格",
          grid_flow.cell_by_overlap(st2, (ox + 2 * cw, oy + ch, cw, ch)) == (2, 1))
    # O2 跨 (1,0)/(2,0) 边界 3:1 -> 面积大者 (1,0)
    check("O2 跨格 3:1 -> 重叠面积大者",
          grid_flow.cell_by_overlap(
              st2, (ox + cw + cw // 4, oy, cw, ch)) == (1, 0))
    # O3 完全在网格左侧外 -> 面积全 0 并列 -> 中心点格（col 夹紧 0）
    check("O3 网格外（全 0 并列）-> 中心点格",
          grid_flow.cell_by_overlap(st2, (ox - 100, oy + ch, cw, ch)) == (0, 1))
    # O4 完全在网格下方 -> 中心点行夹紧到页底
    check("O4 网格下方 -> 中心点格夹紧页底",
          grid_flow.cell_by_overlap(
              st2, (ox + cw, oy + rpp * ch + 50, cw, ch)) == (1, rpp - 1))
    # O5 跨边界正中（面积相等）-> 中心点恰在边界，floor 取右格
    check("O5 等分并列 -> 中心点所在格（边界 floor 取右）",
          grid_flow.cell_by_overlap(
              st2, (ox + 2 * cw - cw // 2, oy, cw, ch)) == (2, 0))
    # O6 与 pos_cell 的关系：指针格 ⊆ 面积格——图标完全在指针格内时一致
    check("O6 完全在格内时与 pos_cell 一致",
          grid_flow.cell_by_overlap(st2, (ox + cw, oy, cw, ch))
          == grid_flow.pos_cell(st2, ox + cw + cw // 2, oy + ch // 2) == (1, 0))

    # ---------- §16 page_grid_center（v6 §6.2 文件夹弹窗居中） ----------
    # 规格（指导文档 §6.2）：弹窗中心对齐当前页网格区中心
    # (ox + cols*cw//2, oy + rows*ch//2)。网格区几何所有页相同
    # （页只是行偏移），故该点与当前页无关——纯函数不读 current_page。
    cols2 = st2.columns
    rows2 = grid_flow.rows_per_page()
    want_c = (ox + cols2 * cw // 2, oy + rows2 * ch // 2)
    check("C1 page_grid_center = (ox+cols*cw//2, oy+rows*ch//2)",
          grid_flow.page_grid_center(st2) == want_c)
    grid_flow.set_page(2)
    check("C2 page_grid_center 与当前页无关（翻页后同值）",
          grid_flow.page_grid_center(st2) == want_c)
    grid_flow.set_page(0)

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL %s PASSED" % "grid_flow")
    return 0


if __name__ == "__main__":
    sys.exit(main())
