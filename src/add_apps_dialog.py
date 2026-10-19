# -*- coding: utf-8 -*-
"""添加应用对话框：从内置系统入口 + 开始菜单扫描结果中选择，添加到桌面整理。"""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout)

from . import appsource
from . import theme
from .storage import entry_app


class AddAppsDialog(QDialog):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setWindowTitle("添加应用")
        self.resize(480, 560)
        self.setStyleSheet(theme.DIALOG_QSS + theme.INPUT_QSS + theme.LIST_QSS
                           + theme.BUTTON_QSS)
        self._apps = []
        self._build()
        self._reload()

    def _build(self):
        root = QVBoxLayout(self)
        tip = QLabel("双击列表项即可添加到桌面整理（来源：开始菜单与桌面文件扫描）")
        tip.setWordWrap(True)
        root.addWidget(tip)
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("搜索应用名称…")
        self.ed_search.textChanged.connect(self._reload)
        root.addWidget(self.ed_search)
        self.list = QListWidget()
        self.list.setIconSize(QSize(32, 32))
        self.list.itemDoubleClicked.connect(self._add_current)
        root.addWidget(self.list)
        self.btn_add = QPushButton("添加到桌面")
        self.btn_add.clicked.connect(self._add_current)
        root.addWidget(self.btn_add)

    def _reload(self):
        kw = self.ed_search.text().strip().lower()
        existing = set()
        for e in self.window.storage.layout:
            if e.get("type") == "app":
                existing.add(entry_app(e).get("target", ""))
            else:
                for a in e.get("apps", []):
                    existing.add(a.get("target", ""))
        self.list.clear()
        self._apps = []
        for app in appsource.all_apps():
            if app.get("target", "") in existing:
                continue
            if kw and kw not in app.get("name", "").lower():
                continue
            item = QListWidgetItem(appsource.icon_for(app, 32), app.get("name", ""))
            self.list.addItem(item)
            self._apps.append(app)

    def _add_current(self):
        row = self.list.currentRow()
        if 0 <= row < len(self._apps):
            self.window.add_app(self._apps[row])
            self._reload()
