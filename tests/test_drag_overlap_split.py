# -*- coding: utf-8 -*-
"""拖放命中：双区模型分流（2026-10-21 反馈 7 = v7 指导文档 §5.2）。

用户原话："现在加入文件夹的判定范围太大了，且没有了边缘判定为碰撞时候的
实时挤开效果。"

旧实现只看**指针**落在谁身上（反馈 9 之前），后改按**重叠比例**一刀切
（2026-10-20 F3：MERGE_OVERLAP_RATIO=0.30 判合并）。一刀切的两个病根
正对反馈 7：0.30 时刚擦上去就弹合并提示（判定范围太大）；0.15~0.30 被
defers_push 整体 defer，挤走路径整个死掉（实时挤开效果没了）。

现在按**拖影中心**落在目标图标哪个区判定（双区模型）：

    中心在核心区（目标中心 55% 内缩矩形）-> 合并目标（dragEnter 武装 dwell）
    中心在核心区外（让位区）              -> 桌面窗口（悬停够久挤走）
    重叠比只当"是否压在图标上"的门槛（MERGE_ARM_RATIO=0.15）

  O1 完全重合 -> ratio ≈ 1，中心在核心区
  O2 只擦一条边（约 6px）-> ratio < 门槛，不进双区
  O3 中心压住（重叠 0.85，中心在内）-> _hit_target 返回目标图标
  O3b 重叠 0.70 但中心在核心区外 -> _hit_target 返回桌面窗口
      （旧 0.30 阈值下这是"合并候选"——反馈 7 要的正是收紧这里）
  O4 边缘擦碰 -> _hit_target 返回桌面窗口（实时挤走语义）
  O5 文件夹成员不参与桌面合并

运行：python tests/test_drag_overlap_split.py   （offscreen）
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QWidget

from src import drag_merge
from src import grid_sizing as gs
from src.iconwidget import AppIcon

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def entry(eid, name):
    return {"id": eid, "type": "app", "name": name,
            "app": {"id": eid, "name": name, "target": eid, "kind": "app"}}


class Ghost(QWidget):
    """最小拖影替身：窗口标志与真实 _DragGhost 一致（ToolTip+Frameless），
    否则带边框窗的客户区原点相对 move() 有偏移，重叠几何会整体漂几像素。"""

    def __init__(self, w, h):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
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
    # 目标全局原点：拖影一律**相对它**放置。宿主窗在 offscreen 下的原点
    # 不保证是 (0,0)，写死绝对坐标会让重叠比整体漂（O1 曾因此 0.938）。
    T = tgt.mapToGlobal(QPoint(0, 0))

    # ---------- O1 完全重合 ----------
    place(src, ghost, T.x(), T.y())
    r1 = src._overlap_ratio(tgt)
    check("O1 完全重合 ratio ≈ 1", abs(r1 - 1.0) < 0.02, "ratio=%.3f" % r1)

    # ---------- O2 只擦一条边 ----------
    place(src, ghost, T.x() + W - 6, T.y())
    r2 = src._overlap_ratio(tgt)
    check("O2 边缘擦碰（≈6px）ratio < 门槛（不进双区）",
          0 < r2 < drag_merge.MERGE_ARM_RATIO,
          "ratio=%.3f" % r2)

    # ---------- O3 中心压住 -> 合并 ----------
    place(src, ghost, T.x() + W - int(W * 0.85), T.y())
    r3 = src._overlap_ratio(tgt)
    best, best_r = src._best_overlap_icon()
    hit = src._hit_target(ghost.mapToGlobal(QPoint(W // 2, H // 2)))
    check("O3 中心重叠 ratio >= 门槛", r3 >= drag_merge.MERGE_ARM_RATIO,
          "ratio=%.3f thr=%.2f" % (r3, drag_merge.MERGE_ARM_RATIO))
    check("O3 _best_overlap_icon 命中目标", best is tgt,
          "best=%s r=%.3f" % (best, best_r))
    check("O3 _hit_target 返回目标图标（武装 dwell 合并）", hit is tgt,
          "%s" % (hit,))

    # ---------- O3b 重叠够大但中心在核心区外 -> 让位区 ----------
    # 反馈 7 的回归点：旧 0.30 阈值下 60% 重叠就算合并候选（"判定范围
    # 太大"）；双区模型按中心判，中心在核心区外（连滞回外扩后也在外）
    # -> 交给桌面挤走。
    place(src, ghost, T.x() + W - int(W * 0.60), T.y())
    r3b = src._overlap_ratio(tgt)
    hit3b = src._hit_target(ghost.mapToGlobal(QPoint(W // 2, H // 2)))
    check("O3b 重叠 0.60 但中心在核心区外 -> 不让位给合并",
          hit3b is not tgt, "ratio=%.3f" % r3b)
    check("O3b 落到桌面窗口（实时挤走语义）", hit3b is host,
          "%s" % (hit3b,))

    # ---------- O4 边缘擦碰 -> 交给桌面挤走 ----------
    place(src, ghost, T.x() + W - 6, T.y())
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
    ghost.move(T.x(), T.y())
    best2, r_best2 = inner._best_overlap_icon()
    check("O5 文件夹成员不参与合并（比例仍可算但命中不选它）",
          best2 is None or best2 is not inner,
          "best=%s r=%.3f" % (best2, r_best2))

    # 硬断言：附近只剩文件夹成员时，候选必须为空（成员永不作为桌面合并目标）
    tgt.hide()
    src._drag_ghost_w = ghost
    ghost.move(T.x(), T.y())
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
