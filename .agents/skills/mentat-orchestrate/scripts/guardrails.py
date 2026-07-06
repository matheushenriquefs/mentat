"""Circuit breaker, stall detection, and process-group kill helpers."""

from __future__ import annotations

_POPEN_NEW_GROUP = "start_new_session"

import contextlib
import os
import signal
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lib.agent import agent_dir as _agent_dir


def load_headroom_ok() -> bool:
    """Best-effort advisory: True when the 1-min load average leaves a spare core."""
    try:
        load1 = os.getloadavg()[0]
    except OSError, AttributeError:
        return True
    cores = os.cpu_count() or 1
    return load1 < cores


def chunk_timeout(read_config: Callable[[], dict[str, Any]]) -> int:
    """Wall-clock deadline per chunk in seconds. Default 1800 (30 min)."""
    env_val = os.environ.get("MENTAT_CHUNK_TIMEOUT")
    if env_val is not None:
        try:
            return max(1, int(env_val))
        except ValueError:
            pass
    raw = read_config().get("chunk_timeout", 1800)
    try:
        return max(1, int(raw))
    except TypeError, ValueError:
        return 1800


def stall_timeout(read_config: Callable[[], dict[str, Any]]) -> int:
    """No-progress window per chunk in seconds. Default 300 (5 min); ``<=0`` disables."""
    env_val = os.environ.get("MENTAT_STALL_TIMEOUT")
    if env_val is not None:
        try:
            return int(env_val)
        except ValueError:
            pass
    raw = read_config().get("stall_timeout", 300)
    try:
        return int(raw)
    except TypeError, ValueError:
        return 300


class CircuitBreaker:
    """Nygard circuit breaker over a shared backend (devcontainer daemon / model API)."""

    def __init__(
        self, threshold: int, *, cooldown_s: float = 30.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.threshold = max(1, threshold)
        self.cooldown_s = cooldown_s
        self._clock = clock
        self.state = "closed"
        self.consecutive_failures = 0
        self._opened_at = 0.0
        self._probe_inflight = False

    def allow(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if self._clock() - self._opened_at >= self.cooldown_s:
                self.state = "half_open"
                self._probe_inflight = True
                return True
            return False
        return not self._probe_inflight

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self._probe_inflight = False
        self.state = "closed"

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        self._probe_inflight = False
        if self.consecutive_failures >= self.threshold:
            self.state = "open"
            self._opened_at = self._clock()

    def record_abandoned(self) -> None:
        if self.state == "half_open":
            self._probe_inflight = False
            self.state = "open"
            self._opened_at = self._clock()


def breaker_threshold(read_config: Callable[[], dict[str, Any]]) -> int:
    raw = read_config().get("breaker_threshold", 3)
    try:
        return max(1, int(raw))
    except TypeError, ValueError:
        return 3


def breaker_cooldown(read_config: Callable[[], dict[str, Any]]) -> float:
    raw = read_config().get("breaker_cooldown", 30)
    try:
        return max(0.0, float(raw))
    except TypeError, ValueError:
        return 30.0


def make_breaker(read_config: Callable[[], dict[str, Any]]) -> CircuitBreaker:
    return CircuitBreaker(breaker_threshold(read_config), cooldown_s=breaker_cooldown(read_config))


def event_age(agent_id: str, *, agent_dir_fn: Callable[[str], Path] | None = None) -> float | None:
    resolve = agent_dir_fn or _agent_dir
    log = resolve(agent_id) / "transcript.jsonl"
    try:
        return max(0.0, time.time() - log.stat().st_mtime)
    except OSError:
        return None


def kill_proc_group(proc: object) -> None:
    pid = getattr(proc, "pid", None)
    if pid is None:
        with contextlib.suppress(Exception):
            proc.kill()  # type: ignore[attr-defined]
        return
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError, OSError:
        with contextlib.suppress(Exception):
            proc.kill()  # type: ignore[attr-defined]
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pgid, signal.SIGKILL)
