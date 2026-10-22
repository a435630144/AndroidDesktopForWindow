# -*- coding: utf-8 -*-
"""天气数据层（v8 C7，指导文档_v8.md §4.4 / §6）。

数据源：Open-Meteo（免 key、免账号）。只发两种请求：
    1. 地理编码：把用户填的城市名换成经纬度；
    2. 预报：用经纬度取当前天气 + 未来几天。
不发设备信息、不发账号、不写日志。

三级降级（这是本模块的核心契约）：
    联网成功          -> ("live",   model)
    联网失败 + 有缓存 -> ("cached", model)
    都没有            -> ("empty",  None)

可测性：所有网络出口收敛到 `_http_json()` 一个函数，测试直接 monkeypatch；
解析（`parse_forecast`）、缓存（`load/save/cache_to_model`）、格式化
（`fmt_temp`）都是纯函数，不需要网络也不需要 QWidget。
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ...paths import data_file

CACHE_TTL_S = 30 * 60          # 缓存新鲜期：30 分钟
HTTP_TIMEOUT = 8.0             # 单次请求超时（秒）——主线程永不等待它

GEO_URL = ("https://geocoding-api.open-meteo.com/v1/search"
           "?name={q}&count=1&language=zh&format=json")
FORECAST_URL = ("https://api.open-meteo.com/v1/forecast"
                "?latitude={lat}&longitude={lon}"
                "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
                "weather_code,wind_speed_10m"
                "&daily=weather_code,temperature_2m_max,temperature_2m_min"
                "&timezone=auto&forecast_days=4")

# WMO 天气码 -> (中文描述, 图标种类)
WEATHER_CODES: Dict[int, Tuple[str, str]] = {
    0: ("晴", "sun"),
    1: ("大部晴朗", "sun"),
    2: ("局部多云", "cloud"),
    3: ("阴", "cloud"),
    45: ("雾", "fog"), 48: ("雾凇", "fog"),
    51: ("毛毛雨", "rain"), 53: ("毛毛雨", "rain"), 55: ("毛毛雨", "rain"),
    56: ("冻毛毛雨", "rain"), 57: ("冻毛毛雨", "rain"),
    61: ("小雨", "rain"), 63: ("中雨", "rain"), 65: ("大雨", "rain"),
    66: ("冻雨", "rain"), 67: ("冻雨", "rain"),
    71: ("小雪", "snow"), 73: ("中雪", "snow"), 75: ("大雪", "snow"),
    77: ("米雪", "snow"),
    80: ("阵雨", "rain"), 81: ("强阵雨", "rain"), 82: ("暴阵雨", "rain"),
    85: ("阵雪", "snow"), 86: ("强阵雪", "snow"),
    95: ("雷阵雨", "thunder"), 96: ("雷暴伴冰雹", "thunder"),
    99: ("强雷暴伴冰雹", "thunder"),
}


def describe(code) -> Tuple[str, str]:
    """天气码 -> (描述, 图标)。未知码给"未知" + 云（绝不抛）。"""
    try:
        return WEATHER_CODES.get(int(code), ("未知", "cloud"))
    except (TypeError, ValueError):
        return ("未知", "cloud")


@dataclass(frozen=True)
class Location:
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Daily:
    code: int
    tmax: float
    tmin: float


@dataclass(frozen=True)
class WeatherModel:
    city: str
    temp: float
    feels: float
    humidity: int
    wind: float
    code: int
    daily: Tuple[Daily, ...] = ()
    fetched_at: float = 0.0

    @property
    def text(self) -> str:
        return describe(self.code)[0]

    @property
    def icon(self) -> str:
        return describe(self.code)[1]


# ---------------------------------------------------------------- 网络出口

def _http_json(url: str, timeout: float = HTTP_TIMEOUT) -> dict:
    """唯一的网络出口（测试 monkeypatch 这里，不碰真实网络）。"""
    req = urllib.request.Request(url, headers={"User-Agent": "DesktopOrganizer/8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310
        return json.loads(resp.read().decode("utf-8", "replace"))


def geocode(name: str, timeout: float = HTTP_TIMEOUT) -> Optional[Location]:
    """城市名 -> 经纬度。查不到 / 网络失败返回 None。"""
    name = (name or "").strip()
    if not name:
        return None
    try:
        url = GEO_URL.format(q=urllib.parse.quote(name))
        data = _http_json(url, timeout)
        results = data.get("results") or []
        if not results:
            return None
        r0 = results[0]
        return Location(name=str(r0.get("name") or name),
                        lat=float(r0["latitude"]), lon=float(r0["longitude"]))
    except Exception:      # noqa: BLE001
        return None


def parse_forecast(payload, city: str) -> Optional[WeatherModel]:
    """Open-Meteo 预报 JSON -> WeatherModel；缺关键字段返回 None。"""
    if not isinstance(payload, dict):
        return None
    cur = payload.get("current")
    daily = payload.get("daily")
    if not isinstance(cur, dict) or not isinstance(daily, dict):
        return None
    temp = cur.get("temperature_2m")
    if temp is None:
        return None
    codes = daily.get("weather_code") or []
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    days: List[Daily] = []
    # 第 0 天是今天，右侧"未来三天"从第 1 天开始
    for i in range(1, min(len(codes), len(highs), len(lows), 4)):
        try:
            days.append(Daily(code=int(codes[i]), tmax=float(highs[i]),
                              tmin=float(lows[i])))
        except (TypeError, ValueError):
            continue
    try:
        return WeatherModel(
            city=str(city or ""),
            temp=float(temp),
            feels=float(cur.get("apparent_temperature", temp)),
            humidity=int(cur.get("relative_humidity_2m", 0) or 0),
            wind=float(cur.get("wind_speed_10m", 0.0) or 0.0),
            code=int(cur.get("weather_code", 0) or 0),
            daily=tuple(days),
            fetched_at=time.time(),
        )
    except (TypeError, ValueError):
        return None


def fetch(lat: float, lon: float, city: str,
          timeout: float = HTTP_TIMEOUT) -> Optional[WeatherModel]:
    """按经纬度拉预报；失败返回 None。"""
    try:
        url = FORECAST_URL.format(lat=lat, lon=lon)
        return parse_forecast(_http_json(url, timeout), city)
    except Exception:      # noqa: BLE001
        return None


# ---------------------------------------------------------------- 缓存

_cache_path: Optional[str] = None


def set_cache_path(path: Optional[str]) -> None:
    """测试用：换缓存文件位置（None = 回到默认）。"""
    global _cache_path
    _cache_path = path


def cache_path() -> str:
    return _cache_path or str(data_file("weather_cache.json"))


def _model_dict(m: WeatherModel) -> dict:
    return {"city": m.city, "temp": m.temp, "feels": m.feels,
            "humidity": m.humidity, "wind": m.wind, "code": m.code,
            "daily": [{"code": d.code, "tmax": d.tmax, "tmin": d.tmin}
                      for d in m.daily],
            "fetched_at": m.fetched_at}


def save_cache(city: str, lat: float, lon: float, model: WeatherModel) -> None:
    """写缓存（原子替换）；失败静默——缓存写不进去不该影响显示。"""
    if model is None:
        return
    raw = {"city": city, "lat": float(lat), "lon": float(lon),
           "fetched_at": float(model.fetched_at or time.time()),
           "model": _model_dict(model)}
    try:
        path = cache_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:      # noqa: BLE001
        pass


def load_cache() -> Optional[dict]:
    """读缓存；没有 / 损坏返回 None。"""
    try:
        path = cache_path()
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) and isinstance(raw.get("model"), dict) else None
    except Exception:      # noqa: BLE001
        return None


def cache_to_model(raw) -> Optional[WeatherModel]:
    """缓存原始字典 -> WeatherModel；脏数据返回 None。"""
    if not isinstance(raw, dict):
        return None
    md = raw.get("model")
    if not isinstance(md, dict) or md.get("temp") is None:
        return None
    days = []
    for d in md.get("daily") or []:
        try:
            days.append(Daily(code=int(d["code"]), tmax=float(d["tmax"]),
                              tmin=float(d["tmin"])))
        except (KeyError, TypeError, ValueError):
            continue
    try:
        return WeatherModel(city=str(md.get("city") or raw.get("city") or ""),
                            temp=float(md["temp"]), feels=float(md.get("feels", md["temp"])),
                            humidity=int(md.get("humidity", 0) or 0),
                            wind=float(md.get("wind", 0.0) or 0.0),
                            code=int(md.get("code", 0) or 0), daily=tuple(days),
                            fetched_at=float(md.get("fetched_at") or raw.get("fetched_at") or 0.0))
    except (KeyError, TypeError, ValueError):
        return None


def cache_fresh(raw) -> bool:
    """缓存是否在 TTL 内。"""
    try:
        ts = float((raw or {}).get("fetched_at") or 0.0)
    except (TypeError, ValueError):
        return False
    return ts > 0 and (time.time() - ts) <= CACHE_TTL_S


def age_text(ts: Optional[float]) -> str:
    """缓存年龄文案（"刚刚" / "N 分钟前" / "N 小时前" / "N 天前"）。"""
    if not ts:
        return "缓存"
    age = max(0.0, time.time() - float(ts))
    if age < 90:
        return "刚刚"
    if age < 3600:
        return "%d 分钟前" % int(age // 60)
    if age < 86400:
        return "%d 小时前" % int(age // 3600)
    return "%d 天前" % int(age // 86400)


# ---------------------------------------------------------------- 编排

def fetch_sync(city: str, online: bool = True) -> Tuple[str, Optional[WeatherModel]]:
    """同步取数并做三级降级（调用方必须放到后台线程里跑）。

    返回 (state, model)：state ∈ {"live", "cached", "empty"}。
    """
    city = (city or "").strip()
    if online and city:
        loc = geocode(city)
        if loc is not None:
            model = fetch(loc.lat, loc.lon, loc.name or city)
            if model is not None:
                save_cache(loc.name or city, loc.lat, loc.lon, model)
                return "live", model
    cached = cache_to_model(load_cache())
    if cached is not None:
        return "cached", cached
    return "empty", None


def fmt_temp(value) -> str:
    """温度文案：四舍五入、保留负号、空值给 `--°`。"""
    if value is None:
        return "--°"
    try:
        return "%d°" % int(round(float(value)))
    except (TypeError, ValueError):
        return "--°"
