# -*- coding: utf-8 -*-
"""可拖拽的桌面图标控件（网格与文件夹弹窗共用）——腾讯桌面整理深色风格。

视觉：
  - 图标 + 下方两行白字标签（带阴影，任意壁纸可读）
  - 悬停：圆角浅色高亮；选中：蓝色浅底 + 蓝色描边
  - 文件夹：深色半透明圆角方形 + 2x2 迷你图标（1/2/3/4 成员自适应布局）

交互：
  - 左键按下移动超过系统拖拽阈值 -> 自管理拖拽循环（grabMouse + 合成拖放事件）
  - 拖到另一个图标上            -> mergeRequested（创建 / 合并文件夹）
  - 拖到窗口空白处              -> 由主窗口移动到目标网格
  - 文件夹内图标拖出            -> payload 形如 "M:fid:idx"
  - 单击        -> 选中（clicked）；双击 -> 打开
  - 右键        -> 打开 / 在文件夹中显示 / 移出文件夹 / 解散 / 移除

动效（苹果 HIG / Fluid Interfaces 规范，真弹簧见 src/effects.py）：
  - 按下 scale(0.97) 100ms ease-out（pointer-down 即反馈，不等松手）
  - 松开 / 悬停归位：临界阻尼弹簧（damping 1.0，无动量不过冲）
  - 拖动落位：欠阻尼弹簧 0.62（带动量才有 ~7% 一次衰减过冲）
  - 悬停 1.04 轻放大；拖动提拉 1.06
  - 双击/打开文件夹脉冲：峰值 1.08 上冲 90ms + 临界阻尼回落
  - rebuild 错峰淡入（stagger 30ms/个，欠阻尼 0.72 落位微弹）
  - 系统关闭动画效果时（prefers-reduced-motion 等价）自动降级为短淡入
"""
from PySide6.QtCore import (QEasingCurve, QMimeData, QPoint, QPointF,
                            QPropertyAnimation, QRect, QRectF, QSize, Qt,
                            Signal, Property, QTimer)
from PySide6.QtGui import (QBrush, QColor, QDragEnterEvent, QDragLeaveEvent,
                           QDragMoveEvent, QDropEvent, QFontMetrics,
                           QLinearGradient, QPen, QPixmap, QPainter)
from PySide6.QtWidgets import QApplication, QMenu, QToolTip, QWidget

from . import appsource
from . import drag_merge
from . import effects
from .folder_tint import folder_tint
from . import theme
from .storage import entry_app

MIME_TYPE = "application/x-desktoporg-item"

# 拖到图标上后进入「合并文件夹」武装状态所需的悬停时长（ms）。
# 未满即松手 -> 走网格让位置换（安卓 launcher 默认语义）；
# 悬停足够久图标高亮后松手 -> 合并文件夹。两套手势由此分流。
DWELL_MERGE_MS = 450

# 判定「压到目标中心」的重叠比例（占较小矩形面积）。
# >= 该值 = 想合并（武装 dwell）；否则视为擦边 = 想放这里并挤走对方。
# 2026-10-20 用户反馈 F3：0.45 太高——把图标叠到目标上往往还不到 45%，
# 于是被判成"擦边"走挤走逻辑，合并提示永远出不来。降到 0.30（压上去
# 就算合并候选）。阈值单点定义在 drag_merge，这里只做 re-export。
MERGE_OVERLAP_RATIO = drag_merge.MERGE_OVERLAP_RATIO

# v6 §5.1（反馈 6）：拖动浮影 = 当前图标的 render 快照，半透明 0.8——
# 替换旧 QDrag 的白块占位，拖动中保留原始样式（图标 + 标签 + 状态）。
GHOST_OPACITY = 0.8


class _DragGhost(QWidget):
    """浮动拖影：frameless + 半透明背景 + 对鼠标事件透明。

    替代 QDrag 的拖拽图像。QDrag.exec() 在 Windows 上走 OLE DoDragDrop
    模态循环，注入（合成）鼠标输入会被该循环吞掉释放事件导致拖拽永不
    成落（DEVLOG Day4 实证：17ms 内取消、零 DragEnter），故改自管理
    拖拽循环 + 本拖影。Qt.ToolTip 标志：无任务栏按钮、不抢焦点、
    在桌面层应用窗口之上可见。
    """

    def __init__(self, pixmap: QPixmap):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._pm = pixmap
        # 快照带 devicePixelRatio（DPR 感知）：固定尺寸要用逻辑尺寸，
        # 否则 125% 缩放下拖影会比图标大一圈（同 AppIcon 的尺寸教训）
        dpr = max(1.0, float(pixmap.devicePixelRatio()))
        self.setFixedSize(max(1, int(round(pixmap.width() / dpr))),
                          max(1, int(round(pixmap.height() / dpr))))

    def paintEvent(self, e):
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pm)


class AppIcon(QWidget):
    activated = Signal(dict)            # 双击启动
    clicked = Signal(str)               # 单击选中（entry id）
    folderClicked = Signal(str)         # 单击文件夹（entry id）
    mergeRequested = Signal(str, str)   # 拖拽合并：dragged_payload, target_entry_id
    removeRequested = Signal(str)       # 右键移除（entry id）
    removeFromFolder = Signal(str)      # 文件夹内右键移出（payload "M:fid:idx"）
    dissolveRequested = Signal(str)     # 解散文件夹（entry id）
    openLocation = Signal(dict)         # 在资源管理器中定位（桌面文件）
    dragStarted = Signal()
    dragFinished = Signal()
    reflowHover = Signal(str, int, int)  # 拖动悬停：payload, 指针全局 x, y
    reflowDrop = Signal(str, int, int)   # 悬停未满即松手：payload, 指针全局 x, y

    def __init__(self, entry: dict, icon_size: int, in_folder: bool = False,
                 parent=None, chrome_scale: float = 1.0, layout=None,
                 compact: bool = False, show_label: bool = True):
        super().__init__(parent)
        self.entry = entry
        self.in_folder = in_folder
        self.selected = False
        # 外围 chrome 缩放（留白 / 标签字号 / 行高随 DPI×用户缩放同比放大，
        # 图标本身由 icon_size 已经放大——2026-10-18 DPI 感知）
        self._m = max(0.5, float(chrome_scale))
        self._no_label = not bool(show_label)
        # v6 批次 A2（指导文档 §2.2）：grid_sizing.IconLayout 三档方案。
        # 传入时 chrome 全部按 cell/widget 比例派生（标签单行小字 elide，
        # 密度加密后瘦身——旧绝对值 24m/40m 在 cell 变小后会把图标挤成小点）；
        # 不传（folder 成员 / 探针 / 旧调用）保持 2026-10-18 旧行为。
        self._layout = layout
        if layout is not None:
            self.icon_size = int(layout.icon_box)      # 绘制区（pixmap 边长）
            self._box_x = int(layout.chrome_x)         # 绘制区左侧留白（居中）
            self._label_h = int(layout.label_h)
            self._label_font_px = int(layout.font_px)
            self.setFixedSize(int(layout.widget_w), int(layout.widget_h))
        elif compact:
            # 文件夹内部格（2026-10-19 反馈 6）：手机文件夹是**紧凑图标阵**，
            # 没有文件名、没有大片留白——参照 iOS/安卓文件夹内部。
            pad = max(2, int(round(4 * self._m)))
            self.icon_size = int(icon_size)
            self._box_x = pad
            self._no_label = True
            self._label_h = 0
            self._label_font_px = 11
            self.setFixedSize(icon_size + pad * 2, icon_size + pad * 2)
        else:
            self.icon_size = icon_size
            self._box_x = None
            self._label_h = int(round(34 * self._m))
            # 旧路径标签字号也按 chrome 现算存档（12px @100%，15px @125%），
            # 属性语义统一：_label_font_px 始终有值
            self._label_font_px = max(11, int(round(theme.LABEL_SIZE * self._m)))
            # chrome 精修（2026-10-18 用户反馈"图标大小不对"）：旧值 28/46 的
            # 留白占比过大，图标显小。收紧到 24/40，标签贴近图标 6px。
            self.setFixedSize(icon_size + int(round(24 * self._m)),
                              icon_size + int(round(40 * self._m)))
        self.drag_payload = entry.get("id", "")
        self.payload_provider = None  # 多选拖拽时由主窗口注入，返回逗号分隔的 id 列表
        self._press_pos = None
        self._dragged = False
        # 自管理拖拽循环状态（替代 QDrag.exec 的 OLE DoDragDrop，见 _exec_drag）：
        #   _drag_loop     拖动进行中（grabMouse 已捕获全部鼠标事件）
        #   _drag_target   当前悬停目标（本应用部件；应用外/无目标为 None）
        #   _drag_ghost_w  浮动拖影部件
        #   _drag_mime     本次拖拽的 MIME 数据（payload 协议不变）
        self._drag_loop = False
        self._drag_target = None
        self._drag_ghost_w = None
        self._drag_mime = None
        self._hover = False
        self._merge_target = False
        # 文件夹「打开中」态（M5）：弹窗打开期间源图标高亮
        self._folder_open = False
        # 拖动虚影：拖动期间本图标不绘制（格子在视觉上被让出），但不 hide()——
        # hide 会牵动显隐生命周期与命中测试，纯绘制跳过零风险
        self._drag_ghost = False
        self._drag_crop_off = QPoint(0, 0)   # 快照裁切偏移（拖影对位用）
        # dwell 合并：悬停 450ms 才武装「合并文件夹」（未满即松手 = 让位置换）
        self._merge_armed = False
        self._dwell = QTimer(self)
        self._dwell.setSingleShot(True)
        self._dwell.setInterval(DWELL_MERGE_MS)
        self._dwell.timeout.connect(self._arm_merge)
        # 外围 chrome 缩放（留白 / 标签字号 / 行高随 DPI×用户缩放同比放大，
        # 图标本身由 icon_size 已经放大——2026-10-18 DPI 感知）
        self._m = max(0.5, float(chrome_scale))
        # 动效状态（三个独立属性，动画互不冲突；paintEvent 相乘）
        self._hover_scale = 1.0    # 悬停轻放大
        self._press_scale = 1.0    # 按压 / 拖动提拉 / 脉冲
        self._appear = 1.0         # 错峰淡入进度（rebuild stagger）
        self._anims = []           # 持有动画引用，防 GC
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        # ClickFocus：点击即获键盘焦点。自管理拖拽循环里 Esc 取消依赖
        # 焦点投递（_exec_drag 中 setFocus）——默认 NoFocus 策略下
        # keyPressEvent 永不触发，Esc 分支是死代码。ClickFocus 不加
        # Tab 停靠点，不污染窗口 Tab 序。
        self.setFocusPolicy(Qt.ClickFocus)
        self.setToolTip(self._tooltip())

    # ---------- 动效属性（QPropertyAnimation 直接驱动） ----------
    def _get_hover_scale(self):
        return self._hover_scale

    def _set_hover_scale(self, v):
        if v != self._hover_scale:
            self._hover_scale = v
            self.update()

    def _get_press_scale(self):
        return self._press_scale

    def _set_press_scale(self, v):
        if v != self._press_scale:
            self._press_scale = v
            self.update()

    def _get_appear(self):
        return self._appear

    def _set_appear(self, v):
        if v != self._appear:
            self._appear = v
            self.update()

    hover_scale = Property(float, _get_hover_scale, _set_hover_scale)
    press_scale = Property(float, _get_press_scale, _set_press_scale)
    appear = Property(float, _get_appear, _set_appear)

    def _animate(self, prop, start, end, duration, easing=None):
        """启动属性动画（自动停止同属性上的旧动画并持有引用防 GC）。"""
        for a in list(self._anims):
            if a.propertyName() == prop:
                a.stop()
                self._anims.remove(a)
        anim = QPropertyAnimation(self, prop, self)
        anim.setDuration(effects.dur(duration))
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(easing if easing is not None else effects.smooth_out())
        anim.finished.connect(lambda: self._anims.remove(anim)
                              if anim in self._anims else None)
        self._anims.append(anim)
        anim.start()
        return anim

    def pulse(self, scale=1.08, up_ms=90):
        """启动 / 打开反馈脉冲：快速放大到峰值后弹簧回落。

        苹果规范：峰值克制（1.06~1.08——1.12+ 显廉价）；上冲 OutCubic 90ms，
        回落用临界阻尼弹簧（无动量不过冲）。旧实现峰值 1.12/1.14 且回落是
        OutCubic，已按规范下调。

        注意：pulse 自带回落动画，调用方不得再叠加同属性归位动画
        （_animate 会按属性名停掉旧动画，曾导致 pulse 上冲被立即杀掉、
        从未完整播放——2026-10-18 修复）。
        """
        for a in list(self._anims):
            if a.propertyName() == b"press_scale":
                a.stop()
                self._anims.remove(a)
        up = QPropertyAnimation(self, b"press_scale", self)
        up.setDuration(effects.dur(up_ms))
        up.setStartValue(float(self._press_scale))
        up.setEndValue(float(scale))
        up.setEasingCurve(QEasingCurve.OutCubic)
        self._anims.append(up)

        def _back():
            if up in self._anims:
                self._anims.remove(up)
            # 回落：临界阻尼弹簧（点按反馈无动量，不过冲）
            self._animate(b"press_scale", float(self._press_scale), 1.0, 240,
                          effects.spring_curve(1.0, 240))

        up.finished.connect(_back)
        up.start()

    def appear_in(self, delay_ms=0):
        """错峰淡入（rebuild 后 iOS 风依次落位）：缩放 0.7->1 + 渐显。
        欠阻尼弹簧（damping 0.72，约 2% 过冲）——落位带一点活力，
        但不过 3%（过大显廉价）。系统关闭动画效果时退化为立即显示。"""
        self._appear = 0.0
        self.update()
        delay = 0 if effects.reduced_motion() else max(0, delay_ms)
        QTimer.singleShot(delay, self._play_appear)

    def _play_appear(self):
        if self._appear >= 1.0:
            return
        self._animate(b"appear", 0.0, 1.0, 260, effects.spring_curve(0.72, 260))

    # ---------- 位置动画（网格实时让位） ----------
    def animate_to(self, x: int, y: int, duration: int = 280, damping: float = 0.78):
        """弹簧滑行到目标格（安卓 launcher 的让位语言）。

        与 press_scale / hover_scale / appear 是不同 property，可并行不冲突。
        曲线：欠阻尼 0.78 ≈ 2% 一次微弹——有生命但不廉价；
        落位（带动量）才用 0.62 ≈ 7% 过冲。
        reduced-motion 时直接跳到位（保留结果、去掉位移）。

        2026-10-18 M2 修复（probe17 S2/S5 实证的竞态）：无论走哪个
        分支，都必须先停掉飞行中的旧 pos 动画——否则旧动画会在下一帧
        把图标继续拖向它的旧目标。典型复现：预览动画刚起播就取消回滚，
        图标当前位置恰等于回滚目标 -> 早退分支放行旧动画 -> 松手后
        图标滑到预览位而非原位。
        """
        tx, ty = int(x), int(y)
        for a in list(self._anims):
            if a.propertyName() == b"pos":
                a.stop()
                self._anims.remove(a)
        if (self.pos().x(), self.pos().y()) == (tx, ty):
            return
        if effects.reduced_motion():
            self.move(tx, ty)
            return
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(effects.dur(duration))
        anim.setStartValue(self.pos())
        anim.setEndValue(QPoint(tx, ty))
        anim.setEasingCurve(effects.spring_curve(damping, duration))
        anim.finished.connect(lambda: self._anims.remove(anim)
                              if anim in self._anims else None)
        self._anims.append(anim)
        anim.start()
        return anim

    def set_drag_ghost(self, on: bool):
        """拖动期间本图标停止绘制（视觉上让出格子），不改变 geometry 与命中测试。"""
        if self._drag_ghost != on:
            self._drag_ghost = on
            self.update()

    # ---------- dwell 合并 ----------
    def _arm_merge(self):
        self._merge_armed = True
        self._merge_target = True
        self.update()
        QToolTip.showText(self.mapToGlobal(QPoint(self.width() // 2, 8)),
                          "松手合并为文件夹")

    def _disarm_merge(self):
        self._dwell.stop()
        self._merge_armed = False
        if self._merge_target:
            self._merge_target = False
            self.update()

    # ---------- 属性 ----------
    @property
    def is_folder(self) -> bool:
        return self.entry.get("type") == "folder"

    @property
    def is_file(self) -> bool:
        return entry_app(self.entry).get("kind") == "file"

    def _display_name(self) -> str:
        if self.is_folder:
            # M5：文件夹可重命名（指导文档 §4.2）；entry["name"] 缺省「文件夹」
            return self.entry.get("name") or "文件夹"
        return entry_app(self.entry).get("name", "")

    def _tooltip(self) -> str:
        if self.is_folder:
            name = self.entry.get("name") or "文件夹"
            names = "、".join(a.get("name", "") for a in self.entry.get("apps", [])[:8])
            return "%s：%s" % (name, names) if names else name
        app = self.entry.get("app", {})
        target = app.get("target", "")
        return "%s\n%s" % (app.get("name", ""), target) if target else app.get("name", "")

    def set_selected(self, on: bool):
        if self.selected != on:
            self.selected = on
            self.update()

    def set_folder_open(self, on: bool):
        """文件夹「打开中」态（M5，指导文档 §4.2 源 cell）：弹窗打开期间
        源图标高亮（ACCENT_SOFT + 描边），关闭恢复。"""
        if self._folder_open != bool(on):
            self._folder_open = bool(on)
            self.update()

    def refresh_meta(self):
        """名称/成员变化后刷新 tooltip 与重绘（M5 重命名 / 增删成员）。"""
        self.setToolTip(self._tooltip())
        self.update()

    # ---------- 绘制 ----------
    def paintEvent(self, event):
        if self._drag_ghost:
            return  # 拖动中：本格子已让出，由其他图标滑入填充
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        dpr = self.devicePixelRatioF()

        # 动效缩放：按压 x 悬停 x 错峰淡入（以图标视觉中心为原点，
        # widget geometry 不变——命中测试 / 框选判定完全不受影响）
        s = self._hover_scale * self._press_scale * self._appear
        if abs(s - 1.0) > 0.002 or self._appear < 0.995:
            cy = 2 + self.icon_size / 2.0
            p.translate(w / 2.0, cy)
            p.scale(s, s)
            p.translate(-w / 2.0, -cy)
        if self._appear < 0.995:
            p.setOpacity(self._appear)

        # 背景状态：文件夹打开中 / 悬停 / 合并目标 / 选中
        if self._folder_open:
            # 打开态最醒目：实心 tint + 强描边（一眼看出弹窗属于哪个 cell）
            p.setPen(QPen(theme.ACCENT, 1.5))
            p.setBrush(theme.ACCENT_SOFT)
            p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), theme.RADIUS_ITEM, theme.RADIUS_ITEM)
        elif self._merge_target:
            p.setPen(QPen(theme.ACCENT_BORDER, 1.5))
            p.setBrush(theme.ACCENT_SOFT)
            p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), theme.RADIUS_ITEM, theme.RADIUS_ITEM)
        elif self.selected:
            # 选中态加强：1.5px 描边 + 56% tint（多选/框选后一眼可辨）
            p.setPen(QPen(theme.ACCENT_BORDER, 1.5))
            p.setBrush(theme.ACCENT_SOFT)
            p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), theme.RADIUS_ITEM, theme.RADIUS_ITEM)
        elif self._hover:
            p.setPen(QPen(theme.HOVER_BORDER, 1))
            p.setBrush(theme.HOVER)
            p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), theme.RADIUS_ITEM, theme.RADIUS_ITEM)

        self._paint_icon_only(p, dpr)
        if not self._no_label:
            self._paint_label(p)

    def _paint_icon_only(self, p: QPainter, dpr: float = 1.0):
        """只画图标本体（文件夹瓷砖或应用图标 pixmap），不画任何 chrome。

        正常绘制与拖影快照共用：快照模式下背景态/标签被跳过，剩下的就是
        "原图标"——用户拖动时看到的应该是手指下那个图标，不是一张卡片。
        """
        if self.is_folder:
            self._paint_folder(p, dpr)
            return
        app = self.entry.get("app", {})
        # 高清 pixmap：逻辑尺寸=icon_size（DPR 感知），按逻辑宽度居中，
        # 绝不能用 pm.width()（物理像素）算偏移——那是图标错位/变虚的根因。
        # v6 A2：有 layout 时绘制区左侧留白由 chrome_x 精确给出
        #（cell 变小后按比例派生，不再 (w-icon_size)//2 近似）。
        pm = appsource.icon_pixmap(app, self.icon_size, dpr)
        px = (self._box_x if self._box_x is not None
              else (self.width() - self.icon_size) // 2)
        p.drawPixmap(px, 2, pm)

    def _paint_folder(self, p: QPainter, dpr: float = 1.0):
        """深色圆角方形 + 迷你图标矩阵（安卓风，按成员数 1/2/3/4 自适应）。

        瓷砖材质（2026-10-18 升级）：垂直渐变（顶亮底沉，受光方向与液态
        玻璃一致）+ 顶部 1px 内高光 + 细描边——替代原来的纯色平底。
        M5：渐变取 entry 色板色（folder_tint，与弹窗背板同一颜色），
        缺省回退 theme 深灰瓷砖（iOS 文件夹语言：图标与弹窗同色）。
        """
        s = self.icon_size
        if self._box_x is not None:
            # v6 A2：layout 模式——瓷砖贴满绘制区（左右各 1px 呼吸）
            box = QRectF(self._box_x + 1, 3, s - 2, s - 2)
        else:
            box = QRectF(3, 3, s - 6, s - 6)
        tint = folder_tint(self.entry)
        grad = QLinearGradient(0, box.top(), 0, box.bottom())
        grad.setColorAt(0.0, tint.lighter(135))
        grad.setColorAt(1.0, tint.darker(165))
        p.setPen(QPen(theme.FOLDER_BORDER, 1))
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(box, s * 0.24, s * 0.24)
        # 顶部内高光（光线打在瓷砖上沿，与玻璃 specular 同语言）
        hl = QLinearGradient(box.left() + s * 0.18, 0, box.right() - s * 0.18, 0)
        hl.setColorAt(0.0, QColor(255, 255, 255, 0))
        hl.setColorAt(0.5, theme.FOLDER_HILIGHT)
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(QPen(QBrush(hl), 1.0))
        p.drawLine(QPointF(box.left() + s * 0.16, box.top() + 1.2),
                   QPointF(box.right() - s * 0.16, box.top() + 1.2))
        members = self.entry.get("apps", [])
        n = len(members)
        if n <= 1:
            slots = [(0.50, 0.50, 0.52)]
        elif n == 2:
            slots = [(0.28, 0.50, 0.36), (0.72, 0.50, 0.36)]
        elif n == 3:
            slots = [(0.50, 0.27, 0.32), (0.27, 0.73, 0.32), (0.73, 0.73, 0.32)]
        else:
            slots = [(0.28, 0.28, 0.32), (0.72, 0.28, 0.32), (0.28, 0.72, 0.32), (0.72, 0.72, 0.32)]
        for (fx, fy, fr), app in zip(slots, members[:4]):
            cs = max(8, int(s * fr))
            pm = appsource.icon_pixmap(app, cs, dpr)
            cx = box.left() + fx * box.width() - cs / 2
            cy = box.top() + fy * box.height() - cs / 2
            p.drawPixmap(int(cx), int(cy), pm)

    def _paint_label(self, p: QPainter):
        name = self._display_name()
        if not name:
            return
        if self._layout is not None:
            # v6 A2：单行小字 elide（手机 launcher 语言——密度加密后旧两行
            # 标签 chrome 占比超 40%，必须瘦身）；字号由 layout.font_px
            font = theme.ui_font(self._label_font_px)
            p.setFont(font)
            rect = QRect(2, self.icon_size + 2,
                         self.width() - 4, self._label_h)
            fm = QFontMetrics(font)
            line = fm.elidedText(name, Qt.ElideRight, rect.width())
            if line:
                # 阴影一层 + 白字，保证任意壁纸下可读
                p.setPen(theme.LABEL_SHADOW)
                p.drawText(rect.adjusted(1, 1, 0, 0), Qt.AlignCenter, line)
                p.setPen(theme.LABEL_COLOR)
                p.drawText(rect, Qt.AlignCenter, line)
            return
        # 旧路径（无 layout）：标签字号随 chrome 缩放（DPI×用户缩放）：
        # 100% 时 12px，125% 时 15px；最多两行折行 + 末行省略号
        font = theme.ui_font(self._label_font_px)
        p.setFont(font)
        rect = QRect(2, self.icon_size + int(round(6 * self._m)),
                     self.width() - 4, int(round(34 * self._m)))
        fm = QFontMetrics(font)
        lines = self._wrap_elide(name, fm, rect.width(), 2)
        lh = fm.height() + 1
        # 阴影一层 + 白字，保证任意壁纸下可读
        for i, line in enumerate(lines):
            r = QRect(rect.left(), rect.top() + i * lh, rect.width(), lh)
            p.setPen(theme.LABEL_SHADOW)
            p.drawText(r.adjusted(1, 1, 0, 0), Qt.AlignCenter, line)
            p.setPen(theme.LABEL_COLOR)
            p.drawText(r, Qt.AlignCenter, line)

    @staticmethod
    def _wrap_elide(name: str, fm: QFontMetrics, width: int, max_lines: int) -> list:
        """按像素宽度折行，超过 max_lines 时末行省略号。"""
        words = name.split(" ")
        lines, cur = [], ""
        for w_ in words:
            trial = (cur + " " + w_).strip()
            if fm.horizontalAdvance(trial) <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w_
        if cur:
            lines.append(cur)
        if len(lines) > max_lines:
            kept = lines[:max_lines]
            kept[-1] = fm.elidedText(kept[-1], Qt.ElideRight, width)
            return kept
        return [fm.elidedText(l, Qt.ElideRight, width) for l in lines]

    # ---------- 鼠标 ----------
    def _picking_origin(self) -> bool:
        """宿主是否处于「取点网格原点」态（v7 §3.2）。

        取点态下点图标 = 在图标那个位置定原点，**不许**启动应用/开文件夹/
        改选中——否则用户往图标附近点一下就误启动了一个程序。
        """
        try:
            return bool(getattr(self.window(), "_picking_origin", False))
        except RuntimeError:
            return False

    def _forward_pick(self, e):
        """把这一次按下转交给桌面窗口的取点逻辑（控件坐标已换算）。"""
        try:
            win = self.window()
            finish = getattr(win, "_finish_pick", None)
            if callable(finish):
                pos = self.mapTo(win, e.position().toPoint())
                finish(pos)
        except RuntimeError:
            pass

    def mousePressEvent(self, e):
        if self._picking_origin():
            self._forward_pick(e)
            return
        if e.button() == Qt.LeftButton:
            self._press_pos = e.pos()
            self._dragged = False
            # 苹果 HIG 按压反馈：scale(0.97) 100ms ease-out，pointer-down
            # 即触发不等松手（按下即反馈，消灭延迟）
            self._animate(b"press_scale", self._press_scale, 0.97, 100,
                          QEasingCurve.OutCubic)
        elif e.button() == Qt.RightButton and self._drag_loop:
            # 拖动中按右键 = 取消（与 OLE 拖拽语义一致）
            self._cancel_drag()

    def mouseMoveEvent(self, e):
        if self._drag_loop:
            # 拖动进行中：grabMouse 保证移动事件全部送到本部件，
            # 由拖拽循环驱动拖影 / 命中测试 / 合成拖放事件
            self._drag_move(e.globalPos())
            return
        if self._press_pos is None or not (e.buttons() & Qt.LeftButton):
            return
        if (e.pos() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            return
        self._dragged = True
        self.dragStarted.emit()
        self._exec_drag()

    def mouseReleaseEvent(self, e):
        if self._drag_loop and e.button() == Qt.LeftButton:
            self._finish_drag(e.globalPos())
            return
        if e.button() == Qt.LeftButton and self._press_pos is not None and not self._dragged:
            if self.is_folder:
                # 打开文件夹：脉冲反馈（自带弹簧回落，不再叠加归位动画）
                self.pulse()
                self.folderClicked.emit(self.entry["id"])
            else:
                self.clicked.emit(self.entry["id"])
                # 松开回弹：点按无动量，按苹果规范用临界阻尼弹簧（无过冲）
                self._animate(b"press_scale", self._press_scale, 1.0, 220,
                              effects.spring_curve(1.0, 220))
        elif e.button() == Qt.LeftButton and self._press_pos is not None:
            # 未形成点击的抬起（如拖拽被取消）：临界阻尼平滑归位
            self._animate(b"press_scale", self._press_scale, 1.0, 180,
                          effects.spring_curve(1.0, 180))
        self._press_pos = None

    def keyPressEvent(self, e):
        if self._drag_loop and e.key() == Qt.Key_Escape:
            # Esc 取消拖拽（与 OLE 拖拽语义一致）
            self._cancel_drag()
            e.accept()
            return
        super().keyPressEvent(e)

    # ---------- 自管理拖拽循环（替代 QDrag.exec 的 OLE DoDragDrop） ----------
    def _drag_snapshot(self) -> QPixmap:
        """拖动浮影快照 = **图标本体 + 文件名**，透明底，烘焙 GHOST_OPACITY。

        2026-10-19 两轮反馈叠在一起：
          - "拖拽还有一个白框，不好看，只要原图标就行了"（`render()` 会铺
            调色板底色 → 白框）；
          - "图标拖拽的时候丢失了文件名"（为去白框把标签一起裁掉了）。
        正解不是二选一：**不 render 部件**（避开调色板底色），改用与
        paintEvent 同一份 `_paint_icon_only` + `_paint_label` 直接画到
        透明 pixmap 上——既有原图标也有名字，且没有卡片底色。

        必须在 set_drag_ghost(True) **之前**调用（虚影态 paintEvent 早退）。
        """
        dpr = max(1.0, float(self.devicePixelRatioF()))
        w, h = max(1, self.width()), max(1, self.height())
        pm = QPixmap(max(1, int(round(w * dpr))), max(1, int(round(h * dpr))))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        self._paint_icon_only(p, dpr)
        if not self._no_label:
            self._paint_label(p)
        p.end()
        self._drag_crop_off = QPoint(0, 0)
        if GHOST_OPACITY >= 1.0:
            return pm
        faded = QPixmap(pm.size())
        faded.setDevicePixelRatio(dpr)
        faded.fill(Qt.transparent)
        p = QPainter(faded)
        p.setOpacity(GHOST_OPACITY)
        p.drawPixmap(0, 0, pm)
        p.end()
        return faded

    def _exec_drag(self):
        """启动拖拽：grabMouse + 浮动拖影 + 合成 Qt 拖放事件。

        不再走 QDrag.exec()/OLE DoDragDrop——该模态循环会吞掉注入的
        鼠标释放事件，合成输入下端到端拖拽永不落位（DEVLOG Day4 实证：
        17ms 内即取消返回、零个 DragEnter；真实鼠标下 OLE 虽可用，
        但两条输入路径行为不一致）。grabMouse 让真实鼠标与合成输入
        走同一条代码路径，drop 侧（dragEnter/dragMove/drop 事件处理器）
        完全不变，只是改由本循环派发合成事件驱动。
        """
        payload = self.drag_payload
        if self.payload_provider is not None:
            try:
                payload = self.payload_provider(self.drag_payload) or payload
            except Exception:
                pass
        # 提拉感：拖动源放大 1.06。自管理循环不阻塞 Qt 定时器，
        # 动画照常驱动，这里仍直接置位保证即时反馈。
        self._set_press_scale(1.06)
        # 快照必须先取：set_drag_ghost(True) 之后 paintEvent 早退
        # （本格视觉让出），再 render 抓到的是全透明空图——拖影一片
        # 空白，用户看不到自己拖的是什么（v6 §5.1 顺序病根）。
        pm = self._drag_snapshot()
        # 虚影：本格子在拖动期间视觉让出（其他图标滑入填充），
        # 不 hide()——不动 geometry 与命中测试，撤销只翻一个标志位
        self.set_drag_ghost(True)
        self._drag_mime = QMimeData()
        self._drag_mime.setData(MIME_TYPE, payload.encode())
        self._drag_ghost_w = _DragGhost(pm)
        self._drag_ghost_w.show()
        self._drag_target = None
        self._drag_loop = True
        # 键盘焦点给拖拽源：Esc 取消（keyPressEvent）走焦点投递，
        # grabMouse 只管鼠标。真实鼠标与注入按键共用同一路径。
        self.setFocus()
        self.grabMouse()

    def _drag_move(self, gpos):
        """拖动中：拖影跟随光标 + 命中测试 + 合成 dragEnter/dragMove/dragLeave。"""
        ghost = self._drag_ghost_w
        if ghost is not None and self._press_pos is not None:
            # 快照裁到图标区后左上角不等于部件左上角：减去裁切偏移，
            # 图标才会正好落在指针下（否则会偏出半个标签行）
            off = self._drag_crop_off
            ghost.move(int(gpos.x() - self._press_pos.x() + off.x()),
                       int(gpos.y() - self._press_pos.y() + off.y()))
        target = self._hit_target(gpos)
        if target is not self._drag_target:
            prev, self._drag_target = self._drag_target, target
            if prev is not None:
                self._send_drag_event(prev, QDragLeaveEvent())
            if target is not None:
                self._send_drag_event(target, QDragEnterEvent(
                    target.mapFromGlobal(gpos), Qt.MoveAction,
                    self._drag_mime, Qt.LeftButton, Qt.NoModifier))
        elif target is not None:
            self._send_drag_event(target, QDragMoveEvent(
                target.mapFromGlobal(gpos), Qt.MoveAction,
                self._drag_mime, Qt.LeftButton, Qt.NoModifier))

    def _hit_target(self, gpos):
        """拖放命中：**按拖影与目标的实际重叠分流**（2026-10-19 反馈 9）。

        用户要的手机语义是两套手势：
          - 压到目标中间 -> 停下来提示「松手合并为文件夹」；
          - 只在边缘擦碰 -> 悬浮一会儿把对方挤走。
        旧实现只看**指针**落在谁身上：抓图标角落时指针与图标本体重叠
        滞后，经常"明明已经叠上了却不出合并提示"，或者反过来刚擦边就
        弹合并提示。现在以拖影（= 被拖图标本体）与目标的相交比例判定：

          ratio >= MERGE_OVERLAP_RATIO -> 合并目标（发 dragEnter 武装 dwell）
          否则（含擦边 / 空白）        -> 桌面窗口（网格落点，悬停够久挤走）

        文件夹内部（in_folder）保持原逻辑：成员只在弹窗里拖动/拖出，
        不参与桌面合并。
        """
        ghost = self._drag_ghost_w
        if not self.in_folder:
            best, ratio = self._best_overlap_icon()
            if best is not None and ratio >= MERGE_OVERLAP_RATIO:
                return best
        target = QApplication.widgetAt(gpos)
        if target is ghost or target is self:
            if ghost is not None:
                gc = ghost.mapToGlobal(QPoint(ghost.width() // 2,
                                             ghost.height() // 2))
                t2 = QApplication.widgetAt(gc)
                if t2 is not ghost and t2 is not self:
                    target = t2
                else:
                    target = None
            else:
                target = None
        if self.in_folder:
            return target
        if isinstance(target, AppIcon) and target is not self:
            # 只擦到边缘：目标保持不动，落点交给桌面窗口（实时挤走语义）
            return self._host_desktop(gpos)
        if target is None:
            return self._host_desktop(gpos)
        return target

    def _ghost_rect(self):
        ghost = self._drag_ghost_w
        if ghost is None:
            return None
        try:
            return QRect(ghost.mapToGlobal(QPoint(0, 0)), ghost.size())
        except RuntimeError:
            return None

    def _overlap_ratio(self, other) -> float:
        """拖影与另一个部件的相交比例（占较小矩形面积的百分比 0~1）。

        算法单点定义在 drag_merge.overlap_ratio（桌面窗口侧共用同一份，
        避免两处各写一套导致手感漂移）。
        """
        g = self._ghost_rect()
        if g is None or g.isEmpty():
            return 0.0
        try:
            r = QRect(other.mapToGlobal(QPoint(0, 0)), other.size())
        except RuntimeError:
            return 0.0
        return drag_merge.overlap_ratio(
            (g.x(), g.y(), g.width(), g.height()),
            (r.x(), r.y(), r.width(), r.height()))

    def _best_overlap_icon(self):
        """与拖影重叠最多的同级桌面图标（排除自身/文件夹成员）。"""
        host = self.window()
        if host is None:
            return None, 0.0
        best, best_ratio = None, 0.0
        try:
            kids = host.findChildren(AppIcon)
        except RuntimeError:
            return None, 0.0
        for w in kids:
            if w is self or w.in_folder or not w.isVisible():
                continue
            ratio = self._overlap_ratio(w)
            if ratio > best_ratio:
                best, best_ratio = w, ratio
        return best, best_ratio

    def _host_desktop(self, gpos):
        """退化为宿主桌面窗口（空白区 / 拖影遮挡 / 边缘擦碰）。"""
        win = self.window()
        if win is not None and win is not self:
            try:
                if win.rect().contains(win.mapFromGlobal(gpos)):
                    return win
            except RuntimeError:
                return None
        return None

    def _send_drag_event(self, widget, event):
        """派发合成拖放事件；目标已被销毁（rebuild/deleteLater）时静默跳过。"""
        try:
            QApplication.sendEvent(widget, event)
        except RuntimeError:
            pass

    def _finish_drag(self, gpos):
        """松手：落点有效 -> 合成 drop；gpos 为 None（取消）-> dragLeave。"""
        self._drag_loop = False
        try:
            self.releaseMouse()
        except RuntimeError:
            pass
        target, self._drag_target = self._drag_target, None
        if target is not None:
            if gpos is not None:
                self._send_drag_event(target, QDropEvent(
                    target.mapFromGlobal(gpos), Qt.MoveAction,
                    self._drag_mime, Qt.LeftButton, Qt.NoModifier))
            else:
                self._send_drag_event(target, QDragLeaveEvent())
        self._after_drag()

    def _cancel_drag(self):
        self._finish_drag(None)

    def _after_drag(self):
        """拖拽结束公共清理：撤拖影、发 dragFinished、落位回弹动画。

        整体防御 RuntimeError：drop 触发 rebuild 后本部件可能已被
        deleteLater（C++ 对象删除后任何触碰都抛 RuntimeError）。
        """
        try:
            ghost, self._drag_ghost_w = self._drag_ghost_w, None
            if ghost is not None:
                ghost.close()
            self._press_pos = None
            self.dragFinished.emit()
            # 松手收尾：**不再放大回弹**（2026-10-20 反馈 10）。
            # 旧实现从 1.06 起用欠阻尼 0.62 弹回 1.0——网格模式有落位动画
            # 盖着还好，无界模式位置没变，那一下"鼓包"格外突兀。
            # 改成从当前缩放临界阻尼归位：无过冲，末值精确 1.0。
            self._animate(b"press_scale", self._press_scale, 1.0, 140,
                          effects.spring_curve(1.0, 140))
        except RuntimeError:
            # 拖动期间本部件已被删除/重建（drop -> rebuild() 的 deleteLater、
            # FolderPopup 关闭等），信号源 C++ 对象已不存在。必须吞掉：
            # 异常会冲掉 dragFinished 信号 -> DesktopWindow _on_drag_finished
            # 不执行 -> _drag_active 永久卡死 -> nativeEvent 全窗口
            # HTCLIENT，桌面点击全部失效。
            pass
        # 安全网：dragFinished 信号万一丢失，也要把虚影撤掉，
        # 否则图标会永久不可见（DEVLOG 4.3 同源风险的绘制版）
        QTimer.singleShot(0, self._safe_unghost)

    def _safe_unghost(self):
        try:
            if self._drag_ghost:
                self.set_drag_ghost(False)
        except RuntimeError:
            pass

    def mouseDoubleClickEvent(self, e):
        if self._picking_origin():
            self._forward_pick(e)   # 取点态双击也只定点，不启动应用
            return
        if self.is_folder:
            self.pulse()
            self.folderClicked.emit(self.entry["id"])
        else:
            self.pulse()   # 启动反馈脉冲
            self.activated.emit(self.entry.get("app", {}))

    def enterEvent(self, e):
        self._hover = True
        # 悬停轻放大 1.04：临界阻尼弹簧，可打断（快速划过时从当前值起播）
        self._animate(b"hover_scale", self._hover_scale, 1.04, 140,
                      effects.spring_curve(1.0, 140))
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self._animate(b"hover_scale", self._hover_scale, 1.0, 160,
                      effects.spring_curve(1.0, 160))
        self.update()

    # ---------- 拖放接收 ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_TYPE):
            dragged = e.mimeData().data(MIME_TYPE).data().decode()
            if dragged not in (self.drag_payload, self.entry.get("id")):
                e.acceptProposedAction()
                # 悬停计时：够久才武装合并；未满即松手 = 让位置换
                self._dwell.start()

    def dragMoveEvent(self, e):
        if not e.mimeData().hasFormat(MIME_TYPE):
            return
        dragged = e.mimeData().data(MIME_TYPE).data().decode()
        if dragged in (self.drag_payload, self.entry.get("id")):
            return
        if self.in_folder:
            return  # 文件夹内部不互相合并 / 不让位
        if self._merge_armed:
            return  # 已进入合并分支，不再驱动让位预览
        # 2026-10-19 反馈 4：悬停在另一个图标上**不再驱动实时让位**。
        # 旧实现这里 emit reflowHover -> 主窗口立刻把本图标让位/交换走 ->
        # 指针下的目标消失 -> dragLeave -> dwell(450ms) 归零 ->
        # 「松手合并为文件夹」提示永远出不来（用户："还没有出现提示两个
        # 图标就分开位置了"）。现在悬停只维持 dwell 计时，目标留在原地；
        # 松手时若未武装（不够久）仍由 dropEvent 走 reflowDrop 做让位交换。
        # 让位预览只在拖到**空白格**时生效（主窗口 dragMoveEvent 负责）。
        e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._disarm_merge()
        e.accept()

    def dropEvent(self, e):
        dragged = e.mimeData().data(MIME_TYPE).data().decode()
        armed = self._merge_armed          # 必须先取，_disarm_merge 会清掉它
        self._disarm_merge()
        if dragged in (self.drag_payload, self.entry.get("id")):
            return
        if self.in_folder:
            return  # 文件夹内部不互相合并
        if not armed:
            # 悬停未满 450ms：不合并，走网格让位。
            # 必须直连上报主窗口，不能靠 e.ignore() 冒泡——实测（probe15 G11a）
            # drop 事件不会从图标传播到父窗口（propagated=0），冒泡丢失会让
            # 预览永不提交、最终被 _cancel_preview 回退，表现为"拖了却没动"。
            # 2026-10-18 M2：同样报指针全局坐标（见 dragMoveEvent 注释）。
            e.acceptProposedAction()
            g = self.mapToGlobal(e.position().toPoint())
            self.reflowDrop.emit(dragged, g.x(), g.y())
            return
        self._merge_target = False
        self.update()
        e.acceptProposedAction()
        self.mergeRequested.emit(dragged, self.entry["id"])

    # ---------- 右键菜单 ----------
    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.setStyleSheet(theme.MENU_QSS)
        if self.in_folder:
            menu.addAction("打开", self._open)
            menu.addAction("移出文件夹", self._remove_from_folder)
        elif self.is_folder:
            menu.addAction("打开", self._open_folder)
            menu.addAction("解散文件夹", self._dissolve)
            menu.addAction("从整理桌面移除", self._remove_self)
        elif self.is_file:
            menu.addAction("打开", self._open)
            menu.addAction("在文件夹中显示", self._reveal)
            menu.addAction("从整理桌面移除", self._remove_self)
        else:
            menu.addAction("打开", self._open)
            menu.addAction("从整理桌面移除", self._remove_self)
        menu.exec(e.globalPos())

    def _open(self):
        if not self.is_folder:
            self.activated.emit(self.entry.get("app", {}))

    def _reveal(self):
        self.openLocation.emit(self.entry.get("app", {}))

    def _open_folder(self):
        self.folderClicked.emit(self.entry["id"])

    def _dissolve(self):
        self.dissolveRequested.emit(self.entry["id"])

    def _remove_self(self):
        self.removeRequested.emit(self.entry["id"])

    def _remove_from_folder(self):
        self.removeFromFolder.emit(self.drag_payload)
