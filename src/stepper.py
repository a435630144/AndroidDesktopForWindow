# -*- coding: utf-8 -*-
"""Stepper：数值步进器（2026-10-21 用户反馈 2，替代设置面板里的 QSpinBox）。

用户原话：

    「设置面板的文件夹大小调节，不要把行列放进框里，让用户以为字也可以
      编辑，并且数字的增加减少箭头没有渲染（其他类似功能的地方也看不到
      箭头）。」

两个病根，都在 QSpinBox 上：

  1. **长得像输入框**：微调框带边框 + 线框感，数字在里面用户就想去点它
     打字；而它在本项目里只是"展示 + 步进"，没有键入需求。
  2. **箭头被 QSS 吞了**：`theme.py` 的 `SPIN_QSS` / `DARK_QSS` 把
     `QSpinBox::up-button, ::down-button` 设成 `background: transparent;
     border: none`——子控件的盒模型被清空后，Fusion 风格不再往上面画
     `PE_IndicatorArrowUp/Down`，于是**所有**用到微调框的地方都没有箭头
     （不是某一处漏配，是全局规则）。

Stepper 的取舍：不自绘"微调框"（那是把 bug 重画一遍），而是换成
「数值标签 + 两个自绘圆角小按钮」——按钮一定看得到、点得到，数字不再
处在"可编辑"的框里。接口刻意与 QSpinBox 同名（`value()` / `setValue()` /
`setRange()` / `valueChanged` / `setEnabled()` / `setSuffix()`），
设置面板的调用点几乎不用改。

长按自动连步（400ms 起、80ms 一步）：行列从 3 调到 8 不用点 5 次。
"""
from PySide6.QtCore import (QEasingCurve, QPropertyAnimation, QRectF, Qt,
                            QTimer, Signal)
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from . import theme

BTN_W = 22            # 单个步进按钮宽
BTN_GAP = 2           # 两按钮间距
REPEAT_DELAY = 400    # 长按起步延迟（ms）
REPEAT_STEP = 80      # 长按连步间隔（ms）


class Stepper(QWidget):
    """数值标签 + ▲/▼ 两个自绘按钮（drop-in 替代 QSpinBox）。"""

    valueChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._lo = 0
        self._hi = 99
        self._step = 1
        self._suffix = ""
        self._hover = None          # "up" / "down" / None
        self._press = None          # "up" / "down" / None
        self._repeat = QTimer(self)
        self._repeat.setSingleShot(True)
        self._repeat.timeout.connect(self._on_repeat)
        self._auto = QTimer(self)
        self._auto.setInterval(REPEAT_STEP)
        self._auto.timeout.connect(self._on_repeat)
        self.setFixedHeight(30)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(84)

    # ---------- QSpinBox 兼容接口 ----------
    def value(self) -> int:
        return self._value

    def setValue(self, v: int):
        # 夹紧：QSpinBox 的 setValue 也夹（超出 range 时显示边界值），
        # 不夹会让"设 9999 显示 9999"而步进又跳到上限，界面与逻辑不一致
        v = max(self._lo, min(int(v), self._hi))
        if v == self._value:
            return
        self._value = v
        self.update()
        self.valueChanged.emit(v)

    def setRange(self, lo: int, hi: int):
        self._lo, self._hi = int(lo), int(hi)
        self.setValue(max(self._lo, min(self._value, self._hi)))
        self.update()

    def minimum(self) -> int:
        return self._lo

    def maximum(self) -> int:
        return self._hi

    def setSuffix(self, s: str):
        self._suffix = s or ""
        self.update()

    def suffix(self) -> str:
        return self._suffix

    def setSingleStep(self, n: int):
        self._step = max(1, int(n))

    def singleStep(self) -> int:
        return self._step

    def stepBy(self, steps: int):
        self.setValue(max(self._lo, min(self._value + int(steps) * self._step,
                                        self._hi)))

    # ---------- 几何 ----------
    def _btn_up_rect(self):
        return QRectF(self.width() - BTN_W, 1, BTN_W, self.height() / 2 - 1)

    def _btn_down_rect(self):
        return QRectF(self.width() - BTN_W, self.height() / 2, BTN_W,
                      self.height() / 2 - 1)

    def _btn_rect(self, which):
        return self._btn_up_rect() if which == "up" else self._btn_down_rect()

    def _hit(self, pos):
        if self._btn_up_rect().contains(pos):
            return "up"
        if self._btn_down_rect().contains(pos):
            return "down"
        return None

    # ---------- 交互 ----------
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton or not self.isEnabled():
            return
        which = self._hit(e.pos())
        if which is None:
            return
        self._press = which
        self.stepBy(1 if which == "up" else -1)
        self._repeat.start(REPEAT_DELAY)
        self.update()

    def mouseMoveEvent(self, e):
        h = self._hit(e.pos())
        if h != self._hover:
            self._hover = h
            self.update()

    def mouseReleaseEvent(self, e):
        self._stop_repeat()
        super().mouseReleaseEvent(e)

    def leaveEvent(self, e):
        self._hover = None
        self.update()

    def _stop_repeat(self):
        self._press = None
        self._repeat.stop()
        self._auto.stop()
        self.update()

    def _on_repeat(self):
        if self._press is None:
            return
        self.stepBy(1 if self._press == "up" else -1)
        if not self._auto.isActive():
            self._auto.start()

    def wheelEvent(self, e):
        """滚轮也能步进（设置面板里换滑道成本高，随手滚一下更顺）。"""
        if not self.isEnabled():
            e.ignore()
            return
        d = e.angleDelta().y()
        if d:
            self.stepBy(1 if d > 0 else -1)
            e.accept()
            return
        e.ignore()

    # ---------- 绘制 ----------
    def _tri(self, p, cx, cy, r, up: bool):
        """实心三角（不用 ▲/▼ 字符：各字体下基线不齐；也不用 QSS 三角，
        本项目已有"subcontrol 上 width:0+border 画不出三角"的坑 #79）。"""
        path = QPainterPath()
        if up:
            p0, p1, p2 = (cx, cy - r), (cx - r, cy + r), (cx + r, cy + r)
        else:
            p0, p1, p2 = (cx, cy + r), (cx - r, cy - r), (cx + r, cy - r)
        path.moveTo(*p0)
        path.lineTo(*p1)
        path.lineTo(*p2)
        path.closeSubpath()
        p.drawPath(path)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        en = self.isEnabled()
        # 底板：极淡圆角底（不是"输入框"——无边框、无内阴影、不可聚焦）
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 12 if en else 6))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 8, 8)
        # 数值：右对齐到按钮左侧（按钮永远在右，数字不参与"可编辑"暗示）
        p.setPen(QColor(240, 242, 246, 235 if en else 120))
        f = theme.ui_font(13, bold=True)
        p.setFont(f)
        text = "%d%s" % (self._value, self._suffix)
        p.drawText(QRectF(10, 0, self.width() - BTN_W - 14, self.height()),
                   Qt.AlignVCenter | Qt.AlignRight, text)
        # 两枚按钮：圆角底 + 三角（hover/press 有反馈，禁用态整体变暗）
        for which in ("up", "down"):
            r = self._btn_rect(which)
            hovered = (self._hover == which and en)
            pressed = (self._press == which and en)
            bg = QColor(255, 255, 255,
                        (46 if pressed else (26 if hovered else 14)) if en else 6)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(r, 6, 6)
            c = r.center()
            p.setBrush(QColor(235, 238, 244, 235 if en else 110))
            self._tri(p, c.x(), c.y(), 3.4, which == "up")
