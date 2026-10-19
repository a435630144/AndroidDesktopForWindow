# -*- coding: utf-8 -*-
"""拖影只保留原图标（2026-10-19 用户反馈："拖拽还有一个白框，不好看"）。

病根：`_drag_snapshot()` 直接 `render()` 整个 AppIcon 部件——悬停/选中/
合并目标态的**背景圆角矩形与标签**一起被烘进拖影，拖动时看到的是一张
带白框的卡片，而不是手指下那个图标。

契约：
  P1 快照尺寸 = 图标绘制区（不含标签行与左右留白）
  P2 悬停 + 选中态下快照四角全透明（背景框没被烘进去）
  P3 快照中心仍有内容（图标本体没被裁掉）
  P4 快照不改动控件自身状态（selected / hover 原样）
  P5 普通应用图标与文件夹瓷砖都成立

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
    w, h = img.width(), img.height()
    return [img.pixelColor(0, 0).alpha(),
            img.pixelColor(w - 1, 0).alpha(),
            img.pixelColor(0, h - 1).alpha(),
            img.pixelColor(w - 1, h - 1).alpha()]


def main(app):
    lay = gs.icon_layout(83, 102, "medium")
    box = int(lay.icon_box)

    ic = AppIcon(folder_entry(), 0, layout=lay)
    # 模拟拖动起点最常见的状态：指针压在上面（悬停）+ 已选中
    ic._hover = True
    ic.selected = True
    snap = ic._drag_snapshot()

    check("P1 快照尺寸 = 图标绘制区（无标签行/留白）",
          (snap.width(), snap.height()) == (box, box),
          "got=%s want=%s" % ((snap.width(), snap.height()), (box, box)))

    alphas = corner_alphas(snap)
    check("P2 悬停+选中态下快照四角全透明（白框未被烘入）",
          all(a == 0 for a in alphas), "corners=%s" % (alphas,))

    img = snap.toImage()
    c_alp = img.pixelColor(box // 2, box // 2).alpha()
    check("P3 快照中心仍有图标内容", c_alp > 8, "center_alpha=%d" % c_alp)

    check("P4 快照不改动控件状态", ic._hover is True and ic.selected is True)

    ic2 = AppIcon(app_entry(), 0, layout=lay)
    ic2._hover = True
    snap2 = ic2._drag_snapshot()
    img2 = snap2.toImage()
    n2 = sum(1 for y in range(img2.height()) for x in range(img2.width())
             if img2.pixelColor(x, y).alpha() > 8)
    check("P5a 应用图标快照非空且无背景框",
          n2 > 50 and all(a == 0 for a in corner_alphas(snap2)),
          "opaque=%d corners=%s" % (n2, corner_alphas(snap2)))

    n1 = sum(1 for y in range(img.height()) for x in range(img.width())
             if img.pixelColor(x, y).alpha() > 8)
    check("P5b 文件夹瓷砖快照非空（迷你图标矩阵保留）", n1 > 100,
          "opaque=%d" % n1)

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
