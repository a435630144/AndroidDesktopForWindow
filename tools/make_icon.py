# -*- coding: utf-8 -*-
"""应用图标正式出口（v13a：新图标 UI）。

源素材是设计稿导出的三件套（用户 2026-10-24 交付，**不要用代码画回去**）：
  assets/app_icon_1024.png  1024 主稿
  assets/app_icon_512.png   512 中间稿
  assets/app_icon_new.ico   多尺寸 ICO（16/24/32/48/64/128/256）

本脚本只做**归一化拷贝**，保证 `app_icon.png` / `app_icon.ico` 这两个
下游固定文件名始终跟主稿一致（build_portable、installer、托盘、窗口
图标都只认这两个名字）。改设计稿时替换三件套后重跑即可。

用法：python tools/make_icon.py
"""
import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

SRC_PNG = ASSETS / "app_icon_1024.png"
SRC_ICO = ASSETS / "app_icon_new.ico"
OUT_PNG = ASSETS / "app_icon.png"
OUT_ICO = ASSETS / "app_icon.ico"


def main() -> int:
    if not SRC_PNG.exists() or not SRC_ICO.exists():
        print("缺少源素材：app_icon_1024.png / app_icon_new.ico（设计稿导出）")
        return 1

    # PNG：主稿直接落成下游文件名（1024 RGBA，Qt/托盘/向导图共用）
    im = Image.open(SRC_PNG)
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    im.save(OUT_PNG)
    print("written:", OUT_PNG, im.size)

    # ICO：多尺寸稿直接落成下游文件名（exe / SetupIconFile 用）
    shutil.copy2(SRC_ICO, OUT_ICO)
    chk = Image.open(OUT_ICO)
    print("written:", OUT_ICO, chk.info.get("sizes"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
