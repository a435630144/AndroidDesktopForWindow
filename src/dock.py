# -*- coding: utf-8 -*-
"""Dock 栏（v10 C3，反馈 17）——纯函数层 + 窗口层。

用户诉求（`docs/指导文档_v10.md` §4.3）：底部一排圆角应用图标（macOS Dock
语言），默认底部，可切顶部/左右，设置里可开关，**开启后网格尺寸重新计算**。

## 三条铁律

1. **可用区扣除只有一个入口**：`storage_inset()` -> `grid_metrics.compute(inset=…)`。
   **不在 `solve_dims` 里塞 if**——否则"可用区"会有第二份定义，网格公式
   迟早与 Dock 各算各的（v7 双源漂移的教训）。
2. **Dock 只是快捷方式副本**：拖入不删网格条目，拖出也只删 `dock_items`
   里那一条。桌面布局永不被 Dock 改写（零数据风险，且幂等）。
3. **只收应用**（Q2 拍板）：文件 / 文件夹 / 组件一律拒绝，`entry_is_app()`
   是唯一判据，UI 层不许自己再写一份。

## 尺寸模型

图标基准 `DOCK_ICON` 逻辑像素 **只乘 `ui_scale()`**（B2 的单一旋钮，
dpr 由 Qt 用一次）。条带厚度预留了 hover 放大空间，所以 hover 时图标
仍在窗口内——**不做 macOS 式"跳出条带"**：分层窗超出窗口的绘制会被
裁剪，要做就得把窗口开大，而多出的透明区会挡住网格图标的点击
（"透明区穿透不是普遍真理"，坑 #39）。v11 若要，得先解决命中测试。

## 分层（与其它模块的关系）

    纯函数（本文件上半）：inset / metrics / bar_rect / item_rect / hit_index
                          move_item / normalize_items / entry_is_app
    DockWindow：绘制 + hover 放大 + 拖入 / 排序 / 拖出
    DesktopWindow：`storage_inset()` 扣可用区 -> refresh_grid
"""
from __future__ import annotations

from typing import NamedTuple

from PySide6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, QRect,
                            QRectF, Qt, Property, Signal)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from . import appsource, effects, theme, win32_layer
from .iconwidget import MIME_TYPE

# ---------------------------------------------------------------- 常量

POSITIONS = ("bottom", "top", "left", "right")

POSITION_LABELS = (("bottom", "底部"), ("top", "顶部"),
                   ("left", "左侧"), ("right", "右侧"))

DOCK_ICON = 40          # 图标基准边长（逻辑 px，100% 缩放）
DOCK_GAP = 6            # 图标间距（图标 PNG 自带透明边，视觉间隙约 2 倍）
DOCK_PAD = 8            # 条带内边距（hover 图标与条带边留出呼吸）
DOCK_HOVER = 1.28       # hover 放大倍数（1.0 = 不放大；1.12 时肉眼几乎看不出）
MIN_SLOTS = 5           # 空态/少量条目时按 5 个槽位撑住长度（条形不会缩成一点）
DOCK_MAX_ITEMS = 24     # 上限（再多滚不动，靠拖出/排序管理；
                        # 与待办清单的 MAX_ITEMS 同名会撞文档门禁的常量表）

HOVER_MS = 160          # hover 放大动画时长（spring_curve，禁近似曲线）
DRAG_OUT_PX = 36        # 拖出多远算"移出 Dock"（松手即移除）


class DockMetrics(NamedTuple):
    """一次 Dock 几何快照（逻辑像素）。"""

    icon: int
    gap: int
    pad: int
    thickness: int      # 条带厚度（副轴）
    length: int         # 条带长度（主轴）
    slots: int = 0      # 参与长度计算的槽位数（含空态撑开的）


# ---------------------------------------------------------------- 纯函数

def _scale(ui_scale) -> float:
    """收敛用户缩放到 0.6~2.0（与 `Storage.user_icon_scale` 同域）。"""
    try:
        s = float(ui_scale)
    except (TypeError, ValueError):
        return 1.0
    return min(2.0, max(0.6, s))


def metrics(ui_scale, count: int) -> DockMetrics:
    """Dock 几何：图标/间距/内边距只随 `ui_scale` 线性放大。

    条带厚度 = pad×2 + hover 后的图标边长——**预留放大空间**是有意的：
    hover 时图标在条带内长大，永远不出窗口（见模块 docstring）。
    """
    s = _scale(ui_scale)
    icon = max(16, int(round(DOCK_ICON * s)))
    gap = max(3, int(round(DOCK_GAP * s)))
    pad = max(2, int(round(DOCK_PAD * s)))
    thickness = pad * 2 + int(round(icon * DOCK_HOVER))
    slots = max(MIN_SLOTS, min(DOCK_MAX_ITEMS, max(0, int(count))))
    length = pad * 2 + slots * icon + (slots - 1) * gap
    return DockMetrics(icon, gap, pad, thickness, length, slots)


def normalize_position(position) -> str:
    """位置收敛：非法值一律回退 bottom（不静默改网格另一个方向）。"""
    p = str(position or "").strip().lower()
    return p if p in POSITIONS else "bottom"


def inset(enabled, position, thickness) -> tuple:
    """Dock 占用的屏幕边条带 -> (left, top, right, bottom)。

    **这是"网格可用区"的唯一扣除入口**（本模块的对外契约）。
    `grid_metrics.compute(inset=…)` 只认这个四元组，不知道 Dock 是什么。
    """
    if not enabled:
        return (0, 0, 0, 0)
    t = max(0, int(thickness))
    if t == 0:
        return (0, 0, 0, 0)
    pos = normalize_position(position)
    if pos == "top":
        return (0, t, 0, 0)
    if pos == "left":
        return (t, 0, 0, 0)
    if pos == "right":
        return (0, 0, t, 0)
    return (0, 0, 0, t)


def usable_size(size, ins) -> tuple:
    """可用区尺寸（扣掉四边 inset）——最小 1，避免除零。"""
    w = max(1, int(size[0]) - int(ins[0]) - int(ins[2]))
    h = max(1, int(size[1]) - int(ins[1]) - int(ins[3]))
    return (w, h)


def bar_rect(size, position, m: DockMetrics) -> tuple:
    """条带矩形 (x, y, w, h)：贴对应边 + 沿副轴居中。"""
    W, H = int(size[0]), int(size[1])
    pos = normalize_position(position)
    if pos in ("bottom", "top"):
        w, h = min(m.length, W), m.thickness
        x = max(0, (W - w) // 2)
        y = H - h if pos == "bottom" else 0
        return (x, y, w, h)
    w, h = m.thickness, min(m.length, H)
    y = max(0, (H - h) // 2)
    x = W - w if pos == "right" else 0
    return (x, y, w, h)


def item_rect(bar, position, m: DockMetrics, index: int) -> tuple:
    """第 index 个图标的矩形（不含 hover 缩放，只算基准位）。"""
    x, y, w, h = bar
    pos = normalize_position(position)
    step = m.icon + m.gap
    if pos in ("bottom", "top"):
        ix = x + m.pad + int(index) * step
        iy = y + (h - m.icon) // 2
    else:
        ix = x + (w - m.icon) // 2
        iy = y + m.pad + int(index) * step
    return (ix, iy, m.icon, m.icon)


def hit_index(bar, position, m: DockMetrics, count: int,
              pos, enabled: bool = True):
    """屏幕/窗口坐标点 -> 命中的条目索引；间隙、条带外、关闭态一律 None。

    只认**图标矩形**（不认整条条带）：条带上留白很多，点空白不该误开应用。
    """
    if not enabled or count <= 0:
        return None
    px, py = int(pos[0]), int(pos[1])
    for i in range(min(int(count), DOCK_MAX_ITEMS)):
        x, y, w, h = item_rect(bar, position, m, i)
        if x <= px < x + w and y <= py < y + h:
            return i
    return None


def move_item(items, src: int, dst: int) -> list:
    """把 src 位置的条目移动到 dst（返回新列表，**不改入参**）。

    越界一律夹紧到 [0, n-1]——拖拽时指针可能在条带外，夹紧比"拒绝移动"
    更符合手感（用户看到的是"拖到最前面"）。
    """
    out = [dict(i) for i in items]
    n = len(out)
    if n <= 1:
        return out
    a = max(0, min(n - 1, int(src)))
    b = max(0, min(n - 1, int(dst)))
    if a == b:
        return out
    out.insert(b, out.pop(a))
    return out


def normalize_items(raw) -> list:
    """把 settings 里的任意脏数据收敛成合法条目列表。

    规则：必须是 dict、`name` 与 `target` 都非空、同 (name, target) 去重、
    最多 `DOCK_MAX_ITEMS` 条。**额外字段原样保留**（未来加 kind/args 不必迁移）。
    """
    if not isinstance(raw, (list, tuple)):
        return []
    out, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        target = str(item.get("target") or "").strip()
        if not name or not target:
            continue
        key = (name, target)
        if key in seen:
            continue
        seen.add(key)
        entry = dict(item)
        entry["name"], entry["target"] = name, target
        entry.setdefault("icon_path", target)
        out.append(entry)
        if len(out) >= DOCK_MAX_ITEMS:
            break
    return out


def entry_is_app(entry) -> bool:
    """桌面布局条目能否进 Dock（Q2：只有应用能）。

    - `type == "app"` 且 `app.kind != "file"`（桌面文件/文件夹克隆是 kind=file）
    - 文件夹（type=folder）、组件（type=widget）一律拒
    """
    if not isinstance(entry, dict):
        return False
    if entry.get("type") != "app":
        return False
    app = entry.get("app")
    if not isinstance(app, dict):
        return False
    if str(app.get("kind") or "app") == "file":
        return False
    return bool(app.get("name") and app.get("target"))


def item_from_entry(entry) -> dict:
    """布局条目 -> Dock 条目（只取自包含的最小字段，重启后仍能启动）。"""
    app = entry.get("app") or {}
    target = str(app.get("target") or "")
    return {"name": str(app.get("name") or ""),
            "target": target,
            "icon_path": str(app.get("icon_path") or target)}


def load_items(storage) -> list:
    """从 settings 读条目（永远返回规范化后的列表，不会 None）。"""
    try:
        raw = storage.get_setting("dock_items")
    except Exception:      # noqa: BLE001 —— 设置层异常不该让 Dock 消失
        return []
    return normalize_items(raw)


def save_items(storage, items) -> list:
    """写回 settings（先规范化再落盘）——幂等，三次往返逐字段相等。"""
    norm = normalize_items(items)
    storage.set_setting("dock_items", [dict(i) for i in norm])
    return norm


def storage_inset(storage) -> tuple:
    """当前设置下的可用区扣除 —— **网格唯一入口**（见模块 docstring 铁律 1）。"""
    if not bool(storage.get_setting("dock_enabled")):
        return (0, 0, 0, 0)
    m = metrics(storage.ui_scale(), len(load_items(storage)))
    return inset(True, storage.get_setting("dock_position"), m.thickness)


def seed_from_layout(storage, limit: int = 6) -> list:
    """首次启用时用桌面上现成的应用把 Dock 填上（规格 §4.3-3「初始为常见应用」）。

    只做一次（`dock_seeded` 标记）：用户手动清空 Dock 后不会被重新塞满——
    "只增不删、幂等"的另一面是"不擅自重建用户改过的集合"。
    """
    items = load_items(storage)
    if bool(storage.get_setting("dock_seeded")):
        return items
    if not items:
        picked = []
        for entry in list(getattr(storage, "layout", None) or []):
            if entry_is_app(entry):
                picked.append(item_from_entry(entry))
                if len(picked) >= max(1, int(limit)):
                    break
        items = save_items(storage, picked)
    storage.set_setting("dock_seeded", True)
    storage.save()
    return items


# ---------------------------------------------------------------- 窗口

class DockWindow(QWidget):
    """Dock 条带窗口（独立分层窗，层号 `BAND_LAYER_DOCK`）。

    自绘而非子控件：图标数量/排序/hover 让位都在一次 `paintEvent` 里完成，
    没有"子控件位置不同步"的第二份真相（与图标层同构）。
    """

    # 条目集合变了（加/删/排序）——调用方据此重算几何/落盘
    changed = Signal()
    # 用户点了某个条目（应用启动后），便于埋点/提示
    launched = Signal(str)

    def __init__(self, storage, parent=None):
        super().__init__(parent)
        self.storage = storage
        self._items = load_items(storage)
        self._avail = (1920, 1080)
        self._bar = (0, 0, 0, 0)
        self._m = metrics(storage.ui_scale(), len(self._items))
        self._position = normalize_position(
            storage.get_setting("dock_position"))
        self._hover_index = None
        self._hover_t = 0.0
        self._anim = None
        # 拖动排序状态
        self._press_pos = None
        self._press_index = None
        self._drag_index = None
        self._drag_out = False
        self._drop_highlight = False

        flags = (Qt.FramelessWindowHint | Qt.Tool
                 | Qt.WindowDoesNotAcceptFocus)
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("Dock 栏")

    # ---------- 几何 ----------
    @property
    def enabled(self) -> bool:
        return bool(self.storage.get_setting("dock_enabled"))

    def position(self) -> str:
        return self._position

    def current_metrics(self) -> DockMetrics:
        return self._m

    def apply_geometry(self, avail_size) -> tuple:
        """按可用区重算条带并落位；未开启则隐藏（返回 (0,0,0,0)）。"""
        self._avail = (max(1, int(avail_size[0])), max(1, int(avail_size[1])))
        self._position = normalize_position(
            self.storage.get_setting("dock_position"))
        self._m = metrics(self.storage.ui_scale(), len(self._items))
        if not self.enabled:
            self.hide()
            self._bar = (0, 0, 0, 0)
            return self._bar
        self._bar = bar_rect(self._avail, self._position, self._m)
        self.setGeometry(*self._bar)
        if not self.isVisible():
            self.show()
        self.update()
        return self._bar

    def is_visible_bar(self) -> bool:
        """条带当前是否可见（启用 + 有窗口）——空态也算可见（占位提示）。"""
        return self.enabled and self.isVisible() and self._bar[2] > 0

    # ---------- 条目 ----------
    def items(self) -> list:
        return [dict(i) for i in self._items]

    def set_items(self, items, save: bool = True):
        """替换条目集合（规范化 + 可选落盘 + 重排几何）。"""
        self._items = normalize_items(items)
        if save:
            save_items(self.storage, self._items)
            self.storage.save()
        if self._hover_index is not None and self._hover_index >= len(self._items):
            self._hover_index = None
            self._set_hover_t(0.0)
        self.apply_geometry(self._avail)
        self.changed.emit()

    def add_item(self, item: dict) -> bool:
        """追加一条（拖入路径）；重复不追加，返回是否真的加了。"""
        if not isinstance(item, dict):
            return False
        norm = normalize_items([item])
        if not norm:
            return False
        if any(i.get("target") == norm[0]["target"] for i in self._items):
            return False
        self.set_items(self._items + norm)
        return True

    def remove_at(self, index: int):
        if 0 <= int(index) < len(self._items):
            rest = list(self._items)
            del rest[int(index)]
            self.set_items(rest)

    def set_drop_highlight(self, on: bool):
        """外部拖拽悬停高亮（桌面窗口在 `dragMoveEvent` 里转发）。

        桌面窗口与 Dock 各有一条 drag 路径（命中投递取决于拖影下的窗口），
        高亮状态必须收在一处，否则两条路径同时亮/同时灭会闪。
        """
        on = bool(on)
        if on != self._drop_highlight:
            self._drop_highlight = on
            self.update()

    # ---------- hover 放大（单一动画驱动全部图标） ----------
    def _get_hover_t(self):
        return self._hover_t

    def _set_hover_t(self, v):
        self._hover_t = max(0.0, min(1.0, float(v)))
        self.update()

    hover_t = Property(float, _get_hover_t, _set_hover_t)

    def _animate_hover(self, to: float):
        if self._anim is not None:
            self._anim.stop()
        if effects.reduced_motion():
            self._set_hover_t(to)
            return
        anim = QPropertyAnimation(self, b"hover_t", self)
        anim.setDuration(effects.dur(HOVER_MS))
        anim.setStartValue(self._hover_t)
        anim.setEndValue(float(to))
        # 弹簧曲线（项目铁律：禁 OutBack/OutCubic 近似）
        anim.setEasingCurve(effects.spring_curve(1.0, HOVER_MS))
        anim.start()
        self._anim = anim

    def _spread(self, index: int) -> int:
        """hover 时相邻图标的让位位移（像素，正 = 向后推）。"""
        if self._hover_index is None or self._hover_t <= 0.001:
            return 0
        d = abs(int(index) - int(self._hover_index))
        if d == 0 or d > 2:
            return 0
        grow = self._m.icon * (DOCK_HOVER - 1.0) * self._hover_t
        falloff = 0.5 if d == 1 else 0.18
        shift = int(round(grow * falloff))
        return shift if index > self._hover_index else -shift

    # ---------- 绘制 ----------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        radius = min(rect.width(), rect.height()) / 2.0
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        p.fillPath(path, theme.SURFACE)
        p.setPen(QPen(theme.BORDER, 1))
        p.drawPath(path)

        if not self._items:
            self._paint_empty_hint(p, rect)
            return

        dpr = float(self.devicePixelRatioF() or 1.0)
        # 先画非 hover 项（含让位），hover 项最后画——保证放大后的图标
        # 不被邻居盖住（绘制顺序即层序）
        order = [i for i in range(len(self._items)) if i != self._hover_index]
        if self._hover_index is not None and self._hover_index < len(self._items):
            order.append(self._hover_index)
        for i in order:
            self._paint_item(p, i, dpr)

        if self._drop_highlight:
            p.setPen(QPen(theme.ACCENT, 2))
            p.drawPath(path)

    def _paint_empty_hint(self, p, rect):
        p.setPen(QPen(theme.TEXT_FAINT, 1))
        f = theme.ui_font(max(11, int(round(12 * _scale(self.storage.ui_scale())))))
        p.setFont(f)
        p.drawText(rect, Qt.AlignCenter, "拖入应用")

    def _paint_item(self, p, i, dpr):
        m = self._m
        x, y, w, h = item_rect(self._bar, self._position, m, i)
        # 条带可能比窗口本身偏移（窗口就是条带，故相对坐标减 bar 原点）
        lx = x - self._bar[0]
        ly = y - self._bar[1]
        grow = 0.0
        if i == self._hover_index:
            grow = m.icon * (DOCK_HOVER - 1.0) * self._hover_t
        # 尺寸量化到 2px 步进：hover 动画每帧都会变，不量化会让
        # `appsource.icon_pixmap` 的 size 缓存键爆炸（每帧新建 pixmap）
        size = max(16, int(round((m.icon + grow) / 2.0)) * 2)
        shift = self._spread(i)
        horizontal = self._position in ("bottom", "top")
        if horizontal:
            cx = lx + m.icon // 2 + shift
            cy = ly + m.icon // 2
        else:
            cx = lx + m.icon // 2
            cy = ly + m.icon // 2 + shift
        target = QRect(int(cx - size // 2), int(cy - size // 2), size, size)

        dropping_out = (self._drag_out and i == self._drag_index)
        if dropping_out:
            p.setOpacity(0.45)
        try:
            pm = appsource.icon_pixmap(self._items[i], size, dpr)
        except Exception:      # noqa: BLE001 —— 单个坏条目不该让整条画不出来
            pm = None
        if pm is not None and not pm.isNull():
            p.drawPixmap(target, pm)
        else:
            self._paint_fallback(p, target, self._items[i])
        p.setOpacity(1.0)

        # hover 项下方的小圆点（macOS 的"运行中"指示位置，这里表示"当前指向"）
        if i == self._hover_index and self._hover_t > 0.2:
            dot = max(2, int(round(3 * self._hover_t)))
            p.setPen(Qt.NoPen)
            p.setBrush(theme.ACCENT)
            if horizontal:
                p.drawEllipse(QPoint(cx, ly + m.icon + m.pad // 2 + dot), dot, dot)
            else:
                p.drawEllipse(QPoint(lx + m.icon + m.pad // 2, cy), dot, dot)
            p.setBrush(Qt.NoBrush)

    def _paint_fallback(self, p, rect, item):
        """取不到图标时的字母占位（与图标层同一套观感）。"""
        f = theme.ui_font(max(11, rect.width() // 2), bold=True)
        p.setFont(f)
        p.setPen(theme.TEXT)
        ch = (str(item.get("name") or "?").strip() or "?")[0]
        p.drawText(rect, Qt.AlignCenter, ch)

    # ---------- 鼠标：hover / 点击启动 / 拖动排序 ----------
    def _local_index(self, pos):
        return hit_index(self._bar, self._position, self._m,
                         len(self._items), (pos.x(), pos.y()),
                         enabled=self.enabled)

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        idx = self._local_index(pos)
        if idx != self._hover_index:
            self._hover_index = idx
            self._animate_hover(1.0 if idx is not None else 0.0)
        # 拖动排序
        if self._press_index is not None and e.buttons() & Qt.LeftButton:
            if self._drag_index is None:
                if (pos - self._press_pos).manhattanLength() >= 6:
                    self._drag_index = self._press_index
                    self.setCursor(Qt.ClosedHandCursor)
            if self._drag_index is not None:
                self._drag_out = self._outside(pos)
                target = self._drop_target(pos)
                if target is not None and target != self._drag_index:
                    self._items = move_item(self._items, self._drag_index, target)
                    self._drag_index = target
                    self._hover_index = target
                    save_items(self.storage, self._items)
                    self.update()
        self.update()

    def _outside(self, pos) -> bool:
        x, y, w, h = self._bar
        g = QRect(x - DRAG_OUT_PX, y - DRAG_OUT_PX,
                  w + DRAG_OUT_PX * 2, h + DRAG_OUT_PX * 2)
        return not g.contains(pos.x(), pos.y())

    def _drop_target(self, pos):
        """拖动中的落点索引：按住某图标时按"中心越过邻居中心"判换位。

        用中心比较而不是矩形命中——拖动时被拖的图标本身跟着指针走，
        矩形命中会在自己身上打转（永远等于自己）。
        """
        if self._drag_index is None:
            return None
        horizontal = self._position in ("bottom", "top")
        v = pos.x() if horizontal else pos.y()
        m = self._m
        origin = (self._bar[0] if horizontal else self._bar[1]) + m.pad
        step = m.icon + m.gap
        if step <= 0:
            return None
        if self._outside(pos):
            return None
        idx = int((v - origin) // step)
        return max(0, min(len(self._items) - 1, idx))

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = e.position().toPoint()
        self._press_pos = pos
        self._press_index = self._local_index(pos)
        self._drag_index = None
        self._drag_out = False
        e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = e.position().toPoint()
        pressed, dragged = self._press_index, self._drag_index
        self._press_index = None
        self._press_pos = None
        self._drag_index = None
        self._drag_out = False
        self.unsetCursor()
        self.setCursor(Qt.PointingHandCursor)
        if dragged is not None:
            # 拖出条带松手 = 从 Dock 移除（桌面条目原样保留，铁律 2）
            if self._outside(pos):
                self.remove_at(dragged)
            else:
                save_items(self.storage, self._items)
                self.storage.save()
                self.changed.emit()
            self.update()
            return
        if pressed is not None and pressed < len(self._items):
            self._launch(self._items[pressed])
        self.update()

    def _launch(self, item):
        try:
            appsource.launch(item)
        except Exception:      # noqa: BLE001 —— 目标被删/无权限：静默（不炸桌面）
            return
        self.launched.emit(str(item.get("name") or ""))

    def leaveEvent(self, _e):
        self._hover_index = None
        self._animate_hover(0.0)
        self.update()

    # ---------- 外部拖入（从网格拖应用进来） ----------
    def dragEnterEvent(self, e):
        if not e.mimeData().hasFormat(MIME_TYPE):
            return
        self._drop_highlight = True
        self.update()
        e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MIME_TYPE):
            e.acceptProposedAction()

    def dragLeaveEvent(self, _e):
        self._drop_highlight = False
        self.update()

    def dropEvent(self, e):
        self._drop_highlight = False
        self.update()
        md = e.mimeData()
        if not md.hasFormat(MIME_TYPE):
            return
        try:
            eid = md.data(MIME_TYPE).data().decode()
        except Exception:      # noqa: BLE001
            return
        entry = None
        try:
            entry = self.storage.find_entry(eid)
        except Exception:      # noqa: BLE001
            entry = None
        if not entry_is_app(entry):
            e.ignore()          # Q2：文件/文件夹/组件不收
            return
        if self.add_item(item_from_entry(entry)):
            e.acceptProposedAction()
            self.storage.save()
        else:
            e.acceptProposedAction()

    # ---------- 桌面带 ----------
    def showEvent(self, e):
        super().showEvent(e)
        # 层号 = DOCK：压在组件之上（组件层 20）、文件夹幕布之下（30）——
        # 幕布/弹窗是"模态"的，必须能盖住 Dock。
        self.attached = win32_layer.attach_to_desktop(
            self, layer=win32_layer.BAND_LAYER_DOCK)
        if self.attached:
            win32_layer.enforce_band_order()
