# -*- coding: utf-8 -*-
"""便签小组件：深色卡片 + 自动保存。"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QTextEdit, QVBoxLayout

from . import theme
from .widget_base import FloatingWidget


class NotesWidget(FloatingWidget):
    TYPE = "notes"

    def __init__(self, storage, entry):
        # interactive=True：去掉 NOACTIVATE，QTextEdit 才能获得键盘焦点输入
        super().__init__(storage, entry, interactive=True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 34, 14, 14)
        lay.setSpacing(8)
        title = QLabel("便签")
        title.setFont(theme.ui_font(12))
        title.setStyleSheet("color: %s; background: transparent;" % theme.rgba(theme.TEXT_FAINT))
        lay.addWidget(title)
        self.edit = QTextEdit()
        self.edit.setPlaceholderText("写点什么，自动保存…")
        self.edit.setPlainText(entry.get("text", ""))
        self.edit.setStyleSheet(
            ("QTextEdit{background: %s; color: rgb(242,243,245); border: 1px solid %s;"
             " border-radius: 10px; padding: 8px; font-family: %s; font-size: 13px;}"
             "QTextEdit:focus{border: 1px solid %s;}")
            % (theme.rgba(theme.SURFACE_RAISED), theme.rgba(theme.BORDER),
               ", ".join('"%s"' % f for f in theme.FONT_FAMILIES), theme.rgba(theme.ACCENT_BORDER)))
        lay.addWidget(self.edit)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self._save_text)
        self.edit.textChanged.connect(self._save_timer.start)

    def _save_text(self):
        self.entry["text"] = self.edit.toPlainText()
        self.storage.save()
