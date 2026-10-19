# -*- coding: utf-8 -*-
"""桌面带守护：周期性把桌面层窗口拉回"Progman 正上方"的桌面带。

触发场景：切显示器 / 壁纸、explorer 重启等可能把窗口挤出桌面带
（一旦漂移，组件就会盖在应用窗口之上）。只在检测到漂移时才重新插入，
正常情况每轮只做一次廉价的 z-order 遍历。

### 2026-10-19 重写：从「一位判定」到「层号堆栈」

旧实现把「在带内」定义成**紧贴 Progman 上方一位**，而带内同时有桌面窗口、
小组件、幕布、文件夹弹窗四个成员——每个窗口只有最底下那个满足判定，于是
每 1.5 秒全体重插一遍：

  - 小组件被插到桌面窗口**之下** → 全屏整理窗口的 HTCLIENT 吞掉点击
    （用户反馈「组件选不中、右键穿透到底层菜单」）；
  - 层级反复抖动 → 文件夹玻璃闪、焦点被桌面抢回（反馈「一移动鼠标就丢焦点」）。

现在每个窗口登记一个层号（desktop 10 < widget 20 < scrim 30 < popup 40），
守护只校验「相对顺序 + 紧贴 Progman」，被破坏时才整段重排。正常态
零 SetWindowPos。

关键边界——"显示桌面"（Win+D / 点任务栏末端）：
  此时 Windows 会把 Progman 提升到 z-order 前部（topmost 带）来盖住
  应用窗口。实测此状态下强行插入会把我们的窗口带进普通 z-order 带的
  顶部区域，等用户还原显示桌面时组件将漂移到应用窗口之间（会盖应用）。
  因此该模式下必须暂停干预；还原后 Windows 会自动恢复窗口的相对位置
  （实测 Progman 回底部时桌面带窗口随之回到其正上方），
  守护只需在退出该模式后兜底重挂一次。
"""
from PySide6.QtCore import QObject, QTimer

from . import win32_layer


class BandGuard(QObject):
    def __init__(self, parent=None, interval_ms: int = 1500, on_tick=None):
        super().__init__(parent)
        self._items = []  # [(hwnd, layer)]：本守护负责的窗口（共享全局层表）
        self._on_tick = on_tick  # 每轮额外回调（如保持原生图标隐藏）
        self._progman = win32_layer._progman()
        self._in_show_desktop = False
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._check)

    # ---------- 跟踪管理 ----------
    def track(self, widget, below_hwnd: int = 0,
              layer: int = win32_layer.BAND_LAYER_DESKTOP):
        """登记一个要守护的窗口。

        签名兼容旧调用（第二个位置参数曾是 below_hwnd）：layer 关键字优先，
        below_hwnd 保留给极少数需要「插到某窗口下方」的历史路径（当前无）。
        """
        try:
            hwnd = int(widget.winId())
        except Exception:
            return
        if not hwnd:
            return
        if (hwnd, layer) not in self._items:
            self._items = [(h, ly) for h, ly in self._items if h != hwnd]
            self._items.append((hwnd, layer))
        win32_layer.set_band_layer(hwnd, layer)
        if not self._timer.isActive():
            self._timer.start()

    def untrack(self, widget):
        try:
            hwnd = int(widget.winId())
        except Exception:
            return
        self._items = [(h, ly) for h, ly in self._items if h != hwnd]
        win32_layer.unregister_band_window(hwnd)
        if not self._items and self._timer.isActive():
            self._timer.stop()

    # ---------- 周期检查 ----------
    def _check(self):
        try:
            progman = win32_layer._progman()
            if not progman:
                return
            # explorer 重启等情况：Progman 句柄变化，全部重新挂载
            if progman != self._progman:
                self._progman = progman
                self._in_show_desktop = False
                win32_layer.enforce_band_order(progman)
                self._tick_hook()
                return

            wins = win32_layer._enum_zorder()
            if progman not in wins:
                return
            pidx = wins.index(progman)
            total = len(wins)

            # "显示桌面"模式识别：Progman 被提到 z-order 前部
            # （正常态 Progman 位于最底部一两位）
            show_desktop = 0 <= pidx < max(60, int(total * 0.3))
            if show_desktop:
                self._in_show_desktop = True
                return  # 暂停干预，交给 Windows 还原
            if self._in_show_desktop:
                # 退出显示桌面：兜底重挂（Windows 通常已自动还原相对位置）
                self._in_show_desktop = False
                win32_layer.enforce_band_order(progman, wins)
                self._tick_hook()
                return

            # 交互型组件正被用户操作时跳过（激活态会自然浮在应用窗口之上，
            # 这是输入所必需的；失焦后下一轮自动回带）
            fg = win32_layer._user32.GetForegroundWindow()
            if fg and fg in [h for h, _ in self._items]:
                self._tick_hook()
                return
            win32_layer.enforce_band_order(progman, wins)
            self._tick_hook()
        except Exception:
            return

    def _tick_hook(self):
        if self._on_tick is None:
            return
        try:
            self._on_tick()
        except Exception:
            pass

    def _remount_all(self, progman):
        try:
            win32_layer.enforce_band_order(progman)
        except Exception:
            pass
