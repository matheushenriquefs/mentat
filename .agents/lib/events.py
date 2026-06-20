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


def ejected_payload(
    slug: str,
    reason: str,
    where: str,
    *,
    logs_path: str | None = None,
    preflight_exit: int | None = None,
    upstream: str | None = None,
) -> dict[str, object]:
    """Build the one canonical ``chunk.ejected`` payload.

    Base shape ``{slug, reason, where}`` for every ejection regardless of caller;
    the optional fields (``logs_path``, ``preflight_exit``, ``upstream``) are
    included only when set. These optionals are declared in mentat-log's
    ``EVENT_OPTIONAL_FIELDS`` — a payload extension, not a new event type (the
    9-event catalog is unchanged).
    """
    payload: dict[str, object] = {"slug": slug, "reason": reason, "where": where}
    if logs_path is not None:
        payload["logs_path"] = logs_path
    if preflight_exit is not None:
        payload["preflight_exit"] = preflight_exit
    if upstream is not None:
        payload["upstream"] = upstream
    return payload
