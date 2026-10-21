#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档一致性检查（docs lint）。

把 `docs/README.md` 的文档生命周期规则变成一条可执行命令，
专门抓历史上真实发生过的四类过期：链接失效 / 章节重复 / 坑号重复 / 文档与代码数值漂移。

用法：
    python scripts/check_docs.py            # 检查并打印报告
    python scripts/check_docs.py --strict   # WARN 也当失败（发版 / 交接前用）

退出码：0 = 无 ERROR（--strict 下无 WARN）；1 = 有问题。
规则与豁免写在本文件顶部常量里，改规则请同步 docs/README.md §4。
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.environ.get("DOCS_LINT_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
ARCHIVE = os.path.join("docs", "archive")

# 冻结的归档文档不参与"内容级"检查（它们记录的是当时的事实），只查链接
SKIP_CONTENT_DIRS = (ARCHIVE, ".git", "build", "dist", "node_modules", ".workbuddy")

SKIP_DIRS = (".git", "build", "dist", "node_modules", ".workbuddy", "__pycache__")

errors: list[str] = []
warns: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warns.append(msg)


def iter_md(include_archive: bool = True):
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel_dir = os.path.relpath(dirpath, ROOT)
        if not include_archive and rel_dir.startswith(ARCHIVE):
            continue
        for name in sorted(filenames):
            if name.endswith(".md"):
                yield os.path.join(dirpath, name)


def rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace("\\", "/")


# ---------------------------------------------------------------- 检查 1：相对链接

LINK_RX = re.compile(r"\]\(([^)\s]+\.md)(?:#[^)]*)?\)")


def check_links() -> None:
    total = 0
    for path in iter_md():
        try:
            text = open(path, encoding="utf-8").read()
        except OSError as exc:
            err(f"{rel(path)}: 读取失败 {exc}")
            continue
        for target in LINK_RX.findall(text):
            if target.startswith(("http://", "https://")):
                continue
            total += 1
            dest = os.path.normpath(os.path.join(os.path.dirname(path), target))
            if not os.path.exists(dest):
                err(f"{rel(path)}: 死链 -> {target}")
    print(f"[1] 相对链接 {total} 条")


# ---------------------------------------------------------------- 检查 2：章节标题重复

HEAD_RX = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.M)


def check_dup_headings() -> None:
    for path in iter_md(include_archive=False):
        text = open(path, encoding="utf-8").read()
        seen: dict[str, int] = {}
        for m in HEAD_RX.finditer(text):
            level, title = m.group(1), m.group(2)
            # 目录里的锚点行不算
            if title.startswith("目录") or set(title) <= set("-— "):
                continue
            key = f"{level} {title}"
            seen[key] = seen.get(key, 0) + 1
        for key, cnt in seen.items():
            if cnt > 1:
                err(f"{rel(path)}: 章节标题重复 {cnt} 次 -> {key}")
    print("[2] 章节标题唯一性已检查")


# ---------------------------------------------------------------- 检查 3：DEVLOG 坑表编号重复

PITFALL_ROW_RX = re.compile(r"^\|\s*(\d+)\s*\|", re.M)


def check_pitfall_ids() -> None:
    path = os.path.join(ROOT, "DEVLOG.md")
    if not os.path.exists(path):
        warn("DEVLOG.md 不存在，跳过坑表检查")
        return
    text = open(path, encoding="utf-8").read()
    start = text.find("## 8.")
    end = text.find("## 9.", start if start >= 0 else 0)
    if start < 0:
        warn("DEVLOG.md 未找到 §8 坑表章节，跳过")
        return
    body = text[start:end if end > start else len(text)]
    ids = [int(x) for x in PITFALL_ROW_RX.findall(body)]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        err(f"DEVLOG.md §8: 坑号重复 -> {dup}")
    mx = max(ids) if ids else 0
    print(f"[3] 坑表 {len(ids)} 行，编号 1..{mx}")


# ---------------------------------------------------------------- 检查 4：文档 ↔ 代码 常量漂移

CONST_DOC_RX = re.compile(r"\b([A-Z][A-Z0-9_]{3,})\s*=\s*(\d+(?:\.\d+)?)\b")
CONST_SRC_RX = r"^\s*{name}\s*(?::\s*[\w\[\], .]+)?=\s*(\d+(?:\.\d+)?)"

# 文档里写旧值是合法的：要么在讲"当时定的是什么"，要么在举反例。
# 命中这些词就不当 ERROR（降 WARN 并提示人工确认），避免把反例本身判成错误。
CONTEXT_WORDS = ("过期", "旧值", "反例", "写成", "已改", "太高", "历史", "当时", "曾")


def _src_constants() -> dict[str, tuple[str, str]]:
    """{常量名: (值, 定义文件)}，只扫 src/*.py。"""
    out: dict[str, tuple[str, str]] = {}
    src = os.path.join(ROOT, "src")
    if not os.path.isdir(src):
        return out
    for name in sorted(os.listdir(src)):
        if not name.endswith(".py"):
            continue
        p = os.path.join(src, name)
        text = open(p, encoding="utf-8").read()
        for m in re.finditer(r"^([A-Z][A-Z0-9_]{3,})\s*(?::[^=\n]+)?=\s*(\d+(?:\.\d+)?)\b", text, re.M):
            out[m.group(1)] = (m.group(2), name)
    return out


def _timeline_span(text: str) -> tuple[int, int]:
    """DEVLOG §5 时间线的字符区间：编年史允许保留"当时的旧值"，只算 WARN。"""
    s = text.find("\n## 5.")
    e = text.find("\n## 6.", s if s >= 0 else 0)
    if s < 0:
        return (0, 0)
    return (s, e if e > s else len(text))


def check_constants() -> None:
    consts = _src_constants()
    if not consts:
        warn("src/ 下未读到常量，跳过漂移检查")
        return
    checked = 0
    for path in iter_md(include_archive=False):
        text = open(path, encoding="utf-8").read()
        is_devlog = os.path.basename(path) == "DEVLOG.md"
        tl_s, tl_e = _timeline_span(text) if is_devlog else (0, 0)
        offset = 0
        for lineno, line in enumerate(text.splitlines(keepends=True), 1):
            pos = offset
            offset += len(line)
            if "=" not in line:
                continue
            for name, doc_val in CONST_DOC_RX.findall(line):
                if name not in consts:
                    continue
                src_val, src_file = consts[name]
                if abs(float(src_val) - float(doc_val)) <= 1e-9:
                    continue
                checked += 1
                msg = (
                    f"{rel(path)}:{lineno}: {name} 文档写 {doc_val}，"
                    f"代码 src/{src_file} 是 {src_val}"
                )
                # 三种可以保留旧值的情形：编年史 / 反例说明 / 历史语境
                in_timeline = tl_s <= pos < tl_e
                ctx = [w for w in CONTEXT_WORDS if w in line]
                if in_timeline:
                    warn(msg + "（DEVLOG §5 历史段，确认同段或后续段落已写新值即可）")
                elif ctx:
                    warn(msg + f"（语境词 {'/'.join(ctx)}：反例或历史说明，人工确认）")
                else:
                    err(msg)
    print(f"[4] 文档-代码常量比对 {checked} 处漂移")


# ---------------------------------------------------------------- 检查 5：他机绝对路径

ABS_RX = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:/[^\s`)\]\"'<>]*")

# 白名单必须"跟着项目走"，不能写死任一会话工作区路径。
# 2026-10-20 的教训（坑 #74/#75）：项目在 D:/OneDrive → D:/WorkBuddy/<会话>/ → C:/.../WorkBuddy/<会话>/
# 之间搬过三次，每次把白名单改成"当前准位"，下一次搬迁就全错。
# 正确做法：把本脚本自身的根目录动态加入白名单——项目搬到哪，白名单就跟着变。
ALLOW_PREFIX = (
    ROOT.replace("\\", "/"),
    "C:/Users/43563/.workbuddy",  # 托管 venv / node（用户级，跨项目稳定）
)
ABS_EXEMPT_WORDS = (
    "另一台机器", "本机不存在", "他机", "示例", "旧路径", "旧机器", "旧位置",
    # 讲"路径迁移史 / 别照抄"的段落，本来就必须写出那些失效路径
    "不存在", "失效", "别照抄", "会话工作区", "历史",
)


def check_abs_paths() -> None:
    hits = 0
    for path in iter_md(include_archive=False):
        text = open(path, encoding="utf-8").read()
        for lineno, line in enumerate(text.splitlines(), 1):
            if any(w in line for w in ABS_EXEMPT_WORDS):
                continue
            for hit in ABS_RX.findall(line):
                if hit.startswith(ALLOW_PREFIX):
                    continue
                hits += 1
                warn(f"{rel(path)}:{lineno}: 绝对路径 {hit}（换机即失效，建议改相对路径）")
    print(f"[5] 绝对路径告警 {hits} 处")


# ---------------------------------------------------------------- 检查 6：文档引用的测试文件

TEST_REF_RX = re.compile(r"tests/(test_[A-Za-z0-9_]+\.py)")


def check_test_refs() -> None:
    seen: dict[str, str] = {}
    for path in iter_md(include_archive=False):
        text = open(path, encoding="utf-8").read()
        for name in TEST_REF_RX.findall(text):
            if "xxx" in name or "*" in name:  # 文档里的占位示例
                continue
            seen.setdefault(name, rel(path))
    missing = [n for n in sorted(seen) if not os.path.exists(os.path.join(ROOT, "tests", n))]
    for name in missing:
        warn(f"{seen[name]}: 引用了 tests/{name}，但文件不存在（计划中？写错？）")
    print(f"[6] 引用测试文件 {len(seen)} 个，缺失 {len(missing)} 个")


# ---------------------------------------------------------------- 检查 7：版本号一致

def check_version() -> None:
    vp = os.path.join(ROOT, "src", "version.py")
    if not os.path.exists(vp):
        return
    src = open(vp, encoding="utf-8").read()
    m = re.search(r'VERSION\s*=\s*"([^"]+)"', src)
    if not m:
        warn("src/version.py 未解析到 VERSION")
        return
    ver = m.group(1)
    ms = re.search(r'SEMVER\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"', src)
    iss = os.path.join(ROOT, "scripts", "installer.iss")
    iss_ver = None
    if os.path.exists(iss):
        t = open(iss, encoding="utf-8-sig", errors="replace").read()
        # Inno 的 preprocessor 语法是 `#define MyAppVersion "2.1.3"`（无 `=`）。
        # 旧正则要求 `=`，于是 [7] 从未真正比对过——这是本检查的存量缺陷，2026-10-21 修。
        m2 = re.search(r'MyAppVersion[^0-9"]{0,8}"?([0-9]+\.[0-9]+\.[0-9]+)', t)
        iss_ver = m2.group(1) if m2 else None

    # 2026-10-21 用户版本规则：对外语义版本（小修 patch / 大批 minor / 新功能 major）
    # 必须与安装包号一致。历史上这里只 print 不校验，于是 v7c 的 README 还挂着 2.1.1。
    if not ms:
        warn("src/version.py 缺少 SEMVER（对外语义版本），无法校验安装包号")
    else:
        semver = ms.group(1)
        if iss_ver and iss_ver != semver:
            err(f"[7] 版本漂移：src/version.py SEMVER={semver}，installer.iss MyAppVersion={iss_ver}")
        elif not iss_ver:
            warn("[7] src/version.py 有 SEMVER，但 installer.iss 未解析到 MyAppVersion")
    print(f"[7] 源码 VERSION={ver} / SEMVER={ms.group(1) if ms else '?'} / 安装包 {iss_ver or '?'}")


def selftest() -> int:
    """自检：在临时目录里造正例/反例，确认本脚本真的能抓到问题。

    没有这一步，脚本某天静默失效（永远 PASS）也没人知道——那它比没有更危险。
    跑法：python scripts/check_docs.py --selftest   （期望 rc==0）
    """
    import shutil
    import subprocess
    import tempfile

    cases = [
        (
            "反例A：文档写 0.45，代码是 0.30 → 必须报 ERROR",
            {
                "src/demo.py": "THRESH_RATIO = 0.30\n",
                "DEVLOG.md": (
                    "## 5. 时间线\n\n一段话。\n\n## 6. 台账\n\n## 8. 已知坑速查表\n\n"
                    "| 1 | 甲 | 乙 |\n\n## 9. 打包\n"
                ),
                "README.md": "阈值 `THRESH_RATIO = 0.45` 是当前值。\n",
            },
            True,
        ),
        (
            "反例B：死链 + 重复章节 + 坑号重复 → 必须报 ERROR",
            {
                "README.md": "# T\n\n见 [不存在](nope.md)\n\n## 8. 坑表\n\n| 3 | a |\n| 3 | b |\n",
            },
            True,
        ),
        (
            "正例C：全部一致 → 必须 PASS",
            {
                "src/demo.py": "THRESH_RATIO = 0.30\n",
                "DEVLOG.md": "## 8. 已知坑速查表\n\n| 1 | 甲 | 乙 |\n\n## 9. 打包\n",
                "README.md": "阈值 `THRESH_RATIO = 0.30`，见 [DEVLOG](DEVLOG.md)。\n",
            },
            False,
        ),
    ]

    failures = 0
    for label, files, want_fail in cases:
        tmp = tempfile.mkdtemp(prefix="docslint_")
        try:
            for relpath, content in files.items():
                dest = os.path.join(tmp, *relpath.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "w", encoding="utf-8") as fh:
                    fh.write(content)
            env = dict(os.environ, DOCS_LINT_ROOT=tmp)
            proc = subprocess.run(
                [sys.executable, os.path.abspath(__file__)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=60,
            )
            got_fail = proc.returncode != 0
            ok = got_fail == want_fail
            print(f"{'PASS' if ok else 'FAIL'}  {label}（rc={proc.returncode}）")
            if not ok:
                failures += 1
                print(proc.stdout[-800:])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print(f"自检：{len(cases) - failures}/{len(cases)} 通过")
    return 0 if failures == 0 else 1


def main() -> int:
    strict = "--strict" in sys.argv
    if "--selftest" in sys.argv:
        return selftest()
    print(f"docs lint @ {ROOT}")
    print("-" * 58)
    check_links()
    check_dup_headings()
    check_pitfall_ids()
    check_constants()
    check_abs_paths()
    check_test_refs()
    check_version()
    print("-" * 58)
    for w in warns:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    print(f"结果：ERROR {len(errors)} / WARN {len(warns)}")
    if errors or (strict and warns):
        print("FAIL")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
