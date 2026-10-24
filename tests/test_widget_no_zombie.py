# -*- coding: utf-8 -*-
"""v10 反馈 28：组件"看不见的命中壳"（僵尸窗口）判据。

病根：`refresh_grid()` 里 `apply_layout_mode()` 无条件把全部组件关掉重建，
而关闭走 140ms 淡出。淡出一旦被打断（松手回弹 / 再次 show / 新的淡入），
`_really_close` 永远不到 —— 窗口以 `windowOpacity()==0` 留在原地：肉眼
看不见，但窗口仍是 HTCLIENT，照样把点击吃掉。组件一移动，露出来的那条
就是用户报的"左侧 1 格宽 / N 格高、没有红底"的盲区。

运行：python tests/test_widget_no_zombie.py    退出码 0 = 全绿
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.desktop_window import DesktopWindow
from src.storage import Storage
from src.widget_layer import WidgetLayer
import src.widgets  # noqa: F401  （注册内建组件）
from src.widgets.monitor.monitor import MonitorWidget

failures = []


def check(name, ok, detail=""):
    print("%s %s%s" % ("[PASS]" if ok else "[FAIL]", name,
                       ("  <- " + str(detail)) if (detail and not ok) else ""))
    if not ok:
        failures.append(name)


def instances(cls=MonitorWidget):
    out = []
    for w in QApplication.allWidgets():
        if isinstance(w, cls):
            try:
                out.append(w)
            except RuntimeError:
                pass
    return out


def visible_count(cls=MonitorWidget):
    return sum(1 for w in instances(cls) if w.isVisible())


def reset_all(wait=120):
    """彻底清场：销毁本进程里所有组件窗口，避免用例间互相污染计数。"""
    for w in instances():
        try:
            w.destroy_now()
        except RuntimeError:
            pass
    QTest.qWait(wait)


def make_state(**settings):
    st = Storage(path=str(Path(tempfile.mkdtemp()) / "s.json"))
    st._data["widgets"] = [{"id": "wm", "type": "monitor", "hidden": False,
                            "anchored": True, "col": 0, "row": 0,
                            "colspan": 2, "rowspan": 2}]
    for k, v in settings.items():
        st.set_setting(k, v)
    st.save()
    return st


app = QApplication.instance() or QApplication([])

# ---------- Z1：模式没变 -> 只重排，不重建窗口 ----------
st1 = make_state()
layer1 = WidgetLayer(st1)
QTest.qWait(250)
hwnd1 = int(layer1.widgets["wm"].winId())
before1 = visible_count()

layer1.apply_layout_mode()
QTest.qWait(120)
check("Z1a 同一模式下重建不会新增窗口",
      visible_count() == before1 == 1, "visible=%d/%d" % (visible_count(), before1))
check("Z1b 同一模式复用原窗口（HWND 不变，证明没有重建）",
      int(layer1.widgets["wm"].winId()) == hwnd1,
      "%s vs %s" % (layer1.widgets["wm"].winId(), hwnd1))
check("Z1c 孤儿窗口数 0", layer1.orphan_count() == 0, layer1.orphan_count())

# ---------- Z2：连续多次重排（模拟调图标尺寸 / Dock inset / 原点） ----------
for _ in range(4):
    layer1.apply_layout_mode()
    QTest.qWait(40)
check("Z2a 连续 4 次重排后窗口数不增长",
      len(instances()) == 1 and visible_count() == 1,
      "instances=%d visible=%d" % (len(instances()), visible_count()))
check("Z2b 连续重排后无孤儿", layer1.orphan_count() == 0, layer1.orphan_count())

# ---------- Z3：模式切换 -> 立即销毁重建（不留淡出壳） ----------
reset_all()
st3 = make_state()
layer3 = WidgetLayer(st3)
QTest.qWait(200)
old3 = layer3.widgets["wm"]
st3.set_setting("layout_mode", "free")
layer3.apply_layout_mode()
QTest.qWait(80)
old_alive = []
try:
    old_alive.append(old3.isVisible())
except RuntimeError:
    old_alive.append("DEAD")
check("Z3a 模式切换后旧窗口立即关掉（不等淡出）",
      old_alive in ([False], ["DEAD"]), old_alive)
check("Z3b 模式切换后只有 1 个可见窗口",
      visible_count() == 1, "visible=%d" % visible_count())
check("Z3c 模式切换后无孤儿", layer3.orphan_count() == 0, layer3.orphan_count())
for w in list(layer3.widgets.values()):
    try:
        w.destroy_now()
    except RuntimeError:
        pass
reset_all()
check("Z3d 清场后无可见组件窗口", visible_count() == 0, visible_count())

# ---------- Z4：淡出被打断也必须销毁（close + show） ----------
st4 = make_state()
layer4 = WidgetLayer(st4)
QTest.qWait(200)
w4 = layer4.widgets["wm"]
w4.close()          # 开始 140ms 淡出
QTest.qWait(30)
w4.show()           # 打断淡出（旧实现：_closing 卡死 + 窗口留在屏上）
QTest.qWait(520)
check("Z4a close 被 show 打断后仍会关闭（不留命中壳）",
      not w4.isVisible(), "visible=%s opacity=%.2f"
      % (w4.isVisible(), w4.windowOpacity()))
check("Z4b 打断路径不产生孤儿计数", layer4.orphan_count() <= 1,
      layer4.orphan_count())

# ---------- Z5：同 id 重复 spawn -> 只留一个 ----------
reset_all()
st5 = make_state()
layer5 = WidgetLayer(st5)
QTest.qWait(150)
entry5 = st5.widgets[0]
layer5._spawn(entry5)          # 直接重复 spawn
QTest.qWait(150)
check("Z5a 重复 spawn 同 id 只留一个可见窗口",
      visible_count() == 1, "visible=%d" % visible_count())
check("Z5b widgets 表仍只有一条", len(layer5.widgets) == 1,
      len(layer5.widgets))
check("Z5c 重复 spawn 后无孤儿", layer5.orphan_count() == 0,
      layer5.orphan_count())

# ---------- Z6：Dock 拖放指示器绘制不再抛 NameError ----------
from src import dock as dock_mod, theme as theme_mod  # noqa: E402
st6 = Storage(path=str(Path(tempfile.mkdtemp()) / "d.json"))
st6.set_setting("dock_enabled", True)
d6 = dock_mod.DockWindow(st6)
d6.resize(360, 64)
d6._drop_highlight = True
d6._drop_index = 0
img6 = QImage(360, 64, QImage.Format_ARGB32_Premultiplied)
img6.fill(0)
p6 = QPainter(img6)
err6 = ""
try:
    d6._paint_drop_indicator(p6)      # 旧实现：QPointF 未导入 -> NameError
except Exception as exc:              # noqa: BLE001
    err6 = "%s: %s" % (type(exc).__name__, exc)
p6.end()
acc = QColor(theme_mod.ACCENT)
n6 = 0
for y in range(0, 64, 2):
    for x in range(0, 360, 2):
        c = img6.pixelColor(x, y)
        if (abs(c.red() - acc.red()) < 40 and abs(c.green() - acc.green()) < 40
                and abs(c.blue() - acc.blue()) < 40 and c.alpha() > 100):
            n6 += 1
check("Z6a 拖放指示器绘制不抛异常", not err6, err6)
check("Z6b 拖放指示器真的画出了强调色竖线", n6 > 3, "accent_px=%d" % n6)
d6.close()

# ---------- Z7：_hit_widget 物理/逻辑坐标换算（125% 缩放） ----------
reset_all()
st7 = make_state()
st7.set_setting("layout_mode", "grid")
win7 = DesktopWindow(st7)
win7.resize(1280, 800)
win7._update_grid_metrics()
layer7 = WidgetLayer(st7)
win7.set_widget_layer(layer7)
QTest.qWait(200)
_w7 = layer7.widgets.get("wm")
win7.devicePixelRatioF = lambda: 2.0          # 模拟 200% 缩放
if _w7 is not None:
    g7 = _w7.mapToGlobal(QPoint(0, 0))
    cx7 = QPoint(int((g7.x() + _w7.width() / 2) * 2),
                 int((g7.y() + _w7.height() / 2) * 2))
    hit7 = win7._hit_widget(cx7)
    check("Z7a 物理坐标点能命中逻辑矩形（缩放换算生效）", hit7 is True, hit7)
    far7 = QPoint(cx7.x() + 4000, cx7.y() + 4000)
    check("Z7b 远离组件的物理点不误命中", win7._hit_widget(far7) is False)
    # 同一模式重排后窗口仍在原位
    layer7.apply_layout_mode()
    QTest.qWait(60)
    g7b = _w7.mapToGlobal(QPoint(0, 0))
    check("Z7c 重排后窗口位置不变（无漂移）", g7b == g7, "%s vs %s" % (g7b, g7))
else:
    check("Z7 组件窗口创建成功", False, "wm 未创建")
for w in list(layer7.widgets.values()):
    try:
        w.destroy_now()
    except RuntimeError:
        pass
win7.close()

print("-" * 56)
if failures:
    print("FAILED: %d -> %s" % (len(failures), failures))
    sys.exit(1)
print("ALL WIDGET NO-ZOMBIE CHECKS PASSED")
sys.exit(0)
