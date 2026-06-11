"""Shared helpers for mentat-implement."""

from __future__ import annotations

import json
from pathlib import Path


def read_config() -> dict:
    config_path = Path.home() / ".mentat" / "config.jsonc"
    if not config_path.exists():
        return {}
    text = "\n".join(line for line in config_path.read_text().splitlines() if not line.lstrip().startswith("//"))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def default_harness() -> str:
    return read_config().get("harness", "claude-code")


def detect_self_answer(session_log_path: Path | str | None) -> bool:
    """Return True if any assistant turn invoked AskUserQuestion.

    Parses the stream-json schema written by harness adapters (claude_code /
    cursor) when MENTAT_SESSION_LOG is set: NDJSON rows where
    `type == "assistant"` carry `message.content[*]` blocks; a `tool_use`
    block with `name == "AskUserQuestion"` is the self-answer signal for AFK
    plans (AFK ejects with exit 42 when seen).
    """
    if not session_log_path:
        return False
    path = Path(session_log_path)
    if not path.exists():
        return False
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or row.get("type") != "assistant":
            continue
        message = row.get("message") or {}
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "AskUserQuestion":
                return True
    return False
