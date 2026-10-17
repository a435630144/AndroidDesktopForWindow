# -*- coding: utf-8 -*-
"""探针十三：无头逻辑验证（不需要屏幕净空，不动用户任何窗口）。

覆盖：
  B1. 橡皮筋：合成 Qt 鼠标事件（press->move->release）验证框选选中
  B2. 多选拖动 payload：_drag_payload_for 多选返回逗号分隔 id
  B3. 多选 drop：_drop_internal 逗号 payload 整体平移 + 主图标交换
  B4. 文件夹成员 payload：M: 标记 + rpartition 解析（含冒号 id 消歧）
  B5. 命中填充：paintEvent 铺 alpha=2 后 WindowFromPoint 归我方（复核 probe11）

安全约束：全程不移动/最小化/关闭任何用户窗口；只用临时状态文件。
"""
import ctypes
import os
import sys
import time
import traceback
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRect, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from src import appsource, win32_layer  # noqa: E402
from src.desktop_window import DesktopWindow  # noqa: E402
from src.storage import Storage  # noqa: E402

STATE = Path(os.environ.get("TEMP", ".")) / "desktoporg_probe_state13.json"

u32 = ctypes.windll.user32
u32.WindowFromPoint.argtypes = [wintypes.POINT]
u32.WindowFromPoint.restype = wintypes.HWND


def wfp(x, y):
    return int(u32.WindowFromPoint(wintypes.POINT(x, y)) or 0)


def p(msg):
    print("    %s" % msg, flush=True)


def send_move(widget, lpos):
    """合成带左键的鼠标移动。

    PySide6 6.10 的 QTest.mouseMove 不支持 buttons 参数（发的移动永远
    NoButton，mouseMoveEvent 会直接早退），故直接构造 QMouseEvent。
    """
    ev = QMouseEvent(QMouseEvent.MouseMove, lpos, widget.mapToGlobal(lpos),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(widget, ev)


def other_visible_rects(mh):
    """枚举其他可见顶层窗口矩形（只读：不移动/最小化/关闭任何窗口）。

    跳过：本窗口、不可见、已最小化、被 UWP  cloaked 的窗口。
    """
    rects = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _l):
        if h == mh or not u32.IsWindowVisible(h) or u32.IsIconic(h):
            return True
        cloaked = ctypes.c_int(0)
        try:
            ctypes.windll.dwmapi.DwmGetWindowAttribute(
                h, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
            if cloaked.value:
                return True
        except Exception:
            pass
        r = wintypes.RECT()
        if u32.GetWindowRect(h, ctypes.byref(r)):
            w, hh = r.right - r.left, r.bottom - r.top
            if w > 0 and hh > 0:
                rects.append((r.left, r.top, r.right, r.bottom))
        return True

    u32.EnumWindows(cb, 0)
    return rects


def add_folder(storage, fid, members, col, row):
    """按真实数据模型直接构造文件夹条目。

    注意：不能用 storage.add_app()——它硬编码 type="app"/apps=[]，
    文件夹在真实应用里只由 _on_merge 合并产生。
    """
    entry = {"id": fid, "type": "folder", "app": None,
             "apps": list(members), "col": col, "row": row}
    storage._data["layout"].append(entry)
    return entry


def main():
    if STATE.exists():
        STATE.unlink()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    storage = Storage(path=str(STATE))
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
    storage._data["layout"] = []
    if jpg:
        storage.add_app(appsource.desktop_file_entry(jpg), col=0, row=0)
    if lnk:
        storage.add_app(appsource.desktop_file_entry(lnk), col=1, row=0)
    storage.add_app({"id": "sys-pc", "name": "此电脑",
                     "target": "::{20D04FE0-3AEA-1069-A2D8-08002B30309D}",
                     "builtin": True}, col=2, row=0)
    storage.save()

    window = DesktopWindow(storage)
    window.show_desktop()

    finished = {"done": False}

    def finish():
        if finished["done"]:
            return
        finished["done"] = True
        try:
            if STATE.exists():
                STATE.unlink()
        except Exception:
            pass
        try:
            win32_layer.restore_native_icons()
        except Exception:
            pass
        app.quit()

    def run():
        try:
            time.sleep(0.3)
            storage.set_setting("hide_native_icons", True)
            storage.set_setting("auto_clone_desktop", True)
            window.apply_native_icons_setting()
            time.sleep(0.5)
            window.rebuild()
            time.sleep(0.3)
            mh = int(window.winId())
            d = window.devicePixelRatio()
            cw, ch = window._cell()
            org = window._origin()

            # ---------- B1: 橡皮筋（合成 Qt 事件，绕过系统命中测试） ----------
            print("\n==== B1 橡皮筋框选（合成 Qt 鼠标事件） ====", flush=True)
            window._selected.clear()
            # 图标实际位置（布局刚重建：col 0-2, row 0）
            bb = None
            for ic in window.icons.values():
                r = QRect(ic.pos(), ic.size())
                bb = r if bb is None else bb.united(r)
            # 框选矩形：包围盒外扩 10px（控件坐标）；按下点落在图标外侧的窗口背景上
            band = QRect(bb.left() - 10, bb.top() - 10,
                         bb.width() + 20, bb.height() + 20)
            QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier,
                             QPoint(band.left() + 2, band.top() + 2))
            send_move(window, QPoint(band.left() + 5, band.top() + 5))
            send_move(window, QPoint(band.right() - 2, band.bottom() - 2))
            QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier,
                               QPoint(band.right() - 2, band.bottom() - 2))
            n_sel = len(window._selected)
            p("框选后 selected=%d/%d %s" % (n_sel, len(window.icons),
                                            "OK" if n_sel == len(window.icons) else "FAIL"))

            # ---------- B2: 多选拖动 payload ----------
            print("\n==== B2 多选拖动 payload ====", flush=True)
            ids = list(window.icons.keys())
            payload = window._drag_payload_for(ids[0])
            expect = ",".join(sorted(window._selected))
            p("payload=%r" % payload)
            p("期望    =%r %s" % (expect, "OK" if payload == expect else "FAIL"))
            p("_drag_active=%s（应为 True）%s" % (window._drag_active,
                                                 "OK" if window._drag_active else "FAIL"))

            # ---------- B3: 多选 drop 整体平移 ----------
            print("\n==== B3 多选 drop 整体平移 ====", flush=True)
            sel = list(window._selected)
            before = {i: (storage.find_entry(i).get("col"), storage.find_entry(i).get("row"))
                      for i in sel}
            # 主图标 = payload 第一个（_drop_internal 的 entries[0]）
            primary_id = payload.split(",")[0]
            pc, pr = before[primary_id]
            tcol, trow = pc + 3, pr + 1
            # 目标点取格子内部（_cell_at 用 round()，贴边界会四舍五入到邻格）
            target = QPoint(org[0] + tcol * cw + cw // 4,
                            org[1] + trow * ch + ch // 4)
            window._drop_internal(payload, target)
            after = {i: (storage.find_entry(i).get("col"), storage.find_entry(i).get("row"))
                     for i in sel}
            dcol, drow = tcol - pc, trow - pr
            p("主图标 %s: %s -> %s（应到 (%d,%d)）%s"
              % (primary_id, before[primary_id], after[primary_id], tcol, trow,
                 "OK" if after[primary_id] == (tcol, trow) else "FAIL"))
            ok_all = all(after[i] == (before[i][0] + dcol, before[i][1] + drow)
                         for i in sel)
            p("整体平移 %d/%d（应全部 +(%d,%d)）%s"
              % (sum(1 for i in sel if after[i] != before[i]), len(sel), dcol, drow,
                 "OK" if ok_all else "FAIL"))
            window._on_drag_finished()
            p("drop 后 _drag_active=%s（应 False）%s" % (window._drag_active,
                                                        "OK" if not window._drag_active else "FAIL"))

            # ---------- B4: 文件夹成员 payload 解析 ----------
            print("\n==== B4 文件夹成员 payload（M: 标记 + 含冒号 id） ====", flush=True)
            fid = "df:deadbeefcafe"
            add_folder(storage, fid, [
                {"id": "m1", "name": "成员1", "target": "x", "kind": "file"},
                {"id": "m2", "name": "成员2", "target": "y", "kind": "file"},
            ], col=0, row=5)
            storage.save()
            n_before = len(storage.layout)
            window._on_extract("M:%s:1" % fid)
            folder = storage.find_entry(fid)
            n_after = len(storage.layout)
            p("extract %r -> 文件夹剩余成员=%d（应 1），布局 %d->%d（应 +1）%s"
              % ("M:%s:1" % fid, len(folder.get("apps", [])) if folder else -1,
                 n_before, n_after,
                 "OK" if folder and folder.get("type") == "folder"
                 and len(folder.get("apps", [])) == 1
                 and n_after == n_before + 1 else "FAIL"))

            storage.add_app({"id": "sys-calc", "name": "计算器", "target": "calc"},
                            col=1, row=5)
            storage.save()
            fid2 = "df:cafe0123beef"
            add_folder(storage, fid2, [
                {"id": "n1", "name": "成员N1", "target": "n1", "kind": "file"},
                {"id": "n2", "name": "成员N2", "target": "n2", "kind": "file"},
            ], col=2, row=5)
            storage.save()
            window._on_merge("M:%s:0" % fid2, "sys-calc")
            calc = storage.find_entry("sys-calc")
            is_folder = calc is not None and calc.get("type") == "folder" \
                and len(calc.get("apps", [])) == 2
            p("merge %r 到「计算器」-> 合并为文件夹，成员数=%d（应 2）%s"
              % ("M:%s:0" % fid2, len(calc.get("apps", [])) if calc else -1,
                 "OK" if is_folder else "FAIL"))

            n_before2 = len(storage.layout)
            window._on_remove_member("M:%s:0" % fid)
            folder2 = storage.find_entry(fid)
            n_after2 = len(storage.layout)
            p("remove_member %r -> 文件夹存在=%s（应 False，空文件夹自动清除），布局 %d->%d（应 -1）%s"
              % ("M:%s:0" % fid, folder2 is not None, n_before2, n_after2,
                 "OK" if folder2 is None and n_after2 == n_before2 - 1 else "FAIL"))

            # ---------- B5: 命中填充复核 ----------
            print("\n==== B5 命中填充（surface alpha + WindowFromPoint） ====", flush=True)
            # (a) 直接抓取窗口表面：paintEvent 铺的 alpha=2 填充必须存在
            #     （全透明像素会被 Windows 逐像素 alpha 命中测试跳过）
            pm = window.grab(window.rect())
            img = pm.toImage()
            iw, ih = img.size().width(), img.size().height()
            fill_hits = []
            for fx, fy in ((0.5, 0.85), (0.3, 0.9), (0.7, 0.9),
                           (0.5, 0.75), (0.2, 0.8), (0.85, 0.95)):
                x, y = min(iw - 1, int(iw * fx)), min(ih - 1, int(ih * fy))
                c = img.pixelColor(x, y)
                ok = 1 <= c.alpha() <= 8 and c.red() < 16 \
                    and c.green() < 16 and c.blue() < 16
                fill_hits.append(ok)
                p("表面采样 (%d,%d) -> rgba=(%d,%d,%d,%d) %s"
                  % (x, y, c.red(), c.green(), c.blue(), c.alpha(),
                     "命中填充" if ok else "非填充"))
            p("alpha=2 命中填充存在: %s" % ("OK" if any(fill_hits) else "FAIL"))

            # (b) 未被其他窗口占据的窗口内点：WindowFromPoint 应归我方
            #     （端到端复核；用户窗口可能占据部分点，取未占据的采样）
            rects = other_visible_rects(mh)
            wx, wy = window.x(), window.y()
            ww, wh = window.width(), window.height()
            step = 240
            cands = []
            py = wy + 60
            while py < wy + wh and len(cands) < 6:
                px = wx + 60
                while px < wx + ww and len(cands) < 6:
                    gx, gy = int(px * d), int(py * d)
                    if not any(rx0 <= gx < rx1 and ry0 <= gy < ry1
                               for rx0, ry0, rx1, ry1 in rects):
                        cands.append((gx, gy))
                    px += step
                py += step
            if not cands:
                p("窗口内所有采样点均被其他可见窗口占据，跳过 WindowFromPoint 复核"
                  "（屏幕环境所致，非 app 问题）")
            else:
                hits = 0
                for gx, gy in cands:
                    h = wfp(gx, gy)
                    ok = h == mh
                    hits += 1 if ok else 0
                    p("空白点物理(%d,%d) WindowFromPoint=%s %s"
                      % (gx, gy, "我方" if ok else "hwnd=%d" % h,
                         "OK" if ok else "(被他窗占据?)"))
                p("命中我方 %d/%d %s" % (hits, len(cands),
                                         "OK" if hits >= 1 else "FAIL"))
            # ---------- B6: 拖拽源在 exec 期间被删除（Fix A 回归） ----------
            print("\n==== B6 拖拽源删除后 dragFinished.emit 不崩溃 ====", flush=True)
            from PySide6.QtCore import QCoreApplication  # noqa: E402
            from PySide6.QtGui import QDrag  # noqa: E402
            icon = next(iter(window.icons.values()))
            icon._press_pos = QPoint(3, 3)
            orig_exec = QDrag.exec

            def fake_exec(drag_self, *a, **k):
                # 模拟真实场景：drop -> _drop_internal -> rebuild() 把拖拽源
                # deleteLater；嵌套循环内立即执行 deferred delete
                drag_self.setParent(None)
                window.rebuild()
                QCoreApplication.sendPostedEvents(None, 0)
                return Qt.IgnoreAction

            QDrag.exec = fake_exec
            crashed = None
            try:
                icon._exec_drag()
            except RuntimeError as e:
                crashed = e
            finally:
                QDrag.exec = orig_exec
            p("emit on deleted source: %s" % ("OK 未崩溃" if crashed is None
                                              else "FAIL %s" % crashed))
            window.rebuild()
        except Exception:
            print("!! run() 异常：", flush=True)
            traceback.print_exc()
        finally:
            QTimer.singleShot(300, finish)

    # 看门狗：任何情况下 25 秒内强制退出，避免进程悬挂被 SIGTERM
    QTimer.singleShot(25000, finish)
    QTimer.singleShot(1500, run)
    app.exec()
    print("==== 探针退出 ====", flush=True)


if __name__ == "__main__":
    main()
