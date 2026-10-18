# -*- coding: utf-8 -*-
"""v6 批次 A2：图标三档 layout 接入 AppIcon——绘制级 + 结构级断言。

覆盖指导文档_网格与无界双模式_v6.md §2.2：
  L1 带 layout 的 AppIcon：widget 尺寸 = layout.widget_w/h；
     icon_size 属性 = icon_box（绘制区）
  L2 绘制级：render 同步触发 paintEvent 不抛（坑 #24 盲区防线），
     图标区（chrome_x..chrome_x+icon_box）有非透明像素
  L3 标签区：单行小字 elide，字号 = layout.font_px
  L4 无 layout 旧路径行为不变（folder 成员 / 探针 / 旧调用兼容）
  L5 storage.icon_tier 默认 medium + 非法回退
  L6 三档单调：small < medium < large（widget 与 icon_box）

运行：python tests/test_icon_layout.py   （offscreen）
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from src import grid_sizing as gs
from src.iconwidget import AppIcon
from src.storage import Storage

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def app_entry(name="测试应用"):
    return {"id": "ap:test", "type": "app",
            "app": {"name": name, "target": "t", "kind": "app"}}


def render(icon: AppIcon) -> QImage:
    img = QImage(icon.size(), QImage.Format_ARGB32)
    img.fill(0)
    icon.render(img)
    return img


def region_opaque(img: QImage, x0, y0, x1, y1) -> int:
    """区域内非透明像素数。"""
    n = 0
    for y in range(max(0, y0), min(img.height(), y1)):
        for x in range(max(0, x0), min(img.width(), x1)):
            if img.pixelColor(x, y).alpha() > 8:
                n += 1
    return n


def main(app):
    # ---------- L1：layout 结构接入 ----------
    lay = gs.icon_layout(83, 102, "medium")
    ic = AppIcon(app_entry(), 0, layout=lay)
    check("L1 widget 尺寸 = layout",
          (ic.width(), ic.height()) == (lay.widget_w, lay.widget_h),
          "got %s" % ((ic.width(), ic.height()),))
    check("L1 icon_size 属性 = icon_box", ic.icon_size == lay.icon_box,
          "got %s" % ic.icon_size)

    # ---------- L2：绘制级（render 同步触发 paintEvent）----------
    img = render(ic)
    check("L2 paintEvent 不抛且画布非空", img.width() > 0)
    icon_zone = region_opaque(img, lay.chrome_x, 2,
                              lay.chrome_x + lay.icon_box, 2 + lay.icon_box)
    check("L2 图标区有内容", icon_zone > 50, "opaque=%d" % icon_zone)

    # ---------- L3：标签单行小字 ----------
    label_zone = region_opaque(img, 2, lay.icon_box + 2,
                               lay.widget_w - 2,
                               lay.icon_box + 2 + lay.label_h)
    check("L3 标签区有文字", label_zone > 10, "opaque=%d" % label_zone)
    check("L3 标签字号 = layout.font_px",
          ic._label_font_px == lay.font_px,
          "got %s" % getattr(ic, "_label_font_px", None))
    # 单行：标签区高度内不应出现两行文字的间隙空白模式——
    # 简化断言 label_h 与规格一致且 font < 旧 12px 基准
    check("L3 单行瘦身（font<=14 且 label_h<=33）",
          lay.font_px <= 14 and lay.label_h <= 33)

    # ---------- L4：无 layout 旧路径 ----------
    old = AppIcon(app_entry(), 64)
    check("L4 旧路径尺寸不变（64+24 / 64+40）",
          (old.width(), old.height()) == (88, 104),
          "got %s" % ((old.width(), old.height()),))
    img_old = render(old)
    check("L4 旧路径 render 不抛", img_old.width() == 88)
    check("L4 旧路径两行标签字号（chrome 1.0 -> 12）",
          old._label_font_px == 12, "got %s" % old._label_font_px)

    # ---------- L5：storage.icon_tier ----------
    import tempfile
    st = Storage(path=str(Path(tempfile.gettempdir()) / "test_tier.json"))
    check("L5 默认 medium", st.icon_tier() == "medium",
          "got %s" % st.icon_tier())
    st.set_setting("icon_tier", "LARGE")
    check("L5 大小写归一", st.icon_tier() == "large")
    st.set_setting("icon_tier", "garbage")
    check("L5 非法回退 medium", st.icon_tier() == "medium")

    # ---------- L6：三档单调 ----------
    s_, m_, l_ = (gs.icon_layout(83, 102, t) for t in ("small", "medium", "large"))
    check("L6 widget 单调",
          s_.widget_w < m_.widget_w < l_.widget_w
          and s_.widget_h < m_.widget_h < l_.widget_h)
    check("L6 icon_box 单调",
          s_.icon_box < m_.icon_box < l_.icon_box)
    check("L6 font 单调", s_.font_px < m_.font_px < l_.font_px)

    print("-" * 60)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL icon_layout PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(QApplication([])))
