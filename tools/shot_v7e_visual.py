# -*- coding: utf-8 -*-
"""v7e 视觉批次离屏目检图（B5：反馈 10 / 13 / 20）。

为什么需要它：`test_folder_visual.py` 用像素包围盒断言"画得够大、居中、点得中"，
但断言通过不等于**看起来对**——反馈 10/13/20 全是"肉眼觉得不对"的体感问题。
本脚本把两处真实渲染（文件夹弹窗 / 组件编辑态）抓成 PNG，供人工目检。

姿势：真实 QPA + `WA_DontShowOnScreen`（不走屏幕但用真实字体引擎），
**不要** 用 `QT_QPA_PLATFORM=offscreen`——那样中文全变方块。

运行：python tools/shot_v7e_visual.py [输出路径]
默认输出 dist/shots/v7e_visual.png
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtTest import QTest

from src import grid_flow
from src.folder_popup import FolderPopup
from src.storage import Storage
from src.widget_layer import WidgetLayer

STATE = Path(tempfile.gettempdir()) / "shot_v7e_visual_state.json"

# 用系统自带 exe 做真实的 256px 图标源（不用假图标，否则看不出"小图上采样"）
SYS = Path(os.environ.get("WINDIR", r"C:\Windows"))
DEMO_APPS = [
    {"name": "记事本", "target": str(SYS / "System32" / "notepad.exe")},
    {"name": "画图", "target": str(SYS / "System32" / "mspaint.exe")},
    {"name": "命令提示符", "target": str(SYS / "System32" / "cmd.exe")},
    {"name": "资源管理器", "target": str(SYS / "explorer.exe")},
    {"name": "任务管理器", "target": str(SYS / "System32" / "Taskmgr.exe")},
    {"name": "控制面板", "target": str(SYS / "System32" / "control.exe")},
    {"name": "注册表", "target": str(SYS / "regedit.exe")},
    {"name": "写字板", "target": str(SYS / "System32" / "write.exe")},
    {"name": "计算器", "target": str(SYS / "System32" / "calc.exe")},
]


def _make_storage():
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"].update({
        "hide_native_icons": False, "auto_clone_desktop": False,
        "layout_mode": "grid", "takeover_desktop": True, "widgets_only": False,
        "dev_mode": False,
    })
    st._data["layout"] = []
    st._data["widgets"] = [{"id": "note1", "type": "notes", "w": 320, "h": 360,
                            "hidden": False, "anchored": True,
                            "text": "拖动四角可改尺寸"}]
    st.save()
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)
    return st


def _child_image(child):
    """把一个子部件的**透明底**渲染结果抠出来（不含调色板底色）。"""
    dpr = child.devicePixelRatioF()
    img = QImage(max(1, int(child.width() * dpr)),
                 max(1, int(child.height() * dpr)),
                 QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    # 只给 DrawChildren、不给 DrawWindowBackground → 没有底色块
    child.render(p, QPoint(0, 0), QRegion(), QWidget.DrawChildren)
    p.end()
    img.setDevicePixelRatio(1.0)
    return img


def _composite_children(parent, img):
    """把 `img` 里缺失的子部件手工补画上去。

    坑（2026-10-21 实测）：`WA_DontShowOnScreen` + 真实 QPA 下，
    `parent.grab()` 与 `parent.render(DrawChildren)` **都不画子部件**
    （子部件 `isVisible()` 为 True、单独渲染有内容，但父级合成里那块
    alpha 恒为 0）；而 `QT_QPA_PLATFORM=offscreen` 能画出子部件却缺中文字体。
    两个姿势各缺一半 → 这里取"真实字体 + 手工合成子部件"。

    另外 `child.grab()` 会**连调色板底色一起烘进去**（白块），所以子部件
    必须走 `render(..., DrawChildren)`（不带 `DrawWindowBackground`），
    且要把出场动画进度 `_appear` 拉回 1.0（否则抓到半透明/空白）。
    """
    img.setDevicePixelRatio(1.0)
    dpr = parent.devicePixelRatioF()
    p = QPainter(img)
    for child in parent.findChildren(QWidget):
        if not child.isVisible() or child.width() <= 0 or child.height() <= 0:
            continue
        if hasattr(child, "_appear"):
            child._appear = 1.0
        pos = child.mapTo(parent, QPoint(0, 0))
        ci = _child_image(child)
        p.drawImage(int(pos.x() * dpr), int(pos.y() * dpr), ci)
    p.end()
    return img


def grab_popup(st):
    entry = {"id": "demo-folder", "name": "常用工具",
             "apps": DEMO_APPS, "tint": QColor("#3d6bd6").name()}
    pop = FolderPopup(st, entry)
    pop.setAttribute(Qt.WA_DontShowOnScreen, True)
    pop.show()
    # 开合动效（_zoom 0→1 + 成员逐个出场）要跑完才拍，否则抓到空弹窗
    QTest.qWait(700)
    pop._zoom = 1.0
    QApplication.processEvents()
    img = _composite_children(pop, pop.grab().toImage())
    print("popup size=%dx%d dpr=%.2f members=%d"
          % (pop.width(), pop.height(), pop.devicePixelRatioF(),
             len(entry.get("apps") or [])))
    pop.close()
    return img


def grab_widget(st, span=(2, 2)):
    layer = WidgetLayer(st)
    w = layer.widgets.get("note1")
    if w is None:
        return QImage()
    w.setAttribute(Qt.WA_DontShowOnScreen, True)
    w.resize(span[0] * 160, span[1] * 180)
    w._edit_mode = True
    w.show()
    QApplication.processEvents()
    img = w.grab().toImage()
    for x in layer.widgets.values():
        x.close()
    return img


def label_band(p, x, w, text, sub):
    """在标题带里画一栏标题 + 副标题（宽度受限，避免两栏文字互压）。"""
    f = QFont("Microsoft YaHei UI", 11, QFont.Bold)
    p.setFont(f)
    p.setPen(QColor("#e8eefc"))
    p.drawText(QRectF(x, 8, w, 26), Qt.AlignLeft | Qt.AlignVCenter, text)
    f2 = QFont("Microsoft YaHei UI", 8)
    p.setFont(f2)
    p.setPen(QColor("#8fa0bd"))
    p.drawText(QRectF(x, 32, w, 22), Qt.AlignLeft | Qt.AlignVCenter, sub)


def main(app):
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parent.parent / "dist" / "shots" / "v7e_visual.png")
    out.parent.mkdir(parents=True, exist_ok=True)

    st = _make_storage()
    pop_img = grab_popup(st)
    wid_img = grab_widget(st)

    gap, pad, top = 28, 24, 62
    pop_w = max(pop_img.width(), 320)
    wid_w = max(wid_img.width(), 320)
    width = pad * 2 + pop_w + gap + wid_w
    height = top + max(pop_img.height(), wid_img.height()) + pad
    canvas = QImage(width, height, QImage.Format_ARGB32)
    canvas.fill(QColor("#0a0d12"))
    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing, True)

    p.fillRect(0, 0, width, 62, QColor("#11151c"))
    label_band(p, pad, pop_w - 8, "v7e · 文件夹弹窗（反馈 10 / 13）",
               "图标 %d px、contain 居中、不随桌面档位放大"
               % FolderPopup._member_icon_size(type("S", (), {
                   "storage": st, "entry": {"apps": DEMO_APPS}})()))
    x0, y0 = pad, top + 6
    p.drawImage(x0, y0, pop_img)

    x1 = pad + pop_w + gap
    p.fillRect(x1 - gap // 2, 0, 1, height, QColor("#1b2330"))
    label_band(p, x1, wid_w,
               "v7e · 组件编辑控制点（反馈 20）",
               "圆球、内缩由点径推导、命中区 ≥22×22")
    p.drawImage(x1, y0, wid_img)

    p.end()
    canvas.save(str(out))
    print("saved:", out, canvas.width(), "x", canvas.height())

    if STATE.exists():
        STATE.unlink()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    main(app)
