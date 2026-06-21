#!/usr/bin/env python3
"""mentat-orchestrate — run / fan-out / land-queue / batch-review."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.events import HITL_IN_SESSION, EjectReason, ejected_payload, spawned_payload  # noqa: E402
from lib.events import bind as _bind  # noqa: E402
from lib.exits import EX_DATAERR, EX_HITL_REQUIRED, EX_NOINPUT  # noqa: E402
from lib.loader import load_sibling  # noqa: E402
from lib.session import ensure_session  # noqa: E402

_utils = load_sibling(__file__, "utils")
_scheduler = load_sibling(__file__, "scheduler")
_fan_out = load_sibling(__file__, "fan_out")
_land_queue = load_sibling(__file__, "land_queue")
_batch_review = load_sibling(__file__, "batch_review")
_coordinator = load_sibling(__file__, "coordinator")


def _resolve_plan_refs(refs: list[str]) -> list[Path]:
    return [_utils.resolve_plan_ref(r) for r in refs]


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

    if not _expanding and parent_slugs:
        for plan in plans:
            for dep in plan.blocked_by:
                if dep in parent_slugs:
                    print(f"cannot block on parent index: {dep}", file=sys.stderr)
                    raise SystemExit(EX_DATAERR)

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
    cfg = _utils.read_config()
    raw = cfg.get("concurrency", 3)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        print(
            f"mentat-orchestrate: config.toml `concurrency` not int ({raw!r}); defaulting to 3",
            file=sys.stderr,
        )
        return 3
    return max(1, n)


_emit_event = _bind("mentat-orchestrate")


def _fan_out_plans(
    plans: list[_scheduler.Plan], *, harness: str | None, model: str | None
) -> list[tuple[_scheduler.Plan, int]]:
    """Spawn AFK plans headless, capped at the configured concurrency.

    Blocks the loop when `cap` subprocesses are still alive — waits for one to
    exit via Popen.poll() before spawning the next plan. The cap defaults to 3
    (ADR-0004) and can be overridden via ~/.mentat/config.toml `concurrency`.

    Returns each plan paired with its child exit code, so the caller can route a
    ``EX_HITL_REQUIRED`` (42) child away from landing (S5) — a wedged AFK self-
    ejected and left its worktree for the operator; landing it would false-merge
    empty or partial work.
    """
    cap = _concurrency_cap()
    live: list[tuple[_scheduler.Plan, subprocess.Popen]] = []
    for plan in plans:
        while sum(1 for _, p in live if p.poll() is None) >= cap:
            time.sleep(0.1)
        _session_id, proc = _fan_out.spawn_with_proc(plan, harness=harness, model=model)
        live.append((plan, proc))
    results: list[tuple[_scheduler.Plan, int]] = []
    for plan, p in live:
        p.wait()
        results.append((plan, p.returncode))
    return results


def _partition_fanout(results, *, emit, mark_ejected, worktree_for):
    """Split fan-out (plan, returncode) results into (landable_chunks, hitl_slugs).

    A child that exited ``EX_HITL_REQUIRED`` is a wedge: it self-ejected and
    preserved its worktree for the operator. We mirror that as an orchestrate-
    session ``chunk.ejected{reason: hitl-required}`` (so the orchestrate operator
    sees it without reading the child's log), cascade it through the scheduler so
    blocked downstream chunks are skipped not stalled, and keep its slug out of
    the land queue. Every other child becomes a landable Chunk. Pure but for the
    injected ``emit`` / ``mark_ejected`` / ``worktree_for`` collaborators.
    """
    chunks = []
    hitl: set[str] = set()
    for plan, rc in results:
        worktree = worktree_for(plan.slug)
        if rc == EX_HITL_REQUIRED:
            hitl.add(plan.slug)
            emit("chunk.ejected", ejected_payload(plan.slug, EjectReason.HITL_REQUIRED, str(worktree)))
            mark_ejected(plan.slug)
        else:
            chunks.append(_land_queue.Chunk(slug=plan.slug, worktree=worktree))
    return chunks, hitl


def _prune_stale_containers() -> None:
    """Prune stale labeled containers — unless a stale worktree is dirty (its
    leftovers need a runnable container). Identity-by-path via lib.worktrees."""
    from lib import devcontainer, worktrees

    wt_root = Path.cwd() / ".mentat" / "worktrees"
    dirty = worktrees.dirty_stale(wt_root)
    if dirty:
        for name in dirty:
            print(f"devcontainer: skipping prune — dirty worktree '{name}'", file=sys.stderr)
        return

    result = devcontainer.prune()
    _utils.emit_event("session.prune", {"reclaimed_bytes": result.reclaimed_bytes})


def _prune_stale_worktrees(preserve: set[str] | None = None) -> None:
    """End-of-batch sweep of clean, inactive, stale worktrees (shared lib).

    ``preserve`` slugs are held back from the sweep — a wedged (hitl-required)
    chunk's worktree must survive for the operator even when it is clean and
    inactive (S5). They are folded into the active set the prune treats as live.
    """
    from lib import devcontainer, worktrees

    wt_root = Path.cwd() / ".mentat" / "worktrees"
    active = set(devcontainer.list_active_slugs()) | (preserve or set())
    removed = worktrees.prune_stale(wt_root, active_slugs=active)
    _utils.emit_event("session.prune", {"reclaimed_bytes": None, "worktrees_removed": removed})


def _worktree_for_slug(slug: str) -> Path:
    """Find worktree path registered for branch <slug>. Falls back to cwd."""
    r = subprocess.run(["git", "worktree", "list", "--porcelain"], capture_output=True, text=True)
    if r.returncode == 0:
        current: Path | None = None
        for line in r.stdout.splitlines():
            if line.startswith("worktree "):
                current = Path(line[len("worktree ") :])
            elif (
                line.startswith("branch refs/heads/")
                and current is not None
                and line[len("branch refs/heads/") :] == slug
            ):
                return current
    return Path.cwd()


def _land_all(chunk_slugs: list[str], *, holding: str, plans: list | None = None) -> list[dict]:
    """Land all chunks onto holding branch serially.

    When `plans` is provided, build a `Scheduler` so drain pulls chunks in
    topo order (blocked downstream chunks wait for upstreams to land).
    Independent AFKs with empty `blocked_by` flow in input order — same
    contract as before slice-2. `plans=None` keeps the legacy iter-only
    path for callers that don't know about cross-chunk deps (e.g. the
    debug `land-queue` subcommand reading slugs from stdin).
    """
    chunks = [_land_queue.Chunk(slug=s, worktree=_worktree_for_slug(s)) for s in chunk_slugs]
    if plans is None:
        return _land_queue.drain(chunks, holding=holding)
    _sched_mod = load_sibling(__file__, "scheduler")
    sched = _sched_mod.Scheduler(plans)
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
        _batch_review.review(session_id=session_id)
        return 0

    _prune_stale_containers()

    # Anchored (HITL) plans: emit chunk.spawned{harness:hitl-in-session} and return
    # control to caller. They do NOT land in this invocation — caller drives
    # /mentat-implement in-session, then re-invokes `orchestrate land-queue`.
    if anchored:
        _emit_anchored_chunks(anchored, harness=harness, model=model)

    # AFK plans: delegate fan-out → drain → review to BatchCoordinator. The
    # scheduler is shared with the fan-out adapter so a hitl-required child can
    # cascade-eject its downstream chunks before the drain pulls them (S5).
    sched = _scheduler.Scheduler(auto)
    hitl_slugs: set[str] = set()

    class _FanOutAdapter:
        """Spawns AFK plans headless; returns landable Chunks. A child that exited
        EX_HITL_REQUIRED is routed away from landing, its worktree preserved."""

        def run(self, plans):
            results = _fan_out_plans(plans, harness=harness, model=model)
            chunks, hitl = _partition_fanout(
                results,
                emit=_emit_event,
                mark_ejected=sched.mark_ejected,
                worktree_for=_worktree_for_slug,
            )
            hitl_slugs.update(hitl)
            return chunks

    coord = _coordinator.BatchCoordinator(
        scheduler=sched,
        fan_out=_FanOutAdapter(),
        land_queue=_land_queue,
        batch_review=_batch_review,
    )
    result = coord.run(auto, session_id, holding=holding)

    # Preserve wedged worktrees from the end-of-batch sweep so the operator can
    # resume them after making the design call.
    _prune_stale_worktrees(preserve=hitl_slugs)

    rc = 1 if result.ejected or hitl_slugs else 0
    if rc == 0:
        from lib.config import load_config_file as _load_cfg

        _cfg_path = Path.home() / ".mentat" / "config.toml"
        _cfg = _load_cfg(_cfg_path) if _cfg_path.exists() else {}
        diff_tool = _cfg.get("diff_tool") or "git diff"
        print(f"mentat-orchestrate: review the diff with `{diff_tool}`", file=sys.stderr)
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
        paths = _resolve_plan_refs(args.plan_refs)
        sys.exit(
            run_orchestrate(
                args.holding,
                paths,
                harness=args.harness,
                model=args.model,
                dry_run=args.dry_run,
            )
        )

    elif args.cmd == "fan-out":
        paths = _resolve_plan_refs(args.plan_refs)
        plans = _load_plans(paths)
        for plan in plans:
            _fan_out.spawn(plan)

    elif args.cmd == "land-queue":
        slugs = [line.strip() for line in sys.stdin if line.strip()]
        import json

        results = _land_all(slugs, holding=args.holding)
        for r in results:
            print(json.dumps(r))

    elif args.cmd == "batch-review":
        _batch_review.review(args.session)


if __name__ == "__main__":
    main()
