# -*- coding: utf-8 -*-
"""系统托盘：常驻右下角，菜单控制整理窗口 / 小组件 / 开机自启 / 设置 / 退出。

另提供 notify_via_tray()：供 desktop_window 等模块发托盘通知（延迟绑定实例）。
"""
import os
import threading
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import autostart
from . import theme
from . import win32_layer
from .paths import asset_path
from .widget_layer import WIDGET_NAMES

_tray_instance = None


def notify_via_tray(title: str, msg: str, msecs: int = 3500):
    """全局托盘通知（无实例时静默丢弃）。"""
    if _tray_instance is not None:
        _tray_instance.notify(title, msg, msecs)


def arm_exit_watchdog(delay: float = 2.0):
    """退出看门狗：Qt 在 Windows 上退出时若托盘气泡仍在播放会死锁（已知问题），
    起一个守护线程兜底强制退出。退出前先恢复原生桌面图标。"""
    def _worker():
        time.sleep(delay)
        win32_layer.restore_native_icons()
        os._exit(0)
    threading.Thread(target=_worker, daemon=True).start()


class SystemTray:
    def __init__(self, window, storage, layer):
        global _tray_instance
        self.window = window
        self.storage = storage
        self.layer = layer
        self.openSettings = None   # 外部注入：打开设置对话框
        self.openAddApps = None    # 外部注入：打开添加应用对话框
        self.tray = QSystemTrayIcon(QIcon(asset_path("app_icon.png")))
        self.tray.setToolTip("桌面整理Demo — 右键图标查看菜单")
        self.menu = QMenu()
        self.menu.setStyleSheet(theme.MENU_QSS)
        # 每次弹出前重建：勾选态 / 模式文案 / 仅小组件下的入口增减都随
        # 当前设置走，杜绝"菜单还是上次构建时的旧状态"。
        self.menu.aboutToShow.connect(self._build_menu)
        self._widget_actions = {}
        self._build_menu()
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)
        self.window.visibilityChanged.connect(self._sync_checks)
        _tray_instance = self

    # ---------- 菜单 ----------
    def _build_menu(self):
        m = self.menu
        m.clear()
        # 2026-10-21 反馈 9：「显示原生桌面 / 小组件模式」两个条目移除——
        # 模式控制统一收口到设置页（仅小组件模式 / 显示桌面小组件），
        # 托盘只留纯动作。窗口显隐改由双击托盘图标完成（_on_activated）。

        act_add = QAction("添加应用…", m)
        act_add.triggered.connect(self._add_apps)
        m.addAction(act_add)

        act_rescan = QAction("重新扫描桌面文件", m)
        act_rescan.triggered.connect(self._rescan)
        m.addAction(act_rescan)

        # 布局切换：仅小组件模式下组件必须无界，入口不出现（窗口侧还有
        # set_layout_mode 护栏双保险）。
        if not bool(self.storage.get_setting("widgets_only")):
            from . import grid_flow
            self.act_layout = QAction(
                "切换到无界模式（自由摆布）" if not grid_flow.free_mode(self.storage)
                else "切换到网格模式（对齐网格）", m)
            self.act_layout.triggered.connect(self._toggle_layout_mode)
            m.addAction(self.act_layout)

        self.widget_menu = m.addMenu("小组件")
        self.widget_menu.setStyleSheet(theme.MENU_QSS)
        self._fill_widget_menu()

        self.act_autostart = QAction("开机自启动", m, checkable=True)
        self.act_autostart.setChecked(autostart.is_enabled())
        self.act_autostart.triggered.connect(self._toggle_autostart)
        m.addAction(self.act_autostart)

        act_settings = QAction("设置…", m)
        act_settings.triggered.connect(lambda: self.openSettings and self.openSettings())
        m.addAction(act_settings)

        m.addSeparator()
        act_quit = QAction("退出", m)
        act_quit.triggered.connect(self._quit)
        m.addAction(act_quit)

    def _fill_widget_menu(self):
        self.widget_menu.clear()
        self._widget_actions.clear()
        for entry in self.storage.widgets:
            name = WIDGET_NAMES.get(entry.get("type"), entry.get("type", ""))
            act = QAction(name, self.widget_menu, checkable=True)
            act.setChecked(not entry.get("hidden"))
            act.triggered.connect(lambda checked, eid=entry["id"]: self.layer.toggle_entry(eid, checked))
            self.widget_menu.addAction(act)
            self._widget_actions[entry["id"]] = act
        self.widget_menu.addSeparator()
        act_new = QAction("新建便签", self.widget_menu)
        act_new.triggered.connect(self.layer.add_note)
        self.widget_menu.addAction(act_new)

    # ---------- 动作 ----------
    def _toggle_window(self):
        self.window.toggle()
        self._sync_checks()

    def _add_apps(self):
        if self.openAddApps:
            self.openAddApps()

    def _rescan(self):
        added, removed = self.window.rescan_desktop()
        self.notify("重新扫描完成", "新增 %d 项，清理失效 %d 项" % (added, removed))

    def _toggle_layout_mode(self):
        """v6 §1.3：网格 <-> 无界 切换（托盘入口；切换后刷新菜单文案）。"""
        from . import grid_flow
        self.window.set_layout_mode(
            "grid" if grid_flow.free_mode(self.storage) else "free")
        self._build_menu()
        self.notify("布局模式已切换",
                    "无界模式：自由摆布、可重叠、可加空白页" if grid_flow.free_mode(self.storage)
                    else "网格模式：所有对象对齐网格")

    def _toggle_autostart(self, checked):
        autostart.set_enabled(checked)
        self.storage.set_setting("autostart", bool(checked))

    def _quit(self):
        # 先恢复原生桌面图标，再走退出流程（atexit 还会兜底一次）
        win32_layer.restore_native_icons()
        arm_exit_watchdog()
        self.storage.save()
        self.window.hide_desktop()
        QApplication.quit()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._toggle_window()
        elif reason == QSystemTrayIcon.Trigger and not self.window.isVisible():
            self.window.show_desktop()

    # ---------- 状态同步 ----------
    def _sync_checks(self):
        self.act_autostart.setChecked(autostart.is_enabled())
        for entry in self.storage.widgets:
            act = self._widget_actions.get(entry["id"])
            if act is not None:
                act.setChecked(not entry.get("hidden"))

    def show(self):
        self.tray.show()

    def notify(self, title: str, msg: str, msecs: int = 4000):
        self.tray.showMessage(title, msg, QSystemTrayIcon.Information, msecs)
