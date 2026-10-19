# -*- coding: utf-8 -*-
"""受控实验：调用 win32_layer 隐藏原生图标，轮询 10 秒看是否被别人抢回。

结束**无条件恢复**。只操作 SysListView32 的可见性，不移动/关闭任何窗口。
用法：python tools/probe_hide_stability.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import win32_layer as w


def state():
    dv = w._find_defview()
    lv = w._find_icon_list(dv)
    vis = bool(w._user32.IsWindowVisible(lv)) if lv else None
    return dv, lv, vis


def main():
    dv, lv, vis = state()
    print("DefView =", dv, " ListView =", lv, " 初始 visible =", vis)
    try:
        ok = w.set_native_icons_visible(False)
        print("hide 调用返回 =", ok)
        for i in range(11):
            _, _, v = state()
            print("  t=%2ds  visible=%s  hidden_flag=%s" % (i, v, w.native_icons_hidden()))
            if i < 10:
                time.sleep(1)
    finally:
        w.set_native_icons_visible(True)
        _, _, v = state()
        print("已恢复，visible =", v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
