# -*- coding: utf-8 -*-
"""版本更新检测（v11 反馈 33）+ 项目/作者常量。

为什么单独一个模块：
  - **网络出口唯一**（与 `weather_api._http_json` 同一条纪律）：整个程序
    只有这里会去访问 GitHub，排查"为什么卡"时不用满仓库找 urllib；
  - **纯函数在前**：`parse_version` / `is_newer` / `release_of` 不碰网络、
    不碰 Qt，测试可以逐条打；
  - 真正的请求在后台线程（`UpdateChecker`），UI 只接信号——网络慢/超时
    绝不能把设置窗口冻住（用户点一下"检查更新"就整窗假死是最糟的体验）。
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QObject, Signal

REPO = "a435630144/PhoneDesktopForWindow"
PROJECT_URL = "https://github.com/" + REPO
RELEASES_URL = PROJECT_URL + "/releases"
LATEST_API = "https://api.github.com/repos/%s/releases/latest" % REPO

# 作者信息（v11 反馈 33：高级页「关于作者」）
AUTHOR_NAME = "a435630144"
AUTHOR_LINKS = (
    ("douyin", "抖音", "https://www.douyin.com/user/"
     "MS4wLjABAAAAcYd6aSteDxtAI4GIXIvBfld4o3lrOXjDhy5wv5J7K80"),
    ("bilibili", "哔哩哔哩",
     "https://space.bilibili.com/21785702"),
)

# GitHub API 要求带 UA，否则直接 403；Accept 固定 v3。
_HEADERS = {
    "User-Agent": "PhoneDesktop-Updater",
    "Accept": "application/vnd.github+json",
}


class UpdaterError(Exception):
    """网络 / 解析失败（文案已经翻成人话，可直接显示）。"""


def parse_version(text) -> Tuple[int, ...]:
    """`v5.0.7` / `5.0.7` / `5.0.7-beta` -> (5, 0, 7)。

    只取前三段数字；缺段补 0（`v5.1` -> (5, 1, 0)），非法返回 ()。
    """
    raw = str(text or "").strip()
    if raw[:1] in ("v", "V"):
        raw = raw[1:]
    parts = []
    for chunk in raw.replace("-", ".").replace("+", ".").split("."):
        chunk = "".join(ch for ch in chunk if ch.isdigit())
        if not chunk:
            break
        parts.append(int(chunk))
        if len(parts) >= 3:
            break
    while 0 < len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(latest, current) -> bool:
    """latest 是否比 current 新（按 (major, minor, patch) 逐段比）。"""
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return False
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a > b


def release_of(data) -> Dict:
    """GitHub release JSON -> 界面要的最小字段（脏数据一律回空串）。"""
    if not isinstance(data, dict):
        return {}
    tag = str(data.get("tag_name") or data.get("name") or "").strip()
    body = str(data.get("body") or "").strip()
    url = str(data.get("html_url") or RELEASES_URL).strip()
    published = str(data.get("published_at") or "").strip()
    return {
        "version": tag.lstrip("vV"),
        "tag": tag,
        "url": url or RELEASES_URL,
        "notes": body,
        "published": published,
        "prerelease": bool(data.get("prerelease")),
    }


def _friendly(exc: Exception) -> str:
    """把 urllib 的异常翻成用户能懂的一句话。"""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return "仓库还没有发布任何 Release"
        if exc.code in (403, 429):
            return "GitHub 限流了，请稍后再试"
        return "GitHub 返回 %s" % exc.code
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        text = str(reason or exc)
        if "timed out" in text.lower() or "timeout" in text.lower():
            return "连接超时，请检查网络或代理"
        return "连接不上 GitHub（%s）" % text
    if isinstance(exc, TimeoutError):
        return "连接超时，请检查网络或代理"
    return str(exc) or exc.__class__.__name__


def fetch_latest(timeout: float = 8.0, opener=None) -> Dict:
    """拉最新 release（同步阻塞，调用方必须在后台线程里跑）。

    失败抛 `UpdaterError`（文案已是人话）。`opener` 可注入（测试用）。
    """
    req = urllib.request.Request(LATEST_API, headers=_HEADERS)
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(req, timeout=timeout) as resp:
            raw = resp.read()
    except Exception as exc:      # noqa: BLE001 —— 统一翻成人话再抛
        raise UpdaterError(_friendly(exc)) from exc
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception as exc:      # noqa: BLE001
        raise UpdaterError("返回内容不是合法 JSON") from exc
    info = release_of(data)
    if not info.get("version"):
        raise UpdaterError("返回内容里没有版本号")
    return info


class UpdateChecker(QObject):
    """后台检查更新：`check()` 立即返回，结果走信号。

    线程模型：`check()` 起一条 daemon 线程，线程里发 `finished` / `failed`。
    Qt 的信号跨线程投递会自动排队到接收者所在线程（本对象在 GUI 线程
    创建，所以槽函数一定在 GUI 线程执行）。
    """

    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, parent=None, fetcher=None, current=None):
        super().__init__(parent)
        self._fetcher = fetcher or fetch_latest
        self._current = current
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def current_version(self) -> str:
        if self._current:
            return str(self._current)
        from . import version
        return version.SEMVER

    def check(self, timeout: float = 8.0) -> bool:
        """发起一次检查；已在检查中返回 False（防连点）。"""
        if self._busy:
            return False
        self._busy = True

        def _run():
            try:
                info = self._fetcher(timeout=timeout)
            except UpdaterError as exc:
                self._busy = False
                self.failed.emit(str(exc))
                return
            except Exception as exc:      # noqa: BLE001 —— 任何异常都不许逃逸
                self._busy = False
                self.failed.emit(_friendly(exc))
                return
            info = dict(info or {})
            info["newer"] = is_newer(info.get("version"), self.current_version())
            info["current"] = self.current_version()
            self._busy = False
            self.finished.emit(info)

        threading.Thread(target=_run, name="update-check", daemon=True).start()
        return True


def latest_or_none(timeout: float = 8.0) -> Optional[Dict]:
    """便捷函数：失败返回 None（给不需要错误文案的调用点用）。"""
    try:
        return fetch_latest(timeout=timeout)
    except UpdaterError:
        return None
