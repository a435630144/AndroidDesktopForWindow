# -*- coding: utf-8 -*-
"""安装器右侧产品图：`assets/wizard.png`（v10 D2，反馈 5）。

Inno 的 `WizardImageFile` 要一张**竖图**（经典尺寸 164×314，这里出 2 倍 328×628
以便高 DPI 不糊）。素材全部来自仓库里现成的真实截图
（`docs/images/01-desktop.png`），不手工拼图——素材随代码一起可重出。

跑法：python tools/make_wizard_image.py
"""
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SHOT = ROOT / "docs" / "images" / "01-desktop.png"
ICON = ROOT / "assets" / "app_icon.png"
OUT = ROOT / "assets" / "wizard.png"

W, H = 328, 628
BG_TOP = (14, 16, 24)
BG_BOT = (32, 28, 44)
ACCENT = (110, 178, 255)
DIM = (150, 160, 180)


def font(size: int, bold: bool = False):
    """中文字体：Windows 自带雅黑；找不到就退回 PIL 默认（英文还行）。"""
    names = ["msyhbd.ttc" if bold else "msyh.ttc", "segoeuib.ttf" if bold else "segoeui.ttf"]
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


def main() -> int:
    if not SHOT.exists():
        print("缺少素材：%s（先跑 tools/shot_readme.py --only 01）" % SHOT)
        return 1

    # 竖版渐变底
    canvas = Image.new("RGB", (W, H), BG_TOP)
    d = ImageDraw.Draw(canvas)
    for y in range(H):
        t = y / float(H - 1)
        d.line([(0, y), (W, y)],
               fill=tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3)))

    # 顶部品牌
    y = 36
    if ICON.exists():
        icon = Image.open(ICON).convert("RGBA").resize((56, 56), Image.LANCZOS)
        canvas.paste(icon, (28, y), icon)
    d.text((96, y + 2), "PhoneDesktop", font=font(25, True), fill=(240, 244, 252))
    d.text((96, y + 32), "安卓式 Windows 桌面整理", font=font(13), fill=DIM)

    # 真实截图：从 01-desktop.png 竖切一块（图标 + 组件同框），圆角 + 细边。
    # 切片尺寸按"给卖点清单留够位置"倒推——第一版按比例切，第 4 条卖点被裁掉了。
    shot = Image.open(SHOT).convert("RGB")
    bullets_h = 24 + 30 * 4 + 24               # 间距 + 四条卖点 + 底边留白
    slice_w = 272
    slice_h = min(320, H - 132 - bullets_h)
    crop_h = int(shot.height * 0.80)
    crop_w = int(crop_h * slice_w / float(slice_h))       # 与目标同比例，不拉伸
    left = min(40, shot.width - crop_w)
    box = (left, 0, left + crop_w, crop_h)
    slice_img = rounded(shot.crop(box).resize((slice_w, slice_h), Image.LANCZOS), 14)
    sx, sy = (W - slice_img.width) // 2, 132
    # 阴影：一层模糊黑底
    shadow = Image.new("RGBA", (slice_img.width + 24, slice_img.height + 24), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((12, 12, shadow.width - 13, shadow.height - 13),
                                             16, fill=(0, 0, 0, 120))
    canvas.paste(shadow, (sx - 12, sy - 8), shadow)
    canvas.paste(slice_img, (sx, sy), slice_img)
    d.rounded_rectangle((sx, sy, sx + slice_img.width - 1, sy + slice_img.height - 1),
                        14, outline=(255, 255, 255, 40), width=1)

    # 卖点清单
    ty = sy + slice_img.height + 26
    lines = [
        ("网格图标 · 文件夹 · 分页滑动", (230, 236, 246)),
        ("八种玻璃小组件，尺寸自适应", DIM),
        ("Dock 栏四向贴边，hover 放大", DIM),
        ("外观自定义 + 组件插件平台", DIM),
    ]
    for text, color in lines:
        d.ellipse((34, ty + 6, 40, ty + 12), fill=ACCENT if color[0] > 200 else (90, 100, 120))
        d.text((50, ty), text, font=font(13), fill=color)
        ty += 30

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT)
    print("出图 ->", OUT, canvas.size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
