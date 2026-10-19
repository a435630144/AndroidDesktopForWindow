# -*- coding: utf-8 -*-
"""设置界面（2026-10-19 反馈 10：整页重构为 AirDeck 式苹果风）。

旧版的病：一列四张卡片、文字全用纯白硬堆层级、QSS 散落在每个控件上，
深色底上失去可读性层次。重构为「左侧导航 + 右栏分页 + 行式卡片」，
文字颜色与字号统一由 theme.SETTINGS_QSS 提供。

  U1 左侧栏 5 个导航项（通用 / 外观与图标 / 布局与网格 / 模式 / 高级）
  U2 点导航切页：stack 索引跟着变，页标题跟着变
  U3 卡片走 objectName=settingsCard，样式统一来自 SETTINGS_QSS
  U4 行标题 rowTitle / 说明 rowHint 两级文字，颜色在 SETTINGS_QSS 里定义
  U5 旧控件属性名一个不少（chk_dev / cmb_tier / spin_icon_px …）
  U6 「模式」页承载接管 / 自动克隆 / 自动同步 / 布局下拉
  U7 布局模式下拉初值来自 storage，切换调 window.set_layout_mode
  U8 内容可滚动（无横向滚动条）
  U9 下拉框 / 数字框走 SETTINGS_QSS 的深色规则（不写就黑底黑字）
  U10 翻页方向下拉默认左右（反馈 5），可切上下
  U11 「自动排列图标」开关落在 storage.auto_arrange（反馈 3）
  U12 高度不超过可用屏幕 92%

运行：python tests/test_settings_ui.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QLabel,
                               QPushButton, QScrollArea, QSlider, QSpinBox,
                               QStackedWidget, QWidget, QApplication)

from src import theme
from src.settings_dialog import SettingsDialog
from src.storage import Storage

TMP = Path(tempfile.gettempdir()) / "test_settings_ui.json"
failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


class FakeWindow:
    def __init__(self, storage):
        self.storage = storage
        self.attached = True
        self.mode_calls = []
        self.rebuilt = 0
        self.refreshed = 0

    def rebuild(self, stagger=False):
        self.rebuilt += 1

    def refresh_grid(self):
        self.refreshed += 1

    def apply_native_icons_setting(self):
        pass

    def set_layout_mode(self, mode):
        self.mode_calls.append(mode)
        self.storage.set_setting("layout_mode", mode)


def fresh(mode="grid"):
    if TMP.exists():
        TMP.unlink()
    st = Storage(path=str(TMP))
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["settings"]["layout_mode"] = mode
    st.save()
    return st


def page_widgets(dlg, index):
    """第 index 页里的全部子控件（用于判断某个控件属于哪一页）。"""
    page = dlg.stack.widget(index)
    return {id(w) for w in page.findChildren(QWidget)} if page else set()


def main(app):
    st = fresh("grid")
    fw = FakeWindow(st)
    dlg = SettingsDialog(fw, st, layer=None)

    # ---------- U1 侧栏导航 ----------
    navs = [b for b in dlg.findChildren(QPushButton)
            if b.objectName() == "navItem"]
    check("U1 左侧栏 5 个导航项", len(navs) == 5, "found=%d" % len(navs))
    check("U1 导航文案依次为 通用/外观与图标/布局与网格/模式/高级",
          [b.text() for b in navs]
          == ["通用", "外观与图标", "布局与网格", "模式", "高级"],
          "%s" % [b.text() for b in navs])
    stack = dlg.findChildren(QStackedWidget)
    check("U1 右栏是 5 页堆栈", len(stack) == 1 and stack[0].count() == 5,
          "stacks=%d" % len(stack))

    # ---------- U2 切页 ----------
    navs[3].click()
    app.processEvents()
    check("U2 点「模式」→ stack 第 3 页",
          dlg.stack.currentIndex() == 3, "idx=%d" % dlg.stack.currentIndex())
    check("U2 页标题跟着变", dlg.lbl_page_title.text() == "模式",
          "%s" % dlg.lbl_page_title.text())
    check("U2 只有当前导航高亮",
          [b.isChecked() for b in navs] == [False, False, False, True, False],
          "%s" % [b.isChecked() for b in navs])
    navs[0].click()
    app.processEvents()

    # ---------- U3 卡片样式统一 ----------
    cards = [c for c in dlg.findChildren(QFrame)
             if c.objectName() == "settingsCard"]
    check("U3 有分组卡片（行式）", len(cards) >= 5, "found=%d" % len(cards))
    check("U3 卡片不再各自写内联 QSS（样式统一来自 SETTINGS_QSS）",
          all(c.styleSheet() == "" for c in cards),
          "inline=%d" % sum(1 for c in cards if c.styleSheet()))
    check("U3 SETTINGS_QSS 定义卡片底与圆角",
          "QFrame#settingsCard" in theme.SETTINGS_QSS
          and "border-radius: 12px" in theme.SETTINGS_QSS)
    check("U3 对话框只挂一份 SETTINGS_QSS",
          dlg.styleSheet() == theme.settings_qss())
    check("U3 下拉箭头走真图（QSS 三角 hack 会渲染成实心块）",
          "QComboBox::down-arrow{image: url(" in theme.settings_qss(),
          "%s" % theme.settings_qss()[-90:])

    # ---------- U4 两级文字 ----------
    titles = [c for c in dlg.findChildren(QLabel)
              if c.objectName() == "rowTitle"]
    hints = [c for c in dlg.findChildren(QLabel)
             if c.objectName() == "rowHint"]
    check("U4 行标题存在", len(titles) >= 8, "found=%d" % len(titles))
    check("U4 每行都有说明文字", len(hints) >= len(titles),
          "titles=%d hints=%d" % (len(titles), len(hints)))
    check("U4 文字颜色由 QSS 提供（不靠内联纯白）",
          all(lb.styleSheet() == "" for lb in titles)
          and "QLabel#rowTitle" in theme.SETTINGS_QSS
          and "QLabel#rowHint" in theme.SETTINGS_QSS)
    check("U4 标题与说明是不同层级（字号/颜色不同）",
          "font-size: 13px" in theme.SETTINGS_QSS
          and "font-size: 11px" in theme.SETTINGS_QSS)

    # ---------- U5 旧控件兼容 ----------
    need = ["chk_autostart", "cmb_tier", "spin_icon_px", "chk_auto_cols",
            "spin_cols", "sld_opacity", "chk_takeover", "chk_autoclone",
            "chk_widgets", "chk_tray", "chk_dev", "btn_rescan", "btn_reset",
            "btn_close", "cmb_layout_mode", "chk_autosync",
            "cmb_page_axis", "chk_auto_arrange", "chk_match_native"]
    missing = [n for n in need if not hasattr(dlg, n)]
    check("U5 旧控件属性名全部保留", not missing, "missing=%s" % missing)
    check("U5 控件类型未被改坏",
          isinstance(dlg.chk_dev, QCheckBox) and isinstance(dlg.cmb_tier, QComboBox)
          and isinstance(dlg.spin_icon_px, QSpinBox)
          and isinstance(dlg.sld_opacity, QSlider))

    # ---------- U6 模式页归属 ----------
    inside = page_widgets(dlg, 3)
    check("U6 接管开关在「模式」页", id(dlg.chk_takeover) in inside)
    check("U6 自动克隆在「模式」页", id(dlg.chk_autoclone) in inside)
    check("U6 自动同步在「模式」页", id(dlg.chk_autosync) in inside)
    check("U6 布局模式下拉在「模式」页", id(dlg.cmb_layout_mode) in inside)

    # ---------- U7 布局模式下拉 ----------
    check("U7 下拉初值 = storage 的 grid",
          dlg.cmb_layout_mode.currentData() == "grid")
    dlg.cmb_layout_mode.setCurrentIndex(dlg.cmb_layout_mode.findData("free"))
    app.processEvents()
    check("U7 切无界 → 调 window.set_layout_mode('free')",
          fw.mode_calls == ["free"], "calls=%s" % fw.mode_calls)
    check("U7 storage 落盘 layout_mode=free",
          st.get_setting("layout_mode") == "free")
    dlg.cmb_layout_mode.setCurrentIndex(dlg.cmb_layout_mode.findData("grid"))
    app.processEvents()

    # ---------- U8 可滚动 ----------
    scrolls = dlg.findChildren(QScrollArea)
    check("U8 每页内容装在可滚动区域", len(scrolls) == 5, "found=%d" % len(scrolls))
    check("U8 滚动区无横向滚动条（宽度自适应）",
          all(s.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
              for s in scrolls))

    # ---------- U9 深色输入控件 ----------
    check("U9 QSS 定义 QComboBox 深色表面",
          "QComboBox{" in theme.SETTINGS_QSS
          and "QComboBox QAbstractItemView" in theme.SETTINGS_QSS
          and "QComboBox::down-arrow" in theme.SETTINGS_QSS)
    check("U9 QSS 定义 QSpinBox 深色表面",
          "QSpinBox{" in theme.SETTINGS_QSS)
    check("U9 QSS 定义主按钮",
          "QPushButton#primaryButton" in theme.SETTINGS_QSS)

    # ---------- U10 翻页方向（反馈 5） ----------
    check("U10 翻页方向默认左右",
          dlg.cmb_page_axis.currentData() == "horizontal",
          "%s" % dlg.cmb_page_axis.currentData())
    dlg.cmb_page_axis.setCurrentIndex(
        dlg.cmb_page_axis.findData("vertical"))
    app.processEvents()
    check("U10 切上下写进 storage",
          st.get_setting("page_axis") == "vertical",
          "%s" % st.get_setting("page_axis"))
    dlg.cmb_page_axis.setCurrentIndex(
        dlg.cmb_page_axis.findData("horizontal"))
    app.processEvents()
    check("U10 切回左右写进 storage",
          st.get_setting("page_axis") == "horizontal",
          "%s" % st.get_setting("page_axis"))

    # ---------- U11 自动排列（反馈 3） ----------
    before = bool(st.get_setting("auto_arrange"))
    dlg.chk_auto_arrange.setChecked(not before)
    app.processEvents()
    check("U11 自动排列开关落 storage.auto_arrange",
          bool(st.get_setting("auto_arrange")) is (not before),
          "%s" % st.get_setting("auto_arrange"))
    dlg.chk_auto_arrange.setChecked(before)
    app.processEvents()

    # ---------- U12 高度受控 ----------
    dlg.show()
    app.processEvents()
    avail = QGuiApplication.primaryScreen().availableGeometry().height()
    check("U12 高度不超过可用屏幕 92%",
          dlg.height() <= int(avail * 0.92) + 2,
          "h=%d avail=%d" % (dlg.height(), avail))
    dlg.hide()
    dlg.deleteLater()

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL settings_ui PASSED")
    return 0


def run_main():
    app = QApplication([])
    try:
        code = main(app)
    except Exception:
        import traceback
        traceback.print_exc()
        failures.append("main() 异常")
        code = 1
    try:
        TMP.unlink()
    except Exception:
        pass
    return code


if __name__ == "__main__":
    sys.exit(run_main())
