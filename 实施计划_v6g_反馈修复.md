# 实施计划 v6g —— 实机反馈修复（4 项）

> 规格来源：`指导文档_网格与无界双模式_v6.md` §11（2026-10-20 用户反馈）
> 纪律：每任务先写 Red 测试 → 看它红 → 最小实现 → 看它绿 → 再下一个。
> 回归底线：42 个测试文件 + smoke 全绿不被破坏。

---

## 任务 1：F2 组件预览不得叠格（先做，纯逻辑、影响面最大）

**文件**
- `src/desktop_window.py`：`_on_widget_hover`、`_displace_from_widgets`

**要做的**
两处调用 `grid_flow.displace_cells(...)` 前，把 `blocked` 扩成：
```python
icon_cells = {(int(e.get("col", 0)), int(e.get("row", 0)))
              for e in self.storage.layout}
src_cells = {c for _e, c in need}
blocked = blocked | (icon_cells - src_cells)
```
其中 `need` 是本次要挪走的条目（它们让出原格，故从禁区里剔除）。
`_on_widget_hover` 里 `blocked` 的初值仍是
`rect | (self._widget_cells() - self._widget_entry_rect(entry))`。

**验证：`tests/test_widget_displace_stack.py`（新）**
- P1 纯函数契约：`displace_cells` 传「全占位」禁区 → 返回值两两不同
- P2 窗口级：铺满一整页图标 + 1 个 2×2 组件，逐格 `_on_widget_hover`，
  每步断言 `len(布局格) == len(set(布局格))`（无重复格）
- P3 同样断言 `_displace_from_widgets()`（落定路径）
- P4 Red 基线：上述断言在修复前必须失败（否则说明没测到真问题）

## 任务 2：F3 合并提示优先于挤走

**文件**
- `src/iconwidget.py`：`MERGE_OVERLAP_RATIO` 0.45→0.30，新增 `MERGE_ARM_RATIO=0.15`
- `src/desktop_window.py`：`PUSH_DWELL_MS` 260→700；`_reflow_preview` 加重叠门控

**要做的**
`_reflow_preview` 在启动推让计时器前，先判断"拖影是否压在目标图标上"：
```python
if occ is not None and self._drag_overlaps_icon(dragged_id, cell) >= MERGE_ARM_RATIO:
    self._push_timer.stop()      # 压住图标：只等合并提示，不挤走
    self._push_cell = None
    return
```
`_drag_overlaps_icon`：取 `self.icons[dragged_id]._ghost_rect()` 与该格上的
图标 widget 全局矩形算交并比（复用 AppIcon._overlap_ratio 的算法，主窗口侧
独立实现，避免跨部件私有调用）。

**验证：`tests/test_merge_priority.py`（新）**
- M1 常量契约：`PUSH_DWELL_MS > DWELL_MERGE_MS`（推让晚于合并提示）
- M2 `MERGE_OVERLAP_RATIO` 落在 (0.2, 0.4) 区间且 `MERGE_ARM_RATIO < 它`
- M3 拖影压住目标图标 → 启动推让计时器后 `_push_cell is None`（不武装）
- M4 拖影只擦边（无实质重叠）→ 推让计时器武装（`_push_cell == cell`）
- M5 计时器超时且目标被压住 → 目标**不被挤走**（布局不变）

## 任务 3：F4 文件夹弹窗贴图标展开

**文件**
- `src/folder_popup.py`：`_build` 定位段

**要做的**
抽出纯函数 `place_beside(anchor: QRect, w: int, h: int, avail: QRect) -> QPoint`：
1. 下方：`y = anchor.bottom() + GAP`，若 `y + h <= avail.bottom() + 1` 用下方；
2. 否则上方：`y = anchor.top() - GAP - h`，若 `y >= avail.top()` 用上方；
3. 否则夹紧 `y ∈ [avail.top()+8, avail.bottom()-h-8]`；
4. `x = anchor.center().x() - w//2`，夹紧 `x ∈ [avail.left()+8, avail.right()-w-8]`。
`_build` 有 `anchor_rect` 时用它，否则回退 `page_grid_center` 居中（旧行为）。

**验证：`tests/test_folder_popup_anchor.py`（新）**
- Q1 常规：图标在屏幕中部 → 弹窗在图标正下方 10px、水平居中
- Q2 图标靠近屏幕底边 → 弹窗翻到图标上方
- Q3 上下都放不下（图标居中且弹窗很高）→ 夹紧进屏幕且不越界
- Q4 图标贴左边 → 弹窗左边界不越出屏幕
- Q5 无 anchor → 回退网格区居中（旧行为不变）
- Q6 窗口级：`FolderPopup(storage, folder, anchor_rect)` 构造后
  `popup.geometry()` 与 `place_beside` 计算结果一致

## 任务 4：F1 显示桌面后保持可见

**文件**
- `src/win32_layer.py`：新增 `restore_band_windows(items, progman, zorder)` +
  `SHOW_DESKTOP` 态下的 `pin_to_topmost_band(...)`
- `src/band_guard.py`：`_check` 的 show desktop 分支改为主动恢复

**要做的**
```python
# win32_layer
SW_SHOWNA = 8
def show_no_activate(hwnd): _user32.ShowWindow(hwnd, SW_SHOWNA)

def restore_band_windows(items, progman):
    """带内窗口被 show desktop 一并隐藏后恢复可见，并按层号重插到
    Progman 正上方（Progman 在 topmost 带，插其下仍被壁纸盖住）。"""
```
`BandGuard._check`：
```python
if show_desktop:
    self._in_show_desktop = True
    win32_layer.restore_band_windows(self._items, progman)   # 恢复 + 插入
    self._tick_hook()
    return
```
退出分支保持现有 `enforce_band_order` 全量重排。

**验证：`tests/test_show_desktop.py`（新，复用 test_band_layers 的 World 注入）**
- W1 show desktop 态：隐藏的带内窗口被 `ShowWindow(SW_SHOWNA)` 恢复
- W2 show desktop 态：每个带内窗口被插到 Progman 正上方（z-order 校验）
- W3 show desktop 态：**不调用** `SetForegroundWindow`/不激活（无相关调用）
- W4 退出 show desktop 态：立刻 `enforce_band_order`，窗口回到带内（Progman 上方连续一段）
- W5 正常态：`restore_band_windows` 不被调用（零多余 SetWindowPos，防抖动回归）

## 收尾

- 全量回归：42 测试文件 + smoke + 4 个新测试
- DEVLOG Day 16 + 坑表 + 测试矩阵 + 目录树
- memory 双日志
- commit + push（走 `https_proxy=http://127.0.0.1:7890`）
- 交付说明：真机验证清单（Win+D 实机手感、合并提示时机、弹窗位置目检）
