# -*- coding: utf-8 -*-
"""组件设置面板（v8 C8，指导文档_v8.md §5）。

契约：
  S1  没有声明设置项的组件（时钟）右键**不出现**「组件设置…」
  S2  有设置项的组件（天气）出现「组件设置…」
  S3  对话框按声明生成控件：text -> QLineEdit、bool -> QCheckBox、combo -> QComboBox
  S4  初值来自 entry["settings"]，没有则用 FieldSpec.default
  S5  应用后写 entry["settings"] 并落盘
  S6  bool 取消勾选能存成 False（不是"默认值覆盖"）
  S7  combo 选项与 FieldSpec.choices 一致，存的是原始值（int 不变成 str）
  S8  应用后组件 on_settings_changed() 被调用（天气据此立即重取）

运行：python tests/test_widget_settings.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit

from src import grid_flow
from src.storage import Storage

STATE = Path(tempfile.gettempdir()) / "test_widget_settings_state.json"

CHECKS = []
failures = []


def check(name, cond, extra=""):
    CHECKS.append(name)
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


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
    from src import widget_settings as ws
    from src import widget_registry as reg
    from src import widgets_clock, widgets_weather

    st = make_state([
        {"id": "clk", "type": "clock", "w": 240, "h": 284, "hidden": False,
         "anchored": False, "x": 100, "y": 100},
        {"id": "wx", "type": "weather", "w": 240, "h": 284, "hidden": False,
         "anchored": False, "x": 400, "y": 100,
         "settings": {"city": "上海"}},
        {"id": "cal", "type": "calendar", "w": 240, "h": 284, "hidden": False,
         "anchored": False, "x": 700, "y": 100, "settings": {}},
    ])
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)

    # ---------- S1 / S2：入口显隐 ----------
    clk = widgets_clock.ClockWidget(st, st.widgets[0])
    clk_menu = clk._build_context_menu()
    texts = [a.text() for a in clk_menu.actions()]
    check("S1 时钟没有「组件设置…」", all("组件设置" not in t for t in texts), str(texts))
    clk.close()

    wx = widgets_weather.WeatherWidget(st, st.widgets[1])
    wx_menu = wx._build_context_menu()
    wx_texts = [a.text() for a in wx_menu.actions()]
    check("S2 天气有「组件设置…」", any("组件设置" in t for t in wx_texts), str(wx_texts))

    # ---------- S3 / S4：生成控件与初值 ----------
    spec = reg.get("weather")
    dlg = ws.WidgetSettingsDialog(spec, st.widgets[1], st)
    edits = dlg.findChildren(QLineEdit)
    checks = dlg.findChildren(QCheckBox)
    check("S3 天气生成 1 个输入框 + 1 个开关", len(edits) == 1 and len(checks) == 1,
          "lineedit=%d check=%d" % (len(edits), len(checks)))
    check("S4 初值取 entry.settings.city", edits[0].text() == "上海",
          repr(edits[0].text()))
    check("S4b bool 缺省值来自 FieldSpec（True）", checks[0].isChecked() is True)
    dlg.close()

    # ---------- S5 / S6：应用落盘 ----------
    dlg2 = ws.WidgetSettingsDialog(spec, st.widgets[1], st)
    dlg2.findChildren(QLineEdit)[0].setText("广州")
    dlg2.findChildren(QCheckBox)[0].setChecked(False)
    dlg2.apply()
    check("S5 应用后 entry.settings.city 更新",
          st.widgets[1]["settings"]["city"] == "广州",
          repr(st.widgets[1]["settings"]))
    check("S6 bool 取消勾选存成 False",
          st.widgets[1]["settings"]["online"] is False,
          repr(st.widgets[1]["settings"].get("online")))
    check("S5b 已落盘", "广州" in STATE.read_text(encoding="utf-8"))
    dlg2.close()

    # ---------- S7：combo ----------
    cal_spec = reg.get("calendar")
    dlg3 = ws.WidgetSettingsDialog(cal_spec, st.widgets[2], st)
    combos = dlg3.findChildren(QComboBox)
    check("S7 日历生成 combo", len(combos) == 1, str(len(combos)))
    if combos:
        cb = combos[0]
        want = [label for _v, label in cal_spec.settings[0].choices]
        got = [cb.itemText(i) for i in range(cb.count())]
        check("S7b 选项与 FieldSpec.choices 一致", got == want, "%s vs %s" % (got, want))
        cb.setCurrentIndex(1)
        dlg3.apply()
        check("S7c 存原始值（int 不变成 str）",
              st.widgets[2]["settings"].get("week_start") == 6,
              repr(st.widgets[2]["settings"]))
    dlg3.close()

    # ---------- S8：回调 ----------
    calls = []
    wx.on_settings_changed = lambda: calls.append(1)
    wx._open_settings_for_test = True
    ws.apply_to_widget(wx, spec, {"city": "深圳", "online": True}, st)
    check("S8 apply_to_widget 触发 on_settings_changed", len(calls) == 1, str(calls))
    check("S8b apply_to_widget 写入 settings",
          st.widgets[1]["settings"]["city"] == "深圳",
          repr(st.widgets[1]["settings"]))
    wx.close()

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
