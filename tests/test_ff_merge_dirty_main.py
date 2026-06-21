"""LQ-BUG2: ff_merge must succeed even when the main worktree has dirty files.

When a feature branch adds a new file and an orphaned process wrote the same
file to the main worktree (untracked), ``git merge --ff-only`` refuses:
"Untracked working tree file 'X' would be overwritten by merge."

The fix replaces ``merge --ff-only`` with ``git fetch . sha:refs/heads/<holding>``
which advances the ref without touching the working tree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import lib.git as git_lib


def _cmd(args: list[str], cwd: Path | None = None) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _sha(cwd: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def _branch_sha(cwd: Path, branch: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", f"refs/heads/{branch}"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _setup_conflicting_untracked_fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    """Feature branch adds new-feature.txt; main worktree has it as untracked.

    This reproduces the exact failure: ``git merge --ff-only`` refuses because
    the untracked file would be overwritten by the merge.

    Returns (main_repo, chunk_worktree, expected_feature_sha).
    """
    main_repo = tmp_path / "main"
    main_repo.mkdir()
    _cmd(["init", "-b", "holding", str(main_repo)], tmp_path)
    for k, v in (("user.email", "t@t"), ("user.name", "T"), ("commit.gpgsign", "false")):
        _cmd(["config", k, v], main_repo)

    (main_repo / "README").write_text("init\n")
    _cmd(["add", "."], main_repo)
    _cmd(["commit", "-m", "init"], main_repo)

    # Feature branch commits a NEW file
    _cmd(["checkout", "-b", "feature"], main_repo)
    (main_repo / "new-feature.txt").write_text("added by plan\n")
    _cmd(["add", "."], main_repo)
    _cmd(["commit", "-m", "add new-feature.txt"], main_repo)
    feature_sha = _sha(main_repo)

    _cmd(["checkout", "holding"], main_repo)

    # Orphaned process wrote the SAME file to main worktree (untracked)
    (main_repo / "new-feature.txt").write_text("added by orphaned process\n")

    chunk_wt = tmp_path / "chunk"
    _cmd(["worktree", "add", str(chunk_wt), "feature"], main_repo)

    return main_repo, chunk_wt, feature_sha


def test_ff_merge_succeeds_with_untracked_conflict_in_main(tmp_path: Path) -> None:
    """ff_merge must return True and advance holding even when main has a conflicting untracked file.

    RED: fails before fix because ``merge --ff-only`` refuses:
    "Untracked working tree file 'new-feature.txt' would be overwritten by merge."
    GREEN: passes after fix uses ``git fetch . sha:refs/heads/<holding>`` which
    only advances the ref without touching the working tree.
    """
    main_repo, chunk_wt, feature_sha = _setup_conflicting_untracked_fixture(tmp_path)

    result = git_lib.ff_merge(chunk_wt, "holding")

    assert result is None, "ff_merge must return None on a clean FF despite dirty main"

    after_holding = _branch_sha(main_repo, "holding")
    assert after_holding == feature_sha, f"holding must advance to {feature_sha!r}, got {after_holding!r}"


def test_ff_merge_does_not_modify_working_tree(tmp_path: Path) -> None:
    """ff_merge via fetch must not overwrite the untracked file in main."""
    main_repo, chunk_wt, _feature_sha = _setup_conflicting_untracked_fixture(tmp_path)

    git_lib.ff_merge(chunk_wt, "holding")

    # The untracked file must still exist with the original content
    content = (main_repo / "new-feature.txt").read_text()
    assert content == "added by orphaned process\n", (
        f"ff_merge via fetch must not touch main worktree files, got: {content!r}"
    )


def test_ff_merge_returns_false_for_non_ff(tmp_path: Path) -> None:
    """ff_merge returns False when branches have diverged (not fast-forward)."""
    main_repo = tmp_path / "main"
    main_repo.mkdir()
    _cmd(["init", "-b", "holding", str(main_repo)], tmp_path)
    for k, v in (("user.email", "t@t"), ("user.name", "T"), ("commit.gpgsign", "false")):
        _cmd(["config", k, v], main_repo)

    (main_repo / "README").write_text("init\n")
    _cmd(["add", "."], main_repo)
    _cmd(["commit", "-m", "init"], main_repo)
    init_sha = _sha(main_repo)

    # Diverge: holding advances
    (main_repo / "other").write_text("holding-only\n")
    _cmd(["add", "."], main_repo)
    _cmd(["commit", "-m", "holding-diverge"], main_repo)
    holding_tip = _sha(main_repo)

    # Feature branches from init (before diverge)
    _cmd(["checkout", "-b", "feature", init_sha], main_repo)
    (main_repo / "feature.txt").write_text("feature\n")
    _cmd(["add", "."], main_repo)
    _cmd(["commit", "-m", "feature"], main_repo)

    _cmd(["checkout", "holding"], main_repo)
    chunk_wt = tmp_path / "chunk"
    _cmd(["worktree", "add", str(chunk_wt), "feature"], main_repo)

    result = git_lib.ff_merge(chunk_wt, "holding")

    assert result == "not-ff", "ff_merge must return 'not-ff' when not fast-forward"
    after_sha = _branch_sha(main_repo, "holding")
    assert after_sha == holding_tip, f"holding must not change: {holding_tip!r} vs {after_sha!r}"
