"""AFK ambiguity wedge: blocked summary read/promote and exit-42 path."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

_AGENTS_ROOT = Path(__file__).resolve().parents[4]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.agent import agent_dir as _agent_dir_fn  # noqa: E402
from lib.agent import summary_file as _summary_file  # noqa: E402
from lib.events import SUMMARY_FILE  # noqa: E402
from lib.support import frontmatter as _frontmatter  # noqa: E402

_BLOCKED_STATUS = "blocked"


def blocked_summary_path() -> Path | None:
    sid = os.environ.get("MENTAT_AGENT")
    if not sid:
        return None
    return _summary_file(sid)


def read_summary_at(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        text = path.read_text()
    except OSError:
        return None
    fm, body_start = _frontmatter.parse(text)
    if str(fm.get("status", "")).strip().lower() != _BLOCKED_STATUS:
        return None
    return "\n".join(text.splitlines()[body_start:]).strip()


def read_blocked_summary(worktree: Path) -> str | None:
    seam = blocked_summary_path()
    if seam is not None:
        result = read_summary_at(seam)
        if result is not None:
            return result
    return read_summary_at(worktree / SUMMARY_FILE)


def promote_blocked_summary(body: str) -> None:
    seam = blocked_summary_path()
    target = seam if seam is not None else _agent_dir_fn(os.environ.get("MENTAT_AGENT", "manual")) / SUMMARY_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"---\nstatus: {_BLOCKED_STATUS}\n---\n{body}\n")


def detect_self_answer(result: Any, *, detect_fn: Any) -> bool:
    agent_log = getattr(result, "agent_log", None)
    if agent_log is None:
        return False
    return bool(detect_fn(Path(agent_log)))


def resolve_wedge(
    result: Any,
    worktree: Path,
    *,
    detect_fn: Any,
) -> str | None:
    """Return blocker body when the AFK agent wedged, else None."""
    blocker = read_blocked_summary(worktree)
    if blocker is not None or detect_self_answer(result, detect_fn=detect_fn):
        return blocker or "AFK ambiguity — self-answer detected in the agent stream."
    return None
