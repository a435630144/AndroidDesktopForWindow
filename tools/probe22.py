# -*- coding: utf-8 -*-
"""probe22：实机只读诊断——屏幕几何 / DPI / 网格参数（排查"网格没铺满"）。

安全铁律（tools/probe*.py 通用）：
- 不创建任何窗口、不碰用户桌面、不改真实 state.json（复制到临时目录）；
- try/finally + 看门狗，保证进程必退；
- 只打印信息，不做任何"清理"。

用法：python tools/probe22.py（实机 windows 平台跑，不要 offscreen）
"""
import os
import shutil
import sys
import tempfile
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

REAL_STATE = os.path.join(os.environ.get("APPDATA", ""), "DesktopOrganizerDemo", "state.json")


def _watchdog(sec=60):
    def _boom():
        print("[watchdog] %ds 超时，强制退出" % sec)
        os._exit(3)
    t = threading.Timer(sec, _boom)
    t.daemon = True
    t.start()
    return t


def main():
    _watchdog(60)
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QGuiApplication

    app = QApplication(sys.argv)
    scr = QGuiApplication.primaryScreen()
    ag = scr.availableGeometry()
    print("== 屏幕 ==")
    print("geometry          :", scr.geometry().width(), "x", scr.geometry().height())
    print("availableGeometry :", ag.width(), "x", ag.height(),
          "(left=%d top=%d)" % (ag.left(), ag.top()))
    print("devicePixelRatio  :", scr.devicePixelRatio())
    print("logicalDotsPerInch:", scr.logicalDotsPerInch())

    from storage import Storage
    from grid_flow import cell_size
    from grid_metrics import compute

    tmp = tempfile.mkdtemp(prefix="probe22_")
    try:
        if not os.path.exists(REAL_STATE):
            print("!! 真实 state.json 不存在:", REAL_STATE)
            return
        tmp_state = os.path.join(tmp, "state.json")
        shutil.copy(REAL_STATE, tmp_state)
        st = Storage(tmp_state)
        print("== storage（副本，只读） ==")
        print("settings.columns  :", repr(st.get_setting("columns")))
        print("settings.icon_size:", repr(st.get_setting("icon_size")),
              "icon_scale:", repr(st.get_setting("icon_scale")))
        print("icon_metric       :", st.icon_metric())
        print("ui_scale          :", st.ui_scale())
        print("cell_size (cw,ch) :", cell_size(st))

        W, H = ag.width(), ag.height()
        m_now = compute(st, (W, H))
        print("== GridMetrics（当前配置） ==")
        print(m_now)
        m_auto = compute(st, (W, H), columns_override="auto")
        print("== GridMetrics（强制 auto 列数） ==")
        print(m_auto)
        print("== 对比 ==")
        print("当前 6 列网格占屏: %.0f%% 宽 / %.0f%% 高"
              % (100.0 * m_now.cols * m_now.cw / W, 100.0 * m_now.rows * m_now.ch / H))
        print("auto 列网格占屏  : %.0f%% 宽 / %.0f%% 高"
              % (100.0 * m_auto.cols * m_auto.cw / W, 100.0 * m_auto.rows * m_auto.ch / H))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        print("[probe22] done")
        sys.stdout.flush()
        os._exit(0)
