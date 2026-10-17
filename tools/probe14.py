# -*- coding: utf-8 -*-
"""探针十四：液态玻璃弹窗 + 图标动效 可视化与逻辑验证。

安全约束：不移动/最小化/关闭任何用户窗口；只用临时状态文件。
覆盖：
  G1 背板抓取非空且尺寸正确（grabWindow 逻辑坐标语义）
  G2 打开动画进行中 zoom < 1（动画确实在跑）
  G3 打开完成 zoom == 1、几何落在锚点附近
  G4 图标按压 press_scale -> ~0.96（HIG scale(0.97) 档）
  G5 松开回弹 press_scale -> 1.0
  G6 关闭动画完成后窗口不可见
  G7 blur_pixmap 尺寸守恒 + 确实模糊（方差下降）
  G8 截图存证（液态玻璃 / 图标）供人工目检
"""
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from src import appsource, effects, win32_layer  # noqa: E402
from src.desktop_window import DesktopWindow  # noqa: E402
from src.storage import Storage  # noqa: E402

STATE = Path(os.environ.get("TEMP", ".")) / "desktoporg_probe_state14.json"
SHOT_GLASS = Path(os.environ.get("TEMP", ".")) / "probe14_glass.png"
SHOT_ICONS = Path(os.environ.get("TEMP", ".")) / "probe14_icons.png"


def p(msg):
    print("    %s" % msg, flush=True)


def main():
    if STATE.exists():
        STATE.unlink()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    storage = Storage(path=str(STATE))
    desktop = appsource.shell_known_folder("desktop")
    files = []
    try:
        for n in sorted(os.listdir(desktop)):
            if n.lower().endswith((".jpg", ".lnk", ".txt")):
                files.append(os.path.join(desktop, n))
            if len(files) >= 5:
                break
    except Exception:
        pass
    storage._data["layout"] = []
    for i, f in enumerate(files[:4]):
        storage.add_app(appsource.desktop_file_entry(f), col=i, row=0)
    storage.add_app({"id": "sys-pc", "name": "此电脑",
                     "target": "::{20D04FE0-3AEA-1069-A2D8-08002B30309D}",
                     "builtin": True}, col=4, row=0)
    # 测试文件夹：5 个成员（触发 3 列布局）
    fid = "df:14e5aab00123"
    storage._data["layout"].append({
        "id": fid, "type": "folder", "app": None,
        "apps": [
            {"id": "g%d" % i, "name": "玻璃成员%d" % i,
             "target": "g%d" % i, "kind": "file"} for i in range(5)
        ], "col": 0, "row": 3})
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
            QTest.qWait(400)
            storage.set_setting("hide_native_icons", True)
            storage.set_setting("auto_clone_desktop", True)
            window.apply_native_icons_setting()
            QTest.qWait(600)
            window.rebuild(stagger=True)
            QTest.qWait(800)
            mh = int(window.winId())

            # ---------- 打开文件夹弹窗 ----------
            print("\n==== 液态玻璃弹窗 ====", flush=True)
            window.open_folder(fid)
            popup = window._popup
            p("弹窗创建: %s" % ("OK" if popup is not None else "FAIL"))
            # G1 背板（grabWindow 逻辑坐标进、物理像素出，pm 带 DPR）
            bd = popup._backdrop
            dpr = popup.devicePixelRatio()
            exp_w = round(popup.width() * dpr)
            exp_h = round(popup.height() * dpr)
            p("G1 背板: %s 尺寸=%dx%d dpr=%.2f（期望 %dx%d 物理 = %dx%d 逻辑）%s"
              % ("非空" if not bd.isNull() else "空",
                 bd.width(), bd.height(), dpr,
                 exp_w, exp_h, popup.width(), popup.height(),
                 "OK" if not bd.isNull() and bd.width() == exp_w
                 and bd.height() == exp_h else "FAIL"))
            # G2 动画进行中（qWait 驱动事件循环；120ms 时 zoom 应在途中）
            QTest.qWait(120)
            z_mid = popup._zoom
            p("G2 打开中 zoom=%.3f（应 <1 且 >0.62）%s"
              % (z_mid, "OK" if 0.62 < z_mid < 1.0 else "FAIL"))
            # G3 完成
            QTest.qWait(800)
            p("G3 完成 zoom=%.3f（应 ==1.0）%s"
              % (popup._zoom, "OK" if abs(popup._zoom - 1.0) < 0.001 else "FAIL"))
            icon = window.icons.get(fid)
            anchor_c = icon.mapToGlobal(QPoint(icon.width() // 2, 0)) if icon else None
            pc = popup.geometry().center()
            p("弹窗中心=%s 锚点=%s %s"
              % ((pc.x(), pc.y()), (anchor_c.x(), anchor_c.y()) if anchor_c else None,
                 "OK" if anchor_c and abs(pc.x() - anchor_c.x()) < 200
                 and abs(pc.y() - anchor_c.y()) < 400 else "FAIL"))

            # ---------- G4/G5 按压回弹 ----------
            print("\n==== 图标按压动效 ====", flush=True)
            target = next((i for i in window.icons.values()
                           if not i.is_folder), None)
            if target is not None:
                c = QPoint(target.width() // 2, target.icon_size // 2)
                QTest.mousePress(target, Qt.LeftButton, Qt.NoModifier, c)
                QTest.qWait(150)
                z_press = target._press_scale
                p("G4 按压 press_scale=%.3f（应 ~0.96）%s"
                  % (z_press, "OK" if 0.90 <= z_press <= 0.99 else "FAIL"))
                QTest.mouseRelease(target, Qt.LeftButton, Qt.NoModifier, c)
                QTest.qWait(450)
                z_rel = target._press_scale
                p("G5 松开 press_scale=%.3f（应 ==1.0）%s"
                  % (z_rel, "OK" if abs(z_rel - 1.0) < 0.01 else "FAIL"))
            else:
                p("G4/G5 跳过：无普通图标")

            # ---------- G6 关闭动画 ----------
            print("\n==== 关闭动画 ====", flush=True)
            popup.close()
            QTest.qWait(600)
            p("G6 关闭后可见=%s（应 False）%s"
              % (popup.isVisible(), "OK" if not popup.isVisible() else "FAIL"))

            # ---------- G7 模糊单元验证 ----------
            print("\n==== blur_pixmap 单元验证 ====", flush=True)
            screen = QGuiApplication.primaryScreen()
            raw = screen.grabWindow(0, 200, 200, 300, 400)
            blurred = effects.blur_pixmap(raw, 8.0, 6)
            same_size = blurred.width() == raw.width() and blurred.height() == raw.height()
            i0, i1 = raw.toImage(), blurred.toImage()
            diff = 0
            n = 0
            for yy in range(0, i0.height(), 7):
                for xx in range(0, i0.width(), 7):
                    a, b = i0.pixel(xx, yy), i1.pixel(xx, yy)
                    diff += abs(((a >> 16) & 255) - ((b >> 16) & 255))
                    diff += abs(((a >> 8) & 255) - ((b >> 8) & 255))
                    diff += abs((a & 255) - (b & 255))
                    n += 3
            mean_diff = diff / max(1, n)
            p("G7 尺寸守恒=%s 平均通道差=%.1f（应 >2，证明模糊生效）%s"
              % (same_size, mean_diff,
                 "OK" if same_size and mean_diff > 2 else "FAIL"))

            # ---------- G8 截图存证 ----------
            print("\n==== 截图存证 ====", flush=True)
            # 重开弹窗拍玻璃（关闭动画已结束，弹窗已销毁——重新打开）
            window.open_folder(fid)
            popup2 = window._popup
            QTest.qWait(900)
            g = popup2.geometry()
            shot = screen.grabWindow(0, g.x(), g.y(), g.width(), g.height())
            ok = shot.save(str(SHOT_GLASS))
            p("玻璃截图: %s (%dx%d) %s"
              % (SHOT_GLASS.name, shot.width(), shot.height(),
                 "OK" if ok else "FAIL"))
            icons_pm = window.grab(window.rect())
            ok2 = icons_pm.save(str(SHOT_ICONS))
            p("图标截图: %s (%dx%d) %s"
              % (SHOT_ICONS.name, icons_pm.width(), icons_pm.height(),
                 "OK" if ok2 else "FAIL"))
            popup2.close()
            QTest.qWait(500)
        except Exception:
            print("!! run() 异常：", flush=True)
            traceback.print_exc()
        finally:
            QTimer.singleShot(400, finish)

    QTimer.singleShot(25000, finish)  # 看门狗
    QTimer.singleShot(1500, run)
    app.exec()
    print("==== 探针退出 ====", flush=True)


if __name__ == "__main__":
    main()
