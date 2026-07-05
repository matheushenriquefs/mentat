#!/usr/bin/env python3
"""mentat-orchestrate — run / fan-out / land-queue / batch-review."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import backoff as _backoff  # noqa: E402
from lib import devcontainer as _devcontainer  # noqa: E402
from lib import git as _git  # noqa: E402
from lib import worktrees as _worktrees  # noqa: E402
from lib.events import HITL_IN_SESSION, EjectReason, ejected_payload, spawned_payload  # noqa: E402
from lib.events import bind as _bind  # noqa: E402
from lib.exits import EX_DATAERR, EX_HITL_REQUIRED, EX_NOINPUT, EX_UNAVAILABLE  # noqa: E402
from lib.loader import load_sibling  # noqa: E402
from lib.session import ensure_session  # noqa: E402
from lib.session import session_dir as _session_dir
from lib.session import summary_file as _summary_file

_utils = load_sibling(__file__, "plans")
_scheduler = load_sibling(__file__, "scheduler")
_fan_out = load_sibling(__file__, "fan_out")
_land_queue = load_sibling(__file__, "land_queue")
_recover = load_sibling(__file__, "recover")

_run_chunk_slugs: set[str] = set()

_SIGNAL_EXIT_BASE = 128  # Shell-reported signal exit: 128 + signum


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


def _parse_list_field(raw: str) -> list[str]:
    if not raw or raw in ("[]", ""):
        return []
    parts = re.split(r"[,\s]+", raw)
    return [s.strip().strip("[]\"'") for s in parts if s.strip().strip("[]\"'")]


def _load_plans(paths: list[Path], *, _expanding: bool = False) -> list[_scheduler.Plan]:
    plans: list[_scheduler.Plan] = []
    parent_slugs: set[str] = set()

    for path in paths:
        fm = _utils.parse_frontmatter(path)
        slug = fm.get("id", path.stem)
        blocked_by = _parse_list_field(fm.get("blocked_by", ""))
        siblings = _parse_list_field(fm.get("siblings", ""))

        if siblings:
            if _expanding:
                print(f"nested parent index: {slug}", file=sys.stderr)
                raise SystemExit(EX_DATAERR)
            if blocked_by:
                print(f"parent index must have empty blocked_by: {slug}", file=sys.stderr)
                raise SystemExit(EX_DATAERR)
            parent_slugs.add(slug)
            sibling_paths: list[Path] = []
            for s in siblings:
                sibling_path = path.parent / f"{s}.md"
                if not sibling_path.exists():
                    print(f"sibling plan not found: {s}", file=sys.stderr)
                    raise SystemExit(EX_NOINPUT)
                sibling_paths.append(sibling_path)
            plans.extend(_load_plans(sibling_paths, _expanding=True))
        else:
            plans.append(
                _scheduler.Plan(
                    slug=slug,
                    class_=fm.get("class", "HITL"),
                    blocked_by=blocked_by,
                    path=path,
                    touches=tuple(_parse_list_field(fm.get("touches", ""))),
                )
            )

    if not _expanding:
        known_slugs = {p.slug for p in plans}
        for plan in plans:
            for dep in plan.blocked_by:
                if dep in parent_slugs:
                    print(f"cannot block on parent index: {dep}", file=sys.stderr)
                    raise SystemExit(EX_DATAERR)
                if dep not in known_slugs:
                    print(
                        f"warning: blocked_by '{dep}' in '{plan.slug}' not in batch"
                        " — treated as already-landed external dep",
                        file=sys.stderr,
                    )

    return plans


def _emit_anchored_chunks(plans: list[_scheduler.Plan], *, harness: str | None, model: str | None) -> list[str]:
    """Emit chunk.spawned{harness:hitl-in-session} per anchored plan, no subprocess.

    HITL plans run in the **calling Claude session** — never via subprocess —
    so AskUserQuestion works. The caller queries the audit log
    (`mentat-log query chunk.spawned --session=$MENTAT_SESSION`) and drives
    `/mentat-implement <slug>` in-session per anchored slug, then re-invokes
    `orchestrate land-queue <holding>` with the HITL slugs on stdin.

    Returns slugs anchored this invocation (caller may use them to drive
    /mentat-implement). They are NOT appended to `_land_all` here — landing
    happens on the post-implement land-queue call.
    """
    chunks: list[str] = []
    for plan in plans:
        _utils.emit_event(
            "chunk.spawned",
            spawned_payload(plan.slug, str(plan.path), harness=HITL_IN_SESSION, worktree=str(Path.cwd())),
        )
        chunks.append(plan.slug)
    return chunks


def _concurrency_cap() -> int:
    """Max parallel AFK chunk processes, clamped to machine headroom.

    Honors ADR-0004 (config default 3) but CLAMPS the configured value to
    ``min(config, max(1, cpu_count // 2))``. One heavy agent per core is the
    timeout root-cause: when the number of concurrent chunks equals the core
    count, every agent starves for CPU and trips its wall/stall deadline on a
    live-but-slow build. Halving the cores reserves headroom for the supervisor,
    the devcontainers, and the host. The clamp is logged so an operator seeing
    an effective cap below their configured ``concurrency`` knows why.
    """
    raw = _utils.read_config().get("concurrency", 3)
    try:
        want = max(1, int(raw))
    except (TypeError, ValueError):
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
    except (OSError, AttributeError):
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
    except (TypeError, ValueError):
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
    except (TypeError, ValueError):
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
    except (TypeError, ValueError):
        return 3


def _breaker_cooldown() -> float:
    """Seconds the breaker stays open before half-opening for a probe. Default 30."""
    raw = _utils.read_config().get("breaker_cooldown", 30)
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 30.0


def _make_breaker() -> _CircuitBreaker:
    """Build the run's shared breaker from config. Patch point for tests."""
    return _CircuitBreaker(_breaker_threshold(), cooldown_s=_breaker_cooldown())


def _event_age(session_id: str) -> float | None:
    """Seconds since the chunk's session log was last written, or None if absent.

    The chunk's ``session.jsonl`` is appended to on every audit event / harness
    stream chunk, so its mtime is a proxy for liveness. None (no log yet) means
    "no progress signal" — the caller must not treat that as a stall, since a
    just-spawned chunk may not have written its first line.
    """
    log = _session_dir(session_id) / "session.jsonl"
    try:
        return max(0.0, time.time() - log.stat().st_mtime)
    except OSError:
        return None


_emit_event = _bind("mentat-orchestrate")


def _kill_proc_group(proc: object) -> None:
    """SIGKILL the child's whole process group.

    fan_out spawns the child with ``start_new_session=True``, so it leads its own
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
    except (ProcessLookupError, OSError):
        with contextlib.suppress(Exception):
            proc.kill()  # type: ignore[attr-defined]
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pgid, signal.SIGKILL)


def _read_chunk_seed(session_id: str) -> str | None:
    """Return summary.md content for session_id if it exists."""
    sf = _summary_file(session_id)
    return sf.read_text() if sf.exists() else None


def _group_teardown(children: dict[str, object]) -> None:
    """Group-kill + container-down + chunk.teardown for every still-live child.

    The signal-shutdown counterpart to ``_await_chunk``'s per-chunk reaper: when
    the supervisor itself is killed (SIGINT/SIGTERM) it must not leave the fleet's
    child harnesses orphaned (reparented to init, still mutating worktrees) or
    their devcontainers running. Kills each child's process group, stops its
    container, and emits ``chunk.teardown`` so the shutdown is auditable. Every
    step is best-effort — one child's docker hiccup must not strand the others —
    and each slug is popped so a re-entrant signal can't double-tear-down.
    """
    for slug, proc in list(children.items()):
        with contextlib.suppress(Exception):
            _kill_proc_group(proc)
        ok = False
        with contextlib.suppress(Exception):
            ok = bool(_down_plan_container(slug))
        _emit_event("chunk.teardown", {"slug": slug, "ok": ok})
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
    session_id: str | None = None,
    stall_s: float = 0.0,
) -> tuple[int | None, str | None]:
    """Await ``proc`` up to ``deadline_s``; kill on wall overrun OR no-progress stall.

    Uses ``communicate()`` (not ``wait()``) so a child that ever writes to a pipe
    cannot dead-lock on a full buffer. The returncode is read AFTER the kill
    signal, so a chunk that exits in the overdue→kill gap is recorded with its
    real rc, not misreported as killed.

    Two independent kill triggers, both returning ``rc`` plus a ``killed_reason``
    the caller turns into a self-describing ``chunk.ejected``:

    * ``timed_out`` — the wall ``asyncio.timeout(deadline_s)`` fired: ran too long.
    * ``stalled`` — with ``stall_s > 0`` and a ``session_id``, the chunk emitted
      no audit event (its ``session.jsonl`` mtime did not advance) for a whole
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
            if stall_s > 0 and session_id is not None:
                while True:
                    try:
                        await asyncio.wait_for(asyncio.shield(comm), timeout=stall_s)
                        break  # chunk finished on its own
                    except TimeoutError:
                        age = _event_age(session_id)
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
            session_id, proc, worktree = await _fan_out.spawn_async(
                plan, harness=harness, model=model, seed_summary=seed
            )
            _bind_chunk_from_worktree(plan.slug, worktree)
            live[plan.slug] = proc
            try:
                rc, killed_reason = await _await_chunk(proc, deadline_s, plan, session_id=session_id, stall_s=stall_s)
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
            summary = _read_chunk_seed(session_id)
            if summary:
                shared["seed"] = summary
            return (plan, rc, str(_session_dir(session_id)), killed_reason)

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
    a worker-died ejection self-describing (ADR-0007 payload extension).
    """
    return asyncio.run(_supervise_fanout(plans, harness=harness, model=model))


def _teardown_ejected(slug: str) -> None:
    """Stop + remove a partition-ejected chunk's container and record it.

    A chunk ejected at partition time never reaches the land queue (which is what
    normally tears containers down), so its container would otherwise leak. Mirror
    the land-queue behaviour: ``devcontainer.down`` then emit chunk.teardown.
    Best-effort — a docker failure must not abort partitioning."""
    ok = False
    with contextlib.suppress(Exception):
        ok = _down_plan_container(slug)
    _emit_event("chunk.teardown", {"slug": slug, "ok": ok})


def _partition_fanout(
    results: list[tuple[_scheduler.Plan, int | None, str | None]],
    *,
    mark_ejected: Callable[[str], list[str]],
) -> tuple[list[_land_queue.Chunk], set[str], set[str]]:
    """Split fan-out results into (landable_chunks, hitl_slugs, transient_slugs).

    A child that exited EX_HITL_REQUIRED is a wedge: self-ejected, worktree
    preserved. Mirrored as chunk.ejected{reason:hitl-required} so the operator
    sees it without reading the child's log, kept out of the land queue.

    A **transient** death (worker-died: timeout kill or container-down) is not
    mark_ejected here — its slug is RETURNED in the third set instead. That set is
    the seam the recovery engine consumes to decide what to respawn; the caller
    (run_orchestrate) marks them ejected once no respawn is pending. Terminal
    ejects (hitl-required, implement-failed) are mark_ejected inline as before —
    respawning them unchanged would just fail again.
    """
    chunks = []
    hitl: set[str] = set()
    transient: set[str] = set()
    for item in results:
        plan, rc = item[0], item[1]
        logs_path = item[2] if len(item) > 2 else None
        killed_reason = item[3] if len(item) > 3 else None
        worktree = _worktree_for_slug(plan.slug)
        if rc is None or rc < 0 or rc >= _SIGNAL_EXIT_BASE:
            # Timeout/stall group-kill (rc<0), a crashed supervise task (rc None), or
            # a shell-reported signal exit (128+signum). A dead worker produced no
            # verdict — landing it would false-merge. Self-describe it so the operator
            # (and the recovery engine) can tell a wall-deadline kill from a
            # no-progress stall kill without reading the child's stream: a ``stalled``
            # reason names the killer, otherwise it defaults to a wall timeout.
            # Transient → returned, not marked (see docstring).
            if killed_reason == "stalled":
                payload = ejected_payload(
                    plan.slug, EjectReason.WORKER_DIED, str(worktree), logs_path=logs_path, killed_by="stalled"
                )
            else:
                payload = ejected_payload(
                    plan.slug, EjectReason.WORKER_DIED, str(worktree), logs_path=logs_path, timed_out=True
                )
            _emit_event("chunk.ejected", payload)
            transient.add(plan.slug)
            _teardown_ejected(plan.slug)
        elif rc == EX_HITL_REQUIRED:
            hitl.add(plan.slug)
            _emit_event("chunk.ejected", ejected_payload(plan.slug, EjectReason.HITL_REQUIRED, str(worktree)))
            mark_ejected(plan.slug)
            _teardown_ejected(plan.slug)
        elif rc == EX_UNAVAILABLE:
            # Container/infra failure — the worker never ran, no code produced.
            # killed_by names the killer so the death is self-describing: a breaker
            # short-circuit ('breaker-open', never launched) vs. a genuine downed
            # container vs. OOM. Transient → returned, not marked (see docstring).
            killed_by = killed_reason if killed_reason == "breaker-open" else "container-down"
            if killed_by == "container-down":
                from lib.chunk import chunk_id_for_plan, chunk_slug

                try:
                    cs = chunk_slug(chunk_id_for_plan(plan.slug), plan.slug)
                    if _devcontainer.container_oom_killed(cs):
                        killed_by = "oom"
                except LookupError:
                    pass
            _emit_event(
                "chunk.ejected",
                ejected_payload(
                    plan.slug,
                    EjectReason.WORKER_DIED,
                    str(worktree),
                    logs_path=logs_path,
                    killed_by=killed_by,
                ),
            )
            transient.add(plan.slug)
            _teardown_ejected(plan.slug)
        elif rc != 0:
            # Any other non-zero exit: implement or gate failure. Terminal.
            _emit_event("chunk.ejected", ejected_payload(plan.slug, EjectReason.IMPLEMENT_FAILED, str(worktree)))
            mark_ejected(plan.slug)
            _teardown_ejected(plan.slug)
        else:
            from lib.chunk import chunk_id_for_plan

            chunk_id = chunk_id_for_plan(plan.slug)
            chunks.append(_land_queue.Chunk(slug=plan.slug, worktree=worktree, chunk_id=chunk_id))
    return chunks, hitl, transient


def _prune_stale_containers() -> None:
    """Tear down exited containers for this run's chunk slugs only.

    Machine-wide docker prune is forbidden — it would reap a concurrent run's
    idle container (H3). Another run's resources are never candidates.
    """
    if not _run_chunk_slugs:
        return
    removed = _devcontainer.down_run(_run_chunk_slugs)
    _utils.emit_event("session.prune", {"reclaimed_bytes": None, "containers_removed": removed})


def _prune_stale_worktrees(preserve: set[str] | None = None) -> None:
    """End-of-batch sweep of clean, inactive, stale worktrees for this run only.

    ``preserve`` plan slugs are held back from the sweep — a wedged (hitl-required)
    chunk's worktree must survive for the operator even when it is clean and
    inactive.
    """
    scope = _run_chunk_ids()
    if not scope:
        return
    wt_root = Path.cwd() / ".mentat" / "worktrees"
    active = _preserve_chunk_slugs(preserve)
    removed = _worktrees.prune_stale(wt_root, active_slugs=active, scope_chunk_ids=scope)
    _utils.emit_event("session.prune", {"reclaimed_bytes": None, "worktrees_removed": removed})


def _gc_preserved_worktrees(preserve: set[str] | None = None) -> None:
    """Reclaim long-abandoned preserved worktrees for this run's chunk ids only."""
    scope = _run_chunk_ids()
    if not scope:
        return
    wt_root = Path.cwd() / ".mentat" / "worktrees"
    active = _preserve_chunk_slugs(preserve)
    reclaimed = _worktrees.gc_preserved(wt_root, active_slugs=active, scope_chunk_ids=scope)
    _utils.emit_event("session.prune", {"reclaimed_bytes": None, "worktrees_gc": reclaimed})


def _chunk_id_for_land(plan_slug: str) -> str:
    from lib.chunk import chunk_id_for_plan

    return chunk_id_for_plan(plan_slug)


def _worktree_for_slug(slug: str) -> Path:
    """Find chunk-keyed worktree for plan slug. Raises GitError on miss."""
    return _git.worktree_for_plan(slug)


def _land_all(
    chunk_slugs: list[str],
    *,
    holding: str,
    plans: list[_scheduler.Plan] | None = None,
) -> list[dict[str, object]]:
    """Land chunks onto holding branch serially (debug land-queue subcommand + dry-run)."""
    chunks = [
        _land_queue.Chunk(slug=s, worktree=_worktree_for_slug(s), chunk_id=_chunk_id_for_land(s)) for s in chunk_slugs
    ]
    if plans is None:
        return _land_queue.drain(chunks, holding=holding)
    sched = _scheduler.Scheduler(plans)
    return _land_queue.drain(
        chunks,
        holding=holding,
        on_landed=sched.mark_landed,
        on_ejected=sched.mark_ejected,
        next_ready=sched.next_ready,
    )


def _spawn_ready(pending: list[_scheduler.Plan], *, known_slugs: set[str], resolved: set[str]) -> list[_scheduler.Plan]:
    """Auto plans whose declared deps are all resolved — the next spawn wave.

    Mirrors ``scheduler.next_ready``'s readiness rule (NNFI: an ejected upstream
    counts as resolved, an unknown/external dep is treated as already-landed) but
    returns EVERY spawnable plan so the coordinator fans a whole wave out at once.
    Gating SPAWN — not just land — keeps a chunk with an un-landed ``blocked_by``
    upstream from branching a worktree off a base that lacks the upstream's change.
    """
    wave: list[_scheduler.Plan] = []
    for plan in pending:
        deps = set(plan.blocked_by) & known_slugs
        if deps - resolved:
            continue
        wave.append(plan)
    return wave


def _run_batch(
    auto: list[_scheduler.Plan],
    *,
    holding: str,
    harness: str | None,
    model: str | None,
    sched: _scheduler.Scheduler,
    known_slugs: set[str],
) -> tuple[list[dict[str, object]], set[str], set[str]]:
    """Staged fan-out coordinator: spawn a dep-ready wave, land it, repeat.

    Each iteration fans out only the auto plans whose ``blocked_by`` upstreams have
    landed (or NNFI-ejected), lands that wave through the dep-aware drain, then
    re-evaluates the remaining plans against the advanced holding tip. Independent,
    write-set-disjoint plans still form a single wave (no needless serialization);
    a dep or shared-touch-path edge (added upstream by ``serialize_conflicts``)
    defers a plan to a later wave. Returns ``(drain_results, hitl_slugs,
    transient_slugs)`` accumulated across all waves — the transient set is the seam
    the recovery engine (S2) consumes; here it is marked ejected.
    """
    resolved: set[str] = set()

    def _on_landed(slug: str) -> None:
        sched.mark_landed(slug)
        resolved.add(slug)

    def _on_ejected(slug: str) -> list[str]:
        cascaded = sched.mark_ejected(slug)
        resolved.add(slug)
        resolved.update(cascaded)
        return cascaded

    pending = list(auto)
    drain_results: list[dict[str, object]] = []
    hitl_slugs: set[str] = set()
    transient_slugs: set[str] = set()

    while pending:
        wave = _spawn_ready(pending, known_slugs=known_slugs, resolved=resolved)
        if not wave:
            # No pending plan's deps are resolved — a dep never landed. The land
            # queue's own stalled verdict already fired for the landable set; emit
            # one here so the un-spawnable remainder is visible to the operator.
            drain_results.append({"slug": None, "status": "stalled", "pending": [p.slug for p in pending]})
            break

        results = _fan_out_plans(wave, harness=harness, model=model)
        chunks, hitl, transient = _partition_fanout(results, mark_ejected=_on_ejected)
        hitl_slugs.update(hitl)
        # Transient (worker-died) ejects: the recovery engine's seam. Absent a
        # respawn engine in this slice, mark them ejected so the cascade + non-zero
        # batch exit are unchanged (S2 replaces this with the recovery pass).
        for slug in transient:
            _on_ejected(slug)
        transient_slugs.update(transient)

        wave_results = _land_queue.drain(
            chunks,
            holding=holding,
            on_landed=_on_landed,
            on_ejected=_on_ejected,
            next_ready=sched.next_ready,
        )
        drain_results.extend(wave_results)
        for plan in wave:
            pending.remove(plan)

    return drain_results, hitl_slugs, transient_slugs


def _recovery_diff(worktree: Path, holding: str) -> str:
    """Best-effort partial diff of the chunk's worktree vs the holding tip.

    Baseline seed when transcript distillation is unavailable. Truncated to keep
    prompts bounded; any git failure yields ""."""
    try:
        result = subprocess.run(
            ["git", "-C", str(worktree), "diff", holding],
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return result.stdout[:4000] if result.returncode == 0 else ""


def make_recovery_seed_for_plan(
    plan: _scheduler.Plan, attempt: int, cap: int, *, holding: str, session_id: str
) -> dict[str, object]:
    """Build the failure context handed to the recovery agent and respawn seed."""
    worktree = _worktree_for_slug(plan.slug)
    return _recover.make_recovery_seed(
        slug=plan.slug,
        reason=EjectReason.WORKER_DIED,
        worktree=worktree,
        holding=holding,
        attempt=attempt,
        cap=cap,
        session_id=session_id,
        diff=_recovery_diff(worktree, holding),
    )


def _spawn_implement_in_worktree(
    plan_path: Path,
    worktree: Path,
    *,
    harness: str | None,
    model: str | None,
    reuse_worktree: bool = False,
    seed_summary: str | None = None,
) -> int:
    """Run mentat-implement inside an EXISTING worktree and return its exit code.

    ``reuse_worktree`` skips ``worktree create`` (rc65 on an existing branch) —
    the idempotent re-land the recovery contract requires."""
    cmd = ["python3", str(_fan_out._IMPLEMENT_SCRIPT), str(plan_path)]
    if harness:
        cmd += ["--harness", harness]
    if model:
        cmd += ["--model", model]
    if reuse_worktree:
        cmd += ["--reuse-worktree"]
    env = dict(os.environ)
    if seed_summary:
        env["MENTAT_SEED_SUMMARY"] = seed_summary
    proc = subprocess.Popen(cmd, cwd=str(worktree), env=env, start_new_session=True)
    return proc.wait()


def _recovery_respawn(
    plan: _scheduler.Plan,
    attempt: int,
    *,
    holding: str,
    harness: str | None,
    model: str | None,
    session_id: str,
    seed: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    """retry action: rebase the preserved worktree onto holding, re-run implement, land."""
    worktree = _worktree_for_slug(plan.slug)
    # mentat-container up dirties .devcontainer/ in every worktree; discard so the
    # rebase does not refuse on unstaged changes (mirrors land_queue._rebase_chunk).
    _git.discard_path(worktree, ".devcontainer/")
    _git.rebase_ff_only(worktree, holding)
    seed_summary = str((seed or {}).get("seed_summary", "")) or None
    rc = _spawn_implement_in_worktree(
        plan.path,
        worktree,
        harness=harness,
        model=model,
        reuse_worktree=True,
        seed_summary=seed_summary,
    )
    if rc != 0:
        _emit_event("chunk.ejected", ejected_payload(plan.slug, EjectReason.IMPLEMENT_FAILED, str(worktree)))
        return [{"slug": plan.slug, "status": "eject", "reason": EjectReason.IMPLEMENT_FAILED}]
    from lib.chunk import chunk_id_for_plan

    chunk_id = chunk_id_for_plan(plan.slug)
    return _land_queue.drain([_land_queue.Chunk(slug=plan.slug, worktree=worktree, chunk_id=chunk_id)], holding=holding)


def _reslice_agent(plan: _scheduler.Plan, *, invoke: Callable[[str], str] | None = None) -> list[Path]:
    """Ask the model to re-plan a too-big chunk into smaller sibling slice files.

    The agent writes ``<slug>-r<N>.md`` slice files next to the original plan; this
    returns the ones that appeared. No files produced → empty list (the caller
    escalates rather than looping)."""
    invoke = invoke or _recover._invoke_claude
    prompt = (
        f"The plan at {plan.path} was too large to finish in one deadline. Re-plan it into "
        f"2-4 smaller vertical-slice plan files named {plan.path.stem}-r1.md, {plan.path.stem}-r2.md, "
        f"... in the same directory ({plan.path.parent}). Each must be independently implementable. "
        "Write the files, then reply 'done'."
    )
    invoke(prompt)
    return sorted(plan.path.parent.glob(f"{plan.path.stem}-r*.md"))


def _recovery_reslice(
    plan: _scheduler.Plan, attempt: int, *, holding: str, harness: str | None, model: str | None
) -> list[dict[str, object]]:
    """reslice action: re-plan into sub-slices JIT and re-fan them through the staged coordinator."""
    sub_paths = _reslice_agent(plan)
    if not sub_paths:
        return [{"slug": plan.slug, "status": "eject", "reason": EjectReason.IMPLEMENT_FAILED, "note": "reslice-empty"}]
    sub_plans = _scheduler.serialize_conflicts(_load_plans(sub_paths))
    sched = _scheduler.Scheduler(sub_plans)
    known = {p.slug for p in sub_plans}
    results, _hitl, _transient = _run_batch(
        sub_plans, holding=holding, harness=harness, model=model, sched=sched, known_slugs=known
    )
    return results


def _recovery_backoff(attempt: int, *, sleep: Callable[[float], None] | None = None) -> None:
    """Sleep the full-jitter backoff delay before a recovery respawn.

    The delay is both computed AND slept: the prior wiring computed the jittered
    delay and discarded it, so respawns fired back-to-back with zero spacing — the
    synchronized re-collision the jitter exists to prevent. ``sleep`` is injectable
    (defaults to ``time.sleep``) so tests stay deterministic."""
    (sleep or time.sleep)(_backoff.full_jitter(attempt))


def _run_recovery(
    transient: set[str],
    *,
    plans_by_slug: dict[str, _scheduler.Plan],
    holding: str,
    session_id: str,
    harness: str | None,
    model: str | None,
) -> tuple[set[str], set[str]]:
    """Run the JIT recovery pass over transient AFK ejects. Returns (recovered_ok, dead_lettered).

    Delegates the decide/apply loop to ``recover.recover`` with the real spawn / land /
    re-plan primitives bound in. ``recovered_ok`` are slugs a retry/reslice landed;
    ``dead_lettered`` are slugs escalated to HITL (abandon / cap breach) — both feed the
    batch exit code."""

    def _dead_letter(plan: _scheduler.Plan, rationale: str) -> None:
        _emit_event(
            "chunk.ejected",
            ejected_payload(
                plan.slug, EjectReason.HITL_REQUIRED, str(_worktree_for_slug(plan.slug)), summary=rationale
            ),
        )

    outcomes = _recover.recover(
        transient,
        plans_by_slug=plans_by_slug,
        holding=holding,
        session_id=session_id,
        harness=harness,
        is_afk=lambda s: plans_by_slug[s].class_ == "AFK",
        context_builder=lambda plan, attempt, cap: make_recovery_seed_for_plan(
            plan, attempt, cap, holding=holding, session_id=session_id
        ),
        teardown=_teardown_ejected,
        respawn=lambda plan, attempt, ctx: _recovery_respawn(
            plan,
            attempt,
            holding=holding,
            harness=harness,
            model=model,
            session_id=session_id,
            seed=ctx,
        ),
        reslice=lambda plan, attempt: _recovery_reslice(plan, attempt, holding=holding, harness=harness, model=model),
        dead_letter=_dead_letter,
        backoff=_recovery_backoff,
    )

    recovered_ok: set[str] = set()
    dead_lettered: set[str] = set()
    for outcome in outcomes:
        slug = str(outcome.get("slug", ""))
        kind = outcome.get("recovery")
        if kind in (_recover.RETRY, _recover.RESLICE):
            results = outcome.get("results") or []
            if any(isinstance(r, dict) and r.get("status") == "success" for r in results):
                recovered_ok.add(slug)
        elif kind in (_recover.ABANDON, "dead-lettered"):
            dead_lettered.add(slug)
    return recovered_ok, dead_lettered


def run_orchestrate(
    holding: str,
    plan_paths: list[Path],
    *,
    harness: str | None,
    model: str | None,
    dry_run: bool,
) -> int:
    session_id = ensure_session("orchestrate", holding)
    print(f"mentat-orchestrate: track this run with `mentat-session track {session_id}`", file=sys.stderr)
    plans = _load_plans(plan_paths)
    anchored, auto = _scheduler.partition(plans)
    _run_chunk_slugs.clear()

    if dry_run:
        print(f"[dry-run] would anchor: {[p.slug for p in anchored]}")
        print(f"[dry-run] would spawn: {[p.slug for p in auto]}")
        _land_all([], holding=holding)
        _utils.emit_event(
            "batch.reviewed",
            {"session": session_id, "summary": f"batch review for session {session_id} — advisory"},
        )
        return 0

    _prune_stale_containers()

    # hitl_slugs is defined before the try so the crash-safe finally can preserve
    # wedged worktrees even if the batch body raises mid-run.
    hitl_slugs: set[str] = set()
    try:
        if anchored:
            _emit_anchored_chunks(anchored, harness=harness, model=model)

        # Serialize write-set conflicts: two auto plans that declare the same
        # touch-path get an implied blocked_by edge (nearest earlier conflictor)
        # so they never fan out concurrently and rebase-collide (the routes.py
        # failure). Disjoint write-sets are returned unchanged.
        auto = _scheduler.serialize_conflicts(auto)

        # Build Scheduler from ALL plans (anchored + auto) so cross-partition
        # blocked_by edges are tracked.  auto chunks are the only spawn candidates
        # (they never appear in `next_ready` as anchored slugs), so anchored plans
        # act as "known but not-yet-landed" deps that gate auto dependents correctly.
        # mark_ejected then cascades across the full plan graph, including HITL
        # downstream — fixing the silent cascade miss when an auto upstream dies.
        sched = _scheduler.Scheduler(anchored + auto)
        known_slugs = {p.slug for p in (anchored + auto)}

        # Staged fan-out: spawn is dep-gated on landing, not fired all-at-once. A
        # chunk whose blocked_by upstream has not landed waits for a later wave.
        drain_results, hitl, transient = _run_batch(
            auto,
            holding=holding,
            harness=harness,
            model=model,
            sched=sched,
            known_slugs=known_slugs,
        )
        hitl_slugs.update(hitl)

        # Recovery pass (ADR-0015): after the drain settles, attempt JIT recovery of
        # transient-ejected AFK chunks — serially, spaced by backoff, so a recovering
        # fleet never re-storms the box. A recovered_ok slug no longer counts against
        # the batch; a dead-lettered slug escalates to HITL (never a silent eject).
        recovered_ok, dead_lettered = _run_recovery(
            transient,
            plans_by_slug={p.slug: p for p in (anchored + auto)},
            holding=holding,
            session_id=session_id,
            harness=harness,
            model=model,
        )
        hitl_slugs.update(dead_lettered)
        stalled = [r for r in drain_results if r.get("status") == "stalled"]
        if stalled:
            pending = stalled[0].get("pending", [])
            print(f"mentat-orchestrate: stalled — pending chunks: {pending}", file=sys.stderr)

        # Emit cascade ejection events for anchored plans whose upstream was ejected.
        # The drain loop only processes auto chunks, so anchored cascade victims are
        # silently in sched.ejected_slugs() but never emitted — fix that here so the
        # operator sees them in the audit log and skips implementing them.
        anchored_slugs = {p.slug for p in anchored}
        for slug in sched.ejected_slugs():
            if slug in anchored_slugs:
                plan_obj = next((p for p in anchored if p.slug == slug), None)
                where = str(plan_obj.path.parent) if plan_obj else str(Path.cwd())
                _emit_event(
                    "chunk.ejected",
                    ejected_payload(slug, EjectReason.UPSTREAM_EJECTED, where),
                )

        _utils.emit_event(
            "batch.reviewed",
            {"session": session_id, "summary": f"batch review for session {session_id} — advisory"},
        )

        # A recovered chunk landed on a later attempt — drop it from the ejection
        # tally so a fully-salvaged batch exits 0.
        unrecovered = sched.ejected_slugs() - recovered_ok
        rc = 1 if unrecovered or hitl_slugs or stalled else 0
        if rc != 0:
            # Print named eject summary so operator knows which slugs failed and why.
            # Drain results carry land-queue eject reasons; partition-ejected chunks
            # appear in sched.ejected_slugs() but not in drain_results.
            drain_eject_slugs = {r.get("slug") for r in drain_results if r.get("status") == "eject"}
            for v in drain_results:
                if v.get("status") == "eject":
                    slug = v.get("slug", "?")
                    reason = v.get("reason", "?")
                    print(f"mentat-orchestrate: ejected {slug} — {reason}", file=sys.stderr)
            for slug in sorted(sched.ejected_slugs()):
                if slug not in drain_eject_slugs and slug not in hitl_slugs:
                    print(f"mentat-orchestrate: ejected {slug}", file=sys.stderr)
            for slug in sorted(hitl_slugs):
                print(f"mentat-orchestrate: ejected {slug} — hitl-required", file=sys.stderr)
        else:
            print(f"mentat-orchestrate: review the diff with `git diff {holding}..HEAD`", file=sys.stderr)
        return rc
    finally:
        # Crash-safe teardown: reclaim clean stale worktrees + GC long-abandoned
        # preserved ones on every exit — including an exception mid-batch — so a
        # crash never leaks worktrees or containers. hitl worktrees are held back.
        _prune_stale_worktrees(preserve=hitl_slugs)
        _gc_preserved_worktrees(preserve=hitl_slugs)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mentat-orchestrate")
    sub = p.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Full orchestrate run")
    run_p.add_argument("holding", help="Holding branch")
    run_p.add_argument("plan_refs", nargs="+", metavar="plan-ref")
    run_p.add_argument("--harness", default=None)
    run_p.add_argument("--model", default=None)
    run_p.add_argument("--dry-run", action="store_true")

    fo_p = sub.add_parser("fan-out", help="Debug: spawn plans headless")
    fo_p.add_argument("plan_refs", nargs="+", metavar="plan-ref")

    lq_p = sub.add_parser("land-queue", help="Debug: land chunks from stdin")
    lq_p.add_argument("holding", help="Holding branch")

    fr_p = sub.add_parser("batch-review", help="Debug: re-run batch review")
    fr_p.add_argument("session", help="Session ID")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "run":
        sys.exit(
            run_orchestrate(
                args.holding,
                [_utils.resolve_plan_ref(r) for r in args.plan_refs],
                harness=args.harness,
                model=args.model,
                dry_run=args.dry_run,
            )
        )

    elif args.cmd == "fan-out":
        plans = _load_plans([_utils.resolve_plan_ref(r) for r in args.plan_refs])
        for plan in plans:
            _fan_out.spawn(plan)

    elif args.cmd == "land-queue":
        slugs = [line.strip() for line in sys.stdin if line.strip()]
        import json

        # Resolve slugs → plan paths for dep-aware drain ordering.  Plans that
        # cannot be resolved (e.g. ad-hoc slugs) are silently skipped; the
        # drain falls back to input order for those chunks.
        plan_paths = [_utils.resolve_plan_ref(s) for s in slugs]
        existing_paths = [p for p in plan_paths if p.exists()]
        lq_plans = _load_plans(existing_paths, _expanding=False) if existing_paths else None
        results = _land_all(slugs, holding=args.holding, plans=lq_plans)
        for r in results:
            print(json.dumps(r))

    elif args.cmd == "batch-review":
        _utils.emit_event(
            "batch.reviewed",
            {"session": args.session, "summary": f"batch review for session {args.session} — advisory"},
        )


if __name__ == "__main__":
    main()
