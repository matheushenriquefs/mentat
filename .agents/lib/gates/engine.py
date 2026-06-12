"""Gate engine: Protocol + discover + evaluate. Stdlib only."""

from __future__ import annotations

import importlib.util as _ilu
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_AGENTS_ROOT = Path(__file__).resolve().parents[2]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import paths  # noqa: E402


@dataclass(frozen=True)
class GateContext:
    chunk_path: Path


class Gate(Protocol):
    id: str
    priority: int

    def run(self, ctx: GateContext) -> tuple[str, str]: ...


def _discover() -> list[Gate]:
    gates: list[Gate] = []
    if not paths.GATES_CODE_DIR.exists():
        return gates
    for gate_file in sorted(paths.GATES_CODE_DIR.glob("*.py")):
        if gate_file.stem in ("__init__", "_walk"):
            continue
        key = f"lib.gates.code.{gate_file.stem}"
        if key in sys.modules:
            mod = sys.modules[key]
        else:
            spec = _ilu.spec_from_file_location(key, gate_file)
            mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
            sys.modules[key] = mod
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        if hasattr(mod, "gate"):
            gates.append(mod.gate)
    return gates


def evaluate(chunk_path: Path, *, _gates: list[Gate] | None = None) -> tuple[str, str]:
    """Run all gates in priority order. Short-circuits on first block."""
    gates = sorted(_gates if _gates is not None else _discover(), key=lambda g: g.priority)
    ctx = GateContext(chunk_path=chunk_path)
    for g in gates:
        verdict, msg = g.run(ctx)
        if verdict == "block":
            return ("block", msg)
    return ("pass", "")
