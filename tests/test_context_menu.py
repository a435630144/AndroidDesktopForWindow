# -*- coding: utf-8 -*-
"""问题反馈 6：右键要还原系统桌面的全部功能（新建 Word / Excel …）。

病根：接管模式把原生右键换成了自绘菜单，而自绘菜单只硬编码了
「新建文件夹 / 新建文本文档」两项——装了 Office 也新建不了 Word 文档。

契约：
  M1 模板枚举至少含 .txt（Win11 记事本未注册 ShellNew 时走兜底）
  M2 每项结构完整：ext 以点开头、label 非空、progid 可为空
  M3 unique_path 重名自动加序号
  M4 create_from_template 在目标目录创建文件（.txt 为空文件）
  M5 Office 模板（若存在）生成的是**带内容的**文件（复制模板，不是空文件）
  M6 桌面右键菜单有「新建」子菜单，首项为「文件夹」
  M7 新建子菜单包含全部模板项
  M8 菜单含系统式入口：刷新 / 粘贴 / 显示设置 / 个性化 / 终端 / 桌面文件夹
  M9 未接管时不弹自绘的「新建」（原生菜单仍由系统提供）

运行：python tests/test_context_menu.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from src import shell_new
from src.desktop_window import DesktopWindow
from src.storage import Storage

W, H = 1920, 1040
STATE = Path(tempfile.gettempdir()) / "test_context_menu_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def settle(app, ms=60):
    end = QTimer()
    end.setSingleShot(True)
    loop = QEventLoop()
    end.timeout.connect(loop.quit)
    end.start(ms)
    loop.exec()


def make_state(takeover=True):
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = takeover
    st._data["settings"]["takeover_desktop"] = takeover
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["settings"]["layout_mode"] = "grid"
    st._data["widgets"] = []
    st._data["layout"] = []
    st.save()
    return st


def menu_texts(menu):
    out = []
    for act in menu.actions():
        if act.isSeparator():
            out.append("---")
        else:
            out.append(act.text())
    return out


def submenu_of(menu, text):
    for act in menu.actions():
        if act.menu() is not None and act.text() == text:
            return act.menu()
    return None


def main(app):
    # ---------- M1/M2：模板枚举 ----------
    tpls = shell_new.shell_new_templates()
    exts = [t["ext"] for t in tpls]
    check("M1 模板含 .txt（兜底）", ".txt" in exts, "%s" % exts)
    total = len(tpls)
    check("M1b 模板结构完整",
          all(t["ext"].startswith(".") and t["label"] for t in tpls),
          "%s" % [(t["ext"], t["label"]) for t in tpls])
    check("M1c 常见文档排在前面（txt 是首项）", exts[0] == ".txt", exts[:3])

    # ---------- M3：重名去重 ----------
    tmpdir = tempfile.mkdtemp(prefix="cm_new_")
    p1 = shell_new.unique_path(tmpdir, "新建文本文档", ".txt")
    open(p1, "w").close()
    p2 = shell_new.unique_path(tmpdir, "新建文本文档", ".txt")
    check("M3 重名自动加序号", os.path.basename(p2) == "新建文本文档 (2).txt",
          os.path.basename(p2))

    # ---------- M4/M5：按模板创建 ----------
    txt = next(t for t in tpls if t["ext"] == ".txt")
    made = shell_new.create_from_template(txt, tmpdir)
    check("M4 .txt 模板创建成功", bool(made) and os.path.exists(made), made)
    if made:
        check("M4b .txt 为空文件", os.path.getsize(made) == 0,
              "%d bytes" % os.path.getsize(made))
    docx = next((t for t in tpls if t["ext"] == ".docx"), None)
    if docx is not None:
        # 注意：Office 的 VFS 模板 word.docx 本身可能就是 0 字节占位
        # （Word 打开空文件即为空白文档），所以断言「跟模板文件同大小」
        src_tpl = shell_new._template_path(docx["ext"], docx["progid"])
        made2 = shell_new.create_from_template(docx, tmpdir)
        check("M5 Word 命中 FileName 模板路径（不是空文件兜底）",
              src_tpl is not None, "%s" % src_tpl)
        check("M5b Word 文档已创建且与模板同大小",
              bool(made2) and os.path.exists(made2)
              and os.path.getsize(made2) == os.path.getsize(src_tpl),
              "%s %s/%s" % (made2,
                            os.path.getsize(made2) if made2 else -1,
                            os.path.getsize(src_tpl) if src_tpl else -1))
    else:
        check("M5 本机未注册 .docx 模板（跳过，不算失败）", True)

    # ---------- M6-M8：菜单结构 ----------
    w = DesktopWindow(make_state(takeover=True))
    w.resize(W, H)
    w._update_grid_metrics()
    settle(app)
    from PySide6.QtWidgets import QMenu
    menu = w._build_context_menu()
    keep = [menu]                     # 持有引用：否则 C++ 菜单被子对象回收
    texts = menu_texts(menu)
    # addMenu 的返回包装在 PySide 里随时可能失效，用 findChild 按对象名取
    new_menu = menu.findChild(QMenu, "ctxNewMenu")
    check("M6 新建子菜单存在", new_menu is not None, "%s" % texts[:6])
    if new_menu is not None:
        items = menu_texts(new_menu)
        check("M6b 新建首项为文件夹", items[0] == "文件夹", "%s" % items[:4])
        labels = [t for t in items if t != "---"]
        check("M7 新建子菜单含全部模板项（标签+1 文件夹）",
              len(labels) == len(tpls) + 1,
              "labels=%d tpls=%d" % (len(labels), len(tpls)))
        check("M7b 新建菜单包含 Word / Excel / PPT 中至少一项",
              any(k in "".join(labels) for k in ("Word", "Excel", "PowerPoint")),
              "%s" % labels)
    for need in ("刷新", "粘贴", "显示设置", "个性化（桌面背景）",
                 "在终端中打开", "打开桌面文件夹", "查看"):
        check("M8 菜单含「%s」" % need, need in texts, "%s" % texts)

    # ---------- M9：未接管不弹自绘新建 ----------
    w2 = DesktopWindow(make_state(takeover=False))
    w2.resize(W, H)
    w2._update_grid_metrics()
    settle(app)
    texts2 = menu_texts(w2._build_context_menu())
    check("M9 未接管时不出现自绘「新建」", "新建" not in texts2, "%s" % texts2)

    # ---------- M10：「查看 ▸ 自动排列图标」是持久开关（反馈 3） ----------
    # 用户："应该先右键-查看-自动排列图标，再总是生效"——即资源管理器那套
    # 语义：勾选后一直按阅读序递进，未勾选时保留空格自由摆放。
    m3 = w._build_context_menu()
    view = None
    for act in m3.actions():
        if act.text() == "查看":
            view = act.menu()
            break
    check("M10 右键菜单有「查看」子菜单", view is not None)
    if view is not None:
        acts = {a.text(): a for a in view.actions()}
        auto = acts.get("自动排列图标")
        check("M10 查看下有「自动排列图标」", auto is not None,
              "%s" % list(acts))
        check("M10 该项是可勾选开关", auto is not None and auto.isCheckable())
        check("M10 勾选态来自 storage.auto_arrange",
              auto is not None
              and auto.isChecked() == bool(w.storage.get_setting("auto_arrange")),
              "act=%s storage=%s" % (auto.isChecked() if auto else None,
                                     w.storage.get_setting("auto_arrange")))
        check("M10 查看下有「立即整理」", any("立即整理" in t for t in acts),
              "%s" % list(acts))
        # 触发一次：勾上 -> 落 setting
        if auto is not None:
            was = bool(w.storage.get_setting("auto_arrange"))
            auto.trigger()
            settle(app)
            check("M10 勾选后立刻落 storage.auto_arrange",
                  bool(w.storage.get_setting("auto_arrange")) is True)
            # 复原，避免影响后续断言
            w.storage.set_setting("auto_arrange", was)

        # ---------- M11：「查看 ▸ 图标大小」三档有勾选标识（v7 §3.3）----------
        # 注意（坑 #68）：QMenu 是 Python 所有，重建菜单后旧对象可能已被回收，
        # 所以这里只在**同一次菜单构建**上取快照，后续校验走 _current_icon_tier。
        size_menu = acts.get("图标大小")
        check("M11 查看下有「图标大小」子菜单", size_menu is not None,
              "%s" % list(acts))
        if size_menu is not None:
            tiers = {a.text(): a for a in size_menu.menu().actions()}
            check("M11 三档都在",
                  set(tiers) >= {"大图标", "中图标", "小图标"}, "%s" % list(tiers))
            check("M11 三档均可勾选",
                  all(a.isCheckable() for a in tiers.values()))
            checked = [t for t, a in tiers.items() if a.isChecked()]
            check("M11 恰好勾中一档（默认中图标）",
                  checked == ["中图标"], "checked=%s" % (checked,))
        check("M11 默认档位 = medium", w._current_icon_tier() == "medium",
              "%s" % (w._current_icon_tier(),))
        # 切到小档 -> storage 落 icon_fit 0.42，档位反查跟着走
        w._set_icon_tier("small")
        settle(app)
        check("M11 切小档落 icon_fit=0.42", w.storage.icon_fit() == 0.42,
              "%s" % (w.storage.icon_fit(),))
        check("M11 勾选状态跟随 icon_fit",
              w._current_icon_tier() == "small", "%s" % (w._current_icon_tier(),))
        w._set_icon_tier("medium")
        settle(app)
        check("M11 回中档 -> 跟随原生",
              w._current_icon_tier() == "medium"
              and w.storage.icon_tier() == "medium",
              "%s / %s" % (w._current_icon_tier(), w.storage.icon_tier()))

    # ---------- M12/M13：网格原点**不在**右键里（2026-10-20 反馈 5 反转） ----------
    # 原点定位是开发者功能：入口只在设置页「高级 → 调试」，且开发者开关
    # 打开后才可配置。桌面右键无论自动 / 手动都不出现这两项。
    m4 = w._build_context_menu()
    texts4 = menu_texts(m4)
    check("M12 右键不出现「定位网格原点」",
          not any("定位网格原点" in t for t in texts4), "%s" % texts4[-8:])
    check("M13 自动模式下不出现「重置网格位置」",
          "重置网格位置" not in texts4, "%s" % texts4[-8:])
    w.storage.set_grid_origin("manual", 100, 50)
    settle(app)
    m5 = w._build_context_menu()
    texts5 = menu_texts(m5)
    check("M12b 手动模式下右键也不出现「定位网格原点」",
          not any("定位网格原点" in t for t in texts5), "%s" % texts5[-8:])
    check("M13b 手动模式下右键也不出现「重置网格位置」",
          "重置网格位置" not in texts5, "%s" % texts5[-8:])

    w2.close()
    w.close()
    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        return 1
    print("ALL context_menu PASSED")
    return 0


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    sys.exit(main(app))
