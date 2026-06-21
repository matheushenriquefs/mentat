#!/usr/bin/env python3
"""mentat-orchestrate — run / fan-out / land-queue / batch-review."""

from __future__ import annotations

import argparse
import re
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
from lib import paths  # noqa: E402
from lib import worktrees as _worktrees  # noqa: E402
from lib.events import HITL_IN_SESSION, EjectReason, ejected_payload, spawned_payload  # noqa: E402
from lib.events import bind as _bind  # noqa: E402
from lib.exits import EX_DATAERR, EX_HITL_REQUIRED, EX_NOINPUT  # noqa: E402
from lib.loader import load_sibling  # noqa: E402
from lib.session import ensure_session  # noqa: E402
from lib.session import summary_file as _summary_file

_utils = load_sibling(__file__, "plans")
_scheduler = load_sibling(__file__, "scheduler")
_fan_out = load_sibling(__file__, "fan_out")
_land_queue = load_sibling(__file__, "land_queue")


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
    """Max parallel AFK chunk processes. Honors ADR-0004: default 3, tunable via config."""
    raw = _utils.read_config().get("concurrency", 3)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 3


_emit_event = _bind("mentat-orchestrate")


def _read_chunk_seed(session_id: str) -> str | None:
    """Return summary.md content for session_id if it exists."""
    sf = _summary_file(session_id)
    return sf.read_text() if sf.exists() else None


def _fan_out_plans(
    plans: list[_scheduler.Plan], *, harness: str | None, model: str | None
) -> list[tuple[_scheduler.Plan, int]]:
    """Spawn AFK plans headless, capped at the configured concurrency.

    Blocks the loop when `cap` subprocesses are still alive — waits for one to
    exit via Popen.poll() before spawning the next plan. The cap defaults to 3
    (ADR-0004) and can be overridden via ~/.mentat/config.toml `concurrency`.

    Returns each plan paired with its child exit code, so the caller can route a
    ``EX_HITL_REQUIRED`` (42) child away from landing — a wedged AFK self-ejected
    and left its worktree for the operator; landing it would false-merge empty or
    partial work.

    After each chunk exits, reads its summary.md and seeds the next
    spawn so context survives across chunk boundaries.
    """
    cap = _concurrency_cap()
    live: list[tuple[_scheduler.Plan, subprocess.Popen, str]] = []
    seed_summary: str | None = None
    for plan in plans:
        while sum(1 for _, p, _ in live if p.poll() is None) >= cap:
            time.sleep(0.1)
        # Harvest seeds from any chunks that finished while we waited.
        for _plan, p, sid in live:
            if p.poll() is not None:
                seed_summary = _read_chunk_seed(sid) or seed_summary
        _session_id, proc = _fan_out.spawn_with_proc(plan, harness=harness, model=model, seed_summary=seed_summary)
        live.append((plan, proc, _session_id))
    results: list[tuple[_scheduler.Plan, int]] = []
    for plan, p, _sid in live:
        p.wait()
        results.append((plan, p.returncode))
    return results


def _partition_fanout(
    results: list[tuple[_scheduler.Plan, int]],
    *,
    mark_ejected: Callable[[str], list[str]],
) -> tuple[list[_land_queue.Chunk], set[str]]:
    """Split fan-out (plan, returncode) results into (landable_chunks, hitl_slugs).

    A child that exited EX_HITL_REQUIRED is a wedge: self-ejected, worktree
    preserved. Mirrored as chunk.ejected{reason:hitl-required} so the operator
    sees it without reading the child's log, cascaded through the scheduler so
    blocked downstream chunks are skipped, kept out of the land queue.
    """
    chunks = []
    hitl: set[str] = set()
    for plan, rc in results:
        worktree = _worktree_for_slug(plan.slug)
        if rc < 0 or rc >= 128:
            # Signal kill (rc<0 from Popen) or shell-reported signal exit (128+signum).
            # A dead worker produced no verdict — landing it would false-merge.
            _emit_event("chunk.ejected", ejected_payload(plan.slug, EjectReason.WORKER_DIED, str(worktree)))
            mark_ejected(plan.slug)
        elif rc == EX_HITL_REQUIRED:
            hitl.add(plan.slug)
            _emit_event("chunk.ejected", ejected_payload(plan.slug, EjectReason.HITL_REQUIRED, str(worktree)))
            mark_ejected(plan.slug)
        else:
            chunks.append(_land_queue.Chunk(slug=plan.slug, worktree=worktree))
    return chunks, hitl


def _prune_stale_containers() -> None:
    """Prune stale labeled containers — unless a stale worktree is dirty (its
    leftovers need a runnable container). Identity-by-path via lib.worktrees."""
    wt_root = Path.cwd() / ".mentat" / "worktrees"
    dirty = _worktrees.dirty_stale(wt_root)
    if dirty:
        for name in dirty:
            print(f"devcontainer: skipping prune — dirty worktree '{name}'", file=sys.stderr)
        return

    result = _devcontainer.prune()
    _utils.emit_event("session.prune", {"reclaimed_bytes": result.reclaimed_bytes})


def _prune_stale_worktrees(preserve: set[str] | None = None) -> None:
    """End-of-batch sweep of clean, inactive, stale worktrees (shared lib).

    ``preserve`` slugs are held back from the sweep — a wedged (hitl-required)
    chunk's worktree must survive for the operator even when it is clean and
    inactive. They are folded into the active set the prune treats as live.
    """
    wt_root = Path.cwd() / ".mentat" / "worktrees"
    active = set(_devcontainer.list_active_slugs()) | (preserve or set())
    removed = _worktrees.prune_stale(wt_root, active_slugs=active)
    _utils.emit_event("session.prune", {"reclaimed_bytes": None, "worktrees_removed": removed})


def _spawn_batch_doctor() -> None:
    """Non-blocking doctor spawn after a failed batch. Swallows all errors."""
    import contextlib

    _session_script = paths.SKILLS_DIR / "mentat-session/scripts/session.py"
    if not _session_script.exists():
        return
    with contextlib.suppress(OSError):
        subprocess.Popen(
            ["python3", str(_session_script), "doctor", "--reason=batch-failed"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _worktree_for_slug(slug: str) -> Path:
    """Find worktree path registered for branch <slug>. Falls back to cwd."""
    return _git.worktree_for_slug(slug)


def _land_all(
    chunk_slugs: list[str],
    *,
    holding: str,
    plans: list[_scheduler.Plan] | None = None,
) -> list[dict[str, object]]:
    """Land chunks onto holding branch serially (debug land-queue subcommand + dry-run)."""
    chunks = [_land_queue.Chunk(slug=s, worktree=_worktree_for_slug(s)) for s in chunk_slugs]
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

    if anchored:
        _emit_anchored_chunks(anchored, harness=harness, model=model)

    # Build Scheduler from ALL plans (anchored + auto) so cross-partition
    # blocked_by edges are tracked.  auto chunks are the only spawn candidates
    # (they never appear in `next_ready` as anchored slugs), so anchored plans
    # act as "known but not-yet-landed" deps that gate auto dependents correctly.
    # mark_ejected then cascades across the full plan graph, including HITL
    # downstream — fixing the silent cascade miss when an auto upstream dies.
    sched = _scheduler.Scheduler(anchored + auto)
    hitl_slugs: set[str] = set()

    results = _fan_out_plans(auto, harness=harness, model=model)
    chunks, hitl = _partition_fanout(results, mark_ejected=sched.mark_ejected)
    hitl_slugs.update(hitl)

    drain_results = _land_queue.drain(
        chunks,
        holding=holding,
        on_landed=sched.mark_landed,
        on_ejected=sched.mark_ejected,
        next_ready=sched.next_ready,
    )
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

    _prune_stale_worktrees(preserve=hitl_slugs)

    rc = 1 if sched.has_ejections() or hitl_slugs or stalled else 0
    if rc != 0:
        _spawn_batch_doctor()
    else:
        print(f"mentat-orchestrate: review the diff with `git diff {holding}..HEAD`", file=sys.stderr)
    return rc


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
