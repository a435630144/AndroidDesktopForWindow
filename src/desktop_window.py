# -*- coding: utf-8 -*-
"""桌面整理主窗口：克隆图标网格、文件夹合并/解散、挂载到桌面层（Progman 上方的桌面带）。

原生桌面图标（SHELLDLL_DefView）在运行期间被隐藏，桌面文件由本窗口
克隆渲染——位置、大小、样式完全由第三方桌面掌控；退出时恢复原生图标。
"""
import os

from PySide6.QtCore import QPoint, QProcess, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from . import appsource
from . import grid_flow
from . import theme
from . import win32_layer
from .band_guard import BandGuard
from .folder_popup import FolderPopup, ScrimWindow
from .iconwidget import MIME_TYPE, AppIcon
from .storage import Storage
from .win32_layer import attach_to_desktop

WM_NCHITTEST = 0x84
HTTRANSPARENT, HTCLIENT = -1, 1


class DesktopWindow(QWidget):
    visibilityChanged = Signal(bool)
    openSettingsRequested = Signal()
    openAddAppsRequested = Signal()
    quitRequested = Signal()

    def __init__(self, storage: Storage):
        super().__init__()
        self.storage = storage
        self.attached = False
        self._attach_retries = 0
        self._attach_known_failed = False
        self._floating_flag_set = False
        self._popup = None
        self._scrim = None             # M5：文件夹幕布（弹窗下一层）
        self._folder_open_icon = None  # M5：处于打开态的源图标（AppIcon）
        # M6 分页：存储里的 row 始终是全局行（零迁移），页是纯视图概念。
        # _page 是 grid_flow 运行时页的委托 property（单一状态源——所有
        # 位置换算 cell_pos/pos_cell/snap_point/widget 都读它）；
        # 持久化在 settings["current_page"]。
        self._page = max(0, int(storage.get_setting("current_page") or 0))
        self._widget_layer = None      # main.py 装配时注入（翻页联动组件）
        self._selected = set()      # 多选：entry id 集合（单击/Ctrl/框选）
        self._drag_active = False   # QDrag 进行中：命中测试临时全窗口接收
        self._drag_entry_id = None  # 当前正在拖的条目（多选拖动时判成员）
        self._ole_active = False    # 外部文件 OLE 拖入进行中（拖放目标全窗口）
        self._band_start = None     # 橡皮筋起点（控件坐标）
        self._band_rect = None
        self._band_moved = False
        self.icons = {}
        # 实时让位（Live Reflow）状态（2026-10-18 M2 起用位移清单）：
        #   _preview_moves  拖动期间算出的位移清单 {id: (col,row)}（只改内存）
        #   _preview_drag   正在被拖的条目 id
        #   _layout_snap    拖动开始时的布局快照（取消回退 / 撤销栈用）
        #   _undo_stack     布局快照栈（Ctrl+Z，最多 20 步）
        self._preview_moves = None
        self._preview_drag = None
        self._layout_snap = None
        self._undo_stack = []
        self._drag_multi = False    # 多选拖动：走整体平移，不参与让位置换
        # 锚定组件拖动实时预览（2026-10-18 M4，与图标拖动同一套语义）：
        #   _widget_snap          进入预览时的布局快照（松手回退基准）
        #   _widget_preview_rect  组件新占位矩形（变化检测，防抖）
        self._widget_snap = None
        self._widget_preview_rect = None
        # WindowDoesNotAcceptFocus(WS_EX_NOACTIVATE)：永不被激活，
        # 保证桌面带窗口永远压在应用窗口之下，不会抢焦点 / 置顶。
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setWindowTitle("桌面整理Demo")
        # 桌面带守护：Win+D / 切屏等导致漂移时自动拉回桌面带
        self._band_guard = BandGuard(self, on_tick=self._on_guard_tick)
        # 载入时规整一次，避免越界 / 重叠
        self.storage.compact_layout()
        self.rebuild(stagger=True)  # 首次显示错峰淡入

    # ---------- 模式 ----------
    def _organize_mode(self) -> bool:
        """桌面整理模式：隐藏原生图标，由本窗口全盘接管（框选 / 自己的右键菜单）。"""
        return bool(self.storage.get_setting("hide_native_icons"))

    def _dev_mode(self) -> bool:
        """开发者模式（2026-10-18）：桌面渲染网格可视化边框，排查布局问题用。

        设置里可开关（SettingsDialog.chk_dev），开发期默认开启
        （storage DEFAULT_SETTINGS["dev_mode"]=True）。
        """
        return bool(self.storage.get_setting("dev_mode"))

    # ---------- 显示 / 隐藏 ----------
    def show_desktop(self):
        if self.attached or self._attach_known_failed:
            self._show_current_mode()
            return
        self._attach_retries = 2
        self._try_attach_once()

    def _try_attach_once(self):
        if self.attached:
            return
        screen = QApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen)
        # 先显示再挂载：挂载后的可见性 / z-order 检查才有意义（未显示的窗口恒为 false）
        self.show()
        self.update()  # 强制全窗重绘：命中填充（alpha=2）立即进入 surface
        self._sync_native_icons()
        if attach_to_desktop(self):
            self.attached = True
            self._band_guard.track(self)
            # M1：几何确定后重算网格（WidgetLayer 随后按新 origin 落位）
            self._update_grid_metrics()
            self.visibilityChanged.emit(True)
            return
        self._attach_retries -= 1
        if self._attach_retries > 0:
            # 桌面层可能还没就绪，稍后重试
            QTimer.singleShot(1500, self._try_attach_once)
        else:
            self._attach_known_failed = True
            self._enter_floating_mode()

    def _enter_floating_mode(self):
        """悬浮模式兜底（挂载失败时）：置顶 + 带面板背景。"""
        screen = QApplication.primaryScreen().availableGeometry()
        if not self._floating_flag_set:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            self._floating_flag_set = True
        self.setGeometry(QRect(screen.left() + 60, screen.top() + 40,
                               min(screen.width(), 1180), min(screen.height(), 780)))
        self.setWindowOpacity(float(self.storage.get_setting("opacity")))
        self.show()
        self._update_grid_metrics()
        self.visibilityChanged.emit(True)

    def _show_current_mode(self):
        """模式已确定后的再次显示（托盘切换显隐时走这里）。"""
        if self.attached:
            if self._floating_flag_set:
                self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
                self._floating_flag_set = False
            self.setGeometry(QApplication.primaryScreen().availableGeometry())
            self._update_grid_metrics()
        else:
            self._enter_floating_mode()
            return
        self.setWindowOpacity(1.0)
        self.show()
        self.update()  # 强制全窗重绘：命中填充（alpha=2）立即进入 surface
        self._sync_native_icons()
        # 重新显示后 Windows 可能改变 z-order，重新插回桌面带
        attach_to_desktop(self)
        self.visibilityChanged.emit(True)

    def hide_desktop(self):
        # M5：隐藏整理窗口前先收好文件夹弹窗与幕布（否则两者留在屏幕上）
        self._close_popup()
        self.hide()
        # 隐藏整理窗口时恢复原生图标：用户要回自己的桌面时不能什么都没有
        if not self._attach_known_failed:
            win32_layer.set_native_icons_visible(True)
        self.visibilityChanged.emit(False)

    def toggle(self):
        if self.isVisible():
            self.hide_desktop()
        else:
            self.show_desktop()

    # ---------- 原生桌面图标 ----------
    def _sync_native_icons(self):
        """按设置隐藏 / 恢复系统原生桌面图标（克隆模式核心）。"""
        hide = bool(self.storage.get_setting("hide_native_icons"))
        win32_layer.set_native_icons_visible(not hide)

    def apply_native_icons_setting(self):
        """设置 / 托盘里切换桌面整理模式后调用。

        整理模式：隐藏原生图标，窗口全盘接管。
        原生模式：恢复原生图标；窗口保持显示（全透明 + 空白区命中穿透），
        手动添加的图标与「从资源管理器拖入」照常工作。
        """
        self._sync_native_icons()
        self.show_desktop()
        self.rebuild(stagger=True)  # 模式切换：图标错峰淡入的仪式感

    def _on_guard_tick(self):
        """守护周期回调：保持原生图标隐藏（explorer 重启等会令其重新可见）；
        M1 附加：工作区几何变化（DPI / 分辨率 / 任务栏位置变化，
        WM_SETTINGCHANGE/WM_DISPLAYCHANGE 的轮询兜底）时重算网格。"""
        if self.storage.get_setting("hide_native_icons") and self.isVisible():
            if not win32_layer.native_icons_hidden():
                win32_layer.set_native_icons_visible(False)
        if self.attached and self.isVisible():
            geo = QApplication.primaryScreen().availableGeometry()
            if (geo.width(), geo.height()) != (self.width(), self.height()):
                self.setGeometry(geo)
                self._update_grid_metrics()

    def paintEvent(self, event):
        if self.attached:
            # 命中填充：分层窗口（WA_TranslucentBackground + WS_EX_LAYERED）的
            # 逐像素 alpha 命中测试会跳过全透明像素——WM_NCHITTEST 根本发不到
            # 本窗口，导致拖到空白格 drop 丢失、空白区按下点击穿透（橡皮筋不
            # 启动）。全窗铺一层 alpha=2（0.8% 不透明度，视觉不可见）使整个
            # surface 可被系统命中；「是否吃事件」仍由 nativeEvent 策略决定
            # （原生模式空闲对非图标区返回 HTTRANSPARENT，穿透不受影响）。
            self._paint_hit_fill()
            # 空态提示只在整理模式画：原生模式下桌面是系统原生的，不能盖任何东西
            if not self.icons and self._organize_mode():
                self._paint_empty_hint(event)
            if self._band_rect is not None:
                self._paint_band(event)
            if self._organize_mode():
                if self._dev_mode():
                    self._paint_grid_debug()
                self._paint_dots()
            return  # 除上述元素外全透明，融入壁纸
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(theme.SURFACE)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(self.rect().adjusted(6, 6, -6, -6), theme.RADIUS_PANEL, theme.RADIUS_PANEL)
        p.setPen(theme.TEXT)
        p.setFont(theme.ui_font(13))
        p.drawText(24, 30, "桌面整理 Demo · 悬浮模式（未能挂载桌面层，功能不受影响）")
        if self._organize_mode():
            if self._dev_mode():
                self._paint_grid_debug()
            self._paint_dots()

    def _paint_hit_fill(self):
        """全窗 alpha=2 命中填充（视觉不可见，使透明像素也可被系统命中测试选中）。"""
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 2))
        p.end()

    def _paint_band(self, event):
        """橡皮筋框选矩形（仅整理模式会绘制：原生模式空白区事件已穿透）。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._band_rect
        p.setPen(QPen(theme.ACCENT, 1.2))
        p.setBrush(QColor(theme.ACCENT.red(), theme.ACCENT.green(), theme.ACCENT.blue(), 40))
        p.drawRoundedRect(r, 4, 4)

    # ---------- 橡皮筋框选（整理模式；原生模式事件已穿透给真实桌面） ----------
    def mousePressEvent(self, e):
        # 新一次按下必然不在拖动中：清掉可能因信号丢失而卡住的拖动状态
        # （_drag_active 卡死会让 nativeEvent 全窗口 HTCLIENT，桌面点不动；
        #  _drag_multi 卡死会让单选拖动也走多选平移分支）
        self._drag_active = False
        self._drag_multi = False
        # 文件夹弹窗开着时点桌面空白处 = 关闭弹窗（iOS 文件夹语义；
        # 弹窗自身 NOACTIVATE 收不到 Esc，× 按钮 + 这里 + 再点图标共三条路径）
        if self._popup is not None and e.button() == Qt.LeftButton:
            self._close_popup()
            return
        # M6：页点点击翻页（整理模式可点；原生模式 dots 不画也不命中——
        # 空白区事件穿透真实桌面，翻页交给用户切模式后使用）
        if e.button() == Qt.LeftButton and self._organize_mode():
            pts = self._dot_centers()
            if pts:
                dr = self._dots_rect()
                if dr is not None and dr.contains(e.pos()):
                    # 就近页点：圆心水平距离最小者
                    best = min(range(len(pts)),
                               key=lambda i: abs(pts[i].x() - e.pos().x()))
                    self.goto_page(best)
                    return
        if e.button() == Qt.LeftButton and self._organize_mode():
            self._band_start = e.pos()
            self._band_rect = None
            self._band_moved = False

    def mouseMoveEvent(self, e):
        if self._band_start is None or not (e.buttons() & Qt.LeftButton):
            return
        if (e.pos() - self._band_start).manhattanLength() >= QApplication.startDragDistance():
            self._band_moved = True
        if self._band_moved:
            self._band_rect = QRect(self._band_start, e.pos()).normalized()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._band_start is None:
            return
        if self._band_moved and self._band_rect is not None:
            self._select_in_rect(self._band_rect)
        else:
            self._clear_selection()
        self._band_start = None
        self._band_rect = None
        self._band_moved = False
        self.update()

    def wheelEvent(self, e):
        """M6：整理模式下滚轮翻页（与页点互补的快捷路径）。

        阈值 15（1/8 度）= 普通滚轮一格的 1/8：高精度滚轮单次增量小
        也能翻页，又不至于被触摸板微抖误触。已到首/末页时消费事件
        不再传递（没有上层需要）。原生模式不拦——滚轮还给真实桌面。
        """
        if self._organize_mode():
            dy = e.angleDelta().y()
            if abs(dy) >= 15:
                # 上滚（负 delta）= 上一页；下滚（正 delta）= 下一页
                self.goto_page(self._page + (-1 if dy < 0 else 1))
            e.accept()
            return
        super().wheelEvent(e)

    def _paint_empty_hint(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(theme.TEXT_FAINT)
        p.setFont(theme.ui_font(13))
        p.drawText(self.rect(), Qt.AlignCenter,
                   "桌面文件会显示在这里\n从资源管理器把文件拖进来，或右键托盘「添加应用」")

    # ---------- 命中测试：分层放行策略 ----------
    def nativeEvent(self, eventType, message):
        """桌面模式下本窗口铺满全屏且基本全透明，命中测试分四层：
        （前提：paintEvent 的 alpha=2 命中填充保证 WM_NCHITTEST 能发到本窗口，
          否则分层窗口会跳过全透明像素，本策略根本没有执行机会）
        - 图标附近（含边距）-> HTCLIENT：本窗口处理（点击/拖动/我们的菜单）
        - 拖拽进行中          -> 全窗口 HTCLIENT：OLE 拖放的命中判定必须能选中
                                  本窗口，否则图标永远落不回桌面（拖动失效根因）
        - 外部文件拖入进行中  -> 全窗口 HTCLIENT：从资源管理器拖文件放到空白区
        - 整理模式            -> 全窗口 HTCLIENT：框选、自己的右键菜单
        - 原生模式空闲        -> HTTRANSPARENT：空白区点击/右键/框选全部落到
                                  真实桌面（SHELLDLL_DefView），原生交互零损失
        """
        if eventType in (b"windows_generic_MSG", "windows_generic_MSG"):
            try:
                import ctypes
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
            except Exception:
                return super().nativeEvent(eventType, message)
            if msg.message == WM_NCHITTEST:
                if self._drag_active or self._ole_active or self._organize_mode():
                    return True, HTCLIENT
                x = ctypes.c_int16(msg.lParam & 0xFFFF).value
                y = ctypes.c_int16((msg.lParam >> 16) & 0xFFFF).value
                pt = QPoint(x, y)
                pad = int(round(14 * self.storage.icon_chrome_scale()))
                for icon in self.icons.values():
                    r = QRect(icon.mapToGlobal(QPoint(0, 0)), icon.size())
                    if r.adjusted(-pad, -pad, pad, pad).contains(pt):
                        return True, HTCLIENT
                return True, HTTRANSPARENT
        return super().nativeEvent(eventType, message)

    # ---------- 网格几何（几何定义统一在 grid_flow，勿在此重复实现） ----------
    def _cell(self):
        return grid_flow.cell_size(self.storage)

    def _origin(self):
        return grid_flow.origin()

    def _update_grid_metrics(self):
        """M1（指导文档 §1）：按当前窗口尺寸重算 GridMetrics 写入
        grid_flow——origin()/columns 等共享几何随之更新为按工作区
        四边等距铺满。已有图标只 move 到新格点（不 rebuild：保留
        动效状态与选中态，也避免闪烁）。

        M6：rows_per_page 随几何变化（DPI/分辨率/任务栏）后，总页数
        可能变少——越界的当前页夹紧回末页。
        """
        before = grid_flow.current_metrics()
        grid_flow.set_grid(self.storage, (self.width(), self.height()))
        after = grid_flow.current_metrics()
        self._clamp_page()
        if before is not None and before == after:
            return
        for eid, icon in self.icons.items():
            entry = self.storage.find_entry(eid)
            if entry is not None:
                icon.move(*self._entry_pos(entry))
        if self._widget_layer is not None:
            self._widget_layer.sync_page(self._page)
        self.update()

    def resizeEvent(self, event):
        # M1：窗口几何变化（挂载后铺满工作区 / 悬浮兜底 / 显示器几何变化）
        # 时重算网格。未挂载时窗口尺寸无网格意义，跳过。
        super().resizeEvent(event)
        if self.attached:
            self._update_grid_metrics()

    def _entry_pos(self, entry):
        # M6：列夹紧 + 页内局部行映射统一在 grid_flow.cell_pos（DRY）
        return grid_flow.cell_pos(self.storage,
                                  int(entry.get("col", 0)),
                                  int(entry.get("row", 0)))

    def _cell_at(self, pos):
        # M6：反算含当前页偏移（页内 y -> 全局 row），委托 grid_flow
        return grid_flow.pos_cell(self.storage, pos.x(), pos.y())

    # ---------- 分页（M6，指导文档 §7-M6） ----------
    # _page 委托 grid_flow 运行时页（单一状态源）：所有位置换算
    # （cell_pos/pos_cell/snap_point/widget_base/widget_layer）都经
    # grid_flow.current_page() 读同一份，杜绝双源漂移。
    @property
    def _page(self):
        return grid_flow.current_page()

    @_page.setter
    def _page(self, value):
        grid_flow.set_page(value)

    def set_widget_layer(self, layer):
        """注入 WidgetLayer（main.py 装配）：翻页时组件与图标联动滑动。"""
        self._widget_layer = layer

    def _clamp_page(self):
        """总页数变少（DPI/分辨率变化、条目减少）后把越界当前页夹回。"""
        total = grid_flow.page_count(self.storage)
        if self._page > total - 1:
            self.goto_page(total - 1, animate=False)

    def goto_page(self, page, animate=True):
        """翻到指定页：运行时页同步 + 持久化 + 全体弹簧滑到新页位置。

        翻页动画 = M4 位移引擎复用：图标 animate_to 新位置（实例不变），
        组件经 WidgetLayer.sync_page 同向滑动——当前页内容滑出屏、
        邻页内容滑入屏（iOS launcher 语言）。animate=False 用于启动
        夹紧等无仪式场景（直接 move，不播动画）。
        """
        page = max(0, int(page))
        page = min(page, grid_flow.page_count(self.storage) - 1)
        if page == self._page:
            return
        self._page = page
        grid_flow.set_page(page)
        self.storage.set_setting("current_page", page)
        if animate:
            for eid, icon in self.icons.items():
                entry = self.storage.find_entry(eid)
                if entry is not None:
                    icon.animate_to(*self._entry_pos(entry))
        else:
            for eid, icon in self.icons.items():
                entry = self.storage.find_entry(eid)
                if entry is not None:
                    icon.move(*self._entry_pos(entry))
        if self._widget_layer is not None:
            self._widget_layer.sync_page(page)
        self.update()

    def _dot_centers(self):
        """页点圆心列表（底部居中；只有 1 页时返回空——不画点）。"""
        total = grid_flow.page_count(self.storage)
        if total <= 1:
            return []
        r, gap = 4, 14
        total_w = total * 2 * r + (total - 1) * gap
        x0 = (self.width() - total_w) // 2
        y = self.height() - 26
        return [QPoint(x0 + i * (2 * r + gap) + r, y) for i in range(total)]

    def _dots_rect(self):
        """页点命中区（含 6px 热区）。无页点时 None。"""
        pts = self._dot_centers()
        if not pts:
            return None
        return QRect(pts[0].x() - 6, pts[0].y() - 6,
                     pts[-1].x() - pts[0].x() + 12, 12)

    def _paint_dots(self):
        """页点（page dots）：当前页 ACCENT 实心，其余 TEXT_DIM 半透明。
        只在整理模式画+可点——原生模式空白区事件穿透真实桌面，画了
        也点不到（与橡皮筋/空态提示同策略）。"""
        pts = self._dot_centers()
        if not pts:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cur = self._page
        for i, c in enumerate(pts):
            if i == cur:
                p.setPen(Qt.NoPen)
                p.setBrush(theme.ACCENT)
                p.drawEllipse(c, 5, 5)
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.TEXT_DIM.red(), theme.TEXT_DIM.green(),
                                  theme.TEXT_DIM.blue(), 110))
                p.drawEllipse(c, 4, 4)
        p.end()

    def _paint_grid_debug(self):
        """开发者模式：网格可视化边框（2026-10-18，排查布局问题用）。

        画四样东西（调试色与主题色刻意错开——ACCENT 是蓝，这里用春绿/
        品红，肉眼一眼区分；像素签名见 tests/test_dev_mode.py）：
          - 网格工作区外边界（ox,oy → +cols*cw, +rows*ch）：2px 春绿实线
          - 内部网格线（cols+1 竖 + rows+1 横）：1px 春绿 140 alpha
            （亮壁纸上也清晰，又不抢图标焦点；叠深色底混合后像素签名
             见 tests/test_dev_mode.py 相对式判据）
          - 原点十字（ox,oy）：8px 品红——四边等距铺满的锚点
          - 左上几何信息文字（ox/oy/列行/格尺寸/页码）：春绿 12px
        只在整理模式画（原生模式桌面是系统原生的，不盖任何东西）；
        GridMetrics 快照未就绪（挂载前）时跳过。
        """
        m = grid_flow.current_metrics()
        if m is None:
            return
        green = QColor(0, 255, 170)      # 春绿：线 + 文字
        pink = QColor(255, 64, 160)      # 品红：原点十字
        x0, y0 = m.ox, m.oy
        x1, y1 = m.ox + m.cols * m.cw, m.oy + m.rows * m.ch
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 外边界
        p.setPen(QPen(green, 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRect(x0, y0, x1 - x0, y1 - y0))
        # 内部网格线（alpha 140：亮壁纸上也清晰，又不抢图标焦点）
        p.setPen(QPen(QColor(0, 255, 170, 140), 1))
        for c in range(1, m.cols):
            x = x0 + c * m.cw
            p.drawLine(x, y0, x, y1)
        for r in range(1, m.rows):
            y = y0 + r * m.ch
            p.drawLine(x0, y, x1, y)
        # 原点十字（四边等距铺满的锚点）
        p.setPen(QPen(pink, 2))
        p.drawLine(x0 - 5, y0, x0 + 5, y0)
        p.drawLine(x0, y0 - 5, x0, y0 + 5)
        # 几何信息文字（左上，边界内侧）
        total = grid_flow.page_count(self.storage)
        p.setPen(QPen(QColor(0, 255, 170, 220), 1))
        p.setFont(theme.ui_font(12))
        p.drawText(QRect(x0 + 6, y0 + 6, 560, 20),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   "DEV 网格 ox=%d oy=%d %d列×%d行 格%dx%d 第%d/%d页"
                   % (m.ox, m.oy, m.cols, m.rows, m.cw, m.ch,
                      self._page + 1, max(1, total)))
        p.end()

    # ---------- 重建 ----------
    def _wire_icon(self, icon):
        """把一个 AppIcon 的全部信号接到窗口（rebuild 与增量 _add_icon 共用）。"""
        icon.activated.connect(self._on_activate)
        icon.clicked.connect(self._on_icon_clicked)
        icon.folderClicked.connect(self.open_folder)
        icon.mergeRequested.connect(self._on_merge)
        icon.removeRequested.connect(self._on_remove_entry)
        icon.dissolveRequested.connect(self._on_dissolve)
        icon.openLocation.connect(self._on_open_location)
        icon.dragStarted.connect(self._on_drag_started)
        icon.dragFinished.connect(self._on_drag_finished)
        icon.reflowHover.connect(self._on_reflow_hover)
        icon.reflowDrop.connect(self._on_reflow_drop)
        icon.payload_provider = self._drag_payload_for

    def rebuild(self, stagger=False):
        for icon in self.icons.values():
            icon.deleteLater()
        self.icons.clear()
        self._selected = {eid for eid in self._selected
                          if self.storage.find_entry(eid) is not None}
        size = self.storage.icon_metric()          # DPI × 缩放感知
        chrome = self.storage.icon_chrome_scale()
        layout = self._icon_layout()               # v6 A2：三档 × 当前 cell
        for idx, entry in enumerate(self.storage.layout):
            icon = AppIcon(entry, size, parent=self, chrome_scale=chrome,
                           layout=layout)
            self._wire_icon(icon)
            icon.set_selected(entry["id"] in self._selected)
            icon.move(*self._entry_pos(entry))
            if stagger:
                # 错峰淡入（模式切换 / 首次显示的仪式感；业务 rebuild 不加，
                # 拖动落位要即时反馈）
                icon.appear_in(min(idx * 30, 600))
            icon.show()
            self.icons[entry["id"]] = icon
        # 安全网：rebuild 销毁全部图标部件，飞行中的拖拽其源已不存在——
        # dragFinished 可能永远送不达（源被 deleteLater 后 emit 抛
        # RuntimeError，被 IconWidget._after_drag 吞掉）。与 dropEvent
        # 末尾同理（无论 dragFinished 是否送达，drop 完成即复位），
        # 这里无条件复位拖动状态；否则 _drag_active 卡死会让
        # nativeEvent 保持全窗口 HTCLIENT，桌面点击全部失效。
        self._drag_active = False
        self._drag_entry_id = None
        self._drag_multi = False
        self._ole_active = False
        self.update()

    # ---------- 增量更新（2026-10-18 M4：去 rebuild 化） ----------
    def _icon_layout(self):
        """网格模式图标 layout（v6 A2，指导文档 §2.2）。

        档位（storage.icon_tier）× 当前 cell（GridMetrics 快照，屏幕驱动）
        -> grid_sizing.IconLayout；快照未就绪返回 None（回退旧 chrome 路径）。
        """
        from . import grid_sizing
        m = grid_flow.current_metrics()
        if m is None:
            return None
        return grid_sizing.icon_layout(m.cw, m.ch, self.storage.icon_tier())

    def _add_icon(self, entry):
        """增量新增一个图标（add_app / rescan / 文件夹提取等）。
        已在位返回原实例；新图标淡入出场（appear_in(0)）。"""
        if entry["id"] in self.icons:
            return self.icons[entry["id"]]
        size = self.storage.icon_metric()
        chrome = self.storage.icon_chrome_scale()
        layout = self._icon_layout()               # v6 A2：三档 × 当前 cell
        icon = AppIcon(entry, size, parent=self, chrome_scale=chrome,
                       layout=layout)
        self._wire_icon(icon)
        icon.set_selected(entry["id"] in self._selected)
        icon.move(*self._entry_pos(entry))
        icon.appear_in(0)
        icon.show()
        self.icons[entry["id"]] = icon
        return icon

    def _remove_icon(self, entry_id):
        """增量移除一个图标（remove_entry / 合并被吸收方 / rescan 丢失）。"""
        if self._folder_open_icon is not None and entry_id == self._folder_open_icon_entry_id():
            self._exit_folder_open_state()
        icon = self.icons.pop(entry_id, None)
        self._selected.discard(entry_id)
        if icon is not None:
            icon.deleteLater()

    def _folder_open_icon_entry_id(self):
        """打开态源图标对应的 entry id（AppIcon.entry 引用同一 dict）。"""
        icon = self._folder_open_icon
        if icon is None:
            return None
        try:
            return (icon.entry or {}).get("id")
        except RuntimeError:
            return None

    def _sync_icons(self):
        """位置类变化的全量同步：每个图标弹簧滑到自己的格子。

        已在目标位上的 animate_to 早退（零成本）。这是 M4「去 rebuild
        化」的核心——位置变化一律走动画，悬停态 / 进行中动画 / 选中态
        全部保留（指导文档 §4.1）。
        """
        for eid, icon in self.icons.items():
            entry = self.storage.find_entry(eid)
            if entry is None:
                continue
            icon.animate_to(*self._entry_pos(entry))

    def _sync_structure(self):
        """结构同步：storage.layout 与 self.icons 对齐（移除多余、补上
        缺失），再 _sync_icons 让位置变化走弹簧动画。

        替代业务路径里的 rebuild()——合并 / 解散 / 增删条目不再销毁重建
        全部 AppIcon。rebuild 只剩模式切换 / 图标大小变更 / 首屏这类
        「整体刷新」仪式场景。条目 type 变化（app→folder）无需重建图标：
        AppIcon.is_folder 是动态属性，直接读同一份 entry dict。
        """
        live = {e["id"] for e in self.storage.layout}
        for eid in [eid for eid in self.icons if eid not in live]:
            self._remove_icon(eid)
        for e in self.storage.layout:
            if e["id"] not in self.icons:
                self._add_icon(e)
        self._selected &= live
        self._sync_icons()

    # ---------- 多选 ----------
    def _on_icon_clicked(self, entry_id):
        ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        if ctrl:
            if entry_id in self._selected:
                self._selected.discard(entry_id)
            else:
                self._selected.add(entry_id)
        else:
            self._selected = {entry_id}
        self._refresh_selection()

    def _refresh_selection(self):
        for eid, icon in self.icons.items():
            icon.set_selected(eid in self._selected)

    def _select_in_rect(self, rect):
        """橡皮筋框选：与矩形相交即选中（Ctrl 追加）。"""
        if not (QApplication.keyboardModifiers() & Qt.ControlModifier):
            self._selected.clear()
        for eid, icon in self.icons.items():
            if rect.intersects(QRect(icon.pos(), icon.size())):
                self._selected.add(eid)
        self._refresh_selection()

    def _clear_selection(self):
        if self._selected:
            self._selected.clear()
            self._refresh_selection()

    # ---------- 拖拽 ----------
    def _on_drag_started(self):
        # 快照当前布局：拖动期间 preview 只改内存，取消时据此回退；
        # 提交时同一快照压入撤销栈（Ctrl+Z）
        self._layout_snap = [(e.get("id"), int(e.get("col", 0)), int(e.get("row", 0)))
                             for e in self.storage.layout]
        self._preview_moves = None
        self._preview_drag = None

    def _on_drag_finished(self):
        self._drag_active = False
        self._drag_entry_id = None
        self._drag_multi = False
        if self._preview_moves is not None:
            # 没有落点（拖到窗外 / 拖到资源管理器 / 按 Esc 取消）-> 回退
            self._cancel_preview()
        self.update()

    def _drag_payload_for(self, entry_id: str) -> str:
        """拖拽 payload：单选=条目 id；多选且拖的是选中成员=逗号分隔 id 集合。
        同时置 _drag_active：命中测试在此期间全窗口接收，保证 OLE 拖放能落下。"""
        self._drag_entry_id = entry_id
        self._drag_active = True
        if len(self._selected) > 1 and entry_id in self._selected:
            self._drag_multi = True
            return ",".join(sorted(self._selected))
        self._drag_multi = False
        return entry_id

    # ---------- 实时让位（Live Reflow） ----------
    def dragMoveEvent(self, e):
        """拖动经过空白格：按落点算一次让位预览并驱动其他图标弹簧滑行。

        这是「安卓式滑动让位」的实时性来源——不等松手，被越过的图标
        立即让出格子（design.md 2.3）。
        """
        if not e.mimeData().hasFormat(MIME_TYPE):
            return
        e.acceptProposedAction()
        dragged = e.mimeData().data(MIME_TYPE).data().decode()
        self._reflow_preview(dragged, self._cell_at(e.position().toPoint()))

    def _on_reflow_hover(self, dragged: str, gx: int, gy: int):
        """拖动悬停（2026-10-18 M2：参数是指针全局坐标，非图标格点）。

        目标格只从指针全局位置反算——预览会改写 entry，读移动中的
        entry 等于追逐漂移（指导文档 §2.3 病根 3）。
        """
        self._reflow_preview(dragged, self._cell_at(self.mapFromGlobal(QPoint(gx, gy))))

    def _on_reflow_drop(self, dragged: str, gx: int, gy: int):
        """在图标上松手且未武装合并：直接走让位提交。

        不能依赖 drop 事件从图标冒泡到本窗口（实测不传播），故由
        AppIcon.reflowDrop 直连（probe15 G11a）。参数为指针全局坐标。
        """
        self._reflow_commit_or_compute(dragged,
                                       self._cell_at(self.mapFromGlobal(QPoint(gx, gy))))

    # ---------- 锚定小组件占位（widget 是网格一等公民） ----------
    def _widget_cells(self):
        """可见锚定小组件占据的格子集合（从 storage 读，与实例解耦）。"""
        return grid_flow.widget_cells(self.storage)

    def on_widget_grid_changed(self):
        """小组件占位变化（落定/移动）：把被挤到的图标挪到第一个空格。

        用户描述"小组件占据格子位置，挤走其他对象"的直接实现：
        widget 松手吸附后 gridChanged -> 这里 displace -> 图标滑走。
        2026-10-18 M4：位移走弹簧动画（_animate_icons_to_layout），
        不再 rebuild——被挤图标只是换格子，实例/悬停态/动画全部保留。
        """
        moved = self._displace_from_widgets()
        if moved:
            self.storage.save()
            self._animate_icons_to_layout(moved)

    def _displace_from_widgets(self) -> dict:
        """把落在小组件占位格上的图标挪到第一个空格（排除组件占位）。
        返回 {id: (col,row)} 位移清单（空 = 无需 displace）。"""
        wc = self._widget_cells()
        if not wc:
            return {}
        moved = {}
        for e in self.storage.layout:
            if (int(e.get("col", 0)), int(e.get("row", 0))) in wc:
                col, row = self.storage.first_free_cell(extra_used=wc)
                e["col"], e["row"] = col, row
                moved[e["id"]] = (col, row)
        return moved

    # ---------- 锚定组件拖动实时预览（2026-10-18 M4） ----------
    def _widget_entry_rect(self, entry) -> set:
        """组件 entry 当前占位矩形（按 span 展开）。"""
        cs, rs = grid_flow.widget_span(self.storage, entry)
        col = max(0, int(entry.get("col", 0)))
        row = max(0, int(entry.get("row", 0)))
        return {(col + dc, row + dr) for dc in range(cs) for dr in range(rs)}

    def _restore_snap(self, snap):
        """按快照写回布局（仅内存；落盘由调用方决定）。"""
        by_id = {e.get("id"): e for e in self.storage.layout}
        for eid, col, row in snap:
            e = by_id.get(eid)
            if e is not None:
                e["col"], e["row"] = col, row

    def _on_widget_hover(self, widget_id: str, gx: int, gy: int):
        """锚定组件拖动悬停（widget_base.anchorHover，指针全局坐标）。

        与图标拖动同一套实时预览语义（M2）：按指针位置算组件新占位
        矩形，把矩形内图标实时挤到最近空格——组件跟着手指走，图标
        同步让位，不等松手。只改内存 + 动画；松手由 anchorDrop 回退，
        组件自身吸附落定后的 gridChanged 按最终占位做正式 displace。
        """
        entry = next((w for w in self.storage.widgets
                      if w.get("id") == widget_id), None)
        if entry is None or not entry.get("anchored") or entry.get("hidden"):
            return
        cs, rs = grid_flow.widget_span(self.storage, entry)
        col, row = self._cell_at(self.mapFromGlobal(QPoint(gx, gy)))
        col = max(0, min(col, self.storage.columns - cs))
        rect = {(col + dc, row + dr) for dc in range(cs) for dr in range(rs)}
        if self._widget_preview_rect == rect:
            return
        if self._widget_snap is None:
            # 进入预览：快照当前布局（松手回退基准）
            self._widget_snap = [(e.get("id"), int(e.get("col", 0)),
                                  int(e.get("row", 0)))
                                 for e in self.storage.layout]
        else:
            # 预览态连续移动：先回到快照再按新矩形 displace，
            # 否则上一次预览的挤位会叠加漂移
            self._restore_snap(self._widget_snap)
        # 其他组件的占位仍要避开；本组件的旧占位释放（图标可回填）
        blocked = rect | (self._widget_cells() - self._widget_entry_rect(entry))
        moves = {}
        for e in self.storage.layout:
            c, r = int(e.get("col", 0)), int(e.get("row", 0))
            if (c, r) in blocked:
                nc, nr = grid_flow.nearest_free_cell((c, r), blocked,
                                                     self.storage.columns)
                e["col"], e["row"] = nc, nr
                moves[e["id"]] = (nc, nr)
        self._widget_preview_rect = rect
        self._animate_icons_to_layout(moves)

    def _on_widget_drop(self, widget_id: str, gx: int, gy: int):
        """组件松手：预览态回退到快照（组件自身吸附落定后的
        gridChanged 会按最终占位做正式 displace + 动画）。
        组件没动（拖回原地）时也走这里——快照回退即原位。"""
        if self._widget_snap is not None:
            self._restore_snap(self._widget_snap)
        self._widget_snap = None
        self._widget_preview_rect = None
        self._sync_icons()

    def _reflow_preview(self, dragged_id: str, cell):
        """实时让位预览（2026-10-18 M2：iOS 局部让位，reflow_moves）。

        与旧 reflow_order 路径的区别：dragged **精确落到 target（含
        空格）**，只有新旧位置之间的图标滑动一格——修复 P2 病根 1
        （空格永不生效）与病根 2（拖到右侧空白被夹紧到最后一列 →
        半幅布局平移；现在 cols 由 GridMetrics 铺满，落点即所见）。
        目标格由调用方从指针全局位置反算（追逐漂移已消灭）。
        """
        if self._drag_multi or dragged_id is None:
            return
        if dragged_id not in self.icons:
            return
        cols = self.storage.columns
        # M6：不再传 rows=GridMetrics.rows——那是单屏行数，分页后目标行
        # 是全局行（可到 page*rpp + rpp-1），传了会把落点错夹回第 0 页
        # （probe21 S4 抓到：拖到 page1 底行落回 row 7）。落点限页由
        # pos_cell 的局部行夹紧保证，reflow 层不做行夹紧。
        moves = grid_flow.reflow_moves(self.storage.layout, cols, dragged_id, cell,
                                       rows=None,
                                       extra_occupied=self._widget_cells())
        if moves is None:
            return
        if moves == self._preview_moves:
            return  # 无变化不重算：dragMove 频率很高，省掉无用动画重启
        self._preview_moves = moves
        self._preview_drag = dragged_id
        # 只改内存：落盘发生在 drop（commit）或根本不来（cancel 回退）
        by_id = {e.get("id"): e for e in self.storage.layout}
        for eid, (c, r) in moves.items():
            e = by_id.get(eid)
            if e is not None:
                e["col"], e["row"] = c, r
        self._animate_icons_to_layout(moves, skip=dragged_id)

    def _animate_icons_to_layout(self, moves: dict, skip=None):
        """把发生位移的图标弹簧滑到新格（reduced-motion 时直接跳位）。

        只动画 moves 里的图标——位移集合最小化是 M2 的核心性质，
        顺带避免每次 dragMove 全量迭代 200 个图标。
        """
        for eid in moves:
            if eid == skip:
                continue
            icon = self.icons.get(eid)
            if icon is None:
                continue
            entry = self.storage.find_entry(eid)
            if entry is None:
                continue
            icon.animate_to(*self._entry_pos(entry))

    def _commit_preview(self):
        """落点有效：把 preview 写盘。图标已在位上，无需 rebuild。"""
        if self._preview_moves is None:
            return
        dragged = self._preview_drag
        self._push_undo(self._layout_snap)
        self.storage.save()
        if dragged and dragged in self.icons:
            entry = self.storage.find_entry(dragged)
            icon = self.icons[dragged]
            if entry is not None:
                icon.move(*self._entry_pos(entry))
            icon.set_drag_ghost(False)
        self._preview_moves = None
        self._preview_drag = None
        self._layout_snap = None

    def _push_undo(self, snap):
        """把改动前的布局快照压入撤销栈（Ctrl+Z 回退用，最多 20 步）。

        覆盖让位/多选平移等布局类操作（指导文档 §2.3/§5-P0-3；
        组件推动与文件夹增删成员在 M3-M5 接入同一条栈）。
        """
        if snap is None:
            return
        if self._undo_stack and self._undo_stack[-1] == snap:
            return  # 与栈顶相同不重复压
        self._undo_stack.append(snap)
        del self._undo_stack[:-20]

    def _undo_layout(self):
        """Ctrl+Z：回退到上一个布局快照，全体图标弹簧滑回。"""
        if not self._undo_stack:
            return
        snap = self._undo_stack.pop()
        by_id = {e.get("id"): e for e in self.storage.layout}
        for eid, col, row in snap:
            e = by_id.get(eid)
            if e is not None:
                e["col"], e["row"] = col, row
        self.storage.save()
        self._clear_preview()
        for eid, icon in self.icons.items():
            entry = by_id.get(eid)
            if entry is None:
                continue
            icon.animate_to(*self._entry_pos(entry), duration=220, damping=1.0)
        self.update()

    def _reflow_commit_or_compute(self, dragged_id: str, cell):
        """单选落位：有预览就直接提交（落点与预览一致，避免坐标反算偏差）；
        没有预览（拖动中未经 dragMove 直达）就按落点现算一次。

        2026-10-18 M4：两条路径都走 _commit_preview 的动画落位——
        不再 rebuild（实例保留：悬停态、进行中动画、选中态不丢；
        原来这里 rebuild 会把全场图标瞬间跳位，正是 P2 病根 4）。
        """
        if self._preview_moves is not None and self._preview_drag == dragged_id:
            self._commit_preview()
            return
        moves = grid_flow.reflow_moves(self.storage.layout, self.storage.columns,
                                       dragged_id, cell,
                                       extra_occupied=self._widget_cells())
        if not moves:
            self.storage.save()
            self._clear_preview()
            return
        by_id = {e.get("id"): e for e in self.storage.layout}
        for eid, (c, r) in moves.items():
            e = by_id.get(eid)
            if e is not None:
                e["col"], e["row"] = c, r
        # 借提交路径收尾：压撤销栈 + 落盘 + 动画落位 + 清预览
        self._preview_moves = moves
        self._preview_drag = dragged_id
        self._commit_preview()

    def _cancel_preview(self):
        """取消：按快照回退布局，所有图标弹簧滑回原位。"""
        snap, self._layout_snap = self._layout_snap, None
        self._preview_moves = None
        self._preview_drag = None
        if snap is None:
            return
        by_id = {e.get("id"): e for e in self.storage.layout}
        for eid, col, row in snap:
            e = by_id.get(eid)
            if e is not None:
                e["col"], e["row"] = col, row
        for eid, icon in self.icons.items():
            entry = by_id.get(eid)
            if entry is None:
                continue
            icon.animate_to(*self._entry_pos(entry), duration=220, damping=1.0)
            icon.set_drag_ghost(False)
        self.update()

    def _clear_preview(self):
        self._preview_moves = None
        self._preview_drag = None
        self._layout_snap = None

    # ---------- 业务 ----------
    def _on_activate(self, app):
        if app:
            appsource.launch(app)

    def _on_open_location(self, app):
        target = app.get("target", "")
        if target:
            appsource.reveal_in_explorer(target)

    def add_app(self, app: dict):
        # M6：新条目落到用户当前这一页的第一个空格（当前页满才回退
        # 全局第一个空格——否则用户在第 2 页点添加、图标加到第 0 页
        # 会"消失"）
        slot = grid_flow.first_free_cell_in_page(self.storage, self._page)
        if slot is not None:
            self.storage.add_app(app, *slot)
        else:
            self.storage.add_app(app)
        self.storage.save()
        # M4：增量新增（新图标淡入；指定格被占时的挤走位移走动画）
        self._sync_structure()

    def rescan_desktop(self):
        """重新扫描桌面文件：补新增、清丢失（仅布局，不动文件）。
        M4：增量同步——新增淡入 / 丢失移除 / compact 移位走弹簧动画。"""
        added, removed = self.storage.rescan_desktop()
        self._sync_structure()
        return added, removed

    def _on_remove_entry(self, entry_id):
        entry = self.storage.find_entry(entry_id)
        self.storage.remove_entry(entry_id)
        self._remove_icon(entry_id)     # M4：只移除目标图标实例
        self.storage.compact_layout()
        self.storage.save()
        self._sync_icons()              # compact 的补位动画
        # 桌面文件只是从整理布局移除，文件本身仍在桌面文件夹
        if entry and entry.get("app", {}).get("kind") == "file":
            from .tray import notify_via_tray  # 延迟导入避免循环
            notify_via_tray("已从整理桌面移除", "文件仍保留在桌面文件夹中，可通过「重新扫描桌面文件」找回")

    def _on_dissolve(self, entry_id):
        entry = self.storage.find_entry(entry_id)
        if not entry or entry.get("type") != "folder":
            return
        for app in entry.get("apps", []):
            self.storage.add_app(app)
        self.storage.remove_entry(entry_id)
        self.storage.compact_layout()
        self.storage.save()
        self._sync_structure()          # M4：成员增量淡入 + 文件夹图标移除

    def _on_merge(self, dragged_payload: str, target_id: str):
        # 合并会整体重排布局，让位预览失效
        self._clear_preview()
        target = self.storage.find_entry(target_id)
        if target is None:
            return

        # 拖的是文件夹成员（payload: "M:fid:idx"，M: 标记避免与含冒号的条目 id 混淆）
        # -> 并入目标
        if dragged_payload.startswith("M:"):
            fid, _, idx = dragged_payload[2:].rpartition(":")
            src = self.storage.find_entry(fid)
            if src is None or src.get("type") != "folder" or not idx.isdigit():
                return
            idx = int(idx)
            if not (0 <= idx < len(src.get("apps", []))):
                return
            app = src["apps"][idx]
            if target["type"] == "folder":
                if app not in target["apps"]:
                    target["apps"].append(app)
            else:
                members = [m for m in (target.get("app"), app) if m]
                target["type"] = "folder"
                target["app"] = None
                target["apps"] = members
            src["apps"].pop(idx)
            if not src["apps"]:
                self.storage.remove_entry(fid)
            self.storage.compact_layout()
            self.storage.save()
            self._sync_structure()     # M4：成员并入/空文件夹移除走增量
            if self._popup is not None:
                self._popup.refresh()
            return

        dragged = self.storage.find_entry(dragged_payload)
        if dragged is None or dragged["id"] == target["id"]:
            return

        if dragged["type"] == "folder" and target["type"] == "folder":
            self._absorb(target, dragged)
        elif target["type"] == "folder":
            self._absorb(target, dragged)
        elif dragged["type"] == "folder":
            self._absorb(dragged, target)
        else:
            members = [m for m in (target.get("app"), dragged.get("app")) if m]
            target["type"] = "folder"
            target["app"] = None
            target["apps"] = members
            self.storage.remove_entry(dragged["id"])
        self.storage.compact_layout()
        self.storage.save()
        # M4：合并是结构变化（条目移除 + type 变更）——增量同步。
        # target 的图标实例保留：AppIcon.is_folder 动态读 entry，自动
        # 按文件夹样式重绘，无需重建。
        self._sync_structure()
        if self._popup is not None:
            self._popup.refresh()

    def _absorb(self, folder_entry, other):
        members = other.get("apps", []) if other.get("type") == "folder" else [other.get("app")]
        for m in members:
            if m and m not in folder_entry["apps"]:
                folder_entry["apps"].append(m)
        self.storage.remove_entry(other["id"])

    # ---------- 文件夹弹窗 ----------
    def open_folder(self, entry_id):
        entry = self.storage.find_entry(entry_id)
        if not entry or entry.get("type") != "folder":
            return
        if self._popup is not None:
            if self._popup.entry.get("id") == entry_id:
                self._close_popup()      # 再次点击同一文件夹 = 关闭（iOS 语义）
                return
            self._close_popup()
        icon = self.icons.get(entry_id)
        anchor_rect = None
        if icon is not None:
            # 传图标完整全局矩形：液态玻璃弹窗的展开动画起点
            anchor_rect = QRect(icon.mapToGlobal(QPoint(0, 0)), icon.size())
        popup = FolderPopup(self.storage, entry, anchor_rect)
        popup.launchApp.connect(self._on_activate)
        popup.extractRequested.connect(self._on_extract)
        popup.removeMember.connect(self._on_remove_member)
        popup.memberAdded.connect(self._on_popup_member_added)
        popup.renamed.connect(lambda: self._refresh_folder_icon(entry_id))
        popup.tintChanged.connect(lambda: self._refresh_folder_icon(entry_id))
        popup.closed.connect(self._on_popup_closed)
        self._popup = popup
        popup.show()
        # M5：幕布先挂（弹窗下层层）——压暗桌面带内所有元素；点击幕布
        # 关闭弹窗（与 DesktopWindow 空白点击关闭双保险）。
        scrim = ScrimWindow()
        scrim.clicked.connect(self._close_popup)
        self._scrim = scrim
        scrim.show()
        scrim.fade_in()
        # 挂桌面带：不用 StaysOnTopHint（那会盖住所有应用窗口）。幕布与
        # 弹窗都插 Progman 正上方；弹窗再 attach_above_band() 插到桌面带
        # 内最顶（压得住整理窗口与所有小组件）。必须 insert_above_window
        # （普通窗口语义）：attach_to_desktop 的 below_hwnd 分支是插到
        # 参照窗口下方——弹窗在整理窗口之下会被其全窗口 HTCLIENT 命中
        # 测试挡住，点不到（2026-10-18 实测）。
        if self.attached:
            win32_layer.attach_to_desktop(scrim)
            self._band_guard.track(scrim)
            win32_layer.attach_to_desktop(popup)
            popup.attach_above_band()
            self._band_guard.track(popup)
        self._folder_open_icon = icon
        if icon is not None:
            icon.set_folder_open(True)

    def _close_popup(self):
        """主动关闭弹窗（切文件夹 / 同文件夹二击 / Esc / 幕布点击 / 隐藏桌面）。

        与 _on_popup_closed（弹窗自行关闭路径：× 按钮、空文件夹 refresh
        自动关等）分离：主动关闭先摘除 closed 信号——旧弹窗的收起动画
        要 200ms 才发 closed，不摘的话会误清随后新建的弹窗引用
        （open_folder 连续切换文件夹的竞态）。
        """
        popup = self._popup
        self._popup = None
        self._exit_folder_open_state()
        if popup is not None:
            try:
                popup.closed.disconnect(self._on_popup_closed)
            except Exception:
                pass
            popup.close()
        scrim = self._scrim
        self._scrim = None
        if scrim is not None:
            scrim.fade_out_then_close()

    def _on_popup_closed(self):
        """弹窗自行关闭后的收尾（closed 信号）：清引用 + 源图标退出
        打开态 + 幕布淡出销毁。幂等：_close_popup 已清场时为空操作。"""
        self._popup = None
        self._exit_folder_open_state()
        scrim = self._scrim
        self._scrim = None
        if scrim is not None:
            scrim.fade_out_then_close()

    def _exit_folder_open_state(self):
        """源图标退出打开态（高亮描边撤销）。图标可能已被增量移除
        （文件夹解散走 _remove_icon），deleteLater 后的部件访问抛
        RuntimeError——吞掉即可。"""
        icon = self._folder_open_icon
        self._folder_open_icon = None
        if icon is not None:
            try:
                icon.set_folder_open(False)
            except RuntimeError:
                pass

    def _refresh_folder_icon(self, entry_id):
        """重命名 / 换色后刷新源图标（标签 + tooltip + 渐变重绘）。"""
        icon = self.icons.get(entry_id)
        if icon is not None:
            try:
                icon.refresh_meta()
            except RuntimeError:
                pass

    def _on_popup_member_added(self, entry_id):
        """＋ 添加面板 / 拖入：桌面条目并入文件夹。成员 apps 的追加由
        popup._add_member_by_id 完成，这里只把桌面上的源条目移出布局
        （M4 增量：不 rebuild）。"""
        e = self.storage.find_entry(entry_id)
        if e is None:
            return
        self.storage.remove_entry(entry_id)
        self.storage.compact_layout()
        self.storage.save()
        self._sync_structure()

    def _on_extract(self, payload: str):
        """把文件夹成员拖出到桌面（落到哪个格子就用哪个格子）。
        payload: "M:fid:idx" 或 "fid:idx"（M: 标记可带可不带；
        fid 自身可能含冒号，故 rpartition 从最后一个冒号切）。"""
        if payload.startswith("M:"):
            payload = payload[2:]
        fid, _, idx = payload.rpartition(":")
        folder = self.storage.find_entry(fid)
        if not folder or folder.get("type") != "folder" or not idx.isdigit():
            return
        idx = int(idx)
        if not (0 <= idx < len(folder.get("apps", []))):
            return
        app = folder["apps"].pop(idx)
        self.storage.add_app(app)
        if not folder["apps"]:
            self.storage.remove_entry(fid)
        self.storage.compact_layout()
        self.storage.save()
        self._sync_structure()          # M4：提取成员增量淡入 + 空文件夹移除
        # M5：文件夹被解散时 refresh 自动关弹窗；仍有成员时刷新成员网格
        if self._popup is not None:
            self._popup.refresh()

    def _on_remove_member(self, payload: str):
        """文件夹内右键移出成员。payload: "M:fid:idx" 或 "fid:idx"。"""
        if payload.startswith("M:"):
            payload = payload[2:]
        fid, _, idx = payload.rpartition(":")
        folder = self.storage.find_entry(fid)
        if not folder or folder.get("type") != "folder" or not idx.isdigit():
            return
        idx = int(idx)
        if 0 <= idx < len(folder.get("apps", [])):
            folder["apps"].pop(idx)
            if not folder["apps"]:
                self.storage.remove_entry(fid)
        self.storage.save()
        self._sync_structure()          # M4：空文件夹移除走增量
        # M5：同上——解散自动关，否则刷到空态
        if self._popup is not None:
            self._popup.refresh()

    # ---------- 拖放 ----------
    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasFormat(MIME_TYPE) or md.hasUrls():
            if md.hasUrls():
                # 外部文件拖入：整个窗口作为放置目标（否则空白格 drop 丢失）
                self._ole_active = True
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._ole_active = False
        e.accept()

    def dropEvent(self, e):
        md = e.mimeData()
        if md.hasFormat(MIME_TYPE):
            self._drop_internal(md.data(MIME_TYPE).data().decode(), e.position().toPoint())
        elif md.hasUrls():
            self._drop_files(md.urls(), e.position().toPoint())
        e.acceptProposedAction()
        # 无论内部拖拽的 dragFinished 信号是否送达（拖拽源可能已被
        # rebuild 删除），drop 完成后拖动状态一律复位
        self._drag_active = False
        self._drag_multi = False
        self._ole_active = False

    def _drop_internal(self, payload: str, pos):
        # 文件夹成员提取（payload: "M:fid:idx"）：M: 标记与含冒号的条目 id 消歧
        if payload.startswith("M:"):
            self._clear_preview()
            self._on_extract(payload[2:])
            return
        ids = [p for p in payload.split(",") if p]
        entries = [e for e in (self.storage.find_entry(i) for i in ids) if e is not None]
        if not entries:
            self._clear_preview()
            return

        if len(entries) == 1 and not self._drag_multi:
            # 单选：走让位（拖动期间已生成预览 -> 直接提交）
            self._reflow_commit_or_compute(entries[0]["id"], self._cell_at(pos))
            return

        # 多选：整体平移语义（让位置换对 N 个图标有歧义，不混用）
        self._push_undo(self._layout_snap)
        primary = entries[0]
        old_col, old_row = int(primary.get("col", 0)), int(primary.get("row", 0))
        col, row = self._cell_at(pos)
        dcol, drow = col - old_col, row - old_row
        occupant = self.storage.occupant(col, row, exclude_id=primary["id"])
        if occupant is not None and occupant["id"] not in self._selected:
            occupant["col"], occupant["row"] = old_col, old_row
        primary["col"], primary["row"] = col, row
        for e in entries[1:]:
            nc = max(0, min(self.storage.columns - 1, int(e.get("col", 0)) + dcol))
            nr = max(0, int(e.get("row", 0)) + drow)
            occ = self.storage.occupant(nc, nr, exclude_id=e["id"])
            if occ is None or occ["id"] in self._selected:
                e["col"], e["row"] = nc, nr
        self.storage.save()
        self._clear_preview()
        # M4：多选平移是位置类变化——动画到位，不 rebuild。
        # 注意逐个复位拖拽幽灵态：增量路径不再销毁图标实例，
        # set_drag_ghost(True) 的残影必须显式清掉。
        for e in entries:
            icon = self.icons.get(e["id"])
            if icon is None:
                continue
            icon.set_drag_ghost(False)
            icon.animate_to(*self._entry_pos(e))
        self.update()

    def _drop_files(self, urls, pos):
        """从资源管理器拖入文件：已在桌面的直接克隆，不在的先移入桌面文件夹。"""
        col, row = self._cell_at(pos)
        added = 0
        for url in urls:
            path = url.toLocalFile()
            if not path or not os.path.exists(path):
                continue
            try:
                if not appsource.on_desktop(path):
                    path = appsource.move_to_desktop(path)
                self.storage.add_app(appsource.desktop_file_entry(path), col, row)
                added += 1
                col += 1
                if col >= self.storage.columns:
                    col, row = 0, row + 1
            except Exception:
                continue
        if added:
            self.storage.save()
            self._sync_structure()      # M4：拖入文件增量淡入 + 被挤位移动画
            from .tray import notify_via_tray
            notify_via_tray("已添加到整理桌面", "新增 %d 个项目" % added)

    # ---------- 背景右键 / 按键 ----------
    def contextMenuEvent(self, e):
        """桌面空白处右键菜单。

        整理模式（路线A）下原生桌面右键被我们接管（nativeEvent 全窗口
        HTCLIENT），Windows 原生的「新建文件夹 / 刷新 / 个性化 / 显示设置」
        全部消失——2026-10-18 用户反馈"桌面右键功能也没了"。这里自绘补齐：
        真实可用的新建（create_on_desktop 真创建 + shell 刷新）、系统设置
        页（ms-settings URI 走 explorer 解析）、以及本软件功能。
        """
        menu = QMenu(self)
        menu.setStyleSheet(theme.MENU_QSS)
        if self._organize_mode():
            menu.addAction("新建文件夹", lambda: self._create_on_desktop("新建文件夹", True))
            menu.addAction("新建文本文档", lambda: self._create_on_desktop("新建文本文档.txt", False))
            menu.addSeparator()
            menu.addAction("重新扫描桌面文件", self.rescan_desktop)
            size_menu = menu.addMenu("图标大小")
            for label, px in (("大", 96), ("中", 72), ("小", 56)):
                act = size_menu.addAction(label)
                act.triggered.connect(lambda checked=False, v=px: self._set_icon_size(v))
            menu.addSeparator()
            menu.addAction("显示设置", lambda: self._open_uri("ms-settings:display"))
            menu.addAction("个性化（桌面背景）",
                           lambda: self._open_uri("ms-settings:personalization-background"))
            menu.addAction("打开桌面文件夹", self._open_desktop_folder)
            menu.addSeparator()
        menu.addAction("添加应用…", self.openAddAppsRequested.emit)
        menu.addAction("整理布局", self._tidy)
        if self._selected:
            menu.addAction("删除选中（%d）" % len(self._selected), self._remove_selected)
        menu.addAction("设置…", self.openSettingsRequested.emit)
        menu.addSeparator()
        if self._organize_mode():
            menu.addAction("恢复系统原生桌面图标", self._exit_organize_mode)
        menu.addAction("隐藏桌面整理", self.hide_desktop)
        menu.exec(e.globalPos())

    def _create_on_desktop(self, name: str, is_dir: bool):
        """右键新建：真实创建到桌面目录，然后重扫让网格立即出现。"""
        try:
            appsource.create_on_desktop(name, is_dir)
        except Exception:
            return
        added, _ = self.rescan_desktop()

    def _set_icon_size(self, px: int):
        self.storage.set_setting("icon_size", int(px))
        self.rebuild(stagger=True)

    @staticmethod
    def _open_uri(uri: str):
        """ms-settings: 等系统 URI 走 explorer 解析（最稳，无需注册协议）。"""
        try:
            QProcess.startDetached("explorer", [uri])
        except Exception:
            pass

    def _open_desktop_folder(self):
        folders = appsource._desktop_folders()
        if folders:
            try:
                os.startfile(str(folders[0]))
            except Exception:
                pass

    def _exit_organize_mode(self):
        """退出整理模式：恢复原生图标显示（设置同步）。"""
        self.storage.set_setting("hide_native_icons", False)
        self._sync_native_icons()

    def _remove_selected(self):
        for eid in list(self._selected):
            self.storage.remove_entry(eid)
            self._remove_icon(eid)
        self._selected.clear()
        self.storage.compact_layout()
        self.storage.save()
        self._sync_icons()              # M4：批量移除后 compact 补位走动画

    def _tidy(self):
        self.storage.tidy_layout()
        self.storage.save()
        self.rebuild(stagger=True)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide_desktop()
        elif e.key() == Qt.Key_Delete and self._selected:
            self._remove_selected()
        elif e.key() == Qt.Key_A and (e.modifiers() & Qt.ControlModifier):
            self._selected = set(self.icons.keys())
            self._refresh_selection()
        elif e.key() == Qt.Key_Z and (e.modifiers() & Qt.ControlModifier):
            # Ctrl+Z：布局撤销（让位 / 多选平移，指导文档 §2.3）
            self._undo_layout()

    def closeEvent(self, e):
        self._band_guard.untrack(self)
        if self.storage.get_setting("minimize_to_tray"):
            e.ignore()
            self.hide_desktop()
        else:
            self.quitRequested.emit()
            e.accept()
