# -*- coding: utf-8 -*-
"""液态玻璃文件夹弹窗：背后内容实时模糊 + tint + 边缘高光（苹果 Liquid Glass 风）。

UI 对标 iOS 文件夹 + Liquid Glass 材质语言（2026-10-18 重做）：
  - 大网格：成员最多 4 列铺开（旧版 2 列窄条被用户反馈"展开 UI 完全不对"）
  - 标题居中（iOS 文件夹标题居中；vibrancy：材质上加字重+微字距）
  - 液态玻璃大圆角背板 + 右上角自绘 × 关闭按钮
  - 成员图标错峰淡入

层级与动效：
  - 挂桌面带（Progman 上方、整理窗口正上方一位）：**不用
    WindowStaysOnTopHint**——那会盖住所有应用程序窗口（用户截图里
    黑弹窗压住桌面中央的根源）。作为桌面的一部分，打开应用时被盖住
    是正确行为。
  - NOACTIVATE：点击/拖动照常接收（NOACTIVATE 只禁激活），但永不抢焦点
  - 打开：玻璃表面从锚点图标位置"涌出"（缩放 0.62->1.0，欠阻尼弹簧
    0.8 = 液态 wobble）+ 淡入；窗口尺寸全程不变——不动 geometry 动画，
    避免 setFixedSize 钳制起点 / 子控件不随窗口缩放等一系列坑
  - 关闭：反向（缩放收 0.55 + 淡出）后才真正 close；临界阻尼、防重入
  - 关闭方式：× 按钮 / 点击桌面空白处（DesktopWindow.mousePressEvent）
    / 再次点击文件夹图标。NOACTIVATE 窗口收不到键盘焦点，故不用 Esc

液态玻璃实现说明（为什么不用 acrylic API）：
  SetWindowCompositionAttribute 的 ACCENT_ENABLE_ACRYLICBLURBEHIND 与
  Qt 的 WA_TranslucentBackground + WS_EX_LAYERED 组合冲突（acrylic 不显示）。
  改为 show() 前抓屏 -> C++ 层高斯模糊 -> paintEvent 自绘，跨 Win10/Win11
  稳定，观感完全可控。桌面场景背后基本静态，一次性抓取完全够用。
"""
import traceback

from PySide6.QtCore import (QParallelAnimationGroup, QPointF, QPropertyAnimation,
                            QRect, QRectF, Qt, Signal, QEasingCurve, Property)
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen, QPixmap
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
        # 桌面带成员：不置顶（不盖应用窗口）、不激活（不抢焦点）。
        # 挂载由 DesktopWindow.open_folder 在 show() 之后调用
        # attach_to_desktop(popup, below_hwnd=主窗口) 完成。
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._build(anchor_rect)
        self._open_animate()

    # ---------- 布局 ----------
    def _build(self, anchor_rect, keep_backdrop=False):
        for child in self.findChildren(AppIcon):
            child.deleteLater()
        # 成员部件全部销毁：飞行中的成员拖拽已死亡，标志位一并复位。
        # 否则 _dragging 卡死会让 focusOutEvent 再也无法自动收起弹窗
        # （拖源被删 -> dragFinished 送不达 -> _on_drag_finish 不执行）。
        self._dragging = False
        # DPI × 用户缩放感知：弹窗成员与桌面网格同大小（旧值 -18 显小，
        # 2026-10-18 用户反馈"展开 UI 完全不对"——iOS 文件夹成员图标
        # 占满格子，不做小一档处理）
        icon_size = max(56, self.storage.icon_metric())
        m = self.storage.icon_chrome_scale()
        members = self.entry.get("apps", [])
        # iOS 文件夹网格：1~2 个成员 2 列（不稀拉）；3 个及以上 4 列
        # （旧版 min(4, max(2, (n+1)//2)) 让 4 个成员排成 2x2，被用户
        # 反馈"展开 UI 完全不对"——iOS 是单行 4 列起步）
        n = len(members)
        cols = 2 if n <= 2 else 4
        rows = max(1, (len(members) + cols - 1) // cols)
        pitch_x = icon_size + int(round(22 * m))
        pitch_y = icon_size + int(round(44 * m))
        pad, title_h = int(round(16 * m)), int(round(36 * m))
        w = pad * 2 + (cols - 1) * pitch_x + icon_size
        h = pad + title_h + (rows - 1) * pitch_y + (icon_size + int(round(42 * m))) + pad - int(round(8 * m))
        # 高度不超过可用屏幕的 82%：桌面文件全拖进来的极端情况不顶出屏幕
        screen = QGuiApplication.screenAt(anchor_rect.center()) if anchor_rect else None
        screen = screen or QGuiApplication.primaryScreen()
        max_h = int(screen.availableGeometry().height() * 0.82)
        self.setFixedSize(max(240, w), min(max(150, h), max_h))
        if anchor_rect is not None:
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
            icon = AppIcon(entry, icon_size, in_folder=True, parent=self,
                           chrome_scale=m)
            icon.drag_payload = member_payload
            icon.dragStarted.connect(self._on_drag_start)
            icon.dragFinished.connect(self._on_drag_finish)
            icon.activated.connect(self.launchApp.emit)
            icon.removeFromFolder.connect(self.removeMember.emit)
            icon.move(pad + (i % cols) * pitch_x, pad + title_h + (i // cols) * pitch_y)
            # 弹窗内图标错峰淡入（玻璃涌出后依次浮现）
            icon.appear_in(120 + i * 45)
            icon.show()

    # ---------- 开合动效 ----------
    def _open_animate(self):
        """液态涌现：背板从图标位置缩放着陆 + 淡入。

        曲线按苹果 Fluid Interfaces 规范取值（真弹簧，见 effects.spring_curve）：
          - sheet 档弹窗 = 欠阻尼弹簧（damping 0.8，一次极小衰减过冲
            ≈ Motion bounce 0.2），duration 380ms 为稳定时间——可见
            运动集中在前期，尾部 30% 是不可见的收敛尾（iOS 弹簧语义）
          - 过冲刻意保持 ~0.7%：玻璃表面缩放 >1 会被窗口边界裁切圆角，
            wobble 幅度以不露裁切痕迹为上限（图标无此约束，可用 0.62）
          - 系统关闭动画效果时（reduced-motion 等价）dur() 自动压减时长
        """
        self.setWindowOpacity(0.0)
        self._zoom = ZOOM_FROM
        group = QParallelAnimationGroup(self)
        opa = QPropertyAnimation(self, b"windowOpacity", self)
        opa.setDuration(effects.dur(180))
        opa.setStartValue(0.0)
        opa.setEndValue(1.0)
        opa.setEasingCurve(QEasingCurve.OutCubic)
        zoom = QPropertyAnimation(self, b"zoom", self)
        zoom.setDuration(effects.dur(380))
        zoom.setStartValue(float(ZOOM_FROM))
        zoom.setEndValue(1.0)
        zoom.setEasingCurve(effects.spring_curve(0.8, 380))
        group.addAnimation(opa)
        group.addAnimation(zoom)
        group.start()
        self._open_anim = group  # 持有引用，避免被 GC
        self.show()

    def close(self):
        """反向收起（缩放 + 淡出）后才真正关闭；动画期间防重入。
        进出场同路径：都绕锚点图标中心收放；收起用临界阻尼（关场不带
        弹性——苹果规范里只有带动量的开场才弹）。"""
        if self._closing:
            return
        self._closing = True
        group = QParallelAnimationGroup(self)
        opa = QPropertyAnimation(self, b"windowOpacity", self)
        opa.setDuration(effects.dur(180))
        opa.setStartValue(float(self.windowOpacity()))
        opa.setEndValue(0.0)
        opa.setEasingCurve(QEasingCurve.InCubic)
        zoom = QPropertyAnimation(self, b"zoom", self)
        zoom.setDuration(effects.dur(200))
        zoom.setStartValue(float(self._zoom))
        zoom.setEndValue(float(ZOOM_TO))
        zoom.setEasingCurve(effects.spring_curve(1.0, 200))
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

    def _close_rect(self):
        s = max(20, int(round(24 * self.storage.icon_chrome_scale())))
        return QRect(self.width() - s - 10, 10, s, s)

    def mousePressEvent(self, e):
        # NOACTIVATE 窗口收不到键盘焦点，Esc 不可用；提供右上角 × 明确关闭
        if e.button() == Qt.LeftButton and self._close_rect().contains(e.pos()):
            self.close()

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
        # 稍加字重、微加字距（不用平灰）。iOS 文件夹标题居中。
        if z > 0.55:
            p.setOpacity(min(1.0, (z - 0.55) / 0.35))
            p.setPen(theme.TEXT)
            f = theme.ui_font(15, bold=True)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 0.3)
            p.setFont(f)
            n = len(self.entry.get("apps", []))
            p.drawText(QRect(10, 9, self.width() - 20, 26),
                       Qt.AlignHCenter | Qt.AlignVCenter,
                       "文件夹 · %d 个项目" % n)
            # 右上角 ×（自绘十字：比"×"字符字形更居中精致）
            r = self._close_rect()
            hovered = self._close_hover
            if hovered:
                p.setBrush(QColor(255, 255, 255, 30))
                p.setPen(Qt.NoPen)
                p.drawEllipse(r)
            p.setPen(QPen(theme.TEXT_DIM, 1.5, Qt.SolidLine, Qt.RoundCap))
            cx, cy = r.center().x(), r.center().y()
            d = r.width() * 0.24
            p.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
            p.drawLine(QPointF(cx + d, cy - d), QPointF(cx - d, cy + d))

    def mouseMoveEvent(self, e):
        r = self._close_rect()
        h = r.contains(e.pos())
        if h != self._close_hover:
            self._close_hover = h
            self.update()
        if h:
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.unsetCursor()

    _close_hover = False

    def focusOutEvent(self, e):
        # NOACTIVATE 窗口通常不会获得焦点，此回调多为兜底；
        # 主动关闭路径见 DesktopWindow 空白点击 / × 按钮。
        if not self._dragging:
            self.close()

    def closeEvent(self, e):
        self.closed.emit()
        super().closeEvent(e)
