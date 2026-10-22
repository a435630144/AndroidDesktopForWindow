# -*- coding: utf-8 -*-
"""组件几何契约（v10 A8，反馈 21 / 22）。

用户原话：
    小组件的尺寸把 cell 填充的太满了，给小组件增加一个填充百分比，默认
    不要填充满……导致的问题是当两个小组件并排放在一起的时候，他们的边缘
    会贴在一起。
    小组件尺寸调节时候的辅助虚线和调节点，再往组件外侧偏移一些，虚线应该
    刚好压在小组件的边缘上，现在是在小组件的内部，定位小球随着虚线同步偏移。

三件事必须是同一份换算（`src/widget_geom.py`）：

    span 盒 = 跨度 × cell        （占位 / 碰撞形状，图标避让按它算）
    卡片    = 盒 居中 × fill     （视觉边界，玻璃与内容画在它上面）
    窗口    = 卡片（静止）/ 卡片 + 2×pad（编辑态，给手柄留半个圆）

判据：
  Y1  card_size = round(span × cell × fill)；fill 默认 0.90
  Y2  并排两组件之间的视觉间隙 = cell × (1-fill)（不再贴死）
  Y3  卡片在格盒内居中（左右 / 上下留白相等）
  Y4  window_size(editing=True) = 卡片 + 2×pad
  Y5  pad ≥ 手柄命中区半径（整圆都在窗口内，可点）
  Y6  span_from_pixels 与 card_size 互逆（1~4 格 × 4 档 fill）
  Y7  fill 脏值夹紧到 [0.6, 1.0]，缺省 0.90
  Y8  真窗口：进入编辑态窗口外扩、退出原样收回（三次往返逐字段相等）
  Y9  真窗口：编辑态虚线正好压在卡片边缘（card_rect 四角 == 手柄圆心）
  Y10 真窗口：静止态窗口 == 卡片（相邻组件透明区不重叠）

运行：python tests/test_widget_geom.py   （offscreen；判据看退出码）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QApplication

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


class FakeStorage:
    """最小 storage 桩：只喂几何需要的设置面。"""

    columns = 20
    rows = 9

    def __init__(self, **settings):
        self._s = {"layout_mode": "grid", "widget_fill": 0.90}
        self._s.update(settings)

    def get_setting(self, key, default=None):
        return self._s.get(key, default)

    def set_setting(self, key, val):
        self._s[key] = val

    def ui_scale(self):
        return 1.0

    def icon_metric(self):
        return 72

    def save(self):
        pass


def settle(app, ms=120):
    from PySide6.QtCore import QEventLoop
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make_widget(note_type="notes", anchored=True, colspan=2, rowspan=2):
    """真窗口（offscreen）——几何契约必须在真 QWidget 上验一次。"""
    from src import grid_flow
    from src.storage import Storage
    from src.widget_layer import WidgetLayer
    path = Path(tempfile.gettempdir()) / "test_widget_geom_state.json"
    if path.exists():
        path.unlink()
    st = Storage(path=str(path))
    st._data["settings"].update({"hide_native_icons": False,
                                 "auto_clone_desktop": False,
                                 "takeover_desktop": True,
                                 "show_widgets": True,
                                 "layout_mode": "grid",
                                 "widget_fill": 0.90})
    st._data["layout"] = []
    st._data["widgets"] = [{"id": "w1", "type": note_type, "hidden": False,
                            "anchored": anchored, "col": 3, "row": 2,
                            "colspan": colspan, "rowspan": rowspan,
                            "text": "x"}]
    st.save()
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)
    layer = WidgetLayer(st)
    return st, layer, layer.widgets.get("w1")


def main():
    from src import grid_flow, widget_geom

    # ---------- Y1：卡片尺寸 ----------
    st = FakeStorage()
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)
    cw, ch = grid_flow.cell_size(st)
    for span in ((1, 1), (2, 2), (3, 4), (4, 2)):
        want = (max(1, int(round(span[0] * cw * 0.90))),
                max(1, int(round(span[1] * ch * 0.90))))
        got = widget_geom.card_size(st, span)
        check("Y1 卡片 %d×%d = 格盒 × 90%%" % span, got == want,
              "%s want=%s" % (got, want))

    # ---------- Y2：并排间隙 ----------
    a = widget_geom.card_pos(st, 10, 0, (2, 2))
    b = widget_geom.card_pos(st, 12, 0, (2, 2))     # 紧邻的下一块 2 格组件
    gap = b[0] - (a[0] + widget_geom.card_size(st, (2, 2))[0])
    # 每块卡片在格盒里左右各留一半，两块相邻 => 间隙 = 盒宽 - 卡宽
    want_gap = 2 * cw - widget_geom.card_size(st, (2, 2))[0]
    check("Y2 并排组件视觉间隙 = 盒宽 - 卡宽",
          gap == want_gap, "gap=%d want=%d cw=%d" % (gap, want_gap, cw))
    check("Y2b 间隙 > 0（不再边缘贴死）", gap > 0, "gap=%d" % gap)

    # ---------- Y3：卡片在格盒内居中 ----------
    dx, dy = widget_geom.box_inset(st, (3, 4))
    bx, by = widget_geom.span_box(st, (3, 4))
    w, h = widget_geom.card_size(st, (3, 4))
    check("Y3 左右留白相等（居中）",
          dx == (bx - w) // 2 and abs((bx - w) % 2 - (bx - w - 2 * dx)) <= 1,
          "dx=%d box=%d card=%d" % (dx, bx, w))
    check("Y3b 上下留白相等（居中）", dy == (by - h) // 2,
          "dy=%d box=%d card=%d" % (dy, by, h))

    # ---------- Y4 / Y5：编辑外扩与命中 ----------
    p = widget_geom.pad(st)
    ew, eh = widget_geom.window_size(st, (2, 2), editing=True)
    cw2, ch2 = widget_geom.card_size(st, (2, 2))
    check("Y4 编辑态窗口 = 卡片 + 2×pad",
          (ew, eh) == (cw2 + 2 * p, ch2 + 2 * p), "%s vs %s" % ((ew, eh), (cw2, ch2)))
    check("Y5 pad ≥ 手柄命中区半径（整圆可点）",
          p >= (widget_geom.handle_hit(st) + 1) // 2,
          "pad=%d hit=%d" % (p, widget_geom.handle_hit(st)))

    # ---------- Y6：反推互逆 ----------
    bad = []
    for f in (0.60, 0.75, 0.90, 1.00):
        st.set_setting("widget_fill", f)
        for span in ((1, 1), (2, 2), (3, 4), (4, 1)):
            w, h = widget_geom.card_size(st, span)
            got = widget_geom.span_from_pixels(st, w, h)
            if got != span:
                bad.append((f, span, got, (w, h)))
    st.set_setting("widget_fill", 0.90)
    check("Y6 span_from_pixels ∘ card_size = 恒等（4 档 fill × 4 跨度）",
          not bad, "%s" % bad[:3])

    # ---------- Y7：脏值夹紧 ----------
    for raw, want in ((0.1, 0.60), (2.0, 1.00), ("bad", 0.90), (None, 0.90)):
        st.set_setting("widget_fill", raw)
        got = widget_geom.fill(st)
        check("Y7 fill(%r) -> %.2f" % (raw, want), abs(got - want) < 1e-6,
              "got=%s" % got)
    st.set_setting("widget_fill", 0.90)

    # ---------- Y8 / Y9 / Y10：真窗口 ----------
    app = QApplication.instance() or QApplication([])
    st2, layer, w = make_widget()
    if w is None:
        check("Y8 组件已创建", False)
    else:
        settle(app)
        card0 = (w.x(), w.y(), w.width(), w.height())
        check("Y10 静止态窗口 == 卡片（无外扩）",
              (w.width(), w.height()) == widget_geom.card_size(st2, (2, 2)),
              "%dx%d" % (w.width(), w.height()))

        snaps = []
        for _ in range(3):
            w._enter_edit()
            settle(app, 40)
            snaps.append((w.x(), w.y(), w.width(), w.height()))
            cr = w.card_rect()
            hs = w._handle_rects()
            centers = {k: (r.center().x(), r.center().y()) for k, r in hs.items()}
            ok = (abs(centers["nw"][0] - cr.left()) <= 1
                  and abs(centers["nw"][1] - cr.top()) <= 1
                  and abs(centers["se"][0] - cr.right()) <= 1
                  and abs(centers["se"][1] - cr.bottom()) <= 1)
            if not ok:
                check("Y9 虚线压在卡片边缘（第 %d 次）" % len(snaps), False,
                      "nw=%s card=%s" % (centers["nw"], cr))
            w._exit_edit()
            settle(app, 40)
        check("Y9 编辑态虚线压在卡片边缘（3 次进入逐次成立）",
              len(snaps) == 3)
        check("Y8 三次进出编辑态窗口几何逐字段相等（外扩幂等）",
              snaps[0] == snaps[1] == snaps[2], "%s" % (snaps,))
        check("Y8b 退出编辑态回到原始几何",
              (w.x(), w.y(), w.width(), w.height()) == card0,
              "%s vs %s" % ((w.x(), w.y(), w.width(), w.height()), card0))
        check("Y8c 进出编辑态不改跨度",
              (w.entry.get("colspan"), w.entry.get("rowspan")) == (2, 2),
              "%s" % ((w.entry.get("colspan"), w.entry.get("rowspan")),))
        for x in list(layer.widgets.values()):
            x.close()

    print("")
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
    else:
        print("ALL widget_geom PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
