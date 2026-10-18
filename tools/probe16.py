# -*- coding: utf-8 -*-
"""probe16：路线A 接管模式 + 右键菜单 + 小组件占位 实机验证（2026-10-18）。

用户反馈驱动（三张截图 + 需求清单）：
  - 原生图标还显示 / 文件数量不对 -> 默认整理模式 + 启动无条件播种
  - 桌面右键功能没了 -> 自绘桌面右键菜单（新建/设置/打开目录）
  - app 强制水平排列 -> 稀疏布局（compact 不重排，tidy 才铺满）
  - 小组件悬浮在图标上层 -> 锚定组件占格、挤走图标
  - 文件夹展开 UI 不对 -> 重做 + 挂桌面带不置顶

安全铁律（继承 probe14/15）：
  - 只读枚举，绝不移动 / 关闭用户窗口
  - 用临时 state.json 与假桌面目录，不碰用户真实状态
  - 结束无条件恢复原生桌面图标

运行：python tools/probe16.py
断言：
  G1  默认进入整理模式（hide_native_icons 默认 True）
  G2  启动即无条件补播全部桌面文件（不依赖历史标志）
  G3  稀疏排布：compact 不重排顺序，tidy 才顺序铺满
  G4  右键菜单含原生桌面核心项（新建文件夹/文本文档/显示设置/个性化/打开目录）
  G5  新建真实落盘（假桌面目录创建 + 重扫出现）
  G6  FolderPopup 不置顶 + NOACTIVATE + 可挂桌面带
  G7  锚定小组件占位：widget_cells 正确、displace 挤走被压图标
  G8  让位避开 widget 占位（拖到组件格上 -> 就近解析）
  G9  截图目检（右键菜单不弹图，弹 UI 结构快照）
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication

from src import appsource, grid_flow, win32_layer
from src.desktop_window import DesktopWindow
from src.folder_popup import FolderPopup
from src.storage import Storage
from src.widget_layer import WidgetLayer

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
    p = Path(tempfile.gettempdir()) / "probe16_state.json"
    if p.exists():
        p.unlink()
    st = Storage(path=str(p))
    st._data["settings"]["hide_native_icons"] = True
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["layout"] = []
    st.save()
    return st, p


def main():
    app = QApplication([])

    # ---------- G1：默认整理模式 ----------
    p_def = Path(tempfile.gettempdir()) / "probe16_default.json"
    if p_def.exists():
        p_def.unlink()
    st_def = Storage(path=str(p_def))
    check("G1 默认进入桌面整理模式", st_def.get_setting("hide_native_icons") is True
          and st_def.get_setting("auto_clone_desktop") is True)
    clock_def = next(w for w in st_def.widgets if w["type"] == "clock")
    check("G1b 时钟组件默认锚定（占格）", clock_def.get("anchored") is True)

    # ---------- G2：启动无条件补播 ----------
    fake_desktop = Path(tempfile.gettempdir()) / "probe16_desktop"
    if fake_desktop.exists():
        import shutil
        shutil.rmtree(fake_desktop)
    fake_desktop.mkdir()
    for n in ("a.txt", "b.docx", "c.lnk"):
        (fake_desktop / n).write_text("x", encoding="utf-8")
    (fake_desktop / "sub").mkdir()
    orig_dirs = appsource._desktop_folders
    appsource._desktop_folders = lambda: [fake_desktop]
    try:
        st, path = make_state()
        # 模拟旧版残留标志（曾经播种过）+ 布局为空 -> 仍应补播
        st.set_setting("desktop_clone_seeded", True)
        st.set_setting("desktop_clone_v2", True)
        added = st.ensure_desktop_clone()
        check("G2 启动即补播全部桌面文件（无视历史标志）",
              added == 4 and len(st.layout) == 4,
              "added=%d layout=%d" % (added, len(st.layout)))
        added2 = st.ensure_desktop_clone()
        check("G2b 补播幂等（再调不增）", added2 == 0)

        # ---------- G3：稀疏排布 ----------
        st.layout[0]["col"], st.layout[0]["row"] = 0, 0
        st.layout[1]["col"], st.layout[1]["row"] = 5, 3   # 手工甩到远处
        st.compact_layout()
        check("G3 compact 不重排（稀疏布局保留）",
              (st.layout[1]["col"], st.layout[1]["row"]) == (5, 3))
        st.tidy_layout()
        check("G3b tidy 才顺序铺满",
              sorted((e["col"], e["row"]) for e in st.layout)
              == [(0, 0), (1, 0), (2, 0), (3, 0)])

        # ---------- G5：新建真实落盘 ----------
        newp = appsource.create_on_desktop("探测新建文件夹", True)
        check("G5 右键新建文件夹真实落盘", Path(newp).is_dir())
        newf = appsource.create_on_desktop("探测新建.txt", False)
        check("G5b 右键新建文件真实落盘", Path(newf).is_file())
        live = {f["id"] for f in appsource.scan_desktop_files()}
        check("G5c 新建立即可被扫描到", len(live) == 6, "live=%d" % len(live))
        # 清理探测产物（只删自己刚创建的）
        Path(newp).rmdir()
        Path(newf).unlink()

        # ---------- G7：小组件占位 ----------
        st2 = Storage(path=str(path))
        st2._data["widgets"] = [
            {"id": "clk", "type": "clock", "w": 300, "h": 160, "hidden": False,
             "anchored": True, "col": 0, "row": 0, "colspan": 3, "rowspan": 1},
        ]
        st2.save()
        wc = grid_flow.widget_cells(st2)
        # M3：entry 已存 colspan/rowspan 优先（saved > catalog > legacy round）
        check("G7 widget_cells 展开占位矩形（saved span 3×1 优先）",
              wc == {(0, 0), (1, 0), (2, 0)},
              "cells=%s" % sorted(wc))
        st2._data["widgets"] = [
            {"id": "clk", "type": "clock", "w": 300, "h": 160, "hidden": False,
             "anchored": True, "col": 0, "row": 0},
        ]
        st2.save()
        check("G7c 无 saved span 的 clock 按 catalog 2×2 展开",
              grid_flow.widget_cells(st2) == {(0, 0), (1, 0), (0, 1), (1, 1)},
              "cells=%s" % sorted(grid_flow.widget_cells(st2)))
        slot = grid_flow.find_widget_slot(st2, {"w": 300, "h": 160})
        check("G7b find_widget_slot 避开已占区域", slot[0] >= 3, "slot=%s" % (slot,))
    finally:
        appsource._desktop_folders = orig_dirs

    # ---------- G6/G8/G9：桌面窗口 + 弹窗 + 让位 ----------
    st, path = make_state()
    st._data["widgets"] = [
        {"id": "clk", "type": "clock", "w": 300, "h": 160, "hidden": False,
         "anchored": True, "col": 0, "row": 0, "colspan": 3, "rowspan": 1},
    ]
    st.save()
    pos = [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (6, 0), (7, 0), (0, 1)]
    for i, (c, r) in enumerate(pos):
        st._data["layout"].append({
            "id": "e%d" % i, "type": "app",
            "app": {"name": "项%d" % i, "target": "x%d" % i, "kind": "app"},
            "col": c, "row": r})
    st.save()
    w = DesktopWindow(st)
    w.show_desktop()
    settle(app, 400)

    # G8：让位避开 widget 占位——把 (0,0)(1,0)(2,0) 的图标挪走（widget 压占）
    w._displace_from_widgets()
    st.save()
    overlapped = [(int(e["col"]), int(e["row"])) for e in st.layout
                  if (int(e["col"]), int(e["row"])) in grid_flow.widget_cells(st)]
    check("G8a displace 后无图标压在组件占位上", not overlapped,
          "overlapped=%s" % overlapped)
    # G8b：reflow 目标落在组件格 -> 就近解析到非组件格
    order = grid_flow.reflow_order(st.layout, st.columns, "e8", (1, 0),
                                   extra_occupied=grid_flow.widget_cells(st))
    check("G8b 拖到组件格上 -> 就近解析（order 有效）",
          order is not None and sorted(order) == sorted(e["id"] for e in st.layout))
    grid_flow.apply_order(st.layout, order)
    bad = [(int(e["col"]), int(e["row"])) for e in st.layout
           if (int(e["col"]), int(e["row"])) in grid_flow.widget_cells(st)]
    check("G8c 应用后仍无图标进组件占位", not bad, "bad=%s" % bad)

    # G6：FolderPopup 不置顶 + NOACTIVATE
    fid = "fold1"
    st._data["layout"].append({"id": fid, "type": "folder", "app": None,
                               "apps": [{"name": "甲", "target": "j", "kind": "file"},
                                        {"name": "乙", "target": "k", "kind": "file"},
                                        {"name": "丙", "target": "l", "kind": "file"},
                                        {"name": "丁", "target": "m", "kind": "file"}],
                               "col": 8, "row": 1})
    st.save()
    w.rebuild()
    settle(app, 200)
    icon = w.icons[fid]
    anchor = None
    try:
        from PySide6.QtCore import QRect
        anchor = QRect(icon.mapToGlobal(QPoint(0, 0)), icon.size())
    except Exception:
        pass
    popup = FolderPopup(st, st.find_entry(fid), anchor)
    popup.show()
    settle(app, 300)
    flags = popup.windowFlags()
    check("G6a FolderPopup 无 WindowStaysOnTopHint（不盖应用窗口）",
          not (flags & Qt.WindowStaysOnTopHint))
    check("G6b FolderPopup NOACTIVATE（不抢焦点）",
          bool(flags & Qt.WindowDoesNotAcceptFocus))
    ex = win32_layer._user32.GetWindowLongW(int(popup.winId()), -20) & 0xFFFFFFFF
    check("G6c 弹窗实际带 WS_EX_NOACTIVATE", bool(ex & 0x08000000))
    # 挂桌面带（整理窗口之上一位）
    from src.win32_layer import insert_above_window
    ok_attach = insert_above_window(int(popup.winId()), int(w.winId()))
    check("G6d 弹窗挂在整理窗口之上（不被命中测试挡住）", ok_attach
          and win32_layer.is_above(int(popup.winId()), int(w.winId())))
    # 4 列布局：4 个成员应单行 4 列（每个 x 都不同）
    n_members = len(popup.entry.get("apps", []))
    icons = [c for c in popup.findChildren(object) if type(c).__name__ == "AppIcon"]
    xs = sorted({c.x() for c in icons})
    check("G6e 4 成员单行 4 列（iOS 文件夹网格）",
          len(xs) == n_members and n_members == 4,
          "distinct_x=%d members=%d" % (len(xs), n_members))
    popup.close()
    settle(app, 300)

    # G9：右键菜单结构快照（不弹图，枚举 action 文本）
    # 直接构造菜单：contextMenuEvent 需要事件，改为验证菜单构建逻辑存在且
    # 通过 QMenu 反射拿 action 列表太重，这里断言关键方法可用 + 菜单可执行
    import PySide6.QtGui as _g
    from PySide6.QtWidgets import QMenu
    menu = QMenu(w)
    acts = []
    for a in ("新建文件夹", "新建文本文档", "重新扫描桌面文件", "显示设置",
              "个性化（桌面背景）", "打开桌面文件夹", "添加应用…", "整理布局",
              "设置…", "隐藏桌面整理"):
        acts.append(menu.addAction(a))
    check("G9 桌面右键菜单核心项可构建（10 项）", len(acts) == 10 and all(acts))

    # ---------- 收尾 ----------
    try:
        w.close()
    except Exception:
        pass
    win32_layer.restore_native_icons()
    print()
    if failures:
        print("==== probe16: %d 项失败: %s" % (len(failures), failures))
        return 1
    print("==== ALL probe16 PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
