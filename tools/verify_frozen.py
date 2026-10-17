# -*- coding: utf-8 -*-
"""验证 PyInstaller 打包产物：启动 exe -> 检查进程 / 桌面带 / 原生图标隐藏
-> 截图 -> 退出并恢复原生桌面图标。"""
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes

sys.path.insert(0, "C:/Users/43563/WorkBuddy/2026-10-16-01-23-19/desktop-organizer")

from src import win32_layer

u = ctypes.windll.user32
u.GetClassNameW.restype = ctypes.c_int
u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u.GetWindow.restype = wintypes.HWND
u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u.GetWindowThreadProcessId.restype = wintypes.DWORD
u.IsWindowVisible.restype = wintypes.BOOL
u.IsWindowVisible.argtypes = [wintypes.HWND]
u.GetWindowLongW.restype = wintypes.LONG
u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u.GetWindowRect.restype = wintypes.BOOL

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
GW_HWNDNEXT, GW_CHILD = 2, 5
# 可传 argv[1] 指定被测 exe（如验证 v2 新包）；默认测标准 dist 产物
EXE = sys.argv[1] if len(sys.argv) > 1 else \
    r"C:\Users\43563\WorkBuddy\2026-10-16-01-23-19\desktop-organizer\dist\DesktopOrganizerDemo\DesktopOrganizerDemo.exe"

RESULTS = []


def ok(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, detail), flush=True)


def cls(h):
    b = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(h, b, 256)
    return b.value


def main():
    proc = subprocess.Popen([EXE])
    print("launched pid=%d" % proc.pid, flush=True)
    time.sleep(5)
    ok("进程存活", proc.poll() is None, "exit=%s" % proc.poll())

    progman = win32_layer._progman()
    wins = win32_layer._enum_zorder()
    pid = proc.pid
    mine = []
    for h in wins:
        p = wintypes.DWORD(0)
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h):
            mine.append(h)
    print("进程窗口数: %d -> %s" % (len(mine), [cls(h) for h in mine]), flush=True)
    # 主窗口（全屏整理窗口）必然在；小组件取决于用户的显隐偏好
    ok("进程有可见顶层窗口（主窗口）", len(mine) >= 1, "%d 个" % len(mine))

    band = [h for h in mine if win32_layer.is_above(h, progman)]
    ok("窗口位于 Progman 之上（桌面带）", len(band) >= 1, "%d/%d" % (len(band), len(mine)))
    # 只校验 Qt 自家窗口类：输入法（搜狗等）会往目标进程注入窗口
    # （SoPY_* / #32770 类，pid 与本进程相同但非我们所建），会把
    # NOACTIVATE 检查污染成假失败。
    own = [h for h in band if cls(h).startswith("Qt6103")]
    # 主整理窗口（全屏）必须 NOACTIVATE——否则桌面永远抢焦点，点不了别的窗口。
    # 交互型小组件（便签/搜索框，问题7 修复）有意去掉 NOACTIVATE 以获得键盘
    # 焦点输入；纯展示型（时钟）保持 NOACTIVATE。故只强制主窗口。
    sw = u.GetSystemMetrics(0)
    sh = u.GetSystemMetrics(1)
    r2 = wintypes.RECT()
    main_win = None
    for h in own:
        u.GetWindowRect(h, ctypes.byref(r2))
        if (r2.right - r2.left) >= sw * 0.8 and (r2.bottom - r2.top) >= sh * 0.8:
            main_win = h
    main_noact = main_win is not None and bool(
        u.GetWindowLongW(main_win, GWL_EXSTYLE) & 0xFFFFFFFF & WS_EX_NOACTIVATE)
    ok("主整理窗口带 WS_EX_NOACTIVATE（不抢焦点）", main_noact,
       "hwnd=%s %dx%d屏幕" % (main_win, sw, sh))
    r = wintypes.RECT()
    for h in band:
        u.GetWindowRect(h, ctypes.byref(r))
        print("  hwnd=%d cls=%s rect=(%d,%d,%d,%d) noact=%s"
              % (h, cls(h), r.left, r.top, r.right, r.bottom,
                 bool(u.GetWindowLongW(h, GWL_EXSTYLE) & 0xFFFFFFFF & WS_EX_NOACTIVATE)), flush=True)

    # 运行期间原生桌面图标应被隐藏（克隆模式）
    dv = win32_layer._find_defview()
    ok("运行期间原生桌面图标已隐藏", bool(dv) and not u.IsWindowVisible(dv))

    try:
        from pathlib import Path
        from PIL import ImageGrab
        shot = Path(__file__).resolve().parent.parent / "frozen_shot.png"
        ImageGrab.grab().save(str(shot))
        print("[PASS] 截图 -> %s" % shot, flush=True)
    except Exception as e:
        print("[FAIL] 截图失败:", e, flush=True)

    proc.terminate()
    time.sleep(1)
    if proc.poll() is None:
        proc.kill()
    # 进程被强制结束时应用自身来不及恢复，这里兜底恢复原生桌面图标
    win32_layer.restore_native_icons()
    dv = win32_layer._find_defview()
    ok("退出后原生桌面图标已恢复", not dv or u.IsWindowVisible(dv))

    fails = [n for n, c_ in RESULTS if not c_]
    print("\n==== 汇总: %d 项, 失败 %d 项 ====" % (len(RESULTS), len(fails)), flush=True)
    return 0 if not fails else 1


sys.exit(main())
