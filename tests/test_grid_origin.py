# -*- coding: utf-8 -*-
"""v7 B1 · 网格原点：手动定位 / 夹紧 / 重置（T12，验收 O1~O8）。

**先红**（TDD）：`test_grid_dims` 已锁 `solve_dims(origin=...)` 的几何，
本文件锁的是**周边三件事**——storage 的两键写入与重置、`grid_flow`
快照跟随、桌面窗口的"取点态"（点图标不许启动应用）。

契约（v7 §3.2 + 反馈 21）：

  O1  自动模式原点 == 旧居中公式（回归锁，逐值相等）
  O2  手动原点精确生效（不被 edge 边距二次加上）
  O3  超界夹紧到 [0, 工作区 - 网格]（负值夹 0，超出夹右/下边界）
  O4  原点**只挪不缩放**：cols/rows/cw/ch 一个都不变
  O5  `grid_flow.origin()` 跟随 `GridMetrics` 快照（唯一几何来源）
  O6  极端遍历不越界：任意 origin × 任意分辨率 × native 32~96
  O7  取点态 `_picking_origin`：点图标**不**启动、不选中；非取点态照常启动
  O8  `reset_grid_origin()`：两键一起清空 -> 回居中（不是回 26/22）

运行：python tests/test_grid_origin.py      （offscreen）
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src import desktop_window, grid_flow, grid_metrics
from src import grid_sizing as gs
from src.desktop_window import DesktopWindow
from src.storage import Storage

W, H = 2048, 1152          # 本机工作区（逻辑像素，任务栏已扣除）
NATIVE = 48                # HKCU Bags\1\Desktop\IconSize
EDGE_X, EDGE_Y = 26, 22
UW, UH = W - 2 * EDGE_X, H - 2 * EDGE_Y
STATE = Path(tempfile.gettempdir()) / "test_grid_origin_state.json"

FAILED = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra), flush=True)
    if not cond:
        FAILED.append(name)


def settle(app, ms=60):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def app_entry(eid, name):
    return {"id": eid, "type": "app", "name": name,
            "app": {"id": eid, "name": name, "target": name, "kind": "app"},
            "col": 0, "row": 0}


def make_window(app):
    """最小桌面窗口：一个 app 条目、不读注册表（走 v6 兜底几何）。"""
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = True
    st._data["settings"]["takeover_desktop"] = True
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["settings"]["layout_mode"] = "grid"
    st._data["settings"]["icon_match_native"] = False
    st._data["widgets"] = []
    st._data["layout"] = [app_entry("a", "记事本")]
    st.save()
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    w.rebuild()
    settle(app)
    return w, st


# ============================ 几何（纯函数） ============================
def test_geometry():
    auto = gs.solve_dims(W, H, NATIVE)

    # ---------- O1：自动模式原点 = 居中公式（回归锁）----------
    check("O1 auto 原点 = 居中公式",
          (auto.ox, auto.oy) == (EDGE_X + (UW - auto.cols * auto.cw) // 2,
                                 EDGE_Y + (UH - auto.rows * auto.ch) // 2),
          "%s vs 居中公式" % ((auto.ox, auto.oy),))
    check("O1b auto 原点 = (58,30)", (auto.ox, auto.oy) == (58, 30),
          "got %s" % ((auto.ox, auto.oy),))

    # ---------- O2：手动原点精确生效 ----------
    m2 = gs.solve_dims(W, H, NATIVE, origin=(100, 50))
    check("O2 manual 原点精确 (100,50)", (m2.ox, m2.oy) == (100, 50),
          "got %s" % ((m2.ox, m2.oy),))

    # ---------- O3：超界夹紧 ----------
    m3a = gs.solve_dims(W, H, NATIVE, origin=(-50, -50))
    check("O3a 负值夹到 0", (m3a.ox, m3a.oy) == (0, 0),
          "got %s" % ((m3a.ox, m3a.oy),))
    m3b = gs.solve_dims(W, H, NATIVE, origin=(9999, 9999))
    check("O3b 超右夹到 W-cols*cw", m3b.ox == W - auto.cols * auto.cw,
          "%d vs %d" % (m3b.ox, W - auto.cols * auto.cw))
    check("O3c 超下夹到 H-rows*ch", m3b.oy == H - auto.rows * auto.ch,
          "%d vs %d" % (m3b.oy, H - auto.rows * auto.ch))
    check("O3d 夹紧后整块仍在屏内",
          m3b.ox + auto.cols * auto.cw <= W
          and m3b.oy + auto.rows * auto.ch <= H,
          "right=%d bottom=%d" % (m3b.ox + auto.cols * auto.cw,
                                  m3b.oy + auto.rows * auto.ch))

    # ---------- O4：只挪不缩放 ----------
    m4 = gs.solve_dims(W, H, NATIVE, origin=(0, 0))
    check("O4 原点不改 cols/rows/cw/ch",
          (auto.cols, auto.rows, auto.cw, auto.ch)
          == (m4.cols, m4.rows, m4.cw, m4.ch),
          "%s vs %s" % ((auto.cols, auto.rows, auto.cw, auto.ch),
                        (m4.cols, m4.rows, m4.cw, m4.ch)))
    check("O4b 原点不影响 cols_auto/rows_auto",
          (auto.cols_auto, auto.rows_auto) == (m4.cols_auto, m4.rows_auto),
          "%s vs %s" % ((auto.cols_auto, auto.rows_auto),
                        (m4.cols_auto, m4.rows_auto)))

    # ---------- O6：极端遍历不越界 ----------
    bad = []
    for (aw, ah) in ((1920, 1040), (2560, 1400), (1280, 720), (2048, 1152)):
        for npx in (32, 48, 64, 96):
            for org in ((-9999, -9999), (0, 0), (100, 50), (9999, 9999)):
                d = gs.solve_dims(aw, ah, npx, origin=org)
                if d.ox < 0 or d.oy < 0:
                    bad.append((aw, ah, npx, org, "neg", (d.ox, d.oy)))
                if d.ox + d.cols * d.cw > aw:
                    bad.append((aw, ah, npx, org, "x溢出", d.ox + d.cols * d.cw))
                if d.oy + d.rows * d.ch > ah:
                    bad.append((aw, ah, npx, org, "y溢出", d.oy + d.rows * d.ch))
    check("O6 极端遍历 64 组全部不越界", not bad, "bad=%s" % (bad[:3],))


# ============================ 快照跟随（O5） ============================
def test_snapshot_follow():
    saved = grid_flow._current_metrics
    # 干净 state：上一次运行留下的 icon_match_native=False 会让 compute 走
    # v6 屏幕驱动兜底（cell 83x102），几何与 solve_dims 完全不同
    if STATE.exists():
        STATE.unlink()
    try:
        base = Storage(path=str(STATE))
        base._data["settings"]["icon_match_native"] = True
        m = grid_metrics.compute(base, (W, H), native_px=NATIVE)
        grid_flow._current_metrics = m
        check("O5 grid_flow.origin() == 快照 ox/oy",
              grid_flow.origin() == (m.ox, m.oy),
              "%s vs %s" % (grid_flow.origin(), (m.ox, m.oy)))
        check("O5b 快照 cell_size 同源",
              grid_flow.cell_size(base) == (m.cw, m.ch),
              "%s vs %s" % (grid_flow.cell_size(base), (m.cw, m.ch)))
        # 手动原点经 storage 一路传到快照。注意 (120,60) 会被夹到
        # W-cols*cw（上限 116）——这里用**合法**值，夹紧行为已由 O3 单独锁定。
        if callable(getattr(base, "set_grid_origin", None)):
            base.set_grid_origin("manual", 100, 50)
            m2 = grid_metrics.compute(base, (W, H), native_px=NATIVE)
            check("O5c 手动原点穿透到快照", (m2.ox, m2.oy) == (100, 50),
                  "got %s" % ((m2.ox, m2.oy),))
        else:
            check("O5c 手动原点穿透到快照", False, "缺 Storage.set_grid_origin")
    finally:
        grid_flow._current_metrics = saved


# ============================ storage 两键与重置（O8） ============================
def test_storage_reset():
    st = Storage(path=str(STATE))
    has_set = callable(getattr(st, "set_grid_origin", None))
    has_reset = callable(getattr(st, "reset_grid_origin", None))
    has_mode = callable(getattr(st, "grid_origin_mode", None))
    check("O8a Storage.set_grid_origin 存在", has_set, "缺写入方法")
    check("O8b Storage.reset_grid_origin 存在", has_reset, "缺重置方法")
    check("O8c Storage.grid_origin_mode 存在", has_mode, "缺模式访问器")

    if has_set:
        st.set_grid_origin("manual", 100, 50)
        check("O8d mode 落 manual", str(st.get_setting("grid_origin_mode")) == "manual",
              "%r" % (st.get_setting("grid_origin_mode"),))
        check("O8e origin 两键落盘",
              list(st.get_setting("grid_origin") or []) == [100, 50],
              "%r" % (st.get_setting("grid_origin"),))
        check("O8f grid_origin() 读出 (100,50)", st.grid_origin() == (100, 50),
              "%r" % (st.grid_origin(),))
        solved = gs.solve_dims(W, H, NATIVE, origin=st.grid_origin())
        check("O8g 手动原点真的改动几何",
              (solved.ox, solved.oy) == (100, 50),
              "got %s" % ((solved.ox, solved.oy),))

    # 重置：两键一起清空 -> 回居中（不是回 26/22）
    if has_reset:
        st.reset_grid_origin()
        if has_mode:
            check("O8h 重置后 mode == auto", st.grid_origin_mode() == "auto",
                  "%r" % (st.grid_origin_mode(),))
        check("O8i 重置后 grid_origin() is None", st.grid_origin() is None,
              "%r" % (st.grid_origin(),))
        check("O8j 重置后 origin 键被清空",
              not st.get_setting("grid_origin"),
              "%r" % (st.get_setting("grid_origin"),))
        auto = gs.solve_dims(W, H, NATIVE)
        back = gs.solve_dims(W, H, NATIVE, origin=st.grid_origin())
        check("O8k 重置后回居中值",
              (back.ox, back.oy) == (auto.ox, auto.oy),
              "%s vs %s" % ((back.ox, back.oy), (auto.ox, auto.oy)))
        check("O8l 重置后居中值 != 边距（不是回 26/22）",
              (auto.ox, auto.oy) != (EDGE_X, EDGE_Y),
              "got %s" % ((auto.ox, auto.oy),))
    else:
        for nm in ("O8h", "O8i", "O8j", "O8k", "O8l"):
            check("%s 重置契约" % nm, False, "缺 Storage.reset_grid_origin")


# ============================ 取点态（O7） ============================
def test_pick_mode(app):
    w, st = make_window(app)
    icon = w.icons.get("a")
    check("O7a 造出图标部件", icon is not None, "icons=%s" % list(w.icons))
    has_pick = hasattr(w, "_picking_origin")
    check("O7b DesktopWindow 有 _picking_origin", has_pick, "缺取点态开关")
    check("O7c 默认不在取点态",
          (not has_pick) or w._picking_origin is False,
          "got %r" % (getattr(w, "_picking_origin", None),))

    calls = []
    orig_launch = desktop_window.appsource.launch
    desktop_window.appsource.launch = lambda a: calls.append(a)

    def icon_now():
        """每次重建后重新取（`_finish_pick` 会 refresh_grid -> rebuild，
        旧的 AppIcon 是 deleteLater 过的，坑见 DEVLOG #68 同类）。"""
        return w.icons.get("a")

    try:
        if icon is not None:
            # ---------- 对照组：非取点态双击 -> 真的启动（证明测试不空转） ----------
            QTest.mouseDClick(icon_now(), Qt.LeftButton,
                              pos=icon_now().rect().center())
            settle(app)
            check("O7d 非取点态双击图标会启动（对照）", len(calls) == 1,
                  "calls=%d" % len(calls))

            # ---------- 取点态单击：完成取点，但不启动、不选中 ----------
            calls.clear()
            w._selected = set()
            w._picking_origin = True
            ic = icon_now()
            expect = ic.mapTo(w, ic.rect().center())   # 点前算：重建后图标会挪位
            QTest.mouseClick(ic, Qt.LeftButton, pos=ic.rect().center())
            settle(app)
            check("O7e 取点态单击图标不启动", len(calls) == 0,
                  "calls=%d" % len(calls))
            check("O7f 取点态单击图标不选中", not w._selected,
                  "_selected=%s" % (w._selected,))
            check("O7g 取点态单击即完成取点", w._picking_origin is False,
                  "got %r" % (w._picking_origin,))
            landed = st.grid_origin()
            check("O7h 取到的原点 == 点击处（图标中心，控件坐标）",
                  landed == (expect.x(), expect.y()),
                  "origin=%s expect=(%d,%d)" % (landed, expect.x(), expect.y()))

            # ---------- 取点态双击：也不许启动 ----------
            calls.clear()
            w._picking_origin = True
            QTest.mouseDClick(icon_now(), Qt.LeftButton,
                              pos=icon_now().rect().center())
            settle(app)
            check("O7i 取点态双击图标不启动", len(calls) == 0,
                  "calls=%d" % len(calls))

            # ---------- 精确落点：_finish_pick 直接用给定坐标 ----------
            if has_pick and callable(getattr(w, "_finish_pick", None)):
                w._picking_origin = True
                w._finish_pick(QPoint(300, 200))
                settle(app)
                check("O7j 取点后退出取点态", w._picking_origin is False,
                      "got %r" % (w._picking_origin,))
                check("O7k 取点后 storage 落 manual 原点 (300,200)",
                      st.grid_origin() == (300, 200),
                      "%r" % (st.grid_origin(),))
            else:
                check("O7j 取点完成落 storage", False, "缺 _finish_pick")
                check("O7k 取点后退出取点态", False, "缺 _finish_pick")
    finally:
        desktop_window.appsource.launch = orig_launch
        w.close()
        w.deleteLater()
        settle(app)


def main(app):
    test_geometry()
    test_snapshot_follow()
    test_storage_reset()
    test_pick_mode(app)


crashed = None
try:
    _app = QApplication.instance() or QApplication(sys.argv[:1])
    main(_app)
except Exception:                      # 坑 #38：异常绝不能被吞成"通过"
    import traceback
    traceback.print_exc()
    crashed = "exception"
finally:
    print("-" * 60)
    if FAILED:
        print("FAILED: %d -> %s" % (len(FAILED), FAILED))
    if crashed or FAILED:
        sys.stdout.flush()
        os._exit(1)
    print("ALL grid_origin PASSED")
    sys.stdout.flush()
    os._exit(0)
