# -*- coding: utf-8 -*-
"""小组件管理层：统一创建 / 显隐 / 关闭桌面小组件。"""
from PySide6.QtCore import QObject, QPoint, Signal
from PySide6.QtWidgets import QApplication

from . import grid_flow
from .band_guard import BandGuard
from .widget_base import FloatingWidget
from .widgets_clock import ClockWidget
from .widgets_notes import NotesWidget
from .widgets_panel import DesktopPanel

WIDGET_TYPES = {"clock": ClockWidget, "notes": NotesWidget, "panel": DesktopPanel}

WIDGET_NAMES = {"clock": "时钟", "notes": "便签", "panel": "桌面面板"}


class WidgetLayer(QObject):
    # 锚定小组件占位变化（落定 / 移动 / 尺寸变化）时发出，
    # 由 main.py 连到 DesktopWindow.on_widget_grid_changed 挤走图标。
    gridChanged = Signal()
    # 锚定组件拖动实时预览（2026-10-18 M4）：转发 FloatingWidget 的
    # anchorHover/anchorDrop（widget id + 指针全局坐标）。
    anchorHover = Signal(str, int, int)
    anchorDrop = Signal(str, int, int)

    def __init__(self, storage):
        super().__init__()
        self.storage = storage
        self.widgets = {}  # entry_id -> FloatingWidget
        self._band_guard = BandGuard()
        for entry in self.storage.widgets:
            self._place_default(entry)
            self._spawn(entry)
        if not self.storage.get_setting("show_widgets"):
            self.set_visible(False)

    # ---------- 默认落位 ----------
    def _place_default(self, entry):
        """首次创建（没有保存过位置）时按类型放到合适位置，避免互相遮挡。

        锚定（非悬浮）组件不在这里定位：由 _spawn 走 find_widget_slot
        分配网格占位（col/row），再换算成像素坐标——它占据格子，
        不是"浮在某个角落"。
        """
        if entry.get("anchored") and "col" not in entry:
            return
        if "x" in entry:
            return
        screen = QApplication.primaryScreen().availableGeometry()
        w, h = int(entry.get("w", 300)), int(entry.get("h", 160))
        t = entry.get("type")
        if t == "clock":
            entry["x"] = screen.right() - w - 56
            entry["y"] = screen.top() + 48
        elif t == "panel":
            # 桌面面板：右侧，时钟下方（时钟隐藏时贴顶）
            clock = next((e for e in self.storage.widgets if e.get("type") == "clock"), None)
            top = screen.top() + 48
            if clock is not None and not clock.get("hidden"):
                top = screen.top() + 48 + int(clock.get("h", 160)) + 20
            entry["x"] = screen.right() - w - 40
            entry["y"] = top
        else:  # notes 等：右下角，多个则向左层叠
            n = sum(1 for e in self.storage.widgets if e.get("type") == t)
            entry["x"] = screen.right() - w - 56 - (n * 44) % 200
            entry["y"] = screen.bottom() - h - 48
        self.storage.save()

    # ---------- 生命周期 ----------
    def _spawn(self, entry):
        if entry.get("hidden"):
            return
        cls = WIDGET_TYPES.get(entry.get("type"))
        if cls is None:
            return
        if entry.get("anchored"):
            if grid_flow.free_mode(self.storage):
                # v6 §1.3 无界锚定：row 仅作页载体，位置读 fx/fy（缺列
                # 时补一份，落在当前页），尺寸用 entry 的 w/h（用户像素），
                # 不分配网格占位、不写 colspan/rowspan 覆盖用户尺寸
                if "col" not in entry or "row" not in entry:
                    entry["col"] = 0
                    entry["row"] = (grid_flow.current_page()
                                    * grid_flow.rows_per_page())
                if "fx" not in entry or "fy" not in entry:
                    entry["fx"] = int(entry.get("x", 0) or 0)
                    entry["fy"] = int(entry.get("y", 0) or 0)
                # __init__ 的初始 geometry 读 x/y——同步一份，窗口才落在
                # fx/fy 上（否则停在网格模式遗留的旧格点像素）
                entry["x"], entry["y"] = entry["fx"], entry["fy"]
            else:
                # 锚定组件：分配网格占位（排除已有组件与图标），按格点定位。
                # M6：find_widget_slot 默认限运行时当前页行范围（组件不越页底）
                if "col" not in entry:
                    col, row = grid_flow.find_widget_slot(self.storage, entry)
                else:
                    # v6 §4：旧数据越页修正——span 夹紧到所属页行范围
                    # （便签 2×2 存在 row=rpp-1 会跨页半截，probe23 S2）
                    cs, rs = grid_flow.widget_span(self.storage, entry)
                    col, row = grid_flow.clamp_widget_cell(
                        self.storage, int(entry.get("col", 0)),
                        int(entry.get("row", 0)), cs, rs)
                entry["col"], entry["row"] = col, row
                cs, rs = grid_flow.widget_span(self.storage, entry)
                entry["colspan"], entry["rowspan"] = cs, rs
                # M6：位置统一走 cell_pos（页内局部行映射）
                entry["x"], entry["y"] = grid_flow.cell_pos(
                    self.storage, int(entry["col"]), int(entry["row"]))
            self.storage.save()
        w = cls(self.storage, entry)
        w.closed.connect(self._on_closed)
        w.gridChanged.connect(self.gridChanged.emit)
        w.anchorHover.connect(self.anchorHover.emit)
        w.anchorDrop.connect(self.anchorDrop.emit)
        self.widgets[entry["id"]] = w
        w.show()
        # v6 §4：不在当前页的锚定组件隐藏——组件是**顶层窗口**（不像
        # 图标是桌面窗口子控件会被裁剪），静止态露在屏顶/屏底就是半截
        # 渲染；翻到它的页由 sync_page 显示
        if entry.get("anchored"):
            rpp = grid_flow.rows_per_page()
            row = int(entry.get("row", 0) or 0)
            if grid_flow.page_of(row, rpp) != grid_flow.current_page():
                w.hide()
        # 小组件同样纳入桌面带守护（防 Win+D 等场景漂移后盖住应用窗口）
        self._band_guard.track(w)

    def apply_layout_mode(self):
        """v6 §1.3 模式切换后重排组件：关闭全部再按新模式 spawn。

        锚定组件的位置来源（cell_pos ↔ fx/fy）与尺寸来源（span 派生 ↔
        用户像素）都随模式变，逐个 set_anchored 式的原地切换表达不了
        「整体刷新」——3 个组件全量重建成本可忽略，语义最干净。
        """
        for w in list(self.widgets.values()):
            self._band_guard.untrack(w)
            w.close()
        self.widgets.clear()
        for entry in self.storage.widgets:
            if entry.get("hidden"):
                continue
            self._spawn(entry)

    def _on_closed(self, widget_id):
        w = self.widgets.pop(widget_id, None)
        if w is not None:
            self._band_guard.untrack(w)
        # 形态切换（锚定 <-> 悬浮）会关闭旧窗口再重建：entry 未 hidden
        # 就必须补一个，否则右键切一次组件就少一个
        entry = next((e for e in self.storage.widgets if e.get("id") == widget_id), None)
        if entry is not None and not entry.get("hidden") and widget_id not in self.widgets:
            self._spawn(entry)

    def sync_page(self, page: int):
        """M6 翻页联动：把所有锚定组件滑到新页位置（与图标同向）。

        只改视觉位置——entry 的 col/row 是全局行，不随页变化（零迁移）。
        非锚定（悬浮）组件不参与翻页：它们靠屏幕角落自由定位。

        v6 §4 分页禁半截：组件是**顶层窗口**，网格四边等距铺满后边距
        放不下整块组件——静止态下邻页组件会从屏顶/屏底露半截。因此：
        新页组件滑入前先显示（showEvent 补挂载 + 淡入，与滑入同向），
        滑出屏的组件动画结束后隐藏（_cull_widget 以当前页复核，防连翻）。
        """
        rpp = grid_flow.rows_per_page()
        page = int(page)
        for w in self.widgets.values():
            if not getattr(w, "anchored", False):
                continue
            col = int(w.entry.get("col", 0))
            row = int(w.entry.get("row", 0))
            on_page = grid_flow.page_of(row, rpp) == page
            if on_page and w.isHidden():
                w.show()      # 滑入前先显示（隐藏窗口的动画不可见）
            # v6 §1.3：位置统一走 widget_pos——网格模式 cell_pos、
            # 无界模式 fx/fy + 页间偏移（与图标同一套页载体语义）
            anim = w.animate_to(*grid_flow.widget_pos(self.storage, w.entry))
            if not on_page:
                if anim is None:
                    self._cull_widget(w)
                else:
                    anim.finished.connect(lambda w=w: self._cull_widget(w))

    def _cull_widget(self, w):
        """组件滑行结束：仍不在当前页就隐藏（v6 §4，防连翻误伤）。"""
        rpp = grid_flow.rows_per_page()
        row = int(w.entry.get("row", 0) or 0)
        if grid_flow.page_of(row, rpp) != grid_flow.current_page():
            w.hide()

    def set_anchored(self, entry_id: str, on: bool):
        """切换小组件的锚定（非悬浮）形态：改 entry 后重建该组件。"""
        entry = next((e for e in self.storage.widgets if e.get("id") == entry_id), None)
        if not entry or bool(entry.get("anchored")) == bool(on):
            return
        entry["anchored"] = bool(on)
        self.storage.save()
        w = self.widgets.pop(entry_id, None)
        if w is not None:
            self._band_guard.untrack(w)
            w.close()
        self._spawn(entry)

    def set_visible(self, on: bool):
        for w in self.widgets.values():
            w.setVisible(on)

    def toggle_entry(self, entry_id: str, visible: bool):
        entry = next((e for e in self.storage.widgets if e.get("id") == entry_id), None)
        if not entry:
            return
        entry["hidden"] = not visible
        self.storage.save()
        if visible and entry_id not in self.widgets:
            self._place_default(entry)
            self._spawn(entry)
        elif not visible and entry_id in self.widgets:
            w = self.widgets.pop(entry_id)
            self._band_guard.untrack(w)
            w.close()

    def add_note(self):
        import uuid
        entry = {"id": uuid.uuid4().hex[:8], "type": "notes",
                 "w": 300, "h": 300, "hidden": False, "text": ""}
        self.storage.widgets.append(entry)
        self._place_default(entry)
        self.storage.save()
        self._spawn(entry)
