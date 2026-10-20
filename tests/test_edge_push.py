# -*- coding: utf-8 -*-
"""边缘 hover 挤走 + 中心压住合并：双区模型（2026-10-21 用户反馈 7）。

用户原话："现在加入文件夹的判定范围太大了，且没有了边缘判定为碰撞时候的
实时挤开效果。"

规格（docs/指导文档_v7.md §5.2 反馈 11，双区模型 / iOS launcher 语义）：

    目标图标矩形 R；核心区 = R 中心缩放 0.55 的内缩矩形
      拖影中心 ∈ 核心区 -> 合并候选：dwell 450ms 出「松手合并」提示
      拖影中心 ∉ 核心区 -> 让位区：悬停 PUSH_DWELL_MS 后目标实时滑走
    重叠比只当"是否压在图标上"的门槛（MERGE_ARM_RATIO = 0.15）

旧实现（2026-10-20 F3）按重叠比一刀切：MERGE_OVERLAP_RATIO=0.30 判合并、
MERGE_ARM_RATIO=0.15 起 defer。两个病根正对反馈 7 的两句话：
  - 0.30 太低：刚擦上去（重叠 30%）就弹合并提示 -> "判定范围太大"；
  - 0.15~0.30 被 defers_push 整体 return：挤走路径整个死掉
    -> "边缘碰撞的实时挤开效果没有了"。

验收（指导文档 §5.2 E1-E4）：
  E0 常量契约（核心区 / 滞回 / 门槛 / 时序；旧双阈值已废止）
  E1 in_merge_core 纯函数：核心区判定 + 滞回 + 退化输入
  E2 窗口级：让位区武装推让并实时挤走；核心区不武装、提示优先
  E3 窗口级：核心 <-> 让位区切换互不双触发（dwell 与 push 单激活）
  E4 端到端：真实拖影 + _drag_move 全链路（合并提示 / 实时挤走）

运行：python tests/test_edge_push.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QMimeData, QPoint, QRect, Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from src import drag_merge
from src.desktop_window import PUSH_DWELL_MS, DesktopWindow
from src.iconwidget import DWELL_MERGE_MS, AppIcon
from src.storage import Storage

STATE = Path(tempfile.gettempdir()) / "test_edge_push_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=120):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make_state(layout=None):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"].update({
        "hide_native_icons": False,
        "auto_clone_desktop": False,
        "takeover_desktop": True,
        "layout_mode": "grid",
        "auto_arrange": False,      # 自由移动：挤走 = 与占位者互换
        "dev_mode": False,
    })
    st._data["widgets"] = []
    st._data["layout"] = [dict(e) for e in (layout or [
        {"id": "a", "type": "app", "col": 0, "row": 0, "app": {"name": "A"}},
        {"id": "b", "type": "app", "col": 1, "row": 0, "app": {"name": "B"}},
        {"id": "c", "type": "app", "col": 2, "row": 0, "app": {"name": "C"}},
    ])]
    st.save()
    return st


def cell_of(st, eid):
    e = st.find_entry(eid)
    return (int(e["col"]), int(e["row"])) if e else None


def new_window(app, st):
    w = DesktopWindow(st)
    w.resize(1920, 1040)
    w._update_grid_metrics()
    w.rebuild()
    # 必须 show：图标 isVisible() 才为真，_best_overlap_icon 才找得到
    # 目标（父窗隐藏时子部件恒不可见，双区判定会整体落空）。show 本身
    # 不触发桌面挂载（那要走 show_desktop -> _try_attach_once），
    # BandGuard 计时器也只在 track() 后启动——测试里两者都不会发生。
    w.show()
    settle(app, 120)
    return w


def icon_rect(icon):
    """图标全局矩形（QWidget 子部件：mapToGlobal + size）。"""
    return QRect(icon.mapToGlobal(QPoint(0, 0)), icon.size())


def core_gpos(icon):
    """拖影中心 = 目标图标正中心（核心区正中）。"""
    return QPoint(icon_rect(icon).center())


def edge_gpos(icon):
    """拖影中心 = 目标中心 + 0.40×图标宽（核心区外、仍大半压在图标上）。

    0.40 > MERGE_CORE_RATIO/2 = 0.275，也大于**滞回外扩后**的 0.305
    （(0.55+0.06)/2）——从核心区刚出来那一帧也不会被滞回吸回去
    （E4f 的回归点）；重叠 = 0.60 >= MERGE_ARM_RATIO，够格进入双区判定。
    """
    r = icon_rect(icon)
    return QPoint(r.center().x() + int(r.width() * 0.40), r.center().y())


class Ghost(QWidget):
    """最小拖影替身：只要 mapToGlobal + size 正确即可。

    窗口标志与真实 `_DragGhost` 一致（ToolTip + Frameless）：带边框的
    普通 QWidget 的客户区原点相对 move() 位置有偏移，会让重叠几何
    整体漂几个像素——双区判定离核心区边界只差 1~2px 时会翻状。
    """

    def __init__(self, w, h):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setFixedSize(w, h)


def arm_drag(icon, ghost):
    """把图标接到最小拖拽态（不走 _exec_drag：窗口级用例只要路由判定）。"""
    ghost.show()
    icon._press_pos = QPoint(ghost.width() // 2, ghost.height() // 2)
    icon._drag_ghost_w = ghost
    icon._drag_mime = QMimeData()
    icon._drag_mime.setData("application/x-desktoporg-item",
                            icon.drag_payload.encode())


def drag_to(src, gpos, nudge=1):
    """真实鼠标不会瞬移：先移到目标区（发 dragEnter），再微移 1px
    （发 dragMove —— _reflow_preview 只在 dragMove 里被驱动，推让
    计时器靠它武装；核心<->让位切换同样依赖这两步）。"""
    src._drag_move(gpos)
    src._drag_move(QPoint(gpos.x() + nudge, gpos.y()))


def main(app):
    # ================= E0 常量契约 =================
    arm = getattr(drag_merge, "MERGE_ARM_RATIO", None)
    core = getattr(drag_merge, "MERGE_CORE_RATIO", None)
    hyst = getattr(drag_merge, "MERGE_CORE_HYSTERESIS", None)
    check("E0a MERGE_ARM_RATIO 存在且落在 (0, 0.5)（压在图标上的门槛）",
          arm is not None and 0 < arm < 0.5, "arm=%s" % (arm,))
    check("E0b MERGE_CORE_RATIO 存在且落在 (0.4, 0.8)（核心区占比）",
          core is not None and 0.4 <= core <= 0.8, "core=%s" % (core,))
    check("E0c MERGE_CORE_HYSTERESIS 存在且够小（防抖带宽）",
          hyst is not None and 0 < hyst < 0.1, "hyst=%s" % (hyst,))
    check("E0d 内缩后核心区仍大于目标 0.4（合并区不会消失）",
          core is not None and hyst is not None and core - hyst > 0.4,
          "core-hyst=%s" % (None if core is None or hyst is None
                            else round(core - hyst, 3),))
    check("E0e 推让晚于合并提示（提示先出现，防'想合并却先被挤走'）",
          DWELL_MERGE_MS < PUSH_DWELL_MS <= 1200,
          "dwell=%s push=%s" % (DWELL_MERGE_MS, PUSH_DWELL_MS))
    check("E0f 旧双阈值模型已废止（不再有 MERGE_OVERLAP_RATIO / defers_push）",
          not hasattr(drag_merge, "MERGE_OVERLAP_RATIO")
          and not hasattr(drag_merge, "defers_push"),
          "残留=%s" % ([n for n in ("MERGE_OVERLAP_RATIO", "defers_push")
                        if hasattr(drag_merge, n)],))
    import src.iconwidget as _iw
    check("E0g iconwidget 不再按重叠比导出合并阈值",
          not hasattr(_iw, "MERGE_OVERLAP_RATIO"))

    # ================= E1 in_merge_core 纯函数 =================
    tgt = (0, 0, 100, 100)                      # 目标矩形
    check("E1a 完全重合（中心=目标中心）-> 合并区",
          drag_merge.in_merge_core((0, 0, 100, 100), tgt) is True)
    check("E1b 中心偏移 20%（< 27.5%）-> 合并区",
          drag_merge.in_merge_core((20, 0, 100, 100), tgt) is True)
    check("E1c 半叠（中心在目标边缘，重叠 0.5）-> 让位区（旧 0.30 会判合并）",
          drag_merge.in_merge_core((50, 0, 100, 100), tgt) is False)
    check("E1d 完全分离 -> 让位区",
          drag_merge.in_merge_core((500, 0, 100, 100), tgt) is False)
    check("E1e 退化拖影（空矩形）-> False",
          drag_merge.in_merge_core((0, 0, 0, 0), tgt) is False)
    check("E1f 退化输入（None）-> False",
          drag_merge.in_merge_core(None, tgt) is False)
    check("E1g 纵向偏移 30% -> 让位区（矩形同律）",
          drag_merge.in_merge_core((0, 30, 100, 100), tgt) is False)

    # 滞回：已在内 -> 有效区外扩；已在外 -> 有效区内缩
    half = 100.0 * core / 2.0                    # 27.5（core=0.55）
    band = 100.0 * hyst / 2.0                    # 3.0（hyst=0.06）
    d_in = half + band * 0.5                     # 刚出边界 1.5px
    d_out = half - band * 0.5                    # 刚进边界 1.5px
    check("E1h 滞回：已在内时外扩（刚出边界不翻出）",
          drag_merge.in_merge_core((d_in, 0, 100, 100), tgt,
                                   was_in=True) is True)
    check("E1i 滞回：已在外时内缩（刚进边界不翻入）",
          drag_merge.in_merge_core((d_out, 0, 100, 100), tgt,
                                   was_in=False) is False)
    check("E1j 无历史（None）按裸核心区判（进得去）",
          drag_merge.in_merge_core((d_out, 0, 100, 100), tgt,
                                   was_in=None) is True)
    check("E1k 无历史（None）按裸核心区判（出得来）",
          drag_merge.in_merge_core((d_in, 0, 100, 100), tgt,
                                   was_in=None) is False)
    # 边界 ±1.5px 抖动 5 次不翻转（E4 规格原话）
    state, flips = True, 0
    for i in range(5):
        g = (half + (band * 0.5 if i % 2 == 0 else -band * 0.5), 0,
             100, 100)
        nxt = drag_merge.in_merge_core(g, tgt, was_in=state)
        if nxt != state:
            flips += 1
        state = nxt
    check("E1l 核心边界 ±1.5px 抖动 5 次零翻转", flips == 0,
          "flips=%d" % flips)

    # ================= E2 窗口级：让位区 -> 武装推让并挤走 =================
    st = make_state()
    w = new_window(app, st)
    src, tgt_icon = w.icons["a"], w.icons["b"]
    r = icon_rect(tgt_icon)
    ghost = Ghost(r.width(), r.height())
    arm_drag(src, ghost)
    drag_to(src, edge_gpos(tgt_icon))
    check("E2a 让位区命中桌面窗口（合并候选以外的落点）",
          src._drag_target is w, "%s" % (src._drag_target,))
    check("E2b 让位区武装推让计时器", w._push_timer.isActive(),
          "cell=%s" % (w._push_cell,))
    check("E2c 推让目标格 = b 所在格", w._push_cell == (1, 0),
          "%s" % (w._push_cell,))
    check("E2d 让位区不武装合并 dwell", not tgt_icon._merge_armed)
    settle(app, DWELL_MERGE_MS + 120)
    check("E2e 停 450ms 也不出合并提示（中心不在核心区）",
          not tgt_icon._merge_armed)
    settle(app, PUSH_DWELL_MS + 250)
    check("E2f 停够 PUSH_DWELL_MS 后 b 被实时挤走",
          cell_of(st, "b") != (1, 0), "b=%s" % (cell_of(st, "b"),))
    check("E2g 拖动者占住目标格", cell_of(st, "a") == (1, 0),
          "a=%s" % (cell_of(st, "a"),))
    src._finish_drag(None)
    ghost.close()
    w.close()

    # ================= E3 窗口级：核心区 -> 提示优先，不挤走 =================
    st = make_state()
    w = new_window(app, st)
    src, tgt_icon = w.icons["a"], w.icons["b"]
    r = icon_rect(tgt_icon)
    ghost = Ghost(r.width(), r.height())
    arm_drag(src, ghost)
    drag_to(src, core_gpos(tgt_icon))
    check("E3a 核心区命中目标图标（合并候选）",
          src._drag_target is tgt_icon, "%s" % (src._drag_target,))
    check("E3b 核心区不武装推让（合并优先）", not w._push_timer.isActive())
    settle(app, DWELL_MERGE_MS + 120)
    check("E3c 450ms 后合并提示武装", tgt_icon._merge_armed)
    settle(app, PUSH_DWELL_MS + 250)
    check("E3d 再等一个推让周期 b 也不动（提示优先）",
          cell_of(st, "b") == (1, 0), "b=%s" % (cell_of(st, "b"),))
    src._finish_drag(None)
    ghost.close()
    w.close()

    # ================= E4 窗口级：核心 <-> 让位区切换 =================
    st = make_state()
    w = new_window(app, st)
    src, tgt_icon = w.icons["a"], w.icons["b"]
    r = icon_rect(tgt_icon)
    ghost = Ghost(r.width(), r.height())
    arm_drag(src, ghost)
    g, e = core_gpos(tgt_icon), edge_gpos(tgt_icon)

    # 让位区 -> 核心区：推让必须撤销（dragLeave 到桌面窗口）
    drag_to(src, e)
    check("E4a 前置：让位区推让已武装", w._push_timer.isActive())
    drag_to(src, g)
    check("E4b 进入核心区撤销推让（不双触发）",
          not w._push_timer.isActive())
    settle(app, PUSH_DWELL_MS + 250)
    check("E4c 推让撤销后 b 不被挤走", cell_of(st, "b") == (1, 0),
          "b=%s" % (cell_of(st, "b"),))
    settle(app, DWELL_MERGE_MS + 120)
    check("E4d 合并提示武装", tgt_icon._merge_armed)

    # 核心区 -> 让位区：dwell 必须撤销 + 推让重新武装
    drag_to(src, e)
    check("E4e 离开核心区撤销合并提示", not tgt_icon._merge_armed)
    check("E4f 离开核心区重新武装推让", w._push_timer.isActive())
    settle(app, PUSH_DWELL_MS + 250)
    check("E4g 推让生效（b 被挤走）", cell_of(st, "b") != (1, 0),
          "b=%s" % (cell_of(st, "b"),))
    src._finish_drag(None)
    ghost.close()
    w.close()

    # ================= E5 端到端：真实拖影 + _drag_move 全链路 =================
    for kind, gpos_of, want_armed, want_push in (
            ("让位区", edge_gpos, False, True),
            ("核心区", core_gpos, True, False)):
        st = make_state()
        w = new_window(app, st)
        src, tgt_icon = w.icons["a"], w.icons["b"]
        r = icon_rect(tgt_icon)
        src._press_pos = QPoint(r.width() // 2, r.height() // 2)
        src._exec_drag()                      # 真实快照拖影 + grabMouse
        try:
            check("E5-%s 拖影已创建且与图标同尺寸" % kind,
                  src._drag_ghost_w is not None
                  and src._drag_ghost_w.size() == tgt_icon.size(),
                  "ghost=%s" % (None if src._drag_ghost_w is None
                                else src._drag_ghost_w.size(),))
            drag_to(src, gpos_of(tgt_icon))
            settle(app, DWELL_MERGE_MS + 120)
            check("E5-%s 450ms 合并提示武装=%s" % (kind, want_armed),
                  tgt_icon._merge_armed is want_armed)
            settle(app, PUSH_DWELL_MS + 250)
            pushed = cell_of(st, "b") != (1, 0)
            check("E5-%s %s" % (kind,
                                "停够后 b 被实时挤走" if want_push
                                else "停够后 b 不被挤走"),
                  pushed is want_push, "b=%s" % (cell_of(st, "b"),))
        finally:
            src._finish_drag(None)
            w.close()

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL edge_push PASSED")
    return 0


def run_main():
    app = QApplication([])
    try:
        code = main(app)
    except Exception:
        import traceback
        traceback.print_exc()
        failures.append("main() 异常")
        code = 1
    try:
        STATE.unlink()
    except Exception:
        pass
    return code


if __name__ == "__main__":
    sys.exit(run_main())
