# -*- coding: utf-8 -*-
"""安装器向导图：`assets/wizard.png` + `assets/wizard_small.png`（v13a 重绘）。

- wizard.png      328×628（经典 164×314 的 2 倍，高 DPI 不糊）——欢迎页/完成页侧图
- wizard_small.png 128×128（64×64 的 2 倍）——modern 向导每页左上角小图

视觉与 `assets/app_icon_*` 同一套设计语言：深石板机身 + 浅灰屏幕 +
灰阶磁贴 + 橙色高亮。素材来自新图标主稿，不手工拼色。

跑法：python tools/make_wizard_image.py
"""
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "assets" / "app_icon_512.png"
OUT = ROOT / "assets" / "wizard.png"
OUT_SMALL = ROOT / "assets" / "wizard_small.png"

# 取色自 app_icon_512.png（2026-10-24 新图标）
BG_TOP = (43, 47, 53)        # #2b2f35 机身
BG_BOT = (58, 63, 71)        # #3a3f47 磁贴深灰
CARD = (240, 240, 240)       # #f0f0f0 屏幕
TEXT = (240, 240, 240)
DIM = (152, 160, 168)        # #98a0a8
ORANGE = (255, 155, 57)      # #ff9b39 高亮
TEAL = (40, 48, 56)          # #283038 侧栏

W, H = 328, 628
SW = 128


def font(size: int, bold: bool = False):
    names = ["msyhbd.ttc" if bold else "msyh.ttc",
             "segoeuib.ttf" if bold else "segoeui.ttf"]
    for name in names:
        for base in (os.environ.get("WINDIR", r"C:\Windows") + r"\Fonts", ""):
            try:
                return ImageFont.truetype(os.path.join(base, name) if base else name, size)
            except Exception:
                continue
    return ImageFont.load_default()


def rounded(im: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius, fill=255)
    out = im.convert("RGBA")
    out.putalpha(mask)
    return out


def gradient(size, top, bot):
    w, h = size
    img = Image.new("RGB", size, top)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / float(h - 1) if h > 1 else 0
        d.line([(0, y), (w, y)],
               fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return img


def main() -> int:
    if not ICON.exists():
        print("缺少素材：%s（先确保新图标 512 稿在位）" % ICON)
        return 1

    icon = Image.open(ICON).convert("RGBA")

    # ---------- wizard.png ----------
    canvas = gradient((W, H), BG_TOP, BG_BOT).convert("RGBA")
    d = ImageDraw.Draw(canvas)

    # 顶部品牌：图标 + 中文名 + 英文名（两行，不再混在一行）
    y = 32
    ic = icon.resize((64, 64), Image.LANCZOS)
    canvas.paste(ic, (28, y), ic)
    d.text((104, y + 4), "掌镜桌面", font=font(26, True), fill=TEXT)
    d.text((104, y + 38), "PhoneDesktop", font=font(13), fill=DIM)

    # 主视觉：新图标放大居中 + 橙色高亮条
    hero = icon.resize((200, 200), Image.LANCZOS)
    hx = (W - 200) // 2
    hy = 128
    shadow = Image.new("RGBA", (224, 224), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((12, 12, 211, 211), 28, fill=(0, 0, 0, 90))
    canvas.paste(shadow, (hx - 12, hy - 6), shadow)
    canvas.paste(hero, (hx, hy), hero)
    d.rounded_rectangle((hx + 40, hy + 212, hx + 160, hy + 218), 3, fill=ORANGE)

    # 卖点四条
    ty = hy + 240
    lines = [
        ("网格图标 · 文件夹 · 分页滑动", TEXT),
        ("玻璃小组件 · 尺寸自适应", DIM),
        ("Dock 四向贴边 · 悬停放大", DIM),
        ("外观自定义 · 组件插件平台", DIM),
    ]
    for text, color in lines:
        d.ellipse((34, ty + 6, 42, ty + 14), fill=ORANGE if color[0] > 200 else (120, 128, 136))
        d.text((54, ty), text, font=font(13), fill=color)
        ty += 32

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT)
    print("出图 ->", OUT, canvas.size)

    # ---------- wizard_small.png（每页左上角） ----------
    small = gradient((SW, SW), TEAL, BG_BOT).convert("RGBA")
    ds = ImageDraw.Draw(small)
    sic = icon.resize((88, 88), Image.LANCZOS)
    small.paste(sic, ((SW - 88) // 2, 20), sic)
    ds.rounded_rectangle((40, 112, 88, 117), 3, fill=ORANGE)
    small.save(OUT_SMALL)
    print("出图 ->", OUT_SMALL, small.size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
