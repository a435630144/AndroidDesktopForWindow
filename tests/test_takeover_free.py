# -*- coding: utf-8 -*-
"""问题反馈 3：隐藏桌面但不接管时，应进入无界模式（小组件自由排布）。

现场：把「接管系统桌面」关掉后，原生桌面图标恢复可见，但整理窗口仍按
网格模式强制对齐——两套图标叠在一起、组件也被网格钉死，用户要的是
「这时像普通悬浮层一样自由摆放」。

契约：
  F1 未接管（takeover=False）时 free_mode 为 True（即使 layout_mode=grid）
  F2 接管开启 + layout_mode=grid -> free_mode False（网格语义保留）
  F3 layout_mode=free 时接管与否都自由
  F4 未接管时 entry_pos 走 fx/fy（懒生成），不被网格钉住
  F5 未接管时 compact_layout 不重排（无界语义：位置在 fx/fy）
  F6 窗口 _widget_cells 为空（组件不再占格挤图标）
  F7 未接管时切「网格模式」自动接管（网格必须由接管承载，否则双套图标）
  F8 未接管时 tidy_layout 空转（无网格可铺）

运行：python tests/test_takeover_free.py   （offscreen）
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

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_takeover_free_state.json"

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


def make_state(takeover=False):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = takeover
    st._data["settings"]["takeover_desktop"] = takeover
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["settings"]["layout_mode"] = "grid"
    st._data["layout"] = [
        {"id": "a", "type": "app",
         "app": {"name": "a", "target": "a", "kind": "app"}, "col": 0, "row": 0},
        {"id": "b", "type": "app",
         "app": {"name": "b", "target": "b", "kind": "app"}, "col": 1, "row": 0},
    ]
    st._data["widgets"] = [
        {"id": "clock", "type": "clock", "w": 300, "h": 160, "hidden": False,
         "anchored": True, "col": 5, "row": 0},
    ]
    st.save()
    return st


def new_window(app, st):
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    settle(app)
    return w


def main(app):
    # ---------- F1-F3：判定表 ----------
    st_off = make_state(takeover=False)
    grid_flow.set_grid(st_off, (W, H))
    check("F1 未接管 + layout_mode=grid -> free", grid_flow.free_mode(st_off) is True)
    check("F1b layout_mode 设置值没被改写（仍是 grid）",
          grid_flow.layout_mode(st_off) == "grid", grid_flow.layout_mode(st_off))

    st_on = make_state(takeover=True)
    grid_flow.set_grid(st_on, (W, H))
    check("F2 接管 + grid -> 网格", grid_flow.free_mode(st_on) is False)
    st_on.set_setting("layout_mode", "free")
    check("F3 接管 + free -> 自由", grid_flow.free_mode(st_on) is True)

    # ---------- F4：未接管时不吸附网格 ----------
    e = st_off.find_entry("a")
    x, y = grid_flow.entry_pos(st_off, e)
    check("F4 未接管时坐标来自 fx/fy（已懒生成）", ("fx" in e and "fy" in e),
          "%s" % ({k: e.get(k) for k in ("fx", "fy")},))
    e["fx"], e["fy"] = 137, 246
    check("F4b 任意像素位生效（不被网格改写）",
          grid_flow.entry_pos(st_off, e) == (137, 246),
          "%s" % (grid_flow.entry_pos(st_off, e),))

    # ---------- F5/F8：不重排 ----------
    e2 = st_off.find_entry("b")
    e2["col"], e2["row"] = 0, 0        # 人为制造重叠
    st_off.compact_layout()
    check("F5 未接管时 compact 不重排（位置在 fx/fy）",
          (e2["col"], e2["row"]) == (0, 0), "%s" % ((e2["col"], e2["row"]),))
    st_off.tidy_layout()
    check("F8 未接管时 tidy 空转", (e2["col"], e2["row"]) == (0, 0),
          "%s" % ((e2["col"], e2["row"]),))

    # ---------- F6：组件不占格 ----------
    w = new_window(app, make_state(takeover=False))
    check("F6 未接管时 _widget_cells 为空", w._widget_cells() == set(),
          "%s" % (sorted(w._widget_cells())[:5],))

    # ---------- F7：切网格自动接管 ----------
    st7 = make_state(takeover=False)
    w7 = new_window(app, st7)
    w7.set_layout_mode("grid")
    check("F7 未接管切网格 -> 自动开启接管",
          st7.takeover() is True, "%s" % st7.takeover())
    check("F7b 有效模式变回网格", grid_flow.free_mode(st7) is False)

    w7.close()
    w.close()
    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL takeover_free PASSED")
    return 0


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    sys.exit(main(app))
