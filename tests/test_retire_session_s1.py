"""S1 grep-gate: zero ``session`` token in ``.agents/lib/``."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = REPO_ROOT / ".agents" / "lib"

sys.path.insert(0, str(REPO_ROOT / ".agents"))
from lib import agent as agent_mod  # noqa: E402
from lib import store  # noqa: E402

_SESSION_RE = re.compile(r"session", re.IGNORECASE)
_MENTAT_SESSION_RE = re.compile(r"MENTAT_SESSION")


def _lib_py_files() -> list[Path]:
    return sorted(LIB_DIR.rglob("*.py"))


def test_lib_has_zero_session_token() -> None:
    offenders: list[str] = []
    for path in _lib_py_files():
        text = path.read_text()
        rel = path.relative_to(REPO_ROOT)
        if _SESSION_RE.search(text):
            offenders.append(str(rel))
        if _MENTAT_SESSION_RE.search(text):
            offenders.append(f"{rel} (MENTAT_SESSION)")
    assert offenders == [], f"session token remains in lib: {offenders}"


def test_agent_id_from_env_reads_mentat_agent_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MENTAT_AGENT", raising=False)
    assert agent_mod.agent_id_from_env() is None
    monkeypatch.setenv("MENTAT_AGENT", "abc123")
    assert agent_mod.agent_id_from_env() == "abc123"
    monkeypatch.setenv("MENTAT_SESSION", "legacy")
    assert agent_mod.agent_id_from_env() == "abc123"


def test_ensure_agent_exports_agent_env_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.delenv("MENTAT_AGENT", raising=False)
    monkeypatch.delenv("MENTAT_AGENT_LOG", raising=False)
    monkeypatch.delenv("MENTAT_AGENT_PID", raising=False)
    for key in ("MENTAT_SESSION", "MENTAT_SESSION_LOG", "MENTAT_SESSION_PID"):
        monkeypatch.delenv(key, raising=False)
    agent_id = agent_mod.ensure_agent("implement", "plan-a")
    assert os.environ["MENTAT_AGENT"] == agent_id
    assert os.environ.get("MENTAT_AGENT_LOG")
    assert os.environ.get("MENTAT_AGENT_PID")
    assert "MENTAT_SESSION" not in os.environ
    assert "MENTAT_SESSION_LOG" not in os.environ
    assert "MENTAT_SESSION_PID" not in os.environ


def test_list_track_entries_round_trips_agent_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = tmp_path / "mentat.db"
    logs = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_DB", str(db))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(logs))
    repo = "demo"
    agent_id = "agent-track-1"
    env = {
        "MENTAT_AGENT": agent_id,
        "MENTAT_AGENT_PID": str(os.getpid()),
        "MENTAT_HARNESS": "cursor",
    }
    store.record_emit(env, "agent_started", {})
    (logs / repo / agent_id).mkdir(parents=True)
    entries = store.list_track_entries(repo, active_only=False)
    assert len(entries) == 1
    assert "agent" in entries[0]
    assert "session" not in entries[0]
    assert entries[0]["agent"] == agent_id


def test_audit_row_uses_agent_id_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MENTAT_DB", str(tmp_path / "mentat.db"))
    conn = store.connect()
    try:
        store.AgentDAO(conn).insert(
            store.Agent(
                id="a1",
                supervisor_id=None,
                resumed_from_id=None,
                forked_from_id=None,
                harness="implement",
                pid=None,
                status="running",
                status_reason=None,
                started_at=store.iso_now(),
                ended_at=None,
            )
        )
        store.EventDAO(conn).append(kind="chunk_started", payload={"slug": "x"}, agent_id="a1")
        rows = store.EventDAO(conn).list_by_agent("a1")
    finally:
        conn.close()
    row = store.audit_row(rows[0], skill="implement")
    assert row["agent_id"] == "a1"
    assert "session" not in row
