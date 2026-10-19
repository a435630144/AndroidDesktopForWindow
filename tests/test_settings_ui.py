# -*- coding: utf-8 -*-
"""v6 §7.3：设置界面配色重设计——分组卡片式（反馈 12）。

规格：分组卡片 = 启动 / 图标与网格 / 模式 / 开发者；主色 ACCENT 蓝，
统一圆角与间距，深色底保持与桌面融合。

  U1 四张分组卡片，标题依次为 启动 / 图标与网格 / 模式 / 开发者
  U2 卡片走统一 objectName + theme.CARD_QSS（圆角取自 RADIUS_CARD）
  U3 卡片标题使用主色 ACCENT（不靠纯白堆砌层级）
  U4 旧控件一个不少（属性名兼容：chk_dev / chk_takeover / cmb_tier …）
  U5 「模式」卡片承载接管开关 + 自动克隆 + 布局模式下拉
  U6 布局模式下拉初值来自 storage，切换调 window.set_layout_mode
  U7 内容可滚动（卡片变多不顶出屏幕），卡片间距统一
  U8 对话框高度不超过可用屏幕 92%

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
                               QScrollArea, QSlider, QSpinBox, QWidget,
                               QApplication)

from src import grid_flow, theme
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

    def rebuild(self, stagger=False):
        self.rebuilt += 1

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


def main(app):
    st = fresh("grid")
    fw = FakeWindow(st)
    dlg = SettingsDialog(fw, st, layer=None)

    # ---------- U1 四张卡片 ----------
    cards = [c for c in dlg.findChildren(QFrame) if c.objectName() == "settingsCard"]
    check("U1 四张分组卡片", len(cards) == 4, "found=%d" % len(cards))
    titles = [c.property("groupTitle") for c in cards]
    check("U1 卡片标题为 启动/图标与网格/模式/开发者",
          titles == ["启动", "图标与网格", "模式", "开发者"], "%s" % titles)

    # ---------- U2 统一卡片样式 ----------
    check("U2 卡片使用 theme.CARD_QSS（圆角 token）",
          all(theme.CARD_QSS in c.styleSheet() for c in cards))
    check("U2 圆角取自 theme.RADIUS_CARD",
          ("%dpx" % theme.RADIUS_CARD) in theme.CARD_QSS)
    check("U2 卡片底为白色低 alpha（深色底透出，与桌面融合）",
          theme.CARD_BG.alpha() < 40 and theme.CARD_BG.red() > 240
          and "rgba(" in theme.CARD_QSS,
          "alpha=%d rgb=%d" % (theme.CARD_BG.alpha(), theme.CARD_BG.red()))

    # ---------- U3 标题主色 ----------
    title_labels = [c for c in dlg.findChildren(QLabel)
                    if c.objectName() == "cardTitle"]
    check("U3 每张卡片都有主色标题", len(title_labels) == 4,
          "found=%d" % len(title_labels))
    check("U3 标题样式含 ACCENT 主色",
          all(theme.rgba(theme.ACCENT) in lb.styleSheet() for lb in title_labels))

    # ---------- U4 旧控件兼容 ----------
    need = ["chk_autostart", "cmb_tier", "spin_icon_px", "chk_auto_cols",
            "spin_cols", "sld_opacity", "chk_takeover", "chk_autoclone",
            "chk_widgets", "chk_tray", "chk_dev", "btn_rescan", "btn_reset",
            "btn_close", "cmb_layout_mode"]
    missing = [n for n in need if not hasattr(dlg, n)]
    check("U4 旧控件属性名全部保留", not missing, "missing=%s" % missing)
    check("U4 控件类型未被改坏",
          isinstance(dlg.chk_dev, QCheckBox) and isinstance(dlg.cmb_tier, QComboBox)
          and isinstance(dlg.spin_icon_px, QSpinBox)
          and isinstance(dlg.sld_opacity, QSlider))

    # ---------- U5 模式卡片内容 ----------
    mode_card = cards[2] if len(cards) == 4 else None
    if mode_card is not None:
        inside = {id(w) for w in mode_card.findChildren(QWidget)}
        check("U5 接管开关在「模式」卡片内", id(dlg.chk_takeover) in inside)
        check("U5 自动克隆在「模式」卡片内", id(dlg.chk_autoclone) in inside)
        check("U5 布局模式下拉在「模式」卡片内", id(dlg.cmb_layout_mode) in inside)

    # ---------- U6 布局模式下拉 ----------
    check("U6 下拉初值 = storage 的 grid",
          dlg.cmb_layout_mode.currentData() == "grid")
    dlg.cmb_layout_mode.setCurrentIndex(dlg.cmb_layout_mode.findData("free"))
    app.processEvents()
    check("U6 切无界 → 调 window.set_layout_mode('free')",
          fw.mode_calls == ["free"], "calls=%s" % fw.mode_calls)
    check("U6 storage 落盘 layout_mode=free",
          st.get_setting("layout_mode") == "free")

    # ---------- U7 可滚动 + 间距 ----------
    scrolls = dlg.findChildren(QScrollArea)
    check("U7 内容装在可滚动区域", len(scrolls) >= 1, "found=%d" % len(scrolls))
    if scrolls:
        check("U7 滚动区无横向滚动条（宽度自适应）",
              scrolls[0].horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff)

    # ---------- U9 下拉框深色（不写 QSS 会回退系统黑底黑字） ----------
    check("U9 下拉框走 theme.COMBO_QSS（深色表面可读）",
          theme.COMBO_QSS in dlg.styleSheet()
          and "QComboBox::down-arrow" in theme.COMBO_QSS
          and "QComboBox QAbstractItemView" in theme.COMBO_QSS)

    # ---------- U8 高度受控 ----------
    dlg.show()
    app.processEvents()
    avail = QGuiApplication.primaryScreen().availableGeometry().height()
    check("U8 高度不超过可用屏幕 92%",
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
