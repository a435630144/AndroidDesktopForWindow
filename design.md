# 设计文档：手机桌面化改造（Live Reflow + 锚定小组件）

> 项目：DesktopOrganizer（`D:\OneDrive\自己的笔记本电脑\桌面\temp\AndroidDesktopForWindow`）
> 阶段：Phase 1 头脑风暴产出 · 2026-10-18
> 目标：把桌面整理从「Windows Fences 风」推向「手机桌面风」——核心是**图标滑动让位**与**小组件融入桌面**。

---

## 1. 需求澄清结论（已与用户确认）

| # | 决策点 | 结论 |
|---|---|---|
| D1 | 让位时机 | **实时重排**：拖动过程中被越过的图标立即滑向新格，松手直接落位 |
| D2 | 网格模型 | **稀疏网格 + 局部让位**：保留 col/row 与空位，state.json 兼容，零迁移 |
| D3 | 非悬浮含义 | **不置顶、跟随桌面层级**：小组件被应用窗口遮挡，点空白处不抢焦点 |
| D4 | 交付范围 | **核心先行分阶段**：M1 让位引擎 → M2 锚定小组件框架 + 1 个组件 → M3 扩充 |

用户原话约束（必须满足）：
- 「桌面的图标也不是一定要克隆」→ 克隆降级为可选，**映射真实目录**成为一等公民（承接 DESKBOX_REFERENCE P0-①）。
- 「更方便的控制图标的移动效果」→ 放弃"瞬间交换"，全面动画化。
- 「最终目标：手机桌面 UI，各种精美小组件 + app 图标 + 动画交互」。

---

## 2. M1：实时滑动让位（Live Reflow）

### 2.1 现状病灶

`DesktopWindow._drop_internal()` 目前的做法：

```python
occupant = self.storage.occupant(col, row, exclude_id=primary["id"])
if occupant is not None: occupant["col"], occupant["row"] = old_col, old_row   # 瞬间交换
primary["col"], primary["row"] = col, row
self.storage.save(); self.rebuild()          # rebuild = 全部图标瞬间跳到新位置
```

两个问题：① **零动画**，位置跳变；② 交换语义（占用者去 dragged 的老格）在稀疏网格下不自然——Windows 原生桌面也是这套，所以用户明确说"win 的机制是瞬间下移"。

### 2.2 核心算法：占用格集合上的置换（permutation over occupied cells）

**关键洞察**：稀疏网格的"让位"不需要解碰撞，只需要在**固定的占用格集合**上重新分配图标。

```
cells = sorted(occupied cells by (row, col))        # 拖动全程不变
order = [icon ids sorted by (row, col)]             # 当前阅读序
new_order = order 去掉 dragged，再按目标格插入
new_layout = zip(new_order, cells)                  # 图标 → 新格
```

性质（可测试）：
- 占用格集合不变 → **永不重叠、永不丢图标、空位保留**
- O(n log n)，每次 dragMove 全量重算无压力（n ≤ 数百）
- 跨行拖动、拖到空格、拖到已占用格、拖回原位，全部统一处理

插入位置规则：
- 目标格被占用 → 插到该占用者**之前**（阅读序）
- 目标格为空 → 插入位置 = 「占用格中严格早于目标格的个数」（排除 dragged 自己的老格）

### 2.3 拖动期状态机

```
mouseMove(超阈值)
  └─ AppIcon._exec_drag()
       ├─ hide()                       # 源图标隐藏，避免与拖拽虚影重影
       ├─ payload_provider()           # 置 _drag_active（命中测试全窗口接收）
       └─ QDrag.exec(MoveAction)       # 保留原生 OLE：拖出到资源管理器仍可用
            │
            ├─ DesktopWindow.dragMoveEvent(e)     ← 新增：实时让位
            │     └─ _reflow_preview(dragged_id, cell)
            │           ├─ grid_flow.reflow_order()  算新顺序
            │           ├─ 对每个位置变化的图标 _animate_pos(目标格)   # 弹簧
            │           └─ self._preview = {id: (col,row)}
            │
            ├─ AppIcon.dragEnterEvent → 450ms dwell 后 _merge_target = True（合并才亮）
            │     └─ 松手时若 armed → mergeRequested（保留文件夹合并）
            │         若未 armed → 走 reflow 置换
            │
            ├─ DesktopWindow.dropEvent
            │     ├─ 落格内 → commit preview 到 storage（不 rebuild，图标已在位上）
            │     └─ 落窗外/Explorer → cancel：动画回退到 storage 位置
            │
            └─ dragFinished → 恢复源图标显隐 + 清 _drag_active
```

** dwell 合并（产品决策 D5，需用户确认）**：拖到图标上默认变成"滑动让位"，文件夹合并改为**悬停 450ms 后该图标高亮**（现有 `_merge_target` 视觉）才生效。理由：安卓 launcher 的默认语义就是置换；合并需要明确意图。若不习惯可改回"悬停即合并 + Ctrl 强制置换"。

### 2.4 动画参数（沿用 effects.spring_curve）

| 场景 | 曲线 | 时长 | 说明 |
|---|---|---|---|
| 让位滑行 | `spring_curve(0.78, 280)` | 280ms | 欠阻尼 ~2% 微弹，有生命但不廉价 |
| 落位（dragged 自己） | `spring_curve(0.62, 300)` | 300ms | 带动量，~7% 一次过冲 |
| 取消回退 | `spring_curve(1.0, 220)` | 220ms | 无动量临界阻尼 |
| reduced-motion | 直接 `move()` | 0 | 读 `SPI_GETCLIENTAREAANIMATION` 降级 |

位置动画走 `QPropertyAnimation(self, b"pos")`，与既有 `press_scale`/`hover_scale`/`appear` **属性不冲突**（不同 property）。

### 2.5 与现有机制的兼容

- **多选拖动**：保持原有"整体平移"语义（不参与 reflow 置换），避免 N 个图标的置换歧义。
- **文件夹成员提取**（`M:fid:idx`）：不变。
- **外部文件拖入**（`_drop_files`）：不变。
- **`compact_layout()`**：只在删除/解散后调用，reflow 不触发。
- **`BandGuard`**：不受影响（不碰 z-order）。

---

## 3. M2：锚定（非悬浮）小组件

### 3.1 现状

`FloatingWidget` = 无边框 + `WA_TranslucentBackground` + `Qt.Tool`(+NOACTIVATE) + `attach_to_desktop()` 挂桌面带 + `paintEvent` 画一整块 `SURFACE` 卡片 + 右上角 × / 右下角缩放手柄。

"悬浮感"来自三处：① 满幅不透明卡片；② 可任意拖拽的自由窗口；③ 常驻的 × 与手柄 chrome。

### 3.2 锚定模式设计（entry 新增 `"anchored": bool`）

| 维度 | 悬浮模式（现状） | 锚定模式（新增） |
|---|---|---|
| 层级 | 桌面带（已在应用窗口之下） | 同左，**明确不置顶** |
| 背景 | 满幅 SURFACE 卡片 + BORDER | 只画内容区，低透明度 tint（~34%），无描边 |
| 点击穿透 | 整窗接收 | **卡片外透明像素自动穿透到桌面**（分层窗口默认行为，无需额外代码） |
| 拖动 | 自由移动 + 几何持久化 | 松手**吸附到网格列**（x 对齐 col 边界，y 对齐 row 边界） |
| chrome | × 按钮 + 缩放手柄 | 隐藏；右键菜单提供「切换悬浮 / 隐藏 / 关闭」 |
| 焦点 | interactive 型可激活 | 一律 NOACTIVATE（锚定型不抢焦点） |
| 显隐 | 独立 | **跟随整理窗口**（托盘 toggle 时一起隐藏） |

### 3.3 新增 API

```python
FloatingWidget.anchored -> bool                    # entry.get("anchored", False)
WidgetLayer.set_anchored(entry_id, on) -> None     # 即时切换 + 持久化
FloatingWidget.contextMenuEvent                    # 新增：锚定/悬浮/隐藏/关闭
```

### 3.4 网格吸附实现

复用 `DesktopWindow._cell()` 的同构计算（抽到 `grid_flow.cell_size(storage)`，两边共用，避免 DRY 违背）：
```
x_snap = origin_x + round((x - origin_x) / cell_w) * cell_w
y_snap = origin_y + round((y - origin_y) / cell_h) * cell_h
```
吸附动画：`spring_curve(0.8, 240)` 驱动 `move()`，松手后 `_save_geom()`。

---

## 4. 目录结构与新增文件

```
src/
  grid_flow.py        # 新增：纯逻辑（reflow_order / cell_size / snap_point）—— 零 Qt 依赖，可单测
  effects.py          # 复用 spring_curve
  desktop_window.py   # dragMoveEvent / _reflow_preview / commit / cancel
  iconwidget.py       # hide-on-drag / dwell-merge / 位置动画支持
  widget_base.py      # anchored 模式
  widget_layer.py     # set_anchored
  settings_dialog.py  # 小组件锚定开关（右键菜单先行，设置面板后置）
tests/
  test_grid_flow.py   # 新增：TDD 红绿
tools/
  probe15.py          # 新增：拖动让位 + 锚定穿透的实机验证
```

---

## 5. 验收标准

**M1**
1. `tests/test_grid_flow.py` 全绿（≥12 条断言）
2. probe15：拖动过程中**其他图标位置在中途即已改变**（证明实时而非事后）
3. probe15：松手后无重叠、无丢图标、空位保留
4. probe15：拖到窗外取消 → 全部图标回退到原位置
5. smoke_test 不回退（27/27）

**M2**
6. 锚定时钟：卡片外点击穿透到真实桌面（资源管理器可点开）
7. 锚定时钟：拖动松手后 x/y 对齐网格
8. 锚定时钟：无 × / 无手柄；右键菜单可切回悬浮
9. verify_live 不回退

---

## 6. 风险与未决

| 风险 | 缓解 |
|---|---|
| `QDrag.exec()` 嵌套循环可能冻结 QPropertyAnimation | probe15 首个断言即验证"拖动中位置已变"；若冻结则退化为"松手后一次性动画"（仍远好于现状） |
| dwell-merge 改变既有肌肉记忆 | 悬停高亮 + tooltip 提示；README 记录；可作为设置项回退 |
| 稀疏网格下 reflow 可能与用户"精确摆放"意图冲突 | reflow 只重排**占用格之间的图标**，不改变占用格集合本身；精确摆放仍可通过拖到空格实现 |
| 锚定组件点击穿透与 `WA_TranslucentBackground` 组合的 Win10 差异 | 需在目标系统实测（Win11 为主，Win10 标注待验证） |
