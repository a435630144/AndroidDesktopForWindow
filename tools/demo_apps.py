# -*- coding: utf-8 -*-
"""README 截图用的演示应用清单（**唯一真相源**）。

## 为什么图标要"导出成 PNG 进仓库"

截图脚本原先直接写 `C:/Windows/System32/notepad.exe` 这类系统路径，图标确实
是真的，但全是记事本、字符映射表、DirectX 诊断——一眼看去不像任何人的桌面，
README 首图的说服力就没了。换成微信 / QQ / 网易云音乐 / Chrome 这类应用，
"像手机桌面一样摆应用"这件事才立得住。

但**不能**在脚本里直接写 exe 路径：

  * QQ / 微信 / 网易云 的安装盘符与版本目录每台机器都不一样（本机在 `D:`）；
  * `QFileIconProvider` 找不到文件时**静默**退回"空白文档"通用图标，
    README 图就会变成一排蓝底白纸，而且没人会注意到。

所以：`tools/make_demo_icons.py` 把本机已装应用的图标一次性导出成
`assets/demo_icons/<slug>.png` 并写 `manifest.json`；截图脚本只读 PNG。
**任何机器、任何时间出图都是同一套图标**，与装没装这些应用无关。

## 版权

图标是各应用的商标，此处仅用于展示本程序"像手机桌面一样摆放应用"的效果，
版权归各自所有者；未修改图标内容，也不用于商业用途。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "assets" / "demo_icons"
MANIFEST = ICON_DIR / "manifest.json"

_PF = "C:/Program Files/"
_PF86 = "C:/Program Files (x86)/"
_LAD = "C:/Users/{user}/AppData/Local/".format(
    user=__import__("os").environ.get("USERNAME", ""))

# (slug, 中文名, [候选 exe 路径…])
# 候选列表按"可能性从高到低"排：先非系统盘（很多人装 D:/E:），再标准盘符，
# 最后是用户级安装目录。取第一个真实存在的。
APPS = [
    ("weixin", "微信", [
        "D:/Program Files/Tencent/Weixin/Weixin.exe",
        _PF + "Tencent/Weixin/Weixin.exe",
        _PF86 + "Tencent/WeChat/WeChat.exe",
    ]),
    ("qq", "QQ", [
        "D:/Program Files/Tencent/QQNT/QQ.exe",
        _PF + "Tencent/QQNT/QQ.exe",
        _PF86 + "Tencent/QQ/Bin/QQ.exe",
    ]),
    ("cloudmusic", "网易云音乐", [
        "D:/Program Files/NetEase/CloudMusic/cloudmusic.exe",
        _PF + "NetEase/CloudMusic/cloudmusic.exe",
        _PF86 + "Netease/CloudMusic/cloudmusic.exe",
    ]),
    ("edge", "Edge", [       # 标签宽度只放得下 8 个字符，全名会被截成 "Microsoft …"
        _PF86 + "Microsoft/Edge/Application/msedge.exe",
        _PF + "Microsoft/Edge/Application/msedge.exe",
    ]),
    ("jianying", "剪映", [
        "D:/JianyingPro/JianyingPro.exe",
        _PF + "JianyingPro/JianyingPro.exe",
        _LAD + "JianyingPro/Apps/JianyingPro.exe",
    ]),
    ("doubao", "豆包", [
        "D:/Program Files/Doubao/Doubao.exe",
        _PF + "Doubao/Doubao.exe",
        _LAD + "Doubao/Application/Doubao.exe",
    ]),
    ("quark", "夸克网盘", [
        # 版本目录会随升级变（这台机是 7.4.0.818），用 * 通配匹配
        "D:/Program Files (x86)/QuarkCloudDrive/*/quark_cloud_drive.exe",
        _PF86 + "QuarkCloudDrive/*/quark_cloud_drive.exe",
        _PF + "QuarkCloudDrive/*/quark_cloud_drive.exe",
        _LAD + "Programs/QuarkCloudDrive/quark_cloud_drive.exe",
    ]),
    ("steam", "Steam", [
        "D:/Program Files (x86)/Steam/steam.exe",
        _PF86 + "Steam/steam.exe",
        _PF + "Steam/steam.exe",
    ]),
    ("excel", "Excel", [
        _PF + "Microsoft Office/root/Office16/EXCEL.EXE",
        _PF86 + "Microsoft Office/root/Office16/EXCEL.EXE",
    ]),
    ("word", "Word", [
        _PF + "Microsoft Office/root/Office16/WINWORD.EXE",
        _PF86 + "Microsoft Office/root/Office16/WINWORD.EXE",
    ]),
    ("ppt", "PPT", [            # 弹窗里的成员名只有约 7 个字符宽，全称会被截断
        _PF + "Microsoft Office/root/Office16/POWERPNT.EXE",
        _PF86 + "Microsoft Office/root/Office16/POWERPNT.EXE",
    ]),
    ("pixpin", "PixPin", [
        _LAD + "Programs/PixPin/PixPin.exe",
        _PF + "PixPin/PixPin.exe",
    ]),
    ("postman", "Postman", [
        _LAD + "Postman/Postman.exe",
        _PF + "Postman/Postman.exe",
    ]),
    ("ima", "ima", [
        "D:/Program Files/ima.copilot/ima.copilot.exe",
        _PF + "ima.copilot/ima.copilot.exe",
        _LAD + "ima.copilot/ima.copilot.exe",
    ]),
]

# 桌面首图：12 个（4 列 × 3 行铺满，右下角空一格给文件夹会让版式显得缺角）
DESKTOP = ["weixin", "qq", "cloudmusic", "edge",
           "jianying", "doubao", "quark", "steam",
           "excel", "word", "pixpin", "postman"]

# 文件夹：品牌图标 + 两个系统小工具混放，说明两类都能进文件夹
FOLDER = {
    "name": "常用工具",
    "slugs": ["ppt", "ima"],
    "extra": [  # 不走图标包的成员：系统自带，路径稳定
        ("记事本", "C:/Windows/notepad.exe"),
        ("计算器", "C:/Windows/System32/calc.exe"),
    ],
}

# 图 7 那个"满页 3×3"弹窗：9 个成员才排满，再多一页就左右翻
POPUP_SLUGS = DESKTOP[:9]

# Dock：7 个横向排布，选形状差异大的（圆/方/异形）才看得出放大与间距
DOCK = ["weixin", "qq", "cloudmusic", "edge", "jianying", "steam", "quark"]

# 图 7 的四个文件夹：成员数 1/2/3/4，用来展示迷你缩略的四种排布
FOLDER_SETS = [
    ("社交", "1 个成员 · 居中", ["weixin"], "#39649F"),
    ("影音", "2 个成员 · 并排", ["cloudmusic", "jianying"], "#2C7E6B"),
    ("办公", "3 个成员 · 三角", ["excel", "word", "ppt"], "#7A55A0"),
    ("工具", "4 个成员 · 田字", ["quark", "pixpin", "postman", "ima"], "#A96B2A"),
]

_BY_SLUG = {slug: (name, paths) for slug, name, paths in APPS}


def _manifest() -> dict:
    if not MANIFEST.exists():
        return {}
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:      # noqa: BLE001 —— 清单坏了不该让出图整体失败
        return {}


def find_exe(slug: str) -> str:
    """本机上的可执行文件（找不到返回空串）。

    候选里带 `*` 的走通配——安装目录常带版本号（`QuarkCloudDrive/7.4.0.818/`），
    写死版本号的话应用一升级就得改脚本。多命中时取排序最后一个（新版本）。
    """
    from glob import glob
    from os.path import exists
    _name, paths = _BY_SLUG.get(slug, ("", []))
    for p in paths:
        if "*" in p:
            hits = sorted(glob(p))
            if hits:
                return hits[-1]
            continue
        if exists(p):
            return p
    return ""


def icon_file(slug: str):
    """导出好的 PNG 图标（没有则 None）。"""
    p = ICON_DIR / ("%s.png" % slug)
    return p if p.exists() else None


def extra_members() -> list:
    """文件夹里的系统成员：[(中文名, exe)]。"""
    return list(FOLDER["extra"])


def entry(slug: str) -> dict:
    """一个 app 字典。

    `icon_path` 指向导出好的 PNG（`appsource._qicon_for` 认图片文件，
    直接 `QIcon(png)` 加载）；PNG 不在（别的机器没跑过导出脚本）时退回
    `target`，让 shell 去取——能拿到就用，拿不到才退字母占位。
    """
    name = _BY_SLUG.get(slug, (slug, []))[0]
    png = icon_file(slug)
    exe = find_exe(slug)
    out = {"name": name, "target": exe or (str(png) if png else ""), "kind": "app"}
    if png is not None:
        out["icon_path"] = str(png)
    return out


def entries(slugs=None) -> list:
    return [entry(s) for s in (slugs if slugs is not None else
                               [s for s, _n, _p in APPS])]


def tuples(slugs=None) -> list:
    """`[(中文名, 图标路径)]`——老脚本按元组取值，保留这个形状。"""
    out = []
    for e in entries(slugs):
        out.append((e["name"], e.get("icon_path") or e["target"]))
    return out


def folder_members() -> list:
    """文件夹成员（品牌 + 系统），`[(中文名, 图标路径或 exe)]`。"""
    out = tuples(FOLDER["slugs"])
    out.extend(extra_members())
    return out


def missing() -> list:
    """还没有 PNG 的 slug（导出脚本据此提示"这台机器没装它"）。"""
    return [slug for slug, _n, _p in APPS if icon_file(slug) is None]
