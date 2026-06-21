"""Tests for mentat-orchestrate land_queue module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


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

    assert result["status"] == "success"
    emitted = [c.args[0] for c in mock_emit.call_args_list]
    assert any("chunk.landed" in e for e in emitted)


def test_land_queue_emits_chunk_ejected_with_gate_failed():
    lq = load_module("land_queue")
    chunk = make_chunk("fail-chunk")

    with patch.object(lq, "_rebase_chunk", return_value=("abc123", None)):
        with patch.object(lq, "_run_gates", return_value=("block", "too smelly")):
            with patch.object(lq, "_emit_event") as mock_emit:
                result = lq.land(chunk, holding="main")

    assert result["status"] == "eject"
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
        return {"status": "success", "tip": "abc", "slug": chunk.slug}

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
    assert "status" in result
    assert "tip" in result
    assert result["status"] in ("success", "eject")
    assert result["tip"] == "sha1"


# ── _ff_merge integration tests ──────────────────────────────────────────────

import subprocess as _subprocess  # noqa: E402


def _git(args: list[str], cwd) -> None:
    _subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _setup_ff_repo(tmp_path):
    """Two-worktree fixture: main on 'holding', chunk on 'feature' 1 commit ahead."""
    lq = load_module("land_queue")
    main_repo = tmp_path / "main"
    main_repo.mkdir()

    _git(["init", "-b", "holding", str(main_repo)], cwd=tmp_path)
    for k, v in (("user.email", "t@t"), ("user.name", "T"), ("commit.gpgsign", "false")):
        _git(["config", k, v], cwd=main_repo)

    (main_repo / "README").write_text("init\n")
    _git(["add", "."], cwd=main_repo)
    _git(["commit", "-m", "init"], cwd=main_repo)

    _git(["checkout", "-b", "feature"], cwd=main_repo)
    (main_repo / "README").write_text("feature\n")
    _git(["add", "."], cwd=main_repo)
    _git(["commit", "-m", "feature commit"], cwd=main_repo)

    feature_sha = _subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=main_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    _git(["checkout", "holding"], cwd=main_repo)

    chunk_wt = tmp_path / "chunk"
    _git(["worktree", "add", str(chunk_wt), "feature"], cwd=main_repo)

    chunk = lq.Chunk(slug="test-chunk", worktree=chunk_wt)
    return main_repo, chunk, lq, feature_sha


def test_ff_merge_updates_main_worktree(tmp_path) -> None:
    """After _ff_merge, main worktree HEAD and on-disk files reflect feature tip."""
    main_repo, chunk, lq, feature_sha = _setup_ff_repo(tmp_path)

    result = lq._ff_merge(chunk, "holding")

    assert result is True, "_ff_merge should return True on clean FF"

    resolved = _subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=main_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert resolved == feature_sha, f"main HEAD {resolved!r} != feature_sha {feature_sha!r}"

    assert (main_repo / "README").read_text() == "feature\n", "README not updated in main worktree working tree"


def test_ff_merge_refuses_dirty_main_worktree(tmp_path) -> None:
    """Dirty main worktree: _ff_merge returns False, ref stays put, dirt survives."""
    main_repo, chunk, lq, _ = _setup_ff_repo(tmp_path)

    before_sha = _subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=main_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    (main_repo / "README").write_text("dirty\n")

    result = lq._ff_merge(chunk, "holding")

    assert result is False, "_ff_merge must return False when main worktree is dirty"

    after_sha = _subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=main_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert after_sha == before_sha, "ref must not advance when main worktree is dirty"

    assert (main_repo / "README").read_text() == "dirty\n", "dirty state must be preserved"
