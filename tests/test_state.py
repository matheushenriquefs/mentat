"""Slice s2: lib/state.py — sqlite3 WAL projection of the audit log."""

from __future__ import annotations

import ast
import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from lib import state

_SRC = Path(__file__).resolve().parents[1] / ".agents/lib/state.py"


def _rows(db: Path) -> list[tuple]:
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(
            "SELECT uuid, repo, branch, pid, status, started_at, last_event_at FROM sessions"
        ).fetchall()
    finally:
        conn.close()


def _env(uuid: str = "cafef00d", **over: str) -> dict[str, str]:
    base = {
        "MENTAT_SESSION": uuid,
        "MENTAT_REPO": "mentat",
        "MENTAT_SESSION_BRANCH": "feat/x",
        "MENTAT_SESSION_PID": "4242",
    }
    base.update(over)
    return base


def test_db_path_honors_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_STATE_DB", str(tmp_path / "x.db"))
    assert state.db_path() == tmp_path / "x.db"


def test_db_path_default_under_mentat_dir(monkeypatch):
    monkeypatch.delenv("MENTAT_STATE_DB", raising=False)
    assert state.db_path() == Path.home() / ".mentat" / "state.db"


def test_status_for_terminal_and_default():
    assert state.status_for("chunk.landed") == "landed"
    assert state.status_for("chunk.ejected") == "ejected"
    assert state.status_for("plan.succeeded") == "succeeded"
    assert state.status_for("plan.failed") == "failed"
    # Every non-terminal lifecycle event keeps the session running.
    assert state.status_for("chunk.spawned") == "running"
    assert state.status_for("gate.evaluated") == "running"


def test_project_inserts_queryable_row(monkeypatch, tmp_path):
    db = tmp_path / "state.db"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    state.project(_env(), "chunk.spawned", now=100.0)

    rows = _rows(db)
    assert rows == [("cafef00d", "mentat", "feat/x", 4242, "running", 100.0, 100.0)]


def test_project_terminal_event_sets_status(monkeypatch, tmp_path):
    db = tmp_path / "state.db"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    state.project(_env(), "chunk.landed", now=5.0)

    assert _rows(db)[0][4] == "landed"


def test_project_upsert_freezes_started_advances_last_event(monkeypatch, tmp_path):
    db = tmp_path / "state.db"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    state.project(_env(), "chunk.spawned", now=10.0)
    state.project(_env(), "chunk.landed", now=25.0)

    uuid, _repo, _branch, _pid, status, started_at, last_event_at = _rows(db)[0]
    assert status == "landed"
    assert started_at == 10.0  # frozen at first emit
    assert last_event_at == 25.0  # advanced


def test_project_coalesce_keeps_earlier_fields(monkeypatch, tmp_path):
    """A later emit with a sparser env must not null out repo/branch/pid the
    first emit already recorded."""
    db = tmp_path / "state.db"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    state.project(_env(), "chunk.spawned", now=1.0)
    state.project({"MENTAT_SESSION": "cafef00d"}, "chunk.landed", now=2.0)

    _uuid, repo, branch, pid, status, _s, last = _rows(db)[0]
    assert (repo, branch, pid) == ("mentat", "feat/x", 4242)
    assert status == "landed"
    assert last == 2.0


def test_project_noop_without_session_id(monkeypatch, tmp_path):
    db = tmp_path / "state.db"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    state.project({"MENTAT_REPO": "mentat"}, "chunk.spawned", now=1.0)

    assert not db.exists()


def test_project_non_numeric_pid_stored_null(monkeypatch, tmp_path):
    db = tmp_path / "state.db"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    state.project(_env(MENTAT_SESSION_PID="not-a-pid"), "chunk.spawned", now=1.0)

    assert _rows(db)[0][3] is None


def test_project_defaults_now_to_wall_clock(monkeypatch, tmp_path):
    db = tmp_path / "state.db"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    with patch.object(state.time, "time", return_value=777.0):
        state.project(_env(), "chunk.spawned")

    assert _rows(db)[0][5] == 777.0


def test_project_enables_wal_mode(monkeypatch, tmp_path):
    db = tmp_path / "state.db"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    state.project(_env(), "chunk.spawned", now=1.0)

    conn = sqlite3.connect(str(db))
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert mode.lower() == "wal"


def test_project_swallows_sqlite_error(monkeypatch, tmp_path):
    """Projection is best-effort: an unopenable db (path is a directory) must not
    raise — the NDJSON log is the source of truth."""
    as_dir = tmp_path / "state.db"
    as_dir.mkdir()
    monkeypatch.setenv("MENTAT_STATE_DB", str(as_dir))

    state.project(_env(), "chunk.spawned", now=1.0)  # no raise


def test_state_is_stdlib_only():
    tree = ast.parse(_SRC.read_text())
    stdlib = sys.stdlib_module_names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in stdlib, f"non-stdlib import: {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            assert top in stdlib or node.module.startswith("lib"), f"non-stdlib from-import: {node.module}"


# ── S3: state.list_sessions — the reader's one indexed query ──────────────────


def test_list_sessions_lists_running_newest_first(monkeypatch, tmp_path):
    """A live + an idle-but-incomplete session both list (both non-terminal);
    ordered newest-activity first."""
    db = tmp_path / "state.db"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    state.project(_env("live", MENTAT_REPO="r"), "chunk.spawned", now=100.0)
    state.project(_env("idle", MENTAT_REPO="r"), "gate.evaluated", now=50.0)

    rows = state.list_sessions("r", now=200.0)
    assert [r["session"] for r in rows] == ["live", "idle"]
    assert rows[0]["status"] == "running"
    assert rows[0]["age"] == 100.0  # 200 - last_event_at(100)


def test_list_sessions_no_recency_window_keeps_ancient_running(monkeypatch, tmp_path):
    """The recency window that hid live-but-idle sessions is gone: an ancient
    still-running session must never false-empty out of the active view."""
    db = tmp_path / "state.db"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    state.project(_env("ancient", MENTAT_REPO="r"), "chunk.spawned", now=0.0)

    rows = state.list_sessions("r", now=10 * 86400.0)  # 10 days later
    assert [r["session"] for r in rows] == ["ancient"]


def test_list_sessions_active_only_excludes_terminal(monkeypatch, tmp_path):
    db = tmp_path / "state.db"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    state.project(_env("live", MENTAT_REPO="r"), "chunk.spawned", now=100.0)
    state.project(_env("done", MENTAT_REPO="r"), "chunk.landed", now=100.0)

    assert [r["session"] for r in state.list_sessions("r", now=200.0)] == ["live"]
    assert {r["session"] for r in state.list_sessions("r", now=200.0, active_only=False)} == {"live", "done"}


def test_list_sessions_filters_by_repo(monkeypatch, tmp_path):
    db = tmp_path / "state.db"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    state.project(_env("a", MENTAT_REPO="r1"), "chunk.spawned", now=1.0)
    state.project(_env("b", MENTAT_REPO="r2"), "chunk.spawned", now=1.0)

    assert [r["session"] for r in state.list_sessions("r1", now=2.0)] == ["a"]


def test_list_sessions_missing_db_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_STATE_DB", str(tmp_path / "never-written.db"))
    assert state.list_sessions("r", now=1.0) == []


# ── S4: state.rebuild — regenerate the db from the durable NDJSON log ─────────


def _iso(y: int, mo: int, d: int, h: int = 12) -> str:
    return datetime.datetime(y, mo, d, h, tzinfo=datetime.UTC).isoformat()


def _epoch(iso: str) -> float:
    return datetime.datetime.fromisoformat(iso).timestamp()


def _write_log(log_root: Path, repo: str, session: str, rows: list[dict]) -> Path:
    """Write ``rows`` as one agent's NDJSON file under log_root/repo/session/."""
    d = log_root / repo / session
    d.mkdir(parents=True, exist_ok=True)
    f = d / "agent-a.jsonl"
    f.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return d


def _row(ts: str, event: str, session: str, **payload) -> dict:
    return {"ts": ts, "agent": "mentat-orchestrate", "session": session, "event": event, "payload": payload}


def test_rebuild_reduces_log_to_db(monkeypatch, tmp_path):
    """Replay NDJSON → one row per session: status from the latest event,
    started_at = earliest ts, last_event_at = latest ts. branch/pid are live-only
    enrichment absent from the durable log, so they rebuild null."""
    db = tmp_path / "state.db"
    log_root = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    t1, t2 = _iso(2026, 7, 1, 10), _iso(2026, 7, 1, 11)
    _write_log(log_root, "mentat", "sess1", [_row(t1, "chunk.spawned", "sess1"), _row(t2, "chunk.landed", "sess1")])
    t3 = _iso(2026, 7, 1, 9)
    _write_log(log_root, "mentat", "sess2", [_row(t3, "chunk.spawned", "sess2")])

    state.rebuild(log_root)

    rows = {r[0]: r for r in _rows(db)}
    assert rows["sess1"] == ("sess1", "mentat", None, None, "landed", _epoch(t1), _epoch(t2))
    assert rows["sess2"] == ("sess2", "mentat", None, None, "running", _epoch(t3), _epoch(t3))


def test_rebuild_delete_then_rebuild_is_identical(monkeypatch, tmp_path):
    """The Kleppmann invariant: delete the throwaway db, rebuild from the log,
    get byte-identical rows."""
    db = tmp_path / "state.db"
    log_root = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    _write_log(
        log_root,
        "mentat",
        "sess1",
        [_row(_iso(2026, 7, 1, 10), "chunk.spawned", "sess1"), _row(_iso(2026, 7, 1, 11), "chunk.landed", "sess1")],
    )

    state.rebuild(log_root)
    before = _rows(db)

    db.unlink()
    state.rebuild(log_root)
    assert _rows(db) == before


def test_rebuild_is_fresh_not_additive(monkeypatch, tmp_path):
    """Rebuild starts from an empty table: a session whose dir no longer exists
    must not survive a rebuild as a stale row."""
    db = tmp_path / "state.db"
    log_root = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    d = _write_log(log_root, "mentat", "gone", [_row(_iso(2026, 7, 1, 10), "chunk.spawned", "gone")])
    state.rebuild(log_root)
    assert {r[0] for r in _rows(db)} == {"gone"}

    import shutil

    shutil.rmtree(d)
    state.rebuild(log_root)
    assert _rows(db) == []


def test_rebuild_prunes_old_orphan_keeps_fresh(monkeypatch, tmp_path):
    """One-shot: a stale session dir older than the cutoff is pruned from disk and
    never projected; a fresh session is kept and projected."""
    db = tmp_path / "state.db"
    log_root = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    old_dir = _write_log(log_root, "mentat", "orphan", [_row(_iso(2020, 1, 1), "chunk.spawned", "orphan")])
    ancient = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC).timestamp()
    os.utime(old_dir, (ancient, ancient))

    fresh_dir = _write_log(log_root, "mentat", "fresh", [_row(_iso(2026, 7, 1), "chunk.spawned", "fresh")])
    recent = datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC).timestamp()
    os.utime(fresh_dir, (recent, recent))

    result = state.rebuild(log_root, prune_before=datetime.date(2026, 1, 1))

    assert not old_dir.exists()
    assert fresh_dir.exists()
    assert {r[0] for r in _rows(db)} == {"fresh"}
    assert result == {"projected": 1, "pruned": 1}


def test_rebuild_skips_empty_and_unparseable_dirs(monkeypatch, tmp_path):
    """A session dir with no valid rows projects nothing — no phantom row."""
    db = tmp_path / "state.db"
    log_root = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    d = log_root / "mentat" / "empty"
    d.mkdir(parents=True)
    (d / "agent-a.jsonl").write_text("not json\n\n")

    state.rebuild(log_root)
    assert _rows(db) == []


def test_list_sessions_swallows_sqlite_error(monkeypatch, tmp_path):
    """Best-effort read: an unopenable db (path is a directory) yields [] rather
    than raising — the NDJSON log is the truth (state.py:101-102)."""
    as_dir = tmp_path / "state.db"
    as_dir.mkdir()
    monkeypatch.setenv("MENTAT_STATE_DB", str(as_dir))

    assert state.list_sessions("r", now=1.0) == []


def test_rebuild_tolerates_malformed_rows_and_nondir_entries(monkeypatch, tmp_path):
    """_reduce_session skips: non-dict JSON, dicts missing ts/event, unparseable
    ts, and rows without a session key — while still projecting a session that has
    at least one valid row. Out-of-order timestamps leave last_ts at the true max.
    Non-directory entries under log_root and under a repo dir are skipped
    (state.py:136, 140-141, 143->145, 147->127, 182, 185)."""
    db = tmp_path / "state.db"
    log_root = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    d = log_root / "mentat" / "s1"
    d.mkdir(parents=True)
    good = _iso(2026, 7, 1, 11)
    nosession = _iso(2026, 7, 1, 12)
    older = _iso(2026, 7, 1, 9)
    lines = [
        "123",  # valid JSON but not a dict → skipped
        json.dumps({"ts": good, "event": "chunk.spawned", "session": "s1"}),
        json.dumps({"foo": 1}),  # dict missing ts/event → skipped
        json.dumps({"ts": "not-a-date", "event": "x", "session": "s1"}),  # bad ts → skipped
        json.dumps({"ts": nosession, "event": "gate.evaluated"}),  # no session key
        json.dumps({"ts": older, "event": "chunk.spawned", "session": "s1"}),  # older → last_ts holds
    ]
    (d / "agent-a.jsonl").write_text("\n".join(lines) + "\n")

    # Non-directory entries at both levels must be skipped, not reduced.
    (log_root / "loose-file.txt").write_text("x")
    (log_root / "mentat" / "loose.txt").write_text("x")

    state.rebuild(log_root)

    rows = {r[0]: r for r in _rows(db)}
    assert set(rows) == {"s1"}
    assert rows["s1"][4] == "running"  # latest event = gate.evaluated
    assert rows["s1"][5] == _epoch(older)  # earliest valid ts
    assert rows["s1"][6] == _epoch(nosession)  # latest valid ts (out-of-order tail ignored)


def test_rebuild_missing_log_root_yields_empty_db(monkeypatch, tmp_path):
    db = tmp_path / "state.db"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))

    result = state.rebuild(tmp_path / "does-not-exist")
    assert result == {"projected": 0, "pruned": 0}
    assert _rows(db) == []


def test_emit_projects_session_row(monkeypatch, tmp_path):
    """The red: a confirmed emit projects a queryable row with correct status."""
    import subprocess

    from lib import events

    db = tmp_path / "state.db"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))
    monkeypatch.setenv("MENTAT_SESSION", "deadbeef")
    monkeypatch.setenv("MENTAT_REPO", "mentat")

    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        events.bind("mentat-orchestrate")("chunk.landed", {"slug": "x", "sha": "a", "holding": "h"})

    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0][0] == "deadbeef"
    assert rows[0][4] == "landed"


def test_emit_failure_does_not_project(monkeypatch, tmp_path):
    """A rejected log write must not leave a phantom row — the projection stays
    consistent with what was actually logged."""
    import subprocess

    from lib import events

    db = tmp_path / "state.db"
    monkeypatch.setenv("MENTAT_STATE_DB", str(db))
    monkeypatch.setenv("MENTAT_SESSION", "deadbeef")

    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "bad payload\n"
        with pytest.raises(RuntimeError):
            events.bind("mentat-orchestrate")("chunk.landed", {"slug": "x"})

    assert not db.exists()
