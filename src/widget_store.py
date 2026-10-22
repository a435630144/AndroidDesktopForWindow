# -*- coding: utf-8 -*-
"""组件商店客户端（v10 A10）：从 gitee 取清单，拿不到就换 github。

## 为什么需要"两个镜像 + 兜底"

组件仓库同时放在 gitee 与 github（`Component/` 目录单独一个仓库）。国内直连
gitee 通常几十毫秒，github raw 经常几秒甚至超时——所以**默认先问 gitee**，
失败或超时才换 github；成功后把"这次用的镜像"记下来，下次先问它（避免每次
都白等一遍超时）。

## 三层结构（本模块只负责第一、二层）

    镜像清单      index.json         （本模块 fetch_index，缓存到 data_file）
    组件包        <type>-<ver>.zip    （本模块 download，校验 sha256）
    安装 / 卸载   widget_plugin       （本模块只转调，不自己解压）

## 安全

  - 只信任 `index.json` 里列出的包名与 sha256；包本身仍走
    `widget_plugin.import_zip()` 的整套校验（白名单后缀 / 拒绝 zip-slip /
    manifest 必填字段），商店不是绕过校验的后门；
  - 下载先落临时文件、校验通过才改名，断电/断网不会留下半个 zip。

测试只 monkeypatch `_http_get`（唯一网络出口），不碰真实网络。
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import urllib.request
from typing import Dict, List, Optional, Tuple

from . import paths
from . import widget_plugin
from . import widget_registry

# 组件仓库（`Component/` 目录对应仓库）的原始文件地址。
# 分支名两边不同：gitee 老仓库默认 master，github 是 main。
# 顺序即优先级：gitee（国内直连最快）-> github raw -> jsDelivr（GitHub 的 CDN
# 镜像，国内常能通）。实测本机直连 raw.githubusercontent.com 会被 TLS 层掐断，
# 所以"只留 github"不够，第三条线路是给"gitee 抽风 + github 被墙"准备的。
MIRRORS: Tuple[Tuple[str, str], ...] = (
    ("gitee",
     "https://gitee.com/suibianwanwanay/phone-desktop-for-windows-office-component/raw/master"),
    ("github",
     "https://raw.githubusercontent.com/a435630144/PhoneDesktopForWindows-OfficeComponent/main"),
    ("jsdelivr",
     "https://cdn.jsdelivr.net/gh/a435630144/PhoneDesktopForWindows-OfficeComponent@main"),
)
INDEX_NAME = "index.json"

# 连接 / 读取超时（秒）：gitee 挂了也不该让设置页转半分钟
TIMEOUT = 6.0
# 清单缓存有效期：过期后后台静默刷新，界面先用缓存
CACHE_TTL = 30 * 60


class StoreError(Exception):
    """商店不可用（两个镜像都失败）——消息可直接展示给用户。"""


# ---------------------------------------------------------------- 网络

def _http_get(url: str, timeout: float = TIMEOUT) -> bytes:
    """唯一的网络出口（测试 monkeypatch 这里，不碰真实网络）。"""
    req = urllib.request.Request(
        url, headers={"User-Agent": "PhoneDesktop/%s" % _app_version(),
                      "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310
        return resp.read()


def _app_version() -> str:
    try:
        from . import version
        return str(getattr(version, "SEMVER", "") or "0")
    except Exception:      # noqa: BLE001
        return "0"


def cache_file():
    return paths.data_file("store_index.json")


def _load_cache() -> Optional[dict]:
    try:
        with open(cache_file(), "r", encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else None
    except Exception:      # noqa: BLE001 —— 缓存坏了就当没有
        return None


def _save_cache(data: dict) -> None:
    try:
        path = cache_file()
        os.makedirs(os.path.dirname(str(path)), exist_ok=True)
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:      # noqa: BLE001 —— 写不进去不该影响浏览
        pass


# ---------------------------------------------------------------- 清单

def mirror_order() -> List[Tuple[str, str]]:
    """镜像顺序：上次成功的排最前，其余按声明顺序。"""
    cached = _load_cache() or {}
    last = str(cached.get("mirror") or "")
    out = [m for m in MIRRORS if m[0] == last]
    out += [m for m in MIRRORS if m[0] != last]
    return out


def fetch_index(force: bool = False) -> dict:
    """拉商店清单；两个镜像都失败抛 `StoreError`（带每个镜像的失败原因）。

    成功时写缓存（含 `mirror` / `fetched_at`），并在返回的 dict 里补
    `_mirror` 字段供界面显示"当前走的是哪条线路"。
    """
    errors = []
    for name, base in mirror_order():
        url = "%s/%s" % (base.rstrip("/"), INDEX_NAME)
        try:
            raw = _http_get(url)
        except Exception as exc:      # noqa: BLE001 —— 逐个镜像降级
            errors.append("%s: %s" % (name, exc))
            continue
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:      # noqa: BLE001
            errors.append("%s: 清单不是合法 JSON（%s）" % (name, exc))
            continue
        if not isinstance(data, dict) or not isinstance(data.get("widgets"), list):
            errors.append("%s: 清单缺 widgets 数组" % name)
            continue
        data["_mirror"] = name
        _save_cache({"mirror": name, "fetched_at": time.time(),
                     "index": {k: v for k, v in data.items() if k != "_mirror"}})
        return data
    raise StoreError("商店暂时打不开：\n" + "\n".join(errors or ["无可用镜像"]))


def cached_index() -> dict:
    """上次成功的清单（没有则返回空清单）；界面首屏用它，不等网络。"""
    cached = _load_cache() or {}
    idx = cached.get("index")
    if isinstance(idx, dict) and isinstance(idx.get("widgets"), list):
        idx = dict(idx)
        idx["_mirror"] = cached.get("mirror") or ""
        idx["_fetched_at"] = cached.get("fetched_at") or 0
        return idx
    return {"widgets": [], "_mirror": "", "_fetched_at": 0}


def cached_mirror() -> str:
    return str((_load_cache() or {}).get("mirror") or "")


def cache_age() -> float:
    """缓存年龄（秒）；没有缓存返回 +inf。"""
    ts = (cached_index().get("_fetched_at") or 0)
    if not ts:
        return float("inf")
    return max(0.0, time.time() - float(ts))


# ---------------------------------------------------------------- 包

def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def package_url(entry: dict, base: str) -> str:
    name = str(entry.get("package") or "").strip()
    if not name:
        raise StoreError("清单条目缺 package 字段：%s" % entry.get("type"))
    return "%s/%s" % (base.rstrip("/"), name.lstrip("/"))


def download(entry: dict) -> str:
    """下载组件包到临时目录并校验 sha256；返回本地路径（调用方负责清理）。"""
    want = str(entry.get("sha256") or "").strip().lower()
    errors = []
    for name, base in mirror_order():
        try:
            url = package_url(entry, base)
            data = _http_get(url, timeout=max(TIMEOUT, 20.0))
        except Exception as exc:      # noqa: BLE001
            errors.append("%s: %s" % (name, exc))
            continue
        fd, tmp = tempfile.mkstemp(prefix="pd_pkg_", suffix=".zip")
        os.close(fd)
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            got = _sha256(tmp)
            if want and got != want:
                errors.append("%s: sha256 不符（期望 %s…，实际 %s…）"
                              % (name, want[:12], got[:12]))
                os.unlink(tmp)
                continue
            return tmp
        except Exception as exc:      # noqa: BLE001
            errors.append("%s: %s" % (name, exc))
            try:
                os.unlink(tmp)
            except OSError:
                pass
    raise StoreError("组件包下载失败：\n" + "\n".join(errors or ["无可用镜像"]))


def install(entry: dict):
    """下载 + 安装一个商店组件（走 `widget_plugin.import_zip` 的全部校验）。"""
    if not isinstance(entry, dict) or not entry.get("type"):
        raise StoreError("清单条目非法")
    tmp = download(entry)
    try:
        spec = widget_plugin.import_zip(tmp)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return spec


def uninstall(wtype: str) -> bool:
    """卸载一个已安装的商店组件（内置组件拒绝）。"""
    return widget_plugin.uninstall(wtype)


# ---------------------------------------------------------------- 状态

def installed_version(wtype: str) -> str:
    spec = widget_registry.PLUGINS.get(wtype)
    return str(getattr(spec, "version", "") or "") if spec else ""


def _newer(a: str, b: str) -> bool:
    """版本比较（点分数字；非数字段按字符串比）。`a` 比 `b` 新返回 True。"""
    def parts(v):
        out = []
        for seg in str(v or "").split("."):
            try:
                out.append(int(seg))
            except (TypeError, ValueError):
                out.append(seg)
        return out
    pa, pb = parts(a), parts(b)
    for x, y in zip(pa, pb):
        if x == y:
            continue
        if isinstance(x, int) and isinstance(y, int):
            return x > y
        return str(x) > str(y)
    return len(pa) > len(pb)


def card_state(entry: dict) -> str:
    """商店卡片状态：builtin / installed / update / available。"""
    wtype = str(entry.get("type") or "")
    if widget_registry.is_builtin(wtype):
        return "builtin"          # 内置组件不在商店里覆盖（产品规则：内置优先）
    cur = installed_version(wtype)
    if not cur:
        return "available"
    if _newer(str(entry.get("version") or ""), cur):
        return "update"
    return "installed"


def summary() -> dict:
    """给设置页顶部的一行状态。"""
    idx = cached_index()
    return {"mirror": idx.get("_mirror") or cached_mirror(),
            "count": len(idx.get("widgets") or []),
            "age": cache_age(),
            "installed": len(widget_registry.PLUGINS)}
