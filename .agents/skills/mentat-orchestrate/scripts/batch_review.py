"""End-of-queue advisory batch review."""

from __future__ import annotations

import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.events import bind  # noqa: E402

_emit_event = bind("mentat-orchestrate")


def review(session_id: str) -> dict:
    """Run advisory batch review. Emits batch.reviewed. Returns summary."""
    summary = f"batch review for session {session_id} — advisory"
    _emit_event(
        "batch.reviewed",
        {
            "session": session_id,
            "summary": summary,
        },
    )
    return {"session": session_id, "summary": summary}
