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


def _install_crash_logger():
    """窗口化(--windowed)构建会把 stderr 静默丢弃，启动期/事件循环里的未捕获
    异常完全看不到，导致「exe 一闪而过 / 静默退出」却查不到原因。

    这里把 traceback 落盘到 crash.log，下次跑 exe 直接看该文件即可定位。
    """
    import os
    import tempfile
    import traceback
    import datetime

    base = os.environ.get("APPDATA")
    d = os.path.join(base, "DesktopOrganizerDemo") if base else tempfile.gettempdir()
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        d = tempfile.gettempdir()
    log = os.path.join(d, "crash.log")

    def _hook(etype, exc, tb):
        try:
            with open(log, "a", encoding="utf-8") as f:
                f.write("\n=== %s ===\n" % datetime.datetime.now().isoformat())
                traceback.print_exception(etype, exc, tb, file=f)
                f.write("crash.log 路径: %s\n" % log)
        except Exception:
            pass
        try:
            sys.__excepthook__(etype, exc, tb)
        except Exception:
            pass

    sys.excepthook = _hook


# 必须在**任何重依赖导入之前**安装：冻结包一旦缺模块，import 阶段就抛
# ImportError，而 --windowed 把 stderr 丢进虚空——v6f「exe 约 12s 静默退出、
# crash.log 一片空白」的最可能真凶，就是这种"死在日志钩子之前"的启动失败。
_install_crash_logger()

from PySide6.QtCore import Qt                      # noqa: E402
from PySide6.QtGui import QIcon                    # noqa: E402
from PySide6.QtWidgets import QApplication         # noqa: E402

from src import autostart                          # noqa: E402
from src import win32_layer                        # noqa: E402
from src.add_apps_dialog import AddAppsDialog      # noqa: E402
from src.desktop_window import DesktopWindow       # noqa: E402
from src.paths import asset_path, ensure_app_dirs  # noqa: E402
from src.settings_dialog import SettingsDialog, open_settings   # noqa: E402
from src import widget_plugin                     # noqa: E402
from src.single_instance import SingleInstance     # noqa: E402
from src.storage import Storage                    # noqa: E402
from src.tray import SystemTray                    # noqa: E402
from src.widget_layer import WidgetLayer           # noqa: E402


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
    # v9 V3：先加载用户导入的组件（外部 zip），再建组件层——否则已在布局里
    # 的插件组件会因为注册表还没有它而静默消失。
    widget_plugin.load_all()

    # 路线A（2026-10-18 用户拍板）：默认进入桌面整理模式——隐藏原生图标、
    # 桌面文件全部映射进网格。启动即无条件补扫一次（幂等，只增不减），
    # 保证升级/重装后网格不空（旧版 migrate_to_native_mode 会清空网格并
    # 关闭整理模式，已废弃为 no-op）。
    storage.ensure_desktop_clone()

    window = DesktopWindow(storage)
    window.show_desktop()

    layer = WidgetLayer(storage)
    # M6：翻页时组件与图标联动滑动（sync_page）
    window.set_widget_layer(layer)
    # 锚定小组件是网格一等公民：占位变化（落定/移动）时挤走被压住的图标
    layer.gridChanged.connect(window.on_widget_grid_changed)
    # M4：组件拖动实时预览（hover 按新占位矩形实时挤走图标，松手回退）
    layer.anchorHover.connect(window._on_widget_hover)
    layer.anchorDrop.connect(window._on_widget_drop)
    # 启动兜底：小组件 spawn 时分配的占位可能压住已有图标（旧 state 升级），
    # 此时信号还未连上，手动触发一次 displace
    window.on_widget_grid_changed()

    tray = SystemTray(window, storage, layer)
    # v9 V2：设置面板改单例 + 非模态（托盘/桌面右键/组件库共用同一个窗口）
    tray.openSettings = lambda: open_settings(window, storage, layer)
    tray.openAddApps = lambda: AddAppsDialog(window).exec()
    tray.openWidgetCenter = lambda: open_settings(window, storage, layer,
                                                 page="widgets")
    window.openSettingsRequested.connect(tray.openSettings)
    window.openAddAppsRequested.connect(tray.openAddApps)
    window.openWidgetCenterRequested.connect(tray.openWidgetCenter)
    window.quitRequested.connect(app.quit)
    tray.show()

    # 设置里开启了自启但注册表项丢失（如换目录运行）时自动修复
    autostart.sync_on_startup(storage)

    # v6 §7.4：桌面目录自动同步（QFileSystemWatcher + 1s debounce，
    # 增量增删不重排；设置里可关）
    window.set_auto_sync(bool(storage.get_setting("auto_sync_desktop")))
    app.aboutToQuit.connect(lambda: window.set_auto_sync(False))

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
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        sys.excepthook(*sys.exc_info())
        raise
