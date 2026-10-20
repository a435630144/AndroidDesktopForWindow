# -*- coding: utf-8 -*-
"""v7 反馈批 · 命中盲区 / 下拉浮层 / 分页入口（反馈 3 / 4 / 17）。

  H1  组件命中填充（#3）：锚定组件的整块矩形都进 Windows 命中表——
      透明边角不再"点了没反应"；WM_NCHITTEST 一律 HTCLIENT
  C1  下拉浮层实心（#4）：弹出列表所在顶层窗口不透明，底层文字不透上来
  P1  分页入口（#17）：网格模式也有「添加空白页」；空白页上出现「删除」
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.desktop_window import DesktopWindow
from src.settings_dialog import SettingsDialog
from src.storage import Storage
from src.ui_choice import ComboBox
from src.widget_base import FloatingWidget

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_hit_popup_state.json"
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


def make_state():
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = False
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["widgets"] = []
    st._data["layout"] = [
        {"id": "a", "type": "app",
         "app": {"name": "a", "target": "a", "kind": "app"},
         "apps": [], "col": 0, "row": 0}]
    st.save()
    return st


def menu_texts(menu):
    out = []
    for act in menu.actions():
        out.append("---" if act.isSeparator() else act.text())
        sub = act.menu()
        if sub is not None:
            out.extend("  " + t for t in menu_texts(sub))
    return out


# ---------------------------------------------------------------- H1
def test_hit(app):
    st = make_state()
    entry = {"id": "clock", "type": "clock", "anchored": True,
             "col": 0, "row": 0, "colspan": 2, "rowspan": 2,
             "x": 100, "y": 100, "w": 200, "h": 200, "hidden": False}
    w = FloatingWidget(st, entry)
    w.resize(200, 200)
    w.show()
    settle(app)
    pm = w.grab()
    img = pm.toImage()
    pts = [(1, 1), (img.width() - 2, 1), (1, img.height() - 2),
           (img.width() - 2, img.height() - 2)]
    alphas = []
    for x, y in pts:
        if 0 <= x < img.width() and 0 <= y < img.height():
            alphas.append(img.pixelColor(x, y).alpha())
    check("H1 组件四角都有 alpha（不再被系统跳过）",
          all(a > 0 for a in alphas), "alphas=%s" % (alphas,))
    check("H1 角落是极淡填充（肉眼不可见）", all(a <= 3 for a in alphas),
          "alphas=%s" % (alphas,))
    mid = img.pixelColor(img.width() // 2, 2).alpha()
    check("H1 组件卡片本身仍是可见的 tint", mid > 20, "alpha=%d" % mid)

    # 左上角按下应当进入拖动（旧实现该点没有事件）
    g = QPointF(w.pos()) + QPointF(2, 2)
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(2, 2), g, Qt.LeftButton,
                     Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(w, ev)
    check("H1 左上角按下进入拖动（无盲区）", w._drag_off is not None,
          "_drag_off=%s" % (w._drag_off,))
    up = QMouseEvent(QEvent.MouseButtonRelease, QPointF(2, 2), g,
                     Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(w, up)

    # nativeEvent：WM_NCHITTEST -> HTCLIENT
    import ctypes
    from ctypes import wintypes
    msg = wintypes.MSG()
    msg.message = 0x0084
    msg.lParam = 0
    try:
        handled, result = w.nativeEvent(b"windows_generic_MSG",
                                        ctypes.addressof(msg))
    except Exception as exc:                     # 非 Windows 事件类型
        handled, result = False, None
        print("  (nativeEvent 不可用: %s)" % exc)
    check("H1 WM_NCHITTEST 返回 HTCLIENT", handled and result == 1,
          "handled=%s result=%s" % (handled, result))
    w.close()


# ---------------------------------------------------------------- C1
def test_combo(app):
    st = make_state()

    class FakeWindow:
        storage = st
        attached = True

        def refresh_grid(self):
            pass

    dlg = SettingsDialog(FakeWindow(), st, layer=None)
    dlg.show()
    settle(app, 200)
    cmb = dlg.cmb_page_axis
    check("C1 设置页下拉是实心实现", isinstance(cmb, ComboBox))
    cmb.showPopup()
    settle(app, 200)
    view = cmb.view()
    win = view.window()
    check("C1 弹层窗口不透明（WA_TranslucentBackground 已关）",
          not win.testAttribute(Qt.WA_TranslucentBackground))
    check("C1 弹层窗口自动填充底色", win.autoFillBackground())
    check("C1 弹层窗口不透明度 1.0", abs(win.windowOpacity() - 1.0) < 0.01,
          "opacity=%s" % win.windowOpacity())
    bg = win.palette().window().color()
    check("C1 弹层底色 = 面板色（38,38,44）",
          (bg.red(), bg.green(), bg.blue()) == (38, 38, 44), "%s" % (bg.getRgb(),))
    # 目检：抓弹层左上角，必须是不透明白/深色（不是 alpha=0）
    img = win.grab().toImage()
    if not img.isNull():
        c = img.pixelColor(min(2, img.width() - 1), min(2, img.height() - 1))
        check("C1 弹层左上角像素不透明", c.alpha() == 255,
              "%s" % (c.getRgb(),))
    cmb.hidePopup()
    dlg.close()


# ---------------------------------------------------------------- P1
def test_pages(app):
    st = make_state()
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    settle(app, 150)

    texts = " | ".join(menu_texts(w._build_context_menu()))
    check("P1 网格模式右键有「添加空白页」", "添加空白页" in texts, texts[-160:])
    check("P1 未在空白页时不显示删除项", "删除当前空白页" not in texts)

    before = w._page
    w._add_blank_page()
    settle(app, 120)
    check("P1 加页后自动翻到新页", w._page == before + 1,
          "%d -> %d" % (before, w._page))
    check("P1 新页登记在 extra_pages",
          w._page in grid_flow.extra_pages(st),
          "%s" % (grid_flow.extra_pages(st),))
    texts2 = " | ".join(menu_texts(w._build_context_menu()))
    check("P1 空白页上出现「删除当前空白页」", "删除当前空白页" in texts2,
          texts2[-160:])
    w._remove_blank_page()
    settle(app, 120)
    check("P1 删除空白页后从 extra_pages 移除",
          w._page not in grid_flow.extra_pages(st))
    w.close()


def main(app):
    test_hit(app)
    test_combo(app)
    test_pages(app)
    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL hit_popup PASSED")
    return 0


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    sys.exit(main(app))
