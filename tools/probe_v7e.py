# -*- coding: utf-8 -*-
"""诊断探针（v7e 反馈 2/3）：无界模式下组件右键菜单 / 切回网格后的组件坐标。

只读观察 + 内存态实验，不启动真实接管、不动用户桌面。
运行：QT_QPA_PLATFORM=offscreen python tools/probe_v7e.py
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
from src.desktop_window import DesktopWindow
from src.storage import Storage
from src.widget_layer import WidgetLayer

STATE = Path(tempfile.gettempdir()) / "probe_v7e_state.json"


def settle(app, ms=300):
    loop = QEventLoop()
    t = QTimer()
    t.setSingleShot(True)
    t.timeout.connect(loop.quit)
    t.start(ms)
    loop.exec()


def new_state():
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"].update({
        "hide_native_icons": False,
        "auto_clone_desktop": False,
        "layout_mode": "grid",
        "takeover_desktop": True,
        "widgets_only": False,
    })
    st._data["layout"] = [
        {"id": "a%d" % i, "type": "app", "name": "A%d" % i,
         "col": i % 6, "row": i // 6} for i in range(12)
    ]
    st._data["widgets"] = [
        {"id": "note1", "type": "notes", "w": 300, "h": 300,
         "hidden": False, "anchored": True, "text": "hi"},
    ]
    st.save()
    return st


def main(app):
    st = new_state()
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)
    w = DesktopWindow(st)
    w.show()
    layer = WidgetLayer(st)
    w.set_widget_layer(layer)
    settle(app, 300)

    note_entry = st.widgets[0]
    print("网格态: anchored=%s col/row=%s span=%s" % (
        note_entry.get("anchored"), (note_entry.get("col"), note_entry.get("row")),
        (note_entry.get("colspan"), note_entry.get("rowspan"))))
    note = layer.widgets.get("note1")
    print("  窗口 pos=%s size=%s" % (note.pos() if note else None,
                                    (note.width(), note.height()) if note else None))

    # 切无界
    w.set_layout_mode("free")
    settle(app, 400)
    note = layer.widgets.get("note1")
    print("\n无界态: free_mode=%s" % grid_flow.free_mode(st))
    print("  entry: col/row=%s fx/fy=%s fpage=%s anchored=%s" % (
        (note_entry.get("col"), note_entry.get("row")),
        (note_entry.get("fx"), note_entry.get("fy")),
        note_entry.get("fpage"), note_entry.get("anchored")))
    print("  窗口 pos=%s size=%s anchored=%s" % (
        note.pos() if note else None,
        (note.width(), note.height()) if note else None,
        getattr(note, "anchored", None)))
    if note is not None:
        menu = note._build_context_menu()
        print("  右键菜单: %s" % [a.text() for a in menu.actions()])

    # 模拟无界拖动松手：move 到像素位再 _save_geom_free
    if note is not None:
        note.move(700, 420)
        note._save_geom_free()
        settle(app, 120)
        print("\n无界拖到 (700,420) 松手后 entry: col/row=%s fx/fy=%s fpage=%s" % (
            (note_entry.get("col"), note_entry.get("row")),
            (note_entry.get("fx"), note_entry.get("fy")), note_entry.get("fpage")))

    # 切回网格
    w.set_layout_mode("grid")
    settle(app, 400)
    note = layer.widgets.get("note1")
    cw, ch = grid_flow.cell_size(st)
    print("\n切回网格: col/row=%s 窗口 pos=%s" % (
        (note_entry.get("col"), note_entry.get("row")), note.pos() if note else None))
    print("  期望落点（按 fx/fy 反算）: %s" % (
        grid_flow.pos_cell(st, 700, 420),))
    cells = grid_flow.widget_cells(st)
    icons_in = [(e["id"], e.get("col"), e.get("row")) for e in st.layout
                if (e.get("col"), e.get("row")) in cells]
    print("  组件占格=%s 与图标重叠=%s" % (sorted(cells), icons_in))

    w.close()
    layer.close() if hasattr(layer, "close") else None


if __name__ == "__main__":
    app = QApplication(sys.argv)
    main(app)
