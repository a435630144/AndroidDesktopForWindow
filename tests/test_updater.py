# -*- coding: utf-8 -*-
"""更新检测 + 关于作者（v11 反馈 33）。

用户原话：「在高级里加入更新检测功能，从 github 仓库获取最新版本更新，并加入
一个关于作者对于作者介绍。」

契约：
  P1  parse_version 认 v 前缀 / 缺段 / 脏值
  P2  is_newer 逐段比较（1.2 == 1.2.0；5.0.10 > 5.0.9）
  P3  release_of 脏数据不抛
  P4  fetch_latest 正常解析（注入 opener，不碰网络）
  P5  fetch_latest 网络错误 -> UpdaterError，文案是人话（不暴露 traceback）
  P6  UpdateChecker 后台跑：成功发 finished 且带 newer 标记
  P7  UpdateChecker 失败发 failed（不静默）
  P8  连点：检查中再 check() 返回 False
  P9  作者链接 = 用户给的两个地址；项目地址指向仓库

运行：python tests/test_updater.py   （offscreen）
"""
import json
import os
import sys
import urllib.error
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src import updater

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


class FakeResp:
    def __init__(self, payload):
        self._raw = payload

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def main(app):
    # ---------- P1 / P2 版本号 ----------
    check("P1 `v5.0.7` -> (5,0,7)", updater.parse_version("v5.0.7") == (5, 0, 7))
    check("P1b `5.1` 补 0 -> (5,1,0)", updater.parse_version("5.1") == (5, 1, 0))
    check("P1c `5.0.7-beta.1` 取前三段",
          updater.parse_version("5.0.7-beta.1") == (5, 0, 7))
    check("P1d 空/脏 -> ()",
          updater.parse_version("") == () and updater.parse_version(None) == ())
    check("P2 5.0.7 比 5.0.6 新", updater.is_newer("5.0.7", "5.0.6") is True)
    check("P2b 5.0.6 不比 5.0.6 新", updater.is_newer("5.0.6", "5.0.6") is False)
    check("P2c 5.0.10 > 5.0.9（按数字比，不是按字符串）",
          updater.is_newer("5.0.10", "5.0.9") is True)
    check("P2d 6.0.0 > 5.9.9", updater.is_newer("6.0.0", "5.9.9") is True)
    check("P2e 脏版本号一律 False", updater.is_newer("", "5.0.6") is False)

    # ---------- P3 release_of ----------
    info = updater.release_of({
        "tag_name": "v6.0.0", "html_url": "https://github.com/x/y/releases/tag/v6.0.0",
        "body": "notes here", "published_at": "2026-10-24T00:00:00Z"})
    check("P3 release_of 取版本/链接/说明",
          info["version"] == "6.0.0" and info["tag"] == "v6.0.0"
          and info["notes"] == "notes here" and "releases" in info["url"], str(info))
    bad = updater.release_of(None)
    check("P3b 脏数据返回空 dict（不抛）", bad == {})
    check("P3c 没有 html_url 时回退 releases 页面",
          updater.release_of({"tag_name": "v1.0.0"})["url"] == updater.RELEASES_URL)

    # ---------- P4 fetch_latest ----------
    payload = json.dumps({"tag_name": "v6.1.0", "body": "hello",
                          "html_url": "https://example.invalid/r"}).encode("utf-8")
    got = updater.fetch_latest(opener=lambda req, timeout=0: FakeResp(payload))
    check("P4 fetch_latest 解析成功", got["version"] == "6.1.0", str(got))

    # ---------- P5 错误文案 ----------
    def _boom(req, timeout=0):
        raise urllib.error.URLError("timed out")

    try:
        updater.fetch_latest(opener=_boom)
        check("P5 网络错误抛 UpdaterError", False, "没抛")
    except updater.UpdaterError as exc:
        check("P5 网络错误抛 UpdaterError（人话：超时）",
              "超时" in str(exc), str(exc))

    def _404(req, timeout=0):
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)

    try:
        updater.fetch_latest(opener=_404)
        check("P5b 404 抛 UpdaterError", False, "没抛")
    except updater.UpdaterError as exc:
        check("P5b 404 -> 提示仓库没有 Release", "Release" in str(exc), str(exc))
    try:
        updater.fetch_latest(opener=lambda req, timeout=0: FakeResp(b"not json"))
        check("P5c 非法 JSON 抛 UpdaterError", False, "没抛")
    except updater.UpdaterError as exc:
        check("P5c 非法 JSON -> 提示内容不合法", "JSON" in str(exc), str(exc))

    # ---------- P6 / P7 / P8 UpdateChecker ----------
    seen = []
    checker = updater.UpdateChecker(current="5.0.6")
    checker.finished.connect(lambda i: seen.append(("ok", i)))
    checker.failed.connect(lambda m: seen.append(("fail", m)))
    checker._fetcher = lambda timeout=8.0: {
        "version": "6.0.0", "url": "https://example.invalid/r", "notes": "n"}
    checker.check()
    for _ in range(100):
        if seen:
            break
        QTest.qWait(20)
    check("P6 成功发 finished", bool(seen) and seen[0][0] == "ok", str(seen))
    check("P6b newer 标记按当前版本算",
          bool(seen) and seen[0][1].get("newer") is True,
          str(seen[0][1] if seen else None))
    check("P6c 带上 current 供界面显示",
          bool(seen) and seen[0][1].get("current") == "5.0.6")

    seen.clear()
    checker2 = updater.UpdateChecker(current="5.0.6")
    checker2.finished.connect(lambda i: seen.append(("ok", i)))
    checker2.failed.connect(lambda m: seen.append(("fail", m)))

    def _raise(timeout=8.0):
        raise updater.UpdaterError("连接超时，请检查网络或代理")

    checker2._fetcher = _raise
    checker2.check()
    for _ in range(100):
        if seen:
            break
        QTest.qWait(20)
    check("P7 失败发 failed（不静默）",
          bool(seen) and seen[0][0] == "fail" and "超时" in seen[0][1], str(seen))

    seen.clear()
    started = []

    def _slow(timeout=8.0):
        started.append(1)
        QTest.qWait(120)
        return {"version": "5.0.6", "url": "", "notes": ""}

    checker3 = updater.UpdateChecker(current="5.0.6")
    checker3._fetcher = _slow
    first = checker3.check()
    second = checker3.check()
    check("P8 连点：第一次 true / 第二次 false（防重入）",
          first is True and second is False, "%s %s" % (first, second))
    for _ in range(100):
        if not checker3.busy:
            break
        QTest.qWait(20)
    check("P8b 检查结束后 busy 复位", checker3.busy is False)

    # ---------- P9 链接 ----------
    urls = {k: u for k, _label, u in updater.AUTHOR_LINKS}
    check("P9 抖音链接是用户给的",
          urls.get("douyin", "").startswith("https://www.douyin.com/user/")
          and "MS4wLjABAAAAcYd6aSteDxtAI4GIXIvBfld4o3lrOXjDhy5wv5J7K80"
          in urls.get("douyin", ""), urls.get("douyin", ""))
    check("P9b B站链接是用户给的",
          urls.get("bilibili", "").startswith("https://space.bilibili.com/21785702"),
          urls.get("bilibili", ""))
    check("P9c 项目地址指向仓库",
          updater.PROJECT_URL == "https://github.com/" + updater.REPO,
          updater.PROJECT_URL)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    main(app)
    print("-" * 56)
    if failures:
        print("FAILED %d: %s" % (len(failures), failures))
        sys.exit(1)
    print("ALL updater PASSED")
