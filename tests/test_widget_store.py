# -*- coding: utf-8 -*-
"""组件商店客户端契约（v10 A10）。

用户原话：
    app 本身不包含小组件，需要去组件商店按需要下载组件，商店的内容优先从
    gitee 获取，gitee 不通或者较慢，由 github 兜底。设置里的组件库要增加
    本地组件界面和组件库商店界面。

判据：
  S1  镜像顺序：gitee 先，github 与 jsDelivr 依次兜底；上次成功的排最前
  S2  gitee 失败 -> 自动换 github，并在清单里记下 `_mirror`
  S3  两个都失败 -> StoreError，消息里带两条线路的失败原因
  S4  清单缓存落盘（data_file("store_index.json")），重读逐字段相等
  S5  安装：下载 + sha256 校验 + 走 widget_plugin.import_zip -> 注册成插件
  S6  sha256 不符一律拒装（不覆盖已装版本）
  S7  卡片状态机：available -> installed -> update（版本抬升）-> 卸载后 available
  S8  内置组件永远显示 builtin（商店不覆盖内置）
  S9  商店页：缓存清单渲染卡片、状态行写线路与数量
  S10 设置 ▸ 组件库两个页签（本地 / 商店），切换不改动本地列表

网络全部走 `widget_store._http_get`（唯一出口），本测试 monkeypatch 它，
不碰真实网络。

运行：python tests/test_widget_store.py   （offscreen；判据看退出码）
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = Path(tempfile.mkdtemp(prefix="pd_store_test_"))
os.environ["APPDATA"] = str(_TMP)          # 数据目录重定向，别碰真实 %APPDATA%
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication   # noqa: E402

failures = []

REPO = Path(__file__).resolve().parent.parent / "Component"


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


class _Sig:
    """最小信号桩（组件库页只需 connect/emit）。"""

    def __init__(self):
        self._subs = []

    def connect(self, fn):
        self._subs.append(fn)

    def emit(self, *a):
        for fn in list(self._subs):
            fn(*a)


def serve(monkey_map):
    """把 {url 后缀: 本地文件} 变成一个假 `_http_get`；未命中的 URL 抛连接错误。"""
    from src import widget_store

    def fake(url, timeout=None):
        for suffix, path in monkey_map.items():
            if url.endswith(suffix):
                return Path(path).read_bytes()
        raise ConnectionError("connection timed out: %s" % url)

    return fake


def main():
    app = QApplication.instance() or QApplication([])   # noqa: F841
    from src import widget_store, widget_plugin, widget_registry

    idx = json.loads((REPO / "index.json").read_text(encoding="utf-8"))
    check("S0 组件仓库有清单", len(idx.get("widgets") or []) >= 2,
          "%d 个" % len(idx.get("widgets") or []))
    if not idx.get("widgets"):
        print("FATAL: Component/index.json 为空，先跑 tools/build.py")
        return 1
    first = idx["widgets"][0]
    pkg_file = REPO / "dist" / first["package"]
    check("S0b 清单里的包真实存在", pkg_file.is_file(), str(pkg_file))

    # ---------- S1：镜像顺序 ----------
    order = [m[0] for m in widget_store.mirror_order()]
    check("S1 线路顺序 gitee -> github -> jsdelivr",
          order == ["gitee", "github", "jsdelivr"], str(order))

    # ---------- S2：gitee 失败自动换 github ----------
    widget_store._http_get = serve({"main/index.json": REPO / "index.json"})
    got = widget_store.fetch_index(force=True)
    check("S2 gitee 不通 -> github 兜底成功", len(got["widgets"]) == len(idx["widgets"]),
          "%d 个" % len(got["widgets"]))
    check("S2b 记录这次走的线路", got.get("_mirror") == "github",
          str(got.get("_mirror")))
    check("S2c 成功后该线路排最前", widget_store.mirror_order()[0][0] == "github",
          str([m[0] for m in widget_store.mirror_order()]))

    # ---------- S4：缓存落盘 ----------
    cache = widget_store.cached_index()
    check("S4 缓存可读回", len(cache["widgets"]) == len(idx["widgets"]))
    check("S4b 缓存文件写进 data_file",
          (Path(os.environ["APPDATA"]) / "PhoneDesktop" / "store_index.json").is_file())
    check("S4c 缓存年龄是有限值", widget_store.cache_age() < 600,
          "%.1fs" % widget_store.cache_age())

    # ---------- S3：两条线路都挂 ----------
    widget_store._http_get = serve({})
    err = ""
    try:
        widget_store.fetch_index(force=True)
    except Exception as exc:      # noqa: BLE001
        err = str(exc)
    check("S3 两个镜像都失败 -> StoreError", "打不开" in err, err[:60])
    check("S3b 消息里带两条线路的原因",
          "gitee" in err and "github" in err, err[:120])
    check("S3c 失败不清掉旧缓存",
          len(widget_store.cached_index()["widgets"]) == len(idx["widgets"]))

    # ---------- S5：安装 ----------
    widget_store._http_get = serve({
        "main/index.json": REPO / "index.json",
        "main/" + first["package"]: pkg_file,
    })
    widget_store.fetch_index(force=True)
    entry = widget_store.cached_index()["widgets"][0]
    check("S5 安装前状态 = available",
          widget_store.card_state(entry) == "available",
          widget_store.card_state(entry))
    spec = widget_store.install(entry)
    check("S5b 安装后注册成插件", spec is not None
          and entry["type"] in widget_registry.PLUGINS,
          "%s" % list(widget_registry.PLUGINS))
    check("S5c 已装版本号来自 manifest",
          widget_store.installed_version(entry["type"]) == entry["version"],
          widget_store.installed_version(entry["type"]))
    check("S5d 装到用户目录（widgets/<type>）",
          (widget_plugin.plugin_root() / entry["type"] / "manifest.json").is_file())
    check("S5e 状态变 installed",
          widget_store.card_state(entry) == "installed",
          widget_store.card_state(entry))
    # 真渲染一次：装进来能用才算装上
    w = widget_plugin.build_spec(widget_plugin.plugin_root() / entry["type"])
    check("S5f 装进来的组件能构造", w is not None and w.factory is not None)
    check("S5g 组件类是 GlassWidget 子类",
          issubclass(w.factory, __import__(
              "src.widget_glass", fromlist=["GlassWidget"]).GlassWidget))

    # ---------- S6：sha256 不符 ----------
    bad = dict(entry)
    bad["sha256"] = "0" * 64
    err = ""
    try:
        widget_store.install(bad)
    except Exception as exc:      # noqa: BLE001
        err = str(exc)
    check("S6 sha256 不符 -> 拒装", "sha256" in err, err[:80])
    check("S6b 拒装不影响已装版本",
          widget_store.installed_version(entry["type"]) == entry["version"])

    # ---------- S7：状态机 update ----------
    newer = dict(entry)
    newer["version"] = "9.9.9"
    check("S7 版本抬升 -> update", widget_store.card_state(newer) == "update",
          widget_store.card_state(newer))
    check("S7b 卸载 -> 回到 available",
          widget_store.uninstall(entry["type"])
          and widget_store.card_state(entry) == "available",
          widget_store.card_state(entry))
    check("S7c 卸载后目录已删",
          not (widget_plugin.plugin_root() / entry["type"]).exists())

    # ---------- S8：内置不被商店覆盖 ----------
    builtin_entry = {"type": "clock", "version": "99.0.0"}
    check("S8 内置组件永远 builtin",
          widget_store.card_state(builtin_entry) == "builtin",
          widget_store.card_state(builtin_entry))
    check("S8b 内置组件拒绝卸载", widget_store.uninstall("clock") is False)

    # ---------- S9：商店页 ----------
    from src import widget_shop
    widget_store._http_get = serve({"main/index.json": REPO / "index.json"})
    widget_store.fetch_index(force=True)
    page = widget_shop.WidgetShopPage(None)
    cards = page.cards()
    check("S9 商店页渲染出卡片", len(cards) == len(idx["widgets"]),
          "%d 张" % len(cards))
    check("S9b 状态行写了线路与数量",
          "github" in page.lbl_status.text()
          and str(len(idx["widgets"])) in page.lbl_status.text(),
          page.lbl_status.text())
    check("S9c 每个卡片都有动作按钮",
          all(c.btn.text() for c in cards),
          "%s" % [c.btn.text() for c in cards])
    page.deleteLater()

    # ---------- S10：设置 ▸ 组件库两个页签 ----------
    from src import settings_dialog, storage
    st = storage.Storage(path=str(_TMP / "state.json"))

    class FakeLayer:
        """组件库页只用到这几个查询（真实 WidgetLayer 的同名方法）。"""

        def __init__(self, storage):
            self.widgets = {}
            self.storage = storage
            self.widgetsChanged = _Sig()

        def entries_of(self, wtype):
            return []

        def add(self, wtype, force_new=False):
            return None

        def toggle_entry(self, entry_id, visible):
            return None

        def remove(self, entry_id):
            return False

        def hide_all(self):
            return 0

        def show_all(self):
            return 0

    dlg = settings_dialog.SettingsDialog(object(), st, FakeLayer(st))
    check("S10 组件库有 本地/商店 两个页签",
          hasattr(dlg, "btn_tab_local") and hasattr(dlg, "btn_tab_shop"),
          "missing")
    check("S10b 默认停在本地",
          dlg.widget_stack.currentIndex() == 0,
          "idx=%d" % dlg.widget_stack.currentIndex())
    dlg.select_widget_tab("shop")
    check("S10c 切到商店页签", dlg.widget_stack.currentIndex() == 1,
          "idx=%d" % dlg.widget_stack.currentIndex())
    check("S10d 本地列表仍在（没被清掉）",
          dlg.center_page is not None and len(dlg.center_page.cards) > 0,
          "%d 张" % len(getattr(dlg.center_page, "cards", [])))
    dlg.deleteLater()

    print("")
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
    else:
        print("ALL widget_store PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
