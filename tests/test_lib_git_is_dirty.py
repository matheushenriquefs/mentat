"""Tests for lib/git.py is_dirty fail-safe behaviour."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_AGENTS = Path(__file__).resolve().parents[1] / ".agents"
if str(_AGENTS) not in sys.path:
    sys.path.insert(0, str(_AGENTS))

from lib import git as _git  # noqa: E402


def _git_cmd(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_is_dirty_no_git_link_returns_true(tmp_path: Path) -> None:
    """Dir with content but no .git must be treated as dirty (fail-safe).

    Partial 'git worktree remove' deletes the .git gitlink but leaves the
    working-tree files.  Reporting clean would cause teardown to discard
    un-landed work.
    """
    (tmp_path / "work.py").write_text("x = 1\n")
    # No .git file/dir — simulates partial worktree remove
    assert not (tmp_path / ".git").exists()
    assert _git.is_dirty(tmp_path) is True


def test_is_dirty_clean_repo_returns_false(tmp_path: Path) -> None:
    """Clean committed repo must still report clean."""
    _git_cmd(["init", "-b", "main", str(tmp_path)], tmp_path)
    for k, v in (("user.email", "t@t"), ("user.name", "T"), ("commit.gpgsign", "false")):
        _git_cmd(["config", k, v], tmp_path)
    (tmp_path / "README").write_text("hi\n")
    _git_cmd(["add", "."], tmp_path)
    _git_cmd(["commit", "-m", "init"], tmp_path)
    assert _git.is_dirty(tmp_path) is False


def test_is_dirty_uncommitted_change_returns_true(tmp_path: Path) -> None:
    """Uncommitted staged change must report dirty."""
    _git_cmd(["init", "-b", "main", str(tmp_path)], tmp_path)
    for k, v in (("user.email", "t@t"), ("user.name", "T"), ("commit.gpgsign", "false")):
        _git_cmd(["config", k, v], tmp_path)
    (tmp_path / "README").write_text("hi\n")
    _git_cmd(["add", "."], tmp_path)
    _git_cmd(["commit", "-m", "init"], tmp_path)
    (tmp_path / "README").write_text("changed\n")
    assert _git.is_dirty(tmp_path) is True
