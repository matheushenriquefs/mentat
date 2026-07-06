"""V1: lib/store.py — canonical SQLite store (ADR-0017)."""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import sqlite3
from pathlib import Path

import pytest
from lib import store


def _agent_row(
    agent_id: str = "a1",
    *,
    harness: str = "cursor",
    pid: int | None = 4242,
    status: store.AgentStatus = "running",
) -> store.Agent:
    return store.Agent(
        id=agent_id,
        supervisor_id=None,
        resumed_from_id=None,
        forked_from_id=None,
        harness=harness,
        pid=pid,
        status=status,
        status_reason=None,
        started_at=store.iso_now(now=1.0),
        ended_at=None,
    )


def test_db_path_honors_mentat_db(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_DB", str(tmp_path / "mentat.db"))
    assert store.db_path() == tmp_path / "mentat.db"


def test_db_path_default_under_mentat_dir(monkeypatch):
    monkeypatch.delenv("MENTAT_DB", raising=False)
    monkeypatch.delenv("MENTAT_STATE_DB", raising=False)
    assert store.db_path() == Path.home() / ".mentat" / "mentat.db"


def test_connect_applies_schema(tmp_path):
    db = tmp_path / "mentat.db"
    conn = store.connect(db)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert {"slice", "agent", "chunk", "event"} <= tables
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == store._USER_VERSION
    finally:
        conn.close()


def test_event_dao_append_and_list(tmp_path):
    db = tmp_path / "mentat.db"
    conn = store.connect(db)
    try:
        store.AgentDAO(conn).insert(_agent_row("agent-1"))
        events = store.EventDAO(conn)
        row_id = events.append(
            kind="chunk_started",
            payload={"slug": "x"},
            agent_id="agent-1",
        )
        listed = events.list_by_agent("agent-1")
        assert row_id == 1
        assert len(listed) == 1
        assert listed[0].kind == "chunk_started"
        assert listed[0].payload == {"slug": "x"}
    finally:
        conn.close()


def test_agent_dao_get_by_id(tmp_path):
    db = tmp_path / "mentat.db"
    conn = store.connect(db)
    try:
        agents = store.AgentDAO(conn)
        agents.insert(_agent_row("agent-42"))
        got = agents.get_by_id("agent-42")
        assert got is not None
        assert got.harness == "cursor"
        assert got.pid == 4242
    finally:
        conn.close()


def test_make_slice_id_is_deterministic():
    a = store.make_slice_id("mentat-track-storage", "V1")
    b = store.make_slice_id("mentat-track-storage", "V1")
    c = store.make_slice_id("mentat-track-storage", "V2")
    assert a == b
    assert a != c
    assert len(a) == 32


def test_canonical_append_raises_on_failure(tmp_path):
    db = tmp_path / "mentat.db"
    conn = store.connect(db)
    store.AgentDAO(conn).insert(_agent_row("a"))
    events = store.EventDAO(conn)

    def _boom(_conn: sqlite3.Connection, _fn: object) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(store, "_write_with_retry", _boom)
        with pytest.raises(sqlite3.OperationalError):
            events.append(kind="chunk_landed", payload={}, agent_id="a", canonical=True)


def _concurrent_writer(db_path: str, agent_id: str, count: int) -> None:
    os.environ["MENTAT_DB"] = db_path
    conn = store.connect()
    try:
        events = store.EventDAO(conn)
        for i in range(count):
            events.append(
                kind="gate_evaluated",
                payload={"i": i},
                agent_id=agent_id,
            )
    finally:
        conn.close()


def test_concurrent_appends_drop_no_rows(tmp_path):
    db = tmp_path / "mentat.db"
    conn = store.connect(db)
    store.AgentDAO(conn).insert(_agent_row("agent-busy"))
    conn.close()
    workers = 4
    per_worker = 25
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=_concurrent_writer, args=(str(db), "agent-busy", per_worker)) for _ in range(workers)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
        assert p.exitcode == 0
    conn = store.connect(db)
    try:
        n = conn.execute("SELECT COUNT(*) FROM event WHERE agent_id = ?", ("agent-busy",)).fetchone()[0]
        assert n == workers * per_worker
    finally:
        conn.close()


def test_migrate_legacy_state_db(tmp_path, monkeypatch):
    legacy = tmp_path / "state.db"
    dest = tmp_path / "mentat.db"
    monkeypatch.setenv("MENTAT_STATE_DB", str(legacy))
    monkeypatch.setenv("MENTAT_DB", str(dest))

    old = sqlite3.connect(str(legacy))
    old.execute("PRAGMA journal_mode=WAL")
    old.execute(
        """
        CREATE TABLE sessions (
            uuid TEXT PRIMARY KEY,
            repo TEXT,
            branch TEXT,
            pid INTEGER,
            status TEXT NOT NULL,
            started_at REAL NOT NULL,
            last_event_at REAL NOT NULL
        )
        """
    )
    old.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("sess-old", "mentat", None, 99, "running", 10.0, 20.0),
    )
    old.commit()
    old.close()

    assert store.migrate_legacy_state_db(dest=dest) is True
    assert dest.exists()
    conn = store.connect(dest)
    try:
        agent = store.AgentDAO(conn).get_by_id("sess-old")
        assert agent is not None
        assert agent.pid == 99
        assert agent.status == "running"
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "sessions" not in tables
    finally:
        conn.close()
    assert store.migrate_legacy_state_db(dest=dest) is False


def test_record_emit_creates_agent_and_event(tmp_path, monkeypatch):
    db = tmp_path / "mentat.db"
    monkeypatch.setenv("MENTAT_DB", str(db))
    env = {
        "MENTAT_AGENT": "agent-emit",
        "MENTAT_AGENT_PID": str(os.getpid()),
        "MENTAT_HARNESS": "cursor",
    }
    store.record_emit(env, "chunk_started", {"slug": "plan-a"})
    conn = store.connect(db)
    try:
        agent = store.AgentDAO(conn).get_by_id("agent-emit")
        assert agent is not None
        assert agent.status == "running"
        events = store.EventDAO(conn).list_by_agent("agent-emit")
        assert len(events) == 1
        assert events[0].kind == "chunk_started"
    finally:
        conn.close()


def test_probe_pid_live_and_dead():
    assert store.probe_pid(os.getpid()) is True
    assert store.probe_pid(2**30) is False


def test_reconcile_liveness_reaps_dead_pid(tmp_path, monkeypatch):
    db = tmp_path / "mentat.db"
    monkeypatch.setenv("MENTAT_DB", str(db))
    conn = store.connect(db)
    store.AgentDAO(conn).insert(
        store.Agent(
            id="dead-agent",
            supervisor_id=None,
            resumed_from_id=None,
            forked_from_id=None,
            harness="test",
            pid=2**30,
            status="running",
            status_reason=None,
            started_at=store.iso_now(),
            ended_at=None,
        )
    )
    conn.close()
    store.reconcile_liveness()
    conn = store.connect(db)
    try:
        agent = store.AgentDAO(conn).get_by_id("dead-agent")
        assert agent is not None
        assert agent.status == "reaped"
        assert agent.status_reason == "dead_pid"
    finally:
        conn.close()


def test_list_track_entries_scoped_to_repo_log_dir(tmp_path, monkeypatch):
    db = tmp_path / "mentat.db"
    logs = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_DB", str(db))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(logs))
    env = {"MENTAT_AGENT": "agent-a", "MENTAT_AGENT_PID": str(os.getpid()), "MENTAT_HARNESS": "cursor"}
    store.record_emit(env, "chunk_started", {"slug": "x"})
    (logs / "repo" / "agent-a").mkdir(parents=True)
    rows = store.list_track_entries("repo", active_only=True)
    assert len(rows) == 1
    assert rows[0]["agent"] == "agent-a"


def test_get_agent_returns_none_for_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAT_DB", str(tmp_path / "mentat.db"))
    assert store.get_agent("missing") is None


def test_cmd_track_by_id_outside_repo(tmp_path, monkeypatch, capsys):
    """track <id> resolves via store, not cwd repo name."""
    from tests.conftest import load_script

    session_py = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-track/scripts/track.py"
    mod = load_script(session_py, "session_track_outside")
    db = tmp_path / "mentat.db"
    logs = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_DB", str(db))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(logs))
    monkeypatch.chdir("/tmp")
    agent_id = "agent-outside-repo"
    store.record_emit(
        {"MENTAT_AGENT": agent_id, "MENTAT_AGENT_PID": str(os.getpid()), "MENTAT_HARNESS": "cursor"},
        "chunk_started",
        {"slug": "x"},
    )
    (logs / "mentat" / agent_id).mkdir(parents=True)
    (logs / "mentat" / agent_id / "transcript.jsonl").write_text(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}) + "\n"
    )
    monkeypatch.setenv("MENTAT_REPO", "mentat")
    assert mod.cmd_track(agent_id) == 0
    assert "hi" in capsys.readouterr().out
