# -*- coding: utf-8 -*-
"""便签的「编辑」态 + 八点拖动改尺寸（2026-10-19 用户反馈）。

用户要的是安卓小组件那套：网格模式下右键 -> 编辑 -> 组件四周出现控制点，
拖点按格步进改大小。

契约：
  R1 锚定 + 网格模式：右键菜单含「编辑」（无界模式不出现——没有格跨度）
  R2 进入编辑态：8 个控制点（4 角 + 4 边），退出后清空
  R3 拖东侧点右移 1 格 -> colspan +1，左边不动
  R4 拖西侧点左移 1 格 -> colspan +1，左边界同时左移 1 格
  R5 拖南侧点上移过量 -> rowspan 夹紧到 1（不出现 0 跨度）
  R6 改尺寸后 entry 与视觉一致，且不压住别的组件

运行：python tests/test_widget_resize.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.storage import Storage
from src.widget_layer import WidgetLayer

STATE = Path(tempfile.gettempdir()) / "test_widget_resize_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=300):
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


def mouse(widget, kind, local, gdelta=(0, 0), button=Qt.LeftButton):
    """构造并派发一次鼠标事件（local 为部件内坐标，gdelta 为全局偏移）。"""
    gp = widget.mapToGlobal(QPoint(int(local.x()) + gdelta[0],
                                   int(local.y()) + gdelta[1]))
    ev = QMouseEvent(kind, QPointF(local), QPointF(gp), button, button,
                     Qt.NoModifier)
    if kind == QEvent.MouseButtonPress:
        widget.mousePressEvent(ev)
    elif kind == QEvent.MouseMove:
        widget.mouseMoveEvent(ev)
    else:
        widget.mouseReleaseEvent(ev)


def drag_handle(widget, edge, dcol, drow):
    """按住某个控制点拖动 (dcol, drow) 格后松手。"""
    cw, ch = grid_flow.cell_size(widget.storage)
    rect = widget._handle_rects()[edge]
    start = rect.center()
    mouse(widget, QEvent.MouseButtonPress, QPointF(start))
    mouse(widget, QEvent.MouseMove, QPointF(start),
          gdelta=(int(dcol * cw), int(drow * ch)))
    mouse(widget, QEvent.MouseButtonRelease, QPointF(start),
          gdelta=(int(dcol * cw), int(drow * ch)))
    settle(QApplication.instance(), 60)


def main(app):
    st = make_state([
        {"id": "clock1", "type": "clock", "w": 300, "h": 300,
         "hidden": False, "anchored": True, "col": 10, "row": 0},
        {"id": "note1", "type": "notes", "w": 300, "h": 300,
         "hidden": False, "anchored": True, "col": 2, "row": 0, "text": ""},
    ])
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)
    layer = WidgetLayer(st)
    settle(app, 300)
    note = layer.widgets.get("note1")
    check("R0 便签已创建且锚定", note is not None and note.anchored)
    if note is None:
        print("!! 便签未创建，后续断言跳过")

    if note is not None:
        cw, ch = grid_flow.cell_size(st)

        # ---------- R1：菜单项 ----------
        menu = note._build_context_menu()
        texts = [a.text() for a in menu.actions()]
        check("R1 锚定+网格模式右键菜单含「编辑」", "编辑" in texts, "%s" % texts)
        check("R1 未进入编辑态时控制点为空", note._handle_rects() == {})

        # ---------- R2：编辑态控制点 ----------
        note._enter_edit()
        handles = note._handle_rects()
        check("R2 编辑态 8 个控制点（4 角 + 4 边）",
              sorted(handles) == sorted(["nw", "n", "ne", "e", "se", "s", "sw", "w"]),
              "%s" % sorted(handles))
        menu2 = note._build_context_menu()
        texts2 = [a.text() for a in menu2.actions()]
        check("R2 编辑态菜单改为「完成编辑」", "完成编辑" in texts2, "%s" % texts2)

        # ---------- R3：东侧 +1 列 ----------
        start_col, start_row = int(note.entry["col"]), int(note.entry["row"])
        drag_handle(note, "e", 1, 0)
        check("R3 拖东侧 +1 格 -> colspan 3",
              int(note.entry.get("colspan", 0)) == 3,
              "colspan=%s" % note.entry.get("colspan"))
        check("R3 左边界不动", int(note.entry["col"]) == start_col,
              "col=%s" % note.entry.get("col"))
        check("R3 视觉宽度 = 3×cell", note.width() == 3 * cw,
              "w=%d want=%d" % (note.width(), 3 * cw))

        # ---------- R4：西侧左移 1 格（同时扩宽） ----------
        drag_handle(note, "w", -1, 0)
        check("R4 拖西侧 -1 格 -> colspan 4",
              int(note.entry.get("colspan", 0)) == 4,
              "colspan=%s" % note.entry.get("colspan"))
        check("R4 左边界同步左移 1 格", int(note.entry["col"]) == start_col - 1,
              "col=%s want=%s" % (note.entry.get("col"), start_col - 1))
        check("R4 视觉位置 = cell_pos(新列)",
              (note.x(), note.y()) == grid_flow.cell_pos(
                  st, int(note.entry["col"]), int(note.entry["row"])))

        # ---------- R5：南侧过度上拖 -> 夹到 1 行 ----------
        drag_handle(note, "s", 0, -5)
        check("R5 rowspan 夹紧到 1（不出现 0 跨度）",
              int(note.entry.get("rowspan", 0)) == 1,
              "rowspan=%s" % note.entry.get("rowspan"))

        # ---------- R6：往别的组件方向扩张时被挡住（不叠上去） ----------
        drag_handle(note, "e", 20, 0)
        nc, nr = int(note.entry["col"]), int(note.entry["row"])
        cs, rs = grid_flow.widget_span(st, note.entry)
        cells = {(nc + dc, nr + dr) for dc in range(cs) for dr in range(rs)}
        clock = next(w for w in st.widgets if w["id"] == "clock1")
        ccs, crs = grid_flow.widget_span(st, clock)
        clock_cells = {(int(clock["col"]) + dc, int(clock["row"]) + dr)
                       for dc in range(ccs) for dr in range(crs)}
        check("R6 扩张到别的组件处被挡住（不叠上去）",
              not (cells & clock_cells),
              "note=%s clock=%s" % (sorted(cells), sorted(clock_cells)))
        check("R6 视觉宽度与跨度一致", note.width() == cs * cw,
              "w=%d span=%d×%d" % (note.width(), cs, rs))

        # ---------- R7：控制点圆心压在虚线框上（反馈 2） ----------
        # 控制点是圆，圆心必须落在虚线上。2026-10-21（v7 B5 反馈 20）：
        # 内缩不再写死 2px，改由点径推导 `_edit_line() = max(3, s//2+1)`
        # ——固定 2px 时 18px 的圆点有一半落在窗外被裁成碎块。
        note._enter_edit()
        hs = note._handle_rects()
        w, h = note.width(), note.height()
        line = note._edit_line()
        centers = {k: (r.center().x(), r.center().y()) for k, r in hs.items()}
        check("R7 角控制点圆心落在虚线框四角",
              abs(centers["nw"][0] - line) <= 1
              and abs(centers["nw"][1] - line) <= 1
              and abs(centers["se"][0] - (w - line)) <= 1
              and abs(centers["se"][1] - (h - line)) <= 1,
              "nw=%s se=%s line=%d" % (centers["nw"], centers["se"], line))
        check("R7 边中点圆心落在虚线框边线上",
              abs(centers["n"][1] - line) <= 1
              and abs(centers["s"][1] - (h - line)) <= 1
              and abs(centers["w"][0] - line) <= 1
              and abs(centers["e"][0] - (w - line)) <= 1,
              "n=%s s=%s w=%s e=%s" % (centers["n"], centers["s"],
                                       centers["w"], centers["e"]))
        check("R7 控制点跨在线上（框内框外都有像素）",
              all(r.left() < line if k in ("nw", "w", "sw") else True
                  for k, r in hs.items())
              and all(r.top() < line if k in ("nw", "n", "ne") else True
                      for k, r in hs.items()),
              "%s" % {k: (r.left(), r.top()) for k, r in hs.items()})
        note._exit_edit()

        # ---------- R2b：退出编辑态 ----------
        note._exit_edit()
        check("R2b 退出编辑态后控制点清空", note._handle_rects() == {})

    for w in layer.widgets.values():
        w.close()

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL widget_resize PASSED")
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
