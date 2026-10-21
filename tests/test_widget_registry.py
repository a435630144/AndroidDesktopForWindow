# -*- coding: utf-8 -*-
"""组件注册表（v8 C1，指导文档_v8.md §2.1）。

契约：
  R1  三个老组件全部登记（clock / notes / panel），显示名与旧 WIDGET_NAMES 一致
  R2  每个 spec 的静态字段完整（type/name/summary/factory/spans/category）
  R3  widget_catalog.spans / default_span 与注册表一致（薄壳，不各存一份）
  R4  widget_layer.WIDGET_TYPES / WIDGET_NAMES 由注册表派生
  R5  未登记类型：get -> None，spans -> []，default_span -> None
  R6  categories() 去重且按"首次登记顺序"稳定
  R7  all_specs() 全量且顺序稳定（两次调用相同）
  R8  add("notes") 新增条目 + 建窗口 + 落盘
  R9  单实例组件重复 add 不新增条目，只把已隐藏的那个显示出来
  R10 多实例组件重复 add 会新增第二个
  R11 remove(id) 关闭窗口 + 从 storage 移除 + 落盘
  R12 add / remove 都发 widgetsChanged（组件库与托盘靠它刷新）
  R13 兼容：grid_flow.widget_span 仍按原逻辑算（老组件行为零变化）

运行：python tests/test_widget_registry.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.storage import Storage

STATE = Path(tempfile.gettempdir()) / "test_widget_registry_state.json"

CHECKS = []
failures = []


def check(name, cond, extra=""):
    CHECKS.append(name)
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=250):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make_state(widgets):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = False
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["layout"] = []
    st._data["widgets"] = [dict(w) for w in widgets]
    st.save()
    return st


def main(app):
    from src import widget_registry as reg

    st = make_state([
        {"id": "clock", "type": "clock", "w": 300, "h": 160, "hidden": False,
         "anchored": True},
        {"id": "note1", "type": "notes", "w": 300, "h": 300, "hidden": True,
         "text": ""},
    ])
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)

    # ---------- R1 老组件登记 ----------
    spec = reg.get("clock")
    check("R1 时钟已登记", spec is not None)
    check("R1b 三个老组件都在册",
          all(reg.get(t) is not None for t in ("clock", "notes", "panel")),
          str(sorted(reg.names())))
    check("R1c 显示名与旧 WIDGET_NAMES 一致",
          reg.names().get("panel") == "桌面面板" and reg.names().get("notes") == "便签",
          str(reg.names()))

    # ---------- R2 字段完整 ----------
    ok = True
    for s in reg.all_specs():
        ok = ok and bool(s.type and s.name and s.summary and s.factory
                         and s.spans and s.category)
    check("R2 每个 spec 的静态字段完整", ok)
    check("R2b 默认跨度 = spans 第一项",
          reg.default_span("panel") == (3, 4) and reg.spans("panel")[0] == (3, 4),
          str(reg.spans("panel")))

    # ---------- R3 catalog 薄壳 ----------
    from src import widget_catalog
    check("R3 catalog.spans 与注册表一致",
          all(widget_catalog.spans(t) == reg.spans(t) for t in reg.names()),
          "%s vs %s" % (widget_catalog.spans("clock"), reg.spans("clock")))
    check("R3b catalog.default_span 与注册表一致",
          widget_catalog.default_span("notes") == reg.default_span("notes"))

    # ---------- R4 widget_layer 派生 ----------
    from src import widget_layer
    check("R4 WIDGET_TYPES 由注册表派生",
          set(widget_layer.WIDGET_TYPES) == set(reg.names()),
          str(sorted(widget_layer.WIDGET_TYPES)))
    check("R4b WIDGET_NAMES 由注册表派生",
          widget_layer.WIDGET_NAMES == reg.names())

    # ---------- R5 未登记类型 ----------
    check("R5 未登记类型 get -> None", reg.get("does-not-exist") is None)
    check("R5b 未登记类型 spans -> [] / default_span -> None",
          reg.spans("does-not-exist") == [] and reg.default_span("does-not-exist") is None)

    # ---------- R6 分类 ----------
    cats = reg.categories()
    check("R6 分类去重且顺序稳定",
          cats == reg.categories() and len(cats) == len(set(cats)) and "时间" in cats,
          str(cats))
    check("R6b 每个 spec 的分类都在 categories() 里",
          all(s.category in cats for s in reg.all_specs()))

    # ---------- R7 全量顺序 ----------
    a = [s.type for s in reg.all_specs()]
    b = [s.type for s in reg.all_specs()]
    check("R7 all_specs 顺序稳定且覆盖全部", a == b and set(a) == set(reg.names()),
          str(a))

    # ---------- R8 add ----------
    layer = widget_layer.WidgetLayer(st)
    settle(app, 300)
    got = []
    layer.widgetsChanged.connect(lambda: got.append("changed"))

    before = len(st.widgets)
    e1 = layer.add("notes")
    settle(app, 200)
    check("R8 add 新增条目", e1 is not None and len(st.widgets) == before + 1,
          "len=%d" % len(st.widgets))
    check("R8b add 建了窗口", e1["id"] in layer.widgets, str(list(layer.widgets)))
    check("R8c add 落盘", STATE.exists() and e1["id"] in STATE.read_text(encoding="utf-8"))
    check("R12 add 发 widgetsChanged", got == ["changed"], str(got))

    # ---------- R9 单实例 ----------
    before = len(st.widgets)
    clock_entry = next(e for e in st.widgets if e["type"] == "clock")
    clock_entry["hidden"] = True
    st.save()
    e2 = layer.add("clock")
    settle(app, 200)
    check("R9 单实例重复 add 不新增条目", len(st.widgets) == before,
          "len=%d" % len(st.widgets))
    check("R9b 单实例 add 复用已有条目", e2 is clock_entry and e2["id"] == "clock")
    check("R9c 单实例 add 会把隐藏的显示出来", not e2.get("hidden"))

    # ---------- R10 多实例 ----------
    before = len(st.widgets)
    e3 = layer.add("notes")
    settle(app, 200)
    check("R10 多实例 add 会新增第二个", len(st.widgets) == before + 1
          and e3["id"] != e1["id"], "len=%d" % len(st.widgets))

    # ---------- R11 remove ----------
    rid = e3["id"]
    ok = layer.remove(rid)
    settle(app, 200)
    check("R11 remove 成功", ok is True)
    check("R11b remove 后条目消失",
          all(e["id"] != rid for e in st.widgets))
    check("R11c remove 后窗口消失", rid not in layer.widgets)
    check("R11d remove 落盘", rid not in STATE.read_text(encoding="utf-8"))

    # ---------- R13 兼容：老跨度逻辑不变 ----------
    cw, ch = grid_flow.cell_size(st)
    span = grid_flow.widget_span(st, {"type": "panel", "colspan": 3, "rowspan": 4})
    check("R13 老组件跨度逻辑不变", span == (3, 4))
    check("R13b cell 尺寸未被注册表改动", cw > 0 and ch > 0, "%dx%d" % (cw, ch))

    # ---------- add 未知类型 ----------
    before = len(st.widgets)
    check("R14 add 未知类型返回 None 且不新增",
          layer.add("nope") is None and len(st.widgets) == before)

    # 收尾：关掉所有组件窗口，避免残留
    for w in list(layer.widgets.values()):
        try:
            w.close()
        except Exception:
            pass
    if STATE.exists():
        STATE.unlink()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    try:
        main(app)
    finally:
        print("-" * 56)
        print("%d/%d checks, %d FAIL" % (len(CHECKS) - len(failures), len(CHECKS),
                                         len(failures)))
        if failures:
            print("FAILED:", ", ".join(failures))
    sys.exit(1 if failures else 0)
