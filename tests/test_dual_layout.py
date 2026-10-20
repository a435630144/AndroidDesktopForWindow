# -*- coding: utf-8 -*-
"""v7 B2：**双布局并存** + **图标尺寸单源**（实机反馈 9 / 11 / 13）。

## 病根（docs/反馈研判_v7_1.md §2 #11 #13）

旧实现只有**一套位置记录**：`col/row`。切无界时把 `fx/fy` 生成出来，
切回网格时 `to_grid_coords()` 用 `fx/fy` **反算吸附并删除** ——

1. 无界模式摆好的位置当场销毁（下次进去重新从格点生成）；
2. 吸附回来的 `col/row` 已不是用户整理的原样 → 一堆 cell 叠在一起。

尺寸同理：`_icon_layout()` 在无界模式返回 `None`，图标改走 `icon_px`
（默认 96）——切模式瞬间图标从 cell×占比 跳到 96px，所有元素挤成一坨。

## 新契约

- **双坐标只增不删**：`col/row`（网格）与 `fx/fy`（无界，页内像素）
  各自独立，切换**只写不读对方的账**；`fpage` 记录无界页号，
  不再用 `row` 当无界页载体（否则网格 row 被污染）。
- **尺寸单源**：网格与无界用**同一套** `icon_layout(cw, ch, fit)`；
  `icon_px` 退役（键保留但不再驱动任何模式）。
- 档位扩成 小/中/大/**自定义**，自定义才启用比例滑条。

运行：python tests/test_dual_layout.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QPoint, QTimer
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.desktop_window import DesktopWindow
from src.storage import Storage

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_dual_layout_state.json"
failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=300):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make_state(spec, settings=None):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st.set_setting("hide_native_icons", False)
    st.set_setting("auto_clone_desktop", False)
    st.set_setting("takeover_desktop", True)     # 切回网格需要接管
    for k, v in (settings or {}).items():
        st.set_setting(k, v)
    st._data["layout"] = [
        {"id": i, "type": "app",
         "app": {"name": i, "target": i, "kind": "app"},
         "col": c, "row": r}
        for i, c, r in spec]
    st.save()
    return st


def new_window(app, st):
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    settle(app, 100)
    return w


def cells_of(st):
    return {e["id"]: (int(e["col"]), int(e["row"])) for e in st.layout}


def free_of(st):
    return {e["id"]: (e.get("fx"), e.get("fy")) for e in st.layout}


# ---------------------------------------------------------------- L1~L7
def test_dual_coords(app):
    st = make_state([("a", 0, 0), ("b", 1, 0), ("c", 2, 1)])
    w = new_window(app, st)
    cells0 = cells_of(st)
    pos_grid = {eid: w.icons[eid].pos() for eid in ("a", "b", "c")}
    size_grid = (w.icons["a"].width(), w.icons["a"].height())
    layout_grid = w._icon_layout()

    # ---------- L1 / L2：切无界 ----------
    w.set_layout_mode("free")
    settle(app, 120)
    size_free = (w.icons["a"].width(), w.icons["a"].height())
    check("L1 切无界图标尺寸不变（尺寸单源）", size_free == size_grid,
          "grid=%s free=%s" % (size_grid, size_free))
    check("L2 切无界视觉原位（无跳变）",
          all(w.icons[eid].pos() == pos_grid[eid] for eid in pos_grid),
          "%s vs %s" % ({e: w.icons[e].pos() for e in pos_grid}, pos_grid))
    check("L2b 无界 _icon_layout 不再返回 None", w._icon_layout() is not None)
    check("L2c 无界 layout 与网格同值",
          w._icon_layout() == layout_grid,
          "%s vs %s" % (w._icon_layout(), layout_grid))
    check("L2d 切无界不改 col/row", cells_of(st) == cells0,
          "%s vs %s" % (cells_of(st), cells0))

    # ---------- L3：无界拖动只写 fx/fy ----------
    icon = w.icons["a"]
    w._drag_entry_id = "a"
    icon._press_pos = QPoint(10, 10)
    icon.grabMouse = lambda: None
    icon.setFocus = lambda: None
    icon._exec_drag()
    ghost = icon._drag_ghost_w
    check("L3 拖影已创建", ghost is not None)
    if ghost is not None:
        ghost.move(500, 300)
        w._drop_internal("a", QPoint(500, 300))
        ea = st.find_entry("a")
        check("L3a 落点是拖影像素位", (ea.get("fx"), ea.get("fy")) == (500, 300),
              "%s" % ((ea.get("fx"), ea.get("fy")),))
        check("L3b 无界拖动不改 col/row", cells_of(st)["a"] == cells0["a"],
              "%s vs %s" % (cells_of(st)["a"], cells0["a"]))
        check("L3c 无界页号写 fpage（不再用 row 当载体）",
              int(ea.get("fpage", -1)) == w._page,
              "fpage=%r page=%r row=%r" % (ea.get("fpage"), w._page, ea.get("row")))
        ghost.close()
    icon.set_drag_ghost(False)
    settle(app, 80)
    free_after_drag = free_of(st)

    # ---------- L4 / L5：切回网格 ----------
    w.set_layout_mode("grid")
    settle(app, 120)
    check("L4 切回网格 col/row 回到整理前原位（不被吸附覆盖）",
          cells_of(st) == cells0, "%s vs %s" % (cells_of(st), cells0))
    check("L5 切回网格 fx/fy 仍保留（无界摆位不丢）",
          free_of(st)["a"] == free_after_drag["a"],
          "%s vs %s" % (free_of(st)["a"], free_after_drag["a"]))
    check("L5b 切回网格图标尺寸仍是同一套", 
          (w.icons["a"].width(), w.icons["a"].height()) == size_grid,
          "%s vs %s" % ((w.icons["a"].width(), w.icons["a"].height()), size_grid))
    check("L5c 切回网格图标位置回到网格位",
          w.icons["a"].pos() == pos_grid["a"],
          "%s vs %s" % (w.icons["a"].pos(), pos_grid["a"]))

    # ---------- L6：再切无界，摆位还在 ----------
    w.set_layout_mode("free")
    settle(app, 120)
    check("L6 再切无界：用户摆的位置还在",
          free_of(st)["a"] == free_after_drag["a"],
          "%s vs %s" % (free_of(st)["a"], free_after_drag["a"]))
    check("L6b 再切无界：视觉落回 fx/fy",
          (w.icons["a"].x(), w.icons["a"].y()) == free_after_drag["a"],
          "%s vs %s" % ((w.icons["a"].x(), w.icons["a"].y()),
                        free_after_drag["a"]))

    # ---------- L7：三次往返不漂移 ----------
    for _ in range(3):
        w.set_layout_mode("grid")
        settle(app, 80)
        w.set_layout_mode("free")
        settle(app, 80)
    check("L7 三次往返 col/row 不漂移", cells_of(st) == cells0,
          "%s vs %s" % (cells_of(st), cells0))
    check("L7b 三次往返 fx/fy 不漂移", free_of(st) == free_after_drag,
          "%s vs %s" % (free_of(st), free_after_drag))

    w.close()
    w.deleteLater()
    settle(app, 80)


# ---------------------------------------------------------------- L8~L10
def test_size_single_source(app):
    """icon_px 退役：无论网格还是无界，图标尺寸都由 cell × fit 推导。"""
    st = make_state([("a", 0, 0)], settings={"icon_px": 200})
    w = new_window(app, st)
    size_grid = (w.icons["a"].width(), w.icons["a"].height())
    check("L8 icon_px=200 不再影响网格模式",
          size_grid[0] < 200, "size=%s" % (size_grid,))
    w.set_layout_mode("free")
    settle(app, 120)
    check("L9 icon_px=200 不再影响无界模式",
          (w.icons["a"].width(), w.icons["a"].height()) == size_grid,
          "%s vs %s" % ((w.icons["a"].width(), w.icons["a"].height()), size_grid))

    # 自定义占比：改 fit 图标像素跟着变（两种模式都生效）
    from src import grid_sizing
    st.apply_icon_fit(0.35, tier="custom")
    w.rebuild()
    settle(app, 120)
    small = (w.icons["a"].width(), w.icons["a"].height())
    check("L10 自定义 35% 时图标变小", small[0] < size_grid[0],
          "35%%=%s vs 原=%s" % (small, size_grid))
    check("L10b 自定义占比在无界模式同样生效",
          (w.icons["a"].width(), w.icons["a"].height()) == small,
          "%s vs %s" % ((w.icons["a"].width(), w.icons["a"].height()), small))
    w.close()
    w.deleteLater()
    settle(app, 80)


# ---------------------------------------------------------------- L11~L15
def test_tier_custom(app):
    from src import grid_sizing
    st = make_state([("a", 0, 0)])
    check("L11 parse_tier 保留 custom",
          grid_sizing.parse_tier("custom") == "custom",
          "got %s" % grid_sizing.parse_tier("custom"))

    st.apply_icon_fit(0.66, tier="custom")
    check("L11b storage 记录 custom 档", st.icon_tier() == "custom",
          "got %s" % st.icon_tier())
    check("L11c custom 档的占比来自 icon_fit 本身",
          abs(st.icon_fit() - 0.66) < 1e-6, "got %.3f" % st.icon_fit())

    # 三档仍写回自己的名字
    st.apply_icon_fit(0.42)
    check("L12 选小档仍是 small", st.icon_tier() == "small",
          "got %s" % st.icon_tier())

    # 设置页：档位下拉含「自定义」，滑条只在自定义时可用
    from src.settings_dialog import SettingsDialog

    class FakeWindow:
        storage = st
        attached = True

        def rebuild(self, stagger=False):
            pass

        def refresh_grid(self):
            pass

        def update(self):
            pass

    dlg = SettingsDialog(FakeWindow(), st, layer=None)
    dlg.show()
    QApplication.processEvents()
    tier_items = [dlg.cmb_tier.itemData(i) for i in range(dlg.cmb_tier.count())]
    check("L13 档位下拉含「自定义」", "custom" in tier_items, "%s" % tier_items)
    check("L13b 非自定义档时比例滑条禁用",
          not dlg.sld_icon_fit.isEnabled(),
          "tier=%s en=%s" % (dlg.cmb_tier.currentData(), dlg.sld_icon_fit.isEnabled()))
    idx = dlg.cmb_tier.findData("custom")
    dlg.cmb_tier.setCurrentIndex(idx)
    QApplication.processEvents()
    check("L13c 切到自定义后滑条可用", dlg.sld_icon_fit.isEnabled())
    check("L14 无界像素 spin 已从设置页移除",
          not hasattr(dlg, "spin_icon_px")
          or dlg.spin_icon_px is None
          or not dlg.spin_icon_px.isVisible(),
          "attr=%r" % getattr(dlg, "spin_icon_px", "missing"))
    dlg.close()
    dlg.deleteLater()
    QApplication.processEvents()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    for fn in (test_dual_coords, test_size_single_source, test_tier_custom):
        try:
            fn(app)
        except Exception:
            import traceback
            traceback.print_exc()
            check(fn.__name__ + " 未抛异常", False)
    print("\n==== %d 失败 ====" % len(failures))
    if failures:
        for f in failures:
            print("  -", f)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
