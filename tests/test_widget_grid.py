# -*- coding: utf-8 -*-
"""v6 批次 C §6.1：组件入网格——锚定 notes/panel 的 span 落位与绘制。

覆盖指导文档_网格与无界双模式_v6.md §6.1（反馈 7b 前半）：
  P1 锚定便签 spawn 在 2×2 span 尺寸 + cell_pos 位置（视觉 = 占位）
  P2 锚定面板 spawn 在 3×4 span 尺寸（旧 340×460 最小值不再挡 span）
  P3 面板 3×4 下 render 不抛且画布非空（内容自适应：按钮网格 + 滚动区）
  P4 便签 2×2 下 render 不抛且画布非空
  P5 widget_cells：notes 2×2 / panel 3×4 精确展开（图标避让依据）
  P1b/P2b 落点无幻影占位：未定位组件不占 (0,0)，首组件落 (0,0)、
         次组件紧随其右不被推远

运行：python tests/test_widget_grid.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.storage import Storage
from src.widget_layer import WidgetLayer

STATE = Path(tempfile.gettempdir()) / "test_widget_grid_state.json"

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
    st._data["settings"]["hide_native_icons"] = False
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["widgets"] = [dict(w) for w in widgets]
    st._data["layout"] = []
    st.save()
    return st


def render_nonempty(w) -> int:
    img = w.grab().toImage()
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() > 8:
                n += 1
    return n


def main(app):
    st = make_state([
        {"id": "note1", "type": "notes", "w": 300, "h": 300,
         "hidden": False, "anchored": True, "text": "你好"},
        {"id": "panel1", "type": "panel", "w": 400, "h": 620,
         "hidden": False, "anchored": True},
    ])
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)
    layer = WidgetLayer(st)
    settle(app, 300)
    cw, ch = grid_flow.cell_size(st)
    ox, oy = grid_flow.origin()

    note = layer.widgets.get("note1")
    panel = layer.widgets.get("panel1")
    check("P0 两个锚定组件都已创建", note is not None and panel is not None)

    if note is not None:
        # ---------- P1：便签 2×2 ----------
        check("P1 便签 entry span = 2×2",
              (st.widgets[0].get("colspan"), st.widgets[0].get("rowspan")) == (2, 2))
        check("P1 便签尺寸 = 2×2 cell（视觉 = 占位）",
              (note.width(), note.height()) == (2 * cw, 2 * ch),
              "got=%s want=%s" % ((note.width(), note.height()), (2 * cw, 2 * ch)))
        nc, nr = int(st.widgets[0]["col"]), int(st.widgets[0]["row"])
        check("P1 便签位置 = cell_pos(col,row)",
              (note.pos().x(), note.pos().y()) == grid_flow.cell_pos(st, nc, nr),
              "pos=%s" % (note.pos(),))
        check("P1b 首个组件落 (0,0)（未定位组件不产生幻影占位）",
              (nc, nr) == (0, 0), "cell=%s" % ((nc, nr),))
        n = render_nonempty(note)
        check("P4 便签 2×2 render 非空", n > 200, "opaque=%d" % n)

    if panel is not None:
        # ---------- P2：面板 3×4 ----------
        check("P2 面板 entry span = 3×4",
              (st.widgets[1].get("colspan"), st.widgets[1].get("rowspan")) == (3, 4))
        check("P2 面板尺寸 = 3×4 cell（旧 340×460 最小值不挡 span）",
              (panel.width(), panel.height()) == (3 * cw, 4 * ch),
              "got=%s want=%s" % ((panel.width(), panel.height()), (3 * cw, 4 * ch)))
        pc, pr = int(st.widgets[1]["col"]), int(st.widgets[1]["row"])
        check("P2 面板位置 = cell_pos(col,row)",
              (panel.pos().x(), panel.pos().y()) == grid_flow.cell_pos(st, pc, pr),
              "pos=%s" % (panel.pos(),))
        check("P2b 面板紧随便签右侧 (2,0)（幻影不把自己推去远处）",
              (pc, pr) == (2, 0), "cell=%s" % ((pc, pr),))
        n = render_nonempty(panel)
        check("P3 面板 3×4 render 非空", n > 400, "opaque=%d" % n)

    # ---------- P5：占位展开（图标避让依据） ----------
    cells = grid_flow.widget_cells(st)
    want = set()
    for w in st.widgets:
        cs, rs = grid_flow.widget_span(st, w)
        c, r = int(w["col"]), int(w["row"])
        want |= {(c + dc, r + dr) for dc in range(cs) for dr in range(rs)}
    check("P5 widget_cells 按 span 精确展开（2×2 + 3×4 = 16 格）",
          cells == want and len(cells) == 16, "%s" % sorted(cells))

    for w in layer.widgets.values():
        w.close()
    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL widget_grid PASSED")
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
    finally:
        try:
            STATE.unlink()
        except Exception:
            pass
    return code


if __name__ == "__main__":
    sys.exit(run_main())
