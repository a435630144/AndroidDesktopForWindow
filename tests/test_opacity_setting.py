"""v10 A8（反馈 14）：悬浮模式不透明度——三种状态各就各位。

诉求：设置 ▸ 外观与图标 ▸「悬浮模式不透明度」拖动后要真有效果。

根因（已核）：`opacity` 设置确实被写入，也确实在 `_enter_floating_mode()` 里
`setWindowOpacity(...)`；但 `_show_current_mode()` 在**挂载成功**分支末尾无条件
`setWindowOpacity(1.0)`——而正常路径全是挂载成功，所以正常机器上怎么拖都没反应。

修法（指导文档_v10 §2.8 决策点 2「选定方案：禁用 + 说明」）：
  - 挂载态：桌面层是分层窗口，`setWindowOpacity` 对内容无效，且全局 alpha 会
    连带命中测试一起变（透明区穿透坑 #39 的教训）→ 滑条置灰 + hint 说明，
    窗口侧恒 1.0（O6 锁这条）；
  - 悬浮态：`_apply_opacity` 直落 `setWindowOpacity`（O2），托盘隐藏/再现经
    `show_desktop()` → `_show_current_mode()` 的 else 分支早返回进
    `_enter_floating_mode()` 重新读 storage，用户值不丢（O4/O5 锁这条）。

关于指导文档同节决策点 3（「把 `_show_current_mode` 的 1.0 改成读 opacity」）：
**已作废**——见 O5/O6 的注释与指导文档 §2.8 的作废记录。

运行：python tests/test_opacity_setting.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication      # noqa: E402

from src import desktop_window as dw            # noqa: E402
from src.desktop_window import DesktopWindow    # noqa: E402
from src.settings_dialog import SettingsDialog  # noqa: E402
from src.storage import DEFAULT_SETTINGS, Storage   # noqa: E402

STATE = Path(tempfile.gettempdir()) / "test_opacity_state.json"
failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def make_state(opacity=0.95):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["settings"]["opacity"] = opacity
    st._data["layout"] = []
    st.save()
    return st


class OpacitySpy:
    """记录 setWindowOpacity 的调用值。

    不真的调 Qt 那个方法——offscreen 平台下 `windowOpacity()` 不保证回显，
    记录调用值才是确定性的判据。
    """

    def __init__(self):
        self.calls = []

    def __call__(self, v):
        self.calls.append(float(v))


def main(app):
    # ---------- O1：默认值 ----------
    check("O1 DEFAULT_SETTINGS opacity 默认 0.95",
          DEFAULT_SETTINGS.get("opacity") == 0.95,
          "%s" % DEFAULT_SETTINGS.get("opacity"))

    # ---------- O2：设置窗拖动 -> 悬浮态直落窗口 ----------
    st = make_state(opacity=0.95)
    spy = OpacitySpy()
    fw = SimpleNamespace(update=lambda: None, rebuild=lambda: None,
                         attached=False, setWindowOpacity=spy)
    dlg = SettingsDialog(fw, st, None)
    dlg._apply_opacity(72)
    check("O2 悬浮态拖动后窗口收到 0.72",
          bool(spy.calls) and spy.calls[-1] == 0.72, "calls=%s" % spy.calls)
    check("O2 setting 同步落 0.72",
          abs(st.get_setting("opacity") - 0.72) < 1e-9,
          "%s" % st.get_setting("opacity"))

    # ---------- O3：挂载态 -> 窗口恒 1.0（滑条置灰外的双保险） ----------
    st3 = make_state(opacity=0.95)
    spy3 = OpacitySpy()
    fw3 = SimpleNamespace(update=lambda: None, rebuild=lambda: None,
                          attached=True, setWindowOpacity=spy3)
    dlg3 = SettingsDialog(fw3, st3, None)
    dlg3._apply_opacity(72)
    check("O3 挂载态下窗口被保持 1.0",
          bool(spy3.calls) and spy3.calls[-1] == 1.0, "calls=%s" % spy3.calls)
    check("O3 挂载态滑条置灰（A8 主修法）", not dlg3.sld_opacity.isEnabled())

    # ---------- O4：真窗 _enter_floating_mode 读 storage ----------
    st4 = make_state(opacity=0.72)
    w4 = DesktopWindow(st4)
    w4.resize(1920, 1040)
    spy4 = OpacitySpy()
    w4.setWindowOpacity = spy4
    w4._enter_floating_mode()
    check("O4 悬浮兜底用 storage 里的 0.72",
          bool(spy4.calls) and spy4.calls[-1] == 0.72, "calls=%s" % spy4.calls)

    # ---------- O5：悬挂态托盘隐藏/再现往返不掉值 ----------
    # 指导文档 §2.8 决策点 3 本想靠"改挂载分支的 1.0"实现这个目标；实际悬挂态
    # 走 show_desktop() → _show_current_mode() 的 else 分支**早返回**进
    # _enter_floating_mode()，目标本就满足——点 3 因此作废（见指导文档记录）。
    st5 = make_state(opacity=0.72)
    w5 = DesktopWindow(st5)
    w5.resize(1920, 1040)
    w5.attached = False
    w5._attach_known_failed = True        # 挂载失败过的悬浮态
    spy5 = OpacitySpy()
    w5.setWindowOpacity = spy5
    w5.show_desktop()                     # 托盘再现的真实入口
    check("O5 悬挂态再现后仍是 0.72（决策点 3 的目标已满足）",
          bool(spy5.calls) and spy5.calls[-1] == 0.72, "calls=%s" % spy5.calls)

    # ---------- O6：挂载态 _show_current_mode 恒 1.0 ----------
    # 决策点 2 的选定方案：挂载态必须不透明（分层窗全局 alpha 会连带命中测试，
    # 且与组件玻璃的视觉语言冲突）。挂载分支的 1.0 是**有意为之**，不是漏改。
    st6 = make_state(opacity=0.72)
    w6 = DesktopWindow(st6)
    w6.resize(1920, 1040)
    w6.attached = True
    spy6 = OpacitySpy()
    w6.setWindowOpacity = spy6
    w6._sync_native_icons = lambda: None   # offscreen 下不动原生图标
    old_attach = dw.attach_to_desktop
    old_enforce = dw.win32_layer.enforce_band_order
    dw.attach_to_desktop = lambda *a, **k: True
    dw.win32_layer.enforce_band_order = lambda: None
    try:
        w6.show_desktop()
    finally:
        dw.attach_to_desktop = old_attach
        dw.win32_layer.enforce_band_order = old_enforce
    check("O6 挂载态再现恒 1.0（决策点 2：挂载必须不透明）",
          bool(spy6.calls) and spy6.calls[-1] == 1.0, "calls=%s" % spy6.calls)

    print()
    if failures:
        print("==== test_opacity_setting: %d 项失败: %s"
              % (len(failures), failures))
        return 1
    print("==== ALL opacity_setting PASSED")
    return 0


if __name__ == "__main__":
    app = QApplication(sys.argv)
    sys.exit(main(app))
