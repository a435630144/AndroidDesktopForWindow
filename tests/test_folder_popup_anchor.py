# -*- coding: utf-8 -*-
"""文件夹弹窗必须贴着文件夹图标展开（2026-10-20 用户反馈 F4）。

现象：文件夹展开后弹窗离文件夹很远（跑到网格区中心），用户要的是
"在旁边弹出"。

病根：`FolderPopup._build` 把弹窗**居中到当前页网格区中心**
（v6 §6.2 为"模态面板"刻意做的决策），与直觉不符 —— 本次按用户反馈
覆盖该决策（指导文档 §11.4）。

契约：
  Q1 常规：放在图标正下方 10px、水平居中对齐图标
  Q2 图标靠屏幕底边 -> 翻到图标正上方
  Q3 上下都放不下 -> 夹紧进可用屏幕（不越界）
  Q4 图标贴左边 -> 弹窗左边界不越出屏幕
  Q5 无 anchor -> 回退网格区居中（旧行为兜底不变）
  Q6 窗口级：FolderPopup 构造后位置 = place_beside 计算结果

运行：python tests/test_folder_popup_anchor.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from src import folder_popup, grid_flow
from src.storage import Storage

STATE = Path(tempfile.gettempdir()) / "test_folder_anchor_state.json"

failures = []

AVAIL = (0, 0, 1920, 1040)          # 可用屏幕（任务栏已扣）
GAP = getattr(folder_popup, "BESIDE_GAP", 10)
MARGIN = getattr(folder_popup, "BESIDE_MARGIN", 8)


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def make_state(folder_apps=None):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"].update({
        "hide_native_icons": False,
        "auto_clone_desktop": False,
        "takeover_desktop": True,
        "layout_mode": "grid",
        "dev_mode": False,
    })
    st._data["widgets"] = []
    st._data["layout"] = [{
        "id": "f1", "type": "folder", "name": "测试夹", "col": 0, "row": 0,
        "apps": list(folder_apps or []),
    }]
    st.save()
    return st


def main(app):
    fn = getattr(folder_popup, "place_beside", None)
    check("Q0 存在纯函数 place_beside", fn is not None)

    if fn is not None:
        # ---------- Q1：常规（图标在屏幕中部）----------
        anchor = (500, 300, 90, 110)      # 图标全局矩形
        x, y = fn(anchor, 320, 240, AVAIL)
        check("Q1a 放在图标正下方（底 + gap）",
              y == 300 + 110 + GAP, "y=%d expect=%d" % (y, 300 + 110 + GAP))
        check("Q1b 水平居中对齐图标",
              x == 500 + 90 // 2 - 320 // 2,
              "x=%d expect=%d" % (x, 500 + 90 // 2 - 320 // 2))

        # ---------- Q2：靠屏幕底边 -> 翻到上方 ----------
        anchor2 = (500, 950, 90, 80)      # 底 = 1030，下方放不下 240 高
        x2, y2 = fn(anchor2, 320, 240, AVAIL)
        check("Q2 翻到图标正上方", y2 == 950 - GAP - 240,
              "y=%d expect=%d" % (y2, 950 - GAP - 240))
        check("Q2 弹窗底边不盖住图标", y2 + 240 <= 950,
              "bottom=%d" % (y2 + 240))

        # ---------- Q3：上下都放不下 -> 夹紧 ----------
        anchor3 = (500, 500, 90, 100)
        x3, y3 = fn(anchor3, 320, 900, AVAIL)      # 900 高，上下都没空间
        check("Q3 夹紧进屏幕（不越上界）", y3 >= 0, "y=%d" % y3)
        check("Q3 夹紧进屏幕（不越下界）", y3 + 900 <= 1040,
              "bottom=%d" % (y3 + 900))

        # ---------- Q4：贴左边 -> 水平夹紧 ----------
        anchor4 = (0, 300, 90, 110)
        x4, _y4 = fn(anchor4, 320, 240, AVAIL)
        check("Q4 左边界不越出屏幕", x4 >= MARGIN, "x=%d" % x4)
        anchor5 = (1850, 300, 90, 110)
        x5, _y5 = fn(anchor5, 320, 240, AVAIL)
        check("Q4 右边界不越出屏幕", x5 + 320 <= 1920 - MARGIN,
              "right=%d" % (x5 + 320))

    # ---------- Q6：窗口级（真实 FolderPopup）----------
    st = make_state()
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)
    anchor_rect = QRect(600, 260, 90, 110)
    pop = folder_popup.FolderPopup(st, st.layout[0], anchor_rect)
    if fn is not None:
        exp_x, exp_y = fn((anchor_rect.x(), anchor_rect.y(),
                           anchor_rect.width(), anchor_rect.height()),
                          pop.width(), pop.height(), AVAIL)
        check("Q6 弹窗位置 = place_beside 结果",
              (pop.x(), pop.y()) == (exp_x, exp_y),
              "got=(%d,%d) expect=(%d,%d)" % (pop.x(), pop.y(), exp_x, exp_y))
    check("Q6 弹窗紧贴图标下方（图标底边 + gap）",
          pop.y() == anchor_rect.y() + anchor_rect.height() + GAP,
          "popup_y=%d expect=%d" % (
              pop.y(), anchor_rect.y() + anchor_rect.height() + GAP))
    icon_cx = anchor_rect.center().x()
    pop_cx = pop.x() + pop.width() // 2
    check("Q6 弹窗水平居中对齐图标（不是网格区中心）",
          abs(pop_cx - icon_cx) <= 4,
          "popup_cx=%d icon_cx=%d" % (pop_cx, icon_cx))
    pop.close()

    # ---------- Q5：无 anchor -> 回退网格区居中 ----------
    # 注意 offscreen 主屏只有 800x800（不同机器尺寸不同）：断言按"旧公式"
    # 锁定语义（居中后夹紧进可用屏幕），不写死任何机器数值。
    st2 = make_state()
    grid_flow.set_grid(st2, (1920, 1040))
    cx, cy = grid_flow.page_grid_center(st2)
    pop2 = folder_popup.FolderPopup(st2, st2.layout[0], None)
    geo = QGuiApplication.primaryScreen().availableGeometry()
    exp_x = max(geo.left() + 8,
                min(cx - pop2.width() // 2, geo.right() - pop2.width() - 8))
    exp_y = max(geo.top() + 8,
                min(cy - pop2.height() // 2, geo.bottom() - pop2.height() - 8))
    check("Q5 无 anchor 时 x 走旧公式（居中 + 夹紧）", pop2.x() == exp_x,
          "x=%d expect=%d geo=%s" % (pop2.x(), exp_x, geo))
    check("Q5 无 anchor 时 y 走旧公式（居中 + 夹紧）", pop2.y() == exp_y,
          "y=%d expect=%d" % (pop2.y(), exp_y))
    check("Q5 无 anchor 时位置与锚点无关（弹窗在屏幕内）",
          geo.left() <= pop2.x() and pop2.x() + pop2.width() <= geo.right() + 1,
          "x=%d w=%d" % (pop2.x(), pop2.width()))
    pop2.close()


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    crashed = None
    try:
        main(app)
    except Exception:
        import traceback
        traceback.print_exc()
        crashed = "exception"
    finally:
        print("")
        if crashed or failures:
            print("FAILED %d: %s" % (len(failures), failures))
            sys.stdout.flush()
            os._exit(1)
        print("ALL PASSED")
        sys.stdout.flush()
        os._exit(0)
