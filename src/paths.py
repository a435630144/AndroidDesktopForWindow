# -*- coding: utf-8 -*-
"""路径工具：开发态取项目目录，打包后取 _MEIPASS；用户数据统一放 %APPDATA%。"""
import os
import sys
from pathlib import Path

APP_NAME = "DesktopOrganizerDemo"


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


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME


def ensure_app_dirs() -> Path:
    p = app_data_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_file(name: str) -> Path:
    return app_data_dir() / name
