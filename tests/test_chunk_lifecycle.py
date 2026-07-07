"""S1 gate: chunk spawn persists slice + chunk rows; events resolve chunk_id."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from lib.chunk_service import ChunkService
from lib.store import ChunkDAO, EventDAO, SliceDAO, connect, make_slice_id, record_emit


def _mini_plan(tmp_path: Path) -> Path:
    body = """---
id: mini-plan
status: ready
kind: AFK
blocked_by: []
---

## Slice S1 — first (AFK)

**depends on:** none

## Slice S2 — second (AFK)

**depends on:** S1
"""
    path = tmp_path / "mini-plan.md"
    path.write_text(body)
    return path


def test_spawn_persists_slices_and_chunk(tmp_path, monkeypatch):
    db = tmp_path / "mentat.db"
    monkeypatch.setenv("MENTAT_DB", str(db))
    plan = _mini_plan(tmp_path)
    wt = tmp_path / ".mentat" / "worktrees" / "cid1" / "mini-plan"
    wt.mkdir(parents=True)

    svc = ChunkService.open()
    row = svc.create(
        chunk_id="cid1",
        plan_slug="mini-plan",
        plan_path=plan,
        agent_id="agent-1",
        worktree=wt,
    )

    conn = connect(db)
    try:
        slices = SliceDAO(conn)
        assert slices.get_by_id(make_slice_id("mini-plan", "S1")) is not None
        assert slices.get_by_id(make_slice_id("mini-plan", "S2")) is not None
        chunk = ChunkDAO(conn).get_by_id("cid1")
        assert chunk is not None
        assert chunk.worktree_path == str(wt)
        assert row.slug == "mini-plan"
    finally:
        conn.close()


def test_record_emit_resolves_chunk_id(tmp_path, monkeypatch):
    db = tmp_path / "mentat.db"
    monkeypatch.setenv("MENTAT_DB", str(db))
    plan = _mini_plan(tmp_path)
    wt = tmp_path / ".mentat" / "worktrees" / "cid2" / "mini-plan"
    wt.mkdir(parents=True)
    ChunkService.open().create(
        chunk_id="cid2",
        plan_slug="mini-plan",
        plan_path=plan,
        agent_id="agent-2",
        worktree=wt,
    )
    env = {
        "MENTAT_AGENT": "agent-2",
        "MENTAT_CHUNK_ID": "cid2",
        "MENTAT_HARNESS": "cursor",
    }
    record_emit(env, "chunk_started", {"slug": "mini-plan"})
    conn = connect(db)
    try:
        events = EventDAO(conn).list_by_agent("agent-2")
        assert len(events) == 1
        assert events[0].chunk_id == "cid2"
    finally:
        conn.close()


def test_landing_chunk_is_store_chunk():
    import landing
    from lib import store

    chunk = landing.land_chunk(slug="x", worktree=Path("/tmp/x"), chunk_id="c")
    assert isinstance(chunk, store.Chunk)
    assert chunk.id == "c"
