"""Unit tests for the lib/git.py seam: repo_root + worktree_list parsing.

Covers the porcelain-parsing edge shapes (leading blank line, no trailing
blank, prunable note) and repo_root's not-a-repo path.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import lib.git as git_lib
import pytest

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
    stdout = "worktree /a\nHEAD abc123\ndetached\nprunable gitdir file points to non-existent location\n"
    monkeypatch.setattr(git_lib, "_run", lambda *a, **k: _cp(0, stdout))

    entries = git_lib.worktree_list()

    assert entries == [
        {
            "worktree": "/a",
            "HEAD": "abc123",
            "prunable": "gitdir file points to non-existent location",
        }
    ]


# ── worktree_for_chunk ────────────────────────────────────────────────────────


def test_worktree_for_chunk_returns_matching_branch(monkeypatch) -> None:
    stdout = "worktree /a\nbranch refs/heads/other\n\nworktree /b\nbranch refs/heads/mentat/cid1/plan-a\n"
    monkeypatch.setattr(git_lib, "_run", lambda *a, **k: _cp(0, stdout))
    monkeypatch.setattr(git_lib, "repo_root", lambda cwd=None: Path("/repo"))

    assert git_lib.worktree_for_chunk("cid1", "plan-a") == Path("/b")


def test_worktree_for_chunk_raises_on_miss(monkeypatch) -> None:
    monkeypatch.setattr(git_lib, "_run", lambda *a, **k: _cp(0, "worktree /a\nbranch refs/heads/x\n"))
    monkeypatch.setattr(git_lib, "repo_root", lambda cwd=None: Path("/repo"))

    with pytest.raises(git_lib.GitError):
        git_lib.worktree_for_chunk("missing", "slug")


# ── rebase_ff_only ────────────────────────────────────────────────────────────


def test_rebase_ff_only_rejects_empty_sha_after_success(monkeypatch, tmp_path: Path) -> None:
    def fake_run(cmd, *, cwd=None):
        if cmd[:2] == ["rebase", "main"]:
            return _cp(0, "")
        if cmd == ["rev-parse", "HEAD"]:
            return _cp(0, "   \n")
        return _cp(0, "")

    monkeypatch.setattr(git_lib, "_run", fake_run)
    sha, err = git_lib.rebase_ff_only(tmp_path, "main")
    assert sha is None
    assert err == "rev-parse HEAD returned empty tip after rebase"


def test_rebase_ff_only_rejects_rev_parse_failure(monkeypatch, tmp_path: Path) -> None:
    def fake_run(cmd, *, cwd=None):
        if cmd[:2] == ["rebase", "main"]:
            return _cp(0, "")
        if cmd == ["rev-parse", "HEAD"]:
            r = _cp(1, "")
            r.stderr = "fatal: ambiguous argument 'HEAD'"
            return r
        return _cp(0, "")

    monkeypatch.setattr(git_lib, "_run", fake_run)
    sha, err = git_lib.rebase_ff_only(tmp_path, "main")
    assert sha is None
    assert "ambiguous argument" in (err or "")


# ── commit identity ───────────────────────────────────────────────────────────


def test_host_commit_identity_reads_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_git_repo(repo)
    ident = git_lib.host_commit_identity(cwd=repo)
    assert ident == {"user.name": "T", "user.email": "t@t"}


def test_require_commit_identity_raises_when_unset(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    monkeypatch.setattr(git_lib, "host_commit_identity", lambda **kw: {})
    with pytest.raises(git_lib.GitError, match="user.name and user.email"):
        git_lib.require_commit_identity(cwd=repo)

