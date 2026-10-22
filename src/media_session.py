# -*- coding: utf-8 -*-
"""本机媒体会话（v10 C2，反馈 9：音乐控制器组件）。

**定位**：控制**本机正在放的音乐**，不是播放器。任何响应用户媒体键的播放器
（网易云 / QQ音乐 / Spotify / Edge / 系统「媒体播放器」）都吃同一套 VK_MEDIA_*
按键，所以"控制"这一半不依赖任何专有接口。

三个层次（对齐组件规格 §4.2）：

    MediaInfo              一次快照（曲名/艺人/进度/播放态/是否演示态）
    MediaSessionSource     数据源协议：snapshot() + 三个控制动作
    DemoSource             无元数据时的降级档：曲目/进度自己走，按键仍发真键

## 为什么本轮没有真 SMTC 读取（重要，别当 bug 查）

规格选型是 B：用 ctypes 自己投影 WinRT 的
`GlobalSystemMediaTransportControlsSessionManager`（零依赖）。本轮实测到：

* `RoGetActivationFactory` + `IInspectable` IID 可以成功拿到工厂；
* 用 `IInspectable::GetIids` 能问出真正的 IID
  `{2050C4EE-11A0-57DE-AED7-C97C70338245}`（省掉了哈希猜 IID 这一步）；
* 用它 QI 后调 slot 6 返回 `S_OK` 且得到一个非空对象，
  **但该对象不是可用的 `IAsyncOperation`**：按 `IAsyncOperation` 布局读
  slot 6（get_Status）直接 AV 崩进程，`GetRuntimeClassName` 返回
  `E_ILLEGAL_METHOD_CALL`。

结论：IID 拿到了，**接口→槽位图仍与文档不符**，而 WinRT 的 vtable 调用一旦
槽位错就是 access violation（进程级崩溃，不是异常）。把未验证的投影装进产品
＝ 每次启动都可能崩，代价远大于"暂时没有曲名"。所以：

* **控制**已完整可用（媒体键，真机有效）；
* **读取**走降级档：`create_source()` 返回 `DemoSource`，组件角标写
  「未检测到播放器信息」，曲目/进度由组件自己走；
* 接线点已经收成一个函数：将来拿到验证过的槽位图，只需新增一个
  `SmtcSource(MediaSessionSource)` 并让 `create_source()` 先试它、失败回落
  `DemoSource`——组件与测试一行都不用改。
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import List, Tuple

# ---------------------------------------------------------------- 媒体键

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3
KEYEVENTF_KEYUP = 0x0002

_user32 = None


def _u32():
    """延迟取 user32（非 Windows / 测试环境 import 本模块时不该炸）。"""
    global _user32
    if _user32 is None:
        _user32 = ctypes.WinDLL("user32", use_last_error=True)
    return _user32


def send_media_key(vk: int) -> bool:
    """发一次媒体键（按下+抬起）。任何响应系统媒体键的播放器都会收到。

    失败返回 False（非 Windows、API 被拦截）——调用方把它当"没控制到"，
    不要炸：组件角度这只是"按了个没反应的按钮"。
    """
    try:
        u = _u32()
        u.keybd_event(int(vk), 0, 0, 0)
        u.keybd_event(int(vk), 0, KEYEVENTF_KEYUP, 0)
        return True
    except Exception:      # noqa: BLE001 —— 控制失败不许拖垮组件
        return False


# ---------------------------------------------------------------- 快照

@dataclass(frozen=True)
class MediaInfo:
    """一次媒体快照。`duration <= 0` = 时长未知（进度条只画底轨、不显示剩余时间）。

    `demo=True` 表示**没有拿到真实会话**：曲目与进度都是组件自己演的，
    界面上要明示（角标 + 弱化的封面色），不能让用户以为这就是他的歌。
    """

    title: str = ""
    artist: str = ""
    album: str = ""
    playing: bool = False
    position: float = 0.0          # 秒
    duration: float = 0.0          # 秒；<= 0 表示未知
    app: str = ""                  # 来源应用（真会话才有）
    demo: bool = False

    def progress(self) -> float:
        """播放进度 0..1；时长未知返回 0。"""
        if self.duration <= 0:
            return 0.0
        return max(0.0, min(1.0, float(self.position) / float(self.duration)))

    def remains(self) -> str:
        """剩余时间 `-1:23`；时长未知返回空串。"""
        if self.duration <= 0:
            return ""
        left = max(0, int(round(self.duration - self.position)))
        return "-%d:%02d" % (left // 60, left % 60)


EMPTY = MediaInfo()


# ---------------------------------------------------------------- 数据源协议

class MediaSessionSource:
    """数据源协议。组件只认这四个方法，不知道背后是 SMTC 还是演示态。

    `snapshot()` 必须**不抛**（拿不到就返回 `EMPTY`）——它每 500ms 被调一次，
    一次异常就会把定时器链路打断。
    """

    name = "none"

    def snapshot(self) -> MediaInfo:      # pragma: no cover - 协议占位
        return EMPTY

    def play_pause(self) -> bool:         # pragma: no cover
        return send_media_key(VK_MEDIA_PLAY_PAUSE)

    def next_track(self) -> bool:         # pragma: no cover
        return send_media_key(VK_MEDIA_NEXT_TRACK)

    def prev_track(self) -> bool:         # pragma: no cover
        return send_media_key(VK_MEDIA_PREV_TRACK)


# ---------------------------------------------------------------- 降级档

DEMO_TRACKS: Tuple[Tuple[str, str], ...] = (
    ("演示曲目 · 一", "打开播放器后显示在这里"),
    ("演示曲目 · 二", "三个按键控制本机播放器"),
    ("演示曲目 · 三", "点一下播放键试试"),
)
DEMO_DURATION = 210.0          # 演示曲目时长（秒）


class DemoSource(MediaSessionSource):
    """没有元数据时的降级档（规格 §4.2 第 2 条）。

    两件事同时成立：
      1. 曲目/艺人/进度**由组件自己走**（按真实时间推进，暂停就停）；
      2. 三个按键**照发真媒体键**——用户按下去，正在放歌的播放器会真的响应
         （这是本档比"纯假按钮"更有用的地方）。
    """

    name = "demo"

    def __init__(self, index: int = 0):
        self._index = max(0, min(len(DEMO_TRACKS) - 1, int(index)))
        self._playing = True
        self._position = 0.0

    # ---------- 数据 ----------
    def snapshot(self) -> MediaInfo:
        title, artist = DEMO_TRACKS[self._index]
        return MediaInfo(title=title, artist=artist, album="",
                         playing=self._playing, position=self._position,
                         duration=DEMO_DURATION, app="", demo=True)

    # ---------- 时间推进（由组件的定时器驱动）----------
    def advance(self, seconds: float) -> None:
        if not self._playing or seconds <= 0:
            return
        self._position += float(seconds)
        if self._position >= DEMO_DURATION:
            self._position = 0.0
            self._index = (self._index + 1) % len(DEMO_TRACKS)

    # ---------- 控制 ----------
    def play_pause(self) -> bool:
        self._playing = not self._playing
        send_media_key(VK_MEDIA_PLAY_PAUSE)
        return True

    def next_track(self) -> bool:
        self._index = (self._index + 1) % len(DEMO_TRACKS)
        self._position = 0.0
        send_media_key(VK_MEDIA_NEXT_TRACK)
        return True

    def prev_track(self) -> bool:
        self._index = (self._index - 1) % len(DEMO_TRACKS)
        self._position = 0.0
        send_media_key(VK_MEDIA_PREV_TRACK)
        return True


# ---------------------------------------------------------------- 工厂

def create_source() -> MediaSessionSource:
    """选一个可用数据源。**当前恒为降级档**（见模块 docstring）。

    将来接通 SMTC 的写法（一行都不用改组件）：

        try:
            return SmtcSource()
        except Exception:
            return DemoSource()

    注意不要写成"try 一下看能不能读到会话"——投影本身如果槽位不对是 AV
    崩进程，try/except 拦不住，必须在**离进程**（探针脚本）里验证过再接。
    """
    return DemoSource()


def available_sources() -> List[str]:
    """当前可用的数据源名（给设置页/说明文案用）。"""
    return ["demo"]
