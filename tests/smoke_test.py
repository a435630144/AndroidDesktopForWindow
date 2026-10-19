# -*- coding: utf-8 -*-
"""离线冒烟测试：验证核心逻辑（存储 / 布局 / 文件夹合并解散 / 自启 / 扫描 /
桌面克隆 / 稳定 id / 重扫去重 / 图标）。
运行：python tests/smoke_test.py   （offscreen 平台，无需显示桌面）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from src import appsource, autostart  # noqa: E402
from src.desktop_window import DesktopWindow  # noqa: E402
from src.storage import Storage  # noqa: E402

failures = []


def check(name, cond):
    print("[%s] %s" % ("PASS" if cond else "FAIL", name))
    if not cond:
        failures.append(name)


def main():
    app = QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # 0. 主题 tokens 可用
        try:
            from src import theme
            check("主题 tokens 可用", theme.SURFACE.isValid() and theme.ui_font(12) is not None)
        except Exception as e:
            check("主题 tokens 可用（%s）" % e, False)

        # 1. 存储默认值与持久化
        st = Storage(path=tmp / "state.json")
        check("存储默认设置", st.get_setting("icon_size") == 72)
        # 2026-10-18 路线A：默认进入整理模式 + 自动播种
        check("默认进入桌面整理模式（路线A）",
              st.get_setting("hide_native_icons") is True
              and st.get_setting("auto_clone_desktop") is True)
        check("默认组件含桌面面板", any(w.get("type") == "panel" for w in st.widgets))
        st.set_setting("icon_size", 96)
        st2 = Storage(path=tmp / "state.json")
        check("存储持久化", st2.get_setting("icon_size") == 96)

        # 2. 布局：添加两个应用 -> 拖拽合并成文件夹 -> 解散
        st.add_app({"name": "记事本", "target": "notepad"})
        st.add_app({"name": "计算器", "target": "calc"})
        check("布局添加", len(st.layout) == 2)
        w = DesktopWindow(st)
        ids = [e["id"] for e in st.layout]
        w._on_merge(ids[0], ids[1])
        check("拖拽合并为文件夹", len(st.layout) == 1 and st.layout[0]["type"] == "folder")
        check("文件夹含 2 个成员", len(st.layout[0].get("apps", [])) == 2)
        w._on_dissolve(st.layout[0]["id"])
        check("解散文件夹", len(st.layout) == 2 and all(e["type"] == "app" for e in st.layout))

        # 3. 移除 + 稀疏保留（自由排布：compact 只修越界/重叠，不重排顺序）
        keep_pos = (st.layout[1]["col"], st.layout[1]["row"])
        st.remove_entry(st.layout[0]["id"])
        st.compact_layout()
        check("移除后保留稀疏布局（其余图标不动）",
              len(st.layout) == 1
              and (st.layout[0]["col"], st.layout[0]["row"]) == keep_pos)
        st.tidy_layout()
        check("显式整理布局后顺序铺满",
              (st.layout[0]["col"], st.layout[0]["row"]) == (0, 0))

        # 4. 文件夹成员拖出（payload: "fid:idx"）：拖出一个仍保留，拖空才溶解
        st.add_app({"name": "画图", "target": "mspaint"})
        st.add_app({"name": "Edge 浏览器", "target": "microsoft-edge:"})
        e0, e1 = st.layout[0], st.layout[1]
        w._on_merge(e1["id"], e0["id"])
        check("再次合并为文件夹", st.layout[0]["type"] == "folder" and len(st.layout[0]["apps"]) == 2)
        fid = st.layout[0]["id"]
        w._on_extract("%s:0" % fid)
        folder = st.find_entry(fid)
        check("拖出一个成员后文件夹保留", len(st.layout) == 3 and folder and len(folder["apps"]) == 1)
        w._on_extract("%s:0" % fid)
        check("成员拖空后文件夹溶解", len(st.layout) == 3
              and all(e["type"] == "app" for e in st.layout) and st.find_entry(fid) is None)

        # 5. 开机自启（写入后立即清理，不在系统留下残留）
        autostart.set_enabled(True)
        check("自启写入注册表", autostart.is_enabled())
        autostart.set_enabled(False)
        check("自启关闭", not autostart.is_enabled())

        # 6. 桌面文件克隆：稳定 id / 播种 / 重扫补增清失 / 去重
        fake_desktop = tmp / "Desktop"
        fake_desktop.mkdir()
        (fake_desktop / "报告.docx").write_text("x", encoding="utf-8")
        (fake_desktop / "素材").mkdir()
        (fake_desktop / "素材" / "图.png").write_text("x", encoding="utf-8")
        (fake_desktop / "chrome.lnk").write_text("x", encoding="utf-8")

        entry = appsource.desktop_file_entry(fake_desktop / "报告.docx")
        check("桌面条目稳定 id", entry["id"].startswith("df:") and entry["kind"] == "file")
        check("桌面条目同名同 id",
              appsource.desktop_file_entry(fake_desktop / "报告.docx")["id"] == entry["id"])

        orig_dirs = appsource._desktop_folders
        appsource._desktop_folders = lambda: [fake_desktop]
        try:
            files = appsource.scan_desktop_files()
            check("桌面扫描含 3 个顶层条目", len(files) == 3)
            check("桌面扫描文件夹优先", files[0]["name"] == "素材")

            st3 = Storage(path=tmp / "state2.json")
            added = st3.seed_desktop_clone()
            check("克隆播种 3 项", added == 3 and len(st3.layout) == 3)
            check("播种不重复", st3.seed_desktop_clone() == 0)
            st3.add_app(entry)  # 已存在 -> 不产生副本
            check("同应用重复添加去重", len(st3.layout) == 3)

            # 新增文件 -> 重扫补增
            (fake_desktop / "新增.txt").write_text("x", encoding="utf-8")
            added2, removed2 = st3.rescan_desktop()
            check("重扫补增 1 项", added2 == 1 and len(st3.layout) == 4)
            # 删除文件 -> 重扫清失
            (fake_desktop / "报告.docx").unlink()
            added3, removed3 = st3.rescan_desktop()
            check("重扫清失 1 项", removed3 == 1 and len(st3.layout) == 3)
        finally:
            appsource._desktop_folders = orig_dirs

        # 7. 应用扫描
        apps = appsource.all_apps()
        check("应用扫描非空", len(apps) > 0)
        check("内置系统入口", any(a["id"] == "sys-notepad" for a in apps))

        # 8. 路线A 默认行为：整理模式开启即自动播种；旧版迁移已废弃（不再清空/关闭）
        orig_dirs2 = appsource._desktop_folders
        appsource._desktop_folders = lambda: [fake_desktop]
        try:
            st4 = Storage(path=tmp / "state3.json")
            st4.ensure_desktop_clone()
            check("整理模式默认自动播种", len(st4.layout) == 3)
            st4.set_takeover(False)
            st4.set_setting("auto_clone_desktop", False)
            st4b = Storage(path=tmp / "state3b.json")
            st4b.set_takeover(False)
            st4b.set_setting("auto_clone_desktop", False)
            st4b.ensure_desktop_clone()
            check("退回原生模式后不自动播种", len(st4b.layout) == 0)
            st4b.set_takeover(True)
            st4b.ensure_desktop_clone(force=True)
            check("重新开启整理模式即补播", len(st4b.layout) == 3)

            # 旧版状态（播种过 + 整理模式）：迁移不再清空布局、不再关闭整理模式
            st5 = Storage(path=tmp / "state4.json")
            st5.seed_desktop_clone()
            st5.set_takeover(True)
            st5.set_setting("desktop_clone_v2", True)
            check("旧版迁移不再清空/关闭（路线A）", st5.migrate_to_native_mode() is False
                  and len(st5.layout) == 3
                  and st5.get_setting("hide_native_icons") is True)
        finally:
            appsource._desktop_folders = orig_dirs2

        # 9. 图标可用（offscreen 平台可生成 QPixmap）
        icon = appsource.icon_for({"name": "记事本", "target": "notepad"}, 48)
        check("图标可用", not icon.isNull())
        pm = appsource.icon_pixmap({"name": "记事本", "target": "notepad"}, 79, 1.25)
        check("高清 pixmap 尺寸归一化",
              pm.devicePixelRatioF() == 1.25 and pm.width() == 99)

    print()
    if failures:
        print("共 %d 项失败: %s" % (len(failures), failures))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
