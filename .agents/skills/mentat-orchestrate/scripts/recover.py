"""Model-driven JIT recovery for transiently-ejected AFK chunks — ADR-0015.

When a chunk ejects for a *transient* reason (worker-died / not-ff: the environment
failed it, not its code — ``lib.events.is_transient_eject``) the batch need not give
up. This pass runs AFTER the drain settles, serially: for each transient **AFK** slug
within its attempt cap it hands a recovery AGENT the failure context and applies the
agent's just-in-time decision:

  retry   → re-run implement on the SAME preserved worktree, rebased onto the live
            holding tip (idempotent re-land, never a fresh ``worktree create``).
  reslice → re-plan the failed chunk into smaller slices and re-fan them.
  abandon → dead-letter the chunk to HITL — never a silent eject.

The model decides retry-vs-reslice, not a failure-class heuristic. HITL chunks are
never auto-respawned — the operator owns them. Audit is payload-only (ADR-0007): a
respawn is ``chunk.spawned{trigger:"recovery", attempt:N}``; the outcome rides the
existing ``chunk.landed`` / ``chunk.ejected`` events.

The side-effecting primitives (respawn / reslice / dead-letter / teardown) are
injected by the caller (orchestrate) so this module stays free of the fan-out and
land-queue imports and is unit-testable in isolation.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import config as _config  # noqa: E402
from lib.events import bind  # noqa: E402
from lib.session import session_dir as _session_dir  # noqa: E402

_emit_event = bind("mentat-orchestrate")

# The three recovery actions the agent may choose (and the wire strings).
RETRY = "retry"
RESLICE = "reslice"
ABANDON = "abandon"
_ACTIONS = frozenset({RETRY, RESLICE, ABANDON})

DEFAULT_ATTEMPTS = 2


class _PlanLike(Protocol):
    slug: str
    class_: str
    path: Path


def recovery_attempts() -> int:
    """Per-slug recovery attempt cap. Config ``recovery_attempts`` (default 2, min 1)."""
    raw = _config.read_config().get("recovery_attempts", DEFAULT_ATTEMPTS)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_ATTEMPTS


def attempt_count(session_id: str, slug: str) -> int:
    """Prior recovery respawns for ``slug``, replayed from the durable audit log.

    Counts ``chunk.spawned`` rows carrying ``trigger:"recovery"`` for this slug
    across the session's NDJSON log dir. Log-derived so the count survives a
    resume — the sqlite projection is disposable, the log is the truth (ADR-0007).
    """
    log_dir = _session_dir(session_id)
    if not log_dir.exists():
        return 0
    count = 0
    for log_file in sorted(log_dir.glob("*.jsonl")):
        try:
            lines = log_file.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event") != "chunk.spawned":
                continue
            payload = row.get("payload") or {}
            if payload.get("slug") == slug and payload.get("trigger") == "recovery":
                count += 1
    return count


_PROMPT_TEMPLATE = """You are a mentat recovery agent. A parallel AFK chunk was ejected for a \
TRANSIENT reason (its environment failed it, not necessarily its code). Decide how to \
recover it. This is attempt {attempt} of {cap}.

Chunk: {slug}
Eject reason: {reason}
Worktree (preserved): {worktree}
Holding tip: {holding}

Diagnosis:
{diagnosis}

Partial diff (what the chunk produced before it died):
{diff}

Choose exactly one action and reply with ONLY a JSON object, no prose:
  {{"action": "retry",   "rationale": "..."}}  re-run the SAME work rebased onto holding \
(pick this when the failure looks purely environmental — a timeout, a downed container, a \
merge that raced out of fast-forward).
  {{"action": "reslice", "rationale": "..."}}  the chunk is too big to finish in one deadline; \
re-plan it into smaller slices (pick this when the work itself is the problem — it timed out \
because it was doing too much).
  {{"action": "abandon", "rationale": "..."}}  do not retry; hand back to a human (pick this \
when retrying or reslicing cannot help).
"""


def build_prompt(context: dict[str, object]) -> str:
    """Render the recovery-agent prompt from a failure context dict."""
    return _PROMPT_TEMPLATE.format(
        slug=context.get("slug", "?"),
        reason=context.get("reason", "?"),
        worktree=context.get("worktree", "?"),
        holding=context.get("holding", "?"),
        attempt=context.get("attempt", "?"),
        cap=context.get("cap", "?"),
        diagnosis=context.get("diagnosis") or "(none)",
        diff=context.get("diff") or "(none)",
    )


def _extract_json(raw: str) -> str:
    """Slice the first balanced ``{...}`` object out of a possibly-chatty reply."""
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in reply")
    return raw[start : end + 1]


def _parse_decision(raw: str) -> dict[str, str]:
    """Parse the agent reply into ``{action, rationale}``.

    Any unparseable reply or unrecognized action degrades to ``abandon`` — the
    safe escalate rung (never a blind retry against an unclassifiable failure)."""
    try:
        obj = json.loads(_extract_json(raw))
    except (json.JSONDecodeError, ValueError):
        return {"action": ABANDON, "rationale": "unparseable recovery decision"}
    if not isinstance(obj, dict):
        return {"action": ABANDON, "rationale": "recovery decision was not an object"}
    action = obj.get("action")
    if action not in _ACTIONS:
        return {"action": ABANDON, "rationale": f"unrecognized recovery action {action!r}"}
    return {"action": action, "rationale": str(obj.get("rationale", ""))}


def _invoke_claude(prompt: str) -> str:
    """Run the recovery agent headless (claude --print, AFK-safe) and return stdout.

    A non-zero exit or launch failure yields an empty string, which
    ``_parse_decision`` turns into a safe ``abandon``."""
    cmd = ["claude", "--print", prompt, "--dangerously-skip-permissions", "--disallowedTools", "AskUserQuestion"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except OSError:
        return ""
    return result.stdout if result.returncode == 0 else ""


def decide(context: dict[str, object], *, invoke: Callable[[str], str] | None = None) -> dict[str, str]:
    """Ask the recovery agent how to recover a chunk. Returns ``{action, rationale}``."""
    invoke = invoke or _invoke_claude
    return _parse_decision(invoke(build_prompt(context)))


def recover(
    transient_slugs: set[str],
    *,
    plans_by_slug: dict[str, _PlanLike],
    holding: str,
    session_id: str,
    harness: str | None,
    is_afk: Callable[[str], bool],
    context_builder: Callable[[_PlanLike, int, int], dict[str, object]],
    teardown: Callable[[str], None],
    respawn: Callable[[_PlanLike, int], list[dict[str, object]]],
    reslice: Callable[[_PlanLike, int], list[dict[str, object]]],
    dead_letter: Callable[[_PlanLike, str], None],
    decide: Callable[[dict[str, object]], dict[str, str]] | None = None,
    cap: int | None = None,
    backoff: Callable[[int], None] | None = None,
) -> list[dict[str, object]]:
    """Run the recovery pass over the transient-ejected set. Returns per-slug outcomes.

    Serial by construction (one slug at a time, spaced by ``backoff``) so a recovering
    fleet never re-storms the box under live contention. Each recoverable AFK slug
    within cap gets a fresh worktree/container teardown, a model decision, and the
    matching action; a HITL slug or a cap breach is escalated, never blindly retried.
    """
    cap = cap if cap is not None else recovery_attempts()
    # Resolve the decider at call time (via the module namespace) so a test — or a
    # caller — can monkeypatch ``decide`` without the def-time default freezing it.
    decider = decide if decide is not None else globals()["decide"]
    outcomes: list[dict[str, object]] = []

    for i, slug in enumerate(sorted(transient_slugs)):
        plan = plans_by_slug.get(slug)
        if plan is None:
            # Ad-hoc / external slug with no loaded plan — nothing to recover from.
            outcomes.append({"slug": slug, "recovery": "unrecoverable", "reason": "no-plan"})
            continue
        if not is_afk(slug):
            # HITL is never auto-respawned — the operator owns it.
            outcomes.append({"slug": slug, "recovery": "skipped-hitl"})
            continue

        attempt = attempt_count(session_id, slug) + 1
        if attempt > cap:
            dead_letter(plan, f"recovery attempt cap ({cap}) exhausted")
            outcomes.append({"slug": slug, "recovery": "dead-lettered", "reason": "attempt-cap"})
            continue

        if backoff is not None:
            backoff(i)
        teardown(slug)
        decision = decider(context_builder(plan, attempt, cap))
        action = decision.get("action", ABANDON)

        if action == ABANDON:
            dead_letter(plan, decision.get("rationale", ""))
            outcomes.append({"slug": slug, "recovery": ABANDON, "rationale": decision.get("rationale", "")})
            continue

        # Payload-only respawn audit (ADR-0007): the outcome rides the existing
        # chunk.landed / chunk.ejected from the re-drained chunk.
        _emit_event(
            "chunk.spawned",
            {
                "slug": slug,
                "plan": str(plan.path),
                "harness": harness or "default",
                "worktree": str(context_builder(plan, attempt, cap).get("worktree", "")),
                "trigger": "recovery",
                "attempt": attempt,
            },
        )
        results = respawn(plan, attempt) if action == RETRY else reslice(plan, attempt)
        outcomes.append({"slug": slug, "recovery": action, "attempt": attempt, "results": results})

    return outcomes
