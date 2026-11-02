# -*- coding: utf-8 -*-
"""通过 GitHub API 提交文件（绕开被墙的 github.com，只走 api.github.com）。

用法：先设环境变量 GH_TOKEN，然后 python push_via_api.py
只提交本地改动过的文件（按相对路径列表）。
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO = "congmingren-music/432hz-studio"
BRANCH = "main"
API = "https://api.github.com"

FILES = [
    "musicxml.py",
    "server.py",
    "test-dual.xml",
    "midi.py",
    "render_api.py",
    "studio.html",
    "test-twinkle.mid",
    "gen_intro_video2.py",
    "gen_intro_video3.py",
    "lines.txt",
    "make_cover.py",
    "make_voice.ps1",
]

MSG = "模型加十二宫位选择与播放间隔控制"


def req(method, url, token, data=None):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    r = urllib.request.Request(url, data=body, method=method)
    r.add_header("Authorization", f"token {token}")
    r.add_header("User-Agent", "dsh")
    r.add_header("Accept", "application/vnd.github+json")
    if body:
        r.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8")[:200]
        except Exception:
            detail = ""
        return None, f"HTTP {e.code} {detail}"
    except Exception as e:
        return None, str(e)[:150]


def main():
    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        print("缺少 GH_TOKEN")
        return 1

    base = os.path.dirname(os.path.abspath(__file__))
    targets = sys.argv[1:] or FILES
    ok = fail = 0
    sha_map = {}

    for path in targets:
        local = os.path.join(base, path)
        if not os.path.exists(local):
            print(f"  跳过（本地不存在）: {path}")
            continue

        # 已有文件的 sha（更新必需）
        meta, err = req("GET", f"{API}/repos/{REPO}/contents/{urllib.parse.quote(path)}?ref={BRANCH}", token)
        sha = meta["sha"] if meta else None

        with open(local, "rb") as f:
            content = base64.b64encode(f.read()).decode("ascii")

        payload = {
            "message": f"{MSG} · {path}",
            "content": content,
            "branch": BRANCH,
        }
        if sha:
            payload["sha"] = sha

        res, err = req("PUT", f"{API}/repos/{REPO}/contents/{urllib.parse.quote(path)}", token, payload)
        if res:
            ok += 1
            print(f"  ok   {path}")
            commit_sha = res["commit"]["sha"]
            sha_map[path] = commit_sha
        else:
            fail += 1
            print(f"  FAIL {path}  {err}")

    print(f"\n完成：成功 {ok}，失败 {fail}")
    if sha_map:
        print("最后一次提交:", list(sha_map.values())[-1][:10])
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
