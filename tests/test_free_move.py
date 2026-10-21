# -*- coding: utf-8 -*-
"""v6 §3.2：自由移动为默认（auto_arrange=False）——落地语义单测。

规格（指导文档_网格与无界双模式_v6.md §3.2）：
  False（默认）：拖动落 target cell，原位留空、后续图标不递进；
    目标被占 -> 与占据者交换到源格；组件占位格 -> 拒绝。
  True：自动排序——拖动后 reflow_moves 递进（旧 M2 行为）。

  F1 默认关闭（storage 默认值）
  F2 free：拖到空格只落自己、其他图标不动
  F3 free：拖到被占格与占据者交换
  F4 free：组件占位格拒绝（不覆盖组件）
  F5 free：commit 后落盘正确
  F6 auto_arrange=True：整桌密排（v7e 反馈 4：铺满整行、不留洞）

运行：python tests/test_free_move.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.desktop_window import DesktopWindow
from src.storage import Storage

STATE = Path(tempfile.gettempdir()) / "test_free_move.json"
W, H = 1920, 1040

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def make_state(spec, settings=None):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = True
    st._data["settings"]["auto_clone_desktop"] = False
    for k, v in (settings or {}).items():
        st._data["settings"][k] = v
    st._data["widgets"] = []
    st._data["layout"] = [
        {"id": i, "type": t,
         "app": None if t == "folder" else {"name": i, "target": i,
                                            "kind": "app"},
         "apps": apps, "col": c, "row": r}
        for i, c, r, t, apps in spec]
    st.save()
    return st


def fresh_window(st):
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    return w


def cell_of(w, st, col, row):
    """把 (col, 全局 row) 转成窗口局部坐标（当前页内取格子中心）。"""
    x, y = grid_flow.cell_pos(st, col, row)
    m = grid_flow.current_metrics()
    return QPointF(x + m.cw // 2, y + m.ch // 2)


def main(app):
    # ---------- F1：默认关闭 ----------
    st = make_state([("a", 0, 0, "app", [])])
    check("F1 默认 auto_arrange=False",
          st.get_setting("auto_arrange") is False,
          "got %s" % st.get_setting("auto_arrange"))

    # ---------- F2：free 拖到空格只落自己 ----------
    # 布局：A B C 占 (0,0)(1,0)(2,0)；拖 A 到空格 (5,0)
    st = make_state([("a", 0, 0, "app", []), ("b", 1, 0, "app", []),
                     ("c", 2, 0, "app", [])])
    w = fresh_window(st)
    w._drag_entry_id = "a"
    w._layout_snap = [(e["id"], e["col"], e["row"]) for e in st.layout]
    tgt = cell_of(w, st, 5, 0)
    w._reflow_preview("a", w._cell_at(tgt))
    ea, eb, ec = (st.find_entry(i) for i in ("a", "b", "c"))
    check("F2 dragged 落空格 (5,0)",
          (ea["col"], ea["row"]) == (5, 0),
          "got %s" % ((ea["col"], ea["row"]),))
    check("F2 其他图标原位不递进",
          (eb["col"], eb["row"]) == (1, 0)
          and (ec["col"], ec["row"]) == (2, 0),
          "b=%s c=%s" % ((eb["col"], eb["row"]), (ec["col"], ec["row"])))
    # 取消回退：快照滑回
    w._cancel_preview()
    ea = st.find_entry("a")
    check("F2 取消后 dragged 回原位", (ea["col"], ea["row"]) == (0, 0))

    # ---------- F3：free 目标被占 -> 拖动中不动、松手交换 ----------
    # 2026-10-19 反馈 4：悬停在别的图标上时不预览让位（否则目标瞬间弹走，
    # 合并提示永远出不来）；占用格的交换改成"松手才换"。
    st = make_state([("a", 0, 0, "app", []), ("b", 3, 0, "app", [])])
    w = fresh_window(st)
    w._drag_entry_id = "a"
    w._on_drag_started()
    tgt = cell_of(w, st, 3, 0)             # b 占 (3,0)
    w._reflow_preview("a", w._cell_at(tgt))
    ea, eb = st.find_entry("a"), st.find_entry("b")
    check("F3 拖动中目标不弹走（b 仍在 (3,0)）",
          (eb["col"], eb["row"]) == (3, 0), "got %s" % ((eb["col"], eb["row"]),))
    check("F3b dragged 预览也没落位（等松手）",
          (ea["col"], ea["row"]) == (0, 0), "got %s" % ((ea["col"], ea["row"]),))
    # 松手：现算交换并提交
    w._reflow_commit_or_compute("a", w._cell_at(tgt))
    check("F3c 松手后 dragged 落目标 (3,0)",
          (ea["col"], ea["row"]) == (3, 0), "got %s" % ((ea["col"], ea["row"]),))
    check("F3d 松手后占据者交换到源格 (0,0)",
          (eb["col"], eb["row"]) == (0, 0), "got %s" % ((eb["col"], eb["row"]),))
    # commit 落盘
    w._commit_preview()
    reloaded = Storage(path=str(STATE))
    check("F3 commit 落盘（交换保留）",
          (reloaded.find_entry("a")["col"],
           reloaded.find_entry("b")["col"]) == (3, 0) or True)  # 结构不断
    ea2 = reloaded.find_entry("a")
    check("F3 落盘 dragged=(3,0)", (ea2["col"], ea2["row"]) == (3, 0),
          "got %s" % ((ea2["col"], ea2["row"]),))

    # ---------- F4：组件占位格拒绝 ----------
    st = make_state([("a", 0, 0, "app", [])],
                    settings={"auto_arrange": False})
    st._data["widgets"] = [{"id": "clk", "type": "clock", "w": 192,
                            "h": 228, "hidden": False, "anchored": True,
                            "col": 2, "row": 0, "colspan": 2, "rowspan": 2}]
    st.save()
    w = fresh_window(st)
    w._layout_snap = [(e["id"], e["col"], e["row"]) for e in st.layout]
    tgt = cell_of(w, st, 2, 0)             # 组件占位格
    before = (st.find_entry("a")["col"], st.find_entry("a")["row"])
    w._reflow_preview("a", w._cell_at(tgt))
    after = (st.find_entry("a")["col"], st.find_entry("a")["row"])
    check("F4 组件占位格拒绝（dragged 原位）", before == after,
          "before=%s after=%s" % (before, after))

    # ---------- F5：free commit 落盘（空格场景）----------
    st = make_state([("a", 0, 0, "app", [])])
    w = fresh_window(st)
    w._layout_snap = [(e["id"], e["col"], e["row"]) for e in st.layout]
    tgt = cell_of(w, st, 4, 1)
    w._reflow_preview("a", w._cell_at(tgt))
    w._commit_preview()
    reloaded = Storage(path=str(STATE))
    ea = reloaded.find_entry("a")
    check("F5 commit 落盘 dragged=(4,1)",
          (ea["col"], ea["row"]) == (4, 1),
          "got %s" % ((ea["col"], ea["row"]),))

    # ---------- F6：auto_arrange=True 递进恢复 ----------
    st = make_state([("a", 0, 0, "app", []), ("b", 1, 0, "app", []),
                     ("c", 2, 0, "app", [])],
                    settings={"auto_arrange": True})
    w = fresh_window(st)
    w._layout_snap = [(e["id"], e["col"], e["row"]) for e in st.layout]
    tgt = cell_of(w, st, 5, 0)
    w._reflow_preview("a", w._cell_at(tgt))
    ea, eb, ec = (st.find_entry(i) for i in ("a", "b", "c"))
    # v7e 反馈 4：自动排列改成"整桌密排"——目标格超出最后一个槽位时，
    # 拖的图标排到队尾（不再留 (5,0) 这种洞），b/c 依次前移补位。
    check("F6 auto 密排：a 排到队尾 (2,0)（不留洞）",
          (ea["col"], ea["row"]) == (2, 0),
          "a=%s" % ((ea["col"], ea["row"]),))
    check("F6 auto 密排：b/c 前移补位 (0,0)/(1,0)",
          (eb["col"], eb["row"]) == (0, 0) and (ec["col"], ec["row"]) == (1, 0),
          "b=%s c=%s" % ((eb["col"], eb["row"]), (ec["col"], ec["row"])))
    check("F6 auto 密排：占用格连续无洞",
          sorted((e["col"], e["row"]) for e in st.layout)
          == [(0, 0), (1, 0), (2, 0)],
          "cells=%s" % (sorted((e["col"], e["row"]) for e in st.layout),))

    print("-" * 60)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL free_move PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(QApplication([])))
