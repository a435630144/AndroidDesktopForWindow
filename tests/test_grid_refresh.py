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

    # v7c（反馈 3）：期望值必须与桌面同源——占比走 storage.resolved_icon_fit()
    # （medium = native_px/cell_w），别再自己按档位串算一份
    lay = grid_sizing.icon_layout(m.cw, m.ch, st.resolved_icon_fit(m.cw))
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
    # v7 §10.3：列数的权威键是 grid_cols + grid_dims_mode（旧键 columns 已迁移）
    check("G4 设置值已落盘（grid_cols / grid_dims_mode）",
          st2.get_setting("grid_cols") == 5
          and st2.grid_dims_mode() == "manual",
          "grid_cols=%s mode=%s" % (st2.get_setting("grid_cols"),
                                    st2.grid_dims_mode()))

    # ---------- G5：切档位 ----------
    # 2026-10-19 反馈 4：icon_match_native 默认开 —— 图标本体锁死在原生
    # 桌面边长，档位只改**格距**（cell），不把图标画小。所以这里断言的是
    # "widget = icon_layout(切档后的新 cell, 新档位)"（反解自洽），
    # 而不是用切档前的旧 cell 快照算期望（那样必然对不上）。
    m2 = grid_flow.current_metrics()
    tier_orig = st2.icon_tier()
    box_before = grid_sizing.icon_layout(m2.cw, m2.ch, tier_orig).icon_box
    dlg.cmb_tier.setCurrentIndex(dlg.cmb_tier.findData("small"))
    settle(app)
    m3 = grid_flow.current_metrics()
    lay_small = grid_sizing.icon_layout(m3.cw, m3.ch, "small")
    check("G5 切 small 档后 widget = icon_layout(新 cell, small)",
          (w2.icons["a"].width(), w2.icons["a"].height())
          == (lay_small.widget_w, lay_small.widget_h),
          "icon=%s want=%s" % ((w2.icons["a"].width(),
                                w2.icons["a"].height()),
                               (lay_small.widget_w, lay_small.widget_h)))
    # v7 §3.1 契约反转：档位只改**图标本体**，格距纹丝不动（v6 是反过来的）
    check("G5b 切档位不改格距、只改图标本体",
          m3.cw == m2.cw and m3.ch == m2.ch and lay_small.icon_box < box_before,
          "cell %dx%d->%dx%d box %d->%d" % (m2.cw, m2.ch, m3.cw, m3.ch,
                                            box_before, lay_small.icon_box))

    # ---------- G6：自动列数 ----------
    # 先切回原档位，保持与 G5 之前的档位一致（v7 起档位已不改 cell，
    # 这里只是让后续断言的上下文干净）。
    dlg.cmb_tier.setCurrentIndex(dlg.cmb_tier.findData(tier_orig))
    settle(app)
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
