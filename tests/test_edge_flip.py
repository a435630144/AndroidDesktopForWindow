# -*- coding: utf-8 -*-
"""边缘悬停翻页：拖到屏幕边缘停住 -> 翻到邻页（2026-10-21 用户反馈 8）。

用户原话：「问题8：新增功能，比如图标位于屏幕边缘且左或右存在分页的时候，
会在hover图标的情况下，把图标拽到下一个分页，就跟手机的逻辑一样。」

规格（手机 launcher 语义）：

  - 拖动图标到**翻页轴末端**的边缘带（EDGE_FLIP_BAND px）内停住，
    悬停 EDGE_FLIP_DWELL_MS 后翻到邻页；没有邻页（首页再往上 /
    末页再往下）不武装
  - 翻页轴跟随设置：horizontal -> 左/右边缘；vertical -> 上/下边缘
  - 按住不放**连续翻**（手机逻辑），翻到底自然收口；离开边缘带 /
    松手 / 拖到图标上（合成 dragLeave）即撤销
  - 翻页只改视图：拖影不动、网格滑动，松手按**新页**落点计算
  - 只对桌面图标拖动生效（_drag_active 门控）：无界模式、文件夹成员
    提取（M: payload 不置 _drag_active）、外部文件拖入都不翻页
  - 翻页 dwell 必须短于推让 dwell（PUSH_DWELL_MS）：同一边缘带上
    "先翻页、后推让"，否则两个手势抢同一位置

运行：python tests/test_edge_flip.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QMimeData, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QDragLeaveEvent
from PySide6.QtWidgets import QApplication, QWidget

from src import grid_flow
from src.desktop_window import (EDGE_FLIP_BAND, EDGE_FLIP_DWELL_MS,
                                PUSH_DWELL_MS, DesktopWindow)
from src.iconwidget import MIME_TYPE
from src.storage import Storage

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_edge_flip_state.json"

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


def make_state():
    """3 页布局：e0..e20 全排在第 0 列、全局行 0..20（rpp=10 -> 3 页）。"""
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"].update({
        "hide_native_icons": False,
        "auto_clone_desktop": False,
        "takeover_desktop": True,
        "layout_mode": "grid",
        "auto_arrange": False,      # 自由移动：落点 = 与占位者互换
        "page_axis": "horizontal",
        "dev_mode": False,
    })
    st._data["widgets"] = []
    st._data["layout"] = [
        {"id": "e%d" % i, "type": "app", "col": 0, "row": i,
         "app": {"name": "E%d" % i, "target": "e%d" % i, "kind": "app"}}
        for i in range(21)]
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
    """dragMoveEvent 只用 mimeData()/position()/acceptProposedAction()。

    PySide6 的 QDragMoveEvent 构造签名跨版本不稳（构造出来是裸 QObject，
    sendEvent 根本不派发——test_merge_dwell 的同款结论），这里用 duck
    typing 桩 + 直调处理器，语义等价。
    """

    def __init__(self, payload: str, pos=QPoint(20, 20)):
        self._md = QMimeData()
        self._md.setData(MIME_TYPE, payload.encode())
        self._pos = QPointF(pos)

    def mimeData(self):
        return self._md

    def position(self):
        return self._pos

    def acceptProposedAction(self):
        pass


def send_drag_move(w, local):
    """给桌面窗口补一发合成 dragMove（MIME_TYPE 内部拖拽）。"""
    w.dragMoveEvent(FakeDragEvent("e0", QPoint(local)))


def page_of_row(row):
    return grid_flow.page_of(int(row), grid_flow.rows_per_page())


def main(app):
    # ================= F1 常量契约 =================
    check("F1a EDGE_FLIP_BAND 存在且为正（边缘带宽度，px）",
          EDGE_FLIP_BAND is not None and 0 < EDGE_FLIP_BAND <= 64,
          "band=%s" % (EDGE_FLIP_BAND,))
    check("F1b EDGE_FLIP_DWELL_MS 落在 200~1500（悬停翻页时长）",
          EDGE_FLIP_DWELL_MS is not None
          and 200 <= EDGE_FLIP_DWELL_MS <= 1500,
          "dwell=%s" % (EDGE_FLIP_DWELL_MS,))
    check("F1c 翻页早于推让（同一边缘带上先翻页、后推让，两手势不抢）",
          EDGE_FLIP_DWELL_MS < PUSH_DWELL_MS,
          "flip=%s push=%s" % (EDGE_FLIP_DWELL_MS, PUSH_DWELL_MS))

    # ================= F2 _edge_dir_at 方向判定 =================
    st = make_state()
    w = new_window(app, st)
    rpp = grid_flow.rows_per_page()
    total = grid_flow.page_count(st)
    check("F2-pre 布局确实是 3 页（rpp 动态）", total == 3,
          "rpp=%s total=%s" % (rpp, total))
    w._drag_active = True
    w._drag_entry_id = "e0"

    check("F2a 指针在屏幕中部 -> 不翻页",
          w._edge_dir_at(QPoint(W // 2, H // 2)) == 0)
    grid_flow.set_page(1)
    check("F2b 左边缘带 + 有上一页 -> -1",
          w._edge_dir_at(QPoint(4, H // 2)) == -1)
    check("F2c 右边缘带 + 有下一页 -> +1",
          w._edge_dir_at(QPoint(W - 4, H // 2)) == 1)
    check("F2d 刚好在带外（band+8）-> 不翻页",
          w._edge_dir_at(QPoint(EDGE_FLIP_BAND + 8, H // 2)) == 0)
    grid_flow.set_page(0)
    check("F2e 首页左边缘带（没有上一页）-> 0",
          w._edge_dir_at(QPoint(4, H // 2)) == 0)
    check("F2f 首页右边缘带 -> +1",
          w._edge_dir_at(QPoint(W - 4, H // 2)) == 1)
    grid_flow.set_page(total - 1)
    check("F2g 末页右边缘带（没有下一页）-> 0",
          w._edge_dir_at(QPoint(W - 4, H // 2)) == 0)
    w._drag_active = False
    check("F2h 非拖动态（悬停不算）-> 0",
          w._edge_dir_at(QPoint(4, H // 2)) == 0)
    w._drag_active = True
    st._data["settings"]["layout_mode"] = "free"
    check("F2i 无界模式不翻页（没有页概念）",
          w._edge_dir_at(QPoint(4, H // 2)) == 0)
    st._data["settings"]["layout_mode"] = "grid"
    st._data["settings"]["page_axis"] = "vertical"
    grid_flow.set_page(1)          # 上下都有邻页，两个方向都可武装
    check("F2j 垂直轴：上边缘带 -> -1",
          w._edge_dir_at(QPoint(W // 2, 4)) == -1)
    check("F2k 垂直轴：下边缘带 -> +1",
          w._edge_dir_at(QPoint(W // 2, H - 4)) == 1)
    check("F2l 垂直轴：左右带不翻（轴不对）",
          w._edge_dir_at(QPoint(4, H // 2)) == 0)
    grid_flow.set_page(0)
    st._data["settings"]["page_axis"] = "horizontal"
    w.close()

    # ================= F3 dwell 到点翻页 =================
    st = make_state()
    w = new_window(app, st)
    grid_flow.set_page(1)
    w._drag_active = True
    w._drag_entry_id = "e0"
    send_drag_move(w, QPoint(4, H // 2))
    check("F3a 左边缘带武装翻页计时器", w._edge_flip_timer.isActive())
    check("F3b 方向 = 上一页(-1)", w._edge_flip_dir == -1)
    settle(app, EDGE_FLIP_DWELL_MS + 150)
    check("F3c dwell 到点翻到第 0 页",
          grid_flow.current_page() == 0, "page=%s" % grid_flow.current_page())
    check("F3d current_page 已持久化",
          w.storage.get_setting("current_page") == 0)
    w._on_drag_finished()
    w.close()

    # ================= F4 离开边缘带撤销 =================
    st = make_state()
    w = new_window(app, st)
    grid_flow.set_page(1)
    w._drag_active = True
    w._drag_entry_id = "e0"
    send_drag_move(w, QPoint(4, H // 2))
    settle(app, 100)
    check("F4-pre 计时器已武装", w._edge_flip_timer.isActive())
    send_drag_move(w, QPoint(W // 2, H // 2))      # 移回中部
    check("F4a 离开边缘带即撤销翻页", not w._edge_flip_timer.isActive())
    check("F4b 方向已清", w._edge_flip_dir == 0)
    settle(app, EDGE_FLIP_DWELL_MS + 250)
    check("F4c 停留再久也不翻页", grid_flow.current_page() == 1,
          "page=%s" % grid_flow.current_page())
    w._on_drag_finished()
    w.close()

    # ================= F5 松手 / dragLeave 撤销 =================
    st = make_state()
    w = new_window(app, st)
    grid_flow.set_page(1)
    w._drag_active = True
    w._drag_entry_id = "e0"
    send_drag_move(w, QPoint(4, H // 2))
    check("F5-pre 计时器已武装", w._edge_flip_timer.isActive())
    w._on_drag_finished()
    check("F5a 松手撤销边缘翻页", not w._edge_flip_timer.isActive()
          and w._edge_flip_dir == 0)
    # dragLeave（拖影滑到目标图标上：合成 dragLeave 先落到本窗口）
    w._drag_active = True
    send_drag_move(w, QPoint(4, H // 2))
    check("F5-pre2 重新武装", w._edge_flip_timer.isActive())
    w.dragLeaveEvent(QDragLeaveEvent())
    check("F5b 拖到图标上（dragLeave）撤销翻页（合并优先，不双触发）",
          not w._edge_flip_timer.isActive() and w._edge_flip_dir == 0)
    settle(app, EDGE_FLIP_DWELL_MS + 250)
    check("F5c 撤销后不翻页", grid_flow.current_page() == 1)
    w._on_drag_finished()
    w.close()

    # ================= F6 按住不放连续翻（手机逻辑）=================
    st = make_state()
    w = new_window(app, st)
    grid_flow.set_page(0)
    w._drag_active = True
    w._drag_entry_id = "e0"
    send_drag_move(w, QPoint(W - 4, H // 2))       # 右带，不移动鼠标
    settle(app, EDGE_FLIP_DWELL_MS + 150)
    check("F6a 第一次悬停到点翻到第 1 页",
          grid_flow.current_page() == 1, "page=%s" % grid_flow.current_page())
    settle(app, EDGE_FLIP_DWELL_MS + 150)
    check("F6b 按住不放继续翻到第 2 页（手机逻辑）",
          grid_flow.current_page() == 2, "page=%s" % grid_flow.current_page())
    settle(app, EDGE_FLIP_DWELL_MS + 250)
    check("F6c 末页收口，不再翻",
          grid_flow.current_page() == 2, "page=%s" % grid_flow.current_page())
    check("F6d 末页后计时器已收起", not w._edge_flip_timer.isActive())
    w._on_drag_finished()
    w.close()

    # ================= F7 端到端：翻页后松手落在新页 =================
    st = make_state()
    w = new_window(app, st)
    src = w.icons["e0"]
    grid_flow.set_page(1)
    src._press_pos = QPoint(src.width() // 2, src.height() // 2)
    src._exec_drag()                                # 真实拖影 + payload 提供者
    try:
        check("F7-pre _exec_drag 置上拖动态（payload 提供者链路）",
              w._drag_active and w._drag_entry_id == "e0")
        # 1) 拖到右边缘 -> 翻到第 2 页
        drag_to(src, QPoint(W - 4, H // 2))
        settle(app, EDGE_FLIP_DWELL_MS + 150)
        check("F7a 悬停翻到第 2 页", grid_flow.current_page() == 2,
              "page=%s" % grid_flow.current_page())
        # 2) 把拖影放到新页第 3 列第 20 行（全局行）的空格上
        cw, ch = grid_flow.cell_size(st)
        cx, cy = grid_flow.cell_pos(st, 3, 20)
        target = w.mapToGlobal(QPoint(cx + cw // 2, cy + ch // 2))
        drag_to(src, target)
        # 3) 松手：合成 drop 走真实入口
        src._finish_drag(target)
        e = st.find_entry("e0")
        check("F7b 松手落在新页（第 2 页）",
              grid_flow.entry_page(st, e) == 2,
              "row=%s page=%s" % (e.get("row"), grid_flow.entry_page(st, e)))
        check("F7c 落点列正确（第 3 列）", int(e["col"]) == 3,
              "col=%s" % (e.get("col"),))
        check("F7d 拖影已撤（松手收尾）", src._drag_ghost_w is None)
    finally:
        src._finish_drag(None)
        w.close()

    # ================= F8 翻页后红框/预览立即按新页重算 =================
    st = make_state()
    w = new_window(app, st)
    src = w.icons["e0"]
    grid_flow.set_page(0)
    src._press_pos = QPoint(src.width() // 2, src.height() // 2)
    src._exec_drag()
    try:
        drag_to(src, QPoint(W - 4, H // 2))
        settle(app, EDGE_FLIP_DWELL_MS + 150)
        check("F8-pre 已翻到第 1 页", grid_flow.current_page() == 1)
        # 不移动鼠标：红框与预览必须已经按新页算好（旧页格子按新页
        # 页偏移换算会画到屏外，用户松手前的最后一帧也必须是新页落点）
        hl = w._hl_cell
        check("F8a 翻页后红框在新页上（屏内可见）",
              hl is not None and page_of_row(hl[1]) == 1,
              "hl=%s" % (hl,))
        e = st.find_entry("e0")
        check("F8b 翻页后预览落点已按新页写入内存",
              grid_flow.entry_page(st, e) == 1,
              "row=%s" % (e.get("row"),))
    finally:
        src._finish_drag(None)
        w.close()

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL edge_flip PASSED")
    return 0


def drag_to(src, gpos, nudge=1):
    """两步移动：先到目标区（dragEnter），再微移 1px（dragMove）。"""
    src._drag_move(gpos)
    src._drag_move(QPoint(gpos.x() + nudge, gpos.y()))


def run_main():
    app = QApplication([])
    try:
        code = main(app)
    except Exception:
        import traceback
        traceback.print_exc()
        failures.append("main() 异常")
        code = 1
    try:
        STATE.unlink()
    except Exception:
        pass
    return code


if __name__ == "__main__":
    sys.exit(run_main())
