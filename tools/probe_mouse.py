# -*- coding: utf-8 -*-
"""合成鼠标输入能力探针（诊断用，不改任何业务状态）。

用法: python tools/probe_mouse.py [A] [B] [C]   （缺省全跑）

  A 光标控制     SetCursorPos / 相对位移 是否真的移动光标
  B 普通窗口     注入的 press / move / release 能否被 QWidget 收到
  C OLE 拖放     QDrag.exec() 嵌套循环下能否被注入移动到目标并 drop

关键教训（2026-10-19 实测）：注入期间**必须泵事件循环**。
GUI 线程被 time.sleep 阻塞时，Windows 会把堆积的 WM_MOUSEMOVE 合并成
最后一条，拖动看起来"只走了一两步"甚至"被取消"——这不是注入失败。

安全约定：只在自己创建的窗口内点击（注入前确认前台是自己）；
结束恢复原光标位置；daemon 看门狗强制退出。
"""
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

from PySide6.QtCore import QMimeData, QPoint, Qt, QTimer
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtTest import QTest

u32 = ctypes.windll.user32
u32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
u32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u32.SetCursorPos.restype = wintypes.BOOL
u32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                            wintypes.DWORD, ctypes.c_void_p]
u32.GetForegroundWindow.restype = wintypes.HWND

MOVE, DOWN, UP = 0x1, 0x2, 0x4
RESULTS = []
ORIG = (0, 0)


def ok(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print("%s %s%s" % ("[PASS]" if cond else "[FAIL]", name,
                       ("  -> " + detail) if detail else ""), flush=True)


def cursor_pos():
    p = wintypes.POINT()
    u32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def fg():
    return int(u32.GetForegroundWindow())


def pump(ms):
    """泵事件循环（关键：不泵则 WM_MOUSEMOVE 被系统合并）。"""
    QTest.qWait(int(ms))


def press():
    u32.mouse_event(DOWN, 0, 0, 0, None)
    pump(20)


def release():
    u32.mouse_event(UP, 0, 0, 0, None)
    pump(60)


def move_to(x, y, settle=40):
    u32.SetCursorPos(int(x), int(y))
    pump(settle)


def move_rel(dx, dy, settle=25):
    u32.mouse_event(MOVE, int(dx), int(dy), 0, None)
    pump(settle)


def click(x, y):
    move_to(x, y)
    press()
    release()
    pump(80)


def drag(x1, y1, x2, y2, steps=16, step_ms=25):
    """按住拖动：相对位移逐步走 + 每步泵事件。"""
    move_to(x1, y1, 60)
    press()
    pump(80)
    cur = cursor_pos()
    for i in range(1, steps + 1):
        tx = int(round(x1 + (x2 - x1) * i / float(steps)))
        ty = int(round(y1 + (y2 - y1) * i / float(steps)))
        dx, dy = tx - cur[0], ty - cur[1]
        if dx or dy:
            move_rel(dx, dy, step_ms)
            cur = cursor_pos()
    pump(80)
    release()
    pump(250)


# ---------------- 测试窗口 ----------------
class Sink(QWidget):
    def __init__(self, name):
        super().__init__()
        self.name = name
        self.setWindowTitle("probe-%s" % name)
        self.counts = {"press": 0, "move": 0, "release": 0, "drop": 0,
                       "enter": 0}
        self.setMouseTracking(True)
        self.setAcceptDrops(True)

    def mousePressEvent(self, e):
        self.counts["press"] += 1
        e.accept()

    def mouseMoveEvent(self, e):
        self.counts["move"] += 1
        e.accept()

    def mouseReleaseEvent(self, e):
        self.counts["release"] += 1
        print("    <%s> release @%s" % (self.name, e.position().toPoint()), flush=True)
        e.accept()

    def dragEnterEvent(self, e):
        self.counts["enter"] += 1
        print("    <%s> dragEnter" % self.name, flush=True)
        e.acceptProposedAction()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dropEvent(self, e):
        self.counts["drop"] += 1
        print("    <%s> DROP %r" % (self.name, e.mimeData().text()), flush=True)
        e.acceptProposedAction()


class DragSource(Sink):
    """按下后移动超阈值就 QDrag.exec()（走 OLE DoDragDrop）。"""

    def __init__(self, name, payload):
        super().__init__(name)
        self.payload = payload
        self.exec_started = 0
        self.exec_result = "未执行"
        self._armed = False

    def mousePressEvent(self, e):
        self.counts["press"] += 1
        if e.button() == Qt.LeftButton:
            self._armed = True
            self._p0 = e.position().toPoint()
        e.accept()

    def mouseMoveEvent(self, e):
        self.counts["move"] += 1
        if not self._armed:
            return
        if (e.position().toPoint() - self._p0).manhattanLength() < 10:
            return
        self._armed = False
        self.exec_started += 1
        mime = QMimeData()
        mime.setText(self.payload)
        d = QDrag(self)
        d.setMimeData(mime)
        t0 = time.time()
        print("    <src> QDrag.exec() 进入" % (), flush=True)
        self.exec_result = d.exec(Qt.CopyAction)
        print("    <src> QDrag.exec() 返回 %s（%.2fs）"
              % (self.exec_result, time.time() - t0), flush=True)

    def mouseReleaseEvent(self, e):
        self.counts["release"] += 1
        self._armed = False
        e.accept()


def stage_a(app):
    print("\n==== A 光标控制 ====", flush=True)
    move_to(300, 300, 120)
    ok("A1 SetCursorPos 生效", cursor_pos() == (300, 300), "got=%s" % (cursor_pos(),))
    before = cursor_pos()
    move_rel(60, 40, 120)
    after = cursor_pos()
    ok("A2 相对位移生效（光标真的动了）",
       after != before, "%s -> %s" % (before, after))


def stage_b(app):
    print("\n==== B 普通窗口收鼠标事件 ====", flush=True)
    w = Sink("sink")
    w.setGeometry(200, 180, 460, 320)
    w.show()
    w.raise_()
    w.activateWindow()
    pump(400)
    own = fg() == int(w.winId())
    ok("B0 测试窗口取得前台", own, "fg=%d self=%d" % (fg(), int(w.winId())))
    if not own:
        ok("B1 收按下", False, "前台不符，放弃注入")
        ok("B2 拖动收连续移动", False, "前台不符，放弃注入")
        ok("B3 收抬起", False, "前台不符，放弃注入")
        return None

    cx, cy = w.mapToGlobal(QPoint(w.width() // 2, w.height() // 2)).toTuple()
    click(cx, cy)
    ok("B1 收按下", w.counts["press"] >= 1, "press=%d" % w.counts["press"])
    ok("B3 收抬起", w.counts["release"] >= 1, "release=%d" % w.counts["release"])

    w.counts["move"] = 0
    drag(cx - 60, cy - 40, cx + 60, cy + 40, steps=16, step_ms=25)
    ok("B2 拖动收连续移动事件（>=8）", w.counts["move"] >= 8,
       "move=%d" % w.counts["move"])
    end = cursor_pos()
    ok("B2b 拖动后光标到达目标附近",
       abs(end[0] - (cx + 60)) <= 6 and abs(end[1] - (cy + 40)) <= 6,
       "end=%s want=(%d,%d)" % (end, cx + 60, cy + 40))
    w.close()
    return w


def stage_c(app):
    print("\n==== C OLE 拖放端到端（QDrag.exec） ====", flush=True)
    src = DragSource("src", "hello-drag")
    src.setGeometry(220, 200, 200, 200)
    dst = Sink("dst")
    dst.setGeometry(500, 200, 300, 260)
    dst.show()          # 后 show 的会抢前台，所以先 dst
    src.show()
    pump(250)
    src.raise_()
    src.activateWindow()
    pump(400)
    if fg() != int(src.winId()):
        print("!! 源窗口未取得前台（fg=%d src=%d），放弃" % (fg(), int(src.winId())),
              flush=True)
        ok("C1 QDrag.exec 被触发", False, "前台不符")
        ok("C2 目标收到 drop", False, "前台不符")
        return

    sx, sy = src.mapToGlobal(QPoint(60, 100)).toTuple()
    dx, dy = dst.mapToGlobal(QPoint(150, 130)).toTuple()
    print("  拖放路径 (%d,%d) -> (%d,%d)" % (sx, sy, dx, dy), flush=True)

    # 注入必须跑在**后台线程**：QDrag.exec() 的嵌套循环由泵消息触发。
    # 若注入器自己在 GUI 线程里泵消息，它会被嵌套循环吞住，永远走不到
    # release —— 拖放表现为"进入了但永不结束"。后台线程用纯 sleep 注入，
    # 主线程 exec 循环自己泵消息，两者互不阻塞。
    def injector():
        time.sleep(0.35)
        u32.SetCursorPos(sx, sy)
        time.sleep(0.15)
        u32.mouse_event(DOWN, 0, 0, 0, None)
        time.sleep(0.15)
        cur = cursor_pos()
        for i in range(1, 25):
            tx = int(round(sx + (dx - sx) * i / 24.0))
            ty = int(round(sy + (dy - sy) * i / 24.0))
            mx, my = tx - cur[0], ty - cur[1]
            if mx or my:
                u32.mouse_event(MOVE, mx, my, 0, None)
                cur = cursor_pos()
            time.sleep(0.04)
        time.sleep(0.35)
        print("    <injector> release @%s" % (cursor_pos(),), flush=True)
        u32.mouse_event(UP, 0, 0, 0, None)

    th = threading.Thread(target=injector, daemon=True)
    th.start()
    for _ in range(100):                 # 最多等 10s
        pump(100)
        if src.exec_result != "未执行" and not th.is_alive():
            break
    pump(400)
    ok("C1 QDrag.exec 被触发（按下并移动后进入嵌套循环）",
       src.exec_started >= 1, "started=%d" % src.exec_started)
    ok("C2 QDrag.exec 正常返回（未卡死）", src.exec_result != "未执行",
       "result=%r" % (src.exec_result,))
    ok("C3 目标窗口收到 drop", dst.counts["drop"] >= 1,
       "drop=%d enter=%d" % (dst.counts["drop"], dst.counts["enter"]))
    src.close()
    dst.close()


def main(argv):
    global ORIG
    stages = [s.upper() for s in argv[1:] if s.upper() in ("A", "B", "C")] or ["A", "B", "C"]
    ORIG = cursor_pos()
    print("原光标:", ORIG, " 屏幕:", u32.GetSystemMetrics(0), u32.GetSystemMetrics(1),
          flush=True)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    for s in stages:
        try:
            {"A": stage_a, "B": stage_b, "C": stage_c}[s](app)
        except Exception:
            import traceback
            traceback.print_exc()
            ok("阶段 %s 未抛异常" % s, False)
    for w in app.topLevelWidgets():
        try:
            w.close()
        except Exception:
            pass
    pump(120)
    u32.SetCursorPos(ORIG[0], ORIG[1])
    fails = [n for n, c in RESULTS if not c]
    print("\n==== 汇总: %d 项，失败 %d 项 ====" % (len(RESULTS), len(fails)), flush=True)
    if fails:
        print("失败项:", fails, flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    wd = threading.Timer(60.0, lambda: os._exit(3))
    wd.daemon = True
    wd.start()
    try:
        code = main(sys.argv)
    except Exception:
        import traceback
        traceback.print_exc()
        code = 4
    sys.stdout.flush()
    os._exit(code)
