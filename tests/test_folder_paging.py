# -*- coding: utf-8 -*-
"""v7 反馈 3 / 4 · 文件夹分页与居中排布。

用户原话（2026-10-21）：

    问题3：比如文件夹的规格是 3*3，可以放入 9 个元素，超出的元素处理方式
    采用左右分页，分页方法与逻辑参考桌面分页。现在是继续渲染。
    问题4：3*3 的文件夹没有居中平均排布，布局偏左。

旧契约「超过容量只加行」（grid_shape(10) == (3,4)）被反馈 3 明确推翻：
弹窗会一路长高甚至顶出屏幕。新契约 = **满页封顶 + 左右分页**：

  - `folder_layout.page_count / clamp_page / page_items`（纯函数，本文件 P0 组）
  - 弹窗 `_build` 只排当前页成员；**payload 用全局下标**（三处消费都直接
    `folder["apps"][idx]`，用页内下标会把第 2 页第 1 个取成第 1 页第 1 个）
  - 翻页三入口：滚轮（与桌面整理模式同阈值 15）/ 横向滑动 / 点页点
  - 弹窗尺寸**不随页数变化**（否则每翻一页跳一次大小）

反馈 4 的根因是**两级左偏**：窗口有 240px 下限，窄内容（2 个成员）时成员
从 x=pad/2 起排，右侧空一大块；末行不足一排时又齐左。修法是两层居中：
内容块在窗口里居中 + 每一行单独居中。

运行：python tests/test_folder_paging.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from src import folder_layout
from src.desktop_window import DesktopWindow
from src.iconwidget import AppIcon
from src.storage import Storage

STATE = Path(tempfile.gettempdir()) / "test_folder_paging_state.json"

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


def make_state(n_members, frame=None):
    """建一个含 n_members 个成员的文件夹；frame 可单设尺寸上限。"""
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = False
    st._data["settings"]["auto_clone_desktop"] = False
    folder = {"id": "f", "type": "folder", "name": "文件夹",
              "col": 1, "row": 0,
              "apps": [{"name": "m%02d" % i, "target": "m%02d" % i,
                        "kind": "app"} for i in range(n_members)]}
    if frame is not None:
        folder["frame"] = list(frame)
    st._data["layout"] = [{"id": "a", "type": "app", "col": 0, "row": 0,
                           "app": {"name": "a", "target": "a",
                                   "kind": "app"}},
                          folder]
    st.save()
    return st


def send_click(w, local):
    g = QPointF(w.pos()) + QPointF(local)
    for etype in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        ev = QMouseEvent(etype, QPointF(local), g, Qt.LeftButton,
                         Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(w, ev)


def send_press(w, local):
    """只发 press（不 release）——滑动翻页要先按住再移动。"""
    g = QPointF(w.pos()) + QPointF(local)
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(local), g, Qt.LeftButton,
                     Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(w, ev)


def send_move(w, local, grab_local):
    g = QPointF(w.pos()) + QPointF(grab_local)
    ev = QMouseEvent(QEvent.MouseMove, QPointF(local), g, Qt.LeftButton,
                     Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(w, ev)


def send_wheel(w, local, dy):
    g = QPointF(w.pos()) + QPointF(local)
    ev = QWheelEvent(QPointF(local), g, QPoint(0, 0), QPoint(0, int(dy)),
                     Qt.NoButton, Qt.NoModifier, Qt.ScrollPhase.NoScrollPhase,
                     False)
    QApplication.sendEvent(w, ev)


def members_of(pop):
    return sorted([c for c in pop.findChildren(AppIcon) if c.in_folder],
                  key=lambda c: c.pos().y() * 10000 + c.pos().x())


def main(app):
    # ---------- P0：纯函数 ----------
    check("P0 capacity 3×3=9", folder_layout.capacity((3, 3)) == 9)
    check("P0 满页封顶：10/20 个成员都不加行",
          folder_layout.grid_shape(10) == (3, 3)
          and folder_layout.grid_shape(20) == (3, 3))
    check("P0 页数 ceil(n/9)：9->1, 10->2, 19->3",
          [folder_layout.page_count(n) for n in (0, 9, 10, 19)] == [1, 1, 2, 3])
    check("P0 page_items 第 2 页 offset=9（全局下标）",
          folder_layout.page_items(list(range(20)), 1)[1] == 9)
    check("P0 clamp_page 越界回末页",
          folder_layout.clamp_page(7, 10) == 1)

    # ---------- P1：12 个成员 -> 2 页，尺寸封顶 ----------
    st = make_state(12)
    w = DesktopWindow(st)
    scr_geo = app.primaryScreen().availableGeometry()
    w.resize(scr_geo.size())
    w._update_grid_metrics()
    w.attached = True
    w.open_folder("f")
    settle(app, 200)
    pop = w._popup
    check("P1 弹窗已创建", pop is not None)
    if pop is None:
        return
    check("P1 12 个成员 -> 2 页", pop._page_total() == 2,
          "total=%d" % pop._page_total())
    check("P1 多页时页点占位（>0）", pop._pager_h() > 0,
          "h=%d" % pop._pager_h())
    check("P1 首页只排 9 个成员控件", len(members_of(pop)) == 9,
          "n=%d" % len(members_of(pop)))

    # 尺寸封顶：12 个成员的**内容高度**必须等于 9 个成员的（不再长高）；
    # 总高只差一个页点条（那是分页的代价，合理且固定）
    st9 = make_state(9)
    w9 = DesktopWindow(st9)
    w9.resize(scr_geo.size())
    w9._update_grid_metrics()
    w9.attached = True
    w9.open_folder("f")
    settle(app, 200)
    pop9 = w9._popup
    check("P1b 12 成员内容高度 == 9 成员（不加行）",
          pop.height() - pop._pager_h() == pop9.height() - pop9._pager_h(),
          "12:%d-%d 9:%d-%d" % (pop.height(), pop._pager_h(),
                                pop9.height(), pop9._pager_h()))
    check("P1b 9 成员时无页点占位", pop9._pager_h() == 0)

    # ---------- P2：翻页后成员数 / payload 全局下标 ----------
    pop._set_page(1)
    settle(app, 200)
    mems = members_of(pop)
    check("P2 第 2 页只排 3 个成员控件", len(mems) == 3,
          "n=%d" % len(mems))
    idxs = sorted(int(c.drag_payload.rsplit(":", 1)[1]) for c in mems)
    check("P2 第 2 页 payload 是全局下标 9/10/11",
          idxs == [9, 10, 11], "%s" % (idxs,))
    check("P2 页点数量 == 总页数", len(pop._pager_dots()) == 2)

    # ---------- P3：滚轮翻页 ----------
    send_wheel(pop, QPoint(pop.width() // 2, pop.height() // 2), -120)
    settle(app, 150)
    check("P3 滚轮下滚 -> 回第 1 页", pop._page == 0,
          "page=%d" % pop._page)
    send_wheel(pop, QPoint(pop.width() // 2, pop.height() // 2), 120)
    settle(app, 150)
    check("P3 滚轮上滚 -> 去第 2 页", pop._page == 1,
          "page=%d" % pop._page)

    # ---------- P4：横向滑动翻页（点在左下留白，不碰标题/按钮/页点/成员） ----------
    swipe_pt = QPoint(6, pop.height() - 4)
    send_press(pop, swipe_pt)                   # 只按不松（release 会清起点）
    for dx in (10, 20, 30, 40):                 # 累计 > 28 阈值即翻页
        send_move(pop, QPoint(swipe_pt.x() + dx, swipe_pt.y()), swipe_pt)
    check("P4 左滑（dx>0）-> 回第 1 页", pop._page == 0,
          "page=%d" % pop._page)
    send_press(pop, swipe_pt)
    for dx in (-10, -20, -30, -40):
        send_move(pop, QPoint(swipe_pt.x() + dx, swipe_pt.y()), swipe_pt)
    check("P4b 右滑（dx<0）-> 去第 2 页", pop._page == 1,
          "page=%d" % pop._page)

    # ---------- P5：点页点跳页 ----------
    dots = pop._pager_dots()
    if len(dots) == 2:
        send_click(pop, dots[0][0].center())
        settle(app, 150)
        check("P5 点第 1 个页点 -> 第 1 页", pop._page == 0,
              "page=%d" % pop._page)
        send_click(pop, dots[1][0].center())
        settle(app, 150)
        check("P5b 点第 2 个页点 -> 第 2 页", pop._page == 1,
              "page=%d" % pop._page)

    # ---------- P6：页号夹紧（删到不满一页时回上一页） ----------
    pop.entry["apps"] = pop.entry["apps"][:3]
    pop.refresh()
    settle(app, 200)
    check("P6 只剩 3 个成员 -> 1 页且页号归 0",
          pop._page_total() == 1 and pop._page == 0,
          "total=%d page=%d" % (pop._page_total(), pop._page))
    check("P6b 单页时不画页点", pop._pager_dots() == [])

    # ---------- P7：反馈 4 · 居中平均排布 ----------
    st4 = make_state(2)                     # 2 个成员：内容远窄于 240 下限
    w4 = DesktopWindow(st4)
    w4.resize(scr_geo.size())
    w4._update_grid_metrics()
    w4.attached = True
    w4.open_folder("f")
    settle(app, 200)
    pop4 = w4._popup
    mems4 = members_of(pop4)
    if len(mems4) == 2:
        left = min(c.x() for c in mems4)
        right = max(c.x() + c.width() for c in mems4)
        gap_l, gap_r = left, pop4.width() - right
        check("P7 反馈4 内容块水平居中（左右留白差 ≤2px）",
              abs(gap_l - gap_r) <= 2, "L=%d R=%d" % (gap_l, gap_r))
    # 末行居中：4 个成员 3 列 -> 第 2 行 1 个，必须排在当行中间
    st5 = make_state(4)
    w5 = DesktopWindow(st5)
    w5.resize(scr_geo.size())
    w5._update_grid_metrics()
    w5.attached = True
    w5.open_folder("f")
    settle(app, 200)
    pop5 = w5._popup
    mems5 = members_of(pop5)
    rows = {}
    for c in mems5:
        rows.setdefault(c.y(), []).append(c)
    if len(rows) == 2:
        last = sorted(rows[sorted(rows)[-1]], key=lambda c: c.x())
        row_w = last[0].width()
        gap_l, gap_r = last[0].x(), pop5.width() - (last[-1].x() + row_w)
        check("P7b 反馈4 末行（1 个）在当行居中",
              abs(gap_l - gap_r) <= 2, "L=%d R=%d" % (gap_l, gap_r))
        first = sorted(rows[sorted(rows)[0]], key=lambda c: c.x())
        check("P7c 首行 3 个仍左起连续排布（不重排）",
              len(first) == 3, "n=%d" % len(first))

    # ---------- P8：新成员跳到它所在的页 ----------
    st6 = make_state(10)                    # 第 2 页只有 1 个
    w6 = DesktopWindow(st6)
    w6.resize(scr_geo.size())
    w6._update_grid_metrics()
    w6.attached = True
    w6.open_folder("f")
    settle(app, 200)
    pop6 = w6._popup
    check("P8 初始停在第 1 页", pop6._page == 0)
    pop6._add_member_by_id("a")
    settle(app, 250)
    check("P8b 加完成员翻到它所在页（第 2 页）", pop6._page == 1,
          "page=%d" % pop6._page)
    mems6 = members_of(pop6)
    check("P8c 第 2 页含新成员 a",
          any((c.drag_payload or "").endswith(":10") for c in mems6),
          "%s" % [c.drag_payload for c in mems6])

    print("")
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL folder_paging PASSED")
    return 0


if __name__ == "__main__":
    app = QApplication(sys.argv)
    sys.exit(main(app))
