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
        self.act_toggle = QAction("隐藏桌面整理", m, checkable=True)
        self.act_toggle.setChecked(self.window.isVisible())
        self.act_toggle.triggered.connect(self._toggle_window)
        m.addAction(self.act_toggle)

        self.act_organize = QAction("桌面整理模式（隐藏原生图标，框选/自动克隆）", m, checkable=True)
        self.act_organize.setChecked(bool(self.storage.get_setting("hide_native_icons")))
        self.act_organize.triggered.connect(self._toggle_organize)
        m.addAction(self.act_organize)

        act_add = QAction("添加应用…", m)
        act_add.triggered.connect(self._add_apps)
        m.addAction(act_add)

        act_rescan = QAction("重新扫描桌面文件", m)
        act_rescan.triggered.connect(self._rescan)
        m.addAction(act_rescan)

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

    def _toggle_organize(self, checked):
        """切换桌面整理模式：开=隐藏原生图标全盘接管；关=恢复系统原生桌面。"""
        self.storage.set_setting("hide_native_icons", bool(checked))
        self.window.apply_native_icons_setting()
        if checked:
            if not self.storage.layout:
                self.storage.ensure_desktop_clone()
            self.storage.set_setting("auto_clone_desktop", True)
            self.window.rebuild()
        self.notify("桌面整理模式" + ("已开启" if checked else "已关闭"),
                    "隐藏原生图标并由整理桌面接管，可框选 / 批量拖动" if checked
                    else "已恢复系统原生桌面，右键 / 点击 / 框选全部原生")

    def _add_apps(self):
        if self.openAddApps:
            self.openAddApps()

    def _rescan(self):
        added, removed = self.window.rescan_desktop()
        self.notify("重新扫描完成", "新增 %d 项，清理失效 %d 项" % (added, removed))

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
        self.act_toggle.setChecked(self.window.isVisible())
        self.act_toggle.setText("隐藏桌面整理" if self.window.isVisible() else "显示桌面整理")
        self.act_autostart.setChecked(autostart.is_enabled())
        self.act_organize.setChecked(bool(self.storage.get_setting("hide_native_icons")))
        for entry in self.storage.widgets:
            act = self._widget_actions.get(entry["id"])
            if act is not None:
                act.setChecked(not entry.get("hidden"))

    def show(self):
        self.tray.show()

    def notify(self, title: str, msg: str, msecs: int = 4000):
        self.tray.showMessage(title, msg, QSystemTrayIcon.Information, msecs)
