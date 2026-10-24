# -*- coding: utf-8 -*-
"""本机媒体会话（v10 C2 起，v11 重做「读取」这一半）。

**定位**：控制**本机正在放的音乐**，不是播放器。任何响应用户媒体键的播放器
（网易云 / QQ音乐 / Spotify / Edge / 系统「媒体播放器」）都吃同一套 VK_MEDIA_*
按键，所以"控制"这一半不依赖任何专有接口。

三个层次：

    MediaInfo              一次快照（曲名/艺人/进度/播放态/是否演示态）
    MediaSessionSource     数据源协议：snapshot() + 控制动作 + seek()
    DemoSource             什么都没有时的降级档

## v11 为什么用 PowerShell 侧车读 SMTC（别再试 ctypes 投影）

Windows 唯一公开的"当前在放什么"接口是 SMTC
（`Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager`）。
v10 试过用 ctypes 手工投影 WinRT：`RoGetActivationFactory` 能拿到工厂、
QI 也成功，但**槽位图与文档不符**，按 `IAsyncOperation` 读 slot 6 直接
access violation（进程级崩溃，try/except 拦不住）。WinRT 的 vtable 一旦错位
就是 AV，不是异常——这条路在没有 IDL 校验的环境里不能上产品。

v11 改成**PowerShell 侧车**：PowerShell 5.1 能直接用
`[Windows.Media.Control.X, Windows.Media.Control, ContentType=WindowsRuntime]`
+ `System.Runtime.WindowsRuntime` 的 `AsTask` 等待异步，全程托管代码，
槽位图由 .NET 投影保证正确。代价是一个常驻子进程（约 60–80MB）——所以：

* **只读不写**：控制仍走媒体键（零依赖、零延迟）；侧车只回传快照 + 执行 seek；
* **懒启动**：组件创建后才起，组件销毁/关闭时 `stop()` 杀掉；
* **随时可退化**：侧车起不来（企业策略禁 PS / 没有 WinRT）→ 窗口标题档
  → 演示档，组件永远有东西可画；
* **编码用 base64**：PS 5.1 的重定向 stdout 走控制台代码页，中文会糊；
  侧车每行输出 `B64:<base64(utf8 json)>`，Python 解码后再 `json.loads`。

## 窗口标题档（`TitleSource`）

很多播放器（含部分版本的网易云）不发布 SMTC。它们的窗口标题仍然是
`歌名 - 歌手`，所以还能拿到曲名——只是拿不到时长/进度，界面必须明示
「仅曲名」。这一档用 `EnumWindows` + `QueryFullProcessImageNameW` 认进程，
**只认白名单里的播放器**（浏览器标签页标题太杂，不收）。

## 封面（v11c）

SMTC 的 `MediaProperties.Thumbnail` 是 `IRandomAccessStreamReference`，但
PowerShell 5.1 **读不了它的结果**：`OpenReadAsync()` 回来的是裸
`__ComObject`，`.Size` 静默为 0，转 `IInputStream` 直接抛。绕法是
`RandomAccessStream.CopyAsync` 反射 + `InMemoryRandomAccessStream`（PS 能
投影这个*类*）→ `DataReader` 读字节，见 `src/media_cover.ps1`（内部有实测
记录）。侧车把图片写进 `%APPDATA%/PhoneDesktop/media_cover_<hash>.img`，
只回传路径 + 内容哈希；组件按哈希缓存 QPixmap，换歌时才重新读盘。
**播放器不发布缩略图时没有封面可抓**——这时退回音符占位，不是 bug。

"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, replace
from typing import List, Optional, Tuple

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

    `partial=True`（v11）表示"只拿到曲名，没有时长/进度"（窗口标题档）。
    此时进度条不画进度、seek 不可用——比画一条假的进度诚实。

    `stamp` 是快照抓取时刻（`time.monotonic()`）。真实会话每秒才回读一次，
    组件 500ms 一跳；`position_at()` 用它在两次回读之间插值，进度条才不会
    "一秒一格"地跳。
    """

    title: str = ""
    artist: str = ""
    album: str = ""
    playing: bool = False
    position: float = 0.0          # 秒
    duration: float = 0.0          # 秒；<= 0 表示未知
    app: str = ""                  # 来源应用（真会话才有）
    demo: bool = False
    partial: bool = False
    stamp: float = 0.0             # time.monotonic() 抓取时刻
    seekable: bool = False         # 能否拖动进度条
    # v11c：SMTC `MediaProperties.Thumbnail` 落到本地缓存的封面图路径。
    # 空串 = 播放器没发布缩略图（或当前是窗口标题档 / 演示态）。
    cover: str = ""
    cover_id: str = ""             # 封面内容哈希（换图才重绘 + 缓存键）

    def position_at(self, now: Optional[float] = None) -> float:
        """当前播放位置（带插值）。`now` 缺省/异常一律回原始 position。"""
        pos = max(0.0, float(self.position))
        if not self.playing or self.stamp <= 0 or not now:
            return pos
        try:
            delta = max(0.0, float(now) - float(self.stamp))
        except (TypeError, ValueError):
            return pos
        pos += delta
        if self.duration > 0:
            pos = min(pos, float(self.duration))
        return pos

    def progress(self, now: Optional[float] = None) -> float:
        """播放进度 0..1；时长未知返回 0。"""
        if self.duration <= 0:
            return 0.0
        return max(0.0, min(1.0, self.position_at(now) / float(self.duration)))

    def remains(self, now: Optional[float] = None) -> str:
        """剩余时间 `-1:23`；时长未知返回空串。"""
        if self.duration <= 0:
            return ""
        left = max(0, int(round(self.duration - self.position_at(now))))
        return "-%d:%02d" % (left // 60, left % 60)


EMPTY = MediaInfo()


def fmt_time(seconds: float) -> str:
    """秒 -> `m:ss`（进度条拖动时的读数；负数/非法 -> `0:00`）。"""
    try:
        s = max(0, int(round(float(seconds))))
    except (TypeError, ValueError):
        s = 0
    return "%d:%02d" % (s // 60, s % 60)


# ---------------------------------------------------------------- 数据源协议

class MediaSessionSource:
    """数据源协议。组件只认这几个方法，不知道背后是 SMTC / 标题 / 演示态。

    `snapshot()` 必须**不抛**（拿不到就返回 `EMPTY`）——它每 500ms 被调一次，
    一次异常就会把定时器链路打断。
    """

    name = "none"

    def start(self):                     # pragma: no cover - 协议占位
        """可选：建立连接（懒启动的侧车在这里 spawn）。不许阻塞 UI。"""

    def stop(self):                      # pragma: no cover
        """可选：释放资源（杀子进程 / 停止线程）。"""

    def advance(self, seconds: float):   # pragma: no cover
        """可选：让"自己走"的降级档推进时间。真实数据源是 no-op。"""

    def snapshot(self) -> MediaInfo:      # pragma: no cover - 协议占位
        return EMPTY

    def seek(self, seconds: float) -> bool:   # pragma: no cover
        return False

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
                         duration=DEMO_DURATION, app="", demo=True,
                         stamp=time.monotonic(), seekable=True)

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

    def seek(self, seconds: float) -> bool:
        try:
            self._position = max(0.0, min(DEMO_DURATION, float(seconds)))
        except (TypeError, ValueError):
            return False
        return True


# ---------------------------------------------------------------- SMTC 侧车

SIDECAR_NAME = "media_smtc.ps1"
CREATE_NO_WINDOW = 0x08000000

# 侧车回读间隔（毫秒）。组件自己是 500ms 一跳，进度靠 `position_at()` 插值，
# 所以侧车不需要跟得那么紧——1.2s 一次足够，省 CPU（WinRT 每次都要过一遍
# 属性异步读 + 三条会话查询）。
SIDECAR_INTERVAL_MS = 1200
# 封面缓存：侧车把播放器给的缩略图写成 `media_cover_<hash>.img`，
# 放在应用数据目录；只保留最近几张（换歌会持续产生新文件）。
COVER_PREFIX = "media_cover_"
COVER_KEEP = 6


def cover_dir() -> str:
    """封面缓存目录（`%APPDATA%/PhoneDesktop`）。路径不可用时返回空串。"""
    try:
        from .paths import ensure_app_dirs
        return str(ensure_app_dirs())
    except Exception:      # noqa: BLE001
        return ""


def prune_covers(keep: str = "", keep_count: int = COVER_KEEP) -> int:
    """删掉旧封面缓存（保留 `keep` 与最新的几张），返回删除数。

    只碰自己的 `media_cover_*.img`——数据目录里还有 state.json /
    用户导入的组件，绝不能按目录整体清理。
    """
    d = cover_dir()
    if not d:
        return 0
    try:
        names = [n for n in os.listdir(d)
                 if n.startswith(COVER_PREFIX) and n.endswith(".img")]
    except OSError:
        return 0
    keep_name = os.path.basename(keep) if keep else ""
    files = []
    for n in names:
        p = os.path.join(d, n)
        try:
            files.append((os.path.getmtime(p), p, n))
        except OSError:
            continue
    files.sort(reverse=True)
    removed = 0
    for _mtime, path, name in files[keep_count:]:
        if name == keep_name:
            continue
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass
    return removed


def _powershell_exe() -> str:
    """找 powershell.exe（PATH 优先，回退 System32 绝对路径）。"""
    for name in ("powershell.exe",):
        for base in (os.environ.get("SystemRoot", r"C:\Windows"),):
            cand = os.path.join(base, "System32", "WindowsPowerShell", "v1.0", name)
            if os.path.exists(cand):
                return cand
    return "powershell.exe"


def _sidecar_path() -> str:
    from .paths import resource_path
    for rel in ("src/" + SIDECAR_NAME, SIDECAR_NAME):
        try:
            p = resource_path(rel)
        except Exception:      # noqa: BLE001
            continue
        if p.exists():
            return str(p)
    return ""


class SmtcSource(MediaSessionSource):
    """SMTC 读取 + seek（PowerShell 侧车，见模块 docstring）。

    线程模型：`start()` spawn 子进程 + 起一条读线程；读线程只更新
    `self._info`（带锁），UI 线程每 500ms 调 `snapshot()` 取拷贝。
    **任何一步失败都只降级、不抛**——组件宁可不显示，也不能把桌面拖崩。
    """

    name = "smtc"

    def __init__(self, script: Optional[str] = None,
                 cmd_path: Optional[str] = None,
                 interval_ms: int = SIDECAR_INTERVAL_MS):
        self._script = script if script is not None else _sidecar_path()
        self._cmd_path = cmd_path
        self._interval_ms = max(300, int(interval_ms))
        self._proc = None
        self._thread = None
        self._lock = threading.Lock()
        self._info = EMPTY
        self._ok_at = 0.0
        self._seq = 0
        self._started = False
        self._dead = False

    # ---------- 生命周期 ----------
    def available(self) -> bool:
        """侧车脚本存在且系统是 Windows。"""
        return bool(self._script) and os.name == "nt"

    def start(self) -> bool:
        """启动侧车（幂等）。返回是否真的起了进程。"""
        if self._started or self._dead:
            return self._proc is not None
        self._started = True
        if not self.available():
            self._dead = True
            return False
        if self._cmd_path is None:
            try:
                from .paths import ensure_app_dirs, data_file
                ensure_app_dirs()
                self._cmd_path = str(data_file("media_cmd.json"))
            except Exception:      # noqa: BLE001
                self._cmd_path = os.path.join(
                    os.environ.get("TEMP") or ".", "pd_media_cmd.json")
        exe = _powershell_exe()
        args = [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", self._script, self._cmd_path, str(self._interval_ms)]
        cover = cover_dir()
        if cover:
            args.append(cover)
        try:
            kw = {}
            if os.name == "nt":
                kw["creationflags"] = CREATE_NO_WINDOW
            self._proc = subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=-1, **kw)
        except Exception:      # noqa: BLE001 —— 企业策略禁 PS 也不许崩
            self._proc = None
            self._dead = True
            return False
        self._thread = threading.Thread(
            target=self._reader, name="smtc-reader", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.terminate()
            except Exception:      # noqa: BLE001
                pass
            try:
                proc.wait(timeout=2)
            except Exception:      # noqa: BLE001
                try:
                    proc.kill()
                except Exception:      # noqa: BLE001
                    pass
        self._dead = True

    @property
    def alive(self) -> bool:
        return self._proc is not None

    # ---------- 读线程 ----------
    def _reader(self):
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for raw in proc.stdout:
                try:
                    info = parse_sidecar_line(raw)
                except Exception:      # noqa: BLE001 —— 单行坏数据跳过即可
                    continue
                if info is None:
                    continue
                with self._lock:
                    changed = info.cover != self._info.cover
                    self._info = info
                    self._ok_at = time.monotonic()
                if changed and info.cover:
                    # 换歌才扫目录（最多 6 个文件，开销可忽略）
                    prune_covers(info.cover)
        except Exception:      # noqa: BLE001
            pass
        # 进程退出：保留最后一次快照不再更新，`fresh()` 会判过期
        self._proc = None

    def fresh(self, max_age: float = 6.0) -> bool:
        """最近是否拿到过有效回读（侧车卡死时不让界面停在旧歌上）。"""
        with self._lock:
            at = self._ok_at
        return bool(at) and (time.monotonic() - at) <= max_age

    # ---------- 协议 ----------
    def snapshot(self) -> MediaInfo:
        with self._lock:
            info = self._info
        if not info.title:
            return EMPTY
        if not self.fresh():
            return EMPTY
        # 重新打时间戳：插值基准应是"这次读到的位置 + 本地当前时刻"，
        # 侧车给的时间戳在另一台时钟上，不能直接用。
        return replace(info, stamp=time.monotonic())

    def seek(self, seconds: float) -> bool:
        """把播放位置跳到 `seconds`（0 = 开头）。侧车不可用返回 False。"""
        try:
            value = max(0.0, float(seconds))
        except (TypeError, ValueError):
            return False
        if not self._cmd_path:
            return False
        self._seq += 1
        payload = {"seq": self._seq, "cmd": "seek", "value": round(value, 3)}
        try:
            tmp = self._cmd_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, self._cmd_path)
        except Exception:      # noqa: BLE001
            return False
        return True


def parse_sidecar_line(raw) -> Optional[MediaInfo]:
    """侧车一行 -> MediaInfo（不是我们的格式 / 无会话 -> None / EMPTY）。

    行格式：`B64:<base64(utf8 json)>`。base64 是为了绕开 PowerShell 5.1
    重定向 stdout 时的控制台代码页问题（中文曲名会变 `?`）。
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8", "replace")
        except Exception:      # noqa: BLE001
            return None
    line = str(raw or "").strip()
    if not line.startswith("B64:"):
        return None
    try:
        data = json.loads(base64.b64decode(line[4:]).decode("utf-8"))
    except Exception:      # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    if not data.get("has"):
        return EMPTY
    title = str(data.get("title") or "").strip()
    if not title:
        return EMPTY
    try:
        pos = float(data.get("pos") or 0.0)
    except (TypeError, ValueError):
        pos = 0.0
    try:
        dur = float(data.get("dur") or 0.0)
    except (TypeError, ValueError):
        dur = 0.0
    return MediaInfo(
        title=title,
        artist=str(data.get("artist") or "").strip(),
        album=str(data.get("album") or "").strip(),
        playing=bool(data.get("playing")),
        position=max(0.0, pos),
        duration=max(0.0, dur),
        app=str(data.get("app") or ""),
        demo=False,
        partial=False,
        stamp=time.monotonic(),
        seekable=dur > 0,
        cover=str(data.get("cover") or ""),
        cover_id=str(data.get("cover_id") or ""),
    )


# ---------------------------------------------------------------- 窗口标题档

# 只认这些进程（exe 小写）。浏览器不收：标签页标题是"页面标题 - 浏览器"，
# 把浏览器标签当歌名会天天误报。
PLAYER_EXES = {
    "cloudmusic.exe": "网易云音乐",
    "qqmusic.exe": "QQ音乐",
    "spotify.exe": "Spotify",
    "music.ui.exe": "媒体播放器",
    "musicplayer.exe": "媒体播放器",
    "foobar2000.exe": "foobar2000",
    "aimp.exe": "AIMP",
    "wmplayer.exe": "Windows Media Player",
    "potplayermini.exe": "PotPlayer",
    "potplayermini64.exe": "PotPlayer",
    "kugou.exe": "酷狗音乐",
    "kuwo.exe": "酷我音乐",
    "thunder.exe": "",     # 迅雷影音（旧版标题格式不一致，留着认进程不认曲）
}
PLAYER_EXES = {k: v for k, v in PLAYER_EXES.items() if v}

# 标题尾巴：播放器常把品牌名缀在后面，去掉后才是"歌名 - 歌手"
_TITLE_TAILS = (" - 网易云音乐", " - QQ音乐", " - 酷狗音乐", " - 酷我音乐",
                " - foobar2000", " - AIMP", " - Spotify", " | Spotify",
                " - PotPlayer", " - 媒体播放器", " - Windows Media Player")


def parse_title(title: str) -> Tuple[str, str]:
    """播放器窗口标题 -> (歌名, 歌手)。认不出歌手时第二个为空。

    支持三种常见分隔：`歌名 - 歌手` / `歌名 • 歌手` / `歌名 – 歌手`（en dash）。
    只有一段时整段当歌名（"打开播放器后显示在这里"这类占位由界面兜底）。
    """
    text = str(title or "").strip()
    for tail in _TITLE_TAILS:
        if text.endswith(tail):
            text = text[: -len(tail)].strip()
            break
    if not text:
        return ("", "")
    for sep in (" - ", " • ", " – ", " — "):
        if sep in text:
            song, artist = text.split(sep, 1)
            return (song.strip(), artist.strip())
    return (text, "")


def _window_exe(pid: int) -> str:
    """PID -> exe 文件名（小写）；拿不到返回空串。"""
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k32.OpenProcess(0x1000, False, int(pid))    # QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            size = ctypes.c_ulong(1024)
            buf = ctypes.create_unicode_buffer(1024)
            if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return ""
            return os.path.basename(buf.value).lower()
        finally:
            k32.CloseHandle(h)
    except Exception:      # noqa: BLE001
        return ""


def _enum_u32():
    """取带 argtypes 的 user32（64 位下不声明会截断 HWND 指针）。"""
    u = _u32()
    try:
        from ctypes import wintypes
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.IsWindowVisible.restype = wintypes.BOOL
        u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        u.GetWindowTextLengthW.restype = ctypes.c_int
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowTextW.restype = ctypes.c_int
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                               ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
        u.EnumWindows.restype = wintypes.BOOL
    except Exception:      # noqa: BLE001
        pass
    return u


def player_windows() -> List[Tuple[str, str, str]]:
    """枚举可见的播放器窗口 -> [(exe, 应用名, 标题)]，按标题非空过滤。"""
    out: List[Tuple[str, str, str]] = []
    if os.name != "nt":
        return out
    try:
        u = _enum_u32()
        EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p,
                                      ctypes.c_void_p)
        found = []

        def _cb(hwnd, _lp):
            try:
                if not u.IsWindowVisible(hwnd):
                    return True
                n = u.GetWindowTextLengthW(hwnd)
                if n <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(n + 2)
                u.GetWindowTextW(hwnd, buf, n + 2)
                title = buf.value.strip()
                if not title:
                    return True
                pid = ctypes.c_ulong(0)
                u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                exe = _window_exe(pid.value)
                if exe in PLAYER_EXES:
                    found.append((exe, PLAYER_EXES[exe], title))
            except Exception:      # noqa: BLE001
                pass
            return True

        cb = EnumProc(_cb)
        # LPARAM 是整数类型：传 None 会 TypeError（被外层 except 吞掉，
        # 结果是"永远认不出播放器"——v11 实测踩到过一次）。
        u.EnumWindows(cb, 0)
        out = found
    except Exception:      # noqa: BLE001
        return out
    return out


class TitleSource(MediaSessionSource):
    """窗口标题档：拿得到 `歌名 - 歌手`，拿不到时长/进度（`partial=True`）。

    这一档存在的理由：大量播放器（尤其旧版网易云）根本不发布 SMTC，
    只做 SMTC 会让用户看到"未检测到播放器信息"——而他明明在放歌。
    """

    name = "titles"

    def snapshot(self) -> MediaInfo:
        for exe, app, title in player_windows():
            song, artist = parse_title(title)
            if not song:
                continue
            return MediaInfo(title=song, artist=artist, album="", playing=True,
                             position=0.0, duration=0.0, app=app,
                             demo=False, partial=True, stamp=time.monotonic(),
                             seekable=False)
        return EMPTY


# ---------------------------------------------------------------- 组合源

class AutoSource(MediaSessionSource):
    """优先级：SMTC（真实进度 + 可 seek）> 窗口标题（只有曲名）> 演示档。

    三者都实现了 `MediaSessionSource`，组件只看到一个源——这就是 v10 模块
    docstring 里承诺的"接线点收成一个函数，组件一行不用改"。
    """

    name = "auto"

    def __init__(self, smtc: Optional[MediaSessionSource] = None,
                 titles: Optional[MediaSessionSource] = None,
                 demo: Optional[MediaSessionSource] = None):
        self.smtc = smtc if smtc is not None else SmtcSource()
        self.titles = titles if titles is not None else TitleSource()
        self.demo = demo if demo is not None else DemoSource()
        self._demo_hits = 0

    # ---------- 生命周期 ----------
    def start(self):
        try:
            self.smtc.start()
        except Exception:      # noqa: BLE001
            pass

    def stop(self):
        for src in (self.smtc,):
            try:
                src.stop()
            except Exception:      # noqa: BLE001
                pass

    # ---------- 数据 ----------
    def snapshot(self) -> MediaInfo:
        try:
            info = self.smtc.snapshot()
        except Exception:      # noqa: BLE001
            info = EMPTY
        if info.title:
            self._demo_hits = 0
            return info
        try:
            info = self.titles.snapshot()
        except Exception:      # noqa: BLE001
            info = EMPTY
        if info.title:
            self._demo_hits = 0
            return info
        self._demo_hits += 1
        return self.demo.snapshot()

    def advance(self, seconds: float):
        """只有演示档需要推进；真实档由播放器自己走。"""
        if self._demo_hits:
            try:
                self.demo.advance(seconds)
            except Exception:      # noqa: BLE001
                pass

    # ---------- 控制 ----------
    def seek(self, seconds: float) -> bool:
        try:
            info = self.smtc.snapshot()
        except Exception:      # noqa: BLE001
            info = EMPTY
        if info.title and info.seekable:
            return self.smtc.seek(seconds)
        # 演示档：直接挪自己的进度（标题档没有时长，拒绝）
        try:
            if self._demo_hits:
                return self.demo.seek(seconds)
        except Exception:      # noqa: BLE001
            pass
        return False

    def play_pause(self) -> bool:
        return self.demo.play_pause()      # 演示档翻状态 + 发真媒体键

    def next_track(self) -> bool:
        return self.demo.next_track()

    def prev_track(self) -> bool:
        return self.demo.prev_track()


# ---------------------------------------------------------------- 工厂

def create_source(storage=None) -> MediaSessionSource:
    """选一个可用数据源（组合源，内部按优先级退化）。

    `storage` 目前不用，留着给"以后让用户在设置里选数据源"扩展；
    传 None 也完全正常。
    """
    return AutoSource()


def available_sources() -> List[str]:
    """当前可用的数据源名（给设置页/说明文案用）。"""
    return ["smtc", "titles", "demo"]
