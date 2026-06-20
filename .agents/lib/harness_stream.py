"""Harness stream-json (NDJSON) row helpers. One owner of the wire schema.

Harness adapters (claude_code / cursor) write NDJSON when MENTAT_SESSION_LOG is
set: rows where `type == "assistant"` carry `message.content[*]` blocks. This is
the single place that knows that shape — consumers (self-answer detection,
session-status pull) call these instead of re-parsing it. Stdlib only.
"""

from __future__ import annotations

from typing import cast


def _field(obj: object, key: str) -> object:
    """Value at `key` if `obj` is a dict, else None — no Unknown leaks."""
    return cast("dict[str, object]", obj).get(key) if isinstance(obj, dict) else None


def is_ask_user_question(row: object) -> bool:
    """True if an assistant stream row carries an AskUserQuestion tool_use block.

    For AFK plans this is the self-answer signal (the agent asked instead of
    ejecting); for live tracking it means the session is blocked on the operator.
    """
    if _field(row, "type") != "assistant":
        return False
    content = _field(_field(row, "message"), "content")
    if not isinstance(content, list):
        return False
    blocks = cast("list[object]", content)
    return any(_field(b, "type") == "tool_use" and _field(b, "name") == "AskUserQuestion" for b in blocks)
