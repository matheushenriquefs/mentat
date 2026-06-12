"""ADR-0007 envelope emitter. Stdlib only."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable

from lib import paths


def _spawn(skill: str, event: str, payload: dict[str, object]) -> None:
    r = subprocess.run(
        ["python3", str(paths.LOG_SCRIPT), "emit", skill, event, json.dumps(payload)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        tail = (r.stderr or "").strip().splitlines()[-1:] or ["(no stderr)"]
        print(f"{skill}: emit {event!r} failed rc={r.returncode}: {tail[0]}", file=sys.stderr)


def bind(skill: str) -> Callable[[str, dict[str, object]], None]:
    def emit(event: str, payload: dict[str, object]) -> None:
        _spawn(skill, event, payload)

    return emit
