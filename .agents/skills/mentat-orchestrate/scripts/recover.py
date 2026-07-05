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
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import config as _config  # noqa: E402
from lib.events import bind  # noqa: E402

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


DEFAULT_MAX_RESTARTS = 3
DEFAULT_RESTART_WINDOW = 60.0


def _int_config(key: str, default: int, *, minimum: int = 1) -> int:
    raw = _config.read_config().get(key, default)
    try:
        return max(minimum, int(raw))
    except (TypeError, ValueError):
        return default


def recovery_attempts() -> int:
    """Per-slug recovery attempt cap. Config ``recovery_attempts`` (default 2, min 1)."""
    return _int_config("recovery_attempts", DEFAULT_ATTEMPTS)


def recovery_max_restarts() -> int:
    """Batch-wide restart-storm intensity: max respawns per window. Config
    ``recovery_max_restarts`` (default 3, min 1) — the OTP supervisor ``MaxR``."""
    return _int_config("recovery_max_restarts", DEFAULT_MAX_RESTARTS)


def recovery_restart_window() -> float:
    """The storm window in seconds — the OTP ``MaxT``. Config
    ``recovery_restart_window`` (default 60)."""
    raw = _config.read_config().get("recovery_restart_window", DEFAULT_RESTART_WINDOW)
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_RESTART_WINDOW


def recovery_budget() -> float | None:
    """Accumulated recovery-cost ceiling for the batch, or None (unlimited). Config
    ``recovery_budget`` — a soft OpenHands-style cost cap (unit-agnostic: respawns
    by default; a caller may charge tokens/wall instead)."""
    raw = _config.read_config().get("recovery_budget")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


class StormGuard:
    """OTP-style restart-intensity limiter (Erlang ``MaxR``/``MaxT``).

    Allows at most ``max_restarts`` respawns within any ``window_s`` sliding window
    across the whole batch. When the window is saturated the batch stops recovering
    and escalates the remainder rather than restart-storming a sick box — the same
    "give up, don't loop" contract an OTP supervisor enforces on its children.
    ``clock`` is injectable for deterministic tests."""

    def __init__(self, max_restarts: int, window_s: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.max_restarts = max(1, max_restarts)
        self.window_s = window_s
        self._clock = clock
        self._stamps: list[float] = []

    def allow(self) -> bool:
        now = self._clock()
        self._stamps = [t for t in self._stamps if now - t <= self.window_s]
        return len(self._stamps) < self.max_restarts

    def record(self) -> None:
        self._stamps.append(self._clock())


class Budget:
    """Accumulated-cost ceiling for a batch's recovery (OpenHands-style).

    ``allow(cost)`` gates the next respawn; ``spend(cost)`` accrues. ``total`` None
    means unlimited. Cost is unit-agnostic — the caller decides whether one unit is
    one respawn, N tokens, or N seconds."""

    def __init__(self, total: float | None = None) -> None:
        self.total = total
        self.spent = 0.0

    def allow(self, cost: float = 1.0) -> bool:
        return self.total is None or self.spent + cost <= self.total

    def spend(self, cost: float = 1.0) -> None:
        self.spent += cost


def _notify(message: str) -> None:
    """Surface an escalation to the operator. Stderr today (audit is the durable
    record); a single seam so a future push/notify backend has one call site."""
    print(f"mentat-recover: ESCALATE — {message}", file=sys.stderr)


def attempt_count(session_id: str, slug: str) -> int:
    """Prior recovery respawns for ``slug``, replayed from the canonical store."""
    from lib import store

    return store.attempt_count(session_id, slug)


_PROMPT_TEMPLATE = """You are a mentat recovery agent. A parallel AFK chunk was ejected for a \
TRANSIENT reason (its environment failed it, not necessarily its code). Decide how to \
recover it. This is attempt {attempt} of {cap}.

Chunk: {slug}
Eject reason: {reason}
Worktree (preserved): {worktree}
Holding tip: {holding}

Progress note (distilled from the dead agent's transcript):
{progress_note}

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

_DISTILL_TEMPLATE = """Distill this AFK agent transcript + worktree diff into a compact handoff note \
for a respawned agent. Output ONLY the note — no preamble.

Format:
## Done
- <completed step> (file pointers: path — what changed)

## In progress
- <partial step> (path — what's left there)

## Pending
- <not started>

## Key decisions
- <decision>

## Git tip
<holding branch tip sha from context>

Transcript (tail):
{transcript}

Worktree diff vs holding (truncated):
{diff}
"""


def make_recovery_prompt(context: dict[str, object]) -> str:
    """Render the recovery-agent prompt from a failure context dict."""
    return _PROMPT_TEMPLATE.format(
        slug=context.get("slug", "?"),
        reason=context.get("reason", "?"),
        worktree=context.get("worktree", "?"),
        holding=context.get("holding", "?"),
        attempt=context.get("attempt", "?"),
        cap=context.get("cap", "?"),
        progress_note=context.get("progress_note") or "(none)",
    )


def build_prompt(context: dict[str, object]) -> str:
    """Deprecated alias for ``make_recovery_prompt``."""
    return make_recovery_prompt(context)


def _transcript_path(agent_log_dir: Path | None) -> Path | None:
    if agent_log_dir is None:
        return None
    for name in ("transcript.jsonl", "session.jsonl"):
        path = agent_log_dir / name
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def _read_tail(path: Path, *, max_bytes: int = 12000) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) <= max_bytes:
        return data.decode("utf-8", errors="replace")
    return data[-max_bytes:].decode("utf-8", errors="replace")


def distill_progress_note(
    *,
    agent_log_dir: Path | None,
    diff: str,
    holding_tip: str,
    invoke: Callable[[str], str] | None = None,
) -> str:
    """Distill transcript + diff into a compact done/pending handoff note.

    Absent transcript → returns ``diff`` unchanged (today's baseline seed).
    """
    transcript_file = _transcript_path(agent_log_dir)
    if transcript_file is None:
        return diff or "(none)"
    invoke = invoke or _invoke_claude
    prompt = _DISTILL_TEMPLATE.format(
        transcript=_read_tail(transcript_file),
        diff=(diff or "(empty)")[:4000],
    )
    if holding_tip:
        prompt = prompt.replace("<holding branch tip sha from context>", holding_tip)
    raw = invoke(prompt).strip()
    return raw if raw else (diff or "(none)")


def _holding_tip_sha(worktree: Path, holding: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", holding],
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _agent_log_dir_for_slug(session_id: str, slug: str) -> Path | None:
    """Resolve the ejected implement agent's log dir from canonical store events."""
    from lib import store

    for row in reversed(store.list_events(session_id)):
        if row.get("event") != "chunk.ejected":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict) or payload.get("slug") != slug:
            continue
        logs_path = payload.get("logs_path")
        if isinstance(logs_path, str) and logs_path:
            return Path(logs_path)
    return None


def make_recovery_seed(
    *,
    slug: str,
    reason: str,
    worktree: Path,
    holding: str,
    attempt: int,
    cap: int,
    session_id: str,
    diff: str,
    invoke: Callable[[str], str] | None = None,
) -> dict[str, object]:
    """Mint the composite recovery context: distilled progress note + metadata."""
    agent_log_dir = _agent_log_dir_for_slug(session_id, slug)
    tip = _holding_tip_sha(worktree, holding)
    progress_note = distill_progress_note(
        agent_log_dir=agent_log_dir,
        diff=diff,
        holding_tip=tip,
        invoke=invoke,
    )
    return {
        "slug": slug,
        "reason": reason,
        "worktree": str(worktree),
        "holding": holding,
        "attempt": attempt,
        "cap": cap,
        "progress_note": progress_note,
        "seed_summary": progress_note,
    }


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
    # _extract_json only ever returns a ``{...}``-bounded slice, so a successful
    # json.loads always yields a dict — a JSON array / scalar reply fails to parse
    # above and degrades to abandon there.
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
    return _parse_decision(invoke(make_recovery_prompt(context)))


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
    """Run the recovery pass over the transient-ejected set. Returns per-slug outcomes.

    Serial by construction (one slug at a time, spaced by ``backoff``) so a recovering
    fleet never re-storms the box under live contention. Each recoverable AFK slug
    within cap gets a fresh worktree/container teardown, a model decision, and the
    matching action.

    Three guardrails escalate to HITL (dead-letter + notify) instead of blind-retrying:
    a per-slug attempt cap, a batch-wide restart-storm intensity cap (``StormGuard``),
    and an accumulated-cost ceiling (``Budget``). A storm or budget breach stops the
    whole pass and escalates every not-yet-recovered slug — the OTP "give up, don't
    loop" contract — so a sick box is never hammered.
    """
    cap = cap if cap is not None else recovery_attempts()
    # Resolve the decider at call time (via the module namespace) so a test — or a
    # caller — can monkeypatch ``decide`` without the def-time default freezing it.
    decider = decide if decide is not None else globals()["decide"]
    storm = storm_guard if storm_guard is not None else StormGuard(recovery_max_restarts(), recovery_restart_window())
    bud = budget if budget is not None else Budget(recovery_budget())
    notifier = notify if notify is not None else _notify
    outcomes: list[dict[str, object]] = []

    ordered = sorted(transient_slugs)
    for i, slug in enumerate(ordered):
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
            notifier(f"{slug}: attempt cap ({cap}) exhausted — handed to HITL")
            outcomes.append({"slug": slug, "recovery": "dead-lettered", "reason": "attempt-cap"})
            continue

        # Batch-wide give-up rungs: a storm-intensity or budget breach escalates this
        # slug AND every remaining one, then stops — never keep restarting a sick box.
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

        # Charge the storm-intensity + budget rungs only for an ACTUAL respawn
        # (retry/reslice). An abandon short-circuits above without charging, so a
        # decision that never respawns can't prematurely trip the batch-wide give-up
        # rungs and dead-letter still-recoverable siblings.
        storm.record()
        bud.spend()

        # Payload-only respawn audit (ADR-0007): the outcome rides the existing
        # chunk.landed / chunk.ejected from the re-drained chunk.
        _emit_event(
            "chunk.spawned",
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
