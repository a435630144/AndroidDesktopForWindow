# -*- coding: utf-8 -*-
"""第三方桌面整理图层：只藏 explorer 的图标列表不够。

2026-10-19 用户反馈（v6c 壁纸修好后的下一轮）：
    "可以看到壁纸了，但是原生桌面的图标怎么也出来了 挤到一起了"

现场取证（tools/probe_deskgoskin*.py + 截图对照）：
    SHELLDLL_DefView
      ├─ TXMiniSkin      ← 腾讯桌面整理 DesktopMgr64.exe，全屏，自绘一份桌面图标
      └─ SysListView32   ← explorer 的图标列表

旧实现只 SW_HIDE 了 SysListView32，DeskGo 那份图标仍在原处渲染，
与我们的网格图标错位叠在一起 = "挤到一起"。实验证明隐藏 TXMiniSkin
后那套大图标整体消失、壁纸不受影响、且 12 秒内不会被抢回。
（隐藏整个 DefView 会把 DeskGo 一起摘掉，但壁纸也没了——上一轮已否决。）

契约：
  O1 接管桌面时，DefView 下「全屏尺寸 + 非系统控件」的子窗口一并隐藏
  O2 图标列表仍按原逻辑隐藏、DefView 本身保持可见（壁纸契约 W2 不变）
  O3 非全屏的小窗口（残留微型 WorkerW 等）不被误伤
  O4 恢复时只恢复「我们亲手藏掉的」图层，原本就隐藏的不去动它
  O5 第三方把图层重新 SHOW 回来后，third_party_overlays_visible() 能发现，
     再次隐藏能重新藏住（守护轮询依赖这个探针）
  O6 SysHeader32 这类系统控件不参与
  O7 跨进程自愈：进程被强杀后，新进程（内存字典为空）仍能把图层恢复回来
  O8 句柄被回收后类名对不上，不误 SHOW 到别的窗口
  O9 隐藏幂等

全部跑在假 user32 上，状态文件也重定向到临时目录，绝不碰真实桌面。

运行：python tests/test_third_party_overlay.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import win32_layer

SW_HIDE, SW_SHOW = 0, 5
DV_HWND = 2001
LV_HWND = 2002
SKIN_HWND = 2003       # 第三方桌面整理全屏层（如 TXMiniSkin）
SMALL_HWND = 2004      # 残留微型 WorkerW（136×38）
HEADER_HWND = 2005     # SysHeader32
ALIEN_HWND = 2006      # 句柄被回收后复用的陌生窗口

SCREEN = (1536, 864)
FULL = (0, 0, 1536, 864)
CLASSES = {
    DV_HWND: "SHELLDLL_DefView",
    LV_HWND: "SysListView32",
    SKIN_HWND: "TXMiniSkin",
    SMALL_HWND: "WorkerW",
    HEADER_HWND: "SysHeader32",
    ALIEN_HWND: "Notepad",
}
RECTS = {
    DV_HWND: FULL, LV_HWND: FULL, SKIN_HWND: FULL,
    SMALL_HWND: (0, 0, 136, 38), HEADER_HWND: (0, 0, 0, 0),
}

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


class FakeRect:
    def __init__(self, rect):
        self.left, self.top, self.right, self.bottom = rect


class FakeUser32:
    def __init__(self, visible=None):
        self.visible = dict(visible or {})
        self.calls = []

    def ShowWindow(self, hwnd, cmd):
        self.calls.append((int(hwnd), int(cmd)))
        self.visible[int(hwnd)] = (int(cmd) != SW_HIDE)
        return True

    def IsWindowVisible(self, hwnd):
        return bool(self.visible.get(int(hwnd), False))

    def IsWindow(self, hwnd):
        return int(hwnd) in self.visible


class Env:
    """把 win32_layer 接到假窗口树上，状态文件重定向到临时目录。"""

    def __init__(self, visible_overrides=None):
        visible = {DV_HWND: True, LV_HWND: True, SKIN_HWND: True,
                   SMALL_HWND: False, HEADER_HWND: False}
        visible.update(visible_overrides or {})
        self.fake = FakeUser32(visible)
        self.state_dir = tempfile.mkdtemp(prefix="overlay_state_")
        self.state_file = os.path.join(self.state_dir, "hidden_overlays.json")

    def __enter__(self):
        w = win32_layer
        self.saved = (w._user32, w._find_defview, w._find_icon_list,
                      w._iter_children, w._class_of, w._rect_of,
                      w._screen_size, w._native_icons_hidden,
                      w._OVERLAY_STATE_PATH)
        saved_overlays = dict(w._third_party_overlays)
        self.saved_overlays = saved_overlays

        def _iter_children(parent):
            if int(parent) == DV_HWND:
                for h in (LV_HWND, SKIN_HWND, SMALL_HWND, HEADER_HWND):
                    yield h

        w._user32 = self.fake
        w._find_defview = lambda: DV_HWND
        w._find_icon_list = lambda dv=0: LV_HWND
        w._iter_children = _iter_children
        w._class_of = lambda h: CLASSES.get(int(h), "")
        w._rect_of = lambda h: FakeRect(RECTS.get(int(h), (0, 0, 0, 0)))
        w._screen_size = lambda: SCREEN
        w._native_icons_hidden = False
        w._OVERLAY_STATE_PATH = self.state_file
        w._third_party_overlays.clear()
        w._third_party_overlays.update(saved_overlays)
        return self

    def __exit__(self, *exc):
        w = win32_layer
        (w._user32, w._find_defview, w._find_icon_list, w._iter_children,
         w._class_of, w._rect_of, w._screen_size, w._native_icons_hidden,
         w._OVERLAY_STATE_PATH) = self.saved
        w._third_party_overlays.clear()
        w._third_party_overlays.update(self.saved_overlays)
        return False


def simulate_crash(env, alien=False):
    """模拟进程被强杀：内存字典清空、状态文件保留；可选模拟句柄被回收复用。"""
    win32_layer._third_party_overlays.clear()
    if alien:
        CLASSES_BACKUP[SKIN_HWND] = CLASSES[SKIN_HWND]
        CLASSES[SKIN_HWND] = "Notepad"
        return CLASSES_BACKUP
    return None


CLASSES_BACKUP = {}


def main():
    # ---------- O1 / O2 / O3 / O6：接管时的隐藏范围 ----------
    with Env() as env:
        fake = env.fake
        ok = win32_layer.set_native_icons_visible(False)
        after = dict(fake.visible)
        probe = win32_layer.third_party_overlays_visible()
        ok2 = win32_layer.set_native_icons_visible(False)
        after2 = dict(fake.visible)
        ok_show = win32_layer.set_native_icons_visible(True)
        shown = dict(fake.visible)
        calls = list(fake.calls)

    check("O1 第三方全屏层被隐藏", ok and after[SKIN_HWND] is False,
          "skin_visible=%s" % after.get(SKIN_HWND))
    check("O2 图标列表被隐藏", after[LV_HWND] is False)
    check("O2b DefView 保持可见（壁纸契约不破）", after[DV_HWND] is True)
    check("O3 微型子窗口未被误伤", not [c for c in calls if c[0] == SMALL_HWND],
          "calls=%s" % [c for c in calls if c[0] == SMALL_HWND])
    check("O6 SysHeader32 不参与", not [c for c in calls if c[0] == HEADER_HWND])
    check("O9 隐藏幂等", ok2 and after2[SKIN_HWND] is False)
    check("O5b 藏好后探针报告无可见第三方层", probe is False)
    check("O4 恢复后第三方层重新可见", ok_show and shown[SKIN_HWND] is True,
          "skin_visible=%s" % shown.get(SKIN_HWND))
    check("O4b 恢复后图标列表可见", shown[LV_HWND] is True)

    # ---------- O4c：原本就隐藏的第三方层不被 SHOW ----------
    with Env(visible_overrides={SKIN_HWND: False}) as env:
        fake = env.fake
        win32_layer.set_native_icons_visible(False)
        win32_layer.set_native_icons_visible(True)
        shown = dict(fake.visible)
    check("O4c 原本就隐藏的图层不被我们 SHOW 出来", shown[SKIN_HWND] is False,
          "skin_visible=%s" % shown.get(SKIN_HWND))

    # ---------- O5：第三方把图层抢回来 ----------
    with Env() as env:
        fake = env.fake
        win32_layer.set_native_icons_visible(False)
        fake.visible[SKIN_HWND] = True       # DeskGo 重新 SHOW
        seen = win32_layer.third_party_overlays_visible()
        again = win32_layer.set_native_icons_visible(False)
        rehidden = fake.visible[SKIN_HWND]
        after2 = win32_layer.third_party_overlays_visible()
    check("O5 抢回后探针能发现", seen is True)
    check("O5c 再次隐藏能重新藏住", again and rehidden is False)
    check("O5d 再藏后探针归零", after2 is False)

    # ---------- O7：跨进程自愈（被强杀后新进程仍能恢复） ----------
    with Env() as env:
        win32_layer.set_native_icons_visible(False)
        state_exists = os.path.exists(env.state_file)
        simulate_crash(env)
        restored = win32_layer.set_native_icons_visible(True)
        skin_visible = env.fake.visible[SKIN_HWND]
        state_cleaned = not os.path.exists(env.state_file)
    check("O7a 隐藏后状态落盘", state_exists, env.state_file)
    check("O7b 新进程（内存为空）仍能恢复图层", restored and skin_visible is True,
          "skin_visible=%s" % skin_visible)
    check("O7c 恢复后清掉状态文件", state_cleaned)

    # ---------- O8：句柄复用后类名对不上，不误 SHOW ----------
    with Env() as env:
        win32_layer.set_native_icons_visible(False)
        simulate_crash(env, alien=True)
        try:
            env.fake.visible[SKIN_HWND] = False
            win32_layer.set_native_icons_visible(True)
            alien_visible = env.fake.visible[SKIN_HWND]
        finally:
            if SKIN_HWND in CLASSES_BACKUP:
                CLASSES[SKIN_HWND] = CLASSES_BACKUP.pop(SKIN_HWND)
    check("O8 类名不符不误 SHOW", alien_visible is False,
          "skin_visible=%s" % alien_visible)

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
