# 实施计划：手机桌面化改造 M1 + M2

> 依据 `design.md` · 2026-10-18 · 每任务 2~5 分钟，TDD 红绿循环

## 任务总览

| ID | 任务 | 文件 | 验证 |
|---|---|---|---|
| T1 | 红：写 test_grid_flow.py（先失败） | tests/test_grid_flow.py | 运行见 FAIL |
| T2 | 绿：实现 grid_flow.py | src/grid_flow.py | 测试全绿 |
| T3 | 绿：cell_size/snap_point + 单测补齐 | src/grid_flow.py | 测试全绿 |
| T4 | AppIcon：位置动画 + hide-on-drag | src/iconwidget.py | smoke 过 |
| T5 | AppIcon：dwell-merge（450ms） | src/iconwidget.py | smoke 过 |
| T6 | DesktopWindow：dragMoveEvent + _reflow_preview | src/desktop_window.py | probe15 G1 |
| T7 | DesktopWindow：drop commit / cancel 回退 | src/desktop_window.py | probe15 G2/G3 |
| T8 | DesktopWindow：_drop_internal 改置换语义 | src/desktop_window.py | probe15 G2 |
| T9 | 红→绿：锚定模式单测（grid_flow.snap_point） | tests/test_grid_flow.py | 全绿 |
| T10 | FloatingWidget：anchored 模式实现 | src/widget_base.py | smoke 过 |
| T11 | WidgetLayer.set_anchored + 右键菜单 | src/widget_layer.py, widget_base.py | smoke 过 |
| T12 | probe15 实机验证 + 截图目检 | tools/probe15.py | G1-G8 |
| T13 | DEVLOG 追加 Day 4 + README 更新 | DEVLOG.md | — |

## T1 详细：先写失败测试

`tests/test_grid_flow.py` 用例清单：

1. `test_reflow_preserves_cell_set` — 任意拖动不改变占用格集合
2. `test_drag_onto_occupied_inserts_before` — 拖到占用格 → 插到占用者之前
3. `test_drag_onto_empty_beyond_all_appends` — 拖到末尾空格 → 追加到队尾
4. `test_drag_back_restores_order` — 拖出去再拖回 → 恢复原顺序
5. `test_drag_earlier_shifts_others_down` — 往前拖 → 后者整体后移一格
6. `test_same_cell_is_identity` — 原地拖动 → 顺序不变
7. `test_cols_clamped` — 目标 col 越界被夹紧
8. `test_single_icon` — 只有 1 个图标
9. `test_no_overlap_after_random_drags` — 50 次随机拖动无重叠
10. `test_reading_order_stable` — 相同 (row,col) 不可能（占用格唯一）
11. `test_snap_point_aligns_to_grid` — 吸附点对齐网格
12. `test_snap_point_clamped_to_screen` — 吸附不越界

## T2-T3 详细：grid_flow.py 契约

```python
def reading_order(entries, cols) -> list[dict]      # 按 (row, col) 排序
def occupied_cells(entries, cols) -> list[tuple]    # 排序去重后的占用格
def reflow_order(entries, cols, dragged_id, target) -> list[str] | None
    # target=(col,row)；越界夹紧；dragged 不存在返回 None
    # 返回：新的 entry_id 阅读序
def apply_order(entries, order) -> None             # 就地写 col/row
def cell_size(storage) -> tuple[int, int]           # 与 DesktopWindow._cell() 同源
def origin() -> tuple[int, int]
def snap_point(storage, x, y, screen) -> tuple[int, int]
```

`cell_size` 必须与 `DesktopWindow._cell()` 数值一致——T6 时把 `_cell()` 改为委托 `grid_flow.cell_size()`，删掉重复实现。

## T6-T8 详细：DesktopWindow 改动面

```python
def dragMoveEvent(self, e):                     # 新增
    if not e.mimeData().hasFormat(MIME_TYPE): return
    self._reflow_preview(payload, self._cell_at(e.position().toPoint()))

def _reflow_preview(self, dragged_id, cell):
    if dragged_id 不在布局 or 多选拖动: return
    order = grid_flow.reflow_order(self.storage.layout, cols, dragged_id, cell)
    if order == self._preview_order: return     # 无变化不重算（省 CPU）
    grid_flow.apply_order(...)  # 只写内存 preview，不 save
    for icon: icon.animate_to(grid_flow 目标格)  # 弹簧

def _commit_preview(self):   # drop 落格内
    self.storage.save()      # preview 已写入 layout
    self._preview_order = None

def _cancel_preview(self):   # drop 落窗外
    按 storage 里的 col/row 动画回退
```

注意：`_drop_internal` 中 `occupant` 交换逻辑整体删除，改为"若已有 preview 则 commit，否则按落点算一次 reflow 再 commit"。

## T10-T11 详细：锚定小组件

- `FloatingWidget.__init__` 读 `entry.get("anchored", False)`
- `paintEvent` 分支：anchored 时画 34% tint 圆角、无 BORDER、跳过 × 与手柄
- `_close_rect()`/`_grip_rect()` 在 anchored 时返回空 QRect（天然不命中）
- `mouseMoveEvent`：anchored 时不改 cursor
- `mouseReleaseEvent`：anchored 时 `snap_point()` + 吸附动画
- `contextMenuEvent`：新增菜单（锚定/悬浮互换、隐藏、关闭）
- `WidgetLayer.set_anchored(entry_id, on)`：改 entry + 重建该 widget

## T12 详细：probe15.py 断言

| 编号 | 断言 |
|---|---|
| G1 | 拖动中（未松手）至少 1 个非源图标位置已偏离原格 → 实时性 |
| G2 | 松手后占用格集合 == 拖动前集合 |
| G3 | 松手后无重叠 |
| G4 | 拖到窗外取消 → 位置回退 |
| G5 | dwell 450ms 后拖到图标上 → mergeRequested 触发（文件夹生成） |
| G6 | dwell 未满即松手 → 不合并，发生置换 |
| G7 | 锚定时钟卡片外点击穿透（HTTRANSPARENT） |
| G8 | 锚定时钟松手后坐标对齐网格 |

## 里程碑门禁

- T2 完成后：`pytest tests/test_grid_flow.py -q` 全绿才进 T4
- T8 完成后：`tests/smoke_test.py` 27/27 才进 T9
- T12 完成后：`tools/verify_live.py` 不退才进 T13
