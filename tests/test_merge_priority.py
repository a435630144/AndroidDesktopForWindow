# -*- coding: utf-8 -*-
"""合并提示必须优先于挤走（2026-10-20 用户反馈 F3）。

现象：想把 A 拖到 B 上合并成文件夹，**提示还没出现 B 就被挤走了**。

病根两处叠加：
  1. `MERGE_OVERLAP_RATIO = 0.45` —— 拖影与目标重叠不足 45% 就判成"擦边"，
     这类拖动落到桌面窗口走让位逻辑（用户的直觉是"叠上去就该合并"）；
  2. `PUSH_DWELL_MS = 260` **小于** `DWELL_MERGE_MS = 450` —— 即使判成
     合并候选，只要拖影抖动一下掉回"擦边"，260ms 就把目标推走了，
     450ms 的合并提示永远等不到。

契约：
  M1 推让延时 > 合并提示延时（提示先出现）
  M2 阈值关系：MERGE_ARM_RATIO < MERGE_OVERLAP_RATIO 且在合理区间
  M3 overlap_ratio 纯函数：包含 / 无交 / 半叠三种情形
  M4 defers_push：实质重叠 -> 暂缓挤走，微弱交集 -> 照常挤走
  M5 窗口级：拖影压住目标时不武装推让计时器；只擦边时才武装
  M6 窗口级：压住目标后等推让超时，目标**不被挤走**（布局不变）

运行：python tests/test_merge_priority.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QPoint, QRect, QTimer
from PySide6.QtWidgets import QApplication

from src import drag_merge, grid_flow
from src.desktop_window import PUSH_DWELL_MS, DesktopWindow
from src.iconwidget import DWELL_MERGE_MS, MERGE_OVERLAP_RATIO
from src.storage import Storage

STATE = Path(tempfile.gettempdir()) / "test_merge_priority_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=120):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make_state(layout):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"].update({
        "hide_native_icons": False,
        "auto_clone_desktop": False,
        "takeover_desktop": True,
        "layout_mode": "grid",
        "auto_arrange": False,
        "dev_mode": False,
    })
    st._data["widgets"] = []
    st._data["layout"] = [dict(e) for e in layout]
    st.save()
    return st


def cell_global(w, col, row):
    x, y = w._entry_pos({"col": col, "row": row})
    return w.mapToGlobal(QPoint(int(x + 20), int(y + 20)))


def cell_size(w):
    m = grid_flow.current_metrics()
    return (m.cw, m.ch) if m else (80, 100)


def main(app):
    # ---------- M1/M2：常量契约 ----------
    check("M1 推让延时晚于合并提示（提示先出现）",
          PUSH_DWELL_MS > DWELL_MERGE_MS,
          "push=%d dwell=%d" % (PUSH_DWELL_MS, DWELL_MERGE_MS))
    check("M1 推让留出至少 200ms 余量", PUSH_DWELL_MS - DWELL_MERGE_MS >= 200,
          "gap=%d" % (PUSH_DWELL_MS - DWELL_MERGE_MS))
    check("M2 MERGE_OVERLAP_RATIO 落在 0.2~0.4（压上去就算合并）",
          0.2 <= MERGE_OVERLAP_RATIO <= 0.4,
          "ratio=%s" % MERGE_OVERLAP_RATIO)
    check("M2 MERGE_ARM_RATIO 严格小于合并阈值",
          0 < drag_merge.MERGE_ARM_RATIO < MERGE_OVERLAP_RATIO,
          "arm=%s merge=%s" % (drag_merge.MERGE_ARM_RATIO, MERGE_OVERLAP_RATIO))
    check("M2 iconwidget 的阈值与 drag_merge 同源（单点定义）",
          MERGE_OVERLAP_RATIO == drag_merge.MERGE_OVERLAP_RATIO,
          "icon=%s module=%s" % (MERGE_OVERLAP_RATIO,
                                 drag_merge.MERGE_OVERLAP_RATIO))

    # ---------- M3：overlap_ratio 纯函数 ----------
    a = (0, 0, 100, 100)
    check("M3a 完全包含 = 1.0",
          abs(drag_merge.overlap_ratio(a, (10, 10, 80, 80)) - 1.0) < 1e-6,
          "%.4f" % drag_merge.overlap_ratio(a, (10, 10, 80, 80)))
    check("M3b 无交集 = 0.0",
          drag_merge.overlap_ratio(a, (200, 200, 100, 100)) == 0.0)
    check("M3c 半叠（按较小矩形面积归一）= 0.5",
          abs(drag_merge.overlap_ratio(a, (50, 0, 100, 100)) - 0.5) < 1e-6,
          "%.4f" % drag_merge.overlap_ratio(a, (50, 0, 100, 100)))

    # ---------- M4：defers_push ----------
    check("M4a 实质重叠 -> 暂缓挤走",
          drag_merge.defers_push(0.20) is True)
    check("M4b 刚好到阈值 -> 暂缓挤走",
          drag_merge.defers_push(drag_merge.MERGE_ARM_RATIO) is True)
    check("M4c 微弱交集 -> 照常挤走",
          drag_merge.defers_push(0.05) is False)
    check("M4d 零重叠 -> 照常挤走", drag_merge.defers_push(0.0) is False)

    # ---------- 窗口级构造 ----------
    st = make_state([
        {"id": "a", "type": "app", "col": 0, "row": 0, "app": {"name": "A"}},
        {"id": "b", "type": "app", "col": 1, "row": 0, "app": {"name": "B"}},
        {"id": "c", "type": "app", "col": 0, "row": 1, "app": {"name": "C"}},
    ])
    w = DesktopWindow(st)
    w.resize(520, 420)
    w._update_grid_metrics()
    w.rebuild()
    settle(app, 150)
    cw, ch = cell_size(w)
    check("M0 窗口与图标就绪", "a" in w.icons and "b" in w.icons,
          "cw=%s ch=%s" % (cw, ch))

    # ---------- M5：压住目标 -> 不武装推让 ----------
    orig = w._drag_overlap_on_cell
    try:
        w._drag_overlap_on_cell = lambda _d, _c, _r=None: 0.60   # 压住了
        w._push_cell = None
        g = cell_global(w, 1, 0)
        w._on_reflow_hover("a", int(g.x()), int(g.y()))
        check("M5a 拖影压住目标时不武装推让", w._push_cell is None,
              "push_cell=%s" % (w._push_cell,))

        w._drag_overlap_on_cell = lambda _d, _c, _r=None: 0.02   # 只擦边
        w._push_cell = None
        g2 = cell_global(w, 0, 1)
        w._on_reflow_hover("a", int(g2.x()), int(g2.y()))
        check("M5b 只擦边时武装推让", w._push_cell is not None,
              "push_cell=%s" % (w._push_cell,))

        # ---------- M6：压住状态下推让超时也不许挤走目标 ----------
        w._drag_overlap_on_cell = lambda _d, _c, _r=None: 0.60
        before = {(e["id"], int(e["col"]), int(e["row"])) for e in st.layout}
        g3 = cell_global(w, 1, 0)
        w._on_reflow_hover("a", int(g3.x()), int(g3.y()))
        settle(app, PUSH_DWELL_MS + 120)
        after = {(e["id"], int(e["col"]), int(e["row"])) for e in st.layout}
        check("M6 压住目标时推让超时也不挤走（布局不变）", before == after,
              "diff=%s" % (set(after) ^ set(before),))
    finally:
        w._drag_overlap_on_cell = orig

    # ---------- M7：拖影矩形与目标图标的真实重叠比 ----------
    tb = w.icons["b"]
    r_b = QRect(tb.mapToGlobal(QPoint(0, 0)), tb.size())
    full = QRect(r_b)
    half = QRect(r_b.left() + r_b.width() // 2, r_b.top(),
                 r_b.width(), r_b.height())
    far = QRect(r_b.left() + 4000, r_b.top(), r_b.width(), r_b.height())
    v_full = w._drag_overlap_on_cell("a", (1, 0), full)
    v_half = w._drag_overlap_on_cell("a", (1, 0), half)
    v_far = w._drag_overlap_on_cell("a", (1, 0), far)
    check("M7a 完全重合 -> 1.0", abs(v_full - 1.0) < 1e-6, "%.4f" % v_full)
    check("M7b 半幅重合 -> ~0.5", abs(v_half - 0.5) < 0.05, "%.4f" % v_half)
    check("M7c 完全分离 -> 0.0", v_far == 0.0, "%.4f" % v_far)
    check("M7d 无拖影且无注入 -> 0.0（照常推让）",
          w._drag_overlap_on_cell("a", (1, 0)) == 0.0)

    w.close()


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    crashed = None
    try:
        main(app)
    except Exception:
        import traceback
        traceback.print_exc()
        crashed = "exception"
    finally:
        print("")
        if crashed or failures:
            print("FAILED %d: %s" % (len(failures), failures))
            sys.stdout.flush()
            os._exit(1)
        print("ALL PASSED")
        sys.stdout.flush()
        os._exit(0)
