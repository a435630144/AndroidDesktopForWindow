# -*- coding: utf-8 -*-
"""日历组件（v8 C6，指导文档_v8.md §4.3）。

三层分离：
    month_matrix / shift_month / week_labels / build_model   纯数据（stdlib calendar）
    layout(rect, model)                                      纯几何
    draw(painter, rect, model)                               纯绘制
    CalendarWidget(GlassWidget)                              点击切换月份

不做农历 / 节假日 / 日程：v8 的目标是"看得清、翻得动"。农历要单独一张
数据表与每年的排布规则，属于 v9 的日程能力，塞进来只会让这个组件变脆。
"""
from __future__ import annotations

import calendar
import datetime
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen

from . import theme
from .widget_style import DEFAULT_STYLE, Style
from .widget_glass import PAD, GlassWidget

WEEKDAY_LABELS = ("一", "二", "三", "四", "五", "六", "日")
CELL_FS_RATIO = 0.44        # 字号 / 格宽
TODAY_R = 0.34              # 今天实心圆半径 / 格短边


# ---------------------------------------------------------------- 纯数据

def month_matrix(year: int, month: int, firstweekday: int = 0) -> List[List[int]]:
    """月矩阵：每行 7 格，0 = 非本月占位（对齐 stdlib calendar）。"""
    cal = calendar.Calendar(firstweekday)
    return [list(wk) for wk in cal.monthdayscalendar(year, month)]


def shift_month(year: int, month: int, delta: int) -> Tuple[int, int]:
    """跨年安全的月份偏移（12 月 +1 必须是次年 1 月）。"""
    idx = year * 12 + (month - 1) + int(delta)
    return idx // 12, idx % 12 + 1


def week_labels(firstweekday: int) -> Tuple[str, ...]:
    """周标题行按起始日轮转（周一起始 = 一…日；周日起始 = 日…六）。"""
    fw = int(firstweekday) % 7
    return tuple(WEEKDAY_LABELS[(fw + i) % 7] for i in range(7))


@dataclass(frozen=True)
class CalendarModel:
    year: int
    month: int
    firstweekday: int
    weeks: Tuple[Tuple[int, ...], ...]
    today: Optional[datetime.date] = None

    @property
    def title(self) -> str:
        return "%d 年 %d 月" % (self.year, self.month)


def build_model(year: int, month: int, firstweekday: int = 0,
                today: Optional[datetime.date] = None) -> CalendarModel:
    weeks = tuple(tuple(w) for w in month_matrix(year, month, firstweekday))
    return CalendarModel(year=year, month=month, firstweekday=int(firstweekday) % 7,
                         weeks=weeks,
                         today=today if today is not None else datetime.date.today())


# ---------------------------------------------------------------- 纯几何

def layout(rect, model: CalendarModel) -> dict:
    """标题行（含左右箭头）/ 周标题行 / 日期格。任意 rect 都不许抛。"""
    rect = QRectF(rect)
    w = max(1.0, rect.width())
    h = max(1.0, rect.height())
    pad = min(PAD, w * 0.10, h * 0.08)
    inner = rect.adjusted(pad, pad, -pad, -pad)

    title_h = max(14.0, min(28.0, inner.height() * 0.13))
    title = QRectF(inner.left(), inner.top(), inner.width(), title_h)
    arrow = min(title_h, 22.0)
    nav_left = QRectF(title.left(), title.center().y() - arrow / 2, arrow, arrow)
    nav_right = QRectF(title.right() - arrow, title.center().y() - arrow / 2,
                       arrow, arrow)
    title_mid = QRectF(nav_left.right(), title.top(),
                       max(1.0, nav_right.left() - nav_left.right()), title_h)

    week_h = max(10.0, min(18.0, inner.height() * 0.08))
    week_row = QRectF(inner.left(), title.bottom() + 2, inner.width(), week_h)

    days_top = week_row.bottom() + 1
    days_h = max(1.0, inner.bottom() - days_top)
    rows = max(1, len(model.weeks))
    cell_w = inner.width() / 7.0
    cell_h = days_h / rows
    cells = []
    for wi in range(rows):
        row = []
        for di in range(7):
            row.append(QRectF(inner.left() + di * cell_w, days_top + wi * cell_h,
                              cell_w, cell_h))
        cells.append(row)

    fs = int(max(6, min(cell_w * CELL_FS_RATIO, cell_h * 0.46, 20)))
    week_fs = int(max(6, min(fs * 0.82, week_h * 0.86)))
    title_fs = int(max(8, min(title_h * 0.56, 18)))
    return {"inner": inner, "title": title, "title_mid": title_mid,
            "nav_left": nav_left, "nav_right": nav_right,
            "week_row": week_row, "cells": cells, "fs": fs,
            "week_fs": week_fs, "title_fs": title_fs,
            "cell_w": cell_w, "cell_h": cell_h}


# ---------------------------------------------------------------- 纯绘制

def draw(p: QPainter, rect, model: CalendarModel, style: Optional[Style] = None) -> None:
    st = style or DEFAULT_STYLE
    rect = QRectF(rect)
    if rect.width() <= 6 or rect.height() <= 6:
        return
    L = layout(rect, model)
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)

    # 标题
    p.setFont(theme.ui_font(L["title_fs"], bold=True))
    p.setPen(QColor(st.text))
    p.drawText(L["title_mid"], Qt.AlignCenter, model.title)

    # 左右箭头（自绘雪佛龙，比字符 "<" 更居中）
    p.setPen(QPen(QColor(st.dim), 1.6, Qt.SolidLine, Qt.RoundCap,
                  Qt.RoundJoin))
    for nav, sign in ((L["nav_left"], -1), (L["nav_right"], 1)):
        c = nav.center()
        d = nav.width() * 0.18
        p.drawLine(QPointF(c.x() + sign * d, c.y() - d),
                   QPointF(c.x() - sign * d, c.y()))
        p.drawLine(QPointF(c.x() - sign * d, c.y()),
                   QPointF(c.x() + sign * d, c.y() + d))

    # 周标题
    p.setFont(theme.ui_font(L["week_fs"]))
    p.setPen(QColor(st.faint))
    for di, label in enumerate(week_labels(model.firstweekday)):
        cr = QRectF(L["week_row"].left() + di * L["cell_w"], L["week_row"].top(),
                    L["cell_w"], L["week_row"].height())
        p.drawText(cr, Qt.AlignCenter, label)

    # 日期格
    today = model.today
    for wi, week in enumerate(model.weeks):
        for di, day in enumerate(week):
            if day <= 0:
                continue        # 非本月：留空（不画灰字，避免和"今天"抢注意力）
            cr = L["cells"][wi][di]
            is_today = bool(today and today.year == model.year
                            and today.month == model.month and today.day == day)
            if is_today:
                r = min(cr.width(), cr.height()) * TODAY_R
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(st.accent))
                p.drawEllipse(cr.center(), r, r)
                p.setPen(QColor(16, 18, 24))
                p.setFont(theme.ui_font(L["fs"], bold=True))
            else:
                weekend = di >= 5
                p.setPen(QColor(st.dim) if weekend else QColor(st.text))
                p.setFont(theme.ui_font(L["fs"]))
            p.drawText(cr, Qt.AlignCenter, str(day))
    p.restore()


def draw_preview(p: QPainter, rect, dpr: float = 1.0) -> None:
    now = datetime.date.today()
    draw(p, rect, build_model(now.year, now.month, 0, today=now))


# ---------------------------------------------------------------- 组件

class CalendarWidget(GlassWidget):
    TYPE = "calendar"

    def __init__(self, storage, entry):
        super().__init__(storage, entry)
        today = datetime.date.today()
        self._year = int(entry.get("cal_year") or today.year)
        self._month = int(entry.get("cal_month") or today.month)
        self._clamp_month()

    # ---------- 状态 ----------
    def _firstweekday(self) -> int:
        try:
            return int((self.entry.get("settings") or {}).get("week_start", 0)) % 7
        except (TypeError, ValueError):
            return 0

    def _clamp_month(self):
        """把存储里可能越界的 (年, 月) 归一（month=13 → 次年 1 月）。"""
        y, m = divmod(self._year * 12 + (self._month - 1), 12)
        self._year, self._month = y, m + 1

    def model(self) -> CalendarModel:
        return build_model(self._year, self._month, self._firstweekday())

    def _goto(self, year: int, month: int):
        self._year, self._month = year, month
        self.entry["cal_year"] = year
        self.entry["cal_month"] = month
        self.storage.save()
        self.update()

    def go_shift(self, delta: int):
        y, m = shift_month(self._year, self._month, delta)
        self._goto(y, m)

    def go_today(self):
        t = datetime.date.today()
        self._goto(t.year, t.month)

    # ---------- 绘制 / 交互 ----------
    def paint_content(self, p: QPainter):
        draw(p, QRectF(self.rect()), self.model(), style=self.style)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            L = layout(QRectF(self.rect()), self.model())
            pos = e.position()
            if L["nav_left"].contains(pos):
                self.go_shift(-1)
                return
            if L["nav_right"].contains(pos):
                self.go_shift(1)
                return
            if L["title"].contains(pos):
                self.go_today()
                return
        super().mousePressEvent(e)

    def on_settings_changed(self):
        super().on_settings_changed()   # 清样式缓存 + 重绘
        self.update()
