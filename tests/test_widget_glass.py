# -*- coding: utf-8 -*-
"""玻璃卡片基类（v8 C2，指导文档_v8.md §2.3）。

契约：
  G1  paint_glass 能画满整块（内部非空）
  G2  圆角外像素全透明（(0,0) alpha == 0）——圆角真实存在，不是矩形
  G3  顶部有一道 specular 高光：顶部 3px 的最亮值 > 中部最亮值
  G4  极小矩形（1×1）与零尺寸不抛异常（组件库缩略图会喂任意大小）
  G5  统一内边距常量 PAD / GAP / TITLE_H 存在且合理
  G6  draw_preview 兜底卡：非空，且不同名称产出不同像素（真的写了字）
  G7  GlassWidget 把绘制交给 paint_content（子类钩子被调用）
  G8  锚定态整窗铺 alpha=2 命中填充（v7 B4：透明区也要能点到）
  G9  悬浮态四角仍透明（玻璃也是圆角，不是把整窗涂满）
  G10 玻璃底色是"上亮下沉"的竖向渐变（顶部比底部亮）

运行：python tests/test_widget_glass.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.storage import Storage

STATE = Path(tempfile.gettempdir()) / "test_widget_glass_state.json"

CHECKS = []
failures = []


def check(name, cond, extra=""):
    CHECKS.append(name)
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def canvas(w, h):
    img = QImage(int(w), int(h), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    return img


def alpha_nonempty(img):
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() > 8:
                n += 1
    return n


def brightness(c: QColor) -> int:
    return c.red() + c.green() + c.blue()


def dpr_of(w) -> float:
    """grab() 得到的是物理像素图，取样前必须按 DPR 换算，否则量错位置。"""
    return float(w.devicePixelRatioF() or 1.0)


def make_state(widgets):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = False
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["layout"] = []
    st._data["widgets"] = [dict(w) for w in widgets]
    st.save()
    return st


def main(app):
    from src import theme
    from src import widget_glass as wg

    # ---------- G1 / G2 / G3 / G10：静态玻璃 ----------
    img = canvas(220, 160)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    wg.paint_glass(p, QRectF(0, 0, 220, 160))
    p.end()

    check("G1 内部非空", alpha_nonempty(img) > 20000, str(alpha_nonempty(img)))
    check("G2 圆角外透明", img.pixelColor(0, 0).alpha() == 0
          and img.pixelColor(219, 159).alpha() == 0,
          "(%d,%d)" % (img.pixelColor(0, 0).alpha(), img.pixelColor(219, 159).alpha()))

    def column_max(x, y0, y1):
        return max(brightness(img.pixelColor(x, y)) for y in range(y0, y1))

    top = column_max(110, 1, 4)
    mid = column_max(110, 70, 90)
    check("G3 顶部 specular 高光 > 中部", top > mid, "top=%d mid=%d" % (top, mid))
    check("G10 竖向渐变上亮下沉",
          brightness(img.pixelColor(110, 12)) > brightness(img.pixelColor(110, 150)),
          "%d vs %d" % (brightness(img.pixelColor(110, 12)),
                        brightness(img.pixelColor(110, 150))))
    check("G3b 玻璃底色带透明度（能看到壁纸）",
          img.pixelColor(110, 80).alpha() < 255,
          "a=%d" % img.pixelColor(110, 80).alpha())

    # ---------- G4：极端尺寸 ----------
    ok = True
    for w, h in ((1, 1), (2, 2), (6, 6)):
        try:
            im2 = canvas(max(w, 1), max(h, 1))
            p2 = QPainter(im2)
            wg.paint_glass(p2, QRectF(0, 0, w, h))
            p2.end()
        except Exception as exc:      # noqa: BLE001
            ok = False
            print("   paint_glass(%dx%d) 抛异常: %r" % (w, h, exc))
    check("G4 极小矩形不抛异常", ok)
    try:
        # 注意：QImage 必须留引用。`QPainter(canvas(8,8))` 会让临时 QImage
        # 立刻被 GC，painter 画在已析构的图像上 → Qt abort（实测，非异常）。
        zero_img = canvas(8, 8)
        p3 = QPainter(zero_img)
        wg.paint_glass(p3, QRectF(0, 0, 0, 0))
        p3.end()
        zero_ok = True
    except Exception:                 # noqa: BLE001
        zero_ok = False
    check("G4b 零尺寸不抛异常", zero_ok)

    # ---------- G5：常量 ----------
    check("G5 内边距常量齐全",
          wg.PAD >= 8 and wg.GAP >= 4 and wg.TITLE_H >= 16,
          "PAD=%s GAP=%s TITLE_H=%s" % (wg.PAD, wg.GAP, wg.TITLE_H))

    # ---------- G6：兜底预览 ----------
    a = canvas(288, 120)
    pa = QPainter(a)
    wg.draw_preview(pa, QRectF(0, 0, 288, 120), "系统监控", "CPU / 内存 / 磁盘")
    pa.end()
    b = canvas(288, 120)
    pb = QPainter(b)
    wg.draw_preview(pb, QRectF(0, 0, 288, 120), "日历", "月视图")
    pb.end()

    check("G6 兜底预览非空", alpha_nonempty(a) > 20000, str(alpha_nonempty(a)))
    diff = sum(1 for y in range(0, 120, 2) for x in range(0, 288, 2)
               if a.pixelColor(x, y) != b.pixelColor(x, y))
    check("G6b 不同名称画出不同像素（真的写了字）", diff > 30, "diff=%d" % diff)

    # ---------- G7：paint_content 钩子 ----------
    st = make_state([{"id": "g1", "type": "notes", "w": 240, "h": 180,
                      "hidden": False, "anchored": False, "x": 100, "y": 100}])
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)

    calls = []

    class Probe(wg.GlassWidget):
        def paint_content(self, painter):
            calls.append(painter)
            # 必须 setBrush：QPainter 默认 NoBrush，drawRect 只画 1px 边框，
            # 取中心像素会取到玻璃底色（首版就这么误判过）
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 0, 0))
            painter.drawRect(20, 20, 40, 40)

    w = Probe(st, dict(st.widgets[0]))
    w.show()
    app.processEvents()
    shot = w.grab().toImage()
    dpr = dpr_of(w)
    check("G7 子类 paint_content 被调用", len(calls) > 0, "calls=%d" % len(calls))
    check("G7b 内容真的画上去了（红色方块）",
          shot.pixelColor(int(40 * dpr), int(40 * dpr)).red() > 180
          and shot.pixelColor(int(40 * dpr), int(40 * dpr)).green() < 90,
          shot.pixelColor(int(40 * dpr), int(40 * dpr)).name())
    check("G9 悬浮态四角透明",
          shot.pixelColor(0, 0).alpha() == 0,
          "a=%d" % shot.pixelColor(0, 0).alpha())
    w.close()

    # ---------- G8：锚定命中填充 ----------
    st2 = make_state([{"id": "g2", "type": "notes", "w": 240, "h": 180,
                       "hidden": False, "anchored": True, "col": 6, "row": 10,
                       "colspan": 2, "rowspan": 2}])
    grid_flow.set_grid(st2, (1920, 1040))
    grid_flow.set_page(0)
    w2 = wg.GlassWidget(st2, dict(st2.widgets[0]))
    w2.show()
    app.processEvents()
    shot2 = w2.grab().toImage()
    amin = 255
    for y in range(shot2.height()):
        for x in range(shot2.width()):
            amin = min(amin, shot2.pixelColor(x, y).alpha())
    check("G8 锚定态整窗 alpha >= 2（命中填充）", amin >= 2, "min_alpha=%d" % amin)
    w2.close()

    # ---------- G11：玻璃不改组件的行为契约 ----------
    check("G11 玻璃基类仍继承 FloatingWidget",
          issubclass(wg.GlassWidget, __import__("src.widget_base", fromlist=["FloatingWidget"]).FloatingWidget))
    check("G11b 默认圆角与主题一致",
          abs(wg.glass_radius(False) - theme.GLASS_RADIUS) < 0.01,
          "%s vs %s" % (wg.glass_radius(False), theme.GLASS_RADIUS))

    # 2026-10-21 实测：本测试曾"16/16 PASS 之后段错误 rc=139"。
    # 根因 = 控件（Python 局部变量）比 QApplication 活得久——解释器退出时
    # Qt 对象析构顺序不确定，C++ 侧访问已销毁的 QApplication 直接段错误。
    # 症状很迷惑：断言全过、退出码却是 139（且只在全量串联跑时稳定复现）。
    # 正解：在 QApplication 还活着的时候显式销毁控件，别交给解释器收尾。
    for _w in (w, w2):
        try:
            _w.close()
            _w.deleteLater()
        except RuntimeError:        # 已被删（幂等）
            pass
    app.processEvents()

    if STATE.exists():
        STATE.unlink()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    try:
        main(app)
    finally:
        print("-" * 56)
        print("%d/%d checks, %d FAIL" % (len(CHECKS) - len(failures), len(CHECKS),
                                         len(failures)))
        if failures:
            print("FAILED:", ", ".join(failures))
    sys.exit(1 if failures else 0)
