# -*- coding: utf-8 -*-
"""设置对话框：深色主题；开机自启 / 图标大小 / 列数 / 不透明度 / 小组件 /
原生图标 / 重新扫描 / 托盘行为 / 重置布局。所有项实时生效。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QSlider, QSpinBox, QVBoxLayout)

from . import autostart
from . import theme


class SettingsDialog(QDialog):
    def __init__(self, window, storage, layer, parent=None):
        super().__init__(parent)
        self.window = window
        self.storage = storage
        self.layer = layer
        self.setWindowTitle("桌面整理Demo - 设置")
        self.setMinimumWidth(480)
        self.setStyleSheet(theme.DIALOG_QSS + theme.CHECKBOX_QSS + theme.SLIDER_QSS
                           + theme.SPIN_QSS + theme.BUTTON_QSS)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(14)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)
        lbl_style = "color: rgb(216,220,226); font-size: 13px;"

        self.chk_autostart = QCheckBox("开机自动启动（写当前用户注册表 Run 项，无需管理员）")
        self.chk_autostart.setChecked(autostart.is_enabled())
        self.chk_autostart.toggled.connect(self._apply_autostart)
        form.addRow("启动：", self.chk_autostart)

        self.sld_icon = QSlider(Qt.Horizontal)
        self.sld_icon.setRange(48, 128)
        self.sld_icon.setSingleStep(8)
        self.sld_icon.setPageStep(8)
        self.sld_icon.setValue(int(self.storage.get_setting("icon_size")))
        self.lbl_icon = QLabel("%d px" % self.sld_icon.value())
        self.lbl_icon.setStyleSheet(lbl_style)
        self.sld_icon.valueChanged.connect(self._apply_icon_size)
        icon_row = QHBoxLayout()
        icon_row.addWidget(self.sld_icon)
        icon_row.addWidget(self.lbl_icon)
        form.addRow("图标大小：", icon_row)

        # 图标缩放比例：DPI 感知之上的用户微调（2026-10-18 用户要求）
        self.sld_scale = QSlider(Qt.Horizontal)
        self.sld_scale.setRange(60, 200)
        self.sld_scale.setSingleStep(5)
        self.sld_scale.setPageStep(10)
        self.sld_scale.setValue(int(round(float(self.storage.get_setting("icon_scale")) * 100)))
        self.lbl_scale = QLabel()
        self.lbl_scale.setStyleSheet(lbl_style)
        self.sld_scale.valueChanged.connect(self._apply_icon_scale)
        scale_row = QHBoxLayout()
        scale_row.addWidget(self.sld_scale)
        scale_row.addWidget(self.lbl_scale)
        form.addRow("图标缩放比例：", scale_row)
        self._refresh_icon_labels()

        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(3, 12)
        self.spin_cols.setValue(int(self.storage.get_setting("columns")))
        self.spin_cols.valueChanged.connect(self._apply_columns)
        form.addRow("每行图标数：", self.spin_cols)

        self.sld_opacity = QSlider(Qt.Horizontal)
        self.sld_opacity.setRange(50, 100)
        self.sld_opacity.setValue(int(float(self.storage.get_setting("opacity")) * 100))
        self.lbl_opacity = QLabel("%d%%" % self.sld_opacity.value())
        self.lbl_opacity.setStyleSheet(lbl_style)
        self.sld_opacity.valueChanged.connect(self._apply_opacity)
        op_row = QHBoxLayout()
        op_row.addWidget(self.sld_opacity)
        op_row.addWidget(self.lbl_opacity)
        form.addRow("整理窗口不透明度（仅悬浮模式）：", op_row)

        self.chk_widgets = QCheckBox("在桌面显示小组件（时钟 / 便签 / 桌面面板）")
        self.chk_widgets.setChecked(bool(self.storage.get_setting("show_widgets")))
        self.chk_widgets.toggled.connect(self._apply_widgets)
        form.addRow("小组件：", self.chk_widgets)

        self.chk_native = QCheckBox("桌面整理模式：隐藏原生图标，由整理桌面接管（框选 / 自己的右键菜单）")
        self.chk_native.setChecked(bool(self.storage.get_setting("hide_native_icons")))
        self.chk_native.toggled.connect(self._apply_native_icons)
        form.addRow("桌面模式：", self.chk_native)

        self.chk_autoclone = QCheckBox("自动把桌面文件克隆进整理网格（关闭则只显示手动添加的图标）")
        self.chk_autoclone.setChecked(bool(self.storage.get_setting("auto_clone_desktop")))
        self.chk_autoclone.toggled.connect(self._apply_auto_clone)
        form.addRow("自动克隆：", self.chk_autoclone)

        self.chk_tray = QCheckBox("关闭整理窗口时隐藏到托盘（取消勾选则直接退出程序）")
        self.chk_tray.setChecked(bool(self.storage.get_setting("minimize_to_tray")))
        self.chk_tray.toggled.connect(lambda v: self.storage.set_setting("minimize_to_tray", bool(v)))
        form.addRow("托盘：", self.chk_tray)

        root.addLayout(form)

        self.btn_rescan = QPushButton("重新扫描桌面文件")
        self.btn_rescan.clicked.connect(self._rescan)
        root.addWidget(self.btn_rescan)

        self.btn_reset = QPushButton("重置桌面布局（重新克隆桌面文件）")
        self.btn_reset.clicked.connect(self._reset_layout)
        root.addWidget(self.btn_reset)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_close = QPushButton("完成")
        self.btn_close.clicked.connect(self.accept)
        btns.addWidget(self.btn_close)
        root.addLayout(btns)

    # ---------- 实时生效 ----------
    def _apply_autostart(self, checked):
        autostart.set_enabled(checked)
        self.storage.set_setting("autostart", bool(checked))

    def _refresh_icon_labels(self):
        """图标大小 / 缩放标签：显示 基准 × 系统DPI × 用户缩放 = 实际像素。"""
        from . import theme
        base = int(self.storage.get_setting("icon_size"))
        scale = int(round(float(self.storage.get_setting("icon_scale")) * 100))
        self.lbl_icon.setText("%d px" % base)
        self.lbl_scale.setText("%d%%（系统 %d%% × %d%% = 实际 %d px）"
                               % (scale, round(theme.screen_dpr() * 100),
                                  scale, self.storage.icon_metric()))

    def _apply_icon_size(self, value):
        self.storage.set_setting("icon_size", int(value))
        self._refresh_icon_labels()
        self.window.rebuild()

    def _apply_icon_scale(self, value):
        self.storage.set_setting("icon_scale", value / 100.0)
        self._refresh_icon_labels()
        self.window.rebuild()

    def _apply_columns(self, value):
        self.storage.set_setting("columns", int(value))
        self.storage.compact_layout()
        self.storage.save()
        self.window.rebuild()

    def _apply_opacity(self, value):
        self.lbl_opacity.setText("%d%%" % value)
        self.storage.set_setting("opacity", value / 100.0)
        # 桌面带模式下窗口铺满全屏、只绘制图标：调窗口透明度会连图标一起
        # 淡化，因此该设置仅在悬浮模式（挂载失败兜底）下生效
        if self.window.attached:
            self.window.setWindowOpacity(1.0)
        else:
            self.window.setWindowOpacity(value / 100.0)

    def _apply_widgets(self, checked):
        self.storage.set_setting("show_widgets", bool(checked))
        self.layer.set_visible(bool(checked))

    def _apply_native_icons(self, checked):
        """切换桌面整理模式：开=隐藏原生图标全盘接管；关=恢复原生桌面。"""
        self.storage.set_setting("hide_native_icons", bool(checked))
        self.window.apply_native_icons_setting()
        if checked:
            # 开启整理模式 = 原生图标被隐藏、网格全盘接管：必须保证桌面文件
            # 已播种，否则用户面对的是空桌面（旧逻辑受 auto_clone 开关与
            # "布局为空"双重门槛限制，是 2026-10-18 反馈"文件缺少很多"的根因）
            self.storage.ensure_desktop_clone(force=True)
            self.window.rebuild()

    def _apply_auto_clone(self, checked):
        self.storage.set_setting("auto_clone_desktop", bool(checked))
        if checked:
            self.storage.ensure_desktop_clone()
            self.window.rebuild()

    def _rescan(self):
        added, removed = self.window.rescan_desktop()
        QMessageBox.information(self, "重新扫描", "扫描完成：新增 %d 项，清理失效 %d 项。" % (added, removed))

    def _reset_layout(self):
        ret = QMessageBox.question(self, "重置布局",
                                   "确定要重置整理布局吗？将重新克隆当前桌面文件（不会删除任何文件）。")
        if ret == QMessageBox.Yes:
            self.storage.seed_desktop_clone(replace=True)
            self.window.rebuild()
