"""Slice s2: lib/state.py — sqlite3 WAL projection of the audit log."""

from __future__ import annotations

import ast
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
