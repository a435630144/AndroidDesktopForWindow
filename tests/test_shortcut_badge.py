# -*- coding: utf-8 -*-
"""v6 批次 D §7.1：快捷方式箭头徽章（反馈 10，TDD Red→Green）。

规格（指导文档_网格与无界双模式_v6.md §7.1）：
  - 现状：壳层把快捷方式箭头 overlay 直接烘焙进 .lnk 图标 pixmap——
    图标放大后箭头占到边长 ~35% 且带柔和阴影发虚（原生只是左下小角标）
  - 修复：徽标尺寸 = 图标边长的 ~25%，锐利渲染（去模糊），位置与原生一致（左下）
  - 实现：快捷方式改取**目标**的干净图标（.lnk → symLinkTarget 解析），
    再自绘白箭 + 深色描边的 crisp 徽章；目标解析不了的回退壳层图标（不加徽标）

覆盖：
  S1  is_shortcut 识别 .lnk/.url（大小写不敏感）
  S2  shortcut_badge_size = round(边长*0.25)，最小 6
  S3  shortcut_target_path 解析（存在才返回）/ 失败 None / 非 lnk None
  S4  渲染级：可解析快捷方式 → 源取目标图标 + 左下徽标 + 不越 25% + 不上半屏
  S5  渲染级：非快捷方式 → 无徽标
  S6  渲染级：解析失败 → 回退 .lnk 自身图标、无徽标（不与壳层 overlay 叠箭头）
  S7  渲染级：徽标 crisp——实心亮白核心 + 深色描边（非软渐变）

运行：python tests/test_shortcut_badge.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QFileInfo
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from src import appsource

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


RED = QColor(200, 30, 30)


class _FakeProvider:
    """确定性图标源：纯红 64×64，并记录被查询的路径。"""

    def __init__(self):
        self.calls = []

    def icon(self, fi):
        self.calls.append(fi.absoluteFilePath())
        pm = QPixmap(64, 64)
        pm.fill(RED)
        return QIcon(pm)


class _FakeFI:
    """假 QFileInfo：按表返回 symLinkTarget（None = 解析失败）。"""

    TABLE = {}

    def __init__(self, path):
        self._p = str(path)

    def absoluteFilePath(self):
        return self._p

    def symLinkTarget(self):
        return self.TABLE.get(self._p)


class _Patch:
    """上下文式 monkeypatch：图标源 / QFileInfo / 存在性 / 缓存。"""

    def __init__(self, target_map=None, exists=True):
        self.provider = _FakeProvider()
        self.target_map = target_map or {}
        self.exists = exists
        self._saved = {}

    def __enter__(self):
        self._saved = (appsource._ICON_PROVIDER, appsource.QFileInfo,
                       appsource._path_exists)
        appsource._ICON_PROVIDER = self.provider
        _FakeFI.TABLE = self.target_map
        appsource.QFileInfo = _FakeFI
        appsource._path_exists = lambda p: self.exists
        appsource._ICON_CACHE.clear()
        appsource._PIXMAP_CACHE.clear()
        return self

    def __exit__(self, *a):
        (appsource._ICON_PROVIDER, appsource.QFileInfo,
         appsource._path_exists) = self._saved
        appsource._ICON_CACHE.clear()
        appsource._PIXMAP_CACHE.clear()


def near_white(img, x, y):
    c = img.pixelColor(x, y)
    return c.red() >= 225 and c.green() >= 225 and c.blue() >= 225


def main(app):
    # ---------- S1：识别 ----------
    check("S1 .lnk 识别为快捷方式",
          appsource.is_shortcut({"target": "C:/x/y.lnk"}))
    check("S1 .LNK 大写也识别",
          appsource.is_shortcut({"icon_path": "C:/x/Y.LNK"}))
    check("S1 .url 识别为快捷方式",
          appsource.is_shortcut({"target": "C:/x/z.url"}))
    check("S1 普通 exe 不是快捷方式",
          not appsource.is_shortcut({"target": "C:/x/a.exe"}))
    check("S1 空 dict 不是快捷方式",
          not appsource.is_shortcut({}))

    # ---------- S2：尺寸 = 25% ----------
    check("S2 96 → 24（25%）", appsource.shortcut_badge_size(96) == 24)
    check("S2 48 → 12", appsource.shortcut_badge_size(48) == 12)
    check("S2 32 → 8", appsource.shortcut_badge_size(32) == 8)
    check("S2 小尺寸钳到最小 6", appsource.shortcut_badge_size(20) == 6)

    # ---------- S3：目标解析 ----------
    with _Patch(target_map={"C:/x/y.lnk": "C:/x/t.exe"}):
        check("S3 解析到目标（存在）",
              appsource.shortcut_target_path(
                  {"icon_path": "C:/x/y.lnk"}) == "C:/x/t.exe")
    with _Patch(target_map={"C:/x/y.lnk": "C:/x/t.exe"}, exists=False):
        check("S3 目标不存在返回 None",
              appsource.shortcut_target_path(
                  {"icon_path": "C:/x/y.lnk"}) is None)
    with _Patch(target_map={"C:/x/y.lnk": ""}):
        check("S3 解析失败（空）返回 None",
              appsource.shortcut_target_path(
                  {"icon_path": "C:/x/y.lnk"}) is None)
    with _Patch(target_map={"C:/x/y.lnk": "C:/x/t.exe"}):
        check("S3 非 .lnk 不解析",
              appsource.shortcut_target_path(
                  {"target": "C:/x/t.exe"}) is None)

    # ---------- S4：可解析快捷方式：目标源 + 徽标 ----------
    lnk_app = {"id": "f1", "name": "y", "kind": "file",
               "target": "C:/x/y.lnk", "icon_path": "C:/x/y.lnk"}
    with _Patch(target_map={"C:/x/y.lnk": "C:/x/t.exe"}) as p:
        pm = appsource.icon_pixmap(lnk_app, 96, 1.0)
        img = pm.toImage()
        w, h = img.width(), img.height()
        check("S4 源图标取自目标（非 .lnk 自身）",
              p.provider.calls == ["C:/x/t.exe"],
              "calls=%s" % (p.provider.calls,))
        # 徽标像素（亮白）只应出现在左下徽标盒内
        badge = max(6, round(96 * 0.25))           # 24
        inset = int(max(1.0, 96 * 0.02))           # ≈2
        bx0, by0 = inset, h - inset - badge
        n_badge = sum(1 for yy in range(by0 - 1, min(h, by0 + badge + 1))
                      for xx in range(bx0 - 1, min(w, bx0 + badge + 1))
                      if near_white(img, xx, yy))
        check("S4 左下徽标盒内有徽标像素", n_badge > 20, "n=%d" % n_badge)
        # 越界检查：右下半屏 / 上半屏不得有徽章像素
        n_right = sum(1 for yy in range(h // 2, h)
                      for xx in range(bx0 + badge + 4, w)
                      if near_white(img, xx, yy))
        n_top = sum(1 for yy in range(0, h // 2)
                    for xx in range(0, w) if near_white(img, xx, yy))
        check("S4 右下半屏无徽标（位置=左下）", n_right == 0, "n=%d" % n_right)
        check("S4 上半屏无徽标", n_top == 0, "n=%d" % n_top)
        # 尺寸封顶 ~26%（bbox 不能超出徽标盒 + 2px 容差）
        xs = [xx for yy in range(0, h) for xx in range(0, w)
              if near_white(img, xx, yy)]
        ys = [yy for yy in range(0, h) for xx in range(0, w)
              if near_white(img, xx, yy)]
        bw, bh = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        check("S4 徽标不越 25%+容差（bbox ≤ 26px）",
              bw <= 26 and bh <= 26, "bbox=%sx%s" % (bw, bh))
        # 源图标仍是红色（徽标只覆盖左下角一小块）
        check("S4 图标主体保留（中心仍红）",
              img.pixelColor(w // 2, h // 2) == RED)

    # ---------- S5：非快捷方式无徽标 ----------
    exe_app = {"id": "f2", "name": "a", "kind": "app",
               "target": "C:/x/a.exe", "icon_path": "C:/x/a.exe"}
    with _Patch() as p:
        pm = appsource.icon_pixmap(exe_app, 96, 1.0)
        img = pm.toImage()
        n = sum(1 for yy in range(img.height() // 2, img.height())
                for xx in range(0, img.width() // 2)
                if near_white(img, xx, yy))
        check("S5 非快捷方式无徽标", n == 0, "n=%d" % n)
        check("S5 源取自自身路径",
              p.provider.calls == ["C:/x/a.exe"], "calls=%s" % (p.provider.calls,))

    # ---------- S6：解析失败回退 ----------
    with _Patch(target_map={"C:/x/y.lnk": ""}) as p:
        pm = appsource.icon_pixmap(lnk_app, 96, 1.0)
        img = pm.toImage()
        n = sum(1 for yy in range(img.height() // 2, img.height())
                for xx in range(0, img.width() // 2)
                if near_white(img, xx, yy))
        check("S6 解析失败回退 .lnk 自身图标",
              p.provider.calls == ["C:/x/y.lnk"],
              "calls=%s" % (p.provider.calls,))
        check("S6 回退路径不加徽标（不与壳层 overlay 叠箭头）",
              n == 0, "n=%d" % n)

    # ---------- S7：crisp（实心亮白 + 深色描边，非软渐变） ----------
    with _Patch(target_map={"C:/x/y.lnk": "C:/x/t.exe"}):
        pm = appsource.icon_pixmap(lnk_app, 96, 1.0)
        img = pm.toImage()
        badge = 24
        inset = int(max(1.0, 96 * 0.02))
        bx0, by0 = inset, 96 - inset - badge
        core = [img.pixelColor(xx, yy)
                for yy in range(by0, by0 + badge)
                for xx in range(bx0, bx0 + badge)]
        whites = [c for c in core if c.red() >= 235 and c.green() >= 235]
        darks = [c for c in core if c.red() <= 90 and c.green() <= 90]
        check("S7 徽标核心是实心亮白（≥235）", len(whites) > 30,
              "n=%d" % len(whites))
        check("S7 徽标有深色描边（≤90，硬边不模糊）", len(darks) > 8,
              "n=%d" % len(darks))

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL shortcut_badge PASSED")
    return 0


def run_main():
    app = QApplication([])
    try:
        code = main(app)
    except Exception:
        import traceback
        traceback.print_exc()
        failures.append("main() 异常")
        code = 1
    return code


if __name__ == "__main__":
    sys.exit(run_main())
