# -*- coding: utf-8 -*-
"""文件夹条目的 `app` 字段不得为 None（2026-10-20 打包自测暴露）。

现场：v6g 冻结包 `--selftest` 在第 5 秒回调里抛

    AttributeError: 'NoneType' object has no attribute 'get'
      File "src\\selftest.py", line 19/20
        1 for e in window.storage.layout if e.get("app", {}).get("kind") == "file"

根因：`desktop_window` 把应用条目升级成文件夹时写 `target["app"] = None`，
于是 state.json 里的 folder 条目长成 `{"app": null, "apps": [...]}`。
`e.get("app", {})` 的默认值**只在键不存在时生效**，键存在且值为 None 时
返回 None，链式 `.get` 当场炸。

全仓共 7 处同款链式写法，其中 4 处会真的遇到文件夹条目
（add_apps_dialog / desktop_window / iconwidget / selftest）——
「添加应用」对话框只要桌面上有文件夹就崩。

契约：
  A0 `storage.entry_app()` 对 dict / None / 缺键 / 非 dict 一律返回 dict
  A1 加载旧 state 时 `app: null` 归一化为 `{}`，且 save 后落盘自愈
  A2 归一化后四处链式 `.get` 不再抛，语义仍正确
  A3 建文件夹不再写 None（源码契约，两处）
  A4 `selftest.collect_info()` 能安全统计含文件夹的 layout
  A5 crash logger 必须先于重依赖导入安装——否则冻结包的 ImportError
     （v6f「exe 静默退出」最可能的真凶）连日志都留不下来

运行：python tests/test_entry_app_shape.py   （offscreen）
"""
import ast
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import storage as storage_mod
from src.storage import Storage

DSTATE = Path(tempfile.gettempdir()) / "test_entry_app_shape_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def write_state(path, layout):
    path.write_text(json.dumps({
        "settings": {"schema_version": 2, "takeover_desktop": True,
                     "hide_native_icons": True},
        "layout": layout,
        "widgets": [],
    }, ensure_ascii=False), encoding="utf-8")


FOLDER_ENTRY = {
    "id": "f1", "type": "folder", "app": None,
    "apps": [{"id": "m1", "kind": "file", "name": "a.jpg", "target": "C:/a.jpg"}],
    "col": 0, "row": 0,
}
APP_ENTRY = {
    "id": "a1", "type": "app",
    "app": {"id": "a1", "kind": "file", "name": "b.png", "target": "C:/b.png"},
    "col": 1, "row": 0,
}


def main():
    # ---------- A0 归一化入口 ----------
    fn = getattr(storage_mod, "entry_app", None)
    check("A0 存在 entry_app() 归一化入口", callable(fn))
    if callable(fn):
        check("A0a dict 原样返回", fn({"app": {"kind": "file"}}) == {"kind": "file"})
        check("A0b app=None -> {}", fn({"app": None}) == {})
        check("A0c 缺 app 键 -> {}", fn({"id": "x"}) == {})
        check("A0d 非 dict 条目 -> {}", fn(None) == {} and fn("x") == {})
        check("A0e app 不是 dict -> {}", fn({"app": 5}) == {})

    # ---------- A1 加载归一化 + 落盘自愈 ----------
    write_state(DSTATE, [FOLDER_ENTRY, APP_ENTRY])
    st = Storage(DSTATE)
    lay = st.layout
    check("A1a 加载后文件夹条目 app 为 {}",
          isinstance(lay[0].get("app"), dict) and lay[0]["app"] == {},
          "got=%r" % (lay[0].get("app"),))
    check("A1b 应用条目 app 不被破坏",
          lay[1].get("app", {}).get("kind") == "file", "got=%r" % (lay[1].get("app"),))
    check("A1c 文件夹成员列表保留", len(lay[0].get("apps") or []) == 1)

    st.save()
    raw = json.loads(DSTATE.read_text(encoding="utf-8"))
    check("A1d 落盘自愈：state.json 不再出现 app:null",
          all(e.get("app") is not None for e in raw["layout"]),
          "got=%r" % ([e.get("app") for e in raw["layout"]],))

    # ---------- A2 原有链式写法在归一化后安全 ----------
    e = st.layout[0]
    ok = True
    try:
        _ = e.get("app", {}).get("kind") == "file"
        _ = e.get("app", {}).get("target", "")
        _ = e.get("app", {}).get("name", "")
    except Exception as exc:
        ok = False
        check("A2 链式 .get 不再抛", False, "%s: %s" % (type(exc).__name__, exc))
    if ok:
        check("A2 链式 .get 不再抛", True)
    check("A2b 文件夹不会被误判成 file 条目",
          (e.get("app") or {}).get("kind") != "file")

    # ---------- A3 源码契约：建文件夹不再写 None ----------
    src = (ROOT / "src" / "desktop_window.py").read_text(encoding="utf-8")
    check("A3a 不再出现 target[\"app\"] = None", 'target["app"] = None' not in src)
    check("A3b 改写为 target[\"app\"] = {}",
          src.count('target["app"] = {}') >= 2,
          "count=%d" % src.count('target["app"] = {}'))

    # ---------- A4 selftest 统计安全 ----------
    from src import selftest
    collect = getattr(selftest, "collect_info", None)
    check("A4 存在 selftest.collect_info()", callable(collect))
    if callable(collect):
        win = SimpleNamespace(attached=True, icons={"f1": object(), "a1": object()},
                              storage=st)
        lyr = SimpleNamespace(widgets={})
        try:
            info = collect(win, lyr)
            good = isinstance(info, dict) and info.get("desktop_file_entries") == 1
            check("A4a 含文件夹的 layout 统计不抛且计数正确", good,
                  "got=%r" % (info.get("desktop_file_entries") if isinstance(info, dict) else info,))
        except Exception as exc:
            check("A4a 含文件夹的 layout 统计不抛且计数正确", False,
                  "%s: %s" % (type(exc).__name__, exc))

    # ---------- A5 crash logger 先于重依赖导入 ----------
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    call_line = None
    first_heavy = None
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            f = node.value.func
            if isinstance(f, ast.Name) and f.id == "_install_crash_logger" and call_line is None:
                call_line = node.lineno
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if (mod.startswith("PySide6") or mod == "src" or mod.startswith("src.")) \
                    and first_heavy is None:
                first_heavy = node.lineno
    check("A5 crash logger 在重依赖导入之前安装",
          call_line is not None and first_heavy is not None and call_line < first_heavy,
          "logger_line=%r first_import_line=%r" % (call_line, first_heavy))


if __name__ == "__main__":
    crashed = None
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        crashed = "exception"
    finally:
        try:
            if DSTATE.exists():
                DSTATE.unlink()
        except Exception:
            pass
        if crashed or failures:
            print("FAILED: %d" % len(failures))
            sys.stdout.flush()
            os._exit(1)
        print("ALL PASSED")
        sys.stdout.flush()
        os._exit(0)
