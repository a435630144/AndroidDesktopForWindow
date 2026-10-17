# -*- coding: utf-8 -*-
"""时钟小组件：深色卡片 + 大号时间 + 秒数 + 中文日期。"""
from PySide6.QtCore import QDateTime, QTimer, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout

from . import theme
from .widget_base import FloatingWidget


class ClockWidget(FloatingWidget):
    TYPE = "clock"

    def __init__(self, storage, entry):
        # interactive=False：纯展示，保持 NOACTIVATE，永不被激活/抢焦点
        super().__init__(storage, entry, interactive=False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 36, 18, 16)
        lay.setSpacing(4)
        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setTextFormat(Qt.RichText)
        # 字体设在控件上（富文本未覆盖的属性继承控件字体）；
        # 注意：rich text 的 style 属性值内不能再出现双引号，否则 HTML 会被截断
        self.time_label.setFont(theme.ui_font(46, bold=True))
        self.date_label = QLabel()
        self.date_label.setAlignment(Qt.AlignCenter)
        self.date_label.setFont(theme.ui_font(13))
        self.date_label.setStyleSheet("color: %s; background: transparent;" % theme.rgba(theme.TEXT_DIM))
        lay.addWidget(self.time_label)
        lay.addWidget(self.date_label)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    def _tick(self):
        now = QDateTime.currentDateTime()
        self.time_label.setText(
            '<span style="font-size:46px; color:#F2F3F5;">%s</span>'
            '<span style="font-size:20px; color:#A8ADB5;">&nbsp;&nbsp;:%s</span>'
            % (now.toString("HH:mm"), now.toString("ss")))
        weekday = _WEEKDAYS_CN.get(now.toString("dddd"), now.toString("dddd"))
        self.date_label.setText(now.toString("M月d日") + " " + weekday)


_WEEKDAYS_CN = {
    "Monday": "星期一", "Tuesday": "星期二", "Wednesday": "星期三",
    "Thursday": "星期四", "Friday": "星期五", "Saturday": "星期六", "Sunday": "星期日",
    "周一": "星期一", "周二": "星期二", "周三": "星期三",
    "周四": "星期四", "周五": "星期五", "周六": "星期六", "周日": "星期日",
}
