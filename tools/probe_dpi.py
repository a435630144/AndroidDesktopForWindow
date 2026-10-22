# -*- coding: utf-8 -*-
"""DPI 探针（v10 B1，反馈 2 / 15-b 的前置）：只读量两种配置下的几何事实。

病根背景：`icon_chrome_scale = screen_dpr × user_icon_scale` 散在 6 处各自
相乘，而 cell 完全不吃 DPI（`cell_from_native` 只由资源管理器图标边长决定）
→ 125% 缩放下 chrome/cell 比例失衡，表现为文件夹弹窗与 UI 偏大、长按圆圈
过大（反馈 2 / 15-b）。B2「单一旋钮」改法需要两台配置的真实数字对比，
**没有两份数据不动 B2/B3 的码**。

探针铁律（遵守 §7.2）：只读枚举——不建窗口、不动用户桌面、不写真实
state.json（用临时 Storage）、不碰原生桌面图标。

运行（**不要加 QT_QPA_PLATFORM=offscreen**：offscreen 的 devicePixelRatio
恒为 1.0，测出来的不是真机）：
    python tools/probe_dpi.py

需要在两种配置下各跑一次，把完整输出贴回对话：
  ① 1920×1080 @ 100%
  ② 2560×1440 @ 125%（逻辑 2048×1152）

**100% 数据不必改系统缩放**（改完还要注销重登，会中断会话）。两条等效路径都实测过：

路径 A · 进程级 DPI 虚拟化（机器 A / 1920×1080 用这条）——
`SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_UNAWARE)`（=-1）在本进程
导入 PySide6 **之前**调用，进程视图即变为 dpr=1.0。
2026-10-22 实测 wrapper：
    python -c "import ctypes,runpy,sys; \
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-1)); \
sys.argv=['probe_dpi.py']; \
runpy.run_path('tools/probe_dpi.py', run_name='__main__')"
注意：DPI 无感知进程拿到的**逻辑视口不变**（系统按缩放折算物理尺寸给它），
所以它适合做「chrome/cell vs dpr」的 A/B，**不适合**代表真 100% 的几何——
真 1920×1080@100% 的视口是 1920×1080（22×10），这条路径给的是 1536×864（17×9）。

路径 B · 缩放乘数（机器 B / 2560×1440 用这条）——
    QT_SCALE_FACTOR=<1/dpr>  python tools/probe_dpi.py       # 125% → 0.8
它乘在系统 dpr 上，**不是**"设成 100%"的开关：设 `1.0` 等于不设（dpr 仍报系统值，
别据此得出"无效"的结论）；要回到 100% 必须设 `1/dpr`。
另：`QT_SCREEN_SCALE_FACTORS=1` 在 Qt6/Windows 下**不覆盖**系统 DPI，实测输出与基线逐字相同。

**已采数据（2026-10-22，两台机器四格全实测）** —— 完整矩阵见
`docs/实施计划_v10.md` §B1「B1 实测矩阵」：

  机器 A（1920×1080 面板）  125% 真机 / 100% DPI 无感知视图  → 比 1.25 / 1.00
  机器 B（2560×1440 面板）  125% 真机 / 100% QT_SCALE_FACTOR=0.8 → 比 1.25 / 1.00
  → **chrome/cell 比 == dpr**，与分辨率无关；`cell` 四格恒为 84×91 逻辑。
    徽标物理 17→26（+53%，dpr²）而 cell 物理 84→105（+25%，dpr¹）
    —— 内层比外层涨得快，就是"长按圆圈变得很大"的量化来源（B2 要收敛它）。
  另一条 B1 顺带发现：`MAX_COLS=24 / MAX_ROWS=12` 在 2560×1440@100% 会夹紧
    （自然需求 29×14 → 24×12），100% 的大屏反而铺不满。
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QGuiApplication      # noqa: E402
from PySide6.QtWidgets import QApplication     # noqa: E402

from src import grid_metrics, grid_sizing, theme   # noqa: E402
from src.folder_popup import popup_metrics     # noqa: E402
from src.storage import Storage                # noqa: E402
from src import win32_layer                     # noqa: E402

STATE = Path(tempfile.gettempdir()) / "probe_dpi_state.json"


def fresh_storage():
    """临时 Storage：默认设置即目标形态（match_native 开 / icon_scale 1.0）。"""
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st.save()
    return st


def main(app):
    scr = QGuiApplication.primaryScreen()
    dpr = theme.screen_dpr()
    logical = scr.size()
    physical = scr.size() * scr.devicePixelRatio()
    avail = scr.availableGeometry()
    print("=" * 64)
    print("DPI 探针（v10 B1）  %s" % scr.name())
    print("=" * 64)
    print("屏幕 logical   : %d × %d" % (logical.width(), logical.height()))
    print("屏幕 physical  : %d × %d" % (physical.width(), physical.height()))
    print("availableGeometry: %d × %d（任务栏已扣）"
          % (avail.width(), avail.height()))
    print("devicePixelRatio: %.4f（theme.screen_dpr 同值）" % dpr)
    print("逻辑 dpi       : %.1f" % scr.logicalDotsPerInch())
    print("物理 dpi       : %.1f" % scr.physicalDotsPerInch())

    st = fresh_storage()
    user_scale = st.user_icon_scale()
    chrome = st.icon_chrome_scale()
    print("-" * 64)
    print("user_icon_scale: %.4f（settings icon_scale，夹 0.6~2.0）" % user_scale)
    print("chrome_scale   : %.4f = dpr %.4f × user %.4f"
          % (chrome, dpr, user_scale))
    print("  ↑ AppIcon._m 用它（chrome 的唯一乘数）；**cell 不吃这个 scale**")

    native = win32_layer.native_icon_size()
    print("-" * 64)
    print("注册表原生图标 : %d px（逻辑；physical %d）"
          % (native, round(native * dpr)))

    cw, ch = grid_sizing.cell_from_native(native)
    print("cell_from_native: %d × %d（逻辑；physical %d × %d）"
          % (cw, ch, round(cw * dpr), round(ch * dpr)))

    m = grid_metrics.compute(st, (avail.width(), avail.height()),
                             native_px=native)
    print("grid_metrics   : cols=%d rows=%d cw=%d ch=%d ox=%d oy=%d"
          % (m.cols, m.rows, m.cw, m.ch, m.ox, m.oy))
    lay = grid_sizing.icon_layout(m.cw, m.ch, "medium")
    print("icon_layout    : icon_box=%d（逻辑；physical %d）"
          % (lay.icon_box, round(lay.icon_box * dpr)))

    print("-" * 64)
    # 长按徽标（反馈 15-b）：d = max(16, round(17 * _m))，_m = chrome_scale
    d_badge = max(16, int(round(17 * chrome)))
    print("长按徽标直径   : %d px（逻辑；physical %d）  [17×chrome_scale]"
          % (d_badge, round(d_badge * dpr)))

    # 文件夹弹窗（反馈 2）：cell_w 只吃逻辑值，chrome 侧却乘了 dpr
    pm = popup_metrics(m.cw, n_members=9, avail_h=avail.height())
    print("popup_metrics(9): w=%d h=%d icon=%d cols=%d rows=%d"
          % (pm["width"], pm["height"], pm["icon"], pm["cols"], pm["rows"]))
    print("                  physical w=%d h=%d icon=%d"
          % (round(pm["width"] * dpr), round(pm["height"] * dpr),
             round(pm["icon"] * dpr)))

    print("-" * 64)
    print("chrome/cell 比 : %.4f（cell 的等效 scale 恒为 1.0；B2 要让这个数收敛）"
          % chrome)
    print("  参考：100% 配置应约为 1.00；125% 配置应约为 1.25——若显著偏离，"
          "说明还有第三处暗乘")
    print("=" * 64)
    print("把本段完整输出贴回对话（含两种配置各一份）。")
    return 0


if __name__ == "__main__":
    app = QApplication(sys.argv)
    sys.exit(main(app))
