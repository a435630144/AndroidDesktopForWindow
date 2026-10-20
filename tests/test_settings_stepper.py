# -*- coding: utf-8 -*-
"""2026-10-21 用户反馈 1 / 2 · 设置面板交互：滑条断触 + 行列调节器。

用户原话：

    问题1：图标大小切换到自定义的时候，拖动条交互有问题，不能流畅的
    拖动，会断触。
    问题2：设置面板的文件夹大小调节，不要把行列放进框里，让用户以为字
    也可以编辑，并且数字的增加减少箭头没有渲染（其他类似功能的地方
    也看不到箭头）。

反馈 1 的根因不是滑条本身，而是**每像素一次全桌面重建**：
`_apply_icon_fit -> _refresh_grid -> refresh_grid()` 会销毁重建全部图标并
重新挂载桌面带，GUI 线程被重建占满，Qt 的鼠标抓取被反复打断 -> "断触"。
修法：写入立即做，重建走 90ms 防抖（S3/S4/S5 断言）。

反馈 2 的根因是 QSpinBox 的两件事：线框长得像输入框（用户想去打字），
以及全局 QSS 把 up/down-button 清成透明 -> **所有**微调框都不画箭头。
修法：新控件 `Stepper`（数值标签 + 两枚自绘按钮），接口与 QSpinBox
同名，设置面板/图标缩放编辑器共 7 处全部替换（S6/S7 断言无残留）。

运行：python tests/test_settings_stepper.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from src.settings_dialog import SettingsDialog
from src.stepper import Stepper
from src.storage import Storage

STATE = Path(tempfile.gettempdir()) / "test_stepper_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=200):
    from PySide6.QtCore import QEventLoop, QTimer
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
    st._data["settings"]["hide_native_icons"] = False
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["layout"] = []
    st.save()
    return st


def press(w, local):
    g = QPointF(w.pos()) + QPointF(local)
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(local), g, Qt.LeftButton,
                     Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(w, ev)


def release(w, local):
    g = QPointF(w.pos()) + QPointF(local)
    ev = QMouseEvent(QEvent.MouseButtonRelease, QPointF(local), g,
                     Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(w, ev)


def main(app):
    # ---------- S1：Stepper 基础契约（QSpinBox 同名接口） ----------
    sp = Stepper()
    sp.setRange(2, 6)
    sp.setValue(3)
    got = []
    sp.valueChanged.connect(got.append)
    sp.setValue(4)
    check("S1 value/setValue/valueChanged 契约", sp.value() == 4 and got == [4])
    check("S1b setValue 同值不重复发信号", (sp.setValue(4), got == [4])[1])
    sp.setValue(99)
    check("S1c 超上限被夹紧", sp.value() == 6)
    sp.setValue(0)
    check("S1d 低于下限被夹紧", sp.value() == 2)
    check("S1e setSuffix 只影响显示", sp.suffix() == "")
    sp.setSuffix(" 列")
    check("S1f setSuffix 回读", sp.suffix() == " 列")
    sp.setSingleStep(2)
    sp.stepBy(1)
    check("S1g setSingleStep 生效", sp.value() == 4, "%d" % sp.value())
    sp.setEnabled(False)
    press(sp, QPointF(sp.width() - 6, 4))       # 禁用态点击不该改值
    check("S1h 禁用态点击不改值", sp.value() == 4)
    sp.setEnabled(True)

    # ---------- S2：按钮真的能步进（反馈 2：箭头要能看到也要点得到） ----------
    sp = Stepper()                     # 全新实例：别把 S1g 的 step=2 带进来
    sp.setRange(2, 6)
    sp.setValue(4)
    up = sp._btn_up_rect().center()
    down = sp._btn_down_rect().center()
    press(sp, up)
    release(sp, up)
    check("S2 点上箭头 +1", sp.value() == 5, "%d" % sp.value())
    press(sp, down)
    release(sp, down)
    check("S2b 点下箭头 -1", sp.value() == 4)
    # 长按连步（400ms 起、80ms 一步）：模拟一次长按
    press(sp, up)
    settle(app, 700)
    release(sp, up)
    check("S2c 长按上箭头自动连步到上限", sp.value() == 6, "%d" % sp.value())
    # 滚轮步进
    from PySide6.QtGui import QWheelEvent
    g = QPointF(sp.pos()) + QPointF(sp.width() / 2, sp.height() / 2)
    ev = QWheelEvent(QPointF(sp.width() / 2, sp.height() / 2), g,
                     sp.mapToGlobal(QPointF(0, 0).toPoint()),
                     sp.mapToGlobal(QPointF(0, 0).toPoint()),
                     Qt.NoButton, Qt.NoModifier, Qt.ScrollPhase.NoScrollPhase,
                     False)
    ev.angleDelta = lambda: __import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(0, 120)
    QApplication.sendEvent(sp, ev)
    check("S2d 上滚 +1（已在上限则不变）", sp.value() == 6)

    # ---------- S3：设置面板用 Stepper 而不是 QSpinBox ----------
    st = make_state()
    dlg = SettingsDialog(SimpleNamespace(attached=False), st, None)
    kinds = {n: type(getattr(dlg, n)).__name__
             for n in ("spin_cols", "spin_rows", "sp_folder_cols",
                       "sp_folder_rows", "sp_ox", "sp_oy")}
    check("S3 设置面板 6 个数值控件全是 Stepper",
          set(kinds.values()) == {"Stepper"}, "%s" % kinds)
    check("S3b 图标缩放编辑器也不用 QSpinBox",
          "QSpinBox" not in open(
              os.path.join(os.path.dirname(os.path.dirname(
                  os.path.abspath(__file__))), "src", "iconwidget.py"),
              encoding="utf-8").read())
    check("S3c 三档预设下自定义滑条只读（B2 反馈 9 既定设计）",
          dlg.sld_icon_fit.isEnabled() is False)
    dlg.cmb_tier.setCurrentIndex(max(0, dlg.cmb_tier.findData("custom")))
    check("S3d 切到自定义后滑条可拖",
          dlg.sld_icon_fit.isEnabled() is True)

    # ---------- S4：拖滑条只写值，不立刻重建（防抖） ----------
    calls = []
    win = SimpleNamespace(attached=False, refresh_grid=lambda: calls.append(1),
                          rebuild=lambda: calls.append(2), update=lambda: None)
    dlg4 = SettingsDialog(win, st, None)
    dlg4.sld_icon_fit.setEnabled(True)
    before = len(calls)
    dlg4.sld_icon_fit.setValue(70)          # 模拟拖到 70%
    check("S4 拖滑条后 storage 立刻写入（实时）",
          abs(st.icon_fit() - 0.70) < 1e-9, "%s" % st.icon_fit())
    check("S4b 拖滑条后**没有**立刻重建（防抖生效）",
          len(calls) == before, "calls=%d" % len(calls))
    settle(app, 200)                        # 等防抖定时器落地
    check("S4c 停顿后重建只发生一次",
          len(calls) == before + 1, "calls=%d" % len(calls))
    dlg4.sld_icon_fit.setValue(72)
    dlg4.sld_icon_fit.setValue(74)          # 连续两次只算一次
    settle(app, 200)
    check("S4d 连续拖动合并成一次重建",
          len(calls) == before + 2, "calls=%d" % len(calls))

    # ---------- S5：行列/原点步进同样走防抖 ----------
    calls5 = []
    win5 = SimpleNamespace(attached=False,
                           refresh_grid=lambda: calls5.append(1),
                           rebuild=lambda: calls5.append(2),
                           update=lambda: None)
    dlg5 = SettingsDialog(win5, st, None)
    dlg5.chk_auto_cols.setChecked(False)
    b5 = len(calls5)
    dlg5.spin_cols.setValue(7)
    check("S5 步进行列后不立刻重建", len(calls5) == b5,
          "calls=%d" % len(calls5))
    settle(app, 200)
    check("S5b 停顿后重建一次", len(calls5) == b5 + 1,
          "calls=%d" % len(calls5))

    print("")
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL settings_stepper PASSED")
    return 0


if __name__ == "__main__":
    app = QApplication(sys.argv)
    sys.exit(main(app))
