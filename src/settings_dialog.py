# -*- coding: utf-8 -*-
"""设置窗口（2026-10-19 重构：苹果 / AirDeck 风格的侧栏 + 分组行）。

用户反馈 10："设置页面现在文字颜色、样式都不好"，并给出 AirDeck 的
参考图——左侧分栏导航、右侧「标题 + 说明 + 圆角卡片行 + 开关」的结构。

设计落点（全部走 theme token，不再散落十六进制）：
  - 侧栏：品牌区（圆角图标 + 产品名）+ 5 个导航项（选中为实心蓝胶囊）
  - 内容区：页标题 22px 粗体 / 副标题 13px 次级色（对比度达标），
    卡片内每行 = 左标题（主文字）+ 右控件；说明文字压在标题下方
  - 开关：自绘 46×26 胶囊（选中 ACCENT），代替系统勾选框——勾选框在
    深色面板上观感割裂，也是"样式不好"的直接来源
  - 所有项实时生效，控件属性名与旧版保持一致（chk_dev / chk_takeover …）

分组：通用 / 外观与图标 / 布局与网格 / 模式 / 高级。
"""
from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame,
                               QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QScrollArea, QSizePolicy, QSlider, QSpinBox,
                               QStackedWidget, QVBoxLayout, QWidget)

from . import autostart
from . import grid_flow
from . import theme


class Switch(QCheckBox):
    """苹果风格开关（QCheckBox 子类，外部按勾选框语义使用）。

    自绘 46×26 胶囊 + 20px 白色圆钮，勾选时轨道 ACCENT；knob 位置由
    `t`（0→1）驱动 160ms 弹簧，与桌面上的动效语言一致。
    """

    W, H, KNOB = 46, 26, 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.PointingHandCursor)
        self._t = 0.0
        self._anim = None
        self.toggled.connect(self._animate_to_state)

    def _get_t(self):
        return self._t

    def _set_t(self, v):
        self._t = max(0.0, min(1.0, float(v)))
        self.update()

    t = Property(float, _get_t, _set_t)

    def _animate_to_state(self, checked):
        if self._anim is not None:
            self._anim.stop()
        anim = QPropertyAnimation(self, b"t", self)
        anim.setDuration(160)
        anim.setStartValue(self._t)
        anim.setEndValue(1.0 if checked else 0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._anim = anim

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self._t
        off = QColor(255, 255, 255, 34)
        on = QColor(theme.ACCENT)
        track = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t),
            int(off.alpha() + (on.alpha() - off.alpha()) * t),
        )
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(0, 0, self.W, self.H, self.H / 2, self.H / 2)
        x = 3 + t * (self.W - self.KNOB - 6)
        p.setBrush(QColor(0, 0, 0, 46))
        p.drawEllipse(int(x), 4, self.KNOB, self.KNOB)   # 极淡投影
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(int(x), 3, self.KNOB, self.KNOB)


class SettingsDialog(QDialog):
    NAV = (("general", "通用"), ("appearance", "外观与图标"),
           ("layout", "布局与网格"), ("mode", "模式"), ("advanced", "高级"))

    def __init__(self, window, storage, layer, parent=None):
        super().__init__(parent)
        self.window = window
        self.storage = storage
        self.layer = layer
        self.setWindowTitle("桌面整理 · 设置")
        self.setStyleSheet(theme.settings_qss())
        self.setMinimumSize(860, 560)
        self._nav_buttons = []
        self._pages = {}
        self._build()

    # ---------- 骨架 ----------
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())

        right = QWidget()
        right.setObjectName("settingsContent")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(28, 22, 28, 18)
        rl.setSpacing(14)
        self.lbl_page_title = QLabel("通用", right)
        self.lbl_page_title.setObjectName("pageTitle")
        self.lbl_page_sub = QLabel("", right)
        self.lbl_page_sub.setObjectName("pageSubtitle")
        self.lbl_page_sub.setWordWrap(True)
        rl.addWidget(self.lbl_page_title)
        rl.addWidget(self.lbl_page_sub)

        self.stack = QStackedWidget(right)
        self.stack.setStyleSheet("background: transparent;")
        for key, _label in self.NAV:
            self.stack.addWidget(self._page(key))
        rl.addWidget(self.stack, 1)

        bar = QHBoxLayout()
        bar.addStretch(1)
        self.btn_close = QPushButton("完成")
        self.btn_close.setObjectName("primaryButton")
        self.btn_close.clicked.connect(self.accept)
        bar.addWidget(self.btn_close)
        rl.addLayout(bar)
        root.addWidget(right, 1)

        avail = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(min(920, int(avail.width() * 0.72)),
                    min(680, int(avail.height() * 0.86)))
        self._select_nav(0)

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("settingsSide")
        side.setFixedWidth(212)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(16, 22, 16, 16)
        lay.setSpacing(6)

        brand = QHBoxLayout()
        logo = QLabel("桌")
        logo.setObjectName("brandLogo")
        logo.setFixedSize(34, 34)
        logo.setAlignment(Qt.AlignCenter)
        names = QVBoxLayout()
        names.setSpacing(0)
        t1 = QLabel("桌面整理")
        t1.setObjectName("brandName")
        t2 = QLabel("Desktop Organizer")
        t2.setObjectName("brandSub")
        names.addWidget(t1)
        names.addWidget(t2)
        brand.addWidget(logo)
        brand.addLayout(names)
        brand.addStretch(1)
        lay.addLayout(brand)
        lay.addSpacing(14)

        for i, (key, label) in enumerate(self.NAV):
            btn = QPushButton(label)
            btn.setObjectName("navItem")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, i=i: self._select_nav(i))
            self._nav_buttons.append(btn)
            lay.addWidget(btn)
        lay.addStretch(1)

        from . import version
        ver = QLabel(version.label())
        ver.setObjectName("sideVersion")
        lay.addWidget(ver)
        return side

    def _select_nav(self, index):
        labels = {
            "general": ("通用", "启动方式、托盘行为与全局开关"),
            "appearance": ("外观与图标", "图标大小、标签与原生桌面对齐"),
            "layout": ("布局与网格", "图标密度、网格计算与翻页方向"),
            "mode": ("模式", "接管桌面的方式与文件同步"),
            "advanced": ("高级", "维护工具与调试选项"),
        }
        for i, b in enumerate(self._nav_buttons):
            b.setChecked(i == index)
        key = self.NAV[index][0]
        title, sub = labels.get(key, ("", ""))
        self.lbl_page_title.setText(title)
        self.lbl_page_sub.setText(sub)
        self.stack.setCurrentIndex(index)

    # ---------- 行 / 卡片 ----------
    def _card(self, parent, title=""):
        card = QFrame(parent)
        card.setObjectName("settingsCard")
        card.setProperty("groupTitle", title)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(2)
        if title:
            lb = QLabel(title, card)
            lb.setObjectName("cardTitle")
            lay.addWidget(lb)
            lay.addSpacing(6)
        return card, lay

    def _row(self, card_lay, parent, title, control, hint=""):
        """一行：左标题（+说明），右控件。返回行容器（测试可定位）。"""
        row = QWidget(parent)
        row.setObjectName("settingsRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 7, 0, 7)
        h.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(2)
        t = QLabel(title, row)
        t.setObjectName("rowTitle")
        t.setWordWrap(True)
        text.addWidget(t)
        if hint:
            d = QLabel(hint, row)
            d.setObjectName("rowHint")
            d.setWordWrap(True)
            text.addWidget(d)
        h.addLayout(text, 1)
        if control is not None:
            # 行标题同时写进控件：① 屏幕阅读器能念出这一行是什么；
            # ② 测试/自动化可按文本定位（Switch 自绘不画 text，视觉无影响）。
            control.setAccessibleName(title)
            if isinstance(control, QCheckBox) and not control.text():
                control.setText(title)
            control.setToolTip(title if not hint else "%s\n%s" % (title, hint))
            control.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            h.addWidget(control, 0, Qt.AlignVCenter)
        card_lay.addWidget(row)
        return row

    def _page(self, key):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent;")
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 2, 8, 8)
        lay.setSpacing(12)
        builder = getattr(self, "_page_" + key, None)
        if builder is not None:
            builder(body, lay)
        lay.addStretch(1)
        scroll.setWidget(body)
        return scroll

    # ---------- 各页 ----------
    def _page_general(self, body, lay):
        card, c = self._card(body, "启动")
        self.chk_autostart = Switch()
        self.chk_autostart.setChecked(autostart.is_enabled())
        self.chk_autostart.toggled.connect(self._apply_autostart)
        self._row(c, card, "开机自动启动",
                  self.chk_autostart, "写入当前用户 Run 项，无需管理员权限")

        self.chk_tray = Switch()
        self.chk_tray.setChecked(bool(self.storage.get_setting("minimize_to_tray")))
        self.chk_tray.toggled.connect(
            lambda v: self.storage.set_setting("minimize_to_tray", bool(v)))
        self._row(c, card, "关闭窗口时隐藏到托盘",
                  self.chk_tray, "关闭后仍在后台运行，可从托盘重新唤出")
        lay.addWidget(card)

        card, c = self._card(body, "桌面")
        self.chk_widgets = Switch()
        self.chk_widgets.setChecked(bool(self.storage.get_setting("show_widgets")))
        self.chk_widgets.toggled.connect(self._apply_widgets)
        self._row(c, card, "显示桌面小组件",
                  self.chk_widgets, "时钟 / 便签 / 桌面面板")
        lay.addWidget(card)

    def _page_appearance(self, body, lay):
        card, c = self._card(body, "图标")
        self.cmb_tier = QComboBox()
        for label, tier in (("小", "small"), ("中（= 原生）", "medium"),
                            ("大", "large")):
            self.cmb_tier.addItem(label, tier)
        cur_tier = self.storage.icon_tier()
        self.cmb_tier.setCurrentIndex(max(0, self.cmb_tier.findData(cur_tier)))
        self.cmb_tier.currentIndexChanged.connect(self._apply_icon_tier)
        self.lbl_icon_px = QLabel()
        self.lbl_icon_px.setObjectName("rowHint")
        tier_box = QWidget()
        tb = QHBoxLayout(tier_box)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(10)
        tb.addWidget(self.lbl_icon_px)
        tb.addWidget(self.cmb_tier)
        self._row(c, card, "图标大小",
                  tier_box, "只改变图标在格子里的占比，网格行列数不变")

        # v7 §3.1：自定义占比（30%~90%），与三档联动
        self.sld_icon_fit = QSlider(Qt.Horizontal)
        self.sld_icon_fit.setRange(30, 90)
        self.sld_icon_fit.setFixedWidth(190)
        self.lbl_icon_fit = QLabel()
        self.lbl_icon_fit.setObjectName("rowHint")
        self.lbl_icon_fit.setFixedWidth(46)
        self.sld_icon_fit.valueChanged.connect(self._apply_icon_fit)
        fit_box = QWidget()
        fb = QHBoxLayout(fit_box)
        fb.setContentsMargins(0, 0, 0, 0)
        fb.setSpacing(8)
        fb.addWidget(self.sld_icon_fit)
        fb.addWidget(self.lbl_icon_fit)
        self._row(c, card, "自定义比例",
                  fit_box, "拖动可微调；落在三档附近即视为该档")

        self.spin_icon_px = QSpinBox()
        self.spin_icon_px.setRange(60, 256)
        self.spin_icon_px.setValue(int(self.storage.get_setting("icon_px") or 96))
        self.spin_icon_px.valueChanged.connect(self._apply_icon_px)
        self._row(c, card, "无界模式图标像素",
                  self.spin_icon_px, "仅在「无界模式」下生效")
        self._refresh_icon_labels()
        lay.addWidget(card)

        card, c = self._card(body, "外观")
        self.sld_opacity = QSlider(Qt.Horizontal)
        self.sld_opacity.setRange(50, 100)
        self.sld_opacity.setFixedWidth(190)
        self.sld_opacity.setValue(int(float(self.storage.get_setting("opacity")) * 100))
        self.lbl_opacity = QLabel("%d%%" % self.sld_opacity.value())
        self.lbl_opacity.setObjectName("rowHint")
        self.lbl_opacity.setFixedWidth(46)
        self.sld_opacity.valueChanged.connect(self._apply_opacity)
        op_box = QWidget()
        ob = QHBoxLayout(op_box)
        ob.setContentsMargins(0, 0, 0, 0)
        ob.setSpacing(8)
        ob.addWidget(self.sld_opacity)
        ob.addWidget(self.lbl_opacity)
        self._row(c, card, "悬浮模式不透明度",
                  op_box, "仅在挂载桌面层失败、作为普通窗口运行时生效")
        lay.addWidget(card)

    def _page_layout(self, body, lay):
        card, c = self._card(body, "网格")
        # ① 读原生图标尺寸（决定 cell 基准）——v7 §3.1 起移入网格卡片
        self.chk_match_native = Switch()
        self.chk_match_native.setChecked(
            bool(self.storage.get_setting("icon_match_native")))
        self.chk_match_native.toggled.connect(self._apply_match_native)
        self._row(c, card, "按系统桌面图标尺寸计算",
                  self.chk_match_native,
                  "读取资源管理器的桌面图标大小，格子按它反推；换屏换缩放自动跟随")

        # ② 自动 / 手动行列（v7 §3.2：列数改格子，行数只裁剪）
        self.chk_auto_cols = Switch()
        self._grid_syncing = False
        dims_auto = self.storage.grid_dims_mode() == "auto"
        self.chk_auto_cols.setChecked(dims_auto)
        self.chk_auto_cols.toggled.connect(self._apply_auto_columns)
        self._row(c, card, "自动计算行列数",
                  self.chk_auto_cols,
                  "关闭后可手动指定列数 / 行数（列数是唯一改变格子大小的旋钮）")

        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(1, 24)
        self.spin_cols.setSuffix(" 列")
        self.spin_cols.setFixedWidth(96)
        self.spin_cols.setEnabled(not dims_auto)
        self.spin_cols.valueChanged.connect(self._apply_columns)
        self._row(c, card, "列数", self.spin_cols,
                  "列数越少格子越大，图标同步变大（不会小于系统桌面图标）")

        self.spin_rows = QSpinBox()
        self.spin_rows.setRange(1, 12)
        self.spin_rows.setSuffix(" 行")
        self.spin_rows.setFixedWidth(96)
        self.spin_rows.setEnabled(not dims_auto)
        self.spin_rows.valueChanged.connect(self._apply_rows)
        self._row(c, card, "行数", self.spin_rows,
                  "只决定网格用几行，格子大小与图标尺寸都不变")

        self.lbl_grid_dims = QLabel()
        self.lbl_grid_dims.setObjectName("rowHint")
        self._row(c, card, "当前网格", self.lbl_grid_dims,
                  "列数越少格子越大；行数只裁剪，不改格子")

        # ③ 网格原点（v7 §3.2 / 反馈 21）
        # 计划里 T13 把它归在「开发者组」，落地时改放「网格」卡片：原点是
        # 用户在设置里要调的几何项（与行列同级），藏在调试组里找不到。
        origin_manual = self.storage.grid_origin_mode() == "manual"
        self.chk_origin = Switch()
        self.chk_origin.setChecked(origin_manual)
        self.chk_origin.toggled.connect(self._apply_origin_mode)
        self._row(c, card, "手动定位网格原点",
                  self.chk_origin,
                  "关闭 = 四边等距居中；开启后可用下面两个数值或右键「定位网格原点」")

        self.sp_ox = QSpinBox()
        self.sp_ox.setRange(0, 9999)
        self.sp_ox.setSingleStep(2)
        self.sp_ox.setSuffix(" px")
        self.sp_ox.setFixedWidth(96)
        self.sp_ox.setEnabled(origin_manual)
        self.sp_ox.valueChanged.connect(self._apply_origin_spin)
        self._row(c, card, "原点 X", self.sp_ox,
                  "网格左上角的横坐标；超出屏幕会被夹回屏内")

        self.sp_oy = QSpinBox()
        self.sp_oy.setRange(0, 9999)
        self.sp_oy.setSingleStep(2)
        self.sp_oy.setSuffix(" px")
        self.sp_oy.setFixedWidth(96)
        self.sp_oy.setEnabled(origin_manual)
        self.sp_oy.valueChanged.connect(self._apply_origin_spin)
        self._row(c, card, "原点 Y", self.sp_oy,
                  "网格左上角的纵坐标；与 X 一起决定整张网格的位置")

        self.btn_reset_origin = QPushButton("重置网格位置")
        self.btn_reset_origin.setEnabled(origin_manual)
        self.btn_reset_origin.clicked.connect(self._reset_grid_origin)
        self._row(c, card, "网格位置", self.btn_reset_origin,
                  "回到四边等距居中（注意：居中值不等于边距，格子越大越靠里）")
        lay.addWidget(card)
        self._refresh_grid_spins()
        self._sync_origin_controls()

        card, c = self._card(body, "翻页与排列")
        self.cmb_page_axis = QComboBox()
        self.cmb_page_axis.addItem("左右翻页", "horizontal")
        self.cmb_page_axis.addItem("上下翻页", "vertical")
        self.cmb_page_axis.setCurrentIndex(
            max(0, self.cmb_page_axis.findData(grid_flow.page_axis(self.storage))))
        self.cmb_page_axis.currentIndexChanged.connect(self._apply_page_axis)
        self._row(c, card, "翻页方向", self.cmb_page_axis,
                  "左右 = 页面横向滑入滑出（默认）；上下 = 竖向")

        self.chk_auto_arrange = Switch()
        self.chk_auto_arrange.setChecked(bool(self.storage.get_setting("auto_arrange")))
        self.chk_auto_arrange.toggled.connect(self._apply_auto_arrange)
        self._row(c, card, "自动排列图标",
                  self.chk_auto_arrange,
                  "开启后拖动始终按阅读序递进（不保留空格）；关闭则自由摆放")
        lay.addWidget(card)

    def _page_mode(self, body, lay):
        card, c = self._card(body, "桌面接管")
        self.chk_takeover = Switch()
        self.chk_takeover.setChecked(self.storage.takeover())
        self.chk_takeover.toggled.connect(self._apply_takeover)
        self._row(c, card, "接管系统桌面",
                  self.chk_takeover,
                  "隐藏原生图标，由整理桌面全盘接管；关闭即恢复原生桌面")

        self.cmb_layout_mode = QComboBox()
        self.cmb_layout_mode.addItem("网格模式（自动对齐）", "grid")
        self.cmb_layout_mode.addItem("无界模式（自由摆布）", "free")
        self.cmb_layout_mode.setCurrentIndex(
            max(0, self.cmb_layout_mode.findData(grid_flow.layout_mode(self.storage))))
        self.cmb_layout_mode.currentIndexChanged.connect(self._apply_layout_mode)
        self._row(c, card, "布局", self.cmb_layout_mode,
                  "无界模式可自由重叠摆放，并支持添加空白页")
        lay.addWidget(card)

        card, c = self._card(body, "桌面文件")
        self.chk_autoclone = Switch()
        self.chk_autoclone.setChecked(bool(self.storage.get_setting("auto_clone_desktop")))
        self.chk_autoclone.toggled.connect(self._apply_auto_clone)
        self._row(c, card, "自动把桌面文件放入网格",
                  self.chk_autoclone, "关闭后只显示手动添加的应用")

        self.chk_autosync = Switch()
        self.chk_autosync.setChecked(bool(self.storage.get_setting("auto_sync_desktop")))
        self.chk_autosync.toggled.connect(self._apply_auto_sync)
        self._row(c, card, "自动同步桌面变动",
                  self.chk_autosync, "新增 / 删除 / 重命名在 1 秒内生效，不重排已有位置")
        lay.addWidget(card)

    def _page_advanced(self, body, lay):
        card, c = self._card(body, "维护")
        btns = QWidget()
        bh = QHBoxLayout(btns)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(8)
        self.btn_rescan = QPushButton("重新扫描桌面")
        self.btn_rescan.clicked.connect(self._rescan)
        self.btn_reset = QPushButton("重置布局")
        self.btn_reset.clicked.connect(self._reset_layout)
        bh.addWidget(self.btn_rescan)
        bh.addWidget(self.btn_reset)
        self._row(c, card, "桌面文件", btns, "重新扫描只增删差异，不会重排已摆好的位置")
        lay.addWidget(card)

        card, c = self._card(body, "调试")
        self.chk_dev = Switch()
        self.chk_dev.setChecked(bool(self.storage.get_setting("dev_mode")))
        self.chk_dev.toggled.connect(self._apply_dev_mode)
        self._row(c, card, "显示网格调试信息",
                  self.chk_dev, "网格线 / 原点 / 当前 cell 尺寸直接画在桌面上")
        lay.addWidget(card)

    # ---------- 实时生效 ----------
    def _call_window(self, name, *args):
        """调用窗口的可选能力（缺失即忽略）。

        设置页只依赖"窗口"这一契约，不该把 refresh_grid / rebuild 之类
        具体方法名变成硬依赖——缺了会直接抛 AttributeError 把整个设置
        窗口带崩（test_dev_mode D7 用最小桩打出来的真实健壮性问题）。
        """
        fn = getattr(self.window, name, None)
        if callable(fn):
            return fn(*args)
        return None

    def _refresh_grid(self):
        """让窗口按新几何重建：优先 refresh_grid，退化为 rebuild / update。"""
        if getattr(self.window, "refresh_grid", None) is not None:
            return self._call_window("refresh_grid")
        if getattr(self.window, "rebuild", None) is not None:
            return self._call_window("rebuild")
        return self._call_window("update")

    def _apply_autostart(self, checked):
        autostart.set_enabled(bool(checked))
        self.storage.set_setting("autostart", bool(checked))

    def _refresh_icon_labels(self):
        """图标档位说明：显示当前占比与推导出的图标像素（v7 §3.1）。"""
        from . import grid_sizing
        m = grid_flow.current_metrics()
        if m is None:
            self.lbl_icon_px.setText("")
            if getattr(self, "lbl_icon_fit", None) is not None:
                self.lbl_icon_fit.setText("")
            return
        fit = self._effective_fit(m)
        lay = grid_sizing.icon_layout(m.cw, m.ch, fit)
        self.lbl_icon_px.setText("图标 %dpx" % lay.icon_box)
        if getattr(self, "lbl_icon_fit", None) is not None:
            self.lbl_icon_fit.setText("%d%%" % int(round(fit * 100)))
        self._sync_fit_controls(fit)

    def _effective_fit(self, m=None):
        """当前**实际生效**的图标占比（medium 用 native_px/cell_w 解算）。"""
        from . import grid_sizing, win32_layer
        m = m if m is not None else grid_flow.current_metrics()
        fit = self.storage.icon_fit()
        if fit is not None:
            return fit
        try:
            native = win32_layer.native_icon_size()
        except Exception:
            native = 48
        cw = m.cw if m is not None else grid_sizing.cell_from_native(native)[0]
        return grid_sizing.fit_for(native, cw, "medium")

    def _sync_fit_controls(self, fit):
        """把三档下拉与自定义滑条同步到 fit（阻断信号，避免回写死循环）。"""
        from .storage import tier_for_fit
        sld = getattr(self, "sld_icon_fit", None)
        if sld is not None:
            sld.blockSignals(True)
            sld.setValue(int(round(fit * 100)))
            sld.blockSignals(False)
        cmb = getattr(self, "cmb_tier", None)
        tier = tier_for_fit(fit)
        if cmb is not None and tier:
            idx = cmb.findData(tier)
            if idx >= 0 and idx != cmb.currentIndex():
                cmb.blockSignals(True)
                cmb.setCurrentIndex(idx)
                cmb.blockSignals(False)

    def _apply_icon_tier(self, _index):
        tier = self.cmb_tier.currentData()
        if not tier:
            return
        from . import grid_sizing
        self.storage.apply_icon_fit(grid_sizing.parse_fit(tier))
        self._refresh_icon_labels()
        self._refresh_grid()

    def _apply_icon_fit(self, value):
        """自定义占比滑条（30%~90%）：走 storage 唯一写入点。"""
        self.storage.apply_icon_fit(int(value) / 100.0)
        self._refresh_icon_labels()
        self._refresh_grid()

    def _apply_icon_px(self, value):
        self.storage.set_setting("icon_px", int(value))
        self._refresh_grid()

    def _apply_match_native(self, checked):
        self.storage.set_setting("icon_match_native", bool(checked))
        self._refresh_grid()
        self._refresh_icon_labels()
        self._refresh_grid_spins()

    # ---------- v7 §3.2：网格行列（列数改 cell，行数只裁剪）----------
    def _refresh_grid_spins(self):
        """按当前几何刷新两个 spin 的上限与显示值，以及摘要文字。"""
        from . import grid_sizing
        spin_r = getattr(self, "spin_rows", None)
        lbl = getattr(self, "lbl_grid_dims", None)
        if spin_r is None:
            return
        m = grid_flow.current_metrics()
        self._grid_syncing = True
        try:
            if m is None:
                return
            cols_auto = m.cols_auto or m.cols
            rows_auto = m.rows_auto or m.rows
            self.spin_cols.setRange(1, max(1, cols_auto))
            spin_r.setRange(1, max(1, rows_auto))
            self.spin_cols.setValue(min(m.cols, cols_auto))
            spin_r.setValue(min(m.rows, rows_auto))
            if lbl is not None:
                lay = grid_sizing.icon_layout(m.cw, m.ch, self._effective_fit(m))
                lbl.setText("%d 列 × %d 行 · 格子 %d×%d · 图标 %dpx"
                            "（上限 %d 列 / %d 行）"
                            % (m.cols, m.rows, m.cw, m.ch, lay.icon_box,
                               cols_auto, rows_auto))
        finally:
            self._grid_syncing = False

    def _apply_columns(self, value):
        if getattr(self, "_grid_syncing", False):
            return
        if self.chk_auto_cols.isChecked():
            return
        self.storage.set_setting("grid_cols", int(value))
        self.storage.compact_layout()
        self._refresh_grid()
        self._refresh_grid_spins()

    def _apply_rows(self, value):
        if getattr(self, "_grid_syncing", False):
            return
        if self.chk_auto_cols.isChecked():
            return
        self.storage.set_setting("grid_rows", int(value))
        self._refresh_grid()
        self._refresh_grid_spins()

    def _apply_auto_columns(self, checked):
        auto = bool(checked)
        self.spin_cols.setEnabled(not auto)
        if getattr(self, "spin_rows", None) is not None:
            self.spin_rows.setEnabled(not auto)
        if auto:
            self.storage.set_setting("grid_dims_mode", "auto")
        else:
            self.storage.set_setting("grid_dims_mode", "manual")
            self.storage.set_setting("grid_cols", int(self.spin_cols.value()))
            if getattr(self, "spin_rows", None) is not None:
                self.storage.set_setting("grid_rows",
                                         int(self.spin_rows.value()))
            self.storage.compact_layout()
        self.storage.save()
        self._refresh_grid()
        self._refresh_grid_spins()

    # ---------- 网格原点（v7 §3.2 / 反馈 21） ----------
    def _sync_origin_controls(self):
        """同步原点开关 / 两个 spin / 重置按钮的状态与显示值。

        spin 显示的是**实际生效**的原点（快照的 ox/oy），不是 storage 里
        存的原始值——用户填 9999 时屏幕上是夹紧后的位置，界面必须一致。
        """
        chk = getattr(self, "chk_origin", None)
        if chk is None:
            return
        manual = self.storage.grid_origin_mode() == "manual"
        ox, oy = grid_flow.origin()          # 生效值（快照已按越界夹紧）
        if manual and grid_flow.current_metrics() is None:
            # 快照还没算出来（悬浮兜底 / 未挂载就开设置）：显示用户存的值，
            # 否则界面会显示一个与 storage 无关的常量，用户以为设置没生效
            ox, oy = self.storage.grid_origin() or (ox, oy)
        self._origin_syncing = True
        try:
            chk.blockSignals(True)
            chk.setChecked(manual)
            chk.blockSignals(False)
            for sp, v in ((self.sp_ox, ox), (self.sp_oy, oy)):
                sp.blockSignals(True)
                sp.setEnabled(manual)
                sp.setValue(max(0, min(int(v), sp.maximum())))
                sp.blockSignals(False)
            self.btn_reset_origin.setEnabled(manual)
        finally:
            self._origin_syncing = False

    def _apply_origin_mode(self, checked):
        """开关：开 = 以当前生效原点为起点转手动；关 = 回居中。"""
        if getattr(self, "_origin_syncing", False):
            return
        if checked:
            self.storage.set_grid_origin("manual",
                                         int(self.sp_ox.value()),
                                         int(self.sp_oy.value()))
        else:
            self.storage.reset_grid_origin()
        self._refresh_grid()
        self._sync_origin_controls()

    def _apply_origin_spin(self, _value):
        if getattr(self, "_origin_syncing", False):
            return
        if not self.chk_origin.isChecked():
            return
        self.storage.set_grid_origin("manual",
                                     int(self.sp_ox.value()),
                                     int(self.sp_oy.value()))
        self._refresh_grid()
        self._sync_origin_controls()

    def _reset_grid_origin(self):
        """重置网格位置：两键一起清空 -> 回居中（与桌面右键同一入口语义）。"""
        self.storage.reset_grid_origin()
        self._refresh_grid()
        self._sync_origin_controls()

    def _apply_page_axis(self, _index):
        axis = self.cmb_page_axis.currentData() or "horizontal"
        hook = getattr(self.window, "set_page_axis", None)
        if hook is not None:
            hook(axis)
        else:
            self.storage.set_setting("page_axis", axis)

    def _apply_auto_arrange(self, checked):
        """自动排列（反馈 3）：开关就是"此后一直生效"，开启时立刻整理一次。"""
        self.storage.set_setting("auto_arrange", bool(checked))
        if checked:
            tidy = getattr(self.window, "_tidy", None)
            if tidy is not None:
                tidy()

    def _apply_dev_mode(self, checked):
        self.storage.set_setting("dev_mode", bool(checked))
        self._call_window('update')

    def _apply_opacity(self, value):
        self.lbl_opacity.setText("%d%%" % value)
        self.storage.set_setting("opacity", value / 100.0)
        if self.window.attached:
            self.window.setWindowOpacity(1.0)
        else:
            self.window.setWindowOpacity(value / 100.0)

    def _apply_widgets(self, checked):
        self.storage.set_setting("show_widgets", bool(checked))
        if self.layer is not None:
            self.layer.set_visible(bool(checked))

    def _apply_takeover(self, checked):
        self.storage.set_takeover(bool(checked))
        self._call_window('apply_native_icons_setting')
        if checked:
            self.storage.ensure_desktop_clone(force=True)
            self._call_window('rebuild')

    def _apply_layout_mode(self, _index):
        mode = self.cmb_layout_mode.currentData()
        if not mode or mode == grid_flow.layout_mode(self.storage):
            return
        self.window.set_layout_mode(mode)

    def _apply_auto_clone(self, checked):
        self.storage.set_setting("auto_clone_desktop", bool(checked))
        if checked:
            self.storage.ensure_desktop_clone()
            self._call_window('rebuild')

    def _apply_auto_sync(self, checked):
        self.storage.set_setting("auto_sync_desktop", bool(checked))
        hook = getattr(self.window, "set_auto_sync", None)
        if hook is not None:
            hook(bool(checked))

    def _rescan(self):
        added, removed = self.window.rescan_desktop()
        QMessageBox.information(self, "重新扫描",
                                "扫描完成：新增 %d 项，清理失效 %d 项。" % (added, removed))

    def _reset_layout(self):
        ret = QMessageBox.question(self, "重置布局",
                                   "确定要重置整理布局吗？将重新克隆当前桌面文件（不会删除任何文件）。")
        if ret == QMessageBox.Yes:
            self.storage.seed_desktop_clone(replace=True)
            self._call_window('rebuild')
