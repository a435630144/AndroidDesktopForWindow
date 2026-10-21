# -*- coding: utf-8 -*-
"""反馈 6 契约：从文件夹拖出（未松手）时的落点预览。

用户原话：
    当软件从文件夹内拖出且没有松手的时候，让它可以与桌面的其他元素发生
    碰撞检测的预览，比如当前格子的红色背景底色。

探针（probe_f6b / probe_f6c）实证抓到两个真 bug：
  ① 拖影是 `Qt.ToolTip` 顶层窗，`QApplication.widgetAt()` 在它下面返回
     None、`topLevelAt()` 也只返回拖影自己 —— 拖动中命中恒为 None。
     桌面图标有 `_host_desktop` 兜底没事，**文件夹成员**在
     `if self.in_folder: return target` 直接返回 None，合成 dragMove /
     drop 全发不出去（慢速拖出"完全失效"）。
  ② 幕布（ScrimWindow）只转发了 drop，没转发 dragMove —— 拖动过程中
     桌面侧完全没有预览（红框 / 让位都没有）。

修法：
  - `AppIcon._drag_surface_at()` 自算承载面：遍历可见顶层窗（排除拖影
    与自己、排除提示气泡），取**包含该点中面积最小**的一个（面积是
    z-order 的可靠代理：弹窗 < 幕布 < 全屏桌面）。
  - `ScrimWindow.dragMoveEvent` 转发 `dragMoved`（带全局落点）。
  - `_preview_from_scrim` 画红框，位置与 `_on_extract` **同口径**：
    目标格空 -> 目标格；被占 -> `storage.first_free_cell()`（与 add_app
    同一函数，不另写一份扫描）。

契约：
  G1 面积最小者胜（弹窗压过全屏桌面）
  G2 提示气泡不是承载面（排除后落到下一层）
  G3 拖影自己不算承载面
  G4 不可见窗不算
  G5 点不在任何窗内 -> None
  G6 幕布 dragMove 转发 dragMoved，带**全局**坐标
  G7 `_preview_from_scrim` 目标格空 -> 红框在目标格
  G8 `_preview_from_scrim` 目标格被占 -> 红框退第一个空格（与落点一致）
  G9 非成员 payload（桌面图标 / 外部文件）不在幕布路径预览
  G10 无界模式不预览（组件与图标都不占格）
  G11 `_extract_landing_cell` 与 `add_app` 同规则（空 -> 原格 / 占 -> 首空）

运行：python tests/test_drag_surface.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QMimeData, QPoint, QPointF, Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from src import grid_flow, grid_sizing as gs
from src.desktop_window import DesktopWindow
from src.folder_popup import ScrimWindow
from src.iconwidget import AppIcon, MIME_TYPE
from src.storage import Storage

W, H = 1920, 1040
BASE = 2600          # 承载面测试的窗口都摆到远处，避开真实桌面窗口
STATE = Path(tempfile.gettempdir()) / "test_drag_surface_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=120):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def folder_entry():
    return {"id": "f1", "type": "folder", "name": "文件夹",
            "apps": [{"name": "A", "target": "a", "kind": "app"},
                     {"name": "B", "target": "b", "kind": "app"}]}


def make_state(icons=()):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"].update({
        "hide_native_icons": False,
        "auto_clone_desktop": False,
        "takeover_desktop": True,
        "layout_mode": "grid",
        "dev_mode": False,
        "auto_arrange": False,
    })
    st._data["widgets"] = []
    st._data["layout"] = [
        {"id": "e%d" % i, "type": "app", "col": c, "row": r,
         "app": {"name": "E%d" % i, "target": "e%d" % i, "kind": "app"}}
        for i, (c, r) in enumerate(icons)]
    st.save()
    return st


def new_window(app, st):
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    w.rebuild()
    w.show()
    settle(app, 120)
    return w


class FakeDragEvent:
    """scrim.dragMoveEvent 只用 mimeData()/position()/acceptProposedAction()。

    PySide6 手搓 QDragMoveEvent 构造出来是裸 QObject、sendEvent 不派发
    （test_merge_dwell / test_edge_flip 同款结论），用 duck typing 桩直调。
    """

    def __init__(self, payload: str, local=QPoint(20, 20)):
        self._md = QMimeData()
        self._md.setData(MIME_TYPE, payload.encode())
        self._pos = QPointF(local)

    def mimeData(self):
        return self._md

    def position(self):
        return self._pos

    def acceptProposedAction(self):
        pass


def md_of(payload: str):
    md = QMimeData()
    md.setData(MIME_TYPE, payload.encode())
    return md


# ------------------------------------------------------------- G1–G5
def part_surface(app):
    lay = gs.icon_layout(83, 102, "medium")
    ic = AppIcon(folder_entry(), 0, layout=lay)

    big = QWidget()
    big.setGeometry(BASE, BASE, 800, 600)
    big.show()
    small = QWidget()
    small.setGeometry(BASE + 100, BASE + 100, 200, 200)
    small.show()
    settle(app, 80)
    point = QPoint(BASE + 150, BASE + 150)      # 同时落在 big / small 内

    check("G1 面积最小者胜（弹窗压过全屏桌面）",
          ic._drag_surface_at(point) is small,
          "hit=%s" % ("small" if ic._drag_surface_at(point) is small else "other"))

    # ---------- G2 提示气泡不是承载面 ----------
    tip = QWidget()
    tip.setWindowFlags(Qt.ToolTip)
    tip.setGeometry(BASE + 120, BASE + 120, 60, 60)
    tip.show()
    settle(app, 60)
    check("G2 气泡（Qt.ToolTip）被排除，落到下一层",
          ic._drag_surface_at(point) is small,
          "hit=%s" % ("small" if ic._drag_surface_at(point) is small else "other"))
    tip.hide()

    # ---------- G3 拖影自己不算 ----------
    ghost = QWidget()
    ghost.setGeometry(BASE + 140, BASE + 140, 20, 20)
    ghost.show()
    settle(app, 60)
    ic._drag_ghost_w = ghost
    check("G3 拖影自己不算承载面",
          ic._drag_surface_at(point) is small,
          "hit=%s" % ("small" if ic._drag_surface_at(point) is small else "other"))
    ic._drag_ghost_w = None
    ghost.hide()

    # ---------- G4 不可见窗不算 ----------
    small.hide()
    settle(app, 60)
    hidden = QWidget()
    hidden.setGeometry(BASE + 90, BASE + 90, 60, 60)     # 更小但没 show
    check("G4 不可见窗不算承载面",
          ic._drag_surface_at(point) is big,
          "hit=%s" % ("big" if ic._drag_surface_at(point) is big else "other"))
    small.show()

    # ---------- G5 点不在任何窗内 ----------
    check("G5 点不在任何窗内 -> None",
          ic._drag_surface_at(QPoint(BASE + 5000, BASE + 5000)) is None,
          "%s" % (ic._drag_surface_at(QPoint(BASE + 5000, BASE + 5000)),))

    for w in (big, small, hidden, tip, ghost):
        w.hide()
        w.deleteLater()
    ic.deleteLater()
    settle(app, 60)


# --------------------------------------------------------------- G6
def part_scrim(app):
    scrim = ScrimWindow()
    scrim.setGeometry(BASE, BASE, 400, 300)
    scrim.show()
    settle(app, 80)
    got = []
    scrim.dragMoved.connect(lambda md, p: got.append((md is not None, p)))

    local = QPoint(30, 40)
    scrim.dragMoveEvent(FakeDragEvent("M:f1:0", local))
    want = scrim.mapToGlobal(local)
    check("G6 幕布 dragMove 转发 dragMoved", len(got) == 1, "n=%d" % len(got))
    check("G6b 转发的是全局坐标（桌面侧直接 mapFromGlobal）",
          bool(got) and got[0][1] == want,
          "got=%s want=%s" % (got[0][1] if got else None, want))
    scrim.hide()
    scrim.deleteLater()
    settle(app, 60)


# ----------------------------------------------------------- G7–G11
def part_preview(app):
    st = make_state(icons=[(0, 0), (1, 0)])
    w = new_window(app, st)
    pos_empty = w.mapToGlobal(QPoint(*grid_flow.cell_pos(st, 5, 5)))
    pos_busy = w.mapToGlobal(QPoint(*grid_flow.cell_pos(st, 0, 0)))

    # ---------- G7 目标格空 -> 红框在目标格 ----------
    w._set_highlight(None)
    w._preview_from_scrim(md_of("M:f1:0"), pos_empty)
    check("G7 目标格空 -> 红框落在目标格", w._hl_cell == (5, 5),
          "hl=%s" % (w._hl_cell,))

    # ---------- G8 目标格被占 -> 退第一个空格 ----------
    free = st.first_free_cell()
    w._set_highlight(None)
    w._preview_from_scrim(md_of("M:f1:0"), pos_busy)
    check("G8 目标格被占 -> 红框退第一个空格",
          w._hl_cell == (int(free[0]), int(free[1])),
          "hl=%s free=%s" % (w._hl_cell, free))

    # ---------- G9 非成员 payload 不走幕布预览 ----------
    w._set_highlight(None)
    w._preview_from_scrim(md_of("e0"), pos_empty)
    check("G9 桌面图标 payload 不在幕布路径预览（有各自路径）",
          w._hl_cell is None, "hl=%s" % (w._hl_cell,))

    # ---------- G10 无界模式不预览 ----------
    st._data["settings"]["layout_mode"] = "free"
    st.save()
    w2 = new_window(app, st)
    w2._set_highlight(None)
    w2._preview_from_scrim(md_of("M:f1:0"),
                           w2.mapToGlobal(QPoint(*grid_flow.cell_pos(st, 3, 3))))
    check("G10 无界模式不预览", w2._hl_cell is None, "hl=%s" % (w2._hl_cell,))
    w2.close()

    # ---------- G11 落点规则与 add_app 同口径 ----------
    check("G11 空格落点 = 原格",
          w._extract_landing_cell((5, 5)) == (5, 5),
          "%s" % (w._extract_landing_cell((5, 5)),))
    free2 = st.first_free_cell()
    check("G11b 被占格落点 = first_free_cell（与 add_app 同一函数）",
          w._extract_landing_cell((0, 0)) == (int(free2[0]), int(free2[1])),
          "%s vs %s" % (w._extract_landing_cell((0, 0)), free2))
    w.close()


def main(app):
    part_surface(app)
    part_scrim(app)
    part_preview(app)

    print("-" * 56)
    if failures:
        print("FAILED: %s" % failures)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    rc = 1
    crashed = False
    try:
        rc = main(app)
    except Exception:
        import traceback
        traceback.print_exc()
        crashed = True
    finally:
        sys.stdout.flush()
        sys.exit(1 if (crashed or rc != 0) else 0)
