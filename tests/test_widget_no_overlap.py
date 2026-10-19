# -*- coding: utf-8 -*-
"""小组件之间不许堆叠（2026-10-19 用户反馈：时钟压在便签上）。

病根：`_snap_to_grid` 只夹紧到网格/页边界，**从不看别的组件**——把便签
拖到时钟身上松手，两者就永久叠在一起（截图实锤：时钟半透明压在便签上）。

契约：
  O1 resolve_widget_cell：无冲突时原样返回（不多余挪动）
  O2 resolve_widget_cell：与其它组件占格相交时换到不冲突的位置
  O3 解出来的矩形与其它组件占格零交集
  O4 窗口层：便签拖到时钟身上松手 -> entry 占位不相交（视觉不叠）
  O5 排除自身：组件自己移动时不被自己的旧占位挡住

运行：python tests/test_widget_no_overlap.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.storage import Storage
from src.widget_layer import WidgetLayer

STATE = Path(tempfile.gettempdir()) / "test_widget_no_overlap_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=400):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make_state(widgets):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"].update({"hide_native_icons": False,
                                 "auto_clone_desktop": False,
                                 "takeover_desktop": True})
    st._data["widgets"] = [dict(w) for w in widgets]
    st._data["layout"] = []
    st.save()
    return st


def occupied(st, exclude_id=None):
    out = set()
    for w in st.widgets:
        if w.get("hidden") or not w.get("anchored"):
            continue
        if exclude_id is not None and w.get("id") == exclude_id:
            continue
        if "col" not in w or "row" not in w:
            continue
        cs, rs = grid_flow.widget_span(st, w)
        c, r = int(w["col"]), int(w["row"])
        out |= {(c + dc, r + dr) for dc in range(cs) for dr in range(rs)}
    return out


def main(app):
    st = make_state([
        {"id": "clock1", "type": "clock", "w": 300, "h": 300,
         "hidden": False, "anchored": True, "col": 0, "row": 0},
        {"id": "note1", "type": "notes", "w": 300, "h": 300,
         "hidden": False, "anchored": True, "col": 4, "row": 0, "text": ""},
    ])
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)

    # ---------- O1/O2/O3：纯函数 ----------
    c1 = grid_flow.resolve_widget_cell(st, 6, 0, 2, 2, exclude_id="note1")
    check("O1 无冲突时原样返回", c1 == (6, 0), "got=%s" % (c1,))

    c2 = grid_flow.resolve_widget_cell(st, 0, 0, 2, 2, exclude_id="note1")
    check("O2 与时钟占格冲突时换位置", c2 != (0, 0), "got=%s" % (c2,))
    got = {(c2[0] + dc, c2[1] + dr) for dc in range(2) for dr in range(2)}
    check("O3 解出的矩形与其它组件占格零交集",
          not (got & occupied(st, exclude_id="note1")), "cells=%s" % sorted(got))

    # ---------- O5：自身旧占位不算冲突 ----------
    c3 = grid_flow.resolve_widget_cell(st, 4, 0, 2, 2, exclude_id="note1")
    check("O5 自身旧占位被排除（原地不动不算冲突）", c3 == (4, 0),
          "got=%s" % (c3,))

    # ---------- O4：窗口层拖动落定 ----------
    layer = WidgetLayer(st)
    settle(app, 300)
    note = layer.widgets.get("note1")
    check("O4 便签窗口已创建", note is not None)
    if note is not None:
        # 把便签拖到时钟的位置上松手（时钟 2×2 在 (0,0)）
        note.move(*grid_flow.cell_pos(st, 0, 0))
        note._snap_to_grid()
        settle(app, 450)
        nc = (int(note.entry["col"]), int(note.entry["row"]))
        note_cells = {(nc[0] + dc, nc[1] + dr) for dc in range(2) for dr in range(2)}
        clock_cells = occupied(st, exclude_id="note1")
        check("O4 落定后与时钟占位不相交（不再堆叠）",
              not (note_cells & clock_cells),
              "note=%s clock=%s" % (sorted(note_cells), sorted(clock_cells)))
        check("O4 窗口视觉位置与 entry 一致",
              (note.x(), note.y()) == grid_flow.cell_pos(st, nc[0], nc[1]),
              "pos=%s entry=%s" % ((note.x(), note.y()),
                                   grid_flow.cell_pos(st, nc[0], nc[1])))

    for w in layer.widgets.values():
        w.close()

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL widget_no_overlap PASSED")
    return 0


def run_main():
    app = QApplication([])
    wd = QTimer()
    wd.setSingleShot(True)
    wd.timeout.connect(lambda: (print("!! 看门狗超时"), os._exit(3)))
    wd.start(60000)
    try:
        code = main(app)
    except Exception:
        import traceback
        traceback.print_exc()
        failures.append("main() 异常")
        code = 1
    return code


if __name__ == "__main__":
    sys.exit(run_main())
