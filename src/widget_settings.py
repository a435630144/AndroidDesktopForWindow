# -*- coding: utf-8 -*-
"""组件设置面板（v8 C8，指导文档_v8.md §5）。

组件不自己写设置界面：在注册表的 `WidgetSpec.settings` 里声明
`FieldSpec` 列表，本模块按声明生成表单。好处是

  - 四个组件的设置长得一样（标签宽度、控件间距、按钮位置统一）；
  - "有没有设置"就是"声明列表空不空"，右键菜单据此决定是否出现入口
    （不留灰项——灰项等于"点不动"，用户会以为坏了）；
  - 新组件加设置 = 加一行 FieldSpec，不写 UI 代码。

存储位置：`entry["settings"][key]`。组件自己实现 `on_settings_changed()`
决定要不要立即重绘 / 重拉数据（天气就是重拉）。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from . import theme
from .ui_choice import ComboBox
from .widget_registry import FieldSpec, WidgetSpec

LABEL_W = 96

DLG_QSS = (
    "QDialog{background: %s;}"
    "QLabel{color: %s; font-size: 13px; background: transparent;}"
    "QLabel#hint{color: %s; font-size: 11px;}"
) % (theme.rgba(theme.SURFACE_POPUP), theme.rgba(theme.TEXT),
     theme.rgba(theme.TEXT_FAINT))


def current_values(spec: WidgetSpec, settings: Optional[Dict]) -> Dict:
    """把 entry 里已有的设置与声明默认值合并（缺的用默认）。"""
    s = settings if isinstance(settings, dict) else {}
    return {f.key: s.get(f.key, f.default) for f in spec.settings}


def apply_values(entry: dict, values: Dict, storage) -> None:
    """把值写进 entry["settings"] 并落盘（其它键原样保留）。"""
    merged = dict(entry.get("settings") or {})
    merged.update(values)
    entry["settings"] = merged
    try:
        storage.save()
    except Exception:      # noqa: BLE001
        pass


def apply_to_widget(widget, spec: WidgetSpec, values: Dict, storage) -> None:
    """写入并通知组件刷新（组件库/测试都可直接调，不必开对话框）。"""
    apply_values(widget.entry, values, storage)
    cb = getattr(widget, "on_settings_changed", None)
    if callable(cb):
        cb()


class WidgetSettingsDialog(QDialog):
    """按 FieldSpec 生成的通用设置对话框。"""

    def __init__(self, spec: WidgetSpec, entry: dict, storage, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.entry = entry
        self.storage = storage
        self._controls: Dict[str, QWidget] = {}
        self.setWindowTitle("%s · 设置" % spec.name)
        self.setStyleSheet(DLG_QSS)
        self.setMinimumWidth(380)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        title = QLabel("%s · 设置" % spec.name)
        title.setStyleSheet("color: %s; font-size: 15px; font-weight: 600;"
                            % theme.rgba(theme.TEXT))
        root.addWidget(title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        vals = current_values(spec, entry.get("settings"))
        for f in spec.settings:
            ctl = self._build_control(f, vals.get(f.key))
            self._controls[f.key] = ctl
            holder = QWidget()
            box = QVBoxLayout(holder)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(2)
            box.addWidget(ctl)
            if f.hint:
                hint = QLabel(f.hint)
                hint.setObjectName("hint")
                box.addWidget(hint)
            lab = QLabel(f.label)
            lab.setFixedWidth(LABEL_W)
            form.addRow(lab, holder)
        root.addLayout(form)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet(theme.BUTTON_QSS)
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("应用")
        btn_ok.setStyleSheet(theme.BUTTON_QSS)
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._on_apply)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        root.addLayout(btns)

    # ---------- 控件 ----------
    def _build_control(self, f: FieldSpec, value) -> QWidget:
        if f.kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(value))
            w.setStyleSheet(theme.CHECKBOX_QSS)
            return w
        if f.kind == "combo":
            w = ComboBox()
            for v, label in f.choices:
                w.addItem(label, v)
            idx = 0
            for i, (v, _label) in enumerate(f.choices):
                if v == value:
                    idx = i
                    break
            if f.choices:
                w.setCurrentIndex(idx)
            return w
        if f.kind == "int":
            w = QSpinBox()
            w.setRange(-9999, 9999)
            try:
                w.setValue(int(value))
            except (TypeError, ValueError):
                pass
            w.setStyleSheet(theme.INPUT_QSS)
            return w
        w = QLineEdit()
        w.setText("" if value is None else str(value))
        w.setPlaceholderText(f.placeholder)
        w.setStyleSheet(theme.INPUT_QSS)
        return w

    def read_values(self) -> Dict:
        out = {}
        for f in self.spec.settings:
            c = self._controls[f.key]
            if f.kind == "bool":
                out[f.key] = bool(c.isChecked())
            elif f.kind == "combo":
                out[f.key] = c.currentData()
            elif f.kind == "int":
                out[f.key] = int(c.value())
            else:
                out[f.key] = c.text().strip()
        return out

    # ---------- 动作 ----------
    def _on_apply(self):
        self.apply()
        self.accept()

    def apply(self) -> bool:
        """写盘（拆出来便于测试：不弹窗也能验）。"""
        apply_values(self.entry, self.read_values(), self.storage)
        return True
