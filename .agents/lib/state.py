"""sqlite3 WAL projection of the ADR-0007 audit log — a disposable read model.

The NDJSON audit log stays the source of truth (ADR-0007); this module keeps a
throwaway ``sessions`` table in ``~/.mentat/state.db`` so readers (track, doctor)
answer with one indexed query instead of scanning + reducing the whole log dir.
WAL mode lets the N worker-writers take short turns while readers never block
(https://sqlite.org/wal.html). The db is derived, never authoritative: it can be
deleted and rebuilt from the log at any time.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

# Coarse session status implied by the event that last touched the session. The
# log is the truth; this is a liveness projection for readers, not a state
# machine — a terminal event names the outcome, everything else is "running".
_TERMINAL_STATUS: dict[str, str] = {
    "chunk.landed": "landed",
    "chunk.ejected": "ejected",
    "plan.succeeded": "succeeded",
    "plan.failed": "failed",
}


def status_for(event: str) -> str:
    """Session status implied by ``event`` — terminal events name the outcome,
    every other event leaves the session ``running``."""
    return _TERMINAL_STATUS.get(event, "running")


def db_path() -> Path:
    """``state.db`` location. Honors ``MENTAT_STATE_DB`` (tests, alt roots),
    else ``~/.mentat/state.db`` — the ``lib.paths.MENTAT_DIR`` anchor, spelled
    directly so this stdlib-only read model carries no lib import."""
    override = os.environ.get("MENTAT_STATE_DB")
    if override:
        return Path(override)
    return Path.home() / ".mentat" / "state.db"


def _connect(path: Path) -> sqlite3.Connection:
    """Open ``path`` in WAL mode, creating the parent dir and ``sessions`` table
    on first use. WAL persists in the db file; ``busy_timeout`` lets a writer
    wait its turn instead of failing under concurrent worker writes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            uuid          TEXT PRIMARY KEY,
            repo          TEXT,
            branch        TEXT,
            pid           INTEGER,
            status        TEXT NOT NULL,
            started_at    REAL NOT NULL,
            last_event_at REAL NOT NULL
        )
        """
    )
    return conn


def list_sessions(repo: str, *, now: float | None = None, active_only: bool = True) -> list[dict[str, object]]:
    """One repo's session rows from the projection — a single indexed query, no dir scan.

    Each record: ``{session, status, mtime, age, last_event}`` where ``session`` is the
    session uuid and ``mtime``/``age`` derive from ``last_event_at``. ``last_event``
    mirrors ``status`` — the projection records the outcome the last event implied, not
    the raw event name (the reader no longer reduces the log for it).

    ``active_only`` (default) keeps only non-terminal (``running``) sessions — a live or
    silently-crashed chunk — with no recency window, so an idle-but-incomplete session
    never false-empties out; ``active_only=False`` returns the full history. Running
    sessions sort ahead of terminal ones, then newest activity first.

    Best-effort read: an unopenable/absent db yields ``[]`` (the NDJSON log is the truth).
    """
    clock = time.time() if now is None else now
    sql = "SELECT uuid, status, last_event_at FROM sessions WHERE repo = ?"
    params: tuple[object, ...] = (repo,)
    if active_only:
        sql += " AND status = 'running'"
    sql += " ORDER BY (status = 'running') DESC, last_event_at DESC"
    try:
        conn = _connect(db_path())
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    return [
        {
            "session": uuid,
            "status": status,
            "mtime": last_event_at,
            "age": max(0.0, clock - last_event_at),
            "last_event": status,
        }
        for uuid, status, last_event_at in rows
    ]


def project(env: dict[str, str], event: str, *, now: float | None = None) -> None:
    """Upsert the ``sessions`` row implied by ``env`` + ``event``.

    First emit for a uuid inserts the row (``started_at`` frozen); later emits
    advance ``status`` + ``last_event_at`` and only fill ``repo``/``branch``/
    ``pid`` if still null, so a partial early env never clobbers a fuller one.

    Best-effort: the NDJSON log is the source of truth, so any sqlite failure is
    swallowed — a projection error must never break an emit. No-op when the env
    carries no session id.
    """
    uuid = env.get("MENTAT_SESSION")
    if not uuid:
        return
    ts = time.time() if now is None else now
    repo = env.get("MENTAT_REPO")
    branch = env.get("MENTAT_SESSION_BRANCH")
    pid_raw = env.get("MENTAT_SESSION_PID")
    pid = int(pid_raw) if pid_raw and pid_raw.isdigit() else None
    try:
        conn = _connect(db_path())
        try:
            conn.execute(
                """
                INSERT INTO sessions
                    (uuid, repo, branch, pid, status, started_at, last_event_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uuid) DO UPDATE SET
                    status        = excluded.status,
                    last_event_at = excluded.last_event_at,
                    repo          = COALESCE(sessions.repo, excluded.repo),
                    branch        = COALESCE(sessions.branch, excluded.branch),
                    pid           = COALESCE(sessions.pid, excluded.pid)
                """,
                (uuid, repo, branch, pid, status_for(event), ts, ts),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        return
