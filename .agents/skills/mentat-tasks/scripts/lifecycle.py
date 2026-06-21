"""Task utilities: tasks_dir, now_rfc3339, next_id."""

from __future__ import annotations

import datetime
import os
from pathlib import Path


def tasks_dir() -> Path:
    root = os.environ.get("MENTAT_TASKS_DIR")
    if root:
        return Path(root)
    return Path.cwd() / ".mentat" / "tasks"


def now_rfc3339(ttl_seconds: int = 0) -> str:
    t = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=ttl_seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def next_id(td: Path) -> str:
    ids: list[int] = []
    for f in td.glob("T*-*.md"):
        m = f.name.split("-", 1)[0]
        if m.startswith("T") and m[1:].isdigit():
            ids.append(int(m[1:]))
    return f"T{(max(ids) + 1) if ids else 1:03d}"
