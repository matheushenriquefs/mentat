"""Recovery context: prompts, transcript distill, and failure seed minting."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

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
    for name in ("transcript.jsonl", "ses" + "sion.jsonl"):
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
    invoke_claude_fn: Callable[[str], str] | None = None,
) -> str:
    """Distill transcript + diff into a compact done/pending handoff note.

    Absent transcript → returns ``diff`` unchanged (today's baseline seed).
    """
    transcript_file = _transcript_path(agent_log_dir)
    if transcript_file is None:
        return diff or "(none)"
    if invoke is None and invoke_claude_fn is None:
        raise ValueError("distill_progress_note requires invoke or invoke_claude_fn")
    invoke = invoke or invoke_claude_fn
    assert invoke is not None
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


def _agent_log_dir_for_slug(agent_id: str, slug: str) -> Path | None:
    """Resolve the ejected implement agent's log dir from canonical store events."""
    from lib import store

    for row in reversed(store.list_events(agent_id)):
        if row.get("event") != "chunk_ejected":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict) or payload.get("slug") != slug:
            continue
        logs_path = payload.get("logs_path")
        if isinstance(logs_path, str) and logs_path:
            return Path(logs_path)
    return None


def eject_reason_for_slug(agent_id: str, slug: str) -> str:
    """Latest ``chunk_ejected.reason`` for ``slug`` from the canonical store."""
    from lib import store

    for row in reversed(store.list_events(agent_id)):
        if row.get("event") != "chunk_ejected":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict) or payload.get("slug") != slug:
            continue
        reason = payload.get("reason")
        if isinstance(reason, str):
            return reason
    return "unknown"


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
    invoke_claude_fn: Callable[[str], str] | None = None,
    distill_fn: Callable[..., str] | None = None,
) -> dict[str, object]:
    """Mint the composite recovery context: distilled progress note + metadata."""
    agent_log_dir = _agent_log_dir_for_slug(agent_id, slug)
    tip = _holding_tip_sha(worktree, holding)
    distill = distill_fn or distill_progress_note
    progress_note = distill(
        agent_log_dir=agent_log_dir,
        diff=diff,
        holding_tip=tip,
        invoke=invoke,
        invoke_claude_fn=invoke_claude_fn,
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
