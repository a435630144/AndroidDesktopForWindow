# -*- coding: utf-8 -*-
"""首次启动的新手操作指引（v11b / 6.1.0）。

用户需求：「给软件设计一套首次安装启动程序的新手操作指引」。

设计取舍
--------
**不做独立向导窗口**，而是"聚光灯 + 卡片"的覆盖层：

  - 全屏半透明遮罩把桌面压暗，只在高亮目标处挖一个圆角洞——用户看的
    始终是**真实界面**，不是示意图（示意图会立刻和实际版本脱节）。
  - 卡片跟着高亮块走（优先下方，其次上方/左右），永不相交（`place_card`
    是纯函数，测试按逐步骤验证）。
  - 单击遮罩 / → / 空格 = 下一步，← = 上一步，Esc = 跳过。

遮罩是**独立置顶窗口**（`Qt.Tool | WindowStaysOnTopHint`），不挂桌面带：
Dock 和小组件是分层窗，挂在桌面带里的窗口盖不住它们；同时它天然吞掉
鼠标，指引期间用户改不动桌面（避免"边看边把布局拖乱"）。

文案全部走 i18n（`onboarding.step.*`），步骤用 key 而不是函数名——测试
可以只查词表，不必构造界面。

首次判定用 `settings["onboarding_version"] < ONBOARDING_VERSION`：
以后加步骤只需 +1，老用户会重新看到新增内容，已经看过的步骤不会重复
打扰（用 `first_run` 布尔做不到这一点）。
"""
from typing import List, Optional

from PySide6.QtCore import (Property, QEasingCurve, QPoint, QPointF, QRect,
                            QRectF, QSizeF, Qt, QPropertyAnimation, Signal)
from PySide6.QtGui import (QColor, QGuiApplication, QPainter, QPainterPath,
                           QPen)
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from . import effects, grid_flow, i18n, theme

ONBOARDING_VERSION = 1          # 加/改步骤时 +1，老用户会重新看到
CARD_W = 430                    # 卡片宽度（逻辑 px）
CARD_RADIUS = 18
HOLE_RADIUS = 18
STEP_MS = 320                   # 高亮块位移（弹簧稳定时间）
MARGIN = 16                     # 卡片与高亮块 / 屏幕边的最小间距

# 步骤 key（顺序即展示顺序；`missing_i18n_keys` 与测试共用这一份，
# 新增步骤时改这里，词表漏翻会被 O2 直接抓住）
STEP_KEYS = ("welcome", "icons", "folder", "pages", "dock", "widgets",
             "settings")

# 当前活跃的指引（模块级持有引用：Qt 只保留 C++ 侧所有权，
# 纯 Python 引用丢了会被 GC 连窗口一起带走）
_active: Optional["GuideOverlay"] = None


# ---------------------------------------------------------------- 步骤数据
class Step:
    """一步指引：文案 + 高亮矩形（**全局坐标**，空 = 不挖洞、卡片居中）。"""

    __slots__ = ("key", "title", "body", "hole")

    def __init__(self, key: str, title: str, body: str, hole: Optional[QRect] = None):
        self.key = key
        self.title = title
        self.body = body
        self.hole = QRect(hole) if hole is not None else QRect()

    def __repr__(self) -> str:      # 测试失败时看得懂
        return "<Step %s hole=%s>" % (self.key, self.hole)


def _safe_global_rect(w) -> QRect:
    """顶层窗口的全局矩形；对象已销毁 / 不可见 -> 空。"""
    if w is None:
        return QRect()
    try:
        if not w.isVisible():
            return QRect()
        g = w.geometry()
        if g.width() <= 0 or g.height() <= 0:
            return QRect()
        return QRect(g)
    except (RuntimeError, AttributeError):
        return QRect()


def _icon_hole(window, limit: int) -> QRect:
    """当前页前 `limit` 个图标的外接矩形（全局坐标，外扩 10px）。

    一个图标都没有（空桌面）时退回网格左上角 2×2 区域——指引不能因为
    "桌面还没放东西"就少讲一步。
    """
    rects = []
    try:
        win_rect = window.rect()
        icons = list((window.icons or {}).values())
    except (AttributeError, RuntimeError):
        icons, win_rect = [], QRect(0, 0, 1920, 1040)
    for w in icons:
        try:
            g = w.geometry()
        except RuntimeError:
            continue
        # 只取**当前页可见**的图标：其他页的图标被平移到窗口外（cell_pos
        # 带页偏移），并进高亮区会得到一个跨越整屏的巨型洞
        if not win_rect.contains(g.center()):
            continue
        rects.append(g)
    rects.sort(key=lambda r: (r.top(), r.left()))
    if rects:
        union = QRect(rects[0])
        for g in rects[1:limit]:
            union = union.united(g)
        return _to_global(window, union.adjusted(-10, -10, 10, 10))
    return _grid_hole(window, 2, 2)


def _grid_hole(window, cols: int, rows: int) -> QRect:
    """网格左上 cols×rows 的区域（全局坐标）。"""
    m = grid_flow.current_metrics()
    if m is None:
        return QRect()
    r = QRect(m.ox, m.oy, max(1, cols) * m.cw - 6, max(1, rows) * m.ch - 6)
    return _to_global(window, r)


def _to_global(window, rect: QRect) -> QRect:
    """桌面窗口控件坐标 -> 全局坐标。"""
    try:
        return QRect(window.mapToGlobal(rect.topLeft()), rect.size())
    except (RuntimeError, AttributeError):
        return QRect(rect)


def _dots_hole(window) -> QRect:
    """页点区域（全局坐标）；只有一页时返回空（该步会被跳过）。"""
    try:
        pts = window._dot_centers()
    except (AttributeError, RuntimeError):
        return QRect()
    if not pts:
        return QRect()
    r = QRect(pts[0], pts[0])
    for p in pts[1:]:
        r = r.united(QRect(p, p))
    return _to_global(window, r.adjusted(-20, -16, 20, 16))


def _dock_hole(window) -> QRect:
    """Dock 条带矩形；未启用/不可见返回空。"""
    dock = getattr(window, "_dock", None)
    r = _safe_global_rect(dock)
    return r.adjusted(-8, -8, 8, 8) if not r.isNull() else QRect()


def _widget_hole(window) -> QRect:
    """第一个可见小组件的矩形；没有组件返回空。"""
    layer = getattr(window, "_widget_layer", None)
    widgets = getattr(layer, "widgets", None) if layer is not None else None
    if not widgets:
        return QRect()
    rects = []
    for w in list(widgets.values()):
        r = _safe_global_rect(w)
        if not r.isNull():
            rects.append(r)
    if not rects:
        return QRect()
    rects.sort(key=lambda r: (r.top(), r.left()))
    return rects[0].adjusted(-8, -8, 8, 8)


def build_steps(window) -> List[Step]:
    """按当前桌面实际内容生成步骤（不可用的目标自动跳过）。

    固定四步（欢迎 / 图标 / 文件夹 / 收尾）保证指引永远成立；
    分页、Dock、小组件三步只在对应元素真的存在时出现。
    """
    steps = [
        Step("welcome", i18n.T("onboarding.welcome.title"),
             i18n.T("onboarding.welcome.body")),
        Step("icons", i18n.T("onboarding.icons.title"),
             i18n.T("onboarding.icons.body"), _icon_hole(window, 4)),
        Step("folder", i18n.T("onboarding.folder.title"),
             i18n.T("onboarding.folder.body"), _icon_hole(window, 2)),
    ]
    dots = _dots_hole(window)
    if not dots.isNull():
        steps.append(Step("pages", i18n.T("onboarding.pages.title"),
                          i18n.T("onboarding.pages.body"), dots))
    dock = _dock_hole(window)
    if not dock.isNull():
        steps.append(Step("dock", i18n.T("onboarding.dock.title"),
                          i18n.T("onboarding.dock.body"), dock))
    widget = _widget_hole(window)
    if not widget.isNull():
        steps.append(Step("widgets", i18n.T("onboarding.widgets.title"),
                          i18n.T("onboarding.widgets.body"), widget))
    steps.append(Step("settings", i18n.T("onboarding.settings.title"),
                      i18n.T("onboarding.settings.body")))
    return steps


# ---------------------------------------------------------------- 纯函数
def place_card(card: QSizeF, hole: QRectF, bounds: QRect, margin: int = MARGIN) -> QPoint:
    """卡片左上角：优先高亮块下方，其次上方、右侧、左侧，最后夹进边界。

    判据是"与高亮块零相交"——卡片压在讲解对象上，聚光灯就白打了。
    四个方向都放不下时（目标几乎占满屏幕）选相交面积最小的那个。
    """
    w, h = int(card.width()), int(card.height())
    if hole.isNull() or hole.width() < 2 or hole.height() < 2:
        return QPoint(int(bounds.center().x() - w // 2),
                      int(bounds.center().y() - h // 2))

    cx = hole.center().x() - w / 2.0
    cy = hole.center().y() - h / 2.0
    cands = [
        QPointF(cx, hole.bottom() + margin),      # 下
        QPointF(cx, hole.top() - margin - h),     # 上
        QPointF(hole.right() + margin, cy),       # 右
        QPointF(hole.left() - margin - w, cy),    # 左
    ]
    best, best_overlap = None, None
    for c in cands:
        x = min(max(c.x(), bounds.left()), max(bounds.left(), bounds.right() - w + 1))
        y = min(max(c.y(), bounds.top()), max(bounds.top(), bounds.bottom() - h + 1))
        r = QRectF(x, y, w, h)
        overlap = r.intersected(hole)
        area = overlap.width() * overlap.height() if overlap.isValid() else 0.0
        if area <= 0.01:
            return QPoint(int(round(x)), int(round(y)))
        if best is None or area < best_overlap:
            best, best_overlap = QPoint(int(round(x)), int(round(y))), area
    return best if best is not None else QPoint(int(bounds.center().x() - w // 2),
                                                int(bounds.center().y() - h // 2))


def should_show(storage) -> bool:
    """首次安装 / 指引升级后为 True。"""
    try:
        done = int(storage.get_setting("onboarding_version") or 0)
    except (TypeError, ValueError, AttributeError):
        done = 0
    return done < ONBOARDING_VERSION


def mark_done(storage) -> None:
    storage.set_setting("onboarding_version", ONBOARDING_VERSION)


# ---------------------------------------------------------------- 卡片
class _StepDots(QWidget):
    """进度点：已看过的实心，当前的是强调色长条。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._n = 0
        self._i = 0
        self.setFixedHeight(8)

    def set_state(self, index: int, total: int):
        self._i, self._n = int(index), int(total)
        self.setFixedWidth(max(1, total) * 12)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        for i in range(self._n):
            x = i * 12 + 4
            if i == self._i:
                p.setBrush(theme.ACCENT)
                p.drawRoundedRect(QRectF(x - 2, 1, 8, 6), 3, 3)
            else:
                p.setBrush(QColor(theme.TEXT_DIM.red(), theme.TEXT_DIM.green(),
                                  theme.TEXT_DIM.blue(), 110))
                p.drawEllipse(QPointF(x + 1, 4), 2.4, 2.4)
        p.end()


class GuideCard(QWidget):
    """讲解卡片（自绘玻璃底 + 标题/正文/按钮）。

    文字用 QLabel 而不是自绘：换行、省略、屏幕阅读器都由 Qt 负责，
    自绘文本在 125%/150% 缩放下几乎必然出现截断（这个项目踩过）。
    """

    PRIMARY_QSS = (
        "QPushButton{background: rgb(76,194,255); color: rgb(12,24,32);"
        " border: none; border-radius: 8px; padding: 7px 18px;"
        " font-family: \"Microsoft YaHei UI\", \"Segoe UI\"; font-size: 13px;"
        " font-weight: 600;}"
        "QPushButton:hover{background: rgb(120,210,255);}"
        "QPushButton:pressed{background: rgb(56,168,226);}"
    )
    LINK_QSS = (
        "QPushButton{background: transparent; color: rgba(168,173,181,255);"
        " border: none; padding: 4px 6px; font-family: \"Microsoft YaHei UI\","
        " \"Segoe UI\"; font-size: 12px;}"
        "QPushButton:hover{color: rgb(242,243,245);}"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(CARD_W)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.lbl_step = QLabel(self)
        self.lbl_step.setFont(theme.ui_font(11))
        self.lbl_step.setStyleSheet("color: rgba(140,146,155,255);")
        head.addWidget(self.lbl_step)
        head.addStretch(1)
        self.btn_skip = QPushButton(i18n.T("onboarding.skip"), self)
        self.btn_skip.setStyleSheet(self.LINK_QSS)
        self.btn_skip.setCursor(Qt.PointingHandCursor)
        self.btn_skip.setFlat(True)
        head.addWidget(self.btn_skip)
        lay.addLayout(head)

        self.lbl_title = QLabel(self)
        self.lbl_title.setFont(theme.ui_font(18, bold=True))
        self.lbl_title.setStyleSheet("color: rgb(242,243,245);")
        self.lbl_title.setWordWrap(True)
        lay.addWidget(self.lbl_title)

        self.lbl_body = QLabel(self)
        self.lbl_body.setFont(theme.ui_font(13))
        self.lbl_body.setStyleSheet("color: rgba(178,184,193,255);")
        self.lbl_body.setWordWrap(True)
        self.lbl_body.setFixedWidth(CARD_W - 48)
        self.lbl_body.setTextFormat(Qt.PlainText)
        self.lbl_body.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        lay.addWidget(self.lbl_body)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.dots = _StepDots(self)
        foot.addWidget(self.dots)
        foot.addStretch(1)
        self.btn_prev = QPushButton(i18n.T("onboarding.prev"), self)
        self.btn_prev.setStyleSheet(theme.BUTTON_QSS)
        self.btn_prev.setCursor(Qt.PointingHandCursor)
        foot.addWidget(self.btn_prev)
        self.btn_next = QPushButton(i18n.T("onboarding.next"), self)
        self.btn_next.setStyleSheet(self.PRIMARY_QSS)
        self.btn_next.setCursor(Qt.PointingHandCursor)
        foot.addWidget(self.btn_next)
        lay.addLayout(foot)

        self.btn_next.setDefault(True)

    def configure(self, step: Step, index: int, total: int, last: bool) -> None:
        self.lbl_step.setText(i18n.T("onboarding.progress", now=index + 1,
                                     total=total))
        self.lbl_title.setText(step.title)
        self.lbl_body.setText(step.body)
        # QLabel 的换行高度必须显式算：只管 width 的布局会把它压成一行
        h = self.lbl_body.heightForWidth(CARD_W - 48)
        self.lbl_body.setMinimumHeight(max(20, h))
        self.dots.set_state(index, total)
        self.btn_prev.setVisible(index > 0)
        self.btn_next.setText(i18n.T("onboarding.finish") if last
                              else i18n.T("onboarding.next"))
        self.layout().activate()
        self.adjustSize()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.BORDER_STRONG, 1))
        p.setBrush(theme.SURFACE_POPUP)
        p.drawRoundedRect(r, CARD_RADIUS, CARD_RADIUS)
        # 顶部一层受光（与文件夹瓷砖 / 玻璃语言一致）
        grad = QColor(255, 255, 255, 16)
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(r.left(), r.top(), r.width(), 42),
                          CARD_RADIUS, CARD_RADIUS)
        p.end()


# ---------------------------------------------------------------- 覆盖层
class GuideOverlay(QWidget):
    """全屏遮罩 + 聚光灯 + 卡片。`finished(skipped)` 表示用户看完 / 跳过。"""

    finished = Signal(bool)

    def __init__(self, window, storage=None, layer=None, dock=None,
                 replay: bool = False):
        super().__init__(None)
        self._window = window
        self._storage = (storage if storage is not None
                         else getattr(window, "storage", None))
        # replay=True 只表示"用户主动重看"，结束时不改版本号语义（mark_done
        # 幂等）；留着这个标记是为了排查"为什么突然弹了"时有据可查。
        self._replay = bool(replay)
        self._steps = build_steps(window) if window is not None else []
        self._index = 0
        self._done = False
        self._hole = QRectF()
        self._from_hole = QRectF()
        self._to_hole = QRectF()
        self._t = 1.0
        self._pulse = 0.0
        self._anim = None
        self._pulse_anim = None

        # 置顶：Dock / 小组件都是桌面带里的分层窗，普通窗口虽然也在它们
        # 之上，但桌面挂载失败会走"悬浮置顶"兜底（见 _enter_floating_mode），
        # 那时不带置顶的遮罩会被桌面窗口盖住。指引只出现一次，宁可压在所有
        # 窗口之上（有醒目的「跳过」），也不要出现"遮罩被挡住"的灵异现象。
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool
                            | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.ArrowCursor)
        self.setAccessibleName(i18n.T("onboarding.a11y"))

        self._card = GuideCard(self)
        self._card.btn_next.clicked.connect(self.next_step)
        self._card.btn_prev.clicked.connect(self.prev_step)
        self._card.btn_skip.clicked.connect(self.skip)

        self._anim = QPropertyAnimation(self, b"guide_t", self)
        self._anim.setEasingCurve(effects.spring_curve(1.0, STEP_MS))
        self._anim.finished.connect(self._on_anim_done)
        if not effects.reduced_motion():
            self._pulse_anim = QPropertyAnimation(self, b"guide_pulse", self)
            self._pulse_anim.setStartValue(0.0)
            self._pulse_anim.setEndValue(1.0)
            self._pulse_anim.setDuration(1800)
            self._pulse_anim.setEasingCurve(QEasingCurve.InOutSine)
            self._pulse_anim.setLoopCount(-1)
            self._pulse_anim.start()

    # ---------- 可动画属性 ----------
    def _get_t(self) -> float:
        return self._t

    def _set_t(self, v: float):
        self._t = float(v)
        self._hole = _lerp_rect(self._from_hole, self._to_hole, self._t)
        self.update()

    guide_t = Property(float, _get_t, _set_t)

    def _get_pulse(self) -> float:
        return self._pulse

    def _set_pulse(self, v: float):
        self._pulse = float(v)
        if not self._hole.isEmpty():
            self.update()

    guide_pulse = Property(float, _get_pulse, _set_pulse)

    # ---------- 生命周期 ----------
    def steps(self) -> List[Step]:
        return list(self._steps)

    def current_index(self) -> int:
        return self._index

    def show_guide(self):
        if not self._steps:
            # 没有任何步骤时绝不 show：会留下一张吞掉全部鼠标的黑幕
            self.deleteLater()
            return
        screen = QGuiApplication.primaryScreen()
        geo = screen.geometry() if screen is not None else QRect(0, 0, 1920, 1080)
        self.setGeometry(geo)
        self._apply_step(0, animate=False)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.OtherFocusReason)

    def next_step(self):
        if self._index + 1 >= len(self._steps):
            self.finish(False)
            return
        self._apply_step(self._index + 1)

    def prev_step(self):
        if self._index <= 0:
            return
        self._apply_step(self._index - 1)

    def finish(self, skipped: bool):
        """结束（看完 / 跳过都算"已看过"，以后不再自动弹）。"""
        if self._done:
            return
        self._done = True
        for a in (self._anim, self._pulse_anim):
            if a is not None:
                try:
                    a.stop()
                except RuntimeError:
                    pass
        global _active
        if self._storage is not None:
            try:
                mark_done(self._storage)
            except Exception:      # noqa: BLE001 —— 落盘失败不该卡住关闭
                pass
        # 直接 hide：淡出动画被打断就留一层看不见却吞点击的壳，这个项目
        # 已经为同一类 bug 付过一次代价（v10 反馈 28 的"透明命中壳"）。
        self.hide()
        self.finished.emit(bool(skipped))
        if _active is self:
            _active = None
        self.deleteLater()

    def skip(self):
        self.finish(True)

    # ---------- 步骤切换 ----------
    def _bounds(self) -> QRect:
        """卡片可落区域（局部坐标，扣掉任务栏）。"""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return self.rect().adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
        avail = screen.availableGeometry()
        tl = self.mapFromGlobal(avail.topLeft())
        return QRect(tl, avail.size()).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)

    def _apply_step(self, index: int, animate: bool = True):
        if not self._steps:
            return
        index = max(0, min(len(self._steps) - 1, int(index)))
        self._index = index
        step = self._steps[index]
        last = index == len(self._steps) - 1
        self._card.configure(step, index, len(self._steps), last)

        hole = QRectF()
        if not step.hole.isNull():
            # 目标可能部分在屏幕外（Dock 贴边、组件跨屏、多显示器拔线后
            # 的残留几何）。不裁剪的话聚光灯会画到画布外，卡片也会被"看不见
            # 的洞"顶到边角上。
            local = QRect(self.mapFromGlobal(step.hole.topLeft()),
                          step.hole.size()).intersected(self.rect())
            if local.width() > 4 and local.height() > 4:
                hole = QRectF(local)
        # 目标为空时收成一个点（"虹膜闭合"），别把洞缩向屏幕左上角
        target = hole if not hole.isEmpty() else QRectF(
            self._hole.center() if not self._hole.isEmpty() else
            QRectF(self.rect()).center(), QSizeF(0, 0))
        card_pos = place_card(QSizeF(self._card.size()), hole, self._bounds())

        self._from_hole = QRectF(self._hole)
        self._to_hole = QRectF(target)
        self._card.move(card_pos)
        self._anim.stop()
        if animate and not effects.reduced_motion() and self.isVisible():
            # 起止值必须显式给：QPropertyAnimation 不设 end 值时"从当前值到
            # 当前值"，动画等于没跑（这个坑在 Switch 上已经踩过一次）。
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.setDuration(STEP_MS)
            self._set_t(0.0)
            self._anim.start()
        else:
            self._set_t(1.0)
        self.update()

    def _on_anim_done(self):
        if not self._to_hole.isEmpty():
            self._hole = QRectF(self._to_hole)
        self.update()

    # ---------- 绘制 ----------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dim = QColor(6, 8, 12, 170)
        hole = self._hole
        has_hole = hole.isValid() and hole.width() > 2 and hole.height() > 2
        if has_hole:
            path = QPainterPath()
            path.setFillRule(Qt.OddEvenFill)
            path.addRect(QRectF(self.rect()))
            path.addRoundedRect(hole, HOLE_RADIUS, HOLE_RADIUS)
            p.fillPath(path, dim)
            # 洞里补一层 alpha=2 的近透明底。
            # 分层窗口（WA_TranslucentBackground -> WS_EX_LAYERED）的命中
            # 测试按像素 alpha 走：alpha 完全为 0 的区域**点击会穿透到桌面**
            # ——指引期间点高亮区会直接把图标拖走 / 启动应用。alpha 2 肉眼看
            # 不出来，但足以让这一块重新接收鼠标（与组件领地同一套做法，
            # 见 widget_base 的 alpha=2 注释）。必须在描边之前铺：后铺会把
            # 强调色描边的内侧 1px 盖掉。
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 2))
            p.drawRoundedRect(hole, HOLE_RADIUS, HOLE_RADIUS)
            # 聚光灯：三层外发光 + 一圈强调色描边（呼吸感由 _pulse 驱动）
            base = 150 + int(70 * self._pulse)
            for grow, alpha, width in ((14, 12, 6), (8, 22, 4), (3, 40, 2)):
                p.setPen(QPen(QColor(theme.ACCENT.red(), theme.ACCENT.green(),
                                     theme.ACCENT.blue(), alpha), width))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(hole.adjusted(-grow, -grow, grow, grow),
                                  HOLE_RADIUS + grow, HOLE_RADIUS + grow)
            p.setPen(QPen(QColor(theme.ACCENT.red(), theme.ACCENT.green(),
                                 theme.ACCENT.blue(), min(255, base)), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(hole, HOLE_RADIUS, HOLE_RADIUS)
        else:
            p.fillRect(self.rect(), dim)

        # 卡片投影（画在父层：子控件随后绘制，阴影只在卡片外沿可见）
        if self._card is not None and self._card.isVisible():
            r = QRectF(self._card.geometry())
            p.setPen(Qt.NoPen)
            for i in range(12, 0, -2):
                p.setBrush(QColor(0, 0, 0, 6))
                p.drawRoundedRect(r.adjusted(-i, -i + 4, i, i + 4),
                                  CARD_RADIUS + i, CARD_RADIUS + i)
        p.end()

    # ---------- 输入 ----------
    def mousePressEvent(self, e):
        # 左键"点一下继续"；右键不动（防止手滑连点直接跳过整段）
        if e.button() == Qt.LeftButton:
            self.next_step()
        e.accept()

    def keyPressEvent(self, e):
        key = e.key()
        if key == Qt.Key_Escape:
            self.skip()
        elif key in (Qt.Key_Right, Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.next_step()
        elif key == Qt.Key_Left:
            self.prev_step()
        else:
            super().keyPressEvent(e)
        e.accept()

    def closeEvent(self, e):
        # 被外部关掉（窗口销毁 / 显示器拔掉）也要落"已看过"，否则下次启动再弹
        if not self._done:
            self._done = True
            global _active
            if self._storage is not None:
                try:
                    mark_done(self._storage)
                except Exception:      # noqa: BLE001
                    pass
            if _active is self:
                _active = None
            self.finished.emit(True)
        super().closeEvent(e)


def _lerp_rect(a: QRectF, b: QRectF, t: float) -> QRectF:
    """两个矩形之间的线性插值（t 已含弹簧缓动）。"""
    return QRectF(a.x() + (b.x() - a.x()) * t,
                  a.y() + (b.y() - a.y()) * t,
                  a.width() + (b.width() - a.width()) * t,
                  a.height() + (b.height() - a.height()) * t)


# ---------------------------------------------------------------- 对外入口
def show_guide(window, storage=None, layer=None, dock=None,
               replay: bool = False) -> Optional[GuideOverlay]:
    """创建并显示指引；已有指引在显示时先关掉旧的（避免叠两层遮罩）。"""
    global _active
    if _active is not None:
        try:
            _active.skip()
        except RuntimeError:
            pass
        _active = None
    if window is None:
        return None
    try:
        ov = GuideOverlay(window, storage, layer, dock, replay=replay)
    except Exception:      # noqa: BLE001 —— 指引是锦上添花，绝不能拖垮启动
        import traceback
        traceback.print_exc()
        return None
    _active = ov
    ov.show_guide()
    return ov


def active() -> Optional["GuideOverlay"]:
    """当前指引（测试用；无则 None）。"""
    return _active


def dismiss():
    """外部关闭（测试 / 托盘退出前）。"""
    global _active
    if _active is not None:
        try:
            _active.skip()
        except RuntimeError:
            pass
    _active = None


def missing_i18n_keys() -> List[str]:
    """返回 on onboarding.* 在两份词表里缺失的 key（自检 / 测试用）。"""
    keys = ["onboarding.progress", "onboarding.next", "onboarding.prev",
            "onboarding.finish", "onboarding.skip", "onboarding.a11y"]
    for key in STEP_KEYS:
        keys += ["onboarding.%s.title" % key, "onboarding.%s.body" % key]
    out = []
    for key in keys:
        if not i18n._table(i18n.ZH).get(key) or not i18n._table(i18n.EN).get(key):
            out.append(key)
    return out
