# -*- coding: utf-8 -*-
"""安装器品牌与分语种一致性（v13a）。

用户诉求：中文名「掌镜桌面」/ 英文名「PhoneDesktop」；安装界面此前中英混搭，
要把每个语言的界面收干净。拆成可执行契约：

  B1  品牌双名：CustomMessages 里 AppTitle 中文=掌镜桌面、英文=PhoneDesktop
  B2  界面显示名走 {cm:AppTitle}，不再把中文名写死进 AppName/图标名
  B3  [Icons] / [Code] 不得硬编码中文快捷方式或中文提示（走 {cm:...}）
  B4  中文 isl 覆盖安装/卸载主路径（关键页面消息齐全，不漏英文）
  B5  向导视觉物料齐全：wizard.png + wizard_small.png + 新图标

跑法：python tests/test_installer_brand.py     （offscreen）
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
ROOT = Path(__file__).resolve().parent.parent

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def section(text: str, name: str) -> str:
    """取 [name] 段正文（到下一个段头为止）。忽略注释行里的字面 [Name]。"""
    lines = text.splitlines()
    out = []
    grabbing = False
    for ln in lines:
        s = ln.strip()
        if s.startswith("[") and s.endswith("]") and not s.startswith("[;"):
            grabbing = (s == "[%s]" % name)
            continue
        if grabbing:
            out.append(ln)
    return "\n".join(out)


def main(_app):
    iss = read_text(ROOT / "scripts" / "installer.iss")
    isl = read_text(ROOT / "scripts" / "languages" / "ChineseSimplified.isl")

    # ---------- B1：双名 ----------
    check("B1a 中文 AppTitle=掌镜桌面",
          "chinesesimplified.AppTitle=掌镜桌面" in iss)
    check("B1b 英文 AppTitle=PhoneDesktop",
          "english.AppTitle=PhoneDesktop" in iss)
    check("B1c 卸载入口分语种",
          "chinesesimplified.UninstallShortcut=卸载 掌镜桌面" in iss
          and "english.UninstallShortcut=Uninstall PhoneDesktop" in iss)

    # ---------- B2：显示名走 cm ----------
    check("B2a AppName={cm:AppTitle}", "AppName={cm:AppTitle}" in iss)
    check("B2b DefaultGroupName={cm:AppTitle}", "DefaultGroupName={cm:AppTitle}" in iss)
    check("B2c UninstallDisplayName={cm:AppTitle}", "UninstallDisplayName={cm:AppTitle}" in iss)
    check("B2d exe/数据目录仍用 MyAppNameEn=PhoneDesktop",
          '#define MyAppNameEn "PhoneDesktop"' in iss
          and "DefaultDirName={autopf}\\{#MyAppNameEn}" in iss)

    # ---------- B3：禁止硬编码中文进图标/代码 ----------
    icons_block = section(iss, "Icons")
    code_block = section(iss, "Code")
    # 只看非注释行：注释里出现「卸载」是说明文字，不是界面文案
    icons_code = "\n".join(
        ln for ln in icons_block.splitlines()
        if ln.strip() and not ln.strip().startswith(";"))
    check("B3a [Icons] 无硬编码中文（卸载/掌镜）",
          "卸载" not in icons_code and "掌镜" not in icons_code,
          icons_code[:120])
    check("B3b [Icons] 用 {cm:UninstallShortcut}",
          "{cm:UninstallShortcut}" in icons_code, icons_code[:200])
    # [Code] 允许出现语言映射字面量 zh_CN/en，但提示语不得硬编码中文
    hard = []
    for ln in code_block.splitlines():
        s = ln.strip()
        if not s or s.startswith("//") or s.startswith("{"):
            continue
        if any(ch >= "一" and ch <= "鿿" for ch in s) and "cm:" not in s:
            hard.append(s)
    check("B3c [Code] 提示语无硬编码中文", not hard, str(hard[:3]))
    check("B3d [Code] 装前提示走 {cm:AppRunning}", "{cm:AppRunning}" in code_block)

    # ---------- B4：中文 isl 覆盖主路径 ----------
    must = [
        "WelcomeLabel1", "WizardSelectDir", "WizardSelectTasks",
        "WizardSelectProgramGroup", "WizardReady", "WizardInstalling",
        "FinishedHeadingLabel", "ExitSetupTitle", "ConfirmUninstall",
        "WizardUninstalling", "ErrorTitle", "ButtonNext", "ButtonInstall",
        "ButtonCancel", "ButtonFinish", "StatusExtractFiles",
    ]
    miss = [k for k in must if ("%s=" % k) not in isl]
    check("B4a 中文 isl 覆盖安装/卸载主路径", not miss, "缺：%s" % miss)
    # 这些 key 若落到英文 Default.isl，中文界面就会中英混搭
    leak = [k for k in ("ErrorExecutingProgram", "ErrorCopying",
                        "StatusCreateIcons", "UninstallStatusLabel")
            if ("%s=" % k) not in isl]
    check("B4b 错误框/状态条也已覆盖", not leak, "缺：%s" % leak)
    check("B4c 中文 isl 仍是 $0804", "LanguageID=$0804" in isl)

    # ---------- B5：视觉物料 ----------
    for name in ("app_icon.ico", "app_icon.png", "wizard.png", "wizard_small.png"):
        p = ROOT / "assets" / name
        check("B5 %s 存在且非空" % name, p.is_file() and p.stat().st_size > 0)
    check("B5c 向导小图挂进了 iss", "WizardSmallImageFile" in iss)
    check("B5d 向导大图仍是 wizard.png", "WizardImageFile=..\\assets\\wizard.png" in iss)

    # 源稿与下游文件名同源（make_icon.py 归一化拷贝）
    src = ROOT / "assets" / "app_icon_new.ico"
    dst = ROOT / "assets" / "app_icon.ico"
    check("B5e app_icon.ico 来自新图标稿（字节一致）",
          src.is_file() and dst.is_file()
          and src.read_bytes() == dst.read_bytes())

    print()
    if failures:
        print("FAILED %d 项：%s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)
    sys.exit(main(_app))
