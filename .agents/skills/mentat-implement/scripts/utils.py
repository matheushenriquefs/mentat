"""Shared helpers for mentat-implement."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


def read_config() -> dict:
    config_path = Path.home() / ".mentat" / "config.jsonc"
    if not config_path.exists():
        return {}
    text = "\n".join(
        line for line in config_path.read_text().splitlines()
        if not line.lstrip().startswith("//")
    )
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def default_harness() -> str:
    return read_config().get("harness", "claude-code")


def detect_self_answer(session_log_path: Path) -> bool:
    """Return True if assistant turn contains a self-answered question pattern."""
    if not session_log_path or not Path(session_log_path).exists():
        return False
    pattern = re.compile(r"Q:\s*.+\?\s*A:", re.IGNORECASE)
    for line in Path(session_log_path).read_text().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        content = row.get("content", "")
        if isinstance(content, str) and pattern.search(content):
            return True
    return False
