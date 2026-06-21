"""Mentat plugin API — Vite-derived, 1 slot: harness.

See docs/PLUGINS.md and ADR-0009 for design rationale.
HarnessProvider is documented-future-API — the real adapters live at
implement/scripts/harness/; wiring through the Protocol is deferred to F5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@runtime_checkable
class HarnessProvider(Protocol):
    """Provides the harness adapter name and invocation."""

    name: str

    def invoke(self, cmd: list[str]) -> int: ...


@dataclass
class MentatPlugin:
    """Single plugin registration.

    A plugin may fill the harness slot.
    First plugin that fills a slot wins (ADR-0009).
    """

    name: str
    harness: HarnessProvider | None = field(default=None)
