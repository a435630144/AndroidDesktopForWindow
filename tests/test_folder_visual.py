# -*- coding: utf-8 -*-
"""v7 B5（文件夹与视觉批次）契约测试 —— 对应 v7e 反馈 5/6「之前提的还没修」。

规格：docs/指导文档_v7.md §7.1 / §7.2 / §7.3。

  Q 弹窗度量（反馈 10 弹窗图标过大）
    Q1 n=4 时 icon/width ∈ [0.18, 0.24]
    Q2 n=12 时 cols=4 且 width <= 520
    Q3 成员图标**不随桌面图标档位变化**（旧实现 icon_metric*0.62）
    Q4 cell 55 → 104 时 icon 仍在 [40, 56]

  R 图标绘制单点化（反馈 13 成员图标变得非常小）
    R1 请求 56px 时实际绘制 >= 0.95*56（小源图强制上采样）
    R2 文件夹瓷砖迷你图标 >= 0.28 * 瓷砖边长
    R3 DPR 1.0 / 1.5 下绘制逻辑尺寸一致（±1px）
    R4 非方形源图 contain 后居中、不溢出 rect

  H 组件编辑控制点（反馈 20 控制点像碎块）
    H1 八点矩形完整落在部件内（1×1/2×2/3×3 × chrome 1.0~2.0）
    H2 圆心落线（line / w//2 / w-line）
    H3 直径 = max(9, round(10*chrome)) 且 <= 14
    H4 命中区 >= 22×22 且包含可见圆
    H5 非编辑态 / 无界模式返回 {}

运行：python tests/test_folder_visual.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from src import appsource, grid_flow
from src.folder_popup import FolderPopup, popup_metrics
from src.iconwidget import AppIcon
from src.storage import Storage
from src.widget_layer import WidgetLayer

STATE = Path(tempfile.gettempdir()) / "test_folder_visual_state.json"
failures = []
CHECKS = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    CHECKS.append(name)
    if not cond:
        failures.append(name)


class FakeStore:
    def __init__(self, settings=None):
        self._s = {"columns": "auto", "layout_mode": "grid", "extra_pages": []}
        self._s.update(settings or {})
        self.layout = []
        self.widgets = []

    def get_setting(self, k):
        return self._s.get(k)

    def set_setting(self, k, v):
        self._s[k] = v

    @property
    def columns(self):
        m = grid_flow.current_metrics()
        return m.cols if m is not None else 10

    def icon_metric(self):
        return int(self._s.get("icon_metric", 96))

    def ui_scale(self):
        return float(self._s.get("chrome", 1.0))

    def save(self):
        pass


def bbox_alpha(img):
    """非透明像素包围盒 (x, y, w, h)；全透明返回 None。"""
    x0 = y0 = 10 ** 9
    x1 = y1 = -1
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() > 8:
                x0, y0 = min(x0, x), min(y0, y)
                x1, y1 = max(x1, x), max(y1, y)
    if x1 < 0:
        return None
    return x0, y0, x1 - x0 + 1, y1 - y0 + 1


def main(app):
    # ------------------------------------------------------------- Q
    m4 = popup_metrics(83, 4)
    check("Q1 n=4 图标/宽度比落在 [0.18, 0.24]",
          0.18 <= m4["icon"] / m4["width"] <= 0.24,
          "icon=%d w=%d ratio=%.3f"
          % (m4["icon"], m4["width"], m4["icon"] / m4["width"]))
    m12 = popup_metrics(83, 12)
    check("Q2 n=12 时 cols=4 且 width<=520",
          m12["cols"] == 4 and m12["width"] <= 520,
          "cols=%d w=%d" % (m12["cols"], m12["width"]))
    check("Q2b 宽度下降时先缩 gap 再缩 icon（顺序契约）",
          m12["icon"] == m4["icon"] or m12["gap"] < 12,
          "icon=%d gap=%d" % (m12["icon"], m12["gap"]))

    st = FakeStore()
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)
    stub = type("P", (), {"storage": st, "entry": {"apps": [{}] * 4}})()
    size_a = FolderPopup._member_icon_size(stub)
    st.set_setting("icon_metric", 240)
    size_b = FolderPopup._member_icon_size(stub)
    check("Q3 成员图标不随桌面图标档位变化（icon_metric 96→240）",
          size_a == size_b, "a=%d b=%d" % (size_a, size_b))
    check("Q4 极小 cell 落到下限 40",
          popup_metrics(55, 4)["icon"] == 40, "%d" % popup_metrics(55, 4)["icon"])
    check("Q4b 极大 cell 落到上限 56",
          popup_metrics(104, 4)["icon"] == 56,
          "%d" % popup_metrics(104, 4)["icon"])

    # ------------------------------------------------------------- R
    rect = QRectF(0, 0, 56, 56)
    orig_pm = appsource.icon_pixmap
    try:
        # 小源图（16px）→ 必须上采样到 ~56，不许原尺寸落笔
        appsource.icon_pixmap = lambda app, size, dpr=1.0: QPixmap(16, 16)
        img = QImage(56, 56, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        drawn = appsource.draw_icon(p, {"name": "x"}, rect, 1.0)
        p.end()
        check("R1 请求 56px 时实际绘制 >= 0.95*56（小源图上采样）",
              drawn >= 53, "drawn=%d" % drawn)

        # 非方形源图 64×32：contain 后 56×28 且垂直居中
        square = QPixmap(64, 32)
        square.fill(QColor(255, 0, 0))
        appsource.icon_pixmap = lambda app, size, dpr=1.0: square
        img2 = QImage(56, 56, QImage.Format_ARGB32)
        img2.fill(Qt.transparent)
        p2 = QPainter(img2)
        appsource.draw_icon(p2, {"name": "y"}, rect, 1.0)
        p2.end()
        bb = bbox_alpha(img2)
        check("R4 非方形源图 contain 居中（56×28 居中于 56×56）",
              bb is not None and abs(bb[2] - 56) <= 2 and abs(bb[3] - 28) <= 2
              and abs(bb[0] - 0) <= 2 and abs(bb[1] - 14) <= 2,
              "bbox=%s" % (bb,))

        # DPR 无关：同一 rect 在 1.0 / 1.5 下逻辑尺寸一致
        d1 = appsource.draw_icon(QPainter(img), {"name": "z"}, rect, 1.0)
        img3 = QImage(84, 84, QImage.Format_ARGB32)
        img3.fill(Qt.transparent)
        d2 = appsource.draw_icon(QPainter(img3), {"name": "z"}, rect, 1.5)
        check("R3 DPR 1.0/1.5 下绘制逻辑尺寸一致（±1）",
              abs(d1 - d2) <= 1, "d1=%d d2=%d" % (d1, d2))

        # R2 文件夹瓷砖迷你图标比例：拦截 draw_icon 记录 rect
        rec = []
        appsource.draw_icon = (lambda p, app, r, dpr=1.0, _old=appsource.draw_icon:
                               (rec.append((r.width(), r.height())),
                                _old(p, app, r, dpr))[1])
        folder = {"id": "f1", "type": "folder",
                  "app": {"id": "f1", "name": "F", "kind": "folder"},
                  "apps": [{"id": "m1", "name": "M1", "target": "m1"},
                           {"id": "m2", "name": "M2", "target": "m2"}],
                  "col": 0, "row": 0}
        ic = AppIcon(folder, 96)
        canvas = QPixmap(120, 120)
        canvas.fill(Qt.transparent)
        pp = QPainter(canvas)
        ic._paint_folder(pp, 1.0)
        pp.end()
        tile = 96 - 2
        check("R2 文件夹迷你图标 >= 0.28*瓷砖边长",
              rec and min(w for w, _h in rec) >= 0.28 * tile,
              "slots=%s tile=%d" % (rec, tile))
        check("R2b 迷你矩阵最多 4 个槽位", len(rec) <= 4, "n=%d" % len(rec))
        ic.close()
    finally:
        appsource.icon_pixmap = orig_pm
        appsource.draw_icon = _ORIG_DRAW
        globals().pop("_ORIG_DRAW", None)

    # ------------------------------------------------------------- H
    if STATE.exists():
        STATE.unlink()
    st2 = Storage(path=str(STATE))
    st2._data["settings"].update({
        "hide_native_icons": False, "auto_clone_desktop": False,
        "layout_mode": "grid", "takeover_desktop": True, "widgets_only": False,
    })
    st2._data["layout"] = []
    st2._data["widgets"] = [{"id": "note1", "type": "notes", "w": 300, "h": 300,
                             "hidden": False, "anchored": True, "text": "hi"}]
    st2.save()
    grid_flow.set_grid(st2, (1920, 1040))
    grid_flow.set_page(0)
    layer = WidgetLayer(st2)
    w = layer.widgets.get("note1")
    check("H0 组件已创建", w is not None)
    orig_chrome = st2.ui_scale
    if w is not None:
        w._edit_mode = True
        ok_all = True
        detail = ""
        for span in ((1, 1), (2, 2), (3, 3)):
            for chrome in (1.0, 1.25, 1.5, 2.0):
                st2.ui_scale = (lambda c=chrome: c)
                w.resize(span[0] * 160, span[1] * 180)
                rects = w._handle_rects()
                if len(rects) != 8:
                    ok_all = False
                    detail = "chrome=%s span=%s n=%d" % (chrome, span, len(rects))
                    continue
                for k, r in rects.items():
                    if not w.rect().contains(r):
                        ok_all = False
                        detail = ("chrome=%s span=%s %s=%s not in %s"
                                  % (chrome, span, k, r, w.rect()))
        check("H1 八点完整落在部件内（12 种组合不裁切）", ok_all, detail)

        st2.ui_scale = (lambda: 1.25)
        w.resize(320, 360)
        s = w._handle_size()
        w._edit_mode = False        # H1 是直接置位的，先归零再走正式入口
        w._enter_edit()
        rects = w._handle_rects()
        cr = w.card_rect()
        check("H3 直径 = max(9, round(10*chrome)) 且 <= 14",
              s == max(9, int(round(10 * 1.25))) and s <= 14, "d=%d" % s)
        cx = rects["nw"].center().x()
        cy = rects["nw"].center().y()
        # v10 A8（反馈 22）：圆心 = **卡片**角点（虚线压在卡片边缘，不再内缩）
        check("H2 圆心落在卡片角点（nw 在 card.left/top）",
              abs(cx - cr.left()) <= 1 and abs(cy - cr.top()) <= 1,
              "center=(%s,%s) card=(%s,%s)" % (cx, cy, cr.left(), cr.top()))
        check("H2b 边中点圆心在卡片边中点",
              abs(rects["n"].center().x() - cr.center().x()) <= 1
              and abs(rects["s"].center().y() - cr.bottom()) <= 1,
              "n=%s s=%s card=%s" % (rects["n"].center(), rects["s"].center(), cr))
        hits = w._handle_hit_rects()
        check("H4 命中区 >= 20×20 且包含可见圆",
              all(hr.width() >= 20 and hr.height() >= 20
                  and hr.contains(rects[k]) for k, hr in hits.items()),
              "hit=%d paint=%d" % (hits["nw"].width(), rects["nw"].width()))
        hit = w._handle_at(rects["nw"].center())
        check("H4b 点圆心必中（命中区语义）", hit == "nw", "hit=%s" % (hit,))
        w._exit_edit()
        w._edit_mode = False
        check("H5 非编辑态返回 {}", w._handle_rects() == {})
        w._edit_mode = True
        st2.set_setting("layout_mode", "free")
        check("H5b 无界模式返回 {}", w._handle_rects() == {})
        st2.set_setting("layout_mode", "grid")
        w._edit_mode = False
    st2.ui_scale = orig_chrome
    for x in list(layer.widgets.values()):
        x.close()

    print("\n%d checks, %d failed" % (len(CHECKS), len(failures)))
    return failures


_ORIG_DRAW = appsource.draw_icon

if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    fails = main(app)
    if fails:
        print("FAILED: %s" % ", ".join(fails))
        sys.exit(1)
    print("ALL folder_visual PASSED")
