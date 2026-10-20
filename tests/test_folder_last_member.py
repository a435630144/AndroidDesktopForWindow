# -*- coding: utf-8 -*-
"""文件夹只剩 1 个图标时自动解除文件夹（2026-10-21 用户反馈 10）。

用户原话：「问题10：当桌面文件夹只剩余1个图标的时候，自动解除文件夹。」

语义：成员被移出 / 拖出后，文件夹里只剩 1 个时**整个文件夹解散**——
最后一个成员弹回桌面（网格模式优先占文件夹原格，视觉连续；被占则退
第一个空格），文件夹条目移除，弹窗随之关闭。0 个成员的旧行为（直接
移除文件夹）保持不变。

契约：
  L1 右键移出后剩 1 → 解散：两个成员都回桌面、文件夹条目消失
  L2 拖出后剩 1 → 解散：拖出的落松手格，最后成员回桌面
  L3 最后成员占文件夹原格（视觉连续：文件夹在哪消失、图标就在哪出现）
  L4 剩 3 移出 1 → 剩 2，不解散
  L5 移到一个不剩 → 文件夹移除（旧行为回归）
  L6 解散后弹窗收到 refresh（条目已消失 -> 自动关）
  L7 无界模式同样解散（成员走自由落点）

运行：python tests/test_folder_last_member.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QPoint, QTimer
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.desktop_window import DesktopWindow
from src.storage import Storage

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_folder_last_member_state.json"
failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=200):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def member(i):
    return {"id": "m%d" % i, "name": "M%d" % i, "target": "m%d" % i,
            "kind": "app"}


def make_state(n_members=3, layout_mode="grid"):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"].update({
        "hide_native_icons": False,
        "auto_clone_desktop": False,
        "takeover_desktop": True,
        "layout_mode": layout_mode,
        "dev_mode": False,
    })
    st._data["widgets"] = []
    st._data["layout"] = [
        {"id": "a", "type": "app", "apps": [],
         "app": {"id": "a", "name": "A", "target": "a", "kind": "app"},
         "col": 0, "row": 0},
        {"id": "f", "type": "folder",
         "app": {"id": "f", "name": "F", "kind": "folder"},
         "apps": [member(i) for i in range(n_members)],
         "col": 4, "row": 2},
    ]
    st.save()
    return st


def new_window(app, st):
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    w.rebuild()
    w.show()
    settle(app, 150)
    return w


class FakePopup:
    """只记录 refresh 调用（真实弹窗的自动关闭是既有行为）。"""

    def __init__(self):
        self.refreshed = 0

    def refresh(self):
        self.refreshed += 1


def folder_entry(st):
    return st.find_entry("f")


def desktop_ids(st):
    return [e["id"] for e in st.layout if e.get("type") != "folder"]


def main(app):
    # ---------- L1 右键移出后剩 1 → 解散 ----------
    st = make_state(n_members=2)
    w = new_window(app, st)
    popup = FakePopup()
    w._popup = popup
    w._on_remove_member("M:f:0")
    check("L1 文件夹条目已移除", folder_entry(st) is None)
    check("L1 移出的成员弹回桌面", "m0" in desktop_ids(st),
          "layout=%s" % [e["id"] for e in st.layout])
    check("L1 最后成员也弹回桌面", "m1" in desktop_ids(st),
          "layout=%s" % [e["id"] for e in st.layout])
    check("L1 桌面没有多余条目", len(st.layout) == 3,
          "layout=%s" % [e["id"] for e in st.layout])
    check("L1 弹窗收到 refresh", popup.refreshed == 1)
    w._popup = None

    # ---------- L3 最后成员占文件夹原格（视觉连续） ----------
    st3 = make_state(n_members=2)
    w3 = new_window(app, st3)
    w3._on_remove_member("M:f:0")
    check("L3 剩 2 移出 1 → 解散", folder_entry(st3) is None)
    check("L3 两个成员都回到桌面",
          sorted(desktop_ids(st3)) == ["a", "m0", "m1"],
          "layout=%s" % [e["id"] for e in st3.layout])
    last = st3.find_entry("m1")
    check("L3 最后成员落在文件夹原格",
          last is not None and (last.get("col"), last.get("row")) == (4, 2),
          "pos=%s,%s" % ((last or {}).get("col"), (last or {}).get("row")))

    # ---------- L4 剩 3 移出 1 → 剩 2，不解散 ----------
    st4 = make_state(n_members=3)
    w4 = new_window(app, st4)
    w4._on_remove_member("M:f:0")
    f4 = folder_entry(st4)
    check("L4 还剩 2 个时文件夹保留", f4 is not None)
    check("L4 成员数正确", f4 is not None and len(f4["apps"]) == 2,
          "apps=%s" % ((f4 or {}).get("apps"),))
    check("L4 移出的成员已在桌面", "m0" in desktop_ids(st4))

    # ---------- L5 移到一个不剩 → 文件夹移除（旧行为） ----------
    st5 = make_state(n_members=1)
    w5 = new_window(app, st5)
    w5._on_remove_member("M:f:0")
    check("L5 最后一个成员被移出 → 文件夹移除", folder_entry(st5) is None)
    check("L5 移出的成员在桌面", "m0" in desktop_ids(st5))

    # ---------- L2 拖出后剩 1 → 解散 ----------
    st2 = make_state(n_members=2)
    w2 = new_window(app, st2)
    # 拖 m0 到空格 (6,0)
    cx, cy = grid_flow.cell_pos(st2, 6, 0)
    w2._on_extract("M:f:0", QPoint(cx, cy))
    check("L2 文件夹条目已移除", folder_entry(st2) is None)
    dragged = st2.find_entry("m0")
    check("L2 拖出的成员落松手格",
          dragged is not None and (dragged.get("col"), dragged.get("row")) == (6, 0),
          "pos=%s,%s" % ((dragged or {}).get("col"), (dragged or {}).get("row")))
    check("L2 最后成员也弹回桌面", "m1" in desktop_ids(st2),
          "layout=%s" % [e["id"] for e in st2.layout])

    # ---------- L7 无界模式同样解散 ----------
    st7 = make_state(n_members=2, layout_mode="free")
    w7 = new_window(app, st7)
    w7._on_remove_member("M:f:0")
    check("L7 无界模式同样解散", folder_entry(st7) is None)
    check("L7 无界模式最后成员回桌面", "m1" in desktop_ids(st7),
          "layout=%s" % [e["id"] for e in st7.layout])

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL folder_last_member PASSED")
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
