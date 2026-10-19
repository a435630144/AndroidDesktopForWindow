# -*- coding: utf-8 -*-
"""设置对话框（v6 §7.3 分组卡片式）：启动 / 图标与网格 / 模式 / 开发者。

设计要点：
  - 显卡式分组：每张卡片 = 深色底上更浅的一层（theme.CARD_QSS），
    标题用 ACCENT 主色，统一圆角（RADIUS_CARD）与卡片间距（CARD_SPACING）；
  - 内容装在 QScrollArea 里：卡片增多或小屏时不会顶出屏幕；
  - 主色只用于标题 / 选中态 / 滑条手柄，正文仍是三级文字色；
  - 所有项实时生效（无「应用」按钮），控件属性名与旧版保持一致
    （chk_dev / chk_takeover / cmb_tier …），外部测试与代码按名引用。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout,
                               QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QScrollArea, QSlider, QSpinBox,
                               QVBoxLayout, QWidget)

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
                           + theme.SPIN_QSS + theme.BUTTON_QSS + theme.SCROLL_QSS
                           + theme.COMBO_QSS)
        self._build()

    # ---------- 卡片骨架 ----------
    def _new_card(self, title: str):
        """建一张分组卡片，返回 (card, form)。form 是卡片内的表单布局。"""
        card = QFrame(self)
        card.setObjectName("settingsCard")
        card.setProperty("groupTitle", title)
        card.setStyleSheet(theme.CARD_QSS)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.CARD_PAD, theme.CARD_PAD - 2,
                               theme.CARD_PAD, theme.CARD_PAD - 2)
        lay.setSpacing(8)
        lb = QLabel(title, card)
        lb.setObjectName("cardTitle")
        lb.setStyleSheet(theme.CARD_TITLE_QSS)
        lay.addWidget(lb)
        form = QFormLayout()
        form.setSpacing(9)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        lay.addLayout(form)
        return card, form

    def _hint(self, text: str) -> QLabel:
        lb = QLabel(text)
        lb.setStyleSheet("color: %s; font-size: 12px;" % theme.rgba(theme.TEXT_FAINT))
        lb.setWordWrap(True)
        return lb

    # ---------- 构建 ----------
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        root = QVBoxLayout(body)
        root.setContentsMargins(16, 14, 16, 6)
        root.setSpacing(theme.CARD_SPACING)

        root.addWidget(self._build_start_card())
        root.addWidget(self._build_icon_card())
        root.addWidget(self._build_mode_card())
        root.addWidget(self._build_dev_card())
        root.addStretch(1)
        scroll.setWidget(body)

        bar = QHBoxLayout()
        bar.setContentsMargins(16, 6, 16, 12)
        bar.addStretch(1)
        self.btn_close = QPushButton("完成")
        self.btn_close.clicked.connect(self.accept)
        bar.addWidget(self.btn_close)
        outer.addLayout(bar)

        # 高度自适应：按卡片内容的 sizeHint 算理想高度（QScrollArea 自身的
        # sizeHint 不含展开内容，直接用会把窗口压到下限），再夹到屏幕可用
        # 高度的 92%——卡片变多时靠滚动，不把「完成」按钮顶出屏幕
        avail = QGuiApplication.primaryScreen().availableGeometry()
        content_h = body.layout().sizeHint().height()
        self.resize(520, max(420, min(int(avail.height() * 0.92), content_h + 64)))

    def _build_start_card(self):
        card, form = self._new_card("启动")
        self.chk_autostart = QCheckBox("开机自动启动（当前用户 Run 项，无需管理员）")
        self.chk_autostart.setChecked(autostart.is_enabled())
        self.chk_autostart.toggled.connect(self._apply_autostart)
        form.addRow("自启动：", self.chk_autostart)

        self.chk_tray = QCheckBox("关闭整理窗口时隐藏到托盘（取消勾选则直接退出）")
        self.chk_tray.setChecked(bool(self.storage.get_setting("minimize_to_tray")))
        self.chk_tray.toggled.connect(
            lambda v: self.storage.set_setting("minimize_to_tray", bool(v)))
        form.addRow("托盘：", self.chk_tray)
        return card

    def _build_icon_card(self):
        card, form = self._new_card("图标与网格")

        # 图标三档（v6 A2，指导文档 §2.2/§2.4）：删除旧「图标缩放比例」
        # 滑条（icon_scale）；「图标大小」改三选一。网格模式下 widget
        # 整体 = 档位 × cell（与 icon_size 解钩）；无界模式用像素输入
        # （icon_px，仅无界模式生效）。
        self.cmb_tier = QComboBox()
        for label, tier in (("小", "small"), ("中", "medium"), ("大", "large")):
            self.cmb_tier.addItem(label, tier)
        cur_tier = self.storage.icon_tier()
        self.cmb_tier.setCurrentIndex(max(0, self.cmb_tier.findData(cur_tier)))
        self.cmb_tier.currentIndexChanged.connect(self._apply_icon_tier)
        tier_row = QHBoxLayout()
        tier_row.addWidget(self.cmb_tier)
        tier_row.addStretch(1)
        form.addRow("图标大小（网格档位）：", tier_row)

        self.spin_icon_px = QSpinBox()
        self.spin_icon_px.setRange(60, 256)
        self.spin_icon_px.setValue(int(self.storage.get_setting("icon_px") or 96))
        self.spin_icon_px.valueChanged.connect(self._apply_icon_px)
        self.lbl_icon_px = QLabel()
        self.lbl_icon_px.setStyleSheet(
            "color: %s; font-size: 12px;" % theme.rgba(theme.TEXT_FAINT))
        px_row = QHBoxLayout()
        px_row.addWidget(self.spin_icon_px)
        px_row.addWidget(self.lbl_icon_px)
        form.addRow("图标像素（无界）：", px_row)
        self._refresh_icon_labels()

        # 每行图标数：auto（M1 GridMetrics 四边等距铺满）或手动覆盖。
        # 2026-10-18 修：columns 默认值改 "auto" 后这里 int("auto") 直接崩，
        # 设置窗口打不开（开发者模式开关也因此摸不到）——auto 用复选框表达，
        # auto 态下 spin 只展示当前生效列数、不落笔。
        self.chk_auto_cols = QCheckBox("自动（按屏幕四边等距铺满）")
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
        self.lbl_opacity.setStyleSheet("color: %s; font-size: 13px;"
                                       % theme.rgba(theme.TEXT_DIM))
        self.sld_opacity.valueChanged.connect(self._apply_opacity)
        op_row = QHBoxLayout()
        op_row.addWidget(self.sld_opacity)
        op_row.addWidget(self.lbl_opacity)
        form.addRow("不透明度（悬浮态）：", op_row)

        # 桌面文件维护：与「图标从哪来」同组，比堆在窗口底部更贴语境
        btns = QHBoxLayout()
        self.btn_rescan = QPushButton("重新扫描桌面文件")
        self.btn_rescan.clicked.connect(self._rescan)
        self.btn_reset = QPushButton("重置布局")
        self.btn_reset.clicked.connect(self._reset_layout)
        btns.addWidget(self.btn_rescan)
        btns.addWidget(self.btn_reset)
        btns.addStretch(1)
        form.addRow("维护：", btns)
        return card

    def _build_mode_card(self):
        card, form = self._new_card("模式")

        # v6 §7.2：原「桌面整理模式」与托盘「显示桌面整理」合并为唯一开关
        # 「接管系统桌面」；hide_native_icons 降级为兼容键（set_takeover 双写）。
        self.chk_takeover = QCheckBox(
            "接管系统桌面（隐藏原生图标，由整理桌面全盘接管）")
        self.chk_takeover.setChecked(self.storage.takeover())
        self.chk_takeover.toggled.connect(self._apply_takeover)
        form.addRow("桌面：", self.chk_takeover)

        # v6 §1.3：网格 / 无界 双模式（与托盘「切换到无界模式」同一入口）
        self.cmb_layout_mode = QComboBox()
        self.cmb_layout_mode.addItem("网格模式（自动对齐网格）", "grid")
        self.cmb_layout_mode.addItem("无界模式（自由摆布，可加空白页）", "free")
        self.cmb_layout_mode.setCurrentIndex(
            max(0, self.cmb_layout_mode.findData(grid_flow.layout_mode(self.storage))))
        self.cmb_layout_mode.currentIndexChanged.connect(self._apply_layout_mode)
        form.addRow("布局：", self.cmb_layout_mode)

        self.chk_autoclone = QCheckBox("自动把桌面文件克隆进网格（关闭则只显示手动添加的）")
        self.chk_autoclone.setChecked(bool(self.storage.get_setting("auto_clone_desktop")))
        self.chk_autoclone.toggled.connect(self._apply_auto_clone)
        form.addRow("自动克隆：", self.chk_autoclone)

        self.chk_widgets = QCheckBox("在桌面显示小组件（时钟 / 便签 / 桌面面板）")
        self.chk_widgets.setChecked(bool(self.storage.get_setting("show_widgets")))
        self.chk_widgets.toggled.connect(self._apply_widgets)
        form.addRow("小组件：", self.chk_widgets)
        return card

    def _build_dev_card(self):
        card, form = self._new_card("开发者")
        self.chk_dev = QCheckBox("显示网格边框等调试信息（排查布局问题时用）")
        self.chk_dev.setChecked(bool(self.storage.get_setting("dev_mode")))
        self.chk_dev.toggled.connect(self._apply_dev_mode)
        form.addRow("调试：", self.chk_dev)
        form.addRow("", self._hint("网格线 / 原点十字 / 当前 cell 尺寸会直接画在桌面带窗口上。"))
        return card

    # ---------- 实时生效 ----------
    def _apply_autostart(self, checked):
        autostart.set_enabled(checked)
        self.storage.set_setting("autostart", bool(checked))

    def _refresh_icon_labels(self):
        """图标档位说明：显示当前档位 × cell 推导出的 widget / 图标像素。"""
        from . import grid_sizing
        m = grid_flow.current_metrics()
        tier = self.storage.icon_tier()
        if m is not None:
            lay = grid_sizing.icon_layout(m.cw, m.ch, tier)
            self.lbl_icon_px.setText(
                "（%s 档：widget %dx%d / 图标 %dpx）"
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
        if self.layer is not None:
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

    def _apply_layout_mode(self, _index):
        """v6 §1.3：网格 <-> 无界（换算 + 重排由 window.set_layout_mode 负责）。"""
        mode = self.cmb_layout_mode.currentData()
        if not mode or mode == grid_flow.layout_mode(self.storage):
            return
        self.window.set_layout_mode(mode)

    def _apply_auto_clone(self, checked):
        self.storage.set_setting("auto_clone_desktop", bool(checked))
        if checked:
            self.storage.ensure_desktop_clone()
            self.window.rebuild()

    def _rescan(self):
        added, removed = self.window.rescan_desktop()
        QMessageBox.information(self, "重新扫描",
                                "扫描完成：新增 %d 项，清理失效 %d 项。" % (added, removed))

    def _reset_layout(self):
        ret = QMessageBox.question(self, "重置布局",
                                   "确定要重置整理布局吗？将重新克隆当前桌面文件（不会删除任何文件）。")
        if ret == QMessageBox.Yes:
            self.storage.seed_desktop_clone(replace=True)
            self.window.rebuild()
