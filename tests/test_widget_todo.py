# -*- coding: utf-8 -*-
"""待办清单组件（v8 C5，指导文档_v8.md §4.2）。

契约：
  T1  load 容错：None / 脏条目 / 缺字段都不抛，坏条目被丢弃
  T2  add：追加到末尾；空文本拒绝；上限 200 拒绝
  T3  toggle：按 id 切换 done；未知 id 原样返回
  T4  remove：按 id 删除；未知 id 原样返回
  T5  序列化往返：dict -> item -> dict 字段不丢
  T6  layout：输入框在顶部，行高 30，2×2 至少看得见 3 行
  T7  layout：空列表也给出空态区域（不是零高）
  T8  draw：有条目时画布非空
  T9  draw：空态画提示且不抛
  T10 完成项用弱化色 + 划线（颜色亮度低于未完成项）
  T11 点勾选圆切换 done（真实鼠标事件）
  T12 滚轮滚动：scroll 变化且被 clamp 在合法范围
  T13 回车新增：QLineEdit.returnPressed -> items +1、输入框清空
  T14 注册表：spans (2,2)/(2,4)、多实例、默认悬浮、可交互

运行：python tests/test_widget_todo.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.storage import Storage

STATE = Path(tempfile.gettempdir()) / "test_widget_todo_state.json"

CHECKS = []
failures = []


def check(name, cond, extra=""):
    CHECKS.append(name)
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def canvas(w, h):
    img = QImage(int(w), int(h), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    return img


def alpha_nonempty(img, step=2):
    return sum(1 for y in range(0, img.height(), step) for x in range(0, img.width(), step)
               if img.pixelColor(x, y).alpha() > 8)


def main(app):
    from src.widgets import todo as wt

    # ---------- T1：容错 ----------
    check("T1 load(None) -> []", wt.load_items(None) == [])
    dirty = [{"id": "a", "text": "ok", "done": False}, None, {"id": "b"},
             {"text": "no id"}, {"id": "c", "text": "x", "done": True}]
    got = wt.load_items(dirty)
    check("T1b 脏条目被丢弃，合法条目保留",
          [i["id"] for i in got] == ["a", "c"], str(got))
    check("T1c 缺 done 视为未完成",
          all(isinstance(i["done"], bool) for i in got))

    # ---------- T2：新增 ----------
    items = wt.add_item([], "买牛奶")
    check("T2 空列表新增一条", len(items) == 1 and items[0]["text"] == "买牛奶")
    check("T2b 空白文本被拒绝", len(wt.add_item(items, "   ")) == 1)
    many = [{"id": "%03d" % i, "text": "t%d" % i, "done": False}
            for i in range(wt.MAX_ITEMS)]
    check("T2c 达到上限后拒绝新增", len(wt.add_item(many, "再来一条")) == wt.MAX_ITEMS)
    two = wt.add_item(items, "买鸡蛋")
    check("T2d 新条目 id 唯一", len(two) == 2 and two[0]["id"] != two[1]["id"],
          str([i["id"] for i in two]))

    # ---------- T3 / T4 ----------
    iid = items[0]["id"]
    toggled = wt.toggle_item(items, iid)
    check("T3 toggle 切换 done", toggled[0]["done"] is True)
    check("T3b toggle 未知 id 原样", wt.toggle_item(items, "nope")[0]["done"] is False)
    removed = wt.remove_item(toggled, iid)
    check("T4 remove 删除指定条目", removed == [])
    check("T4b remove 未知 id 原样", len(wt.remove_item(items, "nope")) == 1)

    # ---------- T5：序列化往返 ----------
    back = wt.load_items(wt.serialize(items))
    check("T5 序列化往返字段不丢",
          back == [{"id": items[0]["id"], "text": items[0]["text"],
                    "done": items[0]["done"]}], str(back))

    # ---------- T6 / T7：布局 ----------
    L = wt.layout(QRectF(0, 0, 240, 284))
    check("T6 输入框在顶部", L["input"].top() < 30 and L["input"].height() >= 24,
          "top=%.1f h=%.1f" % (L["input"].top(), L["input"].height()))
    check("T6b 行高 30", L["row_h"] == wt.ROW_H == 30)
    check("T6c 2×2 至少看得见 3 行", L["visible"] >= 3, "visible=%d" % L["visible"])
    L2 = wt.layout(QRectF(0, 0, 240, 500))
    check("T6d 2×4 看得见的行数更多", L2["visible"] > L["visible"],
          "%d vs %d" % (L2["visible"], L["visible"]))
    check("T7 空列表仍有空态区域", L["list"].height() > 0)

    # ---------- T8 / T9 / T10：绘制 ----------
    demo = [{"id": "1", "text": "写周报", "done": False},
            {"id": "2", "text": "交房租", "done": True},
            {"id": "3", "text": "买牛奶", "done": False}]
    img = canvas(240, 284)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    wt.draw(p, QRectF(0, 0, 240, 284), demo)
    p.end()
    check("T8 有条目时画布非空", alpha_nonempty(img) > 300, str(alpha_nonempty(img)))

    img2 = canvas(240, 284)
    ok = True
    try:
        p2 = QPainter(img2)
        wt.draw(p2, QRectF(0, 0, 240, 284), [])
        p2.end()
    except Exception as exc:      # noqa: BLE001
        ok = False
        print("   draw(empty) 抛异常: %r" % (exc,))
    check("T9 空态不抛且画了提示", ok and alpha_nonempty(img2) > 100)

    done_color = wt.text_color(True)
    todo_color = wt.text_color(False)
    check("T10 完成项弱化色（亮度更低）",
          done_color.red() + done_color.green() + done_color.blue()
          < todo_color.red() + todo_color.green() + todo_color.blue(),
          "%s vs %s" % (done_color.name(), todo_color.name()))

    # ---------- T11 / T12 / T13：交互 ----------
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = False
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["layout"] = []
    st._data["widgets"] = [{"id": "td1", "type": "todo", "w": 240, "h": 284,
                            "hidden": False, "anchored": False, "x": 200, "y": 200,
                            "items": [dict(x) for x in demo]}]
    st.save()
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)

    w = wt.TodoWidget(st, st.widgets[0])
    w.show()
    QTest.qWait(60)

    Lw = wt.layout(QRectF(0, 0, w.width(), w.height()))
    first_row = wt.row_rect(Lw["list"], 0)
    check_pt = wt.check_rect(first_row).center().toPoint()
    before = st.widgets[0]["items"][0]["done"]
    QTest.mouseClick(w, Qt.LeftButton, pos=QPoint(check_pt))
    QTest.qWait(30)
    after = st.widgets[0]["items"][0]["done"]
    check("T11 点勾选圆切换 done", before is False and after is True,
          "%r -> %r" % (before, after))

    # 滚轮：先塞满，再滚
    st.widgets[0]["items"] = [{"id": "s%d" % i, "text": "行%d" % i, "done": False}
                              for i in range(12)]
    w._scroll = 0
    ev = QWheelEvent(QPoint(120, 200), w.mapToGlobal(QPoint(120, 200)),
                     QPoint(0, 0), QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
    w.wheelEvent(ev)
    scrolled = w._scroll
    for _ in range(20):
        w.wheelEvent(QWheelEvent(QPoint(120, 200), w.mapToGlobal(QPoint(120, 200)),
                                 QPoint(0, 0), QPoint(0, -120), Qt.NoButton,
                                 Qt.NoModifier, Qt.NoScrollPhase, False))
    check("T12 滚轮改变 scroll 且不越界",
          scrolled > 0 and 0 <= w._scroll <= max(0, 12 - Lw["visible"]),
          "scrolled=%d max=%d" % (w._scroll, max(0, 12 - Lw["visible"])))

    w.edit.setText("新的待办")
    n_before = len(st.widgets[0]["items"])
    w.edit.returnPressed.emit()
    QTest.qWait(30)
    check("T13 回车新增一条且清空输入框",
          len(st.widgets[0]["items"]) == n_before + 1 and w.edit.text() == "",
          "%d -> %d" % (n_before, len(st.widgets[0]["items"])))
    check("T13b 新增内容正确",
          st.widgets[0]["items"][-1]["text"] == "新的待办")

    w.close()

    # ---------- T14：注册 ----------
    from src import widget_registry as reg
    spec = reg.get("todo")
    check("T14 注册表已登记 todo", spec is not None)
    if spec is not None:
        check("T14b spans (2,2)/(2,4) / 多实例 / 默认悬浮 / 可交互",
              spec.spans == ((2, 2), (2, 4)) and spec.multi_instance is True
              and spec.default_anchored is False and spec.interactive is True,
              "%s %s %s %s" % (spec.spans, spec.multi_instance,
                               spec.default_anchored, spec.interactive))

    # 控件必须比 QApplication 先死——否则解释器退出时段错误 rc=139
    # （test_widget_glass 上实测过：断言全过、退出码 139）。
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
