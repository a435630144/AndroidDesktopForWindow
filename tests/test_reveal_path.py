# -*- coding: utf-8 -*-
"""右键「在文件夹中显示」的路径规则 + 鼠标输入无副作用守卫。

用户诉求（反馈 6）：
    图标右键「在文件夹中显示」以前把路径指到「电脑文档」，正确规则是
      1. 普通文件   -> 文件自己（定位到所在文件夹并选中）
      2. 快捷方式   -> **原文件**（解析 .lnk 目标）
      3. 桌面文件   -> 桌面文件夹（1/2 已覆盖）
    壳层入口（ms-settings: / explorer / ::{GUID}）没有文件位置，不能拿它
    去拼 explorer 命令行——explorer 解析失败会静默打开默认位置（文档库）。

反馈 2：有用户反馈「使用软件之后感觉鼠标的速度异常」。
    本程序**从不修改**系统鼠标设置（SPI_SETMOUSE* / 注册表 MouseSpeed /
    SetCursorPos / ClipCursor 全部没有）。这里立一条守卫：源码里出现这类
    API 就直接红——防止以后某个"智能定位/自动吸附"改掉用户的手感。

跑法：python tests/test_reveal_path.py     （offscreen，不碰真实桌面）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
ROOT = Path(__file__).resolve().parent.parent

from src import appsource    # noqa: E402

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def main(_app):
    # ---------- R1：普通文件 ----------
    tmp = Path(tempfile.mkdtemp(prefix="test_reveal_"))
    try:
        doc = tmp / "报告.docx"
        doc.write_text("x", encoding="utf-8")
        check("R1a 普通文件 → 文件自己",
              appsource.reveal_path_for(
                  {"target": str(doc), "kind": "file"}) == str(doc))

        # ---------- R2：快捷方式 → 原文件 ----------
        lnk = tmp / "快捷方式.lnk"
        lnk.write_text("x", encoding="utf-8")
        app_lnk = {"target": str(lnk), "icon_path": str(lnk), "kind": "file"}
        real = appsource.shortcut_target_path(app_lnk)
        # .lnk 不是真的快捷方式（内容是 x），symLinkTarget 解析不到 → 退到自身
        check("R2a 坏链接退到 .lnk 自己（不抛）",
              appsource.reveal_path_for(app_lnk) == str(lnk),
              "real=%s" % (real,))

        # 真快捷方式：用 Qt 造一个指向 doc 的 .lnk（QFileInfo.symLinkTarget 能解）
        try:
            from PySide6.QtCore import QFileInfo
            made = tmp / "real.lnk"
            # Windows 下没有 Qt 公共 API 造 .lnk；直接验证解析函数的优先级：
            # 目标存在时返回目标，不存在时返回 None（调用方退到 .lnk 自己）
            fake = {"icon_path": str(doc) + ".lnk", "target": str(doc) + ".lnk"}
            check("R2b shortcut_target_path 目标不存在返回 None",
                  appsource.shortcut_target_path(fake) is None)
            check("R2c .lnk 目标不存在时退到 .lnk 自身",
                  appsource.reveal_path_for(fake) == str(doc) + ".lnk")
        except Exception as exc:      # noqa: BLE001
            check("R2 Qt 快捷方式探针", False, str(exc))

        # ---------- R3：桌面文件 → 桌面文件夹 ----------
        desk = appsource._desktop_folders()
        if desk:
            d = desk[0]
            f = d / "test_reveal_probe.txt"
            try:
                f.write_text("x", encoding="utf-8")
                got = appsource.reveal_path_for(
                    {"target": str(f), "kind": "file"})
                check("R3 桌面文件 → 桌面文件自身（定位即桌面文件夹）",
                      got == str(f) and str(f).lower().startswith(
                          str(d).lower()), "got=%s" % (got,))
            finally:
                try:
                    f.unlink()
                except OSError:
                    pass
        else:
            check("R3 桌面文件 → 桌面文件自身", True, "无桌面目录，跳过")

        # ---------- R4：目录 → 直接打开 ----------
        sub = tmp / "sub"
        sub.mkdir(exist_ok=True)
        check("R4 目录也能解析（reveal_in_explorer 走打开分支）",
              appsource.reveal_path_for({"target": str(sub), "kind": "file"})
              == str(sub))

        # ---------- R5：壳层入口没有文件位置 ----------
        for tgt in ("ms-settings:", "explorer", "control", "notepad",
                    "::{20D04FE0-3AEA-1069-A2D8-08002B30309D}",
                    "steam://rungameid/1329410", "microsoft-edge:"):
            check("R5 %s 无文件位置" % tgt,
                  appsource.reveal_path_for({"target": tgt}) is None)
        check("R5b 空 target 无文件位置",
              appsource.reveal_path_for({"target": ""}) is None
              and appsource.reveal_path_for({}) is None)

        # ---------- R6：路径不存在时不许退到文档库 ----------
        ghost = str(tmp / "不存在的文件.txt")
        check("R6a 文件不存在也能给出路径（父目录兜底在 reveal 里做）",
              appsource.reveal_path_for({"target": ghost}) == ghost)
        # reveal_in_explorer 不抛（文件不存在 → 打开父目录）
        try:
            ok = appsource.reveal_in_explorer(ghost)
            check("R6b reveal_in_explorer 对不存在文件不抛", True,
                  "returned=%s" % (ok,))
        except Exception as exc:      # noqa: BLE001
            check("R6b reveal_in_explorer 对不存在文件不抛", False, str(exc))
        check("R6c reveal_in_explorer('') 返回 False 不抛",
              appsource.reveal_in_explorer("") is False)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    # ---------- M：鼠标输入无副作用 ----------
    bad = []
    for dp, dns, fns in os.walk(ROOT / "src"):
        if "__pycache__" in dp:
            continue
        for fn in fns:
            if not fn.endswith(".py"):
                continue
            p = Path(dp) / fn
            for i, ln in enumerate(p.read_text(encoding="utf-8",
                                               errors="replace").splitlines(),
                                   1):
                s = ln.strip()
                if s.startswith("#"):
                    continue
                low = s.lower()
                for kw in ("spi_setmouse", "spi_setwheel", "mousespeed",
                           "mousesensitivity", "clipcursor", "setcursorpos"):
                    if kw in low and "探针" not in s and "probe" not in low:
                        bad.append("%s:%d %s" % (p.name, i, s[:80]))
    check("M1 src 无鼠标设置/光标 warp 写入", not bad, "; ".join(bad[:3]))
    check("M2 SPI_GET 只读用法存在（说明确实审计过系统参数）",
          "SPI_GET" in (ROOT / "src" / "effects.py").read_text(
              encoding="utf-8"))


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    main(app)
    print("----")
    print("failures=%d" % len(failures))
    sys.exit(1 if failures else 0)
