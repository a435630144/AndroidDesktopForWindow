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
            # 锚定组件：分配网格占位（排除已有组件与图标），按格点定位
            if "col" not in entry:
                col, row = grid_flow.find_widget_slot(self.storage, entry)
                entry["col"], entry["row"] = col, row
            cs, rs = grid_flow.widget_span(self.storage, entry)
            entry["colspan"], entry["rowspan"] = cs, rs
            ox, oy = grid_flow.origin()
            cw, ch = grid_flow.cell_size(self.storage)
            entry["x"] = ox + int(entry["col"]) * cw
            entry["y"] = oy + int(entry["row"]) * ch
            self.storage.save()
        w = cls(self.storage, entry)
        w.closed.connect(self._on_closed)
        w.gridChanged.connect(self.gridChanged.emit)
        self.widgets[entry["id"]] = w
        w.show()
        # 小组件同样纳入桌面带守护（防 Win+D 等场景漂移后盖住应用窗口）
        self._band_guard.track(w)

    def _on_closed(self, widget_id):
        w = self.widgets.pop(widget_id, None)
        if w is not None:
            self._band_guard.untrack(w)
        # 形态切换（锚定 <-> 悬浮）会关闭旧窗口再重建：entry 未 hidden
        # 就必须补一个，否则右键切一次组件就少一个
        entry = next((e for e in self.storage.widgets if e.get("id") == widget_id), None)
        if entry is not None and not entry.get("hidden") and widget_id not in self.widgets:
            self._spawn(entry)

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
