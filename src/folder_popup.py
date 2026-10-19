# -*- coding: utf-8 -*-
"""液态玻璃文件夹弹窗 + 幕布 + 行内输入框（2026-10-18 M5 重做，指导文档 §4）。

UI 对标 iOS 文件夹 + Liquid Glass 材质语言：
  - 大网格：成员最多 4 列铺开（单行 4 列起步）
  - 标题居中（点按 → 行内重命名，BandInputBox）；vibrancy：材质上加
    字重 + 微字距
  - 液态玻璃大圆角背板 + 右上角自绘 × 关闭按钮
  - 底部工具条：「＋ 添加图标」「颜色」两个 pill 按钮
  - 背景色板：8 预设 + 「自动」（成员图标平均色，folder_tint.auto_tint）；
    图标渐变与弹窗背板共用同一颜色（iOS 文件夹语言）
  - ＋ 添加面板：桌面条目网格（排除已有成员），点选即加入；
    也支持把桌面图标直接拖到弹窗上加入（dragEnter 识别 payload）
  - 空文件夹态：「空文件夹」+ 提示「从桌面拖入或点 ＋ 添加」

层级与动效：
  - 挂桌面带（Progman 上方、应用窗口之下）：**不用
    WindowStaysOnTopHint**——那会盖住所有应用程序窗口（用户截图里
    黑弹窗压住桌面中央的根源）。作为桌面的一部分，打开应用时被盖住
    是正确行为。
  - M5：弹窗插到**桌面带内最顶**（win32_layer.band_topmost_hwnd →
    insert_above_window）——压得住整理窗口与所有小组件（旧实现只保证
    高于整理窗口，小组件会压住弹窗，指导文档 §4.1 现状证据）
  - ScrimWindow 幕布：桌面带内、弹窗下一层的全屏半透明黑
    （rgba(0,0,0,0.28)，200ms 淡入淡出）；**点击幕布 = 关闭弹窗**
    （与 DesktopWindow 空白点击关闭双保险）；幕布同时压暗图标与
    小组件（iOS 打开文件夹语义）。弹窗与幕布都纳入 BandGuard
  - NOACTIVATE：点击/拖动照常接收（NOACTIVATE 只禁激活），但永不抢焦点
  - 打开：玻璃表面从锚点图标位置"涌出"（缩放 0.62->1.0，欠阻尼弹簧
    0.8 = 液态 wobble）+ 淡入；窗口尺寸全程不变——不动 geometry 动画，
    避免 setFixedSize 钳制起点 / 子控件不随窗口缩放等一系列坑
  - 关闭：反向（缩放收 0.55 + 淡出）后才真正 close；临界阻尼、防重入
  - 关闭方式：× 按钮 / 点击幕布 / 点击桌面空白处 / 再次点击文件夹图标。
    NOACTIVATE 窗口收不到键盘焦点，故 Esc 不可用
  - refresh() 背板重抓：先 hide() → 抓屏 → show()（同帧完成，无闪烁）

液态玻璃实现说明（为什么不用 acrylic API）：
  SetWindowCompositionAttribute 的 ACCENT_ENABLE_ACRYLICBLURBEHIND 与
  Qt 的 WA_TranslucentBackground + WS_EX_LAYERED 组合冲突（acrylic 不显示）。
  改为 show() 前抓屏 -> C++ 层高斯模糊 -> paintEvent 自绘，跨 Win10/Win11
  稳定，观感完全可控。桌面场景背后基本静态，一次性抓取完全够用。
"""
import traceback

from PySide6.QtCore import (QAbstractAnimation, QEasingCurve,
                            QParallelAnimationGroup, QPoint,
                            QPointF, QPropertyAnimation, QRect, QRectF, Qt,
                            Signal, Property)
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from . import appsource
from . import effects
from . import grid_flow
from . import theme
from . import win32_layer
from .folder_tint import auto_tint, folder_tint
from .iconwidget import AppIcon

ZOOM_FROM = 0.62   # 打开时玻璃初始缩放（相对最终尺寸）
ZOOM_TO = 0.55     # 关闭时玻璃收起的缩放
SCRIM_ALPHA = 71   # 幕布黑透明度（0.28 × 255 ≈ 71）
TINT_OVERLAY_ALPHA = 46   # 弹窗背板上的色板色覆盖层透明度


class ScrimWindow(QWidget):
    """文件夹打开时的全屏幕布：压暗桌面带内所有元素（iOS 打开文件夹语义）。

    点击幕布 = 关闭弹窗（双保险之一；DesktopWindow 空白点击关闭是另一重）。
    挂桌面带（NOACTIVATE，不抢焦点；不置顶，不盖应用窗口）。

    2026-10-19 用户反馈修复：幕布必须**转发拖放**。它铺满整个桌面带且
    层级高于整理窗口——从弹窗里把成员往外拖，光标一离开弹窗就落在幕布
    上；旧实现没有 dragEnter/dropEvent，合成 drop 被静默吞掉，
    `_on_extract` 永不执行（用户："拖拽出来后不显示"）。
    """
    clicked = Signal()
    dropReceived = Signal(object, QPoint)   # (QMimeData, 全局落点)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(QGuiApplication.primaryScreen().availableGeometry())
        self.setAcceptDrops(True)
        self._closing = False
        self._anims = []

    # ---------- 拖放转发 ----------
    def _accepts(self, md) -> bool:
        from .iconwidget import MIME_TYPE
        return bool(md is not None
                    and (md.hasFormat(MIME_TYPE) or md.hasUrls()))

    def dragEnterEvent(self, e):
        if self._accepts(e.mimeData()):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if self._accepts(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        if not self._accepts(e.mimeData()):
            return
        self.dropReceived.emit(e.mimeData(),
                               self.mapToGlobal(e.position().toPoint()))
        e.acceptProposedAction()

    # ---------- 淡入淡出 ----------
    def fade_in(self):
        self.setWindowOpacity(0.0)
        self._fade(0.0, 1.0, 200)

    def fade_out_then_close(self):
        if self._closing:
            return
        self._closing = True
        self._fade(float(self.windowOpacity()), 0.0, 200,
                   QEasingCurve.InCubic, done=self._really_close)

    def _fade(self, start, end, ms, easing=None, done=None):
        for a in list(self._anims):
            a.stop()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(effects.dur(ms))
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        anim.setEasingCurve(easing if easing is not None
                            else QEasingCurve.OutCubic)
        if done is not None:
            anim.finished.connect(done)
        anim.finished.connect(lambda: self._anims.remove(anim)
                              if anim in self._anims else None)
        self._anims.append(anim)
        anim.start()
        return anim

    def _really_close(self):
        try:
            win32_layer.unregister_band_window(int(self.winId()))
        except Exception:
            pass
        super().close()

    # ---------- 交互 ----------
    def mousePressEvent(self, e):
        self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0, SCRIM_ALPHA))


class BandInputBox(QWidget):
    """行内单行输入框（M5：重命名 / 添加面板搜索共用）。

    NOACTIVATE 窗口收不到键盘焦点，行内编辑必须由这个**可激活**的
    小型 frameless 窗口承担（与便签 interactive 组件同决策：要键盘
    就不能 NOACTIVATE，见 DEVLOG 6.3）。Enter / 失焦提交，Esc 取消；
    空白输入视为取消（保持原值）。挂桌面带、插到调用方窗口之上。
    """
    committed = Signal(str)
    cancelled = Signal()

    def __init__(self, text="", placeholder="", title="", parent=None):
        super().__init__(parent)
        self.title = title
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(240, 36)
        self.line = QLineEdit(self)
        self.line.setGeometry(0, 0, 240, 36)
        self.line.setText(text or "")
        self.line.setPlaceholderText(placeholder or title or "")
        self.line.setFrame(False)
        self.line.setToolTip(title)
        self.line.setStyleSheet(
            "QLineEdit { background: %s; color: %s; border: 1px solid %s;"
            " border-radius: 10px; padding: 0 12px;"
            " font-family: %s; font-size: 14px; }" % (
                theme.rgba(theme.SURFACE_POPUP), theme.rgba(theme.TEXT),
                theme.rgba(theme.ACCENT),
                ", ".join('"%s"' % f for f in theme.FONT_FAMILIES)))
        self.line.returnPressed.connect(self._commit)
        self.line.textChanged.connect(lambda: self._resize_to_text())

    # ---------- 几何 ----------
    def show_at(self, global_center):
        """在给定全局点居中显示并抢焦点（全选文字，直接覆盖输入）。"""
        self.move(int(global_center.x() - self.width() / 2),
                  int(global_center.y() - self.height() / 2))
        self.show()
        self.line.setFocus()
        self.line.selectAll()

    def attach_above(self, other_window):
        """挂桌面带并插到 other_window 之上（弹窗内浮现的输入框）。"""
        try:
            if not win32_layer.attach_to_desktop(self):
                return False
            if other_window is not None:
                return win32_layer.insert_above_window(
                    int(self.winId()), int(other_window.winId()))
        except Exception:
            pass
        return False

    def _resize_to_text(self):
        pass  # 固定宽度即可；长名滚动

    # ---------- 提交 / 取消 ----------
    def _commit(self):
        t = self.line.text().strip()
        if t:
            self.committed.emit(t)
        else:
            self.cancelled.emit()
        self.close()

    def _cancel(self):
        self.cancelled.emit()
        self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._cancel()
        else:
            super().keyPressEvent(e)

    def focusOutEvent(self, e):
        # 失焦提交（指导文档 §4.2）：点到别处即落定
        self._commit()
        super().focusOutEvent(e)

    def close(self):
        try:
            win32_layer.unregister_band_window(int(self.winId()))
        except Exception:
            pass
        super().close()


class FolderPopup(QWidget):
    launchApp = Signal(dict)
    extractRequested = Signal(str)   # payload "M:fid:idx"（M: 标记与含冒号的条目 id 消歧）
    removeMember = Signal(str)       # payload "M:fid:idx"
    memberAdded = Signal(str)        # M5：桌面图标加入文件夹（entry id）
    renamed = Signal()               # M5：重命名提交（源图标刷新标签/tooltip）
    tintChanged = Signal()           # M5：色板换色（源图标刷新渐变）
    closed = Signal()

    # 色板解析与自动色共用（AppIcon._paint_folder 用同一份实现）
    auto_tint = staticmethod(auto_tint)
    folder_tint = staticmethod(folder_tint)

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
        # M5 交互态
        self._empty = False          # 空文件夹态
        self._empty_hint = ""        # 空态提示文案
        self._palette_open = False   # 色板浮层
        self._palette_rects = []     # [(QRect, QColor|None)] None = 「自动」
        self._add_panel_open = False # ＋ 添加面板
        self._add_rects = []         # [(QRect, entry_id)] 添加面板候选格
        self._editor = None          # 行内输入框（重命名）
        self._close_hover = False
        self._title_hover = False
        self._bar_hover = {}         # pill key -> bool
        # 桌面带成员：不置顶（不盖应用窗口）、不激活（不抢焦点）。
        # 挂载由 DesktopWindow.open_folder 在 show() 之后完成。
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self._build(anchor_rect)
        self._open_animate()

    # ---------- 布局 ----------
    def _metrics(self):
        """DPI × 用户缩放感知的布局度量（成员与桌面网格同大小）。"""
        icon_size = max(56, self.storage.icon_metric())
        m = self.storage.icon_chrome_scale()
        pad = int(round(16 * m))
        title_h = int(round(36 * m))
        bar_h = int(round(46 * m))     # M5 底部工具条
        return icon_size, m, pad, title_h, bar_h

    def _members_rect(self):
        """成员网格区域（标题下、工具条上）。"""
        _s, m, pad, title_h, bar_h = self._metrics()
        return QRect(pad, title_h, self.width() - pad * 2,
                     self.height() - title_h - bar_h)

    def _title_rect(self):
        _s, m, pad, title_h, _b = self._metrics()
        return QRect(pad, 6, self.width() - pad * 2, title_h - 8)

    def _close_rect(self):
        s = max(20, int(round(24 * self.storage.icon_chrome_scale())))
        return QRect(self.width() - s - 10, 10, s, s)

    def _bar_rects(self):
        """底部工具条两个 pill：[("add", rect), ("color", rect)]。"""
        _s, m, pad, _t, bar_h = self._metrics()
        y = self.height() - bar_h + int(round(8 * m))
        h = bar_h - int(round(16 * m))
        w = (self.width() - pad * 3) // 2
        return [("add", QRect(pad, y, w, h)),
                ("color", QRect(pad * 2 + w, y, w, h))]

    def _build(self, anchor_rect, keep_backdrop=False):
        for child in self.findChildren(AppIcon):
            child.deleteLater()
        # 成员部件全部销毁：飞行中的成员拖拽已死亡，标志位一并复位。
        # 否则 _dragging 卡死会让 focusOutEvent 再也无法自动收起弹窗
        # （拖源被删 -> dragFinished 送不达 -> _on_drag_finish 不执行）。
        self._dragging = False
        icon_size, m, pad, title_h, bar_h = self._metrics()
        members = self.entry.get("apps", [])
        self._empty = not members
        self._empty_hint = ("空文件夹\n从桌面拖入，或点底部「＋ 添加」"
                            if self._empty else "")
        # iOS 文件夹网格：1~2 个成员 2 列（不稀拉）；3 个及以上 4 列
        # （旧版 min(4, max(2, (n+1)//2)) 让 4 个成员排成 2x2，被用户
        # 反馈"展开 UI 完全不对"——iOS 是单行 4 列起步）
        n = len(members)
        cols = 2 if n <= 2 else 4
        rows = max(1, (len(members) + cols - 1) // cols)
        pitch_x = icon_size + int(round(22 * m))
        pitch_y = icon_size + int(round(44 * m))
        w = pad * 2 + (cols - 1) * pitch_x + icon_size
        h = pad + title_h + (rows - 1) * pitch_y + (icon_size + int(round(42 * m))) + bar_h + pad - int(round(8 * m))
        # 高度不超过可用屏幕的 82%：桌面文件全拖进来的极端情况不顶出屏幕
        # v6 §6.2（指导文档 §6.2 反馈 8/9）：弹窗中心对齐**当前页网格区
        # 中心**——幕布吞掉桌面层点击后弹窗是模态面板，从任意位置的文件夹
        # 图标打开都落屏幕同一处，比贴锚点更符合预期；网格区几何所有页
        # 相同（页只是行偏移），故与翻页状态解耦。
        cx, cy = grid_flow.page_grid_center(self.storage)
        screen = QGuiApplication.screenAt(QPoint(int(cx), int(cy)))
        screen = screen or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        max_h = int(geo.height() * 0.82)
        self.setFixedSize(max(240, w), min(max(150, h), max_h))
        x = cx - self.width() // 2
        y = cy - self.height() // 2
        x = max(geo.left() + 8, min(x, geo.right() - self.width() - 8))
        y = max(geo.top() + 8, min(y, geo.bottom() - self.height() - 8))
        self.move(x, y)
        if anchor_rect is not None:
            # 玻璃从图标位置涌出：缩放中心 = 图标中心（弹窗本地坐标）
            self._zoom_center = self.mapFromGlobal(anchor_rect.center())
        else:
            self._zoom_center = QPointF(self.width() / 2, self.height() / 2)
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
            icon.move(pad + (i % cols) * pitch_x,
                      pad + title_h + (i // cols) * pitch_y)
            # 弹窗内图标错峰淡入（玻璃涌出后依次浮现）
            icon.appear_in(120 + i * 45)
            icon.show()
        # 2026-10-19 用户反馈"文件夹样式有时候出问题"：稳态必须铺满整个
        # 窗口。开合动画中断 / 被 refresh 打断时 `_zoom` 可能停在中间值，
        # 而 paintEvent 只按 zoom 缩放后的 rect 画玻璃——结果是"图标和工具
        # 条都在、面板却只有中间一小块"。这里在没有动画在跑时强制归位，
        # 并把整窗刷一次（几何变了，旧脏区不足以覆盖新尺寸）。
        anim = getattr(self, "_open_anim", None)
        try:
            running = anim is not None and anim.state() == QAbstractAnimation.Running
        except RuntimeError:
            running = False
        if not running:
            self._zoom = 1.0
        self.update()

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
        if self._editor is not None:
            self._editor.close()
            self._editor = None
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
        try:
            win32_layer.unregister_band_window(int(self.winId()))
        except Exception:
            pass
        super().close()

    def refresh(self):
        """成员变化后刷新；文件夹条目已消失（解散）则自动关闭。

        M5：背板重抓——先 hide() → 抓屏 → show()（同帧完成，无闪烁，
        指导文档 §4.2 保留项 + §6 风险表）。空文件夹不再自动关闭：
        显示空态（「空文件夹」+ 提示），由用户主动关。
        """
        found = self.storage.find_entry(self.entry.get("id"))
        if not found or found.get("type") != "folder":
            self.close()
            return
        self.entry = found
        # v6 §6.2：_build 现在会按网格区中心重新定位——必须先 build
        # （移动 + 重建成员）再抓背板，否则背板抓在旧位置（窗口已移走）。
        self._build(None, keep_backdrop=True)
        self._regrab_backdrop()

    def _regrab_backdrop(self):
        """背板重抓：隐藏本窗 → 抓屏 → 同帧显示回（避免把自己抓进去）。"""
        self.hide()
        self._backdrop = effects.glass_backdrop(
            QRect(self.x(), self.y(), self.width(), self.height()))
        self.show()

    def attach_above_band(self):
        """挂桌面带后插到**带内最顶**（指导文档 §4.2，决策 D5）：
        枚举桌面带成员（整理窗口 + 各小组件 + 幕布），插到当前最顶者
        之上——弹窗压得住桌面带内所有元素。必须在 attach_to_desktop
        成功之后调用。"""
        try:
            hwnd = int(self.winId())
        except Exception:
            return False
        top = win32_layer.band_topmost_hwnd(exclude_hwnd=hwnd)
        if not top:
            return False
        return win32_layer.insert_above_window(hwnd, top)

    # ---------- M5：重命名 ----------
    def _open_rename(self):
        if self._editor is not None:
            self._editor.close()
            self._editor = None
        box = BandInputBox(text=self.entry.get("name") or "文件夹",
                           title="重命名")
        box.committed.connect(self._on_renamed)
        box.cancelled.connect(self._on_editor_cancelled)
        self._editor = box
        c = self.mapToGlobal(self._title_rect().center())
        box.show_at(c)
        box.attach_above(self)

    def _on_editor_cancelled(self):
        self._editor = None

    def _on_renamed(self, name):
        self.entry["name"] = name
        self.storage.save()
        self._editor = None       # 输入框提交后自行关闭，摘除悬空引用
        self.renamed.emit()      # 源图标刷新标签 / tooltip
        self.update()

    # ---------- M5：背景色板 ----------
    def _palette_layout(self):
        """色板浮层几何：一行 8 色 + 「自动」，位于工具条上方。"""
        _s, m, pad, _t, bar_h = self._metrics()
        sw = int(round(30 * m))
        gap = int(round(8 * m))
        total = sw * 9 + gap * 8
        x0 = (self.width() - total) // 2
        y = self.height() - bar_h - sw - int(round(12 * m))
        rects = []
        for i, c in enumerate(theme.FOLDER_TINTS):
            rects.append((QRect(x0 + i * (sw + gap), y, sw, sw), c))
        rects.append((QRect(x0 + 8 * (sw + gap), y, sw, sw), None))  # 「自动」
        return rects

    def _set_tint(self, color):
        if color is None:
            color = self.auto_tint(self.entry.get("apps", []))
            if color is None:
                return                  # 取不到成员图标：保持现色
        self.entry["tint"] = color.name()
        self.storage.save()
        self.tintChanged.emit()
        self._palette_open = False
        self.update()

    # ---------- M5：＋ 添加面板 ----------
    def _open_add_panel(self):
        self._add_panel_open = not self._add_panel_open
        self._palette_open = False
        self.update()

    def _add_candidates(self):
        """桌面条目候选：排除文件夹自身与已在文件夹里的成员（按名称）。"""
        member_names = {m.get("name") for m in self.entry.get("apps", [])}
        out = []
        for e in self.storage.layout:
            if e.get("type") != "app" or e.get("id") == self.entry.get("id"):
                continue
            if (e.get("app") or {}).get("name") in member_names:
                continue
            out.append(e)
        return out

    def _add_panel_layout(self, limit=24):
        """添加面板网格几何：[(QRect, entry_id)]（4 列，超限不显示）。"""
        _s, m, pad, title_h, _b = self._metrics()
        area = self._members_rect()
        icon_size = max(40, int(self.storage.icon_metric() * 0.72))
        cols = 4
        pitch_x = area.width() // cols
        pitch_y = icon_size + int(round(34 * m))
        rows_avail = max(1, area.height() // pitch_y)
        rects = []
        for i, e in enumerate(self._add_candidates()[:limit]):
            r, c = i % cols, i // cols
            if c >= rows_avail:
                break
            rects.append((QRect(area.left() + r * pitch_x,
                                area.top() + c * pitch_y,
                                pitch_x, pitch_y), e["id"]))
        return rects, icon_size

    def _add_member_by_id(self, entry_id):
        """把桌面条目加入文件夹（＋ 点选 / 拖入共用）。"""
        e = self.storage.find_entry(entry_id)
        if e is None or e.get("type") != "app":
            return
        app = e.get("app")
        if not app or app in self.entry.get("apps", []):
            return
        self.entry.setdefault("apps", []).append(app)
        self.storage.save()
        self.memberAdded.emit(entry_id)   # DesktopWindow：移出布局 + 动画
        self._add_panel_open = False
        self.refresh()

    # ---------- 拖放：桌面图标拖到弹窗上加入 ----------
    def dragEnterEvent(self, e):
        from .iconwidget import MIME_TYPE
        if e.mimeData().hasFormat(MIME_TYPE):
            e.acceptProposedAction()

    def dropEvent(self, e):
        from .iconwidget import MIME_TYPE
        data = e.mimeData().data(MIME_TYPE).data().decode()
        for eid in [p for p in data.split(",") if p]:
            if eid.startswith("M:"):
                continue                     # 成员拖出是 extract，不在这里
            if self.storage.find_entry(eid) is not None:
                self._add_member_by_id(eid)
        e.acceptProposedAction()

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

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = e.pos()
        # NOACTIVATE 窗口收不到键盘焦点，Esc 不可用；提供右上角 × 明确关闭
        if self._close_rect().contains(pos):
            self.close()
            return
        if self._title_rect().contains(pos):
            self._open_rename()
            return
        for key, rect in self._bar_rects():
            if rect.contains(pos):
                if key == "add":
                    self._open_add_panel()
                else:
                    self._palette_open = not self._palette_open
                    self._add_panel_open = False
                self.update()
                return
        if self._palette_open:
            for rect, color in self._palette_layout():
                if rect.contains(pos):
                    self._set_tint(color)
                    return
        if self._add_panel_open:
            rects, _sz = self._add_panel_layout()
            for rect, eid in rects:
                if rect.contains(pos):
                    self._add_member_by_id(eid)
                    return

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 缩放系数夹紧到合法区间：任何中断残留的中间值都不该让面板缩水
        # （稳态 1.0 = 面板与内容区完全重合，2026-10-19 反馈）
        z = min(1.0, max(0.05, float(self._zoom)))
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
        if z <= 0.55:
            return
        # M5：色板色覆盖层（与文件夹图标同一颜色，iOS 文件夹语言）
        tint = self.folder_tint(self.entry)
        overlay = QColor(tint.red(), tint.green(), tint.blue(),
                         TINT_OVERLAY_ALPHA)
        p.setPen(Qt.NoPen)
        p.setBrush(overlay)
        p.drawRoundedRect(rect, theme.GLASS_RADIUS * z, theme.GLASS_RADIUS * z)
        # 标题：随玻璃浮现渐显；vibrancy 规范——材质上文字提高对比、
        # 稍加字重、微加字距（不用平灰）。iOS 文件夹标题居中。
        p.setOpacity(min(1.0, (z - 0.55) / 0.35))
        tr = self._title_rect()
        p.setPen(theme.TEXT)
        f = theme.ui_font(15, bold=True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.3)
        p.setFont(f)
        p.drawText(tr, Qt.AlignHCenter | Qt.AlignVCenter,
                   self.entry.get("name") or "文件夹")
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
        # 空态提示（成员网格区居中两行）
        if self._empty:
            p.setPen(theme.TEXT)
            f2 = theme.ui_font(14, bold=True)
            p.setFont(f2)
            area = self._members_rect()
            p.drawText(area, Qt.AlignHCenter | Qt.AlignBottom, "空文件夹")
            p.setPen(theme.TEXT_DIM)
            f3 = theme.ui_font(11)
            p.setFont(f3)
            p.drawText(area.adjusted(0, 0, 0, -26),
                       Qt.AlignHCenter | Qt.AlignBottom,
                       "从桌面拖入，或点底部「＋ 添加」")
        # 底部工具条：两个 pill 按钮
        for key, rect_ in self._bar_rects():
            hovered = self._bar_hover.get(key, False)
            active = ((key == "add" and self._add_panel_open)
                      or (key == "color" and self._palette_open))
            p.setPen(Qt.NoPen)
            if active:
                p.setBrush(QColor(theme.ACCENT.red(), theme.ACCENT.green(),
                                  theme.ACCENT.blue(), 60))
            elif hovered:
                p.setBrush(theme.SURFACE_RAISED)
            else:
                p.setBrush(QColor(255, 255, 255, 18))
            p.drawRoundedRect(QRectF(rect_), 12, 12)
            p.setPen(theme.TEXT if (hovered or active) else theme.TEXT_DIM)
            f4 = theme.ui_font(12)
            p.setFont(f4)
            label = "＋ 添加图标" if key == "add" else "颜色"
            p.drawText(rect_, Qt.AlignCenter, label)
        # 色板浮层（工具条上方一行 8 色 + 自动）
        if self._palette_open:
            for rect_, color in self._palette_layout():
                if color is None:
                    # 「自动」：描边圆形 + 字母 A
                    p.setPen(QPen(theme.TEXT_DIM, 1))
                    p.setBrush(theme.SURFACE_RAISED)
                    p.drawEllipse(QRectF(rect_))
                    p.setPen(theme.TEXT)
                    p.setFont(theme.ui_font(11, bold=True))
                    p.drawText(rect_, Qt.AlignCenter, "A")
                else:
                    p.setPen(QPen(theme.BORDER_STRONG, 1))
                    p.setBrush(color)
                    p.drawEllipse(QRectF(rect_))
        # ＋ 添加面板（成员区上的次级浮层）
        if self._add_panel_open:
            rects, icon_size = self._add_panel_layout()
            area = self._members_rect()
            panel = QRectF(area.left(), area.top(), area.width(), area.height())
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(18, 19, 24, 216))
            p.drawRoundedRect(panel, theme.RADIUS_PANEL, theme.RADIUS_PANEL)
            dpr = self.devicePixelRatioF()
            for rect_, eid in rects:
                hovered = self._bar_hover.get(("item", eid), False)
                if hovered:
                    p.setBrush(theme.SURFACE_RAISED)
                    p.drawRoundedRect(QRectF(rect_.adjusted(2, 2, -2, -2)), 8, 8)
                e = self.storage.find_entry(eid)
                if e is None:
                    continue
                app = e.get("app") or {}
                pm = appsource.icon_pixmap(app, icon_size, dpr)
                px = rect_.center().x() - icon_size // 2
                py = rect_.top() + 4
                p.drawPixmap(px, py, pm)
                p.setPen(theme.TEXT_DIM)
                p.setFont(theme.ui_font(10))
                name = app.get("name", "")
                p.drawText(QRect(rect_.left(), py + icon_size + 2,
                                 rect_.width(), 16),
                           Qt.AlignHCenter, name)

    def mouseMoveEvent(self, e):
        pos = e.pos()
        self._close_hover = self._close_rect().contains(pos)
        self._title_hover = self._title_rect().contains(pos)
        for key, rect in self._bar_rects():
            self._bar_hover[key] = rect.contains(pos)
        if self._add_panel_open:
            rects, _sz = self._add_panel_layout()
            for rect, eid in rects:
                self._bar_hover[("item", eid)] = rect.contains(pos)
        any_hover = (self._close_hover or self._title_hover
                     or any(self._bar_hover.values()))
        self.setCursor(Qt.PointingHandCursor if any_hover else Qt.ArrowCursor)
        self.update()

    _close_hover = False
    _title_hover = False

    def focusOutEvent(self, e):
        # NOACTIVATE 窗口通常不会获得焦点，此回调多为兜底；
        # 主动关闭路径见 幕布点击 / DesktopWindow 空白点击 / × 按钮。
        if not self._dragging:
            self.close()

    def closeEvent(self, e):
        self.closed.emit()
        super().closeEvent(e)
