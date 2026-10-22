# -*- coding: utf-8 -*-
"""系统监控组件（v8 C4，指导文档_v8.md §4.1）。

三层分离（规格 §2.2）：
    sample()                  → Snapshot（纯数据，ctypes 读系统计数）
    layout(rect)              → 环的位置（纯算术，可单测）
    draw(painter, rect, snap) → 画（纯绘制，可画到 QImage 上验收）
    MonitorWidget(GlassWidget) → 只管定时器与把三者接起来

为什么用 ctypes 而不是 psutil：
    项目唯一依赖是 PySide6（打包体积 / 免装依赖是硬约束）。三个指标都有
    现成 Win32 API，且不需要轮询驱动、不产生额外进程。

CPU 的"首采样无基准"是有意为之：GetSystemTimes 返回的是累计值，必须两次
差分才有占用率。首帧返回 None 并显示 `--`，而不是假装 0%——0% 是错误信息。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Dict, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen

from ... import effects
from ... import theme
from ...widget_style import DEFAULT_STYLE, Style
from ...widget_glass import PAD, GlassWidget

RING_STROKE_RATIO = 0.18      # 环线宽 / 半径
WIDE_RATIO = 1.6              # 宽高比 >= 此值走宽版（4×2 是 1.69，2×2 是 0.85）
WARN_AT = 70.0                # 黄色阈值
DANGER_AT = 88.0              # 红色阈值
ANIM_MS = 320                 # 数值推进时长（阻尼 0.9，不过冲）

# ---------------------------------------------------------------- Win32

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD),
                ("dwHighDateTime", wintypes.DWORD)]


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def _ft(v: _FILETIME) -> int:
    return (int(v.dwHighDateTime) << 32) | int(v.dwLowDateTime)


_cpu_prev = None      # 上一次 GetSystemTimes 的三个累计值


def sample_cpu() -> Optional[float]:
    """CPU 占用率（%）。首次调用无基准返回 None；失败返回 None。"""
    global _cpu_prev
    try:
        idle, kern, user = _FILETIME(), _FILETIME(), _FILETIME()
        if not kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern),
                                      ctypes.byref(user)):
            return None
        cur = (_ft(idle), _ft(kern), _ft(user))
        prev, _cpu_prev = _cpu_prev, cur
        if prev is None:
            return None
        d_idle = cur[0] - prev[0]
        # kernel 时间**包含** idle，所以总时间 = kernel + user
        d_total = (cur[1] - prev[1]) + (cur[2] - prev[2])
        if d_total <= 0:
            return None
        return _clamp((1.0 - d_idle / float(d_total)) * 100.0)
    except Exception:      # noqa: BLE001  —— 单个 API 挂了不许拖垮整个组件
        return None


def sample_memory():
    """(占用 %, 已用 GB, 总量 GB)；失败返回 (None, None, None)。"""
    try:
        m = _MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(m)
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return None, None, None
        total = int(m.ullTotalPhys) / (1024.0 ** 3)
        used = (int(m.ullTotalPhys) - int(m.ullAvailPhys)) / (1024.0 ** 3)
        return float(m.dwMemoryLoad), used, total
    except Exception:      # noqa: BLE001
        return None, None, None


def sample_disk(letter: str = "C:"):
    """(占用 %, 剩余 GB, 总量 GB)；盘符不存在/无权限返回 None。"""
    try:
        letter = (letter or "C:").strip().rstrip("\\")
        if len(letter) == 1:
            letter += ":"
        path = letter + "\\"
        free_bytes = ctypes.c_ulonglong()
        total_bytes = ctypes.c_ulonglong()
        total_free = ctypes.c_ulonglong()
        ok = kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(path),
            ctypes.byref(free_bytes), ctypes.byref(total_bytes),
            ctypes.byref(total_free))
        if not ok or int(total_bytes.value) <= 0:
            return None
        total = int(total_bytes.value)
        free = int(free_bytes.value)
        return (1.0 - free / float(total)) * 100.0, free / (1024.0 ** 3), total / (1024.0 ** 3)
    except Exception:      # noqa: BLE001
        return None


@dataclass(frozen=True)
class Snapshot:
    """一次采样的结果。任一字段为 None = 该项不可用（画 `--`）。"""

    cpu: Optional[float] = None
    mem: Optional[float] = None
    mem_used_gb: Optional[float] = None
    mem_total_gb: Optional[float] = None
    disk: Optional[float] = None
    disk_free_gb: Optional[float] = None
    disk_total_gb: Optional[float] = None
    disk_letter: str = "C:"
    ts: float = 0.0


def sample(disk_letter: str = "C:") -> Snapshot:
    """采一次三项指标（任一项失败只影响它自己）。"""
    cpu = sample_cpu()
    mem, mem_used, mem_total = sample_memory()
    disk = sample_disk(disk_letter)
    if disk is None:
        disk_pct = disk_free = disk_total = None
    else:
        disk_pct, disk_free, disk_total = disk
    return Snapshot(cpu=cpu, mem=mem, mem_used_gb=mem_used, mem_total_gb=mem_total,
                    disk=disk_pct, disk_free_gb=disk_free, disk_total_gb=disk_total,
                    disk_letter=(disk_letter or "C:"), ts=time.time())


# ---------------------------------------------------------------- 纯绘制

def _clamp(v: float) -> float:
    return max(0.0, min(100.0, float(v)))


def progress_color(value: float, style: Optional[Style] = None) -> QColor:
    """负载分档配色：正常 = ACCENT、偏高 = 琥珀、危险 = DANGER。"""
    v = _clamp(value)
    if v >= DANGER_AT:
        return QColor(theme.DANGER)
    if v >= WARN_AT:
        return QColor(232, 176, 88)
    return QColor((style or DEFAULT_STYLE).accent)


RING_KEYS = ("cpu", "mem", "disk")
RING_LABELS = {"cpu": "CPU", "mem": "内存", "disk": "磁盘"}


def layout(rect) -> Dict:
    """算出三个环的位置与文字列。纯算术，任意 rect 都不许抛。

    row（近方形，2×2）：三环横排，环下标签，环心偏上留出标签区；
    wide（4×2 宽版）：环集中在左侧 56%，右侧一列大号数值。
    """
    rect = QRectF(rect)
    w = max(1.0, rect.width())
    h = max(1.0, rect.height())
    inner = rect.adjusted(min(PAD, w * 0.12), min(PAD, h * 0.10),
                          -min(PAD, w * 0.12), -min(PAD, h * 0.10))
    wide = w >= h * WIDE_RATIO
    rings = []
    if wide:
        area_w = inner.width() * 0.56
        cell_w = area_w / 3.0
        diameter = max(4.0, min(cell_w - 8.0, inner.height() * 0.66))
        cy = inner.center().y()
        for i, key in enumerate(RING_KEYS):
            cx = inner.left() + cell_w * (i + 0.5)
            r = diameter / 2.0
            rings.append({"key": key, "rect": QRectF(cx - r, cy - r, diameter, diameter)})
        return {"mode": "wide", "rings": rings,
                "value_x": inner.left() + area_w + 4.0,
                "value_w": inner.width() - area_w - 4.0,
                "inner": inner}
    cell_w = inner.width() / 3.0
    diameter = max(4.0, min(cell_w - 6.0, inner.height() * 0.50))
    cy = inner.top() + diameter / 2.0 + (inner.height() - diameter) * 0.26
    for i, key in enumerate(RING_KEYS):
        cx = inner.left() + cell_w * (i + 0.5)
        r = diameter / 2.0
        rings.append({"key": key, "rect": QRectF(cx - r, cy - r, diameter, diameter)})
    return {"mode": "row", "rings": rings, "inner": inner,
            "label_y": cy + diameter / 2.0 + 4.0,
            "label_h": max(10.0, inner.bottom() - (cy + diameter / 2.0) - 4.0)}


def _fmt(value: Optional[float]) -> str:
    return "--" if value is None else "%d%%" % int(round(value))


def draw(p: QPainter, rect, snap: Snapshot, smooth: Optional[Dict] = None, style: Optional[Style] = None) -> None:
    """把快照画进 rect。`smooth` 传动画中的插值（缺省用原始值）。"""
    st = style or DEFAULT_STYLE
    rect = QRectF(rect)
    if rect.width() <= 4 or rect.height() <= 4:
        return
    sm = smooth or {}
    L = layout(rect)
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)

    for ring in L["rings"]:
        key = ring["key"]
        box = ring["rect"]
        raw = getattr(snap, key)
        val = raw if raw is None else _clamp(sm.get(key, raw))
        r = box.width() / 2.0
        pen_w = max(2.0, r * RING_STROKE_RATIO)

        # 轨道
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 30), pen_w, Qt.SolidLine, Qt.RoundCap))
        p.drawEllipse(box)

        # 进度弧（从 12 点顺时针）
        if val is not None and val > 0.5:
            p.setPen(QPen(progress_color(val, st), pen_w, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(box, 90 * 16, -int(round(val / 100.0 * 360 * 16)))

        # 环心数值（太小就不写字，避免糊成一团）
        # 2026-10-22：**宽版不写环心**。wide 布局已经把数值放到右侧一列，
        # 两处都画 = 同一个数字出现两次；组件库缩略图（318×116 就是 wide）
        # 里右列还窄，数字直接压到卡片外面去（README 截图时暴露）。
        if L["mode"] == "row" and r >= 12:
            fs = max(7, int(round(min(r * 0.62, 26))))
            f = theme.ui_font(fs, bold=True)
            p.setFont(f)
            p.setPen(QColor(theme.TEXT))
            txt = _fmt(val if raw is not None else None)
            p.drawText(box, Qt.AlignCenter, txt)

    if L["mode"] == "row":
        fs = max(7, int(round(min(L["rings"][0]["rect"].height() * 0.20, 13))))
        p.setFont(theme.ui_font(fs))
        p.setPen(QColor(theme.TEXT_DIM))
        cell_w = L["inner"].width() / 3.0
        for i, key in enumerate(RING_KEYS):
            lr = QRectF(L["inner"].left() + cell_w * i, L["label_y"],
                        cell_w, max(10.0, L["label_h"]))
            p.drawText(lr, Qt.AlignHCenter | Qt.AlignTop, RING_LABELS[key])
    else:
        # 右侧数值列：三行「CPU 42%」，行距 = 可用高度 / 3
        col_x = L["value_x"]
        col_w = max(10.0, L["value_w"])
        row_h = L["inner"].height() / 3.0
        for i, key in enumerate(RING_KEYS):
            y = L["inner"].top() + row_h * i
            p.setFont(theme.ui_font(max(8, int(min(row_h * 0.30, 13)))))
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(QRectF(col_x, y, col_w, row_h * 0.45),
                       Qt.AlignLeft | Qt.AlignVCenter, RING_LABELS[key])
            raw = getattr(snap, key)
            val = raw if raw is None else _clamp(sm.get(key, raw))
            p.setFont(theme.ui_font(max(11, int(min(row_h * 0.52, 30))), bold=True))
            p.setPen(QColor(st.text) if val is None else progress_color(val, st))
            p.drawText(QRectF(col_x, y + row_h * 0.38, col_w, row_h * 0.62),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       _fmt(None if raw is None else val))
    p.restore()


# ---------------------------------------------------------------- 组件

class MonitorWidget(GlassWidget):
    TYPE = "monitor"

    def __init__(self, storage, entry):
        super().__init__(storage, entry)
        self._snap = Snapshot()
        self._smooth: Dict[str, float] = {}
        self._anim_from: Dict[str, float] = {}
        self._anim_t0 = 0.0
        self._curve = effects.spring_curve(0.9, ANIM_MS)
        self._anim = QTimer(self)
        self._anim.setInterval(16)
        self._anim.timeout.connect(self._step)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()

    # ---------- 数据节拍 ----------
    def _disk_letter(self) -> str:
        return str((self.entry.get("settings") or {}).get("disk_letter") or "C:")

    def _tick(self):
        prev = self._snap
        self._snap = sample(self._disk_letter())
        self._anim_from = {k: getattr(prev, k) for k in RING_KEYS
                           if getattr(prev, k) is not None}
        # 首次有值直接落位（没有起点就不该从 0 弹上去）
        for k in RING_KEYS:
            if getattr(prev, k) is None and getattr(self._snap, k) is not None:
                self._smooth[k] = getattr(self._snap, k)
        self._anim_t0 = time.perf_counter()
        if self._anim_from:
            self._anim.start()
        self.update()

    def _step(self):
        t = (time.perf_counter() - self._anim_t0) / (ANIM_MS / 1000.0)
        done = t >= 1.0
        e = 1.0 if done else self._curve.valueForProgress(t)
        for k, a in self._anim_from.items():
            b = getattr(self._snap, k)
            self._smooth[k] = a + ((b if b is not None else a) - a) * e
        if done:
            self._anim.stop()
            self._anim_from = {}
        self.update()

    # ---------- 绘制 ----------
    def paint_content(self, p: QPainter):
        draw(p, QRectF(self.card_rect()), self._snap, self._smooth, style=self.style)

    def on_settings_changed(self):
        super().on_settings_changed()   # 清样式缓存 + 重绘
        self._tick()

    def closeEvent(self, e):
        for t in ("_timer", "_anim"):
            timer = getattr(self, t, None)
            if timer is not None:
                timer.stop()
        super().closeEvent(e)
