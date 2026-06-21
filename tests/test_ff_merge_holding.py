"""LQ2: ff_merge targets the explicit holding branch, not whatever is checked out."""

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


def _setup_repo(tmp_path: Path) -> tuple[Path, Path, str, str]:
    """Three-branch fixture: holding at init, feature 1 commit ahead, main on some-other-branch.

    Returns (main_repo, chunk_wt, holding_tip_sha, feature_sha).
    """
    main_repo = tmp_path / "main"
    main_repo.mkdir()
    _cmd(["init", "-b", "holding", str(main_repo)], tmp_path)
    for k, v in (("user.email", "t@t"), ("user.name", "T"), ("commit.gpgsign", "false")):
        _cmd(["config", k, v], main_repo)

    (main_repo / "README").write_text("init\n")
    _cmd(["add", "."], main_repo)
    _cmd(["commit", "-m", "init"], main_repo)
    holding_tip = _sha(main_repo)

    _cmd(["checkout", "-b", "feature"], main_repo)
    (main_repo / "README").write_text("feature\n")
    _cmd(["add", "."], main_repo)
    _cmd(["commit", "-m", "feature"], main_repo)
    feature_sha = _sha(main_repo)

    _cmd(["checkout", "holding"], main_repo)
    _cmd(["checkout", "-b", "some-other-branch"], main_repo)

    chunk_wt = tmp_path / "chunk"
    _cmd(["worktree", "add", str(chunk_wt), "feature"], main_repo)

    return main_repo, chunk_wt, holding_tip, feature_sha


def test_ff_merge_advances_holding_when_main_on_other_branch(tmp_path: Path) -> None:
    """When main worktree is on a branch other than holding, ff_merge advances holding."""
    main_repo, chunk_wt, holding_tip, feature_sha = _setup_repo(tmp_path)

    result = git_lib.ff_merge(chunk_wt, "holding")

    assert result is True, "ff_merge must return True on clean FF"

    # holding ref must advance to feature_sha
    after_holding = _branch_sha(main_repo, "holding")
    assert after_holding == feature_sha, f"holding must advance to {feature_sha!r}, got {after_holding!r}"

    # some-other-branch must NOT advance (was at holding_tip)
    after_other = _branch_sha(main_repo, "some-other-branch")
    assert after_other == holding_tip, f"some-other-branch must stay at {holding_tip!r}, got {after_other!r}"


def test_ff_merge_returns_false_when_not_ff(tmp_path: Path) -> None:
    """ff_merge returns False when chunk is not strictly ahead of holding (diverged)."""
    main_repo = tmp_path / "main"
    main_repo.mkdir()
    _cmd(["init", "-b", "holding", str(main_repo)], tmp_path)
    for k, v in (("user.email", "t@t"), ("user.name", "T"), ("commit.gpgsign", "false")):
        _cmd(["config", k, v], main_repo)

    (main_repo / "README").write_text("init\n")
    _cmd(["add", "."], main_repo)
    _cmd(["commit", "-m", "init"], main_repo)
    init_sha = _sha(main_repo)

    # Diverge holding
    (main_repo / "other").write_text("holding-only\n")
    _cmd(["add", "."], main_repo)
    _cmd(["commit", "-m", "holding-diverge"], main_repo)
    holding_tip = _sha(main_repo)

    # Feature branches from init commit (before the diverge)
    _cmd(["checkout", "-b", "feature", init_sha], main_repo)
    (main_repo / "README").write_text("feature\n")
    _cmd(["add", "."], main_repo)
    _cmd(["commit", "-m", "feature"], main_repo)

    _cmd(["checkout", "holding"], main_repo)
    chunk_wt = tmp_path / "chunk"
    _cmd(["worktree", "add", str(chunk_wt), "feature"], main_repo)

    result = git_lib.ff_merge(chunk_wt, "holding")

    assert result is False, "ff_merge must return False when not fast-forward"

    # holding ref must NOT advance
    after_sha = _branch_sha(main_repo, "holding")
    assert after_sha == holding_tip, f"holding must not change, expected {holding_tip!r}, got {after_sha!r}"
