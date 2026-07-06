"""Capped exponential backoff with full jitter (AWS "Exponential Backoff And Jitter").

Stdlib only. Used to space the recovery engine's respawn attempts so a fleet of
chunks recovering from the same shared-backend outage does not re-collide in a
synchronized thundering herd. Full jitter (delay drawn uniformly from
``[0, ceiling)``) de-correlates retries better than equal/decorrelated jitter for
this workload — see the AWS Architecture Blog.
"""

from __future__ import annotations

import random
from collections.abc import Callable


def full_jitter(
    attempt: int,
    *,
    base: float = 0.5,
    cap: float = 30.0,
    rng: Callable[[], float] = random.random,
) -> float:
    """Return a jittered backoff delay in seconds for a zero-based ``attempt``.

    The exponential ceiling ``base * 2**attempt`` is clamped to ``cap`` (so the
    delay never exceeds ``cap``), then the returned delay is drawn uniformly from
    ``[0, ceiling)`` via ``rng`` — AWS "full jitter". Two successive calls at the
    same attempt therefore differ, which is the point: it breaks the synchronized
    retry herd. ``rng`` is injectable for deterministic tests.

    A negative ``attempt`` is floored to 0. ``cap`` also floors the ceiling from
    below at 0 so a nonsensical negative cap can't produce a negative delay.
    """
    attempt = max(0, attempt)
    ceiling = min(cap, base * (2**attempt))
    ceiling = max(0.0, ceiling)
    return rng() * ceiling
