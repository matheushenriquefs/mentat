"""S2 gate: land() reclaims resources; prune reaps cross-run leftovers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import landing
import pytest

from lib.store import Chunk, iso_now, make_slice_id
from tests.conftest import TEST_CHUNK_ID


def _chunk(slug: str, tmp_path: Path) -> landing.Chunk:
    wt = tmp_path / ".mentat" / "worktrees" / TEST_CHUNK_ID / slug
    wt.mkdir(parents=True, exist_ok=True)
    return landing.land_chunk(slug=slug, worktree=wt, chunk_id=TEST_CHUNK_ID)


def test_land_success_teardown_all_three(tmp_path, monkeypatch):
    calls: list[str] = []

    def fake_teardown(chunk: landing.Chunk) -> None:
        calls.append("full")

    monkeypatch.setattr(landing, "_rebase_chunk", lambda c, h: ("sha1", None))
    monkeypatch.setattr(landing, "_run_gates", lambda c: ("pass", ""))
    monkeypatch.setattr(landing, "_ff_merge", lambda c, h: None)
    monkeypatch.setattr(landing, "_emit_event", lambda *a, **kw: None)
    monkeypatch.setattr(landing, "_teardown_chunk_resources", fake_teardown)

    chunk = _chunk("ok", tmp_path)
    verdict = landing.land(chunk, holding="main")

    assert verdict["status"] == "success"
    assert calls == ["full"]


def test_prune_holding_delegates(tmp_path, monkeypatch):
    import batch as batch_mod

    monkeypatch.setattr(batch_mod._git, "repo_root", lambda p: tmp_path)
    monkeypatch.setattr(
        batch_mod._cleanup,
        "prune_landed_chunks",
        lambda holding, **kw: 2,
    )
    assert batch_mod.prune_holding("main") == 2
