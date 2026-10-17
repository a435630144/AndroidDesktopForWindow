# -*- coding: utf-8 -*-
"""
DesktopOrganizerDemo - 第三方桌面整理 / 美化软件（最小可用 Demo）

功能：
  - 类安卓桌面网格：桌面文件克隆（可选），图标可拖拽、双击启动
  - 类安卓文件夹：把一个图标拖到另一个图标上即生成文件夹，支持拖出 / 解散
  - 批量框选：整理模式下空白处拖出橡皮筋多选，可整体拖动
  - 桌面小组件：时钟、便签、桌面面板（搜索 / 快捷文件夹 / 磁盘 / 最近下载 / 天气）
  - 常驻右下角托盘、开机自启动、设置实时生效
  - 窗口挂载到桌面层（Progman 正上方的桌面带），像原生桌面一样
    位于壁纸之上、应用窗口之下
  - 双模式：默认保持系统原生桌面（右键 / 点击 / 框选全部原生）；
    设置里可开启桌面整理模式（隐藏原生图标，由整理桌面全盘接管）

运行：
  python main.py             正常启动
  python main.py --selftest  开发自测（启动 -> 截图 -> 退出）
"""
import atexit
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from src import autostart
from src import win32_layer
from src.add_apps_dialog import AddAppsDialog
from src.desktop_window import DesktopWindow
from src.paths import asset_path, ensure_app_dirs
from src.settings_dialog import SettingsDialog
from src.single_instance import SingleInstance
from src.storage import Storage
from src.tray import SystemTray
from src.widget_layer import WidgetLayer


def main() -> int:
    ensure_app_dirs()

    app = QApplication(sys.argv)
    app.setApplicationName("DesktopOrganizerDemo")
    app.setApplicationDisplayName("桌面整理Demo")
    app.setQuitOnLastWindowClosed(False)  # 隐藏窗口不等于退出，常驻托盘
    app.setWindowIcon(QIcon(asset_path("app_icon.png")))

    # 单实例守护：防止重复运行出现多个整理窗口
    guard = SingleInstance("DesktopOrganizerDemo_SingleInstance")
    if guard.is_running():
        return 0

    # 启动自愈：上次运行若崩溃（原生图标被隐藏时强杀），先恢复再继续
    win32_layer.restore_native_icons()
    # 退出兜底：正常退出 / 异常退出都恢复原生桌面图标
    atexit.register(win32_layer.restore_native_icons)

    storage = Storage()

    # 旧版（自动克隆 + 隐藏原生图标）一次性迁移为原生模式：
    # 清空自动生成的图标网格、恢复系统原生桌面（文件不动，可手动重新扫描找回）
    storage.migrate_to_native_mode()
    # 仅当用户在设置里开启「自动克隆桌面文件」时才播种，不自行创建图标
    storage.ensure_desktop_clone()

    window = DesktopWindow(storage)
    window.show_desktop()

    layer = WidgetLayer(storage)

    tray = SystemTray(window, storage, layer)
    tray.openSettings = lambda: SettingsDialog(window, storage, layer).exec()
    tray.openAddApps = lambda: AddAppsDialog(window).exec()
    window.openSettingsRequested.connect(tray.openSettings)
    window.openAddAppsRequested.connect(tray.openAddApps)
    window.quitRequested.connect(app.quit)
    tray.show()

    # 设置里开启了自启但注册表项丢失（如换目录运行）时自动修复
    autostart.sync_on_startup(storage)

    # 首次运行：弹一条托盘气泡说明基本用法
    if storage.get_setting("first_run"):
        storage.set_setting("first_run", False)
        window.rebuild()
        tray.notify(
            "桌面整理Demo",
            "已就绪：系统桌面保持原生，可右键托盘「添加应用」把常用入口放到整理桌面；"
            "在「设置」里可开启桌面整理模式（隐藏原生图标、框选、自动克隆桌面文件）。"
            "拖一个图标到另一个上可建文件夹，从资源管理器拖文件进来即可添加。",
        )

    if "--selftest" in sys.argv[1:]:
        from src.selftest import run_selftest
        run_selftest(app, window, layer)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
