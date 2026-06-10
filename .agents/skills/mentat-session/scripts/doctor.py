"""Build verdict markdown from session log events."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sessions as _sessions

_SUSPECT_MAP = {
    "implement-failed": "TDD/gate fail mid-implementation. Check `<chunk>.stdout` for harness output.",
    "gate-failed": "Code/LLM gate returned `block`. See payload `message:` field.",
    "rebase-conflicted": "Conflict against holding tip. Worktree preserved at `<where>`.",
    "not-ff": "Non-fast-forward state. Holding moved while this chunk worked.",
    "hitl-required": "AFK ambiguity detected. Self-answered-question pattern in session JSONL.",
}


def build_verdict(session_dir: Path) -> str:
    events = _sessions.all_events(session_dir)
    if not events:
        return "## Verdict\n- Reason: unknown\n- Phase: unknown\n\n## Expected vs actual\n- Expected: unknown\n- Actual: unknown\n\n## Regression\n- Last known good commit: unknown\n- Is regression: unknown\n"

    # Find last chunk.ejected or chunk.landed
    terminal: dict | None = None
    for ev in reversed(events):
        if ev.get("event") in ("chunk.ejected", "chunk.landed"):
            terminal = ev
            break

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
        reason = terminal["payload"].get("reason", "unknown")
        suspect_template = _SUSPECT_MAP.get(reason, f"Unknown reason: {reason}")
        where = terminal["payload"].get("where", "")
        suspect = suspect_template.replace("<where>", where)
    else:
        reason = "unknown"
        suspect = "No terminal event found."

    phase = last_ev.get("event", "unknown")
    first_failed_line = (
        f"{first_failed['event']} @ {first_failed['ts']}" if first_failed
        else "none"
    )

    # Expected vs actual
    spawned = next((e for e in events if e.get("event") == "chunk.spawned"), None)
    started = next((e for e in events if e.get("event") == "plan.started"), None)
    expected = (
        spawned["payload"].get("plan", "unknown") if spawned
        else started["payload"].get("path", "unknown") if started
        else "unknown"
    )
    actual = (
        f"{reason}" + (f" — {suspect}" if reason != "chunk.landed" else "")
    )

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
