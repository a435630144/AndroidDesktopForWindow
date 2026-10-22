# -*- coding: utf-8 -*-
"""双交互逻辑（v9 V4，指导文档_v9.md §5）。

契约：
  I1  模式归一化：缺省 / 脏值 -> windows；set_mode 落盘
  I2  手机模式按住起长按表，Windows 模式不起表
  I3  长按到点弹出菜单，首项是「选择」
  I4  长按后松手不启动应用（不算单击）
  I5  手机模式单击 = 直接启动（activated，不是 clicked）
  I6  Windows 模式单击 = 选中（clicked，不启动）
  I7  多选态里单击 = 勾选（clicked），不启动
  I8  菜单开着时滑动 -> 关菜单 + 进入拖动
  I9  「选择」进入多选态：所有图标出现空心圆
  I10 多选态点空白 -> 退出多选态
  I11 批量菜单项齐全（合并 / 移动分页 / 删除）
  I12 批量合并 -> 一个文件夹含全部成员
  I13 批量移动到分页 -> row 落在目标页行范围
  I14 手机模式空白滑动 -> 翻页（不是框选）
  I15 Windows 模式空白拖动 -> 仍是框选（不翻页）
  I16 多选标记真的画出来了（像素非空）

运行：python tests/test_interaction.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src import interaction
from src.desktop_window import DesktopWindow
from src.storage import Storage

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_interaction_state.json"

CHECKS = []
failures = []


def check(name, cond, extra=""):
    CHECKS.append(name)
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def make_state(mobile=False):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = True
    st._data["settings"]["takeover_desktop"] = True
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["settings"]["layout_mode"] = "grid"
    st._data["widgets"] = []
    st._data["layout"] = [
        {"id": "a1", "type": "app", "col": 0, "row": 0,
         "app": {"name": "记事本", "path": "C:/Windows/notepad.exe"}},
        {"id": "a2", "type": "app", "col": 1, "row": 0,
         "app": {"name": "画图", "path": "C:/Windows/mspaint.exe"}},
        {"id": "a3", "type": "app", "col": 2, "row": 0,
         "app": {"name": "计算器", "path": "C:/Windows/calc.exe"}},
    ]
    grid_flow.set_grid(st, (W, H))
    grid_flow.set_page(0)
    interaction.set_mode(st, interaction.MOBILE if mobile else interaction.WINDOWS)
    st.save()
    return st


def make_window(st):
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    QTest.qWait(80)
    return w


def silence(icon):
    """断开真实启动槽：测试里绝不能真的把 notepad 拉起来。"""
    try:
        icon.activated.disconnect()
    except (RuntimeError, TypeError):
        pass


def click(icon, ms=0):
    """按下 + （可选延时）+ 抬起，全在图标中心。"""
    local = QPoint(icon.width() // 2, icon.height() // 2)
    gp = icon.mapToGlobal(local)
    icon.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, QPointF(local), QPointF(gp),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    if ms:
        QTest.qWait(ms)
    icon.mouseReleaseEvent(QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(local), QPointF(gp),
        Qt.LeftButton, Qt.NoButton, Qt.NoModifier))


def empty_press(win, local):
    gp = win.mapToGlobal(local)
    win.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, QPointF(local), QPointF(gp),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))


def empty_move(win, local, buttons=Qt.LeftButton):
    gp = win.mapToGlobal(local)
    win.mouseMoveEvent(QMouseEvent(
        QEvent.MouseMove, QPointF(local), QPointF(gp),
        Qt.NoButton, buttons, Qt.NoModifier))


def empty_release(win, local):
    gp = win.mapToGlobal(local)
    win.mouseReleaseEvent(QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(local), QPointF(gp),
        Qt.LeftButton, Qt.NoButton, Qt.NoModifier))


def main(app):
    # ---------- I1：模式归一化 ----------
    check("I1 缺省模式 = windows", interaction.normalize(None) == interaction.WINDOWS,
          "%s" % interaction.normalize(None))
    check("I1b 大小写无关", interaction.normalize("MOBILE") == interaction.MOBILE)
    check("I1c 脏值回落默认",
          interaction.normalize("手机") == interaction.WINDOWS)
    st = make_state()
    check("I1d 落盘前读到 windows", interaction.mode(st) == interaction.WINDOWS)
    interaction.set_mode(st, "mobile")
    check("I1e set_mode 落盘",
          Storage(path=str(STATE)).get_setting(interaction.SETTING) == interaction.MOBILE)
    check("I1f 长按阈值 = 450ms", interaction.LONG_PRESS_MS == 450)
    check("I1g 两种模式都有说明文案",
          all(interaction.describe(m) for m, _t in interaction.MODES))

    # ---------- I2：长按表 ----------
    st = make_state(mobile=True)
    win = make_window(st)
    check("I2 手机模式窗口就绪", len(win.icons) == 3, "%s" % sorted(win.icons))
    icon = win.icons["a1"]
    silence(icon)
    local = QPoint(icon.width() // 2, icon.height() // 2)
    gp = icon.mapToGlobal(local)
    icon.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, QPointF(local), QPointF(gp),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    check("I2b 手机模式按下即起长按表", icon._long.isActive())
    icon.mouseReleaseEvent(QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(local), QPointF(gp),
        Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
    check("I2c 抬起后长按表停止", not icon._long.isActive())

    st2 = make_state(mobile=False)
    win2 = make_window(st2)
    icon2 = win2.icons["a1"]
    silence(icon2)
    local2 = QPoint(icon2.width() // 2, icon2.height() // 2)
    gp2 = icon2.mapToGlobal(local2)
    icon2.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, QPointF(local2), QPointF(gp2),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    check("I2d Windows 模式不起长按表", not icon2._long.isActive())
    icon2.mouseReleaseEvent(QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(local2), QPointF(gp2),
        Qt.LeftButton, Qt.NoButton, Qt.NoModifier))

    # ---------- I3 / I4：长按菜单 ----------
    icon3 = win.icons["a2"]
    silence(icon3)
    fired = []
    icon3.activated.connect(lambda app_: fired.append(app_))
    clicked = []
    icon3.clicked.connect(lambda eid: clicked.append(eid))
    click(icon3, ms=interaction.LONG_PRESS_MS + 150)
    check("I3 长按到点弹出菜单", icon3._long_menu is not None)
    texts = [a.text() for a in icon3._long_menu.actions()] if icon3._long_menu else []
    check("I3b 菜单首项是「选择」", bool(texts) and texts[0] == "选择", "%s" % texts)
    check("I4 长按后松手不启动应用", not fired, "%s" % fired)
    check("I4b 长按后松手也不算单击选中", not clicked, "%s" % clicked)
    icon3._close_long_menu()

    # ---------- I5：手机模式单击 = 启动 ----------
    icon5 = win.icons["a3"]
    silence(icon5)
    fired5, clicked5 = [], []
    icon5.activated.connect(lambda app_: fired5.append(app_))
    icon5.clicked.connect(lambda eid: clicked5.append(eid))
    click(icon5)
    check("I5 手机模式单击直接启动", len(fired5) == 1, "%s" % fired5)
    check("I5b 手机模式单击不发 clicked", not clicked5, "%s" % clicked5)

    # ---------- I6：Windows 模式单击 = 选中 ----------
    fired6, clicked6 = [], []
    icon6 = win2.icons["a2"]
    silence(icon6)
    icon6.activated.connect(lambda app_: fired6.append(app_))
    icon6.clicked.connect(lambda eid: clicked6.append(eid))
    click(icon6)
    check("I6 Windows 模式单击发 clicked", clicked6 == ["a2"], "%s" % clicked6)
    check("I6b Windows 模式单击不启动", not fired6, "%s" % fired6)

    # ---------- I7：多选态单击 = 勾选 ----------
    win.enter_selection_mode("a1")
    fired7, clicked7 = [], []
    icon7 = win.icons["a2"]
    silence(icon7)
    icon7.activated.connect(lambda app_: fired7.append(app_))
    icon7.clicked.connect(lambda eid: clicked7.append(eid))
    click(icon7)
    check("I7 多选态单击发 clicked（勾选）", clicked7 == ["a2"], "%s" % clicked7)
    check("I7b 多选态单击不启动", not fired7, "%s" % fired7)
    check("I7c 勾选后选中集合含两项",
          win._selected == {"a1", "a2"}, "%s" % sorted(win._selected))

    # ---------- I8：菜单开着时滑动 -> 拖动 ----------
    from src import iconwidget as iw
    icon8 = win.icons["a3"]
    silence(icon8)
    icon8._long_origin = QPoint(500, 500)
    icon8._long_fired = True
    icon8._long_menu = icon8._build_context_menu(long_press=True)
    icon8._long_menu.show()
    started = []
    icon8.dragStarted.connect(lambda: started.append(1))
    icon8._exec_drag = lambda: started.append("exec")
    old_pos, old_down = iw._cursor_pos, iw._left_button_down
    iw._cursor_pos = lambda: QPoint(540, 500)      # 移动 40px > SLOP
    iw._left_button_down = lambda: True
    try:
        icon8._watch_long_slide()
        check("I8 滑动后菜单关闭", icon8._long_menu is None)
        check("I8b 滑动被判定为拖动", icon8._dragged is True)
        icon8._slide_into_drag()
        check("I8c 进入拖动循环（dragStarted）",
              "exec" in started and 1 in started, "%s" % started)
    finally:
        iw._cursor_pos, iw._left_button_down = old_pos, old_down
        icon8._dragged = False

    # ---------- I9 / I10：多选态进出 ----------
    check("I9 进入多选态", win._selection_mode is True)
    check("I9b 所有图标都出现多选标记",
          all(i._selection_visible for i in win.icons.values()))
    check("I9c 触发项被预选中", "a1" in win._selected, "%s" % sorted(win._selected))
    # 点空白 = 退出多选（不启动任何应用）
    empty_press(win, QPoint(1600, 900))
    empty_release(win, QPoint(1600, 900))
    check("I10 点空白退出多选态", win._selection_mode is False)
    check("I10b 退出后标记消失",
          not any(i._selection_visible for i in win.icons.values()))

    # ---------- I10c：切回 Windows 模式必须自己收干净 ----------
    win.enter_selection_mode("a1")
    win.set_interaction_mode(interaction.WINDOWS)
    check("I10c 切回 Windows 自动退出多选", win._selection_mode is False)
    check("I10d 模式已落盘", interaction.mode(st) == interaction.WINDOWS)
    check("I10e 多选标记已撤",
          not any(i._selection_visible for i in win.icons.values()))
    win.set_interaction_mode(interaction.MOBILE)
    check("I10f 切回手机模式", interaction.mode(st) == interaction.MOBILE)

    # ---------- I11 / I12 / I13：批量菜单与操作 ----------
    win.enter_selection_mode("a1")
    win._selected = {"a1", "a2"}
    win._refresh_selection()
    menu = win._build_batch_menu()
    texts = [a.text() for a in menu.actions()]
    check("I11 批量菜单有「合并为文件夹」",
          any(t.startswith("合并为文件夹") for t in texts), "%s" % texts)
    check("I11b 批量菜单有「移动到分页」子菜单", "移动到分页" in texts, "%s" % texts)
    check("I11c 批量菜单有「删除选中」",
          any(t.startswith("删除选中") for t in texts), "%s" % texts)
    # 子菜单要从 _build_batch_menu 自己留的引用取：PySide 里 addMenu 返回的
    # 包装随时可能失效（DEVLOG 坑 #39），`action.menu()` 会拿到已删除对象
    subs = list(win._ctx_submenus)
    check("I11d 分页子菜单列出页码",
          bool(subs) and len(subs[0].actions()) >= 2,
          "%s 项" % (len(subs[0].actions()) if subs else 0))

    win._selected = {"a1", "a2"}
    win._refresh_selection()
    win._batch_merge()
    folders = [e for e in st.layout if e.get("type") == "folder"]
    check("I12 合并后产生一个文件夹", len(folders) == 1, "%s" % [(e["id"], e.get("type")) for e in st.layout])
    if folders:
        names = [a.get("name") for a in folders[0].get("apps", [])]
        check("I12b 文件夹含两个成员", len(names) == 2, "%s" % names)
        check("I12c 成员就是选中的两个应用",
              set(names) == {"记事本", "画图"}, "%s" % names)
    check("I12d 另一个条目已被并入（不是两份）", len(st.layout) == 2,
          "%s" % [(e["id"], e.get("type")) for e in st.layout])

    # 移动到第 2 页：先选中剩余的一个应用
    app_ids = [e["id"] for e in st.layout if e.get("type") != "folder"]
    check("I13 前置：还有独立应用存在", bool(app_ids), "%s" % app_ids)
    win._selected = set(app_ids)
    win._refresh_selection()
    rpp = grid_flow.rows_per_page()
    win._batch_move_to_page(1)
    moved = [e for e in st.layout if e["id"] in set(app_ids)]
    check("I13b 全部落到第 2 页行范围",
          all(rpp <= int(e.get("row", 0)) < rpp * 2 for e in moved),
          "%s" % [(e["id"], e.get("row")) for e in moved])
    check("I13c 翻到了目标页", win._page == 1, "%s" % win._page)

    # ---------- I14 / I15：空白滑动翻页 vs 框选 ----------
    win.goto_page(0, animate=False)
    win.exit_selection_mode()
    x0 = QPoint(400, 500)
    empty_press(win, x0)
    check("I14 手机模式按下不画选框", win._band_start is None)
    check("I14b 手机模式记录滑动起点", win._swipe_start is not None)
    empty_move(win, QPoint(x0.x() - interaction.SWIPE_PX - 20, x0.y()))
    check("I14c 横向左滑翻到下一页", win._page == 1, "%s" % win._page)
    empty_release(win, QPoint(x0.x() - interaction.SWIPE_PX - 20, x0.y()))
    check("I14d 松手后滑动状态清理",
          win._swipe_start is None and win._swipe_moved is False)

    win2.goto_page(0, animate=False)
    empty_press(win2, x0)
    check("I15 Windows 模式按下进入框选", win2._band_start is not None)
    check("I15b Windows 模式不记录滑动起点", win2._swipe_start is None)
    empty_move(win2, QPoint(x0.x() + 200, x0.y() + 10))
    check("I15c Windows 模式拖动不翻页", win2._page == 0, "%s" % win2._page)
    empty_release(win2, QPoint(x0.x() + 200, x0.y() + 10))

    # ---------- I17：长按菜单的「选择」自动勾选被长按的图标 ----------
    # v10 A3（反馈 7）：以前菜单只调 host.enter_selection_mode()（QAction 的
    # triggered 传 False 进去，first_id 恒为空），进了多选态却一个都没选中，
    # 用户还得再点一下。现在必须把触发长按的那个图标带上。
    st17 = make_state(mobile=True)
    win17 = make_window(st17)
    try:
        icon17 = win17.icons["a2"]
        silence(icon17)
        click(icon17, ms=interaction.LONG_PRESS_MS + 150)
        check("I17a 长按弹出菜单", icon17._long_menu is not None)
        acts = icon17._long_menu.actions() if icon17._long_menu else []
        check("I17b 首项是「选择」", bool(acts) and acts[0].text() == "选择",
              "%s" % [a.text() for a in acts])
        if acts:
            acts[0].trigger()          # 走真实菜单路径，不直接调 host 方法
        check("I17c 进入多选态", win17._selection_mode is True)
        check("I17d 被长按的图标被自动勾选",
              win17._selected == {"a2"}, "%s" % sorted(win17._selected))
        check("I17e 该图标显示选中态（对钩）",
              win17.icons["a2"].selected is True)
        check("I17f 其它图标未被勾选",
              all(not win17.icons[k].selected for k in ("a1", "a3")))
        icon17._close_long_menu()
    finally:
        win17.close()
    QTest.qWait(80)

    # ---------- I16：多选标记真的画出来 ----------    # 不拿 grab() 比像素：图标是桌面窗口的子控件（不透明背景），
    # 抓出来整块都是 alpha=255，画没画圆看不出来。直接喂一张透明
    # QImage 给绘制函数，按 alpha 数像素——这也是"纯绘制可测"的用法。
    from PySide6.QtGui import QImage, QPainter
    st3 = make_state(mobile=True)
    win3 = make_window(st3)
    icon16 = win3.icons["a1"]

    def badge_pixels(visible, selected):
        img = QImage(64, 64, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)          # 留引用：QPainter 持有期间不能被 GC
        icon16.set_selection_visible(visible)
        icon16.set_selected(selected)
        p = QPainter(img)
        icon16._paint_select_badge(p)
        p.end()
        return sum(1 for y in range(64) for x in range(64)
                   if img.pixelColor(x, y).alpha() > 8)

    off = badge_pixels(False, False)
    empty_ring = badge_pixels(True, False)
    checked = badge_pixels(True, True)
    check("I16 多选态关闭时不画标记", off == 0, "%d px" % off)
    check("I16b 未选中画空心圆", empty_ring > 0, "%d px" % empty_ring)
    check("I16c 选中画对钩（实心更大）", checked > empty_ring,
          "%d / %d px" % (empty_ring, checked))

    for w_ in (win, win2, win3):
        try:
            w_.close()
        except RuntimeError:
            pass
    QTest.qWait(120)
    app.processEvents()

    print("-" * 56)
    print("%d checks" % len(CHECKS))
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL interaction PASSED")
    return 0


if __name__ == "__main__":
    a = QApplication.instance() or QApplication(sys.argv)
    raise SystemExit(main(a))
