# -*- coding: utf-8 -*-
"""probe21：M6 分页集成验证（2026-10-18，指导文档 §7-M6）。

安全铁律（继承 probe14-20）：
  - offscreen 平台 + 临时 state.json，绝不碰用户真实状态与桌面
  - 不调用 show_desktop()（不挂桌面带、不隐藏原生图标）
  - try/finally + 看门狗 + 幂等收尾，保证进程必退

断言（M6 验收）：
  S0  两页布局 spawn：首页条目屏内、次页条目屏下方；clock 锚定 page0
  S1  页点点击翻页：图标/组件实例不变 + 位置随页平移 + 持久化落盘
  S2  滚轮翻页（上滚上一页 / 下滚下一页 / 末页不越界）
  S3  add_app 落当前页第一个空格（不是全局第 0 页）
  S4  图标拖到页底：落点夹在当前页底行（不跨页）
  S5  组件拖到页底：entry row 夹紧到页内行范围（rowspan 不越页底）
  S6  DPI/窗口变大（rpp 变大、总页数变少）：越界当前页夹紧回末页
  S7  当前页持久化：重建 DesktopWindow 恢复页码
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.desktop_window import DesktopWindow
from src.storage import Storage
from src.widget_layer import WidgetLayer

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "probe21_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra), flush=True)
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
    st._data["settings"]["hide_native_icons"] = True   # 整理模式：翻页可交互
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


def send_mouse(w, etype, local, buttons=Qt.LeftButton):
    g = QPointF(w.pos()) + QPointF(local)
    ev = QMouseEvent(etype, QPointF(local), g, Qt.LeftButton, buttons,
                     Qt.NoModifier)
    QApplication.sendEvent(w, ev)


def send_wheel(w, local, angle_y):
    g = QPointF(w.pos()) + QPointF(local)
    ev = QWheelEvent(QPointF(local), g, QPoint(0, 0), QPoint(0, angle_y),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(w, ev)


def build(st):
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    layer = WidgetLayer(st)
    w.set_widget_layer(layer)
    layer.gridChanged.connect(w.on_widget_grid_changed)
    layer.anchorHover.connect(w._on_widget_hover)
    layer.anchorDrop.connect(w._on_widget_drop)
    return w, layer


def run(app):
    # 先用临时窗口确立 GridMetrics 快照——rpp/origin 都读它，
    # 快照未就绪时回退 (26,22)/8，与 1920x1040 真实值不同
    scratch = make_state([])
    w_scratch = DesktopWindow(scratch)
    w_scratch.resize(W, H)
    w_scratch._update_grid_metrics()
    settle(app, 100)
    rpp = grid_flow.rows_per_page()
    ox, oy = grid_flow.origin()

    # ---------- S0：两页布局 ----------
    st = make_state([("a", 0, 0, "app", []),
                     ("b", 1, 0, "app", []),
                     ("c", 0, rpp, "app", []),
                     ("d", 1, rpp, "app", []),
                     ("e", 0, 2 * rpp, "app", [])],
                    widgets=[{"id": "clk", "type": "clock", "w": 192,
                              "h": 228, "hidden": False, "anchored": True,
                              "col": 4, "row": 0}])
    cw, ch = grid_flow.cell_size(st)
    w, layer = build(st)
    settle(app, 250)
    check("S0 三页布局 page_count=3", grid_flow.page_count(st) == 3,
          "%s" % grid_flow.page_count(st))
    check("S0 首页条目在屏内",
          w.icons["a"].y() == oy and w.icons["b"].y() == oy)
    check("S0 次页条目在屏下方",
          w.icons["c"].y() == oy + rpp * ch
          and w.icons["d"].y() == oy + rpp * ch,
          "c.y=%s" % w.icons["c"].y())
    check("S0 第三页条目更靠下",
          w.icons["e"].y() == oy + 2 * rpp * ch)
    ck = layer.widgets.get("clk")
    check("S0 clock 锚定 page0 槽位并落在格点",
          ck is not None and (ck.x(), ck.y()) == (ox + 4 * cw, oy),
          "pos=%s" % (((ck.x(), ck.y())) if ck else None,))
    check("S0 clock 不压图标（displace 兜底）",
          all(w._entry_pos(st.find_entry(i))[:1] != (ox + 4 * cw,)
              or st.find_entry(i)["row"] != 0
              for i in ("a", "b")))

    # ---------- S1：页点点击翻页 ----------
    ids0 = {eid: id(ic) for eid, ic in w.icons.items()}
    dots = w._dot_centers()
    check("S1 三个页点", len(dots) == 3, "%s" % (dots,))
    send_mouse(w, QEvent.MouseButtonPress, dots[1])
    send_mouse(w, QEvent.MouseButtonRelease, dots[1])
    settle(app, 600)
    check("S1 点击第 2 点翻到 page1", w._page == 1)
    check("S1 page1：c/d 进屏内、a/b 滑出屏顶",
          w.icons["c"].y() == oy and w.icons["d"].y() == oy
          and w.icons["a"].y() == oy - rpp * ch,
          "a.y=%s c.y=%s" % (w.icons["a"].y(), w.icons["c"].y()))
    check("S1 page1：e 仍在屏下方",
          w.icons["e"].y() == oy + rpp * ch)
    check("S1 clock 随页滑出屏顶（实例不变）",
          ck is not None and ck.y() == oy - rpp * ch
          and id(layer.widgets.get("clk")) == id(ck),
          "ck.y=%s" % (ck.y() if ck else None))
    check("S1 图标实例全程不变",
          all(id(w.icons.get(eid)) == i for eid, i in ids0.items()))
    check("S1 current_page 落盘",
          Storage(path=str(STATE)).get_setting("current_page") == 1)

    # ---------- S2：滚轮翻页 ----------
    send_wheel(w, QPoint(W // 2, H // 2), 120)      # 下滚 -> page2
    settle(app, 600)
    check("S2 下滚到 page2", w._page == 2)
    check("S2 page2：e 进屏内", w.icons["e"].y() == oy)
    send_wheel(w, QPoint(W // 2, H // 2), 120)      # 末页再滚：不动
    settle(app, 400)
    check("S2 末页不越界", w._page == 2)
    send_wheel(w, QPoint(W // 2, H // 2), -120)     # 上滚 -> page1
    settle(app, 600)
    check("S2 上滚回 page1", w._page == 1)
    send_wheel(w, QPoint(W // 2, H // 2), -120)     # 再上滚 -> page0
    settle(app, 600)
    check("S2 上滚到 page0", w._page == 0)
    send_wheel(w, QPoint(W // 2, H // 2), -120)     # 首页再滚：不动
    settle(app, 400)
    check("S2 首页不越界", w._page == 0)

    # ---------- S3：add_app 落当前页 ----------
    send_mouse(w, QEvent.MouseButtonPress, dots[1])
    send_mouse(w, QEvent.MouseButtonRelease, dots[1])
    settle(app, 500)
    check("S3 前置：已回到 page1", w._page == 1)
    w.add_app({"id": "new1", "name": "new1", "target": "new1",
               "kind": "app"})
    settle(app, 300)
    e = st.find_entry("new1")
    check("S3 add_app 落当前页（page1）空格",
          e is not None and grid_flow.page_of(e["row"], rpp) == 1
          and (e["col"], e["row"]) == (2, rpp),
          "%s" % (((e.get("col"), e.get("row"))) if e else None,))
    check("S3 新图标在位", "new1" in w.icons)

    # ---------- S4：图标拖到页底不跨页 ----------
    # QDrag.exec() 在 offscreen 里递送不了 drop（probe17 同款结论），
    # 走信号级链路：_on_reflow_hover(全局坐标) -> _cell_at 页偏移 ->
    # reflow_moves -> _commit_preview 落盘
    w._on_drag_started()
    g = w.mapToGlobal(QPoint(ox + 6 * cw + cw // 4,
                            oy + (rpp - 1) * ch + ch // 4))  # page1 底行内部
    w._on_reflow_hover("new1", g.x(), g.y())
    b_hover = {i: (st.find_entry(i)["col"], st.find_entry(i)["row"])
               for i in ("a", "b", "c", "d", "e", "new1")}
    check("S4 hover 目标 = page1 底行 (6,15)（不跨页）",
          b_hover["new1"] == (6, rpp + rpp - 1), "%s" % (b_hover["new1"],))
    w._commit_preview()
    settle(app, 500)
    b = {i: (st.find_entry(i)["col"], st.find_entry(i)["row"])
         for i in ("a", "b", "c", "d", "e", "new1")}
    check("S4 提交落盘：落点夹在 page1 底行",
          b["new1"] == (6, rpp + rpp - 1), "%s" % (b["new1"],))
    check("S4 落点后无重叠（6 条目占 6 格）", len(set(b.values())) == 6,
          "%s" % b)
    check("S4 落点后无图标压组件",
          not any(v in grid_flow.widget_cells(st) for v in b.values()))
    reloaded = Storage(path=str(STATE))
    check("S4 落点已落盘",
          (reloaded.find_entry("new1")["col"],
           reloaded.find_entry("new1")["row"]) == (6, rpp + rpp - 1))

    # ---------- S5：组件拖到页底（rowspan 不越页底） ----------
    # 回 page0 拖 clock 到页面底部：entry row 应夹到 rpp-2（2 行跨度）
    send_mouse(w, QEvent.MouseButtonPress, dots[0])
    send_mouse(w, QEvent.MouseButtonRelease, dots[0])
    settle(app, 500)
    check("S5 前置：回到 page0", w._page == 0)
    ck = layer.widgets["clk"]
    send_mouse(ck, QEvent.MouseButtonPress, QPoint(12, 12))
    target_g = QPoint(ox + 4 * cw + 12, oy + (rpp - 1) * ch + ch // 2)
    for t in (1, 2, 3, 4, 5):
        gx = ck.pos().x() + 12 + (target_g.x() - ck.pos().x() - 12) * t // 5
        gy = ck.pos().y() + 12 + (target_g.y() - ck.pos().y() - 12) * t // 5
        send_mouse(ck, QEvent.MouseMove,
                   QPoint(gx - ck.pos().x(), gy - ck.pos().y()))
        settle(app, 40)
    send_mouse(ck, QEvent.MouseButtonRelease,
               QPoint(target_g.x() - ck.pos().x(),
                      target_g.y() - ck.pos().y()))
    settle(app, 600)
    went = next(x for x in st.widgets if x.get("id") == "clk")
    check("S5 组件 row 夹到页内（2 行跨度不越页底）",
          went.get("row") == rpp - 2,
          "row=%s colspan/rowspan=%s/%s" % (went.get("row"),
                                            went.get("colspan"),
                                            went.get("rowspan")))
    check("S5 组件像素位置与 entry 一致",
          (ck.x(), ck.y()) == grid_flow.cell_pos(st, went["col"],
                                                 went["row"]),
          "pos=%s expect=%s" % ((ck.x(), ck.y()),
                                grid_flow.cell_pos(st, went["col"],
                                                   went["row"])))

    # ---------- S6：窗口变大（rpp 变大）页夹紧 ----------
    # 顺序：先小窗（rpp 小、页多）翻到第 3 页 -> 再放大窗（rpp 大、
    # 总页数变少）触发越界夹紧。布局 max_row=8：大窗 rpp=8 时共 2 页。
    st2 = make_state([("x%d" % r, 0, r, "app", []) for r in (0, 4, 8)])
    w2 = DesktopWindow(st2)
    w2.resize(640, 360)          # 小窗：rpp=2 -> 5 页
    w2._update_grid_metrics()
    settle(app, 200)
    small_rpp = grid_flow.rows_per_page()
    check("S6 小窗 rpp 变小", small_rpp < rpp, "rpp=%s" % small_rpp)
    check("S6 小窗总页数变多", grid_flow.page_count(st2) == 5,
          "total=%s" % grid_flow.page_count(st2))
    w2.goto_page(2)
    settle(app, 200)
    check("S6 前置：小窗翻到 page2", w2._page == 2, "page=%s" % w2._page)
    w2.resize(W, H)              # 大窗：rpp=8 -> 2 页 -> 夹紧
    w2._update_grid_metrics()
    settle(app, 300)
    total = grid_flow.page_count(st2)
    check("S6 大窗总页数变少且当前页夹紧回末页",
          total == 2 and w2._page == total - 1 and w2._page < 2,
          "page=%s total=%s" % (w2._page, total))
    check("S6 夹紧已落盘",
          Storage(path=str(STATE)).get_setting("current_page") == w2._page)

    # ---------- S7：持久化恢复 ----------
    st3_state = make_state([("y0", 0, 0, "app", []),
                            ("y1", 0, rpp, "app", [])],
                           settings={"current_page": 1})
    w3 = DesktopWindow(st3_state)
    w3.resize(W, H)
    w3._update_grid_metrics()
    settle(app, 200)
    check("S7 重建窗口恢复 page1", w3._page == 1
          and grid_flow.current_page() == 1)
    check("S7 page1 条目在屏内",
          abs(w3.icons["y1"].y() - oy) <= 2
          and w3.icons["y0"].y() == oy - rpp * ch)

    # ---------- 收尾 ----------
    for ww in (w, w2, w3):
        try:
            ww.close()
        except Exception:
            pass
    settle(app, 300)


def main():
    app = QApplication([])
    wd = QTimer()
    wd.setSingleShot(True)
    wd.timeout.connect(lambda: (print("!! 看门狗超时", flush=True),
                                os._exit(3)))
    wd.start(90000)
    try:
        run(app)
    except Exception:
        import traceback
        traceback.print_exc()
        failures.append("run() 异常")
    finally:
        try:
            STATE.unlink()
        except Exception:
            pass
    print("-" * 56, flush=True)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures), flush=True)
        code = 1
    else:
        print("ALL probe21 PASSED", flush=True)
        code = 0
    print("==== 探针退出 ====", flush=True)
    app.processEvents()
    QTimer.singleShot(80, app.quit)
    app.exec()
    return code


if __name__ == "__main__":
    sys.exit(main())
