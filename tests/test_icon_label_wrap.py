# -*- coding: utf-8 -*-
"""图标文件名两行显示（v14 反馈 12）。

用户诉求：图标的文件名显示不全，一行显示不下的可以考虑 2 行显示。

契约：
  L1  `_wrap_elide` 中文长名能折两行（旧实现只按空格切词，中文永远折不了）
  L2  短名仍然一行
  L3  超过两行时末行带省略号，且**只返回两行**
  L4  `grid_sizing.label_height(box, 2)` 比单行高；`icon_layout` 只在格子
      装得下时才给第二行（cell 尺寸 84x91 一个像素不动）
  L5  真实 AppIcon 的两行绘制路径：label_h 预留两行时不抛、行数 ≤ 2

跑法：python tests/test_icon_label_wrap.py     （offscreen）
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
ROOT = Path(__file__).resolve().parent.parent

from PySide6.QtWidgets import QApplication
from src import grid_sizing as gs             # noqa: E402
from src.iconwidget import AppIcon            # noqa: E402

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def main(app):
    font = app.font()
    from PySide6.QtGui import QFontMetrics
    fm = QFontMetrics(font)

    # ---------- L1：中文长名折两行 ----------
    name = "这是一个很长的中文文件名需要折行显示"
    width = max(40, fm.horizontalAdvance(name) // 3)
    lines = AppIcon._wrap_elide(name, fm, width, 2)
    check("L1a 中文长名折成两行", len(lines) == 2, "%r -> %d 行" % (name, len(lines)))
    check("L1b 两行都非空且不溢出", all(lines) and all(
        fm.horizontalAdvance(l) <= width + fm.horizontalAdvance("…")
        for l in lines), str(lines))

    # ---------- L2：短名一行 ----------
    short = "记事本"
    check("L2 短名保持一行",
          AppIcon._wrap_elide(short, fm, 400, 2) == [short],
          str(AppIcon._wrap_elide(short, fm, 400, 2)))

    # ---------- L3：超长名末行省略且只两行 ----------
    long_cn = "超级无敌长的中文文件名一二三四五六七八九十十一十二十三十四十五十六十七十八十九二十"
    lines3 = AppIcon._wrap_elide(long_cn, fm, width, 2)
    check("L3a 最多两行", len(lines3) == 2, "%d 行" % len(lines3))
    check("L3b 末行有省略号（内容确实放不下时）",
          lines3[-1].endswith("…"), lines3[-1])
    check("L3c 西文长串也能折（无空格 URL）",
          len(AppIcon._wrap_elide("https://example.com/very/long/path/that/never/ends",
                                  fm, width, 2)) == 2)

    # ---------- L4：格子不被动大 ----------
    check("L4a label_height 两行高于单行",
          gs.label_height(47, 2) > gs.label_height(47, 1),
          "%s vs %s" % (gs.label_height(47, 1), gs.label_height(47, 2)))
    lay = gs.icon_layout(84, 91, "medium")
    check("L4b 84x91 格子给两行标签", lay.label_h == gs.label_height(lay.icon_box, 2),
          "label_h=%s icon_box=%s" % (lay.label_h, lay.icon_box))
    check("L4c widget 不越出格子", lay.widget_h <= 91 and lay.widget_w <= 84,
          "widget=%sx%s" % (lay.widget_w, lay.widget_h))
    check("L4d cell 仍是 84x91（格距没变）", gs.cell_from_native(48) == (84, 91))
    big = gs.icon_layout(83, 102, "large")
    check("L4e 装不下第二行时退回单行",
          big.label_h == gs.label_height(big.icon_box, 1),
          "label_h=%s" % big.label_h)

    # ---------- L5：真实控件绘制不抛 ----------
    from PySide6.QtWidgets import QApplication
    entry = {"id": "x", "type": "app", "app": {"name": name, "target": "C:\\x"},
             "col": 0, "row": 0}
    try:
        icon = AppIcon(entry, lay.icon_box, layout=lay)
        icon.resize(lay.widget_w, lay.widget_h)
        pm = icon.grab()
        check("L5 两行标签绘制不抛且非空", not pm.isNull())
        icon.deleteLater()
    except Exception as exc:      # noqa: BLE001
        check("L5 两行标签绘制不抛且非空", False, str(exc))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    main(app)
    print("----")
    print("failures=%d" % len(failures))
    sys.exit(1 if failures else 0)
