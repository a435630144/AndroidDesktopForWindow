# -*- coding: utf-8 -*-
"""probe17：M2 reflow_moves 集成验证（2026-10-18，指导文档 §2.3 验收）。

安全铁律（继承 probe14/15/16）：
  - offscreen 平台 + 临时 state.json，绝不碰用户真实状态与桌面
  - 不调用 show_desktop()（不挂桌面带、不隐藏原生图标）
  - try/finally + 看门狗 + 幂等收尾，保证进程必退

断言（§2.3 验收标准）：
  S0  GridMetrics 就绪（1920x1040 -> 19 列 8 行）
  S1  单格微移只动 1~2 个图标；位移图标弹簧滑到新格；无重叠
  S2  取消（拖出窗口/松手无落点）：布局回滚 + 全体滑回原位
  S3  拖到空格精确落点：dragged 落 target，洞随拖动平移，run 外不动
  S4  hover 全局坐标路径：mapFromGlobal 反算格点 = 所见格（无追逐漂移）
  S5  提交落盘 + Ctrl+Z 撤销（快照栈回退 + 滑回动画）
  S6  50 轮随机落点压力：dragged 精确落点、任何时刻无重叠
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QEventLoop, QPoint, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.desktop_window import DesktopWindow
from src.storage import Storage

W, H = 1920, 1040  # 100% DPI 工作区（验收场景：19 列 8 行）
STATE = Path(tempfile.gettempdir()) / "probe17_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra), flush=True)
    if not cond:
        failures.append(name)


def settle(app, ms=400):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make_state(spec, auto_arrange=True):
    """spec: [(id, col, row), ...] -> (Storage, path)。禁用自动克隆/隐藏图标。

    v6 §3.2：默认 auto_arrange=False（自由移动）；本探针是 M2 递进
    让位的专用验证，显式设 True 继续锁定递进算法（free 语义由
    tests/test_free_move.py 锁定）。
    """
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = False
    # 2026-10-19 反馈 3：未接管会自动进入无界模式，网格让位探针
    # 必须显式声明「按接管语义」（不 show 窗口，不会真隐藏原生图标）
    st._data["settings"]["takeover_desktop"] = True
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["settings"]["auto_arrange"] = bool(auto_arrange)
    st._data["widgets"] = []  # 清空默认组件：S1-S6 测纯图标让位
    st._data["layout"] = [
        {"id": i, "type": "app",
         "app": {"name": i, "target": i, "kind": "app"},
         "col": c, "row": r}
        for i, c, r in spec]
    st.save()
    return st


def by_id(st):
    return {e["id"]: (int(e["col"]), int(e["row"])) for e in st.layout}


def cells_of(st):
    return sorted((int(e["col"]), int(e["row"])) for e in st.layout)


def icon_at(w, eid, ox, oy, cw, ch, tol=2):
    """图标是否落在自己的格点上（含反馈 1 的格内居中留白）。"""
    icon = w.icons.get(eid)
    if icon is None:
        return False
    entry = w.storage.find_entry(eid)
    if entry is None:
        return False
    c, r = int(entry["col"]), int(entry["row"])
    dx, dy = grid_flow.icon_center_offset(w.storage)
    return (abs(icon.x() - (ox + c * cw + dx)) <= tol
            and abs(icon.y() - (oy + r * ch + dy)) <= tol)


def run(app):
    st = make_state([("a", 0, 0), ("b", 1, 0), ("c", 2, 0),
                     ("d", 3, 0), ("e", 4, 0), ("f", 5, 0)])
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    settle(app, 100)

    m = grid_flow.current_metrics()
    cw, ch = grid_flow.cell_size(st)
    ox, oy = grid_flow.origin()
    # v6 批次 A：cell 屏幕驱动（grid_sizing），1920x1040 -> cell 75x92
    # -> cols=(1920-52)//75=24, rows=(1040-44)//92=10（旧 icon 派生为
    # 96x114/19x8，断言已按新几何动态化）
    check("S0 GridMetrics 就绪（屏幕驱动几何）",
          m is not None and m.cols == (1920 - 52) // m.cw
          and m.rows == (1040 - 44) // m.ch and m.cols >= 20 and m.rows >= 8,
          "cols=%s rows=%s cell=%s origin=%s" % (
              m.cols if m else None, m.rows if m else None, (cw, ch), (ox, oy)))
    check("S0 图标已按网格落位",
          all(icon_at(w, eid, ox, oy, cw, ch) for eid in "abcdef"))

    orig = by_id(st)

    # ---------- S1：悬停占用格不抢走目标；松手才相邻交换 ----------
    # 2026-10-19 反馈 4：拖到图标上时若实时让位，目标会瞬间弹走，
    # 「松手合并为文件夹」提示永远出不来。占用格改为"松手才换"。
    w._on_drag_started()
    w._reflow_preview("c", (3, 0))  # 拖 c 悬停在 d 上
    check("S1 悬停占用格：布局不动（保住合并提示）",
          by_id(st) == orig, "%s" % by_id(st))
    w._reflow_commit_or_compute("c", (3, 0))   # 松手：交换
    b = by_id(st)
    check("S1b 松手后相邻交换（c→(3,0)、d→(2,0)）",
          b["c"] == (3, 0) and b["d"] == (2, 0)
          and b["a"] == (0, 0) and b["b"] == (1, 0)
          and b["e"] == (4, 0) and b["f"] == (5, 0), "%s" % b)
    check("S1c 任何时刻无重叠", len(cells_of(st)) == 6)
    settle(app, 500)
    check("S1d 位移图标弹簧滑到新格（c 除外——它正被拖动）",
          all(icon_at(w, eid, ox, oy, cw, ch) for eid in "abdef"))
    orig = by_id(st)      # 交换已提交，S2 的"拖动前"基准随之更新
    w._on_drag_started()
    w._reflow_preview("a", (6, 0))            # 空格：递进预览
    w._cancel_preview()
    check("S1e 空格预览取消后布局回滚", by_id(st) == orig)

    # ---------- S2：取消（拖出窗口/松手无落点）全体滑回 ----------
    w._on_drag_started()
    w._reflow_preview("a", (5, 2))  # 拖到远处空格
    check("S2 预览已改动布局", by_id(st) != orig)
    w._on_drag_finished()           # 无落点 -> 回退
    check("S2 拖出窗口：布局回滚到拖动前", by_id(st) == orig)
    settle(app, 500)
    check("S2 全体图标滑回原位",
          all(icon_at(w, eid, ox, oy, cw, ch) for eid in "abcdef"))

    # ---------- S3：拖到空格精确落点 ----------
    st2 = make_state([("a", 0, 0), ("b", 1, 0), ("c", 2, 0), ("e", 4, 0)])
    w2 = DesktopWindow(st2)
    w2.resize(W, H)
    w2._update_grid_metrics()
    settle(app, 100)
    orig2 = by_id(st2)
    w2._on_drag_started()
    w2._reflow_preview("a", (3, 0))  # 空格 (3,0)
    b2 = by_id(st2)
    check("S3 dragged 精确落到空格 (3,0)", b2["a"] == (3, 0), "%s" % b2)
    check("S3 b/c 前移补位、e 不动",
          b2["b"] == (0, 0) and b2["c"] == (1, 0) and b2["e"] == (4, 0))
    check("S3 洞随拖动平移到 (2,0)", (2, 0) not in cells_of(st2))
    check("S3 无重叠", len(cells_of(st2)) == 4)
    settle(app, 500)
    check("S3 位移图标滑到新格",
          all(icon_at(w2, eid, ox, oy, cw, ch) for eid in "bce"))

    # ---------- S4：hover 全局坐标路径（消灭追逐漂移） ----------
    w2._cancel_preview()
    check("S4 取消回到原布局", by_id(st2) == orig2)
    w2._on_drag_started()
    # 取格子**内部**点（偏移 1/4 格）：取中心 (cw//2) 会正好落在 3.5 格
    # 边界上，round() 银行家舍入到邻格（M1 踩过的坑，勿重犯）
    g = w2.mapToGlobal(QPoint(ox + 3 * cw + cw // 4, oy + ch // 4))  # (3,0) 内部
    w2._on_reflow_hover("a", g.x(), g.y())
    b2 = by_id(st2)
    check("S4 全局坐标反算格点 = 所见格 (3,0)",
          b2["a"] == (3, 0) and b2["b"] == (0, 0) and b2["c"] == (1, 0),
          "%s" % b2)

    # ---------- S5：提交落盘 + Ctrl+Z ----------
    w2._commit_preview()
    reloaded = Storage(path=str(STATE))
    check("S5 提交已落盘", by_id(reloaded)["a"] == (3, 0))
    check("S5 撤销栈压入 1 步", len(w2._undo_stack) == 1)
    ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Z, Qt.ControlModifier)
    w2.keyPressEvent(ev)
    check("S5 Ctrl+Z 布局回退到拖动前", by_id(st2) == orig2)
    check("S5 撤销栈已弹出", len(w2._undo_stack) == 0)
    reloaded2 = Storage(path=str(STATE))
    check("S5 撤销也落盘", by_id(reloaded2) == orig2)
    settle(app, 500)
    check("S5 图标滑回原位",
          all(icon_at(w2, eid, ox, oy, cw, ch) for eid in "abce"))

    # ---------- S6：随机落点压力（集成层） ----------
    import random
    rng = random.Random(20261018)
    ok = True
    for i in range(50):
        spec = [(("i%d" % k), c, r) for k, (c, r) in enumerate(
            rng.sample([(c, r) for r in range(3) for c in range(19)], 8))]
        stx = make_state(spec)
        wx = DesktopWindow(stx)
        wx.resize(W, H)
        wx._update_grid_metrics()
        did = rng.choice([s[0] for s in spec])
        tgt = (rng.randrange(19), rng.randrange(3))
        wx._on_drag_started()
        # 占用格不实时预览（反馈 4），压力测试走松手提交路径
        wx._reflow_commit_or_compute(did, tgt)
        b = by_id(stx)
        tc = max(0, min(18, tgt[0]))
        tr = max(0, tgt[1])
        if b.get(did) != (tc, tr) or len(cells_of(stx)) != 8:
            ok = False
            print("  round %d FAIL: did=%s tgt=%s got=%s" % (i, did, tgt, b.get(did)),
                  flush=True)
        wx.deleteLater()
    check("S6 50 轮随机落点：dragged 精确落点 + 无重叠", ok)


def main():
    app = QApplication([])
    # 看门狗：任何卡死 60s 内强制退出（探针必须能退）
    wd = QTimer()
    wd.setSingleShot(True)
    wd.timeout.connect(lambda: (print("!! 看门狗超时", flush=True), os._exit(3)))
    wd.start(60000)
    try:
        run(app)
    except Exception:
        import traceback
        traceback.print_exc()
        failures.append("run() 异常")
    finally:
        try:
            STATE.unlink()
        except Exception:
            pass
    print("-" * 56, flush=True)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures), flush=True)
        code = 1
    else:
        print("ALL probe17 PASSED", flush=True)
        code = 0
    print("==== 探针退出 ====", flush=True)
    # 干净退出：先让挂起的 deleteLater 与动画对象销毁完再退。
    # （直接 os._exit 与原生拆解竞态，触发 access violation 噪声）
    app.processEvents()
    QTimer.singleShot(80, app.quit)
    app.exec()
    return code


if __name__ == "__main__":
    sys.exit(main())
