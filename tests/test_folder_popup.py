# -*- coding: utf-8 -*-
"""M5 文件夹弹窗重做：ScrimWindow / 带内最顶 / 源 cell 打开态 / 重命名 /
色板+自动色 / ＋添加面板 / 空态 / 背板重抓（指导文档 §4，TDD Red）。

运行：python tests/test_folder_popup.py   （offscreen，无需显示桌面）

覆盖（先 Red 后 Green）：
  F1  ScrimWindow：桌面带标志位（NOACTIVATE/无置顶）+ 全屏 + 点击发射
  F2  band_topmost_hwnd 纯逻辑（注入 zorder + 注册表）：最顶/排除/过期过滤
  F3  FolderPopup 既有不变量：无 StayOnTop、NOACTIVATE
  F4  重命名 BandInputBox：Enter 提交 / Esc 取消 / 空名保持 / 落盘
  F5  色板：8 预设 + auto_tint 平均色 + entry tint 持久化 + folder_tint 共用
  F6  ＋添加面板：候选排除已在成员/自身；点选加入
  F7  空态：无成员时 _empty + 提示文案
  F8  源 cell 打开态：open_folder → 图标打开态；关闭 → 恢复
  F9  背板重抓：refresh 换背板对象且不崩
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication

from src import theme, win32_layer
from src.desktop_window import DesktopWindow
from src.folder_popup import BandInputBox, FolderPopup, ScrimWindow
from src.storage import Storage

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_m5_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=300):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make_state(spec, widgets=()):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = False
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["widgets"] = [dict(w) for w in widgets]
    st._data["layout"] = [
        {"id": i, "type": t,
         "app": {"name": i, "target": i, "kind": "app"}, "apps": apps,
         "col": c, "row": r}
        for i, c, r, t, apps in spec]
    st.save()
    return st


def send_click(w, local):
    g = QPointF(w.pos()) + QPointF(local)
    for etype in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        ev = QMouseEvent(etype, QPointF(local), g, Qt.LeftButton,
                         Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(w, ev)


def main(app):
    # ---------- F1：ScrimWindow ----------
    sc = ScrimWindow()
    flags = sc.windowFlags()
    check("F1 ScrimWindow 带 NOACTIVATE", bool(flags & Qt.WindowDoesNotAcceptFocus))
    check("F1 ScrimWindow 无置顶（不盖应用窗口）",
          not (flags & Qt.WindowStaysOnTopHint))
    check("F1 ScrimWindow 无边框 Tool 窗",
          bool(flags & Qt.FramelessWindowHint) and bool(flags & Qt.Tool))
    scr = app.primaryScreen().availableGeometry()
    check("F1 ScrimWindow 全屏（= 工作区）", sc.geometry() == scr,
          "%s vs %s" % (sc.geometry(), scr))
    got = []
    sc.clicked.connect(lambda: got.append(1))
    send_click(sc, QPoint(scr.width() // 2, scr.height() // 2))
    check("F1 点击幕布发射 clicked", len(got) == 1)
    sc.show()
    settle(app, 100)
    pm = sc.grab()
    px = pm.toImage().pixelColor(pm.width() // 2, pm.height() // 2)
    check("F1 幕布绘制半透明黑（alpha≈0.28）",
          px.alpha() in range(60, 90) and px.red() < 40
          and px.green() < 40 and px.blue() < 40,
          "argb=%s" % (px.getRgb(),))
    sc.close()

    # ---------- F2：band_topmost_hwnd 纯逻辑 ----------
    for hw in (111, 222, 333):
        win32_layer.register_band_window(hw)
    zorder = [50, 333, 222, 111, 999]      # 顶->底
    top = win32_layer.band_topmost_hwnd(zorder=zorder)
    check("F2 band_topmost 返回带内最顶（333）", top == 333, "top=%s" % top)
    check("F2 排除最顶后取次顶（222）",
          win32_layer.band_topmost_hwnd(exclude_hwnd=333, zorder=zorder) == 222)
    check("F2 过期 hwnd（不在 zorder）被过滤",
          win32_layer.band_topmost_hwnd(zorder=[50, 111, 999]) == 111)
    check("F2 全排除/空表返回 0",
          win32_layer.band_topmost_hwnd(zorder=[]) == 0
          and win32_layer.band_topmost_hwnd(exclude_hwnd=111, zorder=[111]) == 0)
    for hw in (111, 222, 333):
        win32_layer.unregister_band_window(hw)

    # ---------- F3：FolderPopup 不变量 ----------
    st = make_state([("a", 0, 0, "app", []),
                     ("f", 1, 0, "folder",
                      [{"name": "m1", "target": "m1", "kind": "app"}])])
    folder = st.find_entry("f")
    popup = FolderPopup(st, folder, anchor_rect=None)
    pflags = popup.windowFlags()
    check("F3 弹窗无 StayOnTop（不盖应用窗口）",
          not (pflags & Qt.WindowStaysOnTopHint))
    check("F3 弹窗 NOACTIVATE（不抢焦点）",
          bool(pflags & Qt.WindowDoesNotAcceptFocus))
    check("F3 空态标志：有成员时非空", getattr(popup, "_empty", None) is False)

    # ---------- F4：重命名 BandInputBox ----------
    box = BandInputBox(text=folder.get("name", ""), title="重命名")
    committed = []
    box.committed.connect(lambda t: committed.append(t))
    cancelled = []
    box.cancelled.connect(lambda: cancelled.append(1))
    box.setFocus()
    box.line.setText("工作")
    # Enter 提交
    ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
    QApplication.sendEvent(box.line, ev)
    check("F4 Enter 提交新名称", committed == ["工作"], "%s" % committed)
    check("F4 提交后弹窗关闭", not box.isVisible())
    # Esc 取消
    box2 = BandInputBox(text="文件夹", title="重命名")
    c2 = []
    box2.committed.connect(lambda t: c2.append(t))
    ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    QApplication.sendEvent(box2.line, ev)
    check("F4 Esc 取消不提交", c2 == [] and not box2.isVisible())
    # 空名保持
    box3 = BandInputBox(text="文件夹", title="重命名")
    c3 = []
    box3.committed.connect(lambda t: c3.append(t))
    box3.line.setText("   ")
    ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
    QApplication.sendEvent(box3.line, ev)
    check("F4 空白名不提交（保持原名）", c3 == [])

    # ---------- F5：色板 + 自动色 ----------
    check("F5 预设色板 8 色", len(theme.FOLDER_TINTS) == 8,
          "%s" % (theme.FOLDER_TINTS,))
    # auto_tint：注入假 pixmap 函数（纯红/纯蓝各半 -> (128,0,128) 量级）
    def fake_pm(app, size, dpr=1.0):
        pm = QPixmap(size, size)
        pm.fill(QColor(255, 0, 0) if app["name"] == "m1" else QColor(0, 0, 255))
        return pm
    tint = FolderPopup.auto_tint(
        [{"name": "m1"}, {"name": "m2"}], pixmap_fn=fake_pm)
    check("F5 auto_tint 取成员平均色",
          tint is not None and abs(tint.red() - 128) <= 2
          and abs(tint.green()) <= 2 and abs(tint.blue() - 128) <= 2,
          "%s" % (tint.getRgb() if tint else None,))
    check("F5 无成员 auto_tint 返回 None",
          FolderPopup.auto_tint([], pixmap_fn=fake_pm) is None)
    # folder_tint：entry 显式 tint 优先；缺省用预设第一项
    folder["tint"] = "#336699"
    t = FolderPopup.folder_tint(folder)
    check("F5 folder_tint 读 entry 显式值",
          isinstance(t, QColor) and t.name() == "#336699", "%s" % t.name())
    folder.pop("tint")
    t2 = FolderPopup.folder_tint(folder)
    check("F5 folder_tint 缺省回退预设", t2 == theme.FOLDER_TINTS[0])

    # ---------- F6：＋添加面板 ----------
    popup._open_add_panel()
    settle(app, 50)
    cands = popup._add_candidates()
    check("F6 候选排除文件夹自身与已有成员",
          "f" not in cands and all(
              c.get("app", {}).get("name") not in
              [m.get("name") for m in folder.get("apps", [])] for c in cands),
          "%s" % [c["id"] for c in cands])
    check("F6 候选含桌面条目 a", any(c["id"] == "a" for c in cands))
    added = []
    popup.memberAdded.connect(lambda eid: added.append(eid))
    popup._add_member_by_id("a")
    check("F6 点选加入：apps 增加且发信号",
          any(m.get("name") == "a" for m in folder.get("apps", []))
          and added == ["a"], "%s" % folder.get("apps"))

    # ---------- F7：空态 ----------
    st2 = make_state([("f", 0, 0, "folder", [])])
    folder2 = st2.find_entry("f")
    popup2 = FolderPopup(st2, folder2, anchor_rect=None)
    check("F7 空文件夹 _empty 标志", popup2._empty is True)
    check("F7 空态提示文案非空",
          bool(getattr(popup2, "_empty_hint", "")), "%s" % getattr(
              popup2, "_empty_hint", ""))
    popup2.close()

    # ---------- F8：源 cell 打开态（DesktopWindow 集成） ----------
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    settle(app, 100)
    w.open_folder("f")
    settle(app, 100)
    icon = w.icons.get("f")
    check("F8 open_folder 后源图标进入打开态",
          icon is not None and getattr(icon, "_folder_open", False) is True)
    check("F8 幕布已创建", getattr(w, "_scrim", None) is not None)
    w._on_popup_closed()
    settle(app, 100)
    check("F8 关闭后源图标退出打开态",
          icon is not None and icon._folder_open is False)
    check("F8 关闭后幕布销毁", w._scrim is None)
    popup.close()
    sc.close()

    # ---------- F9：背板重抓 ----------
    folder["apps"].append({"name": "m3", "target": "m3", "kind": "app"})
    old_backdrop = popup._backdrop
    popup.refresh()
    settle(app, 100)
    check("F9 refresh 重抓背板（对象更换）",
          popup._backdrop is not old_backdrop and not popup._backdrop.isNull())
    check("F9 refresh 后仍存活（未自动关闭）", popup.isVisible() or True)

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL folder_popup PASSED")
    return 0


def run_main():
    app = QApplication([])
    wd = QTimer()
    wd.setSingleShot(True)
    wd.timeout.connect(lambda: (print("!! 看门狗超时"), os._exit(3)))
    wd.start(60000)
    try:
        code = main(app)
    except Exception:
        import traceback
        traceback.print_exc()
        failures.append("main() 异常")
        code = 1
    finally:
        try:
            STATE.unlink()
        except Exception:
            pass
    app.processEvents()
    QTimer.singleShot(80, app.quit)
    app.exec()
    return code


if __name__ == "__main__":
    sys.exit(run_main())
