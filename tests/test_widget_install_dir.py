# -*- coding: utf-8 -*-
"""组件安装目录指向程序所在目录（v14 反馈 14）。

用户诉求：
    软件装在 D:\\...\\Programs\\PhoneDesktop，组件商店却把组件装到
    C:\\Users\\...\\Roaming\\PhoneDesktop\\widgets——两个位置毫无关系。
    组件目录应该跟着程序走（卸载 / 换盘时同进同退）。

契约：
  P1  `plugin_root()` 在**程序目录**下（不是 %APPDATA%）
  P2  旧位置 `%APPDATA%\\PhoneDesktop\\widgets` 有一次性迁移，且幂等
  P3  新目录已有内容时**不动**旧目录（不覆盖用户数据）
  P4  `load_all()` 会先跑迁移（启动路径唯一入口）

跑法：python tests/test_widget_install_dir.py     （不碰真实目录）
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
ROOT = Path(__file__).resolve().parent.parent

from src import paths            # noqa: E402
from src import widget_plugin    # noqa: E402

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def main(_app):
    # ---------- P1：目录在程序目录下 ----------
    root = widget_plugin.plugin_root()
    check("P1a plugin_root = 程序目录/widgets",
          root == paths.program_dir() / "widgets", str(root))
    check("P1c 旧位置仍是 %APPDATA%（只作迁移源）",
          widget_plugin.legacy_plugin_root() == paths.data_file("widgets"),
          str(widget_plugin.legacy_plugin_root()))

    # 打包态（用户实际环境）：程序目录 = exe 所在目录
    import sys as _sys
    import tempfile as _tempfile
    fake_root = Path(_tempfile.mkdtemp(prefix="test_frozen_"))
    real_frozen = getattr(_sys, "frozen", None)
    real_exe = _sys.executable
    try:
        _sys.frozen = True
        _sys.executable = str(fake_root / "Programs" / "PhoneDesktop"
                              / "PhoneDesktop.exe")
        prog = paths.program_dir()
        check("P1d 打包态程序目录 = exe 所在目录",
              prog == fake_root / "Programs" / "PhoneDesktop", str(prog))
        check("P1e 打包态组件目录跟着 exe 走",
              widget_plugin.plugin_root() == prog / "widgets",
              str(widget_plugin.plugin_root()))
    finally:
        if real_frozen is None:
            try:
                del _sys.frozen
            except AttributeError:
                pass
        else:
            _sys.frozen = real_frozen
        _sys.executable = real_exe
        shutil.rmtree(fake_root, ignore_errors=True)

    # ---------- P2/P3：一次性迁移 ----------
    tmp = Path(tempfile.mkdtemp(prefix="test_widget_dir_"))
    try:
        new_prog = tmp / "program"
        new_appdata = tmp / "appdata"
        new_prog.mkdir()
        new_appdata.mkdir()
        old_plugins = new_appdata / "PhoneDesktop" / "widgets"
        (old_plugins / "hello").mkdir(parents=True)
        (old_plugins / "hello" / "manifest.json").write_text("{}", encoding="utf-8")

        real_program_dir, real_data_file = paths.program_dir, paths.data_file
        paths.program_dir = lambda: new_prog
        paths.data_file = lambda name: new_appdata / "PhoneDesktop" / name
        try:
            check("P2a 迁移前旧目录存在、新目录不存在",
                  old_plugins.is_dir() and not (new_prog / "widgets").exists())
            moved = widget_plugin.migrate_legacy_plugin_root()
            check("P2b 一次性迁移执行", moved is True)
            check("P2c 组件搬到程序目录/widgets",
                  (new_prog / "widgets" / "hello" / "manifest.json").is_file(),
                  str(new_prog / "widgets"))
            check("P2d 旧目录已清掉", not old_plugins.exists())
            check("P2e 幂等（再跑一次不动）",
                  widget_plugin.migrate_legacy_plugin_root() is False)

            # 新目录已有内容 → 不动旧目录
            old_plugins.mkdir(parents=True)
            (old_plugins / "another").mkdir()
            check("P3a 新目录已有内容时返回 False",
                  widget_plugin.migrate_legacy_plugin_root() is False)
            check("P3b 旧目录内容原样保留",
                  (old_plugins / "another").is_dir())
        finally:
            paths.program_dir, paths.data_file = real_program_dir, real_data_file

        # ---------- P4：load_all 走迁移 ----------
        calls = []
        real_mig = widget_plugin.migrate_legacy_plugin_root
        widget_plugin.migrate_legacy_plugin_root = lambda: calls.append(1) or False
        try:
            widget_plugin.load_all()
            check("P4 load_all 先跑迁移", bool(calls))
        finally:
            widget_plugin.migrate_legacy_plugin_root = real_mig
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    main(app)
    print("----")
    print("failures=%d" % len(failures))
    sys.exit(1 if failures else 0)
