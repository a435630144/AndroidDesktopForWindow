# -*- coding: utf-8 -*-
"""桌面带守护：周期性把桌面层窗口拉回"Progman 正上方"的桌面带。

触发场景：切显示器 / 壁纸、explorer 重启等可能把窗口挤出桌面带
（一旦漂移，组件就会盖在应用窗口之上）。只在检测到漂移时才重新插入，
正常情况每轮只做一次廉价的 z-order 遍历。

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
        self._items = []  # [(hwnd, below_hwnd)]  below_hwnd 预留：插到某桌面带窗口下方
        self._on_tick = on_tick  # 每轮额外回调（如保持原生图标隐藏）
        self._progman = win32_layer._progman()
        self._in_show_desktop = False
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._check)

    # ---------- 跟踪管理 ----------
    def track(self, widget, below_hwnd: int = 0):
        try:
            hwnd = int(widget.winId())
        except Exception:
            return
        if hwnd and (hwnd, below_hwnd) not in self._items:
            self._items.append((hwnd, below_hwnd))
        if not self._timer.isActive():
            self._timer.start()

    def untrack(self, widget):
        try:
            hwnd = int(widget.winId())
        except Exception:
            return
        self._items = [(h, b) for h, b in self._items if h != hwnd]
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
                self._remount_all(progman)
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
                self._remount_all(progman)
                return

            for hwnd, below in list(self._items):
                if not win32_layer._user32.IsWindowVisible(hwnd):
                    continue  # 隐藏中的窗口不抢占桌面带
                if hwnd == win32_layer._user32.GetForegroundWindow():
                    # 交互型组件（便签 / 面板）正被用户操作：激活态会自然浮在
                    # 应用窗口之上，这是输入所必需的；失焦后下一轮自动回带。
                    continue
                if below:
                    if not win32_layer.is_in_desktop_band(below, progman):
                        win32_layer._insert_above(below, progman)
                    if not win32_layer.is_above(hwnd, below):
                        win32_layer._insert_above(hwnd, below)
                elif not win32_layer.is_in_desktop_band(hwnd, progman):
                    win32_layer._insert_above(hwnd, progman)

            if self._on_tick is not None:
                try:
                    self._on_tick()
                except Exception:
                    pass
        except Exception:
            return

    def _remount_all(self, progman):
        for hwnd, below in list(self._items):
            if not win32_layer._user32.IsWindowVisible(hwnd):
                continue
            try:
                if below:
                    if not win32_layer.is_in_desktop_band(below, progman):
                        win32_layer._insert_above(below, progman)
                    win32_layer._insert_above(hwnd, below)
                else:
                    win32_layer._insert_above(hwnd, progman)
            except Exception:
                continue
