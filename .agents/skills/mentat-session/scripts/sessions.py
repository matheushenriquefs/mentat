"""Session directory helpers."""

from __future__ import annotations

import contextlib
import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TypedDict, cast


class SessionRecord(TypedDict):
    session: str
    status: str
    mtime: float
    age: float
    last_event: str | None


_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import harness_stream  # noqa: E402
from lib.events import EjectReason  # noqa: E402

# Terminal audit events — a session whose newest tail is one of these is done, not crashed.
TERMINAL_EVENTS = frozenset({"chunk.landed", "plan.succeeded", "plan.failed", "chunk.teardown", "batch.reviewed"})
# chunk.ejected is terminal too, but a hitl-required eject needs an operator → waiting.
_WAITING_EJECT_REASONS = frozenset({EjectReason.HITL_REQUIRED})

# No activity for this long with a non-terminal tail = the session crashed silently.
STALE_SECS = 300

# Attention-to-top: lower rank shown first.
STATUS_RANK = {"waiting": 0, "idle": 1, "?": 2, "working": 3}


def latest_session(repo_dir: Path) -> str | None:
    """Return the most recently modified session dir, excluding ad-hoc `mentat-manual-*` runs."""
    dirs = [d for d in repo_dir.iterdir() if d.is_dir() and not d.name.startswith("mentat-manual-")]
    dated = [(m, d.name) for d in dirs if (m := _safe_mtime(d)) is not None]
    if not dated:
        return None
    return max(dated)[1]


def sessions_for_repo(repo_dir: Path) -> list[str]:
    return [d.name for d in repo_dir.iterdir() if d.is_dir() and not d.name.startswith("mentat-manual-")]


def chunks_in_session(session_dir: Path) -> list[Path]:
    return list(session_dir.glob("*.jsonl"))


def slug_for_chunk(file: Path) -> str:
    return file.stem


def iter_rows_from_text(text: str) -> Iterator[dict[str, object]]:
    """Yield parsed JSON object rows from jsonl text, skipping blanks/garbage."""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        with contextlib.suppress(json.JSONDecodeError):
            row = json.loads(line)
            if isinstance(row, dict):
                yield row


def iter_rows(log_file: Path) -> Iterator[dict[str, object]]:
    """Yield parsed JSON object rows of a jsonl file, skipping blanks/garbage. Read-safe."""
    with contextlib.suppress(OSError, UnicodeDecodeError):
        yield from iter_rows_from_text(log_file.read_text())


def all_events(session_dir: Path) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for log_file in sorted(session_dir.glob("*.jsonl")):
        events.extend(iter_rows(log_file))
    return sorted(events, key=lambda e: str(e.get("ts", "")))


# ── repo-wide registry (S6) ───────────────────────────────────────────────────
# The filesystem is the registry: each subdir of ~/.mentat/logs/<repo> is one
# session. We have no push hooks, so status is *pulled* from the tail row of the
# session's newest jsonl, classified against its st_mtime freshness.


def _safe_mtime(path: Path) -> float | None:
    """st_mtime, or None if the path vanished (reaper teardown races a live scan)."""
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def newest_jsonl(session_dir: Path) -> Path | None:
    """The session's most-recently-written jsonl (audit *.jsonl or harness session.jsonl).

    Race-safe: a jsonl deleted between glob and stat is skipped, not raised.
    """
    best: Path | None = None
    best_mtime = -1.0
    for f in session_dir.glob("*.jsonl"):
        m = _safe_mtime(f)
        if m is not None and m > best_mtime:
            best, best_mtime = f, m
    return best


def _tail_row(log_file: Path) -> dict[str, object] | None:
    """Last non-blank JSON row of a jsonl file (None if unreadable/empty)."""
    last: dict[str, object] | None = None
    for row in iter_rows(log_file):
        last = row
    return last


def _is_waiting_stream(row: dict[str, object]) -> bool:
    """A harness stream row showing the agent blocked on the operator (AskUserQuestion)."""
    return harness_stream.is_ask_user_question(row)


def _audit_tail(session_dir: Path) -> dict[str, object] | None:
    """The latest audit event (row carrying an `event` key) across the session's jsonls, by ts.

    The terminal signal (chunk.landed / plan.succeeded / chunk.ejected …) lives in the audit
    log, which may have an *older* mtime than a still-open harness session.jsonl. Reading the
    single newest file's tail would then misread a finished session as working/crashed, so
    completion is judged from the audit stream, not from whichever file was touched last.
    """
    best: dict[str, object] | None = None
    best_ts = ""
    for log_file in session_dir.glob("*.jsonl"):
        for row in iter_rows(log_file):
            ts = str(row.get("ts", ""))
            if "event" in row and ts >= best_ts:
                best, best_ts = row, ts
    return best


def derive_status(row: dict[str, object] | None, age_secs: float | None, *, stale_secs: float = STALE_SECS) -> str:
    """Map a single representative row + freshness to working / waiting / idle / ? (crashed).

    `row` is an audit row (`event` key) or a harness stream row (`type` key). `age_secs` is
    seconds since the session was last active. Pure — `session_status` picks the right row.
    """
    is_stale = age_secs is None or age_secs > stale_secs
    if row is not None:
        event = row.get("event")
        if event == "chunk.ejected":
            payload = row.get("payload")
            reason = cast("dict[str, object]", payload).get("reason") if isinstance(payload, dict) else None
            return "waiting" if reason in _WAITING_EJECT_REASONS else "idle"
        if event in TERMINAL_EVENTS:
            return "idle"
        if _is_waiting_stream(row):
            return "waiting"
    # non-terminal (or unreadable) tail: fresh = still working, stale = crashed
    return "?" if is_stale else "working"


def _status_from(
    audit: dict[str, object] | None,
    newest: Path | None,
    age_secs: float | None,
    *,
    stale_secs: float = STALE_SECS,
) -> str:
    """Classify from already-read signals: authoritative audit tail + the newest jsonl.

    A terminal/eject audit event wins regardless of file mtime (fixes the completed-session
    misclassification). Otherwise a live `AskUserQuestion` in the newest tail means waiting;
    failing both, freshness decides working vs ? (crashed).
    """
    if audit is not None and (audit.get("event") in TERMINAL_EVENTS or audit.get("event") == "chunk.ejected"):
        return derive_status(audit, age_secs, stale_secs=stale_secs)
    tail = _tail_row(newest) if newest is not None else None
    if tail is not None and _is_waiting_stream(tail):
        return "waiting"
    return derive_status(audit if audit is not None else tail, age_secs, stale_secs=stale_secs)


def session_status(session_dir: Path, age_secs: float | None, *, stale_secs: float = STALE_SECS) -> str:
    """Pull one session's status, reconciling the audit signal with the live stream."""
    return _status_from(_audit_tail(session_dir), newest_jsonl(session_dir), age_secs, stale_secs=stale_secs)


def _event_name(audit: dict[str, object] | None) -> str | None:
    event = audit.get("event") if audit is not None else None
    return event if isinstance(event, str) else None


def list_sessions(repo_dir: Path, *, now: float | None = None, stale_secs: float = STALE_SECS) -> list[SessionRecord]:
    """Scan one repo's log dir into attention-ordered status records.

    Each record: {session, status, mtime, age, last_event}. Sorted by (rank, age)
    so attention-needing sessions (waiting > idle > ? > working) float to the top.
    Race-safe: a session dir/file removed mid-scan is skipped, never raised. Each
    session's logs are read once (audit tail + newest tail), not per-field.
    """
    if not repo_dir.is_dir():
        return []
    clock = time.time() if now is None else now
    subs: list[Path] = []
    with contextlib.suppress(OSError):
        subs = [s for s in repo_dir.iterdir() if s.is_dir()]
    records: list[SessionRecord] = [r for sub in subs if (r := _build_record(sub, clock, stale_secs)) is not None]
    records.sort(key=lambda r: (STATUS_RANK.get(r["status"], 99), r["age"]))
    return records


def session_stream_tools(session_dir: Path, *, limit: int = 20) -> list[str]:
    """The last `limit` harness tool-call names from a session's stream (S7 preview pane).

    Reads the captured stream-json (session.jsonl). Audit rows yield nothing — only
    assistant tool_use blocks count — so globbing every jsonl is safe. Order is the
    file's append order (chronological for the stream). Race-safe via `iter_rows`.
    """
    names: list[str] = []
    for f in sorted(session_dir.glob("*.jsonl")):
        for row in iter_rows(f):
            names.extend(harness_stream.tool_uses(row))
    return names[-limit:]


def session_worktree(session_dir: Path) -> str | None:
    """The worktree path this session was spawned into (from its `chunk.spawned` audit), or None.

    The S7 kill bind needs the worktree to tear down; the session log dir is not the
    worktree. Returns the `worktree` field of the latest spawn event by ts.
    """
    worktree: str | None = None
    for ev in all_events(session_dir):
        if ev.get("event") == "chunk.spawned":
            payload = ev.get("payload")
            if isinstance(payload, dict):
                wt = cast("dict[str, object]", payload).get("worktree")
                if isinstance(wt, str):
                    worktree = wt
    return worktree


def _build_record(sub: Path, clock: float, stale_secs: float) -> SessionRecord | None:
    """One session's status record, or None if it vanished mid-scan."""
    newest = newest_jsonl(sub)
    mtime = _safe_mtime(newest) if newest is not None else _safe_mtime(sub)
    if mtime is None:
        return None
    audit = _audit_tail(sub)
    age = max(0.0, clock - mtime)
    return {
        "session": sub.name,
        "status": _status_from(audit, newest, age, stale_secs=stale_secs),
        "mtime": mtime,
        "age": age,
        "last_event": _event_name(audit),
    }
