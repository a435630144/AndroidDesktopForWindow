# -*- coding: utf-8 -*-
"""生成 v8 组件目检图：dist/shots/v8_widgets.png

上半：组件库窗口（分类 + 7 张卡片 + 底部计数）
下半：四个新组件在 2×2 尺寸下的真实渲染（调用各自的 draw()，示例数据）

注意三个已知坑：
  0. **不要设 QT_QPA_PLATFORM=offscreen**——离屏平台的字体库不完整，
     中文与数字会全渲染成方块（v7e 坑）；用真实 QPA + WA_DontShowOnScreen；
  1. `WA_DontShowOnScreen` + 真实 QPA 下，父级 grab() **不画子部件**（v7e 坑），
     所以组件库里每个子部件要逐个 render 上去；
  2. 组件的玻璃底与内容是同一套 paint_glass + draw()，这里直接画到 QImage，
     不实例化组件（否则会启定时器 / 联网）。

运行：python tools/shot_v8_widgets.py [输出路径]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datetime

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from src import grid_flow
from src.storage import Storage
from src.widget_layer import WidgetLayer
from src import widget_glass as wg
from src.widgets import calendar as cal
from src.widgets import todo as todo
from src.widgets import weather as wx
from src.widgets import monitor as mon

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "dist", "shots", "v8_widgets.png")

STATE = os.path.join(os.environ.get("TEMP", "."), "shot_v8_center_state.json")
DPR = 1.5
CELL_W, CELL_H = 240, 284


def make_layer():
    if os.path.exists(STATE):
        os.unlink(STATE)
    st = Storage(path=STATE)
    st._data["settings"]["hide_native_icons"] = False
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["layout"] = []
    st._data["widgets"] = [
        {"id": "clock", "type": "clock", "w": CELL_W, "h": CELL_H, "hidden": False,
         "anchored": True, "col": 8, "row": 10, "colspan": 2, "rowspan": 2},
        {"id": "td1", "type": "todo", "w": CELL_W, "h": CELL_H, "hidden": True,
         "anchored": False, "x": 40, "y": 40, "items": []},
    ]
    st.save()
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)
    return WidgetLayer(st)


def grab_with_children(w: QWidget) -> QImage:
    """抓整个窗口（含子部件）。

    2026-10-21 实测修正：`WA_DontShowOnScreen` + 真实 QPA 下 `grab()` **是**含子部件的，
    额外再逐个 `render` 一遍会画成两层重叠影子（DPR 换算不一致 → 偏位、缩放也不同）。
    所以这里只用 grab()，不再手工合成。若某天 grab 又不含子部件，判据是
    「窗口右侧卡片的按钮文字是否出现」——出现即含子部件。
    """
    return w.grab().toImage()


def widget_canvas(drawer) -> QImage:
    img = QImage(int(CELL_W * DPR), int(CELL_H * DPR),
                 QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(DPR)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(0, 0, CELL_W, CELL_H)
    wg.paint_glass(p, rect, wg.glass_radius(True))
    drawer(p, rect)
    p.end()
    return img


def main(app):
    layer = make_layer()
    from src import widget_center

    center = widget_center.WidgetCenter(layer)
    center.setAttribute(Qt.WA_DontShowOnScreen, True)
    center.show()
    app.processEvents()
    shot = grab_with_children(center)
    cw, chh = center.width(), center.height()

    gap = 22
    pad = 28
    strip_w = 4 * CELL_W + 3 * gap
    width = max(cw + pad * 2, strip_w + pad * 2)
    height = 84 + chh + 54 + CELL_H + 40
    canvas = QImage(int(width * DPR), int(height * DPR),
                    QImage.Format_ARGB32_Premultiplied)
    canvas.setDevicePixelRatio(DPR)
    canvas.fill(QColor("#0c0e13"))
    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing)

    p.setPen(QColor("#e8eefc"))
    p.setFont(QFont("Microsoft YaHei UI", 15, QFont.Bold))
    p.drawText(QRectF(pad, 22, width - pad * 2, 30), Qt.AlignLeft | Qt.AlignVCenter,
               "v8 组件中心 + 四个新组件")
    p.setPen(QColor("#8fa0bd"))
    p.setFont(QFont("Microsoft YaHei UI", 10))
    p.drawText(QRectF(pad, 52, width - pad * 2, 22), Qt.AlignLeft | Qt.AlignVCenter,
               "组件库：分类 / 搜索 / 四态卡片 / 实时预览（预览与桌面同一个 draw()）")

    p.drawImage(pad, 84, shot)

    p.setPen(QColor("#8fa0bd"))
    p.setFont(QFont("Microsoft YaHei UI", 10))
    p.drawText(QRectF(pad, 84 + chh + 12, width - pad * 2, 24),
               Qt.AlignLeft | Qt.AlignVCenter,
               "桌面上的样子（2×2 格）：系统监控 / 待办清单 / 日历 / 天气")

    demo_weather = wx.wa.WeatherModel(
        city="北京", temp=23.0, feels=22.0, humidity=55, wind=8.0, code=1,
        daily=(wx.wa.Daily(code=61, tmax=22.0, tmin=14.0),
               wx.wa.Daily(code=3, tmax=24.0, tmin=13.0),
               wx.wa.Daily(code=0, tmax=27.0, tmin=16.0)),
        fetched_at=0.0)
    now = datetime.date.today()

    shots = [
        widget_canvas(lambda pp, r: mon.draw(
            pp, r, mon.Snapshot(cpu=42.0, mem=63.0, disk=55.0))),
        widget_canvas(lambda pp, r: todo.draw(pp, r, todo.DEMO_ITEMS)),
        widget_canvas(lambda pp, r: cal.draw(pp, r, cal.build_model(now.year, now.month, 0))),
        widget_canvas(lambda pp, r: wx.draw(pp, r, demo_weather, "live")),
    ]
    x = pad
    y = 84 + chh + 40
    for img in shots:
        p.drawImage(int(x), int(y), img)
        x += CELL_W + gap

    p.end()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    canvas.save(OUT)
    print("saved", OUT, canvas.width(), "x", canvas.height())

    for w in list(layer.widgets.values()):
        try:
            w.close()
        except Exception:      # noqa: BLE001
            pass
    center.close()
    if os.path.exists(STATE):
        os.unlink(STATE)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    main(app)
