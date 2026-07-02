"""E2E: the worktree lifecycle over REAL git worktrees on tmp_path.

Drives ``.agents/lib/worktrees.py`` end to end against real ``git worktree add``
trees, real dirty/clean status (delegating through ``lib.git`` and its ``git
status`` subprocess), real ``os.utime`` aging, and real removal. No mocking of
the module under test — the only fabrication is time (``os.utime``) so the
cutoff logic is exercised deterministically.

Imports go through the package (``from lib import worktrees``) rather than
``load_script`` because the module uses package imports (``from lib import git``);
the repo's root ``conftest.py`` puts ``.agents`` on ``sys.path``.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from tests.conftest import init_git_repo

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]


def _worktrees_mod():
    from lib import worktrees

    return worktrees


def _add_worktree(repo: Path, wt_path: Path, branch: str) -> None:
    """Real ``git worktree add`` creating a linked worktree with its own branch."""
    subprocess.run(
        ["git", "worktree", "add", str(wt_path), "-b", branch],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _age(path: Path, *, seconds_ago: float) -> None:
    """Backdate a dir's mtime so it reads as stale relative to a small cutoff."""
    t = time.time() - seconds_ago
    os.utime(path, (t, t))


# ── worktrees_root ───────────────────────────────────────────────────────────


def test_worktrees_root_is_mentat_worktrees_under_repo(tmp_path: Path):
    worktrees = _worktrees_mod()
    repo = tmp_path / "repo"
    assert worktrees.worktrees_root(repo) == repo / ".mentat" / "worktrees"


# ── is_managed ───────────────────────────────────────────────────────────────


def test_is_managed_true_for_path_under_worktrees_root(tmp_path: Path):
    worktrees = _worktrees_mod()
    repo = tmp_path / "repo"
    root = worktrees.worktrees_root(repo)
    candidate = root / "foo"
    candidate.mkdir(parents=True)
    assert worktrees.is_managed(candidate, repo) is True


def test_is_managed_false_for_path_outside_worktrees_root(tmp_path: Path):
    worktrees = _worktrees_mod()
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert worktrees.is_managed(outside, repo) is False


# ── is_dirty ─────────────────────────────────────────────────────────────────


def test_is_dirty_false_on_clean_repo(tmp_path: Path):
    worktrees = _worktrees_mod()
    repo = tmp_path / "repo"
    init_git_repo(repo)
    assert worktrees.is_dirty(repo) is False


def test_is_dirty_true_on_uncommitted_change(tmp_path: Path):
    worktrees = _worktrees_mod()
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "README").write_text("changed\n")
    assert worktrees.is_dirty(repo) is True


# ── teardown ─────────────────────────────────────────────────────────────────


def test_teardown_removes_clean_worktree(tmp_path: Path):
    worktrees = _worktrees_mod()
    repo = tmp_path / "repo"
    init_git_repo(repo)
    wt = tmp_path / "wt-clean"
    _add_worktree(repo, wt, "clean-branch")
    assert worktrees.teardown(wt) is True
    assert not wt.exists()


def test_teardown_preserves_dirty_worktree(tmp_path: Path):
    worktrees = _worktrees_mod()
    repo = tmp_path / "repo"
    init_git_repo(repo)
    wt = tmp_path / "wt-dirty"
    _add_worktree(repo, wt, "dirty-branch")
    (wt / "scratch.txt").write_text("un-landed work\n")
    assert worktrees.teardown(wt) is False
    assert wt.exists()


# ── _remove fallback (non-worktree dir → git fails → rmtree) ─────────────────


def test_remove_falls_back_to_rmtree_for_plain_dir(tmp_path: Path):
    worktrees = _worktrees_mod()
    # A plain directory that is NOT a registered git worktree: `git worktree
    # remove` fails, so _remove must fall through to shutil.rmtree.
    plain = tmp_path / "plain-dir"
    plain.mkdir()
    (plain / "file.txt").write_text("x\n")
    assert worktrees._remove(plain) is True
    assert not plain.exists()


# ── prune_stale ──────────────────────────────────────────────────────────────


def test_prune_stale_removes_only_clean_old_inactive(tmp_path: Path):
    worktrees = _worktrees_mod()
    repo = tmp_path / "repo"
    init_git_repo(repo)
    wt_root = tmp_path / "wt-root"
    wt_root.mkdir()

    old_clean = wt_root / "old-clean"
    recent = wt_root / "recent"
    old_active = wt_root / "old-active"
    old_dirty = wt_root / "old-dirty"
    for name, path in (
        ("old-clean", old_clean),
        ("recent", recent),
        ("old-active", old_active),
        ("old-dirty", old_dirty),
    ):
        _add_worktree(repo, path, name)

    (old_dirty / "leftover.txt").write_text("un-landed\n")

    # Age three past the cutoff; keep one recent (untouched mtime = now).
    _age(old_clean, seconds_ago=10_000)
    _age(old_active, seconds_ago=10_000)
    _age(old_dirty, seconds_ago=10_000)

    removed = worktrees.prune_stale(
        wt_root,
        active_slugs={"old-active"},
        cutoff_seconds=5,
    )

    assert removed == 1, "only the clean, old, inactive worktree is removed"
    assert not old_clean.exists()
    assert recent.exists()
    assert old_active.exists()
    assert old_dirty.exists()


def test_prune_stale_returns_zero_for_missing_root(tmp_path: Path):
    worktrees = _worktrees_mod()
    missing = tmp_path / "no-such-root"
    assert worktrees.prune_stale(missing, cutoff_seconds=5) == 0


# ── dirty_stale ──────────────────────────────────────────────────────────────


def test_dirty_stale_names_only_stale_dirty_worktrees(tmp_path: Path):
    worktrees = _worktrees_mod()
    repo = tmp_path / "repo"
    init_git_repo(repo)
    wt_root = tmp_path / "wt-root"
    wt_root.mkdir()

    clean_old = wt_root / "clean-old"
    dirty_old = wt_root / "dirty-old"
    _add_worktree(repo, clean_old, "clean-old")
    _add_worktree(repo, dirty_old, "dirty-old")
    (dirty_old / "leftover.txt").write_text("un-landed\n")

    _age(clean_old, seconds_ago=10_000)
    _age(dirty_old, seconds_ago=10_000)

    names = worktrees.dirty_stale(wt_root, cutoff_seconds=5)

    assert "dirty-old" in names
    assert "clean-old" not in names
