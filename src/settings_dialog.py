# -*- coding: utf-8 -*-
"""设置对话框：深色主题；开机自启 / 图标大小 / 列数 / 不透明度 / 小组件 /
原生图标 / 重新扫描 / 托盘行为 / 重置布局。所有项实时生效。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout,
                               QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QSlider, QSpinBox, QVBoxLayout)

from . import autostart
from . import grid_flow
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

        # 图标三档（v6 A2，指导文档 §2.2/§2.4）：删除旧「图标缩放比例」
        # 滑条（icon_scale）；「图标大小」滑条改三选一。网格模式下 widget
        # 整体 = 档位 × cell（与 icon_size 解钩）；无界模式用像素输入
        # （icon_px，仅无界模式生效）。
        self.cmb_tier = QComboBox()
        for label, tier in (("小", "small"), ("中", "medium"), ("大", "large")):
            self.cmb_tier.addItem(label, tier)
        cur_tier = self.storage.icon_tier()
        idx = max(0, self.cmb_tier.findData(cur_tier))
        self.cmb_tier.setCurrentIndex(idx)
        self.cmb_tier.currentIndexChanged.connect(self._apply_icon_tier)
        tier_row = QHBoxLayout()
        tier_row.addWidget(self.cmb_tier)
        tier_row.addStretch(1)
        form.addRow("图标大小（网格模式档位）：", tier_row)

        # 无界模式图标像素（v6 §2.3）：仅无界模式生效；网格模式置灰。
        self.spin_icon_px = QSpinBox()
        self.spin_icon_px.setRange(60, 256)
        self.spin_icon_px.setValue(int(self.storage.get_setting("icon_px") or 96))
        self.spin_icon_px.valueChanged.connect(self._apply_icon_px)
        self.lbl_icon_px = QLabel("（网格模式下由档位决定，此输入仅无界模式生效）")
        self.lbl_icon_px.setStyleSheet("color: rgb(140,146,155); font-size: 12px;")
        px_row = QHBoxLayout()
        px_row.addWidget(self.spin_icon_px)
        px_row.addWidget(self.lbl_icon_px)
        form.addRow("图标像素（无界模式）：", px_row)
        self._refresh_icon_labels()

        # 每行图标数：auto（M1 GridMetrics 四边等距铺满）或手动覆盖。
        # 2026-10-18 修：columns 默认值改 "auto" 后这里 int("auto") 直接崩，
        # 设置窗口打不开（开发者模式开关也因此摸不到）——auto 用复选框表达，
        # auto 态下 spin 只展示当前生效列数、不落笔。
        self.chk_auto_cols = QCheckBox("自动（按屏幕尺寸四边等距铺满）")
        raw_cols = self.storage.get_setting("columns")
        cols_auto = (raw_cols is None
                     or (isinstance(raw_cols, str)
                         and raw_cols.strip().lower() in ("", "auto")))
        self.chk_auto_cols.setChecked(cols_auto)
        self.chk_auto_cols.toggled.connect(self._apply_auto_columns)
        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(2, 24)  # 与 grid_metrics MIN_COLS/MAX_COLS 一致
        m = grid_flow.current_metrics()
        eff_cols = m.cols if m is not None else 10
        try:
            manual = int(raw_cols)
        except (TypeError, ValueError):
            manual = eff_cols
        self.spin_cols.setValue(manual if not cols_auto else eff_cols)
        self.spin_cols.setEnabled(not cols_auto)
        self.spin_cols.valueChanged.connect(self._apply_columns)
        cols_row = QHBoxLayout()
        cols_row.addWidget(self.chk_auto_cols)
        cols_row.addWidget(self.spin_cols)
        cols_row.addStretch(1)
        form.addRow("每行图标数：", cols_row)

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

        # v6 §7.2：原「桌面整理模式」与托盘「显示桌面整理」合并为唯一开关
        # 「接管系统桌面」；hide_native_icons 降级为兼容键（storage.set_takeover 双写）。
        self.chk_takeover = QCheckBox(
            "接管系统桌面（隐藏原生图标，由整理桌面全盘接管：框选 / 自己的右键菜单）")
        self.chk_takeover.setChecked(self.storage.takeover())
        self.chk_takeover.toggled.connect(self._apply_takeover)
        form.addRow("桌面：", self.chk_takeover)

        self.chk_autoclone = QCheckBox("自动把桌面文件克隆进整理网格（关闭则只显示手动添加的图标）")
        self.chk_autoclone.setChecked(bool(self.storage.get_setting("auto_clone_desktop")))
        self.chk_autoclone.toggled.connect(self._apply_auto_clone)
        form.addRow("自动克隆：", self.chk_autoclone)

        self.chk_tray = QCheckBox("关闭整理窗口时隐藏到托盘（取消勾选则直接退出程序）")
        self.chk_tray.setChecked(bool(self.storage.get_setting("minimize_to_tray")))
        self.chk_tray.toggled.connect(lambda v: self.storage.set_setting("minimize_to_tray", bool(v)))
        form.addRow("托盘：", self.chk_tray)

        self.chk_dev = QCheckBox("开发者模式：桌面显示网格边框等调试信息（开发期默认开启）")
        self.chk_dev.setChecked(bool(self.storage.get_setting("dev_mode")))
        self.chk_dev.toggled.connect(self._apply_dev_mode)
        form.addRow("开发者：", self.chk_dev)

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
        """图标档位说明：显示当前档位 × cell 推导出的 widget / 图标像素。"""
        from . import grid_flow, grid_sizing
        m = grid_flow.current_metrics()
        tier = self.storage.icon_tier()
        if m is not None:
            lay = grid_sizing.icon_layout(m.cw, m.ch, tier)
            self.lbl_icon_px.setText(
                "（当前 %s 档：widget %dx%d / 图标 %dpx；仅无界模式生效）"
                % (tier, lay.widget_w, lay.widget_h, lay.icon_box))
        else:
            self.lbl_icon_px.setText("（仅无界模式生效）")

    def _apply_icon_tier(self, _index):
        tier = self.cmb_tier.currentData()
        if not tier:
            return
        self.storage.set_setting("icon_tier", tier)
        self._refresh_icon_labels()
        self.window.rebuild()

    def _apply_icon_px(self, value):
        """无界模式图标像素（v6 §2.3）：网格模式置灰不生效。"""
        self.storage.set_setting("icon_px", int(value))

    def _apply_columns(self, value):
        if self.chk_auto_cols.isChecked():
            return  # auto 态下 spin 只是展示当前生效列数，不落笔
        self.storage.set_setting("columns", int(value))
        self.storage.compact_layout()
        self.storage.save()
        self.window.rebuild()

    def _apply_auto_columns(self, checked):
        """自动列数开关：开=写 "auto" 由 GridMetrics 按屏幕铺满；关=以当前
        生效列数作手动值落笔（M1 语义，设置 UI 2026-10-18 修 int("auto") 崩）。"""
        self.spin_cols.setEnabled(not checked)
        if checked:
            self.storage.set_setting("columns", "auto")
            self.window.rebuild()
            m = grid_flow.current_metrics()
            if m is not None:
                self.spin_cols.setValue(m.cols)
        else:
            self.storage.set_setting("columns", int(self.spin_cols.value()))
            self.storage.compact_layout()
            self.storage.save()
            self.window.rebuild()

    def _apply_dev_mode(self, checked):
        """开发者模式开关（2026-10-18）：网格可视化边框即时显隐，无需重启。"""
        self.storage.set_setting("dev_mode", bool(checked))
        self.window.update()

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

    def _apply_takeover(self, checked):
        """「接管系统桌面」开关（v6 §7.2 唯一模式入口）。

        开 = 隐藏原生图标全盘接管；关 = 恢复原生桌面，整理窗口仅悬浮。
        """
        self.storage.set_takeover(bool(checked))
        self.window.apply_native_icons_setting()
        if checked:
            # 开启接管 = 原生图标被隐藏、网格全盘接管：必须保证桌面文件
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
