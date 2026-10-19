# -*- coding: utf-8 -*-
"""壁纸保留：隐藏原生图标时不能连壁纸一起摘掉。

2026-10-19 用户反馈："开启之后背景是全黑的，我要的是原始桌面的壁纸。"

根因（本机 Win11 build 26300 实测）：旧实现隐藏整个 SHELLDLL_DefView，
而 DefView 参与壁纸绘制链 —— SW_HIDE 之后整屏变成纯黑；恢复 DefView
壁纸立刻回来（像素从 (20,20,20) 变回 (26,148,201) 一类壁纸色）。
这也解释了为什么动态壁纸软件会失效：容器被摘掉，挂在它下面的渲染层
一并消失。

修法：只隐藏 DefView 内部的图标列表 SysListView32，容器保持可见。

契约：
  W1 隐藏调用返回成功
  W2 **DefView 仍然可见**（壁纸活着）
  W3 图标列表 SysListView32 被隐藏（图标消失）
  W4 恢复后列表重新可见
  W5 找不到 SysListView32 的老系统回退为隐藏 DefView（功能不退步）
  W6 幂等：连续两次隐藏不产生异常、状态稳定
  W7 升级路径：若 DefView 已被旧版本藏起来，新的隐藏调用会先把它 SHOW 回来

全部在假 user32 上跑，绝不碰真实桌面窗口。

运行：python tests/test_wallpaper_preserved.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import win32_layer

SW_HIDE, SW_SHOW = 0, 5
DV_HWND, LV_HWND = 1001, 1002

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


class FakeUser32:
    """只实现 set_native_icons_visible 用到的入口。

    本用例只覆盖「图标列表 / DefView 两条路径」，不带子窗口树；
    第三方桌面整理图层的识别与隐藏由 test_third_party_overlay.py 覆盖。
    """

    def __init__(self, visible=None):
        self.visible = dict(visible or {DV_HWND: True, LV_HWND: True})
        self.calls = []

    def GetWindow(self, hwnd, cmd):
        return 0  # 没有子窗口：DefView 下不挂任何第三方图层

    def ShowWindow(self, hwnd, cmd):
        self.calls.append((int(hwnd), int(cmd)))
        self.visible[int(hwnd)] = (int(cmd) != SW_HIDE)
        return True

    def IsWindowVisible(self, hwnd):
        return bool(self.visible.get(int(hwnd), False))

    def IsWindow(self, hwnd):
        return int(hwnd) in self.visible


def run_case(has_listview=True, dv_initially_visible=True):
    """跑一次独立场景，返回 (结果, fake, 调用列表)。"""
    fake = FakeUser32({DV_HWND: dv_initially_visible, LV_HWND: True})
    saved = (win32_layer._user32, win32_layer._find_defview,
             win32_layer._find_icon_list, win32_layer._native_icons_hidden)
    win32_layer._user32 = fake
    win32_layer._find_defview = lambda: DV_HWND
    win32_layer._find_icon_list = lambda dv=0: (LV_HWND if has_listview else 0)
    win32_layer._native_icons_hidden = False
    try:
        ok_hide = win32_layer.set_native_icons_visible(False)
        state_after_hide = dict(fake.visible)
        ok_hide2 = win32_layer.set_native_icons_visible(False)   # 幂等
        state_after_hide2 = dict(fake.visible)
        ok_show = win32_layer.set_native_icons_visible(True)
        state_after_show = dict(fake.visible)
        hidden_flag = win32_layer._native_icons_hidden
        return dict(ok_hide=ok_hide, ok_hide2=ok_hide2, ok_show=ok_show,
                    hide=state_after_hide, hide2=state_after_hide2,
                    show=state_after_show, hidden_flag=hidden_flag,
                    calls=list(fake.calls))
    finally:
        (win32_layer._user32, win32_layer._find_defview,
         win32_layer._find_icon_list, win32_layer._native_icons_hidden) = saved


def main():
    r = run_case(has_listview=True)

    check("W1 隐藏调用成功", r["ok_hide"], str(r["calls"]))
    check("W2 隐藏后 DefView 仍可见（壁纸活着）", r["hide"][DV_HWND] is True,
          "dv_visible=%s" % r["hide"].get(DV_HWND))
    check("W3 图标列表被隐藏（图标消失）", r["hide"][LV_HWND] is False,
          "lv_visible=%s" % r["hide"].get(LV_HWND))

    check("W6 重复隐藏幂等", r["ok_hide2"] and r["hide2"][DV_HWND] is True
          and r["hide2"][LV_HWND] is False, str(r["hide2"]))

    check("W4 恢复后列表可见", r["ok_show"] and r["show"][LV_HWND] is True,
          "lv_visible=%s" % r["show"].get(LV_HWND))
    check("W4b 恢复后 DefView 也可见", r["show"][DV_HWND] is True)
    check("W4c 恢复后标志位复位", r["hidden_flag"] is False)

    # ---------- W5：没有 SysListView32 的老系统 ----------
    r2 = run_case(has_listview=False)
    check("W5 无列表时回退隐藏 DefView", r2["ok_hide"] and r2["hide"][DV_HWND] is False,
          "dv_visible=%s" % r2["hide"].get(DV_HWND))
    check("W5b 回退路径恢复可见", r2["ok_show"] and r2["show"][DV_HWND] is True)

    # ---------- W7：从旧版本升级（DefView 已被藏起来） ----------
    r3 = run_case(has_listview=True, dv_initially_visible=False)
    check("W7 旧的 DefView 隐藏态会被重新 SHOW", r3["hide"][DV_HWND] is True,
          "dv_visible=%s calls=%s" % (r3["hide"].get(DV_HWND), r3["calls"][:4]))

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
