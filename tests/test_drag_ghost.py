# -*- coding: utf-8 -*-
"""v6 批次 B③ §5.1：拖动保留原始样式——render 快照 + 0.8 半透明。

覆盖指导文档_网格与无界双模式_v6.md §5.1（反馈 6）：
  D1 _drag_snapshot() 快照有内容（图标区非透明像素过阈值）
  D2 快照半透明 0.8：对全不透明 render 像素，快照 alpha ≈ 204
  D3 _exec_drag 集成：拖影快照非空——顺序 bug 回归防线
     （旧代码 set_drag_ghost(True) 先于 render，虚影态 paintEvent
     早退 -> 快照全透明空图，用户看不到自己拖的是什么）

运行：python tests/test_drag_ghost.py   （offscreen）
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPixmap
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


def to_image(pm):
    return pm.toImage()


def main(app):
    lay = gs.icon_layout(83, 102, "medium")
    ic = AppIcon(folder_entry(), 0, layout=lay)

    # ---------- D1：快照有内容 ----------
    snap = ic._drag_snapshot()
    img = snap.toImage()
    n_opaque = 0
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() > 8:
                n_opaque += 1
    check("D1 拖动快照有内容（非空 render）", n_opaque > 100,
          "opaque=%d size=%s" % (n_opaque, snap.size()))

    # ---------- D2：快照半透明 0.8 ----------
    # 参照：全不透明 render（不走 _drag_snapshot 的衰减）
    ref = QPixmap(ic.size())
    ref.fill(Qt.transparent)
    ic.render(ref)
    ref_img = ref.toImage()
    snap_img = snap.toImage()
    pairs = []
    for y in range(ref_img.height()):
        for x in range(ref_img.width()):
            a = ref_img.pixelColor(x, y).alpha()
            if a > 250:      # 只比对原本全不透明的像素（瓷砖/标签实心区）
                pairs.append((a, snap_img.pixelColor(x, y).alpha()))
    ok_alpha = bool(pairs) and all(abs(s - round(r * 0.8)) <= 2
                                   for r, s in pairs)
    check("D2 快照 alpha = 0.8 × 原 alpha（约 204）", ok_alpha,
          "n=%d sample=%s" % (len(pairs), pairs[:3]))

    # ---------- D3：_exec_drag 集成（顺序 bug 回归） ----------
    ic._press_pos = QPoint(10, 10)
    ic.grabMouse = lambda: None      # offscreen 不真抓鼠标
    ic.setFocus = lambda: None
    ic._exec_drag()
    ghost = ic._drag_ghost_w
    check("D3 拖影已创建", ghost is not None)
    if ghost is not None:
        gimg = ghost._pm.toImage()
        g_opaque = sum(1 for y in range(gimg.height())
                       for x in range(gimg.width())
                       if gimg.pixelColor(x, y).alpha() > 8)
        check("D3 拖影快照非空（render 先于虚影态）", g_opaque > 100,
              "opaque=%d" % g_opaque)
    # 清理：撤拖影（_after_drag 依赖 dragFinished 连接前的状态，直关即可）
    if ghost is not None:
        ghost.close()

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL drag_ghost PASSED")
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
