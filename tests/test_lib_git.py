"""Unit tests for the lib/git.py seam: repo_root + worktree_list parsing.

Covers the porcelain-parsing edge shapes (leading blank line, no trailing
blank, prunable note) and repo_root's not-a-repo path.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import lib.git as git_lib

from tests.conftest import init_git_repo


def _cp(returncode: int = 0, stdout: str = "") -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    r: subprocess.CompletedProcess = subprocess.CompletedProcess.__new__(subprocess.CompletedProcess)
    r.returncode, r.stdout, r.stderr, r.args = returncode, stdout, "", []
    return r


# ── repo_root ─────────────────────────────────────────────────────────────────


def test_repo_root_returns_toplevel_inside_repo(tmp_path: Path) -> None:
    """Inside a real repo, repo_root resolves the working-tree top (lines 20-23)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    assert git_lib.repo_root(cwd=repo) == repo.resolve()


def test_repo_root_none_outside_repo(tmp_path: Path) -> None:
    """Outside any repo, rev-parse fails (rc != 0) → None (line 21-22)."""
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    assert git_lib.repo_root(cwd=outside) is None


# ── worktree_list ─────────────────────────────────────────────────────────────


def test_worktree_list_empty_on_error(monkeypatch) -> None:
    """A non-zero rev returncode yields an empty list."""
    monkeypatch.setattr(git_lib, "_run", lambda *a, **k: _cp(1, ""))
    assert git_lib.worktree_list() == []


def test_worktree_list_flushes_trailing_entry(monkeypatch) -> None:
    """Porcelain with no trailing blank line still flushes the last entry (line 52)."""
    stdout = "worktree /a\nbranch refs/heads/main\nHEAD abc123"
    monkeypatch.setattr(git_lib, "_run", lambda *a, **k: _cp(0, stdout))

    entries = git_lib.worktree_list()

    assert entries == [{"worktree": "/a", "branch": "main", "HEAD": "abc123"}]


def test_worktree_list_skips_leading_and_double_blanks(monkeypatch) -> None:
    """Blank lines while the current entry is empty are skipped (branch 39->42)."""
    # Leading blank + a double blank between entries: both hit the empty-cur skip.
    stdout = "\nworktree /a\nbranch refs/heads/main\n\n\nworktree /b\nbranch refs/heads/feat\n"
    monkeypatch.setattr(git_lib, "_run", lambda *a, **k: _cp(0, stdout))

    entries = git_lib.worktree_list()

    assert entries == [
        {"worktree": "/a", "branch": "main"},
        {"worktree": "/b", "branch": "feat"},
    ]


def test_worktree_list_captures_prunable(monkeypatch) -> None:
    """A prunable admin note is recorded and the loop continues (branch 49->37)."""
    # The prunable line is followed by more lines so the loop iterates past it
    # (branch 49->37), not just falls off the end.
    # A 'detached' attribute matches no branch and is followed by more lines, so
    # the final elif (prunable) is evaluated False and the loop continues (49->37).
    stdout = (
        "worktree /a\n"
        "HEAD abc123\n"
        "detached\n"
        "prunable gitdir file points to non-existent location\n"
    )
    monkeypatch.setattr(git_lib, "_run", lambda *a, **k: _cp(0, stdout))

    entries = git_lib.worktree_list()

    assert entries == [
        {
            "worktree": "/a",
            "HEAD": "abc123",
            "prunable": "gitdir file points to non-existent location",
        }
    ]


# ── worktree_for_slug ─────────────────────────────────────────────────────────


def test_worktree_for_slug_returns_matching_branch(monkeypatch) -> None:
    """A branch matching the slug returns that worktree's path (line 60)."""
    stdout = "worktree /a\nbranch refs/heads/other\n\nworktree /b\nbranch refs/heads/target\n"
    monkeypatch.setattr(git_lib, "_run", lambda *a, **k: _cp(0, stdout))

    assert git_lib.worktree_for_slug("target") == Path("/b")


def test_worktree_for_slug_falls_back_to_cwd(monkeypatch) -> None:
    """No branch matches the slug → falls back to cwd."""
    monkeypatch.setattr(git_lib, "_run", lambda *a, **k: _cp(0, "worktree /a\nbranch refs/heads/x\n"))
    assert git_lib.worktree_for_slug("nope") == Path.cwd()
