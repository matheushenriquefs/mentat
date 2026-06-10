"""End-of-queue advisory final review."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import utils as _utils


def _emit_event(event: str, payload: dict) -> None:
    _utils.emit_event(event, payload)


def review(session_id: str) -> dict:
    """Run advisory final review. Emits batch.reviewed. Returns summary."""
    summary = f"batch review for session {session_id} — advisory"
    _emit_event("batch.reviewed", {
        "session": session_id,
        "summary": summary,
    })
    return {"session": session_id, "summary": summary}
