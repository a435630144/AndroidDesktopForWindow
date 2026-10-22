# -*- coding: utf-8 -*-
"""把本机已装应用的图标导出成 `assets/demo_icons/*.png`（README 截图用）。

清单在 `tools/demo_apps.py`（唯一真相源），本脚本只做"找 exe -> 取 shell
图标 -> 存 PNG -> 写 manifest"这一件事。

跑法：

    python tools/make_demo_icons.py            # 导出缺失/全部图标
    python tools/make_demo_icons.py --all      # 强制重导（升级应用后重跑）
    python tools/make_demo_icons.py --sheet    # 额外拼一张目检图到 %TEMP%

## 为什么存 PNG 而不是存 exe 路径

见 `tools/demo_apps.py` 的模块说明：路径每台机器不同，`QFileIconProvider`
找不到文件时会**静默**退回空白文档图标，README 图就废了。

## 取哪一档尺寸

`QFileIconProvider` 在 Windows 上给的是 shell 的 jumbo 档（本机实测 256px，
`availableSizes` 报 320/60/40/20）。截图在 DPR=2 下最多用到 96×2=192px，
所以 256 够；统一存 256，避免同一目录里混着不同边长。

## 找不到的应用怎么办

跳过，并且**不删除**已经存在的 PNG——换台机器重跑时，某个应用没装不该让
仓库里的图标消失（出图仍然完整）。manifest 会记下每个 slug 的来源 exe，
换机器时能一眼看出哪张图是从哪儿来的。

## 版权

导出的图标是各应用的商标，仅用于展示本程序"像手机桌面一样摆放应用"的
效果，版权归各自所有者；未修改图标内容，也不用于商业用途。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

# 必须早于 PySide6 导入：外部若带 offscreen，图标里的中文标签会成方块
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QFileInfo, QSize, Qt                # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap             # noqa: E402
from PySide6.QtWidgets import QApplication, QFileIconProvider   # noqa: E402

import demo_apps                                                # noqa: E402

ICON_PX = 256


def _qapp():
    return QApplication.instance() or QApplication(sys.argv)


def extract(exe: str, provider) -> QPixmap:
    """shell 图标 -> 最大一档 pixmap（失败返回空 pixmap）。"""
    icon = provider.icon(QFileInfo(exe))
    if icon.isNull():
        return QPixmap()
    sizes = sorted(icon.availableSizes(), key=lambda s: s.width(), reverse=True)
    if sizes:
        pm = icon.pixmap(sizes[0])
        if not pm.isNull():
            if pm.width() > ICON_PX:
                pm = pm.scaled(ICON_PX, ICON_PX, Qt.KeepAspectRatio,
                               Qt.SmoothTransformation)
            return pm
    return icon.pixmap(QSize(ICON_PX, ICON_PX))


def run(force: bool = False, sheet: bool = False) -> int:
    _qapp()
    provider = QFileIconProvider()
    demo_apps.ICON_DIR.mkdir(parents=True, exist_ok=True)

    manifest = demo_apps._manifest()
    apps = {a.get("slug"): a for a in manifest.get("apps", [])}
    order = [a.get("slug") for a in manifest.get("apps", [])]

    done, skipped, missing = [], [], []
    for slug, name, _paths in demo_apps.APPS:
        out = demo_apps.ICON_DIR / ("%s.png" % slug)
        if out.exists() and not force:
            skipped.append(slug)
            continue
        exe = demo_apps.find_exe(slug)
        if not exe:
            missing.append(slug)
            continue
        pm = extract(exe, provider)
        if pm.isNull() or pm.width() < 32:
            missing.append(slug)
            continue
        pm.save(str(out), "PNG")
        apps[slug] = {"slug": slug, "name": name, "file": out.name,
                      "source": exe, "px": pm.width()}
        if slug not in order:
            order.append(slug)
        done.append((slug, pm.width()))

    order = [s for s in order if s in apps]
    # 清单按 APPS 顺序排：目录顺序即桌面顺序，别让重跑打乱它
    order = [s for s, _n, _p in demo_apps.APPS if s in apps]
    demo_apps.ICON_DIR.mkdir(parents=True, exist_ok=True)
    demo_apps.MANIFEST.write_text(
        json.dumps({"note": "由 tools/make_demo_icons.py 生成；"
                            "图标为各应用商标，仅用于展示效果",
                    "apps": [apps[s] for s in order]},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    print("导出 %d 个，跳过（已存在）%d 个，缺 %d 个"
          % (len(done), len(skipped), len(missing)))
    for slug, px in done:
        print("  + %-11s %dpx" % (slug, px))
    if missing:
        print("  缺（本机没装，保留既有 PNG，不影响出图）：%s"
              % ", ".join(missing))
    still = demo_apps.missing()
    if still:
        print("  !! 这些 slug 仍然没有 PNG，截图会退回 shell 图标或字母块：%s"
              % ", ".join(still))

    if sheet:
        _sheet()
    return 0 if not still else 1


def _sheet():
    """拼一张目检图（%TEMP%/demo_icons_sheet.png），确认没有"空白文档"。"""
    rows = [(demo_apps.entry(s)["name"], demo_apps.icon_file(s))
            for s, _n, _p in demo_apps.APPS]
    rows = [(n, p) for n, p in rows if p]
    cell, cols = 150, 5
    lines = max(1, (len(rows) + cols - 1) // cols)
    sheet = QPixmap(cols * cell, lines * (cell + 24))
    sheet.fill(QColor(30, 34, 44))
    p = QPainter(sheet)
    for i, (name, path) in enumerate(rows):
        x, y = (i % cols) * cell, (i // cols) * (cell + 24)
        from PySide6.QtGui import QIcon
        pm = QIcon(str(path)).pixmap(QSize(120, 120))
        p.drawPixmap(x + 15, y + 8, pm)
        p.setPen(QColor(232, 236, 244))
        p.drawText(x + 8, y + cell + 10, name)
    p.end()
    out = Path(os.environ.get("TEMP", "/tmp")) / "demo_icons_sheet.png"
    sheet.save(str(out))
    print("目检图：%s" % out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="强制重导全部图标")
    ap.add_argument("--sheet", action="store_true", help="额外拼一张目检图")
    a = ap.parse_args()
    raise SystemExit(run(force=a.all, sheet=a.sheet))
