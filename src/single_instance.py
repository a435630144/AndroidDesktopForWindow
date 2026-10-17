# -*- coding: utf-8 -*-
"""单实例守护：基于 QSharedMemory，防止软件重复启动。"""
from PySide6.QtCore import QSharedMemory


class SingleInstance:
    def __init__(self, key: str):
        self._mem = QSharedMemory(key)
        # create 成功 = 第一个实例；失败 = 已有实例在运行（或残留段，重试一次）
        self._running = not self._mem.create(1)
        if self._running and self._mem.attach():
            self._mem.detach()
            self._running = not self._mem.create(1)

    def is_running(self) -> bool:
        return self._running
