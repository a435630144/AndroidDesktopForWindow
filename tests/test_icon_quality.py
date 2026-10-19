# -*- coding: utf-8 -*-
"""图标清晰度：就近取档，别把 256px 的 jumbo 硬缩到 55px（v6e）。

用户反馈（2026-10-19）："感觉目前的图标图片的分辨率还是不如原图标清晰。"

实测（tools/probe_icon_sharpness.py + 逐条统计 availableSizes）：
  - 桌面 42 个条目，图标源**全部**有 256px（jumbo）——不是"取不到高清"；
  - 实际渲染尺寸：icon_size=44 逻辑 px，DPR 1.25 → 55 物理 px；
  - 旧实现永远取 `max(sizes)` = 256px，再 Smooth 缩到 55px，
    相当于 4.6 倍下采样，边缘被插值糊掉；
  - Windows 原生是挑「不小于目标、且最接近」的那一档（这里是 48px，
    在 125% 缩放下就是 60 物理 px），几乎 1:1 绘制 → 更锐。

修法：`_source_pixmap_for()` 按「最小够用的档位」取源：
  升序找第一个物理宽度 ≥ 目标 × 0.95 的档；都太小才退回最大档（放大）。

契约：
  Q1 目标 55、源含 32/48/256 → 取 48 档（不取 256）
  Q2 目标 200、源含 32/48/256 → 取 256（够用的最小档）
  Q3 源全都小于目标 → 取最大档，不崩
  Q4 无 availableSizes → 退回 icon.pixmap(QSize)
  Q5 输出物理像素 = round(logical × dpr)，DPR 写回 pixmap
  Q6 缓存命中后不再重新选源（同参数两次调用返回同一对象）

运行：python tests/test_icon_quality.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from src import appsource

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def make_icon(sizes):
    """构造一个带多档位 pixmap 的 QIcon（每档颜色不同，便于判断取了哪档）。"""
    ic = QIcon()
    for i, s in enumerate(sizes):
        pm = QPixmap(s, s)
        pm.fill(0xFF000000 | (i * 40) << 8)   # 越大越绿，肉眼可辨
        ic.addPixmap(pm)
    return ic


def main():
    # ---------- Q1：就近取档 ----------
    ic = make_icon([32, 48, 256])
    pm = appsource._source_pixmap_for(ic, 55)
    check("Q1 目标 55 取 48 档（不取 256）", pm.width() == 48, "got=%d" % pm.width())

    # ---------- Q2：大目标取够用的最小档 ----------
    pm2 = appsource._source_pixmap_for(make_icon([32, 48, 256]), 200)
    check("Q2 目标 200 取 256 档", pm2.width() == 256, "got=%d" % pm2.width())

    # ---------- Q3：源全都小于目标 ----------
    pm3 = appsource._source_pixmap_for(make_icon([16, 32, 48]), 120)
    check("Q3 都太小则取最大档（放大兜底）", pm3.width() == 48, "got=%d" % pm3.width())

    # ---------- Q4：无 sizes ----------
    empty = QIcon()
    pm4 = appsource._source_pixmap_for(empty, 40)
    check("Q4 空 icon 不崩", isinstance(pm4, QPixmap))

    # ---------- Q5：输出尺寸 / DPR ----------
    app = {"id": "x", "name": "微信", "kind": "file",
           "target": "C:/x/a.exe", "icon_path": "C:/x/a.exe"}
    appsource._ICON_CACHE[("C:/x/a.exe",)] = make_icon([32, 48, 256])
    appsource._PIXMAP_CACHE.clear()
    pm5 = appsource.icon_pixmap(app, 44, 1.25)
    check("Q5 物理像素 = round(44×1.25) = 55", pm5.width() == 55, "got=%d" % pm5.width())
    check("Q5b DPR 写回 1.25", abs(pm5.devicePixelRatio() - 1.25) < 0.01,
          "dpr=%.3f" % pm5.devicePixelRatio())

    # ---------- Q6：缓存 ----------
    pm6 = appsource.icon_pixmap(app, 44, 1.25)
    check("Q6 同参数命中缓存（同一对象）", pm6 is pm5)

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL icon_quality PASSED")
    return 0


if __name__ == "__main__":
    QApplication([])
    sys.exit(main())
