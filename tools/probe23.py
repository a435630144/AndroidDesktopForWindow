# -*- coding: utf-8 -*-
"""probe23：v6 §4 分页渲染禁半截（2026-10-19，指导文档 §4）。

安全铁律（继承 probe14-22）：
  - offscreen 平台 + 临时 state.json，绝不碰用户真实状态与桌面
  - 不调用 show_desktop()（不挂桌面带、不隐藏原生图标）
  - appsource 已 monkeypatch 隔离（rescan 不扫真实桌面）
  - try/finally + 看门狗 + 幂等收尾，保证进程必退

断言（§4 验收：满页 + 组件贴页底 + 翻页动画中，三个场景均无半截渲染）：
  S0  满页多页布局：静止态无半截图标（可见图标必完整落在网格带内，
      邻页图标要么整块在窗外、要么隐藏）
  S1  组件贴页底：2×2 锚定组件占位底边不越出网格带（合法数据回归）
  S2  旧数据越页：spawn 时 span 夹紧到所属页行范围（rowspan 不越页底）
  S3  组件 hover 预览：指针贴页底时预览矩形不越页底（span 夹紧）
  S4  翻页动画：滑入页图标先显示、滑出页动画结束后隐藏；静止态无半截；
      锚定组件同向显隐
  S5  rescan 铺满后回第 0 页（pack 语义：不停在已被清空的旧页）
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from src import appsource
from src import grid_flow
from src.desktop_window import DesktopWindow
from src.storage import Storage
from src.widget_layer import WidgetLayer

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "probe23_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra), flush=True)
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
    # 2026-10-19 反馈 3：未接管会自动进入无界模式，网格让位探针
    # 必须显式声明「按接管语义」（不 show 窗口，不会真隐藏原生图标）
    st._data["settings"]["takeover_desktop"] = True
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


def build(app, st):
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    layer = WidgetLayer(st)
    w.set_widget_layer(layer)
    layer.gridChanged.connect(w.on_widget_grid_changed)
    layer.anchorHover.connect(w._on_widget_hover)
    layer.anchorDrop.connect(w._on_widget_drop)
    settle(app, 100)
    return w, layer


def band(st):
    """当前页可见带（窗口控件坐标）：(x, y, w, h)。"""
    cw, ch = grid_flow.cell_size(st)
    ox, oy = grid_flow.origin()
    return ox, oy, st.columns * cw, grid_flow.rows_per_page() * ch


def half_rendered_icons(w, st):
    """半截渲染的图标：与窗口有交集（可见）却未完整落在网格带内。"""
    ox, oy, bw, bh = band(st)
    bad = []
    for eid, ic in w.icons.items():
        if ic.isHidden():
            continue
        x, y, iw, ih = ic.x(), ic.y(), ic.width(), ic.height()
        if x + iw <= 0 or y + ih <= 0 or x >= W or y >= H:
            continue                      # 整块在窗外：不渲染，合规
        if (x >= ox and y >= oy
                and x + iw <= ox + bw and y + ih <= oy + bh):
            continue                      # 完整在网格带内：合规
        bad.append((eid, (x, y, iw, ih)))
    return bad


def half_rendered_widgets(layer, st):
    """半截渲染的锚定组件（顶层窗口：不被桌面窗口裁剪，越带即露半截）。"""
    ox, oy, bw, bh = band(st)
    bad = []
    for wid, wd in layer.widgets.items():
        if not getattr(wd, "anchored", False) or wd.isHidden():
            continue
        g = wd.geometry()
        if g.x() + g.width() <= 0 or g.y() + g.height() <= 0 \
                or g.x() >= W or g.y() >= H:
            continue
        if (g.x() >= ox and g.y() >= oy
                and g.x() + g.width() <= ox + bw
                and g.y() + g.height() <= oy + bh):
            continue
        bad.append((wid, (g.x(), g.y(), g.width(), g.height())))
    return bad


def rows_of(st):
    return {e["id"]: int(e.get("row", 0) or 0) for e in st.layout}


def run(app):
    # rescan 隔离：不扫真实桌面（铁律）
    appsource.scan_desktop_files = lambda: []

    cols = 4
    rpp = None

    # ---------- S0：满页多页布局，静止态无半截 ----------
    spec = [("i%02d" % i, i % cols, i // cols) for i in range(60)]
    st = make_state(spec, settings={"columns": cols})
    w, layer = build(app, st)
    rpp = grid_flow.rows_per_page()
    rows = rows_of(st)
    check("S0 布局确为多页（page_count>=2）",
          grid_flow.page_count(st) >= 2, "pages=%d" % grid_flow.page_count(st))
    bad = half_rendered_icons(w, st)
    check("S0 满页静止态无半截图标", not bad, "%s" % (bad[:4],))
    vis = [eid for eid, ic in w.icons.items() if not ic.isHidden()]
    check("S0 可见图标全部在当前页",
          all(grid_flow.page_of(rows[eid], rpp) == grid_flow.current_page()
              for eid in vis), "vis=%d" % len(vis))
    off = [eid for eid in vis
           if grid_flow.page_of(rows[eid], rpp) != grid_flow.current_page()]
    check("S0 邻页图标已隐藏（不露头/露尾）", not off, "%s" % (off[:4],))

    # ---------- S1：组件贴页底（合法数据回归） ----------
    wspec = [{"id": "clk", "type": "clock", "w": 300, "h": 160,
              "hidden": False, "anchored": True,
              "col": 0, "row": rpp - 2, "colspan": 2, "rowspan": 2}]
    st1 = make_state([("a", 0, 0), ("b", 1, 0)], widgets=wspec,
                     settings={"columns": cols})
    w1, layer1 = build(app, st1)
    g = layer1.widgets["clk"].geometry()
    ox, oy, bw, bh = band(st1)
    check("S1 组件贴页底：底边不越出网格带",
          g.y() + g.height() <= oy + bh and g.y() >= oy,
          "widget=%s band=(%d,%d,%d,%d)" % ((g.x(), g.y(), g.width(),
                                             g.height()), ox, oy, bw, bh))
    check("S1 组件贴页底：无半截组件", not half_rendered_widgets(layer1, st1))

    # ---------- S2：旧数据越页 -> spawn 夹紧 ----------
    wspec2 = [{"id": "nt", "type": "notes", "w": 300, "h": 300,
               "hidden": False, "anchored": True,
               "col": 0, "row": rpp - 1, "colspan": 2, "rowspan": 2}]
    st2 = make_state([("a", 0, 0)], widgets=wspec2,
                     settings={"columns": cols})
    w2, layer2 = build(app, st2)
    row2 = int(layer2.widgets["nt"].entry.get("row", -1))
    check("S2 旧数据越页：spawn 时 row 夹紧到 rpp-2（%d）" % (rpp - 2),
          row2 == rpp - 2, "got row=%d" % row2)
    g2 = layer2.widgets["nt"].geometry()
    check("S2 夹紧后组件完整落在网格带内",
          g2.y() + g2.height() <= oy + bh and g2.y() >= oy,
          "widget=%s" % ((g2.x(), g2.y(), g2.width(), g2.height()),))
    check("S2 无半截组件", not half_rendered_widgets(layer2, st2))

    # ---------- S3：hover 预览 span 夹紧 ----------
    cw, ch = grid_flow.cell_size(st2)
    ox, oy = grid_flow.origin()
    gx, gy = ox + cw // 2, oy + (rpp - 1) * ch + ch // 2   # 指针贴页底
    w2._on_widget_hover("nt", gx, gy)
    rect = w2._widget_preview_rect or set()
    max_row = max((r for _, r in rect), default=-1)
    check("S3 hover 贴页底：预览矩形不越页底（max row=%d <= %d）"
          % (max_row, rpp - 1), max_row <= rpp - 1, "rect=%s" % (sorted(rect),))

    # ---------- S4：翻页动画 ----------
    wspec4 = [{"id": "w0", "type": "clock", "w": 300, "h": 160,
               "hidden": False, "anchored": True,
               "col": 0, "row": 0, "colspan": 2, "rowspan": 2},
              {"id": "w1", "type": "clock", "w": 300, "h": 160,
               "hidden": False, "anchored": True,
               "col": 0, "row": rpp, "colspan": 2, "rowspan": 2}]
    st4 = make_state(spec, widgets=wspec4, settings={"columns": cols})
    w4, layer4 = build(app, st4)
    rows4 = rows_of(st4)
    p1 = [eid for eid, r in rows4.items()
          if grid_flow.page_of(r, rpp) == 1]
    check("S4 起始：次页图标隐藏", all(w4.icons[e].isHidden() for e in p1),
          "p1=%d" % len(p1))
    check("S4 起始：首页组件 w1 隐藏", layer4.widgets["w1"].isHidden())
    w4.goto_page(1, animate=True)
    # 滑行起始：新页内容必须先显示，否则滑入不可见
    check("S4 滑行起始：次页图标已显示（滑入可见）",
          all(not w4.icons[e].isHidden() for e in p1))
    check("S4 滑行起始：次页组件 w1 已显示",
          not layer4.widgets["w1"].isHidden())
    settle(app, 700)
    bad4 = half_rendered_icons(w4, st4)
    check("S4 翻页后静止态无半截图标", not bad4, "%s" % (bad4[:4],))
    check("S4 翻页后无半截组件", not half_rendered_widgets(layer4, st4))
    p0 = [eid for eid, r in rows4.items()
          if grid_flow.page_of(r, rpp) == 0]
    check("S4 滑出页图标动画结束后隐藏",
          all(w4.icons[e].isHidden() for e in p0), "p0=%d" % len(p0))
    check("S4 滑出页组件 w0 隐藏", layer4.widgets["w0"].isHidden())
    check("S4 次页图标可见且完整在带内",
          all(not w4.icons[e].isHidden() for e in p1))

    # ---------- S5：rescan 后回第 0 页 ----------
    w4.goto_page(1, animate=False)
    check("S5 准备：当前页=1", grid_flow.current_page() == 1)
    w4.rescan_desktop()
    check("S5 rescan 铺满后回到第 0 页（pack 语义）",
          grid_flow.current_page() == 0,
          "page=%d" % grid_flow.current_page())
    vis0 = [eid for eid, ic in w4.icons.items() if not ic.isHidden()]
    check("S5 第 0 页图标可见（不停在空页）",
          all(grid_flow.page_of(rows4[eid], rpp) == 0 for eid in vis0)
          and len(vis0) > 0, "vis=%d" % len(vis0))

    # ---------- 收尾 ----------
    for ww in (w, w1, w2, w4):
        try:
            ww.close()
        except Exception:
            pass
    settle(app, 300)


def main():
    app = QApplication([])
    wd = QTimer()
    wd.setSingleShot(True)
    wd.timeout.connect(lambda: (print("!! 看门狗超时", flush=True),
                                os._exit(3)))
    wd.start(90000)
    try:
        run(app)
    except Exception:
        import traceback
        traceback.print_exc()
        failures.append("run() 异常")
    finally:
        try:
            STATE.unlink()
        except Exception:
            pass
    print("-" * 56, flush=True)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures), flush=True)
        code = 1
    else:
        print("ALL probe23 PASSED", flush=True)
        code = 0
    print("==== 探针退出 ====", flush=True)
    app.processEvents()
    QTimer.singleShot(80, app.quit)
    app.exec()
    return code


if __name__ == "__main__":
    sys.exit(main())
