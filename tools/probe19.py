# -*- coding: utf-8 -*-
"""probe19：M4 位移引擎统一集成验证（2026-10-18，指导文档 §4.1/§7-M4）。

安全铁律（继承 probe14-18）：
  - offscreen 平台 + 临时 state.json，绝不碰用户真实状态与桌面
  - 不调用 show_desktop()（不挂桌面带、不隐藏原生图标）
  - try/finally + 看门狗 + 幂等收尾，保证进程必退

断言（M4 验收）：
  S0  WidgetLayer spawn 锚定 clock（2×2），信号链接线
  S1  组件拖动实时预览：真实鼠标事件链驱动 anchorHover——矩形内图标
      实时挤走、矩形外不动、AppIcon 实例不变、entry 占位只改内存
  S2  松手提交：anchorDrop 回退 + 吸附落定（落在格点上）→ 占位写盘 →
      gridChanged 正式 displace → 无图标压组件、实例不变
  S3  拖回原位：占位复位 + 图标让位/回填
  S4  add/remove 单图标增量（实例保持）
  S5  组件尺寸切换（_set_span）后 displace 仍正确（M3×M4 交叉）
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.desktop_window import DesktopWindow
from src.storage import Storage
from src.widget_layer import WidgetLayer

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "probe19_state.json"

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


def make_state(spec, widgets=()):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = False
    # 2026-10-19 反馈 3：未接管会自动进入无界模式，网格让位探针
    # 必须显式声明「按接管语义」（不 show 窗口，不会真隐藏原生图标）
    st._data["settings"]["takeover_desktop"] = True
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["widgets"] = [dict(w) for w in widgets]
    st._data["layout"] = [
        {"id": i, "type": "app",
         "app": {"name": i, "target": i, "kind": "app"},
         "col": c, "row": r}
        for i, c, r in spec]
    st.save()
    return st


def cells_of(st):
    return {e["id"]: (int(e["col"]), int(e["row"])) for e in st.layout}


def send_mouse(w, etype, local, buttons=Qt.LeftButton):
    """向组件发送合成鼠标事件（全局坐标 = 窗口坐标 + 局部，offscreen 单屏）。
    注意：PySide6 QTest.mouseMove 不支持 buttons 参数（坑 #3），必须自造。"""
    g = QPointF(w.pos()) + QPointF(local)
    ev = QMouseEvent(etype, QPointF(local), g, Qt.LeftButton, buttons,
                     Qt.NoModifier)
    QApplication.sendEvent(w, ev)


def run(app):
    st = make_state([("i1", 4, 0), ("i2", 5, 0), ("i3", 4, 1),
                     ("i4", 5, 1), ("i5", 6, 6)],
                    widgets=[{"id": "clk", "type": "clock", "w": 300,
                              "h": 160, "hidden": False, "anchored": True,
                              "col": 0, "row": 0}])
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    settle(app, 100)
    layer = WidgetLayer(st)
    layer.gridChanged.connect(w.on_widget_grid_changed)
    layer.anchorHover.connect(w._on_widget_hover)
    layer.anchorDrop.connect(w._on_widget_drop)
    settle(app, 150)

    cw, ch = grid_flow.cell_size(st)
    ox, oy = grid_flow.origin()
    ck = layer.widgets.get("clk")
    check("S0 WidgetLayer spawn 锚定 clock", ck is not None)
    check("S0 clock 落在 (0,0) 格点且尺寸 2×2",
          ck is not None and (ck.x(), ck.y()) == (ox, oy)
          and (ck.width(), ck.height()) == (2 * cw, 2 * ch),
          "pos=%s size=%s" % ((ck.x(), ck.y()) if ck else None,
                              (ck.width(), ck.height()) if ck else None))
    ids0 = {eid: id(ic) for eid, ic in w.icons.items()}
    check("S0 启动后无图标压在组件占位（main.py 同款兜底已由 spawn 前保证）",
          not any(cells_of(st)[i] in grid_flow.widget_cells(st)
                  for i in ("i1", "i2", "i3", "i4", "i5")))

    # ---------- S1：拖动实时预览 ----------
    press_local = QPoint(12, 12)               # 组件左上角内偏 12px
    send_mouse(ck, QEvent.MouseButtonPress, press_local)
    press_g = ck.pos() + press_local           # (60, 76)
    target_tl = QPoint(ox + 4 * cw, oy)        # 组件左上目标 = (4,0) 格点
    target_g = target_tl + press_local         # 指针目标全局
    for t in (1, 2, 3, 4, 5):
        gx = press_g.x() + (target_g.x() - press_g.x()) * t // 5
        gy = press_g.y() + (target_g.y() - press_g.y()) * t // 5
        send_mouse(ck, QEvent.MouseMove, QPoint(gx - ck.pos().x(),
                                                gy - ck.pos().y()))
        settle(app, 30)
    newrect = {(4, 0), (5, 0), (4, 1), (5, 1)}
    b = cells_of(st)
    check("S1 拖动预览：组件跟随指针（左上到 (4,0) 格点）",
          (ck.x(), ck.y()) == (target_tl.x(), target_tl.y()),
          "pos=%s" % ((ck.x(), ck.y()),))
    check("S1 拖动预览：新占位矩形内图标被实时挤走",
          all(b[i] not in newrect for i in ("i1", "i2", "i3", "i4")),
          "%s" % b)
    check("S1 拖动预览：矩形外图标 i5 不动", b["i5"] == (6, 6))
    check("S1 拖动预览：AppIcon 实例不变（无 rebuild）",
          all(id(w.icons.get(eid)) == i for eid, i in ids0.items()))
    entry = next(x for x in st.widgets if x.get("id") == "clk")
    check("S1 拖动预览：entry 占位仍为旧值（只改内存，未落盘）",
          (entry.get("col"), entry.get("row")) == (0, 0),
          "col=%s row=%s" % (entry.get("col"), entry.get("row")))

    # ---------- S2：松手提交（落在格点上的修复路径） ----------
    send_mouse(ck, QEvent.MouseButtonRelease, QPoint(target_g.x() - ck.pos().x(),
                                               target_g.y() - ck.pos().y()))
    settle(app, 400)
    check("S2 松手后组件停在 (4,0) 格点",
          (ck.x(), ck.y()) == (target_tl.x(), target_tl.y()))
    check("S2 entry 占位更新为 (4,0)（落在格点上也要同步——bug 修复路径）",
          (entry.get("col"), entry.get("row")) == (4, 0),
          "col=%s row=%s" % (entry.get("col"), entry.get("row")))
    b2 = cells_of(st)
    check("S2 displace 后无图标压组件最终占位",
          all(b2[i] not in newrect for i in ("i1", "i2", "i3", "i4")),
          "%s" % b2)
    check("S2 无重叠（5 图标 + 4 组件格）",
          len({b2[i] for i in b2} | grid_flow.widget_cells(st)) == 9)
    check("S2 AppIcon 实例仍不变（M4 核心：全程无 rebuild）",
          all(id(w.icons.get(eid)) == i for eid, i in ids0.items()))
    check("S2 预览状态已清空", w._widget_snap is None
          and w._widget_preview_rect is None)
    reloaded = Storage(path=str(STATE))
    check("S2 占位已落盘", (reloaded.widgets[0].get("col"),
                          reloaded.widgets[0].get("row")) == (4, 0))
    ok = all(abs(w.icons[i].x() - w._entry_pos(st.find_entry(i))[0]) <= 2
             and abs(w.icons[i].y() - w._entry_pos(st.find_entry(i))[1]) <= 2
             for i in w.icons)
    check("S2 全部图标动画到位", ok)

    # ---------- S3：拖回原位 ----------
    ck2 = layer.widgets["clk"]
    send_mouse(ck2, QEvent.MouseButtonPress, press_local)
    pg = ck2.pos() + press_local
    home_g = QPoint(ox, oy) + press_local
    for t in (1, 2, 3, 4, 5):
        gx = pg.x() + (home_g.x() - pg.x()) * t // 5
        gy = pg.y() + (home_g.y() - pg.y()) * t // 5
        send_mouse(ck2, QEvent.MouseMove, QPoint(gx - ck2.pos().x(),
                                                 gy - ck2.pos().y()))
        settle(app, 30)
    send_mouse(ck2, QEvent.MouseButtonRelease, QPoint(home_g.x() - ck2.pos().x(),
                                                home_g.y() - ck2.pos().y()))
    settle(app, 400)
    check("S3 拖回后组件停在 (0,0) 格点",
          (ck2.x(), ck2.y()) == (ox, oy))
    check("S3 entry 占位复位 (0,0)",
          (entry.get("col"), entry.get("row")) == (0, 0))
    b3 = cells_of(st)
    home_rect = {(0, 0), (1, 0), (0, 1), (1, 1)}
    check("S3 无图标压组件占位（回填后仍避开）",
          all(b3[i] not in home_rect for i in b3), "%s" % b3)
    check("S3 AppIcon 实例仍不变",
          all(id(w.icons.get(eid)) == i for eid, i in ids0.items()))

    # ---------- S4：add/remove 单图标增量 ----------
    w.add_app({"id": "new1", "name": "new1", "target": "new1", "kind": "app"})
    settle(app, 200)
    check("S4 add_app 增量：新图标在位", "new1" in w.icons)
    check("S4 add_app 增量：原有实例不变",
          all(id(w.icons.get(eid)) == i for eid, i in ids0.items()))
    w._on_remove_entry("i5")
    settle(app, 200)
    check("S4 remove 增量：目标移除、其余实例不变",
          "i5" not in w.icons
          and all(id(w.icons.get(eid)) == i for eid, i in ids0.items()
                  if eid in w.icons))

    # ---------- S5：尺寸切换后 displace（M3×M4 交叉） ----------
    ck2._set_span(4, 2)      # 组件变 4×2：col 0 -> 占 (0..3, 0..1)
    settle(app, 300)
    b5 = cells_of(st)
    big = {(c, r) for c in range(4) for r in range(2)}
    check("S5 4×2 后无图标压组件占位",
          all(b5[i] not in big for i in b5), "%s" % b5)
    check("S5 4×2 后实例不变", all(id(w.icons.get(eid)) == i
                                 for eid, i in ids0.items()
                                 if eid in w.icons))
    check("S5 4×2 占位写盘",
          (entry.get("colspan"), entry.get("rowspan")) == (4, 2))

    # ---------- 收尾 ----------
    ck2.close()
    settle(app, 250)


def main():
    app = QApplication([])
    wd = QTimer()
    wd.setSingleShot(True)
    wd.timeout.connect(lambda: (print("!! 看门狗超时", flush=True), os._exit(3)))
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
        print("ALL probe19 PASSED", flush=True)
        code = 0
    print("==== 探针退出 ====", flush=True)
    app.processEvents()
    QTimer.singleShot(80, app.quit)
    app.exec()
    return code


if __name__ == "__main__":
    sys.exit(main())
