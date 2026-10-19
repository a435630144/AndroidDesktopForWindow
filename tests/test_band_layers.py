# -*- coding: utf-8 -*-
"""桌面带层级守护（2026-10-19 反馈 1 / 7 的根因回归）。

病根：旧守护把"在带内"定义成**紧贴 Progman 上方一位**。带内同时有桌面
窗口 / 小组件 / 幕布 / 弹窗四个成员，只有最底下那个满足判定 —— 每 1.5s
全体重插一遍：组件被压到桌面窗口之下（点不到、右键穿透）、层级抖动
（文件夹玻璃闪、焦点被抢）。

契约：
  B1 层号常量自底向上：desktop < widget < scrim < popup
  B2 顺序本来就正确 -> **零 SetWindowPos**（不再周期性抖动）
  B3 组件被压到桌面窗口之下 -> 重排成 widget 在 desktop 之上
  B4 弹窗被应用窗口埋掉 / 排到小组件下面 -> 回到带内最顶
  B5 隐藏的成员不参与（隐藏窗口不抢占桌面带）
  B6 隐藏成员恢复可见后能重新入列

运行：python tests/test_band_layers.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import win32_layer as w

failures = []
PROGMAN = 100
DESK, WID, SCRIM, POP = 11, 12, 13, 14


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


class FakeU32:
    def __init__(self, visible):
        self.visible = visible
        self.moves = []

    def IsWindowVisible(self, hwnd):
        return bool(self.visible.get(int(hwnd), False))

    def SetWindowPos(self, hwnd, after, *a):
        self.moves.append((int(hwnd), int(after)))
        return True

    def GetWindow(self, hwnd, flag):
        return 0

    def GetForegroundWindow(self):
        return 0


class World:
    """可注入的 z-order 世界：索引 0 = 最顶层。"""

    def __init__(self, z, visible=None):
        self.z = list(z)
        self.visible = {h: True for h in self.z}
        self.visible.update(visible or {})
        self.fake = FakeU32(self.visible)
        self.saved = (w._user32, w._enum_zorder, w._progman,
                      w._insert_above, w.insert_above_window, dict(w._BAND_LAYERS))
        w._user32 = self.fake
        w._enum_zorder = lambda: list(self.z)
        w._progman = lambda: PROGMAN
        w._insert_above = self._insert
        w.insert_above_window = self._insert

    def _insert(self, hwnd, above_of):
        hwnd, above_of = int(hwnd), int(above_of)
        self.fake.moves.append((hwnd, above_of))
        if hwnd in self.z:
            self.z.remove(hwnd)
        if above_of in self.z:
            self.z.insert(self.z.index(above_of), hwnd)   # above_of 之上一格
        else:
            self.z.insert(0, hwnd)
        return True

    def restore(self):
        (w._user32, w._enum_zorder, w._progman,
         w._insert_above, w.insert_above_window, layers) = self.saved
        w._BAND_LAYERS.clear()
        w._BAND_LAYERS.update(layers)


def stack(*hwnds):
    """按自底向上给出窗口，返回 z-order 列表（顶在前，Progman 最后）。"""
    order = [PROGMAN] + list(hwnds)
    return order[::-1]


def main():
    # ---------- B1 层号 ----------
    check("B1 层号自底向上递增",
          w.BAND_LAYER_DESKTOP < w.BAND_LAYER_WIDGET < w.BAND_LAYER_SCRIM
          < w.BAND_LAYER_POPUP,
          "%s" % [w.BAND_LAYER_DESKTOP, w.BAND_LAYER_WIDGET,
                  w.BAND_LAYER_SCRIM, w.BAND_LAYER_POPUP])

    # ---------- B2 正常态零动作 ----------
    world = World(stack(DESK, WID, SCRIM, POP))
    try:
        w.set_band_layer(DESK, w.BAND_LAYER_DESKTOP)
        w.set_band_layer(WID, w.BAND_LAYER_WIDGET)
        w.set_band_layer(SCRIM, w.BAND_LAYER_SCRIM)
        w.set_band_layer(POP, w.BAND_LAYER_POPUP)
        moved = w.enforce_band_order()
        check("B2 顺序正确时不重排", moved is False)
        check("B2 且零 SetWindowPos（消除 1.5s 抖动）",
              world.fake.moves == [], "moves=%s" % world.fake.moves)
    finally:
        world.restore()

    # ---------- B3 组件被压到桌面窗口之下 ----------
    world = World(stack(WID, DESK))       # 自底向上 WID 在 DESK 下面 -> 错误
    try:
        w.set_band_layer(DESK, w.BAND_LAYER_DESKTOP)
        w.set_band_layer(WID, w.BAND_LAYER_WIDGET)
        moved = w.enforce_band_order()
        check("B3 检测到错序并重排", moved is True)
        check("B3 桌面窗口紧贴 Progman、组件在其上",
              world.z[-1] == PROGMAN and world.z[-2] == DESK
              and world.z[-3] == WID, "z=%s" % world.z)
    finally:
        world.restore()

    # ---------- B4 弹窗排到小组件下面 ----------
    world = World([POP, DESK, WID, PROGMAN])   # 弹窗在最顶但顺序错乱
    try:
        w.set_band_layer(DESK, w.BAND_LAYER_DESKTOP)
        w.set_band_layer(WID, w.BAND_LAYER_WIDGET)
        w.set_band_layer(POP, w.BAND_LAYER_POPUP)
        w.enforce_band_order()
        check("B4 弹窗回到带内最顶",
              world.z[:3] == [POP, WID, DESK] and world.z[3] == PROGMAN,
              "z=%s" % world.z)
    finally:
        world.restore()

    # ---------- B5 隐藏成员不参与 ----------
    world = World(stack(DESK, WID), visible={WID: False})
    try:
        w.set_band_layer(DESK, w.BAND_LAYER_DESKTOP)
        w.set_band_layer(WID, w.BAND_LAYER_WIDGET)
        w.enforce_band_order()
        check("B5 隐藏窗口不被拉进带内",
              world.z[-1] == PROGMAN and world.z[-2] == DESK,
              "z=%s" % world.z)
    finally:
        world.restore()

    # ---------- B6 恢复可见后入列 ----------
    world = World(stack(DESK, WID), visible={WID: False})
    try:
        w.set_band_layer(DESK, w.BAND_LAYER_DESKTOP)
        w.set_band_layer(WID, w.BAND_LAYER_WIDGET)
        w.enforce_band_order()
        world.visible[WID] = True
        world.z = [WID, DESK, PROGMAN]        # 恢复后被提到最前
        w.enforce_band_order()
        check("B6 恢复显示后重新压回桌面窗口之上",
              world.z[-2] == DESK and world.z[-3] == WID,
              "z=%s" % world.z)
    finally:
        world.restore()

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL band_layers PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
