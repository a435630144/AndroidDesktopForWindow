# -*- coding: utf-8 -*-
"""组件「关闭」（v9 修复用户反馈）。

反馈原话：「小组件的右键 隐藏 和 关闭 功能描述重复，且关闭无法使用。
合并为关闭。」

病根两处：
  1. 右键菜单同时挂了「隐藏」（写 hidden + save + closed + close）和
     「关闭」（只 closed + close），两项对用户是同一件事，描述重复。
  2. 「关闭」只 close() 不写 `entry["hidden"]`，而 WidgetLayer._on_closed
     的判断是"entry 未 hidden 就补建一个"（那是形态切换 锚定<->悬浮 的
     保底逻辑）。于是点「关闭」→ 窗口关掉 → 层立刻重建同款 → 用户看到
     "组件还在 / 闪一下又回来"，判定为"关闭无法使用"。

契约：
  C1  右键菜单不再有「隐藏」
  C2  右键菜单恰有一个「关闭」，且是最后一项（动作区收尾位置）
  C3  点「关闭」→ entry["hidden"] is True
  C4  点「关闭」→ 落盘（重新打开 Storage 仍是 hidden）
  C5  点「关闭」→ 层里移除该 id，且**没有补建**新实例（原 BUG 的判据）
  C6  关闭是可恢复的：toggle_entry(id, True) 后重新出现
  C7  悬浮态右上角 × 与菜单走同一条路（同样置 hidden + 落盘）
  C8  锚定态菜单同样只有一项「关闭」

运行：python tests/test_widget_close.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.storage import Storage
from src.widget_layer import WidgetLayer

STATE = Path(tempfile.gettempdir()) / "test_widget_close_state.json"

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


def menu_texts(menu):
    out = []
    for act in menu.actions():
        out.append("---" if act.isSeparator() else act.text())
    return out


def entry_of(st, wid):
    return next((e for e in st.widgets if e.get("id") == wid), None)


def press_close_button(w):
    """模拟点右上角 ×：直接投递一次按下事件到 _close_rect 中心。"""
    r = w._close_rect()
    assert not r.isEmpty(), "该组件没有 × 按钮（锚定态无 chrome）"
    local = QPointF(r.center())
    ev = QMouseEvent(QEvent.MouseButtonPress, local,
                     QPointF(w.mapToGlobal(r.center())),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    w.mousePressEvent(ev)


def main(app):
    st = make_state([
        # 悬浮便签：有 chrome（× 按钮）
        {"id": "nt", "type": "notes", "w": 240, "h": 240, "hidden": False,
         "anchored": False, "x": 60, "y": 60},
        # 锚定时钟：无 chrome，只有右键菜单
        {"id": "clk", "type": "clock", "w": 240, "h": 284, "hidden": False,
         "anchored": True, "col": 0, "row": 10, "colspan": 2, "rowspan": 2},
    ])
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)
    layer = WidgetLayer(st)
    QTest.qWait(120)

    check("C0 前置：两个组件都已创建",
          set(layer.widgets) == {"nt", "clk"}, "%s" % sorted(layer.widgets))

    float_w = layer.widgets["nt"]
    anchor_w = layer.widgets["clk"]

    # ---------- C1 / C2：菜单项合并 ----------
    ft = menu_texts(float_w._build_context_menu())
    at = menu_texts(anchor_w._build_context_menu())
    for tag, texts in (("悬浮", ft), ("锚定", at)):
        check("C1 %s态菜单不再有「隐藏」" % tag, "隐藏" not in texts, "%s" % texts)
        close_items = [t for t in texts if t == "关闭"]
        check("C2 %s态菜单恰有一个「关闭」" % tag, close_items == ["关闭"],
              "%s" % texts)
    check("C2b 悬浮态「关闭」是最后一项", ft[-1] == "关闭", "%s" % ft)
    check("C2c 锚定态「关闭」是最后一项", at[-1] == "关闭", "%s" % at)

    # ---------- C3 / C4 / C5：点「关闭」真的关掉且不复活 ----------
    menu = float_w._build_context_menu()
    act = next(a for a in menu.actions() if a.text() == "关闭")
    act.trigger()
    QTest.qWait(260)                       # 淡出 140ms + 余量

    check("C3 点「关闭」后 entry.hidden 为 True",
          bool(entry_of(st, "nt").get("hidden")))
    check("C4 hidden 已落盘", bool(entry_of(Storage(path=str(STATE)), "nt").get("hidden")),
          "磁盘 entry=%s" % entry_of(Storage(path=str(STATE)), "nt"))
    check("C5 层里已移除该 id", "nt" not in layer.widgets,
          "%s" % sorted(layer.widgets))
    # 原 BUG 判据：entry 未 hidden 时 _on_closed 会补建同 id 新实例。
    # 这里用一个显式的"重建诱饵"复核——直接再发一次 closed，若 entry 仍是
    # hidden，层必须拒绝重建（而不只是"这一次刚好没建"）。
    layer._on_closed("nt")
    QTest.qWait(60)
    check("C5b 重复 closed 也不会复活", "nt" not in layer.widgets,
          "%s" % sorted(layer.widgets))
    check("C5c 时钟未受影响", "clk" in layer.widgets, "%s" % sorted(layer.widgets))

    # ---------- C6：可恢复 ----------
    layer.toggle_entry("nt", True)
    QTest.qWait(160)
    check("C6 重新显示后回到层里", "nt" in layer.widgets,
          "%s" % sorted(layer.widgets))
    check("C6b 重新显示后 hidden 归 False",
          not entry_of(st, "nt").get("hidden"))

    # ---------- C7：右上角 × 走同一条路 ----------
    float_w2 = layer.widgets["nt"]
    press_close_button(float_w2)
    QTest.qWait(260)
    check("C7 点 × 后 entry.hidden 为 True",
          bool(entry_of(st, "nt").get("hidden")))
    check("C7b 点 × 后可恢复（落盘也一致）",
          bool(entry_of(Storage(path=str(STATE)), "nt").get("hidden")))
    check("C7c 点 × 后层里已移除且未复活", "nt" not in layer.widgets,
          "%s" % sorted(layer.widgets))

    # ---------- C8：锚定态同类行为 ----------
    am = anchor_w._build_context_menu()
    next(a for a in am.actions() if a.text() == "关闭").trigger()
    QTest.qWait(260)
    check("C8 锚定组件关闭后 hidden 为 True",
          bool(entry_of(st, "clk").get("hidden")))
    check("C8b 锚定组件关闭后层里为空", not layer.widgets,
          "%s" % sorted(layer.widgets))

    for w in list(layer.widgets.values()):
        w.close()
    QTest.qWait(200)
    layer.deleteLater()
    app.processEvents()

    print("-" * 56)
    print("%d checks" % len(CHECKS))
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL widget_close PASSED")
    return 0


if __name__ == "__main__":
    a = QApplication.instance() or QApplication(sys.argv)
    raise SystemExit(main(a))
