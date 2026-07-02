"""Build verdict markdown from session log events."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.events import SUMMARY_FILE, EjectReason  # noqa: E402
from lib.loader import load_sibling  # noqa: E402

_sessions = load_sibling(__file__, "sessions")

_SUSPECT_MAP = {
    EjectReason.IMPLEMENT_FAILED: "TDD/gate fail mid-implementation. Check `<chunk>.stdout` for harness output.",
    EjectReason.GATE_FAILED: "Code/LLM gate returned `block`. See payload `message:` field.",
    EjectReason.REBASE_CONFLICTED: "Conflict against holding tip. Worktree preserved at `<where>`.",
    EjectReason.NOT_FF: "Non-fast-forward state. Holding moved while this chunk worked.",
    EjectReason.HITL_REQUIRED: (
        "AFK hit a decision the plan did not resolve and wrote a blocker to "
        "summary.md instead of guessing. See the blocker below / payload `summary`."
    ),
    EjectReason.WORKER_DIED: (
        "Worker process died before emitting a verdict — no code confirmed. "
        "Container/harness crash or timeout. Worktree preserved at `<where>`."
    ),
}

_TERMINAL_EVENTS = ("chunk.landed", "chunk.ejected")


def _terminal_by_chunk(events: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    """Latest terminal (landed/ejected) event per chunk slug.

    A batch session's log dir holds one chunk per slug; ``all_events`` merges them
    ts-sorted. Reducing to the latest terminal *per slug* lets the verdict see each
    chunk's final state instead of only the ts-latest event across the whole batch —
    which would let a later ``chunk.landed`` mask an earlier dead worker."""
    by_slug: dict[str, dict[str, object]] = {}
    for ev in events:  # ts-ascending → later terminal overwrites earlier per slug
        if ev.get("event") in _TERMINAL_EVENTS:
            payload = ev.get("payload")
            slug = cast("dict[str, object]", payload).get("slug", "") if isinstance(payload, dict) else ""
            by_slug[str(slug)] = ev
    return by_slug


def _select_terminal(events: list[dict[str, object]]) -> dict[str, object] | None:
    """The chunk whose fate the verdict reports: an ejected chunk always wins over a
    landed one (doctor diagnoses failure; a dead/ejected chunk is the story), the
    latest by ts within each group. ``None`` when no chunk reached a terminal state."""
    by_slug = _terminal_by_chunk(events)
    ejected = [ev for ev in by_slug.values() if ev.get("event") == "chunk.ejected"]
    if ejected:
        return max(ejected, key=lambda e: str(e.get("ts", "")))
    landed = [ev for ev in by_slug.values() if ev.get("event") == "chunk.landed"]
    return max(landed, key=lambda e: str(e.get("ts", ""))) if landed else None


def build_verdict(session_dir: Path) -> str:
    events = _sessions.all_events(session_dir)
    if not events:
        return (
            "## Verdict\n- Reason: unknown\n- Phase: unknown\n\n"
            "## Expected vs actual\n- Expected: unknown\n- Actual: unknown\n\n"
            "## Regression\n- Last known good commit: unknown\n- Is regression: unknown\n"
        )

    # Per-chunk aggregation: an ejected chunk wins over a landed one, so a later
    # sibling's chunk.landed never masks an earlier dead worker.
    terminal: dict | None = _select_terminal(events)

    last_ev = events[-1]
    first_failed: dict | None = next(
        (e for e in events if e.get("event", "").endswith(".failed") or e.get("event") == "chunk.ejected"),
        None,
    )

    # Verdict section
    if terminal and terminal.get("event") == "chunk.landed":
        reason = "chunk.landed"
        suspect = "None — chunk landed successfully."
    elif terminal and terminal.get("event") == "chunk.ejected":
        slug = terminal["payload"].get("slug", "unknown")
        reason = terminal["payload"].get("reason", "unknown")
        suspect_template = _SUSPECT_MAP.get(reason, f"Unknown reason: {reason}")
        where = terminal["payload"].get("where", "")
        suspect = f"Chunk `{slug}` — {suspect_template.replace('<where>', where)}"
        blocker = terminal["payload"].get("summary")
        if reason == EjectReason.HITL_REQUIRED and blocker:
            suspect = f"{suspect} Blocker: {blocker}"
    else:
        reason = "unknown"
        suspect = "No terminal event found."

    phase = terminal.get("event", "unknown") if terminal else last_ev.get("event", "unknown")
    first_failed_line = f"{first_failed['event']} @ {first_failed['ts']}" if first_failed else "none"

    # Expected vs actual
    spawned = next((e for e in events if e.get("event") == "chunk.spawned"), None)
    started = next((e for e in events if e.get("event") == "plan.started"), None)
    expected = (
        spawned["payload"].get("plan", "unknown")
        if spawned
        else started["payload"].get("path", "unknown")
        if started
        else "unknown"
    )
    actual = f"{reason}" + (f" — {suspect}" if reason != "chunk.landed" else "")

    # Regression
    prior_landed = next((e for e in events if e.get("event") == "chunk.landed"), None)
    if prior_landed:
        last_good = prior_landed["payload"].get("sha", "unknown")
        is_regression = "yes" if terminal and terminal.get("event") == "chunk.ejected" else "no"
    else:
        last_good = "unknown"
        is_regression = "unknown"

    return (
        f"## Verdict\n"
        f"- Reason: {reason}\n"
        f"- Phase: {phase}\n"
        f"- First failed event: {first_failed_line}\n"
        f"- Suspect: {suspect}\n\n"
        f"## Expected vs actual\n"
        f"- Expected: {expected}\n"
        f"- Actual:   {actual}\n\n"
        f"## Regression\n"
        f"- Last known good commit: {last_good}\n"
        f"- Is regression: {is_regression}\n"
    )


def write_diagnosis(session_dir: Path) -> Path:
    content = build_verdict(session_dir)
    diagnosis = session_dir / "diagnosis.md"
    diagnosis.write_text(content)
    return diagnosis


def build_summary(session_dir: Path) -> str:
    """Success-side twin of build_verdict: a one-paragraph report of what the
    session did, for `mentat-session report`. Landed → success line; ejected →
    the failure reason (pointing at diagnosis.md); no terminal → completed in
    session but not yet landed (implement runs the plan; landing is
    orchestrate's job, so a standalone implement success has no chunk.landed)."""
    events = _sessions.all_events(session_dir)

    spawned = next((e for e in events if e.get("event") == "chunk.spawned"), None)
    plan = spawned["payload"].get("plan", spawned["payload"].get("slug", "unknown")) if spawned else "unknown"

    terminal: dict | None = None
    for ev in reversed(events):
        if ev.get("event") in ("chunk.landed", "chunk.ejected"):
            terminal = ev
            break

    if terminal and terminal.get("event") == "chunk.landed":
        p = terminal["payload"]
        outcome = (
            f"Landed `{p.get('slug', 'unknown')}` at `{p.get('sha', 'unknown')}` onto `{p.get('holding', 'unknown')}`."
        )
    elif terminal and terminal.get("event") == "chunk.ejected":
        p = terminal["payload"]
        reason = p.get("reason", "unknown")
        outcome = f"Ejected `{p.get('slug', 'unknown')}` — {reason}."
        blocker = p.get("summary")
        if reason == EjectReason.HITL_REQUIRED and blocker:
            outcome += f" Blocker: {blocker}"
        else:
            outcome += " See diagnosis.md."
    else:
        outcome = "Completed in session; not yet landed (landing is orchestrate's job)."

    return f"## Summary\n- Plan: {plan}\n- Outcome: {outcome}\n- Events recorded: {len(events)}\n"


def write_summary(session_dir: Path) -> Path:
    content = build_summary(session_dir)
    summary = session_dir / SUMMARY_FILE
    summary.write_text(content)
    return summary
