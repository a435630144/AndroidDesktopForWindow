# -*- coding: utf-8 -*-
"""可拖拽的桌面图标控件（网格与文件夹弹窗共用）——腾讯桌面整理深色风格。

视觉：
  - 图标 + 下方两行白字标签（带阴影，任意壁纸可读）
  - 悬停：圆角浅色高亮；选中：蓝色浅底 + 蓝色描边
  - 文件夹：深色半透明圆角方形 + 2x2 迷你图标（1/2/3/4 成员自适应布局）

交互：
  - 左键按下移动超过系统拖拽阈值 -> 系统级拖拽（QDrag）
  - 拖到另一个图标上            -> mergeRequested（创建 / 合并文件夹）
  - 拖到窗口空白处              -> 由主窗口移动到目标网格
  - 文件夹内图标拖出            -> payload 形如 "M:fid:idx"
  - 单击        -> 选中（clicked）；双击 -> 打开
  - 右键        -> 打开 / 在文件夹中显示 / 移出文件夹 / 解散 / 移除

动效（苹果 HIG / Fluid Interfaces 规范，见 src/effects.py）：
  - 按下 scale(0.96) 100ms ease-out（pointer-down 即反馈，不等松手）
  - 松开临界阻尼回弹（无动量不过冲；带动量的拖动落位才配 OutBack 弹跳）
  - 悬停 1.04 轻放大；拖动提拉 1.06
  - 双击/打开文件夹脉冲（1.12 放大回落）
  - rebuild 错峰淡入（stagger，每个间隔 30ms）
  - 系统关闭动画效果时（prefers-reduced-motion 等价）自动降级为短淡入
"""
from PySide6.QtCore import (QEasingCurve, QMimeData, QPoint, QPropertyAnimation,
                            QRect, QRectF, QSize, Qt, Signal, Property, QTimer)
from PySide6.QtGui import QColor, QDrag, QFontMetrics, QPen, QPixmap, QPainter
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from . import appsource
from . import effects
from . import theme

MIME_TYPE = "application/x-desktoporg-item"


class AppIcon(QWidget):
    activated = Signal(dict)            # 双击启动
    clicked = Signal(str)               # 单击选中（entry id）
    folderClicked = Signal(str)         # 单击文件夹（entry id）
    mergeRequested = Signal(str, str)   # 拖拽合并：dragged_payload, target_entry_id
    removeRequested = Signal(str)       # 右键移除（entry id）
    removeFromFolder = Signal(str)      # 文件夹内右键移出（payload "M:fid:idx"）
    dissolveRequested = Signal(str)     # 解散文件夹（entry id）
    openLocation = Signal(dict)         # 在资源管理器中定位（桌面文件）
    dragStarted = Signal()
    dragFinished = Signal()

    def __init__(self, entry: dict, icon_size: int, in_folder: bool = False, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.icon_size = icon_size
        self.in_folder = in_folder
        self.selected = False
        self.drag_payload = entry.get("id", "")
        self.payload_provider = None  # 多选拖拽时由主窗口注入，返回逗号分隔的 id 列表
        self._press_pos = None
        self._dragged = False
        self._hover = False
        self._merge_target = False
        # 动效状态（三个独立属性，动画互不冲突；paintEvent 相乘）
        self._hover_scale = 1.0    # 悬停轻放大
        self._press_scale = 1.0    # 按压 / 拖动提拉 / 脉冲
        self._appear = 1.0         # 错峰淡入进度（rebuild stagger）
        self._anims = []           # 持有动画引用，防 GC
        self.setFixedSize(icon_size + 28, icon_size + 46)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(self._tooltip())

    # ---------- 动效属性（QPropertyAnimation 直接驱动） ----------
    def _get_hover_scale(self):
        return self._hover_scale

    def _set_hover_scale(self, v):
        if v != self._hover_scale:
            self._hover_scale = v
            self.update()

    def _get_press_scale(self):
        return self._press_scale

    def _set_press_scale(self, v):
        if v != self._press_scale:
            self._press_scale = v
            self.update()

    def _get_appear(self):
        return self._appear

    def _set_appear(self, v):
        if v != self._appear:
            self._appear = v
            self.update()

    hover_scale = Property(float, _get_hover_scale, _set_hover_scale)
    press_scale = Property(float, _get_press_scale, _set_press_scale)
    appear = Property(float, _get_appear, _set_appear)

    def _animate(self, prop, start, end, duration, easing=None):
        """启动属性动画（自动停止同属性上的旧动画并持有引用防 GC）。"""
        for a in list(self._anims):
            if a.propertyName() == prop:
                a.stop()
                self._anims.remove(a)
        anim = QPropertyAnimation(self, prop, self)
        anim.setDuration(effects.dur(duration))
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(easing if easing is not None else effects.smooth_out())
        anim.finished.connect(lambda: self._anims.remove(anim)
                              if anim in self._anims else None)
        self._anims.append(anim)
        anim.start()
        return anim

    def pulse(self, scale=1.12, duration=320):
        """启动 / 打开反馈脉冲：放大后回落（关键帧动画）。"""
        for a in list(self._anims):
            if a.propertyName() == b"press_scale":
                a.stop()
                self._anims.remove(a)
        anim = QPropertyAnimation(self, b"press_scale", self)
        anim.setDuration(effects.dur(duration))
        anim.setKeyValueAt(0.0, self._press_scale)
        anim.setKeyValueAt(0.35, scale)
        anim.setKeyValueAt(1.0, 1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: self._anims.remove(anim)
                              if anim in self._anims else None)
        self._anims.append(anim)
        anim.start()

    def appear_in(self, delay_ms=0):
        """错峰淡入（rebuild 后 iOS 风依次落位）：缩放 0.7->1 + 渐显。
        系统关闭动画效果时退化为立即显示（不占 30ms/个的节奏）。"""
        self._appear = 0.0
        self.update()
        delay = 0 if effects.reduced_motion() else max(0, delay_ms)
        QTimer.singleShot(delay, self._play_appear)

    def _play_appear(self):
        if self._appear >= 1.0:
            return
        self._animate(b"appear", 0.0, 1.0, 220)

    # ---------- 属性 ----------
    @property
    def is_folder(self) -> bool:
        return self.entry.get("type") == "folder"

    @property
    def is_file(self) -> bool:
        return self.entry.get("app", {}).get("kind") == "file"

    def _display_name(self) -> str:
        if self.is_folder:
            return "文件夹"
        return self.entry.get("app", {}).get("name", "")

    def _tooltip(self) -> str:
        if self.is_folder:
            names = "、".join(a.get("name", "") for a in self.entry.get("apps", [])[:8])
            return "文件夹：%s" % names
        app = self.entry.get("app", {})
        target = app.get("target", "")
        return "%s\n%s" % (app.get("name", ""), target) if target else app.get("name", "")

    def set_selected(self, on: bool):
        if self.selected != on:
            self.selected = on
            self.update()

    # ---------- 绘制 ----------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        dpr = self.devicePixelRatioF()

        # 动效缩放：按压 x 悬停 x 错峰淡入（以图标视觉中心为原点，
        # widget geometry 不变——命中测试 / 框选判定完全不受影响）
        s = self._hover_scale * self._press_scale * self._appear
        if abs(s - 1.0) > 0.002 or self._appear < 0.995:
            cy = 2 + self.icon_size / 2.0
            p.translate(w / 2.0, cy)
            p.scale(s, s)
            p.translate(-w / 2.0, -cy)
        if self._appear < 0.995:
            p.setOpacity(self._appear)

        # 背景状态：悬停 / 合并目标 / 选中
        if self._merge_target:
            p.setPen(QPen(theme.ACCENT_BORDER, 1.5))
            p.setBrush(theme.ACCENT_SOFT)
            p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), theme.RADIUS_ITEM, theme.RADIUS_ITEM)
        elif self.selected:
            p.setPen(QPen(theme.ACCENT_BORDER, 1))
            p.setBrush(theme.ACCENT_SOFT)
            p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), theme.RADIUS_ITEM, theme.RADIUS_ITEM)
        elif self._hover:
            p.setPen(QPen(theme.HOVER_BORDER, 1))
            p.setBrush(theme.HOVER)
            p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), theme.RADIUS_ITEM, theme.RADIUS_ITEM)

        if self.is_folder:
            self._paint_folder(p, dpr)
        else:
            app = self.entry.get("app", {})
            # 高清 pixmap：逻辑尺寸=icon_size（DPR 感知），按逻辑宽度居中，
            # 绝不能用 pm.width()（物理像素）算偏移——那是图标错位/变虚的根因
            pm = appsource.icon_pixmap(app, self.icon_size, dpr)
            p.drawPixmap((w - self.icon_size) // 2, 2, pm)

        self._paint_label(p)

    def _paint_folder(self, p: QPainter, dpr: float = 1.0):
        """深色圆角方形 + 迷你图标矩阵（安卓风，按成员数 1/2/3/4 自适应）。"""
        s = self.icon_size
        box = QRectF(3, 3, s - 6, s - 6)
        p.setPen(QPen(theme.FOLDER_BORDER, 1))
        p.setBrush(theme.FOLDER_BG)
        p.drawRoundedRect(box, s * 0.24, s * 0.24)
        members = self.entry.get("apps", [])
        n = len(members)
        if n <= 1:
            slots = [(0.50, 0.50, 0.52)]
        elif n == 2:
            slots = [(0.28, 0.50, 0.36), (0.72, 0.50, 0.36)]
        elif n == 3:
            slots = [(0.50, 0.27, 0.32), (0.27, 0.73, 0.32), (0.73, 0.73, 0.32)]
        else:
            slots = [(0.28, 0.28, 0.32), (0.72, 0.28, 0.32), (0.28, 0.72, 0.32), (0.72, 0.72, 0.32)]
        for (fx, fy, fr), app in zip(slots, members[:4]):
            cs = max(8, int(s * fr))
            pm = appsource.icon_pixmap(app, cs, dpr)
            cx = 3 + fx * (s - 6) - cs / 2
            cy = 3 + fy * (s - 6) - cs / 2
            p.drawPixmap(int(cx), int(cy), pm)

    def _paint_label(self, p: QPainter):
        name = self._display_name()
        if not name:
            return
        font = theme.ui_font(11)
        p.setFont(font)
        rect = QRect(2, self.icon_size + 8, self.width() - 4, 34)
        fm = QFontMetrics(font)
        lines = self._wrap_elide(name, fm, rect.width(), 2)
        lh = fm.height() + 1
        # 阴影一层 + 白字，保证任意壁纸下可读
        for i, line in enumerate(lines):
            r = QRect(rect.left(), rect.top() + i * lh, rect.width(), lh)
            p.setPen(theme.LABEL_SHADOW)
            p.drawText(r.adjusted(1, 1, 0, 0), Qt.AlignCenter, line)
            p.setPen(theme.LABEL_COLOR)
            p.drawText(r, Qt.AlignCenter, line)

    @staticmethod
    def _wrap_elide(name: str, fm: QFontMetrics, width: int, max_lines: int) -> list:
        """按像素宽度折行，超过 max_lines 时末行省略号。"""
        words = name.split(" ")
        lines, cur = [], ""
        for w_ in words:
            trial = (cur + " " + w_).strip()
            if fm.horizontalAdvance(trial) <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w_
        if cur:
            lines.append(cur)
        if len(lines) > max_lines:
            kept = lines[:max_lines]
            kept[-1] = fm.elidedText(kept[-1], Qt.ElideRight, width)
            return kept
        return [fm.elidedText(l, Qt.ElideRight, width) for l in lines]

    # ---------- 鼠标 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_pos = e.pos()
            self._dragged = False
            # 苹果 HIG 按压反馈：scale(0.97) 100ms ease-out，pointer-down
            # 即触发不等松手（按下即反馈，消灭延迟）
            self._animate(b"press_scale", self._press_scale, 0.96, 100,
                          QEasingCurve.OutCubic)

    def mouseMoveEvent(self, e):
        if self._press_pos is None or not (e.buttons() & Qt.LeftButton):
            return
        if (e.pos() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            return
        self._dragged = True
        self.dragStarted.emit()
        self._exec_drag()

    def _exec_drag(self):
        payload = self.drag_payload
        if self.payload_provider is not None:
            try:
                payload = self.payload_provider(self.drag_payload) or payload
            except Exception:
                pass
        # 提拉感：拖动源放大 1.06。QDrag.exec() 是嵌套事件循环且阻塞
        # Qt 定时器，动画不驱动，直接置位 + update。
        self._set_press_scale(1.06)
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_TYPE, payload.encode())
        drag.setMimeData(mime)
        pm = QPixmap(self.size())
        pm.fill(Qt.transparent)
        self.render(pm)
        drag.setPixmap(pm)
        drag.setHotSpot(self._press_pos or QPoint(1, 1))
        drag.exec(Qt.MoveAction)
        try:
            self.dragFinished.emit()
            self._press_pos = None
            # 落位回弹（弹簧过冲）
            self._animate(b"press_scale", 1.06, 1.0, 240,
                          QEasingCurve.OutBack)
        except RuntimeError:
            # 拖动嵌套循环期间本部件已被删除/重建（drop -> rebuild() 的
            # deleteLater、FolderPopup 关闭等），信号源 C++ 对象已不存在。
            # 必须吞掉：异常会冲掉 dragFinished 信号 -> DesktopWindow
            # _on_drag_finished 不执行 -> _drag_active 永久卡死 ->
            # nativeEvent 全窗口 HTCLIENT，桌面点击全部失效。
            pass

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._press_pos is not None and not self._dragged:
            if self.is_folder:
                self.pulse(1.14, 340)   # 打开文件夹：脉冲反馈
                self.folderClicked.emit(self.entry["id"])
            else:
                self.clicked.emit(self.entry["id"])
            # 松开回弹：点按无动量，按苹果规范用临界阻尼（无过冲）；
            # 只有带动量的手势（拖动落位）才配弹跳
            self._animate(b"press_scale", self._press_scale, 1.0, 200,
                          QEasingCurve.OutCubic)
        elif e.button() == Qt.LeftButton and self._press_pos is not None:
            # 未形成点击的抬起（如拖拽被取消）：平滑归位
            self._animate(b"press_scale", self._press_scale, 1.0, 160)
        self._press_pos = None

    def mouseDoubleClickEvent(self, e):
        if self.is_folder:
            self.pulse(1.14, 340)
            self.folderClicked.emit(self.entry["id"])
        else:
            self.pulse()   # 启动反馈脉冲
            self.activated.emit(self.entry.get("app", {}))

    def enterEvent(self, e):
        self._hover = True
        # 悬停轻放大 1.04
        self._animate(b"hover_scale", self._hover_scale, 1.04, 120)
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self._animate(b"hover_scale", self._hover_scale, 1.0, 140)
        self.update()

    # ---------- 拖放接收 ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_TYPE):
            dragged = e.mimeData().data(MIME_TYPE).data().decode()
            if dragged not in (self.drag_payload, self.entry.get("id")):
                e.acceptProposedAction()
                self._merge_target = True
                self.update()

    def dragLeaveEvent(self, e):
        if self._merge_target:
            self._merge_target = False
            self.update()

    def dropEvent(self, e):
        if self._merge_target:
            self._merge_target = False
            self.update()
        dragged = e.mimeData().data(MIME_TYPE).data().decode()
        if dragged in (self.drag_payload, self.entry.get("id")):
            return
        if self.in_folder:
            return  # 文件夹内部不互相合并
        e.acceptProposedAction()
        self.mergeRequested.emit(dragged, self.entry["id"])

    # ---------- 右键菜单 ----------
    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.setStyleSheet(theme.MENU_QSS)
        if self.in_folder:
            menu.addAction("打开", self._open)
            menu.addAction("移出文件夹", self._remove_from_folder)
        elif self.is_folder:
            menu.addAction("打开", self._open_folder)
            menu.addAction("解散文件夹", self._dissolve)
            menu.addAction("从整理桌面移除", self._remove_self)
        elif self.is_file:
            menu.addAction("打开", self._open)
            menu.addAction("在文件夹中显示", self._reveal)
            menu.addAction("从整理桌面移除", self._remove_self)
        else:
            menu.addAction("打开", self._open)
            menu.addAction("从整理桌面移除", self._remove_self)
        menu.exec(e.globalPos())

    def _open(self):
        if not self.is_folder:
            self.activated.emit(self.entry.get("app", {}))

    def _reveal(self):
        self.openLocation.emit(self.entry.get("app", {}))

    def _open_folder(self):
        self.folderClicked.emit(self.entry["id"])

    def _dissolve(self):
        self.dissolveRequested.emit(self.entry["id"])

    def _remove_self(self):
        self.removeRequested.emit(self.entry["id"])

    def _remove_from_folder(self):
        self.removeFromFolder.emit(self.drag_payload)
