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

import threading
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFontMetricsF, QLinearGradient, QPainter,
                           QPen, QPolygonF)

from ... import theme
from ...widget_style import DEFAULT_STYLE, Style
from . import weather_api as wa
from . import source as wsource
from ...widget_glass import PAD, GlassWidget

WIDE_RATIO = 1.6
DAY_LABELS = ("明天", "后天", "第 3 天")


# ---------------------------------------------------------------- 纯几何

def _range_fill(daily) -> list:
    """每天的温程条切分 `[(lo_frac, hi_frac)]`，按全局 [最低温, 最高温] 归一。

    跨天可比较：只看一根条在轨道上的绝对位置，就知道哪天更暖。全等温
    （预报退化 / 演示数据）时给满条——不给 0 宽，那看起来像"没数据"。
    """
    if not daily:
        return []
    lo = min(d.tmin for d in daily)
    hi = max(d.tmax for d in daily)
    span = hi - lo
    out = []
    for d in daily:
        if span <= 0.05:
            out.append((0.0, 1.0))
            continue
        out.append((max(0.0, (d.tmin - lo) / span),
                    min(1.0, (d.tmax - lo) / span)))
    return out


def _daily_col_slots(col: QRectF, fill) -> Dict:
    """每日列槽位：标签 -> 图标 -> 最高温 -> 温程条 -> 最低温。

    温程条是 4×2 相对 2×2 的**新样式**（v14 反馈 7）：文字只给两个数，
    条子给"这两天谁更暖"的一眼答案。高度按列高比例派生，缩略图（列高
    ~90px）时各项仍不重叠。
    """
    h = max(1.0, col.height())
    label = QRectF(col.left(), col.top(), col.width(), h * 0.15)
    icon_d = min(col.width() * 0.52, h * 0.30)
    icon = QRectF(col.center().x() - icon_d / 2.0,
                  label.bottom() + h * 0.03, icon_d, icon_d)
    tmax = QRectF(col.left(), icon.bottom() + h * 0.03, col.width(), h * 0.16)
    bar = QRectF(col.left() + col.width() * 0.16, tmax.bottom() + h * 0.04,
                 col.width() * 0.68, max(4.0, h * 0.038))
    tmin = QRectF(col.left(), bar.bottom() + h * 0.03, col.width(), h * 0.15)
    return {"rect": QRectF(col), "label": label, "icon": icon,
            "tmax": tmax, "bar": bar, "tmin": tmin,
            "fill": tuple(fill) if fill else (0.0, 1.0)}


def _wide_left_slots(current: QRectF, icon_d: float) -> Dict:
    """4×2 左块（当前天气）的纵向槽位。

    与 2×2 的差别只有一处：**多一排指标（湿度 / 风力）**——这就是"拓展"
    的字面含义（反馈 7：4×2 不是 2×2 的缩放，是加了新内容）。这两个数
    模型里一直有（humidity / wind），2×2 放不下就不放，4×2 放了。
    顺序：城市行 -> 大温度 -> 描述 -> 指标排 -> 明日高低温（贴底）。
    """
    city = QRectF(current.left(), current.top(), current.width(),
                  icon_d * 0.62)
    temp = QRectF(current.left(), city.bottom(), current.width(),
                  icon_d * 1.05)
    desc = QRectF(current.left(), temp.bottom(), current.width(),
                  icon_d * 0.44)
    chip_h = max(16.0, icon_d * 0.46)
    chip_top = min(desc.bottom() + icon_d * 0.10,
                   current.bottom() - chip_h - icon_d * 0.55)
    chip_w = current.width() / 2.0
    chips = [QRectF(current.left(), chip_top, chip_w * 0.94, chip_h),
             QRectF(current.left() + chip_w, chip_top, chip_w * 0.94, chip_h)]
    tomorrow = QRectF(current.left(),
                      max(chips[0].bottom() + icon_d * 0.08,
                          current.bottom() - icon_d * 0.5),
                      current.width(), icon_d * 0.5)
    return {"city": city, "temp": temp, "desc": desc, "chips": chips,
            "tomorrow": tomorrow}


def layout(rect, model: Optional[wa.WeatherModel] = None) -> Dict:
    """两种尺寸预设（v14 反馈 7：按尺寸换布局，不按尺寸缩放同一布局）。

    - **square**（2×2，近方形）：当前天气一栏——城市 / 图标 / 大温度 /
      描述·体感 / 明日高低温。
    - **wide**（4×2，宽幅）：左栏当前天气（**多出湿度 / 风力两个指标**）
      + 右栏三天预报（标签 / 图标 / 最高温 / 温程条 / 最低温）。

    判定保持 `WIDE_RATIO`（4×2 ≈ 1.69、2×2 ≈ 0.85，中间不会误判）。
    返回字典始终带 `wide` / `daily_cols` 旧键（老调用方不炸），新消费方
    认 `mode` / `detail_chips` / 每日列的 `bar` / `fill`。
    """
    rect = QRectF(rect)
    w = max(1.0, rect.width())
    h = max(1.0, rect.height())
    pad = min(PAD, w * 0.10, h * 0.08)
    inner = rect.adjusted(pad, pad, -pad, -pad)
    wide = w >= h * WIDE_RATIO

    if wide:
        left_w = inner.width() * 0.44
        current = QRectF(inner.left(), inner.top(), left_w, inner.height())
        gap = max(8.0, inner.width() * 0.02)
        cols_w = max(1.0, inner.width() - left_w - gap)
        col_w = cols_w / 3.0
        daily_cols = [QRectF(inner.left() + left_w + gap + i * col_w,
                             inner.top(), col_w, inner.height())
                      for i in range(3)]
        icon_d = min(current.height() * 0.26, current.width() * 0.34)
        icon = QRectF(current.right() - icon_d, current.top(), icon_d, icon_d)
        temp_fs = int(max(14, min(current.width() * 0.42,
                                  current.height() * 0.30)))
        slots = _wide_left_slots(current, icon_d)
        fills = _range_fill(getattr(model, "daily", ()) or ())
        cols = []
        for i in range(len(daily_cols)):
            slot = _daily_col_slots(daily_cols[i],
                                    fills[i] if i < len(fills) else None)
            slot["index"] = i
            cols.append(slot)
        return {"inner": inner, "current": current, "icon": icon,
                "icon_d": icon_d, "daily_cols": daily_cols, "cols": cols,
                "detail_chips": slots["chips"], "left": slots,
                "temp_fs": temp_fs, "wide": True, "mode": "wide"}
    current = QRectF(inner)
    icon_d = min(inner.height() * 0.30, inner.width() * 0.30)
    icon = QRectF(current.right() - icon_d, current.top(), icon_d, icon_d)
    temp_fs = int(max(14, min(current.width() * 0.30, current.height() * 0.32)))
    return {"inner": inner, "current": current, "icon": icon,
            "icon_d": icon_d,
            "daily_cols": [], "cols": [], "detail_chips": [],
            "temp_fs": temp_fs, "wide": False, "mode": "square"}


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
    if L["mode"] == "wide":
        _draw_wide_left(p, L, model, st, state)
        for i, col in enumerate(L["cols"]):
            if i >= len(model.daily):
                break
            _draw_daily_col(p, col, model.daily[i], st)
        p.restore()
        return

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

    p.restore()


def _chip(p: QPainter, rect: QRectF, label: str, value: str, style) -> None:
    """一个指标槽：「标签」淡色 + 「数值」亮色，同一基线顺序排。

    4×2 左块的湿度 / 风力用这个画。数值缺失（None）画 `--`，不编数。
    """
    fs = max(9, int(min(rect.height() * 0.62, 12)))
    f_lab = theme.ui_font(fs)
    f_val = theme.ui_font(fs, bold=True)
    p.setFont(f_lab)
    p.setPen(QColor(style.faint))
    base = QPointF(rect.left(), rect.center().y()
                   + (QFontMetricsF(f_lab).ascent() - QFontMetricsF(f_lab).descent()) / 2.0)
    p.drawText(base, label)
    w_lab = QFontMetricsF(f_lab).horizontalAdvance(label)
    p.setFont(f_val)
    p.setPen(QColor(style.text))
    p.drawText(QPointF(rect.left() + w_lab + 4.0, base.y()), value)


def _draw_wide_left(p: QPainter, L: Dict, model, style, state: str) -> None:
    """4×2 左栏：2×2 的全部内容 + 湿度 / 风力两个指标（v14 反馈 7）。"""
    st = style
    cur = L["current"]
    slots = L["left"]
    city = model.city or ""
    fs_city = max(9, int(min(cur.width() * 0.09, 12)))
    p.setFont(theme.ui_font(fs_city))
    fm = QFontMetricsF(p.font())
    max_w = max(10.0, L["icon"].left() - cur.left())
    while city and fm.horizontalAdvance(city) > max_w:
        city = city[:-1]
    p.setPen(QColor(st.dim))
    p.drawText(slots["city"], Qt.AlignLeft | Qt.AlignVCenter, city)

    draw_weather_icon(p, model.icon, L["icon"])

    p.setFont(theme.ui_font(L["temp_fs"], bold=True))
    p.setPen(QColor(st.text))
    p.drawText(slots["temp"], Qt.AlignLeft | Qt.AlignVCenter,
               wa.fmt_temp(model.temp))

    p.setFont(theme.ui_font(max(9, int(min(cur.width() * 0.075, 12)))))
    p.setPen(QColor(st.dim))
    p.drawText(slots["desc"], Qt.AlignLeft | Qt.AlignVCenter,
               "%s · 体感 %s" % (model.text, wa.fmt_temp(model.feels)))

    chips = L["detail_chips"]
    if len(chips) == 2:
        _chip(p, chips[0], "湿度", "%d%%" % int(model.humidity or 0), st)
        _chip(p, chips[1], "风力", "%d km/h" % int(round(model.wind or 0)), st)

    if model.daily:
        d0 = model.daily[0]
        p.setPen(QColor(st.faint))
        p.setFont(theme.ui_font(max(9, int(min(cur.width() * 0.075, 12)))))
        p.drawText(slots["tomorrow"], Qt.AlignLeft | Qt.AlignVCenter,
                   "明日 %s / %s" % (wa.fmt_temp(d0.tmax), wa.fmt_temp(d0.tmin)))

    if state == "cached":
        p.setPen(QColor(st.faint))
        p.setFont(theme.ui_font(9))
        p.drawText(QRectF(cur.right() - 120, cur.bottom() - 18, 120, 16),
                   Qt.AlignRight | Qt.AlignVCenter,
                   "缓存 · " + wa.age_text(model.fetched_at))


def _draw_daily_col(p: QPainter, col: Dict, d, style) -> None:
    """4×2 一天的小列：标签 / 图标 / 最高温 / 温程条 / 最低温。"""
    st = style
    fs = max(8, int(min(col["rect"].width() * 0.18, 11)))
    p.setFont(theme.ui_font(fs))
    p.setPen(QColor(st.faint))
    idx = int(col.get("index", 0))
    label = DAY_LABELS[idx] if 0 <= idx < len(DAY_LABELS) else ""
    p.drawText(col["label"], Qt.AlignHCenter | Qt.AlignVCenter, label)

    draw_weather_icon(p, wa.describe(d.code)[1], col["icon"])

    p.setFont(theme.ui_font(fs, bold=True))
    p.setPen(QColor(st.text))
    p.drawText(col["tmax"], Qt.AlignHCenter | Qt.AlignVCenter,
               wa.fmt_temp(d.tmax))

    # 温程条：淡轨道 + 凉→暖渐变的一段（段内渐变，跨天颜色语言一致）
    bar = col["bar"]
    lo, hi = col["fill"]
    radius = bar.height() / 2.0
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 26))
    p.drawRoundedRect(bar, radius, radius)
    fx0 = bar.left() + bar.width() * lo
    fx1 = bar.left() + bar.width() * hi
    seg = QRectF(fx0, bar.top(), max(bar.height(), fx1 - fx0), bar.height())
    grad = QLinearGradient(seg.left(), seg.top(), seg.right(), seg.top())
    grad.setColorAt(0.0, QColor(110, 198, 255))     # 凉：晨蓝
    grad.setColorAt(1.0, QColor(240, 152, 62))      # 暖：暮橙
    p.setBrush(grad)
    p.drawRoundedRect(seg, radius, radius)

    p.setFont(theme.ui_font(fs))
    p.setPen(QColor(st.faint))
    p.drawText(col["tmin"], Qt.AlignHCenter | Qt.AlignVCenter,
               wa.fmt_temp(d.tmin))


# ---------------------------------------------------------------- 组件

class WeatherWidget(GlassWidget):
    """天气组件：**只负责画**共享天气源里的那份数据（v10 A9 反馈 9）。

    取数、缓存、城市、联网开关全部在 `weather/source.py`——桌面面板里的
    天气卡订阅同一个源，于是"两个天气框显示两个温度"在结构上不可能发生。
    """

    TYPE = "weather"
    AUTO_REFRESH_MS = 1500              # 首刷延迟：先把界面画出来（测试可置 0）
    REFRESH_PERIOD_MS = wsource.REFRESH_PERIOD_MS

    def __init__(self, storage, entry):
        super().__init__(storage, entry)
        self._src = wsource.shared(storage)
        self._model: Optional[wa.WeatherModel] = self._src.model()
        self._state = self._src.state()
        self._src.subscribe(self._sync_source)
        self._adopt_city()
        if self.AUTO_REFRESH_MS:
            QTimer.singleShot(self.AUTO_REFRESH_MS, self.refresh)

    # ---------- 城市迁移 ----------
    def _adopt_city(self):
        """把旧版写在组件设置里的城市并入全局设置（只补缺，不覆盖用户）。"""
        own = str((self.entry.get("settings") or {}).get("city") or "").strip()
        if own and not self._src.city():
            self._src.set_city(own, refresh=False)

    # ---------- 取数 ----------
    def _settings(self) -> Dict:
        return self.entry.get("settings") or {}

    def refresh(self):
        """发起一次刷新（立即返回，UI 不等网络）。"""
        city = str(self._settings().get("city") or "").strip()
        if city and city != self._src.city():
            self._src.set_city(city, refresh=False)
        self._src.refresh()

    def _sync_source(self):
        """共享源变了：同步本地镜像并重画（订阅会跨线程排队回主线程）。"""
        self._model = self._src.model()
        self._state = self._src.state()
        self.update()

    # ---------- 绘制 ----------
    def paint_content(self, p: QPainter):
        draw(p, QRectF(self.card_rect()), self._model, self._state,
             style=self.style)

    def on_settings_changed(self):
        # 改城市 / 开关联网后立刻重取（关掉联网时走缓存分支）。
        # city / online 是**全局**设置的代理：面板天气卡与这个组件共用一份。
        super().on_settings_changed()
        st = self._settings()
        if "city" in st:
            self._src.set_city(str(st.get("city") or ""), refresh=False)
        if "online" in st:
            self._src.set_online(bool(st.get("online", True)), refresh=False)
        self.refresh()

    def closeEvent(self, e):
        try:
            self._src.unsubscribe(self._sync_source)
        except RuntimeError:
            pass
        super().closeEvent(e)
