# -*- coding: utf-8 -*-
"""改名 PhoneDesktop（v10 D1，反馈 4，乙档）+ 数据目录一次性迁移。

契约：
  P1  APP_NAME / LEGACY_APP_NAME：新目录叫 PhoneDesktop，旧目录记在 LEGACY_*
  P2  迁移：旧在、新不在 → 内容整份复制过来，旧目录删掉
  P3  幂等：新目录已存在 → 不动新目录、不删旧目录、返回 False
  P4  旧目录不存在 → 返回 False，不擅自建目录（建目录是 ensure_app_dirs 的事）
  P5  复制失败 → 清掉半成品、保留旧目录（不许吞数据）
  P6  ensure_app_dirs() 建目录 + 首次调用顺带迁移
  P7  单实例键：旧键"只读兼容"——旧实例占着键时新实例判定 running，
      且必须让出自己刚抢到的主键（不然下次真正启动会被自己这半次挡住）
  P8  改名完整性：src/ 与 main.py 里再出现旧名，必须只出现在 LEGACY_* 标记的行上
  P9  打包/安装器里的名字与 APP_NAME 一致（exe 名、安装目录、AppId 不变）

跑法：python tests/test_storage_paths.py     （不碰真实 %APPDATA%）
"""
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


_ORIG_APPDATA = os.environ.get("APPDATA")


def use_sandbox(path: Path) -> None:
    """把 %APPDATA% 指到沙箱：迁移逻辑全是"目录存在与否"的判定，
    不隔离就会拿用户真数据做实验（探针铁律）。"""
    os.environ["APPDATA"] = str(path)


def restore_appdata() -> None:
    if _ORIG_APPDATA is None:
        os.environ.pop("APPDATA", None)
    else:
        os.environ["APPDATA"] = _ORIG_APPDATA


def read_text(p: Path) -> str:
    return io.open(str(p), encoding="utf-8").read()


def main(app):
    from src import paths as P
    from src.single_instance import SingleInstance

    # ---------- P1：名字 ----------
    check("P1 新数据目录名是 PhoneDesktop", P.APP_NAME == "PhoneDesktop", P.APP_NAME)
    check("P1b 旧名记在 LEGACY_APP_NAME（供迁移）",
          P.LEGACY_APP_NAME == "DesktopOrganizerDemo", P.LEGACY_APP_NAME)
    check("P1c 新旧不同名（同名的迁移毫无意义）", P.APP_NAME != P.LEGACY_APP_NAME)

    # ---------- P2：正常迁移 ----------
    sandbox = Path(tempfile.mkdtemp(prefix="pd_paths_"))
    try:
        use_sandbox(sandbox)
        old, new = P.legacy_app_data_dir(), P.app_data_dir()
        check("P2a 两个目录都落在沙箱里", str(old).startswith(str(sandbox))
              and str(new).startswith(str(sandbox)), str(old))
        old.mkdir(parents=True)
        (old / "state.json").write_text('{"layout": [{"id": "x"}]}', encoding="utf-8")
        (old / "widgets").mkdir()
        (old / "widgets" / "w.py").write_text("# plugin", encoding="utf-8")

        ok = P.migrate_legacy_data()
        check("P2b 迁移返回 True", ok is True)
        check("P2c 新目录里有 state.json 且内容一致",
              (new / "state.json").read_text(encoding="utf-8")
              == '{"layout": [{"id": "x"}]}')
        check("P2d 子目录一起搬（组件插件目录）", (new / "widgets" / "w.py").exists())
        check("P2e 迁移成功后旧目录被删", not old.exists())

        # ---------- P3：幂等 / 不覆盖 ----------
        old.mkdir(parents=True)
        (old / "state.json").write_text("STALE", encoding="utf-8")
        ok2 = P.migrate_legacy_data()
        check("P3 新目录已存在时不再迁移（返回 False）", ok2 is False)
        check("P3b 新目录内容没被旧数据覆盖",
              "STALE" not in (new / "state.json").read_text(encoding="utf-8"))
        check("P3c 旧目录保留（不删用户的旧数据）", old.exists())

        # ---------- P4：旧目录不存在 ----------
        shutil.rmtree(new)
        shutil.rmtree(old)
        check("P4 旧目录不存在 → False 且不建新目录",
              P.migrate_legacy_data() is False and not new.exists())

        # ---------- P5：复制失败 ----------
        old.mkdir(parents=True)
        (old / "state.json").write_text("DATA", encoding="utf-8")
        real_copytree = shutil.copytree

        def boom(src, dst, *a, **kw):
            os.makedirs(dst, exist_ok=True)          # 模拟"复制到一半"
            (Path(dst) / "half.tmp").write_text("x", encoding="utf-8")
            raise OSError("disk full")

        shutil.copytree = boom
        try:
            ok3 = P.migrate_legacy_data()
        finally:
            shutil.copytree = real_copytree
        check("P5 复制失败返回 False", ok3 is False)
        check("P5b 半成品目录被清掉（半个 state 比没有更糟）", not new.exists())
        check("P5c 旧目录原样保留（数据不许丢）",
              old.exists() and (old / "state.json").read_text(encoding="utf-8") == "DATA")

        # ---------- P6：ensure_app_dirs ----------
        check("P6 ensure_app_dirs 建目录并顺带迁移",
              P.ensure_app_dirs() == new and new.exists() and not old.exists())

        # ---------- P8：改名完整性（静态门禁）----------
        strays = []
        targets = [ROOT / "main.py"] + sorted((ROOT / "src").rglob("*.py"))
        for f in targets:
            for i, line in enumerate(read_text(f).splitlines(), 1):
                if "DesktopOrganizerDemo" in line and "LEGACY" not in line \
                        and "legacy" not in line:
                    strays.append("%s:%d" % (f.name, i))
        check("P8 旧名只出现在 LEGACY 标记处（src/ + main.py）", not strays,
              str(strays[:5]))

        # ---------- P9：打包与安装器 ----------
        iss = read_text(ROOT / "scripts" / "installer.iss")
        build = read_text(ROOT / "scripts" / "build_portable.ps1")
        check("P9 安装器 exe 名与 APP_NAME 一致",
              '#define MyAppExe "PhoneDesktop.exe"' in iss)
        check("P9b 安装目录名取 MyAppNameEn 且为 PhoneDesktop",
              "DefaultDirName={autopf}\\{#MyAppNameEn}" in iss
              and '#define MyAppNameEn "PhoneDesktop"' in iss)
        check("P9c AppId 不变（覆盖升级要落在同一条记录上）",
              "AppId={{8A3F2C41-7D5E-4B9A-9E6F-DesktopOrganizer01}" in iss)
        check("P9d 安装包会清掉旧程序目录",
              '{autopf}\\DesktopOrganizerDemo' in iss)
        check("P9e 打包脚本产物名与 APP_NAME 一致",
              "--name PhoneDesktop" in build and "'PhoneDesktop.exe'" in build)
        check("P9f 打包脚本 onedir 目录名一致",
              '\\$OutName\\PhoneDesktop"' in build.replace('"dist', '"dist'))
        check("P9g 发布者改成「随便玩玩ay」", 'MyAppPublisher "随便玩玩ay"' in iss)

        # ---------- P10：crash.log 的目录不许抢在迁移前面建 ----------
        main_src = read_text(ROOT / "main.py")
        crash_block = main_src.split("def _install_crash_logger")[1].split("def ")[0]
        check("P10 crash.log 目录走 ensure_app_dirs（否则先建空目录会把迁移挡掉）",
              "ensure_app_dirs" in crash_block)
        check("P10b crash.log 目录不再自己 makedirs",
              "os.makedirs" not in crash_block)

        # ---------- P7：单实例键兼容 ----------
        tag = "_t%d" % os.getpid()
        primary = "PhoneDesktop_SingleInstance" + tag
        primary2 = primary + "_b"
        legacy = "DesktopOrganizerDemo_SingleInstance" + tag

        g1 = SingleInstance(primary, legacy_keys=(legacy,))
        check("P7 没有旧实例时新键能抢到", not g1.is_running())

        g2 = SingleInstance(primary, legacy_keys=(legacy,))
        check("P7b 同键第二实例被拦下", g2.is_running())

        # 模拟"旧 exe 还在跑"：手工占住旧键
        from PySide6.QtCore import QSharedMemory
        legacy_mem = QSharedMemory(legacy)
        legacy_mem.create(1)
        try:
            g1._mem.detach()          # 让出主键，模拟"新 exe 刚启动"
            g3 = SingleInstance(primary2, legacy_keys=(legacy,))
            check("P7c 旧键被占 → 新实例判 running（不并存）", g3.is_running())
        finally:
            legacy_mem.detach()

        # 旧实例退出后必须能正常启动（g3 不许把主键占着不放）
        g4 = SingleInstance(primary2, legacy_keys=(legacy,))
        check("P7d 旧实例退出后新键可用（半次启动没留下占用）", not g4.is_running())
        g4._mem.detach()

        g5 = SingleInstance(primary, legacy_keys=())
        check("P7e 不传 legacy_keys 时行为不变", not g5.is_running())
        g5._mem.detach()
    finally:
        restore_appdata()
        shutil.rmtree(sandbox, ignore_errors=True)

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
