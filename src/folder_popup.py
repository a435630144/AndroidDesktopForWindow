# -*- coding: utf-8 -*-
"""液态玻璃文件夹弹窗：背后内容实时模糊 + tint + 边缘高光（苹果 Liquid Glass 风）。

开合动效（参考 iOS 文件夹 / Liquid Glass 材质语言）：
  - 打开：窗口直接以最终尺寸显示，但玻璃表面从锚点图标的位置"涌出"
    （背板缩放 0.62->1.0，OutBack 弹性过冲 = 液态 wobble）+ 透明度淡入；
    成员图标错峰淡入。窗口尺寸全程不变——不动 geometry 动画，避免
    setFixedSize 钳制起点 / 子控件不随窗口缩放等一系列坑。
  - 关闭：反向（缩放收 0.55 + 淡出）后才真正 close；防重入。

液态玻璃实现说明（为什么不用 acrylic API）：
  SetWindowCompositionAttribute 的 ACCENT_ENABLE_ACRYLICBLURBEHIND 与
  Qt 的 WA_TranslucentBackground + WS_EX_LAYERED 组合冲突（acrylic 不显示）。
  改为 show() 前抓屏 -> C++ 层高斯模糊 -> paintEvent 自绘，跨 Win10/Win11
  稳定，观感完全可控。桌面场景背后基本静态，一次性抓取完全够用。
"""
import traceback

from PySide6.QtCore import (QParallelAnimationGroup, QPointF, QPropertyAnimation,
                            QRect, QRectF, Qt, Signal, QEasingCurve, Property)
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from . import effects
from . import theme
from .iconwidget import AppIcon

ZOOM_FROM = 0.62   # 打开时玻璃初始缩放（相对最终尺寸）
ZOOM_TO = 0.55     # 关闭时玻璃收起的缩放


class FolderPopup(QWidget):
    launchApp = Signal(dict)
    extractRequested = Signal(str)   # payload "M:fid:idx"（M: 标记与含冒号的条目 id 消歧）
    removeMember = Signal(str)       # payload "M:fid:idx"
    closed = Signal()

    def __init__(self, storage, entry, anchor_rect=None, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.entry = entry
        self._dragging = False
        self._closing = False
        self._backdrop = QPixmap()
        self._zoom = 1.0             # 玻璃表面缩放（开合动效驱动）
        self._zoom_center = QPointF(0.5, 0.5)  # 缩放中心（弹窗本地坐标）
        self._anchor_rect = anchor_rect  # 锚点图标全局矩形（动画起点参照）
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._build(anchor_rect)
        self._open_animate()

    # ---------- 布局 ----------
    def _build(self, anchor_rect, keep_backdrop=False):
        for child in self.findChildren(AppIcon):
            child.deleteLater()
        icon_size = max(52, int(self.storage.get_setting("icon_size")) - 18)
        members = self.entry.get("apps", [])
        cols = min(4, max(2, (len(members) + 1) // 2)) if members else 2
        rows = max(1, (len(members) + cols - 1) // cols)
        pitch_x = icon_size + 22
        pitch_y = icon_size + 44
        pad, title_h = 16, 36
        w = pad * 2 + (cols - 1) * pitch_x + icon_size
        h = pad + title_h + (rows - 1) * pitch_y + (icon_size + 42) + pad - 8
        self.setFixedSize(max(220, w), max(150, h))
        if anchor_rect is not None:
            screen = QGuiApplication.screenAt(anchor_rect.center()) \
                or QGuiApplication.primaryScreen()
            geo = screen.availableGeometry()
            x = anchor_rect.center().x() - self.width() // 2
            y = anchor_rect.top() - self.height() - 10
            if y < geo.top() + 8:
                y = anchor_rect.bottom() + 10
            x = max(geo.left() + 8, min(x, geo.right() - self.width() - 8))
            y = max(geo.top() + 8, min(y, geo.bottom() - self.height() - 8))
            self.move(x, y)
            # 玻璃从图标位置涌出：缩放中心 = 图标中心（弹窗本地坐标）
            self._zoom_center = self.mapFromGlobal(anchor_rect.center())
        if not keep_backdrop:
            # 玻璃背板：必须在 show() 之前抓屏，否则会把自己抓进去
            self._backdrop = effects.glass_backdrop(
                QRect(self.x(), self.y(), self.width(), self.height()))
        for i, app in enumerate(members):
            member_payload = "M:%s:%d" % (self.entry.get("id"), i)
            entry = {"id": member_payload, "type": "app", "app": app}
            icon = AppIcon(entry, icon_size, in_folder=True, parent=self)
            icon.drag_payload = member_payload
            icon.dragStarted.connect(self._on_drag_start)
            icon.dragFinished.connect(self._on_drag_finish)
            icon.activated.connect(self.launchApp.emit)
            icon.removeFromFolder.connect(self.removeMember.emit)
            icon.move(pad + (i % cols) * pitch_x, pad + title_h + (i // cols) * pitch_y)
            # 弹窗内图标错峰淡入（玻璃涌出后依次浮现）
            icon.appear_in(120 + i * 45)
            icon.show()
        self.activateWindow()

    # ---------- 开合动效 ----------
    def _open_animate(self):
        """液态涌现：背板从图标位置缩放着陆 + 淡入。

        曲线按苹果 Fluid Interfaces 规范取值：
          - sheet 档弹窗 = damping 0.8 / response 0.3（OutBack overshoot
            1.0 ≈ Motion bounce 0.2），打开可轻微过冲
          - 系统关闭动画效果时（reduced-motion 等价）退化为临界阻尼 +
            时长压减——保留反馈、去掉弹性位移
        """
        self.setWindowOpacity(0.0)
        self._zoom = ZOOM_FROM
        rm = effects.reduced_motion()
        group = QParallelAnimationGroup(self)
        opa = QPropertyAnimation(self, b"windowOpacity", self)
        opa.setDuration(effects.dur(180))
        opa.setStartValue(0.0)
        opa.setEndValue(1.0)
        opa.setEasingCurve(QEasingCurve.OutCubic)
        zoom = QPropertyAnimation(self, b"zoom", self)
        zoom.setDuration(effects.dur(340))
        zoom.setStartValue(float(ZOOM_FROM))
        zoom.setEndValue(1.0)
        zoom.setEasingCurve(effects.smooth_out() if rm else effects.spring_out())
        group.addAnimation(opa)
        group.addAnimation(zoom)
        group.start()
        self._open_anim = group  # 持有引用，避免被 GC
        self.show()

    def close(self):
        """反向收起（缩放 + 淡出）后才真正关闭；动画期间防重入。
        进出场同路径：都绕锚点图标中心收放。"""
        if self._closing:
            return
        self._closing = True
        group = QParallelAnimationGroup(self)
        opa = QPropertyAnimation(self, b"windowOpacity", self)
        opa.setDuration(effects.dur(200))
        opa.setStartValue(float(self.windowOpacity()))
        opa.setEndValue(0.0)
        opa.setEasingCurve(QEasingCurve.InCubic)
        zoom = QPropertyAnimation(self, b"zoom", self)
        zoom.setDuration(effects.dur(220))
        zoom.setStartValue(float(self._zoom))
        zoom.setEndValue(float(ZOOM_TO))
        zoom.setEasingCurve(QEasingCurve.InCubic)
        group.addAnimation(opa)
        group.addAnimation(zoom)
        group.finished.connect(self._really_close)
        group.start()
        self._close_anim = group  # 持有引用，避免被 GC

    def _really_close(self):
        super().close()

    def refresh(self):
        """成员变化后刷新；文件夹已消失或为空则自动关闭。"""
        found = self.storage.find_entry(self.entry.get("id"))
        if not found or found.get("type") != "folder" or not found.get("apps"):
            self.close()
            return
        self.entry = found
        # 保留背板（此时已 show，重抓会把自己抓进去）
        self._build(None, keep_backdrop=True)

    def _on_drag_start(self):
        self._dragging = True

    def _on_drag_finish(self):
        self._dragging = False

    # ---------- 绘制：液态玻璃 ----------
    def _get_zoom(self):
        return self._zoom

    def _set_zoom(self, v):
        if v != self._zoom:
            self._zoom = v
            self.update()

    zoom = Property(float, _get_zoom, _set_zoom)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        z = self._zoom
        # 玻璃表面：以图标中心为原点缩放着陆（z<1 时小于窗口，
        # 周围全透明——视觉上就是玻璃从图标位置涌出）
        w, h = self.width() * z, self.height() * z
        rect = QRectF(self._zoom_center.x() - w / 2,
                      self._zoom_center.y() - h / 2, w, h)
        try:
            effects.paint_glass(p, rect, self._backdrop, theme.GLASS_RADIUS * z)
        except Exception:
            # shell 类应用里 paintEvent 异常会穿过多层活动 QPainter 直接
            # 杀死进程（实测 Fatal error: Aborted / SIGSEGV）。兜底：
            # 画纯色圆角背板，保证弹窗可用；同时留痕便于排查。
            traceback.print_exc()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(24, 26, 32, 235))
            p.drawRoundedRect(rect, theme.GLASS_RADIUS * z,
                              theme.GLASS_RADIUS * z)
        # 标题：随玻璃浮现渐显；vibrancy 规范——材质上文字提高对比、
        # 稍加字重、微加字距（不用平灰）
        if z > 0.55:
            p.setOpacity(min(1.0, (z - 0.55) / 0.35))
            p.setPen(theme.TEXT)
            f = theme.ui_font(13, bold=True)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 0.3)
            p.setFont(f)
            n = len(self.entry.get("apps", []))
            p.drawText(QRect(18, 10, self.width() - 36, 24),
                       Qt.AlignLeft | Qt.AlignVCenter, "文件夹 · %d 个项目" % n)

    def focusOutEvent(self, e):
        if not self._dragging:
            self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()

    def closeEvent(self, e):
        self.closed.emit()
        super().closeEvent(e)
