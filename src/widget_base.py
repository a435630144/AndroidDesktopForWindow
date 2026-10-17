# -*- coding: utf-8 -*-
"""桌面小组件基类：无边框半透明卡片，挂载到桌面层（壁纸之上、应用窗口之下），
可拖动、可缩放、可关闭，几何自动持久化。

两种形态（entry["anchored"]）：
  - 悬浮（默认， anchored=False）：满幅不透明卡片 + × / 缩放手柄，自由拖动。
    视觉上是一张浮在桌面上的卡片。
  - 锚定（anchored=True）：「非悬浮」模式——只画内容区（低透明度 tint、
    无描边、无 chrome），卡片外的透明像素自动把点击穿透给真实桌面；
    松手吸附到图标网格；一律 NOACTIVATE 不抢焦点。视觉上长在桌面上，
    与手机桌面 widget 同语言（design.md 3.2）。

动效（2026-10-18 补齐，苹果 Fluid Interfaces 规范）：
  - 进场：淡入（windowOpacity 0->1，临界阻尼弹簧 180ms）——不缩放：
    对任意子控件做渲染缩放需要 QGraphicsEffect，会连内容一起劣化，
    桌面场景不值得；透明度是零成本且零风险的浮层进场语言
  - 退场：淡出（140ms InCubic）后才真正 close，进出场同路径
  - 拖动提拉：按下拖动期间 windowOpacity 0.94（"按下即反馈、反馈在
    手势全程连续"的桌面版），松手弹簧淡回 1.0
  - 锚定吸附：松手后弹簧滑到网格格点（grid_flow.snap_point）
"""
from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from . import effects
from . import grid_flow
from . import theme
from .win32_layer import attach_to_desktop


class FloatingWidget(QWidget):
    closed = Signal(str)  # widget id
    gridChanged = Signal()  # 锚定占位变化（落定 / 尺寸变化）：通知 DesktopWindow 挤走图标

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
        self._anims = []      # 持有透明度动画引用，防 GC
        self._closing = False  # 退场动画防重入
        self._snapping = False  # 吸附动画中：不再响应拖动
        # 注意：不能用 WindowStaysOnTopHint，否则会盖在所有应用程序窗口之上；
        # 正确做法是挂载到桌面带（Progman 正上方），与整理窗口处于同一层级。
        flags = Qt.FramelessWindowHint | Qt.Tool
        if not interactive or self.anchored:
            # WindowDoesNotAcceptFocus(WS_EX_NOACTIVATE)：永不被激活，
            # 因此永远不会抢到应用窗口前面（"时钟组件被置顶"Bug 的根治）。
            # 纯展示型组件与锚定组件一律用它；锚定组件即便内容可交互
            # （如便签）也不抢焦点——它是桌面的一部分，不是窗口。
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

    # ---------- 形态 ----------
    @property
    def anchored(self) -> bool:
        """锚定（非悬浮）模式：无 chrome、低 tint、点击穿透、网格吸附。"""
        return bool(self.entry.get("anchored", False))

    def showEvent(self, e):
        super().showEvent(e)
        # 挂载到桌面带（Progman 正上方）：失败则保持普通无边框窗口（不置顶）。
        # 每次重新显示都重新插入：隐藏再显示后 Windows 可能已改变 z-order。
        self.attached = attach_to_desktop(self)
        # 进场淡入（开机 / 托盘再次显示都走这里；苹果进出场同路径）
        if not self._closing:
            self.setWindowOpacity(0.0)
            self._fade(0.0, 1.0, 180)

    # ---------- 透明度动画（进场 / 退场 / 拖动提拉共用） ----------
    def _fade(self, start: float, end: float, ms: int,
              easing=None, done=None):
        for a in list(self._anims):
            a.stop()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(effects.dur(ms))
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        anim.setEasingCurve(easing if easing is not None
                            else effects.spring_curve(1.0, ms))
        if done is not None:
            anim.finished.connect(done)
        anim.finished.connect(lambda: self._anims.remove(anim)
                              if anim in self._anims else None)
        self._anims.append(anim)
        anim.start()
        return anim

    def close(self):
        """淡出后才真正关闭（进出场同路径）；动画期间防重入。"""
        if self._closing:
            return
        self._closing = True
        self._fade(float(self.windowOpacity()), 0.0, 140,
                   QEasingCurve.InCubic, done=self._really_close)

    def _really_close(self):
        super().close()

    # ---------- 几何持久化 ----------
    def _save_geom(self):
        g = self.geometry()
        self.entry["x"] = g.x()
        self.entry["y"] = g.y()
        self.entry["w"] = g.width()
        self.entry["h"] = g.height()
        self.storage.save()

    def _close_rect(self):
        if self.anchored:
            return QRect()          # 锚定模式无 chrome
        # 24x24：HIG 最小点击目标 28 以下的桌面允许值，比旧的 20x20 好按
        return QRect(self.width() - 30, 6, 24, 24)

    def _grip_rect(self):
        if self.anchored:
            return QRect()          # 锚定模式不允许缩放手柄
        return QRect(self.width() - 22, self.height() - 22, 20, 20)

    # ---------- 绘制 ----------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.anchored:
            # 锚定（非悬浮）：只铺一层低透明度 tint，无描边、无 chrome。
            # 卡片之外的像素保持全透明 -> 分层窗口的逐像素命中测试天然
            # 把点击穿透给真实桌面（design.md 3.2「融入桌面」）。
            tint = QColor(theme.SURFACE)
            tint.setAlphaF(0.34)
            p.setBrush(tint)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(self.rect(), theme.RADIUS_PANEL, theme.RADIUS_PANEL)
            return
        p.setBrush(theme.SURFACE)
        p.setPen(theme.BORDER)
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), theme.RADIUS_PANEL, theme.RADIUS_PANEL)
        # 关闭按钮：自绘十字（"×"字符字形偏高偏小，自绘双斜线更居中精致）
        r = self._close_rect()
        hovered = self._mouse_pos is not None and r.contains(self._mouse_pos)
        if hovered:
            p.setBrush(theme.DANGER)
            p.setPen(Qt.NoPen)
            p.drawEllipse(r)
        p.setPen(QPen(QColor(255, 255, 255) if hovered else theme.TEXT_DIM,
                      1.5, Qt.SolidLine, Qt.RoundCap))
        cx, cy = r.center().x(), r.center().y()
        d = r.width() * 0.22
        p.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
        p.drawLine(QPointF(cx + d, cy - d), QPointF(cx - d, cy + d))
        # 缩放手柄（右下角斜纹）
        g = self._grip_rect()
        p.setPen(QColor(255, 255, 255, 90))
        for i in range(3):
            p.drawLine(g.left() + 3, g.bottom() - 3 - i * 5,
                       g.right() - 3 - i * 5, g.bottom() - 3)

    # ---------- 锚定吸附 ----------
    def _snap_to_grid(self):
        """松手后弹簧吸附到图标网格格点（与整理窗口同一套几何定义）。"""
        if not self.anchored or self._snapping:
            return
        screen = QApplication.primaryScreen().availableGeometry()
        tx, ty = grid_flow.snap_point(self.storage, self.x(), self.y(),
                                      (screen.width(), screen.height()))
        if (tx, ty) == (self.x(), self.y()):
            return
        self._snapping = True
        for a in list(self._anims):
            a.stop()
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(effects.dur(240))
        anim.setStartValue(self.pos())
        anim.setEndValue(QPoint(tx, ty))
        anim.setEasingCurve(effects.spring_curve(0.8, 240))
        anim.finished.connect(self._on_snapped)
        self._anims.append(anim)
        anim.start()

    def _on_snapped(self):
        self._snapping = False
        if self.anchored:
            self._sync_grid_occupancy()
        self._save_geom()

    def _sync_grid_occupancy(self):
        """吸附落定后把占位（col/row/colspan/rowspan）写进 entry。

        小组件由此成为网格一等公民：DesktopWindow 读 storage.widgets
        计算占位格，图标让位/新增都避开这些格；本 widget 移动后
        gridChanged 触发一次 displace，把被占区域的图标挤走。
        """
        cw, ch = grid_flow.cell_size(self.storage)
        ox, oy = grid_flow.origin()
        col = max(0, int(round((self.x() - ox) / max(1, cw))))
        row = max(0, int(round((self.y() - oy) / max(1, ch))))
        cs, rs = grid_flow.widget_span(self.storage, self.entry)
        changed = ((self.entry.get("col"), self.entry.get("row"),
                    self.entry.get("colspan"), self.entry.get("rowspan"))
                   != (col, row, cs, rs))
        self.entry["col"], self.entry["row"] = col, row
        self.entry["colspan"], self.entry["rowspan"] = cs, rs
        self.storage.save()
        if changed:
            self.gridChanged.emit()

    # ---------- 鼠标 ----------
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if not self.anchored and self._close_rect().contains(e.pos()):
            self.entry["hidden"] = True
            self.storage.save()
            self.closed.emit(self.entry.get("id", ""))
            self.close()
            return
        if not self.anchored and self._grip_rect().contains(e.pos()):
            self._resizing = True
            self._resize_origin = e.globalPosition().toPoint()
            self._start_geom = self.geometry()
            return
        self._drag_off = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        # 打断进行中的吸附动画：用户再次按下就是要重新拖，
        # 否则 _snapping 防重入会把第二次吸附整个吞掉（probe15 G8 抓到）
        for a in list(self._anims):
            if a.propertyName() == b"pos":
                a.stop()
                self._anims.remove(a)
        self._snapping = False
        # 拖动提拉：轻微淡化（按下即反馈，全程连续；松手在 release 里回弹）
        for a in list(self._anims):
            if a.propertyName() != b"pos":   # 别打断吸附动画
                a.stop()
        self.setWindowOpacity(0.94)

    def mouseMoveEvent(self, e):
        self._mouse_pos = e.pos()
        if self._resizing:
            delta = e.globalPosition().toPoint() - self._resize_origin
            w = max(self.minimumWidth(), self._start_geom.width() + delta.x())
            h = max(self.minimumHeight(), self._start_geom.height() + delta.y())
            self.resize(w, h)
        elif self._drag_off is not None:
            self.move(e.globalPosition().toPoint() - self._drag_off)
        elif not self.anchored and (self._close_rect().contains(e.pos())
                                    or self._grip_rect().contains(e.pos())):
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.unsetCursor()
        self.update()

    def mouseReleaseEvent(self, e):
        if self._resizing or self._drag_off is not None:
            if self._drag_off is not None and not self._closing:
                # 松手回弹：临界阻尼弹簧淡回（无动量不过冲）
                self._fade(float(self.windowOpacity()), 1.0, 180)
                self._snap_to_grid()
            else:
                self._save_geom()
        self._resizing = False
        self._drag_off = None

    # ---------- 右键菜单 ----------
    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.setStyleSheet(theme.MENU_QSS)
        if self.anchored:
            menu.addAction("切换为自由悬浮", self._toggle_anchored)
        else:
            menu.addAction("锚定到桌面（融入壁纸）", self._toggle_anchored)
        menu.addAction("隐藏", self._hide_self)
        menu.addAction("关闭", self._close_self)
        menu.exec(e.globalPos())

    def _toggle_anchored(self):
        """锚定 <-> 悬浮：窗口标志位（NOACTIVATE）与绘制分支都要变，只能重建。
        发 closed 让 WidgetLayer 重 spawn（entry 未 hidden，见 _on_closed）。
        切换时清掉占位字段：下次锚定由 WidgetLayer 重新找空格分配。"""
        self.entry["anchored"] = not self.anchored
        for k in ("col", "row", "colspan", "rowspan"):
            self.entry.pop(k, None)
        self.storage.save()
        self.closed.emit(self.entry.get("id", ""))
        self.close()

    def _hide_self(self):
        self.entry["hidden"] = True
        self.storage.save()
        self.closed.emit(self.entry.get("id", ""))
        self.close()

    def _close_self(self):
        self.closed.emit(self.entry.get("id", ""))
        self.close()
