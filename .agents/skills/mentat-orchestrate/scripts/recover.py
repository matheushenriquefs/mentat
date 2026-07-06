"""Model-driven JIT recovery for transiently-ejected AFK chunks — ADR-0015.

When a chunk ejects for a *transient* reason (worker_died, not_ff,
preflight_worktree_failed, container_oom: the environment failed it, not its code —
``lib.events.is_transient_eject``) the batch need not give
up. This pass runs AFTER the drain settles, serially: for each transient **AFK** slug
within its attempt cap it hands a recovery AGENT the failure context and applies the
agent's just-in-time decision:

  retry   → re-run implement on the SAME preserved worktree, rebased onto the live
            holding tip (idempotent re-land, never a fresh ``worktree create``).
  reslice → re-plan the failed chunk into smaller slices and re-fan them.
  abandon → dead-letter the chunk to HITL — never a silent eject.

The model decides retry-vs-reslice, not a failure-class heuristic. HITL chunks are
never auto-respawned — the operator owns them. Audit is payload-only (ADR-0007): a
respawn is ``chunk_started{trigger:"recovery", attempt:N}``; the outcome rides the
existing ``chunk_landed`` / ``chunk_ejected`` events.

The side-effecting primitives (respawn / reslice / dead-letter / teardown) are
injected by the caller (orchestrate) so this module stays free of the spawn and
landing imports and is unit-testable in isolation.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

_SCRIPTS_DIR = Path(__file__).resolve().parent
_AGENTS_ROOT = _SCRIPTS_DIR.parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib import config as _config  # noqa: E402, F401
from lib.events import bind  # noqa: E402

_emit_event = bind("mentat-orchestrate")


def _load_sub(name: str) -> Any:
    path = _SCRIPTS_DIR / "recovery" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"mentat_orchestrate_recovery_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load recovery.{name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_guards = _load_sub("guards")
_context = _load_sub("context")
_decision = _load_sub("decision")

RETRY = _decision.RETRY
RESLICE = _decision.RESLICE
ABANDON = _decision.ABANDON

DEFAULT_ATTEMPTS = _guards.DEFAULT_ATTEMPTS
DEFAULT_MAX_RESTARTS = _guards.DEFAULT_MAX_RESTARTS
DEFAULT_RESTART_WINDOW = _guards.DEFAULT_RESTART_WINDOW

StormGuard = _guards.StormGuard
Budget = _guards.Budget


class _PlanLike(Protocol):
    slug: str
    kind: str
    path: Path


def recovery_attempts() -> int:
    return _guards.recovery_attempts()


def recovery_max_restarts() -> int:
    return _guards.recovery_max_restarts()


def recovery_restart_window() -> float:
    return _guards.recovery_restart_window()


def recovery_budget() -> float | None:
    return _guards.recovery_budget()


def attempt_count(agent_id: str, slug: str) -> int:
    return _guards.attempt_count(agent_id, slug)


def _notify(message: str) -> None:
    _guards.notify(message)


def make_recovery_prompt(context: dict[str, object]) -> str:
    return _context.make_recovery_prompt(context)


def build_prompt(context: dict[str, object]) -> str:
    return _context.build_prompt(context)


def distill_progress_note(
    *,
    agent_log_dir: Path | None,
    diff: str,
    holding_tip: str,
    invoke: Callable[[str], str] | None = None,
) -> str:
    return _context.distill_progress_note(
        agent_log_dir=agent_log_dir,
        diff=diff,
        holding_tip=holding_tip,
        invoke=invoke,
        invoke_claude_fn=_invoke_claude if invoke is None else None,
    )


def eject_reason_for_slug(agent_id: str, slug: str) -> str:
    return _context.eject_reason_for_slug(agent_id, slug)


def make_recovery_seed(
    *,
    slug: str,
    reason: str,
    worktree: Path,
    holding: str,
    attempt: int,
    cap: int,
    agent_id: str,
    diff: str,
    invoke: Callable[[str], str] | None = None,
) -> dict[str, object]:
    return _context.make_recovery_seed(
        slug=slug,
        reason=reason,
        worktree=worktree,
        holding=holding,
        attempt=attempt,
        cap=cap,
        agent_id=agent_id,
        diff=diff,
        invoke=invoke,
        invoke_claude_fn=_invoke_claude if invoke is None else None,
        distill_fn=distill_progress_note,
    )


def _extract_json(raw: str) -> str:
    return _decision._extract_json(raw)


def _parse_decision(raw: str) -> dict[str, str]:
    return _decision.parse_decision(raw)


def _invoke_claude(prompt: str) -> str:
    return _decision.invoke_claude(prompt, subprocess_mod=subprocess)


def decide(context: dict[str, object], *, invoke: Callable[[str], str] | None = None) -> dict[str, str]:
    return _decision.decide(
        context,
        invoke=invoke,
        prompt_fn=_context.make_recovery_prompt,
        subprocess_mod=subprocess,
    )


def recover(
    transient_slugs: set[str],
    *,
    plans_by_slug: dict[str, _PlanLike],
    holding: str,
    agent_id: str,
    harness: str | None,
    is_afk: Callable[[str], bool],
    context_builder: Callable[[_PlanLike, int, int], dict[str, object]],
    teardown: Callable[[str], None],
    respawn: Callable[[_PlanLike, int, dict[str, object]], list[dict[str, object]]],
    reslice: Callable[[_PlanLike, int], list[dict[str, object]]],
    dead_letter: Callable[[_PlanLike, str], None],
    decide: Callable[[dict[str, object]], dict[str, str]] | None = None,
    cap: int | None = None,
    backoff: Callable[[int], None] | None = None,
    storm_guard: StormGuard | None = None,
    budget: Budget | None = None,
    notify: Callable[[str], None] | None = None,
) -> list[dict[str, object]]:
    """Run the recovery pass over the transient-ejected set. Returns per-slug outcomes."""
    cap = cap if cap is not None else recovery_attempts()
    decider = decide if decide is not None else globals()["decide"]
    storm = storm_guard if storm_guard is not None else StormGuard(recovery_max_restarts(), recovery_restart_window())
    bud = budget if budget is not None else Budget(recovery_budget())
    notifier = notify if notify is not None else _notify
    outcomes: list[dict[str, object]] = []

    ordered = sorted(transient_slugs)
    for i, slug in enumerate(ordered):
        plan = plans_by_slug.get(slug)
        if plan is None:
            outcomes.append({"slug": slug, "recovery": "unrecoverable", "reason": "no-plan"})
            continue
        if not is_afk(slug):
            outcomes.append({"slug": slug, "recovery": "skipped-hitl"})
            continue

        attempt = attempt_count(agent_id, slug) + 1
        if attempt > cap:
            dead_letter(plan, f"recovery attempt cap ({cap}) exhausted")
            notifier(f"{slug}: attempt cap ({cap}) exhausted — handed to HITL")
            outcomes.append({"slug": slug, "recovery": "dead-lettered", "reason": "attempt-cap"})
            continue

        if not storm.allow() or not bud.allow():
            breach = "restart-storm cap" if not storm.allow() else "recovery budget"
            for rest in ordered[i:]:
                rest_plan = plans_by_slug.get(rest)
                if rest_plan is not None and is_afk(rest):
                    dead_letter(rest_plan, f"{breach} reached — recovery halted")
                    outcomes.append({"slug": rest, "recovery": "dead-lettered", "reason": breach})
            notifier(f"{breach} reached after {i} respawn(s) — escalating {len(ordered[i:])} chunk(s) to HITL")
            break

        if backoff is not None:
            backoff(i)
        teardown(slug)
        context = context_builder(plan, attempt, cap)
        decision = decider(context)
        action = decision.get("action", ABANDON)

        if action == ABANDON:
            dead_letter(plan, decision.get("rationale", ""))
            notifier(f"{slug}: recovery agent chose abandon — handed to HITL")
            outcomes.append({"slug": slug, "recovery": ABANDON, "rationale": decision.get("rationale", "")})
            continue

        storm.record()
        bud.spend()

        _emit_event(
            "chunk_started",
            {
                "slug": slug,
                "plan": str(plan.path),
                "harness": harness or "default",
                "worktree": str(context.get("worktree", "")),
                "trigger": "recovery",
                "attempt": attempt,
            },
        )
        results = respawn(plan, attempt, context) if action == RETRY else reslice(plan, attempt)
        outcomes.append({"slug": slug, "recovery": action, "attempt": attempt, "results": results})

    return outcomes
