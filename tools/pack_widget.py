# -*- coding: utf-8 -*-
"""把组件目录打成可导入的 zip（v9 V3，`docs/组件开发指南.md` §7）。

用法：
    python tools/pack_widget.py examples/widgets/hello
    python tools/pack_widget.py examples/widgets/hello -o dist/widgets/hello.zip
    python tools/pack_widget.py examples/widgets/hello --no-validate

默认产物：`dist/widgets/<id>-<version>.zip`（无 version 时只用 id）。

三条规矩：
  1. **先校验再打包**：走 `widget_plugin.build_spec()`，也就是组件库导入
     时的同一条路径。打出来的包能装，装出来的组件能画——不是"先打再说"。
     （`--no-validate` 只在没装 PySide6 的机器上救急用。）
  2. **manifest.json 在 zip 根目录**：导入器也接受"整体套一层目录"，但那
     依赖"只有一个顶层目录"，多余的空目录/`__MACOSX` 会把它打乱。
  3. **不收垃圾**：`__pycache__`、隐藏文件、超白名单后缀一律跳过，和导入器
     的 `ALLOWED_EXT` 对齐——否则用户拿到的是"自己打得开、程序装不上"的包。
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 与 widget_plugin.ALLOWED_EXT 对齐（这里复制一份而不是 import：打包脚本要
# 在"程序还没装好依赖"的环境里也能跑起来提示错误，import 会连带拉起 Qt）
ALLOWED_EXT = {".py", ".json", ".md", ".txt", ".png", ".jpg", ".jpeg",
               ".gif", ".svg", ".ico", ".webp"}
SKIP_DIRS = {"__pycache__", ".git", ".idea", ".vscode", "__MACOSX"}


def collect(folder: Path):
    """返回 (files, skipped)。files 是 (磁盘路径, zip 内相对路径)。"""
    files, skipped = [], []
    for path in sorted(folder.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(folder)
        parts = set(rel.parts[:-1])
        if parts & SKIP_DIRS or rel.name.startswith("."):
            skipped.append(str(rel))
            continue
        if path.suffix.lower() not in ALLOWED_EXT:
            skipped.append(str(rel))
            continue
        files.append((path, rel.as_posix()))
    return files, skipped


def validate(folder: Path) -> str:
    """返回空串 = 通过；否则返回给用户看的错误文本。"""
    try:
        from src import widget_plugin
    except Exception as exc:      # noqa: BLE001 —— 没装 PySide6 时走这里
        return ("无法加载校验器（%s: %s）。\n"
                "如果这台机器没装运行依赖，可加 --no-validate 跳过校验。"
                % (type(exc).__name__, exc))
    try:
        spec = widget_plugin.build_spec(folder)
    except Exception as exc:      # noqa: BLE001
        return "%s: %s" % (type(exc).__name__, exc)
    print("校验通过：%s（%s）· 跨度 %s"
          % (spec.name, spec.type,
             " / ".join("%d×%d" % s for s in spec.spans)))
    return ""


def default_out(folder: Path) -> Path:
    wid, ver = folder.name, ""
    try:
        import json
        man = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        wid = str(man.get("id") or wid)
        ver = str(man.get("version") or "").strip()
    except Exception:      # noqa: BLE001
        pass
    name = "%s-%s.zip" % (wid, ver) if ver else "%s.zip" % wid
    return ROOT / "dist" / "widgets" / name


def pack(folder: Path, out: Path) -> int:
    files, skipped = collect(folder)
    if not any(rel == "manifest.json" for _p, rel in files):
        print("✗ %s 下没有 manifest.json（必须在组件目录根上）" % folder)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for disk, rel in files:
            zf.write(disk, rel)
    total = out.stat().st_size
    print("已打包 %d 个文件 -> %s（%.1f KB）" % (len(files), out, total / 1024.0))
    for _p, rel in files:
        print("  + %s" % rel)
    if skipped:
        print("跳过 %d 项（缓存/隐藏/非白名单后缀）：" % len(skipped))
        for s in skipped[:12]:
            print("  - %s" % s)
        if len(skipped) > 12:
            print("  … 另有 %d 项" % (len(skipped) - 12))
    print("\n下一步：主程序 ▸ 设置 ▸ 组件库 ▸「导入组件…」选这个 zip。")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="把组件目录打成可导入的 zip（manifest.json 置于包根）")
    ap.add_argument("folder", nargs="?", default="examples/widgets/hello",
                    help="组件目录（含 manifest.json），默认示例组件")
    ap.add_argument("-o", "--out", default="", help="输出 zip 路径")
    ap.add_argument("--no-validate", action="store_true",
                    help="跳过 manifest/模块校验（没装依赖时救急）")
    args = ap.parse_args(argv)

    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        print("✗ 不是目录：%s" % folder)
        return 2

    if not args.no_validate:
        err = validate(folder)
        if err:
            print("✗ 校验失败，未打包：\n%s" % err)
            print("\n按报错改完再打。预览调试：python tools/widget_dev.py %s"
                  % folder)
            return 1

    out = Path(args.out).expanduser() if args.out else default_out(folder)
    return pack(folder, out)


if __name__ == "__main__":
    sys.exit(main())
