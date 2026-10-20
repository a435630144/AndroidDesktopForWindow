# -*- coding: utf-8 -*-
"""悬停推让：停够 PUSH_DWELL_MS 才把占位者挤走（2026-10-19 反馈 9）。

用户原话："手机逻辑是图标在边缘重叠并悬浮一段时间，会实时把对方挤走
（目前的效果是只有松手的时候才会挤走）。"

设计折中：立刻挤走会让人来不及看清「松手合并」提示（反馈 4 的病），
完全不挤又违背手机直觉。所以给一个 dwell：

  P1 拖到被占格 -> 立刻不动（只武装计时器），布局原样
  P2 停够 dwell -> 占位者被挤走，拖动者占住目标格
  P3 快速划过（下一次 dragMove 落到空格）-> 计时器撤销，不挤人
  P4 松手前 _cancel_push() -> 计时器撤销，等再久也不动
  P5 挤走之后两图标格不同（绝不堆叠）
  P6 目标格本来就空 -> 立即预览让位，不用等 dwell
  P7 双区模型常量契约（2026-10-21 反馈 7：核心区 / 滞回 / 门槛）

2026-10-21 反馈 7 起，"什么时候该挤走"由 iconwidget 双区模型路由
（拖影中心在目标核心区外才到得了本窗口的 dragMove），本文件只锁
推让时序与常量契约；状态机验收在 tests/test_edge_push.py。

运行：python tests/test_push_dwell.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from src import drag_merge
from src import grid_flow
from src.desktop_window import PUSH_DWELL_MS, DesktopWindow
from src.iconwidget import DWELL_MERGE_MS
from src.storage import Storage

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_push_dwell_state.json"
failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=60):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make_state():
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = False
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["settings"]["auto_arrange"] = False
    st._data["widgets"] = []
    st._data["layout"] = [
        {"id": eid, "type": "app", "apps": None,
         "app": {"id": eid, "name": eid, "target": eid, "kind": "app"},
         "col": col, "row": 0}
        for eid, col in (("a", 0), ("b", 1), ("c", 2))
    ]
    st.save()
    return st


def cell_of(st, eid):
    e = st.find_entry(eid)
    return (int(e["col"]), int(e["row"])) if e else None


def new_window(app, st):
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    settle(app, 80)
    return w


def main(app):
    st = make_state()
    w = new_window(app, st)
    check("P0 初始 a/b/c 在 (0,0)/(1,0)/(2,0)",
          [cell_of(st, k) for k in ("a", "b", "c")]
          == [(0, 0), (1, 0), (2, 0)],
          "%s" % [cell_of(st, k) for k in ("a", "b", "c")])
    # 2026-10-20 用户反馈 F3：推让延时**必须晚于**合并提示（450ms），
    # 否则"想合并却先被挤走"；但也不该长到让人以为卡住。
    check("P0 推让延时晚于合并提示且不超过 1.2s（提示先出现）",
          DWELL_MERGE_MS < PUSH_DWELL_MS <= 1200,
          "push=%d dwell=%d" % (PUSH_DWELL_MS, DWELL_MERGE_MS))
    # 2026-10-21 反馈 7：双区模型常量（指导文档 v7 §5.2）
    check("P7a 核心区占比落在 (0.4, 0.8)",
          0.4 < drag_merge.MERGE_CORE_RATIO < 0.8,
          "core=%s" % drag_merge.MERGE_CORE_RATIO)
    check("P7b 滞回带够小且不把核心区吃光",
          0 < drag_merge.MERGE_CORE_HYSTERESIS < 0.1
          and drag_merge.MERGE_CORE_RATIO - drag_merge.MERGE_CORE_HYSTERESIS > 0.4,
          "hyst=%s" % drag_merge.MERGE_CORE_HYSTERESIS)
    check("P7c 门槛低于核心区半径（擦边即可进让位区）",
          0 < drag_merge.MERGE_ARM_RATIO < drag_merge.MERGE_CORE_RATIO,
          "arm=%s core=%s" % (drag_merge.MERGE_ARM_RATIO,
                              drag_merge.MERGE_CORE_RATIO))

    # ---------- P1：拖到被占格 -> 立刻不动 ----------
    w._reflow_preview("c", (0, 0))
    settle(app, 60)
    check("P1 刚压上去不动（先让人看清合并提示）",
          cell_of(st, "a") == (0, 0) and cell_of(st, "c") == (2, 0),
          "a=%s c=%s" % (cell_of(st, "a"), cell_of(st, "c")))
    check("P1 推让计时器已武装", w._push_timer.isActive())

    # ---------- P2：停够 dwell -> 挤走 ----------
    settle(app, PUSH_DWELL_MS + 120)
    a_cell, c_cell = cell_of(st, "a"), cell_of(st, "c")
    check("P2 悬停够久后占位者被挤走",
          a_cell != (0, 0), "a=%s" % (a_cell,))
    check("P2 拖动者占住目标格", c_cell == (0, 0), "c=%s" % (c_cell,))
    check("P5 挤走后两图标不重叠", a_cell != c_cell,
          "a=%s c=%s" % (a_cell, c_cell))

    # ---------- P3：快速划过不挤人 ----------
    st2 = make_state()
    w2 = new_window(app, st2)
    w2._reflow_preview("c", (0, 0))      # 压上 a
    settle(app, 30)
    w2._reflow_preview("c", (0, 6))      # 立刻划到空格
    settle(app, 30)
    check("P3 划到空格后计时器撤销", not w2._push_timer.isActive())
    settle(app, PUSH_DWELL_MS + 120)
    check("P3 快速划过后原占位者没被动过",
          cell_of(st2, "a") == (0, 0), "a=%s" % (cell_of(st2, "a"),))
    # 划过后 c 自己应落在空格上（立即预览）
    check("P3 落到空格立即生效（不等 dwell）",
          cell_of(st2, "c") == (0, 6), "c=%s" % (cell_of(st2, "c"),))

    # ---------- P4：松手取消 ----------
    st3 = make_state()
    w3 = new_window(app, st3)
    w3._reflow_preview("c", (0, 0))
    settle(app, 40)
    w3._cancel_push()
    check("P4 松手后计时器撤销", not w3._push_timer.isActive())
    settle(app, PUSH_DWELL_MS + 150)
    check("P4 松手后占位者不再移动", cell_of(st3, "a") == (0, 0),
          "a=%s" % (cell_of(st3, "a"),))

    # ---------- P6：目标格为空 -> 立即让位 ----------
    st4 = make_state()
    w4 = new_window(app, st4)
    w4._reflow_preview("c", (0, 8))
    settle(app, 40)
    check("P6 空格立即落位（不武装计时器）",
          cell_of(st4, "c") == (0, 8) and not w4._push_timer.isActive(),
          "c=%s active=%s" % (cell_of(st4, "c"), w4._push_timer.isActive()))

    for win in (w, w2, w3, w4):
        win.close()

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL push_dwell PASSED")
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
    try:
        STATE.unlink()
    except Exception:
        pass
    return code


if __name__ == "__main__":
    sys.exit(run_main())
