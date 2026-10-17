# -*- coding: utf-8 -*-
"""生成应用图标（PNG + ICO）：蓝紫渐变圆角方块 + 2x2 桌面网格意象。
用法：python tools/make_icon.py [输出目录，默认项目 assets/]
"""
from pathlib import Path

from PIL import Image, ImageDraw


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _rounded_mask(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def make_icon(size: int = 1024) -> Image.Image:
    top, bottom = (86, 160, 250), (62, 84, 220)  # 天蓝 -> 深蓝紫
    grad = Image.new("RGBA", (1, size))
    for y in range(size):
        grad.putpixel((0, y), (*_lerp(top, bottom, y / (size - 1)), 255))
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.paste(grad.resize((size, size)), (0, 0), _rounded_mask(size, int(size * 0.22)))
    d = ImageDraw.Draw(img)
    pad = size * 0.22
    gap = size * 0.06
    cell = (size - pad * 2 - gap) / 2
    r = int(size * 0.05)
    for x, y in ((pad, pad), (pad + cell + gap, pad),
                 (pad, pad + cell + gap), (pad + cell + gap, pad + cell + gap)):
        d.rounded_rectangle([x, y, x + cell, y + cell], radius=r, fill=(255, 255, 255, 235))
    return img


def main():
    import sys
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    icon = make_icon()
    icon.save(out_dir / "app_icon.png")
    icon.save(out_dir / "app_icon.ico",
              sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("written:", out_dir / "app_icon.png")
    print("written:", out_dir / "app_icon.ico")


if __name__ == "__main__":
    main()
