# -*- coding: utf-8 -*-
"""每页排序规则（v9 V2，指导文档_v9.md §3.3）。

契约：
  P1  默认：未启用"每页单独设置" -> 所有页跟随全局开关
  P2  全局 True -> 所有页自动；全局 False -> 所有页自由
  P3  启用独立设置后：显式 auto / free 页生效，未写的页仍跟随全局
  P4  写入落成 {"页号(str)": "auto"|"free"}，能跨进程读回
  P5  回到「跟随全局」= 删掉该页的键（不留下无效键）
  P6  auto_pages() 给出自动页集合（供 grid_flow 按页密排）
  P7  describe() 用中文讲清"这一页实际怎么排"
  P8  脏值（"whatever" / None）一律按跟随全局处理，不抛异常

运行：python tests/test_page_rules.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import page_rules as pr
from src.storage import Storage

STATE = Path(tempfile.gettempdir()) / "test_page_rules_state.json"

CHECKS = []
failures = []


def check(name, cond, extra=""):
    CHECKS.append(name)
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def fresh():
    if STATE.exists():
        STATE.unlink()
    return Storage(STATE)


def main():
    # ---------- P1 默认跟随全局 ----------
    st = fresh()
    check("P1a 默认未启用独立设置", pr.custom_enabled(st) is False)
    check("P1b 默认全局关闭 -> 不自动", pr.mode_for(st, 0) is False)
    st.set_setting("auto_arrange", True)
    check("P1c 全局打开 -> 每页都自动",
          all(pr.mode_for(st, p) for p in range(4)), str([pr.mode_for(st, p) for p in range(4)]))

    # ---------- P2 全局开关直通 ----------
    st.set_setting("auto_arrange", False)
    check("P2 全局关 -> 所有页都不自动",
          not any(pr.mode_for(st, p) for p in range(4)))

    # ---------- P3/P4 逐页覆盖 ----------
    pr.set_custom(st, True)
    pr.set_mode(st, 1, pr.FREE)
    pr.set_mode(st, 2, pr.AUTO)
    st.set_setting("auto_arrange", False)      # 全局关：独立页仍应生效
    check("P3a 显式 free 页 = 自由", pr.mode_for(st, 1) is False)
    check("P3b 显式 auto 页 = 自动", pr.mode_for(st, 2) is True)
    check("P3c 未写的页跟随全局（关）", pr.mode_for(st, 0) is False)
    st.set_setting("auto_arrange", True)
    check("P3d 未写的页跟随全局（开）", pr.mode_for(st, 0) is True)
    check("P3e 全局开也不影响显式 free 页", pr.mode_for(st, 1) is False)

    # ---------- P4 落盘形态 ----------
    raw = json.loads(STATE.read_text(encoding="utf-8"))
    saved = raw["settings"]["page_rules"]
    check("P4a 键是字符串页号", set(saved) == {"1", "2"}, str(saved))
    check("P4b 值是 auto/free", saved == {"1": "free", "2": "auto"}, str(saved))
    again = Storage(STATE)
    check("P4c 重新加载后规则仍生效",
          pr.mode_for(again, 1) is False and pr.mode_for(again, 2) is True)

    # ---------- P5 回到跟随全局 ----------
    pr.set_mode(again, 2, pr.INHERIT)
    check("P5a 键被删掉", "2" not in (again.get_setting("page_rules") or {}),
          str(again.get_setting("page_rules")))
    check("P5b 该页回到跟随全局", pr.mode_for(again, 2) is True)

    # ---------- P6 auto_pages ----------
    pages = pr.auto_pages(again, 5)
    check("P6 auto_pages 给出自动页集合", pages == {0, 2, 3, 4}, str(sorted(pages)))

    # ---------- P7 describe ----------
    check("P7a free 页说明", pr.describe(again, 1) == "自由摆放", pr.describe(again, 1))
    check("P7b 跟随全局页说明含实际结果",
          "跟随全局" in pr.describe(again, 3) and "自动" in pr.describe(again, 3),
          pr.describe(again, 3))

    # ---------- P8 脏值 ----------
    again.set_setting("page_rules", {"0": "whatever", "3": None, "4": "AUTO"})
    check("P8a 脏值按跟随全局", pr.mode_for(again, 0) is True,
          str(again.get_setting("page_rules")))
    check("P8b None 不抛异常", pr.rule_of(again, 3) == pr.INHERIT)
    check("P8c 大小写不同的值也不认（只接受常量）",
          pr.rule_of(again, 4) == pr.INHERIT, pr.rule_of(again, 4))
    again.set_setting("page_rules", "not-a-dict")
    check("P8d 整个 page_rules 坏掉时不崩", pr.mode_for(again, 0) is True)

    if STATE.exists():
        STATE.unlink()

    print("\n%d checks, %d failures" % (len(CHECKS), len(failures)))
    if failures:
        print("FAILED:", ", ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
