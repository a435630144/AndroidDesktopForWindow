# -*- coding: utf-8 -*-
"""组件挤位不叠格（2026-10-19 反馈 7b）。

用户："元素已经排满后再往上移动小组件，自动实时排序规则混乱，有的图标
直接堆叠到一起。"病根是逐个 nearest_free_cell 用同一份静态 blocked——
两个图标被分到同一个空格。

契约：
  D1 一批被压住的图标 -> 分配结果互不重复，且都不在 blocked 内
  D2 页内尽量就近（曼哈顿），保持原有相对顺序
  D3 页内排满 -> 顺延到页底下方的新行（不丢、不叠、不被 paging 裁掉）
  D4 空输入 -> 空结果
  D5 大量条目（100 个）仍然全不重复

运行：python tests/test_displace_no_stack.py
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


def main():
    # ---------- D1 / D2 页内就近、不重复 ----------
    blocked = {(c, r) for c in range(4) for r in range(2)}     # 组件 4x2
    srcs = [(0, 0), (1, 0), (2, 1)]
    plan = grid_flow.displace_cells(srcs, blocked, 10, (0, 5))
    dsts = list(plan.values())
    check("D1 与 blocked 不相交", all(d not in blocked for d in dsts), "%s" % dsts)
    check("D1b 分配结果互不重复", len(set(dsts)) == len(dsts), "%s" % dsts)
    check("D2 就近：全部落在组件右侧同两行",
          all(d[0] >= 4 for d in dsts), "%s" % dsts)
    check("D2b 保持行归属（第 0 行 -> 第 0 行）",
          plan[(0, 0)][1] == 0 and plan[(2, 1)][1] == 1, "%s" % plan)

    # ---------- D3 页满顺延 ----------
    cols, rows = 5, 3
    full = {(c, r) for c in range(cols) for r in range(rows)}
    xs = list(full)
    # blocked = 整页（组件把一页都压住了），15 个条目只能顺延到页底下方
    plan2 = grid_flow.displace_cells(xs, set(full), cols, (0, rows - 1))
    vals = list(plan2.values())
    check("D3 页满后全部分配成功", len(vals) == len(xs), "%d" % len(vals))
    check("D3b 依旧互不重复", len(set(vals)) == len(vals))
    overflow = [d for d in vals if d[1] >= rows]
    used_rows = sorted(set(r for _c, r in overflow))
    per_row = {r: sum(1 for _c, rr in overflow if rr == r) for r in used_rows}
    check("D3c 溢出行在页底下方连续排布（行优先填满）",
          len(overflow) == len(xs) and used_rows == [rows, rows + 1, rows + 2]
          and all(n == cols for n in per_row.values()),
          "rows=%s per_row=%s" % (used_rows, per_row))

    # ---------- D4 空 ----------
    check("D4 空输入空结果", grid_flow.displace_cells([], {(0, 0)}, 8, (0, 4)) == {})

    # ---------- D5 压力（源格必须互不相同，否则 dict 键会互相覆盖）----------
    srcs3 = [(c, r) for r in range(10) for c in range(10)]
    plan3 = grid_flow.displace_cells(srcs3, {(0, 0)}, 10, (0, 5))
    vals3 = list(plan3.values())
    check("D5 100 个条目仍不重复", len(set(vals3)) == len(vals3),
          "uniq=%d/%d" % (len(set(vals3)), len(vals3)))

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL displace_no_stack PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
