# -*- coding: utf-8 -*-
"""拖动浮影：**有文件名、没有白框**（2026-10-19 反馈 8）。

历史：第一版 render() 整个部件 -> 白框（调色板底色 + 选中底色一起烘进去）；
第二版改成只画图标本体 -> 白框没了，但**文件名也没了**（用户反馈 8）。
最终契约：透明底 pixmap 上手绘「图标本体 + 标签」，两轮反馈同时满足。

  P1 快照尺寸 = 整个 widget（图标区 + 标签区）
  P2 四角全透明（没有卡片底色 / 白框）
  P3 图标绘制区有内容
  P4 标签区有内容（文件名没丢）
  P5 快照不改动控件状态
  P6 文件夹瓷砖同样成立

运行：python tests/test_drag_ghost_icon_only.py   （offscreen）
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from src import grid_sizing as gs
from src.iconwidget import AppIcon

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def folder_entry():
    return {"id": "f1", "type": "folder", "name": "文件夹",
            "apps": [{"name": "A", "target": "a", "kind": "app"},
                     {"name": "B", "target": "b", "kind": "app"}]}


def app_entry():
    return {"id": "a1", "type": "app", "name": "应用",
            "app": {"id": "a1", "name": "应用", "target": "a", "kind": "app"}}


def corner_alphas(pm):
    img = pm.toImage()
    dpr = max(1.0, pm.devicePixelRatio())
    w, h = int(img.width() / dpr), int(img.height() / dpr)
    return [img.pixelColor(0, 0).alpha(),
            img.pixelColor(w - 1, 0).alpha(),
            img.pixelColor(0, h - 1).alpha(),
            img.pixelColor(w - 1, h - 1).alpha()]


def opaque_count(img, x0, y0, x1, y1, step=1):
    n = 0
    for y in range(max(0, y0), min(img.height(), y1), step):
        for x in range(max(0, x0), min(img.width(), x1), step):
            if img.pixelColor(x, y).alpha() > 8:
                n += 1
    return n


def main(app):
    lay = gs.icon_layout(83, 102, "medium")
    ic = AppIcon(app_entry(), 0, layout=lay)
    ic._hover = True
    ic.selected = True
    snap = ic._drag_snapshot()
    dpr = max(1.0, snap.devicePixelRatio())
    w, h = int(snap.width() / dpr), int(snap.height() / dpr)

    check("P1 快照尺寸 = 整个 widget（含标签）",
          (w, h) == (ic.width(), ic.height()),
          "got=%s want=%s" % ((w, h), (ic.width(), ic.height())))

    alphas = corner_alphas(snap)
    check("P2 四角全透明（无白框/卡片底色）", all(a == 0 for a in alphas),
          "corners=%s" % (alphas,))

    img = snap.toImage()
    icon_alpha = img.pixelColor(int((lay.icon_box // 2) * dpr),
                                int(4 * dpr)).alpha()
    check("P3 图标区有内容", icon_alpha > 8, "alpha=%d" % icon_alpha)

    label_y = int((lay.icon_box + 4) * dpr)
    label_px = opaque_count(img, 0, label_y,
                            img.width(), int(h * dpr))
    check("P4 标签区有内容（文件名保留）", label_px > 20,
          "opaque=%d label_y=%d" % (label_px, label_y))

    check("P5 快照不改动控件状态", ic._hover is True and ic.selected is True)

    ic2 = AppIcon(folder_entry(), 0, layout=lay)
    snap2 = ic2._drag_snapshot()
    img2 = snap2.toImage()
    n2 = opaque_count(img2, 0, 0, img2.width(), int(lay.icon_box * dpr))
    check("P6 文件夹瓷砖快照非空且无背景框",
          n2 > 100 and all(a == 0 for a in corner_alphas(snap2)),
          "opaque=%d corners=%s" % (n2, corner_alphas(snap2)))

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL drag_ghost_icon_only PASSED")
    return 0


def run_main():
    app = QApplication([])
    try:
        code = main(app)
    except Exception:
        import traceback
        traceback.print_exc()
        failures.append("main() 异常")
        code = 1
    return code


if __name__ == "__main__":
    sys.exit(run_main())
