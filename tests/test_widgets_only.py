# -*- coding: utf-8 -*-
"""仅小组件模式（2026-10-21 用户反馈 9）。

用户原话：「问题9：启动默认接管桌面+小组件；设置加苹果风『仅小组件
模式』开关；移除托盘右键的『小组件模式/显示桌面模式』；仅小组件时全部
组件无界并只显示组件。」

契约：
  W1  存储默认：widgets_only=False；启动默认 = 接管桌面 + 显示小组件
  W2  开（网格起步）→ 记住原模式、切无界（组件无界）、图标全隐藏、
      接管不变（原生图标仍隐藏）、组件层按新模式重建
  W3  开（本就无界）→ 模式不变、prev=free
  W4  关 → 恢复原布局模式、图标回来
  W5  关（prev=free）→ 仍无界、图标回来
  W6  仅小组件期间拒绝切网格（set_layout_mode 护栏）
  W7  绘制门控：仅小组件下不画页点 / 空态提示
  W8  托盘：无「小组件模式 / 显示原生桌面」；布局入口仅平时有；
      双击托盘仍可切换窗口显隐
  W9  桌面右键：无「小组件模式」；仅小组件下无布局切换 / 空白页入口
  W10 设置页：「仅小组件模式」苹果风 Switch；开 → 通知窗口；
      仅小组件下关「显示桌面小组件」→ 自动退出该模式
  W11 持久化往返：开 / 关之后存盘重载，模式与开关都对

运行：python tests/test_widgets_only.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QRect, QTimer
from PySide6.QtGui import QPaintEvent
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from src import grid_flow
from src.desktop_window import DesktopWindow
from src.storage import Storage
from src.settings_dialog import SettingsDialog, Switch
from src.tray import SystemTray

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_widgets_only_state.json"
failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=150):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make_state(widgets=(), icons=3, layout_mode="grid"):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"].update({
        "hide_native_icons": False,
        "auto_clone_desktop": False,
        "takeover_desktop": True,
        "show_widgets": True,
        "layout_mode": layout_mode,
        "dev_mode": False,
    })
    st._data["widgets"] = [dict(w) for w in widgets]
    st._data["layout"] = [
        {"id": "e%d" % i, "type": "app", "col": 6 + i, "row": 6,
         "app": {"name": "i%d" % i, "target": "i%d" % i, "kind": "app"}}
        for i in range(icons)]
    st.save()
    return st


def clock(id_="clock1", col=0, row=0):
    return {"id": id_, "type": "clock", "w": 300, "h": 300, "hidden": False,
            "anchored": True, "col": col, "row": row,
            "colspan": 2, "rowspan": 2}


def new_window(app, st):
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    w.rebuild()
    w.show()
    settle(app, 120)
    return w


def reload_state():
    return Storage(path=str(STATE))


class FakeLayer:
    """WidgetLayer 的最小面：只记录 apply_layout_mode / set_visible。"""

    def __init__(self):
        self.modes = 0
        self.visible_calls = []

    def apply_layout_mode(self):
        self.modes += 1

    def set_visible(self, on):
        self.visible_calls.append(bool(on))

    def add_note(self):
        pass

    def toggle_entry(self, eid, checked):
        pass


class _Sig:
    def __init__(self):
        self.slots = []

    def connect(self, fn):
        self.slots.append(fn)

    def emit(self, *a):
        for fn in self.slots:
            fn(*a)


class FakeWin:
    """托盘 / 设置对话框需要的窗口面（可记录 set_widgets_only）。"""

    def __init__(self, storage):
        self.storage = storage
        self.attached = True
        self.visible = True
        self.rebuilt = 0
        self.widgets_only_calls = []
        self.visibilityChanged = _Sig()

    def set_widgets_only(self, on):
        self.widgets_only_calls.append(bool(on))
        self.storage.set_setting("widgets_only", bool(on))

    def rebuild(self, stagger=False):
        self.rebuilt += 1

    def isVisible(self):
        return self.visible

    def toggle(self):
        self.visible = not self.visible
        return self.visible

    def show_desktop(self):
        self.visible = True
        return True

    def rescan_desktop(self):
        return (0, 0)


def action_texts(menu):
    return [a.text() for a in menu.actions()]


def main(app):
    # ---------- W1 存储默认 ----------
    st1 = make_state()
    check("W1 widgets_only 默认关闭",
          st1.get_setting("widgets_only") is False,
          "val=%s" % (st1.get_setting("widgets_only"),))
    check("W1 启动默认接管桌面", st1.takeover() is True)
    check("W1 启动默认显示小组件", st1.get_setting("show_widgets") is True)

    # ---------- W2 开（网格起步） ----------
    st = make_state([clock()], icons=3)
    w = new_window(app, st)
    layer = FakeLayer()
    w.set_widget_layer(layer)
    check("W2 起步是网格模式", grid_flow.free_mode(st) is False)
    w.set_widgets_only(True)
    check("W2 开仅小组件 → 切无界（组件无界）", grid_flow.free_mode(st) is True)
    check("W2 原模式已记住", st.get_setting("widgets_only_prev_mode") == "grid",
          "prev=%s" % (st.get_setting("widgets_only_prev_mode"),))
    check("W2 图标全部隐藏", len(w.icons) == 0, "icons=%d" % len(w.icons))
    check("W2 接管不变（原生图标仍隐藏）", st.takeover() is True)
    check("W2 组件层按新模式重建", layer.modes >= 1, "modes=%d" % layer.modes)
    check("W2 重复开是 no-op", (w.set_widgets_only(True),
                                grid_flow.free_mode(st))[1] is True)

    # ---------- W6 仅小组件期间拒绝切网格 ----------
    w.set_layout_mode("grid")
    check("W6 仅小组件期间拒绝切网格", grid_flow.free_mode(st) is True)

    # ---------- W7 绘制门控 ----------
    st7 = make_state([], icons=0)
    w7 = new_window(app, st7)
    calls = {"dots": 0, "hint": 0}
    w7._paint_dots = lambda: calls.__setitem__("dots", calls["dots"] + 1)
    w7._paint_empty_hint = lambda ev: calls.__setitem__(
        "hint", calls["hint"] + 1)
    w7.attached = True      # 空态提示只画在挂载分支（融入桌面的那条路）
    w7.paintEvent(QPaintEvent(QRect(0, 0, 10, 10)))
    check("W7 平时：空态提示画", calls["hint"] == 1, "%s" % calls)
    check("W7 平时：页点画", calls["dots"] == 1, "%s" % calls)
    w7.set_widgets_only(True)
    w7.paintEvent(QPaintEvent(QRect(0, 0, 10, 10)))
    check("W7 仅小组件：空态提示不画", calls["hint"] == 1, "%s" % calls)
    check("W7 仅小组件：页点不画", calls["dots"] == 1, "%s" % calls)

    # ---------- W9 桌面右键 ----------
    st9 = make_state([clock()], icons=3)
    w9 = new_window(app, st9)
    texts = action_texts(w9._build_context_menu())
    check("W9 右键无「小组件模式」", "小组件模式" not in texts,
          "%s" % texts)
    check("W9 平时有布局切换入口", any("切换到" in t for t in texts),
          "%s" % texts)
    w9.set_widgets_only(True)
    texts2 = action_texts(w9._build_context_menu())
    check("W9 仅小组件下无布局切换",
          not any("切换到" in t for t in texts2), "%s" % texts2)
    check("W9 仅小组件下无空白页入口",
          not any("空白页" in t for t in texts2), "%s" % texts2)

    # ---------- W11 持久化往返 ----------
    st11 = make_state([clock()], icons=3)
    w11 = new_window(app, st11)
    w11.set_widgets_only(True)
    r1 = reload_state()
    check("W11 重载后仅小组件仍开", r1.get_setting("widgets_only") is True)
    check("W11 重载后仍是无界", grid_flow.free_mode(r1) is True)
    check("W11 重载后记得原模式",
          r1.get_setting("widgets_only_prev_mode") == "grid")
    w11.set_widgets_only(False)
    r2 = reload_state()
    check("W11 关后重载恢复网格", grid_flow.free_mode(r2) is False)
    check("W11 关后重载 widgets_only 已关",
          r2.get_setting("widgets_only") is False)

    # ---------- W4 / W5 关：恢复模式与图标 ----------
    st4 = make_state([clock()], icons=3)
    w4 = new_window(app, st4)
    w4.set_widgets_only(True)
    w4.set_widgets_only(False)
    check("W4 关 → 恢复网格", grid_flow.free_mode(st4) is False)
    check("W4 图标回来", len(w4.icons) == 3, "icons=%d" % len(w4.icons))
    check("W4 图标按网格坐标落位",
          sorted(w4.icons) == ["e0", "e1", "e2"])

    st5 = make_state([clock()], icons=3, layout_mode="free")
    w5 = new_window(app, st5)
    w5.set_widgets_only(True)
    check("W3 本就无界时开：模式不变", grid_flow.free_mode(st5) is True)
    check("W3 prev 记为 free", st5.get_setting("widgets_only_prev_mode") == "free",
          "prev=%s" % (st5.get_setting("widgets_only_prev_mode"),))
    w5.set_widgets_only(False)
    check("W5 关（prev=free）→ 仍无界", grid_flow.free_mode(st5) is True)
    check("W5 图标回来", len(w5.icons) == 3, "icons=%d" % len(w5.icons))

    # ---------- W8 托盘 ----------
    st8 = make_state([clock()], icons=0)
    fw8 = FakeWin(st8)
    t = SystemTray(fw8, st8, layer=FakeLayer())
    check("W8 托盘无「显示原生桌面」入口", not hasattr(t, "act_toggle"))
    check("W8 托盘无「小组件模式」入口", not hasattr(t, "act_widgets"))
    texts8 = action_texts(t.menu)
    check("W8 菜单里没有这两个条目",
          "小组件模式" not in texts8 and "显示原生桌面" not in texts8,
          "%s" % texts8)
    check("W8 布局切换入口平时在",
          hasattr(t, "act_layout") and "切换到" in t.act_layout.text(),
          "%s" % texts8)
    check("W8 小组件子菜单仍在", hasattr(t, "widget_menu"))
    fw8.visible = True
    t._on_activated(QSystemTrayIcon.DoubleClick)
    check("W8 双击托盘仍切换显隐", fw8.visible is False)
    st8.set_setting("widgets_only", True)
    t._build_menu()
    texts8b = action_texts(t.menu)
    check("W8 仅小组件下托盘无布局切换",
          not any("切换到" in x for x in texts8b), "%s" % texts8b)
    t.tray.hide()
    t.menu.deleteLater()

    # ---------- W10 设置页 ----------
    st10 = make_state([clock()], icons=3)
    fw10 = FakeWin(st10)
    dlg = SettingsDialog(fw10, st10, layer=FakeLayer())
    check("W10 设置页有「仅小组件模式」开关", hasattr(dlg, "chk_widgets_only"))
    check("W10 是苹果风 Switch", isinstance(dlg.chk_widgets_only, Switch))
    check("W10 默认未勾选", dlg.chk_widgets_only.isChecked() is False)
    dlg.chk_widgets_only.setChecked(True)
    app.processEvents()
    check("W10 开 → 写入设置", st10.get_setting("widgets_only") is True)
    check("W10 开 → 通知窗口", fw10.widgets_only_calls == [True],
          "%s" % fw10.widgets_only_calls)
    fw10.widgets_only_calls.clear()
    dlg.chk_widgets.setChecked(False)
    app.processEvents()
    check("W10 仅小组件下关小组件 → 自动退出该模式",
          st10.get_setting("widgets_only") is False)
    check("W10 自动退出也通知窗口", fw10.widgets_only_calls == [False],
          "%s" % fw10.widgets_only_calls)
    check("W10 开关同步回落", dlg.chk_widgets_only.isChecked() is False)
    dlg.deleteLater()

    # ---------- W12 空桌面死局防护 ----------
    # 顺序反过来：先关「显示桌面小组件」再开「仅小组件模式」——组件开关
    # 必须跟着开，否则桌面什么都不剩。
    st12 = make_state([clock()], icons=3)
    st12.set_setting("show_widgets", False)
    fw12 = FakeWin(st12)
    dlg12 = SettingsDialog(fw12, st12, layer=FakeLayer())
    dlg12.chk_widgets_only.setChecked(True)
    app.processEvents()
    check("W12 先关组件再开仅小组件 → 组件开关跟着开",
          st12.get_setting("show_widgets") is True)
    check("W12 不会出现空桌面", st12.get_setting("widgets_only") is True)
    check("W12 设置窗开关态同步", dlg12.chk_widgets.isChecked() is True)
    dlg12.deleteLater()

    # 窗口侧护栏（非对话框入口）：同样不能开出空桌面
    st12b = make_state([clock()], icons=3)
    st12b.set_setting("show_widgets", False)
    w12b = new_window(app, st12b)
    layer12 = FakeLayer()
    w12b.set_widget_layer(layer12)
    w12b.set_widgets_only(True)
    check("W12b 窗口侧护栏：组件开关跟着开",
          st12b.get_setting("show_widgets") is True)
    check("W12b 组件层已置为可见",
          layer12.visible_calls and layer12.visible_calls[-1] is True,
          "%s" % layer12.visible_calls)

    # 存储层兜底：手改出 widgets_only + show_widgets=False，加载时自愈
    st12b.set_setting("widgets_only", True)
    st12b.set_setting("show_widgets", False)
    st12b.set_setting("widgets_only_prev_mode", "grid")
    st12b.save()
    r12 = Storage(path=str(STATE))
    check("W12c 加载时自愈：widgets_only 被清",
          r12.get_setting("widgets_only") is False)
    check("W12c 被无界化掉的布局模式恢复网格",
          grid_flow.free_mode(r12) is False)

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL widgets_only PASSED")
    return 0


def run_main():
    app = QApplication([])
    try:
        code = main(app)
    except Exception:
        import traceback
        traceback.print_exc()
        failures.append("main() 异常")
        code = 1
    for f in Path(tempfile.gettempdir()).glob("test_widgets_only_*.json"):
        try:
            f.unlink()
        except Exception:
            pass
    try:
        STATE.unlink()
    except Exception:
        pass
    return code


if __name__ == "__main__":
    sys.exit(run_main())
