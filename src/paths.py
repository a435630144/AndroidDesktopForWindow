# -*- coding: utf-8 -*-
"""路径工具：开发态取项目目录，打包后取 _MEIPASS；用户数据统一放 %APPDATA%。

v10 D1（反馈 4，乙档）：产品名从旧名（`LEGACY_APP_NAME`）改为 `APP_NAME`——
**exe 名 / 安装目录 / 数据目录三处一起改**，数据目录带一次性迁移。
单实例键在 `single_instance.py` 做只读兼容（旧 exe 还开着时不许再起一个）。
"""
import os
import shutil
import sys
from pathlib import Path

APP_NAME = "PhoneDesktop"
LEGACY_APP_NAME = "DesktopOrganizerDemo"


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def resource_path(rel: str) -> Path:
    """资源文件路径（兼容 PyInstaller 打包后的 _MEIPASS 临时目录）。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / rel
    return project_root() / rel


def asset_path(name: str) -> str:
    return str(resource_path("assets") / name)


def _base_dir() -> Path:
    return Path(os.environ.get("APPDATA") or str(Path.home()))


def app_data_dir() -> Path:
    return _base_dir() / APP_NAME


def legacy_app_data_dir() -> Path:
    """改名前的数据目录（只有迁移会用到）。"""
    return _base_dir() / LEGACY_APP_NAME


def migrate_legacy_data() -> bool:
    """把旧品牌的数据目录整份搬到新目录（一次性，幂等）。

    规矩，三条都不能破：
      1. **新目录已存在就不动手**——不覆盖、不合并、不删旧目录。
         用户可能已经在新版里用过一阵，旧目录里反而是过期数据。
      2. 先 `copytree` 复制、**成功之后**才删旧目录。反过来先删再复制，
         一旦复制中途失败（磁盘满 / 杀软锁文件）用户布局就没了。
      3. 复制失败要把新目录里的半成品清掉并回答 False，让调用方按"没迁移"
         继续走——半个 state.json 比没有更糟。
    """
    new, old = app_data_dir(), legacy_app_data_dir()
    if new.exists() or not old.exists():
        return False
    try:
        shutil.copytree(old, new)
    except Exception:
        shutil.rmtree(new, ignore_errors=True)
        return False
    shutil.rmtree(old, ignore_errors=True)   # 删不掉也不影响使用（新目录已就绪）
    return True


def ensure_app_dirs() -> Path:
    p = app_data_dir()
    if not p.exists():
        migrate_legacy_data()
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_file(name: str) -> Path:
    return app_data_dir() / name


def program_dir() -> Path:
    """程序自身所在目录（安装目录 / 便携包解压目录）。

    用户数据（state.json、设置）在 %APPDATA%，**用户内容**（导入的组件）
    却也放 %APPDATA% 会让"卸载软件 = 组件还留在 C 盘"：用户反馈
    「软件装在 D:\\...\\Programs\\PhoneDesktop，组件却装到
    C:\\Users\\...\\Roaming\\PhoneDesktop\\widgets，两个位置毫无关系」。
    打包后组件目录跟着 exe 走，卸载/换盘迁移时与主程序同进同退。

    开发态（未打包）退回 %APPDATA%：仓库根目录是**代码**，把用户组件写
    进去既污染 git 工作区，也让"目录即真相"的插件扫描撞上 examples/
    与 Component/ 里的示例包。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return app_data_dir()
