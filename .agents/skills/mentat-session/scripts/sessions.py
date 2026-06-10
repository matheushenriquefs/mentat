"""Session directory helpers."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path


def latest_session(repo_dir: Path) -> str | None:
    """Return the most recently modified session dir, excluding 'manual'."""
    dirs = [d for d in repo_dir.iterdir() if d.is_dir() and d.name != "manual"]
    if not dirs:
        return None
    return max(dirs, key=lambda d: d.stat().st_mtime).name


def sessions_for_repo(repo_dir: Path) -> list[str]:
    return [d.name for d in repo_dir.iterdir() if d.is_dir() and d.name != "manual"]


def chunks_in_session(session_dir: Path) -> list[Path]:
    return list(session_dir.glob("*.jsonl"))


def slug_for_chunk(file: Path) -> str:
    return file.stem


def last_event(session_dir: Path) -> dict | None:
    events: list[dict] = []
    for log_file in session_dir.glob("*.jsonl"):
        for line in log_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            with contextlib.suppress(json.JSONDecodeError):
                events.append(json.loads(line))
    if not events:
        return None
    return sorted(events, key=lambda e: e.get("ts", ""))[-1]


def all_events(session_dir: Path) -> list[dict]:
    events: list[dict] = []
    for log_file in sorted(session_dir.glob("*.jsonl")):
        for line in log_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            with contextlib.suppress(json.JSONDecodeError):
                events.append(json.loads(line))
    return sorted(events, key=lambda e: e.get("ts", ""))
