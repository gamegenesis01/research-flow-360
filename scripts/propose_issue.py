#!/usr/bin/env python3
"""Send a finished Research Flow 360 issue to GitHub for the editor's approval.

    export GITHUB_TOKEN=...            # fine-grained token: this repo only, Contents + Pull requests read/write
    python3 propose_issue.py issues/2026-11-30.md

What it does:
  1. Checks the file name and header (date must match the file name, title present).
  2. Creates a branch from main, e.g. issue-2026-11-30-0645.
  3. Adds (or updates) the file at issues/<name>.md on that branch.
  4. Opens a pull request for the editor and prints its link.

Nothing is published until the editor merges the pull request.
Python 3.9+ standard library only. Works from any folder; it does not need a copy of the repository.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = os.environ.get("RF360_REPO", "gamegenesis01/research-flow-360")
API = f"https://api.github.com/repos/{REPO}"
NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(-[a-z0-9-]+)?\.md$")


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def call(method: str, path: str, token: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "research-flow-360-propose"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        if e.code == 404 and method == "GET":
            return {"__missing__": True}
        die(f"GitHub {method} {path} failed ({e.code}): {detail[:400]}")
    return {}


def check_issue(path: Path) -> tuple[str, str]:
    m = NAME_RE.match(path.name)
    if not m:
        die(f"{path.name}: file name must look like 2026-11-30.md or 2026-11-30-alert.md")
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        die(f"{path.name}: must start with a header block between two --- lines")
    head = text[4:].split("\n---\n", 1)[0]
    meta = {}
    for line in head.splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.split(" #", 1)[0].strip()
    if meta.get("date") != m.group(1):
        die(f"{path.name}: 'date:' in the header must be {m.group(1)}")
    if not meta.get("title"):
        die(f"{path.name}: 'title:' is missing")
    if "## " not in text:
        die(f"{path.name}: needs at least one '## ' section")
    return meta["title"].replace("*", ""), meta.get("type", "daily")


def main() -> None:
    if len(sys.argv) != 2:
        die("usage: python3 propose_issue.py issues/2026-11-30.md")
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        die("set GITHUB_TOKEN to Muse's fine-grained token first")
    path = Path(sys.argv[1])
    if not path.is_file():
        die(f"file not found: {path}")
    title, kind = check_issue(path)

    stamp = datetime.now().strftime("%H%M")
    branch = f"issue-{path.stem}-{stamp}"
    main_sha = call("GET", "/git/ref/heads/main", token)["object"]["sha"]
    call("POST", "/git/refs", token, {"ref": f"refs/heads/{branch}", "sha": main_sha})

    target = f"issues/{path.name}"
    existing = call("GET", f"/contents/{target}?ref={branch}", token)
    body = {"message": f"Issue {path.stem}: {title}", "branch": branch,
            "content": base64.b64encode(path.read_bytes()).decode()}
    if not existing.get("__missing__") and existing.get("sha"):
        body["sha"] = existing["sha"]  # updating an issue that is already published
    call("PUT", f"/contents/{target}", token, body)

    label = {"daily": "Daily Brief", "alert": "Breaking alert", "wrap": "Weekend Wrap",
             "inside": "Inside Accel Trading"}.get(kind, "Issue")
    pr = call("POST", "/pulls", token, {
        "title": f"{label} {path.stem}: {title}",
        "head": branch, "base": "main",
        "body": ("Ready for the editor's review.\n\n"
                 "Check the automatic **Check issue** result, read **Files changed**, then merge to publish.")})
    print(f"Pull request opened: {pr.get('html_url')}")


if __name__ == "__main__":
    main()
