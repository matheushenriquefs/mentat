"""_ff_merge must advance both the branch pointer and main worktree's working tree."""

from __future__ import annotations

import subprocess
from pathlib import Path

import land_queue


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _setup(tmp_path: Path):
    """Two-worktree fixture: main on 'holding', chunk on 'feature' 1 commit ahead.

    Feature commit modifies README so the dirty-tree test can use README as the
    conflict surface.

    Returns (main_repo, chunk, feature_sha).
    """
    main_repo = tmp_path / "main"
    main_repo.mkdir()

    _git(["init", "-b", "holding", str(main_repo)], cwd=tmp_path)
    for k, v in (("user.email", "t@t"), ("user.name", "T"), ("commit.gpgsign", "false")):
        _git(["config", k, v], cwd=main_repo)

    (main_repo / "README").write_text("init\n")
    _git(["add", "."], cwd=main_repo)
    _git(["commit", "-m", "init"], cwd=main_repo)

    # Feature branch: modify README so the dirty-tree test has a conflict surface
    _git(["checkout", "-b", "feature"], cwd=main_repo)
    (main_repo / "README").write_text("feature\n")
    _git(["add", "."], cwd=main_repo)
    _git(["commit", "-m", "feature commit"], cwd=main_repo)

    feature_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=main_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Return main worktree to 'holding'
    _git(["checkout", "holding"], cwd=main_repo)

    # Add chunk worktree on 'feature'
    chunk_wt = tmp_path / "chunk"
    _git(["worktree", "add", str(chunk_wt), "feature"], cwd=main_repo)

    chunk = land_queue.Chunk(slug="test-chunk", worktree=chunk_wt)
    return main_repo, chunk, feature_sha


def test_ff_merge_updates_main_worktree(tmp_path: Path) -> None:
    """After _ff_merge, main worktree HEAD and on-disk files reflect feature tip."""
    main_repo, chunk, feature_sha = _setup(tmp_path)

    result = land_queue._ff_merge(chunk, "holding")

    assert result is True, "_ff_merge should return True on clean FF"

    resolved = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=main_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert resolved == feature_sha, f"main HEAD {resolved!r} != feature_sha {feature_sha!r}"

    assert (main_repo / "README").read_text() == "feature\n", "README not updated in main worktree working tree"


def test_ff_merge_refuses_dirty_main_worktree(tmp_path: Path) -> None:
    """Dirty main worktree: _ff_merge returns False, ref stays put, dirt survives."""
    main_repo, chunk, _ = _setup(tmp_path)

    before_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=main_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Dirty README — same file the feature commit touches
    (main_repo / "README").write_text("dirty\n")

    result = land_queue._ff_merge(chunk, "holding")

    assert result is False, "_ff_merge must return False when main worktree is dirty"

    after_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=main_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert after_sha == before_sha, "ref must not advance when main worktree is dirty"

    assert (main_repo / "README").read_text() == "dirty\n", "dirty state must be preserved"
