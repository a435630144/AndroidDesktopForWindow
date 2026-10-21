# -*- coding: utf-8 -*-
"""v7e 实机反馈 1–4 / 7–8 的契约测试。

用户原话（2026-10-21 v7d 实机验收后第二批）：
  1. "便于挤开的触发速度可以稍微再快一些，现在感觉反应迟钝，但是也不能
     快到老来不及弹出合并为文件夹就挤走。"
  2. "无界模式移动图标还是有一个奇怪的回弹动画。/ 切换到无界模式，小组件
     的效果切换到了无界模式，但是小组件的右键菜单还是网格模式。"
  3. "从无界模式切换回网格模式，会忘记小组件的坐标位置，导致出现 cell
     重叠的 bug。"
  4. "自动排列图标的功能没有生效，当位于自动排列的时候，用户只能手动控制
     小组件的位置，其余图标应该自动排列铺满整行后再排列到第二行。"
  7. "切换到仅小组件模式的时候，应该显示原生桌面图标，现在是空白。"
  8. "考虑优化软件性能，现在有的时候会掉帧卡顿，至少保持全程 60 帧。"

覆盖：
  N1 推让节拍：提示先到（350）/ 推让提速（470）/ 翻页仍最快（360）
  N2 无界松手不回弹：图标直接出现在落点（零位移动画）
  N3 组件右键菜单随模式（无界无「编辑 / 组件尺寸」）
  N4 free→grid：组件按无界像素位回算格位（不再跳回旧格）+ 图标让位
  N5 自动排列：密排铺满整行（填洞）、跳过组件占位、插入语义
  N6 仅小组件：原生图标恢复可见、整窗不画命中填充（原生图标可点）
  N7 性能：换格只重绘两框并集（不是整屏）；帧统计可读

运行：python tests/test_v7e_feedback.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QPoint, QRect, QTimer
from PySide6.QtWidgets import QApplication

from src import grid_flow, win32_layer
from src.desktop_window import (EDGE_FLIP_DWELL_MS, PUSH_DWELL_MS,
                                DesktopWindow)
from src.iconwidget import DWELL_MERGE_MS
from src.storage import Storage
from src.widget_layer import WidgetLayer

STATE = Path(tempfile.gettempdir()) / "test_v7e_feedback_state.json"
failures = []
CHECKS = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    CHECKS.append(name)
    if not cond:
        failures.append(name)


def settle(app, ms=250):
    loop = QEventLoop()
    t = QTimer()
    t.setSingleShot(True)
    t.timeout.connect(loop.quit)
    t.start(ms)
    loop.exec()


def make_state(n_icons=8, widgets=None, settings=None):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"].update({
        "hide_native_icons": False,
        "auto_clone_desktop": False,
        "layout_mode": "grid",
        "takeover_desktop": True,
        "widgets_only": False,
        "auto_arrange": False,
        "show_widgets": True,
    })
    for k, v in (settings or {}).items():
        st._data["settings"][k] = v
    cols = 6
    st._data["layout"] = [
        {"id": "i%d" % i, "type": "app", "name": "I%d" % i, "target": "i%d" % i,
         "col": i % cols, "row": i // cols} for i in range(n_icons)
    ]
    st._data["widgets"] = [dict(w) for w in (widgets or [])]
    st.save()
    return st


def new_window(st, app=None):
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)
    w = DesktopWindow(st)
    w.show()
    if app is not None:
        settle(app, 60)
    return w


def note_widget(**kw):
    base = {"id": "note1", "type": "notes", "w": 300, "h": 300,
            "hidden": False, "anchored": True, "text": "hi"}
    base.update(kw)
    return base


def main(app):
    # ---------------------------------------------------------------- N1
    check("N1a 合并提示提前到 350（300~400）",
          300 <= DWELL_MERGE_MS <= 400, "dwell=%s" % (DWELL_MERGE_MS,))
    check("N1b 推让提速到 ~470（<=500 且 > 提示）",
          DWELL_MERGE_MS < PUSH_DWELL_MS <= 500,
          "push=%s dwell=%s" % (PUSH_DWELL_MS, DWELL_MERGE_MS))
    check("N1c 提示比推让至少早 100ms（不能\"来不及弹提示就挤走\"）",
          PUSH_DWELL_MS - DWELL_MERGE_MS >= 100,
          "gap=%s" % (PUSH_DWELL_MS - DWELL_MERGE_MS,))
    check("N1d 边缘翻页仍先于推让（留 100ms 以上）",
          EDGE_FLIP_DWELL_MS < PUSH_DWELL_MS - 100,
          "flip=%s push=%s" % (EDGE_FLIP_DWELL_MS, PUSH_DWELL_MS))
    check("N1e 旧值 700 已退役（体感迟钝的原因）",
          PUSH_DWELL_MS <= 500, "push=%s" % (PUSH_DWELL_MS,))

    # ---------------------------------------------------------------- N2
    st = make_state(settings={"layout_mode": "free"})
    w = new_window(st, app)
    check("N2a 无界模式窗口就绪", grid_flow.free_mode(st) and len(w.icons) == 8,
          "icons=%d" % len(w.icons))
    icon = w.icons.get("i0")
    entry = st.find_entry("i0")
    start = icon.pos()
    w._drag_entry_id = "i0"
    target = QPoint(300, 240)
    w._free_drop(["i0"], target)
    settle(app, 60)
    check("N2b 落点即松手位（fx/fy 已写入）",
          (entry.get("fx"), entry.get("fy")) == (target.x(), target.y()),
          "fx/fy=%s" % ((entry.get("fx"), entry.get("fy")),))
    check("N2c 图标**立即**在落点（没有从起点弹过去的位移）",
          icon.pos() == QPoint(target.x(), target.y()),
          "pos=%s want=%s" % (icon.pos(), target))
    running = [a for a in getattr(icon, "_anims", [])
               if a.state() == a.State.Running
               and a.propertyName() in (b"pos", "pos")]
    check("N2d 松手后没有进行中的**位移**动画（回弹的来源）",
          not running, "running=%d" % len(running))
    w.close()

    # ---------------------------------------------------------------- N3
    st3 = make_state(widgets=[note_widget()])
    grid_flow.set_grid(st3, (1920, 1040))
    grid_flow.set_page(0)
    w3 = DesktopWindow(st3)
    w3.show()
    layer3 = WidgetLayer(st3)
    w3.set_widget_layer(layer3)
    settle(app, 250)
    note = layer3.widgets.get("note1")
    grid_menu = [a.text() for a in note._build_context_menu().actions()]
    check("N3a 网格模式菜单有「编辑」", "编辑" in grid_menu, "menu=%s" % (grid_menu,))
    w3.set_layout_mode("free")
    settle(app, 300)
    note = layer3.widgets.get("note1")
    free_menu = [a.text() for a in note._build_context_menu().actions()]
    check("N3b 无界模式菜单**没有**「编辑」（网格专属）",
          "编辑" not in free_menu, "menu=%s" % (free_menu,))
    check("N3c 无界模式菜单没有「组件尺寸」（格跨度专属）",
          "组件尺寸" not in free_menu, "menu=%s" % (free_menu,))
    check("N3d 无界模式菜单保留形态切换",
          any("悬浮" in t for t in free_menu), "menu=%s" % (free_menu,))

    # ---------------------------------------------------------------- N4
    # 在无界模式把组件拖到别的像素位，再切回网格：坐标必须跟着走
    note_entry = st3.widgets[0]
    before_cell = (int(note_entry.get("col", 0)), int(note_entry.get("row", 0)))
    note.move(760, 380)
    note._save_geom_free()
    settle(app, 60)
    check("N4a 无界松手不冲掉网格 row（只写 fpage）",
          (int(note_entry.get("col", 0)), int(note_entry.get("row", 0)))
          == before_cell,
          "cell=%s was=%s" % ((note_entry.get("col"), note_entry.get("row")),
                              before_cell))
    check("N4b 无界页归属写进 fpage", note_entry.get("fpage") == 0,
          "fpage=%s" % (note_entry.get("fpage"),))
    w3.set_layout_mode("grid")
    settle(app, 300)
    want = grid_flow.pos_cell(st3, 760, 380)
    got = (int(note_entry.get("col", 0)), int(note_entry.get("row", 0)))
    check("N4c 切回网格组件落在无界像素位对应的格（不跳回旧格）",
          abs(got[0] - want[0]) <= 1 and abs(got[1] - want[1]) <= 1,
          "got=%s want=%s" % (got, want))
    check("N4d 组件占格与图标 occupy 无重叠",
          not (grid_flow.widget_cells(st3) &
               {(int(e["col"]), int(e["row"])) for e in st3.layout}),
          "widget=%s icons=%s" % (sorted(grid_flow.widget_cells(st3)),
                                  sorted((e["col"], e["row"]) for e in st3.layout)))
    check("N4e fx/fy 保留（再进无界仍回原像素位）",
          (note_entry.get("fx"), note_entry.get("fy")) == (760, 380),
          "fx/fy=%s" % ((note_entry.get("fx"), note_entry.get("fy")),))
    w3.close()

    # ---------------------------------------------------------------- N5
    # 固定格子几何，纯函数层断言密排语义
    class FakeStore:
        def __init__(self, layout, widgets=(), settings=None):
            self.layout = list(layout)
            self.widgets = list(widgets)
            self._s = {"columns": "auto", "layout_mode": "grid",
                       "extra_pages": []}
            self._s.update(settings or {})

        def get_setting(self, k):
            return self._s.get(k)

        def set_setting(self, k, v):
            self._s[k] = v

        @property
        def columns(self):
            m = grid_flow.current_metrics()
            return m.cols if m is not None else 10

        def icon_metric(self):
            return 48

        def icon_chrome_scale(self):
            return 1.0

    fs = FakeStore([])
    grid_flow.set_grid(fs, (1920, 1040))
    grid_flow.set_page(0)
    cols = fs.columns
    check("N5a 网格列数可用", cols >= 4, "cols=%s" % (cols,))

    # 有洞的布局：a(0,0) b(3,0) c(0,1)
    layout = [
        {"id": "a", "type": "app", "col": 0, "row": 0},
        {"id": "b", "type": "app", "col": 3, "row": 0},
        {"id": "c", "type": "app", "col": 0, "row": 1},
        {"id": "d", "type": "app", "col": 2, "row": 1},
    ]
    fs2 = FakeStore(layout)
    moves = grid_flow.auto_arrange_moves(layout, cols, "d", (2, 0))
    after = {e["id"]: (e["col"], e["row"]) for e in layout}
    after.update(moves)
    check("N5b 自动排列后 4 个图标占 (0,0)(1,0)(2,0)(3,0) 连续密排",
          sorted(after.values())[:4] == [(0, 0), (1, 0), (2, 0), (3, 0)],
          "cells=%s" % (sorted(after.values()),))
    check("N5c 拖到 (2,0) 的图标落在第 3 个位置（插入语义）",
          after["d"] == (2, 0), "d=%s" % (after["d"],))
    check("N5d 洞口被填（b 从 (3,0) 前移到 (1,0)）",
          after["b"] == (1, 0), "b=%s" % (after["b"],))

    # 组件占位跳过：blocked (1,0) -> 图标不能压组件
    moves2 = grid_flow.auto_arrange_moves(layout, cols, "a", (0, 0),
                                          extra_occupied={(1, 0)})
    after2 = {e["id"]: (e["col"], e["row"]) for e in layout}
    after2.update(moves2)
    check("N5e 组件占格被跳过（(1,0) 无人占用）",
          all(c != (1, 0) for c in after2.values()),
          "cells=%s" % (sorted(after2.values()),))
    check("N5f 跳过后仍是连续密排（(0,0)(2,0)(3,0)(4,0)）",
          sorted(after2.values())[:4] == [(0, 0), (2, 0), (3, 0), (4, 0)],
          "cells=%s" % (sorted(after2.values()),))

    # 窗口层：开关真的选了不同算法
    st5 = make_state(6, settings={"auto_arrange": True})
    w5 = new_window(st5, app)
    check("N5g 自动排列开 → _arrange_moves 走密排（洞被填）",
          w5._auto_arrange() is True)
    for e in st5.layout:                     # 人为挖洞：c 挪到 (3,2)
        if e["id"] == "i2":
            e["col"], e["row"] = 3, 2
    moves5 = w5._arrange_moves("i0", (0, 0))
    check("N5h 密排清单覆盖被打散后面的图标",
          bool(moves5) and len(moves5) >= 2, "moves=%s" % (moves5,))
    w5.close()

    # ---------------------------------------------------------------- N6
    calls = []
    orig = win32_layer.set_native_icons_visible
    win32_layer.set_native_icons_visible = lambda on: calls.append(bool(on))
    try:
        st6 = make_state(4, widgets=[note_widget()])
        w6 = new_window(st6, app)
        w6.set_widgets_only(True)
        settle(app, 120)
        check("N6a 仅小组件模式：原生图标恢复可见（不再是空白桌面）",
              calls and calls[-1] is True, "calls=%s" % (calls[-3:],))
        check("N6b 仅小组件模式：窗口不再全盘接管（命中穿透）",
              w6._organize_mode() is False, "organize=True")
        check("N6c 仅小组件模式：我们自己的图标不建",
              len(w6.icons) == 0, "icons=%d" % len(w6.icons))
        painted = []
        w6._paint_hit_fill = lambda: painted.append(1)
        w6.repaint()
        settle(app, 60)
        check("N6d 仅小组件模式：不画全窗命中填充（alpha=0 才可穿透）",
              not painted, "painted=%d" % len(painted))
        w6.set_widgets_only(False)
        settle(app, 120)
        check("N6e 退出仅小组件：原生图标重新隐藏（接管恢复）",
              calls[-1] is False, "calls=%s" % (calls[-3:],))
        check("N6f 退出仅小组件：图标回来", len(w6.icons) == 4,
              "icons=%d" % len(w6.icons))
        w6.close()
    finally:
        win32_layer.set_native_icons_visible = orig

    # ---------------------------------------------------------------- N7
    st7 = make_state(8)
    w7 = new_window(st7, app)
    rects = []
    orig_update = w7.update
    w7.update = lambda *a: (rects.append(a[0] if a else None), orig_update(*a))
    try:
        w7._set_highlight((0, 0))
        first = rects[-1]
        check("N7a 红框首次出现走脏区 update(QRect)",
              isinstance(first, QRect), "arg=%r" % (first,))
        w7._set_highlight((1, 0))
        second = rects[-1]
        area = second.width() * second.height() if isinstance(second, QRect) else 0
        full = w7.width() * w7.height()
        check("N7b 换格只重绘两框并集（远小于整屏）",
              area > 0 and area < full * 0.5,
              "area=%d full=%d" % (area, full))
        check("N7c 脏区覆盖旧框与新框两点",
              isinstance(second, QRect)
              and second.contains(w7._hl_rect((0, 0), (1, 1)).topLeft())
              and second.contains(w7._hl_rect((1, 0), (1, 1)).bottomRight()),
              "r=%s" % (second,))
        stats = w7.frame_stats()
        check("N7d 帧统计可读（count/max/avg/p95/area）",
              all(k in stats for k in ("count", "max_ms", "avg_ms",
                                       "p95_ms", "last_area")),
              "stats=%s" % ({k: stats[k] for k in ("count", "max_ms")},))
        # N7e：整段拖动中不许出现整屏重绘（掉帧的结构性来源）
        w7._set_highlight(None)
        rects.clear()
        for i in range(12):
            w7._drag_move_at("i0", QPoint(60 + i * 47, 180))
        big = [r for r in rects
               if isinstance(r, QRect) and r.width() * r.height() > full * 0.5]
        check("N7e 拖动 12 格全程无整屏重绘",
              not big, "big=%d rects=%s" % (len(big), rects[:3]))
    finally:
        w7.update = orig_update
    w7.close()

    print("\n%d checks, %d failed" % (len(CHECKS), len(failures)))
    return failures


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    fails = main(app)
    if fails:
        print("FAILED: %s" % ", ".join(fails))
        sys.exit(1)
    print("ALL v7e CHECKS PASSED")
