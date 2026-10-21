# -*- coding: utf-8 -*-
"""天气组件（v8 C7，指导文档_v8.md §4.4）。

    layout(rect, model)          纯几何
    draw(painter, rect, model, state)  纯绘制（三态：live / cached / empty）
    draw_weather_icon(...)       矢量天气图标（不引入图标资源文件）
    WeatherWidget               后台线程取数 + 30min 定时 + 缓存先亮

主线程零阻塞：`refresh()` 只起线程就返回，结果经 `Signal(object, str)`
排队回主线程（Qt 跨线程禁止直接操作控件）。
"""
from __future__ import annotations

import datetime
import threading
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPen, QPolygonF

from . import theme
from .widget_style import DEFAULT_STYLE, Style
from . import weather_api as wa
from .widget_glass import PAD, GlassWidget

WIDE_RATIO = 1.6
DAY_LABELS = ("明天", "后天", "第 3 天")


# ---------------------------------------------------------------- 纯几何

def layout(rect, model: Optional[wa.WeatherModel] = None) -> Dict:
    rect = QRectF(rect)
    w = max(1.0, rect.width())
    h = max(1.0, rect.height())
    pad = min(PAD, w * 0.10, h * 0.08)
    inner = rect.adjusted(pad, pad, -pad, -pad)
    wide = w >= h * WIDE_RATIO

    if wide:
        left_w = inner.width() * 0.46
        current = QRectF(inner.left(), inner.top(), left_w, inner.height())
        col_w = max(1.0, (inner.width() - left_w) / 3.0)
        daily_cols = [QRectF(inner.left() + left_w + i * col_w, inner.top(),
                             col_w, inner.height()) for i in range(3)]
        icon_d = min(current.height() * 0.30, current.width() * 0.30)
    else:
        current = QRectF(inner)
        daily_cols = []
        icon_d = min(inner.height() * 0.30, inner.width() * 0.30)

    icon = QRectF(current.right() - icon_d, current.top(), icon_d, icon_d)
    temp_fs = int(max(14, min(current.width() * 0.30, current.height() * 0.32)))
    return {"inner": inner, "current": current, "icon": icon, "icon_d": icon_d,
            "daily_cols": daily_cols, "temp_fs": temp_fs, "wide": wide}


# ---------------------------------------------------------------- 矢量图标

def draw_weather_icon(p: QPainter, kind: str, rect, color: QColor = None) -> None:
    """画一个天气图标（太阳/云/雨/雪/雷/雾），全部矢量、随 rect 缩放。"""
    r = QRectF(rect)
    if r.width() <= 4 or r.height() <= 4:
        return
    c = QColor(color or theme.ACCENT)
    s = min(r.width(), r.height())
    cx, cy = r.center().x(), r.center().y()
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)

    def cloud(dx: float = 0.0, dy: float = 0.0, scale: float = 1.0, col: QColor = None):
        cc = QColor(col or c)
        p.setBrush(cc)
        rr = s * 0.30 * scale
        p.drawEllipse(QPointF(cx - s * 0.20 * scale + dx, cy + s * 0.05 * scale + dy),
                      rr, rr * 0.86)
        p.drawEllipse(QPointF(cx + s * 0.19 * scale + dx, cy + s * 0.05 * scale + dy),
                      rr * 0.92, rr * 0.80)
        p.drawEllipse(QPointF(cx + dx, cy - s * 0.09 * scale + dy),
                      rr * 1.16, rr)

    if kind == "sun":
        p.setBrush(c)
        p.drawEllipse(QPointF(cx, cy), s * 0.22, s * 0.22)
        p.setPen(QPen(c, max(1.6, s * 0.055), Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        for i in range(8):
            import math
            a = math.pi * 2 * i / 8
            r0, r1 = s * 0.31, s * 0.44
            p.drawLine(QPointF(cx + r0 * math.cos(a), cy + r0 * math.sin(a)),
                       QPointF(cx + r1 * math.cos(a), cy + r1 * math.sin(a)))
    elif kind == "cloud":
        cloud()
    elif kind == "rain":
        cloud(dy=-s * 0.06, scale=0.92, col=QColor(c.red(), c.green(), c.blue(), 235))
        p.setPen(QPen(c, max(1.6, s * 0.06), Qt.SolidLine, Qt.RoundCap))
        for dx in (-s * 0.16, 0.0, s * 0.16):
            p.drawLine(QPointF(cx + dx, cy + s * 0.20),
                       QPointF(cx + dx - s * 0.03, cy + s * 0.34))
    elif kind == "snow":
        cloud(dy=-s * 0.08, scale=0.90)
        p.setBrush(QColor(255, 255, 255, 235))
        p.setPen(Qt.NoPen)
        for dx in (-s * 0.16, 0.0, s * 0.16):
            p.drawEllipse(QPointF(cx + dx, cy + s * 0.28), s * 0.035, s * 0.035)
    elif kind == "thunder":
        cloud(dy=-s * 0.08, scale=0.90)
        bolt = QPolygonF([QPointF(cx + s * 0.02, cy + s * 0.12),
                          QPointF(cx - s * 0.10, cy + s * 0.30),
                          QPointF(cx - s * 0.01, cy + s * 0.30),
                          QPointF(cx - s * 0.06, cy + s * 0.46),
                          QPointF(cx + s * 0.12, cy + s * 0.22),
                          QPointF(cx + s * 0.02, cy + s * 0.22)])
        p.setBrush(QColor(250, 210, 90))
        p.drawPolygon(bolt)
    elif kind == "fog":
        cloud(dy=-s * 0.10, scale=0.88)
        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 200),
                      max(1.4, s * 0.05), Qt.SolidLine, Qt.RoundCap))
        for i, dy in enumerate((0.16, 0.28, 0.40)):
            half = s * (0.30 - i * 0.03)
            p.drawLine(QPointF(cx - half, cy + s * dy), QPointF(cx + half, cy + s * dy))
    else:
        cloud()
    p.restore()


# ---------------------------------------------------------------- 纯绘制

def draw(p: QPainter, rect, model: Optional[wa.WeatherModel], state: str = "live", style: Optional[Style] = None) -> None:
    st = style or DEFAULT_STYLE
    rect = QRectF(rect)
    if rect.width() <= 6 or rect.height() <= 6:
        return
    L = layout(rect, model)
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)

    if model is None or state == "empty":
        half = L["icon_d"] * 0.9
        draw_weather_icon(p, "cloud", QRectF(rect.center().x() - half / 2,
                                             rect.center().y() - half, half, half),
                          QColor(st.faint))
        p.setPen(QColor(st.dim))
        fs = max(9, int(min(rect.width() * 0.075, 12)))
        p.setFont(theme.ui_font(fs))
        p.drawText(QRectF(rect.left(), rect.center().y() + 4,
                          rect.width(), rect.height() * 0.4),
                   Qt.AlignHCenter | Qt.AlignTop, "右键 ▸ 组件设置，填写城市")
        p.restore()
        return

    cur = L["current"]
    # 城市
    p.setPen(QColor(st.dim))
    p.setFont(theme.ui_font(max(9, int(min(cur.width() * 0.09, 12)))))
    fm = QFontMetricsF(p.font())
    city = model.city or ""
    max_w = max(10.0, L["icon"].left() - cur.left())
    while city and fm.horizontalAdvance(city) > max_w:
        city = city[:-1]
    p.drawText(QRectF(cur.left(), cur.top(), max_w, L["icon_d"] * 0.6),
               Qt.AlignLeft | Qt.AlignVCenter, city)

    # 图标
    draw_weather_icon(p, model.icon, L["icon"])

    # 大号温度
    p.setFont(theme.ui_font(L["temp_fs"], bold=True))
    p.setPen(QColor(st.text))
    temp_rect = QRectF(cur.left(), cur.top() + L["icon_d"] * 0.72,
                       cur.width(), cur.height() * 0.34)
    p.drawText(temp_rect, Qt.AlignLeft | Qt.AlignVCenter, wa.fmt_temp(model.temp))

    # 描述 + 体感
    p.setFont(theme.ui_font(max(9, int(min(cur.width() * 0.075, 12)))))
    p.setPen(QColor(st.dim))
    desc = "%s · 体感 %s" % (model.text, wa.fmt_temp(model.feels))
    p.drawText(QRectF(cur.left(), temp_rect.bottom(), cur.width(), 18),
               Qt.AlignLeft | Qt.AlignVCenter, desc)

    # 今日高低温
    if model.daily:
        d0 = model.daily[0]
        p.setPen(QColor(st.faint))
        p.drawText(QRectF(cur.left(), cur.bottom() - 20, cur.width(), 18),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   "明日 %s / %s" % (wa.fmt_temp(d0.tmax), wa.fmt_temp(d0.tmin)))

    # 缓存角标
    if state == "cached":
        p.setPen(QColor(st.faint))
        p.setFont(theme.ui_font(9))
        p.drawText(QRectF(cur.right() - 120, cur.bottom() - 18, 120, 16),
                   Qt.AlignRight | Qt.AlignVCenter,
                   "缓存 · " + wa.age_text(model.fetched_at))

    # 宽版右侧：未来三天
    for i, col in enumerate(L["daily_cols"]):
        if i >= len(model.daily):
            break
        d = model.daily[i]
        mid = col.center().x()
        fs = max(8, int(min(col.width() * 0.18, 11)))
        p.setFont(theme.ui_font(fs))
        p.setPen(QColor(st.faint))
        p.drawText(QRectF(col.left(), col.top(), col.width(), col.height() * 0.2),
                   Qt.AlignHCenter | Qt.AlignVCenter, DAY_LABELS[i])
        iw = min(col.width() * 0.62, col.height() * 0.36)
        draw_weather_icon(p, wa.describe(d.code)[1],
                          QRectF(mid - iw / 2, col.top() + col.height() * 0.24, iw, iw))
        p.setFont(theme.ui_font(fs, bold=True))
        p.setPen(QColor(st.text))
        p.drawText(QRectF(col.left(), col.top() + col.height() * 0.62,
                          col.width(), col.height() * 0.2),
                   Qt.AlignHCenter | Qt.AlignVCenter, wa.fmt_temp(d.tmax))
        p.setPen(QColor(st.faint))
        p.setFont(theme.ui_font(fs))
        p.drawText(QRectF(col.left(), col.top() + col.height() * 0.80,
                          col.width(), col.height() * 0.18),
                   Qt.AlignHCenter | Qt.AlignVCenter, wa.fmt_temp(d.tmin))

    p.restore()


def draw_preview(p: QPainter, rect, dpr: float = 1.0) -> None:
    """组件库预览：示例数据（不联网、不读缓存）。"""
    today = datetime.date.today()
    demo = wa.WeatherModel(
        city="北京", temp=23.0, feels=22.0, humidity=55, wind=8.0, code=1,
        daily=(wa.Daily(code=61, tmax=22.0, tmin=14.0),
               wa.Daily(code=3, tmax=24.0, tmin=13.0),
               wa.Daily(code=0, tmax=27.0, tmin=16.0)),
        fetched_at=0.0)
    draw(p, rect, demo, "live")


# ---------------------------------------------------------------- 组件

class WeatherWidget(GlassWidget):
    TYPE = "weather"
    AUTO_REFRESH_MS = 1500              # 首刷延迟：先把界面画出来（测试可置 0 关闭）
    REFRESH_PERIOD_MS = 30 * 60 * 1000  # 之后每 30 分钟

    _result = Signal(object, str)       # (model, state) —— 跨线程回主线程

    def __init__(self, storage, entry):
        super().__init__(storage, entry)
        self._model: Optional[wa.WeatherModel] = None
        self._state = "empty"
        self._busy = False
        self._result.connect(self._on_result)
        # 先用缓存点亮：不等网络，打开桌面立刻有东西看
        cached = wa.cache_to_model(wa.load_cache())
        if cached is not None:
            self._model, self._state = cached, "cached"
        self._timer = QTimer(self)
        self._timer.setInterval(self.REFRESH_PERIOD_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        if self.AUTO_REFRESH_MS:
            QTimer.singleShot(self.AUTO_REFRESH_MS, self.refresh)

    # ---------- 取数 ----------
    def _settings(self) -> Dict:
        return self.entry.get("settings") or {}

    def refresh(self):
        """发起一次刷新（立即返回，UI 不等网络）。"""
        if self._busy:
            return
        city = str(self._settings().get("city") or "").strip()
        online = bool(self._settings().get("online", True))
        if not city and self._model is None:
            self._state = "empty"
            self.update()
            return
        self._busy = True
        threading.Thread(target=self._work, args=(city, online), daemon=True).start()

    def _work(self, city: str, online: bool):
        try:
            state, model = wa.fetch_sync(city, online)
        except Exception:      # noqa: BLE001  —— 后台线程绝不能把异常抛给 Qt
            state, model = "cached", None
        self._result.emit(model, state)

    def _on_result(self, model, state: str):
        self._busy = False
        if model is not None:
            self._model = model
            self._state = state
        else:
            self._state = "cached" if self._model is not None else "empty"
        self.update()

    # ---------- 绘制 ----------
    def paint_content(self, p: QPainter):
        draw(p, QRectF(self.rect()), self._model, self._state, style=self.style)

    def on_settings_changed(self):
        # 改城市 / 开关联网后立刻重取（关掉联网时走缓存分支）
        super().on_settings_changed()   # 清样式缓存（颜色可能也改了）
        self.refresh()

    def closeEvent(self, e):
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.stop()
        super().closeEvent(e)
