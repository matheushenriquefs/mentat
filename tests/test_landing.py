"""Tests for mentat-orchestrate landing module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def make_chunk(slug: str):
    lq = load_module("landing")
    return lq.Chunk(slug=slug, worktree=Path(f"/tmp/{slug}"))


def test_land_queue_emits_chunk_landed_on_success():
    lq = load_module("landing")
    chunk = make_chunk("my-chunk")

    with patch.object(lq, "_rebase_chunk", return_value=("abc123", None)):
        with patch.object(lq, "_run_gates", return_value=("pass", "")):
            with patch.object(lq, "_ff_merge", return_value=None):
                with patch.object(lq, "_emit_event") as mock_emit:
                    result = lq.land(chunk, holding="main")

    assert result["status"] == "success"
    emitted = [c.args[0] for c in mock_emit.call_args_list]
    assert any("chunk_landed" in e for e in emitted)


def test_land_queue_emits_chunk_ejected_with_gate_failed():
    lq = load_module("landing")
    chunk = make_chunk("fail-chunk")

    with patch.object(lq, "_rebase_chunk", return_value=("abc123", None)):
        with patch.object(lq, "_run_gates", return_value=("block", "too smelly")):
            with patch.object(lq, "_emit_event") as mock_emit:
                result = lq.land(chunk, holding="main")

    assert result["status"] == "eject"
    assert result["reason"] == "gate_failed"
    emitted = [c.args[0] for c in mock_emit.call_args_list]
    assert any("chunk_ejected" in e for e in emitted)


def test_land_queue_serializes_landings():
    """drain processes chunks one-by-one (serial)."""
    lq = load_module("landing")
    chunks = [make_chunk(f"c{i}") for i in range(3)]

    call_order: list[str] = []

    def fake_land(chunk, *, holding):
        call_order.append(chunk.slug)
        return {"status": "success", "tip": "abc", "slug": chunk.slug}

    with patch.object(lq, "land", side_effect=fake_land):
        with patch.object(lq, "_teardown_container", lambda chunk: None):
            results = lq.drain(chunks, holding="main")

    assert call_order == ["c0", "c1", "c2"]
    assert len(results) == 3


def test_land_queue_rebases_each_chunk():
    """land() calls _rebase_chunk with the correct holding branch."""
    lq = load_module("landing")
    chunk = make_chunk("r-chunk")

    rebase_calls = []

    def fake_rebase(c, holding):
        rebase_calls.append((c.slug, holding))
        return ("sha123", None)

    with patch.object(lq, "_rebase_chunk", side_effect=fake_rebase):
        with patch.object(lq, "_run_gates", return_value=("pass", "")):
            with patch.object(lq, "_ff_merge", return_value=None):
                with patch.object(lq, "_emit_event"):
                    lq.land(chunk, holding="my-holding")

    assert any(slug == "r-chunk" for slug, _ in rebase_calls)
    assert any(h == "my-holding" for _, h in rebase_calls)


def test_land_queue_emits_canonical_verdict_jsonl_shape():
    lq = load_module("landing")
    chunk = make_chunk("shape-chunk")

    with patch.object(lq, "_rebase_chunk", return_value=("sha1", None)):
        with patch.object(lq, "_run_gates", return_value=("pass", "")):
            with patch.object(lq, "_ff_merge", return_value=None):
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
    lq = load_module("landing")
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


def test_ff_merge_advances_holding_ref(tmp_path) -> None:
    """After _ff_merge, the holding branch ref advances to feature tip."""
    main_repo, chunk, lq, feature_sha = _setup_ff_repo(tmp_path)

    result = lq._ff_merge(chunk, "holding")

    assert result is None, "_ff_merge should return None on clean FF"

    holding_sha = _subprocess.run(
        ["git", "rev-parse", "refs/heads/holding"],
        cwd=main_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert holding_sha == feature_sha, f"holding ref {holding_sha!r} != feature_sha {feature_sha!r}"


def test_ff_merge_succeeds_with_dirty_main_worktree(tmp_path) -> None:
    """_ff_merge must succeed and advance the ref even when main worktree has dirty files.

    The fix uses git update-ref (checked-out branch) or git fetch (other branch)
    instead of merge --ff-only, so a dirty working tree cannot block the land.
    """
    main_repo, chunk, lq, feature_sha = _setup_ff_repo(tmp_path)

    # Dirty the main worktree (simulates an orphaned process leftover)
    (main_repo / "README").write_text("dirty\n")

    result = lq._ff_merge(chunk, "holding")

    assert result is None, "_ff_merge must succeed despite dirty main worktree"

    holding_sha = _subprocess.run(
        ["git", "rev-parse", "refs/heads/holding"],
        cwd=main_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert holding_sha == feature_sha, "holding ref must advance to feature_sha"

    # The dirty file must still be dirty (ff_merge must not touch the working tree)
    assert (main_repo / "README").read_text() == "dirty\n", "dirty state must be preserved"


# ── Slice 2: ff_merge reason distinction ─────────────────────────────────────


def _setup_divergent_repo(tmp_path):
    """Fixture: holding has diverged from feature (non-ancestor).

    History:
      A (holding init)
      ├── B (holding advances — diverges)
      └── C (feature commit)
    holding tip (B) is NOT an ancestor of feature HEAD (C).
    """
    lq = load_module("landing")
    main_repo = tmp_path / "main"
    main_repo.mkdir()

    _git(["init", "-b", "holding", str(main_repo)], cwd=tmp_path)
    for k, v in (("user.email", "t@t"), ("user.name", "T"), ("commit.gpgsign", "false")):
        _git(["config", k, v], cwd=main_repo)

    # Commit A on holding
    (main_repo / "README").write_text("init\n")
    _git(["add", "."], cwd=main_repo)
    _git(["commit", "-m", "A"], cwd=main_repo)

    # Branch feature at A, add commit C
    _git(["checkout", "-b", "feature"], cwd=main_repo)
    (main_repo / "feature.txt").write_text("feature\n")
    _git(["add", "."], cwd=main_repo)
    _git(["commit", "-m", "C"], cwd=main_repo)

    # Advance holding to B (diverge)
    _git(["checkout", "holding"], cwd=main_repo)
    (main_repo / "other.txt").write_text("other\n")
    _git(["add", "."], cwd=main_repo)
    _git(["commit", "-m", "B"], cwd=main_repo)

    chunk_wt = tmp_path / "chunk"
    _git(["worktree", "add", str(chunk_wt), "feature"], cwd=main_repo)

    chunk = lq.Chunk(slug="divergent-chunk", worktree=chunk_wt)
    return main_repo, chunk, lq


def test_ff_merge_non_ancestor_returns_not_ff(tmp_path) -> None:
    """Non-ancestor SHA must return 'not_ff', not a generic error."""
    _main_repo, chunk, lq = _setup_divergent_repo(tmp_path)
    result = lq._ff_merge(chunk, "holding")
    assert result == "not_ff", f"expected 'not_ff', got {result!r}"


def test_ff_merge_non_git_dir_returns_git_error(tmp_path) -> None:
    """Non-git worktree dir must return 'git_error', not 'not_ff'."""
    lq = load_module("landing")
    # tmp_path has no .git — rev-parse HEAD will fail
    chunk = lq.Chunk(slug="err-chunk", worktree=tmp_path)
    result = lq._ff_merge(chunk, "holding")
    assert result == "git_error", f"expected 'git_error', got {result!r}"
    assert result != "not_ff"


def test_land_ejects_with_not_ff_reason_on_non_ancestor(tmp_path) -> None:
    """land() must emit NOT_FF reason when merge is genuinely not fast-forward."""
    lq = load_module("landing")
    _main_repo, chunk, _lq = _setup_divergent_repo(tmp_path)

    with patch.object(lq, "_rebase_chunk", return_value=("sha1", None)):
        with patch.object(lq, "_run_gates", return_value=("pass", "")):
            with patch.object(lq, "_emit_event") as mock_emit:
                result = lq.land(chunk, holding="holding")

    assert result["status"] == "eject"
    assert result["reason"] == "not_ff"
    emitted_reasons = [c.args[1].get("reason") for c in mock_emit.call_args_list if "reason" in c.args[1]]
    assert any(r == "not_ff" for r in emitted_reasons)


def test_land_ejects_with_git_error_reason_on_git_failure(tmp_path) -> None:
    """land() must emit GIT_ERROR reason when git/setup fails, not NOT_FF."""
    lq = load_module("landing")
    chunk = lq.Chunk(slug="err-chunk", worktree=tmp_path)

    with patch.object(lq, "_rebase_chunk", return_value=("sha1", None)):
        with patch.object(lq, "_run_gates", return_value=("pass", "")):
            with patch.object(lq, "_emit_event") as mock_emit:
                result = lq.land(chunk, holding="holding")

    assert result["status"] == "eject"
    assert result["reason"] != "not_ff", "git-error must not be reported as not-ff"
    emitted_reasons = [c.args[1].get("reason") for c in mock_emit.call_args_list if "reason" in c.args[1]]
    assert not any(r == "not_ff" for r in emitted_reasons)


# ── drain cascade: downstream already gone from pending is skipped ───────────


def test_drain_cascade_skips_downstream_not_in_pending():
    """A cascaded slug no longer in `pending` is skipped (no duplicate eject verdict)."""
    lq = load_module("landing")
    a, b = make_chunk("a"), make_chunk("b")

    def fake_land(chunk, *, holding):
        return {"slug": chunk.slug, "status": "eject", "reason": "gate_failed"}

    def fake_list_ready_slices(pending):
        return [pending[0]] if pending else []

    # Cascade names "b" (in pending) and a phantom slug that was never pending.
    def fake_on_ejected(slug):
        return ["b", "phantom-slug"]

    with (
        patch.object(lq, "land", side_effect=fake_land),
        patch.object(lq, "_teardown_container", lambda _s: None),
        patch.object(lq, "_emit_event", lambda *a, **k: None),
    ):
        results = lq.drain(
            [a, b],
            holding="main",
            on_ejected=fake_on_ejected,
            list_ready_slices=fake_list_ready_slices,
        )

    slugs = [r.get("slug") for r in results]
    assert "a" in slugs and "b" in slugs
    assert "phantom-slug" not in slugs, "downstream never in pending must not yield a verdict"
