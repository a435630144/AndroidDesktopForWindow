# -*- coding: utf-8 -*-
"""组件库窗口（v8 C3，指导文档_v8.md §3）。

契约：
  W1  卡片数 = 注册表组件数（全部）
  W2  分类计数正确（时间/效率/系统/信息），点分类只显示该类
  W3  搜索按名称/说明过滤（"天气" -> 1 张）
  W4  搜索无结果 -> 空态提示可见、卡片 0 张
  W5  未添加 -> 按钮「添加到桌面」
  W6  点添加 -> 落盘 + widgetsChanged + 卡片转「已在桌面」+ 底部计数 +1
  W7  已隐藏 -> 按钮「显示」；点后 entry.hidden == False
  W8  多实例组件添加后仍可继续添加（按钮不变灰）
  W9  卡片预览画布非空（真的画了，不是空框）
  W10 没有 preview 的组件走兜底卡，也能画出东西
  W11 底部计数显示"已添加 N 个组件"
  W12 移除按钮：已添加卡片可移除，移除后回到「添加到桌面」
  W13 组件库是设置面板的一个分页（open_settings 定位到它，且是单例）

运行：python tests/test_widget_center.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from src import grid_flow
from src.storage import Storage
from src.widget_layer import WidgetLayer

STATE = Path(tempfile.gettempdir()) / "test_widget_center_state.json"

CHECKS = []
failures = []


def check(name, cond, extra=""):
    CHECKS.append(name)
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def make_state(widgets):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = False
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["layout"] = []
    st._data["widgets"] = [dict(w) for w in widgets]
    st.save()
    return st


def alpha_nonempty(img, step=3):
    return sum(1 for y in range(0, img.height(), step) for x in range(0, img.width(), step)
               if img.pixelColor(x, y).alpha() > 8)


def main(app):
    from src import widget_center as wc
    from src import widget_registry as reg

    st = make_state([
        {"id": "clock", "type": "clock", "w": 240, "h": 284, "hidden": False,
         "anchored": True, "col": 6, "row": 10, "colspan": 2, "rowspan": 2},
        {"id": "td1", "type": "todo", "w": 240, "h": 284, "hidden": True,
         "anchored": False, "x": 60, "y": 60, "items": []},
    ])
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)
    layer = WidgetLayer(st)
    QTest.qWait(120)

    # v9 V2：组件库不再是窗口，而是嵌在宿主里的分页（设置面板就是这样用它）
    host = QWidget()
    host.resize(900, 620)
    _lay = QVBoxLayout(host)
    _lay.setContentsMargins(0, 0, 0, 0)
    center = wc.WidgetCenterPage(layer)
    _lay.addWidget(center)
    host.show()
    QTest.qWait(80)

    # ---------- W1 ----------
    check("W1 卡片数 = 注册表组件数",
          len(center.cards) == len(reg.all_specs()),
          "%d vs %d" % (len(center.cards), len(reg.all_specs())))

    # ---------- W2 ----------
    want = {}
    for s in reg.all_specs():
        want[s.category] = want.get(s.category, 0) + 1
    want["全部"] = len(reg.all_specs())     # 左栏第一项是"全部"，计数含它
    check("W2 分类计数正确", center.category_counts() == want,
          "%s vs %s" % (center.category_counts(), want))
    center.select_category("系统")
    QTest.qWait(30)
    check("W2b 点分类只显示该类",
          all(c.spec.category == "系统" for c in center.visible_cards())
          and len(center.visible_cards()) == want.get("系统", 0),
          str([c.spec.type for c in center.visible_cards()]))
    center.select_category("全部")
    QTest.qWait(30)

    # ---------- W3 / W4 ----------
    center.search.setText("天气")
    QTest.qWait(30)
    check("W3 搜索按名称过滤",
          [c.spec.type for c in center.visible_cards()] == ["weather"],
          str([c.spec.type for c in center.visible_cards()]))
    center.search.setText("zzz-不存在")
    QTest.qWait(30)
    check("W4 无结果 -> 卡片 0 张且空态可见",
          len(center.visible_cards()) == 0 and center.empty_tip.isVisible(),
          "%d / tip=%s" % (len(center.visible_cards()), center.empty_tip.isVisible()))
    center.search.setText("")
    QTest.qWait(30)

    # ---------- W5 / W6 ----------
    card = next(c for c in center.cards if c.spec.type == "weather")
    check("W5 未添加 -> 按钮「添加到桌面」",
          card.button.text() == "添加到桌面", card.button.text())

    before = len([e for e in st.widgets if e.get("type") == "weather"])
    got = []
    layer.widgetsChanged.connect(lambda: got.append(1))
    card.button.click()
    QTest.qWait(120)
    after = len([e for e in st.widgets if e.get("type") == "weather"])
    check("W6 点添加 -> 条目 +1", after == before + 1, "%d -> %d" % (before, after))
    check("W6b 发 widgetsChanged", len(got) >= 1, str(got))
    check("W6c 卡片转「已在桌面」", card.button.text() == "已在桌面", card.button.text())
    check("W6d 按钮不可点", card.button.isEnabled() is False)
    check("W11 底部计数包含新组件",
          str(len(st.widgets)) in center.count_label.text(), center.count_label.text())

    # ---------- W7 ----------
    todo_card = next(c for c in center.cards if c.spec.type == "todo")
    check("W7 已隐藏 -> 按钮「显示」", todo_card.button.text() == "显示",
          todo_card.button.text())
    todo_card.button.click()
    QTest.qWait(120)
    td = next(e for e in st.widgets if e.get("id") == "td1")
    check("W7b 点显示 -> entry.hidden 变 False", td.get("hidden") is False)

    # ---------- W8 ----------
    check("W8 多实例组件仍可继续添加",
          todo_card.button.text() == "添加到桌面" and todo_card.button.isEnabled(),
          todo_card.button.text())
    before = len(st.widgets)
    todo_card.button.click()
    QTest.qWait(120)
    check("W8b 再添加确实多了一条", len(st.widgets) == before + 1,
          "%d -> %d" % (before, len(st.widgets)))

    # ---------- W9 / W10 ----------
    shot = card.grab().toImage()
    check("W9 卡片（天气）预览非空", alpha_nonempty(shot) > 300,
          str(alpha_nonempty(shot)))
    # v9 V1 起时钟也有 preview 了；兜底卡改用仍没声明 preview 的「桌面面板」
    plain_card = next(c for c in center.cards if c.spec.type == "panel")
    shot2 = plain_card.grab().toImage()
    check("W10 无 preview 的组件走兜底卡也有内容", alpha_nonempty(shot2) > 300,
          str(alpha_nonempty(shot2)))

    # ---------- W12 ----------
    mon_card = next(c for c in center.cards if c.spec.type == "monitor")
    mon_card.button.click()
    QTest.qWait(120)
    check("W12 添加后可移除", mon_card.remove_btn.isVisible())
    n_before = len(st.widgets)
    mon_card.remove_btn.click()
    QTest.qWait(120)
    check("W12b 移除后条目减少", len(st.widgets) == n_before - 1,
          "%d -> %d" % (n_before, len(st.widgets)))
    check("W12c 移除后回到「添加到桌面」", mon_card.button.text() == "添加到桌面",
          mon_card.button.text())

    # ---------- W13：融合进设置面板 ----------
    from src import settings_dialog as sd
    check("W13a 组件库有独立分页 key",
          "widgets" in [k for k, _l in sd.SettingsDialog.NAV])
    fw = type("FW", (), {"storage": st})()
    dlg = sd.open_settings(fw, st, layer, page="widgets")
    QTest.qWait(60)
    check("W13b open_settings 直接定位到组件库页",
          dlg.NAV[dlg.stack.currentIndex()][0] == "widgets",
          str(dlg.NAV[dlg.stack.currentIndex()][0]))
    check("W13c 设置窗口里带着组件库页面",
          hasattr(dlg, "center_page") and len(dlg.center_page.cards) == len(reg.all_specs()),
          str(len(getattr(getattr(dlg, "center_page", None), "cards", []))))
    check("W13d 组件库不再是独立模态窗口",
          not isinstance(center, __import__("PySide6.QtWidgets", fromlist=["QDialog"]).QDialog))
    again = sd.open_settings(fw, st, layer, page="widgets")
    check("W13e 再次打开复用同一设置窗口（单例）", again is dlg, repr(again is dlg))
    dlg.close()
    dlg.deleteLater()
    host.close()
    host.deleteLater()
    QTest.qWait(40)

    # ---------- W14：v10 A6（反馈 12）分类条顶部横向 ----------
    from src.widget_center import CategoryBar
    bar = CategoryBar()
    bar.rebuild([("全部", 8), ("时间", 2), ("效率", 3), ("系统", 1), ("信息", 1)])
    chips = bar.findChildren(QPushButton)
    check("W14a 胶囊一字排开（不换行：所有 chip 同一行）",
          len(chips) == 5 and len({c.y() for c in chips}) == 1,
          "n=%d ys=%s" % (len(chips), sorted({c.y() for c in chips})))
    check("W14b 横向条（宽 > 高）", bar.width() > bar.height(),
          "%dx%d" % (bar.width(), bar.height()))
    check("W14c 默认选中第一项", bar.current() == "全部", bar.current())
    bar.select("效率")
    check("W14d select 后切换当前分类", bar.current() == "效率", bar.current())
    fired = []
    bar.changed.connect(lambda: fired.append(bar.current()))
    bar.select("系统")
    check("W14e 切换发出 changed 信号", fired == ["系统"], str(fired))
    bar.rebuild([("全部", 8), ("时间", 2)])      # 当前分类被卸载 -> 回落第一项
    check("W14f 重建后当前分类失效则回落", bar.current() == "全部", bar.current())
    bar.deleteLater()

    # ---------- W15：v10 A7（反馈 13）批量显隐 ----------
    st15 = make_state([
        {"id": "w_on", "type": "clock", "w": 240, "h": 284, "hidden": False,
         "anchored": True, "col": 6, "row": 10, "colspan": 2, "rowspan": 2},
        {"id": "w_off", "type": "todo", "w": 240, "h": 284, "hidden": True,
         "anchored": False, "x": 60, "y": 60, "items": []},
    ])
    grid_flow.set_grid(st15, (1920, 1040))
    grid_flow.set_page(0)
    layer15 = WidgetLayer(st15)
    QTest.qWait(120)
    hidden = {e["id"]: e.get("hidden") for e in st15.widgets}
    check("W15a 夹具一显一隐", hidden == {"w_on": False, "w_off": True}, str(hidden))
    n = layer15.hide_all()
    check("W15b hide_all 关掉可见的那个并返回 1",
          n == 1 and all(e.get("hidden") for e in st15.widgets),
          "n=%d %s" % (n, [e.get("hidden") for e in st15.widgets]))
    n2 = layer15.hide_all()
    check("W15c 再次 hide_all 是幂等的（返回 0）", n2 == 0, str(n2))
    n3 = layer15.show_all()
    check("W15d show_all 全部恢复并返回 2",
          n3 == 2 and not any(e.get("hidden") for e in st15.widgets),
          "n=%d %s" % (n3, [e.get("hidden") for e in st15.widgets]))
    n4 = layer15.show_all()
    check("W15e 再次 show_all 返回 0（不重复）", n4 == 0, str(n4))
    check("W15f 组件库页面有关闭所有按钮",
          hasattr(center, "btn_hide_all"))
    for w in list(layer15.widgets.values()):
        try:
            w.close()
        except Exception:      # noqa: BLE001
            pass
    QTest.qWait(60)

    # ---------- W16：v10 响应式卡片区（窄 1 列 / 放得下才 2 列 / 无横滚条） ----------
    from src.widget_center import CARD_MIN_W, GRID_GAP, columns_for
    check("W16a columns_for 窄视口 1 列", columns_for(500) == 1, columns_for(500))
    check("W16b columns_for 恰好放下 2 列",
          columns_for(2 * CARD_MIN_W + GRID_GAP) == 2,
          columns_for(2 * CARD_MIN_W + GRID_GAP))
    check("W16c columns_for 差 1px 不够 2 列",
          columns_for(2 * CARD_MIN_W + GRID_GAP - 1) == 1,
          columns_for(2 * CARD_MIN_W + GRID_GAP - 1))
    check("W16d columns_for 宽视口仍最多 2 列", columns_for(4000) == 2,
          columns_for(4000))
    check("W16e columns_for 脏值回 1 列",
          columns_for(0) == 1 and columns_for(-5) == 1, columns_for(0))

    # W13 已把外层 host 连同 center 销毁，这里自建活页面做布局判据
    host16 = QWidget()
    host16.resize(900, 620)
    lay16 = QVBoxLayout(host16)
    lay16.setContentsMargins(0, 0, 0, 0)
    page16 = wc.WidgetCenterPage(layer)
    lay16.addWidget(page16)
    host16.show()
    QTest.qWait(80)

    card0 = page16.cards[0]
    check("W16f 卡片不再固定宽（最小宽 + 可拉伸）",
          card0.minimumWidth() >= CARD_MIN_W
          and card0.sizePolicy().horizontalPolicy() != 0,   # 0 = Fixed
          "min=%d policy=%s" % (card0.minimumWidth(),
                                card0.sizePolicy().horizontalPolicy()))
    check("W16g 横向滚动条关闭（不出现横向滚动）",
          page16.scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff,
          page16.scroll.horizontalScrollBarPolicy())

    def _used_cols():
        cols = set()
        for card in page16.cards:
            if not card.isVisible():
                continue
            idx = page16.grid.indexOf(card)
            if idx < 0:
                continue
            _r, c, _rs, _cs = page16.grid.getItemPosition(idx)
            cols.add(c)
        return sorted(cols)

    host16.resize(int(2 * CARD_MIN_W + GRID_GAP + 200), 620)   # 宽：2 列
    QTest.qWait(80)
    wide_cols = _used_cols()
    check("W16h 宽窗放得下 -> 2 列", wide_cols == [0, 1], str(wide_cols))
    host16.resize(CARD_MIN_W + 60, 620)                        # 窄：1 列
    QTest.qWait(80)
    narrow_cols = _used_cols()
    check("W16i 窄窗 -> 1 列（无横向滚动）", narrow_cols == [0], str(narrow_cols))
    w1 = page16.cards[0].width()
    check("W16j 窄窗 1 列卡片加宽（>= 最小宽）", w1 >= CARD_MIN_W, "w=%d" % w1)
    host16.resize(900, 620)
    QTest.qWait(80)
    check("W16k 拉回宽窗恢复 2 列", _used_cols() == [0, 1], str(_used_cols()))
    host16.close()
    host16.deleteLater()
    QTest.qWait(30)
    # 1 列形态必须可达：设置窗最小宽要窄于双列阈值（侧栏 212 + 页边距 36）
    dlg16 = sd.open_settings(fw, st, layer, page="widgets")
    QTest.qWait(40)
    dlg_min = dlg16.minimumWidth()
    need_w = 2 * CARD_MIN_W + GRID_GAP + 212 + 36
    check("W16l 设置窗最小宽让 1 列可达", dlg_min < need_w,
          "dlg_min=%d need=%d" % (dlg_min, need_w))
    dlg16.close()
    dlg16.deleteLater()
    QTest.qWait(30)

    for w in list(layer.widgets.values()):
        try:
            w.close()
        except Exception:      # noqa: BLE001
            pass

    # 控件必须比 QApplication 先死——否则解释器退出时段错误 rc=139。
    for _w in QApplication.topLevelWidgets():
        try:
            _w.close()
            _w.deleteLater()
        except RuntimeError:
            pass
    QApplication.instance().processEvents()

    if STATE.exists():
        STATE.unlink()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    try:
        main(app)
    finally:
        print("-" * 56)
        print("%d/%d checks, %d FAIL" % (len(CHECKS) - len(failures), len(CHECKS),
                                         len(failures)))
        if failures:
            print("FAILED:", ", ".join(failures))
    sys.exit(1 if failures else 0)
