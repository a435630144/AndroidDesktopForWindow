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
from PySide6.QtCore import (Property, QElapsedTimer, QEasingCurve,
                            QPropertyAnimation, Qt, QTimer)
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame,
                               QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QScrollArea, QSizePolicy, QSlider,
                               QStackedWidget, QVBoxLayout, QWidget)

from . import autostart
from . import grid_flow
from . import interaction
from . import page_rules
from .stepper import Stepper
from .ui_choice import ComboBox
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


_dialog = None       # 单例（模块级）：多处入口共用同一个设置窗口


def open_settings(window, storage, layer, page="general"):
    """打开设置面板（单例）并定位到指定分页；已开则提到前面。

    托盘 / 桌面右键 / 组件库入口都走这里——以前各自 `SettingsDialog(...)
    .exec()`，点两次就有两个窗口，且模态会挡住桌面。
    """
    global _dialog
    try:
        if _dialog is not None:
            _dialog.select_page(page)
            _dialog.show()
            _dialog.raise_()
            _dialog.activateWindow()
            return _dialog
    except RuntimeError:      # C++ 对象已被销毁（用户关窗后回收）
        _dialog = None
    dlg = SettingsDialog(window, storage, layer, page=page)
    _dialog = dlg
    dlg.show()
    dlg.raise_()
    return dlg


class SettingsDialog(QDialog):
    # v9 V2：新增「组件库」分页（原独立窗口融合进来，BUG1 从结构上消失）
    NAV = (("general", "通用"), ("widgets", "组件库"), ("appearance", "外观与图标"),
           ("layout", "布局与网格"), ("mode", "模式"), ("advanced", "高级"))

    def __init__(self, window, storage, layer, parent=None, page=None):
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
        if page:
            self.select_page(page)

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
            page = self._page(key)
            self._pages[key] = page          # 供测试/自动化按页定位控件
            self.stack.addWidget(page)
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
            "widgets": ("组件库", "浏览、预览、添加与移除桌面组件"),
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
        if key == "widgets":
            # 组件库自带左栏 + 滚动区，再套一层 QScrollArea 会出现双滚动条
            return self._page_widgets()
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

    def _page_widgets(self):
        """组件库分页（v9 V2：原独立窗口）。"""
        if self.layer is None:
            from PySide6.QtWidgets import QLabel as _QL
            tip = _QL("组件库需要桌面已就绪，当前没有可用的组件层")
            tip.setObjectName("rowHint")
            return tip
        from . import widget_center
        self.center_page = widget_center.WidgetCenterPage(self.layer, self)
        return self.center_page

    def select_page(self, key):
        """按 key 切到某一分页（托盘/桌面右键用它定位到「组件库」）。"""
        for i, (k, _label) in enumerate(self.NAV):
            if k == key:
                self._select_nav(i)
                return True
        return False

    # ---------- 各页 ----------
    def _page_general(self, body, lay):
        card, c = self._card(body, "启动")
        self.chk_autostart = Switch()
        self.chk_autostart.setChecked(autostart.is_enabled())
        self.chk_autostart.toggled.connect(self._apply_autostart)
        self._row(c, card, "开机自动启动",
                  self.chk_autostart, "写入用户 Run 项，无需管理员权限")

        self.chk_tray = Switch()
        self.chk_tray.setChecked(bool(self.storage.get_setting("minimize_to_tray")))
        self.chk_tray.toggled.connect(
            lambda v: self.storage.set_setting("minimize_to_tray", bool(v)))
        self._row(c, card, "关闭窗口时隐藏到托盘",
                  self.chk_tray, "仍在后台运行，可从托盘唤出")
        lay.addWidget(card)

        card, c = self._card(body, "桌面")
        self.chk_widgets = Switch()
        self.chk_widgets.setChecked(bool(self.storage.get_setting("show_widgets")))
        self.chk_widgets.toggled.connect(self._apply_widgets)
        # v10 A4（反馈 10 规则 3）：原 hint「时钟 / 便签 / 桌面面板」是组件
        # 清单的复读，且随新组件增加必然过时——清单归组件库页，这里不再列。
        self._row(c, card, "显示桌面小组件", self.chk_widgets)

        # v7 反馈 9：仅小组件模式——只留小组件（组件切无界、图标全隐藏）。
        # 入口唯一：托盘 / 桌面右键里的模式开关已移除。
        self.chk_widgets_only = Switch()
        self.chk_widgets_only.setChecked(
            bool(self.storage.get_setting("widgets_only")))
        self.chk_widgets_only.toggled.connect(self._apply_widgets_only)
        self._row(c, card, "仅小组件模式",
                  self.chk_widgets_only,
                  "只留小组件：组件无界摆放、隐藏桌面图标")

        # v8 C3：组件库入口（第三处：托盘 / 桌面右键 / 这里）
        btn_center = QPushButton("组件库…")
        btn_center.setStyleSheet(theme.BUTTON_QSS)
        btn_center.clicked.connect(self._open_widget_center)
        self._row(c, card, "组件库", btn_center, "浏览并添加桌面组件")

        # v10 A7-1（反馈 13）：「显示桌面小组件」上面那个总开关之外，再给一个
        # **一键救回**的按钮——用户一个个把组件关了（或用了组件库的「关闭所有」），
        # 想全回来时不必去组件库里逐个点「显示」。
        btn_show_all = QPushButton("显示全部组件")
        btn_show_all.setStyleSheet(theme.BUTTON_QSS)
        btn_show_all.setToolTip("把被隐藏的组件全部恢复显示")
        btn_show_all.clicked.connect(self._show_all_widgets)
        # v10 A4（反馈 10 规则 3）：hint 原是按钮名的同义复读，删。
        self._row(c, card, "恢复组件", btn_show_all)
        lay.addWidget(card)

    def _show_all_widgets(self):
        """一键恢复全部被隐藏的组件（v10 A7-1）。没有 layer（测试/异常）时静默跳过。"""
        if self.layer is None:
            return
        try:
            self.layer.show_all()
        except Exception:      # noqa: BLE001 —— 别让一个按钮把设置窗搞崩
            pass

    def _open_widget_center(self):
        """跳到组件库分页（v9 V2：不再新开窗口）。

        旧实现 `widget_center.open_center(..., parent=self)` 会新建一个
        **被拥有的模态窗口**——点不动且被压在设置面板下面（BUG1）。
        """
        self.select_page("widgets")

    def _page_appearance(self, body, lay):
        card, c = self._card(body, "图标")
        self.cmb_tier = ComboBox()
        # v10 A4（反馈 10 规则 2）：「中（= 原生）」是行为解释进控件标签，
        # 去掉；原生等价关系由右侧「图标 Npx」读数与下面
        # 「按系统桌面图标尺寸计算」一行自证。
        for label, tier in (("小", "small"), ("中", "medium"),
                            ("大", "large"), ("自定义", "custom")):
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
                  tier_box, "只改变图标在格子里的占比，行列数不变")

        # v7 B2（反馈 9）：第四档「自定义」才启用滑条。三档是预设，
        # 滑条跟着值显示但不可拖——旧实现滑条常驻可拖，用户拖完档位
        # 显示值又跳回最近预设，看着像"逻辑有问题"。
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
        # 括号保留：30%~90% 是取值域（规则 1 唯一放行的一种括号）。
        self._row(c, card, "自定义比例",
                  fit_box, "选「自定义」后可拖动（30%~90%）")
        lay.addWidget(card)
        self._refresh_icon_labels()

        # 反馈 12：**已配置额外大小的图标**管理区。
        # 存在意义是"反悔入口"——把图标缩到 30% 会小到点不到，右键菜单
        # 都调不出来；这里可以一键恢复 100%。
        card, c = self._card(body, "已配置额外大小的图标")
        self._scaled_box = QVBoxLayout()
        self._scaled_box.setContentsMargins(0, 0, 0, 0)
        self._scaled_box.setSpacing(4)
        holder = QWidget(card)
        holder.setLayout(self._scaled_box)
        c.addWidget(holder)
        self._scaled_rows = []
        lay.addWidget(card)
        self._refresh_scaled_icons()

        card, c = self._card(body, "外观")
        self.sld_opacity = QSlider(Qt.Horizontal)
        self.sld_opacity.setRange(50, 100)
        self.sld_opacity.setFixedWidth(190)
        self.sld_opacity.setValue(int(float(self.storage.get_setting("opacity")) * 100))
        self.lbl_opacity = QLabel("%d%%" % self.sld_opacity.value())
        self.lbl_opacity.setObjectName("rowHint")
        self.lbl_opacity.setFixedWidth(46)
        self.sld_opacity.valueChanged.connect(self._apply_opacity)
        # v10 A8（反馈 14）：**挂载桌面层时这个设置不生效**——整理层是分层
        # 窗口，`setWindowOpacity` 对内容无效（`_show_current_mode()` 在挂载
        # 分支一律置 1.0），且分层窗的全局 alpha 会连带命中测试一起变
        # （透明区穿透的教训）。所以挂载态直接把滑条置灰并说明原因，
        # 不再让用户拖一个看不出变化的滑条。
        self._opacity_attached = bool(getattr(self.window, "attached", False))
        self.sld_opacity.setEnabled(not self._opacity_attached)
        op_box = QWidget()
        ob = QHBoxLayout(op_box)
        ob.setContentsMargins(0, 0, 0, 0)
        ob.setSpacing(8)
        ob.addWidget(self.sld_opacity)
        ob.addWidget(self.lbl_opacity)
        # v10 A4（反馈 10 规则 3）：标签已写「悬浮模式」，hint 不再复读
        # 「当前为悬浮模式」；只留挂载态这一条真正新增的信息。
        self._row(c, card, "悬浮模式不透明度",
                  op_box,
                  "挂载桌面层时不生效"
                  if self._opacity_attached else
                  "拖动立即生效；挂载后不适用")
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
                  "读取资源管理器的图标大小，格子按它反推，换屏自动跟随")

        # ② 自动 / 手动行列（v7 §3.2：列数改格子，行数只裁剪）
        self.chk_auto_cols = Switch()
        self._grid_syncing = False
        dims_auto = self.storage.grid_dims_mode() == "auto"
        self.chk_auto_cols.setChecked(dims_auto)
        self.chk_auto_cols.toggled.connect(self._apply_auto_columns)
        self._row(c, card, "自动计算行列数",
                  self.chk_auto_cols, "关闭后可手动指定列数与行数")

        self.spin_cols = Stepper()
        self.spin_cols.setRange(1, 24)
        self.spin_cols.setSuffix(" 列")
        self.spin_cols.setFixedWidth(96)
        self.spin_cols.setEnabled(not dims_auto)
        self.spin_cols.valueChanged.connect(self._apply_columns)
        self._row(c, card, "列数", self.spin_cols,
                  "列数越少格子越大，图标同步变大")

        self.spin_rows = Stepper()
        self.spin_rows.setRange(1, 12)
        self.spin_rows.setSuffix(" 行")
        self.spin_rows.setFixedWidth(96)
        self.spin_rows.setEnabled(not dims_auto)
        self.spin_rows.valueChanged.connect(self._apply_rows)
        self._row(c, card, "行数", self.spin_rows,
                  "只决定网格用几行，不改格子大小")

        self.lbl_grid_dims = QLabel()
        self.lbl_grid_dims.setObjectName("rowHint")
        # v10 A4（反馈 10 规则 3）：原 hint 与同卡片的「列数 / 行数」两行
        # 完全同义，删；本行是只读读数，不需要说明。
        self._row(c, card, "当前网格", self.lbl_grid_dims)

        # ③ 网格原点不在这里：v7 §3.4 把它定为**开发者选项**，控件在
        #    「高级」页的「调试」卡片里，且 dev_mode 关闭时不可配置
        #    （2026-10-20 用户反馈 5：不要放右键、也不该跟行列同级）。
        lay.addWidget(card)
        self._refresh_grid_spins()

        # 文件夹默认尺寸（反馈 14）：默认 3×3，最小 2×2；成员少时弹窗会按
        # 实际数量收缩（2 个 -> 2×2），这里设的是**上限**。
        card, c = self._card(body, "文件夹")
        fdef = self.storage.folder_frame_default()
        fbox = QWidget()
        fh = QHBoxLayout(fbox)
        fh.setContentsMargins(0, 0, 0, 0)
        fh.setSpacing(8)
        self.sp_folder_cols = Stepper()
        self.sp_folder_cols.setRange(2, 6)
        self.sp_folder_cols.setSuffix(" 列")
        self.sp_folder_cols.setFixedWidth(82)
        self.sp_folder_cols.setValue(int(fdef[0]))
        self.sp_folder_cols.valueChanged.connect(self._apply_folder_frame_default)
        self.sp_folder_rows = Stepper()
        self.sp_folder_rows.setRange(2, 6)
        self.sp_folder_rows.setSuffix(" 行")
        self.sp_folder_rows.setFixedWidth(82)
        self.sp_folder_rows.setValue(int(fdef[1]))
        self.sp_folder_rows.valueChanged.connect(self._apply_folder_frame_default)
        fh.addWidget(self.sp_folder_cols)
        fh.addWidget(self.sp_folder_rows)
        self._row(c, card, "默认展开大小", fbox,
                  "默认 3×3；成员不足时按数量收缩；"
                  "单个文件夹可在右键菜单里单独设置")
        lay.addWidget(card)

        card, c = self._card(body, "翻页与排列")
        self.cmb_page_axis = ComboBox()
        self.cmb_page_axis.addItem("左右翻页", "horizontal")
        self.cmb_page_axis.addItem("上下翻页", "vertical")
        self.cmb_page_axis.setCurrentIndex(
            max(0, self.cmb_page_axis.findData(grid_flow.page_axis(self.storage))))
        self.cmb_page_axis.currentIndexChanged.connect(self._apply_page_axis)
        self._row(c, card, "翻页方向", self.cmb_page_axis,
                  "左右为横向滑入滑出，上下为竖向")

        self.chk_auto_arrange = Switch()
        self.chk_auto_arrange.setChecked(bool(self.storage.get_setting("auto_arrange")))
        self.chk_auto_arrange.toggled.connect(self._apply_auto_arrange)
        self._row(c, card, "自动排列图标",
                  self.chk_auto_arrange, "开启后按阅读序递进；关闭则自由摆放")
        lay.addWidget(card)

        # ---------- v9 V2：每页排序规则 ----------
        card, c = self._card(body, "分页自动排列")
        self.chk_page_rules = Switch()
        self.chk_page_rules.setChecked(page_rules.custom_enabled(self.storage))
        self.chk_page_rules.toggled.connect(self._apply_page_rules_custom)
        self._row(c, card, "每页单独设置",
                  self.chk_page_rules,
                  "关闭时所有分页跟随「自动排列图标」；开启后可逐页指定")
        self._rules_holder = QWidget(card)
        self._rules_lay = QVBoxLayout(self._rules_holder)
        self._rules_lay.setContentsMargins(0, 6, 0, 2)
        self._rules_lay.setSpacing(6)
        c.addWidget(self._rules_holder)
        self._rule_combos = {}
        self._rebuild_page_rules()
        lay.addWidget(card)

    def _page_mode(self, body, lay):
        # ---- v9 V4-6 交互方式（Windows 习惯 / 手机习惯） ----
        # 放在「模式」页最上面：这是"桌面怎么用"的总开关，比布局细节更基础。
        card, c = self._card(body, "交互方式")
        self.cmb_interaction = ComboBox()
        for key, text in interaction.MODES:
            self.cmb_interaction.addItem(text, key)
        self.cmb_interaction.setCurrentIndex(
            max(0, self.cmb_interaction.findData(interaction.mode(self.storage))))
        self.cmb_interaction.currentIndexChanged.connect(self._apply_interaction)
        self._row(c, card, "操作逻辑", self.cmb_interaction,
                  "切换后立即生效")
        self.lbl_interaction = QLabel(interaction.describe(interaction.mode(self.storage)))
        self.lbl_interaction.setObjectName("rowHint")
        self.lbl_interaction.setWordWrap(True)
        c.addWidget(self.lbl_interaction)
        lay.addWidget(card)

        card, c = self._card(body, "桌面接管")
        # 反馈 16：**启动即接管**——「接管系统桌面」开关冗余，已删除。
        # 想回到原生桌面就退出程序；只想用小组件就把「通用 → 显示桌面
        # 小组件」打开、图标仍由本程序接管（两者互不牵连）。
        # v10 A4（反馈 10 规则 1）：括号只留给单位/取值域，行为解释不进括号。
        note = QLabel("程序启动即接管系统桌面，原生图标随之隐藏；"
                      "不需要时退出程序即可恢复。小组件有独立开关，见「通用」页。")
        note.setObjectName("rowHint")
        note.setWordWrap(True)
        c.addWidget(note)

        self.cmb_layout_mode = ComboBox()
        self.cmb_layout_mode.addItem("网格模式", "grid")
        self.cmb_layout_mode.addItem("无界模式", "free")
        self.cmb_layout_mode.setCurrentIndex(
            max(0, self.cmb_layout_mode.findData(grid_flow.layout_mode(self.storage))))
        self.cmb_layout_mode.currentIndexChanged.connect(self._apply_layout_mode)
        # 仅小组件模式（反馈 9）：组件必须无界，布局下拉置灰并说明原因
        # （窗口侧 set_layout_mode 还有护栏，双保险）。
        widgets_only = bool(self.storage.get_setting("widgets_only"))
        self.cmb_layout_mode.setEnabled(not widgets_only)
        self._row(c, card, "布局", self.cmb_layout_mode,
                  "无界模式可自由重叠摆放，可添加空白页" if not widgets_only
                  else "仅小组件模式下组件始终无界，退出后可切换")
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
                  self.chk_autosync, "新增、删除、重命名 1 秒内生效，不重排已有位置")
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
        self._row(c, card, "桌面文件", btns, "重新扫描只增删差异，不重排已摆好的位置")
        lay.addWidget(card)

        card, c = self._card(body, "开发者调试")
        self.chk_dev = Switch()
        self.chk_dev.setChecked(bool(self.storage.get_setting("dev_mode")))
        self.chk_dev.toggled.connect(self._apply_dev_mode)
        self._row(c, card, "显示网格调试信息",
                  self.chk_dev, "网格线、原点与 cell 尺寸画在桌面上")

        # 网格原点定位（v7 §3.4 / 反馈 21）：**开发者功能**，只有上面的
        # 开发者开关打开后才可配置（2026-10-20 用户反馈 5：不要放桌面右键）。
        origin_manual = self.storage.grid_origin_mode() == "manual"
        self.chk_origin = Switch()
        self.chk_origin.setChecked(origin_manual)
        self.chk_origin.toggled.connect(self._apply_origin_mode)
        self._row(c, card, "手动定位网格原点",
                  self.chk_origin,
                  "关闭时四边等距居中；开启后用下面两个数值精调")

        self.sp_ox = Stepper()
        self.sp_ox.setRange(0, 9999)
        self.sp_ox.setSingleStep(2)
        self.sp_ox.setSuffix(" px")
        self.sp_ox.setFixedWidth(96)
        self.sp_ox.setEnabled(origin_manual)
        self.sp_ox.valueChanged.connect(self._apply_origin_spin)
        self._row(c, card, "原点 X", self.sp_ox,
                  "网格左上角的横坐标，超出屏幕会夹回屏内")

        self.sp_oy = Stepper()
        self.sp_oy.setRange(0, 9999)
        self.sp_oy.setSingleStep(2)
        self.sp_oy.setSuffix(" px")
        self.sp_oy.setFixedWidth(96)
        self.sp_oy.setEnabled(origin_manual)
        self.sp_oy.valueChanged.connect(self._apply_origin_spin)
        self._row(c, card, "原点 Y", self.sp_oy,
                  "网格左上角的纵坐标，与 X 共同决定网格位置")

        self.btn_reset_origin = QPushButton("重置网格位置")
        self.btn_reset_origin.setEnabled(origin_manual)
        self.btn_reset_origin.clicked.connect(self._reset_grid_origin)
        self._row(c, card, "网格位置", self.btn_reset_origin,
                  "回到四边等距居中，格子越大越靠里")

        # 桌面取点：从右键挪进来的入口（反馈 5）。点它先关设置窗，
        # 用户在桌面空白处点一下即为网格左上角。
        self.btn_pick_origin = QPushButton("在桌面上点选位置")
        self.btn_pick_origin.setEnabled(origin_manual)
        self.btn_pick_origin.clicked.connect(self._pick_origin_on_desktop)
        self._row(c, card, "点选位置", self.btn_pick_origin,
                  "在桌面空白处点选，即为网格左上角")
        lay.addWidget(card)
        self._sync_origin_controls()

        # 「关于」：版本标识（v6c 跑错包事故的取证设施——从桌面右键挪到这里，
        # 既满足"右键别塞版本号"，又保留"一眼看出跑的是哪个包"的能力）。
        card, c = self._card(body, "关于")
        from . import version
        self.lbl_about_version = QLabel(version.label())
        self.lbl_about_version.setObjectName("rowHint")
        self._row(c, card, "当前版本", self.lbl_about_version,
                  "构建时刻取自程序文件，可确认跑的是否最新包")
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

    # 连续输入控件（滑条 / 步进器长按连步）的统一落地节流。
    # 两个口径都要满足（2026-10-21 反馈 1）：
    #   停顿 60ms 就落地 -> 拖一下停一下也有实时反馈；
    #   连续拖动能忍的上限 220ms -> 不会"拖了半天桌面没反应"。
    # 实测 refresh_grid() 单次 16~22ms（60 图标）：每像素一次 = GUI 线程
    # 100% 占满，鼠标事件排队 -> "拖不动 / 断触"。
    GRID_REFRESH_DEBOUNCE = 60       # ms
    GRID_REFRESH_MAX_WAIT = 220      # ms

    def _schedule_grid_refresh(self):
        """几何类控件的统一落地入口（2026-10-21 反馈 1：滑条**断触**）。

        `refresh_grid()` 会**销毁重建全部桌面图标**并重新挂载桌面带；
        滑条 `valueChanged` 每像素触发一次，GUI 线程被重建占满，Qt 的
        鼠标抓取被反复打断，用户看到的就是"拖一下就停、不流畅"。
        同类问题也命中行列/原点步进器的长按连步（每 80ms 一次重建）。

        修法：**写入立即做**（storage 很便宜，滑条旁边的百分比立刻变），
        **重建走节流**——纯防抖（停顿即落地）+ 上限等待（连续拖动也保证
        每 220ms 内给一次反馈）。一次性操作（勾选 / 切换档位）仍走
        `_refresh_grid` 直连，不需要节流。
        """
        t = getattr(self, "_grid_timer", None)
        if t is None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(self._on_grid_debounced)
            self._grid_timer = t
            self._grid_wait = QElapsedTimer()
            self._grid_wait.start()
        if t.isActive():
            if self._grid_wait.elapsed() >= self.GRID_REFRESH_MAX_WAIT:
                t.stop()                            # 忍够了：立刻给一次反馈
                self._grid_wait.restart()
                self._refresh_grid()
                return
            t.start(self.GRID_REFRESH_DEBOUNCE)     # 重启 = 纯防抖语义
            return
        self._grid_wait.restart()
        t.start(self.GRID_REFRESH_DEBOUNCE)

    def _on_grid_debounced(self):
        self._grid_wait.restart()
        self._refresh_grid()

    def _apply_autostart(self, checked):
        autostart.set_enabled(bool(checked))
        self.storage.set_setting("autostart", bool(checked))

    def _refresh_icon_labels(self):
        """图标档位说明：显示当前占比与推导出的图标像素（v7 §3.1）。"""
        from . import grid_sizing
        # 滑条可用性先于几何算（几何快照未就绪时下面会 early return，
        # 但"三档预设下滑条只读"这条与几何无关，必须先生效）
        sld = getattr(self, "sld_icon_fit", None)
        if sld is not None:
            sld.setEnabled(self.storage.icon_tier() == "custom")
        m = grid_flow.current_metrics()
        if m is None:
            # 快照未就绪（对话框先于几何创建 / 悬浮兜底）：至少把滑条
            # 摆到**实际生效**的占比上，别让它停在 0% 造成"设置丢了"的
            # 错觉。走 resolved_icon_fit()（medium 也有确定值），旧实现读
            # `icon_fit()` 拿到 None -> 滑条留在 30% -> "中档却显示 30%"。
            self.lbl_icon_px.setText("")
            fit0 = self.storage.resolved_icon_fit()
            if getattr(self, "lbl_icon_fit", None) is not None:
                self.lbl_icon_fit.setText("%d%%" % int(round(fit0 * 100)))
            if sld is not None:
                sld.blockSignals(True)
                sld.setValue(max(sld.minimum(),
                                 min(int(round(fit0 * 100)), sld.maximum())))
                sld.blockSignals(False)
            return
        fit = self._effective_fit(m)
        lay = grid_sizing.icon_layout(m.cw, m.ch, fit)
        self.lbl_icon_px.setText("图标 %dpx" % lay.icon_box)
        if getattr(self, "lbl_icon_fit", None) is not None:
            self.lbl_icon_fit.setText("%d%%" % int(round(fit * 100)))
        self._sync_fit_controls(fit)

    def _effective_fit(self, m=None):
        """当前**实际生效**的图标占比（medium 用 native_px/cell_w 解算）。

        v7c（反馈 3）：解算逻辑收到 `storage.resolved_icon_fit()`——设置页
        显示的"图标 Npx"必须与桌面真正画出来的尺寸同源，否则面板说 57%
        桌面画 54%（换屏后两者分叉），用户眼里就是"默认档位不对"。
        """
        from . import grid_flow
        m = m if m is not None else grid_flow.current_metrics()
        return self.storage.resolved_icon_fit(m.cw if m is not None else None)

    def _sync_fit_controls(self, fit):
        """把三档下拉与自定义滑条同步到 fit（阻断信号，避免回写死循环）。

        v7 B2（反馈 9）：滑条**只在「自定义」档可拖**。三档预设下它跟着
        显示该档的占比但置灰——否则用户拖动滑条，值立刻被 `tier_for_fit`
        反查成最近预设，看着像"拖了不生效"。
        """
        from .storage import tier_for_fit
        sld = getattr(self, "sld_icon_fit", None)
        cmb = getattr(self, "cmb_tier", None)
        if sld is not None:
            sld.blockSignals(True)
            sld.setValue(int(round(fit * 100)))
            sld.blockSignals(False)
        # 档位以 storage 为准：custom 是显式档位，不能被数值反查覆盖
        stored = self.storage.icon_tier()
        tier = stored if stored == "custom" else (tier_for_fit(fit) or stored)
        if cmb is not None and tier:
            idx = cmb.findData(tier)
            if idx >= 0 and idx != cmb.currentIndex():
                cmb.blockSignals(True)
                cmb.setCurrentIndex(idx)
                cmb.blockSignals(False)
        if sld is not None:
            sld.setEnabled(tier == "custom")

    def _apply_icon_tier(self, _index):
        tier = self.cmb_tier.currentData()
        if not tier:
            return
        from . import grid_sizing
        if tier == "custom":
            # 切到自定义：沿用当前占比（用户接着拖滑条微调），
            # 只把档位名义改掉，视觉不跳变。
            self.storage.apply_icon_fit(self._effective_fit(), tier="custom")
        else:
            self.storage.apply_icon_fit(grid_sizing.parse_fit(tier), tier=tier)
        self._refresh_icon_labels()
        self._refresh_grid()

    def _apply_icon_fit(self, value):
        """自定义占比滑条（30%~90%）：走 storage 唯一写入点，档位=自定义。

        反馈 1（2026-10-21）：滑条**断触**的根因见 `_schedule_grid_refresh`
        ——每像素一次全桌面重建。这里只写值 + 刷标签，重建交给防抖定时器。
        """
        self.storage.apply_icon_fit(int(value) / 100.0, tier="custom")
        self._refresh_icon_labels()
        self._schedule_grid_refresh()

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
        self._schedule_grid_refresh()
        self._refresh_grid_spins()

    def _apply_rows(self, value):
        if getattr(self, "_grid_syncing", False):
            return
        if self.chk_auto_cols.isChecked():
            return
        self.storage.set_setting("grid_rows", int(value))
        self._schedule_grid_refresh()
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
        # 开发者功能门槛：dev_mode 关闭时整组只读（数据保持，只是不能改）
        dev = bool(self.storage.get_setting("dev_mode"))
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
            chk.setEnabled(dev)
            for sp, v in ((self.sp_ox, ox), (self.sp_oy, oy)):
                sp.blockSignals(True)
                sp.setEnabled(dev and manual)
                sp.setValue(max(0, min(int(v), sp.maximum())))
                sp.blockSignals(False)
            self.btn_reset_origin.setEnabled(dev and manual)
            pick = getattr(self, "btn_pick_origin", None)
            if pick is not None:
                pick.setEnabled(dev and manual)
        finally:
            self._origin_syncing = False

    def _pick_origin_on_desktop(self):
        """关掉设置窗，把桌面让给"取点"（反馈 5：入口从右键挪到开发者页）。"""
        fn = getattr(self.window, "_begin_pick_origin", None)
        if callable(fn) and fn():
            self.accept()

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
        self._schedule_grid_refresh()
        self._sync_origin_controls()

    def _reset_grid_origin(self):
        """重置网格位置：两键一起清空 -> 回居中（与桌面右键同一入口语义）。"""
        self.storage.reset_grid_origin()
        self._refresh_grid()
        self._sync_origin_controls()

    def _refresh_scaled_icons(self):
        """重建「已配置额外大小的图标」列表（反馈 12 的反悔入口）。"""
        box = getattr(self, "_scaled_box", None)
        if box is None:
            return
        while box.count():
            item = box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._scaled_rows = []
        scaled = []
        for e in self.storage.layout:
            if e.get("type") != "app":
                continue
            try:
                s = float(e.get("icon_scale", 1.0) or 1.0)
            except (TypeError, ValueError):
                s = 1.0
            if abs(s - 1.0) > 1e-6:
                scaled.append((e, s))
        if not scaled:
            lb = QLabel("没有单独设置过大小的图标")
            lb.setObjectName("rowHint")
            box.addWidget(lb)
            return
        for e, s in scaled:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 2, 0, 2)
            h.setSpacing(10)
            app = e.get("app") or {}
            name = app.get("name") or e.get("id") or "?"
            pct = int(round(s * 100))
            lb = QLabel("%s · %d%%" % (name, pct))
            lb.setObjectName("rowTitle")
            btn = QPushButton("恢复 100%")
            btn.setFixedWidth(96)
            eid = e.get("id")
            btn.clicked.connect(
                lambda _c=False, eid=eid: self._reset_icon_scale(eid))
            h.addWidget(lb, 1)
            h.addWidget(btn, 0)
            box.addWidget(row)
            self._scaled_rows.append((eid, pct, btn))

    def _reset_icon_scale(self, entry_id):
        """把某个图标的大小恢复成 100%（并刷新本页列表）。"""
        hook = getattr(self.window, "set_icon_scale", None)
        if callable(hook):
            hook(entry_id, 100, True)
        else:
            e = self.storage.find_entry(entry_id)
            if e is not None:
                e.pop("icon_scale", None)
                self.storage.save()
        self._refresh_scaled_icons()

    def _apply_folder_frame_default(self, _value=0):
        """文件夹默认展开尺寸（反馈 14）：写全局默认并让已开的弹窗重排。"""
        c = int(self.sp_folder_cols.value())
        r = int(self.sp_folder_rows.value())
        self.storage.set_setting("folder_frame_default", [c, r])
        hook = getattr(self.window, "refresh_folder_popup", None)
        if callable(hook):
            hook()

    def _apply_page_axis(self, _index):
        axis = self.cmb_page_axis.currentData() or "horizontal"
        hook = getattr(self.window, "set_page_axis", None)
        if hook is not None:
            hook(axis)
        else:
            self.storage.set_setting("page_axis", axis)

    def _apply_auto_arrange(self, checked):
        """自动排列（反馈 3）：开关就是"此后一直生效"，开启时立刻整理一次。

        v9 V2：启用"每页单独设置"时只整理**自动排列的那些页**——否则
        用户特意留作自由摆放的页会被这一次总开关顺手排掉。
        """
        self.storage.set_setting("auto_arrange", bool(checked))
        self._rebuild_page_rules()      # 下拉可用性随开关变（v10 A1 起不再有复述文字）
        if checked:
            tidy = getattr(self.window, "_tidy", None)
            if tidy is not None:
                tidy(self._auto_pages())

    def _auto_pages(self):
        """当前应当自动排列的页集合（None = 全部，交给窗口按全局整理）。"""
        if not page_rules.custom_enabled(self.storage):
            return None
        return page_rules.auto_pages(self.storage,
                                     grid_flow.page_count(self.storage))

    # ---------- v9 V2：分页排序规则 ----------
    def _apply_page_rules_custom(self, checked):
        page_rules.set_custom(self.storage, bool(checked))
        self._rebuild_page_rules()
        self._refresh_grid()

    def _rebuild_page_rules(self):
        """按当前页数重建"第 N 页"下拉（页数随屏幕/条目变化，不能写死）。"""
        if not hasattr(self, "_rules_lay"):
            return
        while self._rules_lay.count():
            item = self._rules_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rule_combos = {}
        total = max(1, grid_flow.page_count(self.storage))
        custom = page_rules.custom_enabled(self.storage)
        for page in range(total):
            row = QWidget(self._rules_holder)
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)
            lab = QLabel("第 %d 页" % (page + 1), row)
            lab.setFixedWidth(64)
            h.addWidget(lab)
            cmb = ComboBox()
            for value, text in page_rules.MODE_LABELS:
                cmb.addItem(text, value)
            cur = page_rules.rule_of(self.storage, page)
            idx = cmb.findData(cur)
            cmb.setCurrentIndex(max(0, idx))
            cmb.setEnabled(custom)
            cmb.currentIndexChanged.connect(
                lambda _i, p=page, c=cmb: self._apply_page_rule(p, c))
            cmb.setAccessibleName("第 %d 页排序规则" % (page + 1))
            h.addWidget(cmb, 1)
            # v10 A1（反馈 1）：原来这里再挂一个 hint 标签复述下拉选中的文字
            # （"跟随全局（自动排列）"），与 combo 完全重复——删掉，全局实际结果
            # 看卡片顶部的「自动排列图标」开关。
            self._rules_lay.addWidget(row)
            self._rule_combos[page] = cmb

    def _apply_page_rule(self, page, combo):
        value = combo.currentData() or page_rules.INHERIT
        page_rules.set_mode(self.storage, page, value)
        self._rebuild_page_rules()
        self._refresh_grid()

    def _apply_dev_mode(self, checked):
        self.storage.set_setting("dev_mode", bool(checked))
        # 原点定位属开发者功能：开关一翻，整组控件跟着可用/不可用
        self._sync_origin_controls()
        self._call_window('update')

    def _apply_opacity(self, value):
        self.lbl_opacity.setText("%d%%" % value)
        self.storage.set_setting("opacity", value / 100.0)
        # v10 A8（反馈 14）：挂载态下半透明对分层窗口无效，还会连带命中测试
        # 一起变（透明区穿透的教训）——保持 1.0，滑条本就在挂载态被置灰。
        if getattr(self.window, "attached", False):
            self.window.setWindowOpacity(1.0)
        else:
            self.window.setWindowOpacity(value / 100.0)

    def _apply_widgets(self, checked):
        on = bool(checked)
        self.storage.set_setting("show_widgets", on)
        if self.layer is not None:
            self.layer.set_visible(on)
        if not on and bool(self.storage.get_setting("widgets_only")):
            # 仅小组件模式下再关小组件 = 桌面什么都不剩：自动退出该模式，
            # 让图标回来（避免"空桌面"死局）。
            self.chk_widgets_only.setChecked(False)

    def _apply_widgets_only(self, checked):
        """仅小组件模式（v7 反馈 9）：写设置 + 通知窗口切模式/重建。

        窗口是单一写者（set_widgets_only 内部自己落设置），这里只转发；
        窗口不可用时（探针 / 单测窗口替身）才自己写，保证设置不丢。
        """
        on = bool(checked)
        if on and not bool(self.storage.get_setting("show_widgets")):
            # 仅小组件 = 只显示组件：组件开关必须跟着开（否则桌面全空），
            # 设置窗里的开关态也同步回落，避免"显示与实际不符"。
            self.chk_widgets.setChecked(True)
        hook = getattr(self.window, "set_widgets_only", None)
        if hook is not None:
            hook(on)
        else:
            self.storage.set_setting("widgets_only", on)

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

    def _apply_interaction(self, _index=0):
        """交互方式落盘（v9 V4-6）。

        优先走窗口的 `set_interaction_mode`：它负责清掉半途手势、退出多选
        标记——两处入口（设置页 / 桌面右键）必须做同一件事，各自写一份
        逻辑迟早漂移。
        """
        key = self.cmb_interaction.currentData()
        apply_win = getattr(self.window, "set_interaction_mode", None)
        if callable(apply_win):
            apply_win(key)
        else:
            interaction.set_mode(self.storage, key)
        self.lbl_interaction.setText(interaction.describe(key))

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
                                   "确定要重置整理布局吗？将重新克隆当前桌面文件，不会删除任何文件。")
        if ret == QMessageBox.Yes:
            self.storage.seed_desktop_clone(replace=True)
            self._call_window('rebuild')
