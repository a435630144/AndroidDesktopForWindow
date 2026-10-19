# -*- coding: utf-8 -*-
"""「显示桌面」（Win+D）后接管桌面必须仍然可见（2026-10-20 用户反馈 F1）。

现象：接管模式下按 Win+D / 点任务栏末端「显示桌面」，接管的桌面整理界面
被一并隐藏，而原生图标已被接管隐藏 → 用户看到**完全空的桌面**。

病根：`BandGuard._check` 识别到 show desktop 态后**直接 return 暂停干预**，
注释假定"Windows 还原时会自动恢复"——但窗口被藏这件事 Windows 不会自己
还回来。而且旧判定用「Progman 落在 z-order 前 30%」的启发式，窗口总数
少时会把正常态误判成 show desktop（把窗口插进 topmost 带 = 盖住应用）。

契约：
  W1 restore_band_windows：隐藏成员 -> ShowWindow(SW_SHOWNA)（不激活）
  W2 restore_band_windows：已可见成员 -> 不再 ShowWindow（幂等）
  W3 restore_band_windows：每个成员都插到 Progman/上一个成员上方，带 NOACTIVATE
  W4 BandGuard：show desktop 态 -> 恢复可见（不是"暂停干预"）
  W5 BandGuard：退出 show desktop 态 -> 全量重排回桌面带，且不调 ShowWindow
  W6 BandGuard：正常态（Progman 非 topmost）-> 不调 ShowWindow、不插 topmost
  W7 progman_is_topmost：读 WS_EX_TOPMOST 位（与 pidx 启发式解耦）

运行：python tests/test_show_desktop.py   （offscreen，无需真实桌面）
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import win32_layer as w
from src.band_guard import BandGuard

failures = []

PROGMAN = 100
DESK, WID, SCRIM, POP = 11, 12, 13, 14
BAND = [DESK, WID, SCRIM, POP]


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


class FakeU32:
    """最小 user32 替身：z-order / 可见性 / 扩展样式 都可注入。"""

    def __init__(self, visible, topmost=False):
        self.visible = dict(visible)
        self.topmost = bool(topmost)
        self.shows = []          # [(hwnd, cmd)]
        self.sets = []           # [(hwnd, insert_after, flags)]
        self.activated = 0

    # --- 可见性 ---
    def IsWindow(self, hwnd):
        return int(hwnd) in self.visible

    def IsWindowVisible(self, hwnd):
        return bool(self.visible.get(int(hwnd), False))

    def ShowWindow(self, hwnd, cmd):
        self.shows.append((int(hwnd), int(cmd)))
        if cmd in (w.SW_SHOW, w.SW_SHOWNA):
            self.visible[int(hwnd)] = True
        elif cmd == w.SW_HIDE:
            self.visible[int(hwnd)] = False
        return True

    # --- z-order ---
    def SetWindowPos(self, hwnd, after, *a):
        # 真实签名 SetWindowPos(hwnd, after, x, y, cx, cy, flags)：
        # *a = (x, y, cx, cy, flags) -> 下标 4
        flags = a[4] if len(a) > 4 else 0
        self.sets.append((int(hwnd), int(after), int(flags)))
        return True

    def GetWindow(self, hwnd, flag):
        return 0                  # 退化 HWND_TOP 分支

    def GetForegroundWindow(self):
        return 0

    def SetForegroundWindow(self, hwnd):
        self.activated += 1
        return True

    # --- 扩展样式 ---
    def GetWindowLongW(self, hwnd, idx):
        if idx == w.GWL_EXSTYLE and self.topmost and int(hwnd) == PROGMAN:
            return w.WS_EX_TOPMOST | w.WS_EX_NOACTIVATE
        return w.WS_EX_NOACTIVATE


class World:
    """可注入的 z-order 世界：索引 0 = 最顶层。"""

    def __init__(self, z, visible, topmost=False):
        self.z = list(z)
        self.fake = FakeU32(visible, topmost=topmost)
        self.saved = (w._user32, w._enum_zorder, w._progman)

    def __enter__(self):
        w._user32 = self.fake
        w._enum_zorder = lambda: list(self.z)
        w._progman = lambda: PROGMAN
        # 层号要登记进全局表，enforce_band_order 才认这些窗口
        for h, ly in items():
            w.set_band_layer(h, ly)
        return self

    def __exit__(self, *exc):
        w._user32, w._enum_zorder, w._progman = self.saved
        for h, _ly in items():
            w.unregister_band_window(h)
        return False


def items():
    return [(DESK, w.BAND_LAYER_DESKTOP), (WID, w.BAND_LAYER_WIDGET),
            (SCRIM, w.BAND_LAYER_SCRIM), (POP, w.BAND_LAYER_POPUP)]


def make_guard():
    g = BandGuard()
    g._items = items()
    g._progman = PROGMAN
    g._in_show_desktop = False
    return g


def main(app):
    _rbw = getattr(w, "restore_band_windows", None)
    _pgt = getattr(w, "progman_is_topmost", None)
    check("W0 存在 restore_band_windows", _rbw is not None)
    check("W0 存在 progman_is_topmost", _pgt is not None)

    # ---------- W1/W2/W3：restore_band_windows 本体 ----------
    # show desktop 态：Progman 在最顶，带内窗口全部被藏
    z_show = [PROGMAN, POP, SCRIM, WID, DESK, 200, 201]
    vis_hidden = {PROGMAN: True, POP: False, SCRIM: False,
                  WID: False, DESK: False, 200: True, 201: True}
    with World(z_show, vis_hidden, topmost=True) as world:
        if _rbw is None:
            return _run_guard_checks(app)
        n = _rbw(items(), PROGMAN)
        check("W1 隐藏成员全部恢复可见", n == 4, "restored=%d" % n)
        check("W1 用 SW_SHOWNA（不激活）",
              all(cmd == w.SW_SHOWNA for _h, cmd in world.fake.shows),
              "shows=%s" % world.fake.shows)
        check("W1 恢复后 IsWindowVisible 为真",
              all(world.fake.IsWindowVisible(h) for h in BAND))
        check("W3 每个成员都做了 SetWindowPos", len(world.fake.sets) == 4,
              "sets=%d" % len(world.fake.sets))
        check("W3 SetWindowPos 全程 NOACTIVATE",
              all(flags & w.SWP_NOACTIVATE for _h, _a, flags in world.fake.sets),
              "sets=%s" % world.fake.sets)
        check("W3 从未激活任何窗口（不抢焦点）", world.fake.activated == 0)

    # 已可见 -> 幂等：一次 ShowWindow 都不该发生
    vis_shown = {PROGMAN: True, POP: True, SCRIM: True, WID: True, DESK: True}
    with World(z_show, vis_shown, topmost=True) as world:
        n2 = _rbw(items(), PROGMAN)
        check("W2 已可见成员不再 ShowWindow（幂等）",
              n2 == 0 and world.fake.shows == [], "restored=%d shows=%s"
              % (n2, world.fake.shows))

    _run_guard_checks(app)


def _run_guard_checks(app):
    z_show = [PROGMAN, POP, SCRIM, WID, DESK, 200, 201]
    vis_hidden = {PROGMAN: True, POP: False, SCRIM: False,
                  WID: False, DESK: False, 200: True, 201: True}

    # ---------- W4：BandGuard show desktop 态 -> 主动恢复 ----------
    with World(z_show, vis_hidden, topmost=True) as world:
        g = make_guard()
        g._check()
        check("W4 show desktop 态被识别", g._in_show_desktop is True)
        check("W4 主动调 ShowWindow 恢复（不再是空桌面）",
              len(world.fake.shows) == 4,
              "shows=%d" % len(world.fake.shows))
        check("W4 恢复期间不抢焦点", world.fake.activated == 0)

    # ---------- W5：退出 show desktop -> 重排回桌面带 ----------
    vis_back = {PROGMAN: True, POP: True, SCRIM: True, WID: True, DESK: True}
    # 退出瞬间：我们的窗口还漂在应用窗口之上（未归位）-> 必须重排
    z_back = [POP, SCRIM, WID, DESK, 200, 201, PROGMAN]
    with World(z_back, vis_back, topmost=False) as world:
        g = make_guard()
        g._in_show_desktop = True          # 上一轮处于 show desktop
        g._check()
        check("W5 退出态被清空", g._in_show_desktop is False)
        check("W5 触发全量重排（SetWindowPos 有调用）",
              len(world.fake.sets) >= 1, "sets=%d" % len(world.fake.sets))
        check("W5 退出时不额外 ShowWindow",
              world.fake.shows == [], "shows=%s" % world.fake.shows)

    # ---------- W6：正常态（Progman 非 topmost，即使窗口很少）----------
    z_normal = [200, 201, 202, POP, SCRIM, WID, DESK, PROGMAN]
    with World(z_normal, vis_back, topmost=False) as world:
        g = make_guard()
        g._check()
        check("W6 窗口很少也不会误判 show desktop", g._in_show_desktop is False)
        check("W6 正常态不调 ShowWindow", world.fake.shows == [],
              "shows=%s" % world.fake.shows)

    # ---------- W7：progman_is_topmost 与 pidx 解耦 ----------
    _pgt = getattr(w, "progman_is_topmost", None)
    if _pgt is None:
        return
    with World([PROGMAN, 200, 201], {PROGMAN: True, 200: True, 201: True},
               topmost=True):
        check("W7a Progman 带 TOPMOST 位 -> True",
              _pgt(PROGMAN) is True)
    with World([200, 201, PROGMAN], {PROGMAN: True, 200: True, 201: True},
               topmost=False):
        check("W7b Progman 无 TOPMOST 位 -> False（即便窗口数极少）",
              _pgt(PROGMAN) is False)


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    crashed = None
    try:
        main(app)
    except Exception:
        import traceback
        traceback.print_exc()
        crashed = "exception"
    finally:
        print("")
        if crashed or failures:
            print("FAILED %d: %s" % (len(failures), failures))
            sys.stdout.flush()
            os._exit(1)
        print("ALL PASSED")
        sys.stdout.flush()
        os._exit(0)
