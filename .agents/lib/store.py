"""SQLite canonical store for mentat runtime state (ADR-0017 V1).

WAL-durable source of truth for agents, chunks, slices, and events. The NDJSON
audit file stays dual-written in V1; readers flip to SQLite in V2.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import random
import shutil
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

_WRITE_RETRIES = 8
_WRITE_BACKOFF_BASE_S = 0.01
_BUSY_TIMEOUT_MS = 5000
_USER_VERSION = 1

AgentStatus = Literal["pending", "running", "stopped", "reaped"]
ChunkStatus = Literal["running", "landed", "ejected"]
StatusReason = Literal["ok", "nonzero", "signal", "dead_pid"]
SliceKind = Literal["AFK", "HITL"]

_CREATE_SLICE = """
CREATE TABLE IF NOT EXISTS slice (
  id         TEXT PRIMARY KEY,
  plan_slug  TEXT NOT NULL,
  key        TEXT NOT NULL,
  kind       TEXT NOT NULL,
  UNIQUE(plan_slug, key)
);
"""

_CREATE_AGENT = """
CREATE TABLE IF NOT EXISTS agent (
  id              TEXT PRIMARY KEY,
  supervisor_id   TEXT REFERENCES agent(id),
  resumed_from_id TEXT REFERENCES agent(id),
  forked_from_id  TEXT REFERENCES agent(id),
  harness         TEXT NOT NULL,
  pid             INTEGER,
  status          TEXT NOT NULL,
  status_reason   TEXT,
  started_at      TEXT NOT NULL,
  ended_at        TEXT
);
"""

_CREATE_CHUNK = """
CREATE TABLE IF NOT EXISTS chunk (
  id            TEXT PRIMARY KEY,
  slice_id      TEXT NOT NULL REFERENCES slice(id),
  agent_id      TEXT NOT NULL REFERENCES agent(id),
  attempt       INTEGER NOT NULL DEFAULT 1,
  container_id  TEXT,
  worktree_path TEXT,
  status        TEXT NOT NULL,
  status_reason TEXT,
  started_at    TEXT NOT NULL,
  ended_at      TEXT
);
"""

_CREATE_EVENT = """
CREATE TABLE IF NOT EXISTS event (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts       TEXT NOT NULL,
  kind     TEXT NOT NULL,
  payload  TEXT NOT NULL DEFAULT '{}',
  agent_id TEXT REFERENCES agent(id),
  chunk_id TEXT REFERENCES chunk(id)
);
CREATE INDEX IF NOT EXISTS event_by_agent ON event(agent_id, id);
CREATE INDEX IF NOT EXISTS event_by_chunk ON event(chunk_id, id);
"""

_MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (_CREATE_SLICE, _CREATE_AGENT, _CREATE_CHUNK, _CREATE_EVENT),
}


def db_path() -> Path:
    """``mentat.db`` location. Honors ``MENTAT_DB`` (tests, alt roots)."""
    override = os.environ.get("MENTAT_DB")
    if override:
        return Path(override)
    legacy = os.environ.get("MENTAT_STATE_DB")
    if legacy:
        return Path(legacy).with_name("mentat.db")
    return Path.home() / ".mentat" / "mentat.db"


def legacy_state_db_path() -> Path:
    override = os.environ.get("MENTAT_STATE_DB")
    if override:
        return Path(override)
    return Path.home() / ".mentat" / "state.db"


def make_slice_id(plan_slug: str, key: str) -> str:
    digest = hashlib.sha256(f"{plan_slug}_{key}".encode()).hexdigest()
    return digest[:32]


def wire_kind(event: str) -> str:
    """Map ADR-0007 dotted event names to underscore catalog keys."""
    return event.replace(".", "_")


def iso_now(*, now: float | None = None) -> str:
    ts = time.time() if now is None else now
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the canonical db with WAL + foreign keys. Applies migrations."""
    target = path if path is not None else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=_BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    _apply_migrations(conn)
    return conn


def _apply_migrations(conn: sqlite3.Connection) -> None:
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    for version in sorted(v for v in _MIGRATIONS if v > current):
        for stmt in _MIGRATIONS[version]:
            conn.executescript(stmt)
        conn.execute(f"PRAGMA user_version={version}")
    conn.commit()


def _is_busy(exc: sqlite3.OperationalError) -> bool:
    msg = str(exc).lower()
    return "locked" in msg or "busy" in msg


def _write_with_retry(conn: sqlite3.Connection, fn: object) -> None:
    """Run ``fn(conn)`` inside BEGIN IMMEDIATE with bounded SQLITE_BUSY retry."""
    if not callable(fn):
        raise TypeError("fn must be callable")
    last: sqlite3.OperationalError | None = None
    for attempt in range(_WRITE_RETRIES):
        try:
            conn.execute("BEGIN IMMEDIATE")
            fn(conn)
            conn.commit()
            return
        except sqlite3.OperationalError as exc:
            conn.rollback()
            if not _is_busy(exc):
                raise
            last = exc
            time.sleep(_WRITE_BACKOFF_BASE_S * (2**attempt) + random.random() * _WRITE_BACKOFF_BASE_S)
    if last is not None:
        raise last
    raise sqlite3.OperationalError("write failed after retries")


def probe_pid(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return False
    return True


@dataclass(frozen=True)
class Slice:
    id: str
    plan_slug: str
    key: str
    kind: SliceKind


@dataclass(frozen=True)
class Agent:
    id: str
    supervisor_id: str | None
    resumed_from_id: str | None
    forked_from_id: str | None
    harness: str
    pid: int | None
    status: AgentStatus
    status_reason: StatusReason | None
    started_at: str
    ended_at: str | None


@dataclass(frozen=True)
class Chunk:
    id: str
    slice_id: str
    agent_id: str
    attempt: int
    container_id: str | None
    worktree_path: str | None
    status: ChunkStatus
    status_reason: StatusReason | None
    started_at: str
    ended_at: str | None


@dataclass(frozen=True)
class Event:
    id: int
    ts: str
    kind: str
    payload: dict[str, object]
    agent_id: str | None
    chunk_id: str | None


def _row_agent(row: sqlite3.Row) -> Agent:
    return Agent(
        id=str(row["id"]),
        supervisor_id=row["supervisor_id"],
        resumed_from_id=row["resumed_from_id"],
        forked_from_id=row["forked_from_id"],
        harness=str(row["harness"]),
        pid=row["pid"],
        status=cast("AgentStatus", row["status"]),
        status_reason=cast("StatusReason | None", row["status_reason"]),
        started_at=str(row["started_at"]),
        ended_at=row["ended_at"],
    )


def _row_chunk(row: sqlite3.Row) -> Chunk:
    return Chunk(
        id=str(row["id"]),
        slice_id=str(row["slice_id"]),
        agent_id=str(row["agent_id"]),
        attempt=int(row["attempt"]),
        container_id=row["container_id"],
        worktree_path=row["worktree_path"],
        status=cast("ChunkStatus", row["status"]),
        status_reason=cast("StatusReason | None", row["status_reason"]),
        started_at=str(row["started_at"]),
        ended_at=row["ended_at"],
    )


def _row_event(row: sqlite3.Row) -> Event:
    return Event(
        id=int(row["id"]),
        ts=str(row["ts"]),
        kind=str(row["kind"]),
        payload=json.loads(str(row["payload"])),
        agent_id=row["agent_id"],
        chunk_id=row["chunk_id"],
    )


class SliceDAO:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, row: Slice) -> None:
        def _write(c: sqlite3.Connection) -> None:
            c.execute(
                """
                INSERT INTO slice (id, plan_slug, key, kind)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    plan_slug = excluded.plan_slug,
                    key = excluded.key,
                    kind = excluded.kind
                """,
                (row.id, row.plan_slug, row.key, row.kind),
            )

        _write_with_retry(self._conn, _write)

    def get_by_id(self, slice_id: str) -> Slice | None:
        row = self._conn.execute("SELECT * FROM slice WHERE id = ?", (slice_id,)).fetchone()
        if row is None:
            return None
        return Slice(
            id=str(row["id"]),
            plan_slug=str(row["plan_slug"]),
            key=str(row["key"]),
            kind=cast("SliceKind", row["kind"]),
        )


class AgentDAO:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(self, row: Agent) -> None:
        def _write(c: sqlite3.Connection) -> None:
            c.execute(
                """
                INSERT INTO agent (
                    id, supervisor_id, resumed_from_id, forked_from_id,
                    harness, pid, status, status_reason, started_at, ended_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.id,
                    row.supervisor_id,
                    row.resumed_from_id,
                    row.forked_from_id,
                    row.harness,
                    row.pid,
                    row.status,
                    row.status_reason,
                    row.started_at,
                    row.ended_at,
                ),
            )

        _write_with_retry(self._conn, _write)

    def update_status(
        self,
        agent_id: str,
        *,
        status: AgentStatus,
        status_reason: StatusReason | None = None,
        ended_at: str | None = None,
    ) -> None:
        def _write(c: sqlite3.Connection) -> None:
            c.execute(
                """
                UPDATE agent
                SET status = ?, status_reason = ?, ended_at = COALESCE(?, ended_at)
                WHERE id = ?
                """,
                (status, status_reason, ended_at, agent_id),
            )

        _write_with_retry(self._conn, _write)

    def get_by_id(self, agent_id: str) -> Agent | None:
        row = self._conn.execute("SELECT * FROM agent WHERE id = ?", (agent_id,)).fetchone()
        if row is None:
            return None
        return _row_agent(row)

    def list_running(self) -> list[Agent]:
        rows = self._conn.execute(
            "SELECT * FROM agent WHERE status IN ('pending', 'running') ORDER BY started_at DESC"
        ).fetchall()
        return [_row_agent(r) for r in rows]

    def list_visible(self) -> list[Agent]:
        rows = self._conn.execute("SELECT * FROM agent WHERE status != 'reaped' ORDER BY started_at DESC").fetchall()
        return [_row_agent(r) for r in rows]

    def mark_reaped(self, agent_id: str, *, ended_at: str | None = None) -> None:
        self.update_status(
            agent_id,
            status="reaped",
            status_reason="dead_pid",
            ended_at=ended_at or iso_now(),
        )


class ChunkDAO:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(self, row: Chunk) -> None:
        def _write(c: sqlite3.Connection) -> None:
            c.execute(
                """
                INSERT INTO chunk (
                    id, slice_id, agent_id, attempt, container_id, worktree_path,
                    status, status_reason, started_at, ended_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.id,
                    row.slice_id,
                    row.agent_id,
                    row.attempt,
                    row.container_id,
                    row.worktree_path,
                    row.status,
                    row.status_reason,
                    row.started_at,
                    row.ended_at,
                ),
            )

        _write_with_retry(self._conn, _write)

    def get_by_id(self, chunk_id: str) -> Chunk | None:
        row = self._conn.execute("SELECT * FROM chunk WHERE id = ?", (chunk_id,)).fetchone()
        if row is None:
            return None
        return _row_chunk(row)


class EventDAO:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append(
        self,
        *,
        kind: str,
        payload: dict[str, object],
        agent_id: str | None = None,
        chunk_id: str | None = None,
        ts: str | None = None,
        canonical: bool = True,
    ) -> int:
        stamp = ts or iso_now()
        wire = wire_kind(kind)

        def _write(c: sqlite3.Connection) -> int:
            cur = c.execute(
                """
                INSERT INTO event (ts, kind, payload, agent_id, chunk_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (stamp, wire, json.dumps(payload), agent_id, chunk_id),
            )
            return int(cur.lastrowid or 0)

        try:
            result: list[int] = []

            def _collect(c: sqlite3.Connection) -> None:
                result.append(_write(c))

            _write_with_retry(self._conn, _collect)
            return result[0]
        except sqlite3.Error:
            if canonical:
                raise
            return 0

    def list_by_agent(self, agent_id: str, *, limit: int = 0) -> list[Event]:
        sql = "SELECT * FROM event WHERE agent_id = ? ORDER BY id"
        if limit > 0:
            sql += f" LIMIT {int(limit)}"
        rows = self._conn.execute(sql, (agent_id,)).fetchall()
        return [_row_event(r) for r in rows]

    def get_by_id(self, event_id: int) -> Event | None:
        row = self._conn.execute("SELECT * FROM event WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            return None
        return _row_event(row)


def migrate_legacy_state_db(*, dest: Path | None = None) -> bool:
    """One-shot ``state.db`` → ``mentat.db`` when dest is absent. Idempotent."""
    target = dest if dest is not None else db_path()
    if target.exists():
        return False
    legacy = legacy_state_db_path()
    if not legacy.exists():
        return False
    shutil.copy2(legacy, target)
    conn = connect(target)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "sessions" not in tables:
            return True
        rows = conn.execute("SELECT uuid, pid, status, started_at, last_event_at FROM sessions").fetchall()
        agents = AgentDAO(conn)
        for uuid, pid, status, started_at, last_event_at in rows:
            mapped: AgentStatus
            if status == "running":
                mapped = "running"
            elif status in ("landed", "succeeded"):
                mapped = "stopped"
            else:
                mapped = "stopped"
            started_iso = datetime.fromtimestamp(float(started_at), tz=UTC).isoformat()
            ended_iso = (
                datetime.fromtimestamp(float(last_event_at), tz=UTC).isoformat() if mapped != "running" else None
            )
            with contextlib.suppress(sqlite3.IntegrityError):
                agents.insert(
                    Agent(
                        id=str(uuid),
                        supervisor_id=None,
                        resumed_from_id=None,
                        forked_from_id=None,
                        harness="unknown",
                        pid=pid,
                        status=mapped,
                        status_reason=None,
                        started_at=started_iso,
                        ended_at=ended_iso,
                    )
                )
        conn.execute("DROP TABLE IF EXISTS sessions")
        conn.commit()
    finally:
        conn.close()
    return True


_AGENT_TERMINAL_EVENTS: dict[str, AgentStatus] = {
    "plan.succeeded": "stopped",
    "plan.failed": "stopped",
    "chunk.landed": "stopped",
    "chunk.ejected": "stopped",
}


def record_emit(env: dict[str, str], event: str, payload: dict[str, object]) -> None:
    """Append one canonical event row and upsert the agent projection (V1 dual-write)."""
    agent_id = env.get("MENTAT_AGENT") or env.get("MENTAT_SESSION")
    if not agent_id:
        return
    migrate_legacy_state_db()
    conn = connect()
    try:
        agents = AgentDAO(conn)
        events = EventDAO(conn)
        row = agents.get_by_id(agent_id)
        pid_raw = env.get("MENTAT_AGENT_PID") or env.get("MENTAT_SESSION_PID")
        pid = int(pid_raw) if pid_raw and pid_raw.isdigit() else None
        harness = env.get("MENTAT_HARNESS", "unknown")
        if row is None:
            agents.insert(
                Agent(
                    id=agent_id,
                    supervisor_id=None,
                    resumed_from_id=None,
                    forked_from_id=None,
                    harness=harness,
                    pid=pid,
                    status="running",
                    status_reason=None,
                    started_at=iso_now(),
                    ended_at=None,
                )
            )
        terminal = _AGENT_TERMINAL_EVENTS.get(event)
        if terminal is not None:
            agents.update_status(agent_id, status=terminal, ended_at=iso_now())
        chunk_id = env.get("MENTAT_CHUNK_ID")
        events.append(
            kind=event,
            payload=payload,
            agent_id=agent_id,
            chunk_id=chunk_id or None,
        )
    finally:
        conn.close()
