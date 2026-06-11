#!/usr/bin/env python3
"""mentat-orchestrate — run / fan-out / land-queue / batch-review."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parents[2]

import importlib.util as _ilu


def _load_sibling(name: str):
    here = Path(__file__).parent
    key = f"{here.parent.name}.{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = _ilu.spec_from_file_location(key, here / f"{name}.py")
    mod = _ilu.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_utils = _load_sibling("utils")
_routing = _load_sibling("routing")
_fan_out = _load_sibling("fan_out")
_land_queue = _load_sibling("land_queue")
_batch_review = _load_sibling("batch_review")


def _resolve_plan_refs(refs: list[str]) -> list[Path]:
    return [_utils.resolve_plan_ref(r) for r in refs]


def _load_plans(paths: list[Path]) -> list[_routing.Plan]:
    plans: list[_routing.Plan] = []
    for path in paths:
        fm = _utils.parse_frontmatter(path)
        blocked_by_raw = fm.get("blocked_by", "")
        blocked_by: list[str] = []
        if blocked_by_raw and blocked_by_raw not in ("[]", ""):
            # parse "[a, b]" or "a, b"
            import re

            parts = re.split(r"[,\s]+", blocked_by_raw)
            blocked_by = [s.strip().strip("[]\"'") for s in parts if s.strip().strip("[]\"'")]
        plans.append(
            _routing.Plan(
                slug=fm.get("id", path.stem),
                class_=fm.get("class", "HITL"),
                blocked_by=blocked_by,
                path=path,
            )
        )
    return plans


def _run_anchored_plans(plans: list[_routing.Plan], *, harness: str | None, model: str | None) -> list[str]:
    """Run anchored (HITL or forced-anchor AFK) plans in current session."""
    implement_script = _SKILL_ROOT / ".agents/skills/mentat-implement/scripts/implement.py"
    chunks: list[str] = []
    for plan in plans:
        cmd = ["python3", str(implement_script), str(plan.path)]
        if harness:
            cmd += ["--harness", harness]
        if model:
            cmd += ["--model", model]
        subprocess.run(cmd)
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
            f"mentat-orchestrate: config.jsonc `concurrency` not int ({raw!r}); defaulting to 3",
            file=sys.stderr,
        )
        return 3
    return max(1, n)


def _fan_out_plans(plans: list[_routing.Plan], *, harness: str | None, model: str | None) -> list[str]:
    """Spawn AFK plans headless, capped at the configured concurrency.

    Blocks the loop when `cap` subprocesses are still alive — waits for one to
    exit via Popen.poll() before spawning the next plan. The cap defaults to 3
    (ADR-0004) and can be overridden via ~/.mentat/config.jsonc `concurrency`.
    """
    cap = _concurrency_cap()
    chunks: list[str] = []
    live: list[subprocess.Popen] = []
    for plan in plans:
        while sum(1 for p in live if p.poll() is None) >= cap:
            time.sleep(0.1)
        session_id, proc = _fan_out.spawn_with_proc(plan, harness=harness, model=model)
        live.append(proc)
        chunks.append(session_id)
    return chunks


def _land_all(chunk_slugs: list[str], *, holding: str) -> list[dict]:
    """Land all chunks onto holding branch serially."""
    chunks = [_land_queue.Chunk(slug=s, worktree=Path.cwd()) for s in chunk_slugs]
    return _land_queue.drain(chunks, holding=holding)


def run_orchestrate(
    holding: str,
    plan_paths: list[Path],
    *,
    harness: str | None,
    model: str | None,
    dry_run: bool,
) -> int:
    plans = _load_plans(plan_paths)
    anchored, auto = _routing.partition(plans)

    if dry_run:
        print(f"[dry-run] would anchor: {[p.slug for p in anchored]}")
        print(f"[dry-run] would spawn: {[p.slug for p in auto]}")
        _land_all([], holding=holding)
        _batch_review.review(session_id=os.environ.get("MENTAT_SESSION", "dry-run"))
        return 0

    # Spawn AFK plans headless
    auto_chunks: list[str] = []
    if auto:
        auto_chunks = _fan_out_plans(auto, harness=harness, model=model)

    # Run anchored plans in current session
    anchored_chunks: list[str] = []
    if anchored:
        anchored_chunks = _run_anchored_plans(anchored, harness=harness, model=model)

    all_chunks = anchored_chunks + auto_chunks
    results = _land_all(all_chunks, holding=holding)

    session_id = os.environ.get("MENTAT_SESSION", f"session-{os.getpid()}")
    _batch_review.review(session_id)

    any_ejected = any(r.get("status") == "eject" for r in results)
    return 1 if any_ejected else 0


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
