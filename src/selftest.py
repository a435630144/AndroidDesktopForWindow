# -*- coding: utf-8 -*-
"""开发自测模式：python main.py --selftest
启动界面与托盘后等待数秒 -> 诊断 + 截屏 + 写报告 -> 退出。

2026-10-20（打包自测暴露）：统计代码曾写
`e.get("app", {}).get("kind")`，而文件夹条目的 `app` 是显式 `null`
→ `.get` 默认值只在**键不存在**时生效，回调当场 AttributeError。
更糟的是异常发生在 QTimer 回调里：Qt 打印完 traceback 就继续跑事件循环，
`arm_exit_watchdog()` / `app.quit()` 永远走不到，`--selftest` 于是永久挂住。
现在统计抽成 `collect_info()`（可单独测），并且 `finally` 里无条件退出。
"""
import json
from pathlib import Path

from PySide6.QtCore import QTimer

from .storage import entry_app


def collect_info(window, layer) -> dict:
    """采集自测诊断信息。纯读取，不抛异常（脏条目走 entry_app 兜底）。"""
    from . import win32_layer
    from .win32_layer import diagnose_desktop_layer

    layout = window.storage.layout
    return {
        "attached_to_desktop": window.attached,
        "native_icons_hidden": win32_layer.native_icons_hidden(),
        "icons": len(window.icons),
        "desktop_file_entries": sum(
            1 for e in layout if entry_app(e).get("kind") == "file"),
        "widgets": len(layer.widgets),
        "widgets_attached": {wid: getattr(w, "attached", None)
                             for wid, w in layer.widgets.items()},
        "entries": len(layout),
        "desktop_layer": diagnose_desktop_layer(),
    }


def run_selftest(app, window, layer):
    def _finish():
        from .tray import arm_exit_watchdog
        try:
            info = collect_info(window, layer)
            print("[selftest]", info, flush=True)
            try:
                report = Path.cwd() / "selftest_report.txt"
                report.write_text(json.dumps(info, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
                print("[selftest] report ->", report, flush=True)
            except Exception as e:
                print("[selftest] report failed:", e, flush=True)
            try:
                from PIL import ImageGrab
                out = Path.cwd() / "selftest_shot.png"
                ImageGrab.grab().save(out)
                print("[selftest] screenshot ->", out, flush=True)
            except Exception as e:
                print("[selftest] screenshot failed:", e, flush=True)
        except Exception:
            # 自测自身的 bug 不许把进程挂死：打印后照常退出
            import traceback
            traceback.print_exc()
        finally:
            arm_exit_watchdog()
            app.quit()

    QTimer.singleShot(5000, _finish)
