# -*- coding: utf-8 -*-
"""接管语义：`takeover_desktop` 是唯一语义入口（v6 §7.2），
v7 反馈 16 起**界面不再提供开关**——启动即接管。

契约演进：
  - v6：接管开关在设置页 / 托盘 / 右键三处可见，用户可关掉回原生桌面。
  - v7（反馈 16）：开关下线。旧 state 里被关掉过的，加载时**一次性**
    强制回 True（否则三处入口同时消失，用户无从打开）；标记位
    `takeover_v7_forced` 保证只做一次。
  - 唯一"回原生桌面"的途径：退出程序；托盘保留"显示原生桌面"纯显隐。

  K1 新 state 默认接管开启 + 键已落盘
  K2 set_takeover 双写：takeover_desktop 与 hide_native_icons 同步
  K3 旧 state 迁移：v7 起**强制接管**（覆盖历史的 False）
  K4 两键矛盾时 takeover_desktop 优先
  K5 窗口 _organize_mode() 跟随 takeover()（不再直读 hide_native_icons）
  K6 设置页**不再有**接管开关；托盘**不再有**接管项
  K7 托盘有独立的「小组件模式」开关，显隐入口仍在
  K8 关闭接管（内部 API）→ 恢复原生图标可见

运行：python tests/test_takeover.py   （offscreen）
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QCheckBox

from src import win32_layer
from src.storage import Storage

TMP = Path(tempfile.gettempdir())
failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def fresh(name) -> Storage:
    p = TMP / ("test_takeover_%s.json" % name)
    if p.exists():
        p.unlink()
    return Storage(path=str(p))


class _Sig:
    """最小信号替身：托盘只需 .connect()。"""

    def __init__(self):
        self.slots = []

    def connect(self, fn):
        self.slots.append(fn)

    def emit(self, *a):
        for fn in self.slots:
            fn(*a)


class FakeWindow:
    """SettingsDialog / SystemTray 只需要这几个面。"""

    def __init__(self, storage):
        self.storage = storage
        self.attached = True
        self.visible = True
        self.rebuilt = 0
        self.native_applied = 0
        self.visibilityChanged = _Sig()

    def rebuild(self, stagger=False):
        self.rebuilt += 1

    def apply_native_icons_setting(self):
        self.native_applied += 1
        self.storage.set_setting(
            "hide_native_icons", self.storage.takeover())

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


class FakeLayer:
    """托盘菜单构建需要的最小 widget 层接口。"""

    def add_note(self):
        pass

    def toggle_entry(self, eid, checked):
        pass

    def set_visible(self, v):
        pass


def main(app):
    # ---------- K1 默认值 ----------
    st = fresh("default")
    check("K1 新 state 默认接管开启", st.takeover() is True)
    check("K1 takeover_desktop 键已登记", "takeover_desktop" in st.settings)

    # ---------- K2 双写 ----------
    st.set_takeover(False)
    check("K2 set_takeover(False) 生效", st.takeover() is False)
    check("K2 兼容键 hide_native_icons 同步为 False",
          st.get_setting("hide_native_icons") is False)
    st.set_takeover(True)
    check("K2 set_takeover(True) 双键同步为 True",
          st.takeover() is True and st.get_setting("hide_native_icons") is True)

    # ---------- K3 旧 state 迁移（v7 反馈 16：强制接管） ----------
    old = TMP / "test_takeover_old.json"
    old.write_text(json.dumps({
        "settings": {"schema_version": 2, "hide_native_icons": False,
                     "auto_clone_desktop": False},
        "layout": [],
        "widgets": [],
    }, ensure_ascii=False), encoding="utf-8")
    st_old = Storage(path=str(old))
    check("K3 旧 state 关闭态在 v7 被强制接管",
          st_old.takeover() is True,
          "takeover=%s hide=%s" % (st_old.takeover(),
                                   st_old.get_setting("hide_native_icons")))
    check("K3 强制迁移留标记位（只做一次）",
          st_old.get_setting("takeover_v7_forced") is True)
    # 标记位已存在时不再覆盖（保留内部 API 手工调整的能力）
    st_old.set_takeover(False)
    st_old2 = Storage(path=str(old))
    check("K3b 标记位已存在时尊重手动值", st_old2.takeover() is False,
          "takeover=%s" % (st_old2.takeover(),))
    old.write_text(json.dumps({
        "settings": {"schema_version": 2, "hide_native_icons": True,
                     "takeover_v7_forced": True},
        "layout": [], "widgets": [],
    }, ensure_ascii=False), encoding="utf-8")
    st_old3 = Storage(path=str(old))
    check("K3c 旧 state 开启态仍为接管", st_old3.takeover() is True)

    # ---------- K4 矛盾时新键优先 ----------
    st4 = fresh("prio")
    st4._data["settings"]["takeover_desktop"] = False
    st4._data["settings"]["hide_native_icons"] = True
    check("K4 两键矛盾时 takeover_desktop 优先", st4.takeover() is False)

    # ---------- K5 窗口模式判定 ----------
    from src.desktop_window import DesktopWindow
    st5 = fresh("window")
    st5._data["settings"]["auto_clone_desktop"] = False
    st5._data["settings"]["dev_mode"] = False
    st5._data["layout"] = []
    st5.set_takeover(True)
    w = DesktopWindow(st5)
    check("K5 接管开启时 _organize_mode 为真", w._organize_mode() is True)
    st5.set_takeover(False)
    check("K5 接管关闭时 _organize_mode 为假", w._organize_mode() is False)

    # ---------- K8 关闭接管 → 原生图标恢复 ----------
    calls = []
    real = win32_layer.set_native_icons_visible

    def fake_visible(v):
        calls.append(bool(v))

    win32_layer.set_native_icons_visible = fake_visible
    try:
        w2 = DesktopWindow(st5)
        w2._sync_native_icons()
        check("K8 关闭接管 → 原生图标可见", calls and calls[-1] is True,
              "calls=%s" % calls)
        calls.clear()
        st5.set_takeover(True)
        w2._sync_native_icons()
        check("K8b 开启接管 → 原生图标隐藏", calls and calls[-1] is False,
              "calls=%s" % calls)
    finally:
        win32_layer.set_native_icons_visible = real

    # ---------- K6 设置页不再有接管开关（反馈 16） ----------
    from src.settings_dialog import SettingsDialog
    st6 = fresh("dialog")
    st6._data["settings"]["auto_clone_desktop"] = False
    st6.set_takeover(True)
    fw = FakeWindow(st6)
    dlg = SettingsDialog(fw, st6, layer=None)
    boxes = [c for c in dlg.findChildren(QCheckBox)]
    takeover_boxes = [c for c in boxes if "接管系统桌面" in c.text()]
    check("K6 设置页已移除「接管系统桌面」开关", len(takeover_boxes) == 0,
          "found=%d" % len(takeover_boxes))
    check("K6 也没有独立的「桌面整理模式」项",
          not any("桌面整理模式" in c.text() for c in boxes),
          "%s" % [c.text()[:14] for c in boxes])
    check("K6 模式页仍然存在（布局选择还在）",
          getattr(dlg, "cmb_layout_mode", None) is not None)
    dlg.deleteLater()

    # ---------- K7 托盘（反馈 16：接管项删除，小组件模式补位） ----------
    from src.tray import SystemTray
    st7 = fresh("tray")
    st7.set_takeover(True)
    fw7 = FakeWindow(st7)
    t = SystemTray(fw7, st7, layer=FakeLayer())
    check("K7 托盘不再有「接管系统桌面」项",
          not hasattr(t, "act_organize"), "act_organize 仍存在")
    check("K7 托盘有「小组件模式」开关",
          "小组件模式" in t.act_widgets.text(), "text=%s" % t.act_widgets.text())
    check("K7 小组件模式勾选态来自 show_widgets",
          t.act_widgets.isChecked() is bool(st7.get_setting("show_widgets")))
    t._toggle_widgets(False)
    app.processEvents()
    check("K7 关掉小组件模式 → show_widgets=False",
          st7.get_setting("show_widgets") is False)
    check("K7 关小组件不影响接管", st7.takeover() is True)
    check("K7 显隐入口保留", "桌面" in t.act_toggle.text(),
          "text=%s" % t.act_toggle.text())
    t._sync_checks()
    check("K7b 显隐项勾选态跟随窗口可见性（与模式解耦）",
          t.act_toggle.isChecked() is fw7.isVisible())
    t.tray.hide()
    t.menu.deleteLater()

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL takeover PASSED")
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
    for f in TMP.glob("test_takeover_*.json"):
        try:
            f.unlink()
        except Exception:
            pass
    return code


if __name__ == "__main__":
    sys.exit(run_main())
