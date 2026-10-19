# -*- coding: utf-8 -*-
"""问题反馈 2：调整网格尺寸（列数 / 档位 / 图标像素）后必须立即生效。

病根：设置的 `_apply_columns` / `_apply_icon_tier` 只 `window.rebuild()`，
而 rebuild 读的是 `grid_flow.current_metrics()` **旧快照**——cell / cols
没重算，图标位置与尺寸都还是老值。用户必须关掉「接管系统桌面」再打开
（走 _try_attach_once -> _update_grid_metrics）才看到变化。

契约：
  G1 window.refresh_grid() 重算快照（手动列数立即进入 GridMetrics）
  G2 refresh_grid 后图标 widget 尺寸 = 新 cell × 档位
  G3 refresh_grid 后图标位置按新格点 + 居中偏移
  G4 设置改列数（_apply_columns）立即重算，无需重开接管
  G5 设置切档位（_apply_icon_tier）立即换图标尺寸
  G6 自动列数开关（_apply_auto_columns）恢复到按屏幕铺满
  G7 组件层收到布局模式刷新（widget_layer.apply_layout_mode）

运行：python tests/test_grid_refresh.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from src import grid_flow, grid_sizing
from src.desktop_window import DesktopWindow
from src.settings_dialog import SettingsDialog
from src.storage import Storage

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_grid_refresh_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=80):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make_state(settings=None):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = True
    st._data["settings"]["takeover_desktop"] = True
    st._data["settings"]["auto_clone_desktop"] = False
    for k, v in (settings or {}).items():
        st._data["settings"][k] = v
    st._data["widgets"] = []
    st._data["layout"] = [
        {"id": "a", "type": "app",
         "app": {"name": "a", "target": "a", "kind": "app"}, "col": 0, "row": 0},
        {"id": "b", "type": "app",
         "app": {"name": "b", "target": "b", "kind": "app"}, "col": 1, "row": 0},
    ]
    st.save()
    return st


def new_window(app, st):
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    settle(app)
    return w


class FakeLayer:
    def __init__(self):
        self.applied = 0

    def apply_layout_mode(self):
        self.applied += 1

    def sync_page(self, page):
        pass


def main(app):
    # ---------- G1-G3：refresh_grid 的窗口级契约 ----------
    st = make_state({"columns": "auto"})
    w = new_window(app, st)
    auto_cols = grid_flow.current_metrics().cols
    check("G0 自动列数已就绪", auto_cols > 2, "cols=%d" % auto_cols)

    st.set_setting("columns", 6)          # 直接落盘，不经过设置对话框
    w.refresh_grid()
    settle(app)
    m = grid_flow.current_metrics()
    check("G1 refresh_grid 后 cols = 手动值 6", m.cols == 6, "cols=%d" % m.cols)

    lay = grid_sizing.icon_layout(m.cw, m.ch, st.icon_tier())
    icon = w.icons["a"]
    check("G2 图标尺寸 = 新 cell × 档位",
          (icon.width(), icon.height()) == (lay.widget_w, lay.widget_h),
          "icon=%s want=%s" % ((icon.width(), icon.height()),
                               (lay.widget_w, lay.widget_h)))
    dx, dy = grid_flow.icon_center_offset(st)
    want = (m.ox + dx, m.oy + dy)
    check("G3 图标位置按新格点 + 居中偏移",
          (icon.pos().x(), icon.pos().y()) == want,
          "got=%s want=%s" % ((icon.pos().x(), icon.pos().y()), want))

    # ---------- G4：设置对话框改列数 -> 立即生效 ----------
    st2 = make_state({"columns": 8})
    w2 = new_window(app, st2)
    dlg = SettingsDialog(w2, st2, None)
    before_cols = grid_flow.current_metrics().cols
    dlg.chk_auto_cols.setChecked(False)   # 手动模式
    dlg.spin_cols.setValue(5)
    settle(app)
    after_cols = grid_flow.current_metrics().cols
    check("G4 改列数立即重算（无需重开接管）",
          after_cols == 5 and after_cols != before_cols,
          "before=%s after=%s" % (before_cols, after_cols))
    check("G4 设置值已落盘", st2.get_setting("columns") == 5,
          "%s" % (st2.get_setting("columns"),))

    # ---------- G5：切档位 -> 立即换尺寸 ----------
    m2 = grid_flow.current_metrics()
    dlg.cmb_tier.setCurrentIndex(dlg.cmb_tier.findData("small"))
    settle(app)
    lay_small = grid_sizing.icon_layout(m2.cw, m2.ch, "small")
    check("G5 切 small 档后图标立刻变小",
          (w2.icons["a"].width(), w2.icons["a"].height())
          == (lay_small.widget_w, lay_small.widget_h),
          "%s" % ((w2.icons["a"].width(), w2.icons["a"].height()),))

    # ---------- G6：自动列数 ----------
    dlg.chk_auto_cols.setChecked(True)
    settle(app)
    check("G6 自动列数恢复屏幕铺满",
          grid_flow.current_metrics().cols == auto_cols,
          "%s vs %s" % (grid_flow.current_metrics().cols, auto_cols))

    # ---------- G7：组件层联动 ----------
    layer = FakeLayer()
    w3 = new_window(app, make_state({"columns": "auto"}))
    w3._widget_layer = layer
    w3.refresh_grid()
    check("G7 refresh_grid 通知组件层", layer.applied >= 1,
          "applied=%d" % layer.applied)

    dlg.close()
    w3.close()
    w2.close()
    w.close()
    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL grid_refresh PASSED")
    return 0


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    sys.exit(main(app))
