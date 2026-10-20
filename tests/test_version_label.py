# -*- coding: utf-8 -*-
"""构建标识：让界面能自证"这是哪个包的构建"。

由来：用户反馈"拖拽白框还是没修好"，实际跑的是上一轮生成的 onedir。
两个包并排在 dist/ 下、名字只差一个字母，用户没有理由知道自己点错了。

契约：
  V1 label() 同时含版本短标签与构建时刻
  V2 build_time() 是「YYYY-MM-DD HH:MM」，拿不到时降级为「未知」而非抛异常
  V3 源码运行时构建时刻 = src/version.py 的 mtime（不需要打包脚本传参）
  V4 桌面右键菜单底部有一条灰显不可点的版本项（objectName=ctxVersion）
  V5 该版本项文本含"构建"，且永远排在最后

运行：python tests/test_version_label.py   （offscreen）
"""
import datetime
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from src import version
from src.desktop_window import DesktopWindow
from src.storage import Storage

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_version_state.json"
VERSION_PY = Path(__file__).resolve().parent.parent / "src" / "version.py"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=60):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make_state():
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = True
    st._data["settings"]["takeover_desktop"] = True
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["settings"]["layout_mode"] = "grid"
    st._data["widgets"] = []
    st._data["layout"] = []
    st.save()
    return st


def main(app):
    # ---------- V1：组合文本 ----------
    text = version.label()
    check("V1 label 含版本标签", ("v" + version.VERSION) in text, text)
    check("V1b label 含「构建」", "构建" in text, text)

    # ---------- V2：格式与降级 ----------
    ok_fmt = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", version.build_time()))
    check("V2 build_time 为 YYYY-MM-DD HH:MM", ok_fmt, version.build_time())

    _orig = version.build_stamp
    version.build_stamp = lambda: None          # 模拟 mtime 读取失败
    try:
        degraded = version.build_time()
    finally:
        version.build_stamp = _orig
    check("V2b 取不到 mtime 时降级为「未知」", degraded == "未知", degraded)

    # ---------- V3：源码运行取本文件 mtime ----------
    expect = datetime.datetime.fromtimestamp(os.path.getmtime(VERSION_PY))
    got = version.build_stamp()
    ok_stamp = got is not None and abs((got - expect).total_seconds()) < 2
    check("V3 构建时刻 = src/version.py 的 mtime", ok_stamp,
          "%s vs %s" % (got, expect))

    # ---------- V4/V5：版本标识不在右键，改挂设置页「关于」（反馈 15） ----------
    # 版本号是 v6c 跑错包事故的取证设施，不能直接删；但桌面右键塞一条
    # 灰色"版本 vXa · 构建 …"确实碍眼，挪到设置页最底部的「关于」卡片。
    w = DesktopWindow(make_state())
    w.resize(W, H)
    w._update_grid_metrics()
    settle(app)
    menu = w._build_context_menu()
    keep = [menu]                       # 持有引用，防 C++ 菜单被回收
    joined = " | ".join(a.text() for a in menu.actions() if not a.isSeparator())
    check("V4 右键不再出现版本标识",
          "构建" not in joined and version.VERSION not in joined, joined[:120])
    check("V4b 右键没有 ctxVersion 项",
          not any(a.objectName() == "ctxVersion" for a in menu.actions()))
    st_w = w.storage
    w.close()

    from src.settings_dialog import SettingsDialog

    class _FakeWindow:
        def __init__(self, storage):
            self.storage = storage
            self.attached = True

        def refresh_grid(self):
            pass

    dlg = SettingsDialog(_FakeWindow(st_w), st_w, layer=None)
    dlg.show()
    app.processEvents()
    lbl = getattr(dlg, "lbl_about_version", None)
    check("V5 设置页「关于」含版本 + 构建时刻",
          lbl is not None and version.VERSION in lbl.text() and "构建" in lbl.text(),
          "%r" % (lbl.text() if lbl is not None else None))
    dlg.close()
    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    app = QApplication.instance() or QApplication([])
    sys.exit(main(app))
