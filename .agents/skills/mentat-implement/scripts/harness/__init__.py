"""Shared types for mentat-implement harness adapters."""

from __future__ import annotations

from typing import Any


class Result:
    def __init__(self, returncode: int, agent_log: Any = None, usage_tokens: int | None = None) -> None:
        self.returncode = returncode
        self.agent_log = agent_log
        self.usage_tokens = usage_tokens
