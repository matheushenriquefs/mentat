"""Shared helpers for mentat-orchestrate."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))
from lib import config as _config  # noqa: E402
from lib import frontmatter as _frontmatter  # noqa: E402
from lib import paths  # noqa: E402,F401  # type: ignore[reportUnusedImport]  # pyright: ignore[reportUnusedImport]
from lib import plans as _plans  # noqa: E402
from lib.events import bind  # noqa: E402
from lib.gates import engine as _gate_engine  # noqa: E402

emit_event = bind("mentat-orchestrate")
read_config = _config.read_config


def resolve_plan_ref(ref: str) -> Path:
    return _plans.resolve_plan_ref(ref)


def parse_frontmatter(plan_path: Path) -> dict[str, str]:
    return _frontmatter.parse(plan_path.read_text())[0]


def run_gates(chunk_path: Path | None) -> tuple[str, str]:
    if chunk_path is None:
        return ("block", "gate: no chunk path")
    return _gate_engine.evaluate(chunk_path)


def concurrency_cap() -> int:
    """Max parallel AFK chunk processes / gate workers, clamped to machine headroom.

    Honors ADR-0004 (config default 3) but CLAMPS the configured value to
    ``min(config, max(1, cpu_count // 2))``. One heavy agent per core is the
    timeout root-cause: when the number of concurrent chunks equals the core
    count, every agent starves for CPU and trips its wall/stall deadline on a
    live-but-slow build. Halving the cores reserves headroom for the supervisor,
    the devcontainers, and the host. The clamp is logged so an operator seeing
    an effective cap below their configured ``concurrency`` knows why.

    Shared by the async fan-out (``orchestrate.py``) and the speculative land
    queue (``land_queue.py``) — both honor the same load-headroom guard.
    """
    raw = read_config().get("concurrency", 3)
    try:
        want = max(1, int(raw))
    except TypeError, ValueError:
        want = 3
    cores = os.cpu_count() or 1
    ceiling = max(1, cores // 2)
    effective = min(want, ceiling)
    if effective < want:
        print(
            f"mentat-orchestrate: concurrency clamped {want}→{effective} "
            f"(cpu_count={cores}, headroom=cores//2) — config asked {want}",
            file=sys.stderr,
        )
    return effective
