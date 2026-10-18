# -*- coding: utf-8 -*-
"""时钟小组件：深色卡片 + 大号时间（含秒）+ 中文日期。

M3 排版重做（指导文档 §3.3，反馈 P3「时钟碰撞形状不对+推动无动画」）：
catalog 一等公民化后 clock = 2×2 格（240×284 @125% DPI），排版按
容器高度比例缩放——时间行 + 日期行两行式，秒数与时间同行（右侧小号），
日期在下；任何跨度/DPI 下都按比例重排（on_resized 钩子），2×2 零溢出。
"""
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
        lay.setSpacing(0)
        lay.addStretch(3)          # 时间行偏上（iOS 桌面 widget 语言）
        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setTextFormat(Qt.RichText)
        # 字体设在控件上（富文本未覆盖的属性继承控件字体）；
        # 注意：rich text 的 style 属性值内不能再出现双引号，否则 HTML 会被截断
        self.time_label.setFont(theme.ui_font(46, bold=True))
        lay.addWidget(self.time_label)
        lay.addSpacing(6)
        self.date_label = QLabel()
        self.date_label.setAlignment(Qt.AlignCenter)
        self.date_label.setFont(theme.ui_font(13))
        self.date_label.setStyleSheet("color: %s; background: transparent;" % theme.rgba(theme.TEXT_DIM))
        lay.addWidget(self.date_label)
        lay.addStretch(4)          # 日期行偏下，与时间行拉开呼吸
        self._fs = (46, 20, 13)    # (time, sec, date) 当前字号，_tick 复用
        self._apply_fonts()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    # ---------- 比例排版（M3） ----------
    def on_resized(self):
        """尺寸变化（span 切换 / DPI 变化）→ 字号与边距按容器比例重算。"""
        if not hasattr(self, "_fs"):
            return    # __init__ 尚未走完（基类 setGeometry/show 期间的事件）
        self._apply_fonts()

    def _apply_fonts(self):
        """字号 / 边距随容器高度比例缩放；容器高度 = 跨度行数 × 行高，
        因此 2×2 与将来的 2×3 都自动适配，无需按跨度特判。"""
        h = max(120, self.height())
        w = max(180, self.width())
        t = max(24, int(h * 0.21))          # 284 * 0.21 ≈ 59
        s = max(12, int(t * 0.46))          # 秒数：时间字号的 46%
        d = max(10, int(h * 0.075))         # 284 * 0.075 ≈ 21
        self._fs = (t, s, d)
        self.time_label.setFont(theme.ui_font(t, bold=True))
        self.date_label.setFont(theme.ui_font(d))
        lay = self.layout()
        if lay is not None:
            lay.setContentsMargins(int(w * 0.06), int(h * 0.10),
                                   int(w * 0.06), int(h * 0.08))
        self._tick()

    def _tick(self):
        now = QDateTime.currentDateTime()
        t, s, _d = self._fs
        self.time_label.setText(
            '<span style="font-size:%dpx; color:#F2F3F5;">%s</span>'
            '<span style="font-size:%dpx; color:#A8ADB5;">&nbsp;:%s</span>'
            % (t, now.toString("HH:mm"), s, now.toString("ss")))
        weekday = _WEEKDAYS_CN.get(now.toString("dddd"), now.toString("dddd"))
        self.date_label.setText(now.toString("M月d日") + " " + weekday)


_WEEKDAYS_CN = {
    "Monday": "星期一", "Tuesday": "星期二", "Wednesday": "星期三",
    "Thursday": "星期四", "Friday": "星期五", "Saturday": "星期六", "Sunday": "星期日",
    "周一": "星期一", "周二": "星期二", "周三": "星期三",
    "周四": "星期四", "周五": "星期五", "周六": "星期六", "周日": "星期日",
}
