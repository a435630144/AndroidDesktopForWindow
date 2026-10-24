# -*- coding: utf-8 -*-
"""首次启动的新手操作指引（v11b / 6.1.0）。

用户需求：「给软件设计一套首次安装启动程序的新手操作指引」。

判据（行为级，不查源码文本）：
  O1  步骤齐全：欢迎 / 图标 / 文件夹 / Dock / 组件 / 收尾；
      分页、Dock、组件三步按实际内容出现（没有就跳过）
  O2  文案全部有中英词条，且不是 key 原文（i18n 漏词一眼可见）
  O3  高亮矩形落在屏幕内、非空；Dock 步的高亮就是 Dock 条带
  O4  卡片与高亮块**零相交**，且完整落在可用区内（逐步骤验证）
  O5  下一步 / 上一步 / 最后一步完成：索引与落盘版本号正确
  O6  Esc 跳过也算"看过"（下次启动不再弹），并关闭遮罩
  O7  should_show：没看过 -> True；看过 -> False；版本 +1 -> 又 True
  O8  像素级：洞内透明（露出桌面），洞外压暗，卡片不透明
  O9  欢迎页不挖洞（全屏遮罩 + 居中卡片）
  O10 Dock 关闭 / 组件全隐藏时，对应步骤自动消失
  O11 遮罩置顶、吞点击（指引期间不会误操作桌面）
  O12 设置 ▸ 通用 的「查看新手指引」能重放（入口真的接上了）

运行：python tests/test_onboarding.py   （offscreen，退出码 0 = 全绿）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from src import effects, i18n, onboarding
from src.desktop_window import DesktopWindow
from src.dock import DockWindow
from src.storage import Storage
from src.widget_layer import WidgetLayer
import src.widgets  # noqa: F401  （注册内建组件）

STATE = Path(tempfile.gettempdir()) / "test_onboarding_state.json"
W, H = 800, 760          # offscreen 平台固定 800×800，桌面留出 40px 任务栏
failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def make_state(icons=9, widget=True, dock=True):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"].update({
        "hide_native_icons": True, "auto_clone_desktop": False,
        "dock_enabled": bool(dock), "dock_position": "bottom",
        "show_widgets": bool(widget), "language": "zh_CN",
    })
    st._data["layout"] = [
        {"id": "p%d" % i, "type": "app", "col": i % 6, "row": i // 6,
         "app": {"name": "示例 %d" % i, "kind": "app",
                 "target": r"C:\Windows\System32\notepad.exe"}}
        for i in range(icons)
    ]
    st._data["widgets"] = ([{"id": "w1", "type": "clock", "col": 2, "row": 1,
                             "colspan": 2, "rowspan": 2, "anchored": True,
                             "hidden": False}] if widget else [])
    st.save()
    return st


def build(st):
    """桌面 + 组件层 + Dock，几何固定成 offscreen 屏幕大小。"""
    w = DesktopWindow(st)
    w.setAttribute(Qt.WA_DontShowOnScreen, True)
    w.setGeometry(0, 0, W, H)
    w.show()
    w._update_grid_metrics()
    w.rebuild()
    layer = WidgetLayer(st)
    w.set_widget_layer(layer)
    dock = DockWindow(st)
    w.set_dock(dock)
    return w, layer, dock


def open_guide(st, w, layer, dock):
    ov = onboarding.GuideOverlay(w, st, layer, dock)
    ov.setAttribute(Qt.WA_DontShowOnScreen, True)
    ov.show_guide()
    ov._set_t(1.0)          # 直接落到目标位（动效另有判据）
    return ov


def pixel(img, x, y):
    return img.pixelColor(int(x), int(y))


def main(app):
    # 动效关掉：步骤切换直接落位，避免测试等动画（判据只看最终几何）
    effects._rm_cache = True

    st = make_state()
    w, layer, dock = build(st)
    ov = open_guide(st, w, layer, dock)

    # ---------- O1 步骤 ----------
    keys = [s.key for s in ov.steps()]
    check("O1 步骤数为 6（欢迎/图标/文件夹/Dock/组件/收尾）",
          len(keys) == 6, str(keys))
    check("O1b 首尾是 welcome / settings",
          keys[0] == "welcome" and keys[-1] == "settings", str(keys))
    check("O1c Dock 与小组件步骤都在", "dock" in keys and "widgets" in keys,
          str(keys))

    # ---------- O2 词条 ----------
    missing = onboarding.missing_i18n_keys()
    check("O2 指引词条中英齐全", not missing, str(missing))
    bad = [s.key for s in ov.steps()
           if not s.title or not s.body or s.title == "onboarding.%s.title" % s.key]
    check("O2b 每步都有真实文案（不是 key 原文）", not bad, str(bad))

    # ---------- O3 高亮矩形 ----------
    screen = QRect(0, 0, W, H)
    bad = [s.key for s in ov.steps()
           if not s.hole.isNull()
           and not screen.adjusted(-8, -8, 8, 8).contains(s.hole)]
    check("O3 高亮矩形都在屏幕内", not bad, str(bad))
    dock_step = [s for s in ov.steps() if s.key == "dock"][0]
    check("O3b Dock 步高亮 = Dock 条带（外扩 8px）",
          dock_step.hole.contains(dock.geometry()),
          "%s vs %s" % (dock_step.hole, dock.geometry()))
    icon_step = [s for s in ov.steps() if s.key == "icons"][0]
    check("O3c 图标步高亮覆盖前几个图标",
          all(icon_step.hole.contains(QRect(w.mapToGlobal(i.geometry().topLeft()),
                                            i.geometry().size()))
              for i in [w.icons[k] for k in list(w.icons)[:2]]),
          str(icon_step.hole))

    # ---------- O4 卡片不压高亮 ----------
    bounds = ov._bounds()
    for i, s in enumerate(ov.steps()):
        ov._apply_step(i, animate=False)
        ov._set_t(1.0)
        card = ov._card.geometry()
        hole = ov._hole
        inter = (card.intersected(QRect(int(hole.x()), int(hole.y()),
                                        int(hole.width()), int(hole.height())))
                 if not hole.isEmpty() else QRect())
        check("O4[%s] 卡片不压高亮块" % s.key, inter.isEmpty(),
              "card=%s hole=%s" % (card, hole))
        check("O4b[%s] 卡片完整在可用区内" % s.key, bounds.contains(card),
              "card=%s bounds=%s" % (card, bounds))

    # ---------- O5 导航 ----------
    ov._apply_step(0, animate=False)
    ov.next_step()
    check("O5 下一步 -> 索引 1", ov.current_index() == 1,
          "idx=%d" % ov.current_index())
    ov.prev_step()
    check("O5b 上一步 -> 回到 0", ov.current_index() == 0)
    ov.prev_step()
    check("O5c 第 0 步再上一步不动", ov.current_index() == 0)
    check("O5d 第 0 步不显示「上一步」按钮",
          not ov._card.btn_prev.isVisible())
    for _ in range(len(ov.steps()) - 1):
        ov.next_step()
    check("O5e 走到最后一步", ov.current_index() == len(ov.steps()) - 1)
    check("O5f 最后一步按钮文案是「开始使用」",
          ov._card.btn_next.text() == i18n.T("onboarding.finish"),
          ov._card.btn_next.text())
    done = []
    ov.finished.connect(lambda skipped: done.append(skipped))
    ov.next_step()
    app.processEvents()
    check("O5g 最后一步继续 -> 结束（未跳过）", done == [False], str(done))
    check("O5h 结束落盘 onboarding_version",
          st.get_setting("onboarding_version") == onboarding.ONBOARDING_VERSION,
          repr(st.get_setting("onboarding_version")))
    check("O5i 结束后遮罩隐藏", not ov.isVisible())
    check("O5j 模块内不再持有活跃指引", onboarding.active() is None)

    # ---------- O6 Esc 跳过 ----------
    st2 = make_state()
    w2, layer2, dock2 = build(st2)
    ov2 = open_guide(st2, w2, layer2, dock2)
    skipped = []
    ov2.finished.connect(lambda s: skipped.append(s))
    ov2.keyPressEvent(_key_event(Qt.Key_Escape))
    app.processEvents()
    check("O6 Esc -> 记为跳过", skipped == [True], str(skipped))
    check("O6b 跳过也落盘（不再骚扰）",
          onboarding.should_show(st2) is False)

    # ---------- O7 should_show ----------
    st3 = make_state()
    check("O7 新装 state -> 应显示", onboarding.should_show(st3) is True)
    onboarding.mark_done(st3)
    check("O7b 看过 -> 不再显示", onboarding.should_show(st3) is False)
    old = onboarding.ONBOARDING_VERSION
    onboarding.ONBOARDING_VERSION = old + 1
    check("O7c 版本 +1（加了新步骤）-> 老用户再看到",
          onboarding.should_show(st3) is True)
    onboarding.ONBOARDING_VERSION = old

    # ---------- O8 像素 ----------
    stx = make_state()
    wx, layerx, dockx = build(stx)
    ovx = open_guide(stx, wx, layerx, dockx)
    ovx._apply_step(1, animate=False)       # 图标步：左上角有洞
    ovx._set_t(1.0)
    app.processEvents()
    img = QImage(ovx.size(), QImage.Format_ARGB32)
    img.fill(QColor(255, 0, 255))           # 品红替身：洞内应原样保留
    ovx.render(img, QPoint(0, 0))
    hole = ovx._hole
    inside = pixel(img, hole.center().x(), hole.center().y())
    outside = pixel(img, ovx.width() - 6, ovx.height() - 6)
    # 洞内铺了 alpha=2 的近透明底（分层窗 alpha=0 的像素会让点击穿透到
    # 桌面，指引期间不能把高亮区变成可操作区），所以只要求"基本原样"。
    check("O8 洞内是透出的桌面（近透明，颜色基本原样）",
          inside.red() >= 248 and inside.blue() >= 248 and inside.green() <= 6,
          str(inside.getRgb()))
    check("O8b 洞外被压暗", outside.red() < 200 or outside.blue() < 200,
          str(outside.getRgb()))
    card = ovx._card.geometry()
    card_px = pixel(img, card.center().x(), card.center().y())
    check("O8c 卡片区域不是透明（有实底）",
          (card_px.red(), card_px.green(), card_px.blue()) != (255, 0, 255),
          str(card_px.getRgb()))

    # ---------- O9 欢迎页不挖洞 ----------
    ovx._apply_step(0, animate=False)
    ovx._set_t(1.0)
    check("O9 欢迎页高亮块为空（全屏遮罩）", ovx._hole.width() < 2,
          str(ovx._hole))
    center_card = ovx._card.geometry().center()
    check("O9b 欢迎页卡片居中（横向误差 < 2px）",
          abs(center_card.x() - ovx.width() // 2) <= 2,
          "card=%s w=%d" % (center_card, ovx.width()))
    ovx.finish(False)

    # ---------- O10 无 Dock / 无组件 ----------
    st4 = make_state(widget=False, dock=False)
    w4, layer4, dock4 = build(st4)
    ov4 = open_guide(st4, w4, layer4, dock4)
    keys4 = [s.key for s in ov4.steps()]
    check("O10 Dock 关闭 -> 没有 dock 步", "dock" not in keys4, str(keys4))
    check("O10b 组件隐藏 -> 没有 widgets 步", "widgets" not in keys4, str(keys4))
    check("O10c 固定步骤仍在（至少 4 步）", len(keys4) >= 4, str(keys4))
    ov4.finish(False)

    # 多页时"分页"步骤自动插入（60 个图标必然分页）
    st6 = make_state(icons=60, widget=False, dock=False)
    w6, layer6, dock6 = build(st6)
    ov6 = open_guide(st6, w6, layer6, dock6)
    keys6 = [s.key for s in ov6.steps()]
    check("O10d 多页桌面 -> 出现 pages 步", "pages" in keys6, str(keys6))
    pages = [s for s in ov6.steps() if s.key == "pages"][0]
    check("O10e 分页步高亮页点区域", pages.hole.width() >= 20 and
          pages.hole.height() >= 8, str(pages.hole))
    ov6.finish(False)

    # ---------- O11 遮罩行为 ----------
    st5 = make_state()
    w5, layer5, dock5 = build(st5)
    ov5 = open_guide(st5, w5, layer5, dock5)
    flags = ov5.windowFlags()
    check("O11 遮罩置顶（盖住 Dock / 组件）",
          bool(flags & Qt.WindowStaysOnTopHint))
    check("O11b 无边框 + 工具窗（不进任务栏 / 不抢焦点图标）",
          bool(flags & Qt.FramelessWindowHint) and bool(flags & Qt.Tool))
    check("O11c 全屏几何覆盖桌面",
          ov5.geometry().contains(QRect(0, 0, W, H)), str(ov5.geometry()))
    before = ov5.current_index()
    ov5.mousePressEvent(_mouse_event())
    check("O11d 点一下遮罩 = 下一步（吞点击）",
          ov5.current_index() == before + 1,
          "%d -> %d" % (before, ov5.current_index()))
    ov5.finish(True)

    # ---------- O12 设置页重放入口 ----------
    from types import SimpleNamespace
    from PySide6.QtTest import QTest
    from src.settings_dialog import SettingsDialog
    rec = []
    fake_win = SimpleNamespace(attached=True, update=lambda: None,
                               start_onboarding=lambda replay=False: rec.append(replay))
    dlg = SettingsDialog(fake_win, make_state(), None, page="general")
    check("O12 通用页有「查看新手指引」按钮",
          getattr(dlg, "btn_guide", None) is not None)
    if getattr(dlg, "btn_guide", None) is not None:
        dlg.btn_guide.click()
        QTest.qWait(220)
        check("O12b 点击后重放（且不落盘版本号）",
              rec == [True], str(rec))
    dlg.close()

    # ---------- 收尾 ----------
    effects._rm_cache = None
    print()
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL PASS")
    return 0


def _key_event(key):
    from PySide6.QtGui import QKeyEvent
    return QKeyEvent(QKeyEvent.KeyPress, key, Qt.NoModifier)


def _mouse_event():
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    return QMouseEvent(QMouseEvent.MouseButtonPress, QPointF(5, 5), QPointF(5, 5),
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)


if __name__ == "__main__":
    app = QApplication([])
    sys.exit(main(app))
