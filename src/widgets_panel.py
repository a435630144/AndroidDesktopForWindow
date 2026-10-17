# -*- coding: utf-8 -*-
"""桌面面板小组件：对标腾讯桌面整理的右侧信息面板。

结构（自上而下）：
  - 搜索框：过滤 应用（开始菜单扫描）+ 桌面文件，回车启动第一个
  - 快捷文件夹：最近下载 / 桌面 / 图片 / 文档 / 视频，点击在资源管理器打开
  - 磁盘卡：系统盘已用 / 总量 + 占用条
  - 最近下载卡：按修改时间列最近 5 个文件，点击打开
  - 天气卡：静态示例（未接入天气服务，明确标注）

与时钟 / 便签一样挂在桌面带（Progman 正上方），可拖动 / 缩放 / 关闭。
"""
import datetime
import math
import os
import shutil
from pathlib import Path

from PySide6.QtCore import QFileInfo, QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QFileIconProvider, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QToolButton, QVBoxLayout, QWidget)

from . import appsource
from . import theme
from .widget_base import FloatingWidget

_FONT_CSS = ", ".join('"%s"' % f for f in theme.FONT_FAMILIES)
_ICON_PROVIDER = QFileIconProvider()

TOOLBUTTON_QSS = (
    "QToolButton{background: transparent; color: rgb(216,220,226); border: none;"
    " border-radius: 10px; padding: 4px; font-family: %s; font-size: 11px;}"
    "QToolButton:hover{background: rgba(255,255,255,22);}"
    "QToolButton:pressed{background: rgba(255,255,255,34);}"
) % _FONT_CSS


_GUID_BY_NAME = {
    "Downloads": "downloads", "下载": "downloads",
    "Desktop": "desktop", "桌面": "desktop",
    "Pictures": "pictures", "图片": "pictures",
    "Documents": "documents", "文档": "documents",
    "Videos": "videos", "视频": "videos",
}


def _known_folder(*names):
    """用户目录：Shell 已知目录 API 优先（处理 OneDrive 重定向），
    中英文目录名兜底；找不到返回 None。"""
    for n in names:
        p = appsource.shell_known_folder(_GUID_BY_NAME.get(n, ""))
        if p and Path(p).exists():
            return Path(p)
    home = Path.home()
    for n in names:
        p = home / n
        if p.exists():
            return p
    return None


class DiskCard(QWidget):
    """系统磁盘占用卡：标题 + 占用条 + 已用/总量。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(96)
        self.used = 0
        self.total = 0
        self._read()

    def _read(self):
        try:
            root = (os.environ.get("SystemDrive", "C:") or "C:") + "\\"
            du = shutil.disk_usage(root)
            self.used, self.total = du.used, du.total
        except Exception:
            self.used, self.total = 0, 0

    @staticmethod
    def _gb(n) -> str:
        return "%.1f GB" % (n / 1e9) if n < 1000e9 else "%.0f GB" % (n / 1e9)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(theme.SURFACE_RAISED)
        p.setPen(theme.BORDER)
        p.drawRoundedRect(self.rect(), theme.RADIUS_CARD, theme.RADIUS_CARD)
        pad = 14
        p.setPen(theme.TEXT)
        p.setFont(theme.ui_font(13))
        drive = (os.environ.get("SystemDrive", "C:") or "C:")
        p.drawText(QRect(pad, 12, 200, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   "本地磁盘（%s:）" % drive)
        if self.total > 0:
            free = self.total - self.used
            p.setPen(theme.TEXT_DIM)
            p.setFont(theme.ui_font(11))
            p.drawText(QRect(self.width() - pad - 200, 12, 200, 22),
                       Qt.AlignRight | Qt.AlignVCenter, "%s 可用" % self._gb(free))
            # 占用条
            bar = QRect(pad, 46, self.width() - pad * 2, 8)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 26))
            p.drawRoundedRect(bar, 4, 4)
            fw = int(bar.width() * self.used / self.total)
            p.setBrush(QColor(theme.ACCENT.red(), theme.ACCENT.green(), theme.ACCENT.blue(), 235))
            p.drawRoundedRect(QRect(bar.left(), bar.top(), max(8, fw), bar.height()), 4, 4)
            p.setPen(theme.TEXT_FAINT)
            p.setFont(theme.ui_font(11))
            pct = self.used * 100.0 / self.total
            p.drawText(QRect(pad, 62, self.width() - pad * 2, 20),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       "已用 %s / %s（%.0f%%）" % (self._gb(self.used), self._gb(self.total), pct))
        else:
            p.setPen(theme.TEXT_FAINT)
            p.setFont(theme.ui_font(11))
            p.drawText(QRect(pad, 46, self.width() - pad * 2, 20),
                       Qt.AlignVCenter, "无法读取磁盘信息")


class WeatherCard(QWidget):
    """天气卡：静态示例数据（未接入天气服务）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(96)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(theme.SURFACE_RAISED)
        p.setPen(theme.BORDER)
        p.drawRoundedRect(self.rect(), theme.RADIUS_CARD, theme.RADIUS_CARD)
        pad = 14
        # 太阳图标（自绘：圆 + 八道光芒）
        cx, cy, r = pad + 16, 48, 11
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 195, 87))
        p.drawEllipse(QRect(cx - r, cy - r, r * 2, r * 2))
        p.setPen(QColor(255, 195, 87, 200))
        for i in range(8):
            a = i * math.pi / 4
            x1 = cx + math.cos(a) * (r + 4)
            y1 = cy + math.sin(a) * (r + 4)
            x2 = cx + math.cos(a) * (r + 8)
            y2 = cy + math.sin(a) * (r + 8)
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
        p.setPen(theme.TEXT)
        p.setFont(theme.ui_font(26, bold=True))
        p.drawText(QRect(cx + 24, 26, 120, 40), Qt.AlignLeft | Qt.AlignVCenter, "17°C")
        p.setPen(theme.TEXT_DIM)
        p.setFont(theme.ui_font(13))
        p.drawText(QRect(cx + 24, 26, 160, 40), Qt.AlignRight | Qt.AlignVCenter, "晴")
        p.setPen(theme.TEXT_FAINT)
        p.setFont(theme.ui_font(11))
        p.drawText(QRect(self.width() - pad - 220, 62, 220, 20),
                   Qt.AlignRight | Qt.AlignVCenter, "北京 · 示例数据")


class RecentCard(QWidget):
    """最近下载卡：按修改时间列最近文件，点击打开。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []  # [(path, row_widget)]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        head = QHBoxLayout()
        title = QLabel("最近下载")
        title.setStyleSheet("color: rgb(168,173,181); font-size: 12px; background: transparent;")
        head.addWidget(title)
        head.addStretch(1)
        self.btn_open = QToolButton()
        self.btn_open.setText("打开文件夹")
        self.btn_open.setCursor(Qt.PointingHandCursor)
        self.btn_open.setStyleSheet(
            "QToolButton{background: transparent; color: rgb(76,194,255); border: none;"
            " font-size: 11px; padding: 2px 4px;}")
        self.btn_open.clicked.connect(self._open_folder)
        head.addWidget(self.btn_open)
        lay.addLayout(head)
        self.list_lay = QVBoxLayout()
        self.list_lay.setSpacing(2)
        lay.addLayout(self.list_lay)
        lay.addStretch(1)
        self._reload()
        self.setMinimumHeight(150)

    def _open_folder(self):
        d = _known_folder("Downloads", "下载")
        if d is not None:
            appsource.launch({"target": str(d)})

    def _reload(self):
        for _, w in self.rows:
            w.deleteLater()
        self.rows = []
        d = _known_folder("Downloads", "下载")
        items = []
        if d is not None:
            try:
                for f in d.iterdir():
                    if f.is_file():
                        items.append(f)
            except Exception:
                pass
        items.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        now = datetime.datetime.now()
        for f in items[:5]:
            row = QWidget()
            row.setCursor(Qt.PointingHandCursor)
            row.setStyleSheet("background: transparent;")
            hl = QHBoxLayout(row)
            hl.setContentsMargins(4, 3, 4, 3)
            hl.setSpacing(8)
            icon = QLabel()
            pm = _ICON_PROVIDER.icon(QFileInfo(str(f))).pixmap(QSize(20, 20))
            icon.setPixmap(pm)
            name = QLabel(f.name)
            name.setStyleSheet("color: rgb(242,243,245); font-size: 12px; background: transparent;")
            dt = datetime.datetime.fromtimestamp(f.stat().st_mtime)
            when = "今天" if dt.date() == now.date() else dt.strftime("%m-%d")
            when_lbl = QLabel(when)
            when_lbl.setStyleSheet("color: rgb(120,126,135); font-size: 11px; background: transparent;")
            hl.addWidget(icon)
            hl.addWidget(name, 1)
            hl.addWidget(when_lbl)
            row.mousePressEvent = lambda e, p=str(f): appsource.launch({"target": p})
            self.list_lay.addWidget(row)
            self.rows.append((str(f), row))
        if not self.rows:
            empty = QLabel("下载文件夹为空")
            empty.setStyleSheet("color: rgb(120,126,135); font-size: 11px; background: transparent;")
            self.list_lay.addWidget(empty)
            self.rows.append(("", empty))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(theme.SURFACE_RAISED)
        p.setPen(theme.BORDER)
        p.drawRoundedRect(self.rect(), theme.RADIUS_CARD, theme.RADIUS_CARD)


def _magnifier_pixmap() -> QPixmap:
    """自绘放大镜图标（浅灰）。"""
    pm = QPixmap(18, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QColor(150, 156, 165, 220))
    p.drawEllipse(QRect(3, 3, 9, 9))
    p.drawLine(11, 11, 15, 15)
    p.end()
    return pm


class DesktopPanel(FloatingWidget):
    TYPE = "panel"

    def __init__(self, storage, entry):
        # interactive=True：搜索框 / 按钮需要键盘焦点（NOACTIVATE 窗口无法输入）
        super().__init__(storage, entry, interactive=True)
        self.setMinimumSize(340, 460)
        self._apps_cache = None
        self._build()

    # ---------- UI ----------
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 36, 16, 16)
        lay.setSpacing(12)

        # 搜索
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("搜索应用、文件")
        self.ed_search.setClearButtonEnabled(True)
        self.ed_search.setStyleSheet(theme.INPUT_QSS)
        self.ed_search.addAction(QIcon(_magnifier_pixmap()), QLineEdit.LeadingPosition)
        self.ed_search.textChanged.connect(self._on_search)
        self.ed_search.returnPressed.connect(self._launch_first)
        lay.addWidget(self.ed_search)

        self.list_results = QListWidget()
        self.list_results.setStyleSheet(theme.LIST_QSS)
        self.list_results.setIconSize(QSize(24, 24))
        self.list_results.setMaximumHeight(200)
        self.list_results.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list_results.hide()
        self.list_results.itemClicked.connect(lambda it: self._launch_item(it))
        lay.addWidget(self.list_results)

        # 快捷文件夹
        folders = QHBoxLayout()
        folders.setSpacing(4)
        for label, path in (
            ("最近下载", _known_folder("Downloads", "下载")),
            ("桌面", _known_folder("Desktop", "桌面")),
            ("图片", _known_folder("Pictures", "图片")),
            ("文档", _known_folder("Documents", "文档")),
            ("视频", _known_folder("Videos", "视频")),
        ):
            btn = QToolButton()
            btn.setText(label)
            if path is not None:
                btn.setIcon(_ICON_PROVIDER.icon(QFileInfo(str(path))))
                btn.setToolTip(str(path))
                btn.clicked.connect(lambda checked=False, p=str(path): appsource.launch({"target": p}))
            else:
                btn.setEnabled(False)
                btn.setToolTip("目录不存在")
            btn.setIconSize(QSize(40, 40))
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            btn.setFixedSize(68, 72)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(TOOLBUTTON_QSS)
            folders.addWidget(btn)
        folders.addStretch(1)
        lay.addLayout(folders)

        # 磁盘 / 最近下载 / 天气
        lay.addWidget(DiskCard(self))
        self.recent = RecentCard(self)
        lay.addWidget(self.recent)
        lay.addWidget(WeatherCard(self))
        lay.addStretch(1)

    # ---------- 搜索 ----------
    def _on_search(self, text):
        text = text.strip()
        self.list_results.clear()
        if not text:
            self.list_results.hide()
            return
        low = text.lower()
        hits = []
        if self._apps_cache is None:
            try:
                self._apps_cache = appsource.all_apps()
            except Exception:
                self._apps_cache = []
        for app in self._apps_cache:
            if low in app.get("name", "").lower():
                hits.append(app)
            if len(hits) >= 8:
                break
        for f in appsource.scan_desktop_files():
            if low in f.get("name", "").lower():
                hits.append(f)
            if len(hits) >= 12:
                break
        if not hits:
            item = QListWidgetItem("无匹配结果")
            item.setFlags(Qt.NoItemFlags)
            self.list_results.addItem(item)
        else:
            for app in hits[:8]:
                item = QListWidgetItem(appsource.icon_for(app, 24), app.get("name", ""))
                item.setData(Qt.UserRole, app)
                self.list_results.addItem(item)
        self.list_results.show()

    def _launch_first(self):
        if self.list_results.count():
            self._launch_item(self.list_results.item(0))

    def _launch_item(self, item):
        app = item.data(Qt.UserRole)
        if app:
            appsource.launch(app)
            self.ed_search.clear()
            self.list_results.hide()
