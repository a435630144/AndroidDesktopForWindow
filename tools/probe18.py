# -*- coding: utf-8 -*-
"""probe18：M3 组件跨度化集成验证（2026-10-18，指导文档 §3.4 验收）。

安全铁律（继承 probe14/15/16/17）：
  - offscreen 平台 + 临时 state.json，绝不碰用户真实状态与桌面
  - 不调用 show_desktop()（不挂桌面带、不隐藏原生图标）
  - try/finally + 看门狗 + 幂等收尾，保证进程必退

断言（§3.4 验收标准）：
  S0  catalog 一等公民：clock 默认 2×2，pixel_size = span × cell
  S1  锚定 clock spawn 尺寸 = 2×cell（240×284），entry w/h 同步
  S2  widget_cells 4 格精确展开；displace 把图标挤出组件占位
  S3  clock 排版：字号按高度比例 + 2×2 内容零溢出
  S4  _set_span 切换：尺寸/entry/col 夹紧/gridChanged/字号重排
  S5  右键「组件尺寸」菜单：单尺寸不出现；多尺寸出现且当前项勾选
  S6  字号随高度缩放（2×2 -> 2×4）
  S7  悬浮态不推导尺寸（legacy 像素）
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QPoint, QTimer
from PySide6.QtWidgets import QApplication, QMenu

from src import grid_flow, widget_catalog
from src.desktop_window import DesktopWindow
from src.storage import Storage
from src.widgets_clock import ClockWidget

W, H = 1920, 1040  # 100% DPI 工作区（验收场景：19 列 8 行）
STATE = Path(tempfile.gettempdir()) / "probe18_state.json"

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
    """spec: [(id, col, row), ...] -> (Storage, path)。禁用自动克隆/隐藏图标。"""
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = False
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["widgets"] = [dict(w) for w in widgets]
    st._data["layout"] = [
        {"id": i, "type": "app",
         "app": {"name": i, "target": i, "kind": "app"},
         "col": c, "row": r}
        for i, c, r in spec]
    st.save()
    return st


def by_id(st):
    return {e["id"]: (int(e["col"]), int(e["row"])) for e in st.layout}


def clock_entry(**kw):
    e = {"id": "clock", "type": "clock", "w": 300, "h": 160,
         "hidden": False, "anchored": True, "x": 400, "y": 300}
    e.update(kw)
    return e


def run(app):
    st = make_state([("a", 0, 0), ("b", 1, 0), ("c", 2, 0)])
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    settle(app, 100)

    m = grid_flow.current_metrics()
    cw, ch = grid_flow.cell_size(st)
    ox, oy = grid_flow.origin()
    check("S0 GridMetrics 就绪（19 列 8 行）",
          m is not None and m.cols == 19 and m.rows == 8,
          "cols=%s rows=%s cell=%s" % (m.cols if m else None,
                                       m.rows if m else None, (cw, ch)))

    # ---------- S0：catalog 一等公民 ----------
    check("S0 catalog: clock 默认跨度 2×2",
          widget_catalog.default_span("clock") == (2, 2))
    check("S0 pixel_size(clock) == 2×cell",
          widget_catalog.pixel_size(st, "clock") == (2 * cw, 2 * ch),
          "%s" % (widget_catalog.pixel_size(st, "clock"),))

    # ---------- S1：锚定 clock spawn 尺寸 = span × cell ----------
    entry = clock_entry()
    ck = ClockWidget(st, entry)
    settle(app, 100)
    check("S1 锚定 clock 尺寸 = 2×cell（碰撞 = 视觉边界）",
          (ck.width(), ck.height()) == (2 * cw, 2 * ch),
          "size=%s expect=%s" % ((ck.width(), ck.height()), (2 * cw, 2 * ch)))
    check("S1 entry w/h 已同步为推导值",
          (entry["w"], entry["h"]) == (2 * cw, 2 * ch),
          "w=%s h=%s" % (entry["w"], entry["h"]))

    # ---------- S2：widget_cells 精确展开 + displace ----------
    st2 = make_state([("a", 0, 0), ("b", 1, 0), ("c", 0, 1), ("d", 1, 1),
                      ("e", 2, 0)],
                     widgets=[clock_entry(col=0, row=0)])
    w2 = DesktopWindow(st2)
    w2.resize(W, H)
    w2._update_grid_metrics()
    settle(app, 100)
    wc = grid_flow.widget_cells(st2)
    check("S2 widget_cells(clock 2×2 @ (0,0)) == 4 格精确展开",
          wc == {(0, 0), (1, 0), (0, 1), (1, 1)}, "%s" % sorted(wc))
    moved = w2._displace_from_widgets()
    b = by_id(st2)
    check("S2 displace 把占位格上的 4 个图标全部挤出", moved)
    check("S2 挤出后无图标落在组件占位格",
          not any((b[i][0], b[i][1]) in wc for i in "abcd"),
          "%s" % b)
    check("S2 run 外图标 e 不动", b["e"] == (2, 0))
    check("S2 无重叠（4 图标 + 4 组件格不冲突）",
          len({b[i] for i in "abcd"} | wc) == 8)
    w2.on_widget_grid_changed()
    settle(app, 200)
    check("S2 on_widget_grid_changed 全路径（rebuild）不崩",
          all(icon.pos() is not None for icon in w2.icons.values()))

    # ---------- S3：排版零溢出 + 字号比例 ----------
    h = ck.height()
    t_expect = max(24, int(h * 0.21))
    check("S3 时间字号按高度比例（h*0.21）",
          ck._fs[0] == t_expect, "fs=%s h=%s" % (ck._fs, h))
    th = ck.time_label.sizeHint().height()
    dh = ck.date_label.sizeHint().height()
    margins = ck.layout().contentsMargins()
    used = margins.top() + th + 6 + dh + margins.bottom()
    check("S3 2×2 内容零溢出（时间行+间隔+日期行+margins <= 高）",
          used <= h, "used=%s h=%s (th=%s dh=%s)" % (used, h, th, dh))
    check("S3 时间+秒同行（RichText 单 label 内含两段字号）",
          "font-size:%dpx" % ck._fs[0] in ck.time_label.text()
          and "font-size:%dpx" % ck._fs[1] in ck.time_label.text())
    check("S3 日期在下（layout 中位于 time_label 之后）",
          ck.layout().indexOf(ck.date_label)
          > ck.layout().indexOf(ck.time_label))

    # ---------- S4：_set_span 切换 ----------
    got = []
    st.widgets.append(entry)      # 让 widget_cells 能读到（与实例共享同一 dict）
    st.save()
    ck.gridChanged.connect(lambda: got.append(1))
    ck.move(ox + 17 * cw, oy)     # 贴右边缘：位置反算 col = 17
    ck._set_span(4, 2)
    settle(app, 100)
    check("S4 切 4×2 后尺寸 = 4×2 cell",
          (ck.width(), ck.height()) == (4 * cw, 2 * ch),
          "size=%s" % ((ck.width(), ck.height()),))
    check("S4 entry colspan/rowspan 写回",
          (entry["colspan"], entry["rowspan"]) == (4, 2))
    check("S4 col 夹紧到网格内（17 -> 19-4=15）",
          entry["col"] == 15, "col=%s" % entry["col"])
    check("S4 窗口随夹紧移回格点（x = ox + 15*cw）",
          ck.x() == ox + 15 * cw, "x=%s expect=%s" % (ck.x(), ox + 15 * cw))
    check("S4 gridChanged 已发射", len(got) >= 1)
    wc2 = grid_flow.widget_cells(st)
    check("S4 widget_cells 扩展到 8 格",
          wc2 == {(15 + dc, dr) for dc in range(4) for dr in range(2)},
          "%s" % sorted(wc2))

    # ---------- S5：右键「组件尺寸」菜单 ----------
    _keep = []   # 持有 QMenu Python 引用：出作用域即被 GC（C++ 对象销毁）
    menu = QMenu(ck)
    _keep.append(menu)
    ck._add_span_menu(menu)
    check("S5 单尺寸（catalog 只有 2×2）不显示尺寸子菜单",
          len(menu.actions()) == 0)
    widget_catalog.WIDGET_CATALOG["clock"] = [(2, 2), (2, 4), (4, 2)]
    try:
        menu2 = QMenu(ck)
        _keep.append(menu2)
        sub = ck._add_span_menu(menu2)
        check("S5 多尺寸时出现「组件尺寸」子菜单",
              sub is not None and sub.title() == "组件尺寸")
        if sub is not None:
            acts = sub.actions()
            check("S5 子菜单 3 个尺寸项", len(acts) == 3)
            check("S5 当前尺寸（4×2）勾选、其余未勾选",
                  [a.isChecked() for a in acts] == [False, False, True],
                  "%s" % [a.text() for a in acts])
    finally:
        widget_catalog.WIDGET_CATALOG["clock"] = [(2, 2)]

    # ---------- S6：字号随高度缩放（2×2 -> 2×4） ----------
    ck._set_span(2, 4)
    settle(app, 100)
    t2 = ck._fs[0]
    check("S6 2×4 高度下时间字号按比例放大",
          t2 == max(24, int(ck.height() * 0.21)) and t2 > t_expect,
          "t2=%s t_expect=%s h=%s" % (t2, t_expect, ck.height()))
    used2 = (ck.layout().contentsMargins().top()
             + ck.time_label.sizeHint().height() + 6
             + ck.date_label.sizeHint().height()
             + ck.layout().contentsMargins().bottom())
    check("S6 2×4 同样零溢出", used2 <= ck.height(),
          "used=%s h=%s" % (used2, ck.height()))

    # ---------- S7：悬浮态 legacy 尺寸 ----------
    fentry = clock_entry(anchored=False, x=100, y=100, w=260, h=140)
    fk = ClockWidget(st, fentry)
    settle(app, 100)
    check("S7 悬浮态尺寸 = entry 像素（不按 span 推导）",
          (fk.width(), fk.height()) == (260, 140),
          "size=%s" % ((fk.width(), fk.height()),))
    check("S7 悬浮态 entry w/h 不被覆盖",
          (fentry["w"], fentry["h"]) == (260, 140))

    # ---------- 收尾：关组件，防退出期动画崩溃 ----------
    ck.close()
    fk.close()
    settle(app, 200)


def main():
    app = QApplication([])
    wd = QTimer()
    wd.setSingleShot(True)
    wd.timeout.connect(lambda: (print("!! 看门狗超时", flush=True), os._exit(3)))
    wd.start(60000)
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
        print("ALL probe18 PASSED", flush=True)
        code = 0
    print("==== 探针退出 ====", flush=True)
    app.processEvents()
    QTimer.singleShot(80, app.quit)
    app.exec()
    return code


if __name__ == "__main__":
    sys.exit(main())
