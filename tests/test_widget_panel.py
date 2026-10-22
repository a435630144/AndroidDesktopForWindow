# -*- coding: utf-8 -*-
"""桌面面板重构契约（v10 A9，反馈 9）。

用户原话：
    桌面面板组件的编辑配色等功能无效，另外内部的天气与天气组件冲突，
    重构一下组件的功能。

两个根因：
  1. 面板是唯一**没接入样式层**的组件（继承 FloatingWidget、QSS 写死 RGB），
     所以「组件设置 ▸ 外观」改了颜色它不变；
  2. 面板里的天气卡是写死的 `17°C 晴 · 北京 · 示例数据`，与桌面上的真天气
     组件各画各的 —— 同一块桌面两个温度。

判据：
  R1 面板是 GlassWidget（走玻璃底 + style）
  R2 文字色 / 强调色设置真的落到子控件 QSS（不再写死 RGB）
  R3 背景色设置进入 paint 路径（style.bg 非空）
  R4 面板天气卡与天气组件**共用同一个共享源实例**
  R5 改城市只改一处：全局 settings["weather_city"]，两处同步
  R6 面板模块开关：关掉就隐藏，开回来恢复（幂等）
  R7 面板源码里不再有示例温度字面量（17°C）
  R8 天气源只有一个后台定时器（多个界面不会各拉一次网络）

运行：python tests/test_widget_panel.py   （offscreen；判据看退出码）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=120):
    from PySide6.QtCore import QEventLoop
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make(storage_path, widgets):
    from src import grid_flow
    from src.storage import Storage
    st = Storage(path=str(storage_path))
    st._data["settings"].update({"hide_native_icons": False,
                                 "auto_clone_desktop": False,
                                 "takeover_desktop": True,
                                 "show_widgets": True,
                                 "layout_mode": "grid"})
    st._data["layout"] = []
    st._data["widgets"] = [dict(w) for w in widgets]
    st.save()
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)
    return st


def main():
    app = QApplication.instance() or QApplication([])
    from src import widget_style
    from src.widget_glass import GlassWidget
    from src.widget_layer import WidgetLayer
    from src.widgets.weather import source as wsource

    tmp = Path(tempfile.mkdtemp(prefix="panel_"))
    st = make(tmp / "state.json", [
        {"id": "p1", "type": "panel", "hidden": False, "anchored": True,
         "col": 0, "row": 0, "colspan": 3, "rowspan": 4},
        {"id": "w1", "type": "weather", "hidden": False, "anchored": True,
         "col": 5, "row": 0, "colspan": 2, "rowspan": 2,
         "settings": {"city": "北京", "online": False}},
    ])
    wsource.reset_shared()
    layer = WidgetLayer(st)
    settle(app)
    panel = layer.widgets.get("p1")
    weather = layer.widgets.get("w1")

    check("R1 面板已创建", panel is not None and weather is not None)
    if panel is None or weather is None:
        print("FATAL: 组件没建起来")
        return 1

    check("R1b 面板是 GlassWidget（走样式层）", isinstance(panel, GlassWidget),
          type(panel).__mro__[1].__name__)

    # ---------- R2：配色真的生效 ----------
    panel.entry["settings"] = {"text_color": "#FF3366", "accent_color": "#00FF88",
                              "bg_color": "#101820", "bg_alpha": 0.6}
    panel._style_cache = None
    panel.on_settings_changed()
    st_ = widget_style.of(panel.entry)
    check("R2 style 读到文字色", st_.text.name().upper() == "#FF3366",
          st_.text.name())
    qss = panel.ed_search.styleSheet()
    check("R2 搜索框 QSS 用用户文字色（不再写死）",
          "255,51,102" in qss, qss[:80])
    check("R2b 面板背景色进入 style", st_.custom_bg and st_.bg is not None,
          "%s" % (st_.bg,))
    check("R2c 强调色进了 QSS（焦点边框）", "0,255,136" in qss, qss[-60:])

    # 重绘一次不抛（真实绘制路径）
    try:
        panel.render_to = None
        pm = panel.grab()
        ok = not pm.isNull() and pm.width() > 0
    except Exception as exc:      # noqa: BLE001
        ok = False
        check("R2d 面板绘制不抛", False, repr(exc))
    if "ok" in dir() or ok:
        check("R2d 面板绘制非空", ok)

    # ---------- R4：共用同一个共享源 ----------
    check("R4 面板天气卡与天气组件同一 source",
          panel.weather_card._src is weather._src,
          "%s vs %s" % (id(panel.weather_card._src), id(weather._src)))
    check("R4b 共享源就是模块单例",
          wsource.shared(st) is weather._src)

    # ---------- R5：城市只配一处 ----------
    weather.entry["settings"] = {"city": "杭州", "online": False}
    weather.on_settings_changed()
    settle(app, 80)
    check("R5 城市写进全局设置", st.get_setting("weather_city") == "杭州",
          str(st.get_setting("weather_city")))
    check("R5b 面板天气卡看到同一城市",
          panel.weather_card._src.city() == "杭州",
          panel.weather_card._src.city())
    check("R5c 联网开关也全局唯一", st.get_setting("weather_online") is False,
          str(st.get_setting("weather_online")))

    # ---------- R6：模块开关 ----------
    panel.entry["settings"] = dict(panel.entry.get("settings") or {},
                                   show_weather=False, show_disk=False)
    panel.on_settings_changed()
    check("R6 关掉天气卡 -> 隐藏", panel.weather_card.isHidden())
    check("R6b 关掉磁盘卡 -> 隐藏", panel.disk_card.isHidden())
    check("R6c 其他模块仍在", not panel.recent_card.isHidden())
    panel.entry["settings"] = dict(panel.entry.get("settings") or {},
                                   show_weather=True, show_disk=True)
    panel.on_settings_changed()
    check("R6d 开回来 -> 显示", not panel.weather_card.isHidden()
          and not panel.disk_card.isHidden())

    # ---------- R7：示例数据已彻底移除 ----------
    src = Path("src/widgets/panel/panel.py").read_text(encoding="utf-8")
    check("R7 面板源码无示例温度字面量",
          "17°C" not in src and "示例数据" not in src)
    check("R7b 面板不再继承 FloatingWidget（只留 GlassWidget）",
          "(FloatingWidget)" not in src and "(GlassWidget)" in src)

    # ---------- R8：只有一个定时器 ----------
    other = wsource.shared(st)
    check("R8 多次 shared() 同一实例（单定时器）",
          other is weather._src and other._timer.isActive(),
          "active=%s" % other._timer.isActive())

    for w in list(layer.widgets.values()):
        w.close()
    wsource.reset_shared()
    print("")
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
    else:
        print("ALL widget_panel PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
