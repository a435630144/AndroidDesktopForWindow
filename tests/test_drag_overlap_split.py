# -*- coding: utf-8 -*-
"""拖放命中：按**重叠比例**分流（2026-10-19 反馈 9）。

用户原话："手机逻辑是图标在边缘重叠并悬浮一段时间，会实时把对方挤走；
在中间会生成文件夹。项目基本实现，但有时明明已经重叠了，却没提示创建
文件夹。"

病根：旧实现只看**指针**落在谁身上。抓图标角落拖动时，指针与图标本体
错位——已经叠上了指针还在外面（该合并却不提示），或者刚擦边指针就进去
了（不该合并却弹提示）。

现在以拖影（= 被拖图标本体）与目标的**相交比例**判定，阈值
MERGE_OVERLAP_RATIO = 0.45：

  O1 完全重合 -> ratio ≈ 1
  O2 只擦一条边（约 10%）-> ratio < 阈值
  O3 中心压住（>45%）-> _hit_target 返回目标图标（发 dragEnter 武装 dwell）
  O4 边缘擦碰（<45%）-> _hit_target 返回桌面窗口（悬停够久挤走对方）
  O5 文件夹成员不参与桌面合并

运行：python tests/test_drag_overlap_split.py   （offscreen）
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QWidget

from src import grid_sizing as gs
from src.iconwidget import MERGE_OVERLAP_RATIO, AppIcon

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def entry(eid, name):
    return {"id": eid, "type": "app", "name": name,
            "app": {"id": eid, "name": name, "target": eid, "kind": "app"}}


class Ghost(QWidget):
    """最小拖影替身：只要 mapToGlobal + size 正确即可。"""

    def __init__(self, w, h):
        super().__init__(None)
        self.setFixedSize(w, h)


def place(src, ghost, x, y):
    ghost.move(x, y)
    ghost.show()
    src._drag_ghost_w = ghost


def main(app):
    lay = gs.icon_layout(83, 102, "medium")
    host = QWidget()
    host.resize(900, 600)
    host.show()

    tgt = AppIcon(entry("t", "目标"), 0, layout=lay)
    tgt.setParent(host)
    tgt.move(100, 100)
    tgt.show()

    src = AppIcon(entry("s", "源"), 0, layout=lay)
    src.setParent(host)
    src.move(400, 400)
    src.show()
    app.processEvents()

    W, H = tgt.width(), tgt.height()
    ghost = Ghost(W, H)

    # ---------- O1 完全重合 ----------
    place(src, ghost, 100, 100)
    r1 = src._overlap_ratio(tgt)
    check("O1 完全重合 ratio ≈ 1", abs(r1 - 1.0) < 0.02, "ratio=%.3f" % r1)

    # ---------- O2 只擦一条边 ----------
    place(src, ghost, 100 + W - 6, 100)
    r2 = src._overlap_ratio(tgt)
    check("O2 边缘擦碰（≈6px）ratio < 阈值", 0 < r2 < MERGE_OVERLAP_RATIO,
          "ratio=%.3f" % r2)

    # ---------- O3 中心压住 -> 合并 ----------
    place(src, ghost, 100 + W - int(W * 0.7), 100)
    r3 = src._overlap_ratio(tgt)
    best, best_r = src._best_overlap_icon()
    hit = src._hit_target(ghost.mapToGlobal(QPoint(W // 2, H // 2)))
    check("O3 中心重叠 ratio >= 阈值", r3 >= MERGE_OVERLAP_RATIO,
          "ratio=%.3f thr=%.2f" % (r3, MERGE_OVERLAP_RATIO))
    check("O3 _best_overlap_icon 命中目标", best is tgt,
          "best=%s r=%.3f" % (best, best_r))
    check("O3 _hit_target 返回目标图标（武装 dwell 合并）", hit is tgt,
          "%s" % (hit,))

    # ---------- O4 边缘擦碰 -> 交给桌面挤走 ----------
    place(src, ghost, 100 + W - 6, 100)
    gpos = ghost.mapToGlobal(QPoint(W // 2, H // 2))
    hit2 = src._hit_target(gpos)
    check("O4 擦边时 _hit_target 不是目标图标", hit2 is not tgt, "%s" % (hit2,))
    check("O4 擦边落到桌面窗口（实时挤走语义）", hit2 is host, "%s" % (hit2,))

    # ---------- O5 文件夹成员不参与桌面合并 ----------
    inner = AppIcon(entry("m", "成员"), 0, in_folder=True, layout=lay)
    inner.setParent(host)
    inner.move(100, 100)
    inner.show()
    inner._drag_ghost_w = ghost
    ghost.move(100, 100)
    best2, r_best2 = inner._best_overlap_icon()
    check("O5 文件夹成员不参与合并（比例仍可算但命中不选它）",
          best2 is None or best2 is not inner,
          "best=%s r=%.3f" % (best2, r_best2))

    # 硬断言：附近只剩文件夹成员时，候选必须为空（成员永不作为桌面合并目标）
    tgt.hide()
    src._drag_ghost_w = ghost
    ghost.move(100, 100)
    best3, r_best3 = src._best_overlap_icon()
    check("O5b 附近只有文件夹成员 -> 无合并候选", best3 is None,
          "best=%s r=%.3f" % (best3, r_best3))
    tgt.show()

    for w in (tgt, src, inner):
        w.close()
    ghost.close()
    host.close()

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL drag_overlap_split PASSED")
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
