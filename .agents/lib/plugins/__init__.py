"""Mentat plugin API — Vite-derived, 2 slots: diff + harness.

See docs/PLUGINS.md and ADR-0009 for design rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@runtime_checkable
class DiffProvider(Protocol):
    """Provides the diff text for a worktree."""

    def get_diff(self, worktree: str) -> str: ...


@runtime_checkable
class HarnessProvider(Protocol):
    """Provides the harness adapter name and invocation."""

    name: str

    def invoke(self, cmd: list[str]) -> int: ...


@dataclass
class MentatPlugin:
    """Single plugin registration.

    A plugin may fill the diff slot, the harness slot, or both.
    First plugin that fills a slot wins (ADR-0009).
    """

    name: str
    diff: DiffProvider | None = field(default=None)
    harness: HarnessProvider | None = field(default=None)
