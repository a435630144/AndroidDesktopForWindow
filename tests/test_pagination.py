# -*- coding: utf-8 -*-
"""M6 分页：行->页映射 / 页内位置换算 / 翻页 / 落点限页（指导文档 §7-M6）。

运行：python tests/test_pagination.py   （offscreen，无需显示桌面）

覆盖（先 Red 后 Green）：
  T1  纯函数：page_of / local_row / page_count / page_row_range 边界
  T2  rows_per_page：GridMetrics.rows 快照 / 未初始化回退
  T3  cell_pos/pos_cell 往返 + 页偏移 + col 夹紧
  T4  _entry_pos 页内映射：row 8（rpp=8）在 page0 屏外、page1 屏内
  T5  goto_page：持久化 current_page + grid_flow 运行时页同步 +
      图标 animate 目标随页平移 + 实例不变
  T6  _cell_at 页偏移：page=1 时 y=oy 反算出全局 row=8
  T7  first_free_cell_in_page：当前页空格 / 当前页满返回 None
  T8  page_count 计入 widget 跨度（row 7 + rs 2 -> 2 页）
  T9  页夹紧：page_count 变小后 goto_page 回退到末页
  T10 find_widget_slot 限当前页行范围
  T11 snap_point 页偏移（像素吸附到当前页局部行）
  T12 add_app 落当前页第一个空格
  T13 页点：_dots_rect 底部居中几何 + 点击翻页
  T14 滚轮翻页（整理模式）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QEventLoop, QPointF, Qt, QTimer
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.desktop_window import DesktopWindow
from src.storage import Storage

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_m6_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=300):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make_state(spec, widgets=(), settings=None):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = False
    st._data["settings"]["auto_clone_desktop"] = False
    for k, v in (settings or {}).items():
        st._data["settings"][k] = v
    st._data["widgets"] = [dict(w) for w in widgets]
    st._data["layout"] = [
        {"id": i, "type": t,
         "app": None if t == "folder" else {"name": i, "target": i,
                                            "kind": "app"},
         "apps": apps, "col": c, "row": r}
        for i, c, r, t, apps in spec]
    st.save()
    return st


def send_click(w, local):
    from PySide6.QtGui import QMouseEvent
    g = QPointF(w.pos()) + QPointF(local)
    for etype in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        ev = QMouseEvent(etype, QPointF(local), g, Qt.LeftButton,
                         Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(w, ev)


def send_wheel(w, local, angle_y):
    from PySide6.QtCore import QPoint
    g = QPointF(w.pos()) + QPointF(local)
    ev = QWheelEvent(QPointF(local), g, QPoint(0, 0), QPoint(0, angle_y),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(w, ev)


def fresh_window(st):
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    return w


def main(app):
    rpp = 8      # 1920x1040 窗口：rows = (1040-44)//114 = 8
    cw, ch = 96, 114

    # ---------- T1：纯函数边界 ----------
    check("T1 page_of 基本", grid_flow.page_of(0, 8) == 0
          and grid_flow.page_of(7, 8) == 0
          and grid_flow.page_of(8, 8) == 1
          and grid_flow.page_of(23, 8) == 2)
    check("T1 page_of 负行回退 0 页", grid_flow.page_of(-3, 8) == 0)
    check("T1 local_row 基本", grid_flow.local_row(0, 8) == 0
          and grid_flow.local_row(7, 8) == 7
          and grid_flow.local_row(8, 8) == 0
          and grid_flow.local_row(19, 8) == 3)
    check("T1 page_count 至少 1 页",
          grid_flow.page_number(0, 8) == 1
          and grid_flow.page_number(-5, 8) == 1)
    check("T1 page_count 跨页", grid_flow.page_number(8, 8) == 2
          and grid_flow.page_number(16, 8) == 3)
    check("T1 page_row_range 组件不越页底",
          grid_flow.page_row_range(0, 8, 1) == (0, 7)
          and grid_flow.page_row_range(0, 8, 2) == (0, 6)
          and grid_flow.page_row_range(1, 8, 2) == (8, 14)
          and grid_flow.page_row_range(1, 8, 9) == (8, 8))

    # ---------- T2：rows_per_page ----------
    st0 = make_state([])
    w0 = fresh_window(st0)
    check("T2 rows_per_page = GridMetrics.rows（1920x1040 -> 8）",
          grid_flow.rows_per_page() == rpp, "%s" % grid_flow.rows_per_page())
    saved = grid_flow.current_metrics()
    grid_flow.set_grid(st0, (0, 0))     # 极端小屏 clamp 到 MIN_ROWS=1
    check("T2 小屏 clamp 后 rows_per_page 跟随",
          grid_flow.rows_per_page() == 1)
    grid_flow._current_metrics = saved   # 还原快照

    # ---------- T3：cell_pos / pos_cell ----------
    ox, oy = grid_flow.origin()
    check("T3 cell_pos 当前页局部映射",
          grid_flow.cell_pos(st0, 2, 3) == (ox + 2 * cw, oy + 3 * ch))
    grid_flow.set_page(1)
    check("T3 cell_pos 次页行翻页后进屏内",
          grid_flow.cell_pos(st0, 2, 3 + rpp) == (ox + 2 * cw, oy + 3 * ch),
          "%s" % (grid_flow.cell_pos(st0, 2, 3 + rpp),))
    check("T3 cell_pos 首页行翻页后滑出屏顶（rel 为负）",
          grid_flow.cell_pos(st0, 2, 3) == (ox + 2 * cw,
                                            oy + (3 - rpp) * ch),
          "%s" % (grid_flow.cell_pos(st0, 2, 3),))
    check("T3 pos_cell 反算 + 页偏移",
          grid_flow.pos_cell(st0, ox + 2 * cw, oy + 3 * ch) == (2, 3 + rpp))
    grid_flow.set_page(0)
    check("T3 pos_cell page0 反算",
          grid_flow.pos_cell(st0, ox + 2 * cw, oy + 3 * ch) == (2, 3))
    check("T3 pos_cell 列夹紧 [0, cols-1]",
          grid_flow.pos_cell(st0, ox - 500, oy)[0] == 0
          and grid_flow.pos_cell(st0, ox + 5000, oy)[0] == st0.columns - 1)

    # ---------- T4：_entry_pos 页内映射 ----------
    st = make_state([("p0", 0, 0, "app", []),
                     ("p1", 0, rpp, "app", []),
                     ("p2", 1, rpp + 1, "app", [])])
    w = fresh_window(st)
    check("T4 page0 条目在屏内",
          w._entry_pos(st.find_entry("p0")) == (ox, oy))
    check("T4 次页条目在屏外（y = oy + rpp*ch，屏下方）",
          w._entry_pos(st.find_entry("p1"))[1] == oy + rpp * ch
          and w._entry_pos(st.find_entry("p2"))[1] == oy + (rpp + 1) * ch,
          "%s" % (w._entry_pos(st.find_entry("p1")),))
    grid_flow.set_page(1)
    check("T4 翻到 page1 后次页条目进屏内、首页条目出屏",
          w._entry_pos(st.find_entry("p1")) == (ox, oy)
          and w._entry_pos(st.find_entry("p2")) == (ox + cw, oy + ch)
          and w._entry_pos(st.find_entry("p0"))[1] == oy - rpp * ch,
          "%s" % (w._entry_pos(st.find_entry("p0")),))
    grid_flow.set_page(0)

    # ---------- T5：goto_page ----------
    ids0 = {eid: id(ic) for eid, ic in w.icons.items()}
    w.goto_page(1)
    settle(app, 400)
    check("T5 goto_page 持久化 current_page",
          st.get_setting("current_page") == 1,
          "%s" % st.get_setting("current_page"))
    check("T5 grid_flow 运行时页同步", grid_flow.current_page() == 1)
    ok = all(abs(w.icons[i].x() - w._entry_pos(st.find_entry(i))[0]) <= 2
             and abs(w.icons[i].y() - w._entry_pos(st.find_entry(i))[1]) <= 2
             for i in w.icons)
    check("T5 图标动画到新页位置", ok)
    check("T5 实例不变（翻页不 rebuild）",
          all(id(w.icons.get(eid)) == i for eid, i in ids0.items()))
    reloaded = Storage(path=str(STATE))
    check("T5 current_page 已落盘", reloaded.get_setting("current_page") == 1)

    # ---------- T6：_cell_at 页偏移 ----------
    check("T6 page1 下 y=oy 反算全局 row=8",
          w._cell_at(QPointF(ox + 10, oy + 10)) == (0, rpp),
          "%s" % (w._cell_at(QPointF(ox + 10, oy + 10)),))
    check("T6 page1 底部行不越页（row 15 上限）",
          w._cell_at(QPointF(ox + 10, oy + 7 * ch + ch - 2))[1] == rpp + 7)

    # ---------- T7：first_free_cell_in_page ----------
    st2 = make_state([("a", 0, 0, "app", []), ("b", 1, 0, "app", [])])
    w2 = fresh_window(st2)
    check("T7 当前页第一个空格 = (2,0)",
          grid_flow.first_free_cell_in_page(st2, 0) == (2, 0),
          "%s" % (grid_flow.first_free_cell_in_page(st2, 0),))
    check("T7 page1 全空 -> (0,8)",
          grid_flow.first_free_cell_in_page(st2, 1) == (0, rpp))
    # 填满 page0
    for c in range(st2.columns):
        for r in range(rpp):
            if (c, r) in ((0, 0), (1, 0)):
                continue
            st2._data["layout"].append(
                {"id": "f_%d_%d" % (c, r), "type": "app",
                 "app": {"name": "f", "target": "f", "kind": "app"},
                 "col": c, "row": r})
    check("T7 当前页满 -> None",
          grid_flow.first_free_cell_in_page(st2, 0) is None,
          "%s" % (grid_flow.first_free_cell_in_page(st2, 0),))

    # ---------- T8：page_count 计入 widget 跨度 ----------
    st3 = make_state([("a", 0, 0, "app", [])],
                     widgets=[{"id": "clk", "type": "clock", "w": 192,
                               "h": 228, "hidden": False, "anchored": True,
                               "col": 0, "row": rpp - 1, "colspan": 2,
                               "rowspan": 2}])
    check("T8 widget 跨页底计入 page_count",
          grid_flow.page_count(st3) == 2,
          "%s" % grid_flow.page_count(st3))

    # ---------- T9：页夹紧 ----------
    st4 = make_state([("a", 0, 0, "app", [])],
                     settings={"current_page": 3})
    w4 = fresh_window(st4)
    check("T9 启动时越界页夹紧到末页",
          w4._page == 0 and grid_flow.current_page() == 0,
          "page=%s" % w4._page)
    check("T9 夹紧后已落盘", Storage(path=str(STATE))
          .get_setting("current_page") == 0)

    # ---------- T10：find_widget_slot 限当前页 ----------
    st5 = make_state([("a", 0, 0, "app", []),
                      ("b", 1, 0, "app", [])],
                     widgets=[{"id": "clk", "type": "clock", "w": 192,
                               "h": 228, "hidden": False, "anchored": True,
                               "col": 0, "row": 0, "colspan": 2, "rowspan": 2}])
    slot = grid_flow.find_widget_slot(st5, {"type": "clock"}, page=0)
    check("T10 page0 组件槽位避开图标与既有组件",
          slot == (2, 0), "%s" % (slot,))
    slot1 = grid_flow.find_widget_slot(st5, {"type": "clock"}, page=1)
    check("T10 page1 槽位在页内行范围",
          slot1 is not None and rpp <= slot1[1] <= 2 * rpp - 2,
          "%s" % (slot1,))

    # ---------- T11：snap_point 页偏移 ----------
    grid_flow.set_page(1)
    sx, sy = grid_flow.snap_point(st5, ox + 10, oy + 10, (W, H))
    check("T11 page1 下 snap_point 落在页内格点像素",
          (sx, sy) == (ox, oy), "(%s,%s)" % (sx, sy))
    grid_flow.set_page(0)

    # ---------- T12：add_app 落当前页 ----------
    st6 = make_state([("a", 0, 0, "app", []), ("b", 1, 0, "app", [])])
    w6 = fresh_window(st6)
    grid_flow.set_page(1)
    w6.add_app({"id": "new1", "name": "new1", "target": "new1",
                "kind": "app"})
    settle(app, 200)
    e = st6.find_entry("new1")
    check("T12 add_app 落当前页（page1）第一个空格",
          e is not None and (e["col"], e["row"]) == (0, rpp),
          "%s" % (((e.get("col"), e.get("row"))) if e else None,))
    check("T12 新图标增量在位", "new1" in w6.icons)
    grid_flow.set_page(0)

    # ---------- T13：页点 ----------
    # 页点/滚轮按设计只在整理模式可点（原生模式空白区事件穿透真实桌面）
    st7 = make_state([("a", 0, 0, "app", []),
                      ("b", 0, rpp, "app", [])],
                     settings={"hide_native_icons": True})
    w7 = fresh_window(st7)
    dr = w7._dots_rect()
    check("T13 页点矩形存在且位于底部",
          dr is not None and dr.bottom() <= H and dr.top() > H // 2,
          "%s" % (dr,))
    check("T13 页点水平居中",
          dr is not None and abs(dr.center().x() - W // 2) <= 2,
          "cx=%s" % (dr.center().x() if dr else None))
    n_before = grid_flow.current_page()
    send_click(w7, dr.center())          # 点第 1 个点 = page0（当前已在）
    settle(app, 300)
    check("T13 点击当前页dot 不翻页", grid_flow.current_page() == n_before)
    dots = w7._dot_centers()
    check("T13 两个页点", len(dots) == 2, "%s" % (dots,))
    send_click(w7, dots[1])
    settle(app, 400)
    check("T13 点击第 2 个点翻到 page1",
          grid_flow.current_page() == 1 and w7._page == 1)
    check("T13 翻页后图标位置更新",
          abs(w7.icons["b"].y() - w7._entry_pos(st7.find_entry("b"))[1]) <= 2)

    # ---------- T14：滚轮翻页 ----------
    send_wheel(w7, QPointF(W // 2, H // 2), -120)   # 上滚 -> 上一页
    settle(app, 400)
    check("T14 滚轮上滚翻回 page0", grid_flow.current_page() == 0,
          "page=%s" % grid_flow.current_page())
    send_wheel(w7, QPointF(W // 2, H // 2), 120)    # 下滚 -> 下一页
    settle(app, 400)
    check("T14 滚轮下滚翻到 page1", grid_flow.current_page() == 1,
          "page=%s" % grid_flow.current_page())
    send_wheel(w7, QPointF(W // 2, H // 2), 120)    # 已到末页：不动
    settle(app, 300)
    check("T14 末页再滚不越界", grid_flow.current_page() == 1)

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL pagination PASSED")
    return 0


def run_main():
    app = QApplication([])
    wd = QTimer()
    wd.setSingleShot(True)
    wd.timeout.connect(lambda: (print("!! 看门狗超时"), os._exit(3)))
    wd.start(60000)
    try:
        code = main(app)
    except Exception:
        import traceback
        traceback.print_exc()
        failures.append("main() 异常")
        code = 1
    finally:
        try:
            STATE.unlink()
        except Exception:
            pass
    app.processEvents()
    QTimer.singleShot(80, app.quit)
    app.exec()
    return code


if __name__ == "__main__":
    sys.exit(run_main())
