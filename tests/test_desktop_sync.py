# -*- coding: utf-8 -*-
"""v6 §7.4：桌面文件自动同步（反馈 13/14）。

契约：
  - `storage.sync_desktop_incremental()` 只增删差异，**绝不重排**已摆放的
    图标（文件系统事件是被动发生的：下载保存 / 删除 / 重命名，不该把用户
    摆好的桌面重排一遍）；
  - 1:1 增删时视为「重命名」，新条目继承旧条目位置（文件改个名不该换位置）；
  - `DesktopWatcher` = QFileSystemWatcher（Windows 底层 ReadDirectoryChangesW，
    零新增依赖）+ 1s debounce（连续事件合并成一次）；
  - 「重新扫描桌面文件」保留为强制全量重扫（走 rescan_desktop 的 pack 语义）。

  S1 新增：只加不重排（既有条目 col/row 不变）
  S2 删除：只移除丢失条目，其余位置不变
  S3 重命名 1:1：新条目继承旧位置
  S4 无变化返回 (0, [])
  S5 2:2 增删不做位置继承（避免错配）
  D1 watcher 监听目录（注入临时目录）
  D2 debounce：事件到点才同步，连续事件合并为一次
  D3 flush 回调 + synced 信号
  D4 stop 后不再触发
  D5 设置项 auto_sync_desktop 默认开 + 设置界面可控

运行：python tests/test_desktop_sync.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QCheckBox

from src import appsource
from src.desktop_watch import DesktopWatcher
from src.settings_dialog import SettingsDialog
from src.storage import Storage

TMP = Path(tempfile.gettempdir()) / "test_desktop_sync"
failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(ms):
    loop = QEventLoop()
    t = QTimer()
    t.setSingleShot(True)
    t.timeout.connect(loop.quit)
    t.start(ms)
    loop.exec()


def mk(fid, name):
    """伪造一条桌面文件扫描结果。"""
    target = "C:/fake_desktop/%s" % name
    return {"id": fid, "name": Path(name).stem, "target": target,
            "icon_path": target, "kind": "file"}


def make_state(positions=None):
    """positions: {id 后缀: (col,row)}，默认 a(0,0) b(1,0) c(2,0)。"""
    positions = positions or {"a": (0, 0), "b": (1, 0), "c": (2, 0)}
    p = TMP / "state.json"
    if p.exists():
        p.unlink()
    st = Storage(path=str(p))
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["settings"]["hide_native_icons"] = False
    st._data["layout"] = [
        {"id": "df:%s" % k, "type": "app", "app": mk("df:%s" % k, "%s.txt" % k),
         "apps": [], "col": c, "row": r}
        for k, (c, r) in positions.items()
    ]
    st.save()
    return st


def pos_map(st):
    return {e["id"]: (int(e["col"]), int(e["row"])) for e in st.layout}


def patch_scan(files):
    appsource.scan_desktop_files = lambda: [dict(f) for f in files]


def main(app):
    real_scan = appsource.scan_desktop_files

    # ---------- S1 新增不重排 ----------
    st = make_state()
    before = pos_map(st)
    patch_scan([mk("df:a", "a.txt"), mk("df:b", "b.txt"),
                mk("df:c", "c.txt"), mk("df:d", "d.txt")])
    added, removed = st.sync_desktop_incremental()
    after = pos_map(st)
    check("S1 新增 1 项", added == 1 and not removed, "added=%s removed=%s" % (added, removed))
    check("S1 既有条目位置不变（不 pack 重排）",
          all(after[k] == before[k] for k in before), "%s -> %s" % (before, after))
    check("S1 新条目存在", "df:d" in after, "%s" % sorted(after))

    # ---------- S2 删除 ----------
    st2 = make_state()
    before2 = pos_map(st2)
    patch_scan([mk("df:a", "a.txt"), mk("df:c", "c.txt")])
    added2, removed2 = st2.sync_desktop_incremental()
    after2 = pos_map(st2)
    check("S2 删除 1 项（b 消失）", removed2 == ["df:b"] and added2 == 0,
          "added=%s removed=%s" % (added2, removed2))
    check("S2 其余位置不变",
          after2.get("df:a") == before2["df:a"]
          and after2.get("df:c") == before2["df:c"])
    check("S2 少了 b 的条目", "df:b" not in after2)

    # ---------- S3 重命名 1:1 继承位置 ----------
    # 初始 b 在 (5,0) 的孤立位置：若只走 add_app 的 first_free_cell，
    # 新条目会落 (1,0)；只有真正继承才会回到 (5,0)。
    st3 = make_state({"a": (0, 0), "b": (5, 0), "c": (2, 0)})
    patch_scan([mk("df:a", "a.txt"), mk("df:c", "c.txt"),
                mk("df:b2", "b_renamed.txt")])
    added3, removed3 = st3.sync_desktop_incremental()
    p3 = pos_map(st3)
    check("S3 重命名 = 1 删 1 增", added3 == 1 and removed3 == ["df:b"],
          "added=%s removed=%s" % (added3, removed3))
    check("S3 新条目继承旧位置 (5,0)", p3.get("df:b2") == (5, 0),
          "pos=%s" % (p3.get("df:b2"),))

    # ---------- S4 无变化 ----------
    st4 = make_state()
    patch_scan([mk("df:a", "a.txt"), mk("df:b", "b.txt"), mk("df:c", "c.txt")])
    added4, removed4 = st4.sync_desktop_incremental()
    check("S4 无变化返回 (0, [])", added4 == 0 and removed4 == [],
          "added=%s removed=%s" % (added4, removed4))

    # ---------- S5 2:2 不继承 ----------
    # b 在 (5,0) 孤立位：若错误地对 2 删 2 增也做配对继承，某个新条目
    # 会出现在 (5,0)；正确实现只按 first_free_cell 就近填充，不会落那里。
    st5 = make_state({"a": (0, 0), "b": (5, 0), "c": (2, 0)})
    patch_scan([mk("df:a", "a.txt"), mk("df:x", "x.txt"), mk("df:y", "y.txt")])
    added5, removed5 = st5.sync_desktop_incremental()
    p5 = pos_map(st5)
    check("S5 2 删 2 增返回正确", len(removed5) == 2 and added5 == 2,
          "added=%s removed=%s" % (added5, removed5))
    check("S5 2:2 不做位置继承（无条目落旧位置 (5,0)）",
          p5.get("df:x") != (5, 0) and p5.get("df:y") != (5, 0), "pos=%s" % p5)

    appsource.scan_desktop_files = real_scan

    # ---------- D1 watcher 监听目录 ----------
    watch_dir = TMP / "desk"
    watch_dir.mkdir(parents=True, exist_ok=True)
    st6 = make_state()
    calls = []
    # D 阶段用 patch 的扫描结果，保证每次 flush 都有明确变化
    patch_scan([mk("df:a", "a.txt"), mk("df:b", "b.txt"),
                mk("df:c", "c.txt"), mk("df:d", "d.txt")])

    w = DesktopWatcher(st6, on_sync=lambda a, r: calls.append((a, r)),
                       folders=[watch_dir], debounce_ms=80)
    check("D1 监听注入的桌面目录", w.paths == [str(watch_dir)], "paths=%s" % w.paths)

    # ---------- D2 debounce 合并 ----------
    w.kick()
    w.kick()
    w.kick()
    check("D2 事件后处于 pending（尚未同步）", w.pending() and not calls)
    settle(220)
    check("D2 debounce 到点后只同步一次", len(calls) == 1, "calls=%s" % calls)
    check("D2 同步后 pending 清除", not w.pending())

    # ---------- D3 回调 + 信号 ----------
    got = []
    w.synced.connect(lambda a, r: got.append((a, r)))
    patch_scan([mk("df:a", "a.txt"), mk("df:b", "b.txt"), mk("df:c", "c.txt")])
    w.kick()
    settle(220)
    check("D3 on_sync 与 synced 信号都触发",
          len(calls) == 2 and len(got) == 1, "calls=%d got=%d" % (len(calls), len(got)))
    check("D3 删除事件被识别", got and got[0][1] == 1, "got=%s" % got)

    # ---------- D4 stop ----------
    w.stop()
    w.kick()
    settle(220)
    check("D4 stop 后不再同步", len(calls) == 2, "calls=%d" % len(calls))
    appsource.scan_desktop_files = real_scan

    # ---------- D5 设置项 ----------
    st7 = make_state()
    check("D5 auto_sync_desktop 默认开启",
          bool(st7.get_setting("auto_sync_desktop")) is True)

    class _W:
        attached = True

        def rebuild(self, stagger=False):
            pass

        def update(self):
            pass

        def apply_native_icons_setting(self):
            pass

        def rescan_desktop(self):
            return (0, 0)

        def set_layout_mode(self, m):
            pass

    dlg = SettingsDialog(_W(), st7, None)
    boxes = [c for c in dlg.findChildren(QCheckBox) if "自动同步" in c.text()]
    check("D5 设置界面有「自动同步」开关", len(boxes) == 1, "found=%d" % len(boxes))
    if boxes:
        check("D5 开关初态跟随设置", boxes[0].isChecked() is True)
        boxes[0].setChecked(False)
        app.processEvents()
        check("D5 关闭后落盘 False", st7.get_setting("auto_sync_desktop") is False)
    dlg.deleteLater()

    # ---------- W1/W2 窗口接线 ----------
    from src import grid_flow
    from src.desktop_window import DesktopWindow
    st8 = make_state()
    st8._data["settings"]["dev_mode"] = False
    st8._data["settings"]["takeover_desktop"] = False
    grid_flow.set_grid(st8, (1280, 800))
    grid_flow.set_page(0)
    patch_scan([mk("df:a", "a.txt"), mk("df:b", "b.txt"), mk("df:c", "c.txt")])
    w8 = DesktopWindow(st8)
    settle(250)

    w8.set_auto_sync(True)
    check("W1 set_auto_sync(True) 启动监听",
          w8._watcher is not None and w8._watcher.running(),
          "paths=%s" % (w8._watcher.paths if w8._watcher else None))
    w8.set_auto_sync(False)
    check("W1 set_auto_sync(False) 停止监听",
          w8._watcher is not None and not w8._watcher.running())

    icons_before = {k: id(v) for k, v in w8.icons.items()}
    pos_before = {e["id"]: (e["col"], e["row"]) for e in st8.layout}
    patch_scan([mk("df:a", "a.txt"), mk("df:b", "b.txt"),
                mk("df:c", "c.txt"), mk("df:d", "d.txt")])
    added8, removed8 = st8.sync_desktop_incremental()
    w8._on_desk_sync(added8, len(removed8))
    settle(250)
    pos_after = {e["id"]: (e["col"], e["row"]) for e in st8.layout}
    check("W2 增量新增图标出现", "df:d" in w8.icons, "%s" % sorted(w8.icons))
    check("W2 已有图标实例未被重建",
          all(id(w8.icons[k]) == v for k, v in icons_before.items() if k in w8.icons),
          "before=%s" % sorted(icons_before))
    check("W2 既有条目位置未变",
          all(pos_after.get(k) == v for k, v in pos_before.items()),
          "%s -> %s" % (pos_before, pos_after))

    appsource.scan_desktop_files = real_scan
    for w in w8.icons.values():
        w.close()
    w8.set_auto_sync(False)
    w8.close()

    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL desktop_sync PASSED")
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
    for f in TMP.glob("*.json"):
        try:
            f.unlink()
        except Exception:
            pass
    return code


if __name__ == "__main__":
    sys.exit(run_main())
