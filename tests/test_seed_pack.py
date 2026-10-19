# -*- coding: utf-8 -*-
"""v6 §3.1：播种铺满（pack_layout 阅读序紧凑重排）单测。

规格（指导文档_网格与无界双模式_v6.md §3.1）：
  - auto_clone 播种 /「重新扫描桌面文件」时，图标按阅读序（左→右、
    上→下）从第 0 页起点依次填满，不留空洞；
  - 仅播种时铺满；**不**在每次加载时 compact（尊重用户自由移动后的留空）。

  S1 稀疏布局（中间有洞）pack 后紧凑无洞
  S2 阅读序保持（按 row,col 排序后重排，顺序不乱）
  S3 pack 避开组件占位格
  S4 条目数量守恒（不丢图标）
  S5 rescan_desktop 走 pack（集成）
  S6 ensure_desktop_clone 增量播种不 pack（尊重留空）

运行：python tests/test_seed_pack.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.storage import Storage

STATE = Path(tempfile.gettempdir()) / "test_seed_pack.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def make_state(spec, widgets=(), settings=None):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = True
    st._data["settings"]["auto_clone_desktop"] = False
    for k, v in (settings or {}).items():
        st._data["settings"][k] = v
    st._data["widgets"] = [dict(w) for w in widgets]
    st._data["layout"] = [
        {"id": i, "type": t,
         "app": None if t == "folder" else {"name": i, "target": i,
                                            "kind": "app"},
         "apps": apps, "col": c, "row": r}
        for i, c, r, t, apps in spec]
    st.save()
    return st


def cells(st):
    return {e["id"]: (int(e["col"]), int(e["row"])) for e in st.layout}


def main(app):
    # ---------- S1：稀疏 pack 紧凑无洞 ----------
    st = make_state([("a", 0, 0, "app", []), ("b", 5, 0, "app", []),
                     ("c", 2, 3, "app", []), ("d", 9, 7, "app", [])])
    grid_flow.set_grid(st, (1920, 1040))     # 建立快照（columns 已知）
    st.pack_layout()
    got = cells(st)
    check("S1 pack 紧凑无洞（阅读序 0,0 / 1,0 / 2,0 / 3,0）",
          got == {"a": (0, 0), "b": (1, 0), "c": (2, 0), "d": (3, 0)},
          "got %s" % (got,))

    # ---------- S2：阅读序保持（原顺序 row,col 排序） ----------
    st = make_state([("x", 4, 4, "app", []), ("y", 0, 1, "app", []),
                     ("z", 0, 0, "app", [])])
    grid_flow.set_grid(st, (1920, 1040))
    st.pack_layout()
    got = cells(st)
    check("S2 阅读序：z(0,0) y(0,1) x(4,4) -> (0,0)(1,0)(2,0)",
          got == {"z": (0, 0), "y": (1, 0), "x": (2, 0)},
          "got %s" % (got,))

    # ---------- S3：避开组件占位 ----------
    st = make_state([("a", 0, 0, "app", [])],
                    widgets=[{"id": "clk", "type": "clock", "w": 192,
                              "h": 228, "hidden": False, "anchored": True,
                              "col": 0, "row": 0, "colspan": 2, "rowspan": 2}])
    grid_flow.set_grid(st, (1920, 1040))
    st.pack_layout()
    got = cells(st)
    check("S3 图标避开组件占位（落到 (2,0)）", got["a"] == (2, 0),
          "got %s" % (got,))

    # ---------- S4：数量守恒 ----------
    st = make_state([("a", 0, 0, "app", []), ("b", 7, 7, "app", []),
                     ("c", 3, 1, "app", [])])
    grid_flow.set_grid(st, (1920, 1040))
    st.pack_layout()
    check("S4 数量守恒（3 条不丢）", len(st.layout) == 3,
          "got %d" % len(st.layout))

    # ---------- S5：rescan(repack=True) 才铺满 ----------
    # 2026-10-19 反馈 5：默认 rescan 不得重排用户布局（右键"新建"内部也走
    # rescan），只有显式整理（repack=True）才 pack。
    # 铁律：测试绝不碰用户真实桌面——patch appsource 扫描为空。
    from src import appsource
    orig_scan = appsource.scan_desktop_files
    appsource.scan_desktop_files = lambda: []
    try:
        st = make_state([("a", 8, 8, "app", []), ("b", 0, 0, "app", [])])
        grid_flow.set_grid(st, (1920, 1040))
        st.rescan_desktop(repack=True)
        got = cells(st)
        check("S5 rescan 后 pack 紧凑", got["a"] == (1, 0) and got["b"] == (0, 0),
              "got %s" % (got,))
    finally:
        appsource.scan_desktop_files = orig_scan

    # ---------- S6：ensure 增量播种不 pack ----------
    st = make_state([("a", 5, 5, "app", [])])
    grid_flow.set_grid(st, (1920, 1040))
    st.ensure_desktop_clone()
    got = cells(st)
    check("S6 增量播种保留原位（不 pack）", got["a"] == (5, 5),
          "got %s" % (got,))

    print("-" * 60)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL seed_pack PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(QApplication([])))
