# -*- coding: utf-8 -*-
"""组件拖动预览不得把图标叠到已占格（2026-10-20 用户反馈 F2）。

病根：`_on_widget_hover` / `_displace_from_widgets` 传给
`grid_flow.displace_cells` 的 `blocked` **只含组件占位**，不含「其他图标
已占用的格子」。displace_cells 把 blocked 当禁区、其余格全算空闲，于是被
组件压到的图标被分配到**另一个图标正占着的格**上——视觉上就是"实时预览
把图标重复堆叠到一个网格里"。

契约：
  P1 禁区构造 `_displace_blocked` 必须包含所有非本次挪走的图标格
  P2 窗口级：铺满一页 + 2x2 组件逐格 hover，每步布局无重复格
  P3 落定路径 `_displace_from_widgets` 同样无重复格
  P4 被挤走的图标必须真的离开组件矩形（不留在组件下面）

运行：python tests/test_widget_displace_stack.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QPoint, QTimer
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.desktop_window import DesktopWindow
from src.storage import Storage

STATE = Path(tempfile.gettempdir()) / "test_displace_stack_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=120):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make_state(widgets, layout):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"].update({
        "hide_native_icons": False,
        "auto_clone_desktop": False,
        "takeover_desktop": True,
        "layout_mode": "grid",
        "auto_arrange": False,
        "dev_mode": False,
    })
    st._data["widgets"] = [dict(w) for w in widgets]
    st._data["layout"] = [dict(e) for e in layout]
    st.save()
    return st


def dup_cells(st):
    """布局里出现次数 >1 的格子（叠格就是它非空）。"""
    seen, dup = {}, []
    for e in st.layout:
        cell = (int(e.get("col", 0)), int(e.get("row", 0)))
        seen[cell] = seen.get(cell, 0) + 1
        if seen[cell] == 2:
            dup.append(cell)
    return dup


def cell_global(w, col, row):
    """格子中心 → 全局坐标（_on_widget_hover 只吃全局坐标）。"""
    x, y = w._entry_pos({"col": col, "row": row})
    return w.mapToGlobal(QPoint(int(x + 20), int(y + 20)))


def main(app):
    # ---------- 构造：小窗口铺满整页 + 1 个 2x2 时钟 ----------
    st = make_state([{"id": "clock1", "type": "clock", "w": 300, "h": 300,
                      "hidden": False, "anchored": True, "col": 0, "row": 9}], [])
    w = DesktopWindow(st)
    w.resize(420, 340)
    w._update_grid_metrics()
    settle(app, 150)

    m = grid_flow.current_metrics()
    check("P0 网格快照就绪", m is not None,
          "cols=%s rows=%s" % (m.cols if m else None, m.rows if m else None))
    if m is None:
        return
    cols, rows = m.cols, m.rows
    total = cols * rows
    check("P0 小窗口网格够小（便于铺满）", total <= 60,
          "cols=%d rows=%d total=%d" % (cols, rows, total))

    # 第 0 页**排满**图标，组件起点在页外（第 9 行）——模拟"桌面排满后
    # 把组件从别处拖进本页"。修复前 blocked 只含组件占位，free 里全是被
    # 图标占着的格，被挤的图标会被分到别人头上（叠格）。
    layout = []
    for r in range(rows):
        for c in range(cols):
            layout.append({"id": "e%d_%d" % (c, r), "type": "app", "col": c,
                           "row": r, "app": {"name": "i%d_%d" % (c, r)}})
    st._data["layout"] = layout
    st.save()
    w.rebuild()
    settle(app, 150)

    check("P0 铺满且起始无重复格", dup_cells(st) == [],
          "dup=%s" % (dup_cells(st),))

    # ---------- P1：禁区构造函数 ----------
    need = [(0, 0), (1, 0)]        # 假装这两个格要被挪走
    icon_cells = {(int(e["col"]), int(e["row"])) for e in st.layout}
    _fn = getattr(w, "_displace_blocked", None)
    check("P1 存在禁区构造函数 _displace_blocked", _fn is not None)
    if _fn is not None:
        blocked = _fn({(0, 0), (1, 0), (0, 1), (1, 1)}, need)
        missing = icon_cells - set(need) - blocked
        check("P1 禁区包含全部非挪走图标格", missing == set(),
              "missing=%s" % sorted(missing)[:6])
        check("P1 组件占位本身始终是禁区（含被挪走的格）",
              set(need) <= blocked, "blocked∩need=%s" % sorted(set(need) & blocked))

    # ---------- P2：实时预览逐格 hover，不许叠格 ----------
    bad = []
    targets = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 2), (5, 4)]
    for (tc, tr) in targets:
        if tc >= cols or tr >= rows:
            continue
        g = cell_global(w, tc, tr)
        w._on_widget_hover("clock1", int(g.x()), int(g.y()))
        settle(app, 30)
        d = dup_cells(st)
        if d:
            bad.append(((tc, tr), d))
    check("P2 逐格 hover 后布局始终无重复格", bad == [],
          "first_bad=%s" % (bad[:2],))

    # ---------- P4：被压住的图标必须离开**预览矩形** ----------
    # 预览态不改组件 entry（entry 只在落定时写），所以必须看
    # _widget_preview_rect，而不是 entry.col/row。
    g = cell_global(w, 0, 0)
    w._on_widget_hover("clock1", int(g.x()), int(g.y()))
    settle(app, 30)
    rect = set(w._widget_preview_rect or set())
    under = [e["id"] for e in st.layout
             if (int(e.get("col", 0)), int(e.get("row", 0))) in rect]
    check("P4 预览矩形下没有残留图标", rect and not under,
          "rect=%s under=%s" % (sorted(rect)[:4], under[:4]))

    # ---------- P3：落定路径（组件 entry 已写新位，再 displace） ----------
    w._on_widget_drop("clock1", int(g.x()), int(g.y())) if hasattr(
        w, "_on_widget_drop") else None
    settle(app, 80)
    ent = next(x for x in st.widgets if x["id"] == "clock1")
    ent["col"], ent["row"] = 0, 0       # 模拟 widget_base 吸附落定写回
    moved = w._displace_from_widgets()
    settle(app, 80)
    check("P3 落定 displace 后无重复格", dup_cells(st) == [],
          "dup=%s" % (dup_cells(st),))
    cs, rs = grid_flow.widget_span(st, ent)
    rect = {(0 + dc, 0 + dr) for dc in range(cs) for dr in range(rs)}
    under = [e["id"] for e in st.layout
             if (int(e.get("col", 0)), int(e.get("row", 0))) in rect]
    check("P3 落定后组件矩形下没有残留图标", under == [],
          "moved=%d under=%s" % (len(moved), under[:4]))

    w.close()


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    crashed = None
    try:
        main(app)
    except Exception:
        import traceback
        traceback.print_exc()
        crashed = "exception"
    finally:
        print("")
        if crashed or failures:
            print("FAILED %d: %s" % (len(failures), failures))
            sys.stdout.flush()
            os._exit(1)
        print("ALL PASSED")
        sys.stdout.flush()
        os._exit(0)
