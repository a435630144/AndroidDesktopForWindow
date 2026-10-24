# -*- coding: utf-8 -*-
"""安装器按系统环境自动选语言（v12c）。

用户诉求：「安装包安装的时候根据用户的配置环境，自动选择当前的配置语言」。
拆成三条可执行契约：

  A1  中文 isl 带 [LangOptions] LanguageID=$0804——没有它 Inno 匹配不到简体中文
  A2  installer.iss 显式 LanguageDetectionMethod=uilanguage + ShowLanguageDialog=no
  A3  安装器把选出的语言写到 install_lang 旁路文件（zh_CN / en 按 ActiveLanguage）
  A4  Storage 启动时把旁路值收进 settings.lang（用户显式 language 仍优先）
  A5  脏旁路文件不写入、不崩溃

跑法：python tests/test_installer_lang.py     （offscreen，不碰真实 %APPDATA%）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
ROOT = Path(__file__).resolve().parent.parent

from src import i18n
from src.storage import Storage

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def main(_app):
    iss = read_text(ROOT / "scripts" / "installer.iss")
    isl = read_text(ROOT / "scripts" / "languages" / "ChineseSimplified.isl")

    # ---------- A1：中文 isl 的 LanguageID ----------
    check("A1a 中文 isl 有 [LangOptions] 段",
          "[LangOptions]" in isl)
    check("A1b LanguageID=$0804（简体中文·中国）",
          "LanguageID=$0804" in isl, isl[isl.find("LangOptions"):isl.find("LangOptions") + 120]
          if "LangOptions" in isl else "无 LangOptions")
    check("A1c LanguageName 是简体中文", "LanguageName=简体中文" in isl)

    # ---------- A2：安装器自动选语言 ----------
    check("A2a LanguageDetectionMethod=uilanguage",
          "LanguageDetectionMethod=uilanguage" in iss)
    check("A2b ShowLanguageDialog=no（不弹语言选择框）",
          "ShowLanguageDialog=no" in iss)
    check("A2c 旧注释「没有 ShowLanguageDialog 指令」已清掉",
          "没有 DefaultLanguage / ShowLanguageDialog" not in iss)

    # ---------- A3：写出 install_lang 旁路 ----------
    check("A3a PostInstall 写 install_lang",
          "install_lang" in iss and "ssPostInstall" in iss)
    check("A3b 按 ActiveLanguage 映射 zh_CN / en",
          "ActiveLanguage = 'english'" in iss and "'zh_CN'" in iss and "'en'" in iss)
    check("A3c 目标目录是 %APPDATA%\\PhoneDesktop",
          r"{userappdata}\{#MyAppNameEn}" in iss)

    # ---------- A4 / A5：Storage 合并旁路 ----------
    tmp = Path(tempfile.mkdtemp(prefix="test_install_lang_"))
    try:
        side = tmp / "install_lang"

        # 无旁路：lang 不出现（默认无此键）
        st = Storage(path=str(tmp / "state.json"))
        check("A4a 无旁路时不写 lang", "lang" not in st.settings)

        # 合法值
        side.write_text("zh_CN", encoding="utf-8")
        st = Storage(path=str(tmp / "state.json"))
        check("A4b 旁路 zh_CN 收进 settings.lang",
              st.get_setting("lang") == i18n.ZH, str(st.get_setting("lang")))

        side.write_text("en\n", encoding="utf-8")   # 允许尾部换行
        st = Storage(path=str(tmp / "state.json"))
        check("A4c 旁路 en（带换行）收进 settings.lang",
              st.get_setting("lang") == i18n.EN, str(st.get_setting("lang")))

        # 重装换语言：下一次启动即生效
        side.write_text("zh_CN", encoding="utf-8")
        st = Storage(path=str(tmp / "state.json"))
        check("A4d 重装换语言后更新 lang",
              st.get_setting("lang") == i18n.ZH)

        # resolve 链：显式 language 仍压过旁路
        st.set_setting("language", i18n.EN)
        check("A4e 显式 language 压过旁路",
              i18n.resolve(None, st) == i18n.EN)
        st.set_setting("language", i18n.AUTO)
        orig_system = i18n.system_language
        try:
            i18n.system_language = lambda: i18n.EN
            check("A4f auto + 旁路 zh_CN -> 用旁路而非系统",
                  i18n.resolve(i18n.AUTO, st) == i18n.ZH)
        finally:
            i18n.system_language = orig_system

        # ---------- A5：脏旁路（独立目录，避免继承上一步的 lang） ----------
        tmp2 = Path(tempfile.mkdtemp(prefix="test_install_lang_dirty_"))
        try:
            side2 = tmp2 / "install_lang"
            side2.write_text("klingon", encoding="utf-8")
            st = Storage(path=str(tmp2 / "state.json"))
            check("A5a 脏旁路值不写入 lang", "lang" not in st.settings)

            side2.write_text("", encoding="utf-8")
            st = Storage(path=str(tmp2 / "state.json"))
            check("A5b 空旁路不写入 lang", "lang" not in st.settings)

            side2.unlink()
            st = Storage(path=str(tmp2 / "state.json"))
            check("A5c 旁路缺失不崩溃", "lang" not in st.settings)

            # 脏旁路不得覆盖已有 lang（state.json 里已经写过的保留）
            side.write_text("zh_CN", encoding="utf-8")
            st = Storage(path=str(tmp / "state.json"))
            st.save()
            side.write_text("klingon", encoding="utf-8")
            st2 = Storage(path=str(tmp / "state.json"))
            check("A5d 脏旁路不覆盖已有 lang",
                  st2.get_setting("lang") == i18n.ZH, str(st2.get_setting("lang")))
        finally:
            import shutil
            shutil.rmtree(tmp2, ignore_errors=True)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

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
