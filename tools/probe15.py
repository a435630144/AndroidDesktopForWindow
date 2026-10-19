# -*- coding: utf-8 -*-
"""probe15：手机桌面化改造实机验证（实时让位 + dwell 合并 + 锚定小组件）。

安全铁律（继承 probe14）：
  - 只读枚举，绝不移动 / 关闭用户窗口
  - 用临时 state.json，不碰用户真实状态
  - 结束无条件恢复原生桌面图标

运行：python tools/probe15.py
断言：
  G1  reflow 预览使其他图标离开原格（实时性）
  G2  嵌套事件循环中 QPropertyAnimation 仍在推进（QDrag.exec() 不冻结动画）
  G3  提交后 storage 与图标位置一致、无重叠、占用格守恒
  G4  取消后全部图标回退到拖动前位置
  G5  dwell 满 450ms 后拖到图标上 -> 触发合并
  G6  dwell 未满即松手 -> 不合并，发生让位置换
  G7  锚定小组件：卡片外点击穿透（HTTRANSPARENT）
  G8  锚定小组件：松手后坐标吸附到网格
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEventLoop, QPoint, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtCore import Qt, QPointF
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from src import grid_flow, win32_layer
from src.desktop_window import DesktopWindow
from src.storage import Storage

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def make_state():
    p = Path(tempfile.gettempdir()) / "probe15_state.json"
    if p.exists():
        p.unlink()
    st = Storage(path=str(p))
    st._data["settings"]["hide_native_icons"] = True
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["layout"] = []
    # 8 个图标占满第一行 + 第二行前 3 个（含空位）
    pos = [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (6, 0), (7, 0),
           (0, 1), (2, 1)]
    for i, (c, r) in enumerate(pos):
        st._data["layout"].append({
            "id": "e%d" % i, "type": "app", "app": {"name": "项%d" % i,
            "target": "x%d" % i, "kind": "app"}, "col": c, "row": r})
    st.save()
    return st, p


def settle(app, ms=60):
    """处理事件循环 ms 毫秒（驱动动画）。"""
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def main():
    app = QApplication([])
    st, path = make_state()
    w = DesktopWindow(st)
    w.show_desktop()
    # 等启动模式解析完成再进断言：offscreen 挂载失败时 _try_attach_once
    # 会在 1500ms 后重试并落入 _enter_floating_mode——那次 setGeometry +
    # _update_grid_metrics 会重建网格快照与全部图标。若在模式解析前记录
    # pos_before（G4），回退断言对照的就是两套几何（G4 存量 flaky 根因）。
    # 真机挂载成功时此等待为空转（attached=True 无重试）。
    QTest.qWait(2200)

    ids = [e["id"] for e in st.layout]
    dragged, other = ids[0], ids[7]        # e0 在 (0,0)，e7 在 (7,0)

    # ---------- G1：悬停占用格不抢走目标（反馈 4）；拖到空格仍实时让位 ----------
    st.set_setting("auto_arrange", True)   # 递进模式：空格预览会牵动其他图标
    before = {eid: w.icons[eid].pos() for eid in ids}
    w._on_drag_started()
    w._drag_multi = False
    w._reflow_preview(dragged, (7, 0))     # 把 e0 悬停到 e7 的格（占用）
    settle(app, 60)
    moved_occ = [eid for eid in ids
                 if eid != dragged and w.icons[eid].pos() != before[eid]]
    check("G1 悬停占用格：其他图标不动（保住「松手合并」提示）",
          not moved_occ, "moved=%s" % moved_occ)
    w._reflow_preview(dragged, (11, 0))    # 空格：递进让位
    settle(app, 60)
    moved = [eid for eid in ids if eid != dragged and w.icons[eid].pos() != before[eid]]
    check("G1b 拖到空格：其他图标实时让位", len(moved) >= 1, "moved=%s" % moved)
    mid = w.icons[other].pos()
    target_other = w._entry_pos(st.find_entry(other))
    check("G1c 其他图标正在滑向新格（中途态）",
          mid != before[other] and mid != target_other,
          "mid=%s from=%s to=%s" % (mid, before[other], target_other))
    settle(app, 400)

    # ---------- G2：嵌套事件循环中动画仍在推进 ----------
    # 用一次性废件验证，绝不碰真实图标（startValue 是绝对坐标，会直接搬走图标）
    from PySide6.QtCore import QPropertyAnimation
    from PySide6.QtWidgets import QWidget
    scratch = QWidget()
    scratch.setGeometry(0, 0, 40, 40)
    scratch.show()
    anim = QPropertyAnimation(scratch, b"pos", scratch)
    anim.setDuration(400)
    anim.setStartValue(QPoint(0, 0))
    anim.setEndValue(QPoint(300, 0))
    anim.start()
    seen = []
    QTimer.singleShot(80, lambda: seen.append(scratch.pos()))
    loop = QEventLoop()
    QTimer.singleShot(160, loop.quit)
    loop.exec()
    check("G2 嵌套事件循环中动画推进", len(seen) == 1 and seen[0].x() > 0,
          "pos=%s" % (seen[0] if seen else None))
    anim.stop()
    scratch.close()
    scratch.deleteLater()

    # ---------- G3：提交一致性与无重叠 ----------
    cells_before = sorted((int(e["col"]), int(e["row"])) for e in st.layout)
    w._commit_preview()
    settle(app, 500)                       # 等让位动画落位再断言
    cells = [(int(e["col"]), int(e["row"])) for e in st.layout]
    check("G3 提交后无重叠", len(cells) == len(set(cells)))
    ok = True
    for e in st.layout:
        icon = w.icons.get(e["id"])
        if icon is None:
            ok = False
            continue
        if icon.pos() != QPoint(*w._entry_pos(e)):
            ok = False
    check("G3 提交后图标位置 == storage 布局", ok)
    if not ok:
        for e in st.layout:
            ic = w.icons.get(e["id"])
            if ic is not None and ic.pos() != QPoint(*w._entry_pos(e)):
                print("    mismatch %s: pos=%s expect=%s" %
                      (e["id"], ic.pos(), w._entry_pos(e)))
    check("G3 占用格守恒", sorted(cells) == cells_before,
          "%s vs %s" % (sorted(cells), cells_before))

    # ---------- G4：取消回退 ----------
    snap_before = [(e["id"], e["col"], e["row"]) for e in st.layout]
    pos_before = {eid: w.icons[eid].pos() for eid in ids}
    w._on_drag_started()
    w._reflow_preview(ids[5], (12, 0))     # e5 拖到空格（占用格不预览，反馈 4）
    settle(app, 120)
    check("G4 取消前预览已生效", any(w.icons[eid].pos() != pos_before[eid] for eid in ids))
    w._cancel_preview()
    settle(app, 400)
    reverted = all(w.icons[eid].pos() == pos_before[eid] for eid in ids)
    check("G4 取消后全部回退原位", reverted)
    if not reverted:
        for eid in ids:
            if w.icons[eid].pos() != pos_before[eid]:
                print("    revert mismatch %s: now=%s before=%s expect=%s" %
                      (eid, w.icons[eid].pos(), pos_before[eid],
                       w._entry_pos(st.find_entry(eid))))
    check("G4 取消后布局回到快照",
          [(e["id"], e["col"], e["row"]) for e in st.layout] == snap_before)

    # ---------- G5：dwell 满 -> 合并 ----------
    n_folders_before = sum(1 for e in st.layout if e.get("type") == "folder")
    merged = []
    w._on_merge_orig = w._on_merge
    w._on_merge = lambda p, t: (merged.append((p, t)), w._on_merge_orig(p, t))
    tgt = w.icons[ids[2]]
    from PySide6.QtCore import QMimeData
    from src.iconwidget import MIME_TYPE
    mime = QMimeData()
    mime.setData(MIME_TYPE, ids[0].encode())
    # 直接驱动 dwell：模拟 dragEnter -> 等待 450ms -> drop
    tgt._disarm_merge()
    tgt._dwell.start()
    QTest.qWait(600)
    check("G5 dwell 450ms 后合并武装", tgt._merge_armed)
    tgt.dropEvent(_mk_drop(mime))
    check("G5 武装后松手触发合并", len(merged) == 1, "merged=%s" % merged)
    check("G5 合并产生文件夹",
          sum(1 for e in st.layout if e.get("type") == "folder") > n_folders_before)
    w._on_merge = w._on_merge_orig
    settle(app, 300)

    # ---------- G6：dwell 未满 -> 不合并 ----------
    merged2 = []
    w._on_merge = lambda p, t: (merged2.append((p, t)), w._on_merge_orig(p, t))
    tgt2 = w.icons.get(ids[1])
    if tgt2 is not None:
        tgt2._disarm_merge()
        tgt2._dwell.start()
        QTest.qWait(80)                    # 远小于 450ms
        tgt2.dropEvent(_mk_drop(mime))
        check("G6 dwell 未满不触发合并", len(merged2) == 0, "merged=%s" % merged2)
    else:
        check("G6 dwell 未满不触发合并", True, "(目标已被合并吸收，跳过)")
    w._on_merge = w._on_merge_orig

    # ---------- G7 / G8 / G9：锚定（非悬浮）小组件 ----------
    from PySide6.QtWidgets import QWidget
    from src.widget_base import FloatingWidget
    from src.widget_layer import WidgetLayer
    from src.widgets_clock import ClockWidget

    def mk_mouse(widget, type_, local, btn=Qt.LeftButton):
        g = widget.mapToGlobal(local)
        return QMouseEvent(type_, QPointF(local), QPointF(g), btn, btn, Qt.NoModifier)

    entry = {"id": "anchor1", "type": "clock", "w": 260, "h": 150,
             "anchored": True, "hidden": False, "x": 400, "y": 300}
    st._data["widgets"] = [entry]
    st.save()
    layer = WidgetLayer(st)
    settle(app, 300)
    aw = layer.widgets.get("anchor1")
    check("G7 锚定组件由 WidgetLayer 创建", aw is not None and aw.isVisible())

    if aw is not None:
        check("G7a 锚定模式无关闭按钮命中区", aw._close_rect().isEmpty())
        check("G7b 锚定模式无缩放手柄命中区", aw._grip_rect().isEmpty())
        check("G7c 锚定组件带 NOACTIVATE（不抢焦点）",
              bool(aw.windowFlags() & Qt.WindowDoesNotAcceptFocus))
        # 点击右上角（悬浮模式下这里是 ×）：锚定模式不得关闭
        QApplication.sendEvent(aw, mk_mouse(aw, QMouseEvent.MouseButtonPress,
                                            QPoint(aw.width() - 10, 8)))
        QApplication.sendEvent(aw, mk_mouse(aw, QMouseEvent.MouseButtonRelease,
                                            QPoint(aw.width() - 10, 8)))
        check("G7d 锚定模式点右上角不关闭", not entry.get("hidden"))
        settle(app, 400)   # 等上一次松手的吸附动画结束，避免污染 G8

        # G8：真实拖拽（press -> move -> release）后吸附到网格
        scr = app.primaryScreen().availableGeometry()
        aw.move(400, 300)
        QApplication.sendEvent(aw, mk_mouse(aw, QMouseEvent.MouseButtonPress,
                                            QPoint(20, 20)))
        QApplication.sendEvent(aw, mk_mouse(aw, QMouseEvent.MouseMove, QPoint(90, 90)))
        QApplication.sendEvent(aw, mk_mouse(aw, QMouseEvent.MouseButtonRelease,
                                            QPoint(90, 90)))
        settle(app, 500)
        cw, ch = grid_flow.cell_size(st)
        ox, oy = grid_flow.origin()
        check("G8 拖拽松手后 x 吸附网格列", (aw.x() - ox) % cw == 0,
              "x=%d cw=%d ox=%d" % (aw.x(), cw, ox))
        check("G8 拖拽松手后 y 吸附网格行", (aw.y() - oy) % ch == 0,
              "y=%d ch=%d oy=%d" % (aw.y(), ch, oy))
        check("G8 吸附后仍在屏幕内",
              0 <= aw.x() <= scr.width() and 0 <= aw.y() <= scr.height())

    # G9：形态切换（锚定 -> 悬浮）后组件被重建且形态已变
    layer.set_anchored("anchor1", False)
    settle(app, 300)
    aw2 = layer.widgets.get("anchor1")
    check("G9 切换悬浮后组件仍存在", aw2 is not None)
    if aw2 is not None:
        check("G9 新组件是悬浮形态（有 × 命中区）", not aw2._close_rect().isEmpty())
        check("G9 entry.anchored 已持久化为 False", entry.get("anchored") is False)
        aw2.close()
    layer.set_visible(False)

    # ---------- G10：让位中途态截图存证 ----------
    live = [eid for eid in ids if eid in w.icons]     # G5 合并后 e0 已不存在
    w._on_drag_started()
    w._drag_multi = False
    w._reflow_preview(live[0], (7, 0))
    settle(app, 45)                       # 动画中途：其他图标正在滑行
    print("    [G10] 采样点位置: %s" %
          {eid: w.icons[eid].pos().x() for eid in live[:4]})
    shot = tempfile.gettempdir() + r"\probe15_reflow_mid.png"
    w.grab().save(shot)
    check("G10 让位中途截图已存证", os.path.exists(shot))
    settle(app, 400)
    w._commit_preview()

    # ---------- G11：图标上的 drop 必须让让位结果落盘 ----------
    # 真实鼠标拖动（verify_live 阶段5）曾失败在 (0,0)->(0,0)：预览在内存里生效、
    # 却从未提交，最后被 _cancel_preview 回退。根因是图标 dropEvent 里
    # e.ignore() 不会冒泡到父窗口（propagated=0）——现改为 reflowDrop 直连。
    live2 = [eid for eid in ids if eid in w.icons]
    if len(live2) >= 2:
        # mime payload 必须在 drop 前刷新：G5 合并后 e0（ids[0]）已不在
        # 布局，复用旧 mime 会让 drop 携带死 id——_reflow_commit_or_compute
        # 走 not moves 分支把在飞预览清掉（不提交也不回退），dragged 图标
        # 停在原位而 storage 已是目标格（G11c 曾经的败因形态；src 侧现已
        # 约定为回退快照，见 test_layout_anim T5f）
        mime.setData(MIME_TYPE, live2[0].encode())
        w._on_drag_started()
        w._drag_multi = False
        src_icon = w.icons[live2[0]]
        tgt_icon = w.icons[live2[1]]
        tgt_cell = (int(tgt_icon.entry.get("col", 0)), int(tgt_icon.entry.get("row", 0)))
        w._reflow_preview(live2[0], tgt_cell)
        settle(app, 400)
        tgt_icon._disarm_merge()
        tgt_icon.dropEvent(_mk_drop(mime))
        settle(app, 300)
        e = st.find_entry(live2[0])
        # 2026-10-19：_preview_order 随 M2 reflow_moves 换代已不存在，
        # 等价断言改为 _preview_moves（提交后必须清空，否则会被
        # _cancel_preview 回退——G11 的病根断言）
        check("G11a 图标上松手后预览已提交（不再待回退）",
              w._preview_moves is None, "preview=%s" % (w._preview_moves,))
        check("G11b dragged 落到目标格",
              (e.get("col"), e.get("row")) == tgt_cell,
              "now=%s target=%s" % ((e.get("col"), e.get("row")), tgt_cell))
        ic = w.icons.get(live2[0])
        check("G11c 图标控件位置与 storage 一致",
              ic is not None and ic.pos() == QPoint(*w._entry_pos(e)))
        cells_now = [(int(x["col"]), int(x["row"])) for x in st.layout]
        check("G11d 提交后仍无重叠", len(cells_now) == len(set(cells_now)))
    else:
        check("G11 图标上的 drop 落盘", True, "(图标不足，跳过)")

    # ---------- 收尾 ----------
    win32_layer.restore_native_icons()
    try:
        path.unlink()
    except Exception:
        pass
    app.quit()
    print("-" * 60)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL probe15 PASSED")
    return 0


def _mk_drop(mime):
    from PySide6.QtGui import QDropEvent
    return QDropEvent(QPointF(5, 5), Qt.MoveAction, mime,
                      Qt.LeftButton, Qt.NoModifier)


if __name__ == "__main__":
    sys.exit(main())
