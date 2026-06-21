"""LQ3: rebase_ff_only aborts on conflict — worktree left clean (no .git/rebase-merge)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import lib.git as git_lib


def _cmd(args: list[str], cwd: Path | None = None) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _gitdir(wt: Path) -> Path:
    """Resolve the actual .git dir for a worktree (follows the .git file for linked worktrees)."""
    git = wt / ".git"
    if git.is_file():
        content = git.read_text().strip()
        if content.startswith("gitdir:"):
            return Path(content[len("gitdir:") :].strip())
    return git


def _setup_conflict_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Two-branch fixture with a conflicting change on the same file.

    Returns (main_repo, feature_worktree).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _cmd(["init", "-b", "main", str(repo)], tmp_path)
    for k, v in (("user.email", "t@t"), ("user.name", "T"), ("commit.gpgsign", "false")):
        _cmd(["config", k, v], repo)

    (repo / "file.txt").write_text("base\n")
    _cmd(["add", "."], repo)
    _cmd(["commit", "-m", "base"], repo)

    _cmd(["checkout", "-b", "feature"], repo)
    (repo / "file.txt").write_text("feature change\n")
    _cmd(["add", "."], repo)
    _cmd(["commit", "-m", "feature commit"], repo)

    _cmd(["checkout", "main"], repo)
    (repo / "file.txt").write_text("main change\n")
    _cmd(["add", "."], repo)
    _cmd(["commit", "-m", "main commit"], repo)

    feature_wt = tmp_path / "feature-wt"
    _cmd(["worktree", "add", str(feature_wt), "feature"], repo)

    return repo, feature_wt


def test_rebase_conflict_leaves_worktree_clean(tmp_path: Path) -> None:
    """Conflicting rebase → abort is called → no rebase-merge dir left in the gitdir."""
    _repo, feature_wt = _setup_conflict_repo(tmp_path)

    tip, err = git_lib.rebase_ff_only(feature_wt, "main")

    assert err is not None, "expected rebase to fail due to conflict"
    assert tip is None, "tip must be None on failure"

    gitdir = _gitdir(feature_wt)
    assert not (gitdir / "rebase-merge").exists(), (
        f".git/rebase-merge must not exist after aborted rebase; gitdir={gitdir}"
    )
    # rebase-apply is the old-style rebase state dir; check it too
    assert not (gitdir / "rebase-apply").exists(), (
        f".git/rebase-apply must not exist after aborted rebase; gitdir={gitdir}"
    )


def test_rebase_success_returns_tip(tmp_path: Path) -> None:
    """Clean rebase returns (sha, None) and no lingering state dirs."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _cmd(["init", "-b", "main", str(repo)], tmp_path)
    for k, v in (("user.email", "t@t"), ("user.name", "T"), ("commit.gpgsign", "false")):
        _cmd(["config", k, v], repo)

    (repo / "README").write_text("base\n")
    _cmd(["add", "."], repo)
    _cmd(["commit", "-m", "base"], repo)

    _cmd(["checkout", "-b", "feature"], repo)
    (repo / "feature.txt").write_text("new\n")
    _cmd(["add", "."], repo)
    _cmd(["commit", "-m", "add feature"], repo)

    feature_wt = tmp_path / "feature-wt"
    _cmd(["checkout", "main"], repo)
    _cmd(["worktree", "add", str(feature_wt), "feature"], repo)

    tip, err = git_lib.rebase_ff_only(feature_wt, "main")

    assert err is None, f"expected clean rebase, got error: {err}"
    assert tip is not None and len(tip) == 40
