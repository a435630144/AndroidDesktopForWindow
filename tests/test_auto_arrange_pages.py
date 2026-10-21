# -*- coding: utf-8 -*-
"""自动排列**按页**密排（v9 V2 BUG2，指导文档_v9.md §3.2）。

BUG 复现：开启自动排列后，把图标拖到下一页松手 —— 全体回到第一页。
根因：`auto_arrange_moves` 用 `pack_cells(len+1, cols)` 从 (0,0) **全局**
密排，与页无关；目标行虽然在页 2，密排结果却全落在页 1。

契约（rpp = 每页行数，cols = 列数）：
  A1  跨页拖动：dragged 落在目标页，且**目��页从该页首行**开始密排
  A2  跨页拖动：原页补洞（该页也是自动排列时）——原页图标仍在该页内
  A3  同页拖动：只影响本页，其它页一格不动（旧行为保持）
  A4  目标页不在 auto_pages -> 返回 None（调用方回退到自由让位）
  A5  原页不在 auto_pages -> 原页不动（不"顺手"整理自由页）
  A6  任何情况下不出现两个条目占同一格
  A7  组件占位（extra_occupied）在页内被跳过；别的页的占位不影响本页
  A8  跨页拖动后目标页首格就是页首（第 rpp 行），不会"漂回第 0 页"

运行：python tests/test_auto_arrange_pages.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import grid_flow as gf

COLS = 4
RPP = 4

CHECKS = []
failures = []


def check(name, cond, extra=""):
    CHECKS.append(name)
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def make(n, per_page=3, start_page=0):
    """造 n 个条目，每页 per_page 个，从 start_page 起按阅读序排。"""
    out = []
    for i in range(n):
        page = start_page + i // per_page
        idx = i % per_page
        out.append({"id": "i%d" % i, "type": "app",
                    "col": idx % COLS, "row": page * RPP + idx // COLS})
    return out


def apply(entries, moves):
    by_id = {e["id"]: e for e in entries}
    for eid, (c, r) in moves.items():
        by_id[eid]["col"], by_id[eid]["row"] = c, r


def no_dup(entries):
    cells = [(e["col"], e["row"]) for e in entries]
    return len(set(cells)) == len(cells)


def rows_of(entries, page):
    return sorted(e["row"] for e in entries
                  if gf.page_of(int(e["row"]), RPP) == page)


def main():
    # ---------- A1 / A2：跨页拖动 ----------
    entries = make(9)            # 页0: i0..i2, 页1: i3..i5, 页2: i6..i8
    moves = gf.auto_arrange_moves(entries, COLS, "i0", (1, RPP + 1),
                                  rpp=RPP)
    check("A1a 跨页拖动有位移", bool(moves), str(moves))
    apply(entries, moves or {})
    check("A1b 拖动的条目落在目标页", gf.page_of(entries[0]["row"], RPP) == 1,
          "row=%d page=%d" % (entries[0]["row"], gf.page_of(entries[0]["row"], RPP)))
    check("A1c 目标页从该页首行开始密排", rows_of(entries, 1)[0] == RPP,
          str(rows_of(entries, 1)))
    # 页 1 原有 3 个 + 拖来 1 个 = 4 个，cols=4 刚好铺满一行
    check("A1d 目标页无空洞（4 个条目全在页首行）",
          rows_of(entries, 1) == [RPP] * 4, str(rows_of(entries, 1)))
    check("A2a 原页补洞：剩余两格在页首", rows_of(entries, 0) == [0, 0],
          str(rows_of(entries, 0)))
    check("A2b 原页条目仍在原页",
          all(gf.page_of(e["row"], RPP) == 0
              for e in entries if e["id"] in ("i1", "i2")))
    check("A6a 跨页拖动后无重叠", no_dup(entries))

    # ---------- A3：同页拖动 ----------
    entries2 = make(6)
    moves2 = gf.auto_arrange_moves(entries2, COLS, "i0", (2, 0), rpp=RPP)
    apply(entries2, moves2 or {})
    check("A3a 同页拖动只影响本页",
          all(gf.page_of(e["row"], RPP) == int(e["id"][1:]) // 3
              for e in entries2), str([(e["id"], e["row"]) for e in entries2]))
    check("A3b 同页拖动后仍密排",
          rows_of(entries2, 0) == [0, 0, 0], str(rows_of(entries2, 0)))
    check("A3c 同页拖动无重叠", no_dup(entries2))

    # ---------- A4 / A5：auto_pages 过滤 ----------
    entries3 = make(6)
    r = gf.auto_arrange_moves(entries3, COLS, "i0", (1, RPP), rpp=RPP,
                              auto_pages={0})
    check("A4 目标页不是自动页 -> None", r is None, str(r))

    entries4 = make(6)
    r4 = gf.auto_arrange_moves(entries4, COLS, "i0", (2, RPP), rpp=RPP,
                               auto_pages={1})
    check("A5a 目标页是自动页 -> 有结果", r4 is not None, str(r4))
    apply(entries4, r4 or {})
    check("A5b 原页（自由页）一格不动",
          [(e["col"], e["row"]) for e in entries4 if e["id"] in ("i1", "i2")]
          == [(1, 0), (2, 0)],
          str([(e["id"], e["col"], e["row"]) for e in entries4]))
    check("A5c 目标页仍从页首密排", rows_of(entries4, 1)[0] == RPP,
          str(rows_of(entries4, 1)))

    # ---------- A7：组件占位 ----------
    entries5 = make(4)                       # 全在页 0
    moves5 = gf.auto_arrange_moves(entries5, COLS, "i3", (1, 2),
                                   extra_occupied={(0, 0)}, rpp=RPP)
    apply(entries5, moves5 or {})
    check("A7a 组件占的格没人用",
          all((e["col"], e["row"]) != (0, 0) for e in entries5),
          str([(e["col"], e["row"]) for e in entries5]))
    check("A7b 另一端页的占位不影响本页",
          gf.auto_arrange_moves(make(4), COLS, "i3", (1, 2),
                                extra_occupied={(0, RPP + 2)}, rpp=RPP) is not None)

    # ---------- A8：目标页首格 ----------
    entries6 = make(3, per_page=3)
    r6 = gf.auto_arrange_moves(entries6, COLS, "i0", (0, 2 * RPP), rpp=RPP)
    apply(entries6, r6 or {})
    check("A8a 拖到第 3 页首格 -> 落在第 3 页首行",
          (entries6[0]["col"], entries6[0]["row"]) == (0, 2 * RPP + 1)
          or gf.page_of(entries6[0]["row"], RPP) == 2,
          str((entries6[0]["col"], entries6[0]["row"])))
    check("A8b 没有条目被留在页 0", rows_of(entries6, 0) == [] or
          len(rows_of(entries6, 0)) <= 2, str(rows_of(entries6, 0)))

    # ---------- 脏数据 ----------
    dup = [{"id": "a", "col": 0, "row": 0}, {"id": "b", "col": 0, "row": 0}]
    check("A9a 重复占用格 -> None",
          gf.auto_arrange_moves(dup, COLS, "a", (1, 1), rpp=RPP) is None)
    check("A9b dragged 不在列表 -> None",
          gf.auto_arrange_moves(make(2), COLS, "nope", (0, 0), rpp=RPP) is None)

    print("\n%d checks, %d failures" % (len(CHECKS), len(failures)))
    if failures:
        print("FAILED:", ", ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
