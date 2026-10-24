# -*- coding: utf-8 -*-
"""v14 反馈 9：液态玻璃（Liquid Glass）效果。

公开实现共识（CSS/SVG 生态：feTurbulence + feDisplacementMap + 分层
backdrop-filter）：液态玻璃 = 半透明底 + 折射 + 色散边缘 + 镜面高光 +
流动微动效。Qt 无 per-pixel shader，本实现用「渐变透镜边 + 色散细线 +
噪声颗粒 + 缓慢扫光」在既有玻璃之上叠加（`paint_overlay`），三个表面
（文件夹弹窗 / Dock 栏 / 小组件背景）各有一个开关。

  L1-L4  参数纯函数（默认全开 / 表面开关 / 总开关 / 夹紧回退）
  L5-L10 绘制不抛与像素判据（色散冷边 / 透镜增亮 / 扫光相位 / 减动效）
  S1-S3  设置 ▸ 外观分页（控件齐全 / 写设置触发重绘 / 重置）
  R1-R4  绘制接线（widget / dock / folder 三表面消费 overlay）

运行：python tests/test_liquid_glass.py   （offscreen；判据看退出码）
"""
import gc
import os
import sys
import tempfile
import weakref
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.storage import Storage  # noqa: E402

failures = []
total = [0]


def check(name, cond, extra=""):
    total[0] += 1
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def _st(name="state.json"):
    tmp = Path(tempfile.mkdtemp())
    return Storage(path=tmp / name)


def _canvas(w, h, bg=None):
    img = QImage(int(w), int(h), QImage.Format_ARGB32)
    img.fill(bg if bg is not None else 0)
    return img


def _folder_state(name, liquid=None):
    st = _st(name)
    st.layout.append({"id": "f1", "type": "folder", "col": 0, "row": 0,
                      "page": 0, "name": "F",
                      "app": {"name": "F", "target": "F", "kind": "app"},
                      "apps": [{"name": "m1", "target": "m1", "kind": "app"}]})
    if liquid is not None:
        st.set_setting("liquid_folder", liquid)
    return st


def main(app):
    from src import liquid_glass as lg

    # ---------- L1 默认：三个表面全开 ----------
    st = _st()
    check("L1 总开关默认开", st.get_setting("liquid_glass") is True)
    for surface in ("folder", "dock", "widget"):
        check("L1%s 默认 %s 表面开" % (surface[0], surface),
              lg.surface_enabled(st, surface) is True)
    s = lg.liquid_style(st)
    check("L1d 默认色散强度 60", s.dispersion == 0.6, str(s.dispersion))
    check("L1e 默认透镜边缘 60", s.bezel == 0.6, str(s.bezel))
    check("L1f 默认噪声 40", s.noise == 0.4, str(s.noise))
    check("L1g 默认流动高光开", s.shimmer is True)

    # ---------- L2 表面开关独立 ----------
    st2 = _st()
    st2.set_setting("liquid_dock", False)
    check("L2 关 dock 只关 dock",
          lg.surface_enabled(st2, "dock") is False
          and lg.surface_enabled(st2, "folder") is True
          and lg.surface_enabled(st2, "widget") is True)

    # ---------- L3 总开关一票否决 ----------
    st3 = _st()
    st3.set_setting("liquid_glass", False)
    check("L3 总开关关 -> 三个表面全关",
          not any(lg.surface_enabled(st3, s_) for s_ in
                  ("folder", "dock", "widget")))

    # ---------- L4 强度夹紧 + 脏值回退 ----------
    st4 = _st()
    st4.set_setting("liquid_dispersion", 999)
    st4.set_setting("liquid_bezel", -5)
    st4.set_setting("liquid_noise", "abc")
    st4.set_setting("liquid_shimmer", "false")     # bool("false") 是 True 的坑
    s4 = lg.liquid_style(st4)
    check("L4 色散夹紧到 1.0", s4.dispersion == 1.0, str(s4.dispersion))
    check("L4b 透镜夹紧到 0.0", s4.bezel == 0.0, str(s4.bezel))
    check("L4c 噪声脏值回退默认 0.4", s4.noise == 0.4, str(s4.noise))
    check("L4d 字符串 'false' 不当真（_flag 铁律）", s4.shimmer is False)

    # ---------- L5 各尺寸不抛 ----------
    img = _canvas(200, 120)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    ok = True
    try:
        for r in (0, 4, 20, 500):
            lg.paint_overlay(p, QRectF(0, 0, 200, 120), r, s)
        lg.paint_overlay(p, QRectF(0, 0, 1, 1), 0, s)          # 极小
        lg.paint_overlay(p, QRectF(0, 0, 0, 0), 0, s)          # 空
    except Exception as exc:                                   # noqa: BLE001
        ok = False
        print("   paint_overlay 抛异常: %r" % exc)
    p.end()
    check("L5 paint_overlay 各尺寸/半径不抛", ok)

    # ---------- L6 色散：开液态后边缘出现冷调（b-r 升高） ----------
    def _edge_shift(style):
        im = _canvas(160, 100, QColor(128, 128, 128).rgb())
        pp = QPainter(im)
        lg.paint_overlay(pp, QRectF(0, 0, 160, 100), 16, style)
        pp.end()
        c = im.pixelColor(80, 2)          # 顶边色散线所在行
        return c.blue() - c.red()

    off = lg.LiquidStyle(dispersion=0.0, bezel=0.0, noise=0.0, shimmer=False)
    on = lg.LiquidStyle(dispersion=1.0, bezel=0.0, noise=0.0, shimmer=False)
    d_off, d_on = _edge_shift(off), _edge_shift(on)
    check("L6 色散开启 -> 顶边冷调（蓝 > 红）", d_on > d_off + 2,
          "off=%d on=%d" % (d_off, d_on))

    # ---------- L7 透镜边缘：开液态后边缘带整体增亮 ----------
    def _edge_luma(style):
        im = _canvas(160, 100, QColor(60, 60, 60).rgb())
        pp = QPainter(im)
        lg.paint_overlay(pp, QRectF(0, 0, 160, 100), 16, style)
        pp.end()
        tot, n = 0.0, 0
        for yy in range(0, 6):
            for xx in range(20, 140):
                c = im.pixelColor(xx, yy)
                tot += (c.red() + c.green() + c.blue()) / 3.0
                n += 1
        return tot / max(1, n)

    l_off = _edge_luma(lg.LiquidStyle(0.0, 0.0, 0.0, False))
    l_on = _edge_luma(lg.LiquidStyle(0.0, 1.0, 0.0, False))
    check("L7 透镜边缘开启 -> 顶边增亮（fresnel 反光）",
          l_on > l_off + 3, "off=%.1f on=%.1f" % (l_off, l_on))

    # ---------- L8 扫光：相位推进改变像素；全零样式静态不画 ----------
    def _shimmer_px(phase, style=None, x=120):
        im = _canvas(160, 100, QColor(60, 60, 60).rgb())
        pp = QPainter(im)
        stl = style or lg.LiquidStyle(0.0, 0.0, 0.0, True)
        lg.paint_overlay(pp, QRectF(0, 0, 160, 100), 16, stl, phase=phase)
        pp.end()
        return im.pixelColor(x, 50).rgb()

    zero = lg.LiquidStyle(0.0, 0.0, 0.0, False)
    # 采样点 x=120：phase 0.5 时高光带中心正落在那里（0 时整条在界外）
    check("L8 扫光相位 0 与 0.5 像素不同",
          _shimmer_px(0.0) != _shimmer_px(0.5),
          "%s vs %s" % (_shimmer_px(0.0), _shimmer_px(0.5)))
    check("L8b 全零样式 + 静态相位不画任何东西",
          _shimmer_px(None, zero, x=80) == QColor(60, 60, 60).rgb(),
          str(_shimmer_px(None, zero, x=80)))

    # ---------- L9 shimmer_phase 减动效时 None ----------
    from src import effects
    effects._rm_cache = True
    check("L9 reduced_motion -> shimmer_phase() 为 None",
          lg.shimmer_phase() is None)
    effects._rm_cache = False
    ph = lg.shimmer_phase()
    check("L9b 正常 -> shimmer_phase() 落在 [0,1)",
          ph is not None and 0 <= ph < 1, str(ph))
    effects._rm_cache = None

    # ---------- L10 挂载表：幂等 + 弱引用不泄漏 ----------
    class _W:
        def update(self):
            pass

    w = _W()
    lg.attach(w)
    lg.attach(w)
    check("L10 attach 幂等", len(lg._surfaces()) == 1, str(len(lg._surfaces())))
    lg.detach(w)
    check("L10b detach 移除", len(lg._surfaces()) == 0)
    wr = weakref.ref(w)
    lg.attach(w)
    del w
    gc.collect()
    check("L10c 弱引用：对象销毁后不泄漏",
          wr() is None and len(lg._surfaces()) == 0,
          "alive=%s n=%d" % (wr() is not None, len(lg._surfaces())))

    # ---------- S1-S3 设置分页 ----------
    from src import settings_dialog

    class FakeWin:
        def __init__(self):
            self.calls = 0

        def apply_liquid_style(self):
            self.calls += 1

    fw = FakeWin()
    st5 = _st("settings.json")
    dlg = None
    try:
        dlg = settings_dialog.SettingsDialog(fw, st5, None, page="appearance")
    except Exception as exc:      # noqa: BLE001
        check("S1 设置窗可构造", False, repr(exc))
    names = ("chk_liquid", "chk_liquid_folder", "chk_liquid_dock",
             "chk_liquid_widget", "sld_liquid_dispersion", "sld_liquid_bezel",
             "sld_liquid_noise", "chk_liquid_shimmer")
    if dlg is not None:
        missing = [n for n in names if not hasattr(dlg, n)]
        check("S1 外观页液态玻璃控件齐全", not missing, str(missing))
        if not missing:
            check("S1b 初值读自设置",
                  dlg.chk_liquid.isChecked() is True
                  and dlg.sld_liquid_dispersion.value() == 60)
            before = fw.calls
            dlg.chk_liquid_dock.setChecked(False)
            check("S2 改表面开关 -> 写设置 + 触发重绘",
                  st5.get_setting("liquid_dock") is False and fw.calls > before,
                  "calls=%d" % fw.calls)
            dlg.sld_liquid_noise.setValue(20)
            check("S2b 强度滑条写设置",
                  st5.get_setting("liquid_noise") == 20,
                  str(st5.get_setting("liquid_noise")))
            dlg._reset_liquid()
            check("S3 恢复默认回写设置",
                  st5.get_setting("liquid_dock") is True
                  and st5.get_setting("liquid_dispersion") == 60
                  and st5.get_setting("liquid_noise") == 40
                  and st5.get_setting("liquid_shimmer") is True,
                  "disp=%s noise=%s" % (st5.get_setting("liquid_dispersion"),
                                        st5.get_setting("liquid_noise")))
        dlg.deleteLater()

    # ---------- R1 接线：小组件背景 ----------
    from src import widget_glass

    class _Probe(widget_glass.GlassWidget):
        def paint_content(self, p):
            pass

    entry = {"id": "p1", "kind": "probe", "span": (2, 2), "settings": {}}
    orig_overlay = lg.paint_overlay

    def _render(widget, w, h):
        hits = []
        lg.paint_overlay = lambda p, rect, radius, style, phase=None, \
            widget=None: (hits.append(widget),
                          orig_overlay(p, rect, radius, style,
                                       phase=phase, widget=widget))[1]
        try:
            widget.render(_canvas(w, h))
        finally:
            lg.paint_overlay = orig_overlay
        return hits

    probe = _Probe(_st(), entry)
    probe.resize(120, 120)
    hits = _render(probe, 120, 120)
    check("R1 小组件开启时绘制 overlay", len(hits) >= 1, str(len(hits)))
    probe.close()

    st_widget_off = _st()
    st_widget_off.set_setting("liquid_widget", False)
    probe2 = _Probe(st_widget_off, entry)
    probe2.resize(120, 120)
    hits2 = _render(probe2, 120, 120)
    check("R1b 组件开关关闭 -> 不画 overlay", not hits2, str(len(hits2)))
    probe2.close()

    # ---------- R2 接线：Dock ----------
    from src import dock as dockmod

    d9 = dockmod.DockWindow(_dock_state())
    d9.resize(300, 82)
    hits3 = _render(d9, 300, 82)
    check("R2 Dock 开启时绘制 overlay", len(hits3) >= 1, str(len(hits3)))
    d9.close()

    d10 = dockmod.DockWindow(_dock_state(liquid=False))
    d10.resize(300, 82)
    hits4 = _render(d10, 300, 82)
    check("R2b Dock 开关关闭 -> 不画 overlay", not hits4, str(len(hits4)))
    d10.close()

    # ---------- R3 接线：文件夹弹窗 ----------
    from src.folder_popup import FolderPopup

    st11 = _folder_state("pop.json")
    popup = FolderPopup(st11, st11.find_entry("f1"), anchor_rect=None)
    popup.resize(320, 240)
    hits5 = _render(popup, 320, 240)
    check("R3 文件夹弹窗开启时绘制 overlay", len(hits5) >= 1, str(len(hits5)))
    popup.close()

    st12 = _folder_state("pop2.json", liquid=False)
    popup2 = FolderPopup(st12, st12.find_entry("f1"), anchor_rect=None)
    popup2.resize(320, 240)
    hits6 = _render(popup2, 320, 240)
    check("R3b 文件夹开关关闭 -> 不画 overlay", not hits6, str(len(hits6)))
    popup2.close()

    # ---------- R4 总开关关闭 -> 不画 ----------
    st13 = _st()
    st13.set_setting("liquid_glass", False)
    st13.set_setting("dock_items", [])
    d13 = dockmod.DockWindow(st13)
    d13.resize(300, 82)
    hits7 = _render(d13, 300, 82)
    check("R4 总开关关 -> Dock 不画 overlay", not hits7, str(len(hits7)))
    d13.close()


def _dock_state(liquid=True):
    st = _st()
    st.set_setting("dock_items", [])
    if not liquid:
        st.set_setting("liquid_dock", False)
    return st


if __name__ == "__main__":
    _app = QApplication.instance() or QApplication([])
    main(_app)
    print("-" * 56)
    print("%d/%d checks, %d FAIL" % (total[0] - len(failures), total[0],
                                     len(failures)))
    for f in failures:
        print("  FAILED:", f)
    sys.exit(1 if failures else 0)
