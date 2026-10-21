# -*- coding: utf-8 -*-
"""日历组件（v8 C6，指导文档_v8.md §4.3）。

契约：
  K1  month_matrix：每行 7 格、当月日期恰好各出现一次、首格是 1 号
  K2  shift_month 跨年正确（12 月 +1 -> 次年 1 月；1 月 -1 -> 上年 12 月）
  K3  week_labels：周一起始以「一」开头，周日起始以「日」开头
  K4  layout：格子数 = 行数 × 7，全部在 rect 内，左箭头在右箭头左侧
  K5  layout：2×2 字号 >= 8（再小就没法看）
  K6  draw 画布非空
  K7  draw 今天：今天那格中心像素偏蓝（ACCENT 实心圆）
  K8  draw 非本月格：不画数字（中心像素无文字亮度）
  K9  点右箭头 -> 下个月（真实鼠标事件）
  K10 点标题 -> 回到今天所在月
  K11 注册表：spans (2,2)/(3,3)、分类时间、单实例、默认锚定
  K12 极小矩形不抛

运行：python tests/test_widget_calendar.py   （offscreen）
"""
import datetime
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.storage import Storage

STATE = Path(tempfile.gettempdir()) / "test_widget_calendar_state.json"

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
    from src import widgets_calendar as wc

    # ---------- K1：月矩阵 ----------
    for y, m in ((2026, 10), (2026, 2), (2024, 2), (2026, 1), (2026, 12)):
        weeks = wc.month_matrix(y, m, 0)
        flat = [d for wk in weeks for d in wk]
        days = [d for d in flat if d > 0]
        import calendar as _cal
        n = _cal.monthrange(y, m)[1]
        ok = (all(len(wk) == 7 for wk in weeks)
              and days == list(range(1, n + 1)))
        check("K1 %04d-%02d 月矩阵正确（%d 行）" % (y, m, len(weeks)), ok,
              "days=%d rows=%d" % (len(days), len(weeks)))
        check("K1b %04d-%02d 首格是 1 号" % (y, m), days and days[0] == 1)

    # ---------- K2：跨年 ----------
    check("K2 12 月 +1 -> 次年 1 月", wc.shift_month(2026, 12, 1) == (2027, 1),
          str(wc.shift_month(2026, 12, 1)))
    check("K2b 1 月 -1 -> 上年 12 月", wc.shift_month(2026, 1, -1) == (2025, 12),
          str(wc.shift_month(2026, 1, -1)))

    # ---------- K3：周起始 ----------
    mon = wc.week_labels(0)
    sun = wc.week_labels(6)
    check("K3 周一起始", mon[0] == "一" and mon[-1] == "日", str(mon))
    check("K3b 周日起始", sun[0] == "日" and sun[-1] == "六", str(sun))

    # ---------- K4 / K5：布局 ----------
    model = wc.build_model(2026, 10, 0, today=datetime.date(2026, 10, 21))
    L = wc.layout(QRectF(0, 0, 240, 284), model)
    n_cells = sum(len(row) for row in L["cells"])
    check("K4 格子数 = 行数 × 7", n_cells == len(model.weeks) * 7,
          "%d vs %d" % (n_cells, len(model.weeks) * 7))
    inside = all(QRectF(0, 0, 240, 284).contains(c) for row in L["cells"] for c in row)
    check("K4b 所有格子都在 rect 内", inside)
    check("K4c 左箭头在右箭头左侧",
          L["nav_left"].right() <= L["nav_right"].left(),
          "%.1f <= %.1f" % (L["nav_left"].right(), L["nav_right"].left()))
    check("K5 2×2 字号 >= 8", L["fs"] >= 8, "fs=%d" % L["fs"])

    L3 = wc.layout(QRectF(0, 0, 360, 420), wc.build_model(2026, 10, 0))
    check("K5b 3×3 字号更大", L3["fs"] > L["fs"], "%d vs %d" % (L3["fs"], L["fs"]))

    # ---------- K6 / K7 / K8：绘制 ----------
    img = canvas(240, 284)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    wc.draw(p, QRectF(0, 0, 240, 284), model)
    p.end()
    # draw() 只画文字与今天圆，玻璃底由组件画；2000 多个像素足够证明"画了东西"
    check("K6 draw 画布非空", alpha_nonempty(img) > 200, str(alpha_nonempty(img)))

    # 今天所在格的中心（物理像素按 DPR 无关：这里直接画在 1x 画布上）
    day_cell = None
    for wi, wk in enumerate(model.weeks):
        for di, d in enumerate(wk):
            if d == 21:
                day_cell = L["cells"][wi][di]
    check("K7 找到今天所在格", day_cell is not None)
    if day_cell is not None:
        # 不能取正中心：今天格中心是白色数字覆盖在蓝圆上，取到的是字形
        # 边缘；沿 45° 取 0.72r 才是"圆本身"的颜色
        c = day_cell.center()
        rr = min(day_cell.width(), day_cell.height()) * wc.TODAY_R
        px = img.pixelColor(int(c.x() + rr * 0.72), int(c.y() - rr * 0.72))
        check("K7b 今天高亮偏蓝（ACCENT 圆）", px.blue() > px.red() + 20,
              "%s rgb(%d,%d,%d)" % (px.name(), px.red(), px.green(), px.blue()))

    # 非本月格（第一行若含 0）不画数字
    blank = None
    for wi, wk in enumerate(model.weeks):
        for di, d in enumerate(wk):
            if d == 0:
                blank = L["cells"][wi][di]
                break
        if blank is not None:
            break
    if blank is not None:
        c = blank.center()
        px = img.pixelColor(int(c.x()), int(c.y()))
        check("K8 非本月格中心无文字（近透明）", px.alpha() < 60,
              "a=%d %s" % (px.alpha(), px.name()))
    else:
        check("K8 非本月格中心无文字（近透明）", True, "本月首行无空格，跳过")

    # ---------- K12：极小矩形 ----------
    ok = True
    try:
        tiny = canvas(120, 80)
        p2 = QPainter(tiny)
        wc.draw(p2, QRectF(0, 0, 120, 80), wc.build_model(2026, 10))
        p2.end()
        Ltiny = wc.layout(QRectF(0, 0, 120, 80), wc.build_model(2026, 10))
    except Exception as exc:      # noqa: BLE001
        ok = False
        print("   tiny 抛异常: %r" % (exc,))
    check("K12 极小矩形不抛", ok)

    # ---------- K9 / K10：真实点击 ----------
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = False
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["layout"] = []
    st._data["widgets"] = [{"id": "cal1", "type": "calendar", "w": 240, "h": 284,
                            "hidden": False, "anchored": True,
                            "col": 6, "row": 10, "colspan": 2, "rowspan": 2,
                            "settings": {}}]
    st.save()
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)

    today = datetime.date.today()
    w = wc.CalendarWidget(st, st.widgets[0])
    w.show()
    QTest.qWait(50)
    # 从当月出发，点右箭头 -> 下月
    y0, m0 = w._year, w._month
    Lw = wc.layout(QRectF(0, 0, w.width(), w.height()), w.model())
    QTest.mouseClick(w, Qt.LeftButton, pos=Lw["nav_right"].center().toPoint())
    QTest.qWait(30)
    check("K9 点右箭头进入下个月",
          (w._year, w._month) == wc.shift_month(y0, m0, 1),
          "%s -> %s" % ((y0, m0), (w._year, w._month)))

    # 点标题 -> 回到今天所在月
    Lw2 = wc.layout(QRectF(0, 0, w.width(), w.height()), w.model())
    QTest.mouseClick(w, Qt.LeftButton, pos=Lw2["title"].center().toPoint())
    QTest.qWait(30)
    check("K10 点标题回到今天所在月",
          (w._year, w._month) == (today.year, today.month),
          str((w._year, w._month)))
    w.close()

    # ---------- K11：注册 ----------
    from src import widget_registry as reg
    spec = reg.get("calendar")
    check("K11 注册表已登记 calendar", spec is not None)
    if spec is not None:
        check("K11b spans (2,2)/(3,3) / 分类时间 / 单实例 / 默认锚定",
              spec.spans == ((2, 2), (3, 3)) and spec.category == "时间"
              and spec.multi_instance is False and spec.default_anchored is True,
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
