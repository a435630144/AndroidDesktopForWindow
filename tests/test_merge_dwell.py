# -*- coding: utf-8 -*-
"""问题反馈 4：拖到图标上时目标被瞬间挤走，来不及看到「松手合并为文件夹」。

病根（两层）：
1. `AppIcon.dragMoveEvent` 在 dwell（450ms）未到期时把悬停上报给主窗口，
   主窗口 `_reflow_preview` 立即把目标图标让位/交换走——指针下的图标消失，
   `dragLeave` 触发，dwell 归零，合并提示永远不出现。
2. `_reflow_preview` 对「目标格被别的图标占用」也照样预览交换，同样会让
   目标弹走。

契约：
  D1 悬停在另一个图标上（dwell 未到期）不上报 reflowHover
  D2 dwell 已武装时不上报（原行为保留）
  D3 未武装松手仍走 reflowDrop（快速拖到图标上 = 让位/交换）
  D4 窗口 _reflow_preview：目标格被非拖动条目占用时不动布局
  D5 目标格为空时照常让位预览（回归：让位不能整体失效）
  D6 dwell 时长足够看清提示（300~400ms）且推让留出 >=100ms 余量
  D7 拖动经过图标（dragMove 数次）后目标格占用者位置不变

运行：python tests/test_merge_dwell.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QMimeData, QPoint, QPointF, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from src import grid_flow
from src.desktop_window import DesktopWindow
from src.iconwidget import MIME_TYPE, AppIcon, DWELL_MERGE_MS
from src.storage import Storage

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_merge_dwell_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=60):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make_state(spec):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = True
    st._data["settings"]["takeover_desktop"] = True
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["settings"]["layout_mode"] = "grid"
    st._data["widgets"] = []
    st._data["layout"] = [
        {"id": i, "type": "app",
         "app": {"name": i, "target": i, "kind": "app"},
         "col": c, "row": r}
        for i, c, r in spec]
    st.save()
    return st


class FakeDragEvent:
    """dragMoveEvent/dropEvent 只用 mimeData()/position()/acceptProposedAction()。

    PySide6 的 QDragMoveEvent 构造签名跨版本不稳（构造出来是裸 QObject），
    这里用 duck typing 桩，语义等价且不依赖 Qt 版本。
    """

    def __init__(self, payload: str, pos=QPoint(20, 20)):
        self._md = QMimeData()
        self._md.setData(MIME_TYPE, payload.encode())
        self._pos = pos

    def mimeData(self):
        return self._md

    def position(self):
        # Qt 6 的 QDropEvent.position() 是 QPointF（调用方会 .toPoint()）
        return QPointF(self._pos)

    def acceptProposedAction(self):
        pass


def drag_event(payload: str, pos=QPoint(20, 20)):
    return FakeDragEvent(payload, pos)


def main(app):
    # ---------- D1/D2/D3：图标层的上报纪律 ----------
    entry_b = {"id": "b", "type": "app",
               "app": {"name": "b", "target": "b", "kind": "app"},
               "col": 1, "row": 0}
    host = QWidget()
    icon = AppIcon(entry_b, 72, parent=host, chrome_scale=1.0)
    icon._drag_mime = None
    got = {"hover": 0, "drop": 0}
    icon.reflowHover.connect(lambda *a: got.__setitem__("hover", got["hover"] + 1))
    icon.reflowDrop.connect(lambda *a: got.__setitem__("drop", got["drop"] + 1))

    icon._merge_armed = False
    ev = drag_event("a")
    icon.dragMoveEvent(ev)
    check("D1 dwell 未到期：不上报 reflowHover（目标不弹走）",
          got["hover"] == 0, "hover=%d" % got["hover"])

    icon._merge_armed = True
    icon.dragMoveEvent(drag_event("a"))
    check("D2 dwell 已武装：不上报（原行为）", got["hover"] == 0,
          "hover=%d" % got["hover"])

    icon._merge_armed = False
    icon.dropEvent(drag_event("a"))
    check("D3 未武装松手仍走 reflowDrop（快速拖 = 让位）",
          got["drop"] == 1, "drop=%d" % got["drop"])
    # v7e 反馈 1：450 缩到 350（提示更早出现），同时推让 470 留 120ms 余量
    check("D6 dwell 300~400ms（够看清合并提示）",
          300 <= DWELL_MERGE_MS <= 400, "%dms" % DWELL_MERGE_MS)

    # ---------- D4/D5/D7：窗口层不再抢走占用者 ----------
    st = make_state([("a", 0, 0), ("b", 1, 0), ("c", 3, 0)])
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    settle(app)

    b_pos_before = (st.find_entry("b")["col"], st.find_entry("b")["row"])
    w._drag_entry_id = "a"
    w._drag_multi = False
    w._reflow_preview("a", (1, 0))          # 指针在 b 的格子上
    b_pos_after = (st.find_entry("b")["col"], st.find_entry("b")["row"])
    check("D4 目标格被占用：预览不动布局（b 留在原格）",
          b_pos_after == b_pos_before, "%s -> %s" % (b_pos_before, b_pos_after))
    check("D4b 拖动条目预览也没落位", (st.find_entry("a")["col"],
                                       st.find_entry("a")["row"]) == (0, 0))

    w._reflow_preview("a", (2, 0))          # 空格
    check("D5 空格照常让位（a 预览到空格）",
          (st.find_entry("a")["col"], st.find_entry("a")["row"]) == (2, 0),
          "%s" % ((st.find_entry("a")["col"], st.find_entry("a")["row"]),))

    # D7：连续经过图标格子，占用者不动
    st2 = make_state([("a", 0, 0), ("b", 1, 0), ("c", 2, 0)])
    w2 = DesktopWindow(st2)
    w2.resize(W, H)
    w2._update_grid_metrics()
    settle(app)
    w2._drag_entry_id = "a"
    snap = [(e["id"], e["col"], e["row"]) for e in st2.layout]
    for col in (1, 2, 1):
        w2._reflow_preview("a", (col, 0))
    after = [(e["id"], e["col"], e["row"]) for e in st2.layout]
    check("D7 连续经过占用格：其余图标位置不变",
          [x for x in after if x[0] != "a"] == [x for x in snap if x[0] != "a"],
          "%s vs %s" % (after, snap))

    icon.deleteLater()
    host.deleteLater()
    w2.close()
    w.close()
    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL merge_dwell PASSED")
    return 0


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    sys.exit(main(app))
