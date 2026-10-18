# -*- coding: utf-8 -*-
"""Windows 桌面层挂载工具：主窗口与桌面小组件共用。

目标：把 Qt 窗口放进"桌面带"——位于壁纸之上、普通应用程序窗口之下。
用户点击 / 打开任何应用时，桌面带内容自动被应用窗口覆盖，不会被置顶。

实现方案（实测验证 2026-10-16）：
  不改变窗口父子关系（SetParent 会把 WS_POPUP 改成 WS_CHILD，
  Qt 半透明窗口依赖 WS_EX_LAYERED，改风格后直接不可见——已踩坑）；
  保持窗口为顶层窗口，用 SetWindowPos 把它插到 Progman（桌面窗口）
  正上方一位，即得到"壁纸之上、应用窗口之下"的桌面带。
  配合 Qt.WindowDoesNotAcceptFocus（WS_EX_NOACTIVATE），
  窗口永不被激活，因此永远不会盖到应用程序窗口前面。

  多显示器：Progman 横跨整个虚拟桌面，插入其上方对所有屏幕生效。

  部分系统在 Progman 上方还有承载原生桌面图标（SHELLDLL_DefView）的
  WorkerW——本方案插在 Progman 正上方，同样位于该图标层之下，行为一致。

实测踩坑记录（重要）：
1. 挂载前必须先 show()：未显示的窗口 IsWindowVisible 恒为 false。
2. 不要 SetParent：见上（分层子窗口不被支持，窗口直接消失）。
3. 不要 WindowStaysOnTopHint：那正是"组件覆盖所有窗口"Bug 的根因。
4. SetWindowPos(hwnd, Progman, ...) 语义：把 hwnd 插到 Progman 正上方
   （hWndInsertAfter 指"排在后面的窗口"，即位于其下）。
5. z-order 校验用 GetWindow(GW_HWNDNEXT) 从桌面窗口向下遍历，
   索引 0 为最顶层；窗口应紧邻 Progman 之上。
6. 第三方桌面软件（如腾讯桌面整理）会留下大量微型 WorkerW 残留，
   任何按"找 WorkerW 父窗口"的方案都不可靠——本方案不依赖 WorkerW。
"""
import ctypes
from ctypes import wintypes

_user32 = ctypes.windll.user32
_user32.FindWindowW.restype = wintypes.HWND
_user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
_user32.GetClassNameW.restype = ctypes.c_int
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetDesktopWindow.restype = wintypes.HWND
_user32.GetDesktopWindow.argtypes = []
_user32.GetWindow.restype = wintypes.HWND
_user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT]
_user32.GetWindowLongW.restype = wintypes.LONG
_user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.SendMessageTimeoutW.restype = wintypes.LPARAM
_user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                        wintypes.UINT, wintypes.UINT, ctypes.POINTER(wintypes.DWORD)]
_user32.ShowWindow.restype = wintypes.BOOL
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]

GA_PARENT = 1
GW_CHILD, GW_HWNDNEXT = 5, 2
SM_CXSCREEN, SM_CYSCREEN = 0, 1
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000

SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_NOZORDER = 0x0001, 0x0002, 0x0010, 0x0004
SW_HIDE, SW_SHOW = 0, 5


def _class_of(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    if _user32.GetClassNameW(hwnd, buf, 256):
        return buf.value
    return ""


def _rect_of(hwnd):
    r = wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r


def _size_of(hwnd):
    r = _rect_of(hwnd)
    return (r.right - r.left, r.bottom - r.top)


def _enum_zorder() -> list:
    """按 z-order（从顶到底）枚举全部顶层窗口（GetWindow 遍历，顺序可靠）。"""
    out = []
    h = _user32.GetWindow(_user32.GetDesktopWindow(), GW_CHILD)
    while h:
        out.append(h)
        h = _user32.GetWindow(h, GW_HWNDNEXT)
    return out


def _screen_size():
    """主屏幕尺寸（GetSystemMetrics 虚拟屏幕指标在部分环境返回 0）。"""
    w = _user32.GetSystemMetrics(SM_CXSCREEN)
    h = _user32.GetSystemMetrics(SM_CYSCREEN)
    if w <= 0 or h <= 0:
        progman = _progman()
        if progman:
            return _size_of(progman)
        return (0, 0)
    return (w, h)


def _is_desktop_sized(hwnd) -> bool:
    """窗口是否达到桌面级尺寸：过滤第三方桌面软件残留的微型 WorkerW。"""
    try:
        w, h = _size_of(hwnd)
        sw, sh = _screen_size()
        if sw <= 0 or sh <= 0:
            return True  # 取不到屏幕尺寸时不加过滤
        return w >= sw * 0.5 and h >= sh * 0.5
    except Exception:
        return False


def _progman() -> int:
    return int(_user32.FindWindowW("Progman", None) or 0)


def _has_noactivate(hwnd) -> bool:
    ex = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
    return bool(ex & WS_EX_NOACTIVATE)


def _insert_above(hwnd: int, above_of: int) -> bool:
    """把 hwnd 插到 above_of 正上方一位（不移动、不改大小、不激活）。

    注意 Win32 语义：SetWindowPos(h, insertAfter) 标准语义是把 h 放到
    insertAfter **下方**（hWndInsertAfter 是"前驱"）。Progman 是例外——
    实测 SetWindowPos(h, Progman) 会把 h 插到 Progman 正上方一位
    （attach_to_desktop 依赖该行为，见模块头注释 4）。
    对普通窗口要用 insert_above_window()。
    """
    return bool(_user32.SetWindowPos(
        hwnd, above_of, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE))


GW_HWNDPREV = 3
HWND_TOP = 0


def insert_above_window(hwnd: int, above_of: int) -> bool:
    """把 hwnd 插到普通窗口 above_of 的正上方一位。

    实现：先取 above_of 的前驱（z-order 中位于其上的窗口），再把 hwnd
    插到该前驱下方（标准 SetWindowPos 语义）= above_of 上方。
    above_of 已是 z-order 最顶时退化为 HWND_TOP。
    用于 FolderPopup 插到整理窗口之上（2026-10-18：弹窗在整理窗口之下
    会被全窗口 HTCLIENT 的命中测试挡住，点不到）。
    """
    prev = int(_user32.GetWindow(above_of, GW_HWNDPREV) or 0)
    if prev:
        return _insert_above(hwnd, prev)
    return bool(_user32.SetWindowPos(
        hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE))


def is_in_desktop_band(hwnd: int, progman: int = 0) -> bool:
    """hwnd 是否位于桌面带（Progman 正上方一位）。"""
    progman = progman or _progman()
    if not progman or not hwnd:
        return False
    wins = _enum_zorder()
    if hwnd not in wins or progman not in wins:
        return False
    return wins.index(hwnd) == wins.index(progman) - 1


def is_above(hwnd: int, other: int) -> bool:
    """hwnd 是否在 other 之上（z-order 索引更小）。"""
    wins = _enum_zorder()
    if hwnd not in wins or other not in wins:
        return False
    return wins.index(hwnd) < wins.index(other)


# ---------- 桌面带成员注册表（M5：弹窗「带内最顶」用） ----------
# attach_to_desktop 成功时登记 hwnd。band_topmost_hwnd() 供文件夹弹窗
# 找带内当前最顶成员（整理窗口 + 各小组件 + 幕布），把弹窗插到其上——
# 保证弹窗压得住桌面带内所有元素（指导文档 §4.2，决策 D5）。
# 关闭的窗口会从 z-order 枚举里消失，过期登记项由 band_topmost_hwnd
# 过滤；显式 unregister 供 close 路径调用。
_BAND_HWNDS = []


def register_band_window(hwnd: int):
    """登记桌面带成员（attach_to_desktop 成功时调用）。"""
    hwnd = int(hwnd)
    if hwnd and hwnd not in _BAND_HWNDS:
        _BAND_HWNDS.append(hwnd)


def unregister_band_window(hwnd: int):
    """注销桌面带成员（窗口关闭路径调用）。"""
    try:
        _BAND_HWNDS.remove(int(hwnd))
    except ValueError:
        pass


def band_topmost_hwnd(exclude_hwnd: int = 0, zorder=None) -> int:
    """桌面带内当前最顶成员的 hwnd（z-order 索引最小；排除 exclude）。

    zorder 可注入（单测用；缺省实时枚举）。过期登记（已关闭窗口）自动
    过滤。无成员返回 0（调用方回退主窗口）。
    """
    wins = list(zorder) if zorder is not None else _enum_zorder()
    best = 0
    for hw in list(_BAND_HWNDS):
        if hw == exclude_hwnd or hw not in wins:
            continue
        if best == 0 or wins.index(hw) < wins.index(best):
            best = hw
    return best


def attach_to_desktop(widget, below_hwnd: int = 0) -> bool:
    """把 Qt 窗口放入桌面带（壁纸之上、应用窗口之下）。

    调用方必须已经 show() 过该窗口。below_hwnd 可选：给定另一个
    桌面带窗口句柄时，把本窗口插到它正下方（例如小组件放在图标层之下）。
    失败返回 False，调用方自行兜底（如悬浮模式）。
    """
    try:
        hwnd = int(widget.winId())
        progman = _progman()
        if not progman:
            return False
        if below_hwnd:
            # 先确保参照窗口自身在桌面带，否则会把本窗口一起带出桌面带
            if not is_in_desktop_band(below_hwnd, progman):
                if not _insert_above(below_hwnd, progman):
                    return False
            ok = _insert_above(hwnd, below_hwnd)
        else:
            ok = _insert_above(hwnd, progman)
        if not ok:
            return False
        # 校验：必须在 Progman 之上（紧邻其上，或下方隔着同带窗口）
        for _ in range(10):
            if is_above(hwnd, progman):
                break
            ctypes.windll.kernel32.Sleep(50)
        if is_above(hwnd, progman):
            register_band_window(hwnd)
            return True
        return False
    except Exception:
        return False


def diagnose_desktop_layer() -> dict:
    """诊断桌面层结构（排查挂载 / 层级问题用）。"""
    progman = _progman()
    wins = _enum_zorder()
    workerws = [h for h in wins if _class_of(h) == "WorkerW"]
    pos = wins.index(progman) if progman in wins else -1
    band = [h for h in wins[:pos]] if pos >= 0 else []  # Progman 之上的窗口
    # 只统计窗口类名为 Qt 的（我们自己的窗口），其余是应用窗口
    qt_band = [h for h in band if "Qt" in _class_of(h)]
    return {
        "progman": progman,
        "progman_size": str(_size_of(progman)) if progman else None,
        "progman_visible": bool(progman and _user32.IsWindowVisible(progman)),
        "screen_size": _screen_size(),
        "total_toplevel": len(wins),
        "progman_zindex": pos,
        "workerw_total": len(workerws),
        "workerw_desktop_sized": len([h for h in workerws if _is_desktop_sized(h)]),
        "band_window_count": len(band),
        "band_qt_windows": qt_band,
        "native_icons_hidden": native_icons_hidden(),
    }


# ---------- 原生桌面图标隐藏 / 恢复 ----------
# 第三方桌面的标准做法（腾讯桌面整理同款）：找到承载原生图标的
# SHELLDLL_DefView（Progman 或 WorkerW 的子窗口）并 ShowWindow(SW_HIDE)，
# 桌面文件改由我们克隆渲染，从而完全掌控位置与样式。
# 退出 / 崩溃自愈时必须恢复，否则用户将看不到任何桌面图标。

_native_icons_hidden = False


def _iter_children(parent):
    h = _user32.GetWindow(parent, GW_CHILD)
    while h:
        yield int(h)
        h = _user32.GetWindow(h, GW_HWNDNEXT)


def _find_defview() -> int:
    """定位 SHELLDLL_DefView：先找 Progman 子窗口，再找各 WorkerW 子窗口。"""
    progman = _progman()
    if not progman:
        return 0
    for h in _iter_children(progman):
        if _class_of(h) == "SHELLDLL_DefView":
            return h
    h = _user32.GetWindow(_user32.GetDesktopWindow(), GW_CHILD)
    while h:
        if _class_of(h) == "WorkerW":
            for c in _iter_children(h):
                if _class_of(c) == "SHELLDLL_DefView":
                    return c
        h = _user32.GetWindow(h, GW_HWNDNEXT)
    return 0


def set_native_icons_visible(visible: bool) -> bool:
    """显示 / 隐藏系统原生桌面图标。返回操作后的实际状态是否符合预期。"""
    global _native_icons_hidden
    dv = _find_defview()
    if not dv:
        return bool(visible)  # 找不到 DefView 时视为原生图标本就可见
    _user32.ShowWindow(dv, SW_SHOW if visible else SW_HIDE)
    _native_icons_hidden = not visible
    now_visible = bool(_user32.IsWindowVisible(dv))
    return now_visible == bool(visible)


def native_icons_hidden() -> bool:
    return _native_icons_hidden


def restore_native_icons():
    """恢复原生桌面图标（退出清理 / 崩溃自愈，重复调用安全）。

    必须无条件恢复：_native_icons_hidden 是进程私有标志，跨进程调用
    （外部恢复脚本、verify 工具、其他实例）时恒为 False，带条件会直接
    跳过恢复——用户桌面将停留在无图标状态直到重启应用。
    SW_SHOW 对已可见窗口无害，幂等安全。
    """
    set_native_icons_visible(True)
