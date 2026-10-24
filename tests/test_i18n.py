# -*- coding: utf-8 -*-
"""i18n 基建与双语界面（v10 D3，反馈 15-a）。

测的是**方案本身**，不是某一句译文：词表 key 集合相等（漏译=ERROR）、缺 key
的回退语义、`auto` 的解析优先级，以及三个界面（设置面板 / 组件库 / 组件设置
弹窗）在英文下真的吐出英文。

  I1  两份词表 key 集合完全相同
  I2  没有空译文
  I3  英文词表里没有中文（CJK）字符
  I4  T() 缺 key 回退 key 本身并记账；TL() 用兜底且不记账
  I5  resolve：显式设置 > 安装器写的 lang > 系统语言
  I6  set_language 收 storage / 字符串，脏值回落中文
  I7  注册表 display_name/display_summary 跟随语言（插件不受影响）
  I8  category_label 翻已知分类、未知分类原样
  I9  内置组件的每个 FieldSpec 都有 field.<key>.label；两个分组名都有 key
  I10 设置面板：中文/英文两套渲染（导航、页标题、完成按钮、语言下拉）
  I11 切语言：落盘 + 生效 + 触发整窗重建
  I12 组件库卡片按钮在英文下是 "Add to desktop"
  I13 组件设置弹窗：标题带组件英文名，字段标签走英文
  I14 托盘菜单的组件名走 display_name
  I15 桌面右键菜单文案与占位符替换（delete_selected 用 {n}）

运行：python tests/test_i18n.py   （offscreen）
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
ROOT = Path(__file__).resolve().parent.parent

from PySide6.QtWidgets import QApplication, QLabel

from src import i18n, widget_registry
from src.storage import Storage

TMP = Path(tempfile.gettempdir()) / "test_i18n.json"
failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def is_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def fresh() -> Storage:
    if TMP.exists():
        TMP.unlink()
    return Storage(path=str(TMP))


class FakeLayer:
    """组件库只需要这三个能力（预览/卡片状态/计数）。"""

    def __init__(self):
        self.storage = fresh()

    def entries_of(self, _wtype):
        return []


def main(app):
    here = Path(__file__).resolve().parent.parent / "src" / "i18n"
    zh = json.loads((here / "zh_CN.json").read_text(encoding="utf-8"))
    en = json.loads((here / "en.json").read_text(encoding="utf-8"))

    # ---------- I1 / I2 / I3 ----------
    check("I1 两份词表 key 集合完全相同",
          set(zh) == set(en), "only-zh=%s only-en=%s"
          % (sorted(set(zh) - set(en))[:3], sorted(set(en) - set(zh))[:3]))
    blanks = [k for table in (zh, en) for k, v in table.items() if not str(v).strip()]
    check("I2 没有空译文", not blanks, str(blanks[:3]))
    # 词表里允许出现中文的地方只有一个：引用的文档文件名（docs/组件开发指南.md）。
    # 那是路径，不是译文——翻译它反而会让链接失效。
    path_rx = re.compile(r"docs/[^\s,)]+")
    cjk = [k for k, v in en.items() if is_cjk(path_rx.sub("", str(v)))]
    check("I3 英文词表里没有中文（文档文件名除外）", not cjk, str(cjk[:4]))

    # ---------- I4 ----------
    i18n.set_language(i18n.ZH)
    i18n.clear_missing()
    check("I4a T() 缺 key 时回退成 key 本身",
          i18n.T("nope.missing.key") == "nope.missing.key")
    check("I4b 缺 key 被记账", "nope.missing.key" in i18n.missing_keys(),
          str(sorted(i18n.missing_keys())[:3]))
    i18n.clear_missing()
    check("I4c TL() 缺 key 用兜底值",
          i18n.TL("nope.missing.key", "兜底") == "兜底")
    check("I4d TL() 不记账", i18n.missing_keys() == set(),
          str(sorted(i18n.missing_keys())[:3]))

    # ---------- I5 / I6 ----------
    st = fresh()
    orig_system = i18n.system_language
    try:
        i18n.system_language = lambda: i18n.EN
        check("I5a auto + 无安装器语言 -> 系统语言",
              i18n.resolve(i18n.AUTO, st) == i18n.EN)
        st.set_setting("lang", i18n.ZH)
        check("I5b auto + 安装器写了 lang -> 用安装器那一个",
              i18n.resolve(i18n.AUTO, st) == i18n.ZH)
        st.set_setting("language", i18n.EN)
        check("I5c 显式设置优先于安装器与系统",
              i18n.resolve(None, st) == i18n.EN)
        st.set_setting("language", "klingon")
        check("I5d 脏设置值 -> 回落安装器语言",
              i18n.resolve(None, st) == i18n.ZH)
    finally:
        i18n.system_language = orig_system

    check("I6a set_language 收字符串",
          i18n.set_language(i18n.EN) == i18n.EN)
    check("I6b set_language 收 storage",
          i18n.set_language(st) == i18n.ZH)

    # ---------- I7 / I8 ----------
    spec = widget_registry.get("clock")
    i18n.set_language(i18n.EN)
    en_name = spec.display_name()
    i18n.set_language(i18n.ZH)
    check("I7a display_name 跟随语言",
          (en_name, spec.display_name()) == ("Clock", "时钟"),
          "%s / %s" % (en_name, spec.display_name()))
    check("I7b display_summary 跟随语言",
          spec.display_summary() == zh["widget.clock.summary"])
    i18n.set_language(i18n.EN)
    check("I8a category_label 翻已知分类",
          i18n.category_label("时间") == "Time", i18n.category_label("时间"))
    check("I8b category_label 未知分类原样",
          i18n.category_label("其他") == "其他", i18n.category_label("其他"))

    # ---------- I9 ----------
    need = set()
    for s in widget_registry.all_specs():
        if s.plugin:
            continue
        for f in s.settings:
            need.add("field.%s.label" % f.key)
        for f in s.settings:
            for value, _label in f.choices:
                need.add("field.%s.%s" % (f.key, value))
    miss = sorted(k for k in need if k not in en)
    check("I9a 内置组件字段标签全部有英文 key", not miss, str(miss[:5]))
    groups = {"field.group.外观", "field.group.组件设置"}
    check("I9b 分组标题有 key", not (groups - set(en)),
          str(sorted(groups - set(en))))

    # ---------- I10 / I11 ----------
    from src import settings_dialog as sd
    from src.widget_center import WidgetCenterPage
    from src.widget_settings import WidgetSettingsDialog

    class FakeWindow:
        attached = True

        def rebuild(self, stagger=False):
            pass

        def refresh_grid(self):
            pass

    def build_dialog(st):
        return sd.SettingsDialog(FakeWindow(), st, None)

    st_zh = fresh()
    st_zh.set_setting("language", i18n.ZH)
    i18n.set_language(st_zh)
    dlg_zh = build_dialog(st_zh)
    nav_zh = [b.text() for b in dlg_zh._nav_buttons]
    check("I10a 中文设置面板导航",
          nav_zh[:2] == ["通用", "组件库"], str(nav_zh))
    check("I10b 中文完成按钮", dlg_zh.btn_close.text() == "完成",
          dlg_zh.btn_close.text())

    st_en = fresh()
    st_en.set_setting("language", i18n.EN)
    i18n.set_language(st_en)
    dlg = build_dialog(st_en)
    nav_en = [b.text() for b in dlg._nav_buttons]
    check("I10c 英文设置面板导航",
          nav_en[:2] == ["General", "Widgets"], str(nav_en))
    check("I10d 英文完成按钮", dlg.btn_close.text() == "Done",
          dlg.btn_close.text())
    check("I10e 页标题随导航切",
          dlg.lbl_page_title.text() == "General", dlg.lbl_page_title.text())
    check("I10f 语言下拉当前值 = 设置里的值",
          dlg.cmb_language.currentData() == i18n.EN,
          str(dlg.cmb_language.currentData()))
    check("I10g 语言下拉三项（自动 / 中文 / English）",
          [dlg.cmb_language.itemData(i) for i in range(dlg.cmb_language.count())]
          == [i18n.AUTO, i18n.ZH, i18n.EN])

    # I11：切换语言 -> 落盘 + 生效 + 触发重建（重建本身打桩，别真的重开窗）
    rebuilt = []
    dlg._restart_ui = lambda: rebuilt.append(i18n.language())
    idx_zh = dlg.cmb_language.findData(i18n.ZH)
    dlg.cmb_language.setCurrentIndex(idx_zh)
    check("I11a 切换写进 storage",
          st_en.get_setting("language") == i18n.ZH,
          str(st_en.get_setting("language")))
    check("I11b 切换立即生效", i18n.language() == i18n.ZH, i18n.language())
    check("I11c 切换触发整窗重建", rebuilt == [i18n.ZH], str(rebuilt))

    # ---------- I12 ----------
    i18n.set_language(i18n.EN)
    layer = FakeLayer()
    center = WidgetCenterPage(layer)
    first = center.cards[0]
    check("I12a 组件库卡片按钮英文",
          first.button.text() == "Add to desktop", first.button.text())
    check("I12b 组件库计数英文",
          "widgets added" in center.count_label.text()
          and not is_cjk(center.count_label.text()),
          center.count_label.text())

    # ---------- I13 ----------
    spec = widget_registry.get("clock")
    entry = {"id": "c1", "type": "clock", "settings": {}}
    wdlg = WidgetSettingsDialog(spec, entry, st_en)
    check("I13a 组件设置标题带英文名",
          wdlg.windowTitle() == "Clock · Settings", wdlg.windowTitle())
    labels = [lb.text() for lb in wdlg.findChildren(QLabel)]
    check("I13b 字段标签走英文", "Show seconds" in labels, str(labels[:6]))

    # ---------- I15：桌面右键菜单（占位符替换） ----------
    check("I15a 菜单文案英文", i18n.T("menu.view") == "View",
          i18n.T("menu.view"))
    check("I15b 菜单占位符替换正确",
          i18n.T("menu.delete_selected", n=3) == "Delete selected (3)",
          i18n.T("menu.delete_selected", n=3))
    i18n.set_language(i18n.ZH)
    check("I15c 中文菜单占位符替换正确",
          i18n.T("menu.delete_selected", n=3) == "删除选中（3）",
          i18n.T("menu.delete_selected", n=3))
    i18n.set_language(i18n.EN)      # 下面 I14 仍按英文断言

    # ---------- I14 ----------
    from src import tray
    check("I14 托盘菜单组件名走 display_name",
          tray.widget_name("clock") == "Clock", tray.widget_name("clock"))

    # ---------- I16：冻结态词表路径（v10a 事故回归，坑 #130） ----------
    # v10a 冻结包没带 src/i18n/*.json，open 失败被 except 吞掉 → 词表空 →
    # T() 全部回退 key 原文（界面满屏 settings.title）。判据：冻结布局下
    # 词表必须从 _MEIPASS/i18n 加载，而不是源码目录。
    import shutil
    fake_meipass = Path(tempfile.mkdtemp(prefix="i18n_meipass_"))
    (fake_meipass / "i18n").mkdir()
    for _lang in (i18n.ZH, i18n.EN):
        data = json.loads((ROOT / "src" / "i18n" / ("%s.json" % _lang))
                          .read_text(encoding="utf-8"))
        data["settings.title"] = "FROM_MEIPASS_%s" % _lang   # 打标记
        (fake_meipass / "i18n" / ("%s.json" % _lang)).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")
    saved_frozen = getattr(sys, "frozen", None)
    saved_meipass = getattr(sys, "_MEIPASS", None)
    try:
        i18n.set_language(i18n.ZH)      # 上面 I15 之后是英文态，先归位
        sys.frozen = True
        sys._MEIPASS = str(fake_meipass)
        i18n._TABLES.clear()
        got = i18n.T("settings.title")
        check("I16 冻结态从 _MEIPASS/i18n 取词",
              got == "FROM_MEIPASS_zh_CN", got)
        i18n.set_language(i18n.EN)
        i18n._TABLES.clear()
        got = i18n.T("settings.title")
        check("I16b 冻结态英文词表同样可取",
              got == "FROM_MEIPASS_en", got)
        i18n.set_language(i18n.ZH)
    finally:
        if saved_frozen is None:
            sys.__dict__.pop("frozen", None)
        else:
            sys.frozen = saved_frozen
        if saved_meipass is None:
            sys.__dict__.pop("_MEIPASS", None)
        else:
            sys._MEIPASS = saved_meipass
        i18n._TABLES.clear()
        shutil.rmtree(fake_meipass, ignore_errors=True)
    check("I16c 回到源码态仍取得到中文词表",
          i18n.T("settings.title") == "掌镜桌面 · 设置", i18n.T("settings.title"))

    # ---------- I17：打包脚本必须带上词表（漏了就重蹈 v10a） ----------
    build_ps1 = (ROOT / "scripts" / "build_portable.ps1").read_text(encoding="utf-8")
    check("I17 build_portable.ps1 含 --add-data src/i18n",
          re.search(r'--add-data\s+"src/i18n', build_ps1) is not None,
          "scripts/build_portable.ps1 缺 --add-data \"src/i18n;i18n\"")

    # ---------- I18：动态拼接的 key 前缀每个都有实例 ----------
    # T("settings.nav." + page) 这类拼 key，词表里必须真的有前缀下的具体 key，
    # 否则拼出来的 key 永远查不到、界面露原样 key 且无人发现。
    used = set()
    for py in (ROOT / "src").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for m in re.finditer(r'\b(?:T|TL)\(\s*["\']([a-z0-9_.]+)["\']\s*\+', text):
            used.add(m.group(1))
    zh_table = json.loads((ROOT / "src" / "i18n" / "zh_CN.json").read_text(encoding="utf-8"))
    bad = sorted(p for p in used if not any(k.startswith(p) for k in zh_table))
    check("I18 动态前缀 %d 个全部有实例" % len(used), not bad, "缺实例：%s" % bad)

    for obj in (dlg, dlg_zh, wdlg):
        obj.close()
        obj.deleteLater()
    center.deleteLater()      # 假 layer 没有 widgetsChanged，不走 closeEvent
    i18n.set_language(i18n.ZH)
    app.processEvents()

    print("-" * 56)
    if failures:
        print("失败 %d 项：%s" % (len(failures), "、".join(failures)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    _app = QApplication(sys.argv)
    sys.exit(main(_app))
