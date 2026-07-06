"""Gate engine: Protocol + evaluate. Stdlib only."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_AGENTS_ROOT = Path(__file__).resolve().parents[2]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.gates.code import precommit as _precommit  # noqa: E402
from lib.gates.code import smells as _smells  # noqa: E402
from lib.gates import drift_lint as _drift_lint  # noqa: E402


@dataclass(frozen=True)
class GateContext:
    chunk_path: Path


class Gate(Protocol):
    id: str
    priority: int

    def run(self, ctx: GateContext) -> tuple[str, str]: ...


_GATES: list[Gate] = [_drift_lint.gate, _precommit.gate, _smells.gate]


def evaluate(chunk_path: Path, *, _gates: list[Gate] | None = None) -> tuple[str, str]:
    """Run all gates in priority order. Short-circuits on first block."""
    gates = sorted(_gates if _gates is not None else _GATES, key=lambda g: g.priority)
    ctx = GateContext(chunk_path=chunk_path)
    for g in gates:
        verdict, msg = g.run(ctx)
        if verdict == "block":
            return ("block", msg)
    return ("pass", "")
