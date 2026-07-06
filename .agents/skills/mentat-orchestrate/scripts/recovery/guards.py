"""Recovery guardrails: attempt caps, storm intensity, and budget ceilings."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable

from lib import config as _config

DEFAULT_ATTEMPTS = 2
DEFAULT_MAX_RESTARTS = 3
DEFAULT_RESTART_WINDOW = 60.0


def _int_config(key: str, default: int, *, minimum: int = 1) -> int:
    raw = _config.read_config().get(key, default)
    try:
        return max(minimum, int(raw))
    except TypeError, ValueError:
        return default


def recovery_attempts() -> int:
    """Per-slug recovery attempt cap. Config ``recovery_attempts`` (default 2, min 1)."""
    return _int_config("recovery_attempts", DEFAULT_ATTEMPTS)


def recovery_max_restarts() -> int:
    """Batch-wide restart-storm intensity: max respawns per window. Config
    ``recovery_max_restarts`` (default 3, min 1) — the OTP supervisor ``MaxR``."""
    return _int_config("recovery_max_restarts", DEFAULT_MAX_RESTARTS)


def recovery_restart_window() -> float:
    """The storm window in seconds — the OTP ``MaxT``. Config
    ``recovery_restart_window`` (default 60)."""
    raw = _config.read_config().get("recovery_restart_window", DEFAULT_RESTART_WINDOW)
    try:
        return max(0.0, float(raw))
    except TypeError, ValueError:
        return DEFAULT_RESTART_WINDOW


def recovery_budget() -> float | None:
    """Accumulated recovery-cost ceiling for the batch, or None (unlimited). Config
    ``recovery_budget`` — a soft OpenHands-style cost cap (unit-agnostic: respawns
    by default; a caller may charge tokens/wall instead)."""
    raw = _config.read_config().get("recovery_budget")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except TypeError, ValueError:
        return None


class StormGuard:
    """OTP-style restart-intensity limiter (Erlang ``MaxR``/``MaxT``).

    Allows at most ``max_restarts`` respawns within any ``window_s`` sliding window
    across the whole batch. When the window is saturated the batch stops recovering
    and escalates the remainder rather than restart-storming a sick box — the same
    "give up, don't loop" contract an OTP supervisor enforces on its children.
    ``clock`` is injectable for deterministic tests."""

    def __init__(self, max_restarts: int, window_s: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.max_restarts = max(1, max_restarts)
        self.window_s = window_s
        self._clock = clock
        self._stamps: list[float] = []

    def allow(self) -> bool:
        now = self._clock()
        self._stamps = [t for t in self._stamps if now - t <= self.window_s]
        return len(self._stamps) < self.max_restarts

    def record(self) -> None:
        self._stamps.append(self._clock())


class Budget:
    """Accumulated-cost ceiling for a batch's recovery (OpenHands-style).

    ``allow(cost)`` gates the next respawn; ``spend(cost)`` accrues. ``total`` None
    means unlimited. Cost is unit-agnostic — the caller decides whether one unit is
    one respawn, N tokens, or N seconds."""

    def __init__(self, total: float | None = None) -> None:
        self.total = total
        self.spent = 0.0

    def allow(self, cost: float = 1.0) -> bool:
        return self.total is None or self.spent + cost <= self.total

    def spend(self, cost: float = 1.0) -> None:
        self.spent += cost


def notify(message: str) -> None:
    """Surface an escalation to the operator. Stderr today (audit is the durable
    record); a single seam so a future push/notify backend has one call site."""
    print(f"mentat-recover: ESCALATE — {message}", file=sys.stderr)


def attempt_count(agent_id: str, slug: str) -> int:
    """Prior recovery respawns for ``slug``, replayed from the canonical store."""
    from lib import store

    return store.attempt_count(agent_id, slug)
