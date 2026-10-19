# -*- coding: utf-8 -*-
"""probe20：M5 文件夹弹窗重做集成验证（2026-10-18，指导文档 §4.2/§7-M5）。

安全铁律（继承 probe14-19）：
  - offscreen 平台 + 临时 state.json，绝不碰用户真实状态与桌面
  - 不调用 show_desktop()（不挂桌面带、不隐藏原生图标）
  - try/finally + 看门狗 + 幂等收尾，保证进程必退

断言（M5 验收，指导文档 §7-M5 清单逐项）：
  S0  打开文件夹：弹窗可见/不变量（无置顶+NOACTIVATE）+ 幕布创建 +
      源图标打开态 + 锚点定位
  S1  重命名：标题点按 → BandInputBox → Enter 提交 → entry 改名 +
      落盘 + 源图标 tooltip 刷新
  S2  色板：「颜色」pill → 色板浮层 → 点选预设 → entry tint 持久化
      + tintChanged 链路（源图标同一 entry dict，渐变即换）
  S3  ＋ 添加面板：「＋ 添加」pill → 面板 → 点选桌面条目 → 成员并入 +
      桌面源条目增量移除（实例不变、无 rebuild）
  S4  提取成员：extractRequested → 成员落桌增量淡入 + 弹窗刷新仍开
  S5  清空 + 解散：removeMember 最后一个成员 → 空文件夹移除 →
      refresh 自动关弹窗 → 幕布销毁 + 源图标退出打开态 + 图标增量移除
  S6  关闭四路径：幕布点击 / 同文件夹二击 / 桌面空白点击 / × 按钮
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from src import theme
from src.desktop_window import DesktopWindow
from src.folder_popup import ScrimWindow
from src.storage import Storage

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "probe20_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra), flush=True)
    if not cond:
        failures.append(name)


def settle(app, ms=400):
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
    # 2026-10-19 反馈 3：未接管会自动进入无界模式，网格让位探针
    # 必须显式声明「按接管语义」（不 show 窗口，不会真隐藏原生图标）
    st._data["settings"]["takeover_desktop"] = True
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["widgets"] = [dict(w) for w in widgets]
    st._data["layout"] = [
        {"id": i, "type": t,
         "app": None if t == "folder" else {"name": i, "target": i,
                                            "kind": "app"},
         "apps": apps, "name": (i if t == "folder" else None),
         "col": c, "row": r}
        for i, c, r, t, apps in spec]
    st.save()
    return st


def send_click(w, local):
    """单击（press+release）合成事件；全局 = 窗口坐标 + 局部。"""
    g = QPointF(w.pos()) + QPointF(local)
    for etype in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        ev = QMouseEvent(etype, QPointF(local), g, Qt.LeftButton,
                         Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(w, ev)


def click_rect_center(w, rect):
    send_click(w, rect.center())


def run(app):
    # 桌面：a / b 两个应用 + 文件夹 f（成员 m1/m2，row 0 区）
    st = make_state([("a", 8, 0, "app", []),
                     ("b", 9, 0, "app", []),
                     ("f", 8, 1, "folder",
                      [{"name": "m1", "target": "m1", "kind": "app"},
                       {"name": "m2", "target": "m2", "kind": "app"}])])
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    settle(app, 150)
    ids0 = {eid: id(ic) for eid, ic in w.icons.items()}

    # ---------- S0：打开文件夹 ----------
    w.open_folder("f")
    settle(app, 250)
    popup = w._popup
    check("S0 弹窗已创建且可见", popup is not None and popup.isVisible())
    check("S0 幕布已创建且可见", w._scrim is not None
          and w._scrim.isVisible())
    icon = w.icons.get("f")
    check("S0 源图标进入打开态", icon is not None
          and icon._folder_open is True)
    flags = popup.windowFlags()
    check("S0 弹窗无置顶（不盖应用窗口）",
          not (flags & Qt.WindowStaysOnTopHint))
    check("S0 弹窗 NOACTIVATE（不抢焦点）",
          bool(flags & Qt.WindowDoesNotAcceptFocus))
    check("S0 弹窗有合理尺寸（成员 2 列起步）",
          popup.width() >= 240 and popup.height() >= 150,
          "%sx%s" % (popup.width(), popup.height()))
    check("S0 弹窗锚点在源图标附近（同屏）",
          abs(popup.x() - icon.x()) < W and abs(popup.y() - icon.y()) < H,
          "popup=(%s,%s) icon=(%s,%s)" % (popup.x(), popup.y(),
                                          icon.x(), icon.y()))
    check("S0 未挂桌面带时探针不调 attach（attached=False）",
          w.attached is False)

    # ---------- S1：重命名 ----------
    click_rect_center(popup, popup._title_rect())
    settle(app, 120)
    box = popup._editor
    check("S1 标题点按弹出行内输入框", box is not None)
    if box is not None:
        box.line.setText("工作")
        ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        QApplication.sendEvent(box.line, ev)
        settle(app, 150)
        check("S1 Enter 提交：entry 改名", st.find_entry("f")["name"] == "工作",
              "%s" % st.find_entry("f").get("name"))
        reloaded = Storage(path=str(STATE))
        check("S1 改名已落盘",
              reloaded.find_entry("f")["name"] == "工作")
        check("S1 输入框已关闭", popup._editor is None)
        check("S1 源图标 tooltip 刷新为新名",
              "工作" in (icon.toolTip() or ""), "%s" % icon.toolTip())

    # ---------- S2：色板 ----------
    click_rect_center(popup, dict(popup._bar_rects())["color"])
    settle(app, 120)
    check("S2 「颜色」pill 打开色板浮层", popup._palette_open is True)
    swatches = popup._palette_layout()
    pick = swatches[2]                      # 第 3 个预设（橙）
    click_rect_center(popup, pick[0])
    settle(app, 150)
    check("S2 点选预设：entry tint 持久化",
          st.find_entry("f").get("tint") == pick[1].name(),
          "%s vs %s" % (st.find_entry("f").get("tint"), pick[1].name()))
    check("S2 源图标读到同一 tint（渐变即换）",
          icon.entry.get("tint") == pick[1].name())
    check("S2 色板浮层已收起", popup._palette_open is False)
    reloaded = Storage(path=str(STATE))
    check("S2 tint 已落盘", reloaded.find_entry("f").get("tint")
          == pick[1].name())

    # ---------- S3：＋ 添加面板 ----------
    click_rect_center(popup, dict(popup._bar_rects())["add"])
    settle(app, 120)
    check("S3 「＋ 添加」pill 打开添加面板", popup._add_panel_open is True)
    rects, _sz = popup._add_panel_layout()
    target = next((r for r, eid in rects if eid == "a"), None)
    check("S3 添加面板候选含桌面条目 a", target is not None,
          "%s" % [eid for _r, eid in rects])
    if target is not None:
        click_rect_center(popup, target)
        settle(app, 300)
        names = [m.get("name") for m in st.find_entry("f").get("apps", [])]
        check("S3 点选加入：成员含 a", "a" in names, "%s" % names)
        check("S3 桌面源条目 a 已从布局移除",
              st.find_entry("a") is None)
        check("S3 源条目图标增量移除", "a" not in w.icons)
        check("S3 其余图标实例不变（无 rebuild）",
              all(id(w.icons.get(eid)) == i for eid, i in ids0.items()
                  if eid in w.icons))
        reloaded = Storage(path=str(STATE))
        check("S3 成员并入已落盘",
              "a" in [m.get("name") for m in
                      reloaded.find_entry("f").get("apps", [])]
              and reloaded.find_entry("a") is None)
        check("S3 弹窗仍在（添加后面板收起）",
              w._popup is popup and popup.isVisible())

    # ---------- S4：提取成员到桌面 ----------
    popup.extractRequested.emit("M:f:0")   # 提取 m1
    settle(app, 400)
    names = [m.get("name") for m in st.find_entry("f").get("apps", [])]
    check("S4 提取后成员移除 m1", "m1" not in names, "%s" % names)
    new_e = next((e for e in st.layout
                  if (e.get("app") or {}).get("name") == "m1"), None)
    check("S4 m1 落桌（布局有新条目）", new_e is not None)
    if new_e is not None:
        check("S4 m1 图标增量淡入在位", new_e["id"] in w.icons)
    check("S4 其余图标实例不变",
          all(id(w.icons.get(eid)) == i for eid, i in ids0.items()
              if eid in w.icons))
    check("S4 弹窗刷新后仍可见", popup.isVisible())

    # ---------- S5：移除最后成员 → 空文件夹解散 → 自动关弹窗 ----------
    # S4 后成员为 [m2, a]：连移两个才空
    popup.removeMember.emit("M:f:0")       # 移除 m2
    settle(app, 300)
    popup.removeMember.emit("M:f:0")       # 移除 a → 空
    settle(app, 700)                       # 等收起动画 + closeEvent
    check("S5 空文件夹条目已移除", st.find_entry("f") is None)
    check("S5 弹窗已自动关闭", w._popup is None)
    check("S5 幕布已销毁", w._scrim is None)
    check("S5 源图标退出打开态", w._folder_open_icon is None)
    check("S5 源图标增量移除", "f" not in w.icons)
    check("S5 桌面图标实例全程不变",
          all(id(w.icons.get(eid)) == i for eid, i in ids0.items()
              if eid in w.icons))

    # ---------- S6：关闭四路径（每次新建文件夹） ----------
    def fresh_folder(fid="f2", member="m3"):
        st._data["layout"].append(
            {"id": fid, "type": "folder", "app": None, "name": fid,
             "apps": [{"name": member, "target": member, "kind": "app"}],
             "col": 8, "row": 3})
        st.save()
        w._sync_structure()
        settle(app, 200)

    def closed_ok(tag):
        check("%s 弹窗引用已清" % tag, w._popup is None)
        check("%s 幕布已销毁" % tag, w._scrim is None)
        ic = w.icons.get("f2")
        check("%s 源图标退出打开态" % tag,
              ic is None or ic._folder_open is False)

    # S6a 幕布点击关闭
    fresh_folder()
    w.open_folder("f2")
    settle(app, 250)
    check("S6a 打开后幕布在位", w._scrim is not None)
    send_click(w._scrim, w._scrim.rect().center())
    settle(app, 700)
    closed_ok("S6a 幕布点击")

    # S6b 同文件夹二击 = 关闭（iOS 语义）
    fresh_folder()
    w.open_folder("f2")
    settle(app, 250)
    w.open_folder("f2")
    settle(app, 700)
    closed_ok("S6b 同文件夹二击")

    # S6c 桌面空白点击关闭
    fresh_folder()
    w.open_folder("f2")
    settle(app, 250)
    send_click(w, QPoint(20, H - 40))      # 窗口左下角空白
    settle(app, 700)
    closed_ok("S6c 桌面空白点击")

    # S6d × 按钮关闭（弹窗自行关闭 → closeEvent → closed 信号链路）
    fresh_folder()
    w.open_folder("f2")
    settle(app, 250)
    click_rect_center(w._popup, w._popup._close_rect())
    settle(app, 700)
    closed_ok("S6d × 按钮")

    # ---------- 收尾 ----------
    if w._popup is not None:
        w._popup.close()
    if w._scrim is not None:
        w._scrim.close()
    settle(app, 300)


def main():
    app = QApplication([])
    wd = QTimer()
    wd.setSingleShot(True)
    wd.timeout.connect(lambda: (print("!! 看门狗超时", flush=True),
                                os._exit(3)))
    wd.start(90000)
    try:
        run(app)
    except Exception:
        import traceback
        traceback.print_exc()
        failures.append("run() 异常")
    finally:
        try:
            STATE.unlink()
        except Exception:
            pass
    print("-" * 56, flush=True)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures), flush=True)
        code = 1
    else:
        print("ALL probe20 PASSED", flush=True)
        code = 0
    print("==== 探针退出 ====", flush=True)
    app.processEvents()
    QTimer.singleShot(80, app.quit)
    app.exec()
    return code


if __name__ == "__main__":
    sys.exit(main())
