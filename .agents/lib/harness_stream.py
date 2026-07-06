"""Harness stream-json (NDJSON) row helpers. One owner of the wire schema.

Harness adapters (claude_code / cursor) write NDJSON when MENTAT_AGENT_LOG is
set: rows where `type == "assistant"` carry `message.content[*]` blocks. This is
the single place that knows that shape — consumers (self-answer detection,
agent-status pull) call these instead of re-parsing it. Stdlib only.
"""

from __future__ import annotations

from typing import cast


def _field(obj: object, key: str) -> object:
    """Value at `key` if `obj` is a dict, else None — no Unknown leaks."""
    return cast("dict[str, object]", obj).get(key) if isinstance(obj, dict) else None


def tool_uses(row: object) -> list[str]:
    """Tool-call names invoked in one assistant stream row, in order (empty if none).

    The live tracker renders these; `is_ask_user_question` is the AskUserQuestion
    case of this — both read the same wire shape so the schema lives in one place.
    """
    if _field(row, "type") != "assistant":
        return []
    content = _field(_field(row, "message"), "content")
    if not isinstance(content, list):
        return []
    names: list[str] = []
    for b in cast("list[object]", content):
        if _field(b, "type") == "tool_use":
            name = _field(b, "name")
            if isinstance(name, str):
                names.append(name)
    return names


def is_ask_user_question(row: object) -> bool:
    """True if an assistant stream row carries an AskUserQuestion tool_use block.

    For AFK plans this is the self-answer signal (the agent asked instead of
    ejecting); for live tracking it means the agent is blocked on the operator.
    """
    return "AskUserQuestion" in tool_uses(row)


def assistant_text(row: object) -> str:
    """Concatenated text content from one assistant stream row (empty if none)."""
    if _field(row, "type") != "assistant":
        return ""
    content = _field(_field(row, "message"), "content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for b in cast("list[object]", content):
        if _field(b, "type") == "text":
            t = _field(b, "text")
            if isinstance(t, str):
                parts.append(t)
    return "".join(parts)


def tool_result(row: object) -> str:
    """Brief summary of tool result content from one user stream row (empty if none)."""
    if _field(row, "type") != "user":
        return ""
    content = _field(_field(row, "message"), "content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for b in cast("list[object]", content):
        if _field(b, "type") == "tool_result":
            inner = _field(b, "content")
            if isinstance(inner, str):
                parts.append(inner[:200])
            elif isinstance(inner, list):
                for ib in cast("list[object]", inner):
                    if _field(ib, "type") == "text":
                        t = _field(ib, "text")
                        if isinstance(t, str):
                            parts.append(t[:100])
    return " ".join(parts)[:300]
