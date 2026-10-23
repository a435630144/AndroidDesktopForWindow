# -*- coding: utf-8 -*-
"""开发者模式：设置开关（默认关）+ 网格可视化边框（绘制级断言）。

需求（2026-10-18 用户）：开发期默认开启；设置里可开关；开启时给网格
边缘渲染可视化边框，供排查布局问题。
**2026-10-19 改为默认关闭**：满屏调试网格盖在壁纸上，用户误以为
"桌面被覆盖/壁纸丢了"。排查布局时从 设置 ▸ 高级 ▸ 开发者调试 开。
**2026-10-20 反馈 4**：桌面右键「查看 ▸ 显示网格调试信息」已移除——
调试信息属于开发者功能，入口只留设置面板（D8 锁住，防回潮）。

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
  D8 桌面右键「查看」菜单**不含**该项（反馈 4），设置页仍是唯一入口
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


def _is_debug_red(px: QColor) -> bool:
    """调试红底签名：红显著占优于绿/蓝（25% 红叠深/浅底都成立）。"""
    return (px.red() > 90 and px.red() - px.green() > 25
            and px.red() - px.blue() > 15)


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

    # ---------- D9：v10 A2（反馈 3）安装后不默认开调试网格 ----------
    # 场景：用户在旧版里手动开过 dev_mode，state.json 里留着 True；覆盖安装
    # 不清 %APPDATA% 数据，于是新版"继承"了调试网格。首次加载一次性关掉。
    st9 = make_state(dev=True)          # 落盘 dev_mode=True（旧版遗留形态）
    st9b = Storage(path=str(STATE))     # 模拟新版首次启动
    check("D9a 首次加载把遗留的 dev_mode 关掉",
          st9b.get_setting("dev_mode") is False)
    check("D9b 一次性标记已落 setting",
          st9b.get_setting("dev_mode_v10_reset") is True)
    st9b.save()
    st9c = Storage(path=str(STATE))     # 第二次启动：标记在，不再动
    check("D9c 二次启动不重复覆盖",
          st9c.get_setting("dev_mode") is False)
    st9c.set_setting("dev_mode", True)  # 用户仍可手动开
    st9c.save()
    check("D9d 手动开启仍然有效",
          Storage(path=str(STATE)).get_setting("dev_mode") is True)

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

    # ---------- D10/D11：组件碰撞体积可视化（v10 反馈 26） ----------
    # 用户要的是"能看见组件占了哪块地"：组件卡片按 fill 居中缩小，四周留缝，
    # 缝隙到底算不算组件领地、命中有没有偏差——调试模式用半透明红底把
    # **span 盒**（碰撞/占位的唯一形状，见 widget_geom 模块头）画出来。
    def _mk_widget_state(dev):
        s = make_state(dev=dev, native=True)
        s._data["widgets"] = [{"id": "wm1", "type": "monitor", "hidden": False,
                               "anchored": True, "col": 0, "row": 0,
                               "colspan": 2, "rowspan": 2}]
        s.save()
        return s

    from src import widget_geom

    st10 = _mk_widget_state(True)
    w10 = DesktopWindow(st10)
    w10.resize(W, H)
    w10._update_grid_metrics()
    rects10 = w10._widget_collision_rects()
    check("D10a 有组件的碰撞矩形（1 个组件）", len(rects10) == 1, "n=%d" % len(rects10))
    if rects10:
        r10, span10 = rects10[0]
        bw10, bh10 = widget_geom.span_box(st10, span10)
        check("D10b 碰撞盒 = 跨度 × 格子（不是卡片尺寸）",
              r10.width() == bw10 and r10.height() == bh10,
              "%dx%d vs %dx%d" % (r10.width(), r10.height(), bw10, bh10))
        cx10, cy10 = grid_flow.cell_pos(st10, 0, 0)
        check("D10c 碰撞盒贴合格点原点",
              r10.x() == cx10 and r10.y() == cy10,
              "(%d,%d) vs (%d,%d)" % (r10.x(), r10.y(), cx10, cy10))
        img10 = render_window(w10)
        n10 = _count(img10, r10.x() + 3, r10.y() + 3,
                     r10.right() - 3, r10.bottom() - 3, _is_debug_red)
        check("D10d 碰撞盒内有红色半透明底", n10 > 200, "red_px=%d" % n10)
    w10.close()

    st11 = _mk_widget_state(False)
    w11 = DesktopWindow(st11)
    w11.resize(W, H)
    w11._update_grid_metrics()
    r11, _sp11 = w11._widget_collision_rects()[0]
    img11 = render_window(w11)
    n11 = _count(img11, r11.x() + 3, r11.y() + 3,
                 r11.right() - 3, r11.bottom() - 3, _is_debug_red)
    check("D11 dev_mode 关闭时不画红底（相对判据）",
          n11 * 8 < max(1, n10), "off=%d on=%d" % (n11, n10))
    w11.close()

    # ---------- D12：组件真实窗口矩形（v10 反馈 27 盲区诊断） ----------
    # 红底画的是**推算**的 span 盒，窗口才是 Qt 实际摆出来的地。两者不一致
    # （历史 span 残留 / 编辑态外扩没收回 / 悬浮组件）时，多出来的透明区会
    # 吞点击——用户"没有红底却点不动"。D12 锁住：真实窗口能被取到，且与
    # card_size 一致；不一致时调试信息要能报出来。
    from src.widget_layer import WidgetLayer
    st12 = _mk_widget_state(True)
    w12 = DesktopWindow(st12)
    w12.resize(W, H)
    w12._update_grid_metrics()
    layer12 = WidgetLayer(st12)
    w12.set_widget_layer(layer12)
    app.processEvents()
    rows12 = w12._widget_window_rects()
    check("D12a 取到组件真实窗口", len(rows12) == 1, "n=%d" % len(rows12))
    if rows12:
        _wid12, win12, card12, anch12 = rows12[0]
        check("D12b 锚定组件的窗口 == 卡片尺寸",
              win12.width() == card12[0] and win12.height() == card12[1],
              "win=%dx%d card=%dx%d" % (win12.width(), win12.height(),
                                        card12[0], card12[1]))
        check("D12c 是锚定组件", anch12 is True)
        img12 = render_window(w12)
        filled12 = _count(img12, 0, 0, W, H, lambda c: c.alpha() > 0)
        check("D12d 带真实窗口/图标框的调试绘制不抛且非空",
              filled12 > 1000, str(filled12))
    for w_ in list(getattr(layer12, "widgets", {}).values()):
        try:
            w_.close()
        except Exception:      # noqa: BLE001
            pass
    w12.close()

    # ---------- D11：dev_mode 关 -> 同区域无调试色 ----------
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

    # ---------- D8：桌面右键不再是入口（2026-10-20 反馈 4） ----------
    st8 = make_state(dev=False, native=True)     # native -> 整理模式才建菜单
    w8 = DesktopWindow(st8)
    w8.resize(W, H)
    w8._update_grid_metrics()
    menu = w8._build_context_menu()
    # 子菜单是 Python 所有的 QMenu：必须持引用，否则被 GC（DEVLOG 坑 #39）
    subs, view_texts = [], None
    for act in menu.actions():
        sub = act.menu()
        if sub is None:
            continue
        subs.append(sub)
        if sub.title() == "查看":
            view_texts = [x.text() for x in sub.actions()]
    check("D8 右键仍有「查看」菜单", view_texts is not None)
    view_texts = view_texts or []
    check("D8 右键「查看」里没有「显示网格调试信息」",
          "显示网格调试信息" not in view_texts, "%s" % view_texts)
    check("D8 「查看」保留了日常项（图标大小 / 自动排列）",
          any("图标大小" in t for t in view_texts)
          and "自动排列图标" in view_texts, "%s" % view_texts)

    from src.settings_dialog import SettingsDialog as _SD
    fake3 = SimpleNamespace(update=lambda: None, rebuild=lambda: None)
    dlg3 = _SD(fake3, st8, None)
    check("D8 设置面板仍是唯一入口（chk_dev 存在且可切）",
          getattr(dlg3, "chk_dev", None) is not None)
    dlg3.chk_dev.setChecked(True)
    check("D8 设置面板开关落 setting", st8.get_setting("dev_mode") is True)

    print()
    if failures:
        print("==== test_dev_mode: %d 项失败: %s" % (len(failures), failures))
        return 1
    print("==== ALL dev_mode PASSED")
    return 0


if __name__ == "__main__":
    app = QApplication(sys.argv)
    sys.exit(main(app))
