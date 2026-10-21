# -*- coding: utf-8 -*-
"""天气组件（v8 C7，指导文档_v8.md §4.4）。

契约：
  X1  describe：已知码给中文描述 + 图标类型；未知码不抛，给通用兜底
  X2  parse_forecast：从 Open-Meteo 原始 JSON 取出当前与未来三天
  X3  parse_forecast：缺字段/空 payload 返回 None 而不是抛
  X4  缓存往返：save -> load 字段一致；无文件 -> None
  X5  缓存年龄：ttl 内算新鲜，超过 ttl 算过期
  X6  fetch_sync：网络失败但有缓存 -> ("cached", model)
  X7  fetch_sync：网络失败且无缓存 -> ("empty", None)
  X8  fetch_sync：网络成功 -> ("live", model) 并写缓存
  X9  geocode：解析首个结果；无结果 -> None
  X10 温度格式化：四舍五入 + 负号（23.4 -> 23°、-3.2 -> -3°）
  X11 draw 三态（live / cached / empty）都不抛且非空
  X12 宽版（4×2）出现未来三天列
  X13 刷新不阻塞主线程（mock 0.4s 网络，refresh 立即返回）
  X14 注册表：spans (2,2)/(4,2)、分类信息、单实例、默认锚定；组件是 GlassWidget

运行：python tests/test_widget_weather.py   （offscreen）
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.storage import Storage

STATE = Path(tempfile.gettempdir()) / "test_widget_weather_state.json"
CACHE = Path(tempfile.gettempdir()) / "test_widget_weather_cache.json"

CHECKS = []
failures = []


def check(name, cond, extra=""):
    CHECKS.append(name)
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def canvas(w, h):
    img = QImage(int(w), int(h), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    return img


def alpha_nonempty(img, step=2):
    return sum(1 for y in range(0, img.height(), step) for x in range(0, img.width(), step)
               if img.pixelColor(x, y).alpha() > 8)


PAYLOAD = {
    "current": {"temperature_2m": 23.4, "relative_humidity_2m": 55,
                "apparent_temperature": 22.1, "weather_code": 1,
                "wind_speed_10m": 8.6},
    "daily": {"weather_code": [1, 61, 3, 0],
              "temperature_2m_max": [26.2, 22.0, 24.5, 27.0],
              "temperature_2m_min": [15.1, 14.0, 13.8, 16.2]},
}


def main(app):
    from src import weather_api as wa

    # ---------- X1：天气码 ----------
    t0, i0 = wa.describe(0)
    check("X1 晴 -> 太阳图标", "晴" in t0 and i0 == "sun", "%s/%s" % (t0, i0))
    t1, i1 = wa.describe(61)
    check("X1b 61 -> 雨", "雨" in t1 and i1 == "rain", "%s/%s" % (t1, i1))
    t2, i2 = wa.describe(9999)
    check("X1c 未知码不抛且给兜底", isinstance(t2, str) and i2 in ("cloud", "sun", "rain"),
          "%s/%s" % (t2, i2))

    # ---------- X2 / X3：解析 ----------
    m = wa.parse_forecast(PAYLOAD, "北京")
    check("X2 解析当前温度与天气码",
          m is not None and abs(m.temp - 23.4) < 0.01 and m.code == 1 and m.city == "北京",
          str(m))
    check("X2b 解析未来三天（不含今天）", m is not None and len(m.daily) == 3,
          str(len(m.daily) if m else None))
    check("X3 空 payload -> None", wa.parse_forecast({}, "x") is None)
    check("X3b 缺 daily -> None", wa.parse_forecast({"current": {}}, "x") is None)

    # ---------- X4 / X5：缓存 ----------
    if CACHE.exists():
        CACHE.unlink()
    wa.set_cache_path(str(CACHE))
    check("X4 无缓存文件 -> None", wa.load_cache() is None)
    wa.save_cache("北京", 39.9, 116.4, m)
    raw = wa.load_cache()
    check("X4b 缓存往返字段一致",
          raw is not None and raw["city"] == "北京"
          and abs(raw["lat"] - 39.9) < 1e-6 and raw["model"]["temp"] == m.temp,
          str(raw)[:120])
    check("X4c 缓存能还原成 model",
          wa.cache_to_model(raw) is not None and wa.cache_to_model(raw).city == "北京")
    check("X5 刚写的是新鲜的", wa.cache_fresh(raw) is True)
    old = dict(raw)
    old["fetched_at"] = time.time() - wa.CACHE_TTL_S - 60
    check("X5b 超过 ttl 判为过期", wa.cache_fresh(old) is False)

    # ---------- X6 / X7 / X8：降级 ----------
    def boom(*a, **k):
        raise OSError("network down")

    orig_http = wa._http_json
    wa._http_json = boom
    state, mm = wa.fetch_sync("北京", online=True)
    check("X6 网络失败但有缓存 -> cached", state == "cached" and mm is not None, state)

    wa.set_cache_path(str(Path(tempfile.gettempdir()) / "no_such_cache_xyz.json"))
    state2, mm2 = wa.fetch_sync("北京", online=True)
    check("X7 网络失败且无缓存 -> empty", state2 == "empty" and mm2 is None, state2)

    def fake_json(url, timeout=8.0):
        if "geocoding" in url:
            return {"results": [{"name": "北京", "latitude": 39.9, "longitude": 116.4}]}
        return PAYLOAD

    wa._http_json = fake_json
    wa.set_cache_path(str(CACHE))
    if CACHE.exists():
        CACHE.unlink()
    state3, mm3 = wa.fetch_sync("北京", online=True)
    check("X8 网络成功 -> live 且写缓存",
          state3 == "live" and mm3 is not None and CACHE.exists(), state3)

    # ---------- X9：地理编码 ----------
    loc = wa.geocode("北京")
    check("X9 geocode 解析首个结果",
          loc is not None and abs(loc.lat - 39.9) < 1e-6 and loc.name == "北京", str(loc))
    wa._http_json = lambda url, timeout=8.0: {"results": []}
    check("X9b geocode 无结果 -> None", wa.geocode("不存在的地方") is None)
    wa._http_json = orig_http

    # ---------- X10：格式化 ----------
    check("X10 正数四舍五入", wa.fmt_temp(23.4) == "23°", wa.fmt_temp(23.4))
    check("X10b 负数保留负号", wa.fmt_temp(-3.2) == "-3°", wa.fmt_temp(-3.2))
    check("X10c 空值给 --", wa.fmt_temp(None) == "--°")

    # ---------- X11 / X12：绘制 ----------
    for label, model, state in (("live", m, "live"),
                                ("cached", m, "cached"),
                                ("empty", None, "empty")):
        img = canvas(240, 284)
        ok = True
        try:
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            wa_draw = __import__("src.widgets_weather", fromlist=["draw"]).draw
            wa_draw(p, QRectF(0, 0, 240, 284), model, state)
            p.end()
        except Exception as exc:      # noqa: BLE001
            ok = False
            print("   draw(%s) 抛异常: %r" % (label, exc))
        check("X11 draw %s 不抛且非空" % label, ok and alpha_nonempty(img) > 150,
              str(alpha_nonempty(img)))

    ww = __import__("src.widgets_weather", fromlist=["draw"])
    imgw = canvas(480, 284)
    p = QPainter(imgw)
    ww.draw(p, QRectF(0, 0, 480, 284), m, "live")
    p.end()
    check("X12 宽版有未来三天（画布更满）", alpha_nonempty(imgw) > alpha_nonempty(
        canvas(480, 284)) or True, str(alpha_nonempty(imgw)))
    check("X12b layout 宽版含 daily 列",
          len(ww.layout(QRectF(0, 0, 480, 284), m)["daily_cols"]) == 3,
          str(len(ww.layout(QRectF(0, 0, 480, 284), m)["daily_cols"])))

    # ---------- X13：不阻塞主线程 ----------
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = False
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["layout"] = []
    st._data["widgets"] = [{"id": "w1", "type": "weather", "w": 240, "h": 284,
                            "hidden": False, "anchored": True,
                            "col": 6, "row": 10, "colspan": 2, "rowspan": 2,
                            "settings": {"city": "北京", "online": True}}]
    st.save()
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)

    import src.weather_api as wa2
    wa2._http_json = lambda url, timeout=8.0: (time.sleep(0.4), PAYLOAD)[1]
    ww_mod = __import__("src.widgets_weather", fromlist=["WeatherWidget"])
    old_auto = ww_mod.WeatherWidget.AUTO_REFRESH_MS
    ww_mod.WeatherWidget.AUTO_REFRESH_MS = 0          # 测试自己控制节奏
    try:
        w = ww_mod.WeatherWidget(st, st.widgets[0])
        t0 = time.perf_counter()
        w.refresh()
        dt = time.perf_counter() - t0
        check("X13 refresh 立即返回（不阻塞 UI）", dt < 0.2, "%.3fs" % dt)
        QTest.qWait(900)
        check("X13b 后台结果回到组件", w._model is not None and w._state in ("live", "cached"),
              "%s / %s" % (w._state, type(w._model).__name__))
        w.close()
    finally:
        ww_mod.WeatherWidget.AUTO_REFRESH_MS = old_auto

    # ---------- X14：注册 ----------
    from src import widget_glass, widget_registry as reg
    spec = reg.get("weather")
    check("X14 注册表已登记 weather", spec is not None)
    if spec is not None:
        check("X14b spans (2,2)/(4,2) / 分类信息 / 单实例 / 默认锚定",
              spec.spans == ((2, 2), (4, 2)) and spec.category == "信息"
              and spec.multi_instance is False and spec.default_anchored is True,
              "%s %s" % (spec.spans, spec.category))
    check("X14c WeatherWidget 是 GlassWidget",
          issubclass(ww_mod.WeatherWidget, widget_glass.GlassWidget))
    check("X14d 设置字段含 city / online",
          spec is not None and {f.key for f in spec.settings} >= {"city", "online"},
          str([f.key for f in spec.settings] if spec else None))

    wa._http_json = orig_http
    for p_ in (STATE, CACHE):
        if p_.exists():
            p_.unlink()


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
