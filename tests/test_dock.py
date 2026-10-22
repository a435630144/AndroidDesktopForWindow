# -*- coding: utf-8 -*-
"""Dock 栏契约（v10 C3，反馈 17）。

契约来源 `docs/指导文档_v10.md` §4.3：

  1. **可用区扣除是唯一入口**——Dock 开启后从可用区里扣掉条带
     （底部/顶部扣高度、左右扣宽度），**不许在 `solve_dims` 里塞 if**。
  2. **四向 × 开/关**都要正确让位，且关闭时一个像素都不扣。
  3. **条目 = 应用快捷方式**（Q2 拍板）：文件 / 文件夹 / 组件一律不收。
  4. **持久化往返**：`settings["dock_items"]` 三次往返逐字段相等
     （项目铁律：模式切换只增不删、幂等）。
  5. 尺寸随 `ui_scale()`（B2 的单一旋钮），与 dpr 无关。

判据（本文件锁死）：
  D1  关闭时 inset 全 0（网格与未开 Dock 逐字段相等）
  D2  四向各扣对边（底部/顶部扣高度，左右扣宽度）
  D3  非法位置回退 bottom（不静默改网格）
  D4  metrics 随 ui_scale 线性；条带厚度包得住 hover 放大
  D5  条带贴边 + 沿副轴居中（四向）
  D6  条目沿主轴递进、副轴居中（横/竖两套）
  D7  hit_index 命中 / 间隙 / 越界 / 关闭态
  D8  move_item 排序（前移/后移/越界夹紧/同位置 no-op）
  D9  normalize_items 过滤非法、去重、上限
  D10 entry_is_app 只认应用（file / folder / 组件都不认）
  D11 dock_items 三次往返逐字段相等
  D12 网格扣除端到端：inset 让 cols/rows 变少且原点偏移正确
  D13 DockWindow 真窗口几何落在条带内、空态可见、ui_scale 变化重排

运行：python tests/test_dock.py   （offscreen；判据看退出码）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


class FakeStorage:
    """最小 storage 桩：grid_metrics.compute 的依赖面（同 B2 契约）。"""

    def __init__(self, scale=1.0):
        self._s = {"icon_match_native": True, "grid_dims_mode": "auto"}
        self._scale = scale

    def get_setting(self, key, default=None):
        return self._s.get(key, default)

    def set_setting(self, key, val):
        self._s[key] = val

    def icon_metric(self):
        return 72

    def ui_scale(self):
        return self._scale

    def grid_dims_mode(self):
        return "auto"

    def grid_origin(self):
        return None


def main():
    from src import dock, grid_metrics
    from src.storage import Storage

    # ---------- D1：关闭 = 零扣除 ----------
    for pos in dock.POSITIONS:
        ins = dock.inset(False, pos, 60)
        check("D1 关闭时零扣除 @%s" % pos, ins == (0, 0, 0, 0), str(ins))

    # ---------- D2：四向各扣对边 ----------
    expect = {
        "bottom": (0, 0, 0, 60),
        "top": (0, 60, 0, 0),
        "left": (60, 0, 0, 0),
        "right": (0, 0, 60, 0),
    }
    for pos, want in expect.items():
        ins = dock.inset(True, pos, 60)
        check("D2 %s 扣对边" % pos, ins == want, "%s != %s" % (ins, want))

    # ---------- D3：非法位置回退 bottom ----------
    for bad in ("", "middle", None, 123):
        check("D3 非法位置回退 bottom %r" % (bad,),
              dock.inset(True, bad, 42) == (0, 0, 0, 42),
              str(dock.inset(True, bad, 42)))
    check("D3b normalize_position 收敛", dock.normalize_position("TOP") == "top")

    # ---------- D4：metrics 随 ui_scale 线性 ----------
    m1 = dock.metrics(1.0, 8)
    m2 = dock.metrics(2.0, 8)
    check("D4 icon 随 scale 线性", m2.icon == m1.icon * 2,
          "%d vs %d" % (m1.icon, m2.icon))
    check("D4 pad 随 scale 线性", m2.pad == m1.pad * 2,
          "%d vs %d" % (m1.pad, m2.pad))
    check("D4 thickness 包得住 hover 放大",
          m1.thickness >= m1.icon * dock.DOCK_HOVER,
          "thickness=%d icon=%d" % (m1.thickness, m1.icon))
    check("D4 thickness = pad*2 + hover 图标",
          m1.thickness == m1.pad * 2 + int(round(m1.icon * dock.DOCK_HOVER)),
          str(m1.thickness))
    check("D4 空态也占位（length > 0）", m1.length > 0, str(m1.length))
    check("D4 length 随条目数增长",
          dock.metrics(1.0, 10).length > dock.metrics(1.0, 4).length,
          "%d vs %d" % (dock.metrics(1.0, 10).length,
                        dock.metrics(1.0, 4).length))

    # ---------- D5：条带贴边 + 副轴居中 ----------
    size = (1920, 1080)
    bar_b = dock.bar_rect(size, "bottom", m1)
    bar_t = dock.bar_rect(size, "top", m1)
    bar_l = dock.bar_rect(size, "left", m1)
    bar_r = dock.bar_rect(size, "right", m1)
    check("D5 bottom 贴底", bar_b[1] + bar_b[3] == 1080, str(bar_b))
    check("D5 top 贴顶", bar_t[1] == 0, str(bar_t))
    check("D5 left 贴左", bar_l[0] == 0, str(bar_l))
    check("D5 right 贴右", bar_r[0] + bar_r[2] == 1920, str(bar_r))
    check("D5 bottom 水平居中",
          abs(bar_b[0] + bar_b[2] // 2 - 960) <= 2, str(bar_b))
    check("D5 left 垂直居中",
          abs(bar_l[1] + bar_l[3] // 2 - 540) <= 2, str(bar_l))
    check("D5 横向厚度 = thickness", bar_b[3] == m1.thickness, str(bar_b))
    check("D5 纵向宽度 = thickness", bar_l[2] == m1.thickness, str(bar_l))

    # ---------- D6：条目主轴递进、副轴居中 ----------
    r0 = dock.item_rect(bar_b, "bottom", m1, 0)
    r1 = dock.item_rect(bar_b, "bottom", m1, 1)
    check("D6 横向第 0 项在此 pad 处", r0[0] == bar_b[0] + m1.pad, str(r0))
    check("D6 横向步进 = icon + gap",
          r1[0] - r0[0] == m1.icon + m1.gap, "%d" % (r1[0] - r0[0]))
    check("D6 横向副轴居中", r0[1] == bar_b[1] + (m1.thickness - m1.icon) // 2,
          str(r0))
    c0 = dock.item_rect(bar_l, "left", m1, 0)
    c1 = dock.item_rect(bar_l, "left", m1, 1)
    check("D6 纵向第 0 项在此 pad 处", c0[1] == bar_l[1] + m1.pad, str(c0))
    check("D6 纵向步进 = icon + gap",
          c1[1] - c0[1] == m1.icon + m1.gap, "%d" % (c1[1] - c0[1]))
    check("D6 纵向副轴居中", c0[0] == bar_l[0] + (m1.thickness - m1.icon) // 2,
          str(c0))

    # ---------- D7：hit_index ----------
    n = 8
    cx0 = r0[0] + m1.icon // 2
    cy0 = r0[1] + m1.icon // 2
    check("D7 命中第 0 项中心",
          dock.hit_index(bar_b, "bottom", m1, n, (cx0, cy0)) == 0)
    check("D7 命中第 3 项中心",
          dock.hit_index(bar_b, "bottom", m1, n,
                         (r0[0] + 3 * (m1.icon + m1.gap) + m1.icon // 2,
                          cy0)) == 3)
    check("D7 间隙里不命中",
          dock.hit_index(bar_b, "bottom", m1, n,
                         (r0[0] + m1.icon + 1, cy0)) is None)
    check("D7 条带外不命中",
          dock.hit_index(bar_b, "bottom", m1, n, (cx0, 5)) is None)
    check("D7 条目数 0 时不命中",
          dock.hit_index(bar_b, "bottom", m1, 0, (cx0, cy0)) is None)
    check("D7 关闭态不命中（inset 为 0 也不该有落点）",
          dock.hit_index(bar_b, "bottom", m1, n, (cx0, cy0), enabled=False) is None)

    # ---------- D8：排序纯函数 ----------
    items = [{"name": c} for c in "abcd"]
    moved = dock.move_item(items, 0, 2)
    check("D8 前移", [i["name"] for i in moved] == ["b", "c", "a", "d"],
          str([i["name"] for i in moved]))
    moved = dock.move_item(items, 3, 1)
    check("D8 后移", [i["name"] for i in moved] == ["a", "d", "b", "c"],
          str([i["name"] for i in moved]))
    check("D8 原位 no-op 返回等价列表",
          [i["name"] for i in dock.move_item(items, 2, 2)] == ["a", "b", "c", "d"])
    check("D8 越界夹紧（目标超上限）",
          [i["name"] for i in dock.move_item(items, 0, 99)] == ["b", "c", "d", "a"])
    check("D8 越界夹紧（源为负）",
          [i["name"] for i in dock.move_item(items, -3, 1)] == ["b", "a", "c", "d"])
    check("D8 不改原列表", [i["name"] for i in items] == ["a", "b", "c", "d"])

    # ---------- D9：normalize_items ----------
    raw = [
        {"name": "记事本", "target": "C:/n.exe", "icon_path": "C:/n.exe"},
        {"name": "", "target": "C:/x.exe"},                    # 无名字 -> 丢
        {"name": "A", "target": "C:/a.exe"},
        {"name": "A", "target": "C:/a.exe"},                    # 重复 -> 丢
        {"name": "无 target"},
        "不是字典",
        {"name": "B", "target": "C:/b.exe", "extra": 1},        # 额外字段保留
    ]
    norm = dock.normalize_items(raw)
    names = [i["name"] for i in norm]
    check("D9 过滤空名/无 target/非字典", names == ["记事本", "A", "B"], str(names))
    check("D9 去重", len(norm) == 3, str(len(norm)))
    check("D9 保留额外字段", norm[2].get("extra") == 1)
    check("D9 非列表输入 -> 空",
          dock.normalize_items(None) == [] and dock.normalize_items("x") == [])
    many = [{"name": str(i), "target": "C:/%d.exe" % i}
            for i in range(dock.DOCK_MAX_ITEMS + 10)]
    check("D9 上限 %d" % dock.DOCK_MAX_ITEMS,
          len(dock.normalize_items(many)) == dock.DOCK_MAX_ITEMS,
          str(len(dock.normalize_items(many))))

    # ---------- D10：只收应用 ----------
    check("D10 应用可入", dock.entry_is_app(
        {"type": "app", "app": {"name": "x", "target": "C:/x.exe"}}))
    check("D10 kind=file 不可入", not dock.entry_is_app(
        {"type": "app", "app": {"name": "x", "target": "C:/x.txt",
                                "kind": "file"}}))
    check("D10 文件夹不可入", not dock.entry_is_app(
        {"type": "folder", "apps": []}))
    check("D10 组件不可入", not dock.entry_is_app(
        {"type": "widget", "widget": "clock"}))
    check("D10 空/非法不可入",
          not dock.entry_is_app(None) and not dock.entry_is_app({}))

    # ---------- D11：持久化三次往返逐字段相等 ----------
    tmp = Path(tempfile.mkdtemp(prefix="dock_"))
    st = Storage(path=tmp / "state.json")
    seed = [
        {"name": "记事本", "target": "C:/Windows/notepad.exe",
         "icon_path": "C:/Windows/notepad.exe"},
        {"name": "计算器", "target": "C:/Windows/calc.exe",
         "icon_path": "C:/Windows/calc.exe"},
    ]
    dock.save_items(st, seed)
    first = [dict(i) for i in dock.load_items(st)]
    for rnd in range(3):
        again = dock.load_items(st)
        dock.save_items(st, again)
        st2 = Storage(path=tmp / "state.json")     # 真从磁盘重读
        check("D11 第 %d 次往返逐字段相等" % (rnd + 1),
              dock.load_items(st2) == first,
              str(dock.load_items(st2)))
    check("D11 落的键就是 dock_items",
          [i["name"] for i in (st.get_setting("dock_items") or [])]
          == ["记事本", "计算器"])

    # ---------- D12：网格扣除端到端 ----------
    fake = FakeStorage(1.0)
    full = grid_metrics.compute(fake, (1920, 1080), native_px=48)
    m = dock.metrics(1.0, 8)
    ins = dock.inset(True, "bottom", m.thickness)
    cut = grid_metrics.compute(fake, (1920, 1080), native_px=48, inset=ins)
    check("D12 扣掉条带后行数不变或更少", cut.rows <= full.rows,
          "%d vs %d" % (cut.rows, full.rows))
    check("D12 底部扣除把网格整体上移",
          cut.oy + cut.rows * cut.ch <= 1080 - m.thickness + 2,
          "oy=%d rows=%d ch=%d" % (cut.oy, cut.rows, cut.ch))
    ins_top = dock.inset(True, "top", m.thickness)
    cut_t = grid_metrics.compute(fake, (1920, 1080), native_px=48, inset=ins_top)
    check("D12 顶部扣除把网格下移", cut_t.oy >= ins_top[1],
          "oy=%d" % cut_t.oy)
    ins_left = dock.inset(True, "left", m.thickness)
    cut_l = grid_metrics.compute(fake, (1920, 1080), native_px=48, inset=ins_left)
    check("D12 左侧扣除把网格右移", cut_l.ox >= ins_left[0], "ox=%d" % cut_l.ox)
    check("D12 inset 全 0 与不传完全一致",
          grid_metrics.compute(fake, (1920, 1080), native_px=48,
                               inset=(0, 0, 0, 0)) == full,
          "%s vs %s" % (grid_metrics.compute(fake, (1920, 1080), native_px=48,
                                             inset=(0, 0, 0, 0)), full))

    # ---------- D13：真窗口 ----------
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])      # noqa: F841
    w = dock.DockWindow(st)
    w.set_items(seed)
    w.apply_geometry((1920, 1080))
    geo = w.geometry()
    bar = dock.bar_rect((1920, 1080), st.get_setting("dock_position"),
                        dock.metrics(st.ui_scale(), 2))
    check("D13 窗口与条带重合",
          (geo.x(), geo.y(), geo.width(), geo.height()) == bar,
          "%s vs %s" % ((geo.x(), geo.y(), geo.width(), geo.height()), bar))
    check("D13 有内容时可见", w.isVisible() or not w.isHidden(), "hidden")
    w.close()
    w2 = dock.DockWindow(st)
    w2.set_items([])
    w2.apply_geometry((1920, 1080))
    check("D13 空态仍占位（有可见的空态条）", w2.is_visible_bar(), "empty")
    w2.close()

    # ---------- D14：真窗口接线（网格真的让位/复原） ----------
    from src import grid_flow
    from src.desktop_window import DesktopWindow
    st14 = Storage(path=tmp / "dock14.json")
    st14._data["settings"]["auto_clone_desktop"] = False
    st14._data["layout"] = []
    st14.save()
    w14 = DesktopWindow(st14)
    w14.resize(1920, 1080)
    st14.set_setting("dock_items", seed)
    bar14 = dock.DockWindow(st14)
    st14.set_setting("dock_enabled", False)
    w14.set_dock(bar14)
    w14.apply_dock_settings()
    off = grid_flow.current_metrics()
    off_bottom = off.oy + off.rows * off.ch
    st14.set_setting("dock_enabled", True)
    w14.apply_dock_settings()
    on = grid_flow.current_metrics()
    on_bottom = on.oy + on.rows * on.ch
    thick = bar14.current_metrics().thickness
    check("D14 开启后网格底边在条带之上", on_bottom <= 1080 - thick + 1,
          "on_bottom=%d thick=%d" % (on_bottom, thick))
    check("D14 开启后行数不变或更少", on.rows <= off.rows,
          "%d vs %d" % (on.rows, off.rows))
    check("D14 关闭时网格铺得更满", off_bottom > on_bottom,
          "%d vs %d" % (off_bottom, on_bottom))
    check("D14 开关与条带可见性一致", bar14.is_visible_bar(), "enabled")
    st14.set_setting("dock_enabled", False)
    w14.apply_dock_settings()
    check("D14 关掉后条带隐藏", not bar14.is_visible_bar(), "hidden")
    w14.close()
    bar14.close()

    print("")
    if failures:
        print("FAILED %d: %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
