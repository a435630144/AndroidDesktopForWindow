# -*- coding: utf-8 -*-
"""桌面小组件基类：无边框半透明卡片，挂载到桌面层（壁纸之上、应用窗口之下），
可拖动、可缩放、可关闭，几何自动持久化。"""
from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from . import theme
from .win32_layer import attach_to_desktop


class FloatingWidget(QWidget):
    closed = Signal(str)  # widget id

    def __init__(self, storage, entry, interactive: bool = False):
        super().__init__()
        self.storage = storage
        self.entry = entry
        self.attached = False
        self.interactive = interactive
        self._drag_off = None
        self._resizing = False
        self._resize_origin = None
        self._start_geom = None
        self._mouse_pos = None
        # 注意：不能用 WindowStaysOnTopHint，否则会盖在所有应用程序窗口之上；
        # 正确做法是挂载到桌面带（Progman 正上方），与整理窗口处于同一层级。
        flags = Qt.FramelessWindowHint | Qt.Tool
        if not interactive:
            # WindowDoesNotAcceptFocus(WS_EX_NOACTIVATE)：永不被激活，
            # 因此永远不会抢到应用窗口前面（"时钟组件被置顶"Bug 的根治）。
            # 仅用于纯展示型组件；交互型组件（便签 / 面板）必须可激活，
            # 否则里面的 QTextEdit / QLineEdit 拿不到键盘焦点，无法输入。
            flags |= Qt.WindowDoesNotAcceptFocus
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setMinimumSize(180, 120)
        # 首次创建（没有保存过位置）时放到屏幕右侧，避免遮挡左上角的图标网格
        if "x" not in entry:
            screen = QApplication.primaryScreen().availableGeometry()
            w, h = int(entry.get("w", 260)), int(entry.get("h", 140))
            entry["x"] = max(0, screen.right() - w - 80)
            entry["y"] = screen.top() + 80
            self.storage.save()
        self.setGeometry(
            int(entry.get("x", 60)), int(entry.get("y", 60)),
            int(entry.get("w", 260)), int(entry.get("h", 140)),
        )
        # 挂载在 showEvent 里做：窗口显示后才谈得上 z-order 插入桌面带
        self.show()

    def showEvent(self, e):
        super().showEvent(e)
        # 挂载到桌面带（Progman 正上方）：失败则保持普通无边框窗口（不置顶）。
        # 每次重新显示都重新插入：隐藏再显示后 Windows 可能已改变 z-order。
        self.attached = attach_to_desktop(self)

    # ---------- 几何持久化 ----------
    def _save_geom(self):
        g = self.geometry()
        self.entry["x"] = g.x()
        self.entry["y"] = g.y()
        self.entry["w"] = g.width()
        self.entry["h"] = g.height()
        self.storage.save()

    def _close_rect(self):
        return QRect(self.width() - 28, 8, 20, 20)

    def _grip_rect(self):
        return QRect(self.width() - 22, self.height() - 22, 20, 20)

    # ---------- 绘制 ----------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(theme.SURFACE)
        p.setPen(theme.BORDER)
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), theme.RADIUS_PANEL, theme.RADIUS_PANEL)
        # 关闭按钮
        r = self._close_rect()
        if self._mouse_pos is not None and r.contains(self._mouse_pos):
            p.setBrush(theme.DANGER)
            p.setPen(Qt.NoPen)
            p.drawEllipse(r)
        p.setPen(theme.TEXT_DIM)
        font = QFont()
        font.setPixelSize(14)
        font.setBold(True)
        p.setFont(font)
        p.drawText(r, Qt.AlignCenter, "×")
        # 缩放手柄（右下角斜纹）
        g = self._grip_rect()
        p.setPen(QColor(255, 255, 255, 90))
        for i in range(3):
            p.drawLine(g.left() + 3, g.bottom() - 3 - i * 5,
                       g.right() - 3 - i * 5, g.bottom() - 3)

    # ---------- 鼠标 ----------
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self._close_rect().contains(e.pos()):
            self.entry["hidden"] = True
            self.storage.save()
            self.closed.emit(self.entry.get("id", ""))
            self.close()
            return
        if self._grip_rect().contains(e.pos()):
            self._resizing = True
            self._resize_origin = e.globalPosition().toPoint()
            self._start_geom = self.geometry()
            return
        self._drag_off = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        self._mouse_pos = e.pos()
        if self._resizing:
            delta = e.globalPosition().toPoint() - self._resize_origin
            w = max(self.minimumWidth(), self._start_geom.width() + delta.x())
            h = max(self.minimumHeight(), self._start_geom.height() + delta.y())
            self.resize(w, h)
        elif self._drag_off is not None:
            self.move(e.globalPosition().toPoint() - self._drag_off)
        elif self._grip_rect().contains(e.pos()):
            self.setCursor(Qt.SizeFDiagCursor)
        else:
            self.unsetCursor()
        self.update()

    def mouseReleaseEvent(self, e):
        if self._resizing or self._drag_off is not None:
            self._save_geom()
        self._resizing = False
        self._drag_off = None
