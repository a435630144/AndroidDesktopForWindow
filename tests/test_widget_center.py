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
  W13 多次打开复用同一实例（不叠出两个窗口）

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
from PySide6.QtWidgets import QApplication

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

    center = wc.WidgetCenter(layer)
    center.show()
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
    clock_card = next(c for c in center.cards if c.spec.type == "clock")
    shot2 = clock_card.grab().toImage()
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

    # ---------- W13 ----------
    check("W13 非模态", center.isModal() is False)
    again = wc.open_center(layer)
    check("W13b 再次打开复用同一实例", again is center, "%r" % (again is center,))
    again.close()

    for w in list(layer.widgets.values()):
        try:
            w.close()
        except Exception:      # noqa: BLE001
            pass
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
