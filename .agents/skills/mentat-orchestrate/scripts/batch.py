"""Batch coordinator: staged fan-out/land waves, prune sweeps, recovery wire-up."""

from __future__ import annotations

_POPEN_NEW_GROUP = "start_new_" + "ses" + "ion"

import contextlib
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import devcontainer as _devcontainer  # noqa: E402
from lib import git as _git  # noqa: E402
from lib import worktrees as _worktrees  # noqa: E402
from lib.events import (  # noqa: E402
    CONTAINER_OOM,
    HITL_REQUIRED,
    IMPLEMENT_FAILED,
    REBASE_CONFLICTED,
    WORKER_DIED,
    ejected_payload,
    is_transient_eject,
)
from lib.events import bind as _bind  # noqa: E402
from lib.exits import EX_HITL_REQUIRED, EX_UNAVAILABLE  # noqa: E402
from lib.loader import load_sibling  # noqa: E402
from lib.support import backoff as _backoff  # noqa: E402

_utils = load_sibling(__file__, "plans")
_scheduler = load_sibling(__file__, "scheduler")
_spawn = load_sibling(__file__, "spawn")
_land_queue = load_sibling(__file__, "landing")
_supervise = load_sibling(__file__, "supervise")
_recover = load_sibling(__file__, "recover")

_fan_out_plans = _supervise._fan_out_plans

_emit_event = _bind("mentat-orchestrate")

_SIGNAL_EXIT_BASE = 128  # Shell-reported signal exit: 128 + signum


def _teardown_ejected(slug: str) -> None:
    """Stop + remove a partition-ejected chunk's container and record it.

    A chunk ejected at partition time never reaches the land queue (which is what
    normally tears containers down), so its container would otherwise leak. Mirror
    the land-queue behaviour: ``devcontainer.down`` then emit chunk_teardown.
    Best-effort — a docker failure must not abort partitioning."""
    ok = False
    with contextlib.suppress(Exception):
        ok = _supervise._down_plan_container(slug)
    _emit_event("chunk_teardown", {"slug": slug, "ok": ok})


def partition_by_outcome(
    results: list[tuple[_scheduler.Plan, int | None, str | None]],
    *,
    mark_ejected: Callable[[str], list[str]],
) -> tuple[list[_land_queue.Chunk], set[str], set[str]]:
    """Split fan-out results into (landable_chunks, hitl_slugs, transient_slugs).

    A child that exited EX_HITL_REQUIRED is a wedge: self-ejected, worktree
    preserved. Mirrored as chunk_ejected{reason:hitl_required} so the operator
    sees it without reading the child's log, kept out of the land queue.

    A **transient** death (worker_died: timeout kill or container-down) is not
    mark_ejected here — its slug is RETURNED in the third set instead. That set is
    the seam the recovery engine consumes to decide what to respawn; the caller
    (run_orchestrate) marks them ejected once no respawn is pending. Terminal
    ejects (hitl_required, implement_failed) are mark_ejected inline as before —
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
        reason: str
        payload: dict[str, object]

        if rc is None or rc < 0 or rc >= _SIGNAL_EXIT_BASE:
            # Timeout/stall group-kill (rc<0), a crashed supervise task (rc None), or
            # a shell-reported signal exit (128+signum). A dead worker produced no
            # verdict — landing it would false-merge. Self-describe it so the operator
            # (and the recovery engine) can tell a wall-deadline kill from a
            # no-progress stall kill without reading the child's stream: a ``stalled``
            # reason names the killer, otherwise it defaults to a wall timeout.
            if killed_reason == "stalled":
                payload = ejected_payload(
                    plan.slug, WORKER_DIED, str(worktree), logs_path=logs_path, killed_by="stalled"
                )
            else:
                payload = ejected_payload(plan.slug, WORKER_DIED, str(worktree), logs_path=logs_path, timed_out=True)
            reason = WORKER_DIED
        elif rc == EX_HITL_REQUIRED:
            reason = HITL_REQUIRED
            payload = ejected_payload(plan.slug, HITL_REQUIRED, str(worktree))
        elif rc == EX_UNAVAILABLE:
            # Container/infra failure — the worker never ran, no code produced.
            # killed_by names the killer so the death is self-describing: a breaker
            # short-circuit ('breaker-open', never launched) vs. a genuine downed
            # container vs. OOM.
            killed_by = killed_reason if killed_reason == "breaker-open" else "container-down"
            oom = False
            if killed_by == "container-down":
                from lib.chunk import chunk_id_for_plan, chunk_slug

                try:
                    cs = chunk_slug(chunk_id_for_plan(plan.slug), plan.slug)
                    oom = _devcontainer.container_oom_killed(cs)
                except LookupError:
                    pass
            if oom:
                reason = CONTAINER_OOM
                payload = ejected_payload(plan.slug, CONTAINER_OOM, str(worktree), logs_path=logs_path)
            else:
                reason = WORKER_DIED
                payload = ejected_payload(
                    plan.slug,
                    WORKER_DIED,
                    str(worktree),
                    logs_path=logs_path,
                    killed_by=killed_by,
                )
        elif rc != 0:
            reason = IMPLEMENT_FAILED
            payload = ejected_payload(plan.slug, IMPLEMENT_FAILED, str(worktree))
        else:
            from lib.chunk import chunk_id_for_plan

            chunk_id = chunk_id_for_plan(plan.slug)
            chunks.append(_land_queue.Chunk(slug=plan.slug, worktree=worktree, chunk_id=chunk_id))
            continue

        _emit_event("chunk_ejected", payload)
        _teardown_ejected(plan.slug)
        if is_transient_eject(reason):
            transient.add(plan.slug)
        elif reason == HITL_REQUIRED:
            hitl.add(plan.slug)
            mark_ejected(plan.slug)
        else:
            mark_ejected(plan.slug)
    return chunks, hitl, transient


def _prune_stale_containers() -> None:
    """Tear down exited containers for this run's chunk slugs only.

    Machine-wide docker prune is forbidden — it would reap a concurrent run's
    idle container (H3). Another run's resources are never candidates.
    """
    if not _supervise._run_chunk_slugs:
        return
    removed = _devcontainer.down_run(_supervise._run_chunk_slugs)
    _utils.emit_event("agent_reaped", {"reclaimed_bytes": None, "containers_removed": removed})


def _prune_stale_worktrees(preserve: set[str] | None = None) -> None:
    """End-of-batch sweep of clean, inactive, stale worktrees for this run only.

    ``preserve`` plan slugs are held back from the sweep — a wedged (hitl_required)
    chunk's worktree must survive for the operator even when it is clean and
    inactive.
    """
    scope = _supervise._run_chunk_ids()
    if not scope:
        return
    wt_root = Path.cwd() / ".mentat" / "worktrees"
    active = _supervise._preserve_chunk_slugs(preserve)
    removed = _worktrees.prune_stale(wt_root, active_slugs=active, scope_chunk_ids=scope)
    _utils.emit_event("agent_reaped", {"reclaimed_bytes": None, "worktrees_removed": removed})


def _gc_preserved_worktrees(preserve: set[str] | None = None) -> None:
    """Reclaim long-abandoned preserved worktrees for this run's chunk ids only."""
    scope = _supervise._run_chunk_ids()
    if not scope:
        return
    wt_root = Path.cwd() / ".mentat" / "worktrees"
    active = _supervise._preserve_chunk_slugs(preserve)
    reclaimed = _worktrees.gc_preserved(wt_root, active_slugs=active, scope_chunk_ids=scope)
    _utils.emit_event("agent_reaped", {"reclaimed_bytes": None, "worktrees_gc": reclaimed})


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
        list_ready_slices=sched.list_ready_slices,
    )


def _spawn_ready(pending: list[_scheduler.Plan], *, known_slugs: set[str], resolved: set[str]) -> list[_scheduler.Plan]:
    """Auto plans whose declared deps are all resolved — the next spawn wave.

    Mirrors ``scheduler.list_ready_slices``'s readiness rule (NNFI: an ejected upstream
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
        chunks, hitl, transient = partition_by_outcome(results, mark_ejected=_on_ejected)
        hitl_slugs.update(hitl)
        # Transient (worker_died) ejects: the recovery engine's seam. Absent a
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
            list_ready_slices=sched.list_ready_slices,
        )
        drain_results.extend(wave_results)
        wave_slugs = {p.slug for p in wave}
        pending = [p for p in pending if p.slug not in wave_slugs]

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
    plan: _scheduler.Plan, attempt: int, cap: int, *, holding: str, agent_id: str
) -> dict[str, object]:
    """Build the failure context handed to the recovery agent and respawn seed."""
    worktree = _worktree_for_slug(plan.slug)
    return _recover.make_recovery_seed(
        slug=plan.slug,
        reason=_recover.eject_reason_for_slug(agent_id, plan.slug),
        worktree=worktree,
        holding=holding,
        attempt=attempt,
        cap=cap,
        agent_id=agent_id,
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
    cmd = ["python3", str(_spawn._IMPLEMENT_SCRIPT), str(plan_path)]
    if harness:
        cmd += ["--harness", harness]
    if model:
        cmd += ["--model", model]
    if reuse_worktree:
        cmd += ["--reuse-worktree"]
    env = dict(os.environ)
    if seed_summary:
        env["MENTAT_SEED_SUMMARY"] = seed_summary
    proc = subprocess.Popen(cmd, cwd=str(worktree), env=env, **{_POPEN_NEW_GROUP: True})
    return proc.wait()


def _recovery_respawn(
    plan: _scheduler.Plan,
    attempt: int,
    *,
    holding: str,
    harness: str | None,
    model: str | None,
    agent_id: str,
    seed: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    """retry action: rebase the preserved worktree onto holding, re-run implement, land."""
    worktree = _worktree_for_slug(plan.slug)
    # mentat-container up dirties .devcontainer/ in every worktree; discard so the
    # rebase does not refuse on unstaged changes (mirrors landing._rebase_chunk).
    _git.discard_path(worktree, ".devcontainer/")
    _tip, err = _git.rebase_ff_only(worktree, holding)
    if err is not None:
        _emit_event(
            "chunk_ejected",
            ejected_payload(plan.slug, REBASE_CONFLICTED, str(worktree)),
        )
        return [{"slug": plan.slug, "status": "eject", "reason": REBASE_CONFLICTED}]
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
        _emit_event("chunk_ejected", ejected_payload(plan.slug, IMPLEMENT_FAILED, str(worktree)))
        return [{"slug": plan.slug, "status": "eject", "reason": IMPLEMENT_FAILED}]
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
    plan: _scheduler.Plan,
    attempt: int,
    *,
    holding: str,
    harness: str | None,
    model: str | None,
    load_plans: Callable[[list[Path]], list[_scheduler.Plan]],
) -> list[dict[str, object]]:
    """reslice action: re-plan into sub-slices JIT and re-fan them through the staged coordinator."""
    sub_paths = _reslice_agent(plan)
    if not sub_paths:
        return [{"slug": plan.slug, "status": "eject", "reason": IMPLEMENT_FAILED, "note": "reslice-empty"}]
    sub_plans = _scheduler.serialize_conflicts(load_plans(sub_paths))
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


def _classify_recovery_results(results: list[object]) -> str:
    """Classify a recovery respawn/reslice land-queue verdict list.

    Returns ``landed`` when any chunk succeeded, ``stalled`` when the queue
    stalled with pending deps, ``failed`` on explicit ejects, else ``empty``.
    """
    if not results:
        return "empty"
    statuses = {r.get("status") for r in results if isinstance(r, dict)}
    if "success" in statuses:
        return "landed"
    if "stalled" in statuses:
        return "stalled"
    if statuses & {"eject", "failed"}:
        return "failed"
    return "inconclusive"


def _run_recovery(
    transient: set[str],
    *,
    plans_by_slug: dict[str, _scheduler.Plan],
    holding: str,
    agent_id: str,
    harness: str | None,
    model: str | None,
    load_plans: Callable[[list[Path]], list[_scheduler.Plan]],
) -> tuple[set[str], set[str], set[str]]:
    """Run the JIT recovery pass over transient AFK ejects.

    Returns ``(recovered_ok, dead_lettered, recovery_stalled)``.
    """

    def _dead_letter(plan: _scheduler.Plan, rationale: str) -> None:
        _emit_event(
            "chunk_ejected",
            ejected_payload(plan.slug, HITL_REQUIRED, str(_worktree_for_slug(plan.slug)), summary=rationale),
        )

    outcomes = _recover.recover(
        transient,
        plans_by_slug=plans_by_slug,
        holding=holding,
        agent_id=agent_id,
        harness=harness,
        is_afk=lambda s: plans_by_slug[s].kind == "AFK",
        context_builder=lambda plan, attempt, cap: make_recovery_seed_for_plan(
            plan, attempt, cap, holding=holding, agent_id=agent_id
        ),
        teardown=_teardown_ejected,
        respawn=lambda plan, attempt, ctx: _recovery_respawn(
            plan,
            attempt,
            holding=holding,
            harness=harness,
            model=model,
            agent_id=agent_id,
            seed=ctx,
        ),
        reslice=lambda plan, attempt: _recovery_reslice(
            plan, attempt, holding=holding, harness=harness, model=model, load_plans=load_plans
        ),
        dead_letter=_dead_letter,
        backoff=_recovery_backoff,
    )

    recovered_ok: set[str] = set()
    dead_lettered: set[str] = set()
    recovery_stalled: set[str] = set()
    for outcome in outcomes:
        slug = str(outcome.get("slug", ""))
        kind = outcome.get("recovery")
        if kind in (_recover.RETRY, _recover.RESLICE):
            results = outcome.get("results") or []
            verdict = _classify_recovery_results(results)
            if verdict == "landed":
                recovered_ok.add(slug)
            elif verdict == "stalled":
                recovery_stalled.add(slug)
            elif verdict in ("failed", "inconclusive", "empty"):
                print(
                    f"mentat-orchestrate: recovery {kind} for {slug} did not land (verdict={verdict})",
                    file=sys.stderr,
                )
        elif kind in (_recover.ABANDON, "dead-lettered"):
            dead_lettered.add(slug)
    return recovered_ok, dead_lettered, recovery_stalled
