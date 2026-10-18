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
    "schema_version": 2,     # 状态结构版本：2 = 路线A（全量接管）。旧版(1)state
                            # 首次加载时一次性升级，见 Storage._migrate
    "first_run": True,         # 是否首次运行（用于一次性气泡提示）
    "autostart": False,        # 开机自启动
    "icon_size": 72,           # 图标边长基准（像素，100% 缩放下的逻辑值）
    "icon_scale": 1.0,         # 用户自定义图标缩放（在 DPI 感知之上再乘，0.6~2.0）
    "columns": "auto",         # 每行图标数："auto"=按工作区尺寸自动计算（M1 GridMetrics，
                               # 指导文档 §1：四边等距铺满）；或整数（>=2）手动覆盖列数
                               # （设置高级选项，rows 始终自动）
    "opacity": 0.95,           # 整理窗口不透明度 0.5 ~ 1.0
    "show_widgets": True,      # 是否显示桌面小组件
    "minimize_to_tray": True,  # 关闭窗口时隐藏到托盘（否则退出程序）
    # 2026-10-18 产品方向调整（用户拍板"路线A：隐藏原图标全部映射"）：
    # 默认即进入桌面整理模式——隐藏原生图标、桌面文件全部映射进网格、
    # 安卓式滑动让位 / 文件夹 / 小组件占位全部可用。原生桌面右键等损失
    # 由自绘桌面右键菜单补齐（desktop_window.contextMenuEvent）。
    "hide_native_icons": True,     # 桌面整理模式：隐藏原生图标由整理桌面接管
    "auto_clone_desktop": True,    # 自动把桌面文件克隆进网格（路线A：全量映射）
    "desktop_clone_seeded": False,  # 是否已把桌面文件克隆进网格
    "desktop_clone_v2": False,      # 是否已按 Shell 已知目录（OneDrive 重定向）补扫过
    "native_mode_migrated": False,  # 旧版状态是否已迁移（现仅作历史标记）
}

DEFAULT_WIDGETS = [
    # 不预设 x/y：首次创建时由 WidgetLayer 按类型放到合适位置
    # clock 默认锚定（非悬浮）：占据网格格子、融入壁纸（2026-10-18 用户要求
    # "小组件占据格子位置，挤走其他对象"）。可交互组件（notes/panel 含
    # 输入框）保持悬浮——锚定一律 NOACTIVATE，无法获得键盘焦点。
    # M3：锚定 clock 的 w/h 在 spawn 时被 widget_catalog 推导值覆盖
    # （2×2 格 = span × cell），此处旧像素值仅作悬浮态回退，不再生效
    {"id": "clock", "type": "clock", "w": 300, "h": 160, "hidden": False,
     "anchored": True},
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
        # 先记录文件里的真实 schema 版本（合并后会被默认值 2 覆盖，读不到旧值）
        raw_schema = 1
        if isinstance(raw.get("settings"), dict):
            try:
                raw_schema = int(raw["settings"].get("schema_version", 1))
            except (TypeError, ValueError):
                raw_schema = 1
        for key in ("settings", "layout", "widgets"):
            val = raw.get(key)
            if isinstance(val, type(self._data[key])):
                if isinstance(val, dict):
                    self._data[key].update(val)
                else:
                    self._data[key] = val
        self._migrate(raw_schema)

    def _migrate(self, raw_schema: int = 2):
        """旧版本 state.json 兼容：
        1. 补齐新增的默认小组件（如桌面面板）；
        2. schema_version 1 -> 2 一次性升级（路线A）：2026-10-18 之前的
           state 里 hide_native_icons/auto_clone_desktop 为 false（旧默认
           "保持系统原生桌面"），直接升级软件用户会看到"原生图标还在、
           文件没映射"——正是本轮三张截图反馈的现象。升级时开启整理模式
           + 自动播种；**只升一次**，之后尊重用户在设置里的手动选择。
        """
        existing = {w.get("id") for w in self._data["widgets"]}
        for w in DEFAULT_WIDGETS:
            if w.get("id") not in existing:
                self._data["widgets"].append(deepcopy(w))
        if raw_schema < 2:
            self._data["settings"]["schema_version"] = 2
            self._data["settings"]["hide_native_icons"] = True
            self._data["settings"]["auto_clone_desktop"] = True
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
        """当前网格列数：优先 GridMetrics 快照（M1 起的默认路径，
        指导文档 §1）；快照未就绪时回退 settings 手动值
        （"auto" -> 静态兜底 10）。"""
        from . import grid_flow
        m = grid_flow.current_metrics()
        if m is not None:
            return m.cols
        raw = self._data["settings"].get("columns", 10)
        if isinstance(raw, str) or raw is None:
            return 10
        return max(2, int(raw))

    def get_setting(self, key):
        return self._data["settings"].get(key, DEFAULT_SETTINGS.get(key))

    def set_setting(self, key, value):
        self._data["settings"][key] = value
        self.save()

    # ---------- 图标尺寸（DPI × 用户缩放双感知） ----------
    def icon_metric(self) -> int:
        """实际图标边长（逻辑 px）= 基准 × 屏幕 DPI × 用户缩放。

        Windows 125% 缩放下基准 72 -> 90px，图标随系统缩放同比变大
        （用户反馈 2026-10-18：图标大小没有随 Windows 缩放比例变化）。
        """
        from . import theme  # 延迟导入：theme 不依赖 storage，无循环
        base = int(self.get_setting("icon_size"))
        return max(24, int(round(base * theme.screen_dpr() * self.user_icon_scale())))

    def user_icon_scale(self) -> float:
        """用户自定义缩放系数（设置滑条，0.6~2.0，默认 1.0）。"""
        try:
            return min(2.0, max(0.6, float(self.get_setting("icon_scale"))))
        except (TypeError, ValueError):
            return 1.0

    def icon_chrome_scale(self) -> float:
        """图标外围 chrome（留白/标签字号/行高）的缩放系数 = DPI × 用户缩放。"""
        from . import theme
        return theme.screen_dpr() * self.user_icon_scale()

    # ---------- 布局辅助 ----------
    def find_entry(self, entry_id):
        for e in self._data["layout"]:
            if e.get("id") == entry_id:
                return e
        return None

    def remove_entry(self, entry_id):
        self._data["layout"] = [e for e in self._data["layout"] if e.get("id") != entry_id]

    def compact_layout(self):
        """最小修正：只修越界与重叠，**不重排顺序**。

        2026-10-18 用户反馈"app 排序还是强制水平的，我要自由排布"：
        旧实现按 (row,col) 排序后顺序铺满，会把用户手工摆放的稀疏布局
        抹平。现在：
          - col 越界（>=columns）夹紧回最后列
          - 同格多条目只保留第一个，其余挪到第一个空格
          - 顺序、空行、空列全部保留——用户想把图标放哪就放哪
        显式「整理布局」（托盘/右键菜单）走 tidy_layout() 才顺序铺满。
        """
        cols = self.columns
        used = set()
        for e in sorted(self._data["layout"],
                        key=lambda x: (x.get("row", 0), x.get("col", 0))):
            col = max(0, min(cols - 1, int(e.get("col", 0))))
            row = max(0, int(e.get("row", 0)))
            if (col, row) in used:
                col, row = self._first_free_cell()
            used.add((col, row))
            e["col"], e["row"] = col, row

    def tidy_layout(self):
        """显式整理：按 (row, col) 排序后顺序铺满为连续网格（用户主动触发）。"""
        entries = sorted(self._data["layout"],
                         key=lambda e: (e.get("row", 0), e.get("col", 0)))
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

    def _first_free_cell(self, exclude_id=None, extra_used=()):
        used = {(e.get("col", 0), e.get("row", 0)) for e in self._data["layout"] if e.get("id") != exclude_id}
        used |= set(extra_used or ())
        cols = self.columns
        col = row = 0
        while (col, row) in used:
            col += 1
            if col >= cols:
                col, row = 0, row + 1
        return col, row

    def first_free_cell(self, extra_used=()):
        """第一个空格（可排除 widget 占位等额外占用）。"""
        from . import grid_flow  # 延迟导入：grid_flow 依赖 storage 的尺寸访问器
        return self._first_free_cell(extra_used=extra_used or grid_flow.widget_cells(self))

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
            col, row = self.first_free_cell()
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

    def ensure_desktop_clone(self, force: bool = False):
        """启动 / 开启整理模式时调用：把桌面文件播种进网格。

        2026-10-18 路线A 拍板后的语义：
          - **整理模式（hide_native_icons）开启且网格为空 -> 无条件播种**：
            路线A 承诺"桌面文件全部映射"，空布局 + 整理模式 = 用户面对
            空桌面 = 文件丢失观感（probe16 G2 抓到旧实现里历史标志 +
            auto_clone 双重拦截会导致播种被跳过）。**不依赖
            desktop_clone_seeded/v2 历史标志**（旧版标志残留曾导致重新
            开启整理模式时网格不恢复，是"加载的文件缺少很多"的根因之一）
          - 布局非空时按 auto_clone_desktop 决定：开=启动补播新增；
            关=尊重用户的手动删除（删过的条目重启不回来）
          - force=True：用户主动操作（开启整理模式 / 重新扫描），无视
            auto_clone 与空布局判断，强制补扫
          - 每次调用都补扫一次，幂等：已有条目跳过、只增不减（丢失文件的
            清理交给显式「重新扫描桌面文件」，不碰用户布局）
        """
        if not (force or self.get_setting("hide_native_icons")):
            return 0
        empty = not self._data["layout"]
        if not force and not empty and not self.get_setting("auto_clone_desktop"):
            return 0
        return self.seed_desktop_clone()

    def migrate_to_native_mode(self):
        """已废弃（2026-10-18 路线A 拍板后保留空实现兼容旧调用）。

        历史：Day2 曾把"自动克隆 + 隐藏原生图标"的旧状态迁移为原生模式
        （关整理模式 + 清空网格）。用户明确选择路线A（隐藏原图标全部映射）
        后该迁移反变为破坏行为——会偷偷关掉用户刚开好的整理模式并清空其
        布局。现不再做任何事；旧 state 的 hide_native_icons 若为 True 则
        原样保留，由 ensure_desktop_clone(force=True) 补播。
        """
        return False
