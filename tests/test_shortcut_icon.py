# -*- coding: utf-8 -*-
"""快捷方式图标：取真实图标、且**不再画任何箭头徽标**（v6e）。

用户反馈（2026-10-19 第三轮，v6d 装包后）：
    "图标的样式还得优化，左下角好像有快捷方式的箭头，不需要。另外有的图标
     会丢失图象，变成空白的图标。比如雀魂麻将 和 异形工厂2"

两件事：
1. **箭头徽标去掉**：v6 §7.1 当初是嫌壳层把它烘焙进 .lnk 图标放大后发虚，
   于是自绘了一个 25% 的锐利徽标。用户现在的意见是"根本不需要"——
   桌面图标就该是干净的。所以自绘徽标整段删除，测试从"必须有徽标"
   反向变成"绝不能有徽标"。
2. **.url 丢图标**：雀魂麻将 / 异形工厂2 都是 Steam 的 `.url`
   （`URL=steam://rungameid/...`），真实图标写在文件内部：
   ```
   [InternetShortcut]
   IconIndex=0
   IconFile=D:\\Program Files (x86)\\Steam\\steam\\games\\<hash>.ico
   ```
   旧实现把 `.url` 直接丢给 QFileIconProvider，壳层只给一张通用"链接"
   白页图 → 看起来像"空白图标"。现在先解析 IconFile 再取图标。

契约：
  C1  is_shortcut 识别 .lnk / .url（大小写不敏感）
  C2  shortcut_target_path 解析 .lnk 目标（存在才返回）
  C3  shortcut_icon_source 解析 .url 的 IconFile / IconIndex（UTF-8 / UTF-16 都能读）
  C4  .url 且 IconFile 存在 → 图标取自该文件（不走壳层通用图标）
  C5  .url 缺 IconFile / 文件不存在 / IconIndex≠0 → 回退壳层，不崩
  C6  .lnk 有目标 → 图标取自目标
  C7  .lnk 目标解析失败 → 回退 .lnk 自身
  C8  非快捷方式 → 取自身
  C9  **任何图标都不含自绘箭头**（整幅无近白像素，快捷方式与非快捷方式一致）

运行：python tests/test_shortcut_icon.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from src import appsource

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


RED = QColor(200, 30, 30)
GREEN = QColor(20, 170, 90)


class _FakeProvider:
    """确定性图标源：纯红 64×64，记录被查询的路径。"""

    def __init__(self):
        self.calls = []

    def icon(self, fi):
        self.calls.append(fi.absoluteFilePath())
        pm = QPixmap(64, 64)
        pm.fill(RED)
        return QIcon(pm)


class _FakeFI:
    TABLE = {}

    def __init__(self, path):
        self._p = str(path)

    def absoluteFilePath(self):
        return self._p

    def symLinkTarget(self):
        return self.TABLE.get(self._p)


class _Patch:
    def __init__(self, target_map=None, exists=None):
        self.provider = _FakeProvider()
        self.target_map = target_map or {}
        self.exists = exists      # None = 用真实 os.path.exists

    def __enter__(self):
        self._saved = (appsource._ICON_PROVIDER, appsource.QFileInfo,
                       appsource._path_exists)
        appsource._ICON_PROVIDER = self.provider
        _FakeFI.TABLE = self.target_map
        appsource.QFileInfo = _FakeFI
        if self.exists is not None:
            appsource._path_exists = lambda p: self.exists
        appsource._ICON_CACHE.clear()
        appsource._PIXMAP_CACHE.clear()
        return self

    def __exit__(self, *a):
        (appsource._ICON_PROVIDER, appsource.QFileInfo,
         appsource._path_exists) = self._saved
        appsource._ICON_CACHE.clear()
        appsource._PIXMAP_CACHE.clear()


def near_white(img):
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > 40 and c.red() >= 225 and c.green() >= 225 and c.blue() >= 225:
                n += 1
    return n


def make_png(path, color):
    img = QImage(64, 64, QImage.Format_ARGB32)
    img.fill(color)
    img.save(path, "PNG")


def make_url(path, icon_file=None, icon_index=0, encoding="utf-8"):
    lines = ["[InternetShortcut]", "URL=steam://rungameid/1329410"]
    if icon_file is not None:
        lines.append("IconFile=%s" % icon_file)
        lines.append("IconIndex=%d" % icon_index)
    body = "\r\n".join(lines) + "\r\n"
    Path(path).write_bytes(body.encode(encoding))


def main():
    tmp = tempfile.mkdtemp(prefix="shortcut_icon_")
    ico = os.path.join(tmp, "game.png")
    make_png(ico, GREEN)

    url_with_icon = os.path.join(tmp, "a.url")
    make_url(url_with_icon, ico)
    url_missing = os.path.join(tmp, "b.url")
    make_url(url_missing, os.path.join(tmp, "nope.png"))
    url_no_icon = os.path.join(tmp, "c.url")
    make_url(url_no_icon)
    url_index = os.path.join(tmp, "d.url")
    make_url(url_index, ico, icon_index=3)
    url_utf16 = os.path.join(tmp, "e.url")
    make_url(url_utf16, ico, encoding="utf-16")

    url_app = lambda p: {"id": "u", "name": "雀魂麻将", "kind": "file",
                         "target": p, "icon_path": p}

    # ---------- C1：识别 ----------
    check("C1 .lnk 识别为快捷方式", appsource.is_shortcut({"target": "C:/x/y.lnk"}))
    check("C1 .LNK 大写也识别", appsource.is_shortcut({"icon_path": "C:/X/Y.LNK"}))
    check("C1 .url 识别为快捷方式", appsource.is_shortcut({"target": "C:/x/z.url"}))
    check("C1 exe 不是快捷方式", not appsource.is_shortcut({"target": "C:/x/a.exe"}))
    check("C1 空 dict 不是快捷方式", not appsource.is_shortcut({}))

    # ---------- C2：.lnk 目标解析 ----------
    with _Patch(target_map={"C:/x/y.lnk": "C:/x/t.exe"}, exists=True):
        check("C2 解析到存在的目标",
              appsource.shortcut_target_path({"icon_path": "C:/x/y.lnk"}) == "C:/x/t.exe")
    with _Patch(target_map={"C:/x/y.lnk": "C:/x/t.exe"}, exists=False):
        check("C2 目标不存在返回 None",
              appsource.shortcut_target_path({"icon_path": "C:/x/y.lnk"}) is None)
    with _Patch(target_map={"C:/x/y.lnk": "C:/x/t.exe"}, exists=True):
        check("C2 非 .lnk 不解析",
              appsource.shortcut_target_path({"target": "C:/x/t.exe"}) is None)

    # ---------- C3：.url 的 IconFile 解析 ----------
    spec = appsource.shortcut_icon_source(url_app(url_with_icon))
    check("C3 解析出 IconFile", spec is not None and os.path.normcase(spec[0]) == os.path.normcase(ico),
          "spec=%s" % (spec,))
    check("C3 IconIndex 一并解析", spec is not None and spec[1] == 0, "spec=%s" % (spec,))
    spec16 = appsource.shortcut_icon_source(url_app(url_utf16))
    check("C3 UTF-16 编码的 .url 也能读",
          spec16 is not None and os.path.normcase(spec16[0]) == os.path.normcase(ico),
          "spec=%s" % (spec16,))
    check("C3 无 IconFile 返回 None",
          appsource.shortcut_icon_source(url_app(url_no_icon)) is None)
    check("C3 非 .url 返回 None",
          appsource.shortcut_icon_source({"target": "C:/x/a.lnk"}) is None)

    # ---------- C4：.url 图标取自 IconFile ----------
    with _Patch() as p:
        pm = appsource.icon_pixmap(url_app(url_with_icon), 64, 1.0)
        img = pm.toImage()
        center = img.pixelColor(img.width() // 2, img.height() // 2)
        check("C4 .url 用 IconFile 的图标（绿色）",
              center.red() < 80 and center.green() > 120, "center=%s" % (center.name(),))
        check("C4 不走壳层通用图标", p.provider.calls == [], "calls=%s" % (p.provider.calls,))

    # ---------- C5：回退 ----------
    with _Patch() as p:
        pm = appsource.icon_pixmap(url_app(url_missing), 64, 1.0)
        img = pm.toImage()
        check("C5 IconFile 不存在 → 回退壳层",
              p.provider.calls == [url_missing], "calls=%s" % (p.provider.calls,))
        check("C5 回退后仍有图标（非空）", not pm.isNull())
    with _Patch() as p:
        appsource.icon_pixmap(url_app(url_no_icon), 64, 1.0)
        check("C5 无 IconFile → 回退壳层",
              p.provider.calls == [url_no_icon], "calls=%s" % (p.provider.calls,))
    with _Patch() as p:
        appsource.icon_pixmap(url_app(url_index), 64, 1.0)
        check("C5 IconIndex≠0 → 回退壳层（QIcon 不能按序号取）",
              p.provider.calls == [url_index], "calls=%s" % (p.provider.calls,))

    # ---------- C6/C7/C8：.lnk 与普通条目 ----------
    lnk_app = {"id": "f", "name": "Obsidian", "kind": "file",
               "target": "C:/x/y.lnk", "icon_path": "C:/x/y.lnk"}
    with _Patch(target_map={"C:/x/y.lnk": "C:/x/t.exe"}, exists=True) as p:
        appsource.icon_pixmap(lnk_app, 64, 1.0)
        check("C6 .lnk 取目标图标", p.provider.calls == ["C:/x/t.exe"],
              "calls=%s" % (p.provider.calls,))
    with _Patch(target_map={"C:/x/y.lnk": ""}) as p:
        appsource.icon_pixmap(lnk_app, 64, 1.0)
        check("C7 目标解析失败回退 .lnk 自身", p.provider.calls == ["C:/x/y.lnk"],
              "calls=%s" % (p.provider.calls,))
    with _Patch() as p:
        appsource.icon_pixmap({"id": "g", "name": "a", "kind": "app",
                               "target": "C:/x/a.exe", "icon_path": "C:/x/a.exe"}, 64, 1.0)
        check("C8 普通条目取自身", p.provider.calls == ["C:/x/a.exe"],
              "calls=%s" % (p.provider.calls,))

    # ---------- C9：绝不能有自绘箭头 ----------
    with _Patch(target_map={"C:/x/y.lnk": "C:/x/t.exe"}, exists=True):
        img_lnk = appsource.icon_pixmap(lnk_app, 96, 1.0).toImage()
        check("C9 .lnk 图标无箭头徽标（整幅无近白像素）",
              near_white(img_lnk) == 0, "n_white=%d" % near_white(img_lnk))
    with _Patch():
        img_url = appsource.icon_pixmap(url_app(url_with_icon), 96, 1.0).toImage()
        check("C9 .url 图标无箭头徽标", near_white(img_url) == 0,
              "n_white=%d" % near_white(img_url))

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL shortcut_icon PASSED")
    return 0


def run_main():
    app = QApplication([])
    try:
        code = main()
    except Exception:
        import traceback
        traceback.print_exc()
        failures.append("main() 异常")
        code = 1
    return code


if __name__ == "__main__":
    sys.exit(run_main())
