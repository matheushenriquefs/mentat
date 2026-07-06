"""Diagnose loop and verdict rendering from the canonical store."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import store  # noqa: E402
from lib.events import (
    CONTAINER_OOM,
    GATE_FAILED,
    GIT_ERROR,
    HITL_REQUIRED,
    IMPLEMENT_FAILED,
    MAIN_TREE_REFUSED,
    NOT_FF,
    PREFLIGHT_WORKTREE_FAILED,
    REBASE_CONFLICTED,
    SUMMARY_FILE,
    UPSTREAM_EJECTED,
    WORKER_DIED,
)  # noqa: E402

_SUSPECT_MAP = {
    IMPLEMENT_FAILED: "TDD/gate fail mid-implementation. Check `<chunk>.stdout` for harness output.",
    GATE_FAILED: "Code/LLM gate returned `block`. See payload `message:` field.",
    REBASE_CONFLICTED: "Conflict against holding tip. Worktree preserved at `<where>`.",
    NOT_FF: "Non-fast-forward state. Holding moved while this chunk worked.",
    GIT_ERROR: "Ambiguous git failure during land. Worktree preserved at `<where>`; inspect git output.",
    HITL_REQUIRED: (
        "AFK hit a decision the plan did not resolve and wrote a blocker to "
        "summary.md instead of guessing. See the blocker below / payload `summary`."
    ),
    PREFLIGHT_WORKTREE_FAILED: "Worktree create/isolation failed before implement ran. Environment failure.",
    MAIN_TREE_REFUSED: "Implement refused to run in the shared main tree. Worktree preserved at `<where>`.",
    UPSTREAM_EJECTED: "A blocked-by upstream ejected; this chunk never ran.",
    WORKER_DIED: (
        "Worker process died before emitting a verdict — no code confirmed. "
        "Container/harness crash or timeout. Worktree preserved at `<where>`."
    ),
    CONTAINER_OOM: "Chunk container hit memory limit (OOMKilled). Environment failure; retry may succeed.",
}

_TERMINAL_EVENTS = ("chunk_landed", "chunk_ejected")


def _events_for_dir(agent_dir: Path) -> list[dict[str, object]]:
    return store.list_events(agent_dir.name)


def _terminal_by_chunk(events: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    by_slug: dict[str, dict[str, object]] = {}
    for ev in events:
        if ev.get("event") in _TERMINAL_EVENTS:
            payload = ev.get("payload")
            slug = cast("dict[str, object]", payload).get("slug", "") if isinstance(payload, dict) else ""
            by_slug[str(slug)] = ev
    return by_slug


def _select_terminal(events: list[dict[str, object]]) -> dict[str, object] | None:
    by_slug = _terminal_by_chunk(events)
    ejected = [ev for ev in by_slug.values() if ev.get("event") == "chunk_ejected"]
    if ejected:
        return max(ejected, key=lambda e: str(e.get("ts", "")))
    landed = [ev for ev in by_slug.values() if ev.get("event") == "chunk_landed"]
    return max(landed, key=lambda e: str(e.get("ts", ""))) if landed else None


def build_verdict(agent_dir: Path) -> str:
    events = _events_for_dir(agent_dir)
    if not events:
        return (
            "## Verdict\n- Reason: unknown\n- Phase: unknown\n\n"
            "## Expected vs actual\n- Expected: unknown\n- Actual: unknown\n\n"
            "## Regression\n- Last known good commit: unknown\n- Is regression: unknown\n"
        )

    terminal: dict[str, object] | None = _select_terminal(events)
    last_ev = events[-1]
    first_failed: dict[str, object] | None = next(
        (e for e in events if e.get("event") == "chunk_ejected"),
        None,
    )

    if terminal and terminal.get("event") == "chunk_landed":
        reason = "chunk_landed"
        suspect = "None — chunk landed successfully."
    elif terminal and terminal.get("event") == "chunk_ejected":
        payload = cast("dict[str, object]", terminal.get("payload") or {})
        slug = payload.get("slug", "unknown")
        reason = payload.get("reason", "unknown")
        suspect_template = _SUSPECT_MAP[str(reason)]
        where = payload.get("where", "")
        suspect = f"Chunk `{slug}` — {suspect_template.replace('<where>', str(where))}"
        blocker = payload.get("summary")
        if reason == HITL_REQUIRED and blocker:
            suspect = f"{suspect} Blocker: {blocker}"
    else:
        reason = "unknown"
        suspect = "No terminal event found."

    phase = terminal.get("event", "unknown") if terminal else last_ev.get("event", "unknown")
    first_failed_line = f"{first_failed['event']} @ {first_failed['ts']}" if first_failed else "none"

    spawned = next((e for e in events if e.get("event") == "chunk_started"), None)
    expected = "unknown"
    if spawned and isinstance(spawned.get("payload"), dict):
        expected = cast("dict[str, object]", spawned["payload"]).get("plan", "unknown")
    actual = f"{reason}" + (f" — {suspect}" if reason != "chunk_landed" else "")

    prior_landed = next((e for e in events if e.get("event") == "chunk_landed"), None)
    if prior_landed and isinstance(prior_landed.get("payload"), dict):
        last_good = cast("dict[str, object]", prior_landed["payload"]).get("sha", "unknown")
        is_regression = "yes" if terminal and terminal.get("event") == "chunk_ejected" else "no"
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


def build_summary(agent_dir: Path) -> str:
    events = _events_for_dir(agent_dir)
    spawned = next((e for e in events if e.get("event") == "chunk_started"), None)
    plan = "unknown"
    if spawned and isinstance(spawned.get("payload"), dict):
        p = cast("dict[str, object]", spawned["payload"])
        plan = str(p.get("plan", p.get("slug", "unknown")))

    terminal: dict[str, object] | None = None
    for ev in reversed(events):
        if ev.get("event") in ("chunk_landed", "chunk_ejected"):
            terminal = ev
            break

    if terminal and terminal.get("event") == "chunk_landed" and isinstance(terminal.get("payload"), dict):
        p = cast("dict[str, object]", terminal["payload"])
        outcome = (
            f"Landed `{p.get('slug', 'unknown')}` at `{p.get('sha', 'unknown')}` onto `{p.get('holding', 'unknown')}`."
        )
    elif terminal and terminal.get("event") == "chunk_ejected" and isinstance(terminal.get("payload"), dict):
        p = cast("dict[str, object]", terminal["payload"])
        reason = p.get("reason", "unknown")
        outcome = f"Ejected `{p.get('slug', 'unknown')}` — {reason}."
        blocker = p.get("summary")
        if reason == HITL_REQUIRED and blocker:
            outcome += f" Blocker: {blocker}"
        else:
            outcome += " See diagnose output."
    else:
        outcome = "Completed in agent; not yet landed (landing is orchestrate's job)."

    return f"## Summary\n- Plan: {plan}\n- Outcome: {outcome}\n- Events recorded: {len(events)}\n"


def write_summary(agent_dir: Path) -> Path:
    content = build_summary(agent_dir)
    summary = agent_dir / SUMMARY_FILE
    summary.write_text(content)
    return summary


def _run_diagnose_loop(context: str) -> None:
    print("=== diagnose context ===")
    print(context)
    print("=== enter diagnose loop (reproduce → minimize → hypothesize → red test) ===")


def run_diagnose(agent_dir: Path) -> None:
    context = build_verdict(agent_dir)
    _run_diagnose_loop(context)
