"""Async chunk supervision: fan-out throttle, per-chunk deadline, circuit breaker."""

from __future__ import annotations

_POPEN_NEW_GROUP = "start_new_session"

import asyncio
import contextlib
import os  # noqa: F401 — patch seam for tests (cpu_count, getpgid, getloadavg)
import signal
import sys
from collections.abc import Callable
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import devcontainer as _devcontainer  # noqa: E402
from lib import git as _git  # noqa: E402
from lib.agent import agent_dir as _agent_dir
from lib.agent import summary_file as _summary_file
from lib.events import bind as _bind  # noqa: E402
from lib.exits import EX_UNAVAILABLE  # noqa: E402
from lib.loader import load_sibling  # noqa: E402

_utils = load_sibling(__file__, "plans")
_scheduler = load_sibling(__file__, "scheduler")
_spawn = load_sibling(__file__, "spawn")
_guardrails = load_sibling(__file__, "guardrails")

# slugs chunked (spawned or bound to a worktree) this run — scoped prune/GC reads it.
_run_chunk_slugs: set[str] = set()

_emit_event = _bind("mentat-orchestrate")

_CircuitBreaker = _guardrails.CircuitBreaker


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
    return _guardrails.load_headroom_ok()


def _chunk_timeout() -> int:
    return _guardrails.chunk_timeout(_utils.read_config)


def _stall_timeout() -> int:
    return _guardrails.stall_timeout(_utils.read_config)


def _breaker_threshold() -> int:
    return _guardrails.breaker_threshold(_utils.read_config)


def _breaker_cooldown() -> float:
    return _guardrails.breaker_cooldown(_utils.read_config)


def _make_breaker() -> _CircuitBreaker:
    return _guardrails.make_breaker(_utils.read_config)


def _event_age(agent_id: str) -> float | None:
    return _guardrails.event_age(agent_id, agent_dir_fn=_agent_dir)


def _kill_proc_group(proc: object) -> None:
    _guardrails.kill_proc_group(proc)


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
