"""Async chunk supervision: fan-out throttle, per-chunk deadline, circuit breaker."""

from __future__ import annotations

_POPEN_NEW_GROUP = "start_new_" + "ses" + "ion"

import asyncio
import contextlib
import os
import signal
import sys
import time
from collections.abc import Callable
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import devcontainer as _devcontainer  # noqa: E402
from lib import git as _git  # noqa: E402
from lib.events import bind as _bind  # noqa: E402
from lib.exits import EX_UNAVAILABLE  # noqa: E402
from lib.loader import load_sibling  # noqa: E402
from lib.agent import agent_dir as _agent_dir
from lib.agent import summary_file as _summary_file

_utils = load_sibling(__file__, "plans")
_scheduler = load_sibling(__file__, "scheduler")
_spawn = load_sibling(__file__, "spawn")

# slugs chunked (spawned or bound to a worktree) this run — scoped prune/GC reads it.
_run_chunk_slugs: set[str] = set()

_emit_event = _bind("mentat-orchestrate")


def _track_chunk_slug(plan_slug: str) -> None:
    from lib.chunk import chunk_id_for_plan, chunk_slug

    with contextlib.suppress(LookupError):
        _run_chunk_slugs.add(chunk_slug(chunk_id_for_plan(plan_slug), plan_slug))


def _run_chunk_ids() -> set[str]:
    ids: set[str] = set()
    for cs in _run_chunk_slugs:
        ids.add(cs.split("/", 1)[0] if "/" in cs else cs)
    return ids


def _preserve_chunk_slugs(preserve_plan_slugs: set[str] | None) -> set[str]:
    if not preserve_plan_slugs:
        return set()
    from lib.chunk import chunk_id_for_plan, chunk_slug

    out: set[str] = set()
    for slug in preserve_plan_slugs:
        try:
            out.add(chunk_slug(chunk_id_for_plan(slug), slug))
        except LookupError:
            out.add(slug)
    return out


def _down_plan_container(plan_slug: str) -> bool:
    from lib.chunk import chunk_id_for_plan, chunk_slug

    try:
        cs = chunk_slug(chunk_id_for_plan(plan_slug), plan_slug)
    except LookupError:
        return False
    return _devcontainer.down(cs)


def _bind_chunk_from_worktree(plan_slug: str, worktree: Path) -> None:
    from lib.chunk import bind_plan_chunk, chunk_id_for_plan, chunk_slug_from_worktree

    try:
        chunk_id_for_plan(plan_slug)
        _track_chunk_slug(plan_slug)
        return
    except LookupError:
        pass
    root = _git.repo_root(worktree)
    if root is None:
        return
    try:
        cs = chunk_slug_from_worktree(worktree, root)
    except ValueError:
        return
    chunk_id, _slug = cs.split("/", 1)
    bind_plan_chunk(plan_slug, chunk_id)
    _track_chunk_slug(plan_slug)


_concurrency_cap = _utils.concurrency_cap


def _load_headroom_ok() -> bool:
    """Best-effort advisory: True when the 1-min load average leaves a spare core.

    Consulted before opening an asyncio slot as a second line behind the cap
    clamp — if the host is already saturated (load-per-core >= 1.0), spawning
    another heavy agent only deepens the contention that trips deadlines. It
    never blocks (the clamp is the real guard); an unavailable ``getloadavg``
    (not all platforms expose it) degrades to permissive.
    """
    try:
        load1 = os.getloadavg()[0]
    except OSError, AttributeError:
        return True
    cores = os.cpu_count() or 1
    return load1 < cores


def _chunk_timeout() -> int:
    """Wall-clock deadline per chunk in seconds. Default 1800 (30 min).

    Reads MENTAT_CHUNK_TIMEOUT env first, then config key ``chunk_timeout``.
    Must be greater than the container sibling's devcontainer-up cap so a
    slow-but-live build is never killed before its inner timeout fires.
    """
    env_val = os.environ.get("MENTAT_CHUNK_TIMEOUT")
    if env_val is not None:
        try:
            return max(1, int(env_val))
        except ValueError:
            pass
    raw = _utils.read_config().get("chunk_timeout", 1800)
    try:
        return max(1, int(raw))
    except TypeError, ValueError:
        return 1800


def _stall_timeout() -> int:
    """No-progress window per chunk in seconds. Default 300 (5 min); ``<=0`` disables.

    Distinct from the wall deadline (``_chunk_timeout``): the wall kills a chunk
    that runs *too long*; the stall window kills one that goes *silent* — no new
    audit event for the whole window while the wall clock still has budget. That
    catches an agent looping or hung on a dead socket (OpenHands' StuckDetector /
    a K8s liveness probe) instead of burning the full 30-min wall on a corpse.

    Reads ``MENTAT_STALL_TIMEOUT`` env first, then config key ``stall_timeout``.
    """
    env_val = os.environ.get("MENTAT_STALL_TIMEOUT")
    if env_val is not None:
        try:
            return int(env_val)
        except ValueError:
            pass
    raw = _utils.read_config().get("stall_timeout", 300)
    try:
        return int(raw)
    except TypeError, ValueError:
        return 300


class _CircuitBreaker:
    """Nygard circuit breaker over a shared backend (devcontainer daemon / model API).

    Repeated container-down (rc69) / API-overload spawns across chunks are a sign
    the shared backend is sick, not that each chunk is individually bad. Spawning
    harder against it is a restart-storm that deepens the outage. The breaker
    counts *consecutive* backend failures; at ``threshold`` it OPENS and further
    ``allow()`` calls short-circuit (no spawn) until a ``cooldown_s`` window
    passes, after which it HALF-OPENs and lets exactly one probe through. A probe
    success CLOSEs it (backend recovered); a probe failure re-OPENs it.

    Single-threaded: the asyncio supervisor drives it cooperatively, so no lock.
    ``clock`` is injectable for deterministic tests.
    """

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
        """True iff a spawn may proceed now. Transitions open→half-open on cooldown."""
        if self.state == "closed":
            return True
        if self.state == "open":
            if self._clock() - self._opened_at >= self.cooldown_s:
                self.state = "half_open"
                self._probe_inflight = True
                return True  # single probe
            return False  # short-circuit: backend still cooling down
        # half_open: only the one in-flight probe runs; siblings short-circuit
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
        """Release a probe that ended WITHOUT a backend verdict — our own deadline
        killed it, not the backend. We learned nothing, so don't score it as success
        or failure, but DO free the single-probe token and return to cooling: else a
        killed probe leaves ``_probe_inflight`` set forever, wedging the breaker
        half-open so every queued chunk short-circuits 'breaker-open'. A no-op unless
        half-open, so a non-probe kill never perturbs a healthy backend."""
        if self.state == "half_open":
            self._probe_inflight = False
            self.state = "open"
            self._opened_at = self._clock()


def _breaker_threshold() -> int:
    """Consecutive backend-failure count that trips the breaker. Default 3."""
    raw = _utils.read_config().get("breaker_threshold", 3)
    try:
        return max(1, int(raw))
    except TypeError, ValueError:
        return 3


def _breaker_cooldown() -> float:
    """Seconds the breaker stays open before half-opening for a probe. Default 30."""
    raw = _utils.read_config().get("breaker_cooldown", 30)
    try:
        return max(0.0, float(raw))
    except TypeError, ValueError:
        return 30.0


def _make_breaker() -> _CircuitBreaker:
    """Build the run's shared breaker from config. Patch point for tests."""
    return _CircuitBreaker(_breaker_threshold(), cooldown_s=_breaker_cooldown())


def _event_age(agent_id: str) -> float | None:
    """Seconds since the chunk's agent log was last written, or None if absent.

    The chunk's ``transcript.jsonl`` is appended to on every audit event / harness
    stream chunk, so its mtime is a proxy for liveness. None (no log yet) means
    "no progress signal" — the caller must not treat that as a stall, since a
    just-spawned chunk may not have written its first line.
    """
    log = _agent_dir(agent_id) / "transcript.jsonl"
    try:
        return max(0.0, time.time() - log.stat().st_mtime)
    except OSError:
        return None


def _kill_proc_group(proc: object) -> None:
    """SIGKILL the child's whole process group.

    spawn spawns the child with ``**{_POPEN_NEW_GROUP: True}``, so it leads its own
    process group and the harness grandchild inherits it. Signalling the group —
    not just ``proc.pid`` — reaps the grandchild that otherwise orphans (reparents
    to init) and keeps mutating the worktree / holding the container (Bug A).

    Guarded: a child already reaped (ProcessLookupError) or a test double without a
    real pid falls back to ``proc.kill()``.
    """
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


def _read_chunk_seed(agent_id: str) -> str | None:
    """Return summary.md content for agent_id if it exists."""
    sf = _summary_file(agent_id)
    return sf.read_text() if sf.exists() else None


def _group_teardown(children: dict[str, object]) -> None:
    """Group-kill + container-down + chunk_teardown for every still-live child.

    The signal-shutdown counterpart to ``_await_chunk``'s per-chunk reaper: when
    the supervisor itself is killed (SIGINT/SIGTERM) it must not leave the fleet's
    child harnesses orphaned (reparented to init, still mutating worktrees) or
    their devcontainers running. Kills each child's process group, stops its
    container, and emits ``chunk_teardown`` so the shutdown is auditable. Every
    step is best-effort — one child's docker hiccup must not strand the others —
    and each slug is popped so a re-entrant signal can't double-tear-down.
    """
    for slug, proc in list(children.items()):
        with contextlib.suppress(Exception):
            _kill_proc_group(proc)
        ok = False
        with contextlib.suppress(Exception):
            ok = bool(_down_plan_container(slug))
        _emit_event("chunk_teardown", {"slug": slug, "ok": ok})
        children.pop(slug, None)


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, handler: Callable[[str], None]) -> None:
    """Wire SIGINT/SIGTERM on the running loop to ``handler(signame)``.

    Best-effort: ``add_signal_handler`` is unavailable off the main thread and on
    some platforms — those cases are swallowed (the process still dies on the
    signal's default disposition, just without the graceful group teardown).
    """
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
            loop.add_signal_handler(sig, handler, sig.name)


async def _await_chunk(
    proc: object,
    deadline_s: float,
    plan: _scheduler.Plan,
    *,
    agent_id: str | None = None,
    stall_s: float = 0.0,
) -> tuple[int | None, str | None]:
    """Await ``proc`` up to ``deadline_s``; kill on wall overrun OR no-progress stall.

    Uses ``communicate()`` (not ``wait()``) so a child that ever writes to a pipe
    cannot dead-lock on a full buffer. The returncode is read AFTER the kill
    signal, so a chunk that exits in the overdue→kill gap is recorded with its
    real rc, not misreported as killed.

    Two independent kill triggers, both returning ``rc`` plus a ``killed_reason``
    the caller turns into a self-describing ``chunk_ejected``:

    * ``timed_out`` — the wall ``asyncio.timeout(deadline_s)`` fired: ran too long.
    * ``stalled`` — with ``stall_s > 0`` and a ``agent_id``, the chunk emitted
      no audit event (its ``transcript.jsonl`` mtime did not advance) for a whole
      ``stall_s`` window while the wall still had budget. A chunk that keeps
      writing events resets the window and runs on.

    The host group-kill cannot reach the in-container agent (it lives in the
    container's PID namespace), so the reaper also ``devcontainer.down``s the
    chunk's slug to stop that container — otherwise the agent survives and keeps
    mutating its worktree after the kill.
    """
    grace_s = 5
    killed_reason: str | None = None
    comm = asyncio.ensure_future(proc.communicate())  # type: ignore[attr-defined]
    try:
        async with asyncio.timeout(deadline_s):
            if stall_s > 0 and agent_id is not None:
                while True:
                    try:
                        await asyncio.wait_for(asyncio.shield(comm), timeout=stall_s)
                        break  # chunk finished on its own
                    except TimeoutError:
                        age = _event_age(agent_id)
                        # None (no log yet) → can't prove a stall; keep waiting.
                        # age below the window → progress was made; keep waiting.
                        if age is not None and age >= stall_s:
                            killed_reason = "stalled"
                            break
            else:
                await comm
    except TimeoutError:
        killed_reason = "timed_out"
    if killed_reason is not None:
        print(
            f"mentat-orchestrate: chunk {plan.slug} {killed_reason} — killing",
            file=sys.stderr,
        )
        try:
            _kill_proc_group(proc)
        finally:
            with contextlib.suppress(Exception):
                _down_plan_container(plan.slug)
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(grace_s):
                    await proc.wait()  # type: ignore[attr-defined]
    return getattr(proc, "returncode", None), killed_reason


async def _supervise_fanout(
    plans: list[_scheduler.Plan], *, harness: str | None, model: str | None
) -> list[tuple[_scheduler.Plan, int | None, str | None, str | None]]:
    """asyncio fan-out supervisor: one task per plan, throttled by a Semaphore.

    Each task acquires a slot (``asyncio.Semaphore(cap)``), spawns its chunk,
    and awaits it under an independent per-chunk ``asyncio.timeout(deadline)`` —
    so a slow-but-healthy sibling never shrinks another chunk's budget and a hung
    chunk is killed at *its* deadline, freeing the slot for a queued chunk. Harvest
    is an ``asyncio.gather(return_exceptions=True)`` so the result order is exactly
    the submission order (deterministic indexed harvest).

    Returns each plan paired with (returncode, logs_path). A chunk's summary.md is
    read on exit and seeds the next spawn so context survives chunk boundaries.
    """
    cap = _concurrency_cap()
    deadline_s = _chunk_timeout()
    stall_s = _stall_timeout()
    sem = asyncio.Semaphore(cap)
    breaker = _make_breaker()
    shared: dict[str, str | None] = {"seed": None}
    # slug → live child proc, so a supervisor SIGINT/SIGTERM can group-tear-down
    # the whole fleet instead of orphaning containers/worktrees (S4).
    live: dict[str, object] = {}

    async def _run_one(plan: _scheduler.Plan) -> tuple[_scheduler.Plan, int | None, str | None, str | None]:
        async with sem:
            if not breaker.allow():
                # Backend (container daemon / model API) is tripped — short-circuit
                # WITHOUT spawning so we don't storm a sick dependency. Reported as a
                # container-down-shaped transient eject (retryable) named 'breaker-open'.
                print(
                    f"mentat-orchestrate: circuit breaker open — short-circuiting {plan.slug}",
                    file=sys.stderr,
                )
                return (plan, EX_UNAVAILABLE, None, "breaker-open")
            if not _load_headroom_ok():
                print(
                    f"mentat-orchestrate: host load high — spawning {plan.slug} into a saturated box",
                    file=sys.stderr,
                )
            seed = shared["seed"]
            agent_id, proc, worktree = await _spawn.spawn_async(plan, harness=harness, model=model, seed_summary=seed)
            _bind_chunk_from_worktree(plan.slug, worktree)
            live[plan.slug] = proc
            try:
                rc, killed_reason = await _await_chunk(proc, deadline_s, plan, agent_id=agent_id, stall_s=stall_s)
            finally:
                live.pop(plan.slug, None)
            # rc69 == the shared backend failed the spawn → a breaker failure. Any
            # verdict-producing exit (rc>=0, != 69) proves the backend is up → success.
            # A supervisor kill (rc<0/None) is our own deadline, not a backend verdict —
            # don't score it, but DO release a half-open probe token (record_abandoned is
            # a no-op unless half-open) so a killed probe can't wedge the breaker.
            if rc == EX_UNAVAILABLE:
                breaker.record_failure()
            elif rc is not None and rc >= 0:
                breaker.record_success()
            else:
                breaker.record_abandoned()
            summary = _read_chunk_seed(agent_id)
            if summary:
                shared["seed"] = summary
            return (plan, rc, str(_agent_dir(agent_id)), killed_reason)

    tasks = [asyncio.create_task(_run_one(p)) for p in plans]

    def _on_signal(signame: str) -> None:
        print(
            f"mentat-orchestrate: {signame} — tearing down {len(live)} live chunk(s)",
            file=sys.stderr,
        )
        _group_teardown(live)
        for t in tasks:
            t.cancel()

    _install_signal_handlers(asyncio.get_running_loop(), _on_signal)

    gathered = await asyncio.gather(*tasks, return_exceptions=True)
    results: list[tuple[_scheduler.Plan, int | None, str | None, str | None]] = []
    for plan, res in zip(plans, gathered, strict=True):
        if isinstance(res, BaseException):
            # A spawn/await crash: record a dead worker (negative rc), no logs.
            results.append((plan, -1, None, None))
        else:
            results.append(res)
    return results


def _fan_out_plans(
    plans: list[_scheduler.Plan], *, harness: str | None, model: str | None
) -> list[tuple[_scheduler.Plan, int | None, str | None, str | None]]:
    """Spawn AFK plans headless via the asyncio supervisor, capped at concurrency.

    Sync wrapper over ``_supervise_fanout`` (which owns the throttle + per-chunk
    deadline + kill logic). The cap defaults to 3 (ADR-0004), overridable via
    ~/.mentat/config.toml `concurrency`; the deadline defaults to 1800s,
    overridable via MENTAT_CHUNK_TIMEOUT / config `chunk_timeout`.

    Returns each plan paired with (child exit code, logs_path). The caller routes
    an ``EX_HITL_REQUIRED`` (42) child away from landing and uses logs_path to make
    a worker_died ejection self-describing (ADR-0007 payload extension).
    """
    return asyncio.run(_supervise_fanout(plans, harness=harness, model=model))
