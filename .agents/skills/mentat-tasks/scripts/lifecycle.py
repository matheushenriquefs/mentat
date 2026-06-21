"""Task utilities: tasks_dir, now_rfc3339, next_id, transition guard."""

from __future__ import annotations

import datetime
import os
from pathlib import Path

LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "todo": frozenset({"in-progress"}),
    "in-progress": frozenset({"done", "wontfix", "blocked"}),
    "blocked": frozenset({"in-progress", "done", "wontfix"}),
    "done": frozenset(),
    "wontfix": frozenset(),
}


def check_transition(current: str, target: str) -> str | None:
    """Return an error message if the transition is illegal, else None."""
    legal = LEGAL_TRANSITIONS.get(current, frozenset())
    if target not in legal:
        return f"illegal transition {current!r} → {target!r}"
    return None


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
