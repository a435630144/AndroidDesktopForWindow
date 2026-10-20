# -*- coding: utf-8 -*-
"""开发者模式：设置开关（默认关）+ 网格可视化边框（绘制级断言）。

需求（2026-10-18 用户）：开发期默认开启；设置里可开关；开启时给网格
边缘渲染可视化边框，供排查布局问题。
**2026-10-19 改为默认关闭**：满屏调试网格盖在壁纸上，用户误以为
"桌面被覆盖/壁纸丢了"。排查布局时从右键「查看 ▸ 显示网格调试信息」开。

运行：python tests/test_dev_mode.py   （offscreen，无需显示桌面）

覆盖（先 Red 后 Green）：
  D1 DEFAULT_SETTINGS["dev_mode"] 默认 False（2026-10-19 起默认关，避免盖住壁纸）
  D2 get/set_setting 往返 + 落盘重载
  D3 旧 state.json 无 dev_mode 键 -> 回退默认 False（向后兼容）
  D4 dev_mode 开 -> render 后网格边界/内线/原点十字/信息文字可见
     （像素级断言：同步 render 到 QImage 取样——Qt 吞 paintEvent
      异常的盲区见 DEVLOG 6.2 A3 / 坑表 #24）
  D5 dev_mode 关 -> 同区域无调试色（不画）
  D6 设置对话框：chk_dev 初始态同步 + 勾选落 setting + 触发重绘
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.desktop_window import DesktopWindow
from src.settings_dialog import SettingsDialog
from src.storage import DEFAULT_SETTINGS, Storage

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_devmode_state.json"

# 调试色签名（相对式：绿显著占优于红/蓝——对半透明叠在深色底上的混合色
# 同样稳健；与主题色错开：ACCENT=(76,194,255) 的 b 远高于 g 不撞签名）
DBG_GREEN = (0, 255, 170)    # 网格线 / 信息文字
DBG_PINK = (255, 64, 160)    # 原点十字

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def make_state(dev=True, native=True):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = native   # 整理模式
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["settings"]["dev_mode"] = dev
    st._data["layout"] = []
    st.save()
    return st


def _is_green(px: QColor) -> bool:
    return (px.green() > 90 and px.green() - px.red() > 50
            and px.green() - px.blue() > 30)


def _is_pink(px: QColor) -> bool:
    return px.red() > 200 and px.blue() > 100 and px.green() < 120


def _count(img: QImage, x0, y0, x1, y1, pred) -> int:
    n = 0
    for yy in range(max(0, y0), min(img.height(), y1)):
        for xx in range(max(0, x0), min(img.width(), x1)):
            if pred(img.pixelColor(xx, yy)):
                n += 1
    return n


def render_window(w: DesktopWindow) -> QImage:
    img = QImage(w.size(), QImage.Format_ARGB32)
    img.fill(0)
    w.render(img)  # QImage 即 QPaintDevice；同步触发 paintEvent
    return img


def main(app):
    # ---------- D1：默认开启 ----------
    check("D1 DEFAULT_SETTINGS dev_mode 默认 False（不盖壁纸）",
          DEFAULT_SETTINGS.get("dev_mode") is False)

    # ---------- D2：读写往返 + 落盘 ----------
    st = make_state(dev=True)
    st.set_setting("dev_mode", False)
    st2 = Storage(path=str(STATE))
    check("D2 set_setting 落盘重载读回 False",
          st2.get_setting("dev_mode") is False)

    # ---------- D3：旧 state 无键回退默认 ----------
    st3 = make_state(dev=True)
    del st3._data["settings"]["dev_mode"]
    st3.save()
    st4 = Storage(path=str(STATE))
    check("D3 旧 state 无 dev_mode 键回退 False",
          st4.get_setting("dev_mode") is False)

    # ---------- D4：dev_mode 开 -> 网格可视化可见 ----------
    st = make_state(dev=True, native=True)
    w = DesktopWindow(st)
    w.resize(W, H)
    w._update_grid_metrics()
    img = render_window(w)
    m = grid_flow.current_metrics()
    check("D4 GridMetrics 快照就绪", m is not None and m.cols >= 2 and m.rows >= 1,
          "metrics=%s" % (m,))
    mid_x = m.ox + m.cols * m.cw // 2
    regions = {
        "上边缘": (mid_x - 40, m.oy - 2, mid_x + 40, m.oy + 4),
        "左边缘": (m.ox - 2, m.oy + 20, m.ox + 4, m.oy + 90),
        "内竖线": (m.ox + 3 * m.cw - 2, m.oy + m.ch, m.ox + 3 * m.cw + 3, m.oy + 2 * m.ch),
        "内横线": (m.ox + m.cw, m.oy + 2 * m.ch - 2, m.ox + 2 * m.cw, m.oy + 2 * m.ch + 3),
        "信息文字": (m.ox + 4, m.oy + 6, m.ox + 200, m.oy + 30),
    }
    for name, (x0, y0, x1, y1) in regions.items():
        n = _count(img, x0, y0, x1, y1, _is_green)
        check("D4 %s有调试色" % name, n > 0, "green_px=%d" % n)
    n = _count(img, m.ox - 4, m.oy - 4, m.ox + 6, m.oy + 6, _is_pink)
    check("D4 原点十字有调试色", n > 0, "pink_px=%d" % n)

    # ---------- D5：dev_mode 关 -> 同区域无调试色 ----------
    st = make_state(dev=False, native=True)
    w2 = DesktopWindow(st)
    w2.resize(W, H)
    w2._update_grid_metrics()
    img2 = render_window(w2)
    m2 = grid_flow.current_metrics()
    mid2 = m2.ox + m2.cols * m2.cw // 2
    regions2 = {
        "上边缘": (mid2 - 40, m2.oy - 2, mid2 + 40, m2.oy + 4),
        "左边缘": (m2.ox - 2, m2.oy + 20, m2.ox + 4, m2.oy + 90),
        "内竖线": (m2.ox + 3 * m2.cw - 2, m2.oy + m2.ch, m2.ox + 3 * m2.cw + 3, m2.oy + 2 * m2.ch),
        "内横线": (m2.ox + m2.cw, m2.oy + 2 * m2.ch - 2, m2.ox + 2 * m2.cw, m2.oy + 2 * m2.ch + 3),
        "信息文字": (m2.ox + 4, m2.oy + 6, m2.ox + 200, m2.oy + 30),
        "原点": (m2.ox - 4, m2.oy - 4, m2.ox + 6, m2.oy + 6),
    }
    for name, (x0, y0, x1, y1) in regions2.items():
        ng = _count(img2, x0, y0, x1, y1, _is_green)
        np_ = _count(img2, x0, y0, x1, y1, _is_pink)
        check("D5 %s无调试色" % name, ng == 0 and np_ == 0,
              "green=%d pink=%d" % (ng, np_))

    # ---------- D6：设置对话框开关 ----------
    st = make_state(dev=True, native=True)
    fake = SimpleNamespace(updates=0, rebuilds=0)

    def _upd():
        fake.updates += 1

    def _rb():
        fake.rebuilds += 1

    fake.update = _upd
    fake.rebuild = _rb
    dlg = SettingsDialog(fake, st, None)
    check("D6 chk_dev 初始态同步 storage（默认开）",
          dlg.chk_dev.isChecked() is True)
    dlg.chk_dev.setChecked(False)
    check("D6 取消勾选落 setting", st.get_setting("dev_mode") is False)
    check("D6 取消勾选触发窗口重绘", fake.updates >= 1, "updates=%d" % fake.updates)
    dlg.chk_dev.setChecked(True)
    check("D6 重新勾选落 setting", st.get_setting("dev_mode") is True)
    check("D6 重新勾选再次触发重绘", fake.updates >= 2, "updates=%d" % fake.updates)

    # ---------- D7：auto 列数不再崩设置窗口（M1 遗留 int("auto")） ----------
    st = make_state(dev=True, native=True)   # columns 保持默认 "auto"
    fake2 = SimpleNamespace(updates=0, rebuilds=0)
    fake2.update = lambda: None
    fake2.rebuild = lambda: None
    dlg2 = SettingsDialog(fake2, st, None)   # 旧代码在此 int("auto") 崩
    check("D7 auto 列数下对话框可打开且复选框勾选",
          dlg2.chk_auto_cols.isChecked() is True)
    check("D7 auto 态 spin 禁用（只展示生效列数）",
          dlg2.spin_cols.isEnabled() is False)
    dlg2.chk_auto_cols.setChecked(False)
    # v7 §10.3：列数的权威键是 grid_cols（int）+ grid_dims_mode="manual"
    check("D7 取消 auto 写手动列数（grid_cols int / mode manual）",
          isinstance(st.get_setting("grid_cols"), int)
          and st.grid_dims_mode() == "manual",
          "grid_cols=%s mode=%s" % (st.get_setting("grid_cols"),
                                    st.grid_dims_mode()))
    check("D7 取消 auto 后 spin 可用", dlg2.spin_cols.isEnabled() is True)
    dlg2.chk_auto_cols.setChecked(True)
    check("D7 勾选 auto 写回 auto 模式",
          st.grid_dims_mode() == "auto", st.grid_dims_mode())
    check("D7 勾选 auto 后 spin 重新禁用",
          dlg2.spin_cols.isEnabled() is False)

    print()
    if failures:
        print("==== test_dev_mode: %d 项失败: %s" % (len(failures), failures))
        return 1
    print("==== ALL dev_mode PASSED")
    return 0


if __name__ == "__main__":
    app = QApplication(sys.argv)
    sys.exit(main(app))
