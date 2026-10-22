# -*- coding: utf-8 -*-
"""音乐控制器组件（v10 C2，反馈 9）。

三层分离（规格 §2.2）：
    MediaInfo（`media_session.py`） → 纯数据快照
    layout(rect, info)             → 封面/文字/进度条/三键的位置（纯算术，可单测）
    draw(painter, rect, info)      → 纯绘制（可画到 QImage 上验像素）
    MusicWidget(GlassWidget)       → 只管定时器 + 点击命中 + 把三者接起来

**它不是播放器**：控制的是本机正在放的应用（媒体键），数据源见
`media_session` 模块头部——本轮是降级档（演示态 + 真媒体键），
`MediaInfo.demo=True` 时界面必须明示「未检测到播放器信息」。

按钮图形走 `QPainterPath` 自绘（三角/双竖条），不用字体图标：
⏮⏯⏭ 这类码位在 Windows 某些字体里会画成豆腐块，自绘零风险。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen

from ... import theme
from ...media_session import MediaInfo, MediaSessionSource, create_source
from ...widget_glass import PAD, GlassWidget
from ...widget_style import DEFAULT_STYLE, Style

TICK_MS = 500           # 进度条刷新（也驱动演示态的进度）
DIM_ALPHA = 150         # 封面底色 / 次文字的弱化程度
BAR_H = 4               # 进度条厚度
MARQUEE_PX_S = 18.0     # 长标题滚动速度（px/s）


# ---------------------------------------------------------------- 纯算术

def layout(rect, info: Optional[MediaInfo] = None) -> Dict:
    """算出封面/文本/进度条/三个按键的位置。任意 rect 都不许抛。

    横向两栏：左侧方形封面，右侧曲名 + 艺人；下面一条进度条，再下面三个按键。
    所有尺寸按容器高度比例派生——(3,2) 与 (4,2) 都能用。
    """
    rect = QRectF(rect)
    w = max(1.0, rect.width())
    h = max(1.0, rect.height())
    pad = min(PAD, max(6.0, h * 0.12))
    inner = rect.adjusted(pad, pad, -pad, -pad)

    cover_side = max(20.0, min(inner.height() * 0.54, inner.width() * 0.30))
    cover = QRectF(inner.left(), inner.top(), cover_side, cover_side)

    gap = max(6.0, inner.width() * 0.04)
    text_x = cover.right() + gap
    text_w = max(20.0, inner.right() - text_x)
    fs_title = max(9, int(round(min(cover_side * 0.28, 20))))
    fs_artist = max(8, int(round(fs_title * 0.82)))
    fm_t = QFontMetricsF(theme.ui_font(fs_title, bold=True))
    fm_a = QFontMetricsF(theme.ui_font(fs_artist))
    # 文字块相对封面**垂直居中**：顶部对齐会让右侧文字贴着卡片上沿、
    # 中间留一大片空白（第一版就是这么丑的）。
    text_h = fm_t.height() + 2.0 + fm_a.height()
    text_top = cover.center().y() - text_h / 2.0
    title_rect = QRectF(text_x, text_top, text_w, fm_t.height())
    artist_rect = QRectF(text_x, title_rect.bottom() + 2, text_w, fm_a.height())

    btn_r = max(8.0, min(inner.width() * 0.055, 15.0))
    font_time = theme.ui_font(max(8, int(round(fs_artist * 0.92))))
    # "剩余时间 / 降级角标"那一行：高度取字高，行高写死 14 会把字的顶部切掉
    # （字号 12 的行高就有 17 了），所以行矩形也由 layout 交付，draw 只消费。
    row_h = max(14.0, QFontMetricsF(font_time).height())
    # 竖直预算：文字块 → 间距 → 进度条 → 5px → 时间行 → 按键行 → 底边
    reserve = row_h + 5.0 + 2.0 * 2.0 + 2.0 * btn_r + 4.0
    text_bottom = max(cover.bottom(), artist_rect.bottom())
    bar_y = text_bottom + max(4.0, inner.height() * 0.10)
    bottom_limit = inner.bottom() - BAR_H - 1.0
    if inner.height() > reserve + BAR_H + 8.0:      # 空间够才给按键行留位置
        bottom_limit = min(bottom_limit, inner.bottom() - reserve - BAR_H)
    bar_y = max(inner.top(), min(bar_y, bottom_limit))
    bar = QRectF(inner.left(), bar_y, inner.width(), BAR_H)
    row = QRectF(inner.left(), bar.bottom() + 5.0, inner.width(), row_h)

    # 按键在"时间行之下、底边之上"这段里居中：上下留白对称，不压文字
    avail_top = row.bottom() + 2.0
    avail_bot = inner.bottom() - 1.0
    btn_cy = min(avail_bot - btn_r,
                 max(avail_top + btn_r, (avail_top + avail_bot) / 2.0))
    step = btn_r * 2.9
    cx = inner.center().x()
    buttons = [QRectF(cx + step * i - btn_r, btn_cy - btn_r, btn_r * 2, btn_r * 2)
               for i in (-1, 0, 1)]
    return {
        "inner": inner, "cover": cover, "title_rect": title_rect,
        "artist_rect": artist_rect, "bar": bar, "row": row, "buttons": buttons,
        "font_title": theme.ui_font(fs_title, bold=True),
        "font_artist": theme.ui_font(fs_artist),
        "font_time": font_time,
        "btn_r": btn_r,
    }


def marquee_offset(text: str, font: QFont, box_w: float, scroll: float) -> float:
    """长标题的横向偏移（px）。

    放得下 → 0（不滚）；放不下 → 在 [0, overflow] 之间来回（整段滚完停 0.8s
    再回来，避免"跳变复位"）。`scroll` 是持续推进的秒数。
    """
    if not text or box_w <= 0:
        return 0.0
    fm = QFontMetricsF(font)
    overflow = fm.horizontalAdvance(text) - box_w
    if overflow <= 0:
        return 0.0
    cycle = max(0.1, overflow / MARQUEE_PX_S + 0.8)
    t = float(scroll) % (cycle * 2.0)
    if t <= cycle - 0.8:
        return min(overflow, t * MARQUEE_PX_S)
    if t <= cycle:
        return overflow                      # 停住看一眼
    back = t - cycle
    return max(0.0, overflow - back * MARQUEE_PX_S)


# ---------------------------------------------------------------- 纯绘制

def _round_bar(p: QPainter, box: QRectF, frac: float, style: Style) -> None:
    r = box.height() / 2.0
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 34))
    p.drawRoundedRect(box, r, r)
    frac = max(0.0, min(1.0, float(frac)))
    if frac <= 0:
        return
    w = max(box.height(), box.width() * frac)
    p.setBrush(QColor(style.accent))
    p.drawRoundedRect(QRectF(box.left(), box.top(), w, box.height()), r, r)


def _note_glyph(p: QPainter, box: QRectF, color: QColor) -> None:
    """封面的音符占位：一个符头 + 符干 + 符尾（自绘，不依赖字体码位）。"""
    r = min(box.width(), box.height())
    head = r * 0.16
    cx = box.center().x() - r * 0.04
    cy = box.center().y() + r * 0.14
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawEllipse(QPointF(cx, cy), head, head * 0.82)
    pen = QPen(color, max(1.6, r * 0.055))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(cx + head * 0.92, cy - head * 0.2),
               QPointF(cx + head * 0.92, cy - r * 0.30))
    p.drawLine(QPointF(cx + head * 0.92, cy - r * 0.30),
               QPointF(cx + head * 2.4, cy - r * 0.20))


def _button_icon(p: QPainter, box: QRectF, kind: str, color: QColor,
                 playing: bool) -> None:
    """三个按键的图形：prev / play-pause / next。"""
    r = min(box.width(), box.height()) * 0.5
    cx, cy = box.center().x(), box.center().y()
    s = r * 0.62
    p.setPen(Qt.NoPen)
    p.setBrush(color)

    def tri(direction: int):
        path = QPainterPath()
        path.moveTo(QPointF(cx - s * 0.52 * direction, cy - s))
        path.lineTo(QPointF(cx + s * 0.62 * direction, cy))
        path.lineTo(QPointF(cx - s * 0.52 * direction, cy + s))
        path.closeSubpath()
        p.drawPath(path)

    if kind == "prev":
        tri(-1)
        p.drawRect(QRectF(cx - s * 0.86, cy - s, max(1.6, s * 0.24), s * 2))
    elif kind == "next":
        tri(1)
        p.drawRect(QRectF(cx + s * 0.62, cy - s, max(1.6, s * 0.24), s * 2))
    elif playing:
        # 暂停：两根竖条
        p.drawRect(QRectF(cx - s * 0.62, cy - s, s * 0.46, s * 2))
        p.drawRect(QRectF(cx + s * 0.16, cy - s, s * 0.46, s * 2))
    else:
        tri(1)


def draw(p: QPainter, rect, info: Optional[MediaInfo] = None,
         style: Optional[Style] = None, scroll: float = 0.0) -> None:
    """画媒体卡内容（不含玻璃底：底色由 `GlassWidget` 负责）。"""
    info = info or MediaInfo()
    st = style or DEFAULT_STYLE
    rect = QRectF(rect)
    if rect.width() <= 8 or rect.height() <= 8:
        return
    L = layout(rect, info)
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)

    # 封面：圆角底 + 音符占位（真封面要 SMTC 缩略图流，本轮见 media_session）
    cover = L["cover"]
    cr = max(6.0, cover.width() * 0.18)
    p.setPen(Qt.NoPen)
    base = QColor(st.accent)
    base.setAlpha(DIM_ALPHA if not info.demo else 90)
    p.setBrush(base)
    p.drawRoundedRect(cover, cr, cr)
    _note_glyph(p, cover, QColor(255, 255, 255, 210))

    # 曲名（长标题滚动）+ 艺人
    title = info.title or "没有在播放"
    p.setFont(L["font_title"])
    p.setPen(QColor(st.text))
    tr = L["title_rect"]
    p.setClipRect(tr)
    off = marquee_offset(title, L["font_title"], tr.width(), scroll)
    p.drawText(QRectF(tr.left() - off, tr.top(), tr.width() + off, tr.height()),
               Qt.AlignLeft | Qt.AlignVCenter, title)
    p.setClipping(False)

    p.setFont(L["font_artist"])
    p.setPen(QColor(st.dim))
    ar = L["artist_rect"]
    fm = QFontMetricsF(L["font_artist"])
    p.drawText(ar, Qt.AlignLeft | Qt.AlignVCenter,
               fm.elidedText(info.artist or "—", Qt.ElideRight, ar.width()))

    # 三键：中间那颗是实心强调色（主操作），两侧只有图标
    for box, kind in zip(L["buttons"], ("prev", "play", "next")):
        if kind == "play":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(st.accent))
            p.drawEllipse(box)
            _button_icon(p, box, kind, QColor(255, 255, 255, 240), info.playing)
        else:
            _button_icon(p, box, kind, QColor(st.dim), info.playing)

    # 进度条 + 剩余时间（右下）+ 降级角标（左下，同一行）
    _round_bar(p, L["bar"], info.progress(), st)
    row = L["row"]
    p.setFont(L["font_time"])
    rem = info.remains()
    if rem:
        p.setPen(QColor(st.dim))
        p.drawText(row, Qt.AlignRight | Qt.AlignVCenter, rem)
    # 没拿到真实会话时必须说清楚（否则用户以为"显示错了"）。放左下角而不是
    # 卡片顶部：顶部是封面/曲名的领地，挤进去会把封面上沿顶到圆角外面。
    if info.demo:
        p.setPen(QColor(st.dim))
        p.drawText(row, Qt.AlignLeft | Qt.AlignVCenter, "未检测到播放器信息")
    p.restore()


# ---------------------------------------------------------------- 组件

class MusicWidget(GlassWidget):
    TYPE = "music"

    def __init__(self, storage, entry):
        # interactive=True：三个按键要收点击（拿键盘焦点是代价，可接受——
        # 焦点只在点它时落到本窗口，点桌面就回去了）。
        super().__init__(storage, entry, interactive=True)
        self.source: MediaSessionSource = create_source()
        self._info = self.source.snapshot()
        self._scroll = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---------- 节拍 ----------
    def _tick(self):
        adv = getattr(self.source, "advance", None)
        if callable(adv):
            adv(TICK_MS / 1000.0)
        info = self.source.snapshot()
        if info.title != self._info.title:
            self._scroll = 0.0          # 换歌：标题从头滚
        else:
            self._scroll += TICK_MS / 1000.0
        self._info = info
        self.update()

    # ---------- 交互 ----------
    def _button_at(self, pos) -> Optional[str]:
        L = layout(QRectF(self.rect()), self._info)
        for box, kind in zip(L["buttons"], ("prev", "play", "next")):
            # 命中区域放大到按钮框外扩 4px：小按钮上"差一点没点到"最恼人
            if box.adjusted(-4, -4, 4, 4).contains(QPointF(pos)):
                return kind
        return None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            kind = self._button_at(e.position())
            if kind == "prev":
                self.source.prev_track()
                self._after_control()
                return
            if kind == "play":
                self.source.play_pause()
                self._after_control()
                return
            if kind == "next":
                self.source.next_track()
                self._after_control()
                return
        super().mousePressEvent(e)

    def _after_control(self):
        """控制后立刻回读一次：演示态要马上反映"暂停了/换歌了"。"""
        self._info = self.source.snapshot()
        self._scroll = 0.0
        self.update()

    # ---------- 绘制 ----------
    def paint_content(self, p):
        draw(p, QRectF(self.rect()), self._info, self.style, self._scroll)

    def on_settings_changed(self):
        super().on_settings_changed()
        self.update()

    def closeEvent(self, e):
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.stop()
        super().closeEvent(e)
