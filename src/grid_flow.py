# -*- coding: utf-8 -*-
"""图标网格让位引擎（Live Reflow）——纯逻辑，零 Qt 依赖，可离线单测。

两个求解入口（2026-10-18 M2 起 preview 走 reflow_moves）：

1. **reflow_moves（位移清单，指导文档 §2.2，当前主路径）**：
   iOS 局部让位——dragged 精确落到 target（含空格，修复 P2 病根 1），
   只有新旧位置之间（阅读序）的图标滑动一格，其余不动。返回
   {id: (col, row)} 最小位移集，由 AppIcon.animate_to 驱动。

2. reflow_order（阅读序置换，旧路径，保留兼容）：
   design.md 2.2「占用格集合上的置换」——占用格集合守恒前提下重排
   阅读序。dragged 落在第 k 个占用格上（空格场景落点不精确，P2 病根）。

性质（tests/test_grid_flow.py 全量断言）：
  - reflow_moves：精确落点 / 最小位移 / 无重叠 / 无丢失 /
    占用集合 = 旧集合 - 老格 + target
  - reflow_order：占用格集合守恒 / 跨行 / 空格 / 占用格 / 原地统一处理
  - O(n log n)，每次 dragMove 全量重算无压力

与 DesktopWindow 的关系：_cell()/_origin() 已下沉到本模块（cell_size/origin），
两边共用同一份几何定义，避免 DRY 违背导致的网格与图标错位。
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

Cell = Tuple[int, int]


# ---------- 阅读序 ----------
def _cell_of(entry: dict) -> Cell:
    return int(entry.get("col", 0)), int(entry.get("row", 0))


def reading_order(entries: Iterable[dict], cols: int) -> List[dict]:
    """按 (row, col) 稳定排序（同一行内从左到右，行间从上到下）。"""
    return sorted(entries, key=lambda e: (int(e.get("row", 0)), int(e.get("col", 0))))


def occupied_cells(entries: Iterable[dict], cols: int) -> List[Cell]:
    """排序去重后的占用格集合。cols 仅用于签名对称（调用方已夹紧 col）。"""
    seen = set()
    for e in entries:
        seen.add(_cell_of(e))
    return sorted(seen)


# ---------- 让位求解 ----------
def reflow_order(entries: Sequence[dict], cols: int, dragged_id: str,
                 target: Cell, extra_occupied: Iterable[Cell] = ()) -> Optional[List[str]]:
    """计算拖动 dragged_id 到 target 后的新阅读序（entry id 列表）。

    target 越界会被夹紧到 [0, cols-1] x [0, +inf)。
    dragged_id 不存在时返回 None（调用方应忽略本次预览）。
    原地拖动返回与原顺序相同的列表（恒等）。

    extra_occupied：额外的固定占用格集合（锚定小组件的占位，2026-10-18
    「小组件占据格子挤走图标」）。target 落在其中时，先就近解析到最近的
    非占用格——小组件的格子不给图标用。

    2026-10-18 M2 修复多行 scrambling：旧实现用 (col,row) 排序的
    occupied_cells 与 (row,col) 阅读序 zip，多行布局下序号错位——B/C
    这类跨行图标会被互换位置（P2「全体乱排」的隐藏帮凶；旧单测只测
    单行所以没抓到）。现统一改为阅读序配对 cells。
    """
    if cols < 1:
        return None
    by_id = {e.get("id"): e for e in entries}
    if dragged_id not in by_id:
        return None

    extra = set(extra_occupied or ())
    tcol = max(0, min(int(cols) - 1, int(target[0])))
    trow = max(0, int(target[1]))
    target = (tcol, trow)
    if target in extra:
        target = nearest_free_cell(target, set(occupied_cells(entries, cols)) | extra, cols)

    ordered = reading_order(entries, cols)
    order = [e["id"] for e in ordered]
    if dragged_id not in order:
        return None
    cells = [_cell_of(e) for e in ordered]  # 阅读序配对：cells[i] 即 order[i] 的占用格
    if len(set(cells)) != len(cells):
        return None  # 脏布局（重复占用格）：宁可不预览也别写坏
    rest = [i for i in order if i != dragged_id]

    # 统一插入规则：k = 阅读序中第一个 >= target 的占用格下标（(row,col) 空间比较）
    #   - target 被占用  -> k = 该格下标，dragged 正好落上目标格，占用者及其后整体后移
    #   - target 为空    -> k = 第一个严格大于 target 的格下标，dragged 落到该格
    #   - target == 老格 -> k = 老格下标，等价于恒等（移回去恢复原序）
    tkey = (target[1], target[0])
    k = len(cells)
    for idx, c in enumerate(cells):
        if (c[1], c[0]) >= tkey:
            k = idx
            break
    k = max(0, min(len(rest), k))
    return rest[:k] + [dragged_id] + rest[k:]


def reflow_moves(entries: Sequence[dict], cols: int, dragged_id: str,
                 target: Cell, rows: Optional[int] = None,
                 extra_occupied: Iterable[Cell] = ()) -> Optional[dict]:
    """计算拖动 dragged_id 到 target 后的**位移清单** {id: (col, row)}。

    iOS 局部让位（指导文档 §2.2，2026-10-18 M2）：与 reflow_order 的本质
    区别是语义从「重排阅读序」换成「位移清单」——dragged **精确落到
    target（含空格）**，只有新旧位置之间（阅读序）的图标滑动一格，
    其余一律不动。空格从此生效（修复 P2 病根 1：空格永不生效）。

    算法（2026-10-18 M2：全部在**阅读序空间**进行，cells[i] 即 order[i]
    的占用格——消除旧实现 (col,row)/(row,col) 双排序导致的跨行 scrambling）：
        order = 阅读序（含 dragged）；cells = 占用格（含 dragged 老格）
        d = dragged 在 order 中的下标；p = 阅读序中第一个 >= target 的下标
        p > d（向后移）：target 被占用 -> run = (d, p]；否则 run = (d, p)
                        run 内图标从 cells[i] 前移一格到 cells[i-1]
        p < d（向前移）：run = [p, d)，图标从 cells[i] 后移一格到 cells[i+1]
        dragged -> target；p == d 且 cells[p] == target：恒等，无位移

    性质（tests/test_grid_flow.py §13 全量断言）：
        - 占用集合 = 旧集合 - 老格 + target（空格精确落点，空位随拖动平移）
        - 永不重叠、永不丢图标、位移集合最小化（run 外图标不动）
        - O(n log n)；target 越界夹紧 [0, cols-1] x [0, rows-1]（rows=None 不限行）
        - target 落在 extra_occupied（小组件占位）时就近解析到最近可用格

    dragged_id 不存在 / 占用格数与图标数不符（脏布局）返回 None；
    原地恒等返回 {}。
    """
    if cols < 1:
        return None
    by_id = {e.get("id"): e for e in entries}
    if dragged_id not in by_id:
        return None

    ordered = reading_order(entries, cols)
    order = [e["id"] for e in ordered]
    cells = [_cell_of(e) for e in ordered]  # 阅读序配对：cells[i] 即 order[i] 的占用格
    if len(set(cells)) != len(cells) or dragged_id not in order:
        return None  # 脏布局（重复占用格）：宁可不预览也别写坏

    extra = set(extra_occupied or ())
    tcol = max(0, min(int(cols) - 1, int(target[0])))
    trow = max(0, int(target[1]))
    if rows is not None:
        trow = min(trow, max(0, int(rows) - 1))
    target = (tcol, trow)
    if target in extra:
        target = nearest_free_cell(target, set(cells) | extra, cols)

    d = order.index(dragged_id)
    # p = 阅读序中第一个 >= target 的占用格下标（(row,col) 空间比较；
    # 越界时为 len(cells)：追加队尾）
    tkey = (target[1], target[0])
    p = len(cells)
    for idx, c in enumerate(cells):
        if (c[1], c[0]) >= tkey:
            p = idx
            break

    moves = {}
    if p > d:
        # 向后移：target 被占用（cells[p] == target）时占用者也要动
        end = p if (p < len(cells) and cells[p] == target) else p - 1
        for i in range(d + 1, end + 1):
            moves[order[i]] = cells[i - 1]
        moves[dragged_id] = target
    elif p < d:
        # 向前移：[p, d) 内图标整体后移一格
        for i in range(p, d):
            moves[order[i]] = cells[i + 1]
        moves[dragged_id] = target
    elif cells[p] != target:
        # p == d 但 target 不是 dragged 老格（空格落在老格与前一个占用格之间）
        moves[dragged_id] = target
    # else：p == d 且 cells[p] == target —— 原地恒等，无位移
    return moves


def nearest_free_cell(target: Cell, occupied: set, cols: int) -> Cell:
    """曼哈顿距离升序找第一个非占用格（同距时阅读序优先）。

    extra_occupied 场景下把落在小组件占位上的落点解析到最近可用格；
    行范围取占用格最大行 +2，保证屏幕外沿也有解。

    2026-10-18 M2：原实现按「|dr|=dist 方环」遍历，dist=1 就会访问
    曼哈顿距 2 的格子（如 (tc-1, tr+1)），与文档「曼哈顿距离升序」
    矛盾；改为真曼哈顿环（|dc|+|dr|=dist），环内按 (row, col) 排序。
    """
    occupied = set(occupied)
    max_row = max((r for _, r in occupied), default=0) + 2
    tc, tr = int(target[0]), int(target[1])
    for dist in range(0, cols + max_row + 4):
        ring = []
        for dc in range(-dist, dist + 1):
            dr = dist - abs(dc)
            for r in ({dr, -dr} if dr else (0,)):
                c, rr = tc + dc, tr + r
                if 0 <= c < cols and 0 <= rr <= max_row and (c, rr) not in occupied:
                    ring.append((c, rr))
        if ring:
            ring.sort(key=lambda c: (c[1], c[0]))  # 同距阅读序优先
            return ring[0]
    return max(0, min(tc, cols - 1)), tr


def apply_order(entries: Sequence[dict], order: Sequence[str]) -> None:
    """把 order（阅读序）按原占用格集合就地写回 col/row。

    前提：order 是 entries 的一个排列（reflow_order 的返回值即满足）。
    占用格按**阅读序**取出与 order 配对（2026-10-18 M2 修复：旧实现
    取 (col,row) 排序的集合，多行布局下与 (row,col) 阅读序序号错位，
    会把跨行图标互相 scrambling）。
    """
    if not order:
        return
    cells = [_cell_of(e) for e in reading_order(entries, 1 << 30)]
    if len(cells) != len(order) or len(set(cells)) != len(cells):
        return  # 防御：调用方传了不完整顺序 / 脏布局，宁可不写也别写坏布局
    by_id = {e.get("id"): e for e in entries}
    for eid, (c, r) in zip(order, cells):
        e = by_id.get(eid)
        if e is not None:
            e["col"], e["row"] = c, r


# ---------- 网格几何（与 DesktopWindow 共用，勿重复实现） ----------
_current_metrics = None  # 当前 GridMetrics 快照（M1：几何确定后由 set_grid 写入）


def set_grid(storage, screen_size):
    """重算并缓存当前网格几何（M1，指导文档 §1：网格自适应铺满）。

    DesktopWindow 在启动 / 窗口几何变化 / DPI·分辨率·任务栏变化后调用。
    screen_size：availableGeometry 的 (W, H)。返回 GridMetrics 快照。
    """
    global _current_metrics
    from . import grid_metrics  # 延迟导入：grid_metrics 依赖本模块 cell_size
    _current_metrics = grid_metrics.compute(storage, screen_size)
    return _current_metrics


def current_metrics():
    """当前 GridMetrics 快照（未初始化时为 None，调用方回退历史默认）。"""
    return _current_metrics


def origin() -> Cell:
    """网格原点（桌面整理窗口控件坐标）。

    2026-10-18 M1（指导文档 §1，反馈 P1/P2）：不再硬编码——读
    DesktopWindow 写入的 GridMetrics 快照（按工作区四边等距铺满）；
    快照未就绪（挂载前 / 无头测试）时回退历史默认 (26, 22)。
    """
    m = _current_metrics
    if m is not None:
        return m.ox, m.oy
    return 26, 22


def cell_size(storage) -> Cell:
    """单元格尺寸——**快照优先**（DRY 单一来源）。

    2026-10-18 M1 前：与 AppIcon(setFixedSize(s+24m, s+40m)) 对齐的
    icon 派生值。2026-10-19 v6 批次 A（指导文档 §2.1）：GridMetrics
    的 cell 改屏幕驱动（grid_sizing.cell_for_screen，与 icon_size 解钩），
    cell_pos/pos_cell/snap_point/_cell_at 等一切几何换算必须跟随快照，
    否则出现"快照 cell 75x92 与派生 cell 96x114"双源漂移（T3 抓到）。
    快照未就绪（无头测试 / 挂载前）回退 icon 派生，保持旧行为。
    """
    m = _current_metrics
    if m is not None:
        return m.cw, m.ch
    s = int(storage.icon_metric())
    m = float(storage.icon_chrome_scale())
    return s + int(round(24 * m)), s + int(round(40 * m)) + 2


def snap_point(storage, x: int, y: int, screen_size: Tuple[int, int]) -> Cell:
    """把任意坐标吸附到最近的网格格点（当前页内），并夹紧在屏幕内。

    2026-10-18 M6：改走 pos_cell/cell_pos——页内局部行 + 列夹紧 +
    当前页偏移全在一处完成（此前这里的 round + clamp 与 DesktopWindow
    _cell_at 各写一份，分页后必然漂移）。
    """
    col, row = pos_cell(storage, x, y)
    return cell_pos(storage, col, row)


# ---------- 分页（2026-10-18 M6，指导文档 §7-M6） ----------
# 语义：存储里的 row 始终是**全局行**（零迁移——旧布局无需换算）；
# 页是纯视图概念：page = row // rows_per_page，像素 y 用页内局部行
# local_row = row % rows_per_page。翻页 = 改运行时当前页，全体位置
# 换算（cell_pos/pos_cell/snap_point/_entry_pos/_cell_at/widget）随之
# 整体偏移——当前页内容滑出屏、邻页内容滑入屏（iOS launcher 语言）。
_current_page = 0


def rows_per_page() -> int:
    """单屏行数 = GridMetrics.rows（M1 已按工作区算好，clamp 1..12）。

    快照未就绪（挂载前 / 无头测试）时回退历史默认 8（与 origin 时代
    的单屏行数同量级，保证 clamp 不会把 page 0 的条目算到屏外）。
    """
    m = _current_metrics
    if m is not None:
        return max(1, int(m.rows))
    return 8


def page_of(row: int, rpp: int = 0) -> int:
    """全局行 -> 页号（负行回退第 0 页）。"""
    rpp = max(1, int(rpp) or rows_per_page())
    return max(0, int(row)) // rpp


def local_row(row: int, rpp: int = 0) -> int:
    """全局行 -> 页内局部行（0..rpp-1）。"""
    rpp = max(1, int(rpp) or rows_per_page())
    return max(0, int(row)) % rpp


def page_row_range(page: int, rpp: int, rs: int = 1) -> Tuple[int, int]:
    """某页可容纳 rs 行跨度组件的全局行范围 [lo, hi]（组件不越页底）。"""
    rpp = max(1, int(rpp))
    lo = max(0, int(page)) * rpp
    hi = lo + rpp - max(1, int(rs))
    return lo, max(lo, hi)


def current_page() -> int:
    """运行时当前页（DesktopWindow 翻页时经 set_page 同步）。"""
    return _current_page


def set_page(page: int) -> int:
    """设置运行时当前页（夹到 >=0）。返回生效值。"""
    global _current_page
    _current_page = max(0, int(page))
    return _current_page


def page_number(max_row: int, rpp: int) -> int:
    """最大全局行号 -> 总页数（至少 1 页）。纯函数。"""
    return max(1, max(0, int(max_row)) // max(1, int(rpp)) + 1)


def page_count(storage, rpp: int = 0) -> int:
    """总页数：布局条目与锚定组件占位（含跨度）的最大全局行决定，
    至少 1 页。"""
    rpp = max(1, int(rpp) or rows_per_page())
    max_row = 0
    for e in getattr(storage, "layout", []):
        max_row = max(max_row, int(e.get("row", 0) or 0))
    for w in getattr(storage, "widgets", []):
        if not w.get("anchored") or w.get("hidden"):
            continue
        _cs, rs = widget_span(storage, w)
        max_row = max(max_row, int(w.get("row", 0) or 0) + rs - 1)
    return page_number(max_row, rpp)


def cell_pos(storage, col: int, row: int) -> Cell:
    """(col, 全局 row) -> 窗口控件坐标像素（列夹紧 + **相对当前页**行偏移）。

    所有「条目/组件 -> 像素」的换算统一走这里（DRY：DesktopWindow
    _entry_pos、widget_base、widget_layer._spawn 都是它的调用方）。

    M6：y = oy + (row - page*rpp) * ch——rel 可为负（上一页条目滑出
    屏顶）或 >= rpp（次页条目在屏下方），翻页时全体沿此式整体平移，
    天然形成「当前页滑出、邻页滑入」的 iOS launcher 动画。
    """
    cw, ch = cell_size(storage)
    ox, oy = origin()
    cols = storage.columns
    col = max(0, min(int(col), cols - 1))
    rel = max(0, int(row)) - current_page() * rows_per_page()
    return ox + col * cw, oy + rel * ch


def pos_cell(storage, x: int, y: int) -> Cell:
    """像素坐标 -> (col, 全局 row)：列夹紧 [0, cols-1] + 当前页偏移。

    与 cell_pos 互逆（当前页内 round-trip）。局部行夹 [0, rpp-1]：
    落点限当前页（指导文档 §2.3「target 行夹紧在当前页，reflow 不
    跨页」）——拖到屏幕上/下边缘不会把目标落到邻页。
    """
    cw, ch = cell_size(storage)
    ox, oy = origin()
    cols = storage.columns
    col = int(round((x - ox) / max(1, cw)))
    local = int(round((y - oy) / max(1, ch)))
    local = max(0, min(local, rows_per_page() - 1))
    col = max(0, min(col, cols - 1))
    return col, current_page() * rows_per_page() + local


def first_free_cell_in_page(storage, page: int):
    """当前页内第一个空格（列优先扫描；占用 = 图标 + 组件占位）。

    当前页满返回 None（调用方回退全局第一个空格）。供「添加应用」
    类操作把新条目放进用户眼前这一页（指导文档 §7-M6 落点限页）。
    """
    cols = storage.columns
    lo, hi = page_row_range(page, rows_per_page(), 1)
    blocked = set(occupied_cells(storage.layout, cols)) | widget_cells(storage)
    for row in range(lo, hi + 1):
        for col in range(cols):
            if (col, row) not in blocked:
                return col, row
    return None


# ---------- 锚定小组件占位（widget 作为网格一等公民） ----------
def widget_span(storage, widget: dict) -> Cell:
    """widget 占据几列几行。三级解析（2026-10-18 M3，指导文档 §3.2）：

    1. entry 已存 colspan/rowspan（用户在右键「组件尺寸」菜单切换过，
       持久化在 storage.widgets）——优先，保证视觉与存储一致；
    2. WIDGET_CATALOG 登记的默认跨度（clock = 2×2，决策 D3）——
       一等公民，不再 round 像素（银行家舍入 round(300/120)=2、
       round(160/142)=1 的坑根除，碰撞 = 视觉边界）；
    3. 未登记类型回退 legacy 像素换算（至少 1×1），兼容旧数据。
    """
    cs = widget.get("colspan")
    rs = widget.get("rowspan")
    if isinstance(cs, int) and isinstance(rs, int) and cs > 0 and rs > 0:
        return cs, rs
    from . import widget_catalog  # 延迟导入，模块级不建依赖边
    wtype = widget.get("type")
    if isinstance(wtype, str):
        span = widget_catalog.default_span(wtype)
        if span is not None:
            return span
    cw, ch = cell_size(storage)
    w = int(widget.get("w", 260))
    h = int(widget.get("h", 140))
    return max(1, int(round(w / max(1, cw)))), max(1, int(round(h / max(1, ch))))


def widget_cells(storage) -> set:
    """所有可见锚定 widget 占据的格子集合（从 storage.widgets 读，解耦：
    小组件只写 storage，DesktopWindow 直接读，无需实例引用）。"""
    cells = set()
    for w in storage.widgets:
        if not w.get("anchored") or w.get("hidden"):
            continue
        col = max(0, int(w.get("col", 0)))
        row = max(0, int(w.get("row", 0)))
        cs, rs = widget_span(storage, w)
        for dc in range(cs):
            for dr in range(rs):
                cells.add((col + dc, row + dr))
    return cells


def find_widget_slot(storage, widget: dict, page: int = None) -> Cell:
    """为锚定 widget 找第一个容得下它的左上空格（排除已有 widget 占位
    与图标占位）。找不到时退回 (0, 0)（极端拥挤场景， displace 会兜底）。

    M6：page 指定时行扫描限制在该页行范围内（page_row_range，组件
    不越页底）；缺省用运行时当前页。
    """
    cs, rs = widget_span(storage, widget)
    blocked = widget_cells(storage)
    for e in storage.layout:
        blocked.add((int(e.get("col", 0)), int(e.get("row", 0))))
    cols = storage.columns
    lo, hi = page_row_range(current_page() if page is None else page,
                            rows_per_page(), rs)
    for row in range(lo, hi + 1):
        for col in range(0, cols - cs + 1):
            rect = {(col + dc, row + dr) for dc in range(cs) for dr in range(rs)}
            if not (rect & blocked):
                return col, row
    return 0, 0
