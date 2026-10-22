# -*- coding: utf-8 -*-
"""v7 反馈 2：小组件改尺寸后，碰撞形状（格跨度）必须同步。

用户原话：
    小组件手动编辑过尺寸之后，他的 cell 碰撞形状不会同步变化，比如时钟
    改成了 4*1 它在挪动过程中的判断预览检测 还是按照 2*1 来计算的。

病根：`entry` 里的 colspan/rowspan 只有**两条路**会写
（右键「组件尺寸」菜单 `_set_span`、编辑态控制点 `_resize_step`）。
任何"像素尺寸变了但没走这两条"的路径——悬浮态拉右下角手柄、无界模式
改尺寸后切回网格、将来新增的缩放入口——跨度都停在旧值：窗口看着 4×1，
`widget_span()` 仍返回 2×2，拖动预览/图标避让/占位判定全按旧跨度算。

修法（widget_base.FloatingWidget）：
  - `_span_from_geometry()`   像素尺寸 → 跨度反算
  - `_sync_span_from_geometry()` 以**视觉尺寸**为准写回 entry 占位
    （幂等；非锚定 / 无界模式 / 未定位 / 半格噪声一律跳过）
  - `resizeEvent()` 与 `_save_geom()` 都调用它——拖动预览期间就生效，
    不用等松手

契约：
  S1 构造后不动：跨度与像素尺寸本就一致，同步是 no-op
  S2 像素尺寸改动（未走占位写入）→ `widget_span()` 立即反映新跨度
  S3 `widget_cells()`（图标避让的禁区）同样立即反映
  S4 拖动实时预览矩形按新跨度（用户看到的"还是按 2×1"）
  S5 角点控制点同时改两个方向（se 拖 2 列、-1 行 → 4×1）
  S6 半格内的尺寸噪声不抖动跨度（不产生无意义写入）
  S7 无界模式跳过（那里没有格跨度概念）
  S8 悬浮（非锚定）组件跳过（不占格）
  S9 已写入正确跨度时同步返回 False（幂等，不发多余 gridChanged）

运行：python tests/test_widget_span_sync.py   （offscreen）
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
from src.desktop_window import DesktopWindow
from src.storage import Storage
from src.widget_layer import WidgetLayer

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_widget_span_sync_state.json"
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


def make_state(widgets, icons=0):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"].update({"hide_native_icons": False,
                                 "auto_clone_desktop": False,
                                 "takeover_desktop": True,
                                 "show_widgets": True,
                                 "layout_mode": "grid"})
    st._data["widgets"] = [dict(w) for w in widgets]
    st._data["layout"] = [
        {"id": "e%d" % i, "type": "app", "col": 6 + i, "row": 6,
         "app": {"name": "i%d" % i, "target": "i%d" % i, "kind": "app"}}
        for i in range(icons)]
    st.save()
    return st


def mouse(widget, kind, local, gdelta=(0, 0)):
    gp = widget.mapToGlobal(QPoint(int(local.x()) + gdelta[0],
                                   int(local.y()) + gdelta[1]))
    ev = QMouseEvent(kind, QPointF(local), QPointF(gp), Qt.LeftButton,
                     Qt.LeftButton, Qt.NoModifier)
    if kind == QEvent.MouseButtonPress:
        widget.mousePressEvent(ev)
    elif kind == QEvent.MouseMove:
        widget.mouseMoveEvent(ev)
    else:
        widget.mouseReleaseEvent(ev)


def drag_handle(widget, edge, dcol, drow):
    cw, ch = grid_flow.cell_size(widget.storage)
    start = widget._handle_rects()[edge].center()
    mouse(widget, QEvent.MouseButtonPress, QPointF(start))
    mouse(widget, QEvent.MouseMove, QPointF(start),
          gdelta=(int(dcol * cw), int(drow * ch)))
    mouse(widget, QEvent.MouseButtonRelease, QPointF(start),
          gdelta=(int(dcol * cw), int(drow * ch)))
    settle(QApplication.instance(), 60)


def clock(id_="clock1", col=0, row=0):
    return {"id": id_, "type": "clock", "w": 300, "h": 300, "hidden": False,
            "anchored": True, "col": col, "row": row,
            "colspan": 2, "rowspan": 2}


# --------------------------------------------------------------- 纯逻辑部分
def part_a(app):
    st = make_state([clock()], icons=3)
    grid_flow.set_grid(st, (W, H))
    grid_flow.set_page(0)
    layer = WidgetLayer(st)
    settle(app, 250)
    w = layer.widgets.get("clock1")
    check("S0 组件已创建且锚定", w is not None and w.anchored)
    if w is None:
        return None, None

    cw, ch = grid_flow.cell_size(st)
    check("S0 快照 cell 已就绪", cw > 0 and ch > 0, "cw=%d ch=%d" % (cw, ch))

    # ---------- S1：构造后是 no-op ----------
    check("S1 构造后跨度仍为 2×2", grid_flow.widget_span(st, w.entry) == (2, 2),
          "%s" % (grid_flow.widget_span(st, w.entry),))
    from src import widget_geom
    check("S1 视觉尺寸 = 卡片尺寸（span × cell × fill）",
          (w.width(), w.height()) == widget_geom.card_size(st, (2, 2)),
          "%dx%d want %s" % (w.width(), w.height(),
                             widget_geom.card_size(st, (2, 2))))
    before = dict(w.entry)
    w._sync_span_from_geometry()
    check("S1 尺寸一致时同步不改 entry",
          {k: v for k, v in w.entry.items() if k in before} == before)

    # ---------- S2：像素尺寸改了但没走占位写入（用户场景） ----------
    w.resize(*widget_geom.card_size(st, (4, 1)))   # 只改视觉，不动 entry 的 span
    span = grid_flow.widget_span(st, w.entry)
    check("S2 改像素尺寸后跨度同步为 4×1", span == (4, 1), "span=%s" % (span,))
    check("S2 entry 的 colspan/rowspan 已落盘",
          (w.entry.get("colspan"), w.entry.get("rowspan")) == (4, 1),
          "cs=%s rs=%s" % (w.entry.get("colspan"), w.entry.get("rowspan")))

    # ---------- S3：图标避让禁区跟着变 ----------
    cells = grid_flow.widget_cells(st)
    col, row = int(w.entry["col"]), int(w.entry["row"])
    want = {(col + dc, row) for dc in range(4)}
    check("S3 组件占位 = 一行 4 格",
          {c for c in cells if c[1] == row and col <= c[0] < col + 4} == want,
          "want=%s" % sorted(want))
    check("S3 占位总格数 = 4", len(cells) == 4, "cells=%d %s" % (len(cells),
                                                                 sorted(cells)))

    # ---------- S9：幂等 ----------
    check("S9 跨度已对齐时同步返回 False", w._sync_span_from_geometry() is False)

    # ---------- S6：半格噪声不抖动 ----------
    # v10 A8：卡片步长是 cell×fill（默认 0.9），"半卡噪声"必须按卡片步长算
    _cw4 = widget_geom.card_size(st, (4, 1))[0]
    w.resize(_cw4 - 4, widget_geom.card_size(st, (4, 1))[1])
    check("S6 半格内的尺寸噪声不改跨度",
          grid_flow.widget_span(st, w.entry) == (4, 1),
          "w=%d span=%s" % (w.width(), grid_flow.widget_span(st, w.entry)))

    # ---------- S5：角点双向步进 ----------
    # 先退回 2×2（走公开入口），再抓 se 角点往右下拖
    w._set_span(2, 2)
    settle(app, 80)
    check("S5 前置：已回到 2×2", grid_flow.widget_span(st, w.entry) == (2, 2),
          "%s" % (grid_flow.widget_span(st, w.entry),))
    w._enter_edit()
    drag_handle(w, "se", 2, -1)
    span = grid_flow.widget_span(st, w.entry)
    check("S5 se 角点同时改宽高（2×2 → 4×1）", span == (4, 1), "span=%s" % (span,))
    check("S5 视觉尺寸（卡片区）与跨度一致",
          (w.card_rect().width(), w.card_rect().height())
          == widget_geom.card_size(st, (4, 1)),
          "%dx%d want %s" % (w.card_rect().width(), w.card_rect().height(),
                             widget_geom.card_size(st, (4, 1))))
    w._exit_edit()

    # ---------- S8：悬浮组件跳过 ----------
    fl = layer.widgets.get("clock1")
    old_anchored = fl.entry.get("anchored")
    fl.entry["anchored"] = False
    fl.entry["colspan"], fl.entry["rowspan"] = 2, 2
    idx = fl.entry.get("id")
    fl.resize(7 * cw, 5 * ch)
    check("S8 悬浮组件不因像素尺寸改跨度",
          grid_flow.widget_span(st, fl.entry) == (2, 2),
          "%s" % (grid_flow.widget_span(st, fl.entry),))
    fl.entry["anchored"] = old_anchored
    _ = idx

    for x in layer.widgets.values():
        x.close()
    return st, (cw, ch)


# --------------------------------------------------------- 预览矩形（真窗口）
def part_b(app):
    st = make_state([clock(col=0, row=0)], icons=4)
    grid_flow.set_grid(st, (W, H))
    grid_flow.set_page(0)
    win = DesktopWindow(st)
    layer = WidgetLayer(st)
    win.set_widget_layer(layer)      # main.py 装配时注入，测试需自己接
    settle(app, 400)
    w = layer.widgets.get("clock1")
    check("S4 真窗口里找到组件实例", w is not None)
    if w is None:
        win.close()
        return

    cw, ch = grid_flow.cell_size(st)
    w.resize(4 * cw, 1 * ch)
    settle(app, 120)
    check("S4 改尺寸后跨度 = 4×1",
          grid_flow.widget_span(st, w.entry) == (4, 1),
          "%s" % (grid_flow.widget_span(st, w.entry),))

    # 悬停到 (5, 3) 格中心：预览矩形应是 4 格一行（用户看到"还是 2×1"）
    win._widget_preview_rect = None
    x, y = win._entry_pos({"col": 5, "row": 3})
    g = win.mapToGlobal(QPoint(int(x + 8), int(y + 8)))
    win._on_widget_hover("clock1", int(g.x()), int(g.y()))
    rect = win._widget_preview_rect or set()
    rows = {c[1] for c in rect}
    check("S4 预览矩形是 4 格（不是 2 格）", len(rect) == 4,
          "rect=%s" % sorted(rect))
    check("S4 预览矩形是**一行**（高度 1 格）", len(rows) == 1,
          "rows=%s" % sorted(rows))

    win.close()


def main(app):
    part_a(app)
    part_b(app)
    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL widget_span_sync PASSED")
    return 0


def run_main():
    app = QApplication([])
    wd = QTimer()
    wd.setSingleShot(True)
    wd.timeout.connect(lambda: (print("!! 看门狗超时"), os._exit(3)))
    wd.start(90000)
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
