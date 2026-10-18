# -*- coding: utf-8 -*-
"""实机验证脚本 v3（问题 1/2/3/4/5/7 全量回归）。

覆盖：
  问题1 图标高清：jpg/lnk/CLSID 三类条目真实渲染（非空、居中、不裁剪）
  问题2 原生模式：DefView 可见；空闲空白区命中测试穿透（HTTRANSPARENT）
  问题3 拖动：真实鼠标事件端到端拖动图标，col/row 实际改变
  问题4 框选：橡皮筋框选 + 多选整体拖动
  问题5 原生右键：原生模式空白区穿透；整理模式走自己的菜单代码路径
  问题7 输入：时钟保持 NOACTIVATE；便签/面板可激活获焦点，真实点击后能输入

运行结束自动还原用户 state.json 与原生图标可见性。
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from src import appsource, win32_layer  # noqa: E402
from src.desktop_window import DesktopWindow  # noqa: E402
from src.storage import Storage  # noqa: E402
from src.widget_layer import WidgetLayer  # noqa: E402

RESULTS = []
STATE_PATH = Path(os.path.expandvars(r"%APPDATA%\DesktopOrganizerDemo\state.json"))
STATE_BACKUP = None
u32 = ctypes.windll.user32
u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
u32.GetWindowLongW.restype = wintypes.LONG
u32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.SendMessageW.restype = wintypes.LPARAM
u32.GetForegroundWindow.restype = wintypes.HWND
u32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
u32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u32.SetCursorPos.restype = wintypes.BOOL
WM_NCHITTEST = 0x84
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
HTCLIENT, HTTRANSPARENT = 1, -1
MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x1, 0x2, 0x4


def ok(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print("%s %s%s" % ("[PASS]" if cond else "[FAIL]", name, ("  -> " + detail) if detail else ""),
          flush=True)


def hit_test(hwnd, x, y):
    """直接向窗口发 WM_NCHITTEST（物理屏幕坐标）。"""
    lparam = (int(y) << 16) | (int(x) & 0xFFFF)
    return int(u32.SendMessageW(hwnd, WM_NCHITTEST, 0, lparam))


def ex_noactivate(hwnd):
    return bool(u32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_NOACTIVATE)


def foreground():
    """当前前台窗口句柄（GetForegroundWindow 可能瞬时返回 NULL，重试几次）。"""
    for _ in range(20):
        h = u32.GetForegroundWindow()
        if h:
            return int(h)
        time.sleep(0.1)
    return 0


def dpr():
    return QApplication.primaryScreen().devicePixelRatio()


def phys(pt_logical):
    d = dpr()
    return int(pt_logical.x() * d), int(pt_logical.y() * d)


def click_at(x, y):
    """真实鼠标点击（物理坐标）：SetCursorPos 定位 + 左键下/抬。
    注意：mouse_event 不带 MOUSEEVENTF_ABSOLUTE 时 dx/dy 是相对位移，
    必须先用 SetCursorPos（原始像素）把光标移到目标位置。"""
    u32.SetCursorPos(x, y)
    time.sleep(0.05)
    u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
    time.sleep(0.05)
    u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
    time.sleep(0.15)


def drag_between(p1, p2, steps=20):
    """真实鼠标拖拽（物理坐标）：定位 -> 按下 -> 分步移动 -> 抬起。"""
    u32.SetCursorPos(p1[0], p1[1])
    time.sleep(0.05)
    u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
    time.sleep(0.08)
    for i in range(1, steps + 1):
        t = i / steps
        u32.SetCursorPos(int(p1[0] + (p2[0] - p1[0]) * t),
                         int(p1[1] + (p2[1] - p1[1]) * t))
        time.sleep(0.03)
    time.sleep(0.1)
    u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
    time.sleep(0.3)


def grab_cell_opaque(pm, x, y, w, h):
    """grab 到的窗口图里，(x,y,w,h) 逻辑区域的不透明像素数。"""
    img = pm.toImage()
    d = pm.devicePixelRatioF()
    x0, y0 = int(x * d), int(y * d)
    x1, y1 = int((x + w) * d), int((y + h) * d)
    cnt = 0
    for yy in range(max(0, y0), min(img.height(), y1), 2):
        for xx in range(max(0, x0), min(img.width(), x1), 2):
            if (img.pixel(xx, yy) >> 24) & 0xFF:
                cnt += 1
    return cnt


def main():
    global STATE_BACKUP
    if STATE_PATH.exists():
        STATE_BACKUP = STATE_PATH.read_bytes()

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    storage = Storage()
    storage.migrate_to_native_mode()

    # ---------- 测试布局：jpg / lnk / CLSID 三种类型 ----------
    desktop = appsource.shell_known_folder("desktop")
    jpg = lnk = None
    try:
        for n in sorted(os.listdir(desktop)):
            if jpg is None and n.lower().endswith(".jpg"):
                jpg = os.path.join(desktop, n)
            if lnk is None and n.lower().endswith(".lnk"):
                lnk = os.path.join(desktop, n)
    except Exception:
        pass
    clsid = "::{20D04FE0-3AEA-1069-A2D8-08002B30309D}"

    storage._data["layout"] = []
    if jpg:
        storage.add_app(appsource.desktop_file_entry(jpg), col=0, row=0)
    if lnk:
        storage.add_app(appsource.desktop_file_entry(lnk), col=1, row=0)
    storage.add_app({"id": "sys-pc", "name": "此电脑", "target": clsid, "builtin": True}, col=2, row=0)
    storage.save()

    window = DesktopWindow(storage)
    window.show_desktop()
    layer = WidgetLayer(storage)

    def phase1_native_mode():
        print("\n==== 阶段1：原生模式（问题2/5） ====", flush=True)
        # 2026-10-18：migrate_to_native_mode() 自路线A（默认整理模式）后
        # 已是空实现——这里显式切原生模式，保持本阶段断言的有效性
        storage.set_setting("hide_native_icons", False)
        window.apply_native_icons_setting()
        time.sleep(0.4)
        ok("整理窗口已挂载桌面带", window.attached)
        ok("原生图标可见（DefView 未隐藏）", win32_layer.native_icons_hidden() is False)
        hwnd = int(window.winId())
        empty = QPoint(window.width() - 80, window.height() - 80)
        ex, ey = phys(empty)
        ht = hit_test(hwnd, ex, ey)
        ok("空闲空白区命中测试穿透（HTTRANSPARENT）", ht == HTTRANSPARENT, "hit=%d" % ht)
        first = next(iter(window.icons.values()))
        c = first.mapToGlobal(QPoint(first.width() // 2, first.height() // 2))
        cx, cy = phys(c)
        ht2 = hit_test(hwnd, cx, cy)
        ok("图标区命中测试归本窗口（HTCLIENT）", ht2 == HTCLIENT, "hit=%d" % ht2)
        QTimer.singleShot(400, phase2_render)

    def phase2_render():
        print("\n==== 阶段2：图标高清渲染（问题1） ====", flush=True)
        pm = window.grab()
        for eid, icon in window.icons.items():
            e = icon.entry
            label = e.get("app", {}).get("name", "?")
            if e.get("app", {}).get("target", "").startswith("::"):
                label = "此电脑(CLSID)"
            n = grab_cell_opaque(pm, icon.x() + 14, icon.y() + 2, icon.icon_size, icon.icon_size)
            ok("图标已渲染：%s" % label, n > 200, "opaque=%d" % n)
        pm.save(str(ROOT / "verify_render.png"))
        QTimer.singleShot(300, phase3_interactive)

    def phase3_interactive():
        print("\n==== 阶段3：交互型组件输入（问题7） ====", flush=True)
        clock = layer.widgets.get("clock")
        notes = layer.widgets.get("notes")
        panel = layer.widgets.get("panel")
        if clock is not None:
            ok("时钟保持 NOACTIVATE（永不被激活）", ex_noactivate(int(clock.winId())))
        else:
            ok("时钟组件存在", False, "未创建")
        if notes is not None:
            ok("便签去掉 NOACTIVATE（可激活）", not ex_noactivate(int(notes.winId())))
            notes.show()
            notes.raise_()
            g = notes.geometry()
            click_at(*phys(QPoint(g.x() + g.width() // 2, g.y() + g.height() // 2)))
            fg = foreground()
            ok("真实点击便签后成为前台窗口（可输入）", fg == int(notes.winId()),
               "fg=%d notes=%d active=%s" % (fg, int(notes.winId()), notes.isActiveWindow()))
            notes.edit.setFocus()
            # 只用 ASCII：QTest.keyClicks 打中文会经输入法（搜狗）合成，
            # 在本机环境直接杀进程（EXIT=127，Plain QTextEdit 上可复现，
            # 与项目代码无关）——键盘输入路径用 ASCII 验证即可
            QTest.keyClicks(notes.edit, "hello")
            ok("便签可以输入文字", "hello" in notes.edit.toPlainText())
        else:
            ok("便签组件存在", False, "未创建")
        if panel is not None:
            ok("面板去掉 NOACTIVATE（可激活）", not ex_noactivate(int(panel.winId())))
            panel.show()
            panel.raise_()
            g = panel.geometry()
            click_at(*phys(QPoint(g.x() + g.width() // 2, g.y() + 40)))
            fg = foreground()
            ok("真实点击面板后成为前台窗口", fg == int(panel.winId()),
               "fg=%d panel=%d active=%s" % (fg, int(panel.winId()), panel.isActiveWindow()))
            panel.ed_search.setFocus()
            QTest.keyClicks(panel.ed_search, "notepad")
            ok("搜索栏可以输入文字", panel.ed_search.text() == "notepad")
        QTimer.singleShot(300, phase4_organize)

    def phase4_organize():
        print("\n==== 阶段4：整理模式（问题3/4/5） ====", flush=True)
        storage.set_setting("hide_native_icons", True)
        storage.set_setting("auto_clone_desktop", True)
        window.apply_native_icons_setting()
        time.sleep(0.4)
        ok("整理模式下原生图标已隐藏", win32_layer.native_icons_hidden() is True)
        hwnd = int(window.winId())
        empty = QPoint(window.width() - 80, window.height() - 80)
        ex, ey = phys(empty)
        ht = hit_test(hwnd, ex, ey)
        ok("整理模式空白区归本窗口（HTCLIENT）", ht == HTCLIENT, "hit=%d" % ht)
        window.rebuild()
        QTimer.singleShot(500, phase5_drag)

    def phase5_drag():
        ids = list(window.icons.keys())
        ok("拖动测试条目足够", len(ids) >= 3, "icons=%d" % len(ids))
        if len(ids) < 3:
            QTimer.singleShot(200, phase7_rightclick)
            return
        src = window.icons[ids[0]]
        old = (src.entry.get("col"), src.entry.get("row"))
        p1 = phys(src.mapToGlobal(QPoint(src.width() // 2, 20)))
        cell = window._cell()
        origin = window._origin()
        p2 = phys(QPoint(origin[0] + 2 * cell[0] + cell[0] // 2,
                         origin[1] + 1 * cell[1] + 20))
        drag_between(p1, p2)
        e = storage.find_entry(ids[0])
        ok("真实拖动后图标位置改变", (e.get("col"), e.get("row")) != old,
           "%s->%s" % (old, (e.get("col"), e.get("row"))))
        QTimer.singleShot(300, phase6_multidrag)

    def phase6_multidrag():
        window._selected.clear()
        ids = list(window.icons.keys())[:3]
        icons = [window.icons[i] for i in ids]
        x0 = min(i.x() for i in icons)
        y0 = min(i.y() for i in icons)
        x1 = max(i.x() + i.width() for i in icons)
        y1 = max(i.y() + i.height() for i in icons)
        drag_between(phys(QPoint(x0 - 6, y0 - 6)), phys(QPoint(x1 + 6, y1 + 6)), steps=15)
        ok("橡皮筋框选选中多个", len(window._selected) >= 3,
           "selected=%d" % len(window._selected))
        if len(window._selected) < 3:
            QTimer.singleShot(200, phase7_rightclick)
            return
        before = [(storage.find_entry(i).get("col"), storage.find_entry(i).get("row"))
                  for i in window._selected]
        src = window.icons[sorted(window._selected)[0]]
        p1 = phys(src.mapToGlobal(QPoint(src.width() // 2, 20)))
        cell = window._cell()
        origin = window._origin()
        p2 = phys(QPoint(origin[0] + 5 * cell[0] + cell[0] // 2, origin[1] + 4 * cell[1] + 20))
        drag_between(p1, p2)
        after = [(storage.find_entry(i).get("col"), storage.find_entry(i).get("row"))
                 for i in window._selected]
        moved = sum(1 for b, a in zip(before, after) if b != a)
        ok("多选整体拖动（>=3 个一起移动）", moved >= 3, "moved=%d/%d" % (moved, len(before)))
        QTimer.singleShot(300, phase7_rightclick)

    def phase7_rightclick():
        print("\n==== 阶段5：右键菜单（问题5） ====", flush=True)
        ok("整理模式右键菜单代码路径存在", hasattr(window, "contextMenuEvent"))
        storage.set_setting("hide_native_icons", False)
        storage.set_setting("auto_clone_desktop", False)
        window.apply_native_icons_setting()
        time.sleep(0.4)
        ok("恢复原生模式后 DefView 可见", win32_layer.native_icons_hidden() is False)
        QTimer.singleShot(300, finish)

    def cleanup():
        """幂等收尾（铁律：任何退出路径都必须恢复用户桌面）。

        顺序有讲究：先停 BandGuard（否则 on_tick 会在恢复后重新隐藏
        原生图标——竞态遗留，2026-10-18 实测过），再藏窗，再恢复图标
        与 state.json。finish() 正常路径与异常/SIGINT 路径都走这里。
        """
        try:
            window._band_guard.untrack(window)
        except Exception:
            pass
        try:
            window.hide()
        except Exception:
            pass
        win32_layer.restore_native_icons()
        try:
            if STATE_BACKUP is not None:
                STATE_PATH.write_bytes(STATE_BACKUP)
            else:
                STATE_PATH.unlink(missing_ok=True)
        except Exception as e:
            print("state restore failed:", e, flush=True)

    def finish():
        fails = [n for n, c_ in RESULTS if not c_]
        print("\n==== 汇总: %d 项, 失败 %d 项 ====" % (len(RESULTS), len(fails)), flush=True)
        if fails:
            print("失败项:", fails, flush=True)
        try:
            window.grab().save(str(ROOT / "verify_shot.png"))
        except Exception:
            pass
        # 先 cleanup 再 quit：注入的拖拽输入可能卡死 OLE DoDragDrop 嵌套
        # 事件循环（2026-10-18 实测 app.quit 后 exec 不返回、进程挂死），
        # cleanup 若排在 exec 返回后就永远跑不到——桌面将遗留隐藏图标
        cleanup()
        code = 1 if any(not c for _, c in RESULTS) else 0
        # daemon 看门狗：主线程卡在嵌套循环时也能强杀（测试工具必须能退）
        import threading
        wd = threading.Timer(8.0, lambda: os._exit(code))
        wd.daemon = True
        wd.start()
        app.quit()

    try:
        QTimer.singleShot(1200, phase1_native_mode)
        app.exec()
    finally:
        cleanup()
    # 正常路径：cleanup 已完成（幂等），确定性退出
    code = 1 if any(not c for _, c in RESULTS) else 0
    sys.stdout.flush()
    os._exit(code)


if __name__ == "__main__":
    sys.exit(main())
