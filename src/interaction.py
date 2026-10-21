# -*- coding: utf-8 -*-
"""交互方式（v9 V4，指导文档_v9.md §5）。

两套操作逻辑，用户自己在设置页切换：

  windows（默认，现行语义）
      单击选中 / 双击打开 / 按住拖动 / 空白处框选

  mobile（模仿手机桌面）
      单击直接打开 / 长按弹菜单（含「选择」）/ 长按后滑动转拖动 /
      菜单 ▸ 选择 进入多选（左上角空心圆 → 选中变对钩）/
      多选态可批量操作（合并文件夹 / 移到其它页 / 删除）/
      空白处滑动整页翻页

为什么单独一个模块：`interaction_mode` 这一个开关同时被三个地方读
（`iconwidget` 的按下/抬起分流、`desktop_window` 的框选与翻页、设置页）。
如果三处各自 `storage.get_setting("interaction_mode") == "mobile"`，就会出现
"新写一个入口时忘了判断"的老毛病（本项目 v7 的图标尺寸三源就是这么坏的）。
这里给唯一入口：`mode(storage)` 负责归一化（脏值一律回落默认），调用方
只比较字符串。
"""
from __future__ import annotations

WINDOWS = "windows"
MOBILE = "mobile"
DEFAULT = WINDOWS

# 设置页下拉用（顺序即展示顺序，第一项是默认）
MODES = ((WINDOWS, "Windows 习惯"), (MOBILE, "手机习惯"))

SETTING = "interaction_mode"

# 长按阈值：450ms 是 iOS 长按（0.5s）与 Android（500ms）之间的折中，
# 比双击间隔（系统默认 500ms）短一点——按住不放的用户不会先触发双击。
LONG_PRESS_MS = 450

# 长按后"算滑动"的距离（逻辑像素）。比 QApplication.startDragDistance()
# 默认的 10 略大：菜单刚弹出时手指/鼠标常有 1~3px 抖动，不该立刻变成拖动。
LONG_SLIDE_SLOP = 14

# 空白处滑动翻页的位移阈值：一页宽度的一半过于苛刻，60px 是"明显在滑"的
# 下限（触控板上一次短滑约 40~80px）。
SWIPE_PX = 60


def normalize(value) -> str:
    """把任意值收敛成合法模式（脏值 / 旧版本缺键 -> 默认）。"""
    v = str(value or "").strip().lower()
    return v if v in (WINDOWS, MOBILE) else DEFAULT


def mode(storage) -> str:
    """当前交互方式（唯一判定入口）。storage 为 None 时返回默认。"""
    if storage is None:
        return DEFAULT
    try:
        return normalize(storage.get_setting(SETTING))
    except Exception:      # noqa: BLE001 —— 设置读取失败不该让点击失效
        return DEFAULT


def set_mode(storage, value) -> str:
    """写入并落盘，返回归一化后的值。"""
    m = normalize(value)
    if storage is not None:
        storage.set_setting(SETTING, m)
        storage.save()
    return m


def is_mobile(storage) -> bool:
    return mode(storage) == MOBILE


def label(value) -> str:
    """设置页/菜单里显示的文字。"""
    m = normalize(value)
    return dict(MODES).get(m, MODES[0][1])


def describe(value) -> str:
    """设置页的说明文案（告诉用户两种模式各自怎么操作）。"""
    if normalize(value) == MOBILE:
        return ("单击直接打开应用；按住 0.45 秒弹出菜单（可选「选择」批量操作）；"
                "按住后滑动即拖动；在空白处左右/上下滑动切换分页。")
    return ("单击选中、双击打开；按住拖动；在空白处拖出选框批量选择。")
