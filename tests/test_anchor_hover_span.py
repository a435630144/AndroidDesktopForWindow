# -*- coding: utf-8 -*-
"""反馈 5 契约：组件拖动悬停按**自身左上角**反算 + 红框画**整 span**。

用户原话：
    测试当前时钟小组件为2*1，但是在拖住移动的过程中，左侧的1*1格子不会
    进行碰撞检测。

病根（两处同源，都是"口径只有一处对"）：
  ① `widget_base.mouseMoveEvent` 的悬停预览报的是**指针**全局坐标，
     而松手吸附 `_snap_to_grid()` 用的是 `pos_cell(self.x(), self.y())`
     ——组件自身左上角。2×1 组件抓右半边拖时指针落在第 2 格、左缘还在
     第 1 格，预览矩形少算左格 = 用户看到的"左侧 1×1 不碰撞"。
  ② `_paint_highlight` 只画 `_hl_cell` 单格：即使预览矩形算对了，用户
     也只看见一格红框，"检测到几格"这件事从来没有可见证据。

修法：悬停改报 `self.pos()`（与吸附同口径）；高亮带上 `_hl_span`，
`_paint_highlight` 按 (col,row)+span 画整块。

契约：
  A1 `_hl_span` 默认 (1,1)；`_set_highlight` 只在 cell/span 变化时重绘
  A2 悬停传**左上角** → 预览矩形 = 组件真实 footprint（2×1 就 2 格）
  A3 同一组件传**指针中心**会得到右移一格的矩形 —— 证明两种口径确实
     差一格，且实现取的是左上角（A2 的结果不是 A3 的结果）
  A4 红框像素按 span 展开：span=(2,1) 与 (1,1) 的渲染在**第 2 格**区域
     大面积不同，远处格子零差异（render 取样，不走保护）
  A5 预览矩形按跨度夹紧在页内（2×2 拖到页底不多出一行）
  A6 无界模式不预览（组件不占格，图标不该被挤走）
  A7 悬浮（非锚定）组件不预览
  A8 源码口径锁：`anchorHover.emit` 前一行必须是 `g = self.pos()`
     （防有人"顺手"改回 `e.globalPosition()`）

运行：python tests/test_anchor_hover_span.py   （offscreen）
"""
import inspect
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QPoint, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from src import grid_flow, widget_base
from src.desktop_window import DesktopWindow
from src.storage import Storage

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_anchor_hover_span_state.json"

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


def clock(id_="clock1", col=0, row=0, span=(2, 1)):
    return {"id": id_, "type": "clock", "w": 300, "h": 300, "hidden": False,
            "anchored": True, "col": col, "row": row,
            "colspan": span[0], "rowspan": span[1]}


def make_state(widgets, icons=()):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"].update({
        "hide_native_icons": False,
        "auto_clone_desktop": False,
        "takeover_desktop": True,
        "show_widgets": True,
        "layout_mode": "grid",
        "dev_mode": False,
        "auto_arrange": False,
    })
    st._data["widgets"] = [dict(w) for w in widgets]
    st._data["layout"] = [
        {"id": "e%d" % i, "type": "app", "col": c, "row": r,
         "app": {"name": "E%d" % i, "target": "e%d" % i, "kind": "app"}}
        for i, (c, r) in enumerate(icons)]
    st.save()
    return st


def new_window(app, st):
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    w.rebuild()
    w.show()
    settle(app, 120)
    return w


def cell_global(w, col, row, dx=4, dy=4):
    """cell(col,row) 左上角 + 微偏移 的**全局**坐标（组件左上角口径）。"""
    x, y = grid_flow.cell_pos(w.storage, col, row)
    return w.mapToGlobal(QPoint(int(x) + dx, int(y) + dy))


def render(w):
    img = QImage(w.size(), QImage.Format_ARGB32)
    img.fill(0)
    w.render(img)
    return img


def diff_count(a, b, rect, step=2):
    n = 0
    for y in range(rect.top(), rect.bottom() + 1, step):
        for x in range(rect.left(), rect.right() + 1, step):
            if a.pixel(x, y) != b.pixel(x, y):
                n += 1
    return n


# ---------------------------------------------------------------- A1–A3
def part_highlight_state(app):
    st = make_state([clock(col=2, row=2, span=(2, 1))])
    w = new_window(app, st)

    check("A1 红框跨度默认 (1,1)", w._hl_span == (1, 1), "%s" % (w._hl_span,))

    updates = {"n": 0}
    w.update = lambda *a, **k: updates.__setitem__("n", updates["n"] + 1)
    w._set_highlight((3, 3), (1, 1))
    first = updates["n"]
    w._set_highlight((3, 3), (1, 1))          # 同 cell 同 span：不重绘
    check("A1b 同 cell 同 span 不重复重绘", updates["n"] == first,
          "n=%d first=%d" % (updates["n"], first))
    w._set_highlight((3, 3), (2, 1))          # 只换 span：必须重绘
    check("A1c 只改 span 也要重绘", updates["n"] == first + 1,
          "n=%d" % updates["n"])
    w._set_highlight(None)
    check("A1d 清空红框时跨度归位 (1,1)", w._hl_span == (1, 1),
          "%s" % (w._hl_span,))
    w.update = DesktopWindow.update.__get__(w, DesktopWindow)

    # ---------- A2 左上角口径 → 2×1 组件占满 2 格 ----------
    col, row = 2, 2
    gp = cell_global(w, col, row)
    w._on_widget_hover("clock1", gp.x(), gp.y())
    rect = set(w._widget_preview_rect or set())
    check("A2 悬停左上角 → 预览矩形 2 格", len(rect) == 2, "%s" % (sorted(rect),))
    check("A2b 起点就是悬停的那一格",
          w._hl_cell == (col, row), "hl=%s" % (w._hl_cell,))
    check("A2c 红框跨度跟随组件 (2,1)", w._hl_span == (2, 1),
          "%s" % (w._hl_span,))

    # ---------- A3 指针中心口径会右移一格（两者确实差一格） ----------
    cw, _ch = grid_flow.cell_size(st)
    x, y = grid_flow.cell_pos(st, col, row)
    center = w.mapToGlobal(QPoint(int(x + cw), int(y + 4)))   # 第 2 格
    w._on_widget_hover("clock1", center.x(), center.y())
    check("A3 指针中心口径落在第 (col+1) 格",
          w._hl_cell == (col + 1, row), "hl=%s" % (w._hl_cell,))
    check("A3b 两种口径确实差一格（A2 不是指针口径的结果）",
          w._hl_cell != (col, row), "hl=%s" % (w._hl_cell,))
    return w, st


# ------------------------------------------------------------------ A4
def part_paint(app, w, st):
    col, row = 2, 2
    cw, ch = grid_flow.cell_size(st)
    x2, y2 = grid_flow.cell_pos(st, col + 1, row)
    second = (int(x2), int(y2), int(cw), int(ch))
    from PySide6.QtCore import QRect
    r2 = QRect(second[0], second[1], second[2], second[3])
    xf, yf = grid_flow.cell_pos(st, col + 5, row + 3)
    rf = QRect(int(xf), int(yf), int(cw), int(ch))

    w._widget_preview_rect = None
    w._set_highlight((col, row), (1, 1))
    img1 = render(w)
    w._set_highlight((col, row), (2, 1))
    img2 = render(w)

    d2 = diff_count(img1, img2, r2)
    df = diff_count(img1, img2, rf)
    check("A4 拉宽 span 后第 2 格区域被画上（像素差异 > 40）", d2 > 40,
          "diff=%d" % d2)
    check("A4b 远处格子零差异（不是整窗重绘造成的假差异）", df == 0,
          "diff=%d" % df)


# --------------------------------------------------------------- A5–A7
def part_guard(app):
    rpp = grid_flow.rows_per_page()
    # ---------- A5 页内夹紧：2×2 拖到页底不多出一行 ----------
    st = make_state([clock(col=3, row=rpp - 2, span=(2, 2))])
    w = new_window(app, st)
    lo, hi = grid_flow.page_row_range(grid_flow.current_page(), rpp, 1)
    gp = cell_global(w, 3, rpp - 1)           # 顶到页底
    w._on_widget_hover("clock1", gp.x(), gp.y())
    rect = set(w._widget_preview_rect or set())
    rows = {r for _c, r in rect}
    check("A5 预览矩形夹紧在页内（不越页底）",
          rect and min(rows) >= lo and max(rows) <= hi,
          "rows=%s page=[%s,%s]" % (sorted(rows), lo, hi))
    check("A5b 夹紧后仍是 2 行（跨度不缩水）", len(rows) == 2,
          "rows=%s" % (sorted(rows),))

    # ---------- A6 无界模式不预览 ----------
    st2 = make_state([clock(col=2, row=2, span=(2, 1))])
    st2._data["settings"]["layout_mode"] = "free"
    st2.save()
    w2 = new_window(app, st2)
    w2._widget_preview_rect = None
    w2._set_highlight(None)
    gp = cell_global(w2, 4, 4)
    w2._on_widget_hover("clock1", gp.x(), gp.y())
    check("A6 无界模式不预览（组件不占格）",
          w2._widget_preview_rect is None, "%s" % (w2._widget_preview_rect,))
    check("A6b 无界模式也不画红框", w2._hl_cell is None,
          "hl=%s" % (w2._hl_cell,))
    w2.close()

    # ---------- A7 悬浮（非锚定）组件不预览 ----------
    st3 = make_state([dict(clock(col=2, row=2, span=(2, 1)), anchored=False)])
    w3 = new_window(app, st3)
    w3._widget_preview_rect = None
    gp = cell_global(w3, 5, 5)
    w3._on_widget_hover("clock1", gp.x(), gp.y())
    check("A7 非锚定组件不预览（不占格）",
          w3._widget_preview_rect is None, "%s" % (w3._widget_preview_rect,))
    w3.close()
    w.close()


# ------------------------------------------------------------------ A8
def part_source_contract():
    src = inspect.getsource(widget_base.FloatingWidget.mouseMoveEvent)
    lines = [ln.strip() for ln in src.splitlines()]
    idx = next((i for i, ln in enumerate(lines) if "anchorHover.emit" in ln), -1)
    check("A8 悬停上报前一行是 g = self.pos()", idx > 0 and
          lines[idx - 1] == "g = self.pos()",
          "prev=%r" % (lines[idx - 1] if idx > 0 else None))
    branch = src[src.index("if self.anchored:"):]
    branch = branch[:branch.index("anchorHover.emit")]
    check("A8b anchored 分支不再用指针坐标上报",
          "globalPosition" not in branch, branch.strip().replace("\n", " ")[:60])


def main(app):
    w, st = part_highlight_state(app)
    part_paint(app, w, st)
    w.close()
    part_guard(app)
    part_source_contract()

    print("-" * 56)
    if failures:
        print("FAILED: %s" % failures)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    rc = 1
    crashed = False
    try:
        rc = main(app)
    except Exception:
        import traceback
        traceback.print_exc()
        crashed = True
    finally:
        sys.stdout.flush()
        sys.exit(1 if (crashed or rc != 0) else 0)
