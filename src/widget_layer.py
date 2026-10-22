# -*- coding: utf-8 -*-
"""小组件管理层：统一创建 / 显隐 / 关闭桌面小组件。

v8 C1 起组件的"静态事实"全部来自 `widget_registry`——本模块只做
生命周期与落位，不再持有 类型→类 / 类型→中文名 的第二份真相。
新增组件请改 `src/widget_registry.py` 的 `REGISTRY`，这里一行都不用动。
"""
import uuid

from PySide6.QtCore import QObject, QPoint, Signal
from PySide6.QtWidgets import QApplication

from . import grid_flow
from . import widget_registry
from . import win32_layer
from .band_guard import BandGuard
from .widget_base import FloatingWidget

# 兼容导出：托盘/设置页/测试长期 import 这两个名字。
# 由注册表派生（不是手写第二份），未登记的类型自然不在这里。
WIDGET_TYPES = {t: s.factory for t, s in widget_registry.REGISTRY.items()}

WIDGET_NAMES = widget_registry.names()


class WidgetLayer(QObject):
    # 锚定小组件占位变化（落定 / 移动 / 尺寸变化）时发出，
    # 由 main.py 连到 DesktopWindow.on_widget_grid_changed 挤走图标。
    gridChanged = Signal()
    # 锚定组件拖动实时预览（2026-10-18 M4）：转发 FloatingWidget 的
    # anchorHover/anchorDrop（widget id + 指针全局坐标）。
    anchorHover = Signal(str, int, int)
    anchorDrop = Signal(str, int, int)
    # 组件增删（v8 C1）：组件库卡片状态、托盘勾选项、底部计数都靠它刷新。
    # 显隐（toggle_entry）不发这个信号——那是"可见性"，不是"有/没有"。
    widgetsChanged = Signal()

    def __init__(self, storage):
        super().__init__()
        self.storage = storage
        self.widgets = {}  # entry_id -> FloatingWidget
        self._band_guard = BandGuard()
        for entry in self.storage.widgets:
            self._place_default(entry)
            self._spawn(entry)
        if not self.storage.get_setting("show_widgets"):
            self.set_visible(False)

    # ---------- 默认落位 ----------
    def _place_default(self, entry):
        """首次创建（没有保存过位置）时按类型放到合适位置，避免互相遮挡。

        锚定（非悬浮）组件不在这里定位：由 _spawn 走 find_widget_slot
        分配网格占位（col/row），再换算成像素坐标——它占据格子，
        不是"浮在某个角落"。
        """
        if entry.get("anchored") and "col" not in entry:
            return
        if "x" in entry:
            return
        screen = QApplication.primaryScreen().availableGeometry()
        w, h = int(entry.get("w", 300)), int(entry.get("h", 160))
        t = entry.get("type")
        if t == "clock":
            entry["x"] = screen.right() - w - 56
            entry["y"] = screen.top() + 48
        elif t == "panel":
            # 桌面面板：右侧，时钟下方（时钟隐藏时贴顶）
            clock = next((e for e in self.storage.widgets if e.get("type") == "clock"), None)
            top = screen.top() + 48
            if clock is not None and not clock.get("hidden"):
                top = screen.top() + 48 + int(clock.get("h", 160)) + 20
            entry["x"] = screen.right() - w - 40
            entry["y"] = top
        else:  # notes 等：右下角，多个则向左层叠
            n = sum(1 for e in self.storage.widgets if e.get("type") == t)
            entry["x"] = screen.right() - w - 56 - (n * 44) % 200
            entry["y"] = screen.bottom() - h - 48
        self.storage.save()

    # ---------- 生命周期 ----------
    def _spawn(self, entry):
        if entry.get("hidden"):
            return
        # v9 V3：工厂走注册表而不是模块级字典快照——外部插件是运行时
        # 注册的，`WIDGET_TYPES` 在 import 时就定死了，拿不到新组件。
        spec = widget_registry.get(entry.get("type"))
        cls = spec.factory if spec is not None else WIDGET_TYPES.get(entry.get("type"))
        if cls is None:
            return
        if entry.get("anchored"):
            if grid_flow.free_mode(self.storage):
                # v6 §1.3 无界锚定：row 仅作页载体，位置读 fx/fy（缺列
                # 时补一份，落在当前页），尺寸用 entry 的 w/h（用户像素），
                # 不分配网格占位、不写 colspan/rowspan 覆盖用户尺寸
                if "col" not in entry or "row" not in entry:
                    entry["col"] = 0
                    entry["row"] = (grid_flow.current_page()
                                    * grid_flow.rows_per_page())
                if "fx" not in entry or "fy" not in entry:
                    if "col" in entry and "row" in entry:
                        # 反馈 3：未接管时自动无界——没有 fx/fy 的旧数据按
                        # 它原来的格点像素懒生成，切换瞬间视觉不跳变
                        # （旧实现回退 x/y，会跳到窗口左上角）
                        entry["fx"], entry["fy"] = grid_flow.cell_pos(
                            self.storage, int(entry["col"]), int(entry["row"]))
                    else:
                        entry["fx"] = int(entry.get("x", 0) or 0)
                        entry["fy"] = int(entry.get("y", 0) or 0)
                # __init__ 的初始 geometry 读 x/y——同步一份，窗口才落在
                # fx/fy 上（否则停在网格模式遗留的旧格点像素）
                entry["x"], entry["y"] = entry["fx"], entry["fy"]
            else:
                # 锚定组件：分配网格占位（排除已有组件与图标），按格点定位。
                # M6：find_widget_slot 默认限运行时当前页行范围（组件不越页底）
                if "col" not in entry:
                    col, row = grid_flow.find_widget_slot(self.storage, entry)
                else:
                    # v6 §4：旧数据越页修正——span 夹紧到所属页行范围
                    # （便签 2×2 存在 row=rpp-1 会跨页半截，probe23 S2）
                    cs, rs = grid_flow.widget_span(self.storage, entry)
                    col, row = grid_flow.clamp_widget_cell(
                        self.storage, int(entry.get("col", 0)),
                        int(entry.get("row", 0)), cs, rs)
                entry["col"], entry["row"] = col, row
                cs, rs = grid_flow.widget_span(self.storage, entry)
                entry["colspan"], entry["rowspan"] = cs, rs
                # M6：位置统一走 cell_pos（页内局部行映射）
                entry["x"], entry["y"] = grid_flow.cell_pos(
                    self.storage, int(entry["col"]), int(entry["row"]))
            self.storage.save()
        w = cls(self.storage, entry)
        w.closed.connect(self._on_closed)
        w.gridChanged.connect(self.gridChanged.emit)
        w.anchorHover.connect(self.anchorHover.emit)
        w.anchorDrop.connect(self.anchorDrop.emit)
        self.widgets[entry["id"]] = w
        w.show()
        # v6 §4：不在当前页的锚定组件隐藏——组件是**顶层窗口**（不像
        # 图标是桌面窗口子控件会被裁剪），静止态露在屏顶/屏底就是半截
        # 渲染；翻到它的页由 sync_page 显示
        if entry.get("anchored"):
            # v7 B2：页归属走 entry_page（无界读 fpage，网格读 row）
            if grid_flow.entry_page(self.storage, entry) != grid_flow.current_page():
                w.hide()
        # 小组件同样纳入桌面带守护（防 Win+D 等场景漂移后盖住应用窗口）。
        # 层号 = WIDGET：必须压在整理窗口之上——整理窗口在接管模式全窗口
        # HTCLIENT，组件落在它下面会被吞掉全部点击（反馈 1 的根因）。
        win32_layer.enforce_band_order()
        self._band_guard.track(w, layer=win32_layer.BAND_LAYER_WIDGET)

    def exit_all_edit(self):
        """退出所有组件的编辑态（点桌面空白 / 开右键菜单时调用）。

        编辑态只是视觉+命中层的临时状态，没有落盘副作用，随时可退。
        """
        for w in list(self.widgets.values()):
            try:
                if getattr(w, "_edit_mode", False):
                    w._exit_edit()
            except RuntimeError:
                pass

    def apply_layout_mode(self):
        """v6 §1.3 模式切换后重排组件：关闭全部再按新模式 spawn。

        锚定组件的位置来源（cell_pos ↔ fx/fy）与尺寸来源（span 派生 ↔
        用户像素）都随模式变，逐个 set_anchored 式的原地切换表达不了
        「整体刷新」——3 个组件全量重建成本可忽略，语义最干净。
        """
        for w in list(self.widgets.values()):
            self._band_guard.untrack(w)
            w.close()
        self.widgets.clear()
        for entry in self.storage.widgets:
            if entry.get("hidden"):
                continue
            self._spawn(entry)

    def _on_closed(self, widget_id):
        w = self.widgets.pop(widget_id, None)
        if w is not None:
            self._band_guard.untrack(w)
        # 形态切换（锚定 <-> 悬浮）会关闭旧窗口再重建：entry 未 hidden
        # 就必须补一个，否则右键切一次组件就少一个
        entry = next((e for e in self.storage.widgets if e.get("id") == widget_id), None)
        if entry is not None and not entry.get("hidden") and widget_id not in self.widgets:
            self._spawn(entry)

    def sync_page(self, page: int):
        """M6 翻页联动：把所有锚定组件滑到新页位置（与图标同向）。

        只改视觉位置——entry 的 col/row 是全局行，不随页变化（零迁移）。
        非锚定（悬浮）组件不参与翻页：它们靠屏幕角落自由定位。

        v6 §4 分页禁半截：组件是**顶层窗口**，网格四边等距铺满后边距
        放不下整块组件——静止态下邻页组件会从屏顶/屏底露半截。因此：
        新页组件滑入前先显示（showEvent 补挂载 + 淡入，与滑入同向），
        滑出屏的组件动画结束后隐藏（_cull_widget 以当前页复核，防连翻）。
        """
        rpp = grid_flow.rows_per_page()
        page = int(page)
        for w in self.widgets.values():
            if not getattr(w, "anchored", False):
                continue
            on_page = grid_flow.entry_page(self.storage, w.entry) == page
            if on_page and w.isHidden():
                w.show()      # 滑入前先显示（隐藏窗口的动画不可见）
            # v6 §1.3：位置统一走 widget_pos——网格模式 cell_pos、
            # 无界模式 fx/fy + 页间偏移（与图标同一套页载体语义）
            anim = w.animate_to(*grid_flow.widget_pos(self.storage, w.entry))
            if not on_page:
                if anim is None:
                    self._cull_widget(w)
                else:
                    anim.finished.connect(lambda w=w: self._cull_widget(w))

    def _cull_widget(self, w):
        """组件滑行结束：仍不在当前页就隐藏（v6 §4，防连翻误伤）。"""
        if grid_flow.entry_page(self.storage, w.entry) != grid_flow.current_page():
            w.hide()

    # ---------- 轮播翻页（v10 B3） ----------
    def apply_flip_frame(self):
        """轮播翻页的**单帧**：只 move，不播动画。

        整页平移的唯一驱动源是 `grid_flow` 的 flip 标量（图标与组件读同一份
        `flip_delta`），所以这里只做"把锚定组件摆到当前帧位置 + 只显示参与
        的两页"。旧实现每个组件各起一条 `animate_to` 弹簧——与图标不同曲线、
        不同起始状态，就是反馈 6「没有接续感」的一部分。
        """
        state = grid_flow.flip_state()
        if state is None:
            return
        target, direction, _progress = state
        pages = (target, target - direction)
        for w in self.widgets.values():
            if not getattr(w, "anchored", False):
                continue          # 悬浮组件靠屏幕角落定位，不参与翻页
            page = grid_flow.entry_page(self.storage, w.entry)
            if page in pages:
                if w.isHidden():
                    w.show()      # 隐藏窗口不动画/不显示，先亮出来
                x, y = grid_flow.widget_pos(self.storage, w.entry)
                dx, dy = grid_flow.flip_px(self.storage, page)
                w.move(int(x) + dx, int(y) + dy)
            elif not w.isHidden():
                w.hide()

    def settle_flip(self):
        """翻页结束：只留当前页组件，位置按最终几何落定（不播动画）。"""
        page = grid_flow.current_page()
        for w in self.widgets.values():
            if not getattr(w, "anchored", False):
                continue
            if grid_flow.entry_page(self.storage, w.entry) == page:
                if w.isHidden():
                    w.show()
                x, y = grid_flow.widget_pos(self.storage, w.entry)
                w.move(int(x), int(y))
            elif not w.isHidden():
                w.hide()

    def set_anchored(self, entry_id: str, on: bool):
        """切换小组件的锚定（非悬浮）形态：改 entry 后重建该组件。"""
        entry = next((e for e in self.storage.widgets if e.get("id") == entry_id), None)
        if not entry or bool(entry.get("anchored")) == bool(on):
            return
        entry["anchored"] = bool(on)
        self.storage.save()
        w = self.widgets.pop(entry_id, None)
        if w is not None:
            self._band_guard.untrack(w)
            w.close()
        self._spawn(entry)

    def set_visible(self, on: bool):
        for w in self.widgets.values():
            w.setVisible(on)

    def toggle_entry(self, entry_id: str, visible: bool):
        entry = next((e for e in self.storage.widgets if e.get("id") == entry_id), None)
        if not entry:
            return
        entry["hidden"] = not visible
        self.storage.save()
        if visible and entry_id not in self.widgets:
            self._place_default(entry)
            self._spawn(entry)
        elif not visible and entry_id in self.widgets:
            w = self.widgets.pop(entry_id)
            self._band_guard.untrack(w)
            w.close()

    # ---------- v10 A7（反馈 13）：批量显隐 ----------
    def show_all(self) -> int:
        """一键恢复全部被隐藏的组件（设置 ▸ 通用「显示桌面小组件」）。

        返回恢复的个数——调用方要能告诉用户"恢复了 3 个"还是"没有可恢复的"。
        语义走 `toggle_entry`（显隐的唯一入口），不自己写第二套。
        """
        n = 0
        for entry in list(self.storage.widgets):
            if entry.get("hidden"):
                self.toggle_entry(entry.get("id"), True)
                n += 1
        return n

    def hide_all(self) -> int:
        """一键关闭全部组件（组件库「关闭所有组件」，桌面只剩图标）。

        与 `show_all` 对称；**调用方必须先弹二次确认**——这是"桌面清空"级
        操作，误触一次用户就要一个个加回来。
        """
        n = 0
        for entry in list(self.storage.widgets):
            if not entry.get("hidden"):
                self.toggle_entry(entry.get("id"), False)
                n += 1
        return n

    # ---------- 增删（v8 C1：唯一入口） ----------
    def entries_of(self, wtype: str) -> list:
        """该类型在存储里的全部条目（按存储顺序）。"""
        return [e for e in self.storage.widgets if e.get("type") == wtype]

    def add(self, wtype: str, force_new: bool = False):
        """添加一个组件实例，返回它的 entry（失败返回 None）。

        语义（组件库「添加到桌面」的唯一实现，别在 UI 层再写一份）：
          - 未登记类型 → None，不落任何数据；
          - 单实例组件已存在 → **复用**那条（顺手把隐藏的显示出来），不新建；
          - 多实例 / force_new → 新建一条，按注册表登记默认锚定与默认跨度。

        新建后 `storage.save()` + `widgetsChanged` 一起发；
        复用路径也算"状态变了"（可能刚从隐藏变显示），同样发信号。
        """
        spec = widget_registry.get(wtype)
        if spec is None:
            return None
        existing = self.entries_of(wtype)
        if existing and not (spec.multi_instance or force_new):
            entry = existing[0]
            if entry.get("hidden"):
                self.toggle_entry(entry.get("id"), True)
            self.widgetsChanged.emit()
            return entry

        entry = {"id": uuid.uuid4().hex[:8], "type": wtype,
                 "hidden": False, "anchored": bool(spec.default_anchored)}
        # 尺寸：锚定组件由 catalog 的 span × cell 推导（widget_base 会覆盖），
        # 这里给的像素值只对悬浮组件生效，也给锚定态一个合理初值。
        from . import widget_catalog
        px = widget_catalog.pixel_size(self.storage, wtype)
        entry["w"], entry["h"] = px if px else (300, 220)
        if wtype == "notes":
            entry["text"] = ""          # 便签的正文键（保持历史行为）
        self.storage.widgets.append(entry)
        self._place_default(entry)
        self.storage.save()
        self._spawn(entry)
        self.widgetsChanged.emit()
        return entry

    def remove(self, entry_id: str) -> bool:
        """彻底删除一个组件（关窗口 + 从存储移除 + 通知桌面重排）。

        与 `toggle_entry(id, False)` 的区别：后者只是隐藏，条目还在
        （组件库会显示为「已添加·已隐藏」）；这里是"从桌面移除"。
        删除后必须发 `gridChanged`——锚定组件占的格子要还回去，
        否则图标会继续绕开一块空白。
        """
        w = self.widgets.pop(entry_id, None)
        if w is not None:
            self._band_guard.untrack(w)
            w.close()
        removed = False
        for i, e in enumerate(self.storage.widgets):
            if e.get("id") == entry_id:
                del self.storage.widgets[i]
                removed = True
                break
        if not removed:
            return False
        self.storage.save()
        self.widgetsChanged.emit()
        self.gridChanged.emit()
        return True

    def add_note(self):
        """兼容入口（托盘「新建便签」）：转调 add("notes")。"""
        return self.add("notes")
