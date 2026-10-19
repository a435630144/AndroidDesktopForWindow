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
from . import drag_merge
from . import grid_flow
from . import theme
from . import win32_layer
from .band_guard import BandGuard
from .folder_popup import FolderPopup, ScrimWindow
from .iconwidget import DWELL_MERGE_MS, MIME_TYPE, AppIcon
from .storage import Storage
from .win32_layer import attach_to_desktop

WM_NCHITTEST = 0x84
HTTRANSPARENT, HTCLIENT = -1, 1

# 拥挤推让的悬停时长（ms）：拖到别人格子上停这么久，对方实时让开。
# 2026-10-20 用户反馈 F3："想合并却先被挤走"——旧值 260ms 比合并武装
# （DWELL_MERGE_MS=450ms）**短**，拖影抖动一下掉回"擦边"目标就被推走，
# 合并提示永远等不到。改成 dwell + 250ms：**提示先出现，推让后到**。
# 另外压住目标图标本身（重叠 ≥ MERGE_ARM_RATIO）时干脆不推让，
# 见 `_reflow_preview`。
PUSH_DWELL_MS = DWELL_MERGE_MS + 250


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
        # v6 §5.2：拖动中目标 cell 红框高亮（判定结果可见、可预期）
        self._hl_cell = None
        self.icons = {}
        # v6 §4：图标当前构建所用的 IconLayout 签名（快照就绪前后 cell
        # 变化时检测到即重建——启动时 rebuild 早于 GridMetrics，旧 chrome
        # 路径尺寸 96×112 会大于 cell 75×92 互相重叠）
        self._icon_layout_sig = None
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
        # 拥挤推让（2026-10-19 反馈 9）：拖到**别人的格子**上停一会儿，对方
        # 实时让开（手机 launcher 的"边缘重叠 → 挤走"）；停在图标中心则
        # 由目标图标自己 450ms 武装合并提示（AppIcon._dwell）。两个手势靠
        # 拖影与目标的重叠比例分流，见 iconwidget._drag_move。
        self._push_timer = QTimer(self)
        self._push_timer.setSingleShot(True)
        self._push_timer.setInterval(PUSH_DWELL_MS)
        self._push_timer.timeout.connect(self._push_occupied)
        self._push_cell = None
        self._push_dragged = None
        # WindowDoesNotAcceptFocus(WS_EX_NOACTIVATE)：永不被激活，
        # 保证桌面带窗口永远压在应用窗口之下，不会抢焦点 / 置顶。
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setWindowTitle("桌面整理Demo")
        # 桌面带守护：Win+D / 切屏等导致漂移时自动拉回桌面带
        self._band_guard = BandGuard(self, on_tick=self._on_guard_tick)
        # 桌面目录监听（v6 §7.4）：由 set_auto_sync 按设置启停，不在构造时启动
        # （测试 / 探针直接构造窗口，不该被动起文件监听）
        self._watcher = None
        # 载入时规整一次，避免越界 / 重叠
        self.storage.compact_layout()
        self.rebuild(stagger=True)  # 首次显示错峰淡入

    # ---------- 模式 ----------
    def _organize_mode(self) -> bool:
        """桌面整理模式 = 「接管系统桌面」开关（v6 §7.2 唯一入口）。

        开：隐藏原生图标，由本窗口全盘接管（框选 / 自己的右键菜单）；
        关：仅悬浮，原生桌面照常可用。
        """
        return self.storage.takeover()

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
        if attach_to_desktop(self, layer=win32_layer.BAND_LAYER_DESKTOP):
            self.attached = True
            self._band_guard.track(self, layer=win32_layer.BAND_LAYER_DESKTOP)
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
        attach_to_desktop(self, layer=win32_layer.BAND_LAYER_DESKTOP)
        win32_layer.enforce_band_order()
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
        """按「接管系统桌面」开关隐藏 / 恢复系统原生桌面图标（克隆模式核心）。"""
        hide = self.storage.takeover()
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
        if self.storage.takeover() and self.isVisible():
            # 三重巡检（2026-10-19）：
            #   1) 缓存标志——进程内我们自己知道的隐藏状态；
            #   2) 图标列表实查——explorer 重启 / 重建 SysListView32 后句柄
            #      会换，缓存标志仍是 True 却已经露出图标；
            #   3) 第三方桌面层——腾讯桌面整理等会把自绘图层重新 SHOW 回来。
            if (not win32_layer.native_icons_hidden()
                    or win32_layer.native_icon_list_visible()
                    or win32_layer.third_party_overlays_visible()):
                win32_layer.set_native_icons_visible(False)
        if self.attached and self.isVisible():
            geo = QApplication.primaryScreen().availableGeometry()
            if (geo.width(), geo.height()) != (self.width(), self.height()):
                self.setGeometry(geo)
                self._update_grid_metrics()

    def paintEvent(self, event):
        hl = self._hl_cell is not None
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
            if hl:
                self._paint_highlight(event)   # v6 §5.2：目标格红框置顶
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
        if hl:
            self._paint_highlight(event)

    def _paint_highlight(self, event):
        """v6 §5.2：目标 cell 红框（2px 描边 + 8% 红填充，圆角与网格语言一致）。"""
        col, row = self._hl_cell
        x, y = grid_flow.cell_pos(self.storage, col, row)
        cw, ch = grid_flow.cell_size(self.storage)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(theme.DANGER, 2))
        p.setBrush(QColor(theme.DANGER.red(), theme.DANGER.green(),
                          theme.DANGER.blue(), 20))
        p.drawRoundedRect(QRect(x + 1, y + 1, cw - 2, ch - 2), 8, 8)

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
        # 点桌面 = 退出组件编辑态（安卓语义：点空白结束编辑）
        if self._widget_layer is not None:
            try:
                self._widget_layer.exit_all_edit()
            except RuntimeError:
                pass
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
            dx = e.angleDelta().x()
            # 左右翻页模式下触控板横向滑动同样翻页（y 仍兼容鼠标滚轮）
            delta = dy if abs(dy) >= abs(dx) else dx
            if abs(delta) >= 15:
                self.goto_page(self._page + (-1 if delta < 0 else 1))
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
                if self._drag_active or self._ole_active:
                    return True, HTCLIENT
                x = ctypes.c_int16(msg.lParam & 0xFFFF).value
                y = ctypes.c_int16((msg.lParam >> 16) & 0xFFFF).value
                pt = QPoint(x, y)
                # 小组件矩形：让出命中（反馈 1）。带内层号已经保证组件压在
                # 整理窗口之上，这里是**兜底**——层序尚未生效的那一两百毫秒
                # 里，也不该让全屏窗口把组件上的点击 / 右键吞掉。
                if self._hit_widget(pt):
                    return True, HTTRANSPARENT
                if self._organize_mode():
                    return True, HTCLIENT
                pad = int(round(14 * self.storage.icon_chrome_scale()))
                for icon in self.icons.values():
                    r = QRect(icon.mapToGlobal(QPoint(0, 0)), icon.size())
                    if r.adjusted(-pad, -pad, pad, pad).contains(pt):
                        return True, HTCLIENT
                return True, HTTRANSPARENT
        return super().nativeEvent(eventType, message)

    def _hit_widget(self, global_pos) -> bool:
        """命中点是否落在某个可见小组件窗口内（nativeEvent 兜底放行用）。"""
        layer = self._widget_layer
        if layer is None:
            return False
        try:
            items = list(layer.widgets.values())
        except Exception:
            return False
        for w in items:
            try:
                if not w.isVisible():
                    continue
                r = QRect(w.mapToGlobal(QPoint(0, 0)), w.size())
                if r.contains(global_pos):
                    return True
            except RuntimeError:
                continue
        return False

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

        v6 §4/A2 连带（probe23 S0 抓到的真 bug）：启动时 __init__ 的
        rebuild 早于快照就绪，图标走旧 chrome 路径（96×112 > cell
        75×92，同列图标互相重叠）；快照就绪后 cell 变 -> 三档 layout
        也变，只 move 不重建尺寸永远是旧的。快照就绪且 layout 签名
        变化时整体重建一次（仅发生在启动 / DPI 变化，日常拖拽位移
        不走本路径，实例保留语义不受影响）。
        """
        before = grid_flow.current_metrics()
        grid_flow.set_grid(self.storage, (self.width(), self.height()))
        after = grid_flow.current_metrics()
        self._clamp_page()
        layout = self._icon_layout()
        if layout != self._icon_layout_sig:
            self._icon_layout_sig = layout
            if self.icons:
                self.rebuild()
            return
        if before is not None and before == after:
            return
        for eid, icon in self.icons.items():
            entry = self.storage.find_entry(eid)
            if entry is not None:
                icon.move(*self._entry_pos(entry))
        self._cull_page_icons()
        if self._widget_layer is not None:
            self._widget_layer.sync_page(self._page)
        self.update()

    def refresh_grid(self):
        """网格参数（列数 / 档位 / 图标像素）变更后立即重算并重排。

        反馈 2（2026-10-19）：「软件调整完网格尺寸之后，应该自动刷新而不是
        需要手动关闭才开启接管」。旧设置路径只调 rebuild()，而 rebuild
        读的是 `grid_flow.current_metrics()` **旧快照**——cell / cols 没重算，
        图标位置尺寸全是老值；用户只能关掉「接管系统桌面」再打开
        （走 _try_attach_once -> _update_grid_metrics）才看到变化。

        这里把「重算快照 + 按新几何重建 + 组件重新落位」收成一个入口，
        设置面板与桌面右键的图标大小入口统一调用。
        """
        # 用惰性哨兵让 _update_grid_metrics 走 rebuild 分支（签名必不等），
        # 避免"先重算再额外 rebuild 一次"的双重建
        self._icon_layout_sig = object()
        self._update_grid_metrics()
        if self._widget_layer is not None:
            self._widget_layer.apply_layout_mode()
        self.update()

    def resizeEvent(self, event):
        # M1：窗口几何变化（挂载后铺满工作区 / 悬浮兜底 / 显示器几何变化）
        # 时重算网格。未挂载时窗口尺寸无网格意义，跳过。
        super().resizeEvent(event)
        if self.attached:
            self._update_grid_metrics()

    def _entry_pos(self, entry):
        # M6：列夹紧 + 页内局部行映射统一在 grid_flow.cell_pos（DRY）；
        # v6 §1.3：双模式唯一入口（无界模式读 fx/fy + 页间偏移）
        return grid_flow.entry_pos(self.storage, entry)

    def _cell_at(self, pos):
        # M6：反算含当前页偏移（页内 y -> 全局 row），委托 grid_flow
        return grid_flow.pos_cell(self.storage, pos.x(), pos.y())

    def _drag_cell(self, fallback: QPoint):
        """v6 §5.2 落点判定：拖动图标框（浮动拖影矩形）vs 候选 cell 面积最大。

        拖影是拖动图标的视觉化身（位置 = 光标 - 抓取偏移），它的矩形
        就是规格说的「拖动图标框」。无拖影时退化为指针所在格
        （_cell_at 旧语义）——合成 drop / 外部文件 OLE 拖入 / 探针
        直调都走这条，保持既有行为不变。
        """
        icon = self.icons.get(self._drag_entry_id or "")
        ghost = getattr(icon, "_drag_ghost_w", None) if icon is not None else None
        if ghost is None:
            return self._cell_at(fallback)
        g = ghost.geometry()                # frameless 顶层：全局矩形
        tl = self.mapFromGlobal(g.topLeft())
        return grid_flow.cell_by_overlap(
            self.storage, (tl.x(), tl.y(), g.width(), g.height()))

    def _drag_overlap_on_cell(self, dragged_id: str, cell,
                              ghost_rect=None) -> float:
        """拖影与**目标格上那个图标**的重叠比（0~1）。

        2026-10-20 用户反馈 F3 的判定入口：拖影实质压住目标（≥
        `drag_merge.MERGE_ARM_RATIO`）时要保住目标、等合并提示；只有擦边
        才允许"悬停够久把他挤走"。

        ghost_rect 可注入（QRect，全局坐标）：真实拖动取浮动拖影；
        无拖影（合成 drop / 探针直调）返回 0.0 —— 退化为"照常推让"，
        不改变既有测试与外部拖入的行为。
        """
        if ghost_rect is None:
            icon = self.icons.get(dragged_id or "")
            ghost = getattr(icon, "_drag_ghost_w", None) if icon else None
            if ghost is None:
                return 0.0
            try:
                ghost_rect = ghost.geometry()
            except RuntimeError:
                return 0.0
        occ = self.storage.occupant(cell[0], cell[1], exclude_id=dragged_id)
        if occ is None:
            return 0.0
        target = self.icons.get(occ.get("id"))
        if target is None:
            return 0.0
        try:
            r = QRect(target.mapToGlobal(QPoint(0, 0)), target.size())
        except RuntimeError:
            return 0.0
        return drag_merge.overlap_ratio(
            (ghost_rect.x(), ghost_rect.y(),
             ghost_rect.width(), ghost_rect.height()),
            (r.x(), r.y(), r.width(), r.height()))

    def _set_highlight(self, cell):
        """v6 §5.2：目标 cell 红框。只在跨格时重绘——dragMove 是高频
        事件，全屏窗口每次 update() 都贵，跨格才换目标。"""
        if cell != self._hl_cell:
            self._hl_cell = cell
            self.update()

    def _drag_pos(self, fallback: QPoint):
        """拖影左上角的窗口坐标（v6 §1.3 无界松手落点用）。

        与 _drag_cell 同一取源：浮动拖影 = 拖动图标的视觉化身。无拖影
        （合成 drop / 探针直调）退化为指针位置。
        """
        icon = self.icons.get(self._drag_entry_id or "")
        ghost = getattr(icon, "_drag_ghost_w", None) if icon is not None else None
        if ghost is None:
            return fallback
        return self.mapFromGlobal(ghost.geometry().topLeft())

    def _free_drop(self, ids, pos):
        """无界模式松手（v6 §1.3）：整块按拖影位移量平移到像素位。

        单选/多选同一条语义：主条目（_drag_entry_id，回退 payload 首个）
        落到 pos（夹紧进当前页画布），其余选中成员保持**相对偏移**平移
        （与 §5.0 多选的形状保持同语言）；row 同步为当前页载体。
        不吸附、不避让、可重叠；不走撤销栈外的任何重排。
        """
        page = grid_flow.current_page()
        rpp = grid_flow.rows_per_page()
        canvas_h = grid_flow.page_canvas_h(self.storage)
        primary = self._drag_entry_id if self._drag_entry_id in ids else ids[0]
        pent = self.storage.find_entry(primary)
        if pent is None:
            return
        picon = self.icons.get(primary)
        pw = picon.width() if picon is not None else 0
        ph = picon.height() if picon is not None else 0
        # 主条目新位置（夹紧进画布：x∈[0,W-w]，y∈[0,画布高-h]）
        nx = max(0, min(int(pos.x()), max(0, self.width() - pw)))
        ny = max(0, min(int(pos.y()), max(0, canvas_h - ph)))
        # 位移量 = 新位置 - 拖动前位置（拖动前位置在 entry.fx/fy，预览在
        # 无界模式下不改写布局，读到的就是拖动前的值）
        dx = nx - int(pent.get("fx", 0) or 0)
        dy = ny - int(pent.get("fy", 0) or 0)
        moved = {}
        for eid in ids:
            e = self.storage.find_entry(eid)
            if e is None:
                continue
            icon = self.icons.get(eid)
            w = icon.width() if icon is not None else 0
            h = icon.height() if icon is not None else 0
            e["fx"] = max(0, min(int(e.get("fx", 0) or 0) + dx,
                                 max(0, self.width() - w)))
            e["fy"] = max(0, min(int(e.get("fy", 0) or 0) + dy,
                                 max(0, canvas_h - h)))
            e["row"] = page * rpp        # 页载体：松手即落入当前页
            moved[eid] = (e["fx"], e["fy"])
        if not moved:
            return
        self._push_undo(self._layout_snap)
        self.storage.save()
        for eid, (fx, fy) in moved.items():
            icon = self.icons.get(eid)
            if icon is not None:
                icon.animate_to(fx, fy)
                icon.set_drag_ghost(False)
        self._cull_page_icons()
        self._clear_preview()
        self.update()

    def set_layout_mode(self, mode: str):
        """v6 §1.3：切换网格 / 无界模式（托盘 + 桌面右键入口）。

        双坐标换算（grid_flow.to_free_coords / to_grid_coords）后整体
        rebuild——图标尺寸体系（三档 layout ↔ 用户像素值）与组件占位
        语义都随模式变，只有重建能一次性换干净；翻页状态夹回合法页。

        2026-10-19 反馈 3：判定按**有效模式**（未接管时 grid 设置值也
        算无界）。用户主动切「网格模式」意味着要网格——网格必须由
        接管承载（原生图标不隐藏会出现两套图标），故自动开启接管。
        """
        mode = "free" if str(mode) == "free" else "grid"
        if (mode == "free") == grid_flow.free_mode(self.storage):
            return
        if mode == "grid" and not self.storage.takeover():
            self.storage.set_takeover(True)
            self._sync_native_icons()
        self.storage.set_setting("layout_mode", mode)
        if mode == "free":
            grid_flow.to_free_coords(self.storage)
        else:
            grid_flow.to_grid_coords(self.storage)
        self.storage.save()
        self.rebuild(stagger=True)      # 模式切换的仪式感：错峰淡入
        self._clamp_page()
        if self._widget_layer is not None:
            self._widget_layer.apply_layout_mode()
        self.update()

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

    def set_page_axis(self, axis: str):
        """切换翻页方向（2026-10-19 反馈 5）：horizontal（默认）/ vertical。

        页容量不变，只换页与页之间的滑行轴。切换后立刻按新方向重排——
        无动画（直接 move），避免"从屏幕外飞进来"的错位感；组件走
        WidgetLayer.sync_page 与新方向对齐。
        """
        axis = "vertical" if str(axis).strip().lower() == "vertical" else "horizontal"
        self.storage.set_setting("page_axis", axis)
        for eid, icon in self.icons.items():
            entry = self.storage.find_entry(eid)
            if entry is not None:
                icon.move(*self._entry_pos(entry))
        if self._widget_layer is not None:
            self._widget_layer.sync_page(self._page)
        self.update()

    def goto_page(self, page, animate=True):
        """翻到指定页：运行时页同步 + 持久化 + 全体弹簧滑到新页位置。

        翻页动画 = M4 位移引擎复用：图标 animate_to 新位置（实例不变），
        组件经 WidgetLayer.sync_page 同向滑动——当前页内容滑出屏、
        邻页内容滑入屏（iOS launcher 语言）。animate=False 用于启动
        夹紧等无仪式场景（直接 move，不播动画）。

        v6 §4 分页禁半截：桌面窗口 = 工作区大小，网格四边等距铺满，
        上下边距（约半格）放不下一整格图标——邻页图标静止态会从屏底/
        屏顶露半截（子控件只被裁到窗口边缘，裁不到网格带）。因此：
        滑入页图标先显示（隐藏窗口的动画不可见），滑出页图标动画结束
        后隐藏（_hide_if_offpage 以**当前页**复核，防连翻中页号已变）。
        """
        page = max(0, int(page))
        page = min(page, grid_flow.page_count(self.storage) - 1)
        if page == self._page:
            return
        self._page = page
        grid_flow.set_page(page)
        self.storage.set_setting("current_page", page)
        rpp = grid_flow.rows_per_page()
        lo = self._page * rpp
        hi = lo + rpp - 1
        hide_after = []
        for eid, icon in self.icons.items():
            entry = self.storage.find_entry(eid)
            if entry is None:
                continue
            row = int(entry.get("row", 0) or 0)
            on_page = lo <= row <= hi
            if animate:
                if on_page and icon.isHidden():
                    icon.show()          # 滑入前先显示（否则滑入不可见）
                anim = icon.animate_to(*self._entry_pos(entry))
                if not on_page and not icon.isHidden():
                    if anim is not None:
                        hide_after.append((icon, row, anim))
                    else:
                        icon.hide()      # 无动画（已在位/reduced-motion）
            else:
                icon.move(*self._entry_pos(entry))
                icon.setVisible(on_page)
        for icon, row, anim in hide_after:
            anim.finished.connect(lambda icon=icon, row=row:
                                  self._hide_if_offpage(icon, row))
        if self._widget_layer is not None:
            self._widget_layer.sync_page(page)
        self.update()

    def _hide_if_offpage(self, icon, row: int):
        """翻页滑行结束：该图标若仍不在当前页则隐藏（v6 §4）。

        连翻（滑行中再次翻页）时页号可能已变——以当前页为准复核，
        避免把新页图标误隐藏。
        """
        rpp = grid_flow.rows_per_page()
        if grid_flow.page_of(int(row), rpp) != grid_flow.current_page():
            icon.hide()

    def _cull_page_icons(self):
        """v6 §4 分页禁半截：只显示当前页图标，其余页隐藏。

        桌面窗口 = 工作区大小，网格四边等距铺满后上下边距（约半格）
        放不下一整格图标——邻页首/末行图标静止态会从屏底/屏顶露半截。
        rebuild / 新增 / rescan / DPI 变化后复核；翻页滑行期间可见
        （动画语言），滑停由 goto_page/_hide_if_offpage 收编。
        """
        rpp = grid_flow.rows_per_page()
        page = grid_flow.current_page()
        for eid, icon in self.icons.items():
            entry = self.storage.find_entry(eid)
            if entry is None:
                continue
            row = int(entry.get("row", 0) or 0)
            icon.setVisible(grid_flow.page_of(row, rpp) == page)

    def _cull_moved_icons(self, moves: dict):
        """按位移清单复核可见性（v6 §4）：落到当前页的显示、别页的隐藏。

        拖动预览路径用（O(位移数)）：多选块跨页拖动时，成员落到当前页
        要立即可见，落到别页立即收编——只动 moves 里的图标，不跑全量。
        """
        rpp = grid_flow.rows_per_page()
        page = grid_flow.current_page()
        for eid in moves:
            entry = self.storage.find_entry(eid)
            icon = self.icons.get(eid)
            if entry is None or icon is None:
                continue
            row = int(entry.get("row", 0) or 0)
            icon.setVisible(grid_flow.page_of(row, rpp) == page)

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
    def _icon_size(self):
        """图标绘制边长（双模式，v6 §1.2/§1.3）。

        网格模式 = storage.icon_metric()（DPI × 用户缩放感知；三档 layout
        再按 cell 比例裁 widget 整体）；无界模式 = 用户像素值 icon_px
        **直接生效**（规格 §1.2：设置内数字输入，不过档位公式）。
        """
        if grid_flow.free_mode(self.storage):
            return max(24, int(self.storage.get_setting("icon_px") or 96))
        return self.storage.icon_metric()

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
        size = self._icon_size()                 # v6 §1.3：双模式图标边长
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
        self._cull_page_icons()      # v6 §4：只显示当前页（禁半截）
        self.update()

    # ---------- 增量更新（2026-10-18 M4：去 rebuild 化） ----------
    def _icon_layout(self):
        """网格模式图标 layout（v6 A2，指导文档 §2.2）。

        档位（storage.icon_tier）× 当前 cell（GridMetrics 快照，屏幕驱动）
        -> grid_sizing.IconLayout；快照未就绪返回 None（回退旧 chrome 路径）。

        v6 §1.3：无界模式返回 None——图标尺寸走用户像素值（icon_px）
        直接生效 + legacy chrome 路径（AppIcon 不传 layout 的行为）。
        """
        from . import grid_sizing
        if grid_flow.free_mode(self.storage):
            return None
        m = grid_flow.current_metrics()
        if m is None:
            return None
        return grid_sizing.icon_layout(m.cw, m.ch, self.storage.icon_tier())

    def _add_icon(self, entry):
        """增量新增一个图标（add_app / rescan / 文件夹提取等）。
        已在位返回原实例；新图标淡入出场（appear_in(0)）。"""
        if entry["id"] in self.icons:
            return self.icons[entry["id"]]
        size = self._icon_size()
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
        self._cull_page_icons()      # v6 §4：新增图标可能落在别页
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
        self._cull_page_icons()      # v6 §4：rescan 等重排后按页显隐

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
        self._hl_cell = None            # v6 §5.2：红框随拖拽结束撤下
        self._cancel_push()             # 反馈 9：未触发的推让随松手作废
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
        if grid_flow.free_mode(self.storage):
            return      # v6 §1.3：无界模式无让位预览、无目标格红框
        cell = self._drag_cell(e.position().toPoint())
        self._set_highlight(cell)       # v6 §5.2：红框跟随面积判定结果
        self._reflow_preview(dragged, cell)

    def _on_reflow_hover(self, dragged: str, gx: int, gy: int):
        """拖动悬停（2026-10-18 M2：参数是指针全局坐标，非图标格点）。

        目标格只从指针全局位置反算——预览会改写 entry，读移动中的
        entry 等于追逐漂移（指导文档 §2.3 病根 3）。2026-10-19 v6
        §5.2：反算升级为拖影矩形的面积判定（_drag_cell），指针位置
        仅作无拖影时的退化输入。v6 §1.3：无界模式整条跳过。
        """
        if grid_flow.free_mode(self.storage):
            return
        pos = self.mapFromGlobal(QPoint(gx, gy))
        cell = self._drag_cell(pos)
        self._set_highlight(cell)
        self._reflow_preview(dragged, cell)

    def _on_reflow_drop(self, dragged: str, gx: int, gy: int):
        """在图标上松手且未武装合并：直接走让位提交。

        不能依赖 drop 事件从图标冒泡到本窗口（实测不传播），故由
        AppIcon.reflowDrop 直连（probe15 G11a）。参数为指针全局坐标。

        2026-10-19 v6 §5.0：多选松手落在图标上同样走这条信号——旧代码
        把 "a,b" 当时条目 id 传给 _reflow_commit_or_compute，查不到 →
        整个 drop 被吞（多选落图标 = 无操作）。改路由 _drop_internal 的
        multi_move 分支，与空白格 drop 同一条语义。

        2026-10-19 v6 §5.2：落点格走拖影矩形面积判定（_drag_cell）。
        2026-10-19 v6 §1.3：无界模式走 _free_drop（像素落点，无让位）。
        """
        pos = self.mapFromGlobal(QPoint(gx, gy))
        if grid_flow.free_mode(self.storage):
            # v6 §1.3：无界模式（含多选）走像素落点，无让位
            self._free_drop([p for p in dragged.split(",") if p],
                            self._drag_pos(pos))
            return
        if self._drag_multi:
            self._drop_internal(dragged, pos)
            return
        self._reflow_commit_or_compute(dragged, self._drag_cell(pos))

    # ---------- 锚定小组件占位（widget 是网格一等公民） ----------
    def _widget_cells(self):
        """可见锚定小组件占据的格子集合（从 storage 读，与实例解耦）。

        v6 §1.3：无界模式下组件不占格（元素可相互重叠）——返回空集，
        让位 / 避让 / 落点拒绝全部自然失效。
        """
        if grid_flow.free_mode(self.storage):
            return set()
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

    def _displace_blocked(self, comp_cells, src_cells) -> set:
        """挤位禁区：组件占位 ∪ 其他图标占位（排除本次要挪走的那些）。

        2026-10-20 F2（用户反馈「移动组件时实时预览把图标叠到同一格」）：
        旧实现只把**组件占位**当禁区传给 `displace_cells`，后者把其余格
        全算空闲——被组件压到的图标于是被分配到**另一个图标正占着的格**
        上，预览里直接叠成一坨。禁区必须含图标自己的占位。

        src_cells 是**要被挪走**的原格：它们本来就在组件矩形里（禁区已有），
        但仍要从"图标禁区"里剔除——否则 displaced 图标会因无空格可去而
        退回原地（留在组件下面）。
        """
        src = set(src_cells)
        icon_cells = {(int(e.get("col", 0)), int(e.get("row", 0)))
                      for e in self.storage.layout}
        return set(comp_cells) | (icon_cells - src)

    def _displace_from_widgets(self) -> dict:
        """把落在小组件占位格上的图标挪到空格（排除组件占位）。
        返回 {id: (col,row)} 位移清单（空 = 无需 displace）。

        2026-10-19：改批量分配（grid_flow.displace_cells）——逐个找空格
        会撞车叠格（反馈 7b）。
        """
        wc = self._widget_cells()
        if not wc:
            return {}
        rpp = grid_flow.rows_per_page()
        lo, hi = grid_flow.page_row_range(grid_flow.current_page(), rpp, 1)
        need = []
        for e in self.storage.layout:
            cell = (int(e.get("col", 0)), int(e.get("row", 0)))
            if cell in wc:
                need.append((e, cell))
        # 2026-10-20 F2：禁区补上其他图标占位，否则被挤的图标会被分到
        # 已经站着人的格子上（预览/落定都叠）
        blocked = self._displace_blocked(wc, [c for _e, c in need])
        plan = grid_flow.displace_cells([c for _e, c in need], blocked,
                                        self.storage.columns, (lo, hi))
        moved = {}
        for e, cell in need:
            dst = plan.get(cell)
            if dst is None:
                continue
            e["col"], e["row"] = dst
            moved[e["id"]] = dst
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
        if grid_flow.free_mode(self.storage):
            return      # v6 §1.3：无界模式组件不占格，图标不被挤走
        cs, rs = grid_flow.widget_span(self.storage, entry)
        col, row = self._cell_at(self.mapFromGlobal(QPoint(gx, gy)))
        # v6 §4：预览矩形按 span 夹紧（clamp_widget_cell）——旧实现只夹
        # 列不夹行，2×2 组件拖到页底最后一行时矩形含页外行，图标被挤到
        # 视野外、组件松手吸附时还会跳一格
        col, row = grid_flow.clamp_widget_cell(self.storage, col, row, cs, rs)
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
        comp_blocked = rect | (self._widget_cells() - self._widget_entry_rect(entry))
        # 2026-10-19 反馈 7b：批量分配（互不重复）。旧实现逐个
        # nearest_free_cell 用同一份静态 blocked，两个图标会被分到同一格
        # ——"排满后再拖组件，图标直接叠在一起"。
        rpp = grid_flow.rows_per_page()
        lo, hi = grid_flow.page_row_range(grid_flow.current_page(), rpp, 1)
        need = []
        for e in self.storage.layout:
            c, r = int(e.get("col", 0)), int(e.get("row", 0))
            if (c, r) in comp_blocked:
                need.append((e, (c, r)))
        # 2026-10-20 F2：禁区再补「其他图标占位」——只给组件占位时
        # displace_cells 会把图标分到别人正占着的格上（预览直接叠格）
        blocked = self._displace_blocked(comp_blocked, [c for _e, c in need])
        plan = grid_flow.displace_cells([c for _e, c in need], blocked,
                                        self.storage.columns, (lo, hi))
        moves = {}
        for e, cell in need:
            dst = plan.get(cell)
            if dst is None:
                continue
            e["col"], e["row"] = dst
            moves[e["id"]] = dst
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

        2026-10-19 v6 §3.2：auto_arrange=False（**默认，自由移动**）时
        不走递进——只落 dragged 自己、原位留空（_free_moves）；True 才
        走 reflow_moves 递进（旧 M2 行为）。

        2026-10-19 v6 §5.0：多选拖动（_drag_multi）走 multi_move 整块
        刚性平移预览——旧代码直接 return，多选拖动全程无预览、松手瞬间
        跳位；且 drop 路径逐成员 clamp 会聚列叠格（反馈病根）。
        """
        if dragged_id is None:
            return
        if grid_flow.free_mode(self.storage):
            return      # v6 §1.3：无界模式无让位——自由摆布、可重叠
        if self._drag_multi:
            self._reflow_preview_multi(dragged_id, cell)
            return
        if dragged_id not in self.icons:
            return
        # 2026-10-19 反馈 4/9：目标格被**别的图标**占着时不立刻让位——
        # 用户可能想合并（悬停 450ms 出提示）。但也**不能一直不动**：
        # 手机语义是"边缘重叠并悬浮一会儿 -> 实时把对方挤走"。折中：
        # 起一个推让计时器，停留够久再算位移（松手/移开即取消）。
        # 拖动中每次 dragMove 都会重置它，只有真正停住才触发。
        if not self._drag_multi:
            occ = self.storage.occupant(cell[0], cell[1], exclude_id=dragged_id)
            if occ is not None:
                # 2026-10-20 F3：拖影**压住**了目标图标（重叠 ≥
                # MERGE_ARM_RATIO）时不武装推让——用户要的是合并提示，
                # 不是把人挤走。只擦边时才走"悬停够久挤走"的老语义。
                if drag_merge.defers_push(
                        self._drag_overlap_on_cell(dragged_id, cell)):
                    self._push_timer.stop()
                    self._push_cell = None
                    self._push_dragged = None
                    return
                self._push_cell = cell
                self._push_dragged = dragged_id
                self._push_timer.start()
                return
        self._push_timer.stop()
        self._push_cell = None
        if self._auto_arrange():
            cols = self.storage.columns
            # M6：不再传 rows=GridMetrics.rows——那是单屏行数，分页后目标行
            # 是全局行（可到 page*rpp + rpp-1），传了会把落点错夹回第 0 页
            # （probe21 S4 抓到：拖到 page1 底行落回 row 7）。落点限页由
            # pos_cell 的局部行夹紧保证，reflow 层不做行夹紧。
            moves = grid_flow.reflow_moves(self.storage.layout, cols, dragged_id,
                                           cell, rows=None,
                                           extra_occupied=self._widget_cells())
        else:
            moves = self._free_moves(dragged_id, cell)
        if not moves:
            return
        self._apply_preview_moves(dragged_id, moves)

    def _auto_arrange(self) -> bool:
        """自动排序开关（v6 §3.2）：False=自由移动（默认）。"""
        return bool(self.storage.get_setting("auto_arrange"))

    def _push_occupied(self):
        """悬停够久：把占着落点的图标实时挤走（手机 launcher 语义）。

        只在"拖到自己想放的位置并停住"时触发；拖动中不断重置计时器，
        所以快速划过不会推人。挤走方式跟随自动排列开关：
          开 -> reflow_moves（递进，后面的图标整体让一格）
          关 -> 与占位者互换（自由摆放的直觉，不产生空洞链）
        """
        cell, dragged = self._push_cell, self._push_dragged
        self._push_cell = None
        if cell is None or dragged is None:
            return
        if dragged not in self.icons:
            return
        occ = self.storage.occupant(cell[0], cell[1], exclude_id=dragged)
        if occ is None:
            return  # 已经空出来了（上次推让生效）
        if self._auto_arrange():
            moves = grid_flow.reflow_moves(self.storage.layout,
                                           self.storage.columns, dragged, cell,
                                           rows=None,
                                           extra_occupied=self._widget_cells())
        else:
            moves = None
        if not moves:
            moves = self._free_moves(dragged, cell)
        if not moves:
            return
        self._apply_preview_moves(dragged, moves)

    def _cancel_push(self):
        """松手/取消：撤掉未触发的推让（避免松手后对方突然跳走）。"""
        self._push_timer.stop()
        self._push_cell = None
        self._push_dragged = None

    def _reflow_preview_multi(self, payload: str, cell):
        """多选拖动实时预览（v6 §5.0）：整块刚性平移跟着指针走。

        主条目 = 真正被抓住的图标（_drag_entry_id）——payload 是
        sorted 逗号串，拿首 id 当时条目会让整块锚点跳错（用户抓的是
        块内哪个图标，哪个才落指针）。
        布局已被上次预览改写也没关系：multi_move 在改写后布局上算的
        等价于增量 delta（块内相对偏移守恒，与单选 reflow 的增量预览
        同构；交换出去的占据者不会再次被换回）。
        """
        ids = [p for p in payload.split(",") if p]
        primary = self._drag_entry_id
        if primary not in ids:
            primary = ids[0] if ids else None
        if primary is None:
            return
        live = {e.get("id") for e in self.storage.layout}
        if primary not in live:
            return
        moves = grid_flow.multi_move(self.storage.layout,
                                     self.storage.columns, primary, cell,
                                     set(ids),
                                     extra_occupied=self._widget_cells())
        if not moves:
            return
        self._apply_preview_moves(primary, moves)

    def _free_moves(self, dragged_id: str, cell) -> dict:
        """自由移动位移清单（v6 §3.2）：只落 dragged 自己，原位留空。

        目标被非 dragged 占据时与占据者**交换**到源格（自由摆放的
        直觉：不丢条目、不覆盖）；目标落在组件占位格上则拒绝（不覆盖
        组件，拖动无效——与 reflow 的 extra_occupied 语义一致）。
        """
        by_id = {e.get("id"): e for e in self.storage.layout}
        src = by_id.get(dragged_id)
        if src is None:
            return {}
        old = (int(src.get("col", 0)), int(src.get("row", 0)))
        if cell == old:
            return {}
        occupant = None
        for e in self.storage.layout:
            if e.get("id") == dragged_id:
                continue
            if (int(e.get("col", 0)), int(e.get("row", 0))) == cell:
                occupant = e
                break
        if occupant is None and cell in self._widget_cells():
            return {}                      # 组件占位格：拒绝
        moves = {dragged_id: cell}
        if occupant is not None:
            moves[occupant["id"]] = old    # 交换到源格
        return moves

    def _apply_preview_moves(self, dragged_id: str, moves: dict):
        """预览位移落地共用路径：去重 -> 写内存 -> 最小集合动画。"""
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
        self._cull_moved_icons(moves)   # v6 §4：跨页位移按落点页显隐

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
        self._cancel_push()
        if self._preview_moves is None:
            return
        dragged = self._preview_drag
        moves = self._preview_moves
        self._push_undo(self._layout_snap)
        self.storage.save()
        if dragged and dragged in self.icons:
            entry = self.storage.find_entry(dragged)
            icon = self.icons[dragged]
            if entry is not None:
                icon.move(*self._entry_pos(entry))
            icon.set_drag_ghost(False)
        # 2026-10-19 反馈 4 连带：占用格改成"松手才换"后，被交换走的
        # 占据者不会经过 _apply_preview_moves 的动画路径（拖动中没有预览），
        # 只 move 拖拽源会让 storage 与画面不一致（下一帧视觉跳变）。
        # 这里把 moves 里其余成员一并弹簧落位——已到位的 animate_to 早退。
        for eid in moves:
            if eid == dragged:
                continue
            icon = self.icons.get(eid)
            entry = self.storage.find_entry(eid)
            if icon is None or entry is None:
                continue
            icon.animate_to(*self._entry_pos(entry))
            icon.set_drag_ghost(False)
        self._preview_moves = None
        self._preview_drag = None
        self._layout_snap = None
        self._cull_page_icons()      # v6 §4：提交后按落点页显隐

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
        self._cull_page_icons()      # v6 §4：撤销回退后按当前页显隐
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
        if self._auto_arrange():
            moves = grid_flow.reflow_moves(self.storage.layout,
                                           self.storage.columns,
                                           dragged_id, cell,
                                           extra_occupied=self._widget_cells())
        else:
            moves = self._free_moves(dragged_id, cell)
        if not moves:
            # 预览在飞但落点无效（如陈旧 payload：drop 携带的 id 已不在
            # 布局）——必须先回退快照再落盘。旧代码只 _clear_preview()，
            # 预览已改写的内存布局被留下：图标停在原位、storage 却是
            # 预览态（probe15 G11c 败因：半截预览态）。反过来先 save 会把
            # 半截状态写进 disk，顺序不能倒。
            self._cancel_preview()
            self.storage.save()
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
        self._cull_page_icons()      # v6 §4：回退后按当前页显隐
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

    # ---------- 桌面目录自动同步（v6 §7.4） ----------
    def set_auto_sync(self, on: bool):
        """启停桌面目录监听（设置项 / 启动时按 auto_sync_desktop 决定）。

        监听走 QFileSystemWatcher（Windows 底层即 ReadDirectoryChangesW，
        零新增依赖），debounce 1s 后调 storage.sync_desktop_incremental()。
        """
        from .desktop_watch import DesktopWatcher
        if on:
            if self._watcher is None:
                self._watcher = DesktopWatcher(
                    self.storage, on_sync=self._on_desk_sync, parent=self)
            else:
                self._watcher.start()
        elif self._watcher is not None:
            self._watcher.stop()

    def _on_desk_sync(self, added: int, removed: int):
        """桌面目录变动：增量补/删图标。

        只做结构同步（_sync_structure 走弹簧动画），**不重排、不翻页**——
        文件系统事件是被动发生的，用户摆放的位置必须原样保留。
        """
        self._sync_structure()
        self._cull_page_icons()
        self.storage.save()

    def rescan_desktop(self):
        """重新扫描桌面文件：补新增、清丢失（仅布局，不动文件）。
        M4：增量同步——新增淡入 / 丢失移除 / compact 移位走弹簧动画。

        v6 §4：rescan 末尾 pack_layout 把全体图标铺回第 0 页（§3.1
        播种语义）——若当前页 >0，不停在已被清空的旧页（那会看到空
        桌面），显式回到第 0 页展示重扫结果。
        """
        added, removed = self.storage.rescan_desktop()
        self._sync_structure()
        if self._page != 0:
            self.goto_page(0, animate=False)
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
        # 2026-10-19 反馈 5：合并前**回退**拖动预览（不是清掉状态）。
        # 旧实现 _clear_preview() 丢弃了快照回退，被递进的图标就停在预览
        # 位置，用户看到的是"加了个文件夹，整张桌面自己重排了一遍"。
        self._cancel_preview()
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
        # 2026-10-19 反馈：幕布铺满桌面带且层级最高，拖放必须由它转发到
        # 桌面窗口——否则"从文件夹里把图标拖出来"的 drop 会被幕布吞掉
        scrim.dropReceived.connect(self._drop_from_scrim)
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
            win32_layer.attach_to_desktop(
                scrim, layer=win32_layer.BAND_LAYER_SCRIM)
            # v6 §6.2 覆盖性：幕布必须吞掉桌面层所有点击（不穿透）。
            # 只插 Progman 正上方会让幕布落在整理窗口之下——桌面窗口是
            # 全窗口 HTCLIENT，命中测试先收到点击，幕布形同虚设（图标层
            # 实际可点）。与弹窗同机制：插到桌面带内最顶。
            top = win32_layer.band_topmost_hwnd(exclude_hwnd=int(scrim.winId()))
            if top:
                win32_layer.insert_above_window(int(scrim.winId()), top)
            self._band_guard.track(scrim, layer=win32_layer.BAND_LAYER_SCRIM)
            win32_layer.attach_to_desktop(
                popup, layer=win32_layer.BAND_LAYER_POPUP)
            popup.attach_above_band()
            self._band_guard.track(popup, layer=win32_layer.BAND_LAYER_POPUP)
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

    def _on_extract(self, payload: str, pos=None):
        """把文件夹成员拖出到桌面（落到哪个格子就用哪个格子）。
        payload: "M:fid:idx" 或 "fid:idx"（M: 标记可带可不带；
        fid 自身可能含冒号，故 rpartition 从最后一个冒号切）。

        pos: 松手点在桌面窗口内的坐标（可选）。给了就按那个格子落位；
        格子上已经有图标时退回"第一个空格"——**不挤走无关图标**
        （提取是用户主动把东西拿出来，不该顺手把别人挪走）。
        """
        if payload.startswith("M:"):
            payload = payload[2:]
        fid, _, idx = payload.rpartition(":")
        folder = self.storage.find_entry(fid)
        if not folder or folder.get("type") != "folder" or not idx.isdigit():
            return
        idx = int(idx)
        if not (0 <= idx < len(folder.get("apps", []))):
            return
        col = row = None
        if pos is not None:
            try:
                tc, tr = self._cell_at(pos)
                if self.storage.occupant(tc, tr) is None:
                    col, row = tc, tr
            except Exception:
                col = row = None
        app = folder["apps"].pop(idx)
        self.storage.add_app(app, col, row)
        if not folder["apps"]:
            self.storage.remove_entry(fid)
        self.storage.compact_layout()
        self.storage.save()
        self._sync_structure()          # M4：提取成员增量淡入 + 空文件夹移除
        # M5：文件夹被解散时 refresh 自动关弹窗；仍有成员时刷新成员网格
        if self._popup is not None:
            self._popup.refresh()

    def _drop_from_scrim(self, md, gpos):
        """幕布上的落点转发到桌面窗口（2026-10-19 反馈：拖出成员丢失）。

        幕布是桌面带里最顶的全屏窗口，从弹窗往外拖必然经过它；它只负责
        把 (mime, 全局坐标) 送过来，真正的语义仍由桌面窗口的
        `_drop_internal` / `_drop_files` 决定（单一实现，不复制逻辑）。
        """
        if md is None:
            return
        pos = self.mapFromGlobal(gpos) if gpos is not None else QPoint(0, 0)
        if md.hasFormat(MIME_TYPE):
            self._drop_internal(md.data(MIME_TYPE).data().decode(), pos)
        elif md.hasUrls():
            self._drop_files(md.urls(), pos)

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
            self._on_extract(payload[2:], pos)
            return
        ids = [p for p in payload.split(",") if p]
        entries = [e for e in (self.storage.find_entry(i) for i in ids) if e is not None]
        if not entries:
            # payload 全是不在布局的 id（条目被并发移除等）：有预览在飞
            # 就回退快照，别留半截预览态（同 _reflow_commit_or_compute）
            self._cancel_preview()
            return

        if grid_flow.free_mode(self.storage):
            # v6 §1.3 无界松手：整块按拖影位移量平移到像素位（不吸附 /
            # 不避让 / 可重叠——§1.2 自由摆布语义）
            self._free_drop(ids, self._drag_pos(pos))
            return

        if len(entries) == 1 and not self._drag_multi:
            # 单选：走让位（拖动期间已生成预览 -> 直接提交）
            self._reflow_commit_or_compute(entries[0]["id"], self._drag_cell(pos))
            return

        # 多选：整体平移语义（v6 §5.0 multi_move——不叠格/形状保持/
        # 边缘夹紧/占据者交换不丢条目）。旧实现逐成员
        # max(0, min(cols-1, col+dcol)) 各自夹紧，多个成员的 nc 全落
        # cols-1 聚成一列叠格（反馈病根）；且主条目取 payload 首 id
        # （sorted 串）而非真正被拖的图标，锚点错误。
        if self._preview_moves is not None and self._preview_drag in ids:
            # 拖动期间已生成预览（落点与预览一致）-> 直接提交
            self._commit_preview()
        else:
            primary = self._drag_entry_id
            if primary not in ids:
                primary = entries[0]["id"]
            moves = grid_flow.multi_move(self.storage.layout,
                                         self.storage.columns, primary,
                                         self._drag_cell(pos), set(ids),
                                         extra_occupied=self._widget_cells())
            if moves:
                by_id = {e.get("id"): e for e in self.storage.layout}
                for eid, (c, r) in moves.items():
                    e = by_id.get(eid)
                    if e is not None:
                        e["col"], e["row"] = c, r
                # 借提交路径收尾：压撤销栈 + 落盘 + 动画落位 + 清预览
                self._preview_moves = moves
                self._preview_drag = primary
                self._commit_preview()
            else:
                # 脏布局等无效输入：不动布局，仅收尾（与单选无位移同策）
                self._cancel_preview()
                return
        # M4：多选平移是位置类变化——动画到位，不 rebuild。
        # 逐个复位拖拽幽灵态：增量路径不再销毁图标实例，
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
        """桌面空白处右键菜单。"""
        self._build_context_menu().exec(e.globalPos())

    def _build_context_menu(self):
        """构建桌面右键菜单（拆出来便于单测）。

        整理模式（路线A）下原生桌面右键被我们接管（nativeEvent 全窗口
        HTCLIENT），Windows 原生菜单全部消失——2026-10-18 用户反馈
        "桌面右键功能也没了"，2026-10-19 追加反馈 6：「右键要还原原系统
        的所有功能，比如新建 word」。

        因此接管态菜单按系统原生的顺序组织：查看 / 刷新 / 粘贴 / 新建▸ /
        显示设置 / 个性化 / 终端 / 打开桌面文件夹。其中「新建」子菜单由
        `shell_new.shell_new_templates()` 枚举注册表 ShellNew 模板生成
        （Word / Excel / PPT / 压缩包…用户装了什么就有什么）。
        """
        menu = QMenu(self)
        menu.setStyleSheet(theme.MENU_QSS)
        if self._organize_mode():
            # 查看 ▸（图标大小 + 自动排列 + 网格调试）
            view = menu.addMenu("查看")
            size_menu = view.addMenu("图标大小")
            for label, tier in (("大图标", "large"), ("中图标", "medium"),
                                ("小图标", "small")):
                act = size_menu.addAction(label)
                act.triggered.connect(
                    lambda checked=False, t=tier: self._set_icon_tier(t))
            view.addSeparator()
            # 2026-10-19 反馈 3：把"自动排列"做成**持久的开关**（与资源
            # 管理器「查看 ▸ 自动排列图标」同语义）——勾选即立刻整理，
            # 之后拖动始终递进生效；取消则自由摆放（允许空格）。
            auto_act = view.addAction("自动排列图标")
            auto_act.setCheckable(True)
            auto_act.setChecked(bool(self.storage.get_setting("auto_arrange")))
            auto_act.triggered.connect(self._toggle_auto_arrange)
            view.addAction("立即整理（重新排列）", self._tidy)
            dev_act = view.addAction("显示网格调试信息")
            dev_act.setCheckable(True)
            dev_act.setChecked(self._dev_mode())
            dev_act.triggered.connect(self._toggle_dev_mode)

            # 刷新 / 粘贴（与系统桌面同一位置）
            menu.addAction("刷新", self.rescan_desktop)
            paste = menu.addAction("粘贴", self._paste_files)
            paste.setEnabled(self._clipboard_has_files())

            menu.addSeparator()
            new_menu = menu.addMenu("新建")
            new_menu.setObjectName("ctxNewMenu")   # 测试/自动化定位用
            self._fill_new_menu(new_menu)
            menu.addSeparator()

            # 系统设置与常用入口
            menu.addAction("显示设置", lambda: self._open_uri("ms-settings:display"))
            menu.addAction("个性化（桌面背景）",
                           lambda: self._open_uri("ms-settings:personalization-background"))
            menu.addAction("在终端中打开", self._open_terminal)
            menu.addAction("打开桌面文件夹", self._open_desktop_folder)
            menu.addSeparator()

            # 本软件的布局能力
            free_now = grid_flow.free_mode(self.storage)
            menu.addAction("切换到无界模式（自由摆布）" if not free_now
                           else "切换到网格模式（对齐网格）",
                           self._toggle_layout_mode)
            if free_now:
                menu.addAction("添加空白页", self._add_blank_page)
                menu.addAction("删除当前空白页", self._remove_blank_page)
            menu.addSeparator()

        menu.addAction("添加应用…", self.openAddAppsRequested.emit)
        if self._selected:
            menu.addAction("删除选中（%d）" % len(self._selected), self._remove_selected)
        menu.addAction("设置…", self.openSettingsRequested.emit)
        menu.addSeparator()
        if self._organize_mode():
            menu.addAction("恢复系统原生桌面图标", self._exit_organize_mode)
        menu.addAction("隐藏桌面整理", self.hide_desktop)

        # 构建标识（2026-10-19 版本混淆事故）：用户报"还是没修好"，实际是
        # 跑着上一轮的包。灰显不可点，只为一眼回答"这是哪个构建"。
        from . import version
        menu.addSeparator()
        ver_act = menu.addAction(version.label())
        ver_act.setEnabled(False)
        ver_act.setObjectName("ctxVersion")
        return menu

    def _fill_new_menu(self, new_menu):
        """「新建」子菜单：文件夹 + 系统注册的全部 ShellNew 模板（反馈 6）。"""
        from . import shell_new
        new_menu.addAction(
            "文件夹", lambda: self._create_on_desktop("新建文件夹", True))
        templates = shell_new.shell_new_templates()
        if templates:
            new_menu.addSeparator()
        for tpl in templates:
            new_menu.addAction(
                tpl["label"],
                lambda checked=False, t=tpl: self._create_from_template(t))

    def _clipboard_has_files(self) -> bool:
        """剪贴板里是否有可粘贴的本地文件 / 目录（决定「粘贴」是否置灰）。"""
        try:
            md = QApplication.clipboard().mimeData()
            return bool(md is not None and md.hasUrls()
                        and any(u.isLocalFile() for u in md.urls()))
        except Exception:
            return False

    def _paste_files(self):
        """粘贴：把剪贴板里的本地文件/目录复制到桌面（系统语义）。"""
        import shutil
        from . import shell_new
        try:
            urls = QApplication.clipboard().mimeData().urls()
        except Exception:
            return
        folders = appsource._desktop_folders()
        if not folders:
            return
        dest = str(folders[0])
        added = 0
        for u in urls:
            src = u.toLocalFile()
            if not src or not os.path.exists(src):
                continue
            base, ext = os.path.splitext(os.path.basename(src))
            try:
                target = shell_new.unique_path(dest, base, ext)
                if os.path.isdir(src):
                    shutil.copytree(src, target)
                else:
                    shutil.copy2(src, target)
                added += 1
            except Exception:
                continue
        if added:
            self.rescan_desktop()
            from .tray import notify_via_tray
            notify_via_tray("已粘贴到桌面", "%d 个项目" % added)

    def _create_from_template(self, tpl):
        """按 ShellNew 模板在桌面新建文件（Office 文档带默认样式）。"""
        from . import shell_new
        folders = appsource._desktop_folders()
        if not folders:
            return
        path = shell_new.create_from_template(tpl, str(folders[0]))
        if not path:
            from .tray import notify_via_tray
            notify_via_tray("新建失败", "系统没有为该类型提供模板")
            return
        self.rescan_desktop()

    def _toggle_dev_mode(self, checked: bool):
        self.storage.set_setting("dev_mode", bool(checked))
        self.update()

    def _open_terminal(self):
        """在桌面目录打开终端（Windows Terminal 优先，回退 cmd）。"""
        folders = appsource._desktop_folders()
        if not folders:
            return
        d = str(folders[0])
        try:
            if QProcess.startDetached("wt.exe", ["-d", d]):
                return
        except Exception:
            pass
        try:
            QProcess.startDetached("cmd.exe", ["/c", "start", "cmd", "/k",
                                               'cd /d "%s"' % d])
        except Exception:
            pass

    def _create_on_desktop(self, name: str, is_dir: bool):
        """右键新建：真实创建到桌面目录，然后重扫让网格立即出现。"""
        try:
            appsource.create_on_desktop(name, is_dir)
        except Exception:
            return
        added, _ = self.rescan_desktop()

    def _set_icon_size(self, px: int):
        self.storage.set_setting("icon_size", int(px))
        self.refresh_grid()

    def _set_icon_tier(self, tier: str):
        """右键「图标大小」三档（v6 A2，指导文档 §2.2）：档位 × 当前 cell，
        与 icon_size/icon_scale 解钩——网格模式下 widget 整体按比例渲染。

        反馈 2：改完必须立刻重算几何（refresh_grid），只 rebuild 会沿用
        旧 cell 快照，看起来"改了没反应"。
        """
        from . import grid_sizing
        self.storage.set_setting("icon_tier", grid_sizing.parse_tier(tier))
        self.refresh_grid()

    def _toggle_auto_arrange(self, checked: bool):
        """自动排列开关（反馈 3）：勾选即整理一次，之后始终按阅读序递进。

        语义与资源管理器「查看 ▸ 自动排列图标」一致：**先打开，再总是
        生效**。未开启时保留空格（自由摆放），拖进空格不会再触发整段
        平移——这正是用户说的"前方有空格时移动逻辑很混乱"。
        """
        on = bool(checked)
        self.storage.set_setting("auto_arrange", on)
        if on:
            self._tidy()

    def _toggle_layout_mode(self):
        """v6 §1.3：网格 <-> 无界 切换（桌面右键 / 托盘同一入口）。"""
        self.set_layout_mode(
            "grid" if grid_flow.free_mode(self.storage) else "free")

    def _add_blank_page(self):
        """v6 §1.3：末尾追加一页空白页（extra_pages 记录页码）。

        取 max(当前总页数, 数据页数) 作为新页号——不与已有页冲突；
        追加后翻过去，用户面对一张干净的画布。
        """
        extras = grid_flow.extra_pages(self.storage)
        total = grid_flow.page_count(self.storage)
        new_page = max(total, extras[-1] + 1 if extras else 0)
        extras.append(new_page)
        self.storage.set_setting("extra_pages", sorted(set(extras)))
        self.goto_page(new_page)
        self.update()

    def _remove_blank_page(self):
        """v6 §1.3：删除当前空白页（仅 extra_pages 里的空页可删——
        有数据的页删了会丢条目，直接拒绝并提示）。"""
        page = self._page
        extras = grid_flow.extra_pages(self.storage)
        if page not in extras:
            from .tray import notify_via_tray
            notify_via_tray("无法删除", "当前页不是空白页（有内容或不存在）")
            return
        extras.remove(page)
        self.storage.set_setting("extra_pages", extras)
        self._clamp_page()
        self.update()

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
        """退出整理模式：关闭「接管系统桌面」并恢复原生图标显示。"""
        self.storage.set_takeover(False)
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
