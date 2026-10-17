# -*- coding: utf-8 -*-
"""桌面整理主窗口：克隆图标网格、文件夹合并/解散、挂载到桌面层（Progman 上方的桌面带）。

原生桌面图标（SHELLDLL_DefView）在运行期间被隐藏，桌面文件由本窗口
克隆渲染——位置、大小、样式完全由第三方桌面掌控；退出时恢复原生图标。
"""
import os

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from . import appsource
from . import theme
from . import win32_layer
from .band_guard import BandGuard
from .folder_popup import FolderPopup
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
        self._selected = set()      # 多选：entry id 集合（单击/Ctrl/框选）
        self._drag_active = False   # QDrag 进行中：命中测试临时全窗口接收
        self._drag_entry_id = None  # 当前正在拖的条目（多选拖动时判成员）
        self._ole_active = False    # 外部文件 OLE 拖入进行中（拖放目标全窗口）
        self._band_start = None     # 橡皮筋起点（控件坐标）
        self._band_rect = None
        self._band_moved = False
        self.icons = {}
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
        self.visibilityChanged.emit(True)

    def _show_current_mode(self):
        """模式已确定后的再次显示（托盘切换显隐时走这里）。"""
        if self.attached:
            if self._floating_flag_set:
                self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
                self._floating_flag_set = False
            self.setGeometry(QApplication.primaryScreen().availableGeometry())
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
        if self._popup is not None:
            self._popup.close()
            self._popup = None
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
        """守护周期回调：保持原生图标隐藏（explorer 重启等会令其重新可见）。"""
        if self.storage.get_setting("hide_native_icons") and self.isVisible():
            if not win32_layer.native_icons_hidden():
                win32_layer.set_native_icons_visible(False)

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
            return  # 除上述元素外全透明，融入壁纸
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(theme.SURFACE)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(self.rect().adjusted(6, 6, -6, -6), theme.RADIUS_PANEL, theme.RADIUS_PANEL)
        p.setPen(theme.TEXT)
        p.setFont(theme.ui_font(13))
        p.drawText(24, 30, "桌面整理 Demo · 悬浮模式（未能挂载桌面层，功能不受影响）")

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
        # （_drag_active 卡死会让 nativeEvent 全窗口 HTCLIENT，桌面点不动）
        self._drag_active = False
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
                for icon in self.icons.values():
                    r = QRect(icon.mapToGlobal(QPoint(0, 0)), icon.size())
                    if r.adjusted(-14, -14, 14, 14).contains(pt):
                        return True, HTCLIENT
                return True, HTTRANSPARENT
        return super().nativeEvent(eventType, message)

    # ---------- 网格几何 ----------
    def _cell(self):
        s = int(self.storage.get_setting("icon_size"))
        return s + 28, s + 48  # 与 AppIcon(setFixedSize(s+28, s+46)) 对齐，消除相邻重叠

    def _origin(self):
        return 26, 22

    def _entry_pos(self, entry):
        cw, ch = self._cell()
        ox, oy = self._origin()
        cols = self.storage.columns
        col = min(max(0, int(entry.get("col", 0))), cols - 1)
        row = max(0, int(entry.get("row", 0)))
        return ox + col * cw, oy + row * ch

    def _cell_at(self, pos):
        cw, ch = self._cell()
        ox, oy = self._origin()
        cols = self.storage.columns
        col = int(round((pos.x() - ox) / cw))
        row = int(round((pos.y() - oy) / ch))
        return max(0, min(col, cols - 1)), max(0, row)

    # ---------- 重建 ----------
    def rebuild(self, stagger=False):
        for icon in self.icons.values():
            icon.deleteLater()
        self.icons.clear()
        self._selected = {eid for eid in self._selected
                          if self.storage.find_entry(eid) is not None}
        size = int(self.storage.get_setting("icon_size"))
        for idx, entry in enumerate(self.storage.layout):
            icon = AppIcon(entry, size, parent=self)
            icon.activated.connect(self._on_activate)
            icon.clicked.connect(self._on_icon_clicked)
            icon.folderClicked.connect(self.open_folder)
            icon.mergeRequested.connect(self._on_merge)
            icon.removeRequested.connect(self._on_remove_entry)
            icon.dissolveRequested.connect(self._on_dissolve)
            icon.openLocation.connect(self._on_open_location)
            icon.dragStarted.connect(self._on_drag_started)
            icon.dragFinished.connect(self._on_drag_finished)
            icon.payload_provider = self._drag_payload_for
            icon.set_selected(entry["id"] in self._selected)
            icon.move(*self._entry_pos(entry))
            if stagger:
                # 错峰淡入（模式切换 / 首次显示的仪式感；业务 rebuild 不加，
                # 拖动落位要即时反馈）
                icon.appear_in(min(idx * 30, 600))
            icon.show()
            self.icons[entry["id"]] = icon
        self.update()

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
        pass  # 占位：具体条目在 payload_provider 调用时确定

    def _on_drag_finished(self):
        self._drag_active = False
        self._drag_entry_id = None
        self.update()

    def _drag_payload_for(self, entry_id: str) -> str:
        """拖拽 payload：单选=条目 id；多选且拖的是选中成员=逗号分隔 id 集合。
        同时置 _drag_active：命中测试在此期间全窗口接收，保证 OLE 拖放能落下。"""
        self._drag_entry_id = entry_id
        self._drag_active = True
        if len(self._selected) > 1 and entry_id in self._selected:
            return ",".join(sorted(self._selected))
        return entry_id

    # ---------- 业务 ----------
    def _on_activate(self, app):
        if app:
            appsource.launch(app)

    def _on_open_location(self, app):
        target = app.get("target", "")
        if target:
            appsource.reveal_in_explorer(target)

    def add_app(self, app: dict):
        self.storage.add_app(app)
        self.storage.save()
        self.rebuild()

    def rescan_desktop(self):
        """重新扫描桌面文件：补新增、清丢失（仅布局，不动文件）。"""
        added, removed = self.storage.rescan_desktop()
        self.rebuild()
        return added, removed

    def _on_remove_entry(self, entry_id):
        entry = self.storage.find_entry(entry_id)
        self.storage.remove_entry(entry_id)
        self.storage.compact_layout()
        self.storage.save()
        self.rebuild()
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
        self.rebuild()

    def _on_merge(self, dragged_payload: str, target_id: str):
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
            self.rebuild()
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
        self.rebuild()
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
            self._popup.close()
            self._popup = None
        icon = self.icons.get(entry_id)
        anchor_rect = None
        if icon is not None:
            # 传图标完整全局矩形：液态玻璃弹窗的展开动画起点
            anchor_rect = QRect(icon.mapToGlobal(QPoint(0, 0)), icon.size())
        popup = FolderPopup(self.storage, entry, anchor_rect)
        popup.launchApp.connect(self._on_activate)
        popup.extractRequested.connect(self._on_extract)
        popup.removeMember.connect(self._on_remove_member)
        popup.closed.connect(self._on_popup_closed)
        self._popup = popup
        popup.show()

    def _on_popup_closed(self):
        self._popup = None

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
            if self._popup is not None:
                self._popup.close()
        self.storage.compact_layout()
        self.storage.save()
        self.rebuild()

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
                if self._popup is not None:
                    self._popup.close()
        self.storage.save()
        self.rebuild()

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
        self._ole_active = False

    def _drop_internal(self, payload: str, pos):
        col, row = self._cell_at(pos)
        # 文件夹成员提取（payload: "M:fid:idx"）：M: 标记与含冒号的条目 id 消歧
        if payload.startswith("M:"):
            self._on_extract(payload[2:])
            return
        ids = [p for p in payload.split(",") if p]
        entries = [e for e in (self.storage.find_entry(i) for i in ids) if e is not None]
        if not entries:
            return
        primary = entries[0]
        old_col, old_row = int(primary.get("col", 0)), int(primary.get("row", 0))
        dcol, drow = col - old_col, row - old_row
        # 主图标：与目标格占用者交换（占用者不在多选集合内才交换）
        occupant = self.storage.occupant(col, row, exclude_id=primary["id"])
        if occupant is not None and occupant["id"] not in self._selected:
            occupant["col"], occupant["row"] = old_col, old_row
        primary["col"], primary["row"] = col, row
        # 多选其余成员：按平移量整体移动，越界夹紧，目标格被占用则跳过
        for e in entries[1:]:
            nc = max(0, min(self.storage.columns - 1, int(e.get("col", 0)) + dcol))
            nr = max(0, int(e.get("row", 0)) + drow)
            occ = self.storage.occupant(nc, nr, exclude_id=e["id"])
            if occ is None or occ["id"] in self._selected:
                e["col"], e["row"] = nc, nr
        self.storage.save()
        self.rebuild()

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
            self.rebuild()
            from .tray import notify_via_tray
            notify_via_tray("已添加到整理桌面", "新增 %d 个项目" % added)

    # ---------- 背景右键 / 按键 ----------
    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.setStyleSheet(theme.MENU_QSS)
        menu.addAction("添加应用…", self.openAddAppsRequested.emit)
        menu.addAction("重新扫描桌面文件", self.rescan_desktop)
        menu.addAction("整理布局", self._tidy)
        if self._selected:
            menu.addAction("删除选中（%d）" % len(self._selected), self._remove_selected)
        menu.addAction("设置…", self.openSettingsRequested.emit)
        menu.addSeparator()
        if self._organize_mode():
            menu.addAction("恢复系统原生桌面图标", self._exit_organize_mode)
        menu.addAction("隐藏桌面整理", self.hide_desktop)
        menu.exec(e.globalPos())

    def _exit_organize_mode(self):
        """退出整理模式：恢复原生图标显示（设置同步）。"""
        self.storage.set_setting("hide_native_icons", False)
        self._sync_native_icons()

    def _remove_selected(self):
        for eid in list(self._selected):
            self.storage.remove_entry(eid)
        self._selected.clear()
        self.storage.compact_layout()
        self.storage.save()
        self.rebuild()

    def _tidy(self):
        self.storage.compact_layout()
        self.storage.save()
        self.rebuild()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide_desktop()
        elif e.key() == Qt.Key_Delete and self._selected:
            self._remove_selected()
        elif e.key() == Qt.Key_A and (e.modifiers() & Qt.ControlModifier):
            self._selected = set(self.icons.keys())
            self._refresh_selection()

    def closeEvent(self, e):
        self._band_guard.untrack(self)
        if self.storage.get_setting("minimize_to_tray"):
            e.ignore()
            self.hide_desktop()
        else:
            self.quitRequested.emit()
            e.accept()
