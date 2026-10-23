# -*- coding: utf-8 -*-
"""v7 反馈 1：组件拖动时图标的连锁避让（预览不叠、松手必完成）。

用户原话：
    小组件移动网格冲突的时候，其他图标进行避让还是存在避让预览的过程中
    堆叠到一起，其次也无法完成避让。

两个病根（逻辑层，可脱离真机断言）：
  W1 **预览重算只动画本次被挤走的图标**——上一轮被挤走、这一轮已回到
     原格的图标没人管，仍停在上一轮的目标格上，与刚被挤过去的图标叠在
     一起。修法：预览重排后把"布局位置与视觉位置不一致"的图标全部滑回。
  W2 **组件落回原格时不发 gridChanged**——预览期间图标已被挤走、松手按
     快照回退，若组件最终占位与拖动前相同（占位没变），没人再执行
     displace，图标留回组件底下，看着像"避让到一半停了"。
     修法：锚定组件落定时无条件通知一次（接收方幂等）。

运行：python tests/test_widget_displace_chain.py   （offscreen）
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
STATE = Path(tempfile.gettempdir()) / "test_displace_chain_state.json"
failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=600):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def QTest_qWait(ms):
    """无 QTest 依赖的小等待（泵事件，让动画计时器跑起来）。"""
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make_state(cols_cells):
    """cols_cells: [(id, col, row)] 图标；固定一个 2×2 锚定组件在 (0,0)。"""
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = True
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["settings"]["show_widgets"] = True
    st._data["widgets"] = [{
        "id": "clock", "type": "clock", "anchored": True,
        "col": 0, "row": 0, "colspan": 2, "rowspan": 2,
        "x": 0, "y": 0, "w": 200, "h": 200, "hidden": False,
    }]
    st._data["layout"] = [
        {"id": i, "type": "app",
         "app": {"name": i, "target": i, "kind": "app"},
         "apps": [], "col": c, "row": r}
        for i, c, r in cols_cells]
    st.save()
    return st


def widget_rect(st, col, row, cs=2, rs=2):
    return {(col + dc, row + dr) for dc in range(cs) for dr in range(rs)}


def snapshot(w):
    """{id: (视觉 x, y)}"""
    return {eid: (ic.x(), ic.y()) for eid, ic in w.icons.items()}


def cells_of(st):
    return {e.get("id"): (int(e.get("col", 0)), int(e.get("row", 0)))
            for e in st.layout}


def hover(w, st, col, row):
    """把组件预览拖到 (col,row)：换算成指针全局坐标后走真实入口。"""
    m = grid_flow.current_metrics()
    x, y = grid_flow.cell_pos(st, col, row)
    g = w.mapToGlobal(QPoint(x + m.cw // 2, y + m.ch // 2))
    w._on_widget_hover("clock", g.x(), g.y())


def assert_no_stack(w, st, tag, avoid_cells=()):
    """所有图标视觉位置唯一 + 不与布局位置脱节 + 不在禁区里。"""
    vis = snapshot(w)
    vals = list(vis.values())
    check("%s 图标视觉位置互不重叠" % tag, len(set(vals)) == len(vals),
          "%d 个图标 %d 个不同位置" % (len(vals), len(set(vals))))
    mismatched = []
    for e in st.layout:
        eid = e.get("id")
        if eid not in w.icons:
            continue
        want = w._entry_pos(e)
        if (w.icons[eid].x(), w.icons[eid].y()) != want:
            mismatched.append((eid, (w.icons[eid].x(), w.icons[eid].y()), want))
    check("%s 图标都滑到布局位置（无掉队）" % tag, not mismatched,
          "%s" % mismatched[:3])
    if avoid_cells:
        inside = [eid for eid, c in cells_of(st).items() if c in avoid_cells]
        check("%s 没有图标留在组件占位上" % tag, not inside, "%s" % inside)


def main(app):
    # 2×2 组件在 (0,0)；图标铺在右边几列，保证左右都有空位
    st = make_state([("a", 2, 0), ("b", 3, 0), ("c", 2, 1), ("d", 3, 1),
                     ("e", 5, 0), ("f", 5, 1)])
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    settle(app, 200)
    check("W0 图标与组件都已就位", len(w.icons) == 6,
          "icons=%d" % len(w.icons))

    # 第一轮预览：组件挪到 (2,0) 覆盖 a/b/c/d
    hover(w, st, 2, 0)
    settle(app)
    assert_no_stack(w, st, "W1 第一次预览", avoid_cells=widget_rect(st, 2, 0))

    # 第二轮预览：组件再挪到 (3,0) —— a/c 该回原位，b/d 与新进入的继续让位
    hover(w, st, 3, 0)
    settle(app)
    assert_no_stack(w, st, "W1 第二次预览", avoid_cells=widget_rect(st, 3, 0))
    check("W1 被释放的图标回到原格",
          cells_of(st).get("a") == (2, 0) and cells_of(st).get("c") == (2, 1),
          "%s" % {k: cells_of(st).get(k) for k in ("a", "c")})

    # 第三次预览：往回拖到 (1,0)（右半释放）
    hover(w, st, 1, 0)
    settle(app)
    assert_no_stack(w, st, "W1 第三次预览", avoid_cells=widget_rect(st, 1, 0))

    # 松手：快照回退 + 组件落定（模拟 _on_snapped 的占位写入）
    w._on_widget_drop("clock", 0, 0)
    we = st.widgets[0]
    we["col"], we["row"] = 3, 0
    w.on_widget_grid_changed()
    settle(app)
    assert_no_stack(w, st, "W2 松手后", avoid_cells=widget_rect(st, 3, 0))

    # W2b 组件落回**原格**：占位没变也必须再跑一次 displace
    hover(w, st, 4, 0)
    settle(app)
    w._on_widget_drop("clock", 0, 0)
    we["col"], we["row"] = 3, 0        # 与松手前相同的占位 -> 旧实现不发信号
    w.on_widget_grid_changed()
    settle(app)
    assert_no_stack(w, st, "W2b 落回原格", avoid_cells=widget_rect(st, 3, 0))

    w.close()

    # ---------- W3 满页：多出来的图标顺延到下一页，一个都不丢 ----------
    cols = None
    st2 = make_state([])
    w2 = DesktopWindow(st2)
    w2.resize(W, H)
    w2._update_grid_metrics()
    settle(app, 200)
    cols = st2.columns
    rpp = grid_flow.rows_per_page()
    spec = []
    k = 0
    for r in range(rpp):
        for c in range(cols):
            if c < 2 and r < 2:
                continue           # 组件占位
            spec.append(("i%d" % k, c, r))
            k += 1
    st2._data["layout"] = [
        {"id": i, "type": "app",
         "app": {"name": i, "target": i, "kind": "app"},
         "apps": [], "col": c, "row": r} for i, c, r in spec]
    st2.save()
    w2.refresh_grid()
    settle(app, 300)
    before = {e["id"] for e in st2.layout}
    # 组件从 (0,0) 挪到 (2,0)：原来 2 列的图标被挤，页内没有空格 -> 顺延
    hover(w2, st2, 2, 0)
    settle(app)
    w2._on_widget_drop("clock", 0, 0)
    we2 = st2.widgets[0]
    we2["col"], we2["row"] = 2, 0
    w2.on_widget_grid_changed()
    settle(app)
    after = {e["id"] for e in st2.layout}
    check("W3 满页挤位不丢图标", before == after,
          "lost=%s" % (before - after,))
    cells = [tuple(c) for c in cells_of(st2).values()]
    check("W3 满页挤位后格子仍互不重复", len(set(cells)) == len(cells),
          "%d cells %d unique" % (len(cells), len(set(cells))))
    w2.close()

    # ---------- W4：松手不回漂（v10 反馈 25） ----------
    # 病根：_on_widget_drop 先 _restore_snap + _sync_icons（图标动画回原位），
    # 再 gridChanged -> _widget_moved 正式 displace + 动画。两段动画之间图标
    # 先漂回冲突格再让位，肉眼看到"先回去再过来"。
    # 判据：_on_widget_drop 之后、gridChanged 之前，图标位置不应在原格上
    # 被 animate_to 弹回——即 _on_widget_drop 不调 _sync_icons。
    # 直接读源文件文本（inspect 可能读到缓存的旧源码）
    _src = (Path(__file__).resolve().parent.parent / "src" / "desktop_window.py").read_text(encoding="utf-8")
    _i = _src.index("def _on_widget_drop")
    _j = _src.index("def _reflow_preview", _i)
    _body = _src[_i:_j]
    # 判据：displace 有结果走 _animate_icons_to_layout，没有才 _sync_icons
    check("W4 displace 有结果走动画、无结果才回位",
          "_animate_icons_to_layout" in _body and "_displace_from_widgets" in _body,
          "missing displace path")
    check("W4 _on_widget_drop 仍 _restore_snap（数据回退）",
          "_restore_snap" in _body, "no restore")

    # ---------- W5：松手瞬间图标不动，落定后只动一次（v10 反馈 28） ----------
    # 病根是**时机**：widget_base 的 anchorDrop.emit() 排在 _snap_to_grid()
    # 之前（931/932 行），松手回调里 entry.col/row 还是旧格——按旧占位算
    # displace 必然为空，接着 _sync_icons 把预览挪走的图标**动画送回原位**，
    # 等 gridChanged 到了再挤一次 = 用户看到的"先漂回冲突格再让位"。
    # 判据：松手前后**视觉位置逐图标相等**（旧实现必红）。
    st5 = make_state([("a", 2, 0), ("b", 3, 0), ("c", 2, 1), ("d", 3, 1),
                      ("e", 5, 0), ("f", 5, 1)])
    w5 = DesktopWindow(st5)
    w5.resize(W, H)
    w5._update_grid_metrics()
    settle(app, 200)

    hover(w5, st5, 2, 0)              # 预览：组件压到 (2,0) 一带，a~d 被挤走
    settle(app, 300)
    check("W5a 预览后持有拖动快照", w5._widget_snap is not None,
          str(w5._widget_snap))
    before5 = snapshot(w5)

    # 松手（真实顺序：此时 entry 仍是旧格 (0,0)，落定在 _snap_to_grid 之后）
    w5._on_widget_drop("clock", 0, 0)
    QTest_qWait(40)
    after5 = snapshot(w5)
    moved5 = {k: (before5[k], after5.get(k)) for k in before5
              if after5.get(k) != before5[k]}
    check("W5b 松手瞬间图标视觉位置不变（不回漂）", not moved5,
          "%s" % list(moved5.items())[:2])
    check("W5c 松手不清快照（等落定再算）", w5._widget_snap is not None,
          str(w5._widget_snap))

    # 模拟组件真正落定：entry 写到最终格，再发 gridChanged
    for e in st5.widgets:
        if e.get("id") == "clock":
            e["col"], e["row"] = 2, 0
    st5.save()
    w5.on_widget_grid_changed()
    settle(app, 600)
    check("W5d 落定后消费掉快照", w5._widget_snap is None, str(w5._widget_snap))
    inside5 = [eid for eid, c in cells_of(st5).items()
               if c in widget_rect(st5, 2, 0)]
    check("W5e 被压图标最终不在组件占位上", not inside5, "%s" % inside5)
    mism5 = [(eid, (w5.icons[eid].x(), w5.icons[eid].y()), w5._entry_pos(e))
             for e in st5.layout if e.get("id") in w5.icons
             for eid in [e.get("id")]
             if (w5.icons[eid].x(), w5.icons[eid].y()) != w5._entry_pos(e)]
    check("W5f 全部图标滑到最终布局位置（一次到位）", not mism5,
          "%s" % mism5[:2])

    # W5g：组件拖回原格（最终没压人）——落定后图标回原位，单段动画
    st5b = make_state([("a", 2, 0), ("b", 3, 0), ("e", 5, 0)])
    w5b = DesktopWindow(st5b)
    w5b.resize(W, H)
    w5b._update_grid_metrics()
    settle(app, 200)
    hover(w5b, st5b, 2, 0)
    settle(app, 300)
    w5b._on_widget_drop("clock", 0, 0)
    w5b.on_widget_grid_changed()      # entry 仍是 (0,0) = 拖回原格
    settle(app, 600)
    back5 = [(eid, (w5b.icons[eid].x(), w5b.icons[eid].y()), w5b._entry_pos(e))
             for e in st5b.layout if e.get("id") in w5b.icons
             for eid in [e.get("id")]
             if (w5b.icons[eid].x(), w5b.icons[eid].y()) != w5b._entry_pos(e)]
    check("W5g 拖回原格：预览挪走的图标回原位", not back5, "%s" % back5[:2])
    w5.close()
    w5b.close()

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL displace_chain PASSED")
    return 0


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    sys.exit(main(app))
