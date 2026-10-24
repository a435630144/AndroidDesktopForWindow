# -*- coding: utf-8 -*-
"""音乐控制器组件（v10 C2 起，v11 接通真实媒体信息 + 可拖动进度条）。

三层分离（规格 §2.2）：
    MediaInfo（`media_session.py`） → 纯数据快照
    layout(rect, info)             → 封面/文字/进度条/三键的位置（纯算术，可单测）
    draw(painter, rect, info)      → 纯绘制（可画到 QImage 上验像素）
    MusicWidget(GlassWidget)       → 只管定时器 + 点击命中 + 把三者接起来

**它不是播放器**：控制的是本机正在放的应用（媒体键），数据源见
`media_session` 模块头部——SMTC 侧车（真实曲名/进度/可 seek）> 窗口标题
（只有曲名）> 演示态。三种档位都必须在界面上可区分：
  真会话      → 封面（播放器给了缩略图时）+ 正常曲名 + 进度 + 剩余时间
  仅标题档    → 曲名 + 「仅曲名 · 无进度」，**整条进度条都不画**（v11c）
  演示态      → 「未检测到播放器信息」

v11（反馈 30）追加：**进度条可拖**。按住进度条左右拖 = 预览位置，松手
才落 seek（拖动过程中不打断播放器）；拖动时右侧读数变成目标时间。

v11c（用户反馈）：① 有 SMTC 缩略图就画真封面（圆角裁切 + 缓存）；
② **拿不到时长就不画进度条**——空底轨既占地方又像"卡在 0"。

按钮图形走 `QPainterPath` 自绘（三角/双竖条），不用字体图标：
⏮⏯⏭ 这类码位在 Windows 某些字体里会画成豆腐块，自绘零风险。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Dict, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QPainter, QPainterPath,
                           QPen, QPixmap)

from ... import theme
from ...media_session import (MediaInfo, MediaSessionSource, create_source,
                              fmt_time)
from ...widget_glass import PAD, GlassWidget
from ...widget_style import DEFAULT_STYLE, Style

TICK_MS = 500           # 进度条刷新（真实会话靠 position_at 插值，不必更快）
DIM_ALPHA = 150         # 封面底色 / 次文字的弱化程度
BAR_H = 4               # 进度条厚度
BAR_HIT_PAD = 8         # 进度条命中区上下外扩（4px 的条太难抓）
MARQUEE_PX_S = 18.0     # 长标题滚动速度（px/s）
SEEK_HANDLE = 5.0       # 拖动时进度条上的圆点半径


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
    # v11c：拿不到时长（窗口标题档 / 播放器不报 timeline）就**不画进度条**，
    # 连它的位置也不留——留一条空底轨既占地方又像"卡住了"。
    # info=None 是"信息未知"的旧调用（布局单测），保持有进度条的旧行为。
    has_bar = info is None or info.duration > 0
    if has_bar:
        bar_y = text_bottom + max(4.0, inner.height() * 0.10)
        bottom_limit = inner.bottom() - BAR_H - 1.0
        if inner.height() > reserve + BAR_H + 8.0:  # 空间够才给按键行留位置
            bottom_limit = min(bottom_limit, inner.bottom() - reserve - BAR_H)
        bar_y = max(inner.top(), min(bar_y, bottom_limit))
        bar = QRectF(inner.left(), bar_y, inner.width(), BAR_H)
        row = QRectF(inner.left(), bar.bottom() + 5.0, inner.width(), row_h)
    else:
        bar = QRectF()
        row = QRectF(inner.left(), text_bottom + max(3.0, inner.height() * 0.05),
                     inner.width(), row_h)

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


def bar_hit_rect(bar) -> QRectF:
    """进度条命中区：上下各外扩 `BAR_HIT_PAD`（4px 的条抓不住）。

    进度条不存在时返回空矩形——否则 `QRectF()` 外扩后会在卡片左上角留下
    一个 4×16 的隐形热区，点封面就被当成"抓进度条"。
    """
    r = QRectF(bar)
    if r.isEmpty():
        return QRectF()
    return r.adjusted(-2, -BAR_HIT_PAD, 2, BAR_HIT_PAD)


def frac_at(bar, x: float) -> float:
    """横坐标 -> 进度 0..1（夹紧；宽度为 0 时回 0）。"""
    rect = QRectF(bar)
    if rect.width() <= 0:
        return 0.0
    return max(0.0, min(1.0, (float(x) - rect.left()) / rect.width()))


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

def _round_bar(p: QPainter, box: QRectF, frac: float, style: Style,
               dim: bool = False, handle: bool = False) -> None:
    r = box.height() / 2.0
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 22 if dim else 34))
    p.drawRoundedRect(box, r, r)
    frac = max(0.0, min(1.0, float(frac)))
    if frac <= 0:
        return
    w = max(box.height(), box.width() * frac)
    p.setBrush(QColor(style.accent))
    p.drawRoundedRect(QRectF(box.left(), box.top(), w, box.height()), r, r)
    if handle:
        # 拖动中：端点画一颗圆点（"你抓的就是这里"）
        p.setBrush(QColor(255, 255, 255, 240))
        p.drawEllipse(QPointF(box.left() + w, box.center().y()),
                      SEEK_HANDLE, SEEK_HANDLE)


_COVER_CACHE: Dict[str, QPixmap] = {}


def cover_pixmap(info: Optional[MediaInfo]) -> Optional[QPixmap]:
    """封面图（按 `cover_id` 缓存）；没有/读不到返回 None。

    读文件失败一律返回 None 而不是抛——封面只是装饰，不许拖垮 500ms 的
    重绘节拍。缓存上限 8 张：一个屏上不会有更多不同的歌。
    """
    path = str(getattr(info, "cover", "") or "") if info is not None else ""
    if not path:
        return None
    key = str(getattr(info, "cover_id", "") or "") or path
    cached = _COVER_CACHE.get(key)
    if cached is not None and not cached.isNull():
        return cached
    if not os.path.isfile(path):
        return None
    pm = QPixmap(path)
    if pm.isNull():
        return None
    if len(_COVER_CACHE) >= 8:
        _COVER_CACHE.clear()
    _COVER_CACHE[key] = pm
    return pm


def _draw_cover(p: QPainter, box: QRectF, radius: float, pm: QPixmap) -> None:
    """把封面按"填满 + 居中裁切"画进圆角方框（不变形、不露底色）。"""
    if pm.isNull() or box.width() <= 1 or box.height() <= 1:
        return
    side = min(pm.width(), pm.height())
    sx = (pm.width() - side) / 2.0
    sy = (pm.height() - side) / 2.0
    clip = QPainterPath()
    clip.addRoundedRect(box, radius, radius)
    p.save()
    p.setClipPath(clip)
    p.drawPixmap(box, pm, QRectF(sx, sy, side, side))
    p.restore()


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
         style: Optional[Style] = None, scroll: float = 0.0,
         now: Optional[float] = None, seek_frac: Optional[float] = None) -> None:
    """画媒体卡内容（不含玻璃底：底色由 `GlassWidget` 负责）。

    - `now`：当前位置的插值基准（`time.monotonic()`）；缺省不插值。
    - `seek_frac`：拖动进度条时的**预览**占比（None = 按真实播放位置画）。
    """
    info = info or MediaInfo()
    st = style or DEFAULT_STYLE
    rect = QRectF(rect)
    if rect.width() <= 8 or rect.height() <= 8:
        return
    L = layout(rect, info)
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)

    # 封面：真封面（SMTC 缩略图缓存）优先，否则强调色底 + 音符占位
    cover = L["cover"]
    cr = max(6.0, cover.width() * 0.18)
    pm = cover_pixmap(info)
    if pm is not None:
        _draw_cover(p, cover, cr, pm)
    else:
        p.setPen(Qt.NoPen)
        base = QColor(st.accent)
        base.setAlpha(DIM_ALPHA if not (info.demo or info.partial) else 90)
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
    artist = info.artist or "—"
    p.drawText(ar, Qt.AlignLeft | Qt.AlignVCenter,
               fm.elidedText(artist, Qt.ElideRight, ar.width()))

    # 三键：中间那颗是实心强调色（主操作），两侧只有图标
    for box, kind in zip(L["buttons"], ("prev", "play", "next")):
        if kind == "play":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(st.accent))
            p.drawEllipse(box)
            _button_icon(p, box, kind, QColor(255, 255, 255, 240), info.playing)
        else:
            _button_icon(p, box, kind, QColor(st.dim), info.playing)

    # 进度条 + 右下读数 + 左下状态角标（同一行）
    frac = info.progress(now)
    if seek_frac is not None:
        frac = max(0.0, min(1.0, float(seek_frac)))
    # v11c：没有时长就整条不画（用户要求）——空底轨会让人以为进度卡在 0
    if not L["bar"].isEmpty():
        _round_bar(p, L["bar"], frac, st, handle=seek_frac is not None)

    row = L["row"]
    p.setFont(L["font_time"])
    p.setPen(QColor(st.dim))
    if seek_frac is not None and info.duration > 0:
        p.drawText(row, Qt.AlignRight | Qt.AlignVCenter,
                   "%s / %s" % (fmt_time(seek_frac * info.duration),
                                fmt_time(info.duration)))
    elif seek_frac is not None:
        p.drawText(row, Qt.AlignRight | Qt.AlignVCenter, fmt_time(0))
    else:
        rem = info.remains(now)
        if rem:
            p.drawText(row, Qt.AlignRight | Qt.AlignVCenter, rem)
        elif info.duration > 0:
            p.drawText(row, Qt.AlignRight | Qt.AlignVCenter,
                       fmt_time(info.position_at(now)))
    # 没拿到真实会话时必须说清楚（否则用户以为"显示错了"）。放左下角而不是
    # 卡片顶部：顶部是封面/曲名的领地，挤进去会把封面上沿顶到圆角外面。
    hint = ""
    if info.demo:
        hint = "未检测到播放器信息"
    elif info.partial:
        hint = "仅曲名 · 无进度"
    if hint:
        p.setPen(QColor(st.dim))
        # 右侧时钟会占掉一段，左侧提示按剩余宽度省略——窄卡片上不许被硬裁
        fm_h = QFontMetricsF(L["font_time"])
        right_w = fm_h.horizontalAdvance(info.remains(now) or "0:00") + 6.0
        left_w = max(20.0, row.width() - right_w)
        p.drawText(QRectF(row.left(), row.top(), left_w, row.height()),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   fm_h.elidedText(hint, Qt.ElideRight, left_w))
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
        self._now = time.monotonic()
        self._scroll = 0.0
        self._seek_frac = None       # 拖动进度条时的预览占比（None = 没在拖）
        # 侧车启动推迟一点：组件构造发生在桌面启动 / 重排路径上，spawn
        # 子进程（哪怕只有 20ms）不该卡在首屏绘制里。
        # 用**挂在自身上的 QTimer**（不是 QTimer.singleShot）：组件在 1.2s
        # 内被重建时，父对象销毁会连定时器一起取消，不会回调到已析构的窗口。
        self._start_timer = QTimer(self)
        self._start_timer.setSingleShot(True)
        self._start_timer.timeout.connect(self._start_source)
        self._start_timer.start(1200)
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---------- 生命周期 ----------
    def _start_source(self):
        start = getattr(self.source, "start", None)
        if callable(start):
            try:
                start()
            except Exception:      # noqa: BLE001 —— 数据源起不来也不许崩组件
                pass

    def _stop_source(self):
        stop = getattr(self.source, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:      # noqa: BLE001
                pass

    def destroy_now(self):
        """销毁路径（重排/切模式）也要收子进程，否则会留下孤儿 PS。"""
        self._stop_source()
        super().destroy_now()

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
        self._now = time.monotonic()
        self.update()

    # ---------- 交互 ----------
    def _button_at(self, pos) -> Optional[str]:
        L = layout(QRectF(self.card_rect()), self._info)
        for box, kind in zip(L["buttons"], ("prev", "play", "next")):
            # 命中区域放大到按钮框外扩 4px：小按钮上"差一点没点到"最恼人
            if box.adjusted(-4, -4, 4, 4).contains(QPointF(pos)):
                return kind
        return None

    def _bar_at(self, pos) -> bool:
        L = layout(QRectF(self.card_rect()), self._info)
        hit = bar_hit_rect(L["bar"])
        return (not hit.isEmpty()) and hit.contains(QPointF(pos))

    def _seek_enabled(self) -> bool:
        return bool(self._info.duration > 0) and not self._info.partial

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
            if self._seek_enabled() and self._bar_at(e.position()):
                # 抓进度条：**不转交 super()**，否则会被当成拖动组件
                L = layout(QRectF(self.card_rect()), self._info)
                self._seek_frac = frac_at(L["bar"], e.position().x())
                self.update()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._seek_frac is not None:
            L = layout(QRectF(self.card_rect()), self._info)
            self._seek_frac = frac_at(L["bar"], e.position().x())
            self.update()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._seek_frac is not None and e.button() == Qt.LeftButton:
            frac = self._seek_frac
            self._seek_frac = None
            if self._seek_enabled():
                self.source.seek(frac * self._info.duration)
                self._after_control()
            self.update()
            return
        super().mouseReleaseEvent(e)

    def _after_control(self):
        """控制后立刻回读一次：演示态要马上反映"暂停了/换歌了"。"""
        self._info = self.source.snapshot()
        self._now = time.monotonic()
        self._scroll = 0.0
        self.update()

    # ---------- 绘制 ----------
    def paint_content(self, p):
        draw(p, QRectF(self.card_rect()), self._info, self.style, self._scroll,
             now=self._now, seek_frac=self._seek_frac)

    def on_settings_changed(self):
        super().on_settings_changed()
        self.update()

    def closeEvent(self, e):
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.stop()
        self._stop_source()
        super().closeEvent(e)
