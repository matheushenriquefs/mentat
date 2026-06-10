"""Tests for mentat-orchestrate land_queue module."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def make_chunk(slug: str):
    lq = load_module("land_queue")
    return lq.Chunk(slug=slug, worktree=Path(f"/tmp/{slug}"))


def test_land_queue_emits_chunk_landed_on_success():
    lq = load_module("land_queue")
    chunk = make_chunk("my-chunk")

    with patch.object(lq, "_rebase_chunk", return_value=("abc123", None)):
        with patch.object(lq, "_run_gates", return_value=("pass", "")):
            with patch.object(lq, "_ff_merge", return_value=True):
                with patch.object(lq, "_emit_event") as mock_emit:
                    result = lq.land(chunk, holding="main")

    assert result["outcome"] == "success"
    emitted = [c.args[0] for c in mock_emit.call_args_list]
    assert any("chunk.landed" in e for e in emitted)


def test_land_queue_emits_chunk_ejected_with_gate_failed():
    lq = load_module("land_queue")
    chunk = make_chunk("fail-chunk")

    with patch.object(lq, "_rebase_chunk", return_value=("abc123", None)):
        with patch.object(lq, "_run_gates", return_value=("block", "too smelly")):
            with patch.object(lq, "_emit_event") as mock_emit:
                result = lq.land(chunk, holding="main")

    assert result["outcome"] == "eject"
    assert result["reason"] == "gate-failed"
    emitted = [c.args[0] for c in mock_emit.call_args_list]
    assert any("chunk.ejected" in e for e in emitted)


def test_land_queue_serializes_landings():
    """drain processes chunks one-by-one (serial)."""
    lq = load_module("land_queue")
    chunks = [make_chunk(f"c{i}") for i in range(3)]

    call_order: list[str] = []

    def fake_land(chunk, *, holding):
        call_order.append(chunk.slug)
        return {"outcome": "success", "tip": "abc", "slug": chunk.slug}

    with patch.object(lq, "land", side_effect=fake_land):
        results = lq.drain(chunks, holding="main")

    assert call_order == ["c0", "c1", "c2"]
    assert len(results) == 3


def test_land_queue_rebases_each_chunk():
    """land() calls _rebase_chunk with the correct holding branch."""
    lq = load_module("land_queue")
    chunk = make_chunk("r-chunk")

    rebase_calls = []

    def fake_rebase(c, holding):
        rebase_calls.append((c.slug, holding))
        return ("sha123", None)

    with patch.object(lq, "_rebase_chunk", side_effect=fake_rebase):
        with patch.object(lq, "_run_gates", return_value=("pass", "")):
            with patch.object(lq, "_ff_merge", return_value=True):
                with patch.object(lq, "_emit_event"):
                    lq.land(chunk, holding="my-holding")

    assert any(slug == "r-chunk" for slug, _ in rebase_calls)
    assert any(h == "my-holding" for _, h in rebase_calls)


def test_land_queue_emits_canonical_verdict_jsonl_shape():
    lq = load_module("land_queue")
    chunk = make_chunk("shape-chunk")

    with patch.object(lq, "_rebase_chunk", return_value=("sha1", None)):
        with patch.object(lq, "_run_gates", return_value=("pass", "")):
            with patch.object(lq, "_ff_merge", return_value=True):
                with patch.object(lq, "_emit_event"):
                    result = lq.land(chunk, holding="main")

    assert "slug" in result
    assert "outcome" in result
    assert "tip" in result
    assert result["outcome"] in ("success", "eject")
    assert result["tip"] == "sha1"
