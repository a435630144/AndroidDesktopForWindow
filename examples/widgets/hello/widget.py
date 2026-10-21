# -*- coding: utf-8 -*-
"""示例外部组件：向 <称呼> 问好，可选显示时间。

这个文件就是 `docs/组件开发指南.md` 里"最小可用组件"的完整实现，
可以直接照抄改：

  1. `import` 只从 `deskorg` 命名空间拿（那是主程序给插件开的 SDK 别名）；
  2. 写一个 `GlassWidget` 子类，实现 `paint_content()`（必须）与
     `on_settings_changed()`（可选）；
  3. 画的时候**不要假设**尺寸：所有坐标按 `self.rect()` 的比例算，
     2×2 与 4×2 都要好看；
  4. 想在组件库里显示缩略图就写 `draw_preview(painter, rect)`，
     没有就自动走兜底卡（名字 + 一句话说明）。
"""

from PySide6.QtCore import QDateTime, QRectF, Qt
from PySide6.QtGui import QColor

from deskorg import theme
from deskorg.widget_glass import GlassWidget

PAD = 18


def _greeting(settings: dict) -> str:
    who = (settings or {}).get("who") or "世界"
    return "你好，%s" % who


def draw_content(painter, rect, settings, style):
    """内容绘制抽成函数：预览与桌面用**同一份**，不会"预览一套、桌面一套"。"""
    r = QRectF(rect)
    who = _greeting(settings)
    show_time = bool((settings or {}).get("show_time", True))

    painter.setRenderHint(painter.RenderHint.Antialiasing, True)

    # 顶部一条强调色短线（用用户的强调色，不写死主题色）
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(style.accent))
    painter.drawRoundedRect(QRectF(r.left() + PAD, r.top() + PAD, 26, 3), 1.5, 1.5)

    # 主文字：字号跟容器高度走（2×2 与 4×2 都合适）
    fs = max(13, int(min(r.height() * 0.16, r.width() * 0.09)))
    painter.setPen(QColor(style.text))
    painter.setFont(theme.ui_font(fs, bold=True))
    painter.drawText(QRectF(r.left() + PAD, r.top() + PAD + 14,
                            r.width() - PAD * 2, fs * 1.6),
                     Qt.AlignLeft | Qt.AlignVCenter, who)

    if show_time:
        painter.setPen(QColor(style.dim))
        painter.setFont(theme.ui_font(max(10, int(fs * 0.62))))
        painter.drawText(QRectF(r.left() + PAD, r.bottom() - PAD - fs * 0.9,
                                r.width() - PAD * 2, fs),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         QDateTime.currentDateTime().toString("HH:mm"))


class HelloWidget(GlassWidget):
    """最小可用外部组件。`GlassWidget` 已经处理好拖动/缩放/玻璃底。"""

    TYPE = "hello"

    def paint_content(self, p):
        draw_content(p, self.rect(), self.entry.get("settings") or {}, self.style)

    def on_settings_changed(self):
        # 必须调 super()：它负责清样式缓存并重绘
        super().on_settings_changed()


def draw_preview(painter, rect, dpr: float = 1.0):
    """组件库缩略图（可选）。用示例数据，不要实例化组件（会启定时器）。"""
    from deskorg.widget_glass import PREVIEW_RADIUS, paint_glass
    from deskorg import widget_style

    r = QRectF(rect)
    paint_glass(painter, r, PREVIEW_RADIUS)
    draw_content(painter, r, {"who": "世界", "show_time": True},
                 widget_style.DEFAULT_STYLE)
