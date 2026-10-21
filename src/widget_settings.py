# -*- coding: utf-8 -*-
"""组件设置面板（v8 C8 / v9 V1 扩展）。

组件不自己写设置界面：在注册表的 `WidgetSpec.settings` 里声明
`FieldSpec` 列表，本模块按声明生成表单。好处是

  - 所有组件的设置长得一样（标签宽度、控件间距、按钮位置统一）；
  - "有没有设置"就是"声明列表空不空"，右键菜单据此决定是否出现入口
    （不留灰项——灰项等于"点不动"，用户会以为坏了）；
  - 新组件加设置 = 加一行 FieldSpec，不写 UI 代码。

v9 起按 `FieldSpec.group` 分组：组件自己的字段归「组件设置」，通用外观
（背景色/透明度/文字色/强调色/圆角）归「外观」——用户一眼能分清
"这个组件特有的" 与 "所有组件都有的"。

存储位置：`entry["settings"][key]`。组件自己实现 `on_settings_changed()`
决定要不要立即重绘 / 重拉数据（天气就是重拉）。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSlider, QSpinBox, QVBoxLayout, QWidget)

from . import theme
from .ui_choice import ComboBox
from .widget_registry import FieldSpec, WidgetSpec
from .widget_style import MAX_ALPHA, MIN_ALPHA

LABEL_W = 96
DEFAULT_GROUP = "组件设置"

DLG_QSS = (
    "QDialog{background: %s;}"
    "QLabel{color: %s; font-size: 13px; background: transparent;}"
    "QLabel#hint{color: %s; font-size: 11px;}"
    "QLabel#group{color: %s; font-size: 12px; font-weight: 600;}"
) % (theme.rgba(theme.SURFACE_POPUP), theme.rgba(theme.TEXT),
     theme.rgba(theme.TEXT_FAINT), theme.rgba(theme.TEXT_DIM))


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


def groups_of(spec: WidgetSpec) -> Dict[str, List[FieldSpec]]:
    """按 group 分组（保持声明顺序；组顺序 = 首次出现顺序）。"""
    out: Dict[str, List[FieldSpec]] = {}
    for f in spec.settings:
        out.setdefault(f.group or DEFAULT_GROUP, []).append(f)
    return out


class ColorField(QWidget):
    """颜色选择：色块按钮 + 「清除」。空值 = 跟随主题。"""

    def __init__(self, value="", parent=None):
        super().__init__(parent)
        self._value = self._norm(value)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.btn = QPushButton()
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setFixedHeight(26)
        self.btn.clicked.connect(self._pick)
        lay.addWidget(self.btn, 1)
        self.clear_btn = QPushButton("清除")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setFixedHeight(26)
        self.clear_btn.setFixedWidth(52)
        self.clear_btn.setStyleSheet(theme.BUTTON_QSS)
        self.clear_btn.clicked.connect(lambda: self.set_value(""))
        lay.addWidget(self.clear_btn)
        self._sync()

    @staticmethod
    def _norm(value) -> str:
        if not isinstance(value, str):
            return ""
        from PySide6.QtGui import QColor
        s = value.strip()
        return s.upper() if QColor(s).isValid() else ""

    def _pick(self):
        from PySide6.QtGui import QColor
        start = QColor(self._value) if self._value else QColor(theme.ACCENT)
        c = QColorDialog.getColor(start, self, "选择颜色")
        if c.isValid():
            self.set_value(c.name().upper())

    def _sync(self):
        from PySide6.QtGui import QColor
        if self._value:
            c = QColor(self._value)
            # 色块用背景色表达，文字用对比色，深浅两色都看得清
            lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
            fg = "#101216" if lum > 150 else "#F2F3F5"
            self.btn.setText(self._value)
            self.btn.setStyleSheet(
                "QPushButton{background: %s; color: %s; border: 1px solid rgba(255,255,255,40);"
                " border-radius: 6px; font-size: 12px;}" % (c.name(), fg))
        else:
            self.btn.setText("跟随主题")
            self.btn.setStyleSheet(theme.BUTTON_QSS)
        self.clear_btn.setVisible(bool(self._value))

    def value(self) -> str:
        return self._value

    def set_value(self, value):
        self._value = self._norm(value)
        self._sync()

    # 兼容"控件里能读出字符串"的通用读法
    def text(self) -> str:
        return self._value


class FloatField(QWidget):
    """0~1 浮点：滑条 + 百分比文字（透明度用它）。"""

    def __init__(self, value=1.0, lo=MIN_ALPHA, hi=MAX_ALPHA, parent=None):
        super().__init__(parent)
        self._lo, self._hi = float(lo), float(hi)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(int(self._lo * 100), int(self._hi * 100))
        self.slider.setSingleStep(5)
        self.slider.setPageStep(10)
        self.slider.setStyleSheet(theme.SLIDER_QSS)
        lay.addWidget(self.slider, 1)
        self.label = QLabel("")
        self.label.setFixedWidth(46)
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.label.setStyleSheet("color: %s; font-size: 12px;" % theme.rgba(theme.TEXT_DIM))
        lay.addWidget(self.label)
        self.set_value(value)
        self.slider.valueChanged.connect(lambda _v: self._sync_label())

    def _sync_label(self):
        self.label.setText("%d%%" % self.slider.value())

    def value(self) -> float:
        return self.slider.value() / 100.0

    def set_value(self, value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = self._hi
        self.slider.setValue(int(round(max(self._lo, min(self._hi, v)) * 100)))
        self._sync_label()


class WidgetSettingsDialog(QDialog):
    """按 FieldSpec 生成的通用设置对话框（按 group 分段）。"""

    def __init__(self, spec: WidgetSpec, entry: dict, storage, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.entry = entry
        self.storage = storage
        self._controls: Dict[str, QWidget] = {}
        self.setWindowTitle("%s · 设置" % spec.name)
        self.setStyleSheet(DLG_QSS)
        self.setMinimumWidth(400)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        title = QLabel("%s · 设置" % spec.name)
        title.setStyleSheet("color: %s; font-size: 15px; font-weight: 600;"
                            % theme.rgba(theme.TEXT))
        root.addWidget(title)

        vals = current_values(spec, entry.get("settings"))
        for group, fields in groups_of(spec).items():
            head = QLabel(group)
            head.setObjectName("group")
            root.addWidget(head)
            root.addLayout(self._build_form(fields, vals))

        btns = QHBoxLayout()
        btn_reset = QPushButton("恢复默认")
        btn_reset.setStyleSheet(theme.BUTTON_QSS)
        btn_reset.clicked.connect(self._on_reset)
        btns.addWidget(btn_reset)
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

    def _build_form(self, fields: List[FieldSpec], vals: Dict) -> QFormLayout:
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        for f in fields:
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
                hint.setWordWrap(True)
                box.addWidget(hint)
            lab = QLabel(f.label)
            lab.setFixedWidth(LABEL_W)
            form.addRow(lab, holder)
        return form

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
        if f.kind == "color":
            return ColorField(value)
        if f.kind == "float":
            return FloatField(value)
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
            elif f.kind in ("color", "float"):
                out[f.key] = c.value()
            else:
                out[f.key] = c.text().strip()
        return out

    # ---------- 动作 ----------
    def _on_reset(self):
        """恢复默认：把每个控件还原成 FieldSpec.default（不落盘，仍需「应用」）。"""
        for f in self.spec.settings:
            c = self._controls[f.key]
            if f.kind == "bool":
                c.setChecked(bool(f.default))
            elif f.kind == "combo":
                for i, (v, _l) in enumerate(f.choices):
                    if v == f.default:
                        c.setCurrentIndex(i)
                        break
            elif f.kind == "int":
                c.setValue(int(f.default))
            elif f.kind in ("color", "float"):
                c.set_value(f.default)
            else:
                c.setText("" if f.default is None else str(f.default))

    def _on_apply(self):
        self.apply()
        self.accept()

    def apply(self) -> bool:
        """写盘（拆出来便于测试：不弹窗也能验）。"""
        apply_values(self.entry, self.read_values(), self.storage)
        return True
