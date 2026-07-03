"""E2E journey: the sqlite session projection (lib/state.py).

The projection is a disposable read model over the durable NDJSON log — pure,
stdlib-only, and fully drivable in-process. This journey exercises the write path
(``project`` insert + coalescing upsert), the reader (``list_sessions`` ordering,
active-only filter, repo scoping, error-swallow), and the log→db rebuild
(reduction, freshness, malformed-row tolerance, pruning).
"""

from __future__ import annotations

import datetime
import json
import sqlite3
from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

STATE_PY = Path(__file__).resolve().parents[2] / ".agents/lib/state.py"


def _state():
    return load_script(STATE_PY, "e2e_state")


def _rows(db: Path):
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(
            "SELECT uuid, repo, branch, pid, status, started_at, last_event_at FROM sessions"
        ).fetchall()
    finally:
        conn.close()


def _env(uuid: str, **over):
    base = {"MENTAT_SESSION": uuid, "MENTAT_REPO": "r", "MENTAT_SESSION_BRANCH": "b", "MENTAT_SESSION_PID": "42"}
    base.update(over)
    return base


def test_project_and_list_roundtrip(monkeypatch, tmp_path):
    m = _state()
    db = tmp_path / "state.db"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    assert m.status_for("chunk.landed") == "landed"
    assert m.status_for("gate.evaluated") == "running"

    m.project(_env("live"), "chunk.spawned", now=100.0)
    m.project(_env("live"), "gate.evaluated", now=150.0)  # upsert: freeze start, advance last, still running
    m.project(_env("idle"), "gate.evaluated", now=120.0)
    m.project(_env("done"), "chunk.landed", now=90.0)

    row = {r[0]: r for r in _rows(db)}["live"]
    assert row[4] == "running" and row[5] == 100.0 and row[6] == 150.0

    active = m.list_sessions("r", now=200.0)
    assert [r["session"] for r in active] == ["live", "idle"], "running sessions, newest activity first"
    full = {r["session"] for r in m.list_sessions("r", now=200.0, active_only=False)}
    assert full == {"live", "idle", "done"}
    assert m.list_sessions("other-repo", now=200.0) == []


def test_project_coalesces_and_handles_bad_pid(monkeypatch, tmp_path):
    m = _state()
    db = tmp_path / "state.db"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    m.project(_env("s"), "chunk.spawned", now=1.0)
    m.project({"MENTAT_SESSION": "s"}, "chunk.landed", now=2.0)  # sparse env keeps earlier fields
    _uuid, repo, branch, pid, status, _s, last = _rows(db)[0]
    assert (repo, branch, pid, status, last) == ("r", "b", 42, "landed", 2.0)

    m.project(_env("np", MENTAT_SESSION_PID="not-a-pid"), "chunk.spawned", now=1.0)
    assert {r[0]: r[3] for r in _rows(db)}["np"] is None


def test_project_and_list_swallow_sqlite_errors(monkeypatch, tmp_path):
    m = _state()
    as_dir = tmp_path / "state.db"
    as_dir.mkdir()  # unopenable as a db file
    monkeypatch.setenv("MENTAT_STATE_DB", str(as_dir))

    m.project(_env("s"), "chunk.spawned", now=1.0)  # no raise
    assert m.list_sessions("r", now=1.0) == []


def _iso(y, mo, d, h=12):
    return datetime.datetime(y, mo, d, h, tzinfo=datetime.UTC).isoformat()


def test_rebuild_reduces_log_and_tolerates_junk(monkeypatch, tmp_path):
    m = _state()
    db = tmp_path / "state.db"
    log_root = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    d = log_root / "r" / "s1"
    d.mkdir(parents=True)
    good, late, early = _iso(2026, 7, 1, 11), _iso(2026, 7, 1, 12), _iso(2026, 7, 1, 9)
    lines = [
        "123",  # not a dict
        json.dumps({"ts": good, "event": "chunk.spawned", "session": "s1"}),
        json.dumps({"foo": 1}),  # missing ts/event
        json.dumps({"ts": "bad", "event": "x", "session": "s1"}),  # unparseable ts
        json.dumps({"ts": late, "event": "gate.evaluated"}),  # no session key
        json.dumps({"ts": early, "event": "chunk.spawned", "session": "s1"}),  # out of order
    ]
    (d / "a.jsonl").write_text("\n".join(lines) + "\n")
    (log_root / "loose.txt").write_text("x")  # non-dir under log_root
    (log_root / "r" / "loose.txt").write_text("x")  # non-dir under repo dir

    result = m.rebuild(log_root)
    assert result["projected"] == 1
    row = _rows(db)[0]
    assert row[0] == "s1" and row[4] == "running"

    # Missing log root → empty db, no raise.
    assert m.rebuild(tmp_path / "nope") == {"projected": 0, "pruned": 0}


def test_rebuild_prunes_stale_orphan(monkeypatch, tmp_path):
    import os

    m = _state()
    db = tmp_path / "state.db"
    log_root = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    old = log_root / "r" / "orphan"
    old.mkdir(parents=True)
    (old / "a.jsonl").write_text(json.dumps({"ts": _iso(2020, 1, 1), "event": "chunk.spawned", "session": "orphan"}))
    ancient = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC).timestamp()
    os.utime(old, (ancient, ancient))

    result = m.rebuild(log_root, prune_before=datetime.date(2026, 1, 1))
    assert result == {"projected": 0, "pruned": 1}
    assert not old.exists()
