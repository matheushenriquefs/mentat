"""sqlite3 WAL projection of the ADR-0007 audit log — a disposable read model.

The NDJSON audit log stays the source of truth (ADR-0007); this module keeps a
throwaway ``sessions`` table in ``~/.mentat/state.db`` so readers (track, doctor)
answer with one indexed query instead of scanning + reducing the whole log dir.
WAL mode lets the N worker-writers take short turns while readers never block
(https://sqlite.org/wal.html). The db is derived, never authoritative: it can be
deleted and rebuilt from the log at any time.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import cast

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


def _reduce_session(session_dir: Path) -> tuple[str, str, float, float] | None:
    """Reduce one session dir's NDJSON events → ``(uuid, status, started_at,
    last_event_at)``, or ``None`` if the dir holds no parseable event.

    ``started_at`` is the earliest event ts, ``last_event_at`` the latest, and
    ``status`` the outcome the *latest* event implies — the same liveness rule
    ``project`` applies incrementally, applied here in one pass over the log."""
    uuid: str | None = None
    first_ts: float | None = None
    last_ts: float | None = None
    last_event: str | None = None
    for log_file in sorted(session_dir.glob("*.jsonl")):
        for line in log_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, dict) or "ts" not in parsed or "event" not in parsed:
                continue
            row = cast("dict[str, object]", parsed)
            try:
                ts = datetime.datetime.fromisoformat(str(row["ts"])).timestamp()
            except ValueError, TypeError:
                continue
            session = row.get("session")
            if session is not None:
                uuid = str(session)
            if first_ts is None or ts < first_ts:
                first_ts = ts
            if last_ts is None or ts >= last_ts:
                last_ts = ts
                last_event = str(row["event"])
    if uuid is None or first_ts is None or last_ts is None or last_event is None:
        return None
    return uuid, status_for(last_event), first_ts, last_ts


def rebuild(log_root: Path, *, prune_before: datetime.date | None = None) -> dict[str, int]:
    """Regenerate ``state.db`` from the durable NDJSON log — the log is the source
    of truth, the db a disposable read model (Kleppmann). Returns
    ``{"projected": M, "pruned": N}``.

    The db is dropped and rebuilt from scratch (not upserted into), so a session
    whose dir no longer exists leaves no stale row. Each surviving session dir is
    reduced to one row; ``repo`` comes from the dir's parent, timestamps and status
    from its event stream. ``branch``/``pid`` are live-only enrichment absent from
    the durable log, so they rebuild ``NULL`` — no reader selects them.

    When ``prune_before`` is given, a session dir whose mtime predates that date is
    removed from disk and never projected (the one-shot orphan-dir sweep); a fresh
    dir is kept and projected.
    """
    db = db_path()
    for suffix in ("", "-wal", "-shm"):
        with contextlib.suppress(OSError):
            Path(str(db) + suffix).unlink(missing_ok=True)

    conn = _connect(db)
    projected = 0
    pruned = 0
    try:
        if log_root.exists():
            for repo_dir in sorted(log_root.iterdir()):
                if not repo_dir.is_dir():
                    continue
                for session_dir in sorted(repo_dir.iterdir()):
                    if not session_dir.is_dir():
                        continue
                    if prune_before is not None:
                        mtime = datetime.date.fromtimestamp(session_dir.stat().st_mtime)
                        if mtime < prune_before:
                            shutil.rmtree(session_dir)
                            pruned += 1
                            continue
                    reduced = _reduce_session(session_dir)
                    if reduced is None:
                        continue
                    uuid, status, started_at, last_event_at = reduced
                    conn.execute(
                        """
                        INSERT INTO sessions
                            (uuid, repo, branch, pid, status, started_at, last_event_at)
                        VALUES (?, ?, NULL, NULL, ?, ?, ?)
                        ON CONFLICT(uuid) DO UPDATE SET
                            status        = excluded.status,
                            started_at    = excluded.started_at,
                            last_event_at = excluded.last_event_at
                        """,
                        (uuid, repo_dir.name, status, started_at, last_event_at),
                    )
                    projected += 1
        conn.commit()
    finally:
        conn.close()
    return {"projected": projected, "pruned": pruned}


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
