# -*- coding: utf-8 -*-
"""配置与布局持久化：JSON 存放于 %APPDATA%/DesktopOrganizerDemo/state.json。

layout 中每个条目：
  {"id": 唯一id, "type": "app" | "folder",
   "app":  {...}                 # type=app 时的应用字典（含 kind: app/file）
   "apps": [{...}, ...]          # type=folder 时的成员应用列表
   "col": 网格列, "row": 网格行}

桌面文件克隆条目：app.kind == "file"，id 为 "df:" + 路径哈希，
重扫不会重复，移除只动布局不删文件。
"""
import json
import os
import tempfile
import uuid
from copy import deepcopy

from .paths import data_file

DEFAULT_SETTINGS = {
    "first_run": True,         # 是否首次运行（用于一次性气泡提示）
    "autostart": False,        # 开机自启动
    "icon_size": 72,           # 图标边长（像素）
    "columns": 8,              # 每行图标数
    "opacity": 0.95,           # 整理窗口不透明度 0.5 ~ 1.0
    "show_widgets": True,      # 是否显示桌面小组件
    "minimize_to_tray": True,  # 关闭窗口时隐藏到托盘（否则退出程序）
    "hide_native_icons": False,     # 桌面整理模式：隐藏原生图标由整理桌面接管
    "auto_clone_desktop": False,    # 自动把桌面文件克隆进网格（默认关：不自行创建图标）
    "desktop_clone_seeded": False,  # 是否已把桌面文件克隆进网格
    "desktop_clone_v2": False,      # 是否已按 Shell 已知目录（OneDrive 重定向）补扫过
    "native_mode_migrated": False,  # 旧版（自动克隆）状态是否已迁移为原生模式
}

DEFAULT_WIDGETS = [
    # 不预设 x/y：首次创建时由 WidgetLayer 按类型放到合适位置
    {"id": "clock", "type": "clock", "w": 300, "h": 160, "hidden": False},
    {"id": "notes", "type": "notes", "w": 300, "h": 300, "hidden": True, "text": ""},
    {"id": "panel", "type": "panel", "w": 400, "h": 620, "hidden": False},
]


class Storage:
    def __init__(self, path=None):
        self.path = str(path or data_file("state.json"))
        self._data = {
            "settings": deepcopy(DEFAULT_SETTINGS),
            "layout": [],
            "widgets": deepcopy(DEFAULT_WIDGETS),
        }
        self._load()

    # ---------- 读写 ----------
    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return  # 文件损坏时回退默认值，不崩溃
        for key in ("settings", "layout", "widgets"):
            val = raw.get(key)
            if isinstance(val, type(self._data[key])):
                if isinstance(val, dict):
                    self._data[key].update(val)
                else:
                    self._data[key] = val
        self._migrate()

    def _migrate(self):
        """旧版本 state.json 兼容：补齐新增的默认小组件（如桌面面板）。"""
        existing = {w.get("id") for w in self._data["widgets"]}
        for w in DEFAULT_WIDGETS:
            if w.get("id") not in existing:
                self._data["widgets"].append(deepcopy(w))
                self.save()

    def save(self):
        """原子写入，避免写一半损坏。"""
        try:
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    # ---------- 访问器 ----------
    @property
    def settings(self) -> dict:
        return self._data["settings"]

    @property
    def layout(self) -> list:
        return self._data["layout"]

    @property
    def widgets(self) -> list:
        return self._data["widgets"]

    @property
    def columns(self) -> int:
        return max(2, int(self._data["settings"].get("columns", 8)))

    def get_setting(self, key):
        return self._data["settings"].get(key, DEFAULT_SETTINGS.get(key))

    def set_setting(self, key, value):
        self._data["settings"][key] = value
        self.save()

    # ---------- 布局辅助 ----------
    def find_entry(self, entry_id):
        for e in self._data["layout"]:
            if e.get("id") == entry_id:
                return e
        return None

    def remove_entry(self, entry_id):
        self._data["layout"] = [e for e in self._data["layout"] if e.get("id") != entry_id]

    def compact_layout(self):
        """按 (row, col) 排序后重排为连续网格，消除空行空列与越界。"""
        entries = sorted(self._data["layout"], key=lambda e: (e.get("row", 0), e.get("col", 0)))
        for i, e in enumerate(entries):
            e["col"] = i % self.columns
            e["row"] = i // self.columns

    def occupant(self, col, row, exclude_id=None):
        for e in self._data["layout"]:
            if e.get("id") == exclude_id:
                continue
            if int(e.get("col", -1)) == col and int(e.get("row", -1)) == row:
                return e
        return None

    def _first_free_cell(self, exclude_id=None):
        used = {(e.get("col", 0), e.get("row", 0)) for e in self._data["layout"] if e.get("id") != exclude_id}
        cols = self.columns
        col = row = 0
        while (col, row) in used:
            col += 1
            if col >= cols:
                col, row = 0, row + 1
        return col, row

    def add_app(self, app: dict, col=None, row=None) -> dict:
        """把应用 / 桌面文件添加到网格（默认第一个空格；指定格子被占时挤走占用者）。

        app 自带稳定 id（df: 哈希 / sm: 路径 / sys-xxx）时直接用作条目 id，
        同一应用重复添加返回已有条目，不产生副本。
        """
        entry_id = app.get("id") or uuid.uuid4().hex[:8]
        existing = self.find_entry(entry_id)
        if existing is not None:
            return existing
        if col is None or row is None:
            col, row = self._first_free_cell()
        else:
            occ = self.occupant(col, row)
            if occ is not None:
                nc, nr = self._first_free_cell(exclude_id=occ["id"])
                occ["col"], occ["row"] = nc, nr
        entry = {
            "id": entry_id,
            "type": "app",
            "app": app,
            "apps": [],
            "col": col,
            "row": row,
        }
        self._data["layout"].append(entry)
        return entry

    def reset_layout(self):
        """重置：清空网格（不删任何文件），由调用方决定是否重新克隆。"""
        self._data["layout"] = []
        self.save()

    def seed_desktop_clone(self, replace: bool = False):
        """把桌面文件克隆进网格（replace=True 先清空；已存在的跳过）。"""
        from . import appsource  # 延迟导入，避免模块级循环依赖
        if replace:
            self._data["layout"] = []
        existing = {e.get("app", {}).get("target") for e in self._data["layout"] if e.get("type") == "app"}
        added = 0
        for f in appsource.scan_desktop_files():
            if f["target"] in existing:
                continue
            self.add_app(f)
            added += 1
        self.set_setting("desktop_clone_seeded", True)
        self.save()
        return added

    def rescan_desktop(self) -> int:
        """重新扫描桌面：补新增、清丢失（同名路径哈希消失的条目）。"""
        from . import appsource
        live = {f["id"] for f in appsource.scan_desktop_files()}
        before = len(self._data["layout"])
        # 文件夹内的成员也可能来自桌面文件：解散语义不变，只清理顶层 df 条目
        self._data["layout"] = [
            e for e in self._data["layout"]
            if not (e.get("type") == "app" and e.get("app", {}).get("kind") == "file"
                    and e.get("id") not in live)
        ]
        added = self.seed_desktop_clone()
        self.compact_layout()
        self.save()
        return added, before - (len(self._data["layout"]) - added)

    def ensure_desktop_clone(self):
        """启动时调用：仅在用户开启「自动克隆桌面文件」时才播种 / 补扫。
        默认关闭——不自行创建桌面图标，桌面保持系统原生状态。"""
        if not self.get_setting("auto_clone_desktop"):
            return
        if not self.get_setting("desktop_clone_seeded"):
            self.seed_desktop_clone()
            return
        if not self.get_setting("desktop_clone_v2"):
            self.rescan_desktop()
            self.set_setting("desktop_clone_v2", True)

    def migrate_to_native_mode(self):
        """旧版本状态一次性迁移（问题反馈后新增）：

        旧版默认自动克隆桌面文件并隐藏原生图标；新版默认不自行创建图标、
        恢复系统原生桌面。检测到旧版播种痕迹（desktop_clone_seeded/v2）时：
        清空自动生成的网格（文件本身仍在桌面文件夹，随时可手动重新扫描找回），
        关闭整理模式，并标记迁移完成，避免反复清空用户后续的手动布局。
        """
        if self.get_setting("native_mode_migrated"):
            return False
        auto_seeded = bool(self.get_setting("desktop_clone_seeded")
                           or self.get_setting("desktop_clone_v2"))
        if auto_seeded:
            self._data["layout"] = []
        self.set_setting("hide_native_icons", False)
        self.set_setting("auto_clone_desktop", False)
        self.set_setting("native_mode_migrated", True)
        self.save()
        return auto_seeded
