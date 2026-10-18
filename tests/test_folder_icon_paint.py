# -*- coding: utf-8 -*-
"""M7 回归补漏：文件夹图标绘制（AppIcon._paint_folder）——绘制级断言。

背景（M7 全量回归抓出的真 bug）：M5（commit 6e2649b）把 iconwidget.py 的
导入误写成 `from . import folder_tint`（导入的是**模块**），而
_paint_folder 调用处 `folder_tint(self.entry)` 当**函数**用 -> TypeError。
Qt 对 paintEvent override 的异常只向 stderr 打印 "Error calling Python
override" 并不中断程序，于是 M5 的单测 / 探针全绿，但桌面上所有文件夹
图标的瓷砖 + 成员迷你图标实际一个像素都没画出来（用户可见缺陷）。
本测试以「同步直调 + 像素取样」封住这个盲区：
  P1 _paint_folder 同步直调不抛（Red 时 TypeError 直接炸穿测试）
  P2 整窗 render 后瓷砖中心像素落在显式 tint 渐变区间（Red 时透明）
  P3 显式 tint 与预设首色可分（证明颜色真的来自 entry["tint"]）
  P4 缺省 tint 回退 theme.FOLDER_TINTS[0]
  P5 非法 tint 字符串回退预设（folder_tint.isValid 分支）
  P6 1 / 4 成员两种网格布局均能画完不抛（slots 分支覆盖）

运行：python tests/test_folder_icon_paint.py   （offscreen，无需显示桌面）
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from src import theme
from src.iconwidget import AppIcon

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def folder_entry(tint="#C0392B", n_members=2):
    """假文件夹条目（红 tint 与预设首色蓝紫相差极大，便于区分断言）。"""
    return {
        "id": "df:paint-test",
        "type": "folder",
        "name": "绘制测试",
        "apps": [{"name": "成员%d" % i, "target": "m%d" % i, "kind": "app"}
                 for i in range(n_members)],
        "tint": tint,
    }


def tile_center_pixel(icon: AppIcon) -> QColor:
    """整窗 render 后取瓷砖中心像素。

    取样点 (icon_size/2, icon_size/2)：瓷砖 box=(3,3)-(s-3,s-3) 的正中心，
    必在瓷砖内；2 成员布局的迷你图标在 x=0.28/0.72 两列，中心 0.5 落在
    成员缝隙（0.46~0.54），不会采到成员图标颜色。
    """
    img = QImage(icon.size(), QImage.Format_ARGB32)
    img.fill(0)
    icon.render(img)  # QImage 即 QPaintDevice；render 会同步触发 paintEvent
    s = icon.icon_size
    return img.pixelColor(s // 2, s // 2)


def near(c: QColor, ref: QColor, tol: int) -> bool:
    return (abs(c.red() - ref.red()) <= tol
            and abs(c.green() - ref.green()) <= tol
            and abs(c.blue() - ref.blue()) <= tol)


def main(app):
    icon = AppIcon(folder_entry(), 64)
    base = theme.FOLDER_TINTS[0]          # 蓝紫 (94,92,230)
    tint = QColor("#C0392B")              # 红 (192,57,43)

    # ---------- P1：同步直调不抛（Red：TypeError 直接炸） ----------
    try:
        img = QImage(icon.size(), QImage.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        icon._paint_folder(p)
        p.end()
        check("P1 _paint_folder 同步直调不抛（模块/函数导入正确）", True)
    except Exception as e:  # noqa: BLE001 —— 测试就是要抓住任何绘制异常
        check("P1 _paint_folder 同步直调不抛（模块/函数导入正确）", False,
              "%s: %s" % (type(e).__name__, e))

    # ---------- P2：整窗 render 瓷砖中心像素落在 tint 渐变区间 ----------
    # 渐变 lighter(135)~darker(165) 使中心色略亮/暗于 tint，容差 70；
    # bug 版瓷砖根本没画 -> 像素全透 (0,0,0,0) -> near/alpha 双重失败
    px = tile_center_pixel(icon)
    check("P2 瓷砖中心像素已绘制（alpha 实心）", px.alpha() >= 200,
          "px=%s" % px.name())
    check("P2 瓷砖中心色落在显式 tint 区间", near(px, tint, 70),
          "px=%s tint=%s" % (px.name(), tint.name()))

    # ---------- P3：显式 tint 与预设首色可分 ----------
    check("P3 显式 tint 生效（与预设首色分得开）", not near(px, base, 70),
          "px=%s preset0=%s" % (px.name(), base.name()))

    # ---------- P4：缺省 tint 回退预设第一项 ----------
    e4 = folder_entry()
    del e4["tint"]
    px4 = tile_center_pixel(AppIcon(e4, 64))
    check("P4 缺省 tint 回退 FOLDER_TINTS[0]",
          px4.alpha() >= 200 and near(px4, base, 70),
          "px=%s preset0=%s" % (px4.name(), base.name()))

    # ---------- P5：非法 tint 字符串回退预设 ----------
    px5 = tile_center_pixel(AppIcon(folder_entry(tint="#ZZZZZZ"), 64))
    check("P5 非法 tint 字符串回退预设",
          px5.alpha() >= 200 and near(px5, base, 70),
          "px=%s" % px5.name())

    # ---------- P6：1 / 4 成员布局画完不抛 ----------
    for n in (1, 4):
        try:
            ic = AppIcon(folder_entry(n_members=n), 64)
            img = QImage(ic.size(), QImage.Format_ARGB32)
            img.fill(0)
            p = QPainter(img)
            ic._paint_folder(p)
            p.end()
            check("P6 %d 成员网格布局绘制不抛" % n, True)
        except Exception as e:  # noqa: BLE001
            check("P6 %d 成员网格布局绘制不抛" % n, False,
                  "%s: %s" % (type(e).__name__, e))

    print()
    if failures:
        print("==== test_folder_icon_paint: %d 项失败: %s"
              % (len(failures), failures))
        return 1
    print("==== ALL folder_icon_paint PASSED")
    return 0


if __name__ == "__main__":
    app = QApplication(sys.argv)
    sys.exit(main(app))
