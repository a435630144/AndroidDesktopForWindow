# -*- coding: utf-8 -*-
"""M4 位移引擎统一：位置类变化走动画、结构变化走增量（指导文档 §4.1/§7-M4）。

运行：python tests/test_layout_anim.py   （offscreen，无需显示桌面）

覆盖（先 Red 后 Green）：
  T1  无预览直达 drop 不再 rebuild：AppIcon 实例不变 + 落点正确
  T2  on_widget_grid_changed 不再 rebuild：displace 后实例不变、位置更新
  T3  add_app 增量：只新增一个图标实例，其余实例不变
  T4  _on_remove_entry 增量：只移除目标实例，其余不变
  T5  多选平移（_drop_internal）不再 rebuild：实例不变 + 平移正确
  T6  merge 结构同步：条目与 icons 对齐，类型变化的图标不重建（is_folder 动态）
  T7  widget 拖动实时预览：hover 按新占位矩形挤走图标，drop 回退
  T8  _sync_structure 幂等：无变化时不动任何实例
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
STATE = Path(tempfile.gettempdir()) / "test_m4_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=400):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make_state(spec, widgets=(), settings=None):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = False
    st._data["settings"]["auto_clone_desktop"] = False
    for k, v in (settings or {}).items():
        st._data["settings"][k] = v
    st._data["widgets"] = [dict(w) for w in widgets]
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


def main(app):
    # ---------- T1：无预览直达 drop 不再 rebuild ----------
    # v6 §3.2：默认 auto_arrange=False（自由移动）——无预览直达走交换
    # 语义（a→(2,0)，c 交换到源格 (0,0)，b 不动）；递进行为显式设
    # auto_arrange=True 验证（T1b）。
    st = make_state([("a", 0, 0), ("b", 1, 0), ("c", 2, 0)])
    w = new_window(app, st)
    ids_before = {eid: id(ic) for eid, ic in w.icons.items()}
    w._on_drag_started()
    w._reflow_commit_or_compute("a", (2, 0))   # 无预览直达：a 落到 c 的格
    b = cells_of(st)
    check("T1 无预览直达（free 交换）：a=(2,0)、c=(0,0)、b 不动",
          b["a"] == (2, 0) and b["b"] == (1, 0) and b["c"] == (0, 0), "%s" % b)
    same = all(id(w.icons.get(eid)) == i for eid, i in ids_before.items())
    check("T1 无预览直达：AppIcon 实例不变（不 rebuild）", same)

    # ---------- T1b：auto_arrange=True 递进（旧 M2 语义保留）----------
    st2 = make_state([("a", 0, 0), ("b", 1, 0), ("c", 2, 0)],
                     settings={"auto_arrange": True})
    w2 = new_window(app, st2)
    w2._on_drag_started()
    w2._reflow_commit_or_compute("a", (2, 0))
    b2 = cells_of(st2)
    check("T1b 自动排序递进：a=(2,0)、b=(0,0)、c=(1,0)",
          b2["a"] == (2, 0) and b2["b"] == (0, 0) and b2["c"] == (1, 0),
          "%s" % b2)
    settle(app, 300)
    check("T1 图标动画到位（a 在 (2,0) 的像素位）",
          abs(w.icons["a"].x() - w._entry_pos(st.find_entry("a"))[0]) <= 2
          and abs(w.icons["a"].y() - w._entry_pos(st.find_entry("a"))[1]) <= 2)

    # ---------- T2：on_widget_grid_changed 不再 rebuild ----------
    st2 = make_state([("a", 0, 0), ("b", 1, 0), ("c", 0, 1), ("d", 1, 1)],
                     widgets=[{"id": "clk", "type": "clock", "w": 300, "h": 160,
                               "hidden": False, "anchored": True,
                               "col": 0, "row": 0}])
    w2 = new_window(app, st2)
    ids2 = {eid: id(ic) for eid, ic in w2.icons.items()}
    w2.on_widget_grid_changed()
    b2 = cells_of(st2)
    wc = grid_flow.widget_cells(st2)
    check("T2 displace 后无图标落在组件占位格",
          not any(b2[i] in wc for i in "abcd"), "%s" % b2)
    check("T2 displace 后 AppIcon 实例不变（不 rebuild）",
          all(id(w2.icons.get(eid)) == i for eid, i in ids2.items()))
    settle(app, 300)
    ok = all(abs(w2.icons[i].x() - w2._entry_pos(st2.find_entry(i))[0]) <= 2
             and abs(w2.icons[i].y() - w2._entry_pos(st2.find_entry(i))[1]) <= 2
             for i in "abcd")
    check("T2 被挤图标动画到新格", ok)

    # ---------- T3：add_app 增量 ----------
    st3 = make_state([("a", 0, 0), ("b", 1, 0)])
    w3 = new_window(app, st3)
    ids3 = {eid: id(ic) for eid, ic in w3.icons.items()}
    w3.add_app({"id": "new1", "name": "new1", "target": "new1", "kind": "app"})
    check("T3 add_app 后新图标在位", "new1" in w3.icons)
    check("T3 add_app 只新增一个实例（原有实例不变）",
          all(id(w3.icons.get(eid)) == i for eid, i in ids3.items())
          and len(w3.icons) == 3)

    # ---------- T4：_on_remove_entry 增量 ----------
    w3._on_remove_entry("b")
    check("T4 移除后图标字典同步", "b" not in w3.icons and len(w3.icons) == 2)
    check("T4 移除只删目标实例（a/new1 不变）",
          all(id(w3.icons.get(eid)) == i for eid, i in ids3.items()
              if eid in w3.icons))

    # ---------- T5：多选平移不再 rebuild ----------
    st5 = make_state([("a", 0, 0), ("b", 1, 0), ("c", 2, 0), ("e", 5, 5)])
    w5 = new_window(app, st5)
    ids5 = {eid: id(ic) for eid, ic in w5.icons.items()}
    w5._selected = {"a", "b"}
    w5._drag_multi = True
    w5._on_drag_started()
    drop_pos = QPoint(200, 200)
    tc, tr = w5._cell_at(drop_pos)   # 1920x1040 @ cell 96x114 -> (2,1)
    w5._drop_internal("a,b", drop_pos)
    b5 = cells_of(st5)
    check("T5 多选平移落点（a→(%d,%d)、b→(%d,%d)）" % (tc, tr, tc + 1, tr),
          b5["a"] == (tc, tr) and b5["b"] == (tc + 1, tr), "%s" % b5)
    check("T5 多选平移后实例不变（不 rebuild）",
          all(id(w5.icons.get(eid)) == i for eid, i in ids5.items()))

    # ---------- T6：merge 结构同步 ----------
    st6 = make_state([("a", 0, 0), ("b", 1, 0), ("c", 2, 0)])
    w6 = new_window(app, st6)
    ids6 = {eid: id(ic) for eid, ic in w6.icons.items()}
    w6._on_merge("b", "a")     # b 并入 a -> a 变文件夹，b 条目移除
    check("T6 merge 后条目与 icons 对齐（b 移除、c 保留）",
          set(w6.icons) == {"a", "c"} and set(cells_of(st6)) == {"a", "c"})
    check("T6 merge 后 a 的图标实例不变（is_folder 动态读 entry）",
          id(w6.icons["a"]) == ids6["a"])
    check("T6 merge 后 a 渲染为文件夹（动态属性）",
          w6.icons["a"].is_folder is True)
    check("T6 merge 后 c 的图标实例不变", id(w6.icons["c"]) == ids6["c"])

    # ---------- T7：widget 拖动实时预览 ----------
    st7 = make_state([("x", 2, 0), ("y", 2, 1), ("z", 6, 6)],
                     widgets=[{"id": "clk", "type": "clock", "w": 300, "h": 160,
                               "hidden": False, "anchored": True,
                               "col": 0, "row": 0, "colspan": 2, "rowspan": 2}])
    w7 = new_window(app, st7)
    ids7 = {eid: id(ic) for eid, ic in w7.icons.items()}
    orig7 = cells_of(st7)
    # hover 到 (2,0)：组件新占位矩形 = (2,0)-(3,1)，x/y 应被实时挤走
    cw, ch = grid_flow.cell_size(st7)
    ox, oy = grid_flow.origin()
    g = w7.mapToGlobal(QPoint(ox + 2 * cw + cw // 4, oy + ch // 4))
    w7._on_widget_hover("clk", g.x(), g.y())
    b7 = cells_of(st7)
    newrect = {(2, 0), (3, 0), (2, 1), (3, 1)}
    check("T7 hover 预览：x/y 被挤出组件新占位矩形",
          b7["x"] not in newrect and b7["y"] not in newrect, "%s" % b7)
    check("T7 hover 预览：z 不动", b7["z"] == (6, 6))
    check("T7 hover 预览：实例不变", all(id(w7.icons.get(e)) == i
                                        for e, i in ids7.items()))
    # drop：回退到进入预览前的布局（组件自身由 FloatingWidget 吸附落定）
    w7._on_widget_drop("clk", g.x(), g.y())
    check("T7 drop 后布局回退到预览前", cells_of(st7) == orig7,
          "%s -> %s" % (orig7, cells_of(st7)))

    # ---------- T8：_sync_structure 幂等 ----------
    st8 = make_state([("a", 0, 0), ("b", 1, 0)])
    w8 = new_window(app, st8)
    ids8 = {eid: id(ic) for eid, ic in w8.icons.items()}
    w8._sync_structure()
    check("T8 无变化时 _sync_structure 不动任何实例",
          {eid: id(ic) for eid, ic in w8.icons.items()} == ids8
          and len(w8.icons) == 2)

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL layout_anim PASSED")
    return 0


def run_main():
    app = QApplication([])
    wd = QTimer()
    wd.setSingleShot(True)
    wd.timeout.connect(lambda: (print("!! 看门狗超时"), os._exit(3)))
    wd.start(60000)
    try:
        code = main(app)
    except Exception:
        import traceback
        traceback.print_exc()
        failures.append("main() 异常")
        code = 1
    finally:
        try:
            STATE.unlink()
        except Exception:
            pass
    app.processEvents()
    QTimer.singleShot(80, app.quit)
    app.exec()
    return code


if __name__ == "__main__":
    sys.exit(run_main())
