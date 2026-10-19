# -*- coding: utf-8 -*-
"""ShellNew 模板枚举与「新建」：还原系统桌面右键的新建能力。

背景（2026-10-19 反馈 6）：整理模式接管桌面后原生右键被替换，自绘菜单
只有"新建文件夹 / 新建文本文档"两项——用户装好的 Word / Excel / PPT
全部新建不了。系统的真实做法是读注册表 ShellNew 模板声明，实测有三条
路径（Windows 11 + Office 2024 本机验证）：

    HKCR\\.docx\\ShellNew                  （传统位置）
    HKCR\\.docx\\Word.Document.12\\ShellNew （Office 装在这层）
    HKCR\\.Word.Document.12\\ShellNew        （独立 ProgID）

值语义：

    NullFile    REG_SZ      空文件（记事本、压缩包等）
    FileName    REG_SZ      模板文件路径（可含 %SystemRoot%，Office 常用）
    Data        REG_BINARY  旧式内联内容（Win95 时代，仍兼容）
    Directory   REG_SZ      建目录（极少见，跳过）

本模块只做三件事：枚举模板、解析友好名、按模板创建（重名自动加序号）。
零第三方依赖：winreg + shutil + ctypes(SHLoadIndirectString)。
"""
from __future__ import annotations

import ctypes
import os
import shutil
import winreg
from typing import Dict, List, Optional

# 常见文档类型排前面（Office 装在哪个版本都能命中）
PRIORITY = (".txt", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
            ".rtf", ".csv", ".bmp", ".png", ".zip", ".rar", ".7z")

# 这些扩展名不提供（文件夹与快捷方式走单独入口）
SKIP_EXTS = {".lnk", ".url", "", "."}


def _load_indirect(text: str) -> str:
    """解析 `@shell32.dll,-12345` 形式的间接字符串（FriendlyTypeName）。"""
    if not text:
        return ""
    if not text.startswith("@"):
        return text
    try:
        buf = ctypes.create_unicode_buffer(512)
        hr = ctypes.windll.shlwapi.SHLoadIndirectString(
            ctypes.c_wchar_p(text), buf, 512, None)
        if hr == 0 and buf.value:
            return buf.value
    except Exception:
        pass
    return ""


def _read_default(root, path: str) -> str:
    try:
        with winreg.OpenKey(root, path) as k:
            v, _ = winreg.QueryValueEx(k, "")
            return str(v or "")
    except OSError:
        return ""


def _read_value(root, path: str, name: str):
    try:
        with winreg.OpenKey(root, path) as k:
            v, t = winreg.QueryValueEx(k, name)
            return v, t
    except OSError:
        return None, None


# 中文系统的「新建」菜单用词（Windows 原生就是这样显示的）。
# 注册表里的 FriendlyTypeName 常是英文（"Microsoft Word Document"），
# 已知类型优先用本地化词，未知类型才回落注册表。
KNOWN_LABELS = {
    ".txt": "文本文档", ".docx": "Word 文档", ".doc": "Word 文档",
    ".xlsx": "Excel 工作表", ".xls": "Excel 工作表",
    ".pptx": "PowerPoint 演示文稿", ".ppt": "PowerPoint 演示文稿",
    ".rtf": "RTF 文档", ".csv": "CSV 文件", ".bmp": "BMP 图像",
    ".png": "PNG 图像", ".zip": "压缩文件夹", ".rar": "RAR 压缩文件",
    ".7z": "7z 压缩文件", ".md": "Markdown 文件",
}


def _shellnew_paths(ext: str, progid: str) -> List[str]:
    """ShellNew 键的三条候选路径（实测 Office 用中间那条）。"""
    out = ["%s\\ShellNew" % ext]
    if progid:
        out.append("%s\\%s\\ShellNew" % (ext, progid))
        out.append("%s\\ShellNew" % progid)
    return out


def _friendly_name(ext: str, progid: str) -> str:
    """用户可读名：已知中文映射 > ProgID FriendlyTypeName > ProgID 默认值
    > 扩展名大写。"""
    if ext in KNOWN_LABELS:
        return KNOWN_LABELS[ext]
    if progid:
        raw, _ = _read_value(winreg.HKEY_CLASSES_ROOT,
                             "%s\\FriendlyTypeName" % progid)
        if raw:
            name = _load_indirect(str(raw))
            if name:
                return name
        name = _read_default(winreg.HKEY_CLASSES_ROOT, progid)
        if name and not name.startswith("@"):
            return name
    raw, _ = _read_value(winreg.HKEY_CLASSES_ROOT,
                         "%s\\FriendlyTypeName" % ext)
    if raw:
        name = _load_indirect(str(raw))
        if name:
            return name
    return ext.lstrip(".").upper()


def _has_shellnew(ext: str, progid: str) -> bool:
    for path in _shellnew_paths(ext, progid):
        try:
            winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, path).Close()
            return True
        except OSError:
            continue
    return False


def shell_new_templates(limit: int = 18) -> List[Dict]:
    """枚举系统「新建」模板：[{ext, progid, label, sort_key}]。

    只读注册表，不创建任何东西。排序：常见文档优先，其余按扩展名字母序。
    单条坏键不影响整体（逐个 try）。
    """
    found: List[Dict] = []
    seen = set()
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "") as root:
            i = 0
            while True:
                try:
                    ext = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                if not ext.startswith(".") or ext.lower() in SKIP_EXTS:
                    continue
                if ext.lower() in seen:
                    continue
                try:
                    progid = _read_default(winreg.HKEY_CLASSES_ROOT, ext)
                    if not _has_shellnew(ext, progid):
                        continue
                    label = _friendly_name(ext, progid)
                except Exception:
                    continue
                seen.add(ext.lower())
                found.append({
                    "ext": ext.lower(),
                    "progid": progid,
                    "label": label,
                    "sort_key": _sort_key(ext.lower()),
                })
    except OSError:
        return []

    # 兜底：Windows 11 的记事本不再注册 ShellNew（本机实测 .txt 无键），
    # 但"新建文本文档"是桌面最高频操作，必须永远可用（空文件即可）
    if not any(t["ext"] == ".txt" for t in found):
        found.append({"ext": ".txt", "progid": "", "label": "文本文档",
                      "sort_key": _sort_key(".txt")})
    found.sort(key=lambda t: t["sort_key"])
    return found[:limit]


def _sort_key(ext: str):
    try:
        idx = PRIORITY.index(ext)
    except ValueError:
        idx = len(PRIORITY)
    return (idx, ext)


def unique_path(folder: str, base: str, ext: str) -> str:
    """在 folder 里取一个不冲突的「base + ext」（重名加 (2)(3)…）。"""
    cand = os.path.join(folder, base + ext)
    if not os.path.exists(cand):
        return cand
    n = 2
    while True:
        cand = os.path.join(folder, "%s (%d)%s" % (base, n, ext))
        if not os.path.exists(cand):
            return cand
        n += 1


def _template_path(ext: str, progid: str) -> Optional[str]:
    """ShellNew 声明的模板文件路径（FileName 值，展开环境变量）。"""
    for path in _shellnew_paths(ext, progid):
        raw, _ = _read_value(winreg.HKEY_CLASSES_ROOT, path, "FileName")
        if raw:
            p = os.path.expandvars(str(raw))
            if os.path.exists(p):
                return p
    return None


def _template_data(ext: str, progid: str) -> Optional[bytes]:
    for path in _shellnew_paths(ext, progid):
        raw, _ = _read_value(winreg.HKEY_CLASSES_ROOT, path, "Data")
        if isinstance(raw, bytes) and raw:
            return raw
    return None


def create_from_template(tpl: Dict, folder: str,
                         base: str = None) -> Optional[str]:
    """按模板新建文件到 folder，返回实际路径（失败返回 None）。

    - FileName：复制模板文件（Office 文档走这条，得到带默认样式的文档）
    - Data    ：写入内联字节（老式模板）
    - 其它    ：创建空文件（NullFile 语义，记事本 / 压缩包等）
    """
    ext = tpl.get("ext") or ""
    if not ext:
        return None
    label = base if base is not None else ("新建" + (tpl.get("label") or ext.lstrip(".")))
    target = unique_path(folder, label, ext)
    try:
        src = _template_path(ext, tpl.get("progid") or "")
        if src:
            shutil.copyfile(src, target)
            return target
        data = _template_data(ext, tpl.get("progid") or "")
        if data:
            with open(target, "wb") as f:
                f.write(data)
            return target
        with open(target, "wb"):
            pass
        return target
    except Exception:
        return None
