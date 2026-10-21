# -*- coding: utf-8 -*-
"""系统监控组件（v8 C4，指导文档_v8.md §4.1）。

契约：
  M1  sample() 返回 Snapshot；首次 CPU 无基准 -> None，第二次采到 0..100
  M2  内存占用 0..100，且 total > 0
  M3  磁盘占用 0..100（盘符可指定，不存在的盘 -> None 而不是抛）
  M4  layout 2×2：三个环都在 rect 内、互不重叠、半径够看
  M5  layout 宽版（4×2）：mode == "wide"，环集中在左半区
  M6  draw 不抛且画布非空
  M7  全 None 的快照也能画（显示 "--"），不抛
  M8  进度色随负载分档：低 = ACCENT，高 = DANGER
  M9  进度值被 clamp 到 0..100（>100 / <0 都不越界、不画反）
  M10 极小矩形（120×80）不抛，环半径 >= 2
  M11 MonitorWidget 是 GlassWidget 子类，采样间隔 1000ms
  M12 注册表已登记：spans 第一项 (2,2)、category 系统、默认锚定

运行：python tests/test_widget_monitor.py   （offscreen）
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.storage import Storage

STATE = Path(tempfile.gettempdir()) / "test_widget_monitor_state.json"

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


def alpha_nonempty(img):
    return sum(1 for y in range(0, img.height(), 2) for x in range(0, img.width(), 2)
               if img.pixelColor(x, y).alpha() > 8)


def main(app):
    from src import widget_monitor as wm

    # ---------- M1 / M2 / M3：采样 ----------
    s0 = wm.sample()
    check("M1 首次采样可用（CPU 可能无基准）", s0 is not None)
    time.sleep(0.12)
    s1 = wm.sample()
    check("M1b 第二次采样 CPU 有值且在 0..100",
          s1.cpu is not None and 0.0 <= s1.cpu <= 100.0, "cpu=%r" % (s1.cpu,))
    check("M1c 首次 CPU 为 None（无基准不撒谎成 0）", s0.cpu is None, "%r" % (s0.cpu,))
    check("M2 内存占用 0..100 且 total > 0",
          s1.mem is not None and 0.0 <= s1.mem <= 100.0 and (s1.mem_total_gb or 0) > 0,
          "mem=%r total=%r" % (s1.mem, s1.mem_total_gb))
    check("M3 磁盘占用 0..100",
          s1.disk is not None and 0.0 <= s1.disk <= 100.0,
          "disk=%r" % (s1.disk,))
    bad = wm.sample_disk("Q:")
    check("M3b 不存在的盘符返回 None 不抛", bad is None, repr(bad))

    # ---------- M4 / M5：布局 ----------
    L = wm.layout(QRectF(0, 0, 240, 284))
    check("M4 2×2 布局三个环", len(L["rings"]) == 3 and L["mode"] == "row",
          str(L["mode"]))
    inside = all(r["rect"].left() >= -0.5 and r["rect"].top() >= -0.5
                 and r["rect"].right() <= 240.5 and r["rect"].bottom() <= 284.5
                 for r in L["rings"])
    check("M4b 环都在 rect 内", inside,
          str([tuple(round(v, 1) for v in (r["rect"].left(), r["rect"].top())) for r in L["rings"]]))
    check("M4c 环半径够看（>= 10）", all(r["rect"].width() / 2 >= 10 for r in L["rings"]),
          str([round(r["rect"].width() / 2, 1) for r in L["rings"]]))
    overlap = False
    for i in range(len(L["rings"])):
        for j in range(i + 1, len(L["rings"])):
            if L["rings"][i]["rect"].intersects(L["rings"][j]["rect"]):
                overlap = True
    check("M4d 三环互不重叠", not overlap)

    W = wm.layout(QRectF(0, 0, 480, 284))
    check("M5 宽版 layout mode = wide", W["mode"] == "wide", W["mode"])
    check("M5b 宽版环集中在左半区",
          all(r["rect"].center().x() < 480 * 0.62 for r in W["rings"]),
          str([round(r["rect"].center().x(), 1) for r in W["rings"]]))
    check("M5c 宽版有数值文字列", bool(W.get("value_x") is not None))

    # ---------- M6 / M7 / M9 / M10：绘制 ----------
    img = canvas(240, 284)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    wm.draw(p, QRectF(0, 0, 240, 284), s1)
    p.end()
    check("M6 draw 画布非空", alpha_nonempty(img) > 400, str(alpha_nonempty(img)))

    empty = wm.Snapshot()
    img2 = canvas(240, 284)
    ok = True
    try:
        p2 = QPainter(img2)
        wm.draw(p2, QRectF(0, 0, 240, 284), empty)
        p2.end()
    except Exception as exc:      # noqa: BLE001
        ok = False
        print("   draw(empty) 抛异常: %r" % (exc,))
    check("M7 全 None 快照也能画（-- 占位）", ok and alpha_nonempty(img2) > 200)

    # clamp：极端值不抛、不画出越界弧
    img3 = canvas(240, 284)
    ok3 = True
    try:
        p3 = QPainter(img3)
        wm.draw(p3, QRectF(0, 0, 240, 284), s1, smooth={"cpu": 180, "mem": -40, "disk": 100})
        p3.end()
    except Exception:             # noqa: BLE001
        ok3 = False
    check("M9 越界进度值被 clamp（不抛）", ok3)

    tiny = canvas(120, 80)
    ok4 = True
    try:
        p4 = QPainter(tiny)
        wm.draw(p4, QRectF(0, 0, 120, 80), s1)
        p4.end()
    except Exception:             # noqa: BLE001
        ok4 = False
    Lt = wm.layout(QRectF(0, 0, 120, 80))
    check("M10 极小矩形不抛且环半径 >= 2",
          ok4 and all(r["rect"].width() / 2 >= 2 for r in Lt["rings"]),
          str([round(r["rect"].width() / 2, 1) for r in Lt["rings"]]))

    # ---------- M8：分档配色 ----------
    low = wm.progress_color(30)
    high = wm.progress_color(96)
    check("M8 低负载用 ACCENT（偏蓝）", low.blue() > low.red(), low.name())
    check("M8b 高负载用 DANGER（偏红）", high.red() > high.blue(), high.name())

    # ---------- M11 / M12：组件与注册 ----------
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = False
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["layout"] = []
    st._data["widgets"] = [{"id": "mon1", "type": "monitor", "w": 240, "h": 284,
                            "hidden": False, "anchored": True,
                            "col": 6, "row": 10, "colspan": 2, "rowspan": 2}]
    st.save()
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)

    from src import widget_glass
    w = wm.MonitorWidget(st, dict(st.widgets[0]))
    check("M11 MonitorWidget 是 GlassWidget 子类",
          isinstance(w, widget_glass.GlassWidget))
    check("M11b 采样间隔 1000ms",
          w._timer.interval() == 1000, str(w._timer.interval()))
    w._timer.stop()
    w.show()
    app.processEvents()
    shot = w.grab().toImage()
    check("M11c 组件真的画了内容（不是只有玻璃底）",
          alpha_nonempty(shot) > 500, str(alpha_nonempty(shot)))
    w.close()

    from src import widget_registry as reg
    spec = reg.get("monitor")
    check("M12 注册表已登记 monitor", spec is not None)
    if spec is not None:
        check("M12b spans 第一项 (2,2) / 分类系统 / 默认锚定",
              spec.spans[0] == (2, 2) and spec.category == "系统"
              and spec.default_anchored is True and spec.multi_instance is False,
              "%s %s %s" % (spec.spans, spec.category, spec.default_anchored))

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
