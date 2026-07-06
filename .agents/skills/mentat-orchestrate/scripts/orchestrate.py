#!/usr/bin/env python3
"""mentat-orchestrate — run / fan-out / land-queue / batch-review."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import git as _git  # noqa: E402
from lib import plans as _plans_lib  # noqa: E402
from lib.events import HITL_IN_AGENT, UPSTREAM_EJECTED, ejected_payload, spawned_payload  # noqa: E402
from lib.events import bind as _bind  # noqa: E402
from lib.exits import EX_CONFIG, EX_DATAERR, EX_NOINPUT  # noqa: E402
from lib.loader import load_sibling  # noqa: E402
from lib.agent import ensure_agent  # noqa: E402

_utils = load_sibling(__file__, "plans")
_scheduler = load_sibling(__file__, "scheduler")
_spawn = load_sibling(__file__, "spawn")
_supervise = load_sibling(__file__, "supervise")
_batch = load_sibling(__file__, "batch")

_emit_event = _bind("mentat-orchestrate")


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
                    kind=fm.get("kind", "HITL"),
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
                    if _plans_lib.resolve_plan_ref(dep).exists():
                        continue
                    print(
                        f"unresolved blocked_by '{dep}' in '{plan.slug}' — "
                        "must name an in-batch plan or an on-disk plan file",
                        file=sys.stderr,
                    )
                    raise SystemExit(EX_DATAERR)

    return plans


def _emit_anchored_chunks(plans: list[_scheduler.Plan], *, harness: str | None, model: str | None) -> list[str]:
    """Emit chunk_started{harness:hitl-in-agent} per anchored plan, no subprocess.

    HITL plans run in the **calling Claude agent** — never via subprocess —
    so AskUserQuestion works. The caller queries the audit log
    (`mentat-log query chunk_started --agent=$MENTAT_AGENT`) and drives
    `/mentat-implement <slug>` in-agent per anchored slug, then re-invokes
    `orchestrate land-queue <holding>` with the HITL slugs on stdin.

    Returns slugs anchored this invocation (caller may use them to drive
    /mentat-implement). They are NOT appended to `_land_all` here — landing
    happens on the post-implement land-queue call.
    """
    chunks: list[str] = []
    for plan in plans:
        _utils.emit_event(
            "chunk_started",
            spawned_payload(plan.slug, str(plan.path), harness=HITL_IN_AGENT, worktree=str(Path.cwd())),
        )
        _utils.emit_event("agent_started", {"harness": HITL_IN_AGENT})
        chunks.append(plan.slug)
    return chunks


def run_orchestrate(
    holding: str,
    plan_paths: list[Path],
    *,
    harness: str | None,
    model: str | None,
    dry_run: bool,
) -> int:
    agent_id = ensure_agent("orchestrate", holding)
    print(f"mentat-orchestrate: track this run with `mentat-track track {agent_id}`", file=sys.stderr)
    try:
        _git.require_commit_identity()
    except _git.GitError as e:
        print(f"mentat-orchestrate: {e}", file=sys.stderr)
        return EX_CONFIG
    plans = _load_plans(plan_paths)
    anchored, auto = _scheduler.partition(plans)
    _supervise._run_chunk_slugs.clear()

    if dry_run:
        print(f"[dry-run] would anchor: {[p.slug for p in anchored]}")
        print(f"[dry-run] would spawn: {[p.slug for p in auto]}")
        _batch._land_all([], holding=holding)
        _utils.emit_event(
            "batch_reviewed",
            {"agent_id": agent_id, "summary": f"batch review for agent {agent_id} — advisory"},
        )
        return 0

    _batch._prune_stale_containers()

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
        # (they never appear in `list_ready_slices` as anchored slugs), so anchored plans
        # act as "known but not-yet-landed" deps that gate auto dependents correctly.
        # mark_ejected then cascades across the full plan graph, including HITL
        # downstream — fixing the silent cascade miss when an auto upstream dies.
        sched = _scheduler.Scheduler(anchored + auto)
        known_slugs = {p.slug for p in (anchored + auto)}

        # Staged fan-out: spawn is dep-gated on landing, not fired all-at-once. A
        # chunk whose blocked_by upstream has not landed waits for a later wave.
        drain_results, hitl, transient = _batch._run_batch(
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
        recovered_ok, dead_lettered, recovery_stalled = _batch._run_recovery(
            transient,
            plans_by_slug={p.slug: p for p in (anchored + auto)},
            holding=holding,
            agent_id=agent_id,
            harness=harness,
            model=model,
            load_plans=_load_plans,
        )
        hitl_slugs.update(dead_lettered)
        for slug in recovery_stalled:
            print(f"mentat-orchestrate: recovery stalled — chunk {slug} still pending land", file=sys.stderr)
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
                    "chunk_ejected",
                    ejected_payload(slug, UPSTREAM_EJECTED, where),
                )

        _utils.emit_event(
            "batch_reviewed",
            {"agent_id": agent_id, "summary": f"batch review for agent {agent_id} — advisory"},
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
                print(f"mentat-orchestrate: ejected {slug} — hitl_required", file=sys.stderr)
        else:
            print(f"mentat-orchestrate: review the diff with `git diff {holding}..HEAD`", file=sys.stderr)
        return rc
    finally:
        # Crash-safe teardown: reclaim clean stale worktrees + GC long-abandoned
        # preserved ones on every exit — including an exception mid-batch — so a
        # crash never leaks worktrees or containers. hitl worktrees are held back.
        _batch._prune_stale_worktrees(preserve=hitl_slugs)
        _batch._gc_preserved_worktrees(preserve=hitl_slugs)


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
    fr_p.add_argument("agent_id", help="Agent ID")

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
            _spawn.spawn(plan)

    elif args.cmd == "land-queue":
        slugs = [line.strip() for line in sys.stdin if line.strip()]
        import json

        # Resolve slugs → plan paths for dep-aware drain ordering.  Plans that
        # cannot be resolved (e.g. ad-hoc slugs) are silently skipped; the
        # drain falls back to input order for those chunks.
        plan_paths = [_utils.resolve_plan_ref(s) for s in slugs]
        existing_paths = [p for p in plan_paths if p.exists()]
        lq_plans = _load_plans(existing_paths, _expanding=False) if existing_paths else None
        results = _batch._land_all(slugs, holding=args.holding, plans=lq_plans)
        for r in results:
            print(json.dumps(r))

    elif args.cmd == "batch-review":
        _utils.emit_event(
            "batch_reviewed",
            {"agent_id": args.agent_id, "summary": f"batch review for agent {args.agent_id} — advisory"},
        )


if __name__ == "__main__":
    main()
