# -*- coding: utf-8 -*-
"""合并 / 挤走 的几何判定（纯函数，无 Qt 依赖，可单测）。

2026-10-21 用户反馈 7（= v7 指导文档 §5.2 反馈 11）重写为**双区模型**：

  用户原话："现在加入文件夹的判定范围太大了，且没有了边缘判定为碰撞
  时候的实时挤开效果。"

旧模型（2026-10-20 F3）按**重叠比**一刀切：
  - `MERGE_OVERLAP_RATIO = 0.30`：重叠够 30% 就判"想合并"；
  - `MERGE_ARM_RATIO = 0.15`：重叠够 15% 就 defer 挤走。
两个病根正对反馈 7 的两句话：
  - 0.30 太低——刚擦上去（拖影压进去 30%）就弹「松手合并」提示，
    用户想把图标搬个位置都会被合并提示截住（"判定范围太大"）；
  - 0.15~0.30 这一整段被 `defers_push` 整体 return：既不出合并提示
    （没到 0.30）也不武装挤走（defer 了）——"边缘碰撞的实时挤开
    效果没有了"，是一条死区。

新模型（iOS launcher 语义，指导文档 §5.2）：

    目标图标矩形 R；核心区 = R 中心缩放 `MERGE_CORE_RATIO` 的内缩矩形
      拖影中心 ∈ 核心区 -> 合并候选（dwell 450ms 出「松手合并」提示）
      拖影中心 ∉ 核心区 -> 让位区（悬停 `PUSH_DWELL_MS` 后目标实时滑走）
    重叠比只当"是否压在图标上"的**门槛**（`MERGE_ARM_RATIO`）：
    低于它视为没碰上，不进双区判定（纯擦过不误判）。

判定改看**拖影中心**而不是重叠比：等尺寸矩形下"中心进核心区"天然
等价于"重叠 ≥ 0.45"，比旧的 0.30 严得多——想合并必须把图标拖到对方
**正中**，与手机 launcher 的手势一致。`MERGE_CORE_HYSTERESIS` 给核心
区加进出滞回，边界抖动不翻状态。
"""

# 拖影与目标重叠到此比例 -> 才算"压在图标上"，进入双区判定。
# 纯擦过（< 该值）视为没碰上：不走合并也不走挤走。
MERGE_ARM_RATIO = 0.15

# 核心区 = 目标矩形中心缩放比例（内缩 (1-ratio)/2 的矩形）。
# 拖影中心落在里面 -> 合并候选；落在外面（让位区）-> 悬停够久挤走。
MERGE_CORE_RATIO = 0.55

# 进出核心区的滞回带：已在内时有效区外扩、已在外时内缩，
# 防边界 ±0.03 的抖动把状态来回翻（指导文档 §5.2 E4）。
MERGE_CORE_HYSTERESIS = 0.06


def overlap_ratio(ghost, target) -> float:
    """两矩形交叠面积 ÷ **较小矩形面积**（0~1）。

    ghost / target 均为 (x, y, w, h)。用较小矩形归一而不是并集（IoU）：
    拖影与被拖图标本体尺寸差不大时两者接近，但拖影裁掉标签区后比目标小，
    IoU 会被无谓压低——用"占较小者的比例"才符合"压住了多大一块"的直觉。
    """
    try:
        gx, gy, gw, gh = [float(v) for v in ghost]
        tx, ty, tw, th = [float(v) for v in target]
    except (TypeError, ValueError):
        return 0.0
    if gw <= 0 or gh <= 0 or tw <= 0 or th <= 0:
        return 0.0
    iw = min(gx + gw, tx + tw) - max(gx, tx)
    ih = min(gy + gh, ty + th) - max(gy, ty)
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    base = min(gw * gh, tw * th)
    return inter / max(1.0, base)


def in_merge_core(ghost, target, was_in=None) -> bool:
    """拖影**中心**是否落在目标矩形的核心区内（2026-10-21 反馈 7）。

    核心区 = 目标矩形正中心、边长为 `MERGE_CORE_RATIO` 倍的内缩矩形
    （0.55 即四边各内缩 22.5%）。中心落里面 -> 判"想合并"；落外面
    （哪怕重叠很大）-> 判"想放这儿并把对方挤走"。

    `was_in`：上一次的判定结果，用于滞回（None = 无历史）：
      - 已在内（True）：有效区**外扩** `MERGE_CORE_HYSTERESIS`——
        刚飘出边界不算出，提示不会闪没；
      - 已在外（False）：有效区**内缩**同样宽度——刚飘进边界不算进，
        推让不会刚发动又撤销。
    两个方向都不翻，边界 ±0.03 的抖动就是稳态（E1l）。

    退化输入（None / 空矩形 / 非数值）一律 False：没拖影就不该判合并。
    """
    try:
        gx, gy, gw, gh = [float(v) for v in ghost]
        tx, ty, tw, th = [float(v) for v in target]
    except (TypeError, ValueError):
        return False
    if gw <= 0 or gh <= 0 or tw <= 0 or th <= 0:
        return False
    ratio = MERGE_CORE_RATIO
    if was_in is True:
        ratio += MERGE_CORE_HYSTERESIS
    elif was_in is False:
        ratio -= MERGE_CORE_HYSTERESIS
    if ratio <= 0:
        return False
    cx, cy = gx + gw / 2.0, gy + gh / 2.0
    tcx, tcy = tx + tw / 2.0, ty + th / 2.0
    return (abs(cx - tcx) <= tw * ratio / 2.0
            and abs(cy - tcy) <= th * ratio / 2.0)
