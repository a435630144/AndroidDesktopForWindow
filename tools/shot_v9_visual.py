# -*- coding: utf-8 -*-
"""v9 目检图：外观自定义 + 玻璃时钟/便签 + 组件库分页 + 多选标记。

出图到 `dist/shots/v9_visual.png`，一张图回答四个问题：

  1. 时钟 / 便签玻璃化之后跟监控/待办/日历/天气是同一套语言吗？
  2. 「背景色 + 透明度」到底改了哪一层（是玻璃底，不是内容）？
  3. 组件库现在真的长在设置面板里吗（有导航、有分类、有卡片）？
  4. 手机模式多选态的"空心圆 / 对钩"画得出来吗（左上角标记）？

为什么不用 QT_QPA_PLATFORM=offscreen：那套平台插件没有中文字体，
数字与汉字全渲染成方块（DEVLOG 坑 #60）。这里用**真实 QPA** +
`WA_DontShowOnScreen`，屏幕不上东西但字体引擎是真的。

为什么组件卡片是"自己画到 QImage"而不是 `grab()`：`FloatingWidget` 是分层
半透明窗，`grab()` 不含子部件也不算透明底（坑 #95）；而组件的内容绘制本来
就是纯函数（`paint_glass` + `draw`），直接画到画布上最接近真实效果。

跑法：python tools/shot_v9_visual.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src import theme
from src.widgets import clock as widgets_clock
from src.widgets import notes as widgets_notes
from src import widget_style
from src.widget_glass import paint_glass

OUT = Path(__file__).resolve().parent.parent / "dist" / "shots" / "v9_visual.png"
W, H = 1240, 980
CARD = 250


def _style(**settings) -> "widget_style.Style":
    return widget_style.of({"settings": settings})


def _label(p, text, x, y, color="#9AA0AC", size=12, bold=False):
    p.setPen(QColor(color))
    p.setFont(theme.ui_font(size, bold=bold))
    p.drawText(QRectF(x, y, 460, 20), Qt.AlignLeft | Qt.AlignVCenter, text)


def _card(x, y, side=CARD):
    return QRectF(x, y, side, side)


def main(argv):
    app = QApplication.instance() or QApplication(argv)
    # 先拿设置面板截图，再按它的实际高度决定画布高度
    # （写死高度会让截图被裁掉一半——第一版就是这么翻的）
    shot = _settings_shot()
    shot_h = shot.height() if shot is not None else 0
    row3 = 740
    settings_y = row3 + 190
    height = settings_y + shot_h + 60 if shot is not None else row3 + 220
    # 不碰用户真实桌面：本脚本只画图，不接管、不隐藏原生图标
    img = QImage(W, max(H, height), QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("#11131a"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)

    # 背景做一层"假壁纸"渐变，玻璃才有东西可透
    from PySide6.QtGui import QLinearGradient
    g = QLinearGradient(0, 0, W, max(H, height))
    g.setColorAt(0.0, QColor("#1b2740"))
    g.setColorAt(0.55, QColor("#20202c"))
    g.setColorAt(1.0, QColor("#2a1e28"))
    p.fillRect(0, 0, W, max(H, height), g)

    p.setPen(QColor("#E8EAEF"))
    p.setFont(theme.ui_font(19, bold=True))
    p.drawText(QRectF(40, 26, 800, 30), Qt.AlignLeft | Qt.AlignVCenter,
               "v9 外观自定义 · 玻璃组件 · 组件库分页 · 手机多选")
    p.setPen(QColor("#8C93A1"))
    p.setFont(theme.ui_font(12))
    p.drawText(QRectF(40, 56, 900, 22), Qt.AlignLeft | Qt.AlignVCenter,
               "同一份 draw()：桌面组件与这里画的是同一段代码")

    # ---------- 第一行：时钟两种外观 ----------
    model = widgets_clock.model_now()
    y = 100
    boxes = [
        ("时钟 · 默认（跟随主题）", _card(40, y), _style()),
        ("时钟 · 自定义底色+弱透明", _card(320, y),
         _style(bg_color="#1E5A8A", bg_alpha=0.55)),
        ("时钟 · 强调色改橙", _card(600, y),
         _style(accent_color="#FF8A3D", text_color="#FFF6EC")),
        ("便签 · 默认", _card(880, y), _style()),
    ]
    for title, rect, st in boxes:
        paint_glass(p, rect, st.radius, tint_alpha=st.tint_alpha, tint_color=st.bg)
        if title.startswith("便签"):
            widgets_notes.draw(p, rect, "1. 出 v9a 包\n2. 实机验收双交互\n3. 收 B5 视觉",
                               st)
        else:
            widgets_clock.draw(p, rect, model, st)
        _label(p, title, rect.left(), rect.bottom() + 8)

    # ---------- 第二行：其余四个组件跟着换文字色 ----------
    from src import widgets_calendar, widgets_todo, widgets_weather
    from src.widgets import monitor as widget_monitor
    y2 = 400
    warm = _style(text_color="#FFE9C7", accent_color="#FFB454", bg_color="#3A2A1C",
                  bg_alpha=0.5)
    paints = [
        ("系统监控", lambda r: widget_monitor.draw(
            p, r, widget_monitor.sample(), None, warm)),
        ("待办", lambda r: widgets_todo.draw(
            p, r, widgets_todo.load_items([
                {"text": "写组件文档", "done": True},
                {"text": "跑全量回归", "done": True},
                {"text": "出 v9a 包", "done": False},
            ]), style=warm)),
        ("日历", lambda r: widgets_calendar.draw(
            p, r, widgets_calendar.build_model(2026, 10), warm)),
        ("天气", lambda r: widgets_weather.draw(
            p, r, widgets_weather.wa.WeatherModel(
                city="上海", temp=21, feels=20, humidity=62, wind=3.4,
                code=3), "live", warm)),
    ]
    for i, (title, fn) in enumerate(paints):
        rect = _card(40 + i * 280, y2)
        paint_glass(p, rect, warm.radius, tint_alpha=warm.tint_alpha,
                    tint_color=warm.bg)
        try:
            fn(rect)
        except Exception as exc:      # noqa: BLE001 —— 目检脚本不该因签名差异挂掉
            p.setPen(QColor("#FF7A7A"))
            p.setFont(theme.ui_font(11))
            p.drawText(rect.adjusted(12, 12, -12, -12), Qt.TextWordWrap,
                       "%s: %s" % (type(exc).__name__, exc))
        _label(p, "%s · 暖色外观" % title, rect.left(), rect.bottom() + 8)

    # ---------- 第三行：多选标记（空心圆 / 对钩） ----------
    from PySide6.QtGui import QRegion
    from PySide6.QtWidgets import QWidget
    from src.iconwidget import AppIcon
    entry = {"id": "demo", "type": "app",
             "app": {"name": "记事本", "path": "notepad.exe"}}
    icon = AppIcon(entry, 96, parent=None)
    icon.setAttribute(Qt.WA_DontShowOnScreen, True)
    icon.show()
    _label(p, "手机模式多选标记（左上角空心圆 → 选中变对钩）", 40, row3 - 26,
           "#C9CEDA", 13, True)
    for i, sel in enumerate((False, True)):
        icon.set_selection_visible(True)
        icon.set_selected(sel)
        chip = QImage(150, 150, QImage.Format_ARGB32_Premultiplied)
        chip.fill(Qt.transparent)      # 透明底：只留图标本体，别铺白板
        cp = QPainter(chip)
        cp.setRenderHint(QPainter.Antialiasing, True)
        # 只画子内容、不画窗口底色（坑 #95 的正向用法）
        icon.render(cp, QPoint(18, 14), QRegion(), QWidget.DrawChildren)
        cp.end()
        p.drawImage(40 + i * 160, row3, chip)
        _label(p, "未选中" if not sel else "已选中", 40 + i * 160, row3 + 132,
               "#C9CEDA", 11)
    icon.close()

    # ---------- 第四行：设置面板里的组件库分页 ----------
    if shot is not None:
        p.drawPixmap(40, settings_y, shot)
        _label(p, "设置 ▸ 组件库（原独立窗口已融合，BUG1 从结构上消失）",
               40, settings_y + shot_h + 6)
    else:
        _label(p, "（设置面板截图跳过：本机无法构造，见控制台输出）",
               40, settings_y, "#FF7A7A")

    p.end()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(OUT))
    print("已出图：%s（%d × %d）" % (OUT, W, img.height()))
    return 0


def _settings_shot():
    """设置面板 ▸ 组件库 分页的真实截图（普通 QWidget，grab 含子部件）。"""
    try:
        from src.desktop_window import DesktopWindow
        from src.settings_dialog import SettingsDialog
        from src.storage import Storage
        from src.widget_layer import WidgetLayer

        state = Path(tempfile.gettempdir()) / "shot_v9_state.json"
        if state.exists():
            state.unlink()
        st = Storage(str(state))
        st._data["settings"]["hide_native_icons"] = False
        st._data["settings"]["takeover_desktop"] = False
        st._data["settings"]["auto_clone_desktop"] = False
        st._data["layout"] = []
        st._data["widgets"] = []
        st.save()
        grid_flow.set_grid(st, (1920, 1040))
        grid_flow.set_page(0)

        # 图标/桌面层一律不挂真实桌面带：本脚本只出图
        import src.win32_layer as wl
        wl.attach_to_desktop = lambda *a, **k: False
        import src.widget_base as wb
        wb.attach_to_desktop = lambda *a, **k: False

        layer = WidgetLayer(st)
        win = DesktopWindow(st)
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        dlg = SettingsDialog(win, st, layer, page="widgets")
        dlg.setAttribute(Qt.WA_DontShowOnScreen, True)
        dlg.show()
        QApplication.processEvents()
        pm = dlg.grab()
        dlg.close()
        win.close()
        # 缩到画布宽度（保持比例）
        target_w = 1180
        return pm.scaledToWidth(target_w, Qt.SmoothTransformation)
    except Exception as exc:      # noqa: BLE001
        print("设置面板截图失败：%s: %s" % (type(exc).__name__, exc))
        return None


if __name__ == "__main__":
    os.environ.pop("QT_QPA_PLATFORM", None)
    sys.exit(main(sys.argv))
