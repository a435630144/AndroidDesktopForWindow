# -*- coding: utf-8 -*-
"""v6 批次 C §1.3：双模式的窗口层行为（切换 / 自由落点 / 空白页 / 组件）。

覆盖指导文档_网格与无界双模式_v6.md §1.2/§1.3 的窗口侧契约：
  W1 切无界：图标尺寸**不变**（v7 B2 尺寸单源），切换瞬间视觉原位
  W2 无界松手：条目落到拖影像素位（夹紧画布），其他图标不让位
  W3 切回网格：col/row 原样（不吸附）、fx/fy 保留（v7 B2 双坐标）
  W4 无界模式让位预览空转（_reflow_preview 不改布局）
  W5 无界模式组件不占格（_widget_cells 空集）
  W6 空白页：追加 -> page_count 增长 -> 可翻页 -> 可删
  W7 WidgetLayer.apply_layout_mode：锚定组件在无界模式落到 fx/fy

运行：python tests/test_dual_mode_window.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QPoint, QTimer
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.desktop_window import DesktopWindow
from src.storage import Storage
from src.widget_layer import WidgetLayer

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_dual_window_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=400):
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
        {"id": i, "type": "app",
         "app": {"name": i, "target": i, "kind": "app"},
         "col": c, "row": r}
        for i, c, r in spec]
    st.save()
    return st


def new_window(app, st):
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    settle(app, 100)
    return w


def cells_of(st):
    return {e["id"]: (int(e["col"]), int(e["row"])) for e in st.layout}


def main(app):
    # ---------- W1：切无界——尺寸体系换档 + 视觉原位 ----------
    st = make_state([("a", 0, 0), ("b", 1, 0), ("c", 2, 0)])
    w = new_window(app, st)
    pos_grid = {eid: w.icons[eid].pos() for eid in ("a", "b", "c")}
    grid_size = (w.icons["a"].width(), w.icons["a"].height())
    w.set_layout_mode("free")
    check("W1 模式已切到 free", grid_flow.free_mode(st))
    # v7 B2（反馈 11）：尺寸单源——切模式图标像素**不许变**，否则整套图标
    # 从 cell×占比 跳到 96px，视觉上"挤成一坨"
    check("W1 切无界图标尺寸不变（尺寸单源）",
          (w.icons["a"].width(), w.icons["a"].height()) == grid_size,
          "grid=%s free=%s" % (grid_size, (w.icons["a"].width(), w.icons["a"].height())))
    check("W1 切换瞬间视觉原位（无跳变）",
          all(w.icons[eid].pos() == pos_grid[eid] for eid in pos_grid),
          "%s vs %s" % ({e: w.icons[e].pos() for e in pos_grid}, pos_grid))
    check("W1 条目已带 fx/fy", all("fx" in e and "fy" in e for e in st.layout))

    # ---------- W2：无界松手——像素落点 + 不让位 ----------
    before_free = {eid: (e.get("fx"), e.get("fy")) for eid, e in
                   ((e["id"], e) for e in st.layout)}
    icon = w.icons["a"]
    w._drag_entry_id = "a"
    icon._press_pos = QPoint(10, 10)
    icon.grabMouse = lambda: None
    icon.setFocus = lambda: None
    icon._exec_drag()
    ghost = icon._drag_ghost_w
    check("W2 拖影已创建", ghost is not None)
    if ghost is not None:
        # 把拖影移到画布中部一个非格点位置
        ghost.move(500, 300)
        w._drop_internal("a", QPoint(500, 300))
        ea = st.find_entry("a")
        check("W2 松手落点是拖影像素位（不吸附格点）",
              (ea.get("fx"), ea.get("fy")) == (500, 300),
              "%s" % ((ea.get("fx"), ea.get("fy")),))
        # v7 B2：页归属写 fpage，**不动网格坐标 row**（否则切回网格会重叠）
        check("W2 页号写 fpage 且 row 不被改写",
              int(ea.get("fpage", -1)) == 0 and ea.get("row") == 0,
              "fpage=%r row=%r" % (ea.get("fpage"), ea.get("row")))
        check("W2 其他图标不让位（b/c 的 fx/fy 不变）",
              before_free["b"] == (st.find_entry("b").get("fx"),
                                   st.find_entry("b").get("fy"))
              and before_free["c"] == (st.find_entry("c").get("fx"),
                                       st.find_entry("c").get("fy")))
        # 夹紧：拖影移出画布右侧 -> x 夹到 W - 图标宽
        ghost.move(99999, 300)
        w._drop_internal("a", QPoint(99999, 300))
        ea = st.find_entry("a")
        check("W2 越界夹紧进画布", ea.get("fx") <= W - w.icons["a"].width(),
              "fx=%s" % ea.get("fx"))
        ghost.close()
    icon.set_drag_ghost(False)

    # ---------- W4：无界让位预览空转 ----------
    w._on_drag_started()
    w._reflow_preview("a", (2, 0))
    check("W4 无界模式预览不生成", w._preview_moves is None)
    check("W4 无界模式布局不被预览改写",
          (st.find_entry("a").get("fx"), st.find_entry("a").get("fy")) != (None, None))

    # ---------- W5：组件不占格 ----------
    check("W5 无界模式 _widget_cells 空集", w._widget_cells() == set())

    # ---------- W3：切回网格——col/row 原样 + fx/fy 保留（v7 B2） ----------
    st.find_entry("a")["fx"], st.find_entry("a")["fy"] = 500, 300
    cells_before_grid = cells_of(st)
    w.set_layout_mode("grid")
    check("W3 模式已切回 grid", not grid_flow.free_mode(st))
    check("W3 fx/fy 仍保留（无界摆位不丢）",
          all(("fx" in e and "fy" in e) for e in st.layout),
          "%s" % [(e["id"], e.get("fx")) for e in st.layout])
    check("W3 col/row 与切走前逐条相同（不被吸附覆盖）",
          cells_of(st) == cells_before_grid,
          "%s vs %s" % (cells_of(st), cells_before_grid))
    check("W3 图标尺寸仍是同一套",
          (w.icons["a"].width(), w.icons["a"].height()) == grid_size)

    # ---------- W6：空白页 ----------
    st2 = make_state([("x", 0, 0)], settings={"layout_mode": "free"})
    w2 = new_window(app, st2)
    w2.set_layout_mode("free")      # 已是 free：幂等
    base_pages = grid_flow.page_count(st2)
    check("W6 初始 1 页", base_pages == 1)
    w2._add_blank_page()
    check("W6 追加空白页后 page_count=2 且已翻过去",
          grid_flow.page_count(st2) == 2 and w2._page == 1,
          "pages=%d page=%d extras=%s" % (grid_flow.page_count(st2), w2._page,
                                          grid_flow.extra_pages(st2)))
    w2._add_blank_page()
    check("W6 再追加一页 -> 3 页", grid_flow.page_count(st2) == 3)
    w2.goto_page(1)
    w2._remove_blank_page()
    check("W6 删除空白页（页码 1）后 extras 去掉 1（页 2 的空白页仍在）",
          grid_flow.page_count(st2) == 3 and 1 not in grid_flow.extra_pages(st2),
          "extras=%s" % (grid_flow.extra_pages(st2),))
    # 有数据的页不可删
    w2.goto_page(0)
    w2._remove_blank_page()
    check("W6 有数据的页拒绝删除（extras 不变）",
          grid_flow.extra_pages(st2) == [2],
          "%s" % (grid_flow.extra_pages(st2),))

    # ---------- W7：WidgetLayer 模式切换重排 ----------
    st3 = make_state([("i", 0, 0)],
                     widgets=[{"id": "clk", "type": "clock", "w": 300, "h": 160,
                               "hidden": False, "anchored": True,
                               "col": 2, "row": 0}])
    w3 = new_window(app, st3)
    layer = WidgetLayer(st3)
    w3.set_widget_layer(layer)
    settle(app, 200)
    cw3, ch3 = grid_flow.cell_size(st3)
    ox3, oy3 = grid_flow.origin()
    aw = layer.widgets.get("clk")
    check("W7 网格模式锚定组件在格点", aw is not None and aw.pos() == QPoint(ox3 + 2 * cw3, oy3),
          "%s" % (aw.pos() if aw else None,))
    # 网格 spawn 已把 w/h 覆写为 span 派生值——切无界后应原样保留
    # （不再按 span 重新推导，用户像素尺寸权威在 entry.w/h）
    wh_before = (st3.widgets[0].get("w"), st3.widgets[0].get("h"))
    w3.set_layout_mode("free")
    aw2 = layer.widgets.get("clk")
    fx, fy = st3.widgets[0].get("fx"), st3.widgets[0].get("fy")
    check("W7 无界模式组件落到 fx/fy",
          aw2 is not None and aw2.pos() == QPoint(fx, fy),
          "pos=%s fx/fy=%s" % (aw2.pos() if aw2 else None, (fx, fy)))
    check("W7 无界模式不按 span 重设尺寸（entry w/h 原样保留）",
          (st3.widgets[0].get("w"), st3.widgets[0].get("h")) == wh_before,
          "before=%s after=%s" % (wh_before, (st3.widgets[0].get("w"),
                                              st3.widgets[0].get("h"))))
    check("W7 无界模式组件视觉尺寸 = entry w/h",
          aw2 is not None and (aw2.width(), aw2.height()) == wh_before)

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL dual_mode_window PASSED")
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
    return code


if __name__ == "__main__":
    sys.exit(run_main())
