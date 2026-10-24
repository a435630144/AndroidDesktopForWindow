# -*- coding: utf-8 -*-
"""液态玻璃光学叠加层（v14 反馈 9）。

设计来源（公开实现调研，2026-10）：
  - CSS/SVG 生态（feTurbulence + feDisplacementMap + 分层 backdrop-filter）
    把液态玻璃拆成五层光学：①半透明底 + 模糊 ②折射位移 ③色散边缘
    ④镜面高光（fresnel 边光 + 顶部亮线）⑤流动微动效。
  - Apple Liquid Glass（WWDC 2025）：高光是"边缘随法线角变化的 rim
    light"，色散在玻璃边界产生 RGB 镶边，表面会缓慢流动。

Qt 没有 per-pixel shader（也不该为常驻组件每帧抓屏模糊——v8 C2 的结论），
所以本模块只做**叠加层**：三个表面（文件夹弹窗 / Dock 栏 / 小组件背景）
各自画好自己的底色之后，调用 `paint_overlay()` 把液态光学叠上去：

  1. 透镜边（bezel）：贴边的渐隐亮带，模拟玻璃厚度的 fresnel 反光，
     光从左上来——顶边最亮、左边次之、底/右渐暗；
  2. 色散（dispersion）：贴边框内侧的四条 1px 细线，顶冷蓝 / 左青 /
     右紫 / 底暖粉——玻璃边界把光拆成彩色镶边；
  3. 颗粒（noise）：预生成一张确定性噪声纹理（feTurbulence 的静态近似），
     低透明度平铺——去掉"塑料感"，让表面有材质；
  4. 扫光（shimmer）：一道柔和高光带缓慢横扫（周期 SHIMMER_PERIOD 秒），
     由模块内共享的低频 ticker 驱动；系统关动画时整条不画
     （`effects.reduced_motion()` 与全项目动效同一把闸）。

单一真相源：参数只从 storage 的 `liquid_*` 键读（`liquid_style()`），
三个表面共用一份；每个表面一个开关（`surface_enabled()`），总开关
`liquid_glass` 一票否决。设置面板只写键，绘制层只认 `paint_overlay`
的返回值——与 `label_style.py` 同一分层范式。
"""
from __future__ import annotations

import random
import time
import weakref
from dataclasses import dataclass
from typing import Dict, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)

from . import effects
from . import theme

# ---------------------------------------------------------------- 常量

SURFACES = ("folder", "dock", "widget")     # 三个可挂表面

SHIMMER_PERIOD = 6.5      # 秒：一道高光扫过一遍（公开 demo 常用 5~8s）
TICK_MS = 110             # 扫光驱动帧间隔（~9fps：慢动效不需要 60fps）
BEZEL_W = 7.0             # 透镜边带宽（逻辑 px，随矩形短边缩放）
DISPERSION_INSET = 2.0    # 色散线距边框内侧的距离
NOISE_TILE = 96           # 噪声纹理边长（feTurbulence 的静态近似）
NOISE_SEED = 20251024     # 固定种子：同一台机器每次看到的颗粒一致

# 色散四边色调（公开实现的蓝/紫/粉/青语言，alpha 很低只是"镶边"）
_DISPERSION_TOP = QColor(110, 160, 255)     # 顶：冷蓝
_DISPERSION_LEFT = QColor(120, 220, 255)    # 左：青
_DISPERSION_RIGHT = QColor(150, 120, 255)   # 右：紫
_DISPERSION_BOTTOM = QColor(255, 140, 170)  # 底：暖粉

_DEFAULTS = {"dispersion": 60, "bezel": 60, "noise": 40, "shimmer": True}


@dataclass(frozen=True)
class LiquidStyle:
    """一次绘制需要的全部液态参数（0~1 强度，不可变可缓存）。"""

    dispersion: float = 0.6
    bezel: float = 0.6
    noise: float = 0.4
    shimmer: bool = True


# ---------------------------------------------------------------- 参数读取


def _flag(value, default: bool) -> bool:
    """只认真布尔 / 0 / 1 / 'true' / 'false'——`bool("false")` 是 True 的坑。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("true", "1"):
            return True
        if s in ("false", "0"):
            return False
    return default


def _pct(value, default: float) -> float:
    """0~100 的强度旋钮 -> 0~1；脏值 / 越界一律回退或夹紧。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default / 100.0
    if v != v:                      # NaN
        return default / 100.0
    return max(0.0, min(1.0, v / 100.0))


def _get(storage, key: str, default):
    """读一个设置；Storage 自带 DEFAULT 回退，这里再兜一层（裸 dict 也行）。"""
    try:
        v = storage.get_setting(key)
    except (AttributeError, TypeError):
        try:
            v = storage[key]
        except (KeyError, TypeError):
            v = None
    return default if v is None else v


def liquid_style(storage) -> LiquidStyle:
    """从 storage 读一份液态参数（唯一入口；设置面板只写键）。"""
    return LiquidStyle(
        dispersion=_pct(_get(storage, "liquid_dispersion",
                             _DEFAULTS["dispersion"]),
                        _DEFAULTS["dispersion"]),
        bezel=_pct(_get(storage, "liquid_bezel", _DEFAULTS["bezel"]),
                   _DEFAULTS["bezel"]),
        noise=_pct(_get(storage, "liquid_noise", _DEFAULTS["noise"]),
                   _DEFAULTS["noise"]),
        shimmer=_flag(_get(storage, "liquid_shimmer", _DEFAULTS["shimmer"]),
                      _DEFAULTS["shimmer"]),
    )


def master_enabled(storage) -> bool:
    """液态玻璃总开关（一票否决三个表面；设置面板总开关与它同源）。"""
    return _flag(_get(storage, "liquid_glass", True), True)


def surface_enabled(storage, surface: str) -> bool:
    """某个表面是否启用液态玻璃（总开关一票否决）。"""
    if surface not in SURFACES:
        return False
    if not master_enabled(storage):
        return False
    return _flag(_get(storage, "liquid_" + surface, True), True)


# ---------------------------------------------------------------- 绘制


def _edge_band(p: QPainter, rect: QRectF, bezel: float) -> None:
    """透镜边：四道贴边渐隐亮带（fresnel 反光，光从左上来）。"""
    w = max(1.0, min(BEZEL_W, rect.width() * 0.25, rect.height() * 0.25))
    # 顶边最亮（34），左次之（26），底/右渐暗（16/12）——法线角越大越暗
    for grad, x0, y0, x1, y1, peak in (
            (QLinearGradient(rect.left(), rect.top(),
                             rect.left(), rect.top() + w),
             rect.left(), rect.top(), rect.right(), rect.top() + w, 34),
            (QLinearGradient(rect.left(), rect.top(),
                             rect.left() + w, rect.top()),
             rect.left(), rect.top(), rect.left() + w, rect.bottom(), 26),
            (QLinearGradient(rect.right() - w, rect.top(),
                             rect.right(), rect.top()),
                             rect.right() - w, rect.top(), rect.right(),
                             rect.bottom(), 12),
            (QLinearGradient(rect.left(), rect.bottom() - w,
                             rect.left(), rect.bottom()),
                             rect.left(), rect.bottom() - w, rect.right(),
                             rect.bottom(), 16)):
        grad.setColorAt(0.0, QColor(255, 255, 255, int(peak * bezel)))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(x0, y0, max(0.0, x1 - x0), max(0.0, y1 - y0)),
                   grad)


def _dispersion(p: QPainter, rect: QRectF, radius: float,
                strength: float) -> None:
    """色散：贴边框内侧四条细线，把白光拆成彩色镶边。"""
    if strength <= 0.0:
        return
    a = int(26 * strength)
    if a <= 0:
        return
    inset = DISPERSION_INSET
    # 线段避开圆角（左右各收 radius*0.55），否则线头会画出弧外
    shrink = max(0.0, radius * 0.55)
    pen = QPen()
    pen.setWidthF(1.2)
    pen.setCapStyle(Qt.FlatCap)
    for grad, p0, p1 in (
            (QLinearGradient(rect.left(), 0, rect.right(), 0),      # 顶
             QPointF(rect.left() + shrink, rect.top() + inset),
             QPointF(rect.right() - shrink, rect.top() + inset)),
            (QLinearGradient(0, rect.top(), 0, rect.bottom()),      # 左
             QPointF(rect.left() + inset, rect.top() + shrink),
             QPointF(rect.left() + inset, rect.bottom() - shrink)),
            (QLinearGradient(0, rect.top(), 0, rect.bottom()),      # 右
             QPointF(rect.right() - inset, rect.top() + shrink),
             QPointF(rect.right() - inset, rect.bottom() - shrink)),
            (QLinearGradient(rect.left(), 0, rect.right(), 0),      # 底
             QPointF(rect.left() + shrink, rect.bottom() - inset),
             QPointF(rect.right() - shrink, rect.bottom() - inset))):
        color = _edge_color(p0, p1, rect)
        if color is None:
            continue
        c = QColor(color)
        c.setAlpha(a)
        grad.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), a // 3))
        grad.setColorAt(0.5, c)
        grad.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), a // 3))
        pen.setBrush(grad)
        p.setPen(pen)
        p.drawLine(p0, p1)


def _edge_color(p0: QPointF, p1: QPointF, rect: QRectF) -> Optional[QColor]:
    """按线段位置判断是哪条边（顶/底是水平线，左/右是垂直线）。"""
    if abs(p0.y() - p1.y()) < 0.01:                    # 水平线
        return _DISPERSION_TOP if p0.y() < rect.center().y() \
            else _DISPERSION_BOTTOM
    if abs(p0.x() - p1.x()) < 0.01:                    # 垂直线
        return _DISPERSION_LEFT if p0.x() < rect.center().x() \
            else _DISPERSION_RIGHT
    return None


_noise_cache: Optional[QPixmap] = None


def _noise_pixmap() -> QPixmap:
    """确定性噪声纹理（feTurbulence 的静态近似）：只生成一次，全局复用。"""
    global _noise_cache
    if _noise_cache is None:
        rng = random.Random(NOISE_SEED)
        img = QImage(NOISE_TILE, NOISE_TILE, QImage.Format_ARGB32)
        for y in range(NOISE_TILE):
            for x in range(NOISE_TILE):
                v = rng.randint(0, 110)               # 灰度颗粒，暗部为主
                img.setPixel(x, y, QColor(v, v, v, v).rgba())
        _noise_cache = QPixmap.fromImage(img)
    return _noise_cache


def _shimmer_band(p: QPainter, rect: QRectF, phase: float) -> None:
    """扫光：一道柔和高光带横扫（phase 0~1；带在界外时不画）。"""
    if phase is None:
        return
    span = rect.width() * 1.5
    cx = rect.left() + (-0.25 + 1.5 * phase) * span
    bw = rect.width() * 0.30
    left = cx - bw / 2.0
    if left > rect.right() or left + bw < rect.left():
        return                                          # 整条在界外
    grad = QLinearGradient(left, 0, left + bw, 0)
    grad.setColorAt(0.0, QColor(255, 255, 255, 0))
    grad.setColorAt(0.5, QColor(255, 255, 255, 30))
    grad.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillRect(QRectF(left, rect.top(), bw, rect.height()), grad)


def paint_overlay(p: QPainter, rect, radius: float, style: LiquidStyle,
                  phase: Optional[float] = None, widget=None) -> None:
    """在**已有玻璃**之上叠加液态光学层（不画底色——底色归各表面）。

    - `rect` / `radius`：表面矩形与圆角（半径会被夹紧到短边一半内）；
    - `style`：`liquid_style()` 的返回值；全零样式什么都不画；
    - `phase`：扫光相位 0~1；None = 静态（预览 / 减动效场景）；
    - `widget`：传入表面控件即自动挂上扫光 ticker（幂等）。
    """
    if widget is not None:
        attach(widget)
    if style is None:
        return
    rect = QRectF(rect)
    if rect.width() <= 1 or rect.height() <= 1:
        return
    r = float(radius if radius is not None else theme.GLASS_RADIUS)
    r = max(0.0, min(r, rect.width() / 2.0, rect.height() / 2.0))
    if (style.dispersion <= 0 and style.bezel <= 0 and style.noise <= 0
            and not (style.shimmer and phase is not None)):
        return                                          # 全零：不碰画布
    path = QPainterPath()
    path.addRoundedRect(rect, r, r)
    p.save()
    p.setClipPath(path)
    if style.bezel > 0:
        _edge_band(p, rect, style.bezel)
    if style.dispersion > 0:
        _dispersion(p, rect, r, style.dispersion)
    if style.noise > 0:
        p.setOpacity(min(1.0, 0.5 * style.noise))
        p.drawTiledPixmap(rect, _noise_pixmap())
        p.setOpacity(1.0)
    if style.shimmer and phase is not None:
        _shimmer_band(p, rect, phase)
    p.restore()


# ---------------------------------------------------------------- 扫光驱动

_surfs: Dict[int, weakref.ref] = {}
_timer: Optional[QTimer] = None
_t0 = time.monotonic()


def _surfaces() -> Dict[int, weakref.ref]:
    """当前挂着的表面（顺手清掉已销毁的弱引用）。"""
    for k in [k for k, r in _surfs.items() if r() is None]:
        _surfs.pop(k, None)
    return dict(_surfs)


def attach(widget) -> None:
    """把表面挂上扫光 ticker（幂等；控件销毁后自动脱落）。"""
    _surfs[id(widget)] = weakref.ref(widget)
    _ensure_timer()


def detach(widget) -> None:
    _surfs.pop(id(widget), None)


def _ensure_timer() -> None:
    global _timer
    if _timer is None:
        _timer = QTimer()
        _timer.setInterval(TICK_MS)
        _timer.timeout.connect(_tick)
    if _surfs and not effects.reduced_motion():
        _timer.start()


def _tick() -> None:
    if effects.reduced_motion() or not _surfs:
        if _timer is not None:
            _timer.stop()
        return
    for r in list(_surfs.values()):
        w = r()
        if w is None:
            continue
        try:
            if w.isVisible():
                w.update()
        except (RuntimeError, AttributeError):
            pass     # 已销毁的控件（C++ 对象已删）直接跳过


def shimmer_phase() -> Optional[float]:
    """当前扫光相位 0~1；系统关动画时 None（调用方据此跳过扫光）。"""
    if effects.reduced_motion():
        return None
    return (time.monotonic() - _t0) % SHIMMER_PERIOD / SHIMMER_PERIOD
