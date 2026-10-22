# -*- coding: utf-8 -*-
"""单实例守护：基于 QSharedMemory，防止软件重复启动。

v10 D1（反馈 4，乙档）：主键随产品名改为 `PhoneDesktop_SingleInstance`。
**旧键只读兼容**——旧版 exe 还开着时，新版不许再起第二个整理窗口（两个进程
同时接管桌面层会互相抢窗口，比"多重启一个"危险得多）。反过来不需要兼容：
旧版不认识新键，但旧版已被覆盖安装替换，不会与新 exe 并存。

Windows 语义（实测，别照抄 Unix 的写法）：段随**最后一个句柄关闭**而销毁，
进程崩溃时句柄由内核回收，所以不需要 Unix 那套"attach 试探 + 重试 create"
来对付残留段。反过来的坑才是真坑：`create` 失败后 Qt 仍握着这个段的句柄，
**对象活多久段就活多久**——第二个实例若把失败的对象留着，会把正在跑的实例的段
续命到本进程结束，于是"前一个退出后再也启动不了"（tests/P7 锁住这条）。
"""
from PySide6.QtCore import QSharedMemory


class SingleInstance:
    def __init__(self, key: str, legacy_keys=()):
        self._mem = QSharedMemory(key)
        self._running = False
        if not self._mem.create(1):
            self._release()          # 已有实例：放手，别续命别人的段
            self._running = True
            return
        for legacy in legacy_keys:
            if not self._free(legacy):
                self._release()      # 旧实例还开着：让出主键，让旧实例当老大
                self._running = True
                return

    def is_running(self) -> bool:
        return self._running

    # ---------- 内部 ----------
    def _release(self):
        """交出主键：先 detach，再丢掉对象（PySide 引用一断，C++ 句柄就关）。"""
        mem, self._mem = self._mem, None
        if mem is None:
            return
        try:
            mem.detach()
        except Exception:
            pass

    @staticmethod
    def _free(key: str) -> bool:
        """这个键是否空闲。True 时我们抢到后立刻放掉（只当探针用）。"""
        mem = QSharedMemory(key)
        try:
            return bool(mem.create(1))
        finally:
            try:
                mem.detach()
            except Exception:
                pass
            del mem                  # 关键：让句柄立刻关闭，否则探针自己会占住键
