# -*- coding: utf-8 -*-
"""问题反馈 5：不该自动整理布局；主动整理时也不能压到小组件。

现场：
- 拖 A 到 B 上生成文件夹 -> 松手后**其它**图标停在了拖动预览的位置
  （_on_merge 用 _clear_preview 丢弃回退，布局留在半截预览态）。
- 右键「整理布局」/ 删除 / 合并后的 compact 补位完全不看小组件占位 ->
  图标叠在时钟/便签上。
- 右键「新建文件夹 / 文本文档」走 rescan -> pack_layout -> 全体重排，
  用户眼里的"加个文件桌面就乱了一遍"。

契约：
  L1 拖到图标上合并：其余图标回到拖动前位置（不回退预览 = 自动重排）
  L2 tidy_layout 避开小组件占位（图标不落在组件格）
  L3 tidy_layout 紧凑连续、不重叠、条目不丢
  L4 compact_layout 的补位避开组件占位
  L5 rescan_desktop 默认不重排（用户布局保留），只补新增
  L6 rescan_desktop(repack=True) 才铺满（显式整理入口）
  L7 窗口 rescan_desktop 不移动既有图标

运行：python tests/test_layout_safety.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from src import appsource, grid_flow
from src.desktop_window import DesktopWindow
from src.storage import Storage

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_layout_safety_state.json"

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


def make_state(spec, widgets=()):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = True
    st._data["settings"]["takeover_desktop"] = True
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["settings"]["layout_mode"] = "grid"
    st._data["settings"]["columns"] = "auto"
    st._data["widgets"] = [dict(w) for w in widgets]
    st._data["layout"] = [
        {"id": i, "type": "app",
         "app": {"name": i, "target": i, "kind": "app"},
         "col": c, "row": r}
        for i, c, r in spec]
    st.save()
    return st


def clock(col=0, row=0):
    return {"id": "clock", "type": "clock", "w": 300, "h": 160, "hidden": False,
            "anchored": True, "col": col, "row": row}


def new_window(app, st):
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    settle(app)
    return w


def fake_scan(files):
    """替换桌面扫描：files = [(id, name)]，返回 appsource 的条目结构。"""
    def _scan():
        return [{"id": i, "name": n, "target": "C:/fake/%s" % n,
                 "kind": "file", "icon": ""} for i, n in files]
    appsource.scan_desktop_files = _scan


def main(app):
    # ---------- L1：合并前回退预览 ----------
    st = make_state([("a", 0, 0), ("b", 1, 0), ("c", 2, 0), ("d", 3, 0)])
    st.set_setting("auto_arrange", True)   # 递进模式才能让预览动到别的图标
    w = new_window(app, st)
    w._drag_entry_id = "a"
    w._drag_multi = False
    w._on_drag_started()                # 真实拖动开始时建立布局快照
    w._reflow_preview("a", (5, 0))      # 拖动中的预览：a->(5,0)，b/c/d 各前移一格
    preview = [(e["id"], e["col"], e["row"]) for e in st.layout]
    check("L1 预览已改变布局（前提）", preview !=
          [("a", 0, 0), ("b", 1, 0), ("c", 2, 0), ("d", 3, 0)], "%s" % (preview,))

    w._on_merge("a", "b")               # 松手合并到 b
    others = {e["id"]: (e["col"], e["row"]) for e in st.layout if e["id"] != "b"}
    check("L1 合并后其余图标回到拖动前位置（不留下预览态）",
          others.get("c") == (2, 0) and others.get("d") == (3, 0),
          "%s" % (others,))
    check("L1b 文件夹留在目标图标原格", ("b" in others) is False)

    # ---------- L2/L3：tidy 避让组件 ----------
    st2 = make_state([("a", 0, 0), ("b", 1, 0), ("c", 2, 0), ("d", 3, 0)],
                     widgets=[clock(0, 0)])
    grid_flow.set_grid(st2, (W, H))
    wc = grid_flow.widget_cells(st2)
    check("L2 组件占 4 格（2x2）", len(wc) == 4, "%s" % (sorted(wc),))
    st2.tidy_layout()
    overlap = [e["id"] for e in st2.layout
               if (int(e["col"]), int(e["row"])) in wc]
    check("L2 tidy 后无图标压在组件上", not overlap, "%s" % (overlap,))
    cells = [(int(e["col"]), int(e["row"])) for e in st2.layout]
    check("L3 tidy 后无重叠", len(set(cells)) == len(cells), "%s" % (cells,))
    check("L3b tidy 后条目不丢", len(st2.layout) == 4)

    # ---------- L4：compact 补位避让组件 ----------
    st4 = make_state([("a", 0, 0), ("b", 0, 0), ("c", 1, 0)],
                     widgets=[clock(0, 0)])
    grid_flow.set_grid(st4, (W, H))
    wc4 = grid_flow.widget_cells(st4)
    st4.compact_layout()
    bad = [e["id"] for e in st4.layout
           if (int(e["col"]), int(e["row"])) in wc4]
    check("L4 compact 补位不落组件格", not bad, "%s" % (bad,))

    # ---------- L5/L6：rescan 默认不重排 ----------
    st5 = make_state([("a", 5, 3), ("b", 7, 4)])
    grid_flow.set_grid(st5, (W, H))
    fake_scan([("df:x", "x.txt")])
    st5.rescan_desktop()
    pos = {e["id"]: (e["col"], e["row"]) for e in st5.layout}
    check("L5 rescan 后既有图标位置不变",
          pos.get("a") == (5, 3) and pos.get("b") == (7, 4), "%s" % (pos,))
    check("L5b 新增条目已补进布局", len(st5.layout) == 3, "%d" % len(st5.layout))

    st6 = make_state([("a", 5, 3), ("b", 7, 4)])
    grid_flow.set_grid(st6, (W, H))
    fake_scan([("df:x", "x.txt")])
    st6.rescan_desktop(repack=True)
    pos6 = {e["id"]: (e["col"], e["row"]) for e in st6.layout}
    check("L6 repack=True 才铺满（既有图标被整理）",
          pos6.get("a") != (5, 3), "%s" % (pos6,))

    # ---------- L7：窗口 rescan 不移动图标 ----------
    st7 = make_state([("a", 6, 2)])
    w7 = new_window(app, st7)
    fake_scan([("df:y", "y.txt")])
    w7.rescan_desktop()
    check("L7 窗口 rescan 后既有图标不动",
          (st7.find_entry("a")["col"], st7.find_entry("a")["row"]) == (6, 2),
          "%s" % ((st7.find_entry("a")["col"], st7.find_entry("a")["row"]),))

    w7.close()
    w.close()
    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL layout_safety PASSED")
    return 0


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    sys.exit(main(app))
