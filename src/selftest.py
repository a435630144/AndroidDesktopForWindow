# -*- coding: utf-8 -*-
"""开发自测模式：python main.py --selftest
启动界面与托盘后等待数秒 -> 诊断 + 截屏 + 写报告 -> 退出。"""
import json
from pathlib import Path

from PySide6.QtCore import QTimer


def run_selftest(app, window, layer):
    def _finish():
        from src import win32_layer
        from src.tray import arm_exit_watchdog
        from src.win32_layer import diagnose_desktop_layer
        info = {
            "attached_to_desktop": window.attached,
            "native_icons_hidden": win32_layer.native_icons_hidden(),
            "icons": len(window.icons),
            "desktop_file_entries": sum(
                1 for e in window.storage.layout if e.get("app", {}).get("kind") == "file"),
            "widgets": len(layer.widgets),
            "widgets_attached": {wid: getattr(w, "attached", None)
                                 for wid, w in layer.widgets.items()},
            "entries": len(window.storage.layout),
            "desktop_layer": diagnose_desktop_layer(),
        }
        print("[selftest]", info, flush=True)
        try:
            report = Path.cwd() / "selftest_report.txt"
            report.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
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
        arm_exit_watchdog()
        app.quit()

    QTimer.singleShot(5000, _finish)
