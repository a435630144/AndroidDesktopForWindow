# -*- coding: utf-8 -*-
"""桌面目录监听（v6 §7.4 自动同步）。

实现选型：**QFileSystemWatcher**，不是 pywin32 的 ReadDirectoryChangesW——
Windows 上 QFileSystemWatcher 底层就是 ReadDirectoryChangesW（同一机制），
而本项目只依赖 PySide6（venv 里没有 pywin32，requirements 也只有 PySide6 /
PyInstaller / pillow），引入 win32file 会多一个运行依赖、还得多处理
PyInstaller 的 win32timezone 隐藏导入。

事件节奏：下载工具 / 编辑器保存会产生成串事件（写临时文件 → 改名 → 删临时
文件，或一次保存触发多次 CHANGE_LAST_WRITE），因此做 1s debounce：每来一个
事件就重置计时器，安静 1s 后才做一次增量 diff。diff 本身不依赖事件类型
（新增 / 删除 / 重命名在 diff 里都能收敛），比按事件类型分支更健壮。
"""
import os

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from . import appsource

DEBOUNCE_MS = 1000


class DesktopWatcher(QObject):
    """监听桌面目录，debounce 后调 storage.sync_desktop_incremental()。"""

    synced = Signal(int, int)      # (added, removed)

    def __init__(self, storage, on_sync=None, folders=None,
                 debounce_ms=DEBOUNCE_MS, parent=None):
        super().__init__(parent)
        self.storage = storage
        self._on_sync = on_sync
        self._debounce_ms = int(debounce_ms)
        self._folders = list(folders) if folders is not None else None
        self._paths = []

        self._watch = QFileSystemWatcher(self)
        self._watch.directoryChanged.connect(self.kick)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self._debounce_ms)
        self._timer.timeout.connect(self.flush)

        self.start()

    # ---------- 生命周期 ----------
    def start(self):
        """挂上桌面目录；返回实际监听的路径列表（不存在 / 无权限的跳过）。"""
        folders = (self._folders if self._folders is not None
                   else appsource._desktop_folders())
        for d in folders:
            p = str(d)
            if p in self._paths:
                continue
            try:
                if os.path.isdir(p) and self._watch.addPath(p):
                    self._paths.append(p)
            except Exception:
                continue
        return list(self._paths)

    def stop(self):
        """停止监听（设置里关掉自动同步 / 程序退出）。"""
        self._timer.stop()
        if self._paths:
            try:
                self._watch.removePaths(self._paths)
            except Exception:
                pass
            self._paths = []

    @property
    def paths(self):
        return list(self._paths)

    def running(self) -> bool:
        return bool(self._paths)

    # ---------- 事件 ----------
    def kick(self, *_args):
        """收到目录事件：重启 debounce（连续事件合并成一次同步）。"""
        if not self._paths:
            return
        self._timer.start()

    def pending(self) -> bool:
        return self._timer.isActive()

    def flush(self):
        """立即做一次增量同步（debounce 到点 / 退出前强制刷）。"""
        self._timer.stop()
        added, removed_ids = self.storage.sync_desktop_incremental()
        removed = len(removed_ids)
        if added or removed:
            if self._on_sync is not None:
                self._on_sync(added, removed)
            self.synced.emit(added, removed)
        return added, removed_ids
