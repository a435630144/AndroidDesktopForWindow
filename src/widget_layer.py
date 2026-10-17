# -*- coding: utf-8 -*-
"""小组件管理层：统一创建 / 显隐 / 关闭桌面小组件。"""
from PySide6.QtWidgets import QApplication

from .band_guard import BandGuard
from .widget_base import FloatingWidget
from .widgets_clock import ClockWidget
from .widgets_notes import NotesWidget
from .widgets_panel import DesktopPanel

WIDGET_TYPES = {"clock": ClockWidget, "notes": NotesWidget, "panel": DesktopPanel}

WIDGET_NAMES = {"clock": "时钟", "notes": "便签", "panel": "桌面面板"}


class WidgetLayer:
    def __init__(self, storage):
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
        """首次创建（没有保存过位置）时按类型放到合适位置，避免互相遮挡。"""
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
        w = cls(self.storage, entry)
        w.closed.connect(self._on_closed)
        self.widgets[entry["id"]] = w
        w.show()
        # 小组件同样纳入桌面带守护（防 Win+D 等场景漂移后盖住应用窗口）
        self._band_guard.track(w)

    def _on_closed(self, widget_id):
        w = self.widgets.pop(widget_id, None)
        if w is not None:
            self._band_guard.untrack(w)

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
