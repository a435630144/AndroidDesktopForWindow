# -*- coding: utf-8 -*-
"""共享天气源（v10 A9，反馈 9）：一份缓存、一个后台线程、多个订阅者。

## 为什么需要它

v10 之前天气有**两份互不相干的实现**：

  - 「天气」组件（`widgets/weather/weather.py`）：真联网、真缓存、城市在
    `entry["settings"]["city"]`；
  - 「桌面面板」里那张天气卡（`widgets/panel/panel.py`）：`17°C 晴 北京 ·
    示例数据`——写死的假数据，连"示例"两个字都只有小字说明。

用户看到的是同一块桌面上两个天气框给了两个温度（反馈 9 原话"内部的天气与
天气组件冲突"）。真正的病根不是"画错了"，而是**两份数据源**：只要各画各的，
城市改一处另一处不动、刷新时间不同、断网时一张有一张没有。

所以这里把"取数"整体收上来：

    城市 / 联网开关  -> settings["weather_city"] / settings["weather_online"]（全局唯一）
    缓存 + 后台刷新  -> 本模块（一个实例，一个定时器，同一份 model）
    订阅             -> WeatherWidget、面板天气卡都只是"画这份 model"

订阅者不关心谁去取、什么时候取；`changed` 一发，全部重画。这样"两个组件显示
不同温度"在结构上就不可能发生。

主线程零阻塞：`refresh()` 只起线程就返回，结果经 Qt 信号排队回主线程。
"""
from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from . import weather_api as wa

# 定时刷新周期（30 分钟）与首刷延迟（先把界面画出来）
REFRESH_PERIOD_MS = 30 * 60 * 1000
FIRST_DELAY_MS = 1500


class WeatherSource(QObject):
    """共享天气数据源（进程内单例，见 `shared()`）。"""

    changed = Signal()
    # 跨线程回主线程的搬运通道：worker 线程只 emit，不在里面碰控件/回调
    _fetched = Signal(str, object)

    def __init__(self, storage):
        super().__init__()
        self._fetched.connect(self._on_fetched)
        self.storage = storage
        self._model: Optional[wa.WeatherModel] = None
        self._state = "empty"       # live / cached / empty
        self._busy = False
        self._subs: List[Callable] = []
        cached = wa.cache_to_model(wa.load_cache())
        if cached is not None:
            self._model, self._state = cached, "cached"
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_PERIOD_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        QTimer.singleShot(FIRST_DELAY_MS, self.refresh)

    # ---------- 配置（全局唯一） ----------
    def city(self) -> str:
        return str(_setting(self.storage, "weather_city", "") or "").strip()

    def online(self) -> bool:
        v = _setting(self.storage, "weather_online", True)
        return True if v is None else bool(v)

    def set_city(self, city: str, refresh: bool = True) -> str:
        city = str(city or "").strip()
        self.storage.set_setting("weather_city", city)
        self.storage.save()
        if refresh:
            self.refresh(force=True)
        return city

    def set_online(self, on: bool, refresh: bool = True) -> bool:
        self.storage.set_setting("weather_online", bool(on))
        self.storage.save()
        if refresh:
            self.refresh(force=True)
        return bool(on)

    # ---------- 数据 ----------
    def model(self) -> Optional[wa.WeatherModel]:
        return self._model

    def state(self) -> str:
        return self._state

    def subscribe(self, fn: Callable) -> None:
        if fn not in self._subs:
            self._subs.append(fn)

    def unsubscribe(self, fn: Callable) -> None:
        try:
            self._subs.remove(fn)
        except ValueError:
            pass

    # ---------- 取数 ----------
    def refresh(self, force: bool = False):
        """发起一次刷新（立即返回，UI 不等网络）；`force` 忽略 busy 防抖。"""
        if self._busy and not force:
            return
        self._busy = True
        city, online = self.city(), self.online()
        import threading
        threading.Thread(target=self._work, args=(city, online),
                         daemon=True).start()

    def _work(self, city: str, online: bool):
        try:
            state, model = wa.fetch_sync(city, online)
        except Exception:      # noqa: BLE001 —— 后台线程绝不能把异常抛给 Qt
            state, model = "cached", None
        self._fetched.emit(state, model)

    def _on_fetched(self, state: str, model):
        # 线程安全：`changed` 由 Qt 排队（连接方在主线程）——这里只改数据，
        # 再发信号。WeatherSource 自身在主线程被创建，emit 会走队列连接。
        self._busy = False
        if model is not None:
            self._model, self._state = model, state
        else:
            self._state = "cached" if self._model is not None else "empty"
        self.changed.emit()
        for fn in list(self._subs):
            try:
                fn()
            except Exception:      # noqa: BLE001 —— 一个订阅者坏了不该拖垮别人
                pass


def _setting(storage, key, default):
    try:
        v = storage.get_setting(key)
    except Exception:      # noqa: BLE001
        return default
    return default if v is None else v


_SHARED: Optional[WeatherSource] = None


def shared(storage) -> WeatherSource:
    """进程内唯一实例（storage 是进程级单例，换 storage 即测试场景）。"""
    global _SHARED
    if _SHARED is None or getattr(_SHARED, "storage", None) is not storage:
        _SHARED = WeatherSource(storage)
    return _SHARED


def reset_shared() -> None:
    """测试用：丢弃单例（下一个 `shared()` 重新建）。"""
    global _SHARED
    if _SHARED is not None:
        try:
            _SHARED._timer.stop()
            _SHARED.deleteLater()
        except RuntimeError:
            pass
    _SHARED = None
