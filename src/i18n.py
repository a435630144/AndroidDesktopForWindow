# -*- coding: utf-8 -*-
"""轻量 i18n（v10 D3，反馈 15-a）。

选型（规格 §5.3 决策 B）：不引 Qt Linguist、不引第三方包，就是**两份 JSON 字典 +
一个查表函数**。理由：本项目从 v6 起零第三方依赖、无构建工具链；而 JSON 能被
`scripts/check_docs.py` 的 [8] 校验"两种语言 key 集合相同"（漏译 = ERROR），
这条门禁比"记得去翻译"可靠得多。

用法：

    from . import i18n
    i18n.set_language(storage)          # 启动时一次，按设置/安装器/系统语言解析
    i18n.T("tray.settings")             # 取当前语言文案
    i18n.T("widget.empty", name="时钟")  # {name} 占位

约定：
  * 缺 key **不抛**，回退成 key 本身并在 `missing_keys()` 里记账——界面宁可显示
    `tray.settings` 这种丑东西，也不该在渲染路径上崩；
  * 语言代码只有 `zh_CN` / `en`；`auto` 只出现在**设置值**里，见 `resolve()`；
  * 文案里允许 `{name}` 这类 `str.format` 占位，值本身不要带花括号。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, Optional

ZH = "zh_CN"
EN = "en"
AUTO = "auto"
LANGS = (ZH, EN)
LANG_LABELS = {AUTO: "自动", ZH: "中文", EN: "English"}

_HERE = os.path.dirname(os.path.abspath(__file__))
_TABLES: Dict[str, Dict[str, str]] = {}
_current = ZH
_missing: set = set()


def _table_path(lang: str) -> str:
    """词表文件路径：源码态 `src/i18n/`，冻结态 `_MEIPASS/i18n/`。

    坑 #130（v10a 事故）：`build_portable.ps1` 只 `--add-data` 了 assets，
    词表没进冻结包；`open` 失败被 `except` 吞成空表 → `T()` 全部回退 key
    原文（界面满屏 `settings.title`），而 `TL()` 有中文兜底看起来正常——
    用户看到的"中英混搭"就是这么来的。源码态测试全绿也发现不了，必须
    由 I16（冻结布局取词）+ I17（打包脚本契约）两条判据钉住。
    """
    name = "%s.json" % lang
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", ""), "i18n", name)
    return os.path.join(_HERE, "i18n", name)


def _table(lang: str) -> Dict[str, str]:
    if lang not in LANGS:
        lang = ZH
    if lang not in _TABLES:
        try:
            with open(_table_path(lang), "r", encoding="utf-8") as f:
                _TABLES[lang] = json.load(f)
        except Exception:
            _TABLES[lang] = {}
    return _TABLES[lang]


def system_language() -> str:
    """系统界面语言（仅用于 auto 的最后兜底）。非 Windows / 取不到时按中文。"""
    try:
        import ctypes
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        # 0x04 = 中文（简/繁同主语言），其余一律按英文处理
        return ZH if (lang_id & 0x3FF) == 0x04 else EN
    except Exception:
        return ZH


def resolve(setting: Optional[str] = None, storage=None) -> str:
    """把设置值（auto/zh_CN/en）解析成生效语言。

    `auto` 的优先级：安装器写下的 `lang`（state.json 的 settings）→ 系统语言。
    安装器那一份是用户在**装的时候**选的，比系统语言更贴近意图。
    """
    value = setting
    if value is None and storage is not None:
        value = storage.get_setting("language")
    if value in LANGS:
        return value
    if storage is not None:
        installed = storage.get_setting("lang")
        if installed in LANGS:
            return installed
    return system_language()


def set_language(value) -> str:
    """`value` 可以是设置值（auto/...）或 storage 对象；返回生效语言。"""
    global _current
    if isinstance(value, str) or value is None:
        _current = resolve(value, None)
    else:
        _current = resolve(None, value)
    return _current


def language() -> str:
    return _current


def T(key: str, **fmt) -> str:
    """取文案；缺失时回退 key 本身（并记进 missing_keys）。"""
    text = _table(_current).get(key)
    if text is None:
        text = _table(ZH).get(key)
        if text is None:
            _missing.add(key)
            return key
    if fmt:
        try:
            return text.format(**fmt)
        except Exception:
            return text
    return text


def TL(key: str, fallback: str = "", **fmt) -> str:
    """带兜底的取词：key 不存在（或译文为空）时用 `fallback`，**不记 missing**。

    用于"数据里已经带着中文标签"的场景（`FieldSpec.label`、`dock.POSITION_LABELS`
    这类常量表、插件自带文案）。好处是插件与用户自定义分类不必提供英文也能
    正常显示；内置部分的覆盖情况由 `tests/test_i18n.py` 逐 key 断言。
    """
    text = _table(_current).get(key)
    if not text:
        text = _table(ZH).get(key)
    if not text:
        return fallback
    if fmt:
        try:
            return text.format(**fmt)
        except Exception:
            return text
    return text


def missing_keys() -> set:
    """本次进程里查过但不存在的 key（测试/门禁用）。"""
    return set(_missing)


def clear_missing() -> None:
    _missing.clear()


def all_keys(lang: str) -> set:
    return set(_table(lang).keys())


def category_label(category: str) -> str:
    """组件分类标签；没有对应 key 时原样返回（插件可自定义分类）。"""
    key = "category." + category
    text = _table(_current).get(key) or _table(ZH).get(key)
    return text if text else category
