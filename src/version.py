# -*- coding: utf-8 -*-
"""构建标识：让"我到底跑的是哪个包"这个问题可以在界面上直接回答。

由来（2026-10-19 事故）：用户报"拖拽白框还是没修好"，查下来他启动的是
14:01 的旧 onedir，而修复在 19:03 的新目录里——两个包并排在 `dist/` 下，
凭文件名毫无区分度，用户没有理由知道自己点错了。

于是每个包自带一个可自证的标识：
  - **构建时刻取文件 mtime**（冻结后 = exe，源码运行 = 本文件），
    不依赖打包脚本传参，也不可能被忘记更新；
  - `VERSION` 只作为口头沟通用的短标签，每次出包顺手改。

界面上以右键菜单底部一条灰色不可点项呈现：`版本 v7b · 构建 2026-10-20 19:10`。

命名规则（别再用错系列）：
  - **首数字 = 迭代系列**（v6 的所有包是 6a/6b/…/6g；v7 的包必须从 7a 起）；
  - **小写字母 = 本迭代内第几个包**，字母没走完就说明规格没做完——
    别在 v7 只完成 B1 时就标 `7.0`，那会让人以为整个 v7 都交付了（坑 #69）。
"""
import datetime
import os
import sys

VERSION = "7b"


def build_stamp() -> datetime.datetime | None:
    """返回构建时刻（exe / 源码文件 mtime）；拿不到返回 None。"""
    try:
        base = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
        return datetime.datetime.fromtimestamp(os.path.getmtime(base))
    except Exception:
        return None


def build_time() -> str:
    """构建时刻字符串（分钟精度）；失败时返回「未知」而不是抛异常。"""
    stamp = build_stamp()
    return stamp.strftime("%Y-%m-%d %H:%M") if stamp else "未知"


def label() -> str:
    """菜单里展示的完整标识。"""
    return "版本 v%s · 构建 %s" % (VERSION, build_time())
