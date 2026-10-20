# -*- coding: utf-8 -*-
"""不透明弹出层的下拉框（v7 反馈 4）。

现象：设置页下拉展开后**背景不实心**，下层文字透上来。

根因：QComboBox 的候选列表是**独立顶层窗口**（Qt::Popup）。Qt 为了让
QSS 里的 `border-radius` 圆角可见，会给这个弹层开半透明（per-pixel
alpha）；`QComboBox QAbstractItemView{background: ...}` 只涂到 list view
自己的矩形，弹层容器 / 内边距 / 圆角之外仍然是透明的——壁纸或面板文字
就从这些缝里透上来。

修法不改 QSS（QSS 表达不了"弹层窗口本身要实心"），而是在 showPopup()
之后把弹层拉回实心：

  - 容器窗口 + list view + viewport 三处关掉 WA_TranslucentBackground
  - 三处 setAutoFillBackground(True)，palette 的 Window/Base 刷成面板色
  - windowOpacity 强制 1.0（继承来的半透明会连带文字一起变淡）

三处都要做：只刷 view 的 viewport 时，Qt 仍会按容器的透明窗口合成，
圆角外的像素依旧是"透"的。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QComboBox, QListView

# 与 theme.SETTINGS_QSS 里 `QComboBox QAbstractItemView` 同一底色
POPUP_BG = QColor(38, 38, 44)
POPUP_TEXT = QColor(242, 243, 245)


class ComboBox(QComboBox):
    """实心弹层的下拉框（设置页统一用它，别再裸用 QComboBox）。"""

    def __init__(self, parent=None, bg=None, text=None):
        super().__init__(parent)
        self._popup_bg = QColor(bg) if bg is not None else QColor(POPUP_BG)
        self._popup_text = QColor(text) if text is not None else QColor(POPUP_TEXT)
        # 显式给一个 QListView：默认 QComboBoxListView 在部分平台上会把
        # 背景画到窗口层，换成普通 QListView 后底色由我们自己兜
        view = QListView(self)
        view.setUniformItemSizes(True)
        view.setFrameShape(QListView.NoFrame)
        self.setView(view)

    # ---------- 弹出层实心化 ----------
    def showPopup(self):
        super().showPopup()
        self.solidify()

    def solidify(self):
        """把弹层三层（窗口 / view / viewport）全部刷成不透明面板色。"""
        try:
            view = self.view()
        except Exception:
            return False
        targets = [view, view.window()]
        try:
            targets.append(view.viewport())
        except Exception:
            pass
        for w in targets:
            if w is None:
                continue
            w.setAttribute(Qt.WA_TranslucentBackground, False)
            w.setAutoFillBackground(True)
            pal = w.palette()
            pal.setColor(QPalette.Window, self._popup_bg)
            pal.setColor(QPalette.Base, self._popup_bg)
            pal.setColor(QPalette.Button, self._popup_bg)
            pal.setColor(QPalette.WindowText, self._popup_text)
            pal.setColor(QPalette.Text, self._popup_text)
            w.setPalette(pal)
            w.setWindowOpacity(1.0)
        return True
