# -*- coding: utf-8 -*-
"""合并 / 挤走 的几何判定（纯函数，无 Qt 依赖，可单测）。

背景（2026-10-20 用户反馈 F3）：拖图标压到另一个图标上时，用户想要的是
「停下来 -> 出『松手合并为文件夹』提示」。旧实现有两个门槛互相打架：

  - `MERGE_OVERLAP_RATIO = 0.45`：拖影与目标重叠不到 45% 就判成"擦边"，
    这类拖动落到桌面窗口走让位（挤走）逻辑；
  - `PUSH_DWELL_MS = 260` **小于** `DWELL_MERGE_MS = 450`：即使判成合并
    候选，拖影抖动一下掉回"擦边"，260ms 就把目标推走了 —— 合并提示
    永远等不到。

现在把"几何阈值"集中在这里（**单点定义**，iconwidget 与桌面窗口共用，
避免两处各写一份 0.45/0.30 再慢慢漂移）：

  - `MERGE_OVERLAP_RATIO` = 0.30：判为合并目标的门槛（压上去就算）
  - `MERGE_ARM_RATIO`     = 0.15：拖影**实质压住**目标的门槛；
    达到它时推让必须让位给合并提示（不武装推让计时器）
"""

# 拖影与目标重叠到此比例 -> 判为"合并目标"（武装 dwell，出合并提示）
MERGE_OVERLAP_RATIO = 0.30

# 拖影实质压住目标 -> 暂缓"挤走"（把优先级让给合并提示）
MERGE_ARM_RATIO = 0.15


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


def is_merge_target(ratio: float) -> bool:
    """拖影与目标的重叠比是否够格当合并目标（武装 dwell 出提示）。"""
    return float(ratio) >= MERGE_OVERLAP_RATIO


def defers_push(ratio: float) -> bool:
    """拖影是否实质压住目标 —— 是则**暂缓挤走**，优先等合并提示。

    这是"想合并却先被挤走"的直接修复点：只要压住了一块（哪怕没达到合并
    阈值），就不许推人；想换位置请把图标拖到格子空白处。
    """
    return float(ratio) >= MERGE_ARM_RATIO
