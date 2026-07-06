"""E2E journey: the sqlite canonical store projection (lib/store.py).

Exercises record_emit upserts, list_track_entries ordering and filters, and
attempt_count replay from the durable store.
"""

from __future__ import annotations

import os
import time

import pytest

from tests.conftest import seed_agent_events

pytestmark = pytest.mark.e2e


def test_record_emit_and_list_track_roundtrip(tmp_path, monkeypatch):
    from lib import store

    log_root = tmp_path / "logs"
    repo = "r"
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_root))
    monkeypatch.setenv("MENTAT_REPO", repo)

    for agent_id, event, status in (
        ("live", "chunk_started", "running"),
        ("idle", "chunk_landed", "stopped"),
        ("done", "chunk_ejected", "stopped"),
    ):
        seed_agent_events(
            tmp_path,
            repo,
            agent_id,
            [{"event": event, "payload": {"slug": "x", "reason": "boom", "where": "w"}}],
            status=status,
        )
        (log_root / repo / agent_id).mkdir(parents=True, exist_ok=True)

    active = store.list_track_entries(repo, active_only=True)
    active_by_id = {str(r["agent"]): str(r["status"]) for r in active}
    assert active_by_id["live"] == "working"
    assert active_by_id["idle"] == "idle"
    assert active_by_id["done"] == "idle"
    full = {r["agent"] for r in store.list_track_entries(repo, active_only=False)}
    assert full == {"live", "idle", "done"}


def test_list_track_marks_stale_running_as_crashed(tmp_path, monkeypatch):
    from lib import store

    log_root = tmp_path / "logs"
    repo = "r"
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_root))
    monkeypatch.setenv("MENTAT_REPO", repo)
    seed_agent_events(tmp_path, repo, "stale", [{"event": "chunk_started", "payload": {"slug": "x"}}])
    sd = log_root / repo / "stale"
    sd.mkdir(parents=True, exist_ok=True)
    ancient = time.time() - 600
    os.utime(sd, (ancient, ancient))
    conn = store.connect()
    try:
        row = store.AgentDAO(conn).get_by_id("stale")
        assert row is not None
        store.AgentDAO(conn).update_status(row.id, status="running", ended_at=None)
        store.EventDAO(conn).append(
            kind="chunk_started",
            payload={"slug": "x"},
            agent_id="stale",
            ts=store.iso_now(now=ancient),
        )
    finally:
        conn.close()

    entries = store.list_track_entries(repo, active_only=False, now=time.time())
    by_id = {str(e["agent"]): e for e in entries}
    assert by_id["stale"]["status"] == "?"


def test_attempt_count_replays_recovery_spawns(tmp_path, monkeypatch):
    from lib import store

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    seed_agent_events(
        tmp_path,
        "repo",
        "s1",
        [
            {"event": "chunk_started", "payload": {"slug": "core", "trigger": "recovery"}},
            {"event": "chunk_started", "payload": {"slug": "core", "trigger": "recovery"}},
            {"event": "chunk_started", "payload": {"slug": "core"}},
            {"event": "chunk_landed", "payload": {"slug": "core", "trigger": "recovery"}},
            {"event": "chunk_started", "payload": {"slug": "other", "trigger": "recovery"}},
        ],
    )
    assert store.attempt_count("s1", "core") == 2
    assert store.attempt_count("no-session", "core") == 0
