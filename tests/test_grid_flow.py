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

        def icon_metric(self):
            return int(self._s["icon_size"] * 1.25)

        def icon_chrome_scale(self):
            return 1.25

    st = _St()
    ox, oy = grid_flow.origin()
    cw, ch = grid_flow.cell_size(st)
    # 目标格 (2,1) 的左上角附近（偏移 1/3 格）应吸附到该格原点
    x, y = grid_flow.snap_point(st, ox + cw * 2 + cw // 3, oy + ch * 1 + ch // 3, (1920, 1080))
    check("snap_point 对齐列", x == ox + cw * 2)
    check("snap_point 对齐行", y == oy + ch * 1)
    # 半格之外：四舍五入到邻近格
    x2, _ = grid_flow.snap_point(st, ox + cw * 2 + cw * 0.75, oy, (1920, 1080))
    check("snap_point 越过半格吸附到下一列", x2 == ox + cw * 3)
    # 越界保护
    x3, y3 = grid_flow.snap_point(st, -5000, -5000, (1920, 1080))
    check("snap_point 左上不越界", x3 >= 0 and y3 >= 0)
    x4, y4 = grid_flow.snap_point(st, 99999, 99999, (1920, 1080))
    check("snap_point 右下不越界", x4 <= 1920 and y4 <= 1080)

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL %s PASSED" % "grid_flow")
    return 0


if __name__ == "__main__":
    sys.exit(main())
