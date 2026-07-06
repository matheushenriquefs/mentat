"""Shared helpers for mentat-implement."""

from __future__ import annotations

import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))
_SESSIONS_SCRIPTS = Path(__file__).resolve().parents[2] / "mentat-session" / "scripts"
if str(_SESSIONS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SESSIONS_SCRIPTS))

import sessions  # noqa: E402
from lib import harness_stream  # noqa: E402
from lib.config import read_config  # noqa: E402


def default_harness() -> str:
    harness = read_config().get("harness", "claude-code")
    return harness if isinstance(harness, str) else "claude-code"


def detect_self_answer(session_log_path: Path | str | None) -> bool:
    """Return True if any assistant turn invoked AskUserQuestion.

    The AskUserQuestion stream-json shape is owned by `lib.harness_stream`; this
    scans the captured session log (written when MENTAT_SESSION_LOG is set) for
    any such row — the self-answer signal for AFK plans (eject with exit 42).
    """
    if not session_log_path:
        return False
    path = Path(session_log_path)
    if not path.exists():
        return False
    return any(harness_stream.is_ask_user_question(row) for row in sessions.iter_rows(path))
