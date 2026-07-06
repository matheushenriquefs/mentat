"""S2: orphan filter + reaped-dir GC at track list root."""

from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".agents"))

from lib import store  # noqa: E402


def _insert_agent(
    conn,
    *,
    agent_id: str,
    supervisor_id: str | None = None,
    status: str = "running",
) -> None:
    agents = store.AgentDAO(conn)
    agents.insert(
        store.Agent(
            id=agent_id,
            supervisor_id=supervisor_id,
            resumed_from_id=None,
            forked_from_id=None,
            harness="cursor",
            pid=os.getpid(),
            status=status,  # type: ignore[arg-type]
            status_reason=None,
            started_at=store.iso_now(),
            ended_at=None,
        )
    )
    store.EventDAO(conn).append(kind="chunk_started", payload={"slug": "x"}, agent_id=agent_id)


def test_supervisor_orphan_excluded_from_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "mentat.db"
    logs = tmp_path / "logs"
    repo = "mentat"
    monkeypatch.setenv("MENTAT_DB", str(db))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(logs))
    conn = store.connect()
    _insert_agent(conn, agent_id="parent-dead", status="reaped")
    _insert_agent(conn, agent_id="child-live", supervisor_id="parent-dead")
    _insert_agent(conn, agent_id="solo-live")
    conn.close()
    for aid in ("child-live", "solo-live"):
        (logs / repo / aid).mkdir(parents=True)
    rows = store.list_track_entries(repo, active_only=False)
    names = {str(r["agent"]) for r in rows}
    assert "solo-live" in names
    assert "child-live" not in names


def test_gc_reaped_track_dirs_removes_stale_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "mentat.db"
    logs = tmp_path / "logs"
    repo = "mentat"
    stale_id = "stale-reaped"
    live_id = "live-agent"
    monkeypatch.setenv("MENTAT_DB", str(db))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(logs))
    conn = store.connect()
    agents = store.AgentDAO(conn)
    old = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    agents.insert(
        store.Agent(
            id=stale_id,
            supervisor_id=None,
            resumed_from_id=None,
            forked_from_id=None,
            harness="cursor",
            pid=None,
            status="reaped",
            status_reason="dead_pid",
            started_at=old,
            ended_at=old,
        )
    )
    _insert_agent(conn, agent_id=live_id)
    conn.close()
    stale_dir = logs / repo / stale_id
    live_dir = logs / repo / live_id
    stale_dir.mkdir(parents=True)
    live_dir.mkdir(parents=True)
    now = time.time()
    store.gc_reaped_track_dirs(repo, now=now + store._RECENCY_SECS + 1)
    assert not stale_dir.exists()
    assert live_dir.exists()
