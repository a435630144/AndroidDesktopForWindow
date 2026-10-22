# -*- coding: utf-8 -*-
"""发布 GitHub Release：建 release + 上传附件（zip / Setup.exe）。

前置：提交与 SEMVER tag 都已推到 origin（本脚本只碰 release，不碰 git）。

用法：
    python tools/publish_release.py 4.0.0 \
        --name "v4.0.0 · 手机式桌面整理（内部版本 v9a）" \
        --notes docs/release_notes/4.0.0.md \
        dist/PhoneDesktop_v9a_Portable.zip \
        dist/PhoneDesktop_v9a_Setup.exe

说明：
- 认证走 git 凭据管理器里 github.com 的 token（`git credential fill`），**不读环境变量、
  不落盘**；`gh` CLI 未登录，别用它。
- 附件名默认取文件名；重名附件（同 tag 再发一次）会被 GitHub 拒绝，需先删旧 asset。
- release 不存在则新建；已存在则复用（只补传缺失的附件）。
"""
import argparse
import json
import mimetypes
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

OWNER_REPO = "a435630144/PhoneDesktopForWindow"
API = "https://api.github.com/repos/%s" % OWNER_REPO
UPLOADS = "https://uploads.github.com/repos/%s" % OWNER_REPO


def token():
    """从 git 凭据管理器取 github.com 的 token（只进内存，不打印）。"""
    out = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True, text=True, check=True,
    ).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line[len("password="):]
    raise SystemExit("凭据管理器里没有 github.com 的 token（git credential fill 为空）")


def call(method, url, tok, payload=None, raw=None, headers=None, timeout=600):
    h = {"Authorization": "token " + tok,
         "Accept": "application/vnd.github+json",
         "User-Agent": "deskorg-publish-release"}
    h.update(headers or {})
    body = payload if payload is not None else raw
    if isinstance(body, str):
        body = body.encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode("utf-8")
            return json.loads(txt) if txt.strip() else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:600]
        raise SystemExit("HTTP %s %s\n%s" % (e.code, url, detail))


def find_release(tok, tag):
    for rel in call("GET", API + "/releases?per_page=100", tok):
        if rel.get("tag_name") == tag:
            return rel
    return None


def main():
    ap = argparse.ArgumentParser(description="发布 GitHub Release 并上传附件")
    ap.add_argument("tag", help="SEMVER tag，需已推到 origin（如 4.0.0）")
    ap.add_argument("--name", default=None, help="release 标题，默认用 tag")
    ap.add_argument("--notes", default=None, help="release 说明（markdown 文件路径）")
    ap.add_argument("--body", default=None, help="release 说明（直接给文本）")
    ap.add_argument("--target", default="main", help="tag 不存在时基于哪个分支")
    ap.add_argument("--prerelease", action="store_true")
    ap.add_argument("assets", nargs="*", help="附件文件路径（可多个）")
    args = ap.parse_args()

    if not args.notes and not args.body:
        raise SystemExit("必须给 --notes <文件> 或 --body <文本>")
    body = args.body if args.body else open(args.notes, encoding="utf-8").read()

    tok = token()
    rel = find_release(tok, args.tag)
    if rel is None:
        rel = call("POST", API + "/releases", tok, payload=json.dumps({
            "tag_name": args.tag,
            "name": args.name or args.tag,
            "body": body,
            "draft": False,
            "prerelease": args.prerelease,
            "target_commitish": args.target,
        }), headers={"Content-Type": "application/json"})
        print("已创建 release：%s" % rel["html_url"])
    else:
        print("release 已存在，复用：%s" % rel["html_url"])

    have = {a["name"] for a in rel.get("assets", [])}
    for path in args.assets:
        if not os.path.isfile(path):
            raise SystemExit("附件不存在：%s" % path)
        name = os.path.basename(path)
        if name in have:
            print("跳过（已存在）：%s" % name)
            continue
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            blob = f.read()
        print("上传 %s（%.1f MB）…" % (name, len(blob) / 1048576))
        call("POST",
             "%s/releases/%d/assets?name=%s" % (UPLOADS, rel["id"], urllib.parse.quote(name)),
             tok, raw=blob, headers={"Content-Type": ctype})
        print("  ok")

    rel2 = call("GET", "%s/releases/%d" % (API, rel["id"]), tok)
    print("附件清单：%s" % ", ".join(a["name"] for a in rel2["assets"]))
    print("完成：%s" % rel2["html_url"])


if __name__ == "__main__":
    main()
