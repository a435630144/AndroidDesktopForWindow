# -*- coding: utf-8 -*-
"""v7 反馈 3：网格模式的「默认大小」必须就是「中」。

用户原话：
    网格模式的默认大小不是中了。
    （追问）我不确定是本地有缓存还是什么问题，运行程序之后图标小一号，
    手动切换到了中。

排查结论（只读探针 + 真实 state.json）：
  * 这台机器上 `icon_tier=medium`、`icon_fit=None`，**启动与手动选「中」
    算出来是同一个尺寸**（62×67 / box 48）——两个入口本身没分叉；
  * 真正的病根是**同一个界面值有两个旋钮**：`icon_fit`（显式浮点）与
    `icon_tier`（档位）。预设档时旧实现"显式占比优先"，一旦 `icon_fit`
    里残留某个旧浮点（历史版本写过 / 手拖滑条后档位又被改回），启动就
    按旧值渲染 —— 看着比「中」小一号，而用户点一次「中」把 None 写回
    才恢复。这正是"本地有缓存"的直觉；
  * 第二个来源：`grid_sizing.icon_layout()` 拿不到 native 时退常量
    0.57，而设置页/菜单走 `fit_for(native, cw)` —— 换屏（native 60 /
    cell 100）时两边差 3px，"默认档位看着小一号"。

修法：
  * `storage.icon_fit()`：**档位是唯一真相源**。预设档忽略残留 `icon_fit`
    浮点，只有「自定义」档才读它；
  * `storage.resolved_icon_fit(cw)`：实际生效占比的唯一出口
    （medium = native_px/cell_w），桌面渲染 / 居中留白 / 设置页三处共用；
  * `desktop_window._icon_layout`、`grid_flow.icon_center_offset`、
    `settings_dialog._effective_fit` 全部改读它。

契约：
  D1 默认（新装：无 icon_fit，tier=medium）占比 = native_px / cell_w
  D2 **脏 state**（icon_fit=0.42 但 tier=medium）仍按「中」渲染，不再小一号
  D3 中档图标边长 == 原生桌面图标边长（"跟原桌面一致"的回归锁）
  D4 自定义档才吃 icon_fit 本身（预设档不许被浮点劫持）
  D5 居中留白与图标尺寸同源（图标视觉中心 = cell 中心）
  D6 设置页显示的占比与桌面实际渲染占比是同一个数

运行：python tests/test_icon_default.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from src import grid_flow, grid_sizing, win32_layer
from src.storage import Storage

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_icon_default_state.json"
failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def make_state(**settings):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"].update({"hide_native_icons": False,
                                 "auto_clone_desktop": False,
                                 "takeover_desktop": True,
                                 "layout_mode": "grid"})
    for k, v in settings.items():
        st._data["settings"][k] = v
    st._data["layout"] = []
    st._data["widgets"] = []
    st.save()
    return st


def main(app):
    native = int(win32_layer.native_icon_size())
    check("D0 能读到原生图标边长", native > 0, "native=%d" % native)

    # ---------- D1：新装默认 ----------
    st = make_state(icon_tier="medium", icon_fit=None)
    m = grid_flow.set_grid(st, (W, H))
    check("D1 默认档位 = medium", st.icon_tier() == "medium",
          "got %s" % st.icon_tier())
    fit = st.resolved_icon_fit(m.cw)
    want = native / float(m.cw)
    check("D1 默认占比 = native_px / cell_w",
          abs(fit - want) < 1e-6, "fit=%.4f want=%.4f (cw=%d)" % (fit, want, m.cw))
    lay = grid_sizing.icon_layout(m.cw, m.ch, fit)
    check("D2 中档图标边长 == 原生图标边长", lay.icon_box == native,
          "box=%d native=%d" % (lay.icon_box, native))

    # ---------- D2：脏 state（老浮点残留在 icon_fit 里） ----------
    st2 = make_state(icon_tier="medium", icon_fit=0.42)
    m2 = grid_flow.set_grid(st2, (W, H))
    check("D2 残留浮点被忽略：icon_fit() 交给档位",
          st2.icon_fit() is None, "got %s" % (st2.icon_fit(),))
    fit2 = st2.resolved_icon_fit(m2.cw)
    lay2 = grid_sizing.icon_layout(m2.cw, m2.ch, fit2)
    lay_small = grid_sizing.icon_layout(m2.cw, m2.ch, grid_sizing.TIER_FIT["small"])
    check("D2 脏 state 仍按「中」渲染（不是小档）",
          lay2.icon_box == native and lay2.icon_box > lay_small.icon_box,
          "dirty=%d native=%d small=%d" % (lay2.icon_box, native,
                                           lay_small.icon_box))

    # ---------- D4：自定义档才吃 icon_fit ----------
    st3 = make_state(icon_tier="custom", icon_fit=0.66)
    grid_flow.set_grid(st3, (W, H))
    check("D4 自定义档占比来自 icon_fit 本身",
          abs(st3.resolved_icon_fit() - 0.66) < 1e-6,
          "got %.3f" % st3.resolved_icon_fit())
    st4 = make_state(icon_tier="small", icon_fit=0.66)
    grid_flow.set_grid(st4, (W, H))
    check("D4 预设小档不被 0.66 劫持",
          abs(st4.resolved_icon_fit() - 0.42) < 1e-6,
          "got %.3f" % st4.resolved_icon_fit())

    # ---------- D5：居中留白与尺寸同源 ----------
    st5 = make_state(icon_tier="medium", icon_fit=None)
    m5 = grid_flow.set_grid(st5, (W, H))
    fit5 = st5.resolved_icon_fit(m5.cw)
    lay5 = grid_sizing.icon_layout(m5.cw, m5.ch, fit5)
    dx, dy = grid_flow.icon_center_offset(st5)
    want_dx = max(0, (m5.cw - lay5.widget_w) // 2)
    want_dy = max(0, (m5.ch - lay5.widget_h) // 2)
    check("D5 居中留白 = 按同一 layout 算的留白",
          (dx, dy) == (want_dx, want_dy),
          "got %s want %s lay=%s" % ((dx, dy), (want_dx, want_dy), lay5))

    # ---------- D6：设置页与桌面同源 ----------
    from src.settings_dialog import SettingsDialog
    st6 = make_state(icon_tier="medium", icon_fit=None)
    grid_flow.set_grid(st6, (W, H))
    try:
        dlg = SettingsDialog(None, st6, None)
        got = dlg._effective_fit()
        check("D6 设置页占比 == 桌面渲染占比",
              abs(got - st6.resolved_icon_fit(grid_flow.current_metrics().cw)) < 1e-9,
              "dlg=%.4f storage=%.4f" % (got, st6.resolved_icon_fit()))
        dlg.close()
    except Exception as exc:
        check("D6 设置页占比 == 桌面渲染占比", False, "构造失败：%r" % (exc,))

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL icon_default PASSED")
    return 0


def run_main():
    app = QApplication([])
    try:
        return main(app)
    except Exception:
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(run_main())
