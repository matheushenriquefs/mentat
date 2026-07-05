"""Unit tests for lib/chunk.py identity derivations."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import lib.chunk as chunk_mod
import pytest

UUID_HEX = re.compile(r"^[0-9a-f]{32}$")


def test_make_chunk_id_is_uuid7_hex() -> None:
    cid = chunk_mod.make_chunk_id()
    assert UUID_HEX.match(cid)
    uuid.UUID(hex=cid, version=7)


def test_chunk_slug_joins_id_and_slug() -> None:
    assert chunk_mod.chunk_slug("abc123", "my-plan") == "abc123/my-plan"


def test_holding_branch_namespaced() -> None:
    cs = chunk_mod.chunk_slug("abc123", "my-plan")
    assert chunk_mod.holding_branch(cs) == "mentat/abc123/my-plan"


def test_worktree_path_under_chunk_id_dir(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    cs = chunk_mod.chunk_slug("deadbeef", "feat")
    assert chunk_mod.worktree_path(repo, cs) == repo / ".mentat" / "worktrees" / "deadbeef" / "feat"


def test_chunk_slug_from_worktree_roundtrip(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    wt = repo / ".mentat" / "worktrees" / "cafe" / "plan-a"
    wt.mkdir(parents=True)
    assert chunk_mod.chunk_slug_from_worktree(wt, repo) == "cafe/plan-a"


def test_bind_and_resolve_plan_chunk() -> None:
    chunk_mod.clear_plan_chunks()
    chunk_mod.bind_plan_chunk("plan-a", "chunk1")
    assert chunk_mod.chunk_id_for_plan("plan-a") == "chunk1"
    chunk_mod.clear_plan_chunks()


def test_chunk_id_for_plan_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    chunk_mod.clear_plan_chunks()
    monkeypatch.delenv("MENTAT_CHUNK_ID", raising=False)
    with pytest.raises(LookupError):
        chunk_mod.chunk_id_for_plan("missing")
