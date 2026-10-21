# -*- coding: utf-8 -*-
"""组件库窗口（v8 C3，指导文档_v8.md §3）。

职责：让用户**看见有哪些组件**（预览 + 一句话说明），并且一次点击就能
放到桌面。它不是设置页的一角——预览需要宽度，管理需要列表，独立窗口
才放得下（规格 §3.1 已拍板）。

与组件的关系：
    卡片预览调 `spec.preview(painter, rect)`；组件没提供 preview 时用
    `widget_glass.draw_preview()` 兜底。**预览不实例化组件**——否则打开
    组件库会顺带启定时器（监控每秒采样、天气立刻联网），不可接受。

四种卡片状态（规格 §3.3）：
    未添加            -> 「添加到桌面」
    多实例已添加      -> 「添加到桌面」（可继续加）
    已添加且隐藏      -> 「显示」
    已添加且显示中    -> 「已在桌面」灰显
    已添加的卡片右侧都有「移除」。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from . import theme
from . import widget_registry
from .widget_glass import draw_preview as _fallback_preview
from .widget_registry import WidgetSpec

CARD_W = 320
CARD_H = 212
PREVIEW_H = 118
COLS = 2

center = None      # 单例（模块级）


def _btn_qss() -> str:
    return theme.BUTTON_QSS + (
        "QPushButton:disabled{background: rgba(255,255,255,10);"
        " border: 1px solid rgba(255,255,255,16); color: rgba(242,243,245,110);}"
    )


class PreviewArea(QWidget):
    """卡片上半：实时画组件预览（同一套 draw()，换个示例 model）。"""

    def __init__(self, spec: WidgetSpec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.setFixedHeight(PREVIEW_H)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.save()
        p.setClipPath(path)
        p.fillRect(self.rect(), QColor(18, 20, 26, 190))
        try:
            if callable(self.spec.preview):
                self.spec.preview(p, r)
            else:
                _fallback_preview(p, r, self.spec.name, self.spec.summary)
        except Exception:      # noqa: BLE001  —— 一个组件画挂不该让整个库白屏
            _fallback_preview(p, r, self.spec.name, "预览不可用")
        p.restore()
        p.setBrush(Qt.NoBrush)
        p.setPen(QColor(255, 255, 255, 20))
        p.drawRoundedRect(r, 12, 12)


class WidgetCard(QFrame):
    """一张组件卡：预览 + 名称 + 说明 + 主按钮 + 移除。"""

    def __init__(self, spec: WidgetSpec, layer, owner, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.layer = layer
        self.owner = owner
        self.setFixedSize(CARD_W, CARD_H)
        self.setStyleSheet(
            "WidgetCard{background: rgba(255,255,255,10);"
            " border: 1px solid rgba(255,255,255,22); border-radius: 14px;}")

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.preview = PreviewArea(spec, self)
        root.addWidget(self.preview)

        name = QLabel(spec.name)
        name.setStyleSheet("color: %s; font-size: 14px; font-weight: 600;"
                           " background: transparent;" % theme.rgba(theme.TEXT))
        root.addWidget(name)

        sub = QLabel(spec.summary)
        sub.setWordWrap(True)
        sub.setStyleSheet("color: %s; font-size: 11px; background: transparent;"
                          % theme.rgba(theme.TEXT_DIM))
        root.addWidget(sub)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.button = QPushButton("添加到桌面")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setStyleSheet(_btn_qss())
        self.button.clicked.connect(self._on_primary)
        row.addWidget(self.button, 1)

        self.remove_btn = QPushButton("移除")
        self.remove_btn.setCursor(Qt.PointingHandCursor)
        self.remove_btn.setFixedWidth(56)
        self.remove_btn.setStyleSheet(_btn_qss())
        self.remove_btn.clicked.connect(self._on_remove)
        row.addWidget(self.remove_btn)
        root.addLayout(row)

        self.refresh_state()

    # ---------- 状态 ----------
    def entries(self):
        return self.layer.entries_of(self.spec.type)

    def refresh_state(self):
        entries = self.entries()
        hidden = [e for e in entries if e.get("hidden")]
        if not entries:
            self.button.setText("添加到桌面")
            self.button.setEnabled(True)
            self.remove_btn.setVisible(False)
        elif hidden:
            self.button.setText("显示")
            self.button.setEnabled(True)
            self.remove_btn.setVisible(True)
        elif self.spec.multi_instance:
            self.button.setText("添加到桌面")
            self.button.setEnabled(True)
            self.remove_btn.setVisible(True)
        else:
            self.button.setText("已在桌面")
            self.button.setEnabled(False)
            self.remove_btn.setVisible(True)

    # ---------- 动作 ----------
    def _on_primary(self):
        entries = self.entries()
        hidden = next((e for e in entries if e.get("hidden")), None)
        if hidden is not None:
            self.layer.toggle_entry(hidden.get("id"), True)
        else:
            self.layer.add(self.spec.type)
        self.owner.refresh()

    def _on_remove(self):
        entries = self.entries()
        if entries:
            self.layer.remove(entries[0].get("id"))
        self.owner.refresh()


class WidgetCenter(QDialog):
    """组件库主窗口（非模态，可与桌面同时操作）。"""

    settingsRequested = Signal()

    def __init__(self, layer, parent=None):
        super().__init__(parent)
        global center
        center = self
        self.layer = layer
        self.cards: List[WidgetCard] = []
        self._visible_types: List[str] = []

        self.setWindowTitle("组件库")
        self.setModal(False)
        self.resize(900, 620)
        self.setStyleSheet(
            "QDialog{background: %s;} QLabel{background: transparent;}"
            % theme.rgba(theme.SURFACE_POPUP))

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        # 顶部：标题 + 搜索
        head = QHBoxLayout()
        title = QLabel("组件库")
        title.setStyleSheet("color: %s; font-size: 17px; font-weight: 600;"
                            % theme.rgba(theme.TEXT))
        head.addWidget(title)
        head.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索组件…")
        self.search.setFixedWidth(220)
        self.search.setStyleSheet(theme.INPUT_QSS)
        self.search.textChanged.connect(lambda _t: self.refresh())
        head.addWidget(self.search)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(14)

        # 左：分类
        self.cats = QListWidget()
        self.cats.setFixedWidth(150)
        self.cats.setStyleSheet(theme.LIST_QSS)
        self.cats.currentItemChanged.connect(lambda *_: self.refresh())
        body.addWidget(self.cats)

        # 右：卡片滚动区
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea{background: transparent;}"
                                  " QScrollArea > QWidget > QWidget{background: transparent;}")
        holder = QWidget()
        self.grid = QGridLayout(holder)
        self.grid.setContentsMargins(0, 0, 8, 0)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(12)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.empty_tip = QLabel("没有匹配的组件")
        self.empty_tip.setAlignment(Qt.AlignCenter)
        self.empty_tip.setStyleSheet("color: %s; font-size: 13px; padding: 40px 0;"
                                     % theme.rgba(theme.TEXT_FAINT))
        self.empty_tip.setVisible(False)
        self.grid.addWidget(self.empty_tip, 0, 0, 1, COLS)
        self.scroll.setWidget(holder)
        body.addWidget(self.scroll, 1)
        root.addLayout(body, 1)

        # 底部：计数 + 设置入口
        foot = QHBoxLayout()
        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color: %s; font-size: 12px;"
                                       % theme.rgba(theme.TEXT_FAINT))
        foot.addWidget(self.count_label)
        foot.addStretch(1)
        btn = QPushButton("打开设置…")
        btn.setStyleSheet(_btn_qss())
        btn.clicked.connect(self.settingsRequested.emit)
        foot.addWidget(btn)
        root.addLayout(foot)

        self._build_cards()
        self._build_categories()
        if hasattr(self.layer, "widgetsChanged"):
            self.layer.widgetsChanged.connect(self.refresh)
        self.refresh()

    # ---------- 构建 ----------
    def _build_cards(self):
        for spec in widget_registry.all_specs():
            card = WidgetCard(spec, self.layer, self, self)
            self.cards.append(card)

    def _build_categories(self):
        self.cats.clear()
        for name in ["全部"] + widget_registry.categories():
            counts = self.category_counts().get(name, 0)
            item = QListWidgetItem("%s  %d" % (name, counts))
            item.setData(Qt.UserRole, name)
            self.cats.addItem(item)
        if self.cats.count():
            self.cats.setCurrentRow(0)

    def category_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for spec in widget_registry.all_specs():
            counts[spec.category] = counts.get(spec.category, 0) + 1
        counts["全部"] = len(widget_registry.all_specs())
        return counts

    # ---------- 过滤 / 刷新 ----------
    def current_category(self) -> str:
        item = self.cats.currentItem()
        return (item.data(Qt.UserRole) if item is not None else "全部") or "全部"

    def select_category(self, name: str):
        for i in range(self.cats.count()):
            if self.cats.item(i).data(Qt.UserRole) == name:
                self.cats.setCurrentRow(i)
                return

    def _matches(self, spec: WidgetSpec, cat: str, query: str) -> bool:
        if cat != "全部" and spec.category != cat:
            return False
        if not query:
            return True
        q = query.strip().lower()
        return q in spec.name.lower() or q in spec.summary.lower()

    def refresh(self):
        cat = self.current_category()
        query = self.search.text() if hasattr(self, "search") else ""
        # 分类角标随数据刷新（数量是静态的，但保持一处计算）
        counts = self.category_counts()
        for i in range(self.cats.count()):
            item = self.cats.item(i)
            name = item.data(Qt.UserRole)
            item.setText("%s  %d" % (name, counts.get(name, 0)))

        shown = []
        for card in self.cards:
            card.refresh_state()
            ok = self._matches(card.spec, cat, query)
            card.setVisible(ok)
            if ok:
                shown.append(card)

        # 重新摆格子（数量少，重建比增量挪动简单且不会错位）
        for card in self.cards:
            self.grid.removeWidget(card)
        self.grid.removeWidget(self.empty_tip)
        for i, card in enumerate(shown):
            self.grid.addWidget(card, i // COLS, i % COLS)
        self.empty_tip.setVisible(not shown)
        if not shown:
            self.grid.addWidget(self.empty_tip, 0, 0, 1, COLS)

        self._visible_types = [c.spec.type for c in shown]
        self.count_label.setText("已添加 %d 个组件" % len(self.layer.storage.widgets))

    def visible_cards(self) -> List[WidgetCard]:
        return [c for c in self.cards if c.isVisible()]

    def closeEvent(self, e):
        try:
            self.layer.widgetsChanged.disconnect(self.refresh)
        except (RuntimeError, TypeError):
            pass
        super().closeEvent(e)


def open_center(layer, parent=None) -> WidgetCenter:
    """打开组件库（单例：重复点击只是把已有窗口提到前面）。"""
    global center
    try:
        if center is not None:
            if hasattr(center, "refresh"):
                center.refresh()
            center.show()
            center.raise_()
            center.activateWindow()
            return center
    except RuntimeError:      # C++ 对象已被销毁（关闭并回收）
        center = None
    center = WidgetCenter(layer, parent)
    center.show()
    center.raise_()
    return center
