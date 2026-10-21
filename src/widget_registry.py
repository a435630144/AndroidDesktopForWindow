# -*- coding: utf-8 -*-
"""组件注册表：组件的"静态事实"只在这里定义一次（v8 C1，指导文档_v8.md §2.1）。

背景：v7 之前一个组件要在四个地方登记——
`widget_layer.WIDGET_TYPES`（类型→类）、`widget_layer.WIDGET_NAMES`（类型→中文名）、
`widget_catalog.WIDGET_CATALOG`（跨度）、`WidgetLayer._place_default`（默认落位分支）。
组件库、托盘、设置页又各自再读一遍，于是"加一个组件"变成"改四个文件 + 记得改 UI"。

v8 起改为：**一份 `WidgetSpec` 声明一切静态事实**，其余模块只查询注册表。
`widget_catalog` 退化为薄壳（保留函数签名，内部转调本模块），
`widget_layer.WIDGET_TYPES` / `WIDGET_NAMES` 由本模块派生——老调用点一行不改。

依赖方向（防循环）：
    本模块 → widgets_*（具体组件类）→ widget_base → grid_flow / theme
    widget_catalog → 本模块（函数内延迟导入，因为它被 grid_flow 引用）
    widget_layer → 本模块

加入新组件只需两步：
    1. 写 `src/widgets_xxx.py`（`draw()` 纯函数 + `XxxWidget(GlassWidget)`）；
    2. 在 `REGISTRY` 末尾追加一条 `WidgetSpec(...)`。
无需改 widget_layer / 托盘 / 组件库 / 设置页。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

Span = Tuple[int, int]


@dataclass(frozen=True)
class FieldSpec:
    """组件设置项声明（纯数据，不含 Qt）。

    `widget_settings.py` 按它生成表单控件；`Entry.settings` 按 `key` 存值。
    kind ∈ {"text", "combo", "int", "bool"}。
    """

    key: str
    label: str
    kind: str = "text"
    default: object = ""
    choices: Tuple[Tuple[object, str], ...] = ()   # ((值, 显示文字), ...)
    placeholder: str = ""
    hint: str = ""


@dataclass(frozen=True)
class WidgetSpec:
    """一种组件的声明。字段都是"不会随运行变化"的事实。"""

    type: str
    name: str
    summary: str
    factory: Callable
    spans: Tuple[Span, ...]
    category: str = "其他"
    default_anchored: bool = True
    interactive: bool = False        # 含输入框 → 去掉 NOACTIVATE，可获键盘焦点
    multi_instance: bool = False     # 是否允许同时放多个
    settings: Tuple[FieldSpec, ...] = ()
    preview: Optional[Callable] = None   # (painter, rect, dpr) -> None，缺省走兜底卡

    @property
    def default_span(self) -> Span:
        return self.spans[0]


def _build_registry() -> Dict[str, WidgetSpec]:
    # 延迟到函数内导入：组件模块会 import widget_base，而 widget_base 在
    # 方法内延迟引用 widget_catalog → 本模块。函数内导入让模块级依赖保持单向。
    from .widgets_clock import ClockWidget
    from .widgets_notes import NotesWidget
    from .widgets_panel import DesktopPanel
    from .widget_monitor import MonitorWidget, draw_preview as _preview_monitor
    from .widgets_todo import TodoWidget, draw_preview as _preview_todo

    specs = [
        WidgetSpec(
            type="clock",
            name="时钟",
            summary="时间与日期，随格子大小自动缩放字号",
            factory=ClockWidget,
            spans=((2, 2),),
            category="时间",
            default_anchored=True,
        ),
        WidgetSpec(
            type="notes",
            name="便签",
            summary="随手记，输入即自动保存",
            factory=NotesWidget,
            spans=((2, 2),),
            category="效率",
            default_anchored=False,   # 含输入框：锚定态 NOACTIVATE 拿不到焦点
            interactive=True,
            multi_instance=True,
        ),
        WidgetSpec(
            type="panel",
            name="桌面面板",
            summary="常用应用与文件夹的集合面板",
            factory=DesktopPanel,
            spans=((3, 4),),
            category="效率",
            default_anchored=True,
        ),
        WidgetSpec(
            type="monitor",
            name="系统监控",
            summary="CPU / 内存 / 磁盘实时占用（纯本地，不联网）",
            factory=MonitorWidget,
            spans=((2, 2), (4, 2)),
            category="系统",
            default_anchored=True,
            preview=_preview_monitor,
        ),
        WidgetSpec(
            type="todo",
            name="待办清单",
            summary="勾选式待办，回车即加，自动保存",
            factory=TodoWidget,
            spans=((2, 2), (2, 4)),
            category="效率",
            default_anchored=False,   # 含输入框，锚定态拿不到键盘焦点
            interactive=True,
            multi_instance=True,
            preview=_preview_todo,
        ),
    ]
    return {s.type: s for s in specs}


REGISTRY: Dict[str, WidgetSpec] = _build_registry()


# ---------------------------------------------------------------- 查询 API

def get(wtype: str) -> Optional[WidgetSpec]:
    """按类型取声明；未登记返回 None（调用方自行决定回退策略）。"""
    return REGISTRY.get(wtype) if isinstance(wtype, str) else None


def all_specs() -> List[WidgetSpec]:
    """全部组件，按登记顺序（= 组件库默认展示顺序）。"""
    return list(REGISTRY.values())


def names() -> Dict[str, str]:
    """类型 → 中文名（`widget_layer.WIDGET_NAMES` 由它派生）。"""
    return {t: s.name for t, s in REGISTRY.items()}


def types() -> List[str]:
    return list(REGISTRY.keys())


def spans(wtype: str) -> List[Span]:
    """可用跨度列表（第一项为默认）；未登记返回 []（对齐旧 catalog 语义）。"""
    spec = get(wtype)
    return [tuple(s) for s in spec.spans] if spec else []


def default_span(wtype: str) -> Optional[Span]:
    spec = get(wtype)
    return tuple(spec.spans[0]) if spec else None


def categories() -> List[str]:
    """分类列表，按"首次登记顺序"去重（组件库左栏顺序）。"""
    out: List[str] = []
    for s in REGISTRY.values():
        if s.category not in out:
            out.append(s.category)
    return out


def specs_in(category: str) -> List[WidgetSpec]:
    """某分类下的组件；`category` 传 "全部" 或空串返回全部。"""
    if not category or category == "全部":
        return all_specs()
    return [s for s in REGISTRY.values() if s.category == category]


def register(spec: WidgetSpec) -> None:
    """登记/覆盖一个组件（测试与将来的外部插件用）。"""
    REGISTRY[spec.type] = spec


def set_spans(wtype: str, spans_) -> None:
    """改某组件的可用跨度（测试/诊断用；正式能力请改 REGISTRY 里的声明）。

    `WidgetSpec` 是 frozen dataclass，只能替换不能原地改——这里用
    `dataclasses.replace` 生成新声明并覆盖，避免调用方各自 new 一遍丢字段。
    """
    from dataclasses import replace
    spec = get(wtype)
    if spec is None:
        raise KeyError(wtype)
    REGISTRY[wtype] = replace(spec, spans=tuple(tuple(s) for s in spans_))
