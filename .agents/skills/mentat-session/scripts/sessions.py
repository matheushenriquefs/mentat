"""Session directory helpers."""

from __future__ import annotations

import contextlib
import json
import sys
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

# Sessions idle/crashed for longer than this are hidden in the default active view.
_RECENCY_SECS = 86400  # 24 hours

# Attention-to-top: lower rank shown first.
STATUS_RANK = {"waiting": 0, "idle": 1, "?": 2, "working": 3}


def _humanize_age(age_secs: float) -> str:
    """Coarse 'N{s,m,h,d} ago' bucket for a session's idle age.

    Lives here so the registry list (`cmd_list`) and the navigator list pane
    (`render_list`) share one impl — no duplicate.
    """
    secs = int(age_secs)
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def latest_session(repo_dir: Path) -> str | None:
    """Return the most recently modified agent dir (legacy name)."""
    return get_latest_agent(repo_dir)


def get_latest_agent(repo_dir: Path) -> str | None:
    from lib import store

    return store.get_latest_agent(repo_dir.name)


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
    return list_events(session_dir)


def list_events(session_dir: Path) -> list[dict[str, object]]:
    from lib import store

    return store.list_events(session_dir.name)


# ── repo-wide registry ────────────────────────────────────────────────────────
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


def _is_waiting_stream(row: dict[str, object]) -> bool:
    """A harness stream row showing the agent blocked on the operator (AskUserQuestion)."""
    return harness_stream.is_ask_user_question(row)


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


def _status_from_signals(
    audit: dict[str, object] | None,
    newest_tail: dict[str, object] | None,
    age_secs: float | None,
    *,
    stale_secs: float = STALE_SECS,
) -> str:
    """Classify from already-read signals: audit tail row + newest-file tail row.

    Terminal/eject audit event wins regardless of file mtime. Otherwise an
    AskUserQuestion in newest_tail means waiting. Freshness decides working vs ?
    as fallback.
    """
    if audit is not None and (audit.get("event") in TERMINAL_EVENTS or audit.get("event") == "chunk.ejected"):
        return derive_status(audit, age_secs, stale_secs=stale_secs)
    if newest_tail is not None and _is_waiting_stream(newest_tail):
        return "waiting"
    return derive_status(audit if audit is not None else newest_tail, age_secs, stale_secs=stale_secs)


class SessionStatus:
    """Fused single-pass scan for one session directory.

    Replaces separate newest_jsonl + _audit_tail + _tail_row calls with one
    pass per jsonl. Memoized — safe to construct once and query many times.
    Falls back to directory mtime when no jsonl files exist.
    """

    def __init__(self, session_dir: Path, now: float, *, stale_secs: float = STALE_SECS) -> None:
        self._dir = session_dir
        self._now = now
        self._stale_secs = stale_secs
        self._scanned = False
        self._mtime: float | None = None
        self._audit: dict[str, object] | None = None
        self._newest_tail: dict[str, object] | None = None

    def _scan(self) -> None:
        if self._scanned:
            return
        self._scanned = True
        best_mtime = -1.0
        best_audit_ts = ""
        for f in self._dir.glob("*.jsonl"):
            m = _safe_mtime(f)
            if m is None:
                continue
            last_row: dict[str, object] | None = None
            for row in iter_rows(f):
                last_row = row
                ts = str(row.get("ts", ""))
                if "event" in row and ts >= best_audit_ts:
                    self._audit, best_audit_ts = row, ts
            if m > best_mtime:
                best_mtime = m
                self._newest_tail = last_row
        # Fall back to directory mtime when no jsonl files are present.
        self._mtime = best_mtime if best_mtime >= 0.0 else _safe_mtime(self._dir)

    @property
    def mtime(self) -> float | None:
        self._scan()
        return self._mtime

    @property
    def audit_tail(self) -> dict[str, object] | None:
        self._scan()
        return self._audit

    @property
    def newest_tail(self) -> dict[str, object] | None:
        self._scan()
        return self._newest_tail

    def derive(self) -> str:
        """Classification string: working / waiting / idle / ? — one entry point."""
        self._scan()
        age = max(0.0, self._now - self._mtime) if self._mtime is not None else None
        return _status_from_signals(self._audit, self._newest_tail, age, stale_secs=self._stale_secs)


def session_status(session_dir: Path, age_secs: float | None, *, stale_secs: float = STALE_SECS) -> str:
    """Pull one session's status, reconciling the audit signal with the live stream."""
    ss = SessionStatus(session_dir, 0.0, stale_secs=stale_secs)
    return _status_from_signals(ss.audit_tail, ss.newest_tail, age_secs, stale_secs=stale_secs)


def _event_name(audit: dict[str, object] | None) -> str | None:
    event = audit.get("event") if audit is not None else None
    return event if isinstance(event, str) else None


def list_sessions(
    repo_dir: Path,
    *,
    now: float | None = None,
    stale_secs: float = STALE_SECS,
    active_only: bool = True,
) -> list[SessionRecord]:
    return list_agents(repo_dir, now=now, stale_secs=stale_secs, active_only=active_only)


def list_agents(
    repo_dir: Path,
    *,
    now: float | None = None,
    stale_secs: float = STALE_SECS,
    active_only: bool = True,
) -> list[SessionRecord]:
    from lib import store

    rows = store.list_track_entries(repo_dir.name, active_only=active_only, now=now)
    return [cast("SessionRecord", r) for r in rows]


def session_stream_tools(session_dir: Path, *, limit: int = 20) -> list[str]:
    """The last `limit` harness tool-call names from a session's stream (preview pane).

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

    The kill bind needs the worktree to tear down; the session log dir is not the
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
    ss = SessionStatus(sub, clock, stale_secs=stale_secs)
    mtime = ss.mtime
    if mtime is None:
        return None
    age = max(0.0, clock - mtime)
    return {
        "session": sub.name,
        "status": ss.derive(),
        "mtime": mtime,
        "age": age,
        "last_event": _event_name(ss.audit_tail),
    }
