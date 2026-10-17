# -*- coding: utf-8 -*-
"""视觉动效工具箱：液态玻璃背板、弹性缓动、玻璃表面绘制。

设计参考（2025 苹果 Liquid Glass + 安卓/iOS 交互动效）：
  - 液态玻璃：背后内容实时高斯模糊 + 半透明 tint + 边缘高光(specular)
  - 弹性出场：OutBack 过冲（打开）/ InCubic 收起（关闭）
  - 控件按压回弹、错峰淡入（stagger）

实现取舍（重要）：
  不用 SetWindowCompositionAttribute 的 acrylic blur——它与 Qt 的
  WA_TranslucentBackground + WS_EX_LAYERED 组合冲突（acrylic 不显示，
  实测踩坑）。改为：show() 前抓屏 -> C++ 层高斯模糊 -> 自绘。
  桌面场景背后基本静态（壁纸+桌面带），一次性抓取完全够用，
  且跨 Win10/Win11 稳定、观感完全可控。

全部只用 Qt 自带模块，零第三方依赖，不影响打包体积。
"""
from PySide6.QtCore import QEasingCurve, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QGuiApplication, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap)

from . import theme

SPI_GETCLIENTAREAANIMATION = 0x1002  # 系统动画效果开关（设置 -> 视觉效果 -> 动画）
_rm_cache = None


def reduced_motion() -> bool:
    """系统动画效果是否被关闭——prefers-reduced-motion 的桌面等价物。

    苹果无障碍规范：关动画时去掉位移/弹性过冲，保留透明度/颜色反馈。
    结果缓存（系统设置运行期不变）。
    """
    global _rm_cache
    if _rm_cache is None:
        try:
            import ctypes
            v = ctypes.c_int(0)
            ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(v), 0)
            _rm_cache = not bool(v.value)
        except Exception:
            _rm_cache = False
    return _rm_cache


def dur(ms: int) -> int:
    """动效时长：系统关动画时压到 120ms 内（保留反馈、去掉大幅位移感）。"""
    return min(ms, 120) if reduced_motion() else ms


# ---------- 缓动曲线 ----------
def spring_out(overshoot: float = 1.0) -> QEasingCurve:
    """弹性出场：OutBack。仅用于带动量的交互（拖动落位）与 sheet 档
    弹窗打开（苹果抽屉/sheet = damping 0.8 / response 0.3 ≈ overshoot 1.0）。
    默认 overshoot 1.0 ≈ Motion 的 bounce 0.2；无动量淡入禁用过冲
    （"淡入的菜单过冲是错的"）。"""
    c = QEasingCurve(QEasingCurve.OutBack)
    c.setOvershoot(overshoot)
    return c


def smooth_out() -> QEasingCurve:
    """临界阻尼出场（苹果默认 UI 弹簧 damping 1.0 的曲线近似）。"""
    return QEasingCurve(QEasingCurve.OutCubic)


# ---------- 玻璃背板 ----------
def grab_backdrop(rect: QRect) -> QPixmap:
    """抓取 rect（全局逻辑坐标）处的屏幕内容作为玻璃背板。

    必须在目标窗口 show() 之前调用，否则会把自己抓进去。
    返回的 pixmap 带屏幕 DPR，绘制时按目标矩形缩放即可。
    """
    if rect.isEmpty():
        return QPixmap()
    center = rect.center()
    screen = None
    for s in QGuiApplication.screens():
        if s.geometry().contains(center):
            screen = s
            break
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    try:
        return screen.grabWindow(0, rect.x(), rect.y(),
                                 rect.width(), rect.height())
    except Exception:
        return QPixmap()


def blur_pixmap(pm: QPixmap, blur_radius: float = 6.0,
                downscale: int = 6) -> QPixmap:
    """高斯模糊近似：缩小 downscale 倍 -> C++ 层真高斯 -> 平滑放大回原尺寸。

    - 缩小/放大走 Qt C++ 双线性，快且自带柔化
    - QGraphicsBlurEffect 在 C++ 层完成，质量接近真高斯
    - 300x400 面板整体 < 15ms，打开文件夹时一次性，无感
    """
    if pm.isNull() or pm.width() < 8 or pm.height() < 8:
        return pm
    from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsScene
    small = pm.scaled(max(1, pm.width() // downscale),
                      max(1, pm.height() // downscale),
                      Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    scene = QGraphicsScene()
    item = scene.addPixmap(small)
    eff = QGraphicsBlurEffect()
    eff.setBlurRadius(blur_radius)
    item.setGraphicsEffect(eff)
    out = QPixmap(small.size())
    out.fill(Qt.transparent)
    painter = QPainter(out)
    scene.render(painter)
    painter.end()
    return out.scaled(pm.width(), pm.height(),
                      Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def glass_backdrop(rect: QRect, blur_radius: float = 8.0) -> QPixmap:
    """液态玻璃背板：抓屏 -> 高斯模糊（一步到位）。"""
    return blur_pixmap(grab_backdrop(rect), blur_radius)


# ---------- 玻璃表面绘制 ----------
def paint_glass(p: QPainter, rect: QRect, backdrop: QPixmap,
                radius: float = None):
    """在 painter 上绘制液态玻璃表面（backdrop 为已模糊的背板）。

    层次（自内而外）：
      1. 模糊背板：背后是什么就透什么，随窗口形变（玻璃的"透"）
      2. 垂直 tint 渐变：顶部冷光 -> 中部玻璃色 -> 底部加深（保文字可读）
      3. 顶部 specular 高光线：液态玻璃的灵魂，两端渐隐
      4. 底部反光细线 + 全周 1px 描边
    """
    if radius is None:
        radius = theme.GLASS_RADIUS
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)

    p.save()
    p.setClipPath(path)
    if not backdrop.isNull():
        # 必须走四参重载：PySide6 没有 drawPixmap(QRectF, QPixmap) 两参签名，
        # 传 QRectF 会抛 TypeError——且异常若在重入绘制栈中向上传播，
        # 会穿过多层活动 QPainter 直接杀掉进程（Fatal error: Aborted）。
        # source 用背板完整物理矩形（pixmap 坐标），target 是逻辑矩形，
        # DPR 由 painter 自动映射，1:1 无损。
        p.drawPixmap(rect, backdrop, QRectF(backdrop.rect()))
    # tint 渐变：上浅下深——顶部透光、底部沉实
    grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
    grad.setColorAt(0.0, QColor(255, 255, 255, 30))
    grad.setColorAt(0.35, QColor(20, 22, 28, theme.GLASS_TINT_ALPHA))
    grad.setColorAt(1.0, QColor(15, 16, 21, theme.GLASS_TINT_ALPHA + 38))
    p.fillPath(path, grad)
    p.restore()

    # 顶部高光（水平渐变线，两端透明，中间最亮）
    inset = radius * 0.9
    hl = QLinearGradient(rect.left() + inset, 0, rect.right() - inset, 0)
    hl.setColorAt(0.0, QColor(255, 255, 255, 0))
    hl.setColorAt(0.5, QColor(255, 255, 255, theme.GLASS_SPECULAR))
    hl.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setPen(QPen(QBrush(hl), 1.5))
    p.drawLine(QPointF(rect.left() + inset, rect.top() + 1.2),
               QPointF(rect.right() - inset, rect.top() + 1.2))

    # 底部反光（更弱，模拟玻璃厚度折射）
    bl = QLinearGradient(rect.left() + inset, 0, rect.right() - inset, 0)
    bl.setColorAt(0.0, QColor(255, 255, 255, 0))
    bl.setColorAt(0.5, QColor(255, 255, 255, 46))
    bl.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setPen(QPen(QBrush(bl), 1.0))
    p.drawLine(QPointF(rect.left() + inset, rect.bottom() - 1.2),
               QPointF(rect.right() - inset, rect.bottom() - 1.2))

    # 全周 1px 描边，界定玻璃边界
    p.setPen(QPen(QColor(255, 255, 255, theme.GLASS_BORDER), 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
